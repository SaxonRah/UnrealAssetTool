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

import uatool_semantic_report as report


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(value, separators=(",", ":")) + "\n" for value in values),
        encoding="utf-8",
    )


def rows(path: Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            yield json.loads(line)


def pin(
    pin_id: str,
    node_id: str,
    graph_id: str,
    name: str,
    direction: str,
    category: str,
    *,
    default_value: str = "",
) -> dict:
    return {
        "pin_id": pin_id,
        "node_id": node_id,
        "blueprint_path": "/Game/Test/BP.BP",
        "graph_id": graph_id,
        "graph_name": "EventGraph" if graph_id == "caller" else "Macro",
        "pin_index": 0,
        "name": name,
        "direction": direction,
        "type": {
            "category": category,
            "subcategory": "",
            "container_type": 0,
            "is_reference": False,
            "is_const": False,
            "subcategory_object": "",
        },
        "default_value": default_value,
        "default_object": "",
        "default_text": "",
        "hidden": False,
        "not_connectable": False,
        "linked_count": 0,
    }


class SemanticReportMacroDataProvenanceTest(unittest.TestCase):
    def _fixture(self, root: Path) -> None:
        macro_path = "/Game/Test/BPL.BPL:Macro"
        write_jsonl(root / "blueprint_semantic_nodes.jsonl", [{
            "node_id": "macro",
            "operation": "macro_instance",
            "semantic_kind": "call",
            "opaque": False,
        }])
        write_jsonl(root / "blueprint_nodes.jsonl", [
            {
                "node_id": "macro",
                "graph_id": "caller",
                "operation": "macro_instance",
                "semantic": {
                    "macro_graph": macro_path,
                    "source_blueprint": "/Game/Test/BPL.BPL",
                },
            },
            {"node_id": "entry", "graph_id": "macro-graph", "operation": "tunnel", "semantic": {}},
            {"node_id": "exit", "graph_id": "macro-graph", "operation": "tunnel", "semantic": {}},
            {"node_id": "source", "graph_id": "caller", "operation": "variable_get", "semantic": {}},
            {"node_id": "consumer", "graph_id": "caller", "operation": "function_call", "semantic": {}},
        ])
        write_jsonl(root / "blueprint_graphs.jsonl", [
            {"graph_id": "caller", "graph_path": "/Game/Test/BP.BP:EventGraph"},
            {"graph_id": "macro-graph", "graph_path": macro_path},
        ])
        write_jsonl(root / "blueprint_pins.jsonl", [
            pin("macro-exec-in", "macro", "caller", "execute", "input", "exec"),
            pin("macro-exec-out", "macro", "caller", "then", "output", "exec"),
            pin("macro-value", "macro", "caller", "Value", "input", "float"),
            pin("macro-defaulted", "macro", "caller", "Defaulted", "input", "float", default_value="1.0"),
            pin("macro-unused", "macro", "caller", "Unused", "input", "float", default_value="2.0"),
            pin("macro-result", "macro", "caller", "Result", "output", "float"),
            pin("entry-exec", "entry", "macro-graph", "execute", "output", "exec"),
            pin("entry-value", "entry", "macro-graph", "Value", "output", "float"),
            pin("entry-defaulted", "entry", "macro-graph", "Defaulted", "output", "float"),
            pin("entry-unused", "entry", "macro-graph", "Unused", "output", "float"),
            pin("exit-exec", "exit", "macro-graph", "then", "input", "exec"),
            pin("exit-result", "exit", "macro-graph", "Result", "input", "float"),
            pin("source-out", "source", "caller", "Value", "output", "float"),
            pin("consumer-in", "consumer", "caller", "Value", "input", "float"),
        ])
        write_jsonl(root / "blueprint_semantic_edges.jsonl", [
            {
                "source_node_id": "macro",
                "relation": "maps_to_macro_graph",
                "target_kind": "blueprint_graph",
                "target": "macro-graph",
                "source_pin_id": "",
                "target_pin_id": "",
                "pin_category": "",
            },
            {
                "source_node_id": "macro",
                "relation": "binds_macro_input",
                "target_kind": "blueprint_pin",
                "target": "entry-value",
                "source_pin_id": "macro-value",
                "target_pin_id": "entry-value",
                "source_pin_name": "Value",
                "target_pin_name": "Value",
                "pin_category": "float",
            },
            {
                "source_node_id": "macro",
                "relation": "binds_macro_input",
                "target_kind": "blueprint_pin",
                "target": "entry-defaulted",
                "source_pin_id": "macro-defaulted",
                "target_pin_id": "entry-defaulted",
                "source_pin_name": "Defaulted",
                "target_pin_name": "Defaulted",
                "pin_category": "float",
            },
            {
                "source_node_id": "macro",
                "relation": "binds_macro_input",
                "target_kind": "blueprint_pin",
                "target": "entry-unused",
                "source_pin_id": "macro-unused",
                "target_pin_id": "entry-unused",
                "source_pin_name": "Unused",
                "target_pin_name": "Unused",
                "pin_category": "float",
            },
            {
                "source_node_id": "macro",
                "relation": "binds_macro_output",
                "target_kind": "blueprint_pin",
                "target": "exit-result",
                "source_pin_id": "macro-result",
                "target_pin_id": "exit-result",
                "source_pin_name": "Result",
                "target_pin_name": "Result",
                "pin_category": "float",
            },
        ])
        write_jsonl(root / "blueprint_edges.jsonl", [
            {
                "edge_kind": "data",
                "source_node_id": "source",
                "source_pin_id": "source-out",
                "source_pin_name": "Value",
                "target_node_id": "macro",
                "target_pin_id": "macro-value",
                "target_pin_name": "Value",
            },
            {
                "edge_kind": "data",
                "source_node_id": "entry",
                "source_pin_id": "entry-value",
                "source_pin_name": "Value",
                "target_node_id": "exit",
                "target_pin_id": "exit-result",
                "target_pin_name": "Result",
            },
            {
                "edge_kind": "data",
                "source_node_id": "entry",
                "source_pin_id": "entry-defaulted",
                "source_pin_name": "Defaulted",
                "target_node_id": "exit",
                "target_pin_id": "exit-result",
                "target_pin_name": "Result",
            },
            {
                "edge_kind": "data",
                "source_node_id": "macro",
                "source_pin_id": "macro-result",
                "source_pin_name": "Result",
                "target_node_id": "consumer",
                "target_pin_id": "consumer-in",
                "target_pin_name": "Value",
            },
        ])
        write_jsonl(root / "blueprint_data_dependencies.jsonl", [{
            "dependency_id": "dep-result",
            "sink_node_id": "exit",
            "sink_pin_id": "exit-result",
            "sink_pin_name": "Result",
            "sink_operation": "tunnel",
            "source_count": 2,
            "expression": {"kind": "multi", "sources": []},
            "text": "multi(Value, Defaulted)",
        }])
        write_jsonl(root / "blueprint_execution_blocks.jsonl", [])

    def test_reports_bridge_ready_connected_and_defaulted_inputs_and_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root)
            result = report.build_report(root, rows)

            self.assertEqual(result["macro_data_input_binding_count"], 3)
            self.assertEqual(result["macro_data_input_connected_source_count"], 1)
            self.assertEqual(result["macro_data_input_authored_value_count"], 2)
            self.assertEqual(result["macro_data_input_no_value_count"], 0)
            self.assertEqual(result["macro_data_input_used_binding_count"], 2)
            self.assertEqual(result["macro_data_input_body_consumer_edge_count"], 2)
            self.assertEqual(result["macro_data_input_bridge_ready_count"], 2)

            self.assertEqual(result["macro_data_output_binding_count"], 1)
            self.assertEqual(result["macro_data_output_internal_source_edge_count"], 2)
            self.assertEqual(result["macro_data_output_dependency_count"], 1)
            self.assertEqual(result["macro_data_output_caller_consumer_edge_count"], 1)
            self.assertEqual(result["macro_data_output_used_binding_count"], 1)
            self.assertEqual(result["macro_data_output_bridge_ready_count"], 1)
            self.assertEqual(result["macro_data_mismatches"], [])

    def test_missing_output_dependency_prevents_bridge_ready_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root)
            write_jsonl(root / "blueprint_data_dependencies.jsonl", [])
            result = report.build_report(root, rows)

            self.assertEqual(result["macro_data_output_binding_count"], 1)
            self.assertEqual(result["macro_data_output_internal_source_edge_count"], 2)
            self.assertEqual(result["macro_data_output_dependency_count"], 0)
            self.assertEqual(result["macro_data_output_bridge_ready_count"], 0)
            self.assertIn(
                ("output_missing_dependency_provenance", 1),
                result["macro_data_status"],
            )


if __name__ == "__main__":
    unittest.main()
