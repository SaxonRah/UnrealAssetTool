from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_gas_graph as graph
from test_systems_gas import valid_rows, write_jsonl


class FakeGraph:
    COVERAGE_RANK = {"external_or_excluded": 0, "partial": 1, "first_class_depth_pending": 2, "first_class": 3}

    @staticmethod
    def _node_id(kind: str, path: str) -> str:
        return "pnode:" + hashlib.sha1(f"{kind}\x1f{path}".encode()).hexdigest()[:24]

    @staticmethod
    def _edge_id(source_kind: str, source: str, relation: str, target_kind: str, target: str) -> str:
        value = "\x1f".join((source_kind, source, relation, target_kind, target))
        return "pedge:" + hashlib.sha1(value.encode()).hexdigest()[:24]

    @staticmethod
    def _package(path: str) -> str:
        return path.split(".", 1)[0] if str(path).startswith("/") else ""


class GASGraphTest(unittest.TestCase):
    def _write(self, root: Path) -> None:
        data = valid_rows()
        for filename, rows in data.items():
            write_jsonl(root / filename, rows)

    def test_expected_edge_contract_is_exact_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(root)
            expected = graph.expected_edge_keys(root, graph._read_rows if hasattr(graph, "_read_rows") else self._rows)
            # The synthetic fixture has one of each structured family and
            # therefore a stable exact contract of 28 GAS relations.
            self.assertEqual(len(expected), 28)
            relations = {relation for _, relation, _ in expected}
            self.assertEqual(relations, set(graph.RELATION_STREAMS))
            self.assertNotIn("emits_gameplay_cue_tag", relations)

    @staticmethod
    def _rows(path: Path):
        if not path.is_file():
            return
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    yield json.loads(line)

    def test_augment_matches_expected_source_relation_target_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(root)
            nodes, edges = graph._augment(root, self._rows, [], [], FakeGraph)
            expected = graph.expected_edge_keys(root, self._rows)
            actual = {
                (str(row.get("source", "")), str(row.get("relation", "")), str(row.get("target", "")))
                for row in edges if str(row.get("relation", "")) in graph.RELATION_STREAMS
            }
            self.assertEqual(actual, expected)
            self.assertTrue(all(row.get("edge_quality") == "exact_semantic" for row in edges))

            roots = {(row.get("node_kind"), row.get("path")) for row in nodes if row.get("root")}
            self.assertIn(("gameplay_ability", "/Game/Abilities/GA_Test.GA_Test"), roots)
            self.assertIn(("gameplay_ability_set", "/Game/AbilitySets/AS_Test.AS_Test"), roots)
            self.assertIn(("gameplay_effect", "/Game/Effects/GE_Test.GE_Test"), roots)
            self.assertIn(("gameplay_cue", "/Game/Cues/GC_Test.GC_Test"), roots)
            self.assertIn(("gameplay_attribute_set", "/Script/TestGame.TestAttributeSet"), roots)

    def test_phase_style_ability_adds_only_class_topology_without_children(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._write(root)
            phase = {
                "ability_path": "/ShooterCore/Experiences/Phases/Phase_Playing.Phase_Playing",
                "package_name": "/ShooterCore/Experiences/Phases/Phase_Playing",
                "generated_class": "/ShooterCore/Experiences/Phases/Phase_Playing.Phase_Playing_C",
                "parent_class": "/Script/LyraGame.LyraGamePhaseAbility",
                "cdo_path": "/ShooterCore/Experiences/Phases/Phase_Playing.Default__Phase_Playing_C",
                "activation_policy": "OnInputTriggered", "activation_group": "Independent",
                "replication_policy": "ReplicateNo", "instancing_policy": "InstancedPerActor",
                "net_execution_policy": "ServerInitiated", "net_security_policy": "ServerOnly",
                "ability_tags": "", "cancel_abilities_with_tag": "", "block_abilities_with_tag": "",
                "activation_owned_tags": "", "activation_required_tags": "", "activation_blocked_tags": "",
                "source_required_tags": "", "source_blocked_tags": "", "target_required_tags": "",
                "target_blocked_tags": "", "cost_gameplay_effect_class": "",
                "cooldown_gameplay_effect_class": "", "trigger_count": 0, "additional_cost_count": 0,
            }
            with (root / "gas_abilities.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(phase, separators=(",", ":")) + "\n")
            expected = graph.expected_edge_keys(root, self._rows)
            phase_edges = [edge for edge in expected if edge[0].startswith(phase["ability_path"]) or edge[0] == phase["generated_class"]]
            self.assertEqual(
                set(phase_edges),
                {
                    (phase["ability_path"], "defines_gameplay_ability_class", phase["generated_class"]),
                    (phase["generated_class"], "inherits_gameplay_ability_class", phase["parent_class"]),
                },
            )


if __name__ == "__main__":
    unittest.main()
