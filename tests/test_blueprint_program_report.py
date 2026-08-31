from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_blueprint_program_report as report


def write_jsonl(path: Path, values: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


class BlueprintProgramReportTest(unittest.TestCase):
    def test_compact_program_view(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            bp = "/Game/Test/BP_Test.BP_Test"
            graph = "g"
            write_jsonl(out / "blueprint_semantic_nodes.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "EventGraph", "node_id": "event"},
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "EventGraph", "node_id": "call"},
                {"blueprint_path": "/Game/Other.Other", "graph_id": "x", "graph_name": "Other", "node_id": "other"},
            ])
            write_jsonl(out / "blueprints.jsonl", [
                {
                    "object_path": bp,
                    "components": [
                        {
                            "variable_name": "Mover",
                            "component_class": "/Script/Mover.MoverComponent",
                            "parent_component_or_variable": "",
                            "attach_to": "",
                            "is_root": False,
                        }
                    ],
                }
            ])
            write_jsonl(out / "blueprint_functions.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "DoThing", "name": "DoThing", "inputs": [{"name": "Value"}], "outputs": [], "blueprint_pure": False},
            ])
            write_jsonl(out / "blueprint_events.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "EventGraph", "name": "BeginPlay", "event_kind": "event", "parameters": []},
            ])
            write_jsonl(out / "blueprint_component_properties.jsonl", [
                {"blueprint_path": bp, "component_name": "Mover", "property_name": "StartingMovementMode", "array_index": 0, "value": "Walking", "referenced_object_path": ""},
            ])
            write_jsonl(out / "blueprint_semantic_edges.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "source_node_id": "call", "relation": "calls", "target_kind": "function", "target": "/Script/Test.Lib:Run"},
                {"blueprint_path": bp, "graph_id": graph, "source_node_id": "call", "relation": "provides_value_to", "target_kind": "node", "target": "event"},
            ])
            write_jsonl(out / "blueprint_semantic_statements.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "EventGraph", "node_id": "event", "block_id": "block-a", "block_position": 0, "text": "event BeginPlay"},
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "EventGraph", "node_id": "call", "block_id": "block-a", "block_position": 1, "text": "Run(Value=1)"},
            ])
            write_jsonl(out / "blueprint_semantic_blocks.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "EventGraph", "block_id": "block-a", "block_index": 0},
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "EventGraph", "block_id": "block-dead", "block_index": 1},
            ])
            write_jsonl(out / "blueprint_execution_block_edges.jsonl", [])
            write_jsonl(out / "blueprint_execution_roots.jsonl", [
                {
                    "root_id": "root-a",
                    "blueprint_path": bp,
                    "graph_id": graph,
                    "graph_name": "EventGraph",
                    "root_node_id": "event",
                    "root_kind": "event",
                    "root_name": "BeginPlay",
                    "block_id": "block-a",
                }
            ])

            built = report.build_report(out, rows, bp, statement_limit=10, property_limit=10)
            self.assertEqual(built["semantic_node_count"], 2)
            self.assertEqual(built["component_count"], 1)
            self.assertEqual(built["component_property_count"], 1)
            self.assertEqual(built["root_count"], 1)
            self.assertEqual(built["unreachable_block_count"], 1)
            self.assertFalse(built["uses_control_semantics"])
            self.assertEqual(built["endpoint_groups"]["calls"], ["/Script/Test.Lib:Run"])
            self.assertEqual(built["block_label"]["block-a"], "B0")
            self.assertEqual(built["block_label"]["block-dead"], "B1")
            self.assertEqual(built["roots_by_graph"][graph][0]["root_name"], "BeginPlay")

            stream = io.StringIO()
            with redirect_stdout(stream):
                report.print_report(built)
            text = stream.getvalue()
            self.assertIn("Mover | /Script/Mover.MoverComponent", text)
            self.assertIn("Mover.StartingMovementMode = Walking", text)
            self.assertIn("DoThing(Value)", text)
            self.assertIn("calls (1)", text)
            self.assertIn("roots: event:BeginPlay->B0", text)
            self.assertIn("unreachable_blocks=1", text)
            self.assertIn("B1 [unreachable]", text)
            self.assertIn("Run(Value=1)", text)

    def test_semantic_control_flow_rendering(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            bp = "/Game/Test/BP_Control.BP_Control"
            graph = "control-g"
            write_jsonl(out / "blueprint_semantic_nodes.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "Control", "node_id": "root"},
            ])
            write_jsonl(out / "blueprint_semantic_blocks.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "Control", "block_id": f"b{i}", "block_index": i}
                for i in range(7)
            ])
            write_jsonl(out / "blueprint_execution_roots.jsonl", [
                {
                    "root_id": "root",
                    "blueprint_path": bp,
                    "graph_id": graph,
                    "graph_name": "Control",
                    "root_node_id": "root",
                    "root_kind": "function",
                    "root_name": "Control",
                    "block_id": "b0",
                }
            ])
            write_jsonl(out / "blueprint_execution_block_edges.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "Control", "source_block_id": "b0", "target_block_id": "b1", "source_node_id": "branch", "source_pin_name": "then"},
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "Control", "source_block_id": "b0", "target_block_id": "b2", "source_node_id": "branch", "source_pin_name": "else"},
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "Control", "source_block_id": "b1", "target_block_id": "b3", "source_node_id": "switch", "source_pin_name": "NewEnumerator2"},
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "Control", "source_block_id": "b1", "target_block_id": "b4", "source_node_id": "switch", "source_pin_name": "NewEnumerator1"},
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "Control", "source_block_id": "b2", "target_block_id": "b5", "source_node_id": "seq", "source_pin_name": "then_0"},
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "Control", "source_block_id": "b2", "target_block_id": "b6", "source_node_id": "seq", "source_pin_name": "then_1"},
            ])
            write_jsonl(out / "blueprint_control_edges.jsonl", [
                {
                    "blueprint_path": bp, "graph_id": graph, "graph_name": "Control",
                    "source_block_id": "b0", "target_block_id": "b1", "source_node_id": "branch",
                    "source_pin_name": "then", "source_pin_display_name": "then", "control_kind": "branch",
                    "condition_text": "Speed > 380", "condition_polarity": True,
                },
                {
                    "blueprint_path": bp, "graph_id": graph, "graph_name": "Control",
                    "source_block_id": "b0", "target_block_id": "b2", "source_node_id": "branch",
                    "source_pin_name": "else", "source_pin_display_name": "else", "control_kind": "branch",
                    "condition_text": "Speed > 380", "condition_polarity": False,
                },
                {
                    "blueprint_path": bp, "graph_id": graph, "graph_name": "Control",
                    "source_block_id": "b1", "target_block_id": "b3", "source_node_id": "switch",
                    "source_pin_name": "NewEnumerator2", "source_pin_display_name": "Aim", "control_kind": "switch_case",
                    "selector_text": "RotationMode", "case_name": "Aim", "case_raw_name": "NewEnumerator2",
                },
                {
                    "blueprint_path": bp, "graph_id": graph, "graph_name": "Control",
                    "source_block_id": "b1", "target_block_id": "b4", "source_node_id": "switch",
                    "source_pin_name": "NewEnumerator1", "source_pin_display_name": "Strafe", "control_kind": "switch_case",
                    "selector_text": "RotationMode", "case_name": "Strafe", "case_raw_name": "NewEnumerator1",
                },
                {
                    "blueprint_path": bp, "graph_id": graph, "graph_name": "Control",
                    "source_block_id": "b2", "target_block_id": "b5", "source_node_id": "seq",
                    "source_pin_name": "then_0", "source_pin_display_name": "then_0", "control_kind": "sequence",
                    "sequence_index": 0,
                },
                {
                    "blueprint_path": bp, "graph_id": graph, "graph_name": "Control",
                    "source_block_id": "b2", "target_block_id": "b6", "source_node_id": "seq",
                    "source_pin_name": "then_1", "source_pin_display_name": "then_1", "control_kind": "sequence",
                    "sequence_index": 1,
                },
            ])

            built = report.build_report(out, rows, bp, statement_limit=10, property_limit=10)
            self.assertTrue(built["uses_control_semantics"])
            self.assertEqual(built["control_edge_count"], 6)
            self.assertEqual(built["unreachable_block_count"], 0)

            stream = io.StringIO()
            with redirect_stdout(stream):
                report.print_report(built)
            text = stream.getvalue()
            self.assertIn("control_edges=6", text)
            self.assertIn("B0 | if Speed > 380: true->B1, false->B2", text)
            self.assertIn("B1 | switch RotationMode: Aim->B3, Strafe->B4", text)
            self.assertIn("B2 | sequence: [0]->B5, [1]->B6", text)
            self.assertNotIn("NewEnumerator2->", text)


if __name__ == "__main__":
    unittest.main()
