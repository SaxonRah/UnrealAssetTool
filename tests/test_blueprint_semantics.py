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


class BlueprintSemanticsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> None:
        blueprint = "/Game/Test/BP_Test.BP_Test"
        graph = blueprint + "::graph::EventGraph"
        nodes = [
            {
                "node_id": "event", "blueprint_path": blueprint, "graph_id": graph,
                "graph_name": "EventGraph", "graph_kind": "ubergraph", "graph_system": "k2",
                "node_class": "/Script/BlueprintGraph.K2Node_Event", "operation": "event",
                "symbol": "ReceiveBeginPlay", "owner": "/Script/Engine.Actor",
                "semantic": {"event_name": "ReceiveBeginPlay"},
            },
            {
                "node_id": "get", "blueprint_path": blueprint, "graph_id": graph,
                "graph_name": "EventGraph", "graph_kind": "ubergraph", "graph_system": "k2",
                "node_class": "/Script/BlueprintGraph.K2Node_VariableGet", "operation": "variable_get",
                "symbol": "Health", "owner": "/Game/Test/BP_Test.BP_Test_C", "semantic": {},
            },
            {
                "node_id": "branch", "blueprint_path": blueprint, "graph_id": graph,
                "graph_name": "EventGraph", "graph_kind": "ubergraph", "graph_system": "k2",
                "node_class": "/Script/BlueprintGraph.K2Node_IfThenElse", "operation": "branch",
                "symbol": "", "owner": "", "semantic": {},
            },
            {
                "node_id": "call", "blueprint_path": blueprint, "graph_id": graph,
                "graph_name": "EventGraph", "graph_kind": "ubergraph", "graph_system": "k2",
                "node_class": "/Script/BlueprintGraph.K2Node_CallFunction", "operation": "function_call",
                "symbol": "PrintString", "owner": "/Script/Engine.KismetSystemLibrary",
                "semantic": {
                    "resolved_function": "/Script/Engine.KismetSystemLibrary:PrintString",
                    "pure": False, "latent": False, "interface_call": False,
                },
            },
            {
                "node_id": "unknown", "blueprint_path": blueprint, "graph_id": graph,
                "graph_name": "EventGraph", "graph_kind": "ubergraph", "graph_system": "k2",
                "node_class": "/Script/Test.K2Node_Unknown", "operation": "node",
                "symbol": "", "owner": "", "semantic": {},
            },
        ]
        pins = [
            {"pin_id": "e-out", "node_id": "event", "direction": "output", "type": {"category": "exec"}, "linked_count": 1, "default_value": "", "default_object": "", "default_text": ""},
            {"pin_id": "g-out", "node_id": "get", "direction": "output", "type": {"category": "real"}, "linked_count": 1, "default_value": "", "default_object": "", "default_text": ""},
            {"pin_id": "b-in", "node_id": "branch", "direction": "input", "type": {"category": "exec"}, "linked_count": 1, "default_value": "", "default_object": "", "default_text": ""},
            {"pin_id": "b-cond", "node_id": "branch", "direction": "input", "type": {"category": "real"}, "linked_count": 1, "default_value": "", "default_object": "", "default_text": ""},
            {"pin_id": "b-true", "node_id": "branch", "direction": "output", "type": {"category": "exec"}, "linked_count": 1, "default_value": "", "default_object": "", "default_text": ""},
            {"pin_id": "c-in", "node_id": "call", "direction": "input", "type": {"category": "exec"}, "linked_count": 1, "default_value": "", "default_object": "", "default_text": ""},
            {"pin_id": "c-string", "node_id": "call", "direction": "input", "type": {"category": "string"}, "linked_count": 0, "default_value": "hello", "default_object": "", "default_text": ""},
            {"pin_id": "u-value", "node_id": "unknown", "direction": "input", "type": {"category": "string"}, "linked_count": 0, "default_value": "opaque", "default_object": "", "default_text": ""},
        ]
        edges = [
            {
                "blueprint_path": blueprint, "graph_id": graph, "graph_name": "EventGraph",
                "source_node_id": "event", "source_pin_id": "e-out", "source_pin_name": "then",
                "target_node_id": "branch", "target_pin_id": "b-in", "target_pin_name": "execute",
                "pin_category": "exec", "edge_kind": "execution",
            },
            {
                "blueprint_path": blueprint, "graph_id": graph, "graph_name": "EventGraph",
                "source_node_id": "get", "source_pin_id": "g-out", "source_pin_name": "Health",
                "target_node_id": "branch", "target_pin_id": "b-cond", "target_pin_name": "Condition",
                "pin_category": "real", "edge_kind": "data",
            },
            {
                "blueprint_path": blueprint, "graph_id": graph, "graph_name": "EventGraph",
                "source_node_id": "branch", "source_pin_id": "b-true", "source_pin_name": "then",
                "target_node_id": "call", "target_pin_id": "c-in", "target_pin_name": "execute",
                "pin_category": "exec", "edge_kind": "execution",
            },
        ]
        write_jsonl(self.output / "blueprint_nodes.jsonl", nodes)
        write_jsonl(self.output / "blueprint_pins.jsonl", pins)
        write_jsonl(self.output / "blueprint_edges.jsonl", edges)

    def test_all_nodes_flow_endpoints_coverage_and_sqlite(self) -> None:
        self._fixture()
        nodes, edges, graphs = semantics.derive(self.output, read_rows)
        self.assertEqual(len(nodes), 5)
        self.assertEqual({row["node_id"] for row in nodes}, {"event", "get", "branch", "call", "unknown"})

        by_id = {row["node_id"]: row for row in nodes}
        self.assertEqual(by_id["get"]["semantic_kind"], "symbol_access")
        self.assertEqual(by_id["get"]["primary_effect"], "read")
        self.assertEqual(by_id["get"]["target"], "/Game/Test/BP_Test.BP_Test_C::Health")
        self.assertEqual(by_id["call"]["target"], "/Script/Engine.KismetSystemLibrary:PrintString")
        self.assertEqual(by_id["call"]["literal_input_count"], 1)
        self.assertTrue(by_id["unknown"]["opaque"])

        flow = [edge for edge in edges if edge["target_kind"] == "node"]
        self.assertEqual(len(flow), 3)
        self.assertEqual(
            {edge["relation"] for edge in flow},
            {"controls_execution_of", "provides_value_to"},
        )
        endpoint_relations = {(edge["source_node_id"], edge["relation"], edge["target_kind"], edge["target"]) for edge in edges if edge["target_kind"] != "node"}
        self.assertIn(("get", "reads", "variable", "/Game/Test/BP_Test.BP_Test_C::Health"), endpoint_relations)
        self.assertIn(("call", "calls", "function", "/Script/Engine.KismetSystemLibrary:PrintString"), endpoint_relations)
        self.assertIn(("event", "receives_event", "event", "/Script/Engine.Actor::ReceiveBeginPlay"), endpoint_relations)

        self.assertEqual(len(graphs), 1)
        graph = graphs[0]
        self.assertEqual(graph["node_count"], 5)
        self.assertEqual(graph["classified_node_count"], 4)
        self.assertEqual(graph["opaque_node_count"], 1)
        self.assertAlmostEqual(graph["coverage"], 0.8)
        self.assertEqual(graph["opaque_node_class_counts"], {"/Script/Test.K2Node_Unknown": 1})

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

        conn = sqlite3.connect(":memory:")
        try:
            semantics.create_schema(conn)
            semantics.load_database(conn, self.output, read_rows)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM blueprint_semantic_nodes").fetchone()[0], 5)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM blueprint_semantic_edges").fetchone()[0], len(edges))
            self.assertEqual(conn.execute("SELECT opaque_node_count FROM blueprint_semantic_graphs").fetchone()[0], 1)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
