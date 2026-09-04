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


def exec_pin(
    pin_id: str,
    node_id: str,
    blueprint_path: str,
    graph_id: str,
    graph_name: str,
    name: str,
    direction: str,
) -> dict:
    return {
        "pin_id": pin_id,
        "node_id": node_id,
        "blueprint_path": blueprint_path,
        "graph_id": graph_id,
        "graph_name": graph_name,
        "pin_index": 0,
        "name": name,
        "direction": direction,
        "type": {
            "category": "exec",
            "subcategory": "",
            "container_type": 0,
            "is_reference": False,
            "is_const": False,
            "subcategory_object": "",
        },
        "default_value": "",
        "default_object": "",
        "default_text": "",
        "hidden": False,
        "not_connectable": False,
        "linked_count": 0,
    }


class BlueprintInterproceduralExecutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.caller_bp = "/Game/Test/BP_User.BP_User"
        self.macro_bp = "/Game/Test/BPL.BPL"
        self.caller_graph = "caller-graph"
        self.macro_graph = "macro-graph"
        self.macro_node = "macro-instance"
        self.entry_node = "entry"
        self.exit_node = "exit"
        self.next_node = "next"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        write_jsonl(self.output / "blueprint_pins.jsonl", [
            exec_pin(
                "macro-in", self.macro_node, self.caller_bp, self.caller_graph,
                "EventGraph", "execute", "input",
            ),
            exec_pin(
                "macro-then", self.macro_node, self.caller_bp, self.caller_graph,
                "EventGraph", "then", "output",
            ),
            exec_pin(
                "macro-failed", self.macro_node, self.caller_bp, self.caller_graph,
                "EventGraph", "Failed", "output",
            ),
            exec_pin(
                "entry-exec", self.entry_node, self.macro_bp, self.macro_graph,
                "Macro", "execute", "output",
            ),
            exec_pin(
                "exit-then", self.exit_node, self.macro_bp, self.macro_graph,
                "Macro", "then", "input",
            ),
            exec_pin(
                "exit-failed", self.exit_node, self.macro_bp, self.macro_graph,
                "Macro", "Failed", "input",
            ),
            exec_pin(
                "next-in", self.next_node, self.caller_bp, self.caller_graph,
                "EventGraph", "execute", "input",
            ),
        ])
        write_jsonl(self.output / "blueprint_execution_blocks.jsonl", [
            {
                "block_id": "caller-block",
                "blueprint_path": self.caller_bp,
                "graph_id": self.caller_graph,
                "graph_name": "EventGraph",
                "node_ids": [self.macro_node],
            },
            {
                "block_id": "entry-block",
                "blueprint_path": self.macro_bp,
                "graph_id": self.macro_graph,
                "graph_name": "Macro",
                "node_ids": [self.entry_node],
            },
            {
                "block_id": "exit-block",
                "blueprint_path": self.macro_bp,
                "graph_id": self.macro_graph,
                "graph_name": "Macro",
                "node_ids": [self.exit_node],
            },
            {
                "block_id": "next-block",
                "blueprint_path": self.caller_bp,
                "graph_id": self.caller_graph,
                "graph_name": "EventGraph",
                "node_ids": [self.next_node],
            },
        ])
        write_jsonl(self.output / "blueprint_semantic_edges.jsonl", [
            {
                "source_node_id": self.macro_node,
                "relation": "maps_to_macro_graph",
                "target_kind": "blueprint_graph",
                "target": self.macro_graph,
                "source_pin_id": "",
                "target_pin_id": "",
                "source_pin_name": "",
                "target_pin_name": "",
                "pin_category": "",
            },
            {
                "source_node_id": self.macro_node,
                "relation": "binds_macro_input",
                "target_kind": "blueprint_pin",
                "target": "entry-exec",
                "source_pin_id": "macro-in",
                "target_pin_id": "entry-exec",
                "source_pin_name": "execute",
                "target_pin_name": "execute",
                "pin_category": "exec",
            },
            {
                "source_node_id": self.macro_node,
                "relation": "binds_macro_output",
                "target_kind": "blueprint_pin",
                "target": "exit-then",
                "source_pin_id": "macro-then",
                "target_pin_id": "exit-then",
                "source_pin_name": "then",
                "target_pin_name": "then",
                "pin_category": "exec",
            },
            {
                "source_node_id": self.macro_node,
                "relation": "binds_macro_output",
                "target_kind": "blueprint_pin",
                "target": "exit-failed",
                "source_pin_id": "macro-failed",
                "target_pin_id": "exit-failed",
                "source_pin_name": "Failed",
                "target_pin_name": "Failed",
                "pin_category": "exec",
            },
        ])
        write_jsonl(self.output / "blueprint_edges.jsonl", [{
            "edge_kind": "execution",
            "blueprint_path": self.caller_bp,
            "graph_id": self.caller_graph,
            "source_node_id": self.macro_node,
            "source_pin_id": "macro-then",
            "source_pin_name": "then",
            "target_node_id": self.next_node,
            "target_pin_id": "next-in",
            "target_pin_name": "execute",
        }])

    def test_derives_enter_return_and_terminal_without_flattening(self) -> None:
        self._write_fixture()
        edges, terminals = interproc.derive(self.output, rows)

        self.assertEqual(len(edges), 2)
        self.assertEqual(len(terminals), 1)
        by_kind = {row["edge_kind"]: row for row in edges}

        enter = by_kind["macro_enter"]
        self.assertEqual(enter["source_block_id"], "caller-block")
        self.assertEqual(enter["target_block_id"], "entry-block")
        self.assertEqual(enter["call_pin_id"], "macro-in")
        self.assertEqual(enter["interface_pin_id"], "entry-exec")
        self.assertEqual(enter["continuation_pin_id"], "")

        returned = by_kind["macro_return"]
        self.assertEqual(returned["source_block_id"], "exit-block")
        self.assertEqual(returned["target_block_id"], "next-block")
        self.assertEqual(returned["call_pin_id"], "macro-then")
        self.assertEqual(returned["interface_pin_id"], "exit-then")
        self.assertEqual(returned["continuation_pin_id"], "next-in")

        terminal = terminals[0]
        self.assertEqual(terminal["terminal_kind"], "macro_exit_unconnected")
        self.assertEqual(terminal["exit_block_id"], "exit-block")
        self.assertEqual(terminal["call_pin_id"], "macro-failed")
        self.assertEqual(terminal["interface_pin_id"], "exit-failed")
        self.assertEqual(terminal["canonical_outgoing_exec_count"], 0)

        write_jsonl(
            self.output / "blueprint_interprocedural_execution_edges.jsonl",
            edges,
        )
        write_jsonl(
            self.output / "blueprint_interprocedural_execution_terminals.jsonl",
            terminals,
        )
        self.assertIsNone(interproc.validation_error(self.output, rows))

    def test_validation_rejects_changed_cross_graph_target(self) -> None:
        self._write_fixture()
        edges, terminals = interproc.derive(self.output, rows)
        edges[0]["target_block_id"] = "invented"
        write_jsonl(
            self.output / "blueprint_interprocedural_execution_edges.jsonl",
            edges,
        )
        write_jsonl(
            self.output / "blueprint_interprocedural_execution_terminals.jsonl",
            terminals,
        )
        self.assertIn(
            "do not exactly match",
            str(interproc.validation_error(self.output, rows)),
        )

    def test_missing_continuation_block_is_a_derivation_error(self) -> None:
        self._write_fixture()
        blocks = list(rows(self.output / "blueprint_execution_blocks.jsonl"))
        write_jsonl(
            self.output / "blueprint_execution_blocks.jsonl",
            [row for row in blocks if row["block_id"] != "next-block"],
        )
        with self.assertRaisesRegex(RuntimeError, "continuation node lacks execution block"):
            interproc.derive(self.output, rows)

    def test_sqlite_round_trip(self) -> None:
        self._write_fixture()
        edges, terminals = interproc.derive(self.output, rows)
        write_jsonl(
            self.output / "blueprint_interprocedural_execution_edges.jsonl",
            edges,
        )
        write_jsonl(
            self.output / "blueprint_interprocedural_execution_terminals.jsonl",
            terminals,
        )

        conn = sqlite3.connect(":memory:")
        try:
            interproc.create_schema(conn)
            interproc.load_database(conn, self.output, rows)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blueprint_interprocedural_execution_edges"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blueprint_interprocedural_execution_terminals"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT edge_kind,source_block_id,target_block_id "
                    "FROM blueprint_interprocedural_execution_edges "
                    "WHERE edge_kind='macro_return'"
                ).fetchone(),
                ("macro_return", "exit-block", "next-block"),
            )
        finally:
            conn.close()


class BlueprintInterproceduralCompositionTest(unittest.TestCase):
    def test_schema33_and_bundle_membership_are_composed_without_global_import_side_effects(self) -> None:
        facade = (SCRIPTS / "uatool.py").read_text(encoding="utf-8")
        self.assertIn("FINAL_DERIVED_SCHEMA_VERSION = 33", facade)
        self.assertIn("import uatool_blueprint_interprocedural as blueprint_interprocedural", facade)
        self.assertIn("*blueprint_interprocedural.DERIVED_FILES", facade)
        self.assertIn("_require_blueprint_interprocedural(output)", facade)


if __name__ == "__main__":
    unittest.main()
