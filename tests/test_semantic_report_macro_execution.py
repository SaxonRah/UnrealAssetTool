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

import uatool_blueprint_interprocedural as interproc
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


def pin(pin_id: str, node_id: str, graph_id: str, name: str, direction: str) -> dict:
    return {
        "pin_id": pin_id,
        "node_id": node_id,
        "blueprint_path": "/Game/Test/BP.BP",
        "graph_id": graph_id,
        "graph_name": "EventGraph" if graph_id == "caller" else "Macro",
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


class SemanticReportMacroExecutionTest(unittest.TestCase):
    def _fixture(self, root: Path, *, connected: bool) -> None:
        macro_path = "/Game/Test/BPL.BPL:Macro"
        write_jsonl(root / "blueprint_semantic_nodes.jsonl", [
            {"node_id": "macro", "operation": "macro_instance", "semantic_kind": "call", "opaque": False},
            {"node_id": "entry", "operation": "tunnel", "semantic_kind": "boundary", "opaque": False},
            {"node_id": "exit", "operation": "tunnel", "semantic_kind": "boundary", "opaque": False},
            {"node_id": "next", "operation": "function_call", "semantic_kind": "call", "opaque": False},
        ])
        write_jsonl(root / "blueprint_nodes.jsonl", [
            {
                "node_id": "macro",
                "graph_id": "caller",
                "operation": "macro_instance",
                "semantic": {
                    "macro_graph": macro_path,
                    "source_blueprint": "/Game/Test/BPL.BPL",
                },
            },
            {"node_id": "entry", "graph_id": "macro-graph", "operation": "tunnel", "semantic": {}},
            {"node_id": "exit", "graph_id": "macro-graph", "operation": "tunnel", "semantic": {}},
            {"node_id": "next", "graph_id": "caller", "operation": "function_call", "semantic": {}},
        ])
        write_jsonl(root / "blueprint_graphs.jsonl", [
            {"graph_id": "caller", "graph_path": "/Game/Test/BP.BP:EventGraph"},
            {"graph_id": "macro-graph", "graph_path": macro_path},
        ])
        write_jsonl(root / "blueprint_pins.jsonl", [
            pin("macro-in", "macro", "caller", "execute", "input"),
            pin("macro-out", "macro", "caller", "then", "output"),
            pin("entry-out", "entry", "macro-graph", "execute", "output"),
            pin("exit-in", "exit", "macro-graph", "then", "input"),
            pin("next-in", "next", "caller", "execute", "input"),
        ])
        write_jsonl(root / "blueprint_semantic_edges.jsonl", [
            {
                "source_node_id": "macro",
                "relation": "maps_to_macro_graph",
                "target_kind": "blueprint_graph",
                "target": "macro-graph",
                "source_pin_id": "",
                "target_pin_id": "",
                "pin_category": "",
            },
            {
                "source_node_id": "macro",
                "relation": "binds_macro_input",
                "target_kind": "blueprint_pin",
                "target": "entry-out",
                "source_pin_id": "macro-in",
                "target_pin_id": "entry-out",
                "source_pin_name": "execute",
                "target_pin_name": "execute",
                "pin_category": "exec",
            },
            {
                "source_node_id": "macro",
                "relation": "binds_macro_output",
                "target_kind": "blueprint_pin",
                "target": "exit-in",
                "source_pin_id": "macro-out",
                "target_pin_id": "exit-in",
                "source_pin_name": "then",
                "target_pin_name": "then",
                "pin_category": "exec",
            },
        ])
        write_jsonl(root / "blueprint_execution_blocks.jsonl", [
            {"block_id": "caller-block", "graph_id": "caller", "node_ids": ["macro"]},
            {"block_id": "entry-block", "graph_id": "macro-graph", "node_ids": ["entry"]},
            {"block_id": "exit-block", "graph_id": "macro-graph", "node_ids": ["exit"]},
            {"block_id": "next-block", "graph_id": "caller", "node_ids": ["next"]},
        ])
        write_jsonl(
            root / "blueprint_edges.jsonl",
            [{
                "edge_kind": "execution",
                "source_node_id": "macro",
                "source_pin_id": "macro-out",
                "source_pin_name": "then",
                "target_node_id": "next",
                "target_pin_id": "next-in",
                "target_pin_name": "execute",
            }] if connected else [],
        )

    def _write_interprocedural_streams(self, root: Path) -> None:
        edges, terminals, data_routes = interproc.derive(root, rows)
        write_jsonl(root / interproc.DERIVED_FILES[0], edges)
        write_jsonl(root / interproc.DERIVED_FILES[1], terminals)
        write_jsonl(root / interproc.DERIVED_FILES[2], data_routes)

    def test_connected_macro_exec_output_has_exact_entry_and_return_block_bridges(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root, connected=True)
            self._write_interprocedural_streams(root)
            result = report.build_report(root, rows)

            self.assertEqual(result["macro_exec_exact_instance_count"], 1)
            self.assertEqual(result["macro_exec_input_binding_count"], 1)
            self.assertEqual(result["macro_exec_exact_entry_bridge_count"], 1)
            self.assertEqual(result["macro_exec_output_binding_count"], 1)
            self.assertEqual(result["macro_exec_connected_output_count"], 1)
            self.assertEqual(result["macro_exec_terminal_output_count"], 0)
            self.assertEqual(result["macro_exec_exact_return_bridge_count"], 1)
            self.assertEqual(result["macro_exec_mismatches"], [])
            self.assertEqual(result["interprocedural_execution_edge_count"], 2)
            self.assertEqual(dict(result["interprocedural_execution_edge_kinds"]), {
                "macro_enter": 1,
                "macro_return": 1,
            })
            self.assertEqual(result["interprocedural_execution_terminal_count"], 0)
            self.assertTrue(result["interprocedural_stream_alignment"])

    def test_terminal_macro_exec_output_is_not_a_bridge_defect(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._fixture(root, connected=False)
            self._write_interprocedural_streams(root)
            result = report.build_report(root, rows)

            self.assertEqual(result["macro_exec_exact_instance_count"], 1)
            self.assertEqual(result["macro_exec_exact_entry_bridge_count"], 1)
            self.assertEqual(result["macro_exec_output_binding_count"], 1)
            self.assertEqual(result["macro_exec_connected_output_count"], 0)
            self.assertEqual(result["macro_exec_terminal_output_count"], 1)
            self.assertEqual(result["macro_exec_exact_return_bridge_count"], 0)
            self.assertIn(
                ("terminal_output_exact_exit_block", 1),
                result["macro_exec_status"],
            )
            self.assertEqual(result["macro_exec_mismatches"], [])
            self.assertEqual(result["interprocedural_execution_edge_count"], 1)
            self.assertEqual(dict(result["interprocedural_execution_edge_kinds"]), {
                "macro_enter": 1,
            })
            self.assertEqual(result["interprocedural_execution_terminal_count"], 1)
            self.assertEqual(dict(result["interprocedural_execution_terminal_kinds"]), {
                "macro_exit_unconnected": 1,
            })
            self.assertTrue(result["interprocedural_stream_alignment"])


if __name__ == "__main__":
    unittest.main()
