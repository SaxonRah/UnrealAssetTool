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

import uatool_gameplay_camera_report as report


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


class GameplayCameraReportTest(unittest.TestCase):
    def test_collects_registry_component_and_reference_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            bp = "/Game/BP_CameraUser.BP_CameraUser"
            camera_asset = "/Game/Cameras/CA_Test.CA_Test"

            write_jsonl(out / "assets.jsonl", [
                {
                    "object_path": camera_asset,
                    "class_path": "/Script/GameplayCameras.CameraAsset",
                    "package_name": "/Game/Cameras/CA_Test",
                },
                {
                    "object_path": "/Game/Other.Other",
                    "class_path": "/Script/Engine.Texture2D",
                },
            ])
            write_jsonl(out / "blueprints.jsonl", [
                {
                    "object_path": bp,
                    "components": [
                        {
                            "variable_name": "GameplayCamera",
                            "component_class": "/Script/GameplayCameras.GameplayCameraComponent",
                            "parent_component_or_variable": "",
                            "is_root": False,
                        }
                    ],
                }
            ])
            write_jsonl(out / "blueprint_component_properties.jsonl", [
                {
                    "blueprint_path": bp,
                    "component_name": "GameplayCamera",
                    "property_name": "CameraReference",
                    "value": "CameraAsset=/Script/GameplayCameras.CameraAsset'/Game/Cameras/CA_Test.CA_Test'",
                },
                {
                    "blueprint_path": bp,
                    "component_name": "GameplayCamera",
                    "property_name": "bRunInEditor",
                    "value": "False",
                },
            ])
            write_jsonl(out / "systems_references.jsonl", [
                {
                    "asset_path": camera_asset,
                    "owner_path": camera_asset,
                    "root_property": "CameraDirector",
                    "property_path": "CameraDirector",
                    "target_path": camera_asset + ":Director",
                    "target_class": "/Script/GameplayCameras.SingleCameraDirector",
                }
            ])

            built = report.build_report(out, rows)
            self.assertEqual(len(built["assets"]), 1)
            self.assertEqual(len(built["components"]), 1)
            self.assertEqual(len(built["component_properties"]), 2)
            self.assertEqual(len(built["systems_references"]), 1)
            self.assertEqual(
                built["asset_classes"]["/Script/GameplayCameras.CameraAsset"],
                1,
            )
            self.assertEqual(
                built["component_classes"]["/Script/GameplayCameras.GameplayCameraComponent"],
                1,
            )

            stream = io.StringIO()
            with redirect_stdout(stream):
                report.print_report(built)
            text = stream.getvalue()
            self.assertIn("GAMEPLAY CAMERAS EVIDENCE REPORT", text)
            self.assertIn("CA_Test.CA_Test", text)
            self.assertIn("GameplayCamera", text)
            self.assertIn("SingleCameraDirector", text)


if __name__ == "__main__":
    unittest.main()
