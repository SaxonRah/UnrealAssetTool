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

import uatool_staticmesh_schema as schema
import uatool_staticmesh_model as model
import uatool_staticmesh_graph as graph
import uatool_staticmesh_capabilities as mesh_capabilities


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text("".join(json.dumps(value, separators=(",", ":")) + "\n" for value in values), encoding="utf-8")


def rows(path: Path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class StubGraph:
    DERIVED_SCHEMA_VERSION = 29
    COVERAGE_RANK = {"external_or_excluded": 0, "generic_only": 1, "partial": 2, "first_class_depth_pending": 3, "first_class": 4}

    @staticmethod
    def _node_id(kind, path):
        return f"node:{kind}:{path}"

    @staticmethod
    def _edge_id(sk, source, relation, tk, target):
        return f"edge:{sk}:{source}:{relation}:{tk}:{target}"

    @staticmethod
    def _package(path):
        return str(path).split(".", 1)[0] if str(path).startswith("/") else ""


class StaticMeshSchema1Test(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.corpus = self.root / ".uatool"
        self.capture = self.corpus / "staticmesh-native-capture"
        self.capture.mkdir(parents=True)
        self.mesh = "/Game/Test/SM_a.SM_a"
        self.body = self.mesh + ":BodySetup_0"
        write_json(self.corpus / "manifest.json", {
            "schema_version": 12,
            "world_schema_version": 12,
            "animation_schema_version": 3,
            "derived_schema_version": 29,
            "canonical_passes": ["structural", "world", "animation"],
        })
        write_json(self.capture / "staticmesh_capture_manifest.json", {
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
            "engine_version": "5.8.2",
            "counts": {
                "registry_candidates": 1, "static_meshes": 1, "load_failures": 0,
                "source_models": 1, "materials": 2, "sockets": 1,
                "body_setups": 1, "collision_shapes": 1, "selected_properties": 3,
            },
        })
        write_jsonl(self.capture / "staticmesh_assets.jsonl", [{
            "static_mesh_path": self.mesh,
            "class_path": "/Script/Engine.StaticMesh",
            "package_name": "/Game/Test/SM_a",
            "registry_lod_count": 0,
            "registry_material_count": 2,
            "registry_collision_prim_count": 1,
            "registry_nanite_enabled": True,
            "source_model_count": 1,
            "static_material_count": 2,
            "socket_count": 1,
            "body_setup_path": self.body,
            "complex_collision_mesh_path": "",
        }])
        write_jsonl(self.capture / "staticmesh_source_models.jsonl", [{
            "static_mesh_path": self.mesh,
            "lod_index": 0,
            "source_model_struct": "/Script/Engine.StaticMeshSourceModel",
            "fields": {
                "ScreenSize": "(Default=1.000000)",
                "SourceImportFilename": "mesh.fbx",
                "bImportWithBaseMesh": "False",
                "StaticMeshDescriptionBulkData": "must-not-promote",
            },
            "build_settings_struct": "/Script/Engine.MeshBuildSettings",
            "build_settings": {"bRecomputeNormals": "False"},
            "reduction_settings_struct": "/Script/Engine.MeshReductionSettings",
            "reduction_settings": {"PercentTriangles": "1.000000"},
        }])
        write_jsonl(self.capture / "staticmesh_materials.jsonl", [
            {
                "static_mesh_path": self.mesh, "material_index": 0,
                "material_path": "/Game/Test/M.M", "material_class": "/Script/Engine.Material",
                "material_slot_name": "Body", "imported_material_slot_name": "Body", "uv_channel_data": "()",
            },
            {
                "static_mesh_path": self.mesh, "material_index": 1,
                "material_path": "", "material_class": "",
                "material_slot_name": "Empty", "imported_material_slot_name": "Empty", "uv_channel_data": "()",
            },
        ])
        write_jsonl(self.capture / "staticmesh_sockets.jsonl", [{
            "static_mesh_path": self.mesh, "socket_index": 0,
            "socket_path": self.mesh + ":Socket_0", "socket_class": "/Script/Engine.StaticMeshSocket",
            "socket_name": "Attach", "relative_location": "(X=1)", "relative_rotation": "()", "relative_scale": "(X=1,Y=1,Z=1)", "tag": "",
        }])
        write_jsonl(self.capture / "staticmesh_body_setups.jsonl", [{
            "static_mesh_path": self.mesh, "body_setup_path": self.body, "body_setup_class": "/Script/Engine.BodySetup",
            "collision_trace_flag": "CTF_UseSimpleAndComplex", "default_instance": "()", "phys_material": "None",
            "build_scale3d": "(X=1,Y=1,Z=1)", "walkable_slope_override": "()", "double_sided_geometry": "False",
            "never_needs_cooked_collision_data": "False",
        }])
        write_jsonl(self.capture / "staticmesh_collision_shapes.jsonl", [{
            "static_mesh_path": self.mesh, "body_setup_path": self.body,
            "shape_type": "BoxElems", "shape_index": 0, "shape_struct": "/Script/Engine.KBoxElem",
            "fields": {"X": "10"}, "raw_value": "(X=10)",
        }])
        write_jsonl(self.capture / "staticmesh_properties.jsonl", [
            {
                "static_mesh_path": self.mesh, "property_name": "NaniteSettings",
                "property_type": "StructProperty", "cpp_type": "FMeshNaniteSettings",
                "struct_type": "/Script/Engine.MeshNaniteSettings", "value": "(bEnabled=True)", "fields": {"bEnabled": "True"},
            },
            {
                "static_mesh_path": self.mesh, "property_name": "SectionInfoMap",
                "property_type": "StructProperty", "cpp_type": "FMeshSectionInfoMap",
                "struct_type": "/Script/Engine.MeshSectionInfoMap", "value": "(Map=((0,())))", "fields": {},
            },
            {
                "static_mesh_path": self.mesh, "property_name": "LODGroup",
                "property_type": "NameProperty", "cpp_type": "FName", "value": "SmallProp",
            },
        ])

    def tearDown(self):
        self.temp.cleanup()

    def test_promotion_uses_loaded_source_models_and_preserves_structural_12(self):
        manifest = schema.promote_capture(self.corpus, self.capture)
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["source_capture_schema_version"], 2)
        top = json.loads((self.corpus / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(top["schema_version"], 12)
        self.assertEqual(top["mesh_schema_version"], 1)
        mesh = rows(self.corpus / "static_meshes.jsonl")[0]
        self.assertEqual(mesh["lod_count"], 1)
        self.assertEqual(mesh["registry_summary"]["lod_count"], 0)
        self.assertTrue(mesh["nanite_enabled"])
        lod = rows(self.corpus / "static_mesh_lods.jsonl")[0]
        self.assertNotIn("StaticMeshDescriptionBulkData", lod)
        self.assertEqual(lod["screen_size"], "(Default=1.000000)")
        self.assertIsNone(schema.validation_error(self.corpus, require_present=True))

    def test_model_preserves_owner_namespaced_topology_and_skips_empty_material_target(self):
        schema.promote_capture(self.corpus, self.capture)
        data = model.build_model(self.corpus, rows)
        edges = {(e["source"], e["relation"], e["target"]) for e in data["edge_specs"]}
        self.assertIn((self.mesh, "static_mesh_has_lod", self.mesh + "#lod:0"), edges)
        self.assertIn((self.mesh, "static_mesh_has_material_slot", self.mesh + "#material-slot:1"), edges)
        self.assertIn((self.mesh + "#material-slot:0", "material_slot_uses_material", "/Game/Test/M.M"), edges)
        self.assertFalse(any(source.endswith("#material-slot:1") and relation == "material_slot_uses_material" for source, relation, _ in edges))
        self.assertIn((self.body, "body_setup_has_collision_shape", self.body + "#shape:BoxElems:0"), edges)

    def test_graph_is_exact_and_promotes_derived_30(self):
        schema.promote_capture(self.corpus, self.capture)
        nodes, edges = graph._augment(self.corpus, rows, [], [], StubGraph)
        self.assertTrue(all(edge["edge_quality"] == "exact_semantic" for edge in edges))
        lod_edge = next(edge for edge in edges if edge["relation"] == "static_mesh_has_lod")
        self.assertEqual(lod_edge["evidence"][0]["stream"], "static_mesh_lods.jsonl")
        class Core:
            DERIVED_SCHEMA_VERSION = 29
        class Runtime:
            DERIVED_SCHEMA_VERSION = 29
        stub = StubGraph()
        graph.promote_public_derived_version(stub, Core, Runtime)
        self.assertEqual(stub.DERIVED_SCHEMA_VERSION, 30)
        self.assertEqual(Core.DERIVED_SCHEMA_VERSION, 30)
        self.assertEqual(Runtime.DERIVED_SCHEMA_VERSION, 30)

    def test_sqlite_round_trip(self):
        schema.promote_capture(self.corpus, self.capture)
        conn = sqlite3.connect(":memory:")
        schema.create_schema(conn)
        schema.load_database(conn, self.corpus, rows)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM static_meshes").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT lod_count FROM static_meshes").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM static_mesh_material_slots").fetchone()[0], 2)
        conn.close()

    def test_capability_adds_independent_mesh_schema(self):
        schema.promote_capture(self.corpus, self.capture)

        class StubCapabilities:
            @staticmethod
            def _read_json(path):
                if not Path(path).is_file(): return {}
                return json.loads(Path(path).read_text(encoding="utf-8"))

            @staticmethod
            def _manifest_files(manifest):
                files = manifest.get("files", [])
                return list(files) if isinstance(files, list) else []

            @staticmethod
            def build_manifest(output):
                return {"schemas": {"structural": 12, "derived": 30}, "families": [], "canonical_passes": ["structural"]}

        mesh_capabilities.install(StubCapabilities)
        manifest = StubCapabilities.build_manifest(self.corpus)
        self.assertEqual(manifest["schemas"]["structural"], 12)
        self.assertEqual(manifest["schemas"]["mesh"], 1)
        family = next(row for row in manifest["families"] if row["family"] == "static_mesh")
        self.assertEqual(family["contract_coverage"], "first_class")
        self.assertTrue(family["available_in_corpus"])
        self.assertIn("mesh", manifest["canonical_passes"])


if __name__ == "__main__":
    unittest.main()
