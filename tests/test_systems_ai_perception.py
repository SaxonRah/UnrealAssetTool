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

import uatool_ai_perception_graph as graph
import uatool_systems_ai_perception as schema8


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class AIPerceptionSchema8Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.bp = "/Game/AI/BP_AIController.BP_AIController"
        self.generated = self.bp + "_C"
        self.component = self.generated + ":AIPerception_GEN_VARIABLE"
        self.hearing = self.component + ".AISenseConfig_Hearing_0"
        self.sight = self.component + ".AISenseConfig_Sight_1"
        self.player = "/Game/Player/PlayerCharacter.PlayerCharacter"
        self.player_generated = self.player + "_C"
        self.source = self.player_generated + ":AIPerceptionStimuliSource_GEN_VARIABLE"
        self.sight_class = "/Script/AIModule.AISense_Sight"
        self.hearing_class = "/Script/AIModule.AISense_Hearing"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _property(self, blueprint: str, owner: str, kind: str, index: int, name: str, value: str) -> dict:
        return {
            "blueprint_path": blueprint,
            "owner_path": owner,
            "owner_kind": kind,
            "property_index": index,
            "declaring_type": "/Script/AIModule.Test",
            "property_name": name,
            "property_path": name,
            "property_type": "TestProperty",
            "cpp_type": "test",
            "value": value,
            "class_default_value": "",
            "class_default_present": True,
            "differs_from_class_default": True,
            "truncated": False,
        }

    def _write_fixture(self) -> None:
        write_jsonl(self.output / "ai_perception_components.jsonl", [{
            "blueprint_path": self.bp,
            "generated_class": self.generated,
            "component_path": self.component,
            "component_name": "AIPerception",
            "component_class": "/Script/AIModule.AIPerceptionComponent",
            "dominant_sense_class": self.sight_class,
            "sense_config_count": 2,
            "property_count": 1,
        }])
        write_jsonl(self.output / "ai_perception_sense_configs.jsonl", [
            {
                "blueprint_path": self.bp,
                "component_path": self.component,
                "config_index": 0,
                "config_path": self.hearing,
                "config_class": "/Script/AIModule.AISenseConfig_Hearing",
                "implementation_class": self.hearing_class,
                "is_null": False,
                "max_age": 1.0,
                "detection_by_affiliation": "(bDetectEnemies=True,bDetectNeutrals=True,bDetectFriendlies=True)",
                "detect_enemies": True,
                "detect_neutrals": True,
                "detect_friendlies": True,
                "hearing_range": 800.0,
                "sight_radius": None,
                "lose_sight_radius": None,
                "peripheral_vision_angle_degrees": None,
                "property_count": 1,
            },
            {
                "blueprint_path": self.bp,
                "component_path": self.component,
                "config_index": 1,
                "config_path": self.sight,
                "config_class": "/Script/AIModule.AISenseConfig_Sight",
                "implementation_class": self.sight_class,
                "is_null": False,
                "max_age": 1.0,
                "detection_by_affiliation": "(bDetectEnemies=True,bDetectNeutrals=True,bDetectFriendlies=True)",
                "detect_enemies": True,
                "detect_neutrals": True,
                "detect_friendlies": True,
                "hearing_range": None,
                "sight_radius": 500.0,
                "lose_sight_radius": 600.0,
                "peripheral_vision_angle_degrees": 45.0,
                "property_count": 1,
            },
        ])
        write_jsonl(self.output / "ai_perception_stimuli_sources.jsonl", [{
            "blueprint_path": self.player,
            "generated_class": self.player_generated,
            "component_path": self.source,
            "component_name": "AIPerceptionStimuliSource",
            "component_class": "/Script/AIModule.AIPerceptionStimuliSourceComponent",
            "auto_register_as_source": True,
            "registered_sense_count": 3,
            "property_count": 1,
        }])
        write_jsonl(self.output / "ai_perception_registered_senses.jsonl", [
            {"blueprint_path": self.player, "component_path": self.source, "sense_index": 0,
             "sense_class": self.sight_class, "is_null": False},
            {"blueprint_path": self.player, "component_path": self.source, "sense_index": 1,
             "sense_class": self.hearing_class, "is_null": False},
            {"blueprint_path": self.player, "component_path": self.source, "sense_index": 2,
             "sense_class": "", "is_null": True},
        ])
        write_jsonl(self.output / "ai_perception_properties.jsonl", [
            self._property(self.bp, self.component, "perception_component_template", 0, "DominantSense", self.sight_class),
            self._property(self.bp, self.hearing, "sense_config", 0, "HearingRange", "800.000000"),
            self._property(self.bp, self.sight, "sense_config", 0, "SightRadius", "500.000000"),
            self._property(self.player, self.source, "stimuli_source_component_template", 0, "bAutoRegisterAsSource", "True"),
        ])

    def test_contentexamples_shape_validates_loads_and_has_exact_nine_edges(self) -> None:
        self._write_fixture()
        self.assertIsNone(schema8.validation_error(self.output, rows))

        conn = sqlite3.connect(":memory:")
        schema8.create_schema(conn)
        schema8.load_database(conn, self.output, rows)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_perception_components").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_perception_sense_configs").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_perception_stimuli_sources").fetchone()[0], 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_perception_registered_senses").fetchone()[0], 3)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM ai_perception_properties").fetchone()[0], 4)

        edges = graph.expected_edge_keys(self.output, rows)
        self.assertEqual(len(edges), 9)
        self.assertIn((self.bp, "has_ai_perception_component", self.component), edges)
        self.assertIn((self.component, "has_ai_perception_sense_config", self.hearing), edges)
        self.assertIn((self.component, "has_ai_perception_sense_config", self.sight), edges)
        self.assertIn((self.component, "uses_ai_perception_dominant_sense", self.sight_class), edges)
        self.assertIn((self.hearing, "implements_ai_perception_sense", self.hearing_class), edges)
        self.assertIn((self.sight, "implements_ai_perception_sense", self.sight_class), edges)
        self.assertIn((self.player, "has_ai_perception_stimuli_source", self.source), edges)
        self.assertIn((self.source, "registers_ai_perception_sense", self.sight_class), edges)
        self.assertIn((self.source, "registers_ai_perception_sense", self.hearing_class), edges)
        self.assertFalse(any(target == "" for _, _, target in edges))

    def test_null_sense_config_row_preserves_source_index_without_graph_edge(self) -> None:
        self._write_fixture()
        configs = list(rows(self.output / "ai_perception_sense_configs.jsonl"))
        configs.insert(1, {
            "blueprint_path": self.bp,
            "component_path": self.component,
            "config_index": 1,
            "config_path": "",
            "config_class": "",
            "implementation_class": "",
            "is_null": True,
            "max_age": None,
            "detection_by_affiliation": "",
            "detect_enemies": None,
            "detect_neutrals": None,
            "detect_friendlies": None,
            "hearing_range": None,
            "sight_radius": None,
            "lose_sight_radius": None,
            "peripheral_vision_angle_degrees": None,
            "property_count": 0,
        })
        configs[2]["config_index"] = 2
        write_jsonl(self.output / "ai_perception_sense_configs.jsonl", configs)
        component = list(rows(self.output / "ai_perception_components.jsonl"))[0]
        component["sense_config_count"] = 3
        write_jsonl(self.output / "ai_perception_components.jsonl", [component])

        self.assertIsNone(schema8.validation_error(self.output, rows))
        edges = graph.expected_edge_keys(self.output, rows)
        self.assertEqual(len(edges), 9)


if __name__ == "__main__":
    unittest.main()
