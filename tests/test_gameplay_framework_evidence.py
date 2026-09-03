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

import uatool_gameplay_framework_evidence as evidence


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


class GameplayFrameworkEvidenceTest(unittest.TestCase):
    def test_transitive_blueprint_inheritance_and_authored_defaults_are_proven(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base_gm = "/Game/Framework/BP_BaseGM.BP_BaseGM"
            base_gm_class = "/Game/Framework/BP_BaseGM.BP_BaseGM_C"
            child_gm = "/Game/Framework/BP_ChildGM.BP_ChildGM"
            child_gm_class = "/Game/Framework/BP_ChildGM.BP_ChildGM_C"
            pawn = "/Game/Framework/BP_PlayerPawn.BP_PlayerPawn"
            pawn_class = "/Game/Framework/BP_PlayerPawn.BP_PlayerPawn_C"
            pc = "/Game/Framework/BP_PC.BP_PC"
            pc_class = "/Game/Framework/BP_PC.BP_PC_C"

            write_jsonl(root / "blueprints.jsonl", [
                {
                    "object_path": base_gm,
                    "name": "BP_BaseGM",
                    "parent_class": "/Script/Engine.GameModeBase",
                    "generated_class": base_gm_class,
                },
                {
                    "object_path": child_gm,
                    "name": "BP_ChildGM",
                    "parent_class": base_gm_class,
                    "generated_class": child_gm_class,
                },
                {
                    "object_path": pawn,
                    "name": "BP_PlayerPawn",
                    "parent_class": "/Script/Engine.Pawn",
                    "generated_class": pawn_class,
                },
                {
                    "object_path": pc,
                    "name": "BP_PC",
                    "parent_class": "/Script/Engine.PlayerController",
                    "generated_class": pc_class,
                },
                {
                    "object_path": "/Game/Fakes/BP_GameModeFake.BP_GameModeFake",
                    "name": "BP_GameModeFake",
                    "parent_class": "/Script/Engine.Actor",
                    "generated_class": "/Game/Fakes/BP_GameModeFake.BP_GameModeFake_C",
                },
            ])
            write_jsonl(root / "blueprint_state_values.jsonl", [
                {
                    "blueprint_path": base_gm,
                    "owner_path": base_gm_class,
                    "property_path": "DefaultPawnClass",
                    "value": pawn_class,
                },
                {
                    "blueprint_path": base_gm,
                    "owner_path": base_gm_class,
                    "property_path": "PlayerControllerClass",
                    "value": pc_class,
                },
            ])
            write_jsonl(root / "worlds.jsonl", [{"world_path": "/Game/Maps/Test.Test"}])
            write_jsonl(root / "world_instance_properties.jsonl", [{
                "world_path": "/Game/Maps/Test.Test",
                "actor_path": "/Game/Maps/Test.Test:PersistentLevel.WorldSettings",
                "actor_class": "/Script/Engine.WorldSettings",
                "property_path": "DefaultGameMode",
                "value": child_gm_class,
            }])
            write_jsonl(root / "source_chunks.jsonl", [{
                "path": "Config/DefaultEngine.ini",
                "text": (
                    "[/Script/EngineSettings.GameMapsSettings]\n"
                    f"GlobalDefaultGameMode={base_gm_class}\n"
                    "GameDefaultMap=/Game/Maps/Test\n"
                ),
            }])
            write_jsonl(root / "blueprint_node_references.jsonl", [{
                "blueprint_path": "/Game/Framework/BP_Helper.BP_Helper",
                "target": pawn_class,
                "target_class": pawn_class,
            }])
            write_jsonl(root / "blueprint_semantic_statements.jsonl", [{
                "blueprint_path": base_gm,
                "operation": "RestartPlayer",
            }])

            report = evidence.build_report(root, rows, include_source=True)
            proof = report["proof"]
            self.assertEqual(proof["game_mode_blueprints"], 2)
            self.assertEqual(proof["transitive_framework_blueprints"], 1)
            self.assertEqual(proof["pawn_blueprints"], 1)
            self.assertEqual(proof["player_controller_blueprints"], 1)
            self.assertEqual(proof["game_mode_selector_rows"], 2)
            self.assertGreaterEqual(proof["project_game_mode_rows"], 1)
            self.assertGreaterEqual(proof["project_map_rows"], 1)
            self.assertEqual(proof["world_game_mode_override_rows"], 1)
            self.assertEqual(proof["exact_framework_reference_rows"], 1)
            self.assertEqual(proof["framework_usage_rows"], 1)
            self.assertFalse(any("BP_GameModeFake" in item["blueprint"] for item in report["inheritance"]))

            child = next(item for item in report["inheritance"] if item["blueprint"] == child_gm)
            self.assertTrue(child["parent_is_framework_blueprint"])
            self.assertEqual(child["kind"], "game_mode")

            rendered = evidence.render_report(report, row_limit=10)
            self.assertIn("diagnostic_only=True", rendered)
            self.assertIn("runtime_state_captured=False", rendered)
            self.assertIn("BP_ChildGM", rendered)
            self.assertIn("DefaultPawnClass", rendered)
            self.assertIn("WorldSettings GameMode override evidence", rendered)

    def test_no_class_or_name_guessing_without_exact_inheritance(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_jsonl(root / "blueprints.jsonl", [{
                "object_path": "/Game/GameModeAndPawnByNameOnly.GameModeAndPawnByNameOnly",
                "name": "GameModeAndPawnByNameOnly",
                "parent_class": "/Script/Engine.Actor",
                "generated_class": "/Game/GameModeAndPawnByNameOnly.GameModeAndPawnByNameOnly_C",
            }])
            report = evidence.build_report(root, rows, include_source=False)
            self.assertEqual(report["proof"]["framework_blueprints"], 0)
            self.assertEqual(report["proof"]["game_mode_blueprints"], 0)
            self.assertEqual(report["proof"]["pawn_blueprints"], 0)

    def test_canonical_facade_wires_one_public_command(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_gameplay_framework_evidence as _gameplay_framework_evidence", facade)
        self.assertIn("_gameplay_framework_evidence.install(_runtime)", facade)
        source = (SCRIPTS / "uatool_gameplay_framework_evidence.py").read_text(encoding="utf-8")
        self.assertIn('sys.argv[1] == "gameplay-framework-evidence"', source)
        self.assertNotIn("semantic_promotion=True", source)
        self.assertNotIn("schema_promotion=True", source)


if __name__ == "__main__":
    unittest.main()
