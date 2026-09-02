from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_gas as gas


class SystemsGASRealCorpusRegressionTest(unittest.TestCase):
    def test_blueprint_identity_does_not_guess_semantic_type_from_names(self) -> None:
        ability = {
            "ability_path": "/Game/Weapons/Pistol/GA_Weapon_Reload_Pistol.GA_Weapon_Reload_Pistol",
            "package_name": "/Game/Weapons/Pistol/GA_Weapon_Reload_Pistol",
            "generated_class": "/Game/Weapons/Pistol/GA_Weapon_Reload_Pistol.GA_Weapon_Reload_Pistol_C",
            "parent_class": "/Game/Weapons/GA_Weapon_ReloadMagazine.GA_Weapon_ReloadMagazine_C",
            "cdo_path": "/Game/Weapons/Pistol/GA_Weapon_Reload_Pistol.Default__GA_Weapon_Reload_Pistol_C",
        }
        effect = {
            "gameplay_effect_path": "/TopDownArena/Game/Pickups/GE_AdditionalHeart.GE_AdditionalHeart",
            "package_name": "/TopDownArena/Game/Pickups/GE_AdditionalHeart",
            "generated_class": "/TopDownArena/Game/Pickups/GE_AdditionalHeart.GE_AdditionalHeart_C",
            "parent_class": "/TopDownArena/Game/Pickups/GET_ArenaPickup_Base.GET_ArenaPickup_Base_C",
            "cdo_path": "/TopDownArena/Game/Pickups/GE_AdditionalHeart.Default__GE_AdditionalHeart_C",
        }
        self.assertIsNone(gas._blueprint_identity_error(ability, "ability_path", "GAS ability"))
        self.assertIsNone(gas._blueprint_identity_error(effect, "gameplay_effect_path", "GAS GameplayEffect"))

    def test_blueprint_identity_rejects_wrong_generated_class(self) -> None:
        row = {
            "ability_path": "/Game/Abilities/GA_Test.GA_Test",
            "package_name": "/Game/Abilities/GA_Test",
            "generated_class": "/Game/Abilities/GA_Test.NotTheGeneratedClass_C",
            "parent_class": "/Script/LyraGame.LyraGameplayAbility",
            "cdo_path": "/Game/Abilities/GA_Test.Default__GA_Test_C",
        }
        self.assertIn(
            "generated class mismatch",
            gas._blueprint_identity_error(row, "ability_path", "GAS ability") or "",
        )

    def test_native_policy_uses_real_inheritance_and_project_module_scope(self) -> None:
        policy = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsGASPolicy.inl"
        ).read_text(encoding="utf-8")
        scanner = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp"
        ).read_text(encoding="utf-8")

        self.assertIn("AssetInSystemsScope(", policy)
        self.assertIn("Asset.GetAsset()", policy)
        self.assertIn("GASWriteAbility(Blueprint", policy)
        self.assertIn("GASWriteGameplayEffect(Blueprint", policy)
        self.assertIn("GASWriteGameplayCue(Blueprint", policy)
        self.assertNotIn("GASBlueprintMetadataCandidate(Asset)", policy)

        self.assertIn("FModuleManager::Get().GetModuleFilename", policy)
        self.assertIn("FPackageName::DoesPackageExist", policy)
        self.assertIn("IsInsideDirectory(OwnerFilename, ProjectDir)", policy)
        self.assertIn("IsInsideDirectory(OwnerFilename, ToolPluginDir)", policy)
        self.assertIn("GASClassInSystemsScope(", policy)

        self.assertIn('#include "UnrealAssetToolSystemsGASPolicy.inl"', scanner)
        self.assertIn("#define ScanGASProjectModel ScanGASProjectModelPolicy", scanner)
        self.assertIn("#undef ScanGASProjectModel", scanner)


if __name__ == "__main__":
    unittest.main()
