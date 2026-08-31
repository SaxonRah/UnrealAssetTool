from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_blueprint_semantics as semantics


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


class BlueprintRigVMSemanticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _node(self, node_id: str, symbol: str) -> dict:
        blueprint = "/Game/Test/CR_Test.CR_Test"
        graph = blueprint + "::graph::RigGraph"
        return {
            "node_id": node_id,
            "blueprint_path": blueprint,
            "graph_id": graph,
            "graph_name": "Rig Graph",
            "graph_kind": "graph",
            "graph_system": "control_rig",
            "node_class": "/Script/ControlRigDeveloper.ControlRigGraphNode",
            "operation": "control_rig_node",
            "symbol": symbol,
            "owner": "",
            "semantic": {"model_node_path": symbol},
        }

    def test_matched_control_rig_node_uses_exact_rigvm_bridge(self) -> None:
        node = self._node("rig-unit", "GetCurveValue")
        write_jsonl(self.output / "blueprint_nodes.jsonl", [node])
        write_jsonl(self.output / "blueprint_pins.jsonl", [])
        write_jsonl(self.output / "blueprint_edges.jsonl", [])
        write_jsonl(
            self.output / "rigvm_editor_links.jsonl",
            [{
                "node_id": "rig-unit",
                "blueprint_path": node["blueprint_path"],
                "graph_id": node["graph_id"],
                "graph_name": node["graph_name"],
                "model_node_path": "GetCurveValue",
                "status": "matched",
                "confidence": "high",
                "score": 200,
                "candidate_count": 1,
                "rigvm_object_id": "rigvm:/Game/Test/CR_Test::GetCurveValue",
                "rigvm_operation": "rigvm_unit",
                "rigvm_class": "/Script/RigVMDeveloper.RigVMUnitNode",
                "resolved_function_name": "FRigUnit_GetCurveValue::Execute",
                "template_notation": "GetCurveValue::Execute(in Curve,out Value)",
            }],
        )

        nodes, edges, graphs = semantics.derive(self.output, read_rows)
        self.assertEqual(len(nodes), 1)
        semantic = nodes[0]
        self.assertEqual(semantic["semantic_kind"], "call")
        self.assertEqual(semantic["primary_effect"], "call")
        self.assertEqual(semantic["target_kind"], "rigvm_node")
        self.assertEqual(semantic["target"], "rigvm:/Game/Test/CR_Test::GetCurveValue")
        self.assertEqual(semantic["rigvm_bridge_status"], "matched")
        self.assertEqual(semantic["rigvm_confidence"], "high")
        self.assertEqual(semantic["rigvm_operation"], "rigvm_unit")
        self.assertEqual(semantic["rigvm_class"], "/Script/RigVMDeveloper.RigVMUnitNode")
        self.assertEqual(semantic["rigvm_function"], "FRigUnit_GetCurveValue::Execute")

        relations = {
            (edge["relation"], edge["target_kind"], edge["target"])
            for edge in edges
        }
        self.assertIn(
            ("maps_to_rigvm_node", "rigvm_node", "rigvm:/Game/Test/CR_Test::GetCurveValue"),
            relations,
        )
        self.assertIn(
            ("has_rigvm_operation", "rigvm_operation", "rigvm_unit"),
            relations,
        )
        self.assertIn(
            ("uses_rigvm_class", "class", "/Script/RigVMDeveloper.RigVMUnitNode"),
            relations,
        )
        self.assertIn(
            ("invokes_rigvm_function", "function", "FRigUnit_GetCurveValue::Execute"),
            relations,
        )
        self.assertIn(
            ("uses_rigvm_template", "rigvm_template", "GetCurveValue::Execute(in Curve,out Value)"),
            relations,
        )
        self.assertEqual(graphs[0]["semantic_kind_counts"], {"call": 1})

        for filename, file_rows in zip(semantics.DERIVED_FILES, (nodes, edges, graphs)):
            write_jsonl(self.output / filename, file_rows)
        manifest = {
            "blueprint_semantic_schema_version": semantics.SEMANTIC_SCHEMA_VERSION,
            "derived_counts": {
                filename.removesuffix(".jsonl"): len(file_rows)
                for filename, file_rows in zip(semantics.DERIVED_FILES, (nodes, edges, graphs))
            },
        }
        (self.output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIsNone(semantics.validation_error(self.output, read_rows))

    def test_unmatched_control_rig_node_remains_fallback(self) -> None:
        node = self._node("rig-unmatched", "UnknownRigNode")
        write_jsonl(self.output / "blueprint_nodes.jsonl", [node])
        write_jsonl(self.output / "blueprint_pins.jsonl", [])
        write_jsonl(self.output / "blueprint_edges.jsonl", [])
        write_jsonl(
            self.output / "rigvm_editor_links.jsonl",
            [{
                "node_id": "rig-unmatched",
                "status": "unmatched",
                "confidence": "none",
                "rigvm_object_id": "",
                "rigvm_operation": "",
                "rigvm_class": "",
                "resolved_function_name": "",
                "template_notation": "",
            }],
        )

        nodes, edges, _ = semantics.derive(self.output, read_rows)
        self.assertEqual(nodes[0]["semantic_kind"], "classified")
        self.assertEqual(nodes[0]["primary_effect"], "operation")
        self.assertEqual(nodes[0]["target_kind"], "")
        self.assertEqual(nodes[0]["rigvm_bridge_status"], "unmatched")
        self.assertFalse(any(edge["relation"] == "maps_to_rigvm_node" for edge in edges))


if __name__ == "__main__":
    unittest.main()
