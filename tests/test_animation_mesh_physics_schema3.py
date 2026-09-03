from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_animation_mesh_physics as mesh_physics


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8", newline="\n")


class AnimationMeshPhysicsSchema3Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_valid(self) -> None:
        mesh = "/Game/Test/SKM_Test.SKM_Test"
        physics = "/Game/Test/PA_Test.PA_Test"
        body = physics + ":SkeletalBodySetup_0"
        constraint = physics + ":PhysicsConstraintTemplate_0"
        clothing = mesh + ":TestCloth"
        rows = {
            "skeletal_meshes.jsonl": [{
                "skeletal_mesh_path": mesh, "class_path": "/Script/Engine.SkeletalMesh", "package_name": "/Game/Test/SKM_Test",
                "skeleton_path": "/Game/Test/SK_Test.SK_Test", "physics_asset_path": physics, "shadow_physics_asset_path": "",
                "lod_settings_path": "", "bone_count": 3, "lod_count": 1, "source_model_count": 1,
                "material_count": 1, "morph_target_count": 1, "clothing_asset_count": 1, "mesh_socket_count": 0,
                "nanite_enabled": "False",
            }],
            "skeletal_mesh_lods.jsonl": [{
                "skeletal_mesh_path": mesh, "lod_index": 0, "source_model_struct": "/Script/Engine.SkeletalMeshSourceModel",
                "build_settings": {"bRecomputeNormals": "False"}, "reduction_settings": {"BaseLOD": "0"},
            }],
            "skeletal_mesh_materials.jsonl": [{
                "skeletal_mesh_path": mesh, "material_index": 0, "material_path": "/Game/Test/M_Test.M_Test",
                "material_class": "/Script/Engine.Material", "material_slot_name": "Body", "imported_material_slot_name": "Body",
            }],
            "skeletal_mesh_morph_targets.jsonl": [{
                "skeletal_mesh_path": mesh, "morph_index": 0, "morph_target_path": mesh + ":Smile",
                "object_name": "Smile", "class_path": "/Script/Engine.MorphTarget",
            }],
            "skeletal_mesh_clothing_assets.jsonl": [{
                "skeletal_mesh_path": mesh, "clothing_index": 0, "clothing_asset_path": clothing,
                "clothing_asset_name": "TestCloth", "class_path": "/Script/ClothingSystemRuntimeCommon.ClothingAssetCommon",
                "physics_asset_path": physics,
            }],
            "skeletal_mesh_clothing_configs.jsonl": [{
                "skeletal_mesh_path": mesh, "clothing_asset_path": clothing, "config_index": 0,
                "config_path": clothing + ":ChaosClothConfig_0", "config_class": "/Script/ChaosCloth.ChaosClothConfig",
                "properties": {"EdgeStiffnessWeighted": "(Low=1.0,High=1.0)"},
            }],
            "physics_assets.jsonl": [{
                "physics_asset_path": physics, "class_path": "/Script/Engine.PhysicsAsset", "package_name": "/Game/Test/PA_Test",
                "preview_skeletal_mesh_path": mesh, "body_count": 1, "constraint_count": 1,
                "constraint_profile_count": 1, "physical_animation_profile_count": 1,
            }],
            "physics_bodies.jsonl": [{
                "physics_asset_path": physics, "body_index": 0, "body_path": body, "body_class": "/Script/Engine.SkeletalBodySetup",
                "bone_name": "pelvis", "physics_type": "PhysType_Default", "collision_response": "BodyCollision_Enabled",
                "authored_properties": {"BoneName": "pelvis"},
            }],
            "physics_body_shapes.jsonl": [{
                "physics_asset_path": physics, "body_index": 0, "body_path": body, "shape_type": "SphylElems",
                "shape_index": 0, "shape_struct": "/Script/Engine.KSphylElem", "fields": {"Radius": "15.0", "Length": "30.0"},
                "raw_value": "(Radius=15.0,Length=30.0)",
            }],
            "physics_constraints.jsonl": [{
                "physics_asset_path": physics, "constraint_index": 0, "constraint_path": constraint,
                "constraint_class": "/Script/Engine.PhysicsConstraintTemplate", "joint_name": "pelvis",
                "constraint_bone1": "pelvis", "constraint_bone2": "root",
                "default_instance": {"JointName": "pelvis"},
                "profile_instance": {"LinearLimit": "(XMotion=LCM_Locked)"}, "profile_handles": "",
            }],
            "physics_constraint_profiles.jsonl": [{"physics_asset_path": physics, "profile_index": 0, "profile_name": "Ragdoll"}],
            "physics_physical_animation_profiles.jsonl": [{"physics_asset_path": physics, "profile_index": 0, "profile_name": "Strong"}],
            "physics_collision_disable_pairs.jsonl": [{
                "physics_asset_path": physics, "pair_index": 0, "key": "(Indices=(0,1))", "value": "True",
                "key_fields": {"Indices[0]": "0", "Indices[1]": "1"},
            }],
        }
        counts = {name.removesuffix(".jsonl"): len(values) for name, values in rows.items()}
        counts["mesh_physics_registry_candidates"] = 2
        for name, values in rows.items():
            write_jsonl(self.output / name, values)
        (self.output / "animation_mesh_physics_manifest.json").write_text(json.dumps({
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
            "files": list(rows),
        }), encoding="utf-8")

    def test_valid_normalized_capture(self) -> None:
        self._write_valid()
        self.assertIsNone(mesh_physics.validation_error(self.output, require_present=True))

    def test_count_mismatch_is_rejected(self) -> None:
        self._write_valid()
        manifest = json.loads((self.output / "animation_mesh_physics_manifest.json").read_text(encoding="utf-8"))
        manifest["counts"]["physics_bodies"] = 2
        (self.output / "animation_mesh_physics_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.assertIn("count mismatch", mesh_physics.validation_error(self.output, require_present=True) or "")

    def test_unresolved_shape_body_is_rejected(self) -> None:
        self._write_valid()
        rows = list(mesh_physics._rows(self.output / "physics_body_shapes.jsonl"))
        rows[0]["body_index"] = 9
        write_jsonl(self.output / "physics_body_shapes.jsonl", rows)
        self.assertIn("unresolved body", mesh_physics.validation_error(self.output, require_present=True) or "")

    def test_normalize_promotes_schema2_to_schema3(self) -> None:
        self._write_valid()
        (self.output / "animation_manifest.json").write_text(json.dumps({
            "schema_version": 2,
            "pass": "UnrealAssetToolAnimation",
            "counts": {"animation_assets": 7},
            "files": ["animation_assets.jsonl"],
            "curve_key_encoding": "float64-blocks-v1",
        }), encoding="utf-8")
        self.assertTrue(mesh_physics.normalize_output(self.output))
        manifest = json.loads((self.output / "animation_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema_version"], 3)
        self.assertEqual(manifest["mesh_physics_schema_version"], 1)
        self.assertEqual(manifest["counts"]["skeletal_meshes"], 1)
        self.assertIn("physics_constraints.jsonl", manifest["files"])

    def test_sqlite_round_trip(self) -> None:
        self._write_valid()
        conn = sqlite3.connect(":memory:")
        try:
            mesh_physics.create_schema(conn)
            mesh_physics.load_database(conn, self.output, mesh_physics._rows)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM skeletal_meshes").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT bone_name FROM physics_bodies").fetchone()[0], "pelvis")
            self.assertEqual(conn.execute("SELECT constraint_bone2 FROM physics_constraints").fetchone()[0], "root")
        finally:
            conn.close()

    def test_native_scanner_boundary_and_wiring(self) -> None:
        source = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolAnimationMeshPhysicsScanner.cpp").read_text(encoding="utf-8")
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        integration = (SCRIPTS / "uatool_animation_mesh_physics_integration.py").read_text(encoding="utf-8")
        self.assertIn('TEXT("/Script/Engine.SkeletalMesh")', source)
        self.assertIn('TEXT("/Script/Engine.PhysicsAsset")', source)
        self.assertIn('TEXT("SkeletalBodySetups")', source)
        self.assertIn('TEXT("ConstraintSetup")', source)
        self.assertIn('TEXT("AggGeom")', source)
        self.assertIn('TEXT("MeshClothingAssets")', source)
        self.assertIn('TEXT("MorphTargets")', source)
        self.assertIn('TEXT("Materials")', source)
        for forbidden in ("GetResourceForRendering", "GetSkeletalMeshRenderData", "StartSimulation", "CreatePhysicsState", "LoadMap("):
            self.assertNotIn(forbidden, source)
        self.assertIn("uatool_animation_mesh_physics_integration", facade)
        self.assertIn("_animation_mesh_physics_integration.install(_runtime, _core)", facade)
        self.assertIn("require_present=True", integration)
        self.assertIn("PUBLIC_ANIMATION_SCHEMA_VERSION = 3", (SCRIPTS / "uatool_animation_mesh_physics.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
