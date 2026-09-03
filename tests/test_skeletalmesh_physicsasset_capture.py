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

import uatool_skeletalmesh_physicsasset_capture as capture


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


class SkeletalMeshPhysicsAssetCaptureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_valid(self) -> None:
        mesh = "/Game/Meshes/SKM_Test.SKM_Test"
        physics = "/Game/Physics/PA_Test.PA_Test"
        socket = mesh + ":Socket_Test"
        body = physics + ":BodySetup_Test"
        constraint = physics + ":Constraint_Test"
        assets = [
            {
                "asset_path": mesh,
                "class_path": capture.SKELETAL_MESH_CLASS,
                "asset_kind": "skeletal_mesh",
                "loaded": True,
                "loaded_class": capture.SKELETAL_MESH_CLASS,
                "registry_tags": {"LODs": "2", "MorphTargets": "1"},
            },
            {
                "asset_path": physics,
                "class_path": capture.PHYSICS_ASSET_CLASS,
                "asset_kind": "physics_asset",
                "loaded": True,
                "loaded_class": capture.PHYSICS_ASSET_CLASS,
                "registry_tags": {"Bodies": "1", "Constraints": "1"},
            },
        ]
        asset_properties = [
            {
                "asset_path": mesh,
                "owner_path": mesh,
                "owner_kind": "skeletal_mesh",
                "property_path": "Materials[0].MaterialSlotName",
                "truncated": False,
            },
            {
                "asset_path": physics,
                "owner_path": physics,
                "owner_kind": "physics_asset",
                "property_path": "SkeletalBodySetups[0]",
                "truncated": False,
            },
        ]
        asset_references = [
            {
                "asset_path": mesh,
                "owner_path": mesh,
                "property_path": "PhysicsAsset",
                "target_path": physics,
                "target_class": capture.PHYSICS_ASSET_CLASS,
            }
        ]
        owned_objects = [
            {"asset_path": mesh, "object_path": socket, "class_path": "/Script/Engine.SkeletalMeshSocket"},
            {"asset_path": physics, "object_path": body, "class_path": "/Script/Engine.SkeletalBodySetup"},
            {"asset_path": physics, "object_path": constraint, "class_path": "/Script/Engine.PhysicsConstraintTemplate"},
        ]
        owned_properties = [
            {
                "asset_path": mesh,
                "owner_path": socket,
                "owner_type": "/Script/Engine.SkeletalMeshSocket",
                "property_path": "BoneName",
                "truncated": False,
            },
            {
                "asset_path": physics,
                "owner_path": body,
                "owner_type": "/Script/Engine.SkeletalBodySetup",
                "property_path": "AggGeom.SphereElems[0].Radius",
                "truncated": False,
            },
            {
                "asset_path": physics,
                "owner_path": constraint,
                "owner_type": "/Script/Engine.PhysicsConstraintTemplate",
                "property_path": "DefaultInstance.ConstraintBone1",
                "truncated": False,
            },
        ]
        owned_references: list[dict] = []
        rows = {
            "skeletalmesh_physicsasset_assets.jsonl": assets,
            "skeletalmesh_physicsasset_asset_properties.jsonl": asset_properties,
            "skeletalmesh_physicsasset_asset_references.jsonl": asset_references,
            "skeletalmesh_physicsasset_owned_objects.jsonl": owned_objects,
            "skeletalmesh_physicsasset_owned_object_properties.jsonl": owned_properties,
            "skeletalmesh_physicsasset_owned_object_references.jsonl": owned_references,
        }
        for name, values in rows.items():
            write_jsonl(self.output / name, values)

        counts = {
            "registry_candidates": 2,
            "loaded_assets": 2,
            "load_failures": 0,
            "skeletal_meshes": 1,
            "physics_assets": 1,
            "asset_properties": 2,
            "asset_references": 1,
            "owned_objects": 3,
            "owned_object_properties": 3,
            "owned_object_references": 0,
            "truncated_properties": 0,
            "property_depth_limit_hits": 0,
            "property_row_limit_hits": 0,
            "container_element_limit_hits": 0,
        }
        (self.output / "skeletalmesh_physicsasset_capture_manifest.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "success": True,
                    "diagnostic_only": True,
                    "semantic_promotion": False,
                    "schema_promotion": False,
                    "runtime_state_captured": False,
                    "render_buffers_captured": False,
                    "cloth_simulation_state_captured": False,
                    "chaos_runtime_state_captured": False,
                    "maps_loaded": False,
                    "counts": counts,
                }
            ),
            encoding="utf-8",
        )

    def test_valid_synthetic_capture(self) -> None:
        self._write_valid()
        manifest = capture.validate_capture(self.output)
        self.assertTrue(manifest["success"])
        report = capture.semantic_report(self.output, manifest)
        self.assertIn("SkeletalBodySetup", report)
        self.assertIn("ConstraintBone1", report)
        self.assertIn("render_buffers_captured: False", report)

    def test_unresolved_owned_property_is_rejected(self) -> None:
        self._write_valid()
        write_jsonl(
            self.output / "skeletalmesh_physicsasset_owned_object_properties.jsonl",
            [
                {
                    "asset_path": "/Game/Physics/PA_Test.PA_Test",
                    "owner_path": "/Game/Physics/PA_Test.PA_Test:Missing",
                    "property_path": "BoneName",
                    "truncated": False,
                }
            ],
        )
        with self.assertRaisesRegex(RuntimeError, "unresolved owner"):
            capture.validate_capture(self.output)

    def test_native_contract_is_authored_reflection_only(self) -> None:
        source = (
            ROOT
            / "Source/UnrealAssetTool/Private/UnrealAssetToolSkeletalMeshPhysicsAssetCommandlet.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn('TEXT("/Script/Engine.SkeletalMesh")', source)
        self.assertIn('TEXT("/Script/Engine.PhysicsAsset")', source)
        self.assertIn("Registry.GetAllAssets(Assets, true)", source)
        self.assertIn(
            "GetObjectsWithOuter(Object, Owned, EGetObjectsFlags::IncludeNestedObjects)",
            source,
        )
        self.assertIn("FScriptSetHelper", source)
        self.assertIn("FScriptMapHelper", source)
        self.assertIn("Property->Identical", source)
        self.assertNotIn("GetResourceForRendering", source)
        self.assertNotIn("FSkeletalMeshRenderData", source)
        self.assertNotIn("GetImportedModel", source)
        self.assertNotIn("GetWorld()", source)
        self.assertNotIn("FindPath", source)
        self.assertNotIn("GetPhysicsScene", source)
        self.assertNotIn("StartSimulation", source)

    def test_launcher_is_canonical_and_requires_explicit_native_run(self) -> None:
        launcher = (SCRIPTS / "uatool_skeletalmesh_physicsasset_capture.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"-run=UnrealAssetToolSkeletalMeshPhysicsAsset"', launcher)
        self.assertIn('"-nullrhi"', launcher)
        self.assertIn('"-nosound"', launcher)
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn(
            "import uatool_skeletalmesh_physicsasset_capture as _skeletalmesh_physicsasset_capture",
            facade,
        )
        self.assertIn(
            "_skeletalmesh_physicsasset_capture.install(_runtime, _core)", facade
        )


if __name__ == "__main__":
    unittest.main()
