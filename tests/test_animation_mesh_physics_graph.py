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

import uatool_animation_mesh_physics_graph as graph
import uatool_animation_mesh_physics_model as model


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text("".join(json.dumps(v, separators=(",", ":")) + "\n" for v in values), encoding="utf-8")


def rows(path: Path):
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class StubGraph:
    DERIVED_SCHEMA_VERSION = 28
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


class AnimationMeshPhysicsGraphTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.mesh = "/Game/Test/SKM_Test.SKM_Test"
        self.physics = "/Game/Test/PA_Test.PA_Test"
        self.body = self.physics + ":Body_0"
        self.constraint = self.physics + ":Constraint_0"
        write_jsonl(self.output / "skeletal_meshes.jsonl", [{
            "skeletal_mesh_path": self.mesh, "class_path": "/Script/Engine.SkeletalMesh", "package_name": "/Game/Test/SKM_Test",
            "skeleton_path": "/Game/Test/SK_Test.SK_Test", "physics_asset_path": self.physics,
            "shadow_physics_asset_path": "", "lod_settings_path": "/Game/Test/LOD.LOD",
        }])
        write_jsonl(self.output / "skeletal_mesh_lods.jsonl", [{"skeletal_mesh_path": self.mesh, "lod_index": 0}])
        write_jsonl(self.output / "skeletal_mesh_materials.jsonl", [{
            "skeletal_mesh_path": self.mesh, "material_index": 0, "material_path": "/Game/Test/M_Test.M_Test",
            "material_class": "/Script/Engine.Material", "material_slot_name": "Body",
        }])
        write_jsonl(self.output / "skeletal_mesh_morph_targets.jsonl", [{
            "skeletal_mesh_path": self.mesh, "morph_index": 0, "morph_target_path": self.mesh + ":Smile", "class_path": "/Script/Engine.MorphTarget",
        }])
        write_jsonl(self.output / "skeletal_mesh_clothing_assets.jsonl", [])
        write_jsonl(self.output / "skeletal_mesh_clothing_configs.jsonl", [])
        write_jsonl(self.output / "physics_assets.jsonl", [{
            "physics_asset_path": self.physics, "class_path": "/Script/Engine.PhysicsAsset", "package_name": "/Game/Test/PA_Test",
            "preview_skeletal_mesh_path": self.mesh,
        }])
        write_jsonl(self.output / "physics_bodies.jsonl", [{
            "physics_asset_path": self.physics, "body_index": 0, "body_path": self.body,
            "body_class": "/Script/Engine.SkeletalBodySetup", "bone_name": "pelvis",
        }])
        write_jsonl(self.output / "physics_body_shapes.jsonl", [{
            "physics_asset_path": self.physics, "body_index": 0, "body_path": self.body,
            "shape_type": "SphylElems", "shape_index": 0, "shape_struct": "/Script/Engine.KSphylElem",
        }])
        write_jsonl(self.output / "physics_constraints.jsonl", [{
            "physics_asset_path": self.physics, "constraint_index": 0, "constraint_path": self.constraint,
            "constraint_class": "/Script/Engine.PhysicsConstraintTemplate", "joint_name": "pelvis",
            "constraint_bone1": "pelvis", "constraint_bone2": "root",
        }])
        for name in ("physics_constraint_profiles.jsonl", "physics_physical_animation_profiles.jsonl", "physics_collision_disable_pairs.jsonl"):
            write_jsonl(self.output / name, [])

    def tearDown(self):
        self.temp.cleanup()

    def test_model_preserves_exact_authored_endpoints(self):
        data = model.build_model(self.output, rows)
        edges = {(e["source"], e["relation"], e["target"]) for e in data["edge_specs"]}
        self.assertIn((self.mesh, "skeletal_mesh_uses_skeleton", "/Game/Test/SK_Test.SK_Test"), edges)
        self.assertIn((self.mesh, "skeletal_mesh_has_lod", self.mesh + "#lod:0"), edges)
        self.assertIn((self.physics, "physics_asset_owns_body", self.body), edges)
        self.assertIn((self.body, "physics_body_bound_to_bone_name", self.physics + "#bone-name:pelvis"), edges)
        self.assertIn((self.constraint, "physics_constraint_uses_bone2_name", self.physics + "#bone-name:root"), edges)
        self.assertIn((self.body, "physics_body_has_shape", self.body + "#shape:SphylElems:0"), edges)

    def test_project_graph_edges_are_exact_and_upgrade_generic_roots(self):
        nodes = [{
            "node_id": "old", "node_kind": "skeletal_mesh", "path": self.mesh, "coverage": "generic_only",
            "class_path": "/Script/Engine.SkeletalMesh", "package_name": "/Game/Test/SKM_Test", "family": "asset_registry", "root": False,
        }]
        nodes, edges = graph._augment(self.output, rows, nodes, [], StubGraph)
        mesh = next(n for n in nodes if n["node_kind"] == "skeletal_mesh" and n["path"] == self.mesh)
        self.assertEqual(mesh["coverage"], "first_class")
        self.assertTrue(mesh["root"])
        self.assertTrue(all(e["edge_quality"] == "exact_semantic" for e in edges))
        body_edge = next(e for e in edges if e["relation"] == "physics_asset_owns_body")
        self.assertEqual(body_edge["target"], self.body)
        self.assertEqual(body_edge["evidence"][0]["stream"], "physics_bodies.jsonl")

    def test_schema29_promotion_is_monotonic(self):
        class Core:
            DERIVED_SCHEMA_VERSION = 28
        class Runtime:
            DERIVED_SCHEMA_VERSION = 28
        stub = StubGraph()
        graph.promote_public_derived_version(stub, Core, Runtime)
        self.assertEqual(stub.DERIVED_SCHEMA_VERSION, 29)
        self.assertEqual(Core.DERIVED_SCHEMA_VERSION, 29)
        self.assertEqual(Runtime.DERIVED_SCHEMA_VERSION, 29)


if __name__ == "__main__":
    unittest.main()
