import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_gameplay_framework_model as model
import uatool_project_graph as project_graph
import uatool_gameplay_framework_graph as framework_graph


def write_jsonl(root: Path, name: str, rows):
    with (root / name).open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


class GameplayFrameworkDerived28Tests(unittest.TestCase):
    def corpus(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        write_jsonl(root, "assets.jsonl", [])
        write_jsonl(root, "asset_dependencies.jsonl", [])
        write_jsonl(root, "blueprints.jsonl", [
            {
                "object_path": "/Game/BP_BaseGM.BP_BaseGM",
                "parent_class": "/Script/Engine.GameMode",
                "generated_class": "/Game/BP_BaseGM.BP_BaseGM_C",
                "class": "/Script/Engine.Blueprint",
            },
            {
                "object_path": "/Game/BP_ChildGM.BP_ChildGM",
                "parent_class": "/Game/BP_BaseGM.BP_BaseGM_C",
                "generated_class": "/Game/BP_ChildGM.BP_ChildGM_C",
                "class": "/Script/Engine.Blueprint",
            },
            {
                "object_path": "/Game/BP_Player.BP_Player",
                "parent_class": "/Script/Engine.Character",
                "generated_class": "/Game/BP_Player.BP_Player_C",
                "class": "/Script/Engine.Blueprint",
            },
            {
                "object_path": "/Game/BP_AIController.BP_AIController",
                "parent_class": "/Script/AIModule.AIController",
                "generated_class": "/Game/BP_AIController.BP_AIController_C",
                "class": "/Script/Engine.Blueprint",
            },
            {
                "object_path": "/Game/BP_NotFramework.BP_NotFramework",
                "parent_class": "/Script/Engine.Actor",
                "generated_class": "/Game/BP_NotFramework.BP_NotFramework_C",
                "class": "/Script/Engine.Blueprint",
            },
        ])
        write_jsonl(root, "blueprint_state_values.jsonl", [
            {
                "blueprint_path": "/Game/BP_ChildGM.BP_ChildGM",
                "owner_class": "/Game/BP_ChildGM.BP_ChildGM_C",
                "owner_kind": "class_default",
                "property_name": "DefaultPawnClass",
                "property_path": "DefaultPawnClass",
                "depth": 0,
                "referenced_object_path": "/Game/BP_Player.BP_Player_C",
                "baseline_class": "/Game/BP_BaseGM.BP_BaseGM_C",
                "baseline_object_path": "/Script/Engine.DefaultPawn",
            },
            {
                "blueprint_path": "/Game/BP_Player.BP_Player",
                "owner_class": "/Game/BP_Player.BP_Player_C",
                "owner_kind": "class_default",
                "property_name": "AIControllerClass",
                "property_path": "AIControllerClass",
                "depth": 0,
                "referenced_object_path": "/Game/BP_AIController.BP_AIController_C",
            },
        ])
        write_jsonl(root, "worlds.jsonl", [
            {"world_path": "/Game/Maps/Test.Test", "package_name": "/Game/Maps/Test"},
        ])
        write_jsonl(root, "world_actors.jsonl", [])
        write_jsonl(root, "world_components.jsonl", [])
        write_jsonl(root, "world_instance_properties.jsonl", [
            {
                "world_path": "/Game/Maps/Test.Test",
                "actor_path": "/Game/Maps/Test.Test:PersistentLevel.WorldSettings",
                "owner_class": "/Script/Engine.WorldSettings",
                "property_name": "DefaultGameMode",
                "value": "/Script/Engine.BlueprintGeneratedClass'/Game/BP_ChildGM.BP_ChildGM_C'",
            },
        ])
        write_jsonl(root, "world_references.jsonl", [])
        write_jsonl(root, "source_chunks.jsonl", [
            {
                "path": "Config/DefaultEngine.ini",
                "start_line": 1,
                "end_line": 20,
                "text": "[/Script/EngineSettings.GameMapsSettings]\n"
                        "GameInstanceClass=/Script/Engine.GameInstance\n"
                        "GameDefaultMap=/Game/Maps/Test.Test\n"
                        "GlobalDefaultGameMode=/Game/BP_ChildGM.BP_ChildGM_C\n"
                        "TransitionMap=None\n",
            },
        ])
        # Base project-graph optional streams.
        for name in (
            "animation_assets.jsonl", "vfx_assets.jsonl", "systems_assets.jsonl",
            "behavior_trees.jsonl", "blackboards.jsonl", "eqs_queries.jsonl", "statetrees.jsonl",
            "pcg_graphs.jsonl", "materials.jsonl", "animation_relations.jsonl", "vfx_relations.jsonl",
            "world_relations.jsonl", "world_system_relations.jsonl", "blueprint_relations.jsonl",
            "ai_relations.jsonl", "visual_relations.jsonl", "movie_scene_tracks.jsonl",
            "movie_scene_sections.jsonl", "movie_scene_channels.jsonl", "movie_scene_bindings.jsonl",
            "sound_cue_nodes.jsonl", "metasound_nodes.jsonl", "metasound_edges.jsonl",
            "input_mappings.jsonl", "input_processors.jsonl", "gameplay_tags.jsonl",
            "systems_references.jsonl",
        ):
            write_jsonl(root, name, [])
        return temp, root

    def test_model_uses_exact_transitive_inheritance_and_authored_overrides(self):
        temp, root = self.corpus()
        self.addCleanup(temp.cleanup)
        data = model.build_model(root, rows)
        records = {row["blueprint_path"]: row for row in data["framework_blueprints"]}
        self.assertEqual(records["/Game/BP_ChildGM.BP_ChildGM"]["framework_kind"], "game_mode")
        self.assertTrue(records["/Game/BP_ChildGM.BP_ChildGM"]["transitive"])
        self.assertNotIn("/Game/BP_NotFramework.BP_NotFramework", records)

        edges = {(e["source"], e["relation"], e["target"]) for e in data["edge_specs"]}
        self.assertIn((
            "/Game/BP_ChildGM.BP_ChildGM_C",
            "inherits_gameplay_framework_class",
            "/Game/BP_BaseGM.BP_BaseGM_C",
        ), edges)
        self.assertIn((
            "/Game/BP_ChildGM.BP_ChildGM_C",
            "game_mode_overrides_default_pawn_class",
            "/Game/BP_Player.BP_Player_C",
        ), edges)
        self.assertIn((
            "/Game/BP_Player.BP_Player_C",
            "pawn_uses_ai_controller_class",
            "/Game/BP_AIController.BP_AIController_C",
        ), edges)
        self.assertIn((
            "/Game/Maps/Test.Test",
            "world_overrides_default_game_mode_class",
            "/Game/BP_ChildGM.BP_ChildGM_C",
        ), edges)
        self.assertIn((
            model.GAME_MAPS_SETTINGS_NODE,
            "project_sets_game_default_map",
            "/Game/Maps/Test.Test",
        ), edges)
        self.assertFalse(any(target == "None" for _, _, target in edges))

    def test_graph_promotion_is_schema_28_and_exact_semantic(self):
        temp, root = self.corpus()
        self.addCleanup(temp.cleanup)
        # Install once on the module used by this test process.
        framework_graph.install(project_graph)
        nodes, edges, _ = project_graph.derive(root, rows)
        self.assertGreaterEqual(project_graph.DERIVED_SCHEMA_VERSION, 28)
        domain = [edge for edge in edges if edge.get("relation") in model.RELATIONS]
        self.assertTrue(domain)
        self.assertTrue(all(edge.get("edge_quality") == "exact_semantic" for edge in domain))
        self.assertTrue(any(
            edge.get("relation") == "game_mode_overrides_default_pawn_class"
            and edge.get("source_kind") == "game_mode_class"
            and edge.get("target_kind") == "character_class"
            for edge in domain
        ))

    def test_gamemaps_parser_is_section_scoped(self):
        temp, root = self.corpus()
        self.addCleanup(temp.cleanup)
        # Add a misleading key outside the GameMapsSettings section; it must not win.
        write_jsonl(root, "source_chunks.jsonl", [
            {
                "path": "Config/DefaultEngine.ini",
                "start_line": 1,
                "end_line": 30,
                "text": "[Other]\nGlobalDefaultGameMode=/Game/Wrong.Wrong_C\n"
                        "[/Script/EngineSettings.GameMapsSettings]\n"
                        "GlobalDefaultGameMode=/Script/Engine.GameModeBase\n"
                        "GameInstanceClass=/Script/Engine.GameInstance\n",
            },
        ])
        settings = model.game_maps_settings(root, rows)
        self.assertEqual(settings["GlobalDefaultGameMode"]["value"], "/Script/Engine.GameModeBase")
        self.assertEqual(settings["GameInstanceClass"]["value"], "/Script/Engine.GameInstance")


if __name__ == "__main__":
    unittest.main()
