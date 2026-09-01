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


class GameplayCameraDirectorInterfaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.director = "/Game/Cameras/CameraDirector.CameraDirector"
        self.interface = "/Game/Blueprints/BPI_SandboxCharacter_Pawn.BPI_SandboxCharacter_Pawn"
        self.interface_class = "/Game/Blueprints/BPI_SandboxCharacter_Pawn.BPI_SandboxCharacter_Pawn_C"
        self.impl = "/Game/Blueprints/SandboxCharacter_Mover.SandboxCharacter_Mover"
        self.impl_graph = "graph:get-camera"
        self.call_node = "node:get-camera"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> None:
        write_jsonl(self.output / "blueprints.jsonl", [
            {
                "object_path": self.director,
                "parent_class": "/Script/GameplayCameras.BlueprintCameraDirectorEvaluator",
                "generated_class": self.director + "_C",
                "implemented_interfaces": [],
            },
            {
                "object_path": self.impl,
                "parent_class": "/Script/Engine.Character",
                "generated_class": self.impl + "_C",
                "implemented_interfaces": [{"interface_class": self.interface_class}],
            },
        ])
        write_jsonl(self.output / "blueprint_relations.jsonl", [])
        write_jsonl(self.output / "chooser_tables.jsonl", [])
        write_jsonl(self.output / "blueprint_semantic_nodes.jsonl", [])
        write_jsonl(self.output / "blueprint_pins.jsonl", [])
        write_jsonl(self.output / "blueprint_semantic_blocks.jsonl", [])
        write_jsonl(self.output / "blueprint_functions.jsonl", [{
            "function_id": self.impl_graph,
            "blueprint_path": self.impl,
            "graph_id": self.impl_graph,
            "graph_name": "Get_PropertiesForCamera",
            "name": "Get_PropertiesForCamera",
            "resolved_function": self.interface_class + ":Get_PropertiesForCamera",
            "result_node_ids": ["node:return"],
            "outputs": [{"name": "ReturnValue", "type": {"category": "struct"}}],
        }])
        write_jsonl(self.output / "blueprint_call_edges.jsonl", [{
            "call_id": self.call_node,
            "call_node_id": self.call_node,
            "blueprint_path": self.director,
            "graph_id": "graph:director",
            "graph_name": "EventGraph",
            "target_function": self.interface_class + ":Get_PropertiesForCamera",
            "target_name": "Get_PropertiesForCamera",
            "target_owner": "/Game/Blueprints/BPI_SandboxCharacter_Pawn.SKEL_BPI_SandboxCharacter_Pawn_C",
            "target_blueprint_path": self.interface,
            "target_function_id": "",
            "resolution": "external",
            "candidate_count": 0,
            "candidate_function_ids": [],
            "interface_call": True,
        }])
        write_jsonl(self.output / "blueprint_semantic_statements.jsonl", [{
            "statement_id": "stmt:return",
            "node_id": "node:return",
            "blueprint_path": self.impl,
            "graph_id": self.impl_graph,
            "graph_name": "Get_PropertiesForCamera",
            "block_id": "block:return",
            "block_position": 1,
            "operation": "function_result",
            "text": "return ReturnValue=Make S_CharacterPropertiesForCamera(CameraMode=Aim, MovementMode=OnGround)",
        }])
        write_jsonl(self.output / "blueprint_data_dependencies.jsonl", [{
            "dependency_id": "dep:return",
            "blueprint_path": self.impl,
            "graph_id": self.impl_graph,
            "graph_name": "Get_PropertiesForCamera",
            "sink_node_id": "node:return",
            "sink_operation": "function_result",
            "sink_pin_id": "pin:return",
            "sink_pin_name": "ReturnValue",
            "text": "Make S_CharacterPropertiesForCamera(CameraMode=Aim, MovementMode=OnGround, Gait=Run, Stance=Stand)",
            "expression": {"kind": "expression", "operation": "make_struct", "label": "S_CharacterPropertiesForCamera"},
            "function_calls": [],
            "object_refs": [],
        }])

    def test_traces_dynamic_interface_call_to_implementation_candidates(self) -> None:
        self._fixture()
        report = director_report.build_report(self.output, rows)
        self.assertEqual(len(report["camera_property_calls"]), 1)
        self.assertEqual(len(report["implementation_candidates"]), 1)
        candidate = report["implementation_candidates"][0]
        self.assertEqual(candidate["blueprint_path"], self.impl)
        self.assertEqual(candidate["implementation_kind"], "implements_interface")
        self.assertEqual(candidate["interface_blueprint_path"], self.interface)
        self.assertEqual(candidate["dependencies"][0]["dependency_id"], "dep:return")
        self.assertIn("MovementMode=OnGround", candidate["dependencies"][0]["text"])

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            director_report.print_report(report)
        text = buffer.getvalue()
        self.assertIn("[Camera property interface calls]", text)
        self.assertIn("[Get_PropertiesForCamera implementation candidates]", text)
        self.assertIn("SandboxCharacter_Mover", text)
        self.assertIn("MovementMode=OnGround", text)


if __name__ == "__main__":
    unittest.main()
