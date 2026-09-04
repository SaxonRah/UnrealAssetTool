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


def ptype(
    category: str = "float",
    *,
    object_path: str = "",
    is_reference: bool = False,
    is_const: bool = False,
) -> dict:
    return {
        "category": category,
        "subcategory": "",
        "subcategory_object": object_path,
        "container_type": 0,
        "is_reference": is_reference,
        "is_const": is_const,
    }


def pin(
    pin_id: str,
    node_id: str,
    name: str,
    direction: str,
    pin_type: dict,
) -> dict:
    return {
        "pin_id": pin_id,
        "node_id": node_id,
        "blueprint_path": "/Game/Test/BP.BP",
        "graph_id": "graph",
        "graph_name": "Graph",
        "pin_index": 0,
        "name": name,
        "direction": direction,
        "type": pin_type,
        "default_value": "",
        "default_object": "",
        "default_text": "",
        "hidden": False,
        "not_connectable": False,
        "linked_count": 0,
    }


class BlueprintCallBindingTypeProvenanceTest(unittest.TestCase):
    def test_preserves_qualifier_surfaces_and_split_parent_projection(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            struct_path = "/Script/Test.Config"

            # Exact A mirrors the GASP shape where call and actual parameter pin
            # agree while signature qualifiers differ. Exact B mirrors the shape
            # where signature and actual parameter pin agree while the call-site
            # reference presentation differs.
            call_a = ptype()
            sig_a = ptype(is_reference=True, is_const=True)
            pin_a = ptype()

            call_b = ptype()
            sig_b = ptype(is_reference=True)
            pin_b = ptype(is_reference=True)

            split_call = ptype()
            split_parent = ptype("struct", object_path=struct_path)

            write_jsonl(root / "blueprint_pins.jsonl", [
                pin("call-a", "call", "A", "input", call_a),
                pin("call-b", "call", "B", "input", call_b),
                pin("call-speed", "call", "Config_Speed", "input", split_call),
                pin("entry-a", "entry", "A", "output", pin_a),
                pin("entry-b", "entry", "B", "output", pin_b),
                pin("entry-config", "entry", "Config", "output", split_parent),
            ])
            write_jsonl(root / "blueprint_edges.jsonl", [])

            functions = [{
                "function_id": "fn",
                "blueprint_path": "/Game/Test/BP_Target.BP_Target",
                "entry_node_id": "entry",
                "result_node_ids": [],
                "inputs": [
                    {"name": "A", "type": sig_a},
                    {"name": "B", "type": sig_b},
                    {"name": "Config", "type": split_parent},
                ],
                "outputs": [],
            }]
            calls = [{
                "call_id": "call",
                "call_node_id": "call",
                "blueprint_path": "/Game/Test/BP.BP",
                "graph_id": "graph",
                "caller_function_id": "",
                "target_blueprint_path": "/Game/Test/BP_Target.BP_Target",
                "target_function_id": "fn",
                "resolution": "internal",
            }]

            bindings = core.derive_blueprint_call_bindings(root, functions, calls, [])
            self.assertEqual(len(bindings), 3)
            by_pin = {row["call_pin_id"]: row for row in bindings}

            a = by_pin["call-a"]
            self.assertEqual(a["parameter_identity_kind"], "exact_parameter")
            self.assertTrue(a["member_identity_exact"])
            self.assertTrue(a["value_type_compatible"])
            self.assertEqual(a["value_type_basis"], "call_signature_parameter_pin")
            self.assertEqual(a["parameter_pin_types"], [pin_a])
            self.assertEqual(a["qualifier_surfaces"], {
                "call_pin": {"is_reference": False, "is_const": False},
                "signature": {"is_reference": True, "is_const": True},
                "parameter_pins": [{"is_reference": False, "is_const": False}],
            })

            b = by_pin["call-b"]
            self.assertEqual(b["parameter_identity_kind"], "exact_parameter")
            self.assertTrue(b["member_identity_exact"])
            self.assertTrue(b["value_type_compatible"])
            self.assertEqual(b["parameter_pin_types"], [pin_b])
            self.assertEqual(b["qualifier_surfaces"]["call_pin"]["is_reference"], False)
            self.assertEqual(b["qualifier_surfaces"]["signature"]["is_reference"], True)
            self.assertEqual(b["qualifier_surfaces"]["parameter_pins"][0]["is_reference"], True)

            split = by_pin["call-speed"]
            self.assertEqual(split["match_kind"], "split_struct")
            self.assertEqual(split["split_suffix"], "Speed")
            self.assertEqual(split["parameter_identity_kind"], "split_parent_projection")
            self.assertFalse(split["member_identity_exact"])
            self.assertTrue(split["value_type_compatible"])
            self.assertEqual(split["value_type_basis"], "signature_parent_parameter_pin")
            self.assertEqual(split["parameter_pin_ids"], ["entry-config"])
            self.assertEqual(split["parameter_pin_types"], [split_parent])


if __name__ == "__main__":
    unittest.main()
