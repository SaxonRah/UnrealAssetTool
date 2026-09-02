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

import uatool_gas_capture as gas_capture


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


class GASCaptureTest(unittest.TestCase):
    def test_validation_accepts_diagnostic_authored_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            assets = [{
                "asset_path": "/Game/Abilities/GA_Test.GA_Test",
                "package_name": "/Game/Abilities/GA_Test",
                "asset_name": "GA_Test",
                "asset_class": "/Script/Engine.Blueprint",
                "parent_class_tag": "/Script/GameplayAbilities.GameplayAbility",
                "native_parent_class_tag": "/Script/GameplayAbilities.GameplayAbility",
                "generated_class_tag": "/Game/Abilities/GA_Test.GA_Test_C",
                "loaded_object_class": "/Script/Engine.Blueprint",
                "generated_class": "/Game/Abilities/GA_Test.GA_Test_C",
                "gas_kind": "gameplay_ability",
                "loaded": True,
            }]
            classes = [{
                "class_path": "/Game/Abilities/GA_Test.GA_Test_C",
                "class_name": "GA_Test_C",
                "super_class": "/Script/GameplayAbilities.GameplayAbility",
                "gas_kind": "gameplay_ability",
                "native": False,
                "cdo_path": "/Game/Abilities/GA_Test.Default__GA_Test_C",
            }]
            properties = [{
                "source_path": assets[0]["asset_path"],
                "owner_path": "/Game/Abilities/GA_Test.Default__GA_Test_C",
                "owner_kind": "blueprint_cdo",
                "gas_kind": "gameplay_ability",
                "owner_class": classes[0]["class_path"],
                "declaring_type": "/Script/GameplayAbilities.GameplayAbility",
                "property_name": "CostGameplayEffectClass",
                "property_type": "ClassProperty",
                "cpp_type": "TSubclassOf<UGameplayEffect>",
                "value": "/Game/Effects/GE_Cost.GE_Cost_C",
                "truncated": False,
            }]
            references = [{
                "source_path": assets[0]["asset_path"],
                "owner_path": "/Game/Abilities/GA_Test.Default__GA_Test_C",
                "owner_kind": "blueprint_cdo",
                "gas_kind": "gameplay_ability",
                "root_property": "CostGameplayEffectClass",
                "property_path": "CostGameplayEffectClass",
                "reference_kind": "hard_object",
                "target_path": "/Game/Effects/GE_Cost.GE_Cost_C",
                "target_class": "/Script/CoreUObject.Class",
            }]
            write_jsonl(output / "gas_assets.jsonl", assets)
            write_jsonl(output / "gas_classes.jsonl", classes)
            write_jsonl(output / "gas_properties.jsonl", properties)
            write_jsonl(output / "gas_references.jsonl", references)
            (output / "gas_capture_manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "schema_name": "gas_capture",
                "success": True,
                "diagnostic_only": True,
                "semantic_promotion": False,
                "runtime_state_captured": False,
                "counts": {
                    "assets_considered": 100,
                    "candidate_assets": 1,
                    "loaded_assets": 1,
                    "gas_assets": 1,
                    "gas_classes": 1,
                    "gas_properties": 1,
                    "gas_references": 1,
                    "nested_objects": 0,
                    "truncated_properties": 0,
                },
            }) + "\n", encoding="utf-8")

            manifest = gas_capture._validate_capture(output)
            self.assertTrue(manifest["diagnostic_only"])
            report = gas_capture._semantic_report(output, manifest)
            self.assertIn("runtime_state_captured: False", report)
            self.assertIn("gameplay_ability", report)
            self.assertIn("CostGameplayEffectClass", report)

    def test_validation_rejects_runtime_state_claim(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            for filename in gas_capture.CAPTURE_FILES[1:]:
                (output / filename).write_text("", encoding="utf-8")
            (output / "gas_capture_manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "success": True,
                "diagnostic_only": True,
                "semantic_promotion": False,
                "runtime_state_captured": True,
                "counts": {
                    "candidate_assets": 0,
                    "loaded_assets": 0,
                    "gas_assets": 0,
                    "gas_classes": 0,
                    "gas_properties": 0,
                    "gas_references": 0,
                    "truncated_properties": 0,
                },
            }) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "runtime_state_captured=false"):
                gas_capture._validate_capture(output)

    def test_native_commandlet_is_reflection_first_and_closes_before_manifest(self) -> None:
        cpp = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolGASCommandlet.cpp").read_text(encoding="utf-8")
        build = (ROOT / "Source/UnrealAssetTool/UnrealAssetTool.Build.cs").read_text(encoding="utf-8")
        self.assertIn("Registry.SearchAllAssets(true)", cpp)
        self.assertIn("ContainsCandidateAnchor(Metadata)", cpp)
        self.assertIn("Asset.GetAsset()", cpp)
        self.assertIn("TObjectIterator<UClass>", cpp)
        self.assertIn("runtime_state_captured", cpp)
        self.assertIn("Writers.Close()", cpp)
        self.assertLess(cpp.index("Writers.Close()"), cpp.index("WriteManifest(OutputDir"))
        self.assertNotIn('#include "Abilities/', cpp)
        self.assertNotIn('#include "AbilitySystemComponent.h"', cpp)
        self.assertNotIn('"GameplayAbilities"', build)

    def test_launcher_explicitly_skips_normal_scan_and_derive(self) -> None:
        text = (SCRIPTS / "uatool_gas_capture.py").read_text(encoding="utf-8")
        self.assertIn('"-run=UnrealAssetToolGAS"', text)
        self.assertIn('print("normal project scan was not run")', text)
        self.assertIn('print("derive was not run")', text)
        self.assertNotIn("derive_output(", text)


if __name__ == "__main__":
    unittest.main()
