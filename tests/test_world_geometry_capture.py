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
import uatool_world_geometry_capture as capture


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


class WorldGeometryCaptureTest(unittest.TestCase):
    def test_native_source_is_exact_authored_and_schema_neutral(self):
        source = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolWorldGeometryCommandlet.cpp"
        ).read_text(encoding="utf-8")
        header = (
            ROOT / "Source/UnrealAssetTool/Public/UnrealAssetToolWorldGeometryCommandlet.h"
        ).read_text(encoding="utf-8")
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")

        for class_path in (
            "/Script/Landscape.Landscape",
            "/Script/Landscape.LandscapeStreamingProxy",
            "/Script/Landscape.LandscapeLayerInfoObject",
            "/Script/Landscape.LandscapeGrassType",
            "/Script/Foliage.FoliageType_InstancedStaticMesh",
            "/Script/Foliage.InstancedFoliageActor",
            "/Script/Engine.HLODLayer",
        ):
            self.assertIn(class_path, source)

        self.assertNotIn("SkeletalMeshLODSettings", source)
        self.assertIn("WeightmapLayerAllocations", source)
        self.assertIn("LandscapeComponents", source)
        self.assertIn("GrassVarieties", source)
        self.assertIn("FoliageInfos", source)
        self.assertIn("Instances", source)
        self.assertIn("HLODBuilderSettings", source)
        self.assertIn("diagnostic_only", source)
        self.assertIn("semantic_promotion", source)
        self.assertIn("schema_promotion", source)
        self.assertIn("generated_geometry_captured", source)
        self.assertIn("render_resources_captured", source)
        self.assertIn("world_runtime_streaming_state_captured", source)
        self.assertIn("maps_loaded", source)
        self.assertIn("UUnrealAssetToolWorldGeometryCommandlet", header)
        self.assertIn("uatool_world_geometry_capture", facade)
        self.assertIn("_world_geometry_capture.install(_runtime, _core)", facade)
        self.assertIn("uatool_world_geometry_capture.py", freshness.NON_DERIVED_SCRIPTS)

        for forbidden in (
            "GetResourceForRendering",
            "GetStaticMeshRenderData",
            "GetSkeletalMeshRenderData",
            "LoadMap(",
            "CreatePhysicsState",
            "StartSimulation",
            "Nanite::",
        ):
            self.assertNotIn(forbidden, source)

    def test_python_validator_accepts_bounded_diagnostic_shape(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            rows = {
                "landscape_roots.jsonl": [{
                    "landscape_path": "/Game/Map.Map:PersistentLevel.Landscape_0",
                    "class_path": "/Script/Landscape.Landscape",
                }],
                "landscape_components.jsonl": [{
                    "landscape_path": "/Game/Map.Map:PersistentLevel.Landscape_0",
                    "component_path": "/Game/Map.Map:PersistentLevel.Landscape_0.LandscapeComponent_0",
                    "component_index": 0,
                }],
                "landscape_weightmap_allocations.jsonl": [{
                    "component_path": "/Game/Map.Map:PersistentLevel.Landscape_0.LandscapeComponent_0",
                    "allocation_index": 0,
                }],
                "landscape_layer_infos.jsonl": [{"layer_info_path": "/Game/Land/LI_Mud.LI_Mud"}],
                "landscape_grass_types.jsonl": [{"grass_type_path": "/Game/Land/GT_Grass.GT_Grass"}],
                "landscape_grass_varieties.jsonl": [{
                    "grass_type_path": "/Game/Land/GT_Grass.GT_Grass",
                    "variety_index": 0,
                }],
                "foliage_types.jsonl": [{
                    "foliage_type_path": "/Game/Foliage/FT_Tree.FT_Tree",
                    "class_path": "/Script/Foliage.FoliageType_InstancedStaticMesh",
                    "mesh_path": "/Game/Meshes/SM_Tree.SM_Tree",
                }],
                "foliage_actors.jsonl": [{
                    "foliage_actor_path": "/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0",
                    "class_path": "/Script/Foliage.InstancedFoliageActor",
                }],
                "foliage_actor_type_infos.jsonl": [{
                    "foliage_actor_path": "/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0",
                    "map_index": 0,
                    "foliage_type_path": "/Game/Foliage/FT_Tree.FT_Tree",
                    "instances_reflected_as_struct_array": True,
                }],
                "foliage_instances.jsonl": [{
                    "foliage_actor_path": "/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0",
                    "map_index": 0,
                    "instance_index": 0,
                }],
                "hlod_layers.jsonl": [{
                    "hlod_layer_path": "/Game/HLOD/HLOD_Default.HLOD_Default",
                    "class_path": "/Script/Engine.HLODLayer",
                }],
                "world_geometry_properties.jsonl": [{
                    "owner_path": "/Game/Foliage/FT_Tree.FT_Tree",
                    "property_name": "Density",
                    "family": "foliage",
                    "role": "foliage_type",
                }],
            }
            for filename, values in rows.items():
                write_jsonl(output / filename, values)

            counts = {key: len(rows[filename]) for key, filename in capture.COUNT_FILES.items()}
            counts.update({
                "registry_candidates": 6,
                "load_failures": 0,
                "foliage_info_maps_opaque": 0,
            })
            manifest = {
                "schema_version": 1,
                "success": True,
                "error": "",
                "diagnostic_only": True,
                "semantic_promotion": False,
                "schema_promotion": False,
                "runtime_state_captured": False,
                "generated_geometry_captured": False,
                "render_resources_captured": False,
                "world_runtime_streaming_state_captured": False,
                "maps_loaded": False,
                "counts": counts,
            }
            (output / "world_geometry_capture_manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            validated = capture.validate_capture(output)
            self.assertEqual(validated["counts"]["registry_candidates"], 6)
            report = capture.semantic_report(output, validated)
            self.assertIn("foliage_types_with_mesh_ref: 1", report)
            self.assertIn("foliage_infos_with_reflected_instance_array: 1", report)
            self.assertIn("generated_geometry_captured=False", report)

    def test_validator_rejects_hlod_false_positive(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            for filename in capture.COUNT_FILES.values():
                write_jsonl(output / filename, [])
            write_jsonl(output / "hlod_layers.jsonl", [{
                "hlod_layer_path": "/Game/Characters/LOD.LOD",
                "class_path": "/Script/Engine.SkeletalMeshLODSettings",
            }])
            counts = {key: 0 for key in capture.COUNT_FILES}
            counts["hlod_layers"] = 1
            manifest = {
                "schema_version": 1,
                "success": True,
                "diagnostic_only": True,
                "semantic_promotion": False,
                "schema_promotion": False,
                "runtime_state_captured": False,
                "generated_geometry_captured": False,
                "render_resources_captured": False,
                "world_runtime_streaming_state_captured": False,
                "maps_loaded": False,
                "counts": {**counts, "registry_candidates": 1, "load_failures": 0},
            }
            (output / "world_geometry_capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "non-HLODLayer"):
                capture.validate_capture(output)


if __name__ == "__main__":
    unittest.main()
