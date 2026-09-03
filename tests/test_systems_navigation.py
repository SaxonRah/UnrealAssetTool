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

import uatool_systems_navigation as navigation
import uatool_navigation_graph as graph


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


class SystemsNavigationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.system = navigation.NAV_SYSTEM_CLASS
        self.agent = graph.agent_path(self.system, 0, "Default")
        self._write_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        nav = "/Script/NavigationSystem."
        areas = [
            {"class_path": nav + "NavArea", "parent_class": "/Script/CoreUObject.Object", "area_kind": "base", "default_cost": "1.000000", "fixed_area_entering_cost": "0.000000", "supported_agents": [0]},
            {"class_path": nav + "NavAreaMeta", "parent_class": nav + "NavArea", "area_kind": "meta", "default_cost": "1.000000", "fixed_area_entering_cost": "0.000000", "supported_agents": [0]},
            {"class_path": nav + "NavAreaMeta_SwitchByAgent", "parent_class": nav + "NavAreaMeta", "area_kind": "meta_switch_by_agent", "default_cost": "1.000000", "fixed_area_entering_cost": "0.000000", "supported_agents": [0]},
            {"class_path": nav + "NavArea_Default", "parent_class": nav + "NavArea", "area_kind": "default", "default_cost": "1.000000", "fixed_area_entering_cost": "0.000000", "supported_agents": [0]},
            {"class_path": nav + "NavArea_LowHeight", "parent_class": nav + "NavArea", "area_kind": "low_height", "default_cost": "339999995214436424907732413799364296704.000000", "fixed_area_entering_cost": "0.000000", "supported_agents": [0]},
            {"class_path": nav + "NavArea_Null", "parent_class": nav + "NavArea", "area_kind": "null", "default_cost": "340282346638528859811704183484516925440.000000", "fixed_area_entering_cost": "0.000000", "supported_agents": [0]},
            {"class_path": nav + "NavArea_Obstacle", "parent_class": nav + "NavArea", "area_kind": "obstacle", "default_cost": "1000000.000000", "fixed_area_entering_cost": "0.000000", "supported_agents": [0]},
        ]
        mappings = [{"source_area": nav + "NavAreaMeta_SwitchByAgent", "agent_index": 0, "target_area": nav + "NavArea_Default"}]
        systems = [
            {"class_path": self.system, "system_kind": "navigation_system", "default_agent_name": "None", "supported_agents": [0], "generate_navigation_only_around_invokers": False, "skip_agent_height_check_when_picking_nav_data": False, "crowd_manager_class": "/Script/AIModule.CrowdManager", "agent_count": 1},
            {"class_path": navigation.NAV_SYSTEM_CONFIG_CLASS, "system_kind": "navigation_system_config", "default_agent_name": "None", "supported_agents": [0], "generate_navigation_only_around_invokers": False, "skip_agent_height_check_when_picking_nav_data": False, "crowd_manager_class": "", "agent_count": 0},
        ]
        agents = [{
            "system_class": self.system, "agent_index": 0, "name": "Default",
            "nav_data_class": navigation.RECAST_CLASS, "preferred_nav_data": navigation.RECAST_CLASS,
            "agent_radius": "50.000000", "agent_height": "144.000000", "agent_step_height": "-1.000000",
            "default_query_extent": "(X=50.000000,Y=50.000000,Z=250.000000)",
            "nav_walking_search_height_scale": "0.500000", "can_crouch": False, "can_jump": False,
            "can_walk": True, "can_swim": False, "can_fly": False,
        }]
        links = [
            {"link_id": "/Script/AIModule.NavLinkProxy#SimpleLinkDefault:0", "class_path": "/Script/AIModule.NavLinkProxy", "link_kind": "simple", "link_index": 0, "direction": "BothWays", "area_class": nav + "NavArea_Default", "enabled_area_class": "", "disabled_area_class": "", "obstacle_area_class": "", "supported_agents": [0], "left": "(X=0,Y=-50,Z=0)", "right": "(X=0,Y=50,Z=0)", "left_project_height": "0.000000", "max_fall_down_length": "1000.000000", "snap_radius": "30.000000", "snap_height": "50.000000", "use_snap_height": False, "snap_to_cheapest_area": True, "smart_link_relevant": False},
            {"link_id": nav + "NavLinkCustomComponent#SmartLinkDefault", "class_path": nav + "NavLinkCustomComponent", "link_kind": "smart", "link_index": -1, "direction": "BothWays", "area_class": "", "enabled_area_class": nav + "NavArea_Default", "disabled_area_class": nav + "NavArea_Null", "obstacle_area_class": nav + "NavArea_Null", "supported_agents": [0], "left": "", "right": "", "left_project_height": "", "max_fall_down_length": "", "snap_radius": "", "snap_height": "", "use_snap_height": False, "snap_to_cheapest_area": False, "smart_link_relevant": False},
        ]
        modifiers = [
            {"modifier_id": nav + "NavModifierComponent#ModifierDefault", "class_path": nav + "NavModifierComponent", "modifier_kind": "component", "area_class": nav + "NavArea_Null", "area_class_to_replace": "", "include_agent_height": True},
            {"modifier_id": nav + "NavModifierVolume#ModifierDefault", "class_path": nav + "NavModifierVolume", "modifier_kind": "volume", "area_class": nav + "NavArea_Null", "area_class_to_replace": "", "include_agent_height": False},
        ]
        invokers = [{"invoker_id": nav + "NavigationInvokerComponent#InvokerDefault", "class_path": nav + "NavigationInvokerComponent", "tile_generation_radius": "3000.000000", "tile_removal_radius": "5000.000000", "invoker_priority": "", "supported_agents": [0]}]
        bounds = [{"bounds_id": nav + "NavMeshBoundsVolume#BoundsDefault", "class_path": nav + "NavMeshBoundsVolume", "supported_agents": [0]}]
        recast = [{"recast_id": nav + "RecastNavMesh#RecastDefaults", "class_path": navigation.RECAST_CLASS, "runtime_generation": "Static", "cell_size": "", "cell_height": "", "tile_size_uu": "", "agent_radius": "50.000000", "agent_height": "144.000000", "agent_max_step_height": "-1.000000", "nav_data_config": "", "jump_down_area_class": nav + "NavArea_Default", "jump_up_area_class": nav + "NavArea_Default"}]

        rows = {
            "navigation_areas.jsonl": areas,
            "navigation_area_agent_mappings.jsonl": mappings,
            "navigation_systems.jsonl": systems,
            "navigation_agents.jsonl": agents,
            "navigation_link_defaults.jsonl": links,
            "navigation_modifier_defaults.jsonl": modifiers,
            "navigation_invoker_defaults.jsonl": invokers,
            "navigation_bounds_defaults.jsonl": bounds,
            "navigation_recast_defaults.jsonl": recast,
        }
        for filename, values in rows.items():
            write_jsonl(self.output / filename, values)
        counts = {filename.removesuffix(".jsonl"): len(values) for filename, values in rows.items()}
        counts.update({"navigation_truncated_values": 0, "navigation_missing_expected_classes": 0})
        (self.output / "systems_manifest.json").write_text(json.dumps({
            "schema_version": 11,
            "success": True,
            "counts": counts,
            "files": list(rows),
        }), encoding="utf-8")

    def test_schema11_validation_and_exact_relations(self) -> None:
        self.assertIsNone(navigation.validation_error(self.output))
        edges = graph.expected_edge_keys(self.output, navigation._rows)
        self.assertIn((navigation.NAV_SYSTEM_CLASS, "navigation_system_supports_agent", self.agent), edges)
        self.assertIn((self.agent, "navigation_agent_uses_nav_data", navigation.RECAST_CLASS), edges)
        self.assertIn(("/Script/NavigationSystem.NavArea_Obstacle", "navigation_area_supports_agent", self.agent), edges)
        self.assertIn(("/Script/AIModule.NavLinkProxy#SimpleLinkDefault:0", "navigation_link_uses_area", "/Script/NavigationSystem.NavArea_Default"), edges)
        self.assertIn(("/Script/NavigationSystem.NavModifierComponent#ModifierDefault", "navigation_modifier_uses_area", "/Script/NavigationSystem.NavArea_Null"), edges)
        self.assertIn(("/Script/NavigationSystem.NavigationInvokerComponent#InvokerDefault", "navigation_invoker_supports_agent", self.agent), edges)

    def test_supported_agent_masks_are_normalized_arrays(self) -> None:
        bad = json.loads((self.output / "navigation_areas.jsonl").read_text(encoding="utf-8").splitlines()[0])
        bad["supported_agents"] = [1, 0]
        lines = (self.output / "navigation_areas.jsonl").read_text(encoding="utf-8").splitlines()
        lines[0] = json.dumps(bad, separators=(",", ":"))
        (self.output / "navigation_areas.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assertIn("not sorted", navigation.validation_error(self.output))

    def test_native_extractor_preserves_split_ownership_boundary(self) -> None:
        native = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsNavigation.inl").read_text(encoding="utf-8")
        policy = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsNavigationPolicy.inl").read_text(encoding="utf-8")
        scanner = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp").read_text(encoding="utf-8")
        self.assertIn("GetDerivedClasses(NavAreaBase, Derived, true)", native)
        self.assertIn("FCString::Strcmp", native)
        self.assertIn('TEXT("SupportedAgentsMask")', native)
        self.assertIn('TEXT("PointLinks")', native)
        self.assertIn('TEXT("TileGenerationRadius")', native)
        self.assertNotIn("GetNavMeshTiles", native)
        self.assertNotIn("FindPath", native)
        self.assertIn('Root->SetNumberField(TEXT("schema_version"), 11)', policy)
        self.assertIn("FNavigationSystemsFileHelperProxy", scanner)
        self.assertIn("UnrealAssetToolSystemsNavigation.inl", scanner)

    def test_canonical_facade_composes_schema11_and_derived27(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_systems_navigation as _systems_navigation", facade)
        self.assertIn("import uatool_navigation_graph as _navigation_graph", facade)
        self.assertIn("import uatool_systems_schema11_accept as _systems_schema11_accept", facade)
        self.assertIn("_systems_navigation.install(_systems)", facade)
        self.assertIn("_navigation_graph.install(_project_graph)", facade)
        self.assertIn('if schema >= 11:', facade)
        self.assertIn('name.startswith("navigation_")', facade)


if __name__ == "__main__":
    unittest.main()
