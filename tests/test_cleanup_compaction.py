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

import uatool_canonical_cleanup as cleanup
import uatool_project_neighborhood_compact as compact


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class CleanupCompactionTest(unittest.TestCase):
    def test_material_expression_guid_cleanup_is_byte_preserving_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            target = output / "material_properties.jsonl"
            stable = {
                "asset_path": "/Game/M.M",
                "owner_kind": "expression",
                "owner_id": "/Game/M.M:E0",
                "declaring_type": "/Script/Engine.MaterialExpression",
                "property_name": "Desc",
                "value": "keep me",
            }
            generated = {
                "asset_path": "/Game/M.M",
                "owner_kind": "expression",
                "owner_id": "/Game/M.M:E0",
                "declaring_type": "/Script/Engine.MaterialExpression",
                "property_name": "MaterialExpressionGuid",
                "value": "A-GENERATED-GUID",
            }
            write_jsonl(target, [stable, generated])
            original_stable_line = json.dumps(stable, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
            (output / "manifest.json").write_text(
                json.dumps({"counts": {"material_properties": 2}}, indent=2) + "\n",
                encoding="utf-8",
            )

            result = cleanup.apply(output)
            self.assertEqual(result["material_expression_guids"], 1)
            self.assertEqual(target.read_bytes(), original_stable_line)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"]["material_properties"], 1)
            self.assertIsNone(cleanup.validation_error(output))

            before = target.read_bytes()
            result = cleanup.apply(output)
            self.assertEqual(result["material_expression_guids"], 0)
            self.assertEqual(target.read_bytes(), before)

    def test_compact_neighborhood_references_authoritative_edge_and_rebuilds_text(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            edge = {
                "edge_id": "pedge:1",
                "source_kind": "blueprint",
                "source": "/Game/BP.BP",
                "relation": "references_vfx_asset",
                "target_kind": "niagara_system",
                "target": "/Game/VFX.NS",
                "source_coverage": "first_class",
                "target_coverage": "first_class",
                "edge_quality": "exact_reference",
                "evidence_count": 1,
                "evidence": [{"stream": "blueprint_relations.jsonl", "kind": "test"}],
            }
            expanded = [{
                "root_path": "/Game/BP.BP",
                "root_kind": "blueprint",
                "root_coverage": "first_class",
                "max_depth": 3,
                "edge_count": 1,
                "node_count": 2,
                "truncated": False,
                "text": "large duplicated text",
                "hops": [{
                    "depth": 1,
                    "direction": "out",
                    **edge,
                }],
            }]
            compact_rows = compact.compact(expanded)
            self.assertNotIn("text", compact_rows[0])
            self.assertNotIn("source", compact_rows[0]["hops"][0])
            self.assertNotIn("evidence", compact_rows[0]["hops"][0])
            self.assertEqual(compact_rows[0]["hops"][0]["edge_id"], "pedge:1")

            write_jsonl(output / "project_edges.jsonl", [edge])
            write_jsonl(output / "project_neighborhoods.jsonl", compact_rows)
            self.assertIsNone(compact.validation_error(output, rows))

            conn = sqlite3.connect(":memory:")
            try:
                conn.execute(
                    "CREATE TABLE project_edges(edge_id TEXT,source_kind TEXT,source TEXT,relation TEXT,target_kind TEXT,target TEXT,"
                    "source_coverage TEXT,target_coverage TEXT,edge_quality TEXT,evidence_count INTEGER)"
                )
                conn.execute(
                    "CREATE TABLE project_neighborhoods(root_path TEXT PRIMARY KEY,text TEXT,json TEXT)"
                )
                conn.execute(
                    "INSERT INTO project_edges VALUES(?,?,?,?,?,?,?,?,?,?)",
                    tuple(edge[key] for key in (
                        "edge_id", "source_kind", "source", "relation", "target_kind", "target",
                        "source_coverage", "target_coverage", "edge_quality", "evidence_count",
                    )),
                )
                conn.execute(
                    "INSERT INTO project_neighborhoods VALUES(?,?,?)",
                    ("/Game/BP.BP", "", json.dumps(compact_rows[0])),
                )
                compact.enrich_database(conn, output, rows, max_chars=131072)
                text = conn.execute(
                    "SELECT text FROM project_neighborhoods WHERE root_path='/Game/BP.BP'"
                ).fetchone()[0]
                self.assertIn("references_vfx_asset", text)
                self.assertIn("/Game/VFX.NS", text)
                self.assertIn("quality=exact_reference", text)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
