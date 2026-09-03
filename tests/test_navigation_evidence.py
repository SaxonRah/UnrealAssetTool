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

import uatool_navigation_evidence as navigation


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def rows(path: Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            yield json.loads(line)


class NavigationEvidenceTest(unittest.TestCase):
    def test_authored_navigation_inventory_stays_diagnostic_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_jsonl(root / "world_actors.jsonl", [
                {
                    "world_path": "/Game/Maps/Nav.Nav",
                    "actor_path": "/Game/Maps/Nav.Nav:PersistentLevel.NavMeshBoundsVolume_0",
                    "actor_class": "/Script/NavigationSystem.NavMeshBoundsVolume",
                },
                {
                    "world_path": "/Game/Maps/Nav.Nav",
                    "actor_path": "/Game/Maps/Nav.Nav:PersistentLevel.NavModifierVolume_0",
                    "actor_class": "/Script/NavigationSystem.NavModifierVolume",
                },
                {
                    "world_path": "/Game/Maps/Nav.Nav",
                    "actor_path": "/Game/Maps/Nav.Nav:PersistentLevel.NavLinkProxy_0",
                    "actor_class": "/Script/AIModule.NavLinkProxy",
                },
                {
                    "world_path": "/Game/Maps/Nav.Nav",
                    "actor_path": "/Game/Maps/Nav.Nav:PersistentLevel.RecastNavMesh_Default",
                    "actor_class": "/Script/NavigationSystem.RecastNavMesh",
                },
            ])
            write_jsonl(root / "world_components.jsonl", [
                {
                    "component_path": "/Game/Maps/Nav.Nav:PersistentLevel.Pawn_0.NavigationInvokerComponent",
                    "component_class": "/Script/NavigationSystem.NavigationInvokerComponent",
                },
            ])
            write_jsonl(root / "blueprints.jsonl", [
                {
                    "blueprint_path": "/Game/AI/BP_NavAreaMud.BP_NavAreaMud",
                    "parent_class": "/Script/NavigationSystem.NavArea",
                },
            ])
            write_jsonl(root / "world_instance_properties.jsonl", [
                {
                    "owner_path": "/Game/Maps/Nav.Nav:PersistentLevel.NavModifierVolume_0",
                    "property_name": "AreaClass",
                    "property_path": "AreaClass",
                    "value": "/Game/AI/BP_NavAreaMud.BP_NavAreaMud_C",
                },
                {
                    "owner_path": "/Game/Maps/Nav.Nav:PersistentLevel.NavLinkProxy_0",
                    "property_name": "PointLinks",
                    "property_path": "PointLinks",
                    "value": "((Left=(X=0),Right=(X=100),Direction=BothWays,AreaClass=/Script/NavigationSystem.NavArea_Default))",
                },
                {
                    "owner_path": "/Game/Maps/Nav.Nav:PersistentLevel.Pawn_0.NavigationInvokerComponent",
                    "property_name": "GenerationRadius",
                    "property_path": "GenerationRadius",
                    "value": "3000.0",
                },
                {
                    "owner_path": "/Game/Maps/Nav.Nav:PersistentLevel.Pawn_0.NavigationInvokerComponent",
                    "property_name": "RemovalRadius",
                    "property_path": "RemovalRadius",
                    "value": "5000.0",
                },
            ])
            write_jsonl(root / "systems_properties.jsonl", [
                {
                    "owner_path": "/Script/NavigationSystem.Default__NavigationSystemV1",
                    "owner_class": "/Script/NavigationSystem.NavigationSystemV1",
                    "property_name": "SupportedAgents",
                    "property_path": "SupportedAgents",
                    "value": "((Name=Default,AgentRadius=42.0,AgentHeight=192.0))",
                },
            ])
            write_jsonl(root / "source_chunks.jsonl", [
                {
                    "path": "Config/DefaultEngine.ini",
                    "text": "[/Script/NavigationSystem.NavigationSystemV1]\nSupportedAgents=(Name=Default,AgentRadius=42.0,AgentHeight=192.0)\nDefaultAgentName=Default",
                },
            ])

            report = navigation.build_report(root, rows)
            proof = report["proof"]

            self.assertTrue(report["diagnostic_only"])
            self.assertFalse(report["semantic_promotion"])
            self.assertFalse(report["schema_promotion"])
            self.assertFalse(report["runtime_state_captured"])
            self.assertFalse(report["generated_navmesh_promoted"])
            self.assertEqual(proof["unique_navmesh_bounds_volumes"], 1)
            self.assertEqual(proof["unique_nav_modifier_volumes"], 1)
            self.assertEqual(proof["unique_nav_link_proxies"], 1)
            self.assertEqual(proof["unique_navigation_invoker_components"], 1)
            self.assertEqual(proof["unique_recast_navmesh_objects"], 1)
            self.assertEqual(proof["unique_nav_area_blueprints"], 1)
            self.assertEqual(proof["modifier_area_owners"], 1)
            self.assertEqual(proof["link_topology_owners"], 1)
            self.assertEqual(proof["invoker_setting_owners"], 1)
            self.assertGreaterEqual(proof["supported_agent_owners"], 1)
            self.assertGreaterEqual(proof["navigation_system_setting_owners"], 1)
            self.assertTrue(any("Generated Recast/NavMesh evidence" in gap for gap in report["gaps"]))
            self.assertFalse(any("Navigation modifiers are proven" in gap for gap in report["gaps"]))
            self.assertFalse(any("NavLinkProxy actors are proven" in gap for gap in report["gaps"]))
            self.assertFalse(any("NavigationInvokerComponent is proven" in gap for gap in report["gaps"]))

            rendered = navigation.render_report(report, row_limit=5)
            self.assertIn("AUTHORED NAVIGATION EVIDENCE REPORT", rendered)
            self.assertIn("generated_navmesh_promoted=False", rendered)
            self.assertIn("FOCUS: links", rendered)

    def test_empty_corpus_requires_representative_navigation_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            report = navigation.build_report(root, rows, include_source=False)
            self.assertTrue(any("No authored Navigation" in gap for gap in report["gaps"]))
            self.assertEqual(sum(report["proof"].values()), 0)

    def test_canonical_facade_installs_navigation_evidence(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_navigation_evidence as _navigation_evidence", facade)
        self.assertIn("_navigation_evidence.install(_runtime)", facade)


if __name__ == "__main__":
    unittest.main()
