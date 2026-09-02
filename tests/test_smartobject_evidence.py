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

import uatool_smartobject_evidence as evidence


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


class SmartObjectEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.definition = "/Game/AI/SmartObject/SO_Def.SO_Def"
        self.actor = "/Game/Maps/Test.Test:PersistentLevel.SO_Actor_1"
        self.component = self.actor + ".SmartObjectComponent"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_report_proves_definition_placement_reference_usage_and_internals(self) -> None:
        write_jsonl(self.output / "assets.jsonl", [{
            "object_path": self.definition,
            "class_path": "/Script/SmartObjectsModule.SmartObjectDefinition",
        }])
        write_jsonl(self.output / "world_components.jsonl", [{
            "component_path": self.component,
            "component_class": "/Script/SmartObjectsModule.SmartObjectComponent",
            "actor_path": self.actor,
        }])
        write_jsonl(self.output / "world_actors.jsonl", [{
            "actor_path": self.actor,
            "actor_class": "/Game/AI/SmartObject/SO_Actor.SO_Actor_C",
            "tags": ["WithSmartObject"],
        }])
        write_jsonl(self.output / "world_references.jsonl", [{
            "owner_path": self.component,
            "target_path": self.definition,
            "target_class": "/Script/SmartObjectsModule.SmartObjectDefinition",
            "property_path": "Definition",
        }])
        write_jsonl(self.output / "blueprint_state_values.jsonl", [{
            "blueprint_path": "/Game/AI/SmartObject/SO_Actor.SO_Actor",
            "property_path": "Definition.Slots[0].BehaviorDefinitions[0]",
            "cpp_type": "FSmartObjectSlotDefinition",
            "value": "SmartObjectDefinition=/Game/AI/SmartObject/SO_Def.SO_Def Behavior=SmartObjectBehaviorDefinition",
        }])
        write_jsonl(self.output / "statetree_bindings.jsonl", [{
            "statetree_path": "/Game/AI/ST_SmartObject.ST_SmartObject",
            "property_path": "SlotToBeClaimed",
            "value": "Slot Handle",
        }])

        report = evidence.build_report(self.output, rows, include_source=False)
        proof = report["proof"]
        self.assertEqual(proof["unique_definition_assets"], 1)
        self.assertEqual(proof["unique_placed_smartobject_components"], 1)
        self.assertEqual(proof["unique_exact_definition_references"], 1)
        self.assertGreaterEqual(proof["definition_slot_internal_rows"], 1)
        self.assertGreaterEqual(proof["definition_behavior_internal_rows"], 1)
        self.assertGreaterEqual(proof["usage_rows"], 1)
        self.assertEqual(report["gaps"], [])
        self.assertEqual(report["definitions"], [self.definition])
        self.assertEqual(report["definition_references"][0]["definition"], self.definition)

    def test_definition_without_internal_rows_requests_focused_capture(self) -> None:
        write_jsonl(self.output / "assets.jsonl", [{
            "object_path": self.definition,
            "class_path": "/Script/SmartObjectsModule.SmartObjectDefinition",
        }])
        write_jsonl(self.output / "world_components.jsonl", [{
            "component_path": self.component,
            "component_class": "/Script/SmartObjectsModule.SmartObjectComponent",
        }])

        report = evidence.build_report(self.output, rows, include_source=False)
        self.assertEqual(report["proof"]["unique_definition_assets"], 1)
        self.assertEqual(report["proof"]["definition_slot_internal_rows"], 0)
        joined = "\n".join(report["gaps"])
        self.assertIn("slot internals", joined)
        self.assertIn("behavior-definition internals", joined)

    def test_render_states_diagnostic_boundary(self) -> None:
        write_jsonl(self.output / "assets.jsonl", [{
            "object_path": self.definition,
            "class_path": "/Script/SmartObjectsModule.SmartObjectDefinition",
        }])
        report = evidence.build_report(self.output, rows, include_source=False)
        text = evidence.render_report(report, row_limit=2)
        self.assertIn("SMART OBJECTS EVIDENCE REPORT", text)
        self.assertIn("diagnostic_only=True semantic_promotion=False", text)
        self.assertIn(self.definition, text)
        self.assertIn("focused Unreal reflection capture is required", text)

    def test_install_wraps_runtime_without_intercepting_other_commands(self) -> None:
        fake = types.SimpleNamespace(main=lambda: 19, _rows=rows)
        evidence.install(fake)
        self.assertTrue(fake._smartobject_evidence_installed)
        with mock.patch.object(sys, "argv", ["uatool.py", "query"]):
            self.assertEqual(fake.main(), 19)

        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("uatool_smartobject_evidence", facade)
        self.assertIn("_smartobject_evidence.install", facade)


if __name__ == "__main__":
    unittest.main()
