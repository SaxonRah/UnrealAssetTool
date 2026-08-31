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
        for filename, rows in rows_by_file.items():
            write_jsonl(self.output / filename, rows)
        counts = {
            name.removesuffix(".jsonl"): len(rows_by_file[name])
            for name in systems.JSONL_FILES
        }
        (self.output / "systems_manifest.json").write_text(json.dumps({
            "schema_version": 1,
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
                self.assertTrue(hop["target_coverage"])

        conn = sqlite3.connect(":memory:")
        try:
            project_graph.create_schema(conn)
            project_graph.load_database(conn, self.output, read_rows)
            self.assertEqual(conn.execute("SELECT count(*) FROM project_edges").fetchone()[0], len(edges))
            self.assertEqual(conn.execute("SELECT count(*) FROM project_neighborhoods").fetchone()[0], len(neighborhoods))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
