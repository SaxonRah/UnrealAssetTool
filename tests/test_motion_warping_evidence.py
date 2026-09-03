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
import uatool_motion_warping_evidence as evidence


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def rows(path: Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            yield json.loads(line)


class MotionWarpingEvidenceTest(unittest.TestCase):
    def test_exact_component_notify_call_and_literal_are_proven(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            write_jsonl(out / "blueprint_components.jsonl", [
                {
                    "blueprint_path": "/Game/BP_Char.BP_Char",
                    "variable_name": "MotionWarping",
                    "component_class": evidence.MOTION_WARPING_COMPONENT,
                },
                {
                    "blueprint_path": "/Game/BP_Fake.BP_Fake",
                    "variable_name": "MotionWarpingLookalike",
                    "component_class": "/Script/Fake.MotionWarpingComponent",
                },
            ])
            write_jsonl(out / "animation_notifies.jsonl", [{
                "asset_path": "/Game/A_Montage.A_Montage",
                "notify_index": 2,
                "notify_name": "Motion Warping",
                "trigger_time": 0.25,
                "duration": 0.4,
                "notify_state_object": "/Game/A_Montage.A_Montage:AnimNotifyState_MotionWarping_0",
                "notify_state_class": evidence.MOTION_WARPING_NOTIFY_STATE,
            }])
            write_jsonl(out / "blueprint_nodes.jsonl", [{
                "node_id": "n1",
                "blueprint_path": "/Game/BP_Char.BP_Char",
                "semantic": {
                    "operation": "function_call",
                    "member_parent_class": evidence.MOTION_WARPING_COMPONENT,
                    "member_name": "AddOrUpdateWarpTargetFromTransform",
                },
            }, {
                "node_id": "n2",
                "blueprint_path": "/Game/BP_Fake.BP_Fake",
                "semantic": {
                    "operation": "function_call",
                    "member_parent_class": "/Script/Fake.MotionWarpingComponent",
                    "member_name": "AddOrUpdateWarpTargetFromTransform",
                },
            }])
            write_jsonl(out / "blueprint_pins.jsonl", [{
                "node_id": "n1",
                "blueprint_path": "/Game/BP_Char.BP_Char",
                "name": "WarpTargetName",
                "default_value": "VaultTarget",
            }])
            for name in evidence.STREAMS:
                path = out / name
                if not path.exists():
                    write_jsonl(path, [])

            report = evidence.build_report(out, rows)
            self.assertEqual(report["proof"]["motion_warping_components"], 1)
            self.assertEqual(report["proof"]["motion_warping_notify_windows"], 1)
            self.assertEqual(report["proof"]["exact_target_management_calls"], 1)
            self.assertEqual(report["proof"]["target_name_literal_pins"], 1)
            self.assertEqual(report["call_function_counts"]["AddOrUpdateWarpTargetFromTransform"], 1)
            self.assertEqual(report["target_name_literals"][0]["default_value"], "VaultTarget")

    def test_notify_without_modifier_template_is_reported_as_capture_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            for name in evidence.STREAMS:
                write_jsonl(out / name, [])
            write_jsonl(out / "animation_notifies.jsonl", [{
                "asset_path": "/Game/A_Montage.A_Montage",
                "notify_index": 0,
                "notify_state_object": "/Game/A_Montage.A_Montage:WarpWindow",
                "notify_state_class": evidence.MOTION_WARPING_NOTIFY_STATE,
            }])
            report = evidence.build_report(out, rows)
            self.assertEqual(report["proof"]["motion_warping_notify_windows"], 1)
            self.assertEqual(report["proof"]["root_motion_modifier_rows"], 0)
            self.assertTrue(any("focused native authored capture is required" in gap for gap in report["gaps"]))

    def test_notify_owned_root_modifier_evidence_satisfies_internal_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            for name in evidence.STREAMS:
                write_jsonl(out / name, [])
            obj = "/Game/A_Montage.A_Montage:WarpWindow"
            write_jsonl(out / "animation_notifies.jsonl", [{
                "asset_path": "/Game/A_Montage.A_Montage",
                "notify_index": 0,
                "notify_state_object": obj,
                "notify_state_class": evidence.MOTION_WARPING_NOTIFY_STATE,
            }])
            write_jsonl(out / "animation_properties.jsonl", [{
                "asset_path": "/Game/A_Montage.A_Montage",
                "owner_path": obj + ".RootMotionModifier",
                "owner_class": "/Script/MotionWarping.RootMotionModifier_Warp",
                "property_name": "WarpTargetName",
                "value": "VaultTarget",
            }])
            report = evidence.build_report(out, rows)
            self.assertEqual(report["proof"]["notify_owned_property_rows"], 1)
            self.assertGreaterEqual(report["proof"]["root_motion_modifier_rows"], 1)
            self.assertFalse(any("focused native authored capture is required" in gap for gap in report["gaps"]))

    def test_evidence_script_is_read_only_for_derived_freshness(self) -> None:
        self.assertIn("uatool_motion_warping_evidence.py", freshness.NON_DERIVED_SCRIPTS)
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_motion_warping_evidence as _motion_warping_evidence", facade)
        self.assertIn("_motion_warping_evidence.install(_runtime)", facade)
        source = (SCRIPTS / "uatool_motion_warping_evidence.py").read_text(encoding="utf-8")
        self.assertIn("diagnostic_only", source)
        self.assertIn("semantic_promotion", source)
        self.assertIn("schema_promotion", source)
        self.assertIn("live_warp_targets_captured", source)
        self.assertIn("root_motion_evaluated", source)


if __name__ == "__main__":
    unittest.main()
