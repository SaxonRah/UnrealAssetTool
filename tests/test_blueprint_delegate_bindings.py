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

import uatool_blueprint_delegates as delegates


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


def pin(pin_id: str, node_id: str, name: str, direction: str, category: str = "delegate") -> dict:
    return {
        "pin_id": pin_id,
        "node_id": node_id,
        "blueprint_path": "/Game/Test/BP.BP",
        "graph_id": "graph",
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


class BlueprintDelegateBindingsTest(unittest.TestCase):
    def test_exact_event_function_and_direct_event_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bp = "/Game/Test/BP.BP"
            owner = "/Game/Test/BP_Target.BP_Target_C"
            event_guid = "11111111-2222-3333-4444-555555555555"
            event_id = f"{bp}::graph::graph::node::{event_guid}"
            direct_event_id = f"{bp}::graph::graph::node::22222222-3333-4444-5555-666666666666"
            create_event_id = f"{bp}::graph::graph::node::33333333-4444-5555-6666-777777777777"
            create_function_id = f"{bp}::graph::graph::node::44444444-5555-6666-7777-888888888888"
            bind_event_id = f"{bp}::graph::graph::node::55555555-6666-7777-8888-999999999999"
            bind_function_id = f"{bp}::graph::graph::node::66666666-7777-8888-9999-aaaaaaaaaaaa"
            assign_direct_id = f"{bp}::graph::graph::node::77777777-8888-9999-aaaa-bbbbbbbbbbbb"

            dispatcher_guid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
            nodes = [
                {
                    "node_id": event_id,
                    "blueprint_path": bp,
                    "graph_id": "graph",
                    "operation": "custom_event",
                    "symbol": "OnEvent",
                    "semantic": {},
                },
                {
                    "node_id": direct_event_id,
                    "blueprint_path": bp,
                    "graph_id": "graph",
                    "operation": "custom_event",
                    "symbol": "OnDirect",
                    "semantic": {},
                },
                {
                    "node_id": create_event_id,
                    "blueprint_path": bp,
                    "graph_id": "graph",
                    "operation": "delegate_create",
                    "symbol": "OnEvent",
                    "semantic": {
                        "selected_function": "OnEvent",
                        "selected_function_guid": event_guid,
                    },
                },
                {
                    "node_id": create_function_id,
                    "blueprint_path": bp,
                    "graph_id": "graph",
                    "operation": "delegate_create",
                    "symbol": "HandleFunction",
                    "semantic": {
                        "selected_function": "HandleFunction",
                        "selected_function_guid": "99999999-8888-7777-6666-555555555555",
                        "selected_function_path": "/Game/Test/BP.BP_C:HandleFunction",
                    },
                },
            ]
            for node_id, operation, name in (
                (bind_event_id, "delegate_bind", "OnEventDelegate"),
                (bind_function_id, "delegate_bind", "OnFunctionDelegate"),
                (assign_direct_id, "delegate_assign", "OnDirectDelegate"),
            ):
                nodes.append({
                    "node_id": node_id,
                    "blueprint_path": bp,
                    "graph_id": "graph",
                    "operation": operation,
                    "symbol": name,
                    "semantic": {
                        "delegate_name": name,
                        "delegate_owner": owner,
                        "delegate_member_guid": dispatcher_guid,
                        "delegate_self_context": False,
                        "delegate_local_scope": False,
                        "delegate_member_scope": "",
                    },
                })
            write_jsonl(root / "blueprint_nodes.jsonl", nodes)
            write_jsonl(root / "blueprint_functions.jsonl", [{
                "function_id": "fn-handle",
                "blueprint_path": bp,
                "name": "HandleFunction",
                "resolved_function": "/Game/Test/BP.BP_C:HandleFunction",
            }])
            write_jsonl(root / "blueprint_pins.jsonl", [
                pin("create-event-out", create_event_id, "OutputDelegate", "output"),
                pin("create-function-out", create_function_id, "OutputDelegate", "output"),
                pin("direct-event-out", direct_event_id, "OutputDelegate", "output"),
                pin("bind-event-in", bind_event_id, "Delegate", "input"),
                pin("bind-function-in", bind_function_id, "Delegate", "input"),
                pin("assign-direct-in", assign_direct_id, "Delegate", "input"),
            ])
            write_jsonl(root / "blueprint_edges.jsonl", [
                {
                    "edge_kind": "data",
                    "source_node_id": create_event_id,
                    "source_pin_id": "create-event-out",
                    "source_pin_name": "OutputDelegate",
                    "target_node_id": bind_event_id,
                    "target_pin_id": "bind-event-in",
                    "target_pin_name": "Delegate",
                },
                {
                    "edge_kind": "data",
                    "source_node_id": create_function_id,
                    "source_pin_id": "create-function-out",
                    "source_pin_name": "OutputDelegate",
                    "target_node_id": bind_function_id,
                    "target_pin_id": "bind-function-in",
                    "target_pin_name": "Delegate",
                },
                {
                    "edge_kind": "data",
                    "source_node_id": direct_event_id,
                    "source_pin_id": "direct-event-out",
                    "source_pin_name": "OutputDelegate",
                    "target_node_id": assign_direct_id,
                    "target_pin_id": "assign-direct-in",
                    "target_pin_name": "Delegate",
                },
            ])

            bindings, stats = delegates.derive(root, rows)
            self.assertEqual(len(bindings), 3)
            self.assertEqual(stats["bindings"], 3)
            self.assertEqual(stats["operation:delegate_bind"], 2)
            self.assertEqual(stats["operation:delegate_assign"], 1)
            self.assertEqual(stats["create_delegate_sources"], 2)
            self.assertEqual(stats["direct_event_sources"], 1)
            self.assertEqual(stats["basis:selected_guid"], 1)
            self.assertEqual(stats["basis:selected_function_path"], 1)
            self.assertEqual(stats["basis:direct_event_node"], 1)

            by_basis = {row["resolution_basis"]: row for row in bindings}
            self.assertEqual(by_basis["selected_guid"]["endpoint_kind"], "custom_event")
            self.assertEqual(by_basis["selected_guid"]["endpoint_id"], event_id)
            self.assertEqual(by_basis["selected_function_path"]["endpoint_kind"], "function")
            self.assertEqual(
                by_basis["selected_function_path"]["endpoint_path"],
                "/Game/Test/BP.BP_C:HandleFunction",
            )
            self.assertEqual(by_basis["direct_event_node"]["endpoint_name"], "OnDirect")
            self.assertTrue(all(row["evidence_kind"] == "exact_authored_delegate_binding" for row in bindings))

            write_jsonl(root / delegates.DERIVED_FILES[0], bindings)
            self.assertIsNone(delegates.validation_error(root, rows))

            conn = sqlite3.connect(":memory:")
            try:
                delegates.create_schema(conn)
                delegates.load_database(conn, root, rows)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM blueprint_delegate_bindings").fetchone()[0],
                    3,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT endpoint_kind,resolution_basis FROM blueprint_delegate_bindings "
                        "WHERE dispatcher_name='OnFunctionDelegate'"
                    ).fetchone(),
                    ("function", "selected_function_path"),
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
