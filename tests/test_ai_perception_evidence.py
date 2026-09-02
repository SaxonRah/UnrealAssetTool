from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_ai_perception_evidence as evidence


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class AIPerceptionEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.actor = "/Game/Maps/Test.Test:PersistentLevel.AI_1"
        self.perception = self.actor + ".AIPerception"
        self.stimuli = self.actor + ".StimuliSource"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_report_proves_components_configs_stimuli_and_usage(self) -> None:
        write_jsonl(self.output / "world_components.jsonl", [
            {
                "component_path": self.perception,
                "component_class": "/Script/AIModule.AIPerceptionComponent",
                "actor_path": self.actor,
            },
            {
                "component_path": self.stimuli,
                "component_class": "/Script/AIModule.AIPerceptionStimuliSourceComponent",
                "actor_path": self.actor,
            },
        ])
        write_jsonl(self.output / "world_instance_properties.jsonl", [
            {
                "owner_path": self.perception,
                "property_path": "SensesConfig[0]",
                "cpp_type": "TObjectPtr<UAISenseConfig>",
                "value": "/Script/AIModule.AISenseConfig_Sight SightRadius=3000 LoseSightRadius=3500",
            },
            {
                "owner_path": self.perception,
                "property_path": "DominantSense",
                "cpp_type": "TSubclassOf<UAISense>",
                "value": "/Script/AIModule.AISense_Sight",
            },
            {
                "owner_path": self.stimuli,
                "property_path": "RegisterAsSourceForSenses[0]",
                "cpp_type": "TSubclassOf<UAISense>",
                "value": "/Script/AIModule.AISense_Sight",
            },
        ])
        write_jsonl(self.output / "blueprint_semantic_nodes.jsonl", [{
            "blueprint_path": "/Game/AI/BP_AI.BP_AI",
            "node_class": "/Script/BlueprintGraph.K2Node_Event",
            "display_name": "OnTargetPerceptionUpdated",
        }])

        report = evidence.build_report(self.output, rows, include_source=False)
        proof = report["proof"]
        self.assertEqual(proof["unique_perception_components"], 1)
        self.assertEqual(proof["unique_stimuli_source_components"], 1)
        self.assertEqual(proof["dominant_sense_rows"], 1)
        self.assertGreaterEqual(proof["sense_config_rows"], 1)
        self.assertEqual(proof["stimuli_registered_sense_rows"], 1)
        self.assertGreaterEqual(proof["usage_rows"], 1)
        self.assertGreaterEqual(proof["unique_sense_classes"], 2)
        self.assertEqual(report["gaps"], [])
        self.assertIn(self.perception, report["perception_components"])
        self.assertIn(self.stimuli, report["stimuli_source_components"])

    def test_component_without_internal_state_requests_focused_capture(self) -> None:
        write_jsonl(self.output / "world_components.jsonl", [{
            "component_path": self.perception,
            "component_class": "/Script/AIModule.AIPerceptionComponent",
            "actor_path": self.actor,
        }])
        report = evidence.build_report(self.output, rows, include_source=False)
        joined = "\n".join(report["gaps"])
        self.assertIn("SensesConfig internals", joined)
        self.assertIn("DominantSense", joined)
        self.assertIn("AISense/AISenseConfig", joined)
        self.assertTrue(report["diagnostic_only"])
        self.assertFalse(report["semantic_promotion"])
        self.assertFalse(report["runtime_state_captured"])

    def test_render_states_evidence_boundary(self) -> None:
        write_jsonl(self.output / "world_components.jsonl", [{
            "component_path": self.perception,
            "component_class": "/Script/AIModule.AIPerceptionComponent",
        }])
        text = evidence.render_report(evidence.build_report(self.output, rows, include_source=False), row_limit=2)
        self.assertIn("AI PERCEPTION EVIDENCE REPORT", text)
        self.assertIn("diagnostic_only=True semantic_promotion=False runtime_state_captured=False", text)
        self.assertIn("focused UE reflection capture is required", text)

    def test_install_wraps_runtime_without_intercepting_other_commands(self) -> None:
        fake = types.SimpleNamespace(main=lambda: 19, _rows=rows)
        evidence.install(fake)
        self.assertTrue(fake._ai_perception_evidence_installed)
        with mock.patch.object(sys, "argv", ["uatool.py", "query"]):
            self.assertEqual(fake.main(), 19)

        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("uatool_ai_perception_evidence", facade)
        self.assertIn("_ai_perception_evidence.install", facade)


if __name__ == "__main__":
    unittest.main()
