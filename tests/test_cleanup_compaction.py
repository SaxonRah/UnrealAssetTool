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

    def test_inline_blueprint_pins_are_removed_only_with_authoritative_pin_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            pins = [
                {"pin_id": "pin:1", "node_id": "node:1", "name": "A"},
                {"pin_id": "pin:2", "node_id": "node:1", "name": "B"},
            ]
            node = {
                "node_id": "node:1",
                "blueprint_path": "/Game/BP_Test.BP_Test",
                "title": "Test node",
                "pins": pins,
                "semantic": {"member_name": "DoThing"},
            }
            write_jsonl(output / "blueprint_pins.jsonl", pins)
            write_jsonl(output / "blueprint_nodes.jsonl", [node])
            pins_before = (output / "blueprint_pins.jsonl").read_bytes()

            result = cleanup.apply(output)
            self.assertEqual(result["blueprint_nodes_rewritten"], 1)
            self.assertEqual(result["inline_blueprint_pins"], 2)
            cleaned = list(rows(output / "blueprint_nodes.jsonl"))
            self.assertEqual(len(cleaned), 1)
            self.assertNotIn("pins", cleaned[0])
            self.assertEqual(cleaned[0]["semantic"], {"member_name": "DoThing"})
            self.assertEqual((output / "blueprint_pins.jsonl").read_bytes(), pins_before)
            self.assertIsNone(cleanup.validation_error(output))

            nodes_before = (output / "blueprint_nodes.jsonl").read_bytes()
            result = cleanup.apply(output)
            self.assertEqual(result["blueprint_nodes_rewritten"], 0)
            self.assertEqual(result["inline_blueprint_pins"], 0)
            self.assertEqual((output / "blueprint_nodes.jsonl").read_bytes(), nodes_before)

    def test_legacy_inline_blueprint_pins_are_preserved_without_normalized_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            node = {
                "node_id": "node:legacy",
                "pins": [{"pin_id": "pin:legacy", "node_id": "node:legacy"}],
            }
            write_jsonl(output / "blueprint_nodes.jsonl", [node])
            before = (output / "blueprint_nodes.jsonl").read_bytes()

            result = cleanup.apply(output)
            self.assertEqual(result["blueprint_nodes_rewritten"], 0)
            self.assertEqual(result["inline_blueprint_pins"], 0)
            self.assertEqual((output / "blueprint_nodes.jsonl").read_bytes(), before)
            self.assertIsNone(cleanup.validation_error(output))

    def test_inline_pin_cleanup_refuses_incomplete_normalized_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            write_jsonl(
                output / "blueprint_pins.jsonl",
                [{"pin_id": "pin:1", "node_id": "node:1"}],
            )
            write_jsonl(
                output / "blueprint_nodes.jsonl",
                [{
                    "node_id": "node:1",
                    "pins": [
                        {"pin_id": "pin:1", "node_id": "node:1"},
                        {"pin_id": "pin:missing", "node_id": "node:1"},
                    ],
                }],
            )
            before = (output / "blueprint_nodes.jsonl").read_bytes()

            with self.assertRaisesRegex(RuntimeError, "normalized pin 'pin:missing' is missing"):
                cleanup.apply(output)
            self.assertEqual((output / "blueprint_nodes.jsonl").read_bytes(), before)

    def test_compact_neighborhood_references_authoritative_edge_and_renders_on_query(self) -> None:
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
            conn.row_factory = sqlite3.Row
            try:
                conn.execute(
                    "CREATE TABLE project_nodes(node_kind TEXT,path TEXT,coverage TEXT,family TEXT,class_path TEXT)"
                )
                conn.execute(
                    "CREATE TABLE project_edges(edge_id TEXT PRIMARY KEY,source_kind TEXT,source TEXT,relation TEXT,target_kind TEXT,target TEXT,"
                    "source_coverage TEXT,target_coverage TEXT,edge_quality TEXT,evidence_count INTEGER,evidence_json TEXT)"
                )
                conn.execute(
                    "CREATE TABLE project_neighborhoods(root_path TEXT PRIMARY KEY,root_kind TEXT,root_coverage TEXT,"
                    "edge_count INTEGER,node_count INTEGER,truncated INTEGER,json TEXT,text TEXT)"
                )
                conn.execute(
                    "INSERT INTO project_nodes VALUES(?,?,?,?,?)",
                    ("blueprint", "/Game/BP.BP", "first_class", "blueprint", "/Script/Engine.Blueprint"),
                )
                conn.execute(
                    "INSERT INTO project_edges VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    tuple(edge[key] for key in (
                        "edge_id", "source_kind", "source", "relation", "target_kind", "target",
                        "source_coverage", "target_coverage", "edge_quality", "evidence_count",
                    )) + (json.dumps(edge["evidence"]),),
                )
                conn.execute(
                    "INSERT INTO project_neighborhoods VALUES(?,?,?,?,?,?,?,?)",
                    (
                        "/Game/BP.BP", "blueprint", "first_class", 1, 2, 0,
                        json.dumps(compact_rows[0]), "",
                    ),
                )

                captured = []

                def capture(result_rows, fields):
                    for row in result_rows:
                        captured.append({field: row[field] for field in fields})

                compact.query(conn, capture, "%VFX%", 20, max_chars=131072)
                neighborhood_texts = [
                    row["text"] for row in captured
                    if "text" in row and "root_path" in row
                ]
                self.assertTrue(neighborhood_texts)
                self.assertTrue(any("references_vfx_asset" in text for text in neighborhood_texts))
                self.assertTrue(any("/Game/VFX.NS" in text for text in neighborhood_texts))
                self.assertTrue(any("quality=exact_reference" in text for text in neighborhood_texts))
                self.assertEqual(
                    conn.execute("SELECT text FROM project_neighborhoods WHERE root_path='/Game/BP.BP'").fetchone()[0],
                    "",
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
