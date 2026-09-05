from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_motion_warping_schema as schema
import uatool_motion_warping_model as model
import uatool_motion_warping_graph as graph
import uatool_animation_mesh_physics as mesh_physics
import uatool_motion_warping_integration as integration


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


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


def write_empty_mesh_physics_sidecar(root: Path) -> None:
    counts = {name.removesuffix(".jsonl"): 0 for name in mesh_physics.JSONL_FILES}
    counts["mesh_physics_registry_candidates"] = 0
    for filename in mesh_physics.JSONL_FILES:
        write_jsonl(root / filename, [])
    write_json(root / "animation_mesh_physics_manifest.json", {
        "schema_version": 1,
        "public_animation_schema_version": 3,
        "pass": "UnrealAssetToolAnimationMeshPhysics",
        "success": True,
        "runtime_state_captured": False,
        "render_buffers_captured": False,
        "cloth_simulation_state_captured": False,
        "chaos_runtime_state_captured": False,
        "maps_loaded": False,
        "counts": counts,
        "files": list(mesh_physics.JSONL_FILES),
    })


class MotionWarpingSchema4Test(unittest.TestCase):
    def _fixture(self, root: Path, *, provider: str = "Bone", bone_name: str = "attach") -> Path:
        corpus = root
        capture = corpus / "motion-warping-native-capture"
        capture.mkdir()

        asset = "/Game/A.A"
        state = asset + ":AnimNotifyState_MotionWarping_0"
        modifier = state + ".RootMotionModifier_SkewWarp"

        write_json(corpus / "manifest.json", {
            "schema_version": 12,
            "world_schema_version": 12,
            "animation_schema_version": 3,
            "animation_counts": {"animation_notifies": 1},
            "animation_files": ["animation_notifies.jsonl"],
        })
        write_json(corpus / "animation_manifest.json", {
            "schema_version": 3,
            "counts": {"animation_notifies": 1},
            "files": ["animation_notifies.jsonl"],
            "curve_key_encoding": "columnar-v1",
            "animation_property_encoding": "columnar-v1",
        })
        write_jsonl(corpus / "animation_notifies.jsonl", [{
            "asset_path": asset,
            "notify_index": 2,
            "notify_state_object": state,
            "notify_state_class": schema.NOTIFY_CLASS,
        }])

        write_json(capture / "motion_warping_capture_manifest.json", {
            "schema_version": 1,
            "success": True,
            "error": "",
            "engine_version": "5.8.2-test",
            "include_engine": False,
            "diagnostic_only": True,
            "semantic_promotion": False,
            "schema_promotion": False,
            "runtime_state_captured": False,
            "live_warp_targets_captured": False,
            "active_root_motion_modifiers_captured": False,
            "root_motion_evaluated": False,
            "maps_loaded": False,
            "motion_warping_module_linked": False,
            "counts": {
                "animation_candidates": 1,
                "animation_assets_loaded": 1,
                "load_failures": 0,
                "motion_warping_windows": 1,
                "modifiers": 1,
                "modifier_properties": 2,
                "windows_without_modifier": 0,
            },
        })
        write_jsonl(capture / "motion_warping_windows.jsonl", [{
            "asset_path": asset,
            "asset_class": "/Script/Engine.AnimMontage",
            "notify_index": 2,
            "notify_guid": "abc",
            "notify_state_path": state,
            "notify_state_class": schema.NOTIFY_CLASS,
            "trigger_time": 1.0,
            "end_trigger_time": 1.5,
            "duration": 0.5,
            "track_index": 0,
            "modifier_path": modifier,
            "modifier_class": "/Script/MotionWarping.RootMotionModifier_SkewWarp",
            "modifier_present": True,
        }])
        write_jsonl(capture / "motion_warping_modifiers.jsonl", [{
            "asset_path": asset,
            "notify_index": 2,
            "notify_state_path": state,
            "modifier_path": modifier,
            "modifier_class": "/Script/MotionWarping.RootMotionModifier_SkewWarp",
            "outer_path": state,
            "outer_class": schema.NOTIFY_CLASS,
            "is_template": True,
            "warp_target_name": "FrontLedge",
            "warp_point_anim_provider": provider,
            "warp_point_anim_bone_name": bone_name,
            "warp_point_anim_transform": "(Identity)",
            "warp_translation": True,
            "ignore_z_axis": False,
            "warp_to_feet_location": True,
            "add_translation_easing_func": "Linear",
            "add_translation_easing_curve": "",
            "add_translation_easing_curve_class": "",
            "warp_rotation": True,
            "rotation_type": "Default",
            "rotation_method": "Slerp",
            "subtract_remaining_root_motion": False,
            "additional_rotation_offset": "(Pitch=0,Yaw=0,Roll=0)",
            "warp_rotation_time_multiplier": "1.000000",
            "warp_max_rotation_rate": "0.000000",
        }])
        write_jsonl(capture / "motion_warping_modifier_properties.jsonl", [
            {
                "asset_path": asset,
                "notify_index": 2,
                "notify_state_path": state,
                "modifier_path": modifier,
                "modifier_class": "/Script/MotionWarping.RootMotionModifier_SkewWarp",
                "declaring_type": "/Script/MotionWarping.RootMotionModifier_Warp",
                "property_name": "WarpTargetName",
                "static_index": 0,
                "property_type": "NameProperty",
                "cpp_type": "FName",
                "value": "FrontLedge",
            },
            {
                "asset_path": asset,
                "notify_index": 2,
                "notify_state_path": state,
                "modifier_path": modifier,
                "modifier_class": "/Script/MotionWarping.RootMotionModifier_SkewWarp",
                "declaring_type": "/Script/MotionWarping.RootMotionModifier_SkewWarp",
                "property_name": "MaxSpeedClampRatio",
                "static_index": 0,
                "property_type": "FloatProperty",
                "cpp_type": "float",
                "value": "0.000000",
            },
        ])
        return capture

    def test_promote_capture_composes_public_animation_schema4(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            corpus = Path(temp)
            capture = self._fixture(corpus)
            manifest = schema.promote_capture(corpus, capture)
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["public_animation_schema_version"], 4)
            self.assertEqual(manifest["counts"]["motion_warping_windows"], 1)
            self.assertEqual(manifest["counts"]["motion_warping_modifiers"], 1)
            self.assertEqual(manifest["counts"]["motion_warping_modifier_properties"], 2)

            animation = json.loads((corpus / "animation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(animation["schema_version"], 4)
            self.assertEqual(animation["motion_warping_schema_version"], 1)
            self.assertIn("motion_warping_modifiers.jsonl", animation["files"])
            self.assertIsNone(schema.validation_error(corpus, require_present=True))

    def test_normal_pending_capture_promotes_mesh_schema_before_motion_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            corpus = Path(temp)
            capture = self._fixture(corpus)

            animation = json.loads((corpus / "animation_manifest.json").read_text(encoding="utf-8"))
            animation["schema_version"] = 2
            animation.pop("mesh_physics_schema_version", None)
            write_json(corpus / "animation_manifest.json", animation)
            write_empty_mesh_physics_sidecar(corpus)

            self.assertTrue(integration._promote_pending_capture(corpus))
            promoted = json.loads((corpus / "animation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(promoted["schema_version"], 4)
            self.assertEqual(promoted["mesh_physics_schema_version"], 1)
            self.assertEqual(promoted["motion_warping_schema_version"], 1)
            self.assertFalse(capture.exists())
            self.assertIsNone(schema.validation_error(corpus, require_present=True))

    def test_graph_uses_only_active_bone_provider(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            corpus = Path(temp)
            schema.promote_capture(corpus, self._fixture(corpus, provider="None", bone_name="interaction"))
            built = model.build_model(corpus, rows)
            relations = [spec["relation"] for spec in built["edge_specs"]]
            self.assertEqual(relations.count("animation_asset_has_motion_warping_window"), 1)
            self.assertEqual(relations.count("motion_warping_window_owns_modifier"), 1)
            self.assertEqual(relations.count("motion_warping_modifier_targets_name"), 1)
            self.assertNotIn("motion_warping_modifier_uses_warp_point_bone_name", relations)
            self.assertEqual(graph.TARGET_DERIVED_SCHEMA_VERSION, 32)

    def test_graph_emits_exact_active_bone_relation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            corpus = Path(temp)
            schema.promote_capture(corpus, self._fixture(corpus))
            built = model.build_model(corpus, rows)
            relations = [spec["relation"] for spec in built["edge_specs"]]
            self.assertEqual(relations.count("motion_warping_modifier_uses_warp_point_bone_name"), 1)
            self.assertEqual(built["counts"]["exact_semantic_edges"], 4)

    def test_sqlite_round_trip_preserves_common_and_exact_property_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            corpus = Path(temp)
            schema.promote_capture(corpus, self._fixture(corpus))
            conn = sqlite3.connect(":memory:")
            schema.create_schema(conn)
            schema.load_database(conn, corpus, rows)
            modifier = conn.execute(
                "SELECT warp_target_name,warp_point_anim_provider,warp_point_anim_bone_name "
                "FROM motion_warping_modifiers"
            ).fetchone()
            self.assertEqual(modifier, ("FrontLedge", "Bone", "attach"))
            prop = conn.execute(
                "SELECT property_name,cpp_type,value FROM motion_warping_modifier_properties "
                "WHERE property_name='MaxSpeedClampRatio'"
            ).fetchone()
            self.assertEqual(prop, ("MaxSpeedClampRatio", "float", "0.000000"))
            conn.close()

    def test_normalize_is_idempotent_on_current_schema4_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            corpus = Path(temp)
            schema.promote_capture(corpus, self._fixture(corpus))

            animation_path = corpus / "animation_manifest.json"
            top_path = corpus / "manifest.json"
            frozen_animation = 1_700_000_000_000_000_000
            frozen_top = 1_700_000_001_000_000_000
            os.utime(animation_path, ns=(frozen_animation, frozen_animation))
            os.utime(top_path, ns=(frozen_top, frozen_top))
            animation_before = animation_path.read_bytes()
            top_before = top_path.read_bytes()

            self.assertTrue(schema.normalize_output(corpus))
            self.assertEqual(animation_path.read_bytes(), animation_before)
            self.assertEqual(top_path.read_bytes(), top_before)
            self.assertEqual(animation_path.stat().st_mtime_ns, frozen_animation)
            self.assertEqual(top_path.stat().st_mtime_ns, frozen_top)

    def test_clear_schema_downgrades_only_motion_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            corpus = Path(temp)
            schema.promote_capture(corpus, self._fixture(corpus))
            schema.clear_schema(corpus, base_animation_schema=3)
            self.assertFalse((corpus / schema.MANIFEST_FILE).exists())
            animation = json.loads((corpus / "animation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(animation["schema_version"], 3)
            self.assertNotIn("motion_warping_schema_version", animation)
            self.assertNotIn("motion_warping_windows.jsonl", animation["files"])

    def test_normal_scan_and_public_composition_are_wired(self) -> None:
        module = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolModule.cpp"
        ).read_text(encoding="utf-8")
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        integration = (SCRIPTS / "uatool_motion_warping_integration.py").read_text(encoding="utf-8")
        mesh_integration = (SCRIPTS / "uatool_animation_mesh_physics_integration.py").read_text(encoding="utf-8")

        self.assertIn('#include "UnrealAssetToolMotionWarpingCommandlet.h"', module)
        self.assertIn("RunMotionWarpingPass(OutputDir);", module)
        self.assertIn('TEXT("motion-warping-native-capture")', module)
        self.assertIn("import uatool_motion_warping_integration as _motion_warping_integration", facade)
        self.assertIn("_motion_warping_integration.install(_runtime, _core)", facade)
        self.assertIn("_motion_warping_schema32_composition_installed", integration)
        self.assertIn("TARGET_DERIVED_SCHEMA_VERSION = 32", (SCRIPTS / "uatool_motion_warping_graph.py").read_text(encoding="utf-8"))
        self.assertIn("< mesh_physics.PUBLIC_ANIMATION_SCHEMA_VERSION", mesh_integration)

    def test_capture_boundary_remains_runtime_free_and_optional_plugin_free(self) -> None:
        source = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolMotionWarpingCommandlet.cpp"
        ).read_text(encoding="utf-8")
        build = (ROOT / "Source/UnrealAssetTool/UnrealAssetTool.Build.cs").read_text(encoding="utf-8")
        for forbidden in ('"MotionWarping"', "GetWarpTargets(", "GetModifiers(", "ProcessRootMotion(", "LoadMap("):
            if forbidden == '"MotionWarping"':
                self.assertNotIn(forbidden, build)
            else:
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
