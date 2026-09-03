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
import uatool_world_geometry_evidence as evidence


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def iter_rows(path: Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            yield json.loads(line)


class WorldGeometryEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        write_jsonl(self.root / "assets.jsonl", [
            {
                "object_path": "/Game/Land/L_Layer.L_Layer",
                "class_path": "/Script/Landscape.LandscapeLayerInfoObject",
                "tags": {"LayerName": "Mud"},
            },
            {
                "object_path": "/Game/Foliage/FT_Tree.FT_Tree",
                "class_path": "/Script/Foliage.FoliageType_InstancedStaticMesh",
                "tags": {"Mesh": "/Game/Meshes/SM_Tree.SM_Tree"},
            },
            {
                "object_path": "/Game/HLOD/HLOD_Default.HLOD_Default",
                "class_path": "/Script/Engine.HLODLayer",
                "tags": {},
            },
            {
                "object_path": "/Game/Foliage/SM_FoliageNamed.SM_FoliageNamed",
                "class_path": "/Script/Engine.StaticMesh",
                "tags": {"NameLooksLike": "Foliage"},
            },
        ])
        write_jsonl(self.root / "world_actors.jsonl", [
            {
                "actor_path": "/Game/Map.Map:PersistentLevel.Landscape_0",
                "actor_class": "/Script/Landscape.Landscape",
                "actor_name": "Landscape_0",
            },
            {
                "actor_path": "/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0",
                "actor_class": "/Script/Foliage.InstancedFoliageActor",
                "actor_name": "InstancedFoliageActor_0",
            },
            {
                "actor_path": "/Game/Map.Map:PersistentLevel.HLOD_0",
                "actor_class": "/Script/Engine.WorldPartitionHLOD",
                "actor_name": "HLOD_0",
            },
            {
                "actor_path": "/Game/Map.Map:PersistentLevel.FoliageNamedOnly",
                "actor_class": "/Script/Engine.Actor",
                "actor_name": "FoliageNamedOnly",
            },
        ])
        write_jsonl(self.root / "world_components.jsonl", [
            {
                "component_path": "/Game/Map.Map:PersistentLevel.Landscape_0.LandscapeComponent_0",
                "actor_path": "/Game/Map.Map:PersistentLevel.Landscape_0",
                "component_class": "/Script/Landscape.LandscapeComponent",
            },
            {
                "component_path": "/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0.HISM_0",
                "actor_path": "/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0",
                "component_class": "/Script/Engine.HierarchicalInstancedStaticMeshComponent",
            },
            {
                "component_path": "/Game/Map.Map:PersistentLevel.FoliageNamedOnly.HISM_1",
                "actor_path": "/Game/Map.Map:PersistentLevel.FoliageNamedOnly",
                "component_class": "/Script/Engine.HierarchicalInstancedStaticMeshComponent",
            },
        ])
        write_jsonl(self.root / "world_instance_properties.jsonl", [
            {
                "owner_path": "/Game/Map.Map:PersistentLevel.Landscape_0.LandscapeComponent_0",
                "property_path": "SectionBaseX",
                "property_name": "SectionBaseX",
                "value": "0",
            },
        ])
        write_jsonl(self.root / "world_references.jsonl", [
            {
                "owner_path": "/Game/Map.Map:PersistentLevel.Landscape_0",
                "property_path": "LandscapeMaterial",
                "root_property": "LandscapeMaterial",
                "target_path": "/Game/Materials/M_Land.M_Land",
                "target_class": "/Script/Engine.Material",
            },
            {
                "owner_path": "/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0",
                "property_path": "FoliageInfos",
                "target_path": "/Game/Foliage/FT_Tree.FT_Tree",
                "target_class": "/Script/Foliage.FoliageType_InstancedStaticMesh",
            },
        ])
        write_jsonl(self.root / "systems_properties.jsonl", [
            {
                "asset_path": "/Game/Foliage/FT_Tree.FT_Tree",
                "property_path": "Density",
                "property_name": "Density",
                "value": "100",
            },
            {
                "asset_path": "/Game/HLOD/HLOD_Default.HLOD_Default",
                "property_path": "LayerType",
                "property_name": "LayerType",
                "value": "Instancing",
            },
        ])
        write_jsonl(self.root / "systems_references.jsonl", [])
        write_jsonl(self.root / "world_partition_actor_descs.jsonl", [
            {
                "actor_soft_path": "/Game/Map.Map:PersistentLevel.Actor_1",
                "native_class": "/Script/Engine.Actor",
                "hlod_relevant": True,
            },
            {
                "actor_soft_path": "/Game/Map.Map:PersistentLevel.HLOD_0",
                "native_class": "/Script/Engine.WorldPartitionHLOD",
                "hlod_relevant": False,
            },
        ])

    def tearDown(self):
        self.temp.cleanup()

    def test_exact_class_paths_and_owner_provenance_define_candidates(self):
        report = evidence.build_report(self.root, iter_rows, example_limit=10)
        self.assertTrue(report["diagnostic_only"])
        self.assertFalse(report["semantic_promotion"])
        self.assertFalse(report["schema_promotion"])
        self.assertFalse(report["generated_geometry_captured"])

        self.assertEqual(report["proof"]["landscape"]["exact_asset_candidates"], 1)
        self.assertEqual(report["proof"]["foliage"]["exact_asset_candidates"], 1)
        self.assertEqual(report["proof"]["hlod"]["exact_asset_candidates"], 1)
        self.assertEqual(report["proof"]["landscape"]["exact_world_actor_candidates"], 1)
        self.assertEqual(report["proof"]["foliage"]["exact_world_actor_candidates"], 1)
        self.assertEqual(report["proof"]["hlod"]["exact_world_actor_candidates"], 1)

        # The unrelated StaticMesh/Actor containing "Foliage" only in the path/name
        # never becomes a foliage candidate.
        self.assertEqual(report["class_counts"]["assets"]["foliage"]["/Script/Engine.StaticMesh"], 0)
        self.assertEqual(report["class_counts"]["actors"]["foliage"]["/Script/Engine.Actor"], 0)

        # Both HISM components are visible globally, but only the one owned by the
        # exact /Script/Foliage actor receives foliage association.
        self.assertEqual(
            report["generic_instance_component_classes"]["/Script/Engine.HierarchicalInstancedStaticMeshComponent"],
            2,
        )
        self.assertEqual(report["generic_instance_components_under_foliage_actor"], 1)
        self.assertEqual(
            report["class_counts"]["components"]["foliage"]["/Script/Engine.HierarchicalInstancedStaticMeshComponent"],
            1,
        )

    def test_world_and_asset_owned_evidence_stay_separate(self):
        report = evidence.build_report(self.root, iter_rows, example_limit=10)
        self.assertEqual(report["proof"]["landscape"]["world_authored_property_rows"], 1)
        self.assertEqual(report["proof"]["landscape"]["world_authored_reference_rows"], 1)
        self.assertEqual(report["proof"]["foliage"]["asset_owned_system_property_rows"], 1)
        self.assertEqual(report["proof"]["hlod"]["asset_owned_system_property_rows"], 1)
        self.assertEqual(report["partition_hlod_relevant_descriptors"], 1)
        self.assertEqual(report["property_counts"]["landscape"]["SectionBaseX"], 1)
        self.assertEqual(report["asset_property_counts"]["foliage"]["Density"], 1)

    def test_canonical_facade_and_freshness_keep_evidence_read_only(self):
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        source = (SCRIPTS / "uatool_world_geometry_evidence.py").read_text(encoding="utf-8")
        self.assertIn("uatool_world_geometry_evidence", facade)
        self.assertIn("_world_geometry_evidence.install(_runtime)", facade)
        self.assertIn('sys.argv[1] == "landscape-foliage-hlod-evidence"', source)
        self.assertIn('"diagnostic_only": True', source)
        self.assertIn('"schema_promotion": False', source)
        self.assertIn("uatool_world_geometry_evidence.py", freshness.NON_DERIVED_SCRIPTS)


if __name__ == "__main__":
    unittest.main()
