from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_gas_graph as graph
import uatool_systems_gas as gas
import uatool_systems_schema6_accept as accept
from test_systems_gas import valid_rows, write_jsonl


class SystemsSchema6AcceptanceTest(unittest.TestCase):
    @staticmethod
    def _rows(path: Path):
        yield from gas._read_rows(path)

    def _capture(self, root: Path) -> types.SimpleNamespace:
        data = valid_rows()
        for filename in gas.GAS_FILES:
            write_jsonl(root / filename, data.get(filename, []))
        manifest = {
            "schema_version": 6,
            "success": True,
            "error": "",
            "counts": {
                filename.removesuffix(".jsonl"): len(data.get(filename, []))
                for filename in gas.GAS_FILES
            },
        }
        (root / "systems_manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        return types.SimpleNamespace(
            __name__="uatool_systems",
            SYSTEMS_SCHEMA_VERSION=6,
            RAW_FILES=("systems_manifest.json", *gas.GAS_FILES),
            _rows=self._rows,
            validation_error=lambda output: gas.validation_error(Path(output), self._rows),
        )

    def test_accept_promotes_raw_and_writes_exact_graph_expectations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "Test.uproject"
            project.write_text("{}\n", encoding="utf-8")
            capture = root / "capture"
            corpus = root / "corpus"
            capture.mkdir()
            systems = self._capture(capture)
            result = accept.accept_schema6(systems, project, corpus=corpus, systems_capture=capture)
            self.assertEqual(result["systems_schema_version"], 6)
            self.assertEqual(result["target_derived_schema_version"], 22)
            self.assertEqual(result["expected_exact_semantic_edge_count"], 28)
            self.assertEqual(json.loads((corpus / "systems_manifest.json").read_text())["schema_version"], 6)
            expectations = json.loads((corpus / accept.GRAPH_EXPECTATIONS_MANIFEST).read_text())
            self.assertEqual(expectations["expected_exact_semantic_edge_count"], 28)
            self.assertFalse(expectations["runtime_state_captured"])

    def test_verifier_accepts_only_exact_edges_and_specialist_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            corpus = Path(temp)
            systems = self._capture(corpus)
            expectations = accept._graph_expectations(corpus, self._rows)
            (corpus / accept.GRAPH_EXPECTATIONS_MANIFEST).write_text(json.dumps(expectations) + "\n", encoding="utf-8")
            (corpus / "manifest.json").write_text(json.dumps({"derived_schema_version": 22}) + "\n", encoding="utf-8")

            expected = graph.expected_edge_keys(corpus, self._rows)
            edge_rows = []
            for source, relation, target in sorted(expected):
                edge_rows.append({
                    "source": source,
                    "relation": relation,
                    "target": target,
                    "edge_quality": "exact_semantic",
                    "evidence": [{"stream": graph.RELATION_STREAMS[relation], "quality": "exact_semantic"}],
                })
            write_jsonl(corpus / "project_edges.jsonl", edge_rows)

            roots = []
            for filename, path_field, kind in (
                ("gas_abilities.jsonl", "ability_path", "gameplay_ability"),
                ("gas_ability_sets.jsonl", "ability_set_path", "gameplay_ability_set"),
                ("gas_gameplay_effects.jsonl", "gameplay_effect_path", "gameplay_effect"),
                ("gas_gameplay_cues.jsonl", "gameplay_cue_path", "gameplay_cue"),
                ("gas_attribute_sets.jsonl", "attribute_set_class", "gameplay_attribute_set"),
            ):
                for row in self._rows(corpus / filename):
                    roots.append({"path": row[path_field], "node_kind": kind, "root": True})
            write_jsonl(corpus / "project_nodes.jsonl", roots)

            result = accept._verify_graph(corpus, self._rows)
            self.assertTrue(result["verified"])
            self.assertEqual(result["verified_exact_semantic_edge_count"], 28)
            self.assertFalse(result["runtime_state_captured"])

            # An invented GAS-domain edge is rejected even when otherwise exact.
            with (corpus / "project_edges.jsonl").open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({
                    "source": "/Game/Fake.Fake",
                    "relation": "grants_gameplay_ability_class",
                    "target": "/Game/Fake.GA_Fake_C",
                    "edge_quality": "exact_semantic",
                    "evidence": [{"stream": "gas_ability_set_abilities.jsonl"}],
                }) + "\n")
            with self.assertRaisesRegex(RuntimeError, "edge set mismatch"):
                accept._verify_graph(corpus, self._rows)

    def test_public_composition_resolves_schema6_and_derived22(self) -> None:
        import uatool
        import uatool_project_graph
        import uatool_systems

        self.assertEqual(uatool_systems.SYSTEMS_SCHEMA_VERSION, 6)
        self.assertEqual(uatool.FINAL_DERIVED_SCHEMA_VERSION, 22)
        self.assertEqual(uatool_project_graph.DERIVED_SCHEMA_VERSION, 22)
        self.assertTrue(getattr(uatool_project_graph, "_gas_graph_installed", False))


if __name__ == "__main__":
    unittest.main()
