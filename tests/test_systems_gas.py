from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_gas as gas


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def valid_rows() -> dict[str, list[dict]]:
    ability = "/Game/Abilities/GA_Test.GA_Test"
    ability_set = "/Game/AbilitySets/AS_Test.AS_Test"
    effect = "/Game/Effects/GE_Test.GE_Test"
    cue = "/Game/Cues/GC_Test.GC_Test"
    attribute_set = "/Script/TestGame.TestAttributeSet"
    return {
        "gas_abilities.jsonl": [{
            "ability_path": ability,
            "package_name": "/Game/Abilities/GA_Test",
            "generated_class": "/Game/Abilities/GA_Test.GA_Test_C",
            "parent_class": "/Script/GameplayAbilities.GameplayAbility",
            "cdo_path": "/Game/Abilities/GA_Test.Default__GA_Test_C",
            "activation_policy": "OnInputTriggered",
            "activation_group": "Independent",
            "replication_policy": "ReplicateNo",
            "instancing_policy": "InstancedPerActor",
            "net_execution_policy": "LocalPredicted",
            "net_security_policy": "ClientOrServer",
            "ability_tags": "",
            "cancel_abilities_with_tag": "",
            "block_abilities_with_tag": "",
            "activation_owned_tags": "",
            "activation_required_tags": "",
            "activation_blocked_tags": "",
            "source_required_tags": "",
            "source_blocked_tags": "",
            "target_required_tags": "",
            "target_blocked_tags": "",
            "cost_gameplay_effect_class": "/Game/Effects/GE_Test.GE_Test_C",
            "cooldown_gameplay_effect_class": "",
            "trigger_count": 1,
            "additional_cost_count": 1,
        }],
        "gas_ability_triggers.jsonl": [{
            "ability_path": ability, "trigger_index": 0, "trigger_tag": "GameplayEvent.Test",
            "trigger_source": "GameplayEvent", "raw_value": "(...)" , "truncated": False,
        }],
        "gas_ability_costs.jsonl": [{
            "ability_path": ability, "cost_index": 0, "cost_path": "/Game/Abilities/GA_Test.Default__GA_Test_C:Cost",
            "cost_class": "/Script/TestGame.TestAbilityCost", "raw_value": "Cost", "truncated": False,
        }],
        "gas_ability_sets.jsonl": [{
            "ability_set_path": ability_set, "package_name": "/Game/AbilitySets/AS_Test",
            "class_path": "/Script/LyraGame.LyraAbilitySet", "ability_count": 1,
            "gameplay_effect_count": 1, "attribute_set_count": 1,
        }],
        "gas_ability_set_abilities.jsonl": [{
            "ability_set_path": ability_set, "grant_index": 0,
            "ability_class": "/Game/Abilities/GA_Test.GA_Test_C", "input_tag": "InputTag.Test",
            "raw_value": "AbilityGrant", "truncated": False,
        }],
        "gas_ability_set_effects.jsonl": [{
            "ability_set_path": ability_set, "grant_index": 0,
            "gameplay_effect_class": "/Game/Effects/GE_Test.GE_Test_C",
            "raw_value": "EffectGrant", "truncated": False,
        }],
        "gas_ability_set_attributes.jsonl": [{
            "ability_set_path": ability_set, "grant_index": 0,
            "attribute_set_class": attribute_set, "raw_value": "AttributeGrant", "truncated": False,
        }],
        "gas_gameplay_effects.jsonl": [{
            "gameplay_effect_path": effect, "package_name": "/Game/Effects/GE_Test",
            "generated_class": "/Game/Effects/GE_Test.GE_Test_C",
            "parent_class": "/Script/GameplayAbilities.GameplayEffect",
            "cdo_path": "/Game/Effects/GE_Test.Default__GE_Test_C",
            "duration_policy": "Instant", "duration_magnitude": "", "period": "",
            "execute_periodic_on_application": "False", "periodic_inhibition_policy": "NeverReset",
            "effect_tags": "", "owned_tags": "", "blocked_ability_tags": "",
            "ongoing_tag_requirements": "", "application_tag_requirements": "",
            "removal_tag_requirements": "", "stacking_type": "None", "stack_limit_count": "0",
            "component_count": 1, "modifier_count": 1, "execution_count": 1, "cue_count": 1,
        }],
        "gas_gameplay_effect_components.jsonl": [{
            "gameplay_effect_path": effect, "component_index": 0,
            "component_path": "/Game/Effects/GE_Test.Default__GE_Test_C:AssetTags",
            "component_class": "/Script/GameplayAbilities.AssetTagsGameplayEffectComponent",
            "asset_tags": "", "target_tags": "",
        }],
        "gas_gameplay_effect_modifiers.jsonl": [{
            "gameplay_effect_path": effect, "modifier_index": 0, "attribute_name": "Health",
            "attribute_owner_class": attribute_set, "modifier_op": "Additive", "magnitude": "1.0",
            "raw_value": "Modifier", "truncated": False,
        }],
        "gas_gameplay_effect_executions.jsonl": [{
            "gameplay_effect_path": effect, "execution_index": 0,
            "calculation_class": "/Script/TestGame.TestExecution", "modifier_count": 1,
            "passed_in_tags": "", "raw_value": "Execution", "truncated": False,
        }],
        "gas_gameplay_effect_execution_modifiers.jsonl": [{
            "gameplay_effect_path": effect, "execution_index": 0, "modifier_index": 0,
            "attribute_name": "Health", "attribute_owner_class": attribute_set,
            "snapshot": "False", "modifier_op": "Additive", "magnitude": "1.0",
            "raw_value": "ExecutionModifier", "truncated": False,
        }],
        "gas_gameplay_effect_cues.jsonl": [{
            "gameplay_effect_path": effect, "cue_index": 0,
            "gameplay_cue_tags": "GameplayCue.Test", "magnitude_attribute_name": "Health",
            "magnitude_attribute_owner_class": attribute_set, "min_level": "0", "max_level": "0",
            "raw_value": "Cue", "truncated": False,
        }],
        "gas_gameplay_cues.jsonl": [{
            "gameplay_cue_path": cue, "package_name": "/Game/Cues/GC_Test",
            "generated_class": "/Game/Cues/GC_Test.GC_Test_C",
            "parent_class": "/Script/GameplayAbilities.GameplayCueNotify_Burst",
            "cdo_path": "/Game/Cues/GC_Test.Default__GC_Test_C",
            "gameplay_cue_tag": "GameplayCue.Test", "gameplay_cue_name": "GameplayCue.Test",
            "is_override": "False",
        }],
        "gas_attribute_sets.jsonl": [{
            "attribute_set_class": attribute_set,
            "super_class": "/Script/GameplayAbilities.AttributeSet",
            "module_package": "/Script/TestGame",
            "cdo_path": "/Script/TestGame.Default__TestAttributeSet",
            "native": True, "attribute_count": 1,
        }],
        "gas_attributes.jsonl": [{
            "attribute_set_class": attribute_set, "attribute_index": 0,
            "attribute_name": "Health", "cpp_type": "FGameplayAttributeData",
            "base_value": "100.0", "current_value": "100.0",
        }],
    }


