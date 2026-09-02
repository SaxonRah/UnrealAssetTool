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

import uatool_ai_perception_capture as capture


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


class AIPerceptionCaptureTest(unittest.TestCase):
    def test_discovers_only_corpus_proven_blueprint_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_jsonl(root / "blueprints.jsonl", [
                {
                    "object_path": "/Game/AI/BP_AIController.BP_AIController",
                    "components": [{"component_class": "/Script/AIModule.AIPerceptionComponent"}],
                },
                {
                    "object_path": "/Game/Player/PlayerCharacter.PlayerCharacter",
                    "components": [{"component_class": "/Script/AIModule.AIPerceptionStimuliSourceComponent"}],
                },
                {
                    "object_path": "/Game/Other/BP_Other.BP_Other",
                    "components": [{"component_class": "/Script/Engine.SceneComponent"}],
                },
            ])
            write_jsonl(root / "blueprint_state_values.jsonl", [])
            write_jsonl(root / "blueprint_component_properties.jsonl", [])
            self.assertEqual(capture._discover_focus_assets(root), [
                "/Game/AI/BP_AIController.BP_AIController",
                "/Game/Player/PlayerCharacter.PlayerCharacter",
            ])

    def test_capture_validation_round_trips_template_and_config_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            focus = ["/Game/AI/BP_AIController.BP_AIController", "/Game/Player/PlayerCharacter.PlayerCharacter"]
            (root / "ai_perception_focus_assets.txt").write_text("".join(value + "\n" for value in focus), encoding="utf-8")
            write_jsonl(root / "ai_perception_assets.jsonl", [
                {"asset_path": focus[0], "loaded": True, "is_blueprint": True},
                {"asset_path": focus[1], "loaded": True, "is_blueprint": True},
            ])
            objects = [
                {"source_path": focus[0], "object_path": focus[0] + "_C:AIPerception", "object_kind": "perception_component_template", "object_class": "/Script/AIModule.AIPerceptionComponent"},
                {"source_path": focus[0], "object_path": focus[0] + "_C:AIPerception.AISenseConfig_Sight_0", "object_kind": "sense_config", "object_class": "/Script/AIModule.AISenseConfig_Sight"},
                {"source_path": focus[1], "object_path": focus[1] + "_C:Stimuli", "object_kind": "stimuli_source_component_template", "object_class": "/Script/AIModule.AIPerceptionStimuliSourceComponent"},
            ]
            write_jsonl(root / "ai_perception_objects.jsonl", objects)
            write_jsonl(root / "ai_perception_properties.jsonl", [{
                "source_path": focus[0], "owner_path": objects[1]["object_path"], "root_property": "SightRadius", "property_path": "SightRadius", "differs_from_class_default": True, "truncated": False,
            }])
            write_jsonl(root / "ai_perception_references.jsonl", [{
                "source_path": focus[0], "owner_path": objects[0]["object_path"], "property_path": "DominantSense", "target_path": "/Script/AIModule.AISense_Sight",
            }])
            manifest = {
                "schema_version": 1,
                "success": True,
                "diagnostic_only": True,
                "semantic_promotion": False,
                "runtime_state_captured": False,
                "counts": {
                    "focus_assets": 2,
                    "loaded_assets": 2,
                    "blueprint_assets": 2,
                    "perception_components": 1,
                    "stimuli_source_components": 1,
                    "sense_configs": 1,
                    "objects": 3,
                    "properties": 1,
                    "references": 1,
                    "truncated_properties": 0,
                },
            }
            (root / "ai_perception_capture_manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
            self.assertEqual(capture._validate_capture(root), manifest)
            report = capture._semantic_report(root, manifest)
            self.assertIn("perception_component_templates: 1", report)
            self.assertIn("sense_configs: 1", report)
            self.assertIn("PASS: nested AISenseConfig UObject state", report)
            self.assertIn("runtime_state_captured: False", report)

    def test_native_capture_is_reflection_first_without_aimodule_dependency(self) -> None:
        source = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolAIPerceptionCommandlet.cpp").read_text(encoding="utf-8")
        build = (ROOT / "Source/UnrealAssetTool/UnrealAssetTool.Build.cs").read_text(encoding="utf-8")
        header = (ROOT / "Source/UnrealAssetTool/Public/UnrealAssetToolAIPerceptionCommandlet.h").read_text(encoding="utf-8")
        self.assertIn("ClassInheritsName", source)
        self.assertIn('TEXT("AIPerceptionComponent")', source)
        self.assertIn('TEXT("AIPerceptionStimuliSourceComponent")', source)
        self.assertIn('TEXT("AISenseConfig")', source)
        self.assertIn("GetObjectsWithOuter", source)
        self.assertIn("differs_from_class_default", source)
        self.assertIn("FocusFile=", source)
        self.assertIn("UUnrealAssetToolAIPerceptionCommandlet", header)
        self.assertNotIn('"AIModule"', build)
        self.assertNotIn('#include "Perception/', source)

    def test_canonical_launcher_wires_focused_capture(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("uatool_ai_perception_capture", facade)
        self.assertIn("_ai_perception_capture.install(_runtime)", facade)


if __name__ == "__main__":
    unittest.main()
