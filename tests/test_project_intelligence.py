from __future__ import annotations

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

import uatool_project_intelligence as intel


class ProjectIntelligenceTest(unittest.TestCase):
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
            CREATE TABLE project_neighborhoods(
                root_path TEXT PRIMARY KEY,root_kind TEXT NOT NULL,root_coverage TEXT NOT NULL,max_depth INTEGER NOT NULL,
                edge_count INTEGER NOT NULL,node_count INTEGER NOT NULL,truncated INTEGER NOT NULL,text TEXT NOT NULL,json TEXT NOT NULL
            );
            CREATE TABLE blueprints(object_path TEXT PRIMARY KEY,json TEXT NOT NULL);
            CREATE TABLE gas_abilities(ability_path TEXT PRIMARY KEY,json TEXT NOT NULL);
            """
        )
        self.a = "/Game/Test/A.A"
        self.b = "/Game/Test/B.B"
        self.c = "/Game/Test/C.C"
        self.d = "/Game/Test/D.D"
        self._node("a", "blueprint", self.a, family="blueprint")
        self._node("b", "gameplay_ability", self.b, family="gas")
        self._node("c", "gameplay_effect", self.c, family="gas")
        self._node("d", "niagara_system", self.d, family="vfx")
        self.conn.execute("INSERT INTO blueprints VALUES(?,?)", (self.a, json.dumps({"object_path": self.a})))
        self.conn.execute("INSERT INTO gas_abilities VALUES(?,?)", (self.b, json.dumps({"ability_path": self.b})))
        self._write_capabilities()

    def tearDown(self) -> None:
        self.conn.close()
        self.temp.cleanup()

    def _node(self, node_id: str, kind: str, path: str, *, family: str) -> None:
        self.conn.execute(
            "INSERT INTO project_nodes VALUES(?,?,?,?,?,?,?,?,?)",
            (node_id, kind, path, "first_class", "", path.split(".", 1)[0], family, 1, "{}"),
        )

    def _edge(
        self,
        edge_id: str,
        source: str,
        relation: str,
        target: str,
        quality: str,
        *,
        source_kind: str = "object",
        target_kind: str = "object",
        stream: str = "test.jsonl",
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
                "first_class",
                quality,
                1,
                json.dumps(evidence, separators=(",", ":")),
            ),
        )

    def _write_capabilities(self) -> None:
        (self.output / "capabilities.json").write_text(
            json.dumps(
                {
                    "capability_schema_version": 1,
                    "schemas": {
                        "structural": 12,
                        "world": 12,
                        "animation": 1,
                        "vfx": 1,
                        "systems": 6,
                        "derived": 22,
                    },
                    "corpus": {
                        "partial": False,
                        "canonical_passes": ["structural", "world", "animation", "vfx", "systems"],
                    },
                    "families": [
                        {
                            "family": "blueprint",
                            "contract_coverage": "first_class",
                            "corpus_coverage": "first_class",
                            "available_in_corpus": True,
                            "runtime_state_captured": False,
                        },
                        {
                            "family": "gas",
                            "contract_coverage": "first_class",
                            "corpus_coverage": "first_class",
                            "available_in_corpus": True,
                            "runtime_state_captured": False,
                        },
                    ],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def test_neighbors_preserves_quality_evidence_and_filtering(self) -> None:
        self._edge(
            "ab", self.a, "calls", self.b, "exact_semantic",
            source_kind="blueprint", target_kind="gameplay_ability", stream="blueprint_calls.jsonl",
        )
        self._edge(
            "ac", self.a, "depends_on_package", self.c, "generic_package_dependency",
            source_kind="blueprint", target_kind="gameplay_effect", stream="asset_dependencies.jsonl",
        )
        self.conn.commit()

        report = intel.neighbors_report(self.output, self.a, min_quality="exact_reference")
        self.assertTrue(report["found"])
        self.assertEqual(report["total"], 1)
        self.assertEqual(len(report["edges"]), 1)
        edge = report["edges"][0]
        self.assertEqual(edge["relation"], "calls")
        self.assertEqual(edge["edge_quality"], "exact_semantic")
        self.assertEqual(edge["neighbor_path"], self.b)
        self.assertEqual(edge["evidence"][0]["stream"], "blueprint_calls.jsonl")

    def test_why_connected_prefers_stronger_two_hop_path_over_generic_shortcut(self) -> None:
        self._edge(
            "direct", self.a, "package_shortcut", self.c, "generic_package_dependency",
            source_kind="blueprint", target_kind="gameplay_effect", stream="asset_dependencies.jsonl",
        )
        self._edge(
            "ab", self.a, "grants", self.b, "exact_semantic",
            source_kind="blueprint", target_kind="gameplay_ability", stream="grant.jsonl",
        )
        self._edge(
            "bc", self.b, "uses_effect", self.c, "exact_semantic",
            source_kind="gameplay_ability", target_kind="gameplay_effect", stream="gas_abilities.jsonl",
        )
        self.conn.commit()

        report = intel.why_connected_report(self.output, self.a, self.c, max_depth=3)
        self.assertTrue(report["path_found"])
        self.assertEqual(report["hop_count"], 2)
        self.assertEqual(report["bottleneck_quality"], "exact_semantic")
        self.assertEqual([edge["edge_id"] for edge in report["hops"]], ["ab", "bc"])

    def test_why_connected_not_found_is_explicitly_bounded_not_disconnected(self) -> None:
        self._edge(
            "ab", self.a, "grants", self.b, "exact_semantic",
            source_kind="blueprint", target_kind="gameplay_ability",
        )
        self.conn.commit()

        report = intel.why_connected_report(self.output, self.a, self.d, max_depth=1, per_node_limit=8)
        self.assertTrue(report["found"])
        self.assertFalse(report["path_found"])
        self.assertIn("not proof", report["note"])
        self.assertEqual(report["search"]["max_depth"], 1)

    def test_project_summary_reports_capability_graph_and_specialist_counts(self) -> None:
        self._edge(
            "ab", self.a, "grants", self.b, "exact_semantic",
            source_kind="blueprint", target_kind="gameplay_ability",
        )
        self.conn.execute(
            "INSERT INTO project_neighborhoods VALUES(?,?,?,?,?,?,?,?,?)",
            (self.a, "blueprint", "first_class", 3, 1, 2, 0, "", "{}"),
        )
        self.conn.commit()

        report = intel.project_summary_report(self.output, limit=5)
        self.assertFalse(report["partial"])
        self.assertEqual(report["schemas"]["systems"], 6)
        self.assertEqual(report["graph"]["nodes"], 4)
        self.assertEqual(report["graph"]["edges"], 1)
        self.assertEqual(report["graph"]["quality_counts"]["exact_semantic"], 1)
        self.assertEqual(report["specialist_counts"]["blueprints"], 1)
        self.assertEqual(report["specialist_counts"]["gas_abilities"], 1)
        self.assertEqual(report["neighborhoods"]["count"], 1)

    def test_install_wraps_runtime_and_canonical_facade(self) -> None:
        fake = types.SimpleNamespace(main=lambda: 23)
        intel.install(fake)
        self.assertTrue(fake._project_intelligence_commands_installed)
        with mock.patch.object(sys, "argv", ["uatool.py", "query"]):
            self.assertEqual(fake.main(), 23)

        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_project_intelligence as _project_intelligence", facade)
        self.assertIn("_project_intelligence.install()", facade)


if __name__ == "__main__":
    unittest.main()
