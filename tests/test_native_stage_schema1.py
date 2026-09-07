from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
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

    def install_current_reflection(self) -> None:
        for name in native_stage.REFLECTED_FILES:
            shutil.copyfile(
                self.reflected / name,
                self.output / name,
            )

    def run_composed_ensure(
        self,
    ) -> subprocess.CompletedProcess[str]:
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(SCRIPTS)!r}); "
            "from pathlib import Path; "
            "import uatool; "
            f"counts=uatool._ensure_staged_native_database("
            f"Path({str(self.output)!r})); "
            "print(counts)"
        )
        return subprocess.run(
            [sys.executable, "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def run_composed_bundle(
        self,
        destination: Path,
    ) -> subprocess.CompletedProcess[str]:
        code = (
            "import sys; "
            f"sys.path.insert(0, {str(SCRIPTS)!r}); "
            "from pathlib import Path; "
            "import uatool; "
            f"uatool.create_upload_bundle(Path({str(self.output)!r}), "
            f"Path({str(destination)!r}))"
        )
        return subprocess.run(
            [sys.executable, "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
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
        self.assertEqual(
            manifest["reflected_semantics"],
            native_stage._reflected_semantic_records(
                native_stage.roots(self.output)[0]
            ),
        )

    def test_tampered_staged_file_is_rejected(self) -> None:
        self.stage()
        self.install_current_reflection()
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
        self.install_current_reflection()
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

    def test_current_reflection_semantic_reordering_is_accepted(self) -> None:
        self.stage()
        self.install_current_reflection()

        current_types = self.output / "native_types.jsonl"
        lines = [
            line
            for line in current_types.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        current_types.write_text(
            "\n".join(reversed(lines)) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        self.assertIsNone(
            native_stage.validation_error(
                self.output,
                require_current_reflected=True,
            )
        )

    def test_current_reflection_real_semantic_change_is_rejected(self) -> None:
        self.stage()
        self.install_current_reflection()

        current_types = self.output / "native_types.jsonl"
        rows = [
            json.loads(line)
            for line in current_types.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        ]
        self.assertTrue(rows)
        rows[0]["cpp_name"] = (
            str(rows[0].get("cpp_name", "")) + "_Changed"
        )
        current_types.write_text(
            "".join(
                json.dumps(row, separators=(",", ":")) + "\n"
                for row in rows
            ),
            encoding="utf-8",
            newline="\n",
        )

        self.assertIsNone(
            native_stage.reflected_native.validation_error(self.output)
        )
        error = native_stage.validation_error(
            self.output,
            require_current_reflected=True,
        )
        self.assertIsNotNone(error)
        self.assertIn(
            "current reflected native semantics differ",
            error,
        )
        self.assertIn("native_types.jsonl", error)

    def test_current_reflection_is_required_for_normal_db_load(self) -> None:
        self.stage()
        conn = sqlite3.connect(":memory:")
        try:
            native_index.create_schema(conn)
            with self.assertRaisesRegex(
                RuntimeError,
                "current normal reflected native manifest is missing",
            ):
                native_stage.load_database(conn, self.output)
        finally:
            conn.close()

    def test_scan_postcondition_repairs_empty_native_cache(self) -> None:
        manifest = self.stage()
        self.install_current_reflection()
        db = self.output / "uat.db"
        conn = sqlite3.connect(db)
        try:
            native_index.create_schema(conn)
            conn.commit()
            self.assertFalse(native_index.has_native_index(conn))
        finally:
            conn.close()

        result = self.run_composed_ensure()
        self.assertEqual(result.returncode, 0, result.stderr)

        conn = sqlite3.connect(db)
        try:
            self.assertTrue(native_index.has_native_index(conn))
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM native_compiler_symbols"
                ).fetchone()[0],
                manifest["counts"]["compiler_symbols"],
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM native_function_joins"
                ).fetchone()[0],
                manifest["counts"]["function_joins"],
            )
        finally:
            conn.close()

    def test_scan_postcondition_is_idempotent_when_native_cache_exists(self) -> None:
        self.stage()
        self.install_current_reflection()
        db = self.output / "uat.db"
        conn = sqlite3.connect(db)
        try:
            native_index.create_schema(conn)
        finally:
            conn.close()

        first = self.run_composed_ensure()
        self.assertEqual(first.returncode, 0, first.stderr)
        second = self.run_composed_ensure()
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("{}", second.stdout)

    def test_normal_bundle_contains_complete_native_stage(self) -> None:
        self.stage()
        self.install_current_reflection()
        destination = self.root / "portable.zip"
        result = self.run_composed_bundle(destination)
        self.assertEqual(result.returncode, 0, result.stderr)

        with zipfile.ZipFile(destination, "r") as archive:
            names = set(archive.namelist())
        self.assertTrue(
            set(native_stage.BUNDLE_FILES).issubset(names)
        )

    def test_normal_bundle_rejects_invalid_native_stage(self) -> None:
        self.stage()
        self.install_current_reflection()
        _, compiler, _ = native_stage.roots(self.output)
        (compiler / native_ast.CALLS).unlink()

        result = self.run_composed_bundle(
            self.root / "bad.zip"
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "native semantic stage incomplete",
            result.stderr,
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
        result = self.run_composed_bundle(destination)
        self.assertEqual(result.returncode, 0, result.stderr)
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
        self.assertIn(
            "_ensure_staged_native_database(output)",
            source,
        )
        self.assertIn(
            "_ensure_staged_native_database(output, db)",
            source,
        )


if __name__ == "__main__":
    unittest.main()
