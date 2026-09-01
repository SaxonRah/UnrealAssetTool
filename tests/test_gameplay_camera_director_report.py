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

import uatool_gameplay_camera_director_report as director_report


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


class GameplayCameraDirectorReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.bp = "/Game/Cameras/CameraDirector.CameraDirector"
        self.chooser = "/Game/Cameras/CHT_CameraRig.CHT_CameraRig"
        self.graph = "graph:run"
        self.eval_node = "node:chooser"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> None:
        write_jsonl(self.output / "blueprints.jsonl", [{
            "object_path": self.bp,
            "parent_class": "/Script/GameplayCameras.BlueprintCameraDirectorEvaluator",
            "generated_class": self.bp + "_C",
        }])
        write_jsonl(self.output / "blueprint_relations.jsonl", [{
            "blueprint_path": self.bp,
            "relation": "uses_asset",
            "source_id": self.eval_node,
            "target": self.chooser,
        }])
        write_jsonl(self.output / "chooser_tables.jsonl", [{
            "chooser_path": self.chooser,
            "result_count": 1,
            "column_count": 3,
            "context_count": 1,
        }])
        write_jsonl(self.output / "blueprint_semantic_nodes.jsonl", [
            {
                "node_id": self.eval_node,
                "blueprint_path": self.bp,
                "graph_id": self.graph,
                "graph_name": "RunCameraDirector",
                "operation": "evaluate_chooser",
                "symbol": "EvaluateChooser",
                "target": self.chooser,
                "owner": self.bp,
            },
            {
                "node_id": "node:mode",
                "blueprint_path": self.bp,
                "graph_id": self.graph,
                "graph_name": "RunCameraDirector",
                "operation": "variable_get",
                "symbol": "CameraMode",
                "target": self.bp + "::CameraMode",
                "owner": self.bp,
            },
        ])
        write_jsonl(self.output / "blueprint_semantic_statements.jsonl", [{
            "statement_id": "stmt:chooser",
            "node_id": self.eval_node,
            "blueprint_path": self.bp,
            "graph_id": self.graph,
            "graph_name": "RunCameraDirector",
            "block_id": "block:0",
            "block_position": 1,
            "operation": "evaluate_chooser",
            "text": "EvaluateChooser(Context=CharacterPropertiesForCamera)",
        }])
        write_jsonl(self.output / "blueprint_data_dependencies.jsonl", [{
            "dependency_id": "dep:context",
            "blueprint_path": self.bp,
            "graph_id": self.graph,
            "graph_name": "RunCameraDirector",
            "sink_node_id": self.eval_node,
            "sink_operation": "evaluate_chooser",
            "sink_pin_id": "pin:context",
            "sink_pin_name": "ContextObject",
            "text": "Make S_CharacterPropertiesForCamera(CameraStyle=CameraStyle, CameraMode=CameraMode, MovementMode=MovementMode)",
            "expression_node_count": 4,
            "expression": {
                "operation": "make_struct",
                "label": "S_CharacterPropertiesForCamera",
                "inputs": [
                    {"pin": "CameraStyle", "literal": "Medium"},
                    {"pin": "CameraMode", "literal": "Aim"},
                    {"pin": "MovementMode", "literal": "OnGround"},
                ],
            },
            "function_calls": [],
            "object_refs": [],
        }])
        write_jsonl(self.output / "blueprint_pins.jsonl", [{
            "pin_id": "pin:context",
            "node_id": self.eval_node,
            "blueprint_path": self.bp,
            "graph_id": self.graph,
            "graph_name": "RunCameraDirector",
            "pin_index": 0,
            "name": "ContextObject",
            "direction": "input",
            "linked_count": 1,
            "default_value": "",
            "default_object": "",
            "default_text": "",
            "type": {"category": "struct"},
        }])
        write_jsonl(self.output / "blueprint_semantic_blocks.jsonl", [{
            "block_id": "block:0",
            "blueprint_path": self.bp,
            "graph_id": self.graph,
            "graph_name": "RunCameraDirector",
            "statement_count": 1,
            "text": "EvaluateChooser(Context=CharacterPropertiesForCamera)",
        }])

    def test_reports_chooser_evaluation_and_camera_property_dependencies(self) -> None:
        self._fixture()
        report = director_report.build_report(self.output, rows)
        self.assertEqual(len(report["directors"]), 1)
        self.assertEqual(len(report["director_chooser_links"]), 1)
        self.assertEqual(len(report["evaluation_nodes"]), 1)
        self.assertEqual(report["evaluation_nodes"][0]["node_id"], self.eval_node)
        self.assertEqual(len(report["relevant_dependencies"]), 1)
        self.assertIn("CameraStyle", report["relevant_dependencies"][0]["text"])
        self.assertIn("node:mode", {row["node_id"] for row in report["relevant_nodes"]})

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            director_report.print_report(report)
        text = buffer.getvalue()
        self.assertIn("[Chooser evaluation nodes]", text)
        self.assertIn("S_CharacterPropertiesForCamera", text)
        self.assertIn("CameraMode", text)
        self.assertIn("MovementMode", text)


if __name__ == "__main__":
    unittest.main()
