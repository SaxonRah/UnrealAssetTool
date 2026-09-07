from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
TESTS = ROOT / "tests"
for path in (SCRIPTS, TESTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import test_native_index_schema1 as fixture
import uatool as launcher
import uatool_native_ast as native_ast
import uatool_native_index as native_index
import uatool_native_join as native_join
import uatool_native_stage as native_stage


class NativeStageSchema1Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reflected = self.root / "reflected"
        self.compiler = self.root / "compiler"
        self.joins = self.root / "joins"
        self.output = self.root / ".uatool"
        self.reflected.mkdir()
        self.compiler.mkdir()
        self.joins.mkdir()
        self.output.mkdir()

        fixture.make_reflected(self.reflected)
        fixture.make_ast(self.compiler)
        native_join.capture(
            self.reflected,
            self.compiler,
            self.joins,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def stage(self) -> dict:
        return native_stage.stage(
            self.output,
            self.reflected,
            self.compiler,
            self.joins,
        )

    def test_stage_preserves_authoritative_bytes_and_validates(self) -> None:
        manifest = self.stage()
        self.assertIsNone(native_stage.validation_error(self.output))
        reflected, compiler, joins = native_stage.roots(self.output)

        for source, staged, names in (
            (
                self.reflected,
                reflected,
                native_stage.REFLECTED_FILES,
            ),
            (
                self.compiler,
                compiler,
                native_stage.COMPILER_FILES,
            ),
            (
                self.joins,
                joins,
                native_stage.JOIN_FILES,
            ),
        ):
            for name in names:
                self.assertEqual(
                    (source / name).read_bytes(),
                    (staged / name).read_bytes(),
                )

        self.assertEqual(
            manifest["rulesets"]["compiler"],
            native_ast.RULESET,
        )
        self.assertEqual(
            manifest["rulesets"]["joins"],
            native_join.RULESET,
        )
        self.assertEqual(manifest["counts"]["function_joins"], 1)

    def test_tampered_staged_file_is_rejected(self) -> None:
        self.stage()
        _, compiler, _ = native_stage.roots(self.output)
        with (compiler / native_ast.SYMBOLS).open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write('{"tampered":true}\n')

        error = native_stage.validation_error(self.output)
        self.assertIsNotNone(error)
        self.assertIn("hash/size mismatch", error)

    def test_failed_restage_preserves_previous_valid_stage(self) -> None:
        self.stage()
        before = (
            native_stage.root(self.output)
            / native_stage.MANIFEST
        ).read_bytes()

        with mock.patch.object(
            native_stage,
            "_copy_group",
            side_effect=RuntimeError("synthetic copy failure"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "synthetic copy failure",
            ):
                self.stage()

        after = (
            native_stage.root(self.output)
            / native_stage.MANIFEST
        ).read_bytes()
        self.assertEqual(before, after)
        self.assertIsNone(native_stage.validation_error(self.output))

    def test_stale_compiler_ruleset_is_rejected_before_swap(self) -> None:
        manifest_path = self.compiler / native_ast.MANIFEST
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        manifest["ruleset"] = "obsolete"
        manifest_path.write_text(
            json.dumps(manifest) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        with self.assertRaisesRegex(
            RuntimeError,
            "native AST ruleset is stale or missing",
        ):
            self.stage()
        self.assertFalse(native_stage.root(self.output).exists())

    def test_stage_loads_native_tables_without_touching_standard_table(self) -> None:
        manifest = self.stage()
        db = self.output / "uat.db"
        conn = sqlite3.connect(db)
        try:
            native_index.create_schema(conn)
            conn.execute(
                "CREATE TABLE standard_sentinel(value TEXT PRIMARY KEY)"
            )
            conn.execute(
                "INSERT INTO standard_sentinel(value) VALUES('keep')"
            )
            counts = native_stage.load_database(conn, self.output)
            conn.commit()

            self.assertEqual(
                counts["native_compiler_symbols"],
                manifest["counts"]["compiler_symbols"],
            )
            self.assertEqual(
                conn.execute(
                    "SELECT value FROM standard_sentinel"
                ).fetchone()[0],
                "keep",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM native_function_joins"
                ).fetchone()[0],
                manifest["counts"]["function_joins"],
            )
        finally:
            conn.close()

    def test_normal_bundle_contains_complete_native_stage(self) -> None:
        self.stage()
        destination = self.root / "portable.zip"
        launcher.create_upload_bundle(
            self.output,
            destination,
        )

        with zipfile.ZipFile(destination, "r") as archive:
            names = set(archive.namelist())
        self.assertTrue(
            set(native_stage.BUNDLE_FILES).issubset(names)
        )

    def test_normal_bundle_rejects_invalid_native_stage(self) -> None:
        self.stage()
        _, compiler, _ = native_stage.roots(self.output)
        (compiler / native_ast.CALLS).unlink()

        with self.assertRaisesRegex(
            RuntimeError,
            "native semantic stage incomplete",
        ):
            launcher.create_upload_bundle(
                self.output,
                self.root / "bad.zip",
            )

    def test_projects_without_native_stage_remain_optional(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            native_index.create_schema(conn)
            self.assertEqual(
                native_stage.load_database(conn, self.output),
                {},
            )
        finally:
            conn.close()

        destination = self.root / "empty.zip"
        launcher.create_upload_bundle(self.output, destination)
        self.assertTrue(destination.is_file())

    def test_canonical_launcher_wires_stage_to_db_and_bundle(self) -> None:
        source = (SCRIPTS / "uatool.py").read_text(encoding="utf-8")
        self.assertIn('prog="uatool native-stage"', source)
        self.assertIn('sys.argv[1] == "native-stage"', source)
        self.assertIn("native_stage.load_database(conn, output)", source)
        self.assertIn("*native_stage.BUNDLE_FILES", source)
        self.assertIn(
            "core.create_upload_bundle = create_upload_bundle",
            source,
        )


if __name__ == "__main__":
    unittest.main()
