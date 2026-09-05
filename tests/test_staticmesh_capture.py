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

import uatool_staticmesh_capture as capture


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(value, separators=(",", ":")) + "\n" for value in values),
        encoding="utf-8",
    )


class StaticMeshCaptureTest(unittest.TestCase):
    def test_validation_preserves_authored_topology_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mesh = "/Game/Meshes/SM_Test.SM_Test"
            body = mesh + ":BodySetup"
            rows = {
                "staticmesh_assets.jsonl": [{
                    "static_mesh_path": mesh,
                    "class_path": capture.STATIC_MESH_CLASS,
                    "registry_lod_count": 2,
                    "registry_material_count": 1,
                    "registry_collision_prim_count": 1,
                    "registry_nanite_enabled": True,
                    "source_model_count": 2,
                    "static_material_count": 1,
                    "socket_count": 1,
                    "body_setup_path": body,
                }],
                "staticmesh_source_models.jsonl": [
                    {"static_mesh_path": mesh, "lod_index": 0, "build_settings": {"bRecomputeNormals": "False"}, "reduction_settings": {}},
                    {"static_mesh_path": mesh, "lod_index": 1, "build_settings": {"bRecomputeNormals": "True"}, "reduction_settings": {"PercentTriangles": "0.5"}},
                ],
                "staticmesh_materials.jsonl": [{"static_mesh_path": mesh, "material_index": 0, "material_path": "/Game/M_Mat.M_Mat"}],
                "staticmesh_sockets.jsonl": [{"static_mesh_path": mesh, "socket_index": 0, "socket_path": mesh + ":Socket0", "socket_name": "Grip"}],
                "staticmesh_body_setups.jsonl": [{"static_mesh_path": mesh, "body_setup_path": body, "collision_trace_flag": "CTF_UseSimpleAndComplex"}],
                "staticmesh_collision_shapes.jsonl": [{"static_mesh_path": mesh, "body_setup_path": body, "shape_type": "BoxElems", "shape_index": 0}],
                "staticmesh_properties.jsonl": [
                    {"static_mesh_path": mesh, "property_name": "NaniteSettings", "property_type": "StructProperty", "value": "(...)"},
                    {"static_mesh_path": mesh, "property_name": "SectionInfoMap", "property_type": "StructProperty", "value": "(...)"},
                ],
            }
            for filename, values in rows.items():
                write_jsonl(root / filename, values)
            manifest = {
                "schema_version": 2,
                "success": True,
                "selected_struct_field_policy": "direct_safe_scalar_leaves_only: bool,numeric,enum,name,string,text; object/container/delegate/nested-struct members skipped",
                "diagnostic_only": True,
                "semantic_promotion": False,
                "schema_promotion": False,
                "runtime_state_captured": False,
                "render_buffers_captured": False,
                "nanite_resources_captured": False,
                "runtime_physics_state_captured": False,
                "maps_loaded": False,
                "counts": {
                    "registry_candidates": 1,
                    "static_meshes": 1,
                    "load_failures": 0,
                    "source_models": 2,
                    "materials": 1,
                    "sockets": 1,
                    "body_setups": 1,
                    "collision_shapes": 1,
                    "selected_properties": 2,
                    "registry_multi_lod_assets": 1,
                    "registry_nanite_enabled_assets": 1,
                    "registry_collision_primitive_assets": 1,
                    "registry_material_assets": 1,
                },
            }
            (root / "staticmesh_capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            result = capture.validate_capture(root)
            self.assertEqual(result["counts"]["static_meshes"], 1)
            report = capture.semantic_report(root, result)
            self.assertIn("lod_count_mismatches: 0", report)
            self.assertIn("material_count_mismatches: 0", report)
            self.assertIn("collision_prim_count_mismatches: 0", report)
            self.assertIn("NaniteSettings", report)
            self.assertIn("SectionInfoMap", report)

    def test_cpp_capture_is_authored_only_and_avoids_render_runtime_apis(self) -> None:
        source = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolStaticMeshCommandlet.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn('StaticMeshClassPath = TEXT("/Script/Engine.StaticMesh")', source)
        for token in ("SourceModels", "StaticMaterials", "Sockets", "BodySetup", "AggGeom", "NaniteSettings", "SectionInfoMap"):
            self.assertIn(token, source)
        for forbidden in (
            "GetRenderData(", "RenderData->", "NaniteResources", "CreatePhysicsMeshes(",
            "GetPhysicsTriMeshData(", "LoadMap(", "OpenLevel(", "TickWorld(",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn('SetBoolField(TEXT("render_buffers_captured"), false)', source)
        self.assertIn('SetBoolField(TEXT("nanite_resources_captured"), false)', source)
        self.assertIn('SetBoolField(TEXT("runtime_physics_state_captured"), false)', source)
        self.assertIn('SetBoolField(TEXT("maps_loaded"), false)', source)
        self.assertIn("constexpr int32 SchemaVersion = 2;", source)
        self.assertIn("static bool IsSafeSelectedStructLeaf", source)
        self.assertIn("static TSharedRef<FJsonObject> SelectedStructFields", source)
        self.assertIn("CastField<FBoolProperty>", source)
        self.assertIn("CastField<FNumericProperty>", source)
        self.assertIn("CastField<FEnumProperty>", source)
        self.assertIn("CastField<FNameProperty>", source)
        self.assertIn("CastField<FStrProperty>", source)
        self.assertIn("CastField<FTextProperty>", source)
        selected_block = source[
            source.index("static bool WriteSelectedProperties"):
            source.index("static bool WriteSourceModels")
        ]
        self.assertIn("SelectedStructFields(", selected_block)
        self.assertNotIn("StructFields(StructProperty->Struct", selected_block)
        self.assertIn("selected_struct_field_policy", source)

    def test_launcher_is_canonical_and_headless(self) -> None:
        launcher = (SCRIPTS / "uatool_staticmesh_capture.py").read_text(encoding="utf-8")
        self.assertIn('"-run=UnrealAssetToolStaticMesh"', launcher)
        self.assertIn('"-nullrhi"', launcher)
        self.assertIn('"-nosound"', launcher)
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_staticmesh_capture as _staticmesh_capture", facade)
        self.assertIn("_staticmesh_capture.install(_runtime, _core)", facade)
        freshness = (SCRIPTS / "uatool_derived_freshness.py").read_text(encoding="utf-8")
        self.assertIn('"uatool_staticmesh_capture.py"', freshness)


if __name__ == "__main__":
    unittest.main()
