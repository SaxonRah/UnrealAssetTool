from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_mass_zonegraph as mz


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _rows(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def _fixture(root: Path) -> None:
    _write(root / "mass_entity_configs.jsonl", [
        {
            "config_path": "/Game/AI/Crowd.Crowd",
            "package_name": "/Game/AI/Crowd",
            "class_path": "/Script/MassSpawner.MassEntityConfigAsset",
            "config_property": "Config",
            "config_guid": "ABC",
            "parent_config_path": "",
            "parent_config_class": "",
            "trait_count": 2,
        }
    ])
    _write(root / "mass_entity_traits.jsonl", [
        {
            "config_path": "/Game/AI/Crowd.Crowd",
            "trait_index": 0,
            "trait_path": "/Game/AI/Crowd.Crowd:Trait_0",
            "trait_class": "/Script/MassMovement.MassMovementTrait",
        },
        {
            "config_path": "/Game/AI/Crowd.Crowd",
            "trait_index": 1,
            "trait_path": "/Game/AI/Crowd.Crowd:Trait_1",
            "trait_class": "/Script/MassZoneGraphNavigation.MassZoneGraphNavigationTrait",
        },
    ])
    _write(root / "mass_spawners.jsonl", [
        {
            "spawner_path": "/Game/AI/BP_Spawner.BP_Spawner",
            "package_name": "/Game/AI/BP_Spawner",
            "generated_class": "/Game/AI/BP_Spawner.BP_Spawner_C",
            "cdo_path": "/Game/AI/BP_Spawner.Default__BP_Spawner_C",
            "entity_type_count": 1,
            "spawn_generator_count": 1,
            "count": "100",
            "auto_spawn_on_begin_play": "True",
        }
    ])
    _write(root / "mass_spawner_entity_types.jsonl", [
        {
            "spawner_path": "/Game/AI/BP_Spawner.BP_Spawner",
            "entity_type_index": 0,
            "entity_config_path": "/Game/AI/Crowd.Crowd",
            "entity_config_class": "/Script/MassSpawner.MassEntityConfigAsset",
            "proportion": "1.000000",
            "raw_value": "(EntityConfig=...,Proportion=1.000000)",
            "truncated": False,
        }
    ])
    _write(root / "mass_spawn_generator_assets.jsonl", [
        {
            "generator_asset_path": "/Game/AI/BP_ZoneGenerator.BP_ZoneGenerator",
            "package_name": "/Game/AI/BP_ZoneGenerator",
            "generated_class": "/Game/AI/BP_ZoneGenerator.BP_ZoneGenerator_C",
            "parent_class": "/Script/MassSpawner.MassEntityZoneGraphSpawnPointsGenerator",
            "cdo_path": "/Game/AI/BP_ZoneGenerator.Default__BP_ZoneGenerator_C",
            "zonegraph_generator": True,
        }
    ])
    _write(root / "mass_spawner_generators.jsonl", [
        {
            "spawner_path": "/Game/AI/BP_Spawner.BP_Spawner",
            "generator_index": 0,
            "generator_path": "/Game/AI/BP_Spawner.Default__BP_Spawner_C:Generator_0",
            "generator_class": "/Game/AI/BP_ZoneGenerator.BP_ZoneGenerator_C",
            "generator_asset_path": "/Game/AI/BP_ZoneGenerator.BP_ZoneGenerator",
            "proportion": "0.750000",
            "raw_value": "(GeneratorInstance=...,Proportion=0.750000)",
            "truncated": False,
        }
    ])
    _write(root / "mass_agent_components.jsonl", [
        {
            "component_path": "/Game/Characters/BP_Player.BP_Player_C:MassAgent",
            "blueprint_path": "/Game/Characters/BP_Player.BP_Player",
            "component_name": "MassAgent",
            "component_class": "/Script/MassActors.MassAgentComponent",
            "entity_config_parent_path": "/Game/AI/Crowd.Crowd",
            "entity_config_parent_class": "/Script/MassSpawner.MassEntityConfigAsset",
            "config_guid": "DEF",
            "raw_entity_config": "(Parent=...,ConfigGuid=DEF)",
            "truncated": False,
        }
    ])
    _write(root / "zonegraph_shapes.jsonl", [
        {
            "shape_path": "/Game/Map/City.City:PersistentLevel.ZoneShape_0",
            "package_name": "/Game/Map/City",
            "class_path": "/Script/ZoneGraph.ZoneShape",
            "component_path": "/Game/Map/City.City:PersistentLevel.ZoneShape_0.ShapeComp",
            "component_class": "/Script/ZoneGraph.ZoneShapeComponent",
            "point_count": 2,
            "shape_type": "Spline",
            "lane_profile": "(Name=Sidewalk)",
            "tags": "(Mask=4)",
            "reverse_lane_profile": "False",
            "polygon_routing_type": "Bezier",
            "relative_location": "(X=0,Y=0,Z=0)",
            "relative_rotation": "(Pitch=0,Yaw=0,Roll=0)",
        }
    ])
    _write(root / "zonegraph_shape_points.jsonl", [
        {
            "shape_path": "/Game/Map/City.City:PersistentLevel.ZoneShape_0",
            "point_index": 0,
            "position": "(X=0,Y=0,Z=0)",
            "rotation": "(Pitch=0,Yaw=0,Roll=0)",
            "tangent_length": "100.000000",
            "point_type": "Sharp",
            "lane_profile": "(Name=Sidewalk)",
            "lane_connection_restrictions": "None",
            "raw_value": "(Position=...)",
            "truncated": False,
        },
        {
            "shape_path": "/Game/Map/City.City:PersistentLevel.ZoneShape_0",
            "point_index": 1,
            "position": "(X=100,Y=0,Z=0)",
            "rotation": "(Pitch=0,Yaw=0,Roll=0)",
            "tangent_length": "100.000000",
            "point_type": "Sharp",
            "lane_profile": "(Name=Sidewalk)",
            "lane_connection_restrictions": "None",
            "raw_value": "(Position=...)",
            "truncated": False,
        },
    ])


class SystemsMassZoneGraphTests(unittest.TestCase):
    def test_validates_and_loads_schema5_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _fixture(root)
            self.assertIsNone(mz.validation_error(root, _rows))

            conn = sqlite3.connect(":memory:")
            try:
                mz.create_schema(conn)
                mz.load_database(conn, root, _rows)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM mass_entity_traits").fetchone()[0], 2)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM mass_spawner_generators").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM zonegraph_shape_points").fetchone()[0], 2)
                self.assertEqual(
                    conn.execute("SELECT zonegraph_generator FROM mass_spawn_generator_assets").fetchone()[0],
                    1,
                )
            finally:
                conn.close()

    def test_rejects_noncontiguous_trait_indices(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _fixture(root)
            traits = list(_rows(root / "mass_entity_traits.jsonl"))
            traits[1]["trait_index"] = 3
            _write(root / "mass_entity_traits.jsonl", traits)
            self.assertIn("not contiguous", mz.validation_error(root, _rows) or "")

    def test_rejects_declared_zone_point_count_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _fixture(root)
            shapes = list(_rows(root / "zonegraph_shapes.jsonl"))
            shapes[0]["point_count"] = 3
            _write(root / "zonegraph_shapes.jsonl", shapes)
            self.assertIn("point_count mismatch", mz.validation_error(root, _rows) or "")

    def test_rejects_unresolved_generator_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _fixture(root)
            generators = list(_rows(root / "mass_spawner_generators.jsonl"))
            generators[0]["generator_asset_path"] = "/Game/AI/Missing.Missing"
            _write(root / "mass_spawner_generators.jsonl", generators)
            self.assertIn("does not resolve", mz.validation_error(root, _rows) or "")

    def test_install_promotes_schema_and_appends_files(self):
        fake = types.SimpleNamespace(
            SYSTEMS_SCHEMA_VERSION=4,
            JSONL_FILES=("existing.jsonl",),
            RAW_FILES=("systems_manifest.json", "existing.jsonl"),
            create_schema=lambda conn: None,
            validation_error=lambda output: None,
            load_database=lambda conn, output, rows=None: None,
            query=lambda conn, print_rows, pattern, limit: None,
            _rows=_rows,
        )
        mz.install(fake)
        self.assertEqual(fake.SYSTEMS_SCHEMA_VERSION, 5)
        self.assertEqual(fake.JSONL_FILES[-len(mz.MASS_ZONEGRAPH_FILES):], mz.MASS_ZONEGRAPH_FILES)
        self.assertEqual(fake.RAW_FILES[0], "systems_manifest.json")
        self.assertTrue(fake._mass_zonegraph_schema_installed)

    def test_native_manifest_and_scanner_are_wired_for_schema5(self):
        driver = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsDriver.inl").read_text(
            encoding="utf-8"
        )
        scanner = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp").read_text(
            encoding="utf-8"
        )
        native = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsMassZoneGraph.inl").read_text(
            encoding="utf-8"
        )
        self.assertIn('SetNumberField(TEXT("schema_version"), 5)', driver)
        for filename in mz.MASS_ZONEGRAPH_FILES:
            self.assertIn(filename, driver)
        self.assertIn('#include "UnrealAssetToolSystemsMassZoneGraph.inl"', scanner)
        self.assertIn("ScanMassZoneGraphProjectModel", native)
        self.assertIn("MassEntityConfig", native)
        self.assertIn("ZoneShapeComponent", native)


if __name__ == "__main__":
    unittest.main()