class SystemsGASTest(unittest.TestCase):
    def _write(self, root: Path, data: dict[str, list[dict]]) -> None:
        for filename in gas.GAS_FILES:
            write_jsonl(root / filename, data.get(filename, []))

    def test_valid_schema6_rows_validate_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = valid_rows()
            self._write(root, data)
            self.assertIsNone(gas.validation_error(root))
            conn = sqlite3.connect(":memory:")
            gas.create_schema(conn)
            gas.load_database(conn, root)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM gas_abilities").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM gas_gameplay_effects").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM gas_attributes").fetchone()[0], 1)

    def test_dangling_child_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = valid_rows()
            data["gas_ability_triggers.jsonl"][0]["ability_path"] = "/Game/Missing.Missing"
            self._write(root, data)
            self.assertIn("unknown parent", gas.validation_error(root) or "")

    def test_noncontiguous_and_truncated_structured_rows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = valid_rows()
            data["gas_gameplay_effect_modifiers.jsonl"][0]["modifier_index"] = 1
            self._write(root, data)
            self.assertIn("not contiguous", gas.validation_error(root) or "")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            data = valid_rows()
            data["gas_gameplay_effect_cues.jsonl"][0]["truncated"] = True
            self._write(root, data)
            self.assertIn("truncated", gas.validation_error(root) or "")

    def test_installer_promotes_schema_and_appends_raw_files(self) -> None:
        fake = types.SimpleNamespace(
            SYSTEMS_SCHEMA_VERSION=5,
            JSONL_FILES=("systems_assets.jsonl",),
            RAW_FILES=("systems_manifest.json", "systems_assets.jsonl"),
            create_schema=lambda conn: None,
            validation_error=lambda output: None,
            load_database=lambda conn, output, rows=None: None,
            query=lambda conn, print_rows, pattern, limit: None,
            _rows=gas._read_rows,
        )
        gas.install(fake)
        self.assertEqual(fake.SYSTEMS_SCHEMA_VERSION, 6)
        self.assertTrue(set(gas.GAS_FILES).issubset(fake.JSONL_FILES))
        self.assertTrue(set(gas.GAS_FILES).issubset(fake.RAW_FILES))

    def test_canonical_composition_retains_schema6(self) -> None:
        import uatool  # noqa: F401
        import uatool_systems

        self.assertGreaterEqual(uatool_systems.SYSTEMS_SCHEMA_VERSION, 6)
        self.assertTrue(set(gas.GAS_FILES).issubset(uatool_systems.RAW_FILES))

    def test_native_schema6_is_reflection_first_and_finalized(self) -> None:
        scanner = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp").read_text(encoding="utf-8")
        driver = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsDriver.inl").read_text(encoding="utf-8")
        finalizer = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsFinalize.inl").read_text(encoding="utf-8")
        native = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsGAS.inl").read_text(encoding="utf-8")
        self.assertIn('Root->SetNumberField(TEXT("schema_version"), 6)', driver)
        self.assertIn("GGASWriters.Open(OutputDir)", driver)
        self.assertIn("ScanGASProjectModel(", driver)
        self.assertIn("GGASWriters = FGASWriters();", driver)
        self.assertLess(driver.index("GGASWriters = FGASWriters();"), driver.index("SaveSystemsManifest(OutputDir, Counts, true"))
        self.assertIn("GGASWriters = FGASWriters();", finalizer)
        self.assertLess(scanner.index('#include "UnrealAssetToolSystemsMassZoneGraph.inl"'), scanner.index('#include "UnrealAssetToolSystemsGAS.inl"'))
        self.assertNotIn('#include "AbilitySystemComponent.h"', scanner)
        self.assertNotIn('#include "Abilities/', scanner)
        candidate_start = native.index("static bool GASBlueprintMetadataCandidate")
        candidate_end = native.index("static const FStructProperty* GASStructField", candidate_start)
        candidate = native[candidate_start:candidate_end]
        self.assertIn('GASAssetTag(Asset, TEXT("ParentClass"))', candidate)
        self.assertIn('GASAssetTag(Asset, TEXT("NativeParentClass"))', candidate)
        self.assertNotIn('GASAssetTag(Asset, TEXT("GeneratedClass"))', candidate)
        self.assertNotIn("Asset.AssetName", candidate)
        self.assertNotIn("Asset.PackageName", candidate)


if __name__ == "__main__":
    unittest.main()
