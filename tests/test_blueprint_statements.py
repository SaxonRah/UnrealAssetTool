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

import uatool_blueprint_statements as statements


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


class BlueprintStatementsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> None:
        bp = "/Game/BP_Test.BP_Test"
        graph = "graph:test"
        semantic_nodes = [
            {
                "node_id": "entry", "blueprint_path": bp, "graph_id": graph, "graph_name": "Test",
                "operation": "function_entry", "semantic_kind": "boundary", "primary_effect": "control",
                "symbol": "DoThing", "owner": bp, "target_kind": "function", "target": bp + "::DoThing",
                "has_exec_flow": True,
            },
            {
                "node_id": "pure", "blueprint_path": bp, "graph_id": graph, "graph_name": "Test",
                "operation": "variable_get", "semantic_kind": "symbol_access", "primary_effect": "read",
                "symbol": "IsReady", "owner": bp, "target_kind": "variable", "target": bp + "::IsReady",
                "has_exec_flow": False,
            },
            {
                "node_id": "branch", "blueprint_path": bp, "graph_id": graph, "graph_name": "Test",
                "operation": "branch", "semantic_kind": "control", "primary_effect": "branch",
                "symbol": "", "owner": "", "target_kind": "", "target": "", "has_exec_flow": True,
            },
            {
                "node_id": "set", "blueprint_path": bp, "graph_id": graph, "graph_name": "Test",
                "operation": "variable_set", "semantic_kind": "symbol_access", "primary_effect": "write",
                "symbol": "Health", "owner": bp, "target_kind": "variable", "target": bp + "::Health",
                "has_exec_flow": True,
            },
        ]
        write_jsonl(self.output / "blueprint_semantic_nodes.jsonl", semantic_nodes)

        def pin(pin_id: str, node_id: str, name: str, direction: str, category: str, default: str = "") -> dict:
            return {
                "pin_id": pin_id, "node_id": node_id, "blueprint_path": bp, "graph_id": graph,
                "graph_name": "Test", "pin_index": 0, "name": name, "direction": direction,
                "type": {"category": category, "subcategory": "", "container_type": 0,
                         "is_reference": False, "is_const": False, "subcategory_object": ""},
                "default_value": default, "default_object": "", "default_text": "",
                "hidden": False, "not_connectable": False, "linked_count": 1 if name in {"Condition", "Health"} else 0,
            }

        write_jsonl(self.output / "blueprint_pins.jsonl", [
            pin("entry-out", "entry", "then", "output", "exec"),
            pin("branch-in", "branch", "execute", "input", "exec"),
            pin("branch-cond", "branch", "Condition", "input", "bool"),
            pin("branch-true", "branch", "then", "output", "exec"),
            pin("set-in", "set", "execute", "input", "exec"),
            pin("set-value", "set", "Health", "input", "real"),
            pin("set-notify", "set", "Notify", "input", "bool", "true"),
            pin("set-out", "set", "then", "output", "exec"),
        ])

        write_jsonl(self.output / "blueprint_data_dependencies.jsonl", [
            {
                "dependency_id": "dep-cond", "sink_node_id": "branch", "sink_pin_id": "branch-cond",
                "text": "IsReady", "expression_node_count": 1, "truncated": False, "cycle": False,
            },
            {
                "dependency_id": "dep-health", "sink_node_id": "set", "sink_pin_id": "set-value",
                "text": "ComputeHealth(CurrentHealth=Health)", "expression_node_count": 2,
                "truncated": False, "cycle": False,
            },
        ])
        write_jsonl(self.output / "blueprint_execution_blocks.jsonl", [
            {
                "block_id": "b0", "blueprint_path": bp, "graph_id": graph, "graph_name": "Test",
                "block_index": 0, "node_count": 2, "node_ids": ["entry", "branch"],
            },
            {
                "block_id": "b1", "blueprint_path": bp, "graph_id": graph, "graph_name": "Test",
                "block_index": 1, "node_count": 1, "node_ids": ["set"],
            },
        ])
        write_jsonl(self.output / "blueprint_execution_block_edges.jsonl", [
            {"source_block_id": "b0", "target_block_id": "b1"},
        ])

    def test_statements_join_dependencies_literals_blocks_and_sqlite(self) -> None:
        self._fixture()
        statement_rows, block_rows = statements.derive(self.output, read_rows)
        write_jsonl(self.output / "blueprint_semantic_statements.jsonl", statement_rows)
        write_jsonl(self.output / "blueprint_semantic_blocks.jsonl", block_rows)

        self.assertEqual([row["node_id"] for row in statement_rows], ["entry", "branch", "set"])
        by_node = {row["node_id"]: row for row in statement_rows}
        self.assertEqual(by_node["branch"]["text"], "if IsReady")
        self.assertEqual(by_node["branch"]["dependency_ids"], ["dep-cond"])
        self.assertIn("ComputeHealth(CurrentHealth=Health)", by_node["set"]["text"])
        self.assertEqual(by_node["set"]["literal_count"], 1)
        self.assertEqual(by_node["set"]["block_id"], "b1")
        self.assertEqual(by_node["set"]["block_position"], 0)

        self.assertEqual(len(block_rows), 2)
        block_by_id = {row["block_id"]: row for row in block_rows}
        self.assertEqual(block_by_id["b0"]["statement_count"], 2)
        self.assertEqual(block_by_id["b0"]["branch_count"], 1)
        self.assertEqual(block_by_id["b1"]["write_count"], 1)
        self.assertIsNone(statements.validation_error(self.output, read_rows))

        conn = sqlite3.connect(":memory:")
        try:
            statements.create_schema(conn)
            statements.load_database(conn, self.output, read_rows)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM blueprint_semantic_statements").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM blueprint_semantic_blocks").fetchone()[0], 2)
            self.assertEqual(
                conn.execute("SELECT text FROM blueprint_semantic_statements WHERE node_id='branch'").fetchone()[0],
                "if IsReady",
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
