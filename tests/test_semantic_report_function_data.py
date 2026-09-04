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


def ptype(category: str = "float", *, object_path: str = "", is_ref: bool = False) -> dict:
    return {
        "category": category,
        "subcategory": "",
        "subcategory_object": object_path,
        "container_type": 0,
        "is_reference": is_ref,
        "is_const": False,
    }


def pin(
    pin_id: str,
    node_id: str,
    graph_id: str,
    name: str,
    direction: str,
    pin_type: dict,
    *,
    default_value: str = "",
) -> dict:
    return {
        "pin_id": pin_id,
        "node_id": node_id,
        "blueprint_path": "/Game/Test/BP.BP",
        "graph_id": graph_id,
        "graph_name": graph_id,
        "pin_index": 0,
        "name": name,
        "direction": direction,
        "type": pin_type,
        "default_value": default_value,
        "default_object": "",
        "default_text": "",
        "hidden": False,
        "not_connectable": False,
        "linked_count": 0,
    }


class SemanticReportFunctionDataAuditTest(unittest.TestCase):
    def test_exact_split_pure_return_and_interface_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            caller_bp = "/Game/Test/BP.BP"
            target_bp = "/Game/Test/BP_Target.BP_Target"
            interface_bp = "/Game/Test/BPI_Target.BPI_Target"
            struct_type = "/Script/Test.Config"

            write_jsonl(root / "blueprint_semantic_nodes.jsonl", [])
            write_jsonl(root / "blueprint_nodes.jsonl", [])
            write_jsonl(root / "blueprint_graphs.jsonl", [])
            write_jsonl(root / "blueprint_semantic_edges.jsonl", [])
            write_jsonl(root / "blueprint_execution_blocks.jsonl", [])
            write_jsonl(root / "blueprint_execution_block_edges.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_execution_edges.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_execution_terminals.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_data_routes.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_function_execution_edges.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_function_execution_terminals.jsonl", [])

            write_jsonl(root / "blueprints.jsonl", [
                {"object_path": caller_bp, "blueprint_type": 0},
                {"object_path": target_bp, "blueprint_type": 0},
                {"object_path": interface_bp, "blueprint_type": 3},
            ])
            write_jsonl(root / "blueprint_functions.jsonl", [
                {
                    "function_id": "fn-pure",
                    "blueprint_path": target_bp,
                    "blueprint_pure": True,
                    "entry_node_id": "entry-pure",
                    "result_node_ids": ["result-pure"],
                    "inputs": [
                        {"name": "Value", "type": ptype()},
                        {"name": "Config", "type": ptype("struct", object_path=struct_type)},
                    ],
                    "outputs": [{"name": "Result", "type": ptype()}],
                },
                {
                    "function_id": "fn-interface",
                    "blueprint_path": interface_bp,
                    "blueprint_pure": False,
                    "entry_node_id": "entry-interface",
                    "result_node_ids": [],
                    "inputs": [{"name": "Value", "type": ptype()}],
                    "outputs": [],
                },
            ])

            write_jsonl(root / "blueprint_call_edges.jsonl", [
                {
                    "call_id": "call-pure",
                    "call_node_id": "call-pure",
                    "blueprint_path": caller_bp,
                    "graph_id": "caller",
                    "target_blueprint_path": target_bp,
                    "target_function_id": "fn-pure",
                    "resolution": "internal",
                    "pure": True,
                    "latent": False,
                    "interface_call": False,
                },
                {
                    "call_id": "call-interface",
                    "call_node_id": "call-interface",
                    "blueprint_path": caller_bp,
                    "graph_id": "caller",
                    "target_blueprint_path": interface_bp,
                    "target_function_id": "fn-interface",
                    "resolution": "internal",
                    "pure": False,
                    "latent": False,
                    "interface_call": True,
                },
            ])

            struct_parent_type = ptype("struct", object_path=struct_type)
            write_jsonl(root / "blueprint_pins.jsonl", [
                pin("call-value", "call-pure", "caller", "Value", "input", ptype()),
                pin("call-config-speed", "call-pure", "caller", "Config_Speed", "input", ptype(), default_value="2.0"),
                pin("call-result", "call-pure", "caller", "Result", "output", ptype()),
                pin("call-interface-value", "call-interface", "caller", "Value", "input", ptype(), default_value="3.0"),
                pin("source-value", "source", "caller", "Value", "output", ptype()),
                pin("caller-result-in", "consumer", "caller", "Value", "input", ptype()),
                pin("entry-value", "entry-pure", "fn-pure", "Value", "output", ptype()),
                pin("entry-config", "entry-pure", "fn-pure", "Config", "output", struct_parent_type),
                pin("entry-config-speed", "entry-pure", "fn-pure", "Config_Speed", "output", ptype()),
                pin("body-value-in", "body-value", "fn-pure", "Value", "input", ptype()),
                pin("body-speed-in", "body-speed", "fn-pure", "Speed", "input", ptype()),
                pin("result-value", "result-pure", "fn-pure", "Result", "input", ptype(), default_value="4.0"),
                pin("entry-interface-value", "entry-interface", "fn-interface", "Value", "output", ptype()),
                pin("body-interface-in", "body-interface", "fn-interface", "Value", "input", ptype()),
            ])

            write_jsonl(root / "blueprint_edges.jsonl", [
                {
                    "edge_kind": "data",
                    "source_node_id": "source",
                    "source_pin_id": "source-value",
                    "source_pin_name": "Value",
                    "target_node_id": "call-pure",
                    "target_pin_id": "call-value",
                    "target_pin_name": "Value",
                },
                {
                    "edge_kind": "data",
                    "source_node_id": "entry-pure",
                    "source_pin_id": "entry-value",
                    "source_pin_name": "Value",
                    "target_node_id": "body-value",
                    "target_pin_id": "body-value-in",
                    "target_pin_name": "Value",
                },
                {
                    "edge_kind": "data",
                    "source_node_id": "entry-pure",
                    "source_pin_id": "entry-config-speed",
                    "source_pin_name": "Config_Speed",
                    "target_node_id": "body-speed",
                    "target_pin_id": "body-speed-in",
                    "target_pin_name": "Speed",
                },
                {
                    "edge_kind": "data",
                    "source_node_id": "call-pure",
                    "source_pin_id": "call-result",
                    "source_pin_name": "Result",
                    "target_node_id": "consumer",
                    "target_pin_id": "caller-result-in",
                    "target_pin_name": "Value",
                },
                {
                    "edge_kind": "data",
                    "source_node_id": "entry-interface",
                    "source_pin_id": "entry-interface-value",
                    "source_pin_name": "Value",
                    "target_node_id": "body-interface",
                    "target_pin_id": "body-interface-in",
                    "target_pin_name": "Value",
                },
            ])
            write_jsonl(root / "blueprint_data_dependencies.jsonl", [{
                "dependency_id": "dep-call-value",
                "sink_node_id": "call-pure",
                "sink_pin_id": "call-value",
                "sink_pin_name": "Value",
                "source_count": 1,
                "text": "Source.Value",
            }])

            write_jsonl(root / "blueprint_call_bindings.jsonl", [
                {
                    "binding_id": "bind-value",
                    "call_node_id": "call-pure",
                    "target_function_id": "fn-pure",
                    "direction": "argument",
                    "call_pin_id": "call-value",
                    "call_pin_name": "Value",
                    "parameter_name": "Value",
                    "parameter_pin_ids": ["entry-value"],
                    "match_kind": "exact",
                    "split_suffix": "",
                    "call_pin_type": ptype(),
                    "parameter_type": ptype(),
                    "dependency_ids": ["dep-call-value"],
                    "consumer_pin_ids": ["body-value-in"],
                },
                {
                    "binding_id": "bind-speed",
                    "call_node_id": "call-pure",
                    "target_function_id": "fn-pure",
                    "direction": "argument",
                    "call_pin_id": "call-config-speed",
                    "call_pin_name": "Config_Speed",
                    "parameter_name": "Config",
                    "parameter_pin_ids": ["entry-config"],
                    "match_kind": "split_struct",
                    "split_suffix": "Speed",
                    "call_pin_type": ptype(),
                    "parameter_type": struct_parent_type,
                    "dependency_ids": [],
                    "consumer_pin_ids": [],
                },
                {
                    "binding_id": "bind-result",
                    "call_node_id": "call-pure",
                    "target_function_id": "fn-pure",
                    "direction": "return",
                    "call_pin_id": "call-result",
                    "call_pin_name": "Result",
                    "parameter_name": "Result",
                    "parameter_pin_ids": ["result-value"],
                    "match_kind": "exact",
                    "split_suffix": "",
                    "call_pin_type": ptype(),
                    "parameter_type": ptype(),
                    "dependency_ids": [],
                    "consumer_pin_ids": ["caller-result-in"],
                },
                {
                    "binding_id": "bind-interface",
                    "call_node_id": "call-interface",
                    "target_function_id": "fn-interface",
                    "direction": "argument",
                    "call_pin_id": "call-interface-value",
                    "call_pin_name": "Value",
                    "parameter_name": "Value",
                    "parameter_pin_ids": ["entry-interface-value"],
                    "match_kind": "exact",
                    "split_suffix": "",
                    "call_pin_type": ptype(),
                    "parameter_type": ptype(),
                    "dependency_ids": [],
                    "consumer_pin_ids": ["body-interface-in"],
                },
            ])

            result = report.build_report(root, rows)

            self.assertEqual(result["function_data_binding_count"], 4)
            self.assertEqual(result["function_data_parameter_identity_count"], 4)
            self.assertEqual(result["function_data_member_identity_exact_count"], 3)
            self.assertEqual(result["function_data_split_parent_projection_count"], 1)
            self.assertEqual(result["function_data_value_type_verified_count"], 4)
            self.assertEqual(result["function_data_type_verified_count"], 4)
            self.assertEqual(result["function_data_qualifier_difference_count"], 0)
            self.assertEqual(result["function_data_exact_call_signature_equal_count"], 3)
            self.assertEqual(result["function_data_exact_signature_pin_equal_count"], 3)
            self.assertEqual(result["function_data_exact_call_pin_equal_count"], 3)
            self.assertEqual(dict(result["function_data_type_surface_shapes"]), {
                "call_signature=same signature_pin=same call_pin=same": 3,
            })
            self.assertEqual(result["function_data_type_diff_fields"], [])
            self.assertEqual(result["function_data_split_member_resolved_count"], 1)
            self.assertEqual(result["function_data_split_member_unresolved_count"], 0)
            self.assertEqual(result["function_data_split_parent_pin_count"], 1)
            self.assertEqual(result["function_data_split_exact_name_candidate_count"], 1)
            self.assertEqual(result["function_data_split_suffix_candidate_count"], 0)
            self.assertEqual(result["function_data_split_prefixed_candidate_count"], 1)
            self.assertEqual(dict(result["function_data_split_candidate_shapes"]), {
                "parent=yes exact=1 suffix=0 prefixed=1 raw_nonexec=3": 1,
            })
            self.assertEqual(dict(result["function_data_directions"]), {
                "argument": 3,
                "return": 1,
            })
            self.assertEqual(dict(result["function_data_match_kinds"]), {
                "exact": 3,
                "split_struct": 1,
            })

            self.assertEqual(result["function_data_argument_count"], 3)
            self.assertEqual(result["function_data_argument_connected_value_count"], 1)
            self.assertEqual(result["function_data_argument_authored_value_count"], 2)
            self.assertEqual(result["function_data_argument_no_value_count"], 0)
            self.assertEqual(result["function_data_argument_body_consumer_count"], 2)
            self.assertEqual(result["function_data_argument_unused_count"], 1)
            self.assertEqual(result["function_data_argument_binding_verified_count"], 2)
            self.assertEqual(result["function_data_argument_route_ready_count"], 1)

            self.assertEqual(result["function_data_return_count"], 1)
            self.assertEqual(result["function_data_return_dependency_count"], 0)
            self.assertEqual(result["function_data_return_authored_value_pin_count"], 1)
            self.assertEqual(result["function_data_return_missing_provenance_binding_count"], 0)
            self.assertEqual(result["function_data_return_caller_consumer_count"], 1)
            self.assertEqual(result["function_data_return_unused_count"], 0)
            self.assertEqual(result["function_data_return_binding_verified_count"], 1)
            self.assertEqual(result["function_data_return_route_ready_count"], 1)

            self.assertEqual(result["function_data_mismatches"], [])
            self.assertEqual(dict(result["function_data_target_kinds"]), {
                "interface_dispatch_or_declaration": 1,
                "pure_internal": 3,
            })


if __name__ == "__main__":
    unittest.main()
