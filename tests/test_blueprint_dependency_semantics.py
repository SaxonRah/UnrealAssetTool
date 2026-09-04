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

import uatool_core as core


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(value, separators=(",", ":")) + "\n" for value in values),
        encoding="utf-8",
    )


class BlueprintDependencySemanticsTest(unittest.TestCase):
    def test_variable_set_output_get_is_a_value_read_not_a_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bp = "/Game/Test/BP_Toggle.BP_Toggle"
            graph = "graph"

            write_jsonl(root / "blueprint_nodes.jsonl", [
                {
                    "node_id": "set",
                    "blueprint_path": bp,
                    "graph_id": graph,
                    "graph_name": "EventGraph",
                    "operation": "variable_set",
                    "symbol": "Flag",
                    "semantic": {},
                },
                {
                    "node_id": "not",
                    "blueprint_path": bp,
                    "graph_id": graph,
                    "graph_name": "EventGraph",
                    "operation": "function_call",
                    "symbol": "Not_PreBool",
                    "semantic": {"pure": True, "resolved_function": "Not_PreBool"},
                },
            ])
            write_jsonl(root / "blueprint_pins.jsonl", [
                {
                    "pin_id": "set-exec-in", "node_id": "set", "pin_index": 0,
                    "name": "execute", "direction": "input", "type": {"category": "exec"},
                },
                {
                    "pin_id": "set-exec-out", "node_id": "set", "pin_index": 1,
                    "name": "then", "direction": "output", "type": {"category": "exec"},
                },
                {
                    "pin_id": "set-value", "node_id": "set", "pin_index": 2,
                    "name": "Flag", "direction": "input", "type": {"category": "boolean"},
                },
                {
                    "pin_id": "set-get", "node_id": "set", "pin_index": 3,
                    "name": "Output_Get", "direction": "output", "type": {"category": "boolean"},
                },
                {
                    "pin_id": "not-a", "node_id": "not", "pin_index": 0,
                    "name": "A", "direction": "input", "type": {"category": "boolean"},
                },
                {
                    "pin_id": "not-out", "node_id": "not", "pin_index": 1,
                    "name": "ReturnValue", "direction": "output", "type": {"category": "boolean"},
                },
            ])
            write_jsonl(root / "blueprint_edges.jsonl", [
                {
                    "edge_kind": "data",
                    "graph_id": graph,
                    "source_node_id": "set",
                    "source_pin_id": "set-get",
                    "source_pin_name": "Output_Get",
                    "target_node_id": "not",
                    "target_pin_id": "not-a",
                    "target_pin_name": "A",
                },
                {
                    "edge_kind": "data",
                    "graph_id": graph,
                    "source_node_id": "not",
                    "source_pin_id": "not-out",
                    "source_pin_name": "ReturnValue",
                    "target_node_id": "set",
                    "target_pin_id": "set-value",
                    "target_pin_name": "Flag",
                },
            ])

            deps = core.derive_blueprint_data_dependencies(root)
            self.assertEqual(len(deps), 1)
            dep = deps[0]
            self.assertEqual(dep["sink_node_id"], "set")
            self.assertEqual(dep["sink_pin_id"], "set-value")
            self.assertFalse(dep["cycle"])
            self.assertEqual(dep["variable_reads"], ["Flag"])
            self.assertEqual(dep["text"], "Not_PreBool(A=Flag).ReturnValue")

    def test_multiple_sources_render_explicitly(self) -> None:
        expression = {
            "kind": "multi",
            "sources": [
                {"kind": "expression", "label": "A"},
                {"kind": "expression", "label": "B"},
            ],
        }
        self.assertEqual(core._render_data_expression(expression), "multi(A, B)")

        nested = {
            "kind": "expression",
            "label": "Consumer",
            "inputs": [{
                "pin": "self",
                "sources": [
                    {"kind": "expression", "label": "A"},
                    {"kind": "expression", "label": "B"},
                ],
            }],
        }
        self.assertEqual(core._render_data_expression(nested), "Consumer(self=multi(A, B))")


if __name__ == "__main__":
    unittest.main()
