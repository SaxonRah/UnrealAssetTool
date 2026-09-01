from __future__ import annotations

import unittest

from scripts import uatool_systems_input_validation as validation


class SystemsInputValidationTests(unittest.TestCase):
    def test_accepts_null_input_action_modifier_slots(self):
        actions = [{
            "action_path": "/Game/Input/IA_Test.IA_Test",
            "trigger_count": 0,
            "modifier_count": 2,
        }]
        processors = [{
            "asset_path": "/Game/Input/IA_Test.IA_Test",
            "owner_scope": "action",
            "mapping_index": -1,
            "processor_kind": "modifier",
            "processor_index": 1,
            "processor_path": "/Game/Input/IA_Test.IA_Test:Modifier_1",
            "processor_class": "/Script/EnhancedInput.InputModifierDeadZone",
        }]

        self.assertIsNone(validation.validate_processor_topology(actions, [], processors))

    def test_accepts_null_mapping_trigger_slots(self):
        mappings = [{
            "context_path": "/Game/Input/IMC_Test.IMC_Test",
            "mapping_index": 3,
            "trigger_count": 3,
            "modifier_count": 0,
        }]
        processors = [{
            "asset_path": "/Game/Input/IMC_Test.IMC_Test",
            "owner_scope": "mapping",
            "mapping_index": 3,
            "processor_kind": "trigger",
            "processor_index": 2,
            "processor_path": "/Game/Input/IMC_Test.IMC_Test:Trigger_2",
            "processor_class": "/Script/EnhancedInput.InputTriggerPressed",
        }]

        self.assertIsNone(validation.validate_processor_topology([], mappings, processors))

    def test_rejects_processor_index_outside_declared_slots(self):
        actions = [{
            "action_path": "/Game/Input/IA_Test.IA_Test",
            "trigger_count": 0,
            "modifier_count": 2,
        }]
        processors = [{
            "asset_path": "/Game/Input/IA_Test.IA_Test",
            "owner_scope": "action",
            "mapping_index": -1,
            "processor_kind": "modifier",
            "processor_index": 2,
            "processor_path": "/Game/Input/IA_Test.IA_Test:Modifier_2",
            "processor_class": "/Script/EnhancedInput.InputModifierDeadZone",
        }]

        error = validation.validate_processor_topology(actions, [], processors)
        self.assertIn("out of bounds", error or "")

    def test_rejects_duplicate_processor_slot_identity(self):
        actions = [{
            "action_path": "/Game/Input/IA_Test.IA_Test",
            "trigger_count": 1,
            "modifier_count": 0,
        }]
        processor = {
            "asset_path": "/Game/Input/IA_Test.IA_Test",
            "owner_scope": "action",
            "mapping_index": -1,
            "processor_kind": "trigger",
            "processor_index": 0,
            "processor_path": "/Game/Input/IA_Test.IA_Test:Trigger_0",
            "processor_class": "/Script/EnhancedInput.InputTriggerPressed",
        }

        error = validation.validate_processor_topology(actions, [], [processor, dict(processor)])
        self.assertIn("duplicate", error or "")


if __name__ == "__main__":
    unittest.main()
