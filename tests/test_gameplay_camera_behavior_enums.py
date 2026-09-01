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

import uatool_gameplay_camera_behavior as behavior
import uatool_gameplay_camera_behavior_enums as behavior_enums

behavior_enums.install(behavior)


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


class GameplayCameraBehaviorEnumTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.camera_mode = "/Game/Data/E_CameraMode.E_CameraMode"
        self.rotation_mode = "/Game/Data/E_RotationMode.E_RotationMode"
        self.movement_mode = "/Game/Data/E_MovementMode.E_MovementMode"
        self.dep_id = "dep:return"
        self.provider_id = "camera_provider:test"
        self.raw_camera_field = "CameraMode_6_A59B5561435DC3553D7444B49C47015A"
        self.raw_movement_field = "MovementMode_29_9179014C47EBE85BE880F78CB6E2E69D"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> tuple[list[dict], list[dict], list[dict]]:
        write_jsonl(self.output / "blueprint_enum_entries.jsonl", [
            {"enum_path": self.camera_mode, "raw_name": "NewEnumerator0", "display_name": "FreeCam"},
            {"enum_path": self.camera_mode, "raw_name": "NewEnumerator1", "display_name": "Strafe"},
            {"enum_path": self.rotation_mode, "raw_name": "NewEnumerator0", "display_name": "OrientToMovement"},
            {"enum_path": self.rotation_mode, "raw_name": "NewEnumerator1", "display_name": "Strafe"},
            {"enum_path": self.movement_mode, "raw_name": "NewEnumerator4", "display_name": "OnGround"},
        ])
        write_jsonl(self.output / "blueprint_pins.jsonl", [
            {
                "node_id": "node:make",
                "name": self.raw_camera_field,
                "type": {"category": "byte", "subcategory_object": self.camera_mode},
            },
            {
                "node_id": "node:make",
                "name": self.raw_movement_field,
                "type": {"category": "byte", "subcategory_object": self.movement_mode},
            },
            {
                "node_id": "node:select",
                "name": "Index",
                "type": {"category": "byte", "subcategory_object": self.rotation_mode},
            },
            {
                "node_id": "node:select",
                "name": "NewEnumerator0",
                "type": {"category": "byte", "subcategory_object": self.camera_mode},
            },
            {
                "node_id": "node:select",
                "name": "NewEnumerator1",
                "type": {"category": "byte", "subcategory_object": self.camera_mode},
            },
        ])
        select_expression = {
            "kind": "expression",
            "operation": "select",
            "label": "Select",
            "node_id": "node:select",
            "output_pin": "ReturnValue",
            "inputs": [
                {"pin": "NewEnumerator0", "sources": [{"literal": "NewEnumerator0", "type": "byte"}]},
                {"pin": "NewEnumerator1", "sources": [{"literal": "NewEnumerator1", "type": "byte"}]},
                {"pin": "Index", "sources": [{"literal": "NewEnumerator0", "type": "byte"}]},
            ],
        }
        make_expression = {
            "kind": "expression",
            "operation": "make_struct",
            "label": "Make S_CharacterPropertiesForCamera",
            "node_id": "node:make",
            "inputs": [
                {"pin": self.raw_camera_field, "sources": [select_expression]},
                {"pin": self.raw_movement_field, "sources": [{"literal": "NewEnumerator4", "type": "byte"}]},
            ],
        }
        write_jsonl(self.output / "blueprint_data_dependencies.jsonl", [{
            "dependency_id": self.dep_id,
            "expression": make_expression,
        }])

        providers = [{
            "provider_id": self.provider_id,
            "schema_version": 1,
            "director_blueprint_path": "/Game/Cameras/Director.Director",
            "interface_blueprint_path": "/Game/BPI.BPI",
            "call_id": "call:test",
            "provider_blueprint_path": "/Game/BP_Mover.BP_Mover",
            "function_id": "graph:get-camera",
            "function_name": "Get_PropertiesForCamera",
            "implementation_kind": "implements_interface",
            "return_struct_type": "/Game/Data/S_CharacterPropertiesForCamera.S_CharacterPropertiesForCamera",
            "return_dependency_count": 1,
            "field_count": 2,
            "fully_modeled": True,
        }]
        fields = [
            {
                "field_id": "field:camera-mode",
                "provider_id": self.provider_id,
                "provider_blueprint_path": "/Game/BP_Mover.BP_Mover",
                "function_id": "graph:get-camera",
                "dependency_id": self.dep_id,
                "field_index": 0,
                "field_name": "CameraMode",
                "raw_field_name": self.raw_camera_field,
                "expression_text": "raw",
                "literal_values": ["NewEnumerator0", "NewEnumerator1"],
                "expression": select_expression,
            },
            {
                "field_id": "field:movement-mode",
                "provider_id": self.provider_id,
                "provider_blueprint_path": "/Game/BP_Mover.BP_Mover",
                "function_id": "graph:get-camera",
                "dependency_id": self.dep_id,
                "field_index": 1,
                "field_name": "MovementMode",
                "raw_field_name": self.raw_movement_field,
                "expression_text": "raw",
                "literal_values": ["NewEnumerator4"],
                "expression": {"literal": "NewEnumerator4", "type": "byte"},
            },
        ]
        return providers, fields, []

    def test_decodes_selector_values_and_parent_typed_literal_without_rewriting_raw_expression(self) -> None:
        providers, fields, inputs = self._fixture()
        providers, fields, inputs = behavior_enums.decorate(self.output, providers, fields, inputs)
        self.assertEqual(inputs, [])
        self.assertEqual(providers[0]["schema_version"], 2)
        self.assertTrue(providers[0]["fully_decoded"])

        by_name = {row["field_name"]: row for row in fields}
        camera = by_name["CameraMode"]
        movement = by_name["MovementMode"]

        self.assertEqual(camera["schema_version"], 2)
        self.assertNotIn("NewEnumerator", camera["expression_text"])
        self.assertIn("OrientToMovement=FreeCam", camera["expression_text"])
        self.assertIn("Strafe=Strafe", camera["expression_text"])
        self.assertIn("Index=OrientToMovement", camera["expression_text"])
        self.assertEqual(camera["raw_literal_values"], ["NewEnumerator0", "NewEnumerator1"])
        self.assertEqual(camera["literal_values"], ["FreeCam", "OrientToMovement", "Strafe"])
        self.assertTrue(camera["enum_literals_fully_decoded"])
        self.assertEqual(camera["expression"]["inputs"][0]["sources"][0]["literal"], "NewEnumerator0")

        self.assertEqual(movement["expression_text"], "OnGround")
        self.assertEqual(movement["raw_literal_values"], ["NewEnumerator4"])
        self.assertEqual(movement["literal_values"], ["OnGround"])
        self.assertTrue(movement["enum_literals_fully_decoded"])
        self.assertEqual(movement["expression"]["literal"], "NewEnumerator4")


if __name__ == "__main__":
    unittest.main()
