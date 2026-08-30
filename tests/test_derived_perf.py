from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_bundle_perf as bundle_perf
import uatool_derived_freshness as freshness
import uatool_project_neighborhood_compact as compact_schema
import uatool_project_neighborhoods as neighborhoods
import uatool_sqlite_perf as sqlite_perf
import uatool_validation_perf as validation_perf


class DerivedPerfTest(unittest.TestCase):
    def test_direct_compact_neighborhood_matches_expand_then_compact(self) -> None:
        nodes = [
            {
                "node_kind": "blueprint",
                "path": "/Game/A.A",
                "coverage": "first_class",
                "root": True,
            },
            {
                "node_kind": "niagara_system",
                "path": "/Game/B.B",
                "coverage": "first_class",
                "root": True,
            },
        ]
        edges = [
            {
                "edge_id": "pedge:1",
                "source_kind": "blueprint",
                "source": "/Game/A.A",
                "relation": "references_vfx_asset",
                "target_kind": "niagara_system",
                "target": "/Game/B.B",
                "source_coverage": "first_class",
                "target_coverage": "first_class",
                "edge_quality": "exact_reference",
                "evidence_count": 1,
                "evidence": [{"stream": "blueprint_relations.jsonl", "kind": "test"}],
            }
        ]
        kwargs = dict(
            quality_rank={"exact_reference": 3},
            coverage_rank={"first_class": 4},
            max_depth=3,
            max_edges=256,
            max_chars=131072,
        )
        expanded = neighborhoods.rebuild(nodes, edges, **kwargs)
        old_compact = compact_schema.compact(expanded)
        direct_compact = neighborhoods.rebuild(nodes, edges, compact=True, **kwargs)
        self.assertEqual(direct_compact, old_compact)

    def test_freshness_stamp_invalidates_on_raw_or_python_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "out"
            scripts = root / "scripts"
            output.mkdir()
            scripts.mkdir()

            raw = output / "assets.jsonl"
            derived = output / "project_nodes.jsonl"
            raw.write_text('{"asset":"A"}\n', encoding="utf-8")
            derived.write_text('{"node":"A"}\n', encoding="utf-8")
            (output / "manifest.json").write_text(
                json.dumps(
                    {
                        "derived_schema_version": 14,
                        "derived_counts": {"project_nodes": 1},
                    }
                ) + "\n",
                encoding="utf-8",
            )
            source = scripts / "uatool_example.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")

            freshness.mark_fresh(output, schema_version=14, script_dir=scripts)
            self.assertTrue(freshness.is_fresh(output, schema_version=14, script_dir=scripts))

            with raw.open("a", encoding="utf-8") as handle:
                handle.write('{"asset":"B"}\n')
            self.assertFalse(freshness.is_fresh(output, schema_version=14, script_dir=scripts))

            freshness.mark_fresh(output, schema_version=14, script_dir=scripts)
            self.assertTrue(freshness.is_fresh(output, schema_version=14, script_dir=scripts))

            source.write_text("VALUE = 2\n", encoding="utf-8")
            os.utime(source, None)
            self.assertFalse(freshness.is_fresh(output, schema_version=14, script_dir=scripts))

    def test_validator_cache_reuses_only_unchanged_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            target = output / "project_edges.jsonl"
            target.write_text('{"edge":1}\n', encoding="utf-8")
            calls = []
            module = types.SimpleNamespace()

            def validator(root, *args, **kwargs):
                calls.append(Path(root))
                return None

            module.validation_error = validator
            validation_perf._wrap(module, ("project_edges.jsonl",), "test")
            self.assertIsNone(module.validation_error(output))
            self.assertIsNone(module.validation_error(output))
            self.assertEqual(len(calls), 1)

            with target.open("a", encoding="utf-8") as handle:
                handle.write('{"edge":2}\n')
            self.assertIsNone(module.validation_error(output))
            self.assertEqual(len(calls), 2)

    def test_sqlite_bulk_defer_keeps_unique_constraint_live(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            conn.executescript(
                """
                CREATE TABLE t(id INTEGER PRIMARY KEY, value TEXT, unique_value TEXT);
                CREATE UNIQUE INDEX t_unique_idx ON t(unique_value);
                CREATE INDEX t_value_idx ON t(value);
                """
            )
            sqlite_perf._DEFERRED = {}
            sqlite_perf._defer_nonunique_indexes(conn)
            indexes = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
            self.assertIn("t_unique_idx", indexes)
            self.assertNotIn("t_value_idx", indexes)

            conn.execute("INSERT INTO t(value,unique_value) VALUES('a','u')")
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO t(value,unique_value) VALUES('b','u')")

            sqlite_perf._restore_indexes(conn)
            indexes = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
            self.assertIn("t_value_idx", indexes)
        finally:
            conn.close()

    def test_bundle_level_override_keeps_standard_zip_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "out"
            output.mkdir()
            payload = b'{"value":"' + (b"x" * 10000) + b'"}\n'
            (output / "sample.jsonl").write_bytes(payload)
            fake_core = types.SimpleNamespace(DEFAULT_BUNDLE_FILES=("sample.jsonl",))
            destination = root / "sample.zip"

            old = os.environ.get(bundle_perf.ENV_NAME)
            os.environ[bundle_perf.ENV_NAME] = "1"
            try:
                result = bundle_perf.create_upload_bundle(fake_core, output, destination)
            finally:
                if old is None:
                    os.environ.pop(bundle_perf.ENV_NAME, None)
                else:
                    os.environ[bundle_perf.ENV_NAME] = old

            self.assertEqual(result, destination.resolve())
            with zipfile.ZipFile(result, "r") as archive:
                self.assertEqual(archive.read("sample.jsonl"), payload)

    def test_bundle_level_rejects_invalid_value(self) -> None:
        old = os.environ.get(bundle_perf.ENV_NAME)
        os.environ[bundle_perf.ENV_NAME] = "10"
        try:
            with self.assertRaises(RuntimeError):
                bundle_perf.compression_level()
        finally:
            if old is None:
                os.environ.pop(bundle_perf.ENV_NAME, None)
            else:
                os.environ[bundle_perf.ENV_NAME] = old


if __name__ == "__main__":
    unittest.main()
