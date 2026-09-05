from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_inspect as inspect_report


class InspectReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.db = self.output / "uat.db"
        self.conn = sqlite3.connect(self.db)
        self.conn.executescript(
            """
            CREATE TABLE project_nodes(
                node_id TEXT PRIMARY KEY,node_kind TEXT NOT NULL,path TEXT NOT NULL,coverage TEXT NOT NULL,
                class_path TEXT NOT NULL,package_name TEXT NOT NULL,family TEXT NOT NULL,root INTEGER NOT NULL,json TEXT NOT NULL
            );
            CREATE INDEX project_nodes_path_idx ON project_nodes(path);
            CREATE TABLE project_edges(
                edge_id TEXT PRIMARY KEY,source_kind TEXT NOT NULL,source TEXT NOT NULL,relation TEXT NOT NULL,
                target_kind TEXT NOT NULL,target TEXT NOT NULL,source_coverage TEXT NOT NULL,target_coverage TEXT NOT NULL,
                edge_quality TEXT NOT NULL,evidence_count INTEGER NOT NULL,evidence_json TEXT NOT NULL
            );
            CREATE INDEX project_edges_source_idx ON project_edges(source,relation);
            CREATE INDEX project_edges_target_idx ON project_edges(target,relation);
            CREATE TABLE gas_abilities(
                ability_path TEXT PRIMARY KEY,activation_policy TEXT NOT NULL,json TEXT NOT NULL
            );
            CREATE TABLE gas_ability_triggers(
                ability_path TEXT NOT NULL,trigger_index INTEGER NOT NULL,trigger_tag TEXT NOT NULL,json TEXT NOT NULL
            );
            """
        )

    def tearDown(self) -> None:
        self.conn.close()
        self.temp.cleanup()

    def _node(
        self,
        node_id: str,
        kind: str,
        path: str,
        *,
        coverage: str = "first_class",
        family: str = "gas",
        root: int = 1,
        class_path: str = "",
    ) -> None:
        self.conn.execute(
            "INSERT INTO project_nodes VALUES(?,?,?,?,?,?,?,?,?)",
            (node_id, kind, path, coverage, class_path, path.split(".", 1)[0], family, root, "{}"),
        )

    def _edge(
        self,
        edge_id: str,
        source: str,
        relation: str,
        target: str,
        *,
        quality: str,
        source_kind: str = "gameplay_ability",
        target_kind: str = "gameplay_effect",
        target_coverage: str = "first_class",
        stream: str,
    ) -> None:
        evidence = [{"stream": stream, "quality": quality}]
        self.conn.execute(
            "INSERT INTO project_edges VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                edge_id,
                source_kind,
                source,
                relation,
                target_kind,
                target,
                "first_class",
                target_coverage,
                quality,
                len(evidence),
                json.dumps(evidence, separators=(",", ":")),
            ),
        )

    def _capabilities(self) -> None:
        (self.output / "capabilities.json").write_text(
            json.dumps(
                {
                    "capability_schema_version": 1,
                    "schemas": {
                        "structural": 0,
                        "world": 0,
                        "animation": 0,
                        "vfx": 0,
                        "systems": 6,
                        "derived": 22,
                    },
                    "corpus": {"partial": True, "canonical_passes": ["systems"]},
                    "families": [
                        {
                            "family": "gas",
                            "contract_coverage": "first_class",
                            "corpus_coverage": "first_class",
                            "runtime_state_captured": False,
                            "boundary": "Authored GAS facts only; live ASC state is not captured.",
                        }
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_dossier_joins_canonical_child_capability_and_provenance(self) -> None:
        ability = "/Game/Abilities/GA_Test.GA_Test"
        effect = "/Game/Effects/GE_Cost.GE_Cost_C"
        package = "/Game/Abilities/GA_Test"
        self._node("a", "gameplay_ability", ability)
        self._node("e", "gameplay_effect", effect)
        self._node("p", "package", package, coverage="generic_only", family="package", root=0)
        self._edge(
            "exact",
            ability,
            "uses_cost_gameplay_effect_class",
            effect,
            quality="exact_semantic",
            stream="gas_abilities.jsonl",
        )
        self._edge(
            "generic",
            ability,
            "member_of_package",
            package,
            quality="generic_package_dependency",
            target_kind="package",
            target_coverage="generic_only",
            stream="asset_dependencies.jsonl",
        )
        ability_row = {
            "ability_path": ability,
            "activation_policy": "OnInputTriggered",
            "cost_gameplay_effect_class": effect,
        }
        trigger_row = {
            "ability_path": ability,
            "trigger_index": 0,
            "trigger_tag": "GameplayEvent.Test",
            "trigger_source": "GameplayEvent",
        }
        self.conn.execute(
            "INSERT INTO gas_abilities VALUES(?,?,?)",
            (ability, "OnInputTriggered", json.dumps(ability_row, separators=(",", ":"))),
        )
        self.conn.execute(
            "INSERT INTO gas_ability_triggers VALUES(?,?,?,?)",
            (ability, 0, "GameplayEvent.Test", json.dumps(trigger_row, separators=(",", ":"))),
        )
        self.conn.commit()
        self._capabilities()

        report = inspect_report.build_report(self.output, ability)
        self.assertTrue(report["found"])
        self.assertEqual(report["resolved_path"], ability)
        self.assertEqual(report["primary"]["node_kind"], "gameplay_ability")
        self.assertEqual(report["capabilities"]["family"]["family"], "gas")
        self.assertFalse(report["capabilities"]["family"]["runtime_state_captured"])

        roots = {row["table"]: row for row in report["canonical_facts"]}
        self.assertEqual(roots["gas_abilities"]["record"]["activation_policy"], "OnInputTriggered")
        children = {row["table"]: row for row in report["child_facts"]}
        self.assertEqual(children["gas_ability_triggers"]["count"], 1)
        self.assertEqual(children["gas_ability_triggers"]["records"][0]["trigger_tag"], "GameplayEvent.Test")

        self.assertEqual(report["graph"]["quality_counts"]["exact_semantic"], 1)
        self.assertEqual(report["graph"]["quality_counts"]["generic_package_dependency"], 1)
        self.assertEqual(report["edges"][0]["edge_quality"], "exact_semantic")
        self.assertEqual(report["edges"][0]["evidence"][0]["stream"], "gas_abilities.jsonl")

    def test_fragment_resolution_proves_ambiguity_across_many_node_variants(self) -> None:
        first = "/Game/Foo/FooA.FooA"
        second = "/Game/Foo/FooB.FooB"
        # The old implementation sampled candidate_limit*8 node rows. Eight or
        # more variants for the lexicographically first path could hide the
        # second distinct path and incorrectly mark the fragment unambiguous.
        for index in range(12):
            self._node(
                f"a{index}",
                f"variant_{index:02d}",
                first,
                coverage="generic_only",
                family="asset_registry",
                root=0,
            )
        self._node("b", "blueprint", second, family="blueprint")
        self.conn.commit()

        report = inspect_report.build_report(self.output, "/Game/Foo/", candidate_limit=1)
        self.assertFalse(report["found"])
        self.assertTrue(report["ambiguous"])
        self.assertTrue(report["candidates_truncated"])
        self.assertEqual(len(report["candidates"]), 1)
        self.assertEqual(report["candidates"][0]["path"], first)

    def test_unambiguous_object_fragment_can_resolve(self) -> None:
        ability = "/Game/Abilities/GA_Unique.GA_Unique"
        package = "/Game/Abilities/GA_Unique"
        self._node("a", "gameplay_ability", ability)
        self._node("p", "package", package, coverage="generic_only", family="package", root=0)
        self.conn.commit()

        report = inspect_report.build_report(self.output, ".GA_Unique")
        self.assertTrue(report["found"])
        self.assertEqual(report["resolved_path"], ability)

    def test_edge_limit_does_not_change_full_relation_or_quality_counts(self) -> None:
        ability = "/Game/Abilities/GA_Limited.GA_Limited"
        effect = "/Game/Effects/GE_Limited.GE_Limited_C"
        other = "/Game/Effects/GE_Other.GE_Other_C"
        self._node("a", "gameplay_ability", ability)
        self._node("e", "gameplay_effect", effect)
        self._node("o", "gameplay_effect", other)
        self._edge(
            "1", ability, "uses_cost_gameplay_effect_class", effect,
            quality="exact_semantic", stream="gas_abilities.jsonl",
        )
        self._edge(
            "2", ability, "references_effect", other,
            quality="exact_reference", stream="systems_references.jsonl",
        )
        self.conn.commit()

        report = inspect_report.build_report(self.output, ability, edge_limit=1)
        self.assertEqual(report["graph"]["total"], 2)
        self.assertEqual(report["graph"]["shown"], 1)
        self.assertTrue(report["graph"]["truncated"])
        self.assertEqual(report["edges"][0]["edge_quality"], "exact_semantic")
        relations = {(row["direction"], row["relation"]): row["count"] for row in report["graph"]["relation_counts"]}
        self.assertEqual(relations[("out", "uses_cost_gameplay_effect_class")], 1)
        self.assertEqual(relations[("out", "references_effect")], 1)

    def test_json_cli_output_is_ascii_safe_and_unicode_round_trips(self) -> None:
        report = {
            "found": True,
            "query": "/Game/Test.Test",
            "canonical_facts": [
                {
                    "table": "assets",
                    "identity_column": "object_path",
                    "record": {"display_name": "Café → テスト"},
                }
            ],
        }
        stream = io.StringIO()
        with mock.patch.object(inspect_report, "build_report", return_value=report), \
             mock.patch.object(inspect_report, "_canonical_module", return_value=None), \
             mock.patch.object(sys, "stdout", stream):
            result = inspect_report._cli([
                str(self.output),
                "/Game/Test.Test",
                "--json",
            ])
        self.assertEqual(result, 0)
        payload = stream.getvalue()
        payload.encode("ascii")
        self.assertEqual(
            json.loads(payload)["canonical_facts"][0]["record"]["display_name"],
            "Café → テスト",
        )

    def test_install_wraps_runtime_without_creating_an_alternate_launcher(self) -> None:
        fake = types.SimpleNamespace(main=lambda: 17)
        inspect_report.install(fake)
        self.assertTrue(fake._inspect_command_installed)
        with mock.patch.object(sys, "argv", ["uatool.py", "query"]):
            self.assertEqual(fake.main(), 17)

        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_inspect as _inspect", facade)
        self.assertIn("_inspect.install()", facade)


if __name__ == "__main__":
    unittest.main()
