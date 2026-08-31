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
            write_jsonl(out / "blueprint_functions.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "DoThing", "name": "DoThing", "inputs": [{"name": "Value"}], "outputs": [], "blueprint_pure": False},
            ])
            write_jsonl(out / "blueprint_events.jsonl", [
                {"blueprint_path": bp, "graph_id": graph, "graph_name": "EventGraph", "name": "BeginPlay", "event_kind": "event", "parameters": []},
            ])
            write_jsonl(out / "blueprint_components.jsonl", [
                {"blueprint_path": bp, "variable_name": "Mover", "component_class": "/Script/Mover.MoverComponent", "parent_component_or_variable": "", "attach_to": "", "is_root": False},
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
            ])
            write_jsonl(out / "blueprint_execution_block_edges.jsonl", [])
            write_jsonl(out / "blueprint_execution_roots.jsonl", [])

            built = report.build_report(out, rows, bp, statement_limit=10, property_limit=10)
            self.assertEqual(built["semantic_node_count"], 2)
            self.assertEqual(built["component_count"], 1)
            self.assertEqual(built["component_property_count"], 1)
            self.assertEqual(built["endpoint_groups"]["calls"], ["/Script/Test.Lib:Run"])
            self.assertEqual(built["block_label"]["block-a"], "B0")

            stream = io.StringIO()
            with redirect_stdout(stream):
                report.print_report(built)
            text = stream.getvalue()
            self.assertIn("Mover.StartingMovementMode = Walking", text)
            self.assertIn("DoThing(Value)", text)
            self.assertIn("calls (1)", text)
            self.assertIn("B0", text)
            self.assertIn("Run(Value=1)", text)


if __name__ == "__main__":
    unittest.main()
