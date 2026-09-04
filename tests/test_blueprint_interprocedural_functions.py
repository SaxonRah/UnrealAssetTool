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


class BlueprintFunctionInterproceduralTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.caller = "/Game/Test/BP_Caller.BP_Caller"
        self.target = "/Game/Test/BP_Target.BP_Target"
        self.interface = "/Game/Test/BPI_Target.BPI_Target"
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
                "function_id": "fn-connected",
                "blueprint_path": self.target,
                "blueprint_pure": False,
                "entry_node_id": "entry-connected",
                "result_node_ids": [],
            },
            {
                "function_id": "fn-terminal",
                "blueprint_path": self.target,
                "blueprint_pure": True,
                "entry_node_id": "entry-terminal",
                "result_node_ids": ["result-terminal"],
            },
            {
                "function_id": "fn-pure",
                "blueprint_path": self.target,
                "blueprint_pure": True,
                "entry_node_id": "entry-pure",
                "result_node_ids": ["result-pure"],
            },
            {
                "function_id": "fn-interface",
                "blueprint_path": self.interface,
                "blueprint_pure": False,
                "entry_node_id": "entry-interface",
                "result_node_ids": [],
            },
            {
                "function_id": "fn-unreachable",
                "blueprint_path": self.target,
                "blueprint_pure": False,
                "entry_node_id": "entry-unreachable",
                "result_node_ids": [],
            },
        ])

        def call(node_id: str, fn: str, bp: str, *, pure=False, interface=False) -> dict:
            return {
                "call_id": node_id,
                "call_node_id": node_id,
                "blueprint_path": self.caller,
                "graph_id": "caller",
                "target_blueprint_path": bp,
                "target_function_id": fn,
                "resolution": "internal",
                "pure": pure,
                "latent": False,
                "interface_call": interface,
            }

        write_jsonl(self.output / "blueprint_call_edges.jsonl", [
            call("call-connected", "fn-connected", self.target),
            call("call-terminal", "fn-terminal", self.target),
            call("call-pure", "fn-pure", self.target, pure=True),
            call("call-interface", "fn-interface", self.interface, interface=True),
            call("call-unreachable", "fn-unreachable", self.target),
        ])
        write_jsonl(self.output / "blueprint_call_bindings.jsonl", [
            {"binding_id": "b1", "call_node_id": "call-connected"},
            {"binding_id": "b2", "call_node_id": "call-terminal"},
            {"binding_id": "b3", "call_node_id": "call-terminal"},
        ])

        write_jsonl(self.output / "blueprint_execution_blocks.jsonl", [
            {"block_id": "caller-connected", "blueprint_path": self.caller, "graph_id": "caller", "exit_node_id": "call-connected", "node_ids": ["call-connected"]},
            {"block_id": "caller-next", "blueprint_path": self.caller, "graph_id": "caller", "exit_node_id": "next", "node_ids": ["next"]},
            {"block_id": "caller-terminal", "blueprint_path": self.caller, "graph_id": "caller", "exit_node_id": "call-terminal", "node_ids": ["call-terminal"]},
            {"block_id": "connected-entry", "blueprint_path": self.target, "graph_id": "fn-connected", "exit_node_id": "entry-connected", "node_ids": ["entry-connected"]},
            {"block_id": "connected-exit-a", "blueprint_path": self.target, "graph_id": "fn-connected", "exit_node_id": "exit-a", "node_ids": ["exit-a"]},
            {"block_id": "connected-exit-b", "blueprint_path": self.target, "graph_id": "fn-connected", "exit_node_id": "exit-b", "node_ids": ["exit-b"]},
            {"block_id": "terminal-entry", "blueprint_path": self.target, "graph_id": "fn-terminal", "exit_node_id": "entry-terminal", "node_ids": ["entry-terminal"]},
            {"block_id": "terminal-result", "blueprint_path": self.target, "graph_id": "fn-terminal", "exit_node_id": "result-terminal", "node_ids": ["result-terminal"]},
            {"block_id": "pure-entry", "blueprint_path": self.target, "graph_id": "fn-pure", "exit_node_id": "entry-pure", "node_ids": ["entry-pure"]},
            {"block_id": "pure-result", "blueprint_path": self.target, "graph_id": "fn-pure", "exit_node_id": "result-pure", "node_ids": ["result-pure"]},
            {"block_id": "interface-entry", "blueprint_path": self.interface, "graph_id": "fn-interface", "exit_node_id": "entry-interface", "node_ids": ["entry-interface"]},
            {"block_id": "unreachable-entry", "blueprint_path": self.target, "graph_id": "fn-unreachable", "exit_node_id": "entry-unreachable", "node_ids": ["entry-unreachable"]},
        ])
        write_jsonl(self.output / "blueprint_execution_block_edges.jsonl", [
            {"source_block_id": "connected-entry", "target_block_id": "connected-exit-a"},
            {"source_block_id": "connected-entry", "target_block_id": "connected-exit-b"},
            {"source_block_id": "terminal-entry", "target_block_id": "terminal-result"},
            {"source_block_id": "pure-entry", "target_block_id": "pure-result"},
        ])
        write_jsonl(self.output / "blueprint_edges.jsonl", [{
            "edge_kind": "execution",
            "graph_id": "caller",
            "source_node_id": "call-connected",
            "source_pin_id": "call-connected-then",
            "source_pin_name": "then",
            "target_node_id": "next",
            "target_pin_id": "next-exec",
            "target_pin_name": "execute",
        }])

        # Existing macro schema streams are empty in this function-only fixture.
        write_jsonl(self.output / "blueprint_semantic_edges.jsonl", [])
        write_jsonl(self.output / "blueprint_pins.jsonl", [])
        write_jsonl(self.output / "blueprint_data_dependencies.jsonl", [])
        write_jsonl(self.output / interproc.DERIVED_FILES[0], [])
        write_jsonl(self.output / interproc.DERIVED_FILES[1], [])
        write_jsonl(self.output / interproc.DERIVED_FILES[2], [])

    def test_materializes_only_executable_direct_internal_calls(self) -> None:
        edges, terminals, stats = interproc.derive_function_execution(self.output, rows)

        self.assertEqual(interproc.INTERPROCEDURAL_SCHEMA_VERSION, 4)
        self.assertEqual(stats["direct_impure"], 3)
        self.assertEqual(stats["excluded_pure"], 1)
        self.assertEqual(stats["excluded_interface"], 1)
        self.assertEqual(stats["excluded_unreachable_callsite"], 1)

        kinds = {}
        for row in edges:
            kinds[row["edge_kind"]] = kinds.get(row["edge_kind"], 0) + 1
        self.assertEqual(kinds, {"function_enter": 2, "function_return": 2})
        self.assertEqual(len(terminals), 1)

        connected_enters = [
            row for row in edges
            if row["edge_kind"] == "function_enter" and row["call_node_id"] == "call-connected"
        ]
        self.assertEqual(len(connected_enters), 1)
        self.assertEqual(connected_enters[0]["target_block_id"], "connected-entry")
        self.assertEqual(connected_enters[0]["return_frontier_block_count"], 2)
        self.assertEqual(connected_enters[0]["call_binding_count"], 1)

        returns = [row for row in edges if row["edge_kind"] == "function_return"]
        self.assertEqual({row["source_block_id"] for row in returns}, {"connected-exit-a", "connected-exit-b"})
        self.assertEqual({row["target_block_id"] for row in returns}, {"caller-next"})

        terminal = terminals[0]
        self.assertEqual(terminal["call_node_id"], "call-terminal")
        self.assertEqual(terminal["return_frontier_block_ids"], ["terminal-result"])
        self.assertEqual(terminal["call_binding_count"], 2)
        self.assertTrue(terminal["purity_override"])

    def test_validation_and_sqlite_round_trip(self) -> None:
        function_edges, function_terminals, _stats = interproc.derive_function_execution(
            self.output, rows
        )
        write_jsonl(self.output / interproc.DERIVED_FILES[3], function_edges)
        write_jsonl(self.output / interproc.DERIVED_FILES[4], function_terminals)
        write_jsonl(self.output / interproc.DERIVED_FILES[5], [])
        self.assertIsNone(interproc.validation_error(self.output, rows))

        conn = sqlite3.connect(":memory:")
        try:
            interproc.create_schema(conn)
            interproc.load_database(conn, self.output, rows)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blueprint_interprocedural_function_execution_edges"
                ).fetchone()[0],
                4,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blueprint_interprocedural_function_execution_terminals"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM blueprint_interprocedural_function_execution_edges "
                    "WHERE edge_kind='function_return'"
                ).fetchone()[0],
                2,
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
