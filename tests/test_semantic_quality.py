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

import uatool_semantic_quality as quality


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


class SemanticQualityTest(unittest.TestCase):
    def _fixture(self, root: Path, *, missing_call_identity: bool = False) -> tuple[str, str]:
        bp = "/Game/Test/BP_Complex.BP_Complex"
        other = "/Game/Test/BP_Simple.BP_Simple"
        write_jsonl(root / "blueprints.jsonl", [
            {
                "object_path": bp,
                "generated_class": bp + "_C",
                "parent_class": "/Script/Engine.Actor",
                "components": [
                    {"variable_name": "Root", "component_class": "/Script/Engine.SceneComponent"},
                ],
            },
            {
                "object_path": other,
                "generated_class": other + "_C",
                "parent_class": "/Script/Engine.Actor",
                "components": [],
            },
        ])
        write_jsonl(root / "blueprint_semantic_nodes.jsonl", [
            {
                "node_id": "event", "blueprint_path": bp, "graph_name": "EventGraph",
                "operation": "event", "semantic_kind": "event", "has_exec_flow": True, "opaque": False,
            },
            {
                "node_id": "branch", "blueprint_path": bp, "graph_name": "EventGraph",
                "operation": "branch", "semantic_kind": "control", "has_exec_flow": True, "opaque": False,
            },
            {
                "node_id": "call", "blueprint_path": bp, "graph_name": "EventGraph",
                "operation": "function_call", "semantic_kind": "call", "has_exec_flow": True, "opaque": False,
            },
            {
                "node_id": "set", "blueprint_path": bp, "graph_name": "EventGraph",
                "operation": "variable_set", "semantic_kind": "symbol_access", "has_exec_flow": True, "opaque": False,
            },
            {
                "node_id": "simple-event", "blueprint_path": other, "graph_name": "EventGraph",
                "operation": "event", "semantic_kind": "event", "has_exec_flow": True, "opaque": False,
            },
        ])
        write_jsonl(root / "blueprint_semantic_statements.jsonl", [
            {
                "node_id": "event", "blueprint_path": bp, "graph_name": "EventGraph", "block_id": "b0",
                "block_position": 0, "operation": "event", "semantic_kind": "event", "primary_effect": "event",
                "symbol": "BeginPlay", "target": "", "dependency_count": 0, "literal_count": 0,
                "inputs": [], "text": "event BeginPlay",
            },
            {
                "node_id": "branch", "blueprint_path": bp, "graph_name": "EventGraph", "block_id": "b0",
                "block_position": 1, "operation": "branch", "semantic_kind": "control", "primary_effect": "branch",
                "symbol": "", "target": "", "dependency_count": 1, "literal_count": 0,
                "inputs": [{"source_kind": "dependency", "expression_text": "IsReady", "pin_name": "Condition"}],
                "text": "if IsReady",
            },
            {
                "node_id": "call", "blueprint_path": bp, "graph_name": "EventGraph", "block_id": "b1",
                "block_position": 0, "operation": "function_call", "semantic_kind": "call", "primary_effect": "call",
                "symbol": "" if missing_call_identity else "DoThing", "target": "", "dependency_count": 1,
                "literal_count": 1,
                "inputs": [{"source_kind": "dependency", "expression_text": "Health", "pin_name": "Value"}],
                "text": "DoThing(Value=Health)",
            },
            {
                "node_id": "set", "blueprint_path": bp, "graph_name": "EventGraph", "block_id": "b2",
                "block_position": 0, "operation": "variable_set", "semantic_kind": "symbol_access", "primary_effect": "write",
                "symbol": "Health", "target": bp + "::Health", "dependency_count": 0, "literal_count": 1,
                "inputs": [{"source_kind": "literal", "literal": "100", "pin_name": "Health"}],
                "text": "Health = 100",
            },
            {
                "node_id": "simple-event", "blueprint_path": other, "graph_name": "EventGraph", "block_id": "s0",
                "block_position": 0, "operation": "event", "semantic_kind": "event", "primary_effect": "event",
                "symbol": "BeginPlay", "target": "", "dependency_count": 0, "literal_count": 0,
                "inputs": [], "text": "event BeginPlay",
            },
        ])
        write_jsonl(root / "blueprint_semantic_blocks.jsonl", [
            {"block_id": "b0", "blueprint_path": bp, "graph_name": "EventGraph"},
            {"block_id": "b1", "blueprint_path": bp, "graph_name": "EventGraph"},
            {"block_id": "b2", "blueprint_path": bp, "graph_name": "EventGraph"},
            {"block_id": "s0", "blueprint_path": other, "graph_name": "EventGraph"},
        ])
        control = [
            {
                "blueprint_path": bp, "graph_name": "EventGraph", "source_block_id": "b0", "target_block_id": "b1",
                "control_kind": "branch", "condition_text": "IsReady", "condition_polarity": True,
            },
            {
                "blueprint_path": bp, "graph_name": "EventGraph", "source_block_id": "b0", "target_block_id": "b2",
                "control_kind": "branch", "condition_text": "IsReady", "condition_polarity": False,
            },
        ]
        write_jsonl(root / "blueprint_control_edges.jsonl", control)
        write_jsonl(root / "blueprint_execution_block_edges.jsonl", control)
        write_jsonl(root / "blueprint_data_dependencies.jsonl", [
            {"blueprint_path": bp, "dependency_id": "dep-ready"},
            {"blueprint_path": bp, "dependency_id": "dep-health"},
        ])
        write_jsonl(root / "blueprint_semantic_edges.jsonl", [
            {"blueprint_path": bp, "relation": "calls", "target_kind": "function", "target": "DoThing"},
            {"blueprint_path": bp, "relation": "writes", "target_kind": "variable", "target": bp + "::Health"},
        ])
        write_jsonl(root / "blueprint_events.jsonl", [
            {"blueprint_path": bp, "name": "BeginPlay"},
            {"blueprint_path": other, "name": "BeginPlay"},
        ])
        write_jsonl(root / "blueprint_functions.jsonl", [])
        return bp, other

    def test_quality_case_accepts_structurally_complete_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bp, _ = self._fixture(root)
            report = quality.quality_case(root, rows, bp)
            self.assertTrue(report["structural_quality_ok"])
            self.assertEqual(report["defect_counts"]["fallback_nodes"], 0)
            self.assertEqual(report["defect_counts"]["missing_statement_nodes"], 0)
            self.assertEqual(report["counts"]["control_edges"], 2)
            self.assertEqual(report["endpoint_relation_counts"], {"calls": 1, "writes": 1})
            rendered = quality.render_case(report)
            self.assertIn("if IsReady", rendered)
            self.assertIn("DoThing(Value=Health)", rendered)
            self.assertIn("runtime_state_captured=False", rendered)
            self.assertIn("human_semantic_review_required=True", rendered)

    def test_missing_call_identity_is_a_machine_quality_defect(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bp, _ = self._fixture(root, missing_call_identity=True)
            report = quality.quality_case(root, rows, bp)
            self.assertFalse(report["structural_quality_ok"])
            self.assertEqual(report["defect_counts"]["missing_call_identity"], 1)

    def test_candidates_rank_control_and_dependency_rich_blueprint_first(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bp, other = self._fixture(root)
            report = quality.candidate_report(root, rows, limit=10)
            paths = [item["blueprint_path"] for item in report["candidates"]]
            self.assertEqual(paths[0], bp)
            self.assertIn(other, paths)
            self.assertGreater(
                report["candidates"][0]["quality_candidate_score"],
                report["candidates"][1]["quality_candidate_score"],
            )

    def test_composition_and_freshness_treat_diagnostic_as_read_only(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        freshness = (SCRIPTS / "uatool_derived_freshness.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_semantic_quality as _semantic_quality", facade)
        self.assertIn("_semantic_quality.install(_runtime)", facade)
        self.assertIn('"uatool_semantic_quality.py"', freshness)


if __name__ == "__main__":
    unittest.main()
