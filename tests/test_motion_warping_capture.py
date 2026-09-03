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
import uatool_motion_warping_capture as capture


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


class MotionWarpingCaptureTest(unittest.TestCase):
    def _fixture(self, root: Path) -> Path:
        out = root / "motion-warping-native-capture"
        out.mkdir()
        state = "/Game/A.A:AnimNotifyState_MotionWarping_0"
        modifier = state + ".RootMotionModifier"
        write_jsonl(root / "animation_notifies.jsonl", [{
            "asset_path": "/Game/A.A",
            "notify_index": 2,
            "notify_state_object": state,
            "notify_state_class": capture.NOTIFY_CLASS,
        }])
        write_jsonl(out / "motion_warping_windows.jsonl", [{
            "asset_path": "/Game/A.A",
            "notify_index": 2,
            "notify_state_path": state,
            "notify_state_class": capture.NOTIFY_CLASS,
            "modifier_path": modifier,
            "modifier_class": "/Script/MotionWarping.RootMotionModifier_SkewWarp",
            "modifier_present": True,
        }])
        write_jsonl(out / "motion_warping_modifiers.jsonl", [{
            "asset_path": "/Game/A.A",
            "notify_index": 2,
            "notify_state_path": state,
            "modifier_path": modifier,
            "modifier_class": "/Script/MotionWarping.RootMotionModifier_SkewWarp",
            "is_template": True,
            "warp_target_name": "FrontLedge",
        }])
        write_jsonl(out / "motion_warping_modifier_properties.jsonl", [{
            "asset_path": "/Game/A.A",
            "notify_index": 2,
            "notify_state_path": state,
            "modifier_path": modifier,
            "modifier_class": "/Script/MotionWarping.RootMotionModifier_SkewWarp",
            "declaring_type": "/Script/MotionWarping.RootMotionModifier_Warp",
            "property_name": "WarpTargetName",
            "static_index": 0,
            "value": "FrontLedge",
        }])
        write_json(out / "motion_warping_capture_manifest.json", {
            "schema_version": 1,
            "success": True,
            "diagnostic_only": True,
            "semantic_promotion": False,
            "schema_promotion": False,
            "runtime_state_captured": False,
            "live_warp_targets_captured": False,
            "active_root_motion_modifiers_captured": False,
            "root_motion_evaluated": False,
            "maps_loaded": False,
            "counts": {
                "animation_candidates": 1,
                "animation_assets_loaded": 1,
                "load_failures": 0,
                "motion_warping_windows": 1,
                "modifiers": 1,
                "modifier_properties": 1,
                "windows_without_modifier": 0,
            },
        })
        return out

    def test_capture_validates_against_canonical_animation_notify_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = self._fixture(Path(temp))
            manifest = capture.validate_capture(out)
            self.assertEqual(manifest["counts"]["motion_warping_windows"], 1)
            report = capture.semantic_report(out, manifest)
            self.assertIn("canonical_motion_warping_windows: 1", report)
            self.assertIn("RootMotionModifier_SkewWarp", report)
            self.assertIn("FrontLedge", report)

    def test_wrong_notify_index_is_rejected_even_when_counts_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            out = self._fixture(Path(temp))
            for filename in (
                "motion_warping_windows.jsonl",
                "motion_warping_modifiers.jsonl",
                "motion_warping_modifier_properties.jsonl",
            ):
                row = json.loads((out / filename).read_text(encoding="utf-8"))
                row["notify_index"] = 3
                write_jsonl(out / filename, [row])
            with self.assertRaisesRegex(RuntimeError, "native/canonical window mismatch"):
                capture.validate_capture(out)

    def test_native_source_captures_template_only_and_forbids_runtime_state(self) -> None:
        source = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolMotionWarpingCommandlet.cpp"
        ).read_text(encoding="utf-8")
        build = (ROOT / "Source/UnrealAssetTool/UnrealAssetTool.Build.cs").read_text(encoding="utf-8")
        header = (
            ROOT / "Source/UnrealAssetTool/Public/UnrealAssetToolMotionWarpingCommandlet.h"
        ).read_text(encoding="utf-8")

        self.assertIn('"MotionWarping"', build)
        self.assertIn("UUnrealAssetToolMotionWarpingCommandlet", header)
        self.assertIn("UAnimNotifyState_MotionWarping", source)
        self.assertIn("NotifyState->RootMotionModifier.Get()", source)
        self.assertIn("CPF_Edit", source)
        self.assertIn("CPF_Transient", source)
        self.assertIn('TEXT("WarpTargetName")', source)
        self.assertIn("Warp->WarpTargetName", source)
        self.assertIn("Warp->bWarpTranslation", source)
        self.assertIn("Warp->bWarpRotation", source)
        self.assertIn("Warp->RotationType", source)
        self.assertIn("Warp->RotationMethod", source)
        self.assertNotIn("GetWarpTargets(", source)
        self.assertNotIn("GetModifiers(", source)
        self.assertNotIn("ProcessRootMotion(", source)
        self.assertNotIn("LoadMap", source)
        self.assertNotIn("EditorLoadingAndSavingUtils", source)

    def test_launcher_is_read_only_for_derived_freshness_and_canonical_facade(self) -> None:
        self.assertIn("uatool_motion_warping_capture.py", freshness.NON_DERIVED_SCRIPTS)
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_motion_warping_capture as _motion_warping_capture", facade)
        self.assertIn("_motion_warping_capture.install(_runtime, _core)", facade)
        launcher = (SCRIPTS / "uatool_motion_warping_capture.py").read_text(encoding="utf-8")
        self.assertIn('"-run=UnrealAssetToolMotionWarping"', launcher)
        self.assertIn('"-nullrhi"', launcher)
        self.assertIn("normal scan was not run", launcher)
        self.assertIn("derive was not run", launcher)


if __name__ == "__main__":
    unittest.main()
