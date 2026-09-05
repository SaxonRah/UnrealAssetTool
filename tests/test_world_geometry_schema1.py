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

import uatool_world_geometry_accept as accept
import uatool_world_geometry_graph as graph
import uatool_world_geometry_model as model
import uatool_world_geometry_schema as schema


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


class WorldGeometrySchema1Test(unittest.TestCase):
    def test_public_versions_and_real_contentexamples_contract(self):
        self.assertEqual(schema.WORLD_GEOMETRY_SCHEMA_VERSION, 1)
        self.assertEqual(graph.TARGET_DERIVED_SCHEMA_VERSION, 31)
        self.assertEqual(accept.CONTENTEXAMPLES_EXACT_COUNTS["world_geometry_landscapes"], 75)
        self.assertEqual(accept.CONTENTEXAMPLES_EXACT_COUNTS["world_geometry_landscape_components"], 100)
        self.assertEqual(accept.CONTENTEXAMPLES_EXACT_COUNTS["world_geometry_landscape_layer_allocations"], 256)
        self.assertEqual(accept.CONTENTEXAMPLES_EXACT_COUNTS["world_geometry_foliage_infos"], 6)
        self.assertEqual(accept.CONTENTEXAMPLES_EXACT_COUNTS["world_geometry_foliage_instances"], 101)
        self.assertEqual(accept.CONTENTEXAMPLES_EXACT_COUNTS["world_geometry_hlod_layers"], 4)
        self.assertEqual(accept.CONTENTEXAMPLES_EXACT_COUNTS["foliage_infos_native_editor_array"], 6)
        self.assertEqual(accept.CONTENTEXAMPLES_EXACT_COUNTS["foliage_instances_native_editor_array"], 101)

    def test_query_uses_shared_printer_contract(self):
        conn = sqlite3.connect(":memory:")
        try:
            schema.create_schema(conn)
            calls = []

            def print_rows(rows_value, fields):
                calls.append((list(rows_value), tuple(fields)))

            schema.query(conn, print_rows, "%NoMatch%", 5)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][1], ("kind", "path", "detail"))
            self.assertEqual(calls[0][0], [])
        finally:
            conn.close()

    def test_schema_is_independent_and_authored_only(self):
        source = (SCRIPTS / "uatool_world_geometry_schema.py").read_text(encoding="utf-8")
        integration = (SCRIPTS / "uatool_world_geometry_integration.py").read_text(encoding="utf-8")
        capabilities = (SCRIPTS / "uatool_world_geometry_capabilities.py").read_text(encoding="utf-8")
        self.assertIn('MANIFEST_FILE = "world_geometry_manifest.json"', source)
        self.assertIn('"world_geometry_schema_version"', source)
        self.assertIn('AUTO_CAPTURE_DIR = "world-geometry-native-capture"', integration)
        self.assertIn("TARGET_DERIVED_SCHEMA_VERSION = 31", (SCRIPTS / "uatool_world_geometry_graph.py").read_text(encoding="utf-8"))
        self.assertIn("HISM render-instance substitution", capabilities)
        for forbidden in (
            "PerInstanceSMData",
            "GetInstanceTransform",
            "GetResourceForRendering",
            "LoadMap(",
            "CreatePhysicsState",
            "StartSimulation",
        ):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, (SCRIPTS / "uatool_world_geometry_model.py").read_text(encoding="utf-8"))

    def test_model_uses_stable_struct_nodes_and_exact_relations(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            canonical = {
                "world_geometry_landscapes.jsonl": [{
                    "landscape_path": "/Game/Map.Map:PersistentLevel.Landscape_0",
                    "class_path": "/Script/Landscape.Landscape",
                    "package_name": "/Game/Map",
                    "landscape_material_path": "/Game/Mat/M_Land.M_Land",
                    "landscape_hole_material_path": "",
                }],
                "world_geometry_landscape_components.jsonl": [{
                    "landscape_path": "/Game/Map.Map:PersistentLevel.Landscape_0",
                    "component_path": "/Game/Map.Map:PersistentLevel.Landscape_0.LandscapeComponent_0",
                    "component_class": "/Script/Landscape.LandscapeComponent",
                    "component_index": 0,
                    "heightmap_texture_path": "/Game/Map.Map:PersistentLevel.Landscape_0.Heightmap_0",
                    "heightmap_texture_class": "/Script/Engine.Texture2D",
                }],
                "world_geometry_landscape_weightmaps.jsonl": [{
                    "landscape_path": "/Game/Map.Map:PersistentLevel.Landscape_0",
                    "component_path": "/Game/Map.Map:PersistentLevel.Landscape_0.LandscapeComponent_0",
                    "texture_index": 0,
                    "texture_path": "/Game/Map.Map:PersistentLevel.Landscape_0.Weightmap_0",
                    "texture_class": "/Script/Engine.Texture2D",
                }],
                "world_geometry_landscape_layer_allocations.jsonl": [{
                    "landscape_path": "/Game/Map.Map:PersistentLevel.Landscape_0",
                    "component_path": "/Game/Map.Map:PersistentLevel.Landscape_0.LandscapeComponent_0",
                    "allocation_index": 0,
                    "layer_info_path": "/Game/Land/LI_Grass.LI_Grass",
                    "weightmap_texture_index": "0",
                    "weightmap_texture_channel": "2",
                    "struct_type": "/Script/Landscape.WeightmapLayerAllocationInfo",
                }],
                "world_geometry_landscape_layer_infos.jsonl": [{
                    "layer_info_path": "/Game/Land/LI_Grass.LI_Grass",
                    "class_path": "/Script/Landscape.LandscapeLayerInfoObject",
                    "package_name": "/Game/Land/LI_Grass",
                }],
                "world_geometry_grass_types.jsonl": [{
                    "grass_type_path": "/Game/Land/GT_Grass.GT_Grass",
                    "class_path": "/Script/Landscape.LandscapeGrassType",
                    "package_name": "/Game/Land/GT_Grass",
                }],
                "world_geometry_grass_varieties.jsonl": [{
                    "grass_type_path": "/Game/Land/GT_Grass.GT_Grass",
                    "variety_index": 0,
                    "struct_type": "/Script/Landscape.GrassVariety",
                    "grass_mesh_path": "/Game/Mesh/SM_Grass.SM_Grass",
                }],
                "world_geometry_foliage_types.jsonl": [{
                    "foliage_type_path": "/Game/Foliage/FT_Tree.FT_Tree",
                    "class_path": "/Script/Foliage.FoliageType_InstancedStaticMesh",
                    "package_name": "/Game/Foliage/FT_Tree",
                    "mesh_path": "/Game/Mesh/SM_Tree.SM_Tree",
                    "mesh_class": "/Script/Engine.StaticMesh",
                }],
                "world_geometry_foliage_actors.jsonl": [{
                    "foliage_actor_path": "/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0",
                    "class_path": "/Script/Foliage.InstancedFoliageActor",
                    "package_name": "/Game/Map",
                }],
                "world_geometry_foliage_infos.jsonl": [{
                    "foliage_actor_path": "/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0",
                    "map_index": 0,
                    "foliage_type_path": "/Game/Foliage/FT_Tree.FT_Tree",
                    "foliage_type_class": "/Script/Foliage.FoliageType_InstancedStaticMesh",
                    "capture_mode": "native_editor_array",
                }],
                "world_geometry_foliage_instances.jsonl": [{
                    "foliage_actor_path": "/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0",
                    "map_index": 0,
                    "instance_index": 0,
                    "instance_struct": "FFoliageInstance",
                    "capture_mode": "native_editor_array",
                    "base_component_path": "",
                    "base_component_class": "",
                    "base_id": 7,
                }],
                "world_geometry_hlod_layers.jsonl": [{
                    "hlod_layer_path": "/Game/HLOD/HLOD_Parent.HLOD_Parent",
                    "class_path": "/Script/Engine.HLODLayer",
                    "package_name": "/Game/HLOD/HLOD_Parent",
                    "parent_layer_path": "",
                    "linked_layer_path": "",
                    "builder_settings_path": "/Game/HLOD/HLOD_Parent.HLOD_Parent:HLODBuilderSettings",
                    "builder_settings_class": "/Script/Engine.HLODBuilderSettings",
                }, {
                    "hlod_layer_path": "/Game/HLOD/HLOD_Child.HLOD_Child",
                    "class_path": "/Script/Engine.HLODLayer",
                    "package_name": "/Game/HLOD/HLOD_Child",
                    "parent_layer_path": "/Game/HLOD/HLOD_Parent.HLOD_Parent",
                    "parent_layer_class": "/Script/Engine.HLODLayer",
                    "linked_layer_path": "",
                    "builder_settings_path": "/Game/HLOD/HLOD_Child.HLOD_Child:HLODBuilderSettings",
                    "builder_settings_class": "/Script/Engine.HLODBuilderSettings",
                }],
            }
            for filename in schema.JSONL_FILES:
                write_jsonl(output / filename, canonical.get(filename, []))

            built = model.build_model(output, rows)
            edge_keys = {
                (edge["source"], edge["relation"], edge["target"])
                for edge in built["edge_specs"]
            }
            component = "/Game/Map.Map:PersistentLevel.Landscape_0.LandscapeComponent_0"
            allocation = model.allocation_path(component, 0)
            info = model.foliage_info_path("/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0", 0)
            instance = model.foliage_instance_path("/Game/Map.Map:PersistentLevel.InstancedFoliageActor_0", 0, 0)
            self.assertIn((component, "landscape_component_has_layer_allocation", allocation), edge_keys)
            self.assertIn((allocation, "landscape_allocation_uses_layer_info", "/Game/Land/LI_Grass.LI_Grass"), edge_keys)
            self.assertIn((info, "foliage_info_has_instance", instance), edge_keys)
            self.assertNotIn((instance, "foliage_instance_uses_base_component", "7"), edge_keys)
            self.assertIn(("/Game/HLOD/HLOD_Child.HLOD_Child", "hlod_layer_has_parent_layer", "/Game/HLOD/HLOD_Parent.HLOD_Parent"), edge_keys)


if __name__ == "__main__":
    unittest.main()
