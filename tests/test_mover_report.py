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

import uatool_mover_report as mover_report


class MoverReportTest(unittest.TestCase):
    def test_report_selects_mover_components_and_authored_properties(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            blueprints = [
                {
                    "object_path": "/Game/BP_Mover.BP_Mover",
                    "parent_class": "/Script/Engine.Character",
                    "components": [
                        {
                            "variable_name": "CharacterMover",
                            "component_class": "/Script/Mover.CharacterMoverComponent",
                            "is_root": False,
                        },
                        {
                            "variable_name": "Mesh",
                            "component_class": "/Script/Engine.SkeletalMeshComponent",
                            "is_root": False,
                        },
                    ],
                },
                {
                    "object_path": "/Game/BP_Mode.BP_Mode",
                    "parent_class": "/Script/Mover.BaseMovementMode",
                    "components": [],
                },
            ]
            component_properties = [
                {
                    "blueprint_path": "/Game/BP_Mover.BP_Mover",
                    "component_name": "CharacterMover",
                    "property_name": "MovementModes",
                    "property_path": "MovementModes[Walking]",
                    "cpp_type": "TMap<FName,TObjectPtr<UBaseMovementMode>>",
                    "referenced_object_path": "/Game/BP_Mode.BP_Mode_C:Walking",
                    "referenced_object_class": "/Script/Mover.WalkingMode",
                },
                {
                    "blueprint_path": "/Game/BP_Mover.BP_Mover",
                    "component_name": "Mesh",
                    "property_name": "MoverDebugLabel",
                    "property_path": "MoverDebugLabel",
                    "cpp_type": "FString",
                    "value": "mentions Mover but is not a Mover class",
                },
            ]

            def write(name: str, rows: list[dict]) -> None:
                with (output / name).open("w", encoding="utf-8") as handle:
                    for row in rows:
                        handle.write(json.dumps(row) + "\n")

            write("blueprints.jsonl", blueprints)
            write("blueprint_component_properties.jsonl", component_properties)
            for name in (
                "blueprint_node_references.jsonl",
                "blueprint_defaults.jsonl",
                "blueprint_state_values.jsonl",
                "world_components.jsonl",
                "world_instance_properties.jsonl",
                "world_references.jsonl",
            ):
                write(name, [])

            def rows(path: Path):
                with path.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        yield json.loads(line)

            report = mover_report.build_report(output, rows)
            self.assertEqual(len(report["mover_components"]), 1)
            self.assertEqual(report["mover_components"][0]["variable_name"], "CharacterMover")
            self.assertEqual(len(report["mover_blueprints"]), 1)
            self.assertEqual(report["mover_blueprints"][0]["object_path"], "/Game/BP_Mode.BP_Mode")
            self.assertEqual(len(report["component_properties"]), 1)
            self.assertEqual(report["component_properties"][0]["property_path"], "MovementModes[Walking]")
            self.assertNotIn("MoverDebugLabel", report["property_roots"])
            self.assertEqual(report["referenced_classes"]["/Script/Mover.WalkingMode"], 1)

    def test_type_matching_requires_script_mover_namespace(self) -> None:
        self.assertTrue(mover_report._is_mover_type("/Script/Mover.CharacterMoverComponent"))
        self.assertTrue(mover_report._is_mover_type("/Script/ChaosMover.ChaosMoverComponent"))
        self.assertFalse(mover_report._is_mover_type("/Game/Mover/BP_Mover.BP_Mover_C"))
        self.assertFalse(mover_report._is_mover_type("/Script/Engine.CharacterMovementComponent"))


if __name__ == "__main__":
    unittest.main()
