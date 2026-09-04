from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_blueprint_enums as enums


class BlueprintEnumTest(unittest.TestCase):
    def test_select_renders_selector_and_value_enum_display_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            entries = [
                {
                    "enum_path": "/Game/Data/E_Select.E_Select",
                    "enum_index": 0,
                    "numeric_value": 0,
                    "raw_name": "NewEnumerator0",
                    "authored_name": "Forward",
                    "display_name": "Forward",
                    "tooltip": "",
                    "hidden": False,
                    "is_max": False,
                },
                {
                    "enum_path": "/Game/Data/E_Select.E_Select",
                    "enum_index": 1,
                    "numeric_value": 1,
                    "raw_name": "NewEnumerator1",
                    "authored_name": "Back",
                    "display_name": "Back",
                    "tooltip": "",
                    "hidden": False,
                    "is_max": False,
                },
                {
                    "enum_path": "/Game/Data/E_Value.E_Value",
                    "enum_index": 0,
                    "numeric_value": 0,
                    "raw_name": "NewEnumerator0",
                    "authored_name": "Walk",
                    "display_name": "Walk",
                    "tooltip": "",
                    "hidden": False,
                    "is_max": False,
                },
            ]
            with (output / "blueprint_enum_entries.jsonl").open("w", encoding="utf-8") as handle:
                for row in entries:
                    handle.write(json.dumps(row) + "\n")

            pins = [
                {
                    "pin_id": "p0",
                    "node_id": "select-node",
                    "name": "NewEnumerator0",
                    "type": {"subcategory_object": "/Game/Data/E_Value.E_Value"},
                },
                {
                    "pin_id": "p1",
                    "node_id": "select-node",
                    "name": "NewEnumerator1",
                    "type": {"subcategory_object": "/Game/Data/E_Value.E_Value"},
                },
                {
                    "pin_id": "pi",
                    "node_id": "select-node",
                    "name": "Index",
                    "type": {"subcategory_object": "/Game/Data/E_Select.E_Select"},
                },
            ]
            core = types.SimpleNamespace(iter_blueprint_pin_rows=lambda _: iter(pins))
            pins_by_node, _ = enums._pin_maps(output, core)
            lookup = enums._entry_lookup(output)
            expression = {
                "kind": "expression",
                "node_id": "select-node",
                "operation": "select",
                "label": "Select",
                "output_pin": "ReturnValue",
                "inputs": [
                    {"pin": "NewEnumerator0", "literal": "NewEnumerator0"},
                    {"pin": "NewEnumerator1", "literal": "NewEnumerator0"},
                ],
            }
            self.assertEqual(
                enums._render_expression(expression, lookup, pins_by_node),
                "Select(Forward=Walk, Back=Walk).ReturnValue",
            )
            self.assertEqual(expression["inputs"][0]["pin"], "NewEnumerator0")
            self.assertEqual(expression["inputs"][0]["literal"], "NewEnumerator0")

    def test_enum_renderer_preserves_explicit_multi_source_marker(self) -> None:
        expression = {
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
        self.assertEqual(
            enums._render_expression(expression, {}, {}),
            "Consumer(self=multi(A, B))",
        )

    def test_input_debug_key_is_promoted_to_input_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            (output / "blueprint_nodes.jsonl").write_text(
                json.dumps(
                    {
                        "node_id": "debug-key",
                        "blueprint_path": "/Game/BP.BP",
                        "graph_id": "event-graph",
                        "graph_name": "EventGraph",
                        "node_class": "/Script/BlueprintGraph.K2Node_InputDebugKey",
                        "operation": "input_debug_key",
                        "title": "F2",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            def property_value(props, *names):
                for name in names:
                    if name in props:
                        return str(props[name].get("value", ""))
                return ""

            core = types.SimpleNamespace(
                _node_property_lookup=lambda _: {"debug-key": {"InputKey": {"value": "F2"}}},
                iter_blueprint_pin_rows=lambda _: iter(()),
                iter_jsonl=lambda path: (json.loads(line) for line in path.read_text().splitlines()),
                _property_value=property_value,
                _pin_signature=lambda pin: pin,
                _pin_direction_is_output=lambda pin: False,
                _is_exec_pin=lambda pin: False,
            )
            rows = enums._augment_debug_input_events(output, [], core)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["event_id"], "debug-key")
            self.assertEqual(rows[0]["operation"], "input_debug_key")
            self.assertEqual(rows[0]["event_kind"], "input_key")
            self.assertEqual(rows[0]["input_name"], "F2")


if __name__ == "__main__":
    unittest.main()
