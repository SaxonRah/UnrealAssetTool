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

import uatool_smartobject_graph as graph
import uatool_systems_schema7_accept as accept
import uatool_systems_smartobjects as smart
from test_systems_smartobjects import valid_rows, write_jsonl


class SystemsSchema7AcceptanceTest(unittest.TestCase):
    @staticmethod
    def _rows(path: Path):
        yield from smart._read_rows(path)

    def _populate(self, root: Path) -> None:
        data = valid_rows()
        for filename in smart.SMARTOBJECT_FILES:
            write_jsonl(root / filename, data.get(filename, []))

    def test_citysample_shaped_expectations_lock_exact_graph_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._populate(root)
            expectations = accept._graph_expectations(root, self._rows)
            self.assertEqual(expectations["systems_schema_version"], 7)
            self.assertEqual(expectations["target_derived_schema_version"], 23)
            self.assertEqual(expectations["expected_exact_semantic_edge_count"], 7)
            self.assertEqual(expectations["expected_relation_counts"]["has_smart_object_slot"], 2)
            self.assertEqual(expectations["expected_relation_counts"]["has_default_smart_object_behavior"], 1)
            self.assertEqual(expectations["expected_relation_counts"]["has_smart_object_behavior"], 0)
            self.assertEqual(expectations["expected_relation_counts"]["instance_of_smart_object_behavior_class"], 1)
            self.assertEqual(expectations["expected_relation_counts"]["uses_smart_object_world_condition_schema"], 1)
            self.assertEqual(expectations["expected_relation_counts"]["uses_smart_object_selection_schema"], 2)
            self.assertFalse(expectations["runtime_state_captured"])

    def test_verifier_accepts_only_exact_smartobject_edges_and_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._populate(root)
            expectations = accept._graph_expectations(root, self._rows)
            (root / accept.GRAPH_EXPECTATIONS_MANIFEST).write_text(json.dumps(expectations) + "\n", encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({"derived_schema_version": 23}) + "\n", encoding="utf-8")

            edge_rows = []
            for source, relation, target in sorted(graph.expected_edge_keys(root, self._rows)):
                edge_rows.append({
                    "source": source,
                    "relation": relation,
                    "target": target,
                    "edge_quality": "exact_semantic",
                    "evidence": [{"stream": graph.RELATION_STREAMS[relation], "quality": "exact_semantic"}],
                })
            write_jsonl(root / "project_edges.jsonl", edge_rows)
            definition = valid_rows()["smartobject_definitions.jsonl"][0]["definition_path"]
            write_jsonl(root / "project_nodes.jsonl", [{
                "path": definition,
                "node_kind": "smart_object_definition",
                "root": True,
            }])

            result = accept._verify_graph(root, self._rows)
            self.assertTrue(result["verified"])
            self.assertEqual(result["verified_exact_semantic_edge_count"], 7)
            self.assertEqual(result["root_counts"]["smart_object_definition"], 1)

            with (root / "project_edges.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "source": definition,
                    "relation": "has_smart_object_slot",
                    "target": definition + "#smartobject_slot:INVENTED",
                    "edge_quality": "exact_semantic",
                    "evidence": [{"stream": "smartobject_slots.jsonl"}],
                }) + "\n")
            with self.assertRaisesRegex(RuntimeError, "edge set mismatch"):
                accept._verify_graph(root, self._rows)

    def test_public_composition_installs_schema7_acceptance_commands(self) -> None:
        import uatool  # noqa: F401
        import uatool_runtime
        import uatool_systems

        self.assertEqual(uatool_systems.SYSTEMS_SCHEMA_VERSION, 7)
        self.assertTrue(getattr(uatool_runtime, "_systems_schema7_accept_installed", False))

    def test_native_manifest_publication_is_synchronous(self) -> None:
        scanner = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp"
        ).read_text(encoding="utf-8")
        policy = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsSmartObjectsPolicy.inl"
        ).read_text(encoding="utf-8")
        self.assertIn("SmartObjectSchema7SaveStringToFile", policy)
        self.assertIn("UpgradeSystemsManifestToSchema7", policy)
        self.assertIn("#define SaveStringToFile SmartObjectSchema7SaveStringToFile", scanner)
        self.assertIn("#undef SaveStringToFile", scanner)
        self.assertNotIn("GSmartObjectSchema7ExitHookRegistered", policy)
        self.assertNotIn("FCoreDelegates::OnEnginePreExit.AddStatic", policy)
        self.assertNotIn("FCoreDelegates::OnPreExit.AddStatic", policy)
        self.assertNotIn("FCoreDelegates::OnExit.AddStatic", policy)


if __name__ == "__main__":
    unittest.main()
