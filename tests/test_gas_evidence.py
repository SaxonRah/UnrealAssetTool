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

import uatool_derived_freshness as freshness
import uatool_gas_evidence as gas


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


class GASEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

        write_jsonl(self.output / "assets.jsonl", [
            {
                "object_path": "/Game/Abilities/GA_Fire.GA_Fire",
                "class_path": "/Script/GameplayAbilitiesEditor.GameplayAbilityBlueprint",
                "parent_class": "/Script/GameplayAbilities.GameplayAbility",
                "property_name": "CostGameplayEffectClass",
            },
            {
                "object_path": "/Game/Effects/GE_Buff.GE_Buff",
                "class_path": "/Script/GameplayAbilities.TargetTagsGameplayEffectComponent",
                "property_name": "InheritableGrantedTagsContainer",
            },
            {
                "object_path": "/Game/Data/AS_Weapons.AS_Weapons",
                "class_path": "/Script/LyraGame.LyraAbilitySet",
                "property_name": "GrantedGameplayAbilities",
            },
            {
                "object_path": "/Game/Noise/DA_Noise.DA_Noise",
                "class_path": "/Script/Engine.PrimaryDataAsset",
                "property_name": "Modifiers",
                "description": "an ability to configure something unrelated",
            },
        ])
        write_jsonl(self.output / "world_components.jsonl", [
            {
                "component_path": "/Game/Map.Map:PersistentLevel.Hero.AbilitySystem",
                "component_class": "/Script/LyraGame.LyraAbilitySystemComponent",
                "property_name": "ReplicationMode",
            }
        ])
        write_jsonl(self.output / "blueprint_defaults.jsonl", [
            {
                "blueprint_path": "/Game/Hero/BP_Hero.BP_Hero",
                "declaring_class": "/Script/LyraGame.LyraHealthSet",
                "property_name": "Health",
                "cpp_type": "FGameplayAttributeData",
                "value": "(BaseValue=100,CurrentValue=100)",
            }
        ])
        write_jsonl(self.output / "project_edges.jsonl", [
            {
                "source": "/Game/DerivedOnly",
                "relation": "references",
                "target": "/Script/GameplayAbilities.GameplayTagResponseTable",
            }
        ])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_focus_requires_concrete_gas_anchor(self) -> None:
        report = gas.build_focus_report(self.output, rows)
        self.assertTrue(report["diagnostic_only"])
        self.assertFalse(report["semantic_promotion"])
        self.assertFalse(report["include_derived"])

        self.assertGreater(report["buckets"]["ability"]["matched_rows"], 0)
        self.assertGreater(report["buckets"]["effect"]["matched_rows"], 0)
        self.assertGreater(report["buckets"]["ability-system"]["matched_rows"], 0)
        self.assertGreater(report["buckets"]["attribute"]["matched_rows"], 0)
        self.assertGreater(report["buckets"]["granting"]["matched_rows"], 0)

        # Generic English/domain-detail words are deliberately not anchors.
        noise = json.dumps({
            "property_name": "Modifiers",
            "description": "an ability to configure something unrelated",
        }).lower()
        for definition in gas.FOCUS_DEFINITIONS.values():
            self.assertEqual(gas._hits(noise, definition["anchors"]), ())

    def test_default_scan_excludes_large_derived_streams(self) -> None:
        broad = gas.build_report(self.output, rows)
        self.assertNotIn("project_edges.jsonl", broad["stream_stats"])
        self.assertNotIn("gameplaytagresponsetable", broad["marker_counts"])

        # Derived streams are visible only when explicitly requested.
        broad_with_derived = gas.build_report(self.output, rows, include_derived=True)
        self.assertIn("project_edges.jsonl", broad_with_derived["stream_stats"])
        self.assertEqual(broad_with_derived["stream_stats"]["project_edges.jsonl"]["matched_rows"], 1)
        self.assertEqual(broad_with_derived["marker_counts"]["gameplaytagresponsetable"], 1)

    def test_effect_component_and_attribute_details_are_ranked_high_signal(self) -> None:
        report = gas.build_focus_report(self.output, rows, focuses=("effect", "attribute"))
        effect = report["buckets"]["effect"]
        attribute = report["buckets"]["attribute"]
        self.assertGreater(effect["high_signal_rows"], 0)
        self.assertGreater(attribute["high_signal_rows"], 0)
        self.assertIn("InheritableGrantedTagsContainer", effect["property_counts"])
        self.assertIn("FGameplayAttributeData", attribute["cpp_type_counts"])

    def test_diagnostic_modules_do_not_invalidate_derived_fingerprint(self) -> None:
        self.assertIn("uatool_gas_evidence.py", freshness.NON_DERIVED_SCRIPTS)
        self.assertIn("uatool_zonegraph_mass_evidence.py", freshness.NON_DERIVED_SCRIPTS)

    def test_canonical_launcher_composition_installs_gas_diagnostics(self) -> None:
        text = (SCRIPTS / "uatool_build_perf.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_gas_evidence as gas_evidence", text)
        self.assertIn("gas_evidence.install(runtime)", text)


if __name__ == "__main__":
    unittest.main()
