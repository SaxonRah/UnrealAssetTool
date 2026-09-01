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

import uatool_mover_graph as mover_graph
import uatool_project_graph as project_graph
import uatool_systems_mover as mover


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class SystemsMoverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.bp = "/Game/BP_Mover.BP_Mover"
        self.component = "/Game/BP_Mover.BP_Mover_C:CharacterMover"
        self.mode = self.component + ".WalkingMode"
        self.mode_bp = "/Game/Modes/BP_Walking.BP_Walking"
        self.setting = self.component + ".CommonLegacyMovementSettings_0"
        self.transition_bp = "/Game/Modes/BP_ToSlide.BP_ToSlide"
        self.transition_class = "/Game/Modes/BP_ToSlide.BP_ToSlide_C"
        self.transition_instance = self.mode + ".BP_ToSlide_C_0"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        write_jsonl(self.output / "mover_blueprints.jsonl", [
            {
                "blueprint_path": self.mode_bp,
                "package_name": "/Game/Modes/BP_Walking",
                "mover_kind": "movement_mode",
                "generated_class": self.mode_bp + "_C",
                "parent_class": "/Script/Mover.SmoothWalkingMode",
                "cdo_path": "/Game/Modes/BP_Walking.Default__BP_Walking_C",
                "cdo_class": self.mode_bp + "_C",
                "shared_setting_class_count": 0,
                "transition_count": 0,
            },
            {
                "blueprint_path": self.transition_bp,
                "package_name": "/Game/Modes/BP_ToSlide",
                "mover_kind": "movement_transition",
                "generated_class": self.transition_class,
                "parent_class": "/Script/Mover.BaseMovementModeTransition",
                "cdo_path": "/Game/Modes/BP_ToSlide.Default__BP_ToSlide_C",
                "cdo_class": self.transition_class,
                "shared_setting_class_count": 0,
                "transition_count": 0,
            },
        ])
        write_jsonl(self.output / "mover_components.jsonl", [{
            "blueprint_path": self.bp,
            "component_path": self.component,
            "component_name": "CharacterMover",
            "component_class": "/Script/Mover.CharacterMoverComponent",
            "component_kind": "character_mover",
            "backend_class": "",
            "starting_movement_mode": "Walking",
            "sync_inputs_for_sim_proxy": "True",
            "mode_count": 1,
            "shared_setting_count": 1,
            "transition_count": 1,
        }])
        write_jsonl(self.output / "mover_modes.jsonl", [{
            "blueprint_path": self.bp,
            "component_path": self.component,
            "mode_index": 0,
            "mode_name": "Walking",
            "mode_path": self.mode,
            "mode_class": self.mode_bp + "_C",
            "mode_asset_path": self.mode_bp,
            "is_starting": True,
        }])
        write_jsonl(self.output / "mover_settings.jsonl", [{
            "asset_path": self.bp,
            "owner_path": self.component,
            "owner_kind": "mover_component",
            "relation": "shared_setting",
            "setting_index": 0,
            "setting_path": self.setting,
            "setting_class": "/Script/Mover.CommonLegacyMovementSettings",
            "setting_asset_path": "",
            "target_kind": "object",
        }])
        write_jsonl(self.output / "mover_transitions.jsonl", [{
            "asset_path": self.bp,
            "owner_path": self.component,
            "owner_kind": "mover_component",
            "transition_index": 0,
            "transition_path": self.transition_instance,
            "transition_class": self.transition_class,
            "transition_asset_path": self.transition_bp,
            "target_kind": "object",
        }])

    def test_mover_validation_and_sqlite(self) -> None:
        self._write_fixture()
        self.assertIsNone(mover.validation_error(self.output, rows))
        conn = sqlite3.connect(":memory:")
        try:
            mover.create_schema(conn)
            mover.load_database(conn, self.output, rows)
            self.assertEqual(conn.execute("SELECT count(*) FROM mover_components").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT mode_name FROM mover_modes").fetchone()[0], "Walking")
            self.assertEqual(conn.execute("SELECT relation FROM mover_settings").fetchone()[0], "shared_setting")
            self.assertEqual(conn.execute("SELECT transition_asset_path FROM mover_transitions").fetchone()[0], self.transition_bp)
        finally:
            conn.close()

    def test_mover_graph_edges_are_exact_semantic(self) -> None:
        self._write_fixture()
        nodes = [
            {
                "node_id": project_graph._node_id("blueprint", self.bp),
                "node_kind": "blueprint",
                "path": self.bp,
                "coverage": "first_class",
                "class_path": "/Script/Engine.Blueprint",
                "package_name": "/Game/BP_Mover",
                "family": "blueprint",
                "root": True,
            },
            {
                "node_id": project_graph._node_id("blueprint", self.mode_bp),
                "node_kind": "blueprint",
                "path": self.mode_bp,
                "coverage": "first_class",
                "class_path": "/Script/Engine.Blueprint",
                "package_name": "/Game/Modes/BP_Walking",
                "family": "blueprint",
                "root": True,
            },
            {
                "node_id": project_graph._node_id("blueprint", self.transition_bp),
                "node_kind": "blueprint",
                "path": self.transition_bp,
                "coverage": "first_class",
                "class_path": "/Script/Engine.Blueprint",
                "package_name": "/Game/Modes/BP_ToSlide",
                "family": "blueprint",
                "root": True,
            },
        ]
        nodes, edges = mover_graph._augment(self.output, rows, nodes, [], project_graph)
        relations = {edge["relation"]: edge for edge in edges}
        self.assertIn("owns_mover_component", relations)
        self.assertIn("has_movement_mode", relations)
        self.assertIn("starts_in_movement_mode", relations)
        self.assertIn("instance_of_movement_mode_blueprint", relations)
        self.assertIn("uses_shared_setting", relations)
        self.assertIn("has_movement_transition", relations)
        self.assertIn("instance_of_movement_transition_blueprint", relations)
        transition_link = relations["instance_of_movement_transition_blueprint"]
        self.assertEqual(transition_link["source"], self.transition_instance)
        self.assertEqual(transition_link["target"], self.transition_bp)
        self.assertTrue(all(edge["edge_quality"] == "exact_semantic" for edge in edges))
        self.assertTrue(any(node["node_kind"] == "mover_component" for node in nodes))
        self.assertTrue(any(node["node_kind"] == "mover_mode" for node in nodes))
        self.assertTrue(any(node["node_kind"] == "mover_transition" for node in nodes))

    def test_mover_validation_rejects_unresolved_starting_mode(self) -> None:
        self._write_fixture()
        path = self.output / "mover_components.jsonl"
        component = next(rows(path))
        component["starting_movement_mode"] = "Flying"
        write_jsonl(path, [component])
        error = mover.validation_error(self.output, rows)
        self.assertIn("starting mode", str(error))


if __name__ == "__main__":
    unittest.main()
