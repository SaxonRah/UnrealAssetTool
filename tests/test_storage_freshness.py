from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_animation_stitch as animation_stitch
import uatool_derived_freshness as freshness
import uatool_project_neighborhood_compact as compact
import uatool_vfx_stitch as vfx_stitch


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class StorageFreshnessRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name) / "out"
        self.scripts = Path(self.temp.name) / "scripts"
        self.output.mkdir()
        self.scripts.mkdir()
        (self.scripts / "uatool_fake.py").write_text("VALUE = 1\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_freshness_requires_same_schema_scripts_canonical_and_derived_files(self) -> None:
        write_jsonl(self.output / "raw.jsonl", [{"raw": 1}])
        write_jsonl(self.output / "derived.jsonl", [{"derived": 1}])
        (self.output / "manifest.json").write_text(json.dumps({
            "derived_schema_version": 14,
            "derived_counts": {"derived": 1},
        }) + "\n", encoding="utf-8")

        freshness.mark_fresh(self.output, schema_version=14, script_dir=self.scripts)
        self.assertTrue(freshness.is_fresh(self.output, schema_version=14, script_dir=self.scripts))
        self.assertFalse(freshness.is_fresh(self.output, schema_version=13, script_dir=self.scripts))

        write_jsonl(self.output / "raw.jsonl", [{"raw": 2}, {"raw": 3}])
        self.assertFalse(freshness.is_fresh(self.output, schema_version=14, script_dir=self.scripts))

        freshness.mark_fresh(self.output, schema_version=14, script_dir=self.scripts)
        (self.scripts / "uatool_fake.py").write_text("VALUE = 2\n", encoding="utf-8")
        self.assertFalse(freshness.is_fresh(self.output, schema_version=14, script_dir=self.scripts))

        (self.scripts / "uatool_fake.py").write_text("VALUE = 1\n", encoding="utf-8")
        freshness.mark_fresh(self.output, schema_version=14, script_dir=self.scripts)
        (self.output / "derived.jsonl").unlink()
        self.assertFalse(freshness.is_fresh(self.output, schema_version=14, script_dir=self.scripts))

    def test_specialist_derived_rows_survive_sqlite_load(self) -> None:
        animation_rows = [{
            "relation_id": "arel:test",
            "source_kind": "anim_montage",
            "source": "/Game/Anim/M.M",
            "relation": "plays_animation_segment",
            "target_kind": "anim_sequence",
            "target": "/Game/Anim/A.A",
            "target_coverage": "first_class",
            "evidence_count": 1,
            "evidence": [{"stream": "animation_segments.jsonl"}],
        }]
        vfx_rows = [{
            "relation_id": "vrel:test",
            "source_kind": "niagara_system",
            "source": "/Game/VFX/NS.NS",
            "relation": "uses_stateless_emitter",
            "target_kind": "niagara_stateless_emitter",
            "target": "/Game/VFX/NSE.NSE",
            "target_coverage": "first_class",
            "evidence_count": 1,
            "evidence": [{"stream": "niagara_system_emitters.jsonl"}],
        }]
        write_jsonl(self.output / "animation_relations.jsonl", animation_rows)
        write_jsonl(self.output / "animation_context.jsonl", [])
        write_jsonl(self.output / "animation_summaries.jsonl", [])
        write_jsonl(self.output / "vfx_relations.jsonl", vfx_rows)
        write_jsonl(self.output / "vfx_context.jsonl", [])
        write_jsonl(self.output / "vfx_summaries.jsonl", [])

        conn = sqlite3.connect(":memory:")
        try:
            animation_stitch.create_schema(conn)
            vfx_stitch.create_schema(conn)
            animation_stitch.load_database(conn, self.output, read_rows)
            vfx_stitch.load_database(conn, self.output, read_rows)
            self.assertEqual(conn.execute("SELECT count(*) FROM animation_relations").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM vfx_relations").fetchone()[0], 1)
            self.assertEqual(
                conn.execute("SELECT evidence_count FROM animation_relations").fetchone()[0],
                animation_rows[0]["evidence_count"],
            )
            self.assertEqual(
                conn.execute("SELECT evidence_count FROM vfx_relations").fetchone()[0],
                vfx_rows[0]["evidence_count"],
            )
        finally:
            conn.close()

    def test_compact_neighborhood_renders_authoritative_edge(self) -> None:
        edge = {
            "edge_id": "pedge:test",
            "source_kind": "input_mapping",
            "source": "/Game/Input/IMC.IMC::mapping[0]",
            "relation": "maps_input_action",
            "target_kind": "input_action",
            "target": "/Game/Input/IA.IA",
            "source_coverage": "first_class",
            "target_coverage": "first_class",
            "edge_quality": "exact_reference",
            "evidence_count": 1,
        }
        row = {
            "root_path": "/Game/Input/IMC.IMC",
            "root_kind": "input_mapping_context",
            "root_coverage": "first_class",
            "max_depth": 3,
            "edge_count": 1,
            "node_count": 2,
            "truncated": False,
            "hops": [{
                "depth": 1,
                "direction": "out",
                "edge_id": edge["edge_id"],
                "edge_quality": edge["edge_quality"],
                "source_coverage": edge["source_coverage"],
                "target_coverage": edge["target_coverage"],
                "evidence_count": edge["evidence_count"],
            }],
        }
        text = compact.render_text(row, {edge["edge_id"]: edge}, 4096)
        self.assertIn("maps_input_action", text)
        self.assertIn(edge["source"], text)
        self.assertIn(edge["target"], text)
        self.assertIn("quality=exact_reference", text)
        self.assertIn("coverage=first_class->first_class", text)


if __name__ == "__main__":
    unittest.main()
