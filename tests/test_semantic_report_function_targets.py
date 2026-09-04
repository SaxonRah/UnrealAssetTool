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


class SemanticReportFunctionTargetAuditTest(unittest.TestCase):
    def _write_function_streams(self, root: Path) -> None:
        function_edges, function_terminals, _stats = interproc.derive_function_execution(
            root, rows
        )
        write_jsonl(root / interproc.DERIVED_FILES[3], function_edges)
        write_jsonl(root / interproc.DERIVED_FILES[4], function_terminals)
        write_jsonl(root / interproc.DERIVED_FILES[5], [])

    def test_distinguishes_direct_interface_pure_and_latent_internal_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            write_jsonl(root / "blueprint_semantic_nodes.jsonl", [
                {
                    "node_id": node_id,
                    "operation": "function_call",
                    "semantic_kind": "call",
                    "opaque": False,
                }
                for node_id in ("call-direct", "call-void", "call-interface", "call-pure", "call-latent")
            ])
            write_jsonl(root / "blueprint_nodes.jsonl", [])
            write_jsonl(root / "blueprint_graphs.jsonl", [])
            write_jsonl(root / "blueprint_pins.jsonl", [])
            write_jsonl(root / "blueprint_semantic_edges.jsonl", [])
            write_jsonl(root / "blueprint_data_dependencies.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_execution_edges.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_execution_terminals.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_data_routes.jsonl", [])

            caller_bp = "/Game/Test/BP_Caller.BP_Caller"
            direct_bp = "/Game/Test/BP_Direct.BP_Direct"
            void_bp = "/Game/Test/BP_Void.BP_Void"
            interface_bp = "/Game/Test/BPI_Target.BPI_Target"
            pure_bp = "/Game/Test/BP_Pure.BP_Pure"
            latent_bp = "/Game/Test/BP_Latent.BP_Latent"

            write_jsonl(root / "blueprints.jsonl", [
                {"object_path": caller_bp, "blueprint_type": 0},
                {"object_path": direct_bp, "blueprint_type": 0},
                {"object_path": void_bp, "blueprint_type": 0},
                {"object_path": interface_bp, "blueprint_type": 3},
                {"object_path": pure_bp, "blueprint_type": 0},
                {"object_path": latent_bp, "blueprint_type": 0},
            ])

            write_jsonl(root / "blueprint_functions.jsonl", [
                {
                    "function_id": "fn-direct",
                    "blueprint_path": direct_bp,
                    "name": "DoDirect",
                    "blueprint_pure": False,
                    "entry_node_id": "entry-direct",
                    "result_node_ids": ["result-direct"],
                },
                {
                    "function_id": "fn-void",
                    "blueprint_path": void_bp,
                    "name": "DoVoid",
                    "blueprint_pure": False,
                    "entry_node_id": "entry-void",
                    "result_node_ids": [],
                },
                {
                    "function_id": "fn-interface",
                    "blueprint_path": interface_bp,
                    "name": "DoInterface",
                    "blueprint_pure": False,
                    "entry_node_id": "entry-interface",
                    "result_node_ids": [],
                },
                {
                    "function_id": "fn-pure",
                    "blueprint_path": pure_bp,
                    "name": "GetPure",
                    "blueprint_pure": True,
                    "entry_node_id": "entry-pure",
                    "result_node_ids": ["result-pure"],
                },
                {
                    "function_id": "fn-latent",
                    "blueprint_path": latent_bp,
                    "name": "DoLatent",
                    "blueprint_pure": False,
                    "entry_node_id": "entry-latent",
                    "result_node_ids": ["result-latent"],
                },
            ])

            def call_row(
                node_id: str,
                target_bp: str,
                target_function_id: str,
                *,
                pure: bool = False,
                latent: bool = False,
                interface_call: bool = False,
            ) -> dict:
                return {
                    "call_id": node_id,
                    "call_node_id": node_id,
                    "blueprint_path": caller_bp,
                    "graph_id": "caller-graph",
                    "graph_name": "EventGraph",
                    "caller_function_id": "",
                    "target_blueprint_path": target_bp,
                    "target_function_id": target_function_id,
                    "resolution": "internal",
                    "pure": pure,
                    "latent": latent,
                    "interface_call": interface_call,
                }

            write_jsonl(root / "blueprint_call_edges.jsonl", [
                call_row("call-direct", direct_bp, "fn-direct"),
                call_row("call-void", void_bp, "fn-void"),
                call_row("call-interface", interface_bp, "fn-interface"),
                call_row("call-pure", pure_bp, "fn-pure", pure=True),
                call_row("call-latent", latent_bp, "fn-latent", latent=True),
            ])
            write_jsonl(root / "blueprint_call_bindings.jsonl", [
                {
                    "binding_id": "bind-direct",
                    "call_node_id": "call-direct",
                    "direction": "argument",
                },
            ])

            write_jsonl(root / "blueprint_execution_blocks.jsonl", [
                {
                    "block_id": "caller-call-block",
                    "blueprint_path": caller_bp,
                    "graph_id": "caller-graph",
                    "node_ids": ["call-direct"],
                },
                {
                    "block_id": "caller-void-block",
                    "blueprint_path": caller_bp,
                    "graph_id": "caller-graph",
                    "node_ids": ["call-void"],
                },
                {
                    "block_id": "caller-next-block",
                    "blueprint_path": caller_bp,
                    "graph_id": "caller-graph",
                    "node_ids": ["next"],
                },
                {
                    "block_id": "direct-entry-block",
                    "blueprint_path": direct_bp,
                    "graph_id": "fn-direct",
                    "node_ids": ["entry-direct"],
                },
                {
                    "block_id": "direct-result-block",
                    "blueprint_path": direct_bp,
                    "graph_id": "fn-direct",
                    "node_ids": ["result-direct"],
                },
                {
                    "block_id": "void-entry-block",
                    "blueprint_path": void_bp,
                    "graph_id": "fn-void",
                    "node_ids": ["entry-void"],
                },
                {
                    "block_id": "void-terminal-block",
                    "blueprint_path": void_bp,
                    "graph_id": "fn-void",
                    "node_ids": ["void-last"],
                },
            ])
            write_jsonl(root / "blueprint_edges.jsonl", [
                {
                    "edge_kind": "execution",
                    "graph_id": "caller-graph",
                    "source_node_id": "call-direct",
                    "source_pin_id": "call-direct-then",
                    "source_pin_name": "then",
                    "target_node_id": "next",
                    "target_pin_id": "next-exec",
                    "target_pin_name": "execute",
                },
                {
                    "edge_kind": "execution",
                    "graph_id": "fn-void",
                    "source_node_id": "entry-void",
                    "source_pin_id": "entry-void-then",
                    "source_pin_name": "then",
                    "target_node_id": "void-last",
                    "target_pin_id": "void-last-exec",
                    "target_pin_name": "execute",
                },
            ])
            write_jsonl(root / "blueprint_execution_block_edges.jsonl", [
                {
                    "edge_id": "direct-edge",
                    "blueprint_path": direct_bp,
                    "graph_id": "fn-direct",
                    "source_block_id": "direct-entry-block",
                    "target_block_id": "direct-result-block",
                    "source_node_id": "entry-direct",
                    "target_node_id": "result-direct",
                    "source_pin_name": "then",
                    "target_pin_name": "execute",
                },
                {
                    "edge_id": "void-edge",
                    "blueprint_path": void_bp,
                    "graph_id": "fn-void",
                    "source_block_id": "void-entry-block",
                    "target_block_id": "void-terminal-block",
                    "source_node_id": "entry-void",
                    "target_node_id": "void-last",
                    "source_pin_name": "then",
                    "target_pin_name": "execute",
                },
            ])

            self._write_function_streams(root)
            result = report.build_report(root, rows)
            self.assertEqual(result["function_call_count"], 5)
            self.assertEqual(result["function_call_internal_count"], 5)
            self.assertEqual(result["function_call_internal_target_count"], 5)
            self.assertEqual(result["function_call_interface_count"], 1)
            self.assertEqual(result["function_call_pure_internal_count"], 1)
            self.assertEqual(result["function_call_latent_internal_count"], 1)
            self.assertEqual(result["function_call_direct_impure_count"], 2)
            self.assertEqual(result["function_call_purity_override_count"], 0)
            self.assertEqual(result["function_call_suspicious_purity_count"], 0)
            self.assertEqual(result["function_call_unknown_blueprint_type_count"], 0)

            self.assertEqual(result["function_direct_exact_caller_block_count"], 2)
            self.assertEqual(result["function_direct_exact_entry_block_count"], 2)
            self.assertEqual(result["function_direct_explicit_result_call_count"], 1)
            self.assertEqual(result["function_direct_result_node_count"], 1)
            self.assertEqual(result["function_direct_exact_result_block_count"], 1)
            self.assertEqual(result["function_direct_void_call_count"], 1)
            self.assertEqual(result["function_direct_calls_with_terminal_frontier"], 2)
            self.assertEqual(result["function_direct_reachable_terminal_block_count"], 2)
            self.assertEqual(result["function_direct_reachable_result_node_count"], 1)
            self.assertEqual(result["function_direct_unreachable_result_node_count"], 0)
            self.assertEqual(result["function_direct_unreachable_callsite_count"], 0)
            self.assertEqual(result["function_direct_no_return_frontier_count"], 0)
            self.assertEqual(result["function_direct_connected_continuation_count"], 1)
            self.assertEqual(result["function_direct_terminal_call_count"], 1)
            self.assertEqual(result["function_direct_exact_continuation_block_count"], 1)
            self.assertEqual(result["function_direct_binding_count"], 1)
            self.assertEqual(result["function_direct_bridge_ready_count"], 2)
            self.assertEqual(result["function_call_mismatches"], [])
            self.assertTrue(result["function_interprocedural_stream_alignment"])
            self.assertEqual(
                dict(result["function_interprocedural_edge_kinds"]),
                {"function_enter": 2, "function_return": 1},
            )
            self.assertEqual(
                dict(result["function_interprocedural_terminal_kinds"]),
                {"function_call_no_continuation": 1},
            )

            self.assertEqual(dict(result["function_call_resolution"]), {"internal": 5})
            self.assertEqual(dict(result["function_internal_kinds"]), {
                "direct_impure_bridge_ready": 2,
                "direct_impure_internal": 2,
                "interface_dispatch_or_declaration": 1,
                "latent_internal": 1,
                "pure_internal": 1,
            })


    def test_pure_target_can_be_used_as_impure_call_node(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            caller_bp = "/Game/Test/BP_Caller.BP_Caller"
            target_bp = "/Game/Test/BP_PureTarget.BP_PureTarget"

            write_jsonl(root / "blueprint_semantic_nodes.jsonl", [{
                "node_id": "call",
                "operation": "function_call",
                "semantic_kind": "call",
                "opaque": False,
            }])
            write_jsonl(root / "blueprint_nodes.jsonl", [])
            write_jsonl(root / "blueprint_graphs.jsonl", [])
            write_jsonl(root / "blueprint_pins.jsonl", [])
            write_jsonl(root / "blueprint_semantic_edges.jsonl", [])
            write_jsonl(root / "blueprint_data_dependencies.jsonl", [])
            write_jsonl(root / "blueprint_call_bindings.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_execution_edges.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_execution_terminals.jsonl", [])
            write_jsonl(root / "blueprint_interprocedural_data_routes.jsonl", [])
            write_jsonl(root / "blueprints.jsonl", [
                {"object_path": caller_bp, "blueprint_type": 0},
                {"object_path": target_bp, "blueprint_type": 0},
            ])
            write_jsonl(root / "blueprint_functions.jsonl", [{
                "function_id": "fn",
                "blueprint_path": target_bp,
                "name": "PureByDefault",
                "blueprint_pure": True,
                "entry_node_id": "entry",
                "result_node_ids": ["result"],
            }])
            write_jsonl(root / "blueprint_call_edges.jsonl", [{
                "call_id": "call",
                "call_node_id": "call",
                "blueprint_path": caller_bp,
                "graph_id": "caller",
                "target_blueprint_path": target_bp,
                "target_function_id": "fn",
                "resolution": "internal",
                "pure": False,
                "latent": False,
                "interface_call": False,
            }])
            write_jsonl(root / "blueprint_execution_blocks.jsonl", [
                {
                    "block_id": "call-block",
                    "blueprint_path": caller_bp,
                    "graph_id": "caller",
                    "node_ids": ["call"],
                },
                {
                    "block_id": "next-block",
                    "blueprint_path": caller_bp,
                    "graph_id": "caller",
                    "node_ids": ["next"],
                },
                {
                    "block_id": "entry-block",
                    "blueprint_path": target_bp,
                    "graph_id": "fn",
                    "node_ids": ["entry"],
                },
                {
                    "block_id": "result-block",
                    "blueprint_path": target_bp,
                    "graph_id": "fn",
                    "node_ids": ["result"],
                },
            ])
            write_jsonl(root / "blueprint_execution_block_edges.jsonl", [{
                "edge_id": "fn-edge",
                "blueprint_path": target_bp,
                "graph_id": "fn",
                "source_block_id": "entry-block",
                "target_block_id": "result-block",
                "source_node_id": "entry",
                "target_node_id": "result",
                "source_pin_name": "then",
                "target_pin_name": "execute",
            }])
            write_jsonl(root / "blueprint_edges.jsonl", [
                {
                    "edge_kind": "execution",
                    "graph_id": "caller",
                    "source_node_id": "call",
                    "source_pin_id": "call-then",
                    "source_pin_name": "then",
                    "target_node_id": "next",
                    "target_pin_id": "next-exec",
                    "target_pin_name": "execute",
                },
                {
                    "edge_kind": "execution",
                    "graph_id": "fn",
                    "source_node_id": "entry",
                    "source_pin_id": "entry-then",
                    "source_pin_name": "then",
                    "target_node_id": "result",
                    "target_pin_id": "result-exec",
                    "target_pin_name": "execute",
                },
            ])

            self._write_function_streams(root)
            result = report.build_report(root, rows)
            self.assertEqual(result["function_call_purity_override_count"], 1)
            self.assertEqual(result["function_call_suspicious_purity_count"], 0)
            self.assertEqual(result["function_call_direct_impure_count"], 1)
            self.assertEqual(result["function_call_pure_internal_count"], 0)
            self.assertEqual(result["function_direct_bridge_ready_count"], 1)
            self.assertIn(
                ("pure_target_impure_call_node", 1),
                result["function_internal_kinds"],
            )
            self.assertEqual(result["function_call_mismatches"], [])


if __name__ == "__main__":
    unittest.main()
