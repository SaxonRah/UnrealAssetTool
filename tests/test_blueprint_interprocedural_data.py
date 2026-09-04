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


def write_jsonl(path: Path, values: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


def data_pin(
    pin_id: str,
    node_id: str,
    blueprint_path: str,
    graph_id: str,
    name: str,
    direction: str,
    *,
    default_value: str = "",
) -> dict:
    return {
        "pin_id": pin_id,
        "node_id": node_id,
        "blueprint_path": blueprint_path,
        "graph_id": graph_id,
        "graph_name": "EventGraph" if graph_id == "caller" else "Macro",
        "pin_index": 0,
        "name": name,
        "direction": direction,
        "type": {
            "category": "float",
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


class BlueprintInterproceduralDataRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.caller_bp = "/Game/Test/BP_User.BP_User"
        self.macro_bp = "/Game/Test/BPL.BPL"
        self.macro_node = "macro"
        self.macro_graph = "macro-graph"
        self._write_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        write_jsonl(self.output / "blueprint_semantic_edges.jsonl", [
            {
                "source_node_id": self.macro_node,
                "relation": "maps_to_macro_graph",
                "target_kind": "blueprint_graph",
                "target": self.macro_graph,
                "source_pin_id": "",
                "target_pin_id": "",
                "pin_category": "",
            },
            {
                "source_node_id": self.macro_node,
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
                "source_node_id": self.macro_node,
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
                "source_node_id": self.macro_node,
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
        write_jsonl(self.output / "blueprint_pins.jsonl", [
            data_pin("macro-value", "macro", self.caller_bp, "caller", "Value", "input"),
            data_pin(
                "macro-defaulted", "macro", self.caller_bp, "caller",
                "Defaulted", "input", default_value="1.0",
            ),
            data_pin("macro-result", "macro", self.caller_bp, "caller", "Result", "output"),
            data_pin("source-out", "source", self.caller_bp, "caller", "Value", "output"),
            data_pin("caller-consumer-in", "caller-consumer", self.caller_bp, "caller", "Value", "input"),
            data_pin("entry-value", "entry", self.macro_bp, self.macro_graph, "Value", "output"),
            data_pin(
                "entry-defaulted", "entry", self.macro_bp, self.macro_graph,
                "Defaulted", "output",
            ),
            data_pin("body-value-in", "body-value", self.macro_bp, self.macro_graph, "Value", "input"),
            data_pin(
                "body-defaulted-in", "body-defaulted", self.macro_bp, self.macro_graph,
                "Defaulted", "input",
            ),
            data_pin("internal-out", "internal", self.macro_bp, self.macro_graph, "Result", "output"),
            data_pin("exit-result", "exit", self.macro_bp, self.macro_graph, "Result", "input"),
        ])
        write_jsonl(self.output / "blueprint_edges.jsonl", [
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
                "target_node_id": "body-value",
                "target_pin_id": "body-value-in",
                "target_pin_name": "Value",
            },
            {
                "edge_kind": "data",
                "source_node_id": "entry",
                "source_pin_id": "entry-defaulted",
                "source_pin_name": "Defaulted",
                "target_node_id": "body-defaulted",
                "target_pin_id": "body-defaulted-in",
                "target_pin_name": "Defaulted",
            },
            {
                "edge_kind": "data",
                "source_node_id": "internal",
                "source_pin_id": "internal-out",
                "source_pin_name": "Result",
                "target_node_id": "exit",
                "target_pin_id": "exit-result",
                "target_pin_name": "Result",
            },
            {
                "edge_kind": "data",
                "source_node_id": "macro",
                "source_pin_id": "macro-result",
                "source_pin_name": "Result",
                "target_node_id": "caller-consumer",
                "target_pin_id": "caller-consumer-in",
                "target_pin_name": "Value",
            },
        ])
        write_jsonl(self.output / "blueprint_data_dependencies.jsonl", [{
            "dependency_id": "dep-output",
            "sink_node_id": "exit",
            "sink_pin_id": "exit-result",
            "sink_pin_name": "Result",
            "source_count": 1,
            "truncated": False,
            "cycle": False,
            "text": "Internal.Result",
        }])
        write_jsonl(self.output / "blueprint_execution_blocks.jsonl", [])

    def test_materializes_one_route_per_exact_data_binding(self) -> None:
        edges, terminals, routes = interproc.derive(self.output, rows)
        self.assertEqual(edges, [])
        self.assertEqual(terminals, [])
        self.assertEqual(len(routes), 3)
        self.assertEqual(interproc.INTERPROCEDURAL_SCHEMA_VERSION, 4)

        by_pin = {row["call_pin_id"]: row for row in routes}

        connected = by_pin["macro-value"]
        self.assertEqual(connected["route_kind"], "macro_data_input")
        self.assertEqual(connected["value_kind"], "connected_source")
        self.assertEqual(connected["caller_source_count"], 1)
        self.assertEqual(connected["body_consumer_count"], 1)
        self.assertTrue(connected["bridge_ready"])
        self.assertEqual(connected["caller_sources"][0]["pin_id"], "source-out")
        self.assertEqual(connected["body_consumers"][0]["pin_id"], "body-value-in")

        defaulted = by_pin["macro-defaulted"]
        self.assertEqual(defaulted["value_kind"], "authored_value")
        self.assertEqual(defaulted["caller_source_count"], 0)
        self.assertEqual(defaulted["body_consumer_count"], 1)
        self.assertEqual(defaulted["authored_default_value"], "1.0")
        self.assertTrue(defaulted["bridge_ready"])

        output = by_pin["macro-result"]
        self.assertEqual(output["route_kind"], "macro_data_output")
        self.assertEqual(output["value_kind"], "derived_output")
        self.assertEqual(output["internal_source_count"], 1)
        self.assertEqual(output["dependency_count"], 1)
        self.assertEqual(output["caller_consumer_count"], 1)
        self.assertEqual(output["internal_sources"][0]["pin_id"], "internal-out")
        self.assertEqual(output["dependencies"][0]["dependency_id"], "dep-output")
        self.assertEqual(output["caller_consumers"][0]["pin_id"], "caller-consumer-in")
        self.assertTrue(output["bridge_ready"])

        write_jsonl(self.output / interproc.DERIVED_FILES[0], edges)
        write_jsonl(self.output / interproc.DERIVED_FILES[1], terminals)
        write_jsonl(self.output / interproc.DERIVED_FILES[2], routes)
        write_jsonl(self.output / interproc.DERIVED_FILES[3], [])
        write_jsonl(self.output / interproc.DERIVED_FILES[4], [])
        write_jsonl(self.output / interproc.DERIVED_FILES[5], [])
        self.assertIsNone(interproc.validation_error(self.output, rows))

    def test_validation_rejects_changed_route_provenance(self) -> None:
        edges, terminals, routes = interproc.derive(self.output, rows)
        routes[0]["bridge_ready"] = False
        write_jsonl(self.output / interproc.DERIVED_FILES[0], edges)
        write_jsonl(self.output / interproc.DERIVED_FILES[1], terminals)
        write_jsonl(self.output / interproc.DERIVED_FILES[2], routes)
        write_jsonl(self.output / interproc.DERIVED_FILES[3], [])
        write_jsonl(self.output / interproc.DERIVED_FILES[4], [])
        write_jsonl(self.output / interproc.DERIVED_FILES[5], [])
        self.assertIn(
            "data routes do not exactly match",
            str(interproc.validation_error(self.output, rows)),
        )

    def test_sqlite_round_trip(self) -> None:
        edges, terminals, routes = interproc.derive(self.output, rows)
        write_jsonl(self.output / interproc.DERIVED_FILES[0], edges)
        write_jsonl(self.output / interproc.DERIVED_FILES[1], terminals)
        write_jsonl(self.output / interproc.DERIVED_FILES[2], routes)
        write_jsonl(self.output / interproc.DERIVED_FILES[3], [])
        write_jsonl(self.output / interproc.DERIVED_FILES[4], [])
        write_jsonl(self.output / interproc.DERIVED_FILES[5], [])

        conn = sqlite3.connect(":memory:")
        try:
            interproc.create_schema(conn)
            interproc.load_database(conn, self.output, rows)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blueprint_interprocedural_data_routes"
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT route_kind,value_kind,caller_source_count,body_consumer_count,bridge_ready "
                    "FROM blueprint_interprocedural_data_routes WHERE call_pin_id='macro-value'"
                ).fetchone(),
                ("macro_data_input", "connected_source", 1, 1, 1),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT route_kind,internal_source_count,dependency_count,caller_consumer_count,bridge_ready "
                    "FROM blueprint_interprocedural_data_routes WHERE call_pin_id='macro-result'"
                ).fetchone(),
                ("macro_data_output", 1, 1, 1, 1),
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
