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

import uatool_mover_behavior as behavior
import uatool_mover_graph as mover_graph
import uatool_project_graph as project_graph


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class MoverBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.character_bp = "/Game/BP_Character.BP_Character"
        self.component = self.character_bp + "_C:CharacterMover"
        self.walking = self.component + ".WalkingMode"
        self.sliding = self.component + ".SlidingMode"
        self.transition = self.walking + ".BP_ToSlide_C_0"
        self.transition_bp = "/Game/Modes/BP_ToSlide.BP_ToSlide"
        self.graph_id = self.transition_bp + "::graph::Evaluate"
        self.branch = self.graph_id + "::node::branch"
        self.result = self.graph_id + "::node::result"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _condition_expression(self) -> dict:
        params = {"kind": "boundary", "operation": "function_entry", "label": "Evaluate", "output_pin": "Params"}
        proposed = {
            "kind": "expression", "operation": "break_struct", "label": "Break SimulationTickParams", "output_pin": "ProposedMove",
            "inputs": [{"pin": "SimulationTickParams", "sources": [params]}],
        }
        velocity = {
            "kind": "expression", "operation": "break_struct", "label": "Break ProposedMove", "output_pin": "LinearVelocity",
            "inputs": [{"pin": "ProposedMove", "sources": [proposed]}],
        }
        length_xy = {
            "kind": "expression", "operation": "function_call", "label": "VSizeXY", "output_pin": "ReturnValue",
            "inputs": [{"pin": "A", "sources": [velocity]}],
        }
        speed = {
            "kind": "expression", "operation": "function_call", "label": "Greater_DoubleDouble", "output_pin": "ReturnValue",
            "inputs": [{"pin": "A", "sources": [length_xy]}, {"pin": "B", "literal": "380.000000"}],
        }
        moving = {
            "kind": "expression", "operation": "break_struct", "label": "Break SimulationTickParams", "output_pin": "MovingComps",
            "inputs": [{"pin": "SimulationTickParams", "sources": [params]}],
        }
        mover = {
            "kind": "expression", "operation": "break_struct", "label": "Break MovingComponentSet", "output_pin": "MoverComponent",
            "inputs": [{"pin": "MovingComponentSet", "sources": [moving]}],
        }
        crouching = {
            "kind": "expression", "operation": "function_call", "label": "HasGameplayTag", "output_pin": "ReturnValue",
            "inputs": [
                {"pin": "self", "sources": [mover]},
                {"pin": "TagToFind", "literal": '(TagName="Mover.Stance.IsCrouching")'},
                {"pin": "bExactMatch", "literal": "false"},
            ],
        }
        return {
            "kind": "expression", "operation": "function_call", "label": "BooleanAND", "output_pin": "ReturnValue",
            "inputs": [{"pin": "A", "sources": [speed]}, {"pin": "B", "sources": [crouching]}],
        }

    def _write_fixture(self, branch_output: str = "then") -> None:
        write_jsonl(self.output / "mover_blueprints.jsonl", [{
            "blueprint_path": self.transition_bp,
            "mover_kind": "movement_transition",
        }])
        write_jsonl(self.output / "mover_modes.jsonl", [
            {
                "blueprint_path": self.character_bp,
                "component_path": self.component,
                "mode_index": 0,
                "mode_name": "Walking",
                "mode_path": self.walking,
                "mode_class": "/Game/Modes/BP_Walking.BP_Walking_C",
                "mode_asset_path": "/Game/Modes/BP_Walking.BP_Walking",
                "is_starting": True,
            },
            {
                "blueprint_path": self.character_bp,
                "component_path": self.component,
                "mode_index": 1,
                "mode_name": "Sliding",
                "mode_path": self.sliding,
                "mode_class": "/Game/Modes/BP_Slide.BP_Slide_C",
                "mode_asset_path": "/Game/Modes/BP_Slide.BP_Slide",
                "is_starting": False,
            },
        ])
        write_jsonl(self.output / "mover_transitions.jsonl", [{
            "asset_path": self.character_bp,
            "owner_path": self.walking,
            "owner_kind": "mover_mode",
            "transition_index": 0,
            "transition_path": self.transition,
            "transition_class": self.transition_bp + "_C",
            "transition_asset_path": self.transition_bp,
            "target_kind": "object",
        }])
        write_jsonl(self.output / "mover_components.jsonl", [])
        write_jsonl(self.output / "mover_settings.jsonl", [])
        write_jsonl(self.output / "blueprint_nodes.jsonl", [{
            "node_id": self.branch,
            "blueprint_path": self.transition_bp,
            "graph_id": self.graph_id,
            "graph_name": "Evaluate",
            "operation": "branch",
            "node_class": "/Script/BlueprintGraph.K2Node_IfThenElse",
        }])
        write_jsonl(self.output / "blueprint_edges.jsonl", [{
            "blueprint_path": self.transition_bp,
            "graph_id": self.graph_id,
            "graph_name": "Evaluate",
            "source_node_id": self.branch,
            "source_pin_name": branch_output,
            "target_node_id": self.result,
            "target_pin_name": "execute",
            "edge_kind": "execution",
        }])
        write_jsonl(self.output / "blueprint_data_dependencies.jsonl", [
            {
                "dependency_id": "dep_condition",
                "blueprint_path": self.transition_bp,
                "graph_id": self.graph_id,
                "graph_name": "Evaluate",
                "sink_node_id": self.branch,
                "sink_operation": "branch",
                "sink_pin_name": "Condition",
                "expression_node_count": 8,
                "function_calls": [
                    "/Script/Engine.KismetMathLibrary:BooleanAND",
                    "/Script/Engine.KismetMathLibrary:Greater_DoubleDouble",
                    "/Script/Engine.KismetMathLibrary:VSizeXY",
                    "/Script/Mover.MoverComponent:HasGameplayTag",
                ],
                "object_refs": [],
                "expression": self._condition_expression(),
                "text": "raw condition",
            },
            {
                "dependency_id": "dep_result",
                "blueprint_path": self.transition_bp,
                "graph_id": self.graph_id,
                "graph_name": "Evaluate",
                "sink_node_id": self.result,
                "sink_operation": "function_result",
                "sink_pin_name": "ReturnValue",
                "expression_node_count": 1,
                "function_calls": [],
                "object_refs": [],
                "expression": {
                    "kind": "expression",
                    "operation": "make_struct",
                    "label": "Make TransitionEvalResult",
                    "output_pin": "TransitionEvalResult",
                    "inputs": [{"pin": "NextMode", "literal": "Sliding", "type": "name"}],
                },
                "text": "Make TransitionEvalResult(NextMode=Sliding).TransitionEvalResult",
            },
        ])

    def test_derives_readable_behavior_concrete_route_and_graph_edges(self) -> None:
        self._write_fixture()
        behaviors, routes_out = behavior.derive(self.output, rows)
        self.assertEqual(len(behaviors), 1)
        self.assertEqual(len(routes_out), 1)
        expected = (
            '((length_xy(Params.ProposedMove.LinearVelocity) > 380) and '
            'has_gameplay_tag(Params.MovingComps.MoverComponent, "Mover.Stance.IsCrouching", exact=false))'
        )
        self.assertEqual(behaviors[0]["condition_text"], expected)
        self.assertEqual(behaviors[0]["next_mode"], "Sliding")
        self.assertTrue(behaviors[0]["condition_polarity"])
        self.assertEqual(routes_out[0]["source_mode_name"], "Walking")
        self.assertEqual(routes_out[0]["target_mode_name"], "Sliding")

        write_jsonl(self.output / behavior.DERIVED_FILES[0], behaviors)
        write_jsonl(self.output / behavior.DERIVED_FILES[1], routes_out)
        self.assertIsNone(behavior.validation_error(self.output, rows))

        conn = sqlite3.connect(":memory:")
        try:
            behavior.create_schema(conn)
            behavior.load_database(conn, self.output, rows)
            self.assertEqual(conn.execute("SELECT next_mode FROM mover_transition_behaviors").fetchone()[0], "Sliding")
            self.assertEqual(conn.execute("SELECT target_mode_name FROM mover_transition_routes").fetchone()[0], "Sliding")
        finally:
            conn.close()

        nodes, edges = mover_graph._augment(self.output, rows, [], [], project_graph)
        relations = {edge["relation"]: edge for edge in edges}
        self.assertIn("transitions_to_movement_mode", relations)
        self.assertIn("can_transition_to_movement_mode", relations)
        self.assertEqual(relations["can_transition_to_movement_mode"]["target"], self.sliding)
        self.assertEqual(relations["can_transition_to_movement_mode"]["edge_quality"], "exact_semantic")
        self.assertEqual(
            relations["can_transition_to_movement_mode"]["evidence"][0]["condition_text"],
            expected,
        )

    def test_else_branch_preserves_false_condition_polarity(self) -> None:
        self._write_fixture(branch_output="else")
        behaviors, routes_out = behavior.derive(self.output, rows)
        self.assertEqual(len(behaviors), 1)
        self.assertFalse(behaviors[0]["condition_polarity"])
        self.assertEqual(behaviors[0]["branch_output"], "else")
        self.assertEqual(len(routes_out), 1)


if __name__ == "__main__":
    unittest.main()
