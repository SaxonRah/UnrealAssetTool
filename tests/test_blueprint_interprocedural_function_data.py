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

import uatool_blueprint_interprocedural as interproc
import uatool_core as core


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


def ptype(category: str = "float", *, object_path: str = "") -> dict:
    return {
        "category": category,
        "subcategory": "",
        "subcategory_object": object_path,
        "container_type": 0,
        "is_reference": False,
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
        "blueprint_path": "/Game/Test/BP_Caller.BP_Caller",
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


class BlueprintFunctionDataRoutesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.caller = "/Game/Test/BP_Caller.BP_Caller"
        self.target = "/Game/Test/BP_Target.BP_Target"
        self.interface = "/Game/Test/BPI_Target.BPI_Target"
        self.struct_path = "/Script/Test.Config"
        self._fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> None:
        write_jsonl(self.output / "blueprints.jsonl", [
            {"object_path": self.caller, "blueprint_type": 0},
            {"object_path": self.target, "blueprint_type": 0},
            {"object_path": self.interface, "blueprint_type": 3},
        ])
        write_jsonl(self.output / "blueprint_functions.jsonl", [
            {
                "function_id": "fn",
                "blueprint_path": self.target,
                "blueprint_pure": True,
                "entry_node_id": "entry",
                "result_node_ids": ["result"],
            },
            {
                "function_id": "fn-interface",
                "blueprint_path": self.interface,
                "blueprint_pure": False,
                "entry_node_id": "entry-interface",
                "result_node_ids": [],
            },
            {
                "function_id": "fn-latent",
                "blueprint_path": self.target,
                "blueprint_pure": False,
                "entry_node_id": "entry-latent",
                "result_node_ids": [],
            },
        ])
        write_jsonl(self.output / "blueprint_call_edges.jsonl", [
            {
                "call_id": "call",
                "call_node_id": "call",
                "blueprint_path": self.caller,
                "graph_id": "caller",
                "target_blueprint_path": self.target,
                "target_function_id": "fn",
                "resolution": "internal",
                "pure": True,
                "latent": False,
                "interface_call": False,
            },
            {
                "call_id": "call-interface",
                "call_node_id": "call-interface",
                "blueprint_path": self.caller,
                "graph_id": "caller",
                "target_blueprint_path": self.interface,
                "target_function_id": "fn-interface",
                "resolution": "internal",
                "pure": False,
                "latent": False,
                "interface_call": True,
            },
            {
                "call_id": "call-latent",
                "call_node_id": "call-latent",
                "blueprint_path": self.caller,
                "graph_id": "caller",
                "target_blueprint_path": self.target,
                "target_function_id": "fn-latent",
                "resolution": "internal",
                "pure": False,
                "latent": True,
                "interface_call": False,
            },
        ])

        float_type = ptype()
        struct_type = ptype("struct", object_path=self.struct_path)
        write_jsonl(self.output / "blueprint_pins.jsonl", [
            pin("source", "source-node", "caller", "Value", "output", float_type),
            pin("call-value", "call", "caller", "Value", "input", float_type),
            pin("call-speed", "call", "caller", "Config_Speed", "input", float_type, default_value="2.0"),
            pin("call-result", "call", "caller", "Result", "output", float_type),
            pin("caller-result", "consumer", "caller", "Value", "input", float_type),
            pin("entry-value", "entry", "fn", "Value", "output", float_type),
            pin("entry-config", "entry", "fn", "Config", "output", struct_type),
            pin("body-value", "body-value", "fn", "Value", "input", float_type),
            pin("body-config", "body-config", "fn", "Config", "input", struct_type),
            pin("result-value", "result", "fn", "Result", "input", float_type),
            pin("interface-value", "call-interface", "caller", "Value", "input", float_type, default_value="1.0"),
            pin("entry-interface-value", "entry-interface", "fn-interface", "Value", "output", float_type),
            pin("latent-value", "call-latent", "caller", "Value", "input", float_type, default_value="1.0"),
            pin("entry-latent-value", "entry-latent", "fn-latent", "Value", "output", float_type),
        ])
        write_jsonl(self.output / "blueprint_edges.jsonl", [
            {
                "edge_kind": "data",
                "source_node_id": "source-node",
                "source_pin_id": "source",
                "source_pin_name": "Value",
                "target_node_id": "call",
                "target_pin_id": "call-value",
                "target_pin_name": "Value",
            },
            {
                "edge_kind": "data",
                "source_node_id": "entry",
                "source_pin_id": "entry-value",
                "source_pin_name": "Value",
                "target_node_id": "body-value",
                "target_pin_id": "body-value",
                "target_pin_name": "Value",
            },
            {
                "edge_kind": "data",
                "source_node_id": "entry",
                "source_pin_id": "entry-config",
                "source_pin_name": "Config",
                "target_node_id": "body-config",
                "target_pin_id": "body-config",
                "target_pin_name": "Config",
            },
            {
                "edge_kind": "data",
                "source_node_id": "call",
                "source_pin_id": "call-result",
                "source_pin_name": "Result",
                "target_node_id": "consumer",
                "target_pin_id": "caller-result",
                "target_pin_name": "Value",
            },
        ])
        write_jsonl(self.output / "blueprint_data_dependencies.jsonl", [
            {
                "dependency_id": "dep-call",
                "sink_node_id": "call",
                "sink_pin_id": "call-value",
                "sink_pin_name": "Value",
                "source_count": 1,
                "text": "Source.Value",
            },
            {
                "dependency_id": "dep-result",
                "sink_node_id": "result",
                "sink_pin_id": "result-value",
                "sink_pin_name": "Result",
                "source_count": 1,
                "text": "Body.Result",
            },
        ])

        def binding(
            binding_id: str,
            call_node_id: str,
            target_function_id: str,
            direction: str,
            call_pin_id: str,
            call_pin_name: str,
            parameter_name: str,
            parameter_pin_ids: list[str],
            *,
            match_kind: str = "exact",
            identity_kind: str = "exact_parameter",
            member_exact: bool = True,
            split_suffix: str = "",
            dependency_ids: list[str] | None = None,
        ) -> dict:
            return {
                "schema_version": core.BLUEPRINT_CALL_BINDING_SCHEMA_VERSION,
                "binding_id": binding_id,
                "call_id": call_node_id,
                "call_node_id": call_node_id,
                "caller_blueprint_path": self.caller,
                "caller_graph_id": "caller",
                "caller_function_id": "",
                "target_blueprint_path": (
                    self.interface if target_function_id == "fn-interface" else self.target
                ),
                "target_function_id": target_function_id,
                "direction": direction,
                "call_pin_id": call_pin_id,
                "call_pin_name": call_pin_name,
                "parameter_name": parameter_name,
                "parameter_pin_ids": parameter_pin_ids,
                "match_kind": match_kind,
                "split_suffix": split_suffix,
                "parameter_identity_kind": identity_kind,
                "member_identity_exact": member_exact,
                "call_pin_type": float_type,
                "parameter_type": float_type,
                "parameter_pin_types": [float_type],
                "value_type_compatible": True,
                "value_type_basis": (
                    "call_signature_parameter_pin"
                    if match_kind == "exact"
                    else "signature_parent_parameter_pin"
                ),
                "qualifier_surfaces": {
                    "call_pin": {"is_reference": False, "is_const": False},
                    "signature": {"is_reference": False, "is_const": False},
                    "parameter_pins": [{"is_reference": False, "is_const": False}],
                },
                "dependency_ids": dependency_ids or [],
                "consumer_pin_ids": [],
            }

        split = binding(
            "b-speed", "call", "fn", "argument", "call-speed", "Config_Speed",
            "Config", ["entry-config"],
            match_kind="split_struct",
            identity_kind="split_parent_projection",
            member_exact=False,
            split_suffix="Speed",
        )
        split["parameter_type"] = struct_type
        split["parameter_pin_types"] = [struct_type]

        write_jsonl(self.output / "blueprint_call_bindings.jsonl", [
            binding(
                "b-value", "call", "fn", "argument", "call-value", "Value",
                "Value", ["entry-value"], dependency_ids=["dep-call"],
            ),
            split,
            binding(
                "b-result", "call", "fn", "return", "call-result", "Result",
                "Result", ["result-value"], dependency_ids=["dep-result"],
            ),
            binding(
                "b-interface", "call-interface", "fn-interface", "argument",
                "interface-value", "Value", "Value", ["entry-interface-value"],
            ),
            binding(
                "b-latent", "call-latent", "fn-latent", "argument",
                "latent-value", "Value", "Value", ["entry-latent-value"],
            ),
        ])

        write_jsonl(self.output / "blueprint_semantic_edges.jsonl", [])
        write_jsonl(self.output / "blueprint_execution_blocks.jsonl", [])
        write_jsonl(self.output / "blueprint_execution_block_edges.jsonl", [])
        for index in range(5):
            write_jsonl(self.output / interproc.DERIVED_FILES[index], [])

    def test_routes_preserve_exact_members_and_split_parent_projection(self) -> None:
        routes, stats = interproc.derive_function_data_routes(self.output, rows)
        self.assertEqual(interproc.INTERPROCEDURAL_SCHEMA_VERSION, 4)
        self.assertEqual(len(routes), 3)
        self.assertEqual(stats["excluded_interface"], 1)
        self.assertEqual(stats["excluded_latent"], 1)
        self.assertEqual(stats["pure_internal"], 3)
        self.assertEqual(stats["function_argument"], 2)
        self.assertEqual(stats["function_return"], 1)
        self.assertEqual(stats["boundary_ready"], 3)
        self.assertEqual(stats["member_route_ready"], 2)

        by_binding = {row["binding_id"]: row for row in routes}

        argument = by_binding["b-value"]
        self.assertEqual(argument["route_kind"], "function_argument")
        self.assertEqual(argument["value_kind"], "connected_source")
        self.assertEqual(argument["caller_source_count"], 1)
        self.assertEqual(argument["callee_consumer_count"], 1)
        self.assertTrue(argument["boundary_ready"])
        self.assertTrue(argument["member_route_ready"])

        split = by_binding["b-speed"]
        self.assertEqual(split["parameter_identity_kind"], "split_parent_projection")
        self.assertFalse(split["member_identity_exact"])
        self.assertEqual(split["split_suffix"], "Speed")
        self.assertEqual(split["value_kind"], "authored_value")
        self.assertEqual(split["callee_consumer_scope"], "parent_parameter_projection")
        self.assertEqual(split["callee_consumer_count"], 1)
        self.assertTrue(split["boundary_ready"])
        self.assertFalse(split["member_route_ready"])

        result = by_binding["b-result"]
        self.assertEqual(result["route_kind"], "function_return")
        self.assertEqual(result["value_kind"], "derived_output")
        self.assertEqual(result["dependency_count"], 1)
        self.assertEqual(result["caller_consumer_count"], 1)
        self.assertTrue(result["internal_provenance_complete"])
        self.assertTrue(result["member_route_ready"])

    def test_validation_and_sqlite_round_trip(self) -> None:
        routes, _stats = interproc.derive_function_data_routes(self.output, rows)
        write_jsonl(self.output / interproc.DERIVED_FILES[5], routes)
        self.assertIsNone(interproc.validation_error(self.output, rows))

        conn = sqlite3.connect(":memory:")
        try:
            interproc.create_schema(conn)
            interproc.load_database(conn, self.output, rows)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blueprint_interprocedural_function_data_routes"
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT parameter_identity_kind,boundary_ready,member_route_ready "
                    "FROM blueprint_interprocedural_function_data_routes "
                    "WHERE binding_id='b-speed'"
                ).fetchone(),
                ("split_parent_projection", 1, 0),
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
