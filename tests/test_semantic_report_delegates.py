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

import uatool_blueprint_delegates as delegates
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


def pin(pin_id: str, node_id: str, name: str, direction: str, category: str) -> dict:
    return {
        "pin_id": pin_id,
        "node_id": node_id,
        "blueprint_path": "/Game/Test/BP.BP",
        "graph_id": "caller",
        "graph_name": "EventGraph",
        "pin_index": 0,
        "name": name,
        "direction": direction,
        "type": {
            "category": category,
            "subcategory": "",
            "subcategory_object": "",
            "container_type": 0,
            "is_reference": False,
            "is_const": False,
        },
        "default_value": "",
        "default_object": "",
        "default_text": "",
        "hidden": False,
        "not_connectable": False,
        "linked_count": 0,
    }


class SemanticReportDelegateAuditTest(unittest.TestCase):
    def test_exact_create_bind_dispatcher_and_component_event_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bp = "/Game/Test/BP.BP"
            owner = "/Game/Test/BP_Target.BP_Target_C"
            guid = "11111111-2222-3333-4444-555555555555"
            create_id = f"{bp}::graph::caller::node::aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            event_id = f"{bp}::graph::caller::node::{guid}"
            bind_id = f"{bp}::graph::caller::node::bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
            call_id = f"{bp}::graph::caller::node::cccccccc-dddd-eeee-ffff-000000000000"
            clear_id = f"{bp}::graph::caller::node::dddddddd-eeee-ffff-0000-111111111111"
            unbind_id = f"{bp}::graph::caller::node::eeeeeeee-ffff-0000-1111-222222222222"
            function_create_id = f"{bp}::graph::caller::node::ffffffff-0000-1111-2222-333333333333"

            raw_nodes = [
                {
                    "node_id": create_id,
                    "blueprint_path": bp,
                    "graph_id": "caller",
                    "graph_name": "EventGraph",
                    "node_class": "/Script/BlueprintGraph.K2Node_CreateDelegate",
                    "operation": "delegate_create",
                    "symbol": "OnReady",
                    "semantic": {
                        "selected_function": "ONREADY",
                        "selected_function_guid": "{" + guid + "}",
                    },
                },
                {
                    "node_id": event_id,
                    "blueprint_path": bp,
                    "graph_id": "caller",
                    "graph_name": "EventGraph",
                    "node_class": "/Script/BlueprintGraph.K2Node_CustomEvent",
                    "operation": "custom_event",
                    "symbol": "OnReady",
                    "semantic": {},
                },
                {
                    "node_id": bind_id,
                    "blueprint_path": bp,
                    "graph_id": "caller",
                    "graph_name": "EventGraph",
                    "node_class": "/Script/BlueprintGraph.K2Node_AddDelegate",
                    "operation": "delegate_bind",
                    "symbol": "OnReadyDelegate",
                    "semantic": {
                        "delegate_name": "OnReadyDelegate",
                        "delegate_owner": owner,
                        "delegate_member_guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                        "delegate_self_context": True,
                    },
                },
                {
                    "node_id": call_id,
                    "blueprint_path": bp,
                    "graph_id": "caller",
                    "graph_name": "EventGraph",
                    "node_class": "/Script/BlueprintGraph.K2Node_CallDelegate",
                    "operation": "delegate_call",
                    "symbol": "OnReadyDelegate",
                    "semantic": {
                        "delegate_name": "OnReadyDelegate",
                        "delegate_owner": owner,
                        "delegate_member_guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                        "delegate_self_context": True,
                    },
                },
                {
                    "node_id": clear_id,
                    "blueprint_path": bp,
                    "graph_id": "caller",
                    "graph_name": "EventGraph",
                    "node_class": "/Script/BlueprintGraph.K2Node_ClearDelegate",
                    "operation": "delegate_clear",
                    "symbol": "OnReadyDelegate",
                    "semantic": {
                        "delegate_name": "OnReadyDelegate",
                        "delegate_owner": owner,
                        "delegate_member_guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                        "delegate_self_context": True,
                    },
                },
                {
                    "node_id": unbind_id,
                    "blueprint_path": bp,
                    "graph_id": "caller",
                    "graph_name": "EventGraph",
                    "node_class": "/Script/BlueprintGraph.K2Node_RemoveDelegate",
                    "operation": "delegate_unbind",
                    "symbol": "OnReadyDelegate",
                    "semantic": {
                        "delegate_name": "OnReadyDelegate",
                        "delegate_owner": owner,
                        "delegate_member_guid": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                        "delegate_self_context": True,
                    },
                },
                {
                    "node_id": function_create_id,
                    "blueprint_path": bp,
                    "graph_id": "caller",
                    "graph_name": "EventGraph",
                    "node_class": "/Script/BlueprintGraph.K2Node_CreateDelegate",
                    "operation": "delegate_create",
                    "symbol": "DoThing",
                    "semantic": {
                        "selected_function": "DoThing",
                        "selected_function_guid": "99999999-8888-7777-6666-555555555555",
                        "selected_function_path": "/Game/Test/BP.BP_C:DoThing",
                        "selected_function_scope_class": "/Game/Test/BP.BP_C",
                    },
                },
            ]
            write_jsonl(root / "blueprint_nodes.jsonl", raw_nodes)
            write_jsonl(root / "blueprint_semantic_nodes.jsonl", [
                {
                    "node_id": row["node_id"],
                    "operation": row["operation"],
                    "semantic_kind": "delegate" if row["operation"].startswith("delegate_") else "event",
                    "opaque": False,
                    "has_exec_flow": row["operation"] != "delegate_create",
                    "node_class": row["node_class"],
                    "blueprint_path": bp,
                    "graph_id": "caller",
                }
                for row in raw_nodes
            ])
            write_jsonl(root / "blueprint_graphs.jsonl", [])
            write_jsonl(root / "blueprint_semantic_edges.jsonl", [])
            write_jsonl(root / "blueprint_execution_blocks.jsonl", [])
            write_jsonl(root / "blueprint_execution_block_edges.jsonl", [])
            write_jsonl(root / "blueprint_pins.jsonl", [
                pin("create-out", create_id, "OutputDelegate", "output", "delegate"),
                pin("bind-in", bind_id, "Delegate", "input", "delegate"),
            ])
            write_jsonl(root / "blueprint_edges.jsonl", [{
                "edge_kind": "data",
                "source_node_id": create_id,
                "source_pin_id": "create-out",
                "source_pin_name": "OutputDelegate",
                "target_node_id": bind_id,
                "target_pin_id": "bind-in",
                "target_pin_name": "Delegate",
            }])
            write_jsonl(root / "blueprint_data_dependencies.jsonl", [])
            write_jsonl(root / "blueprint_functions.jsonl", [
                {
                    "function_id": "fn-do-thing-a",
                    "blueprint_path": bp,
                    "graph_id": "fn-do-thing-a",
                    "graph_name": "DoThing",
                    "name": "DoThing",
                    "resolved_function": "/Game/Test/BP.BP_C:DoThing",
                    "entry_node_id": "",
                    "result_node_ids": [],
                },
                {
                    "function_id": "fn-do-thing-b",
                    "blueprint_path": bp,
                    "graph_id": "fn-do-thing-b",
                    "graph_name": "DoThing",
                    "name": "DoThing",
                    "resolved_function": "/Game/Test/BP.BP_C:DoThing",
                    "entry_node_id": "",
                    "result_node_ids": [],
                },
            ])
            write_jsonl(root / "blueprint_call_edges.jsonl", [])
            write_jsonl(root / "blueprint_call_bindings.jsonl", [])
            write_jsonl(root / "blueprints.jsonl", [{"object_path": bp, "blueprint_type": 0}])
            write_jsonl(root / "blueprint_events.jsonl", [{
                "event_id": "component-event",
                "blueprint_path": bp,
                "graph_id": "caller",
                "graph_name": "EventGraph",
                "node_class": "/Script/BlueprintGraph.K2Node_ComponentBoundEvent",
                "operation": "event",
                "event_kind": "component_bound",
                "name": "OnReadyDelegate",
                "owner": "",
                "component_name": "Target",
                "delegate_name": "OnReadyDelegate",
                "delegate_owner": owner,
                "input_name": "",
                "override_function": False,
                "parameters": [],
                "consume_input": "",
                "execute_when_paused": "",
                "override_parent_binding": "",
            }])
            for name in (
                "blueprint_interprocedural_execution_edges.jsonl",
                "blueprint_interprocedural_execution_terminals.jsonl",
                "blueprint_interprocedural_data_routes.jsonl",
                "blueprint_interprocedural_function_execution_edges.jsonl",
                "blueprint_interprocedural_function_execution_terminals.jsonl",
                "blueprint_interprocedural_function_data_routes.jsonl",
            ):
                write_jsonl(root / name, [])

            delegate_bindings, _delegate_stats = delegates.derive(root, rows)
            write_jsonl(root / "blueprint_delegate_bindings.jsonl", delegate_bindings)
            result = report.build_report(root, rows)

            self.assertEqual(result["delegate_node_count"], 6)
            self.assertEqual(dict(result["delegate_operation_counts"]), {
                "delegate_bind": 1,
                "delegate_call": 1,
                "delegate_clear": 1,
                "delegate_create": 2,
                "delegate_unbind": 1,
            })
            self.assertEqual(result["delegate_dispatcher_node_count"], 4)
            self.assertEqual(result["delegate_exact_dispatcher_identity_count"], 4)
            self.assertEqual(result["delegate_member_guid_count"], 4)
            self.assertEqual(result["delegate_self_context_count"], 4)
            self.assertEqual(result["delegate_external_context_count"], 0)
            self.assertEqual(
                dict(result["delegate_dispatcher_identity_status"]),
                {"exact_owner_and_name": 4},
            )
            self.assertEqual(result["delegate_create_count"], 2)
            self.assertEqual(result["delegate_create_selected_name_count"], 2)
            self.assertEqual(result["delegate_create_selected_guid_count"], 2)
            self.assertEqual(result["delegate_create_exact_endpoint_count"], 2)
            self.assertEqual(
                dict(result["delegate_create_status"]),
                {"exact_function_path": 1, "exact_guid_name_case_variant": 1},
            )
            self.assertEqual(
                dict(result["delegate_create_target_operations"]),
                {"custom_event": 1, "function": 1},
            )
            self.assertEqual(
                dict(result["delegate_create_function_local_resolution"]),
                {"multiple_captured_function_rows": 1},
            )
            self.assertEqual(result["delegate_bind_assign_node_count"], 1)
            self.assertEqual(result["delegate_bind_assign_delegate_input_edge_count"], 1)
            self.assertEqual(result["delegate_create_to_bind_assign_edge_count"], 1)
            self.assertEqual(result["delegate_exact_bound_endpoint_chain_count"], 1)
            self.assertEqual(
                dict(result["delegate_data_source_status"]),
                {"single_create_delegate_source": 1},
            )
            self.assertEqual(
                dict(result["delegate_data_source_operations"]),
                {"delegate_create": 1},
            )
            self.assertEqual(result["delegate_binding_route_count"], 1)
            self.assertEqual(result["delegate_binding_create_route_count"], 1)
            self.assertEqual(result["delegate_binding_direct_route_count"], 0)
            self.assertTrue(result["delegate_binding_alignment"])
            self.assertEqual(
                dict(result["delegate_binding_operation_counts"]),
                {"delegate_bind": 1},
            )
            self.assertEqual(
                dict(result["delegate_binding_basis_counts"]),
                {"selected_guid": 1},
            )
            self.assertEqual(
                dict(result["delegate_binding_endpoint_kinds"]),
                {"custom_event": 1},
            )
            self.assertEqual(result["delegate_component_bound_event_count"], 1)
            self.assertEqual(result["delegate_component_event_exact_identity_count"], 1)
            self.assertEqual(result["delegate_component_event_join_count"], 1)
            self.assertEqual(
                dict(result["delegate_component_event_status"]),
                {"exact_dispatcher_join": 1},
            )
            self.assertEqual(
                dict(result["delegate_call_identity_status"]),
                {"call_identity_has_binding_site": 1},
            )
            self.assertEqual(result["delegate_mismatch_count"], 0)
            self.assertEqual(result["delegate_mismatches"], [])


if __name__ == "__main__":
    unittest.main()
