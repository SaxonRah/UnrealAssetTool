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

import uatool_project_graph as project_graph
import uatool_project_graph_finalize as project_graph_finalize
import uatool_systems as systems


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class SystemsGraphSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_systems_fixture(self) -> None:
        action = "/Game/Input/IA_Jump.IA_Jump"
        context = "/Game/Input/IMC_Default.IMC_Default"
        sound_class = "/Game/Audio/SC_Master.SC_Master"
        rows_by_file: dict[str, list[dict]] = {name: [] for name in systems.JSONL_FILES}
        rows_by_file["systems_assets.jsonl"] = [
            {
                "systems_path": action,
                "systems_kind": "input_action",
                "family": "input",
                "class_path": "/Script/EnhancedInput.InputAction",
                "package_name": "/Game/Input/IA_Jump",
            },
            {
                "systems_path": context,
                "systems_kind": "input_mapping_context",
                "family": "input",
                "class_path": "/Script/EnhancedInput.InputMappingContext",
                "package_name": "/Game/Input/IMC_Default",
            },
            {
                "systems_path": sound_class,
                "systems_kind": "sound_class",
                "family": "audio",
                "class_path": "/Script/Engine.SoundClass",
                "package_name": "/Game/Audio/SC_Master",
            },
        ]
        rows_by_file["input_actions.jsonl"] = [{
            "action_path": action,
            "package_name": "/Game/Input/IA_Jump",
            "class_path": "/Script/EnhancedInput.InputAction",
            "value_type": "Boolean",
            "consume_input": "True",
            "trigger_when_paused": "False",
            "reserve_all_mappings": "False",
            "consume_legacy_keys": "",
            "trigger_count": 0,
            "modifier_count": 0,
        }]
        rows_by_file["input_mapping_contexts.jsonl"] = [{
            "context_path": context,
            "package_name": "/Game/Input/IMC_Default",
            "class_path": "/Script/EnhancedInput.InputMappingContext",
            "mapping_count": 1,
            "description": "Default",
        }]
        rows_by_file["input_mappings.jsonl"] = [{
            "context_path": context,
            "mapping_index": 0,
            "struct_type": "/Script/EnhancedInput.EnhancedActionKeyMapping",
            "action_path": action,
            "action_class": "/Script/EnhancedInput.InputAction",
            "key": "SpaceBar",
            "trigger_count": 0,
            "modifier_count": 0,
            "player_mappable_options": "",
            "setting_behavior": "",
            "raw_value": "",
            "truncated": False,
        }]
        # Systems schema 2 always emits one project Gameplay Tags settings row,
        # even when the test project has no explicit dictionary sources/tags.
        rows_by_file["gameplay_tag_settings.jsonl"] = [{
            "settings_path": "/Script/GameplayTags.Default__GameplayTagsSettings",
            "class_path": "/Script/GameplayTags.GameplayTagsSettings",
            "config_file_name": "",
            "import_tags_from_config": "False",
            "warn_on_invalid_tags": "True",
            "fast_replication": "False",
            "invalid_tag_characters": "",
            "gameplay_tag_table_list": "",
            "restricted_config_files": "",
            "num_bits_for_container_size": 6,
            "net_index_first_bit_segment": 16,
        }]

        # Schema 11 always publishes the normalized native Navigation/default
        # surface even for a project whose authored gameplay fixture has no
        # placed Navigation actors. Keep this generic smoke fixture intentionally
        # minimal while satisfying the schema-level identity invariants; the
        # representative acceptance gate separately requires the full UE 5.8.2
        # seven-area/link/modifier/invoker corpus.
        if "navigation_areas.jsonl" in rows_by_file:
            nav = "/Script/NavigationSystem."
            rows_by_file["navigation_areas.jsonl"] = [{
                "class_path": nav + "NavArea",
                "parent_class": "/Script/CoreUObject.Object",
                "area_kind": "base",
                "default_cost": "1.000000",
                "fixed_area_entering_cost": "0.000000",
                "supported_agents": [],
            }]
            rows_by_file["navigation_systems.jsonl"] = [
                {
                    "class_path": nav + "NavigationSystemV1",
                    "system_kind": "navigation_system",
                    "default_agent_name": "None",
                    "supported_agents": [],
                    "generate_navigation_only_around_invokers": False,
                    "skip_agent_height_check_when_picking_nav_data": False,
                    "crowd_manager_class": "",
                    "agent_count": 0,
                },
                {
                    "class_path": "/Script/Engine.NavigationSystemConfig",
                    "system_kind": "navigation_system_config",
                    "default_agent_name": "None",
                    "supported_agents": [],
                    "generate_navigation_only_around_invokers": False,
                    "skip_agent_height_check_when_picking_nav_data": False,
                    "crowd_manager_class": "",
                    "agent_count": 0,
                },
            ]
            rows_by_file["navigation_recast_defaults.jsonl"] = [{
                "recast_id": nav + "RecastNavMesh#RecastDefaults",
                "class_path": nav + "RecastNavMesh",
                "runtime_generation": "Static",
                "cell_size": "",
                "cell_height": "",
                "tile_size_uu": "",
                "agent_radius": "",
                "agent_height": "",
                "agent_max_step_height": "",
                "nav_data_config": "",
                "jump_down_area_class": "",
                "jump_up_area_class": "",
            }]

        for filename, rows in rows_by_file.items():
            write_jsonl(self.output / filename, rows)
        counts = {
            name.removesuffix(".jsonl"): len(rows_by_file[name])
            for name in systems.JSONL_FILES
        }
        # Schema 9 publishes one semantic asset count in addition to the
        # physical dataflow_graphs stream count, plus non-file loss counters.
        counts["dataflow_assets"] = len(rows_by_file["dataflow_graphs.jsonl"])
        counts["dataflow_chaos_truncated_properties"] = 0
        counts["dataflow_chaos_property_row_limit_hits"] = 0
        # Schema 10 adds one UAF non-file loss counter alongside the physical
        # uaf_* stream counts above.
        counts["uaf_truncated_values"] = 0
        # Schema 11 likewise has explicit native loss/identity counters that do
        # not correspond to physical JSONL streams.
        if systems.SYSTEMS_SCHEMA_VERSION >= 11:
            counts["navigation_truncated_values"] = 0
            counts["navigation_missing_expected_classes"] = 0
        (self.output / "systems_manifest.json").write_text(json.dumps({
            "schema_version": systems.SYSTEMS_SCHEMA_VERSION,
            "pass": "UnrealAssetToolSystems",
            "success": True,
            "error": "",
            "files": list(systems.JSONL_FILES),
            "counts": counts,
        }, indent=2) + "\n", encoding="utf-8")

    def _write_project_inputs(self) -> None:
        action = "/Game/Input/IA_Jump.IA_Jump"
        context = "/Game/Input/IMC_Default.IMC_Default"
        sound_class = "/Game/Audio/SC_Master.SC_Master"
        write_jsonl(self.output / "assets.jsonl", [
            {"object_path": action, "class_path": "/Script/EnhancedInput.InputAction", "package_name": "/Game/Input/IA_Jump"},
            {"object_path": context, "class_path": "/Script/EnhancedInput.InputMappingContext", "package_name": "/Game/Input/IMC_Default"},
            {"object_path": sound_class, "class_path": "/Script/Engine.SoundClass", "package_name": "/Game/Audio/SC_Master"},
        ])
        write_jsonl(self.output / "asset_dependencies.jsonl", [{
            "source_package": "/Game/Input/IMC_Default",
            "target_package": "/Game/Input/IA_Jump",
            "category": "hard",
        }])
        # Every other upstream stream may be absent; the graph reader treats that
        # as a legitimate empty specialist family.

    def test_systems_manifest_validation_and_sqlite_load(self) -> None:
        self._write_systems_fixture()
        self.assertIsNone(systems.validation_error(self.output))
        conn = sqlite3.connect(":memory:")
        try:
            systems.create_schema(conn)
            systems.load_database(conn, self.output, read_rows)
            self.assertEqual(conn.execute("SELECT count(*) FROM systems_assets").fetchone()[0], 3)
            self.assertEqual(conn.execute("SELECT count(*) FROM input_mappings").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM gameplay_tag_settings").fetchone()[0], 1)
        finally:
            conn.close()

    def test_systems_kind_coverage_policy_defaults_conservatively(self) -> None:
        self.assertEqual(project_graph.systems_kind_coverage("input_action"), "first_class")
        self.assertEqual(project_graph.systems_kind_coverage("input_mapping_context"), "first_class")
        self.assertEqual(project_graph.systems_kind_coverage("sound_class"), "first_class_depth_pending")
        self.assertEqual(project_graph.systems_kind_coverage("future_system_kind"), "first_class_depth_pending")

    def test_project_graph_quality_and_neighborhoods(self) -> None:
        self._write_systems_fixture()
        self._write_project_inputs()
        nodes, edges, _ = project_graph.derive(self.output, read_rows)
        nodes, edges, neighborhoods = project_graph_finalize.finalize(
            self.output, read_rows, nodes, edges
        )
        write_jsonl(self.output / "project_nodes.jsonl", nodes)
        write_jsonl(self.output / "project_edges.jsonl", edges)
        write_jsonl(self.output / "project_neighborhoods.jsonl", neighborhoods)
        self.assertIsNone(project_graph.validation_error(self.output, read_rows))
        self.assertIsNone(project_graph_finalize.validation_error(self.output, read_rows))

        root_nodes = {node["path"]: node for node in nodes if node.get("root")}
        self.assertEqual(len(root_nodes), len([node for node in nodes if node.get("root")]))
        self.assertFalse(any(not node["path"].strip() for node in nodes))
        self.assertEqual(root_nodes["/Game/Input/IA_Jump.IA_Jump"]["coverage"], "first_class")
        self.assertEqual(root_nodes["/Game/Input/IMC_Default.IMC_Default"]["coverage"], "first_class")
        self.assertEqual(root_nodes["/Game/Audio/SC_Master.SC_Master"]["coverage"], "first_class_depth_pending")

        generic = [edge for edge in edges if edge["relation"] == "depends_on_package"]
        self.assertEqual(len(generic), 1)
        self.assertEqual(generic[0]["edge_quality"], "generic_package_dependency")
        semantic = [edge for edge in edges if edge["relation"] == "maps_input_action"]
        self.assertEqual(len(semantic), 1)
        self.assertEqual(semantic[0]["edge_quality"], "exact_reference")
        self.assertTrue(neighborhoods)
        for neighborhood in neighborhoods:
            self.assertLessEqual(neighborhood["edge_count"], project_graph.MAX_NEIGHBOR_EDGES)
            for hop in neighborhood["hops"]:
                self.assertIn(hop["edge_quality"], project_graph.QUALITY_RANK)
                self.assertTrue(hop["source_coverage"])
