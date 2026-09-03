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

import uatool_capabilities as capabilities
import uatool_dataflow_chaos_capabilities as dataflow_capabilities


class DataflowChaosCapabilitiesTest(unittest.TestCase):
    def test_schema9_and_schema25_verification_promote_both_first_class_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            streams = [
                *dataflow_capabilities.DATAFLOW_STREAMS,
                *dataflow_capabilities.GEOMETRY_COLLECTION_STREAMS,
            ]
            (root / "systems_manifest.json").write_text(json.dumps({
                "schema_version": 9,
                "success": True,
                "files": streams,
                "counts": {},
            }), encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({
                "schema_version": 12,
                "systems_schema_version": 9,
                "derived_schema_version": 25,
                "files": [],
            }), encoding="utf-8")
            (root / "systems_schema9_acceptance.json").write_text(json.dumps({
                "systems_schema_version": 9,
                "project": "E:/TheDigitalGame/ue/ContentExamples/ContentExamples.uproject",
            }), encoding="utf-8")
            (root / "dataflow_chaos_graph_verification.json").write_text(json.dumps({
                "verified": True,
                "derived_schema_version": 25,
                "verified_exact_semantic_edge_count": 4595,
            }), encoding="utf-8")
            for name in streams:
                (root / name).write_text("", encoding="utf-8")

            dataflow_capabilities.install(capabilities)
            manifest = capabilities.build_manifest(root)

            dataflow = next(row for row in manifest["families"] if row["family"] == "dataflow")
            geometry = next(row for row in manifest["families"] if row["family"] == "geometry_collection")

            for row in (dataflow, geometry):
                self.assertEqual(row["contract_coverage"], "first_class")
                self.assertEqual(row["corpus_coverage"], "first_class")
                self.assertTrue(row["available_in_corpus"])
                self.assertFalse(row["runtime_state_captured"])
                self.assertTrue(row["acceptance"]["accepted"])
                self.assertTrue(row["acceptance"]["verification"])
                self.assertEqual(row["acceptance"]["corpus_provenance"], "ContentExamples.uproject")

            self.assertEqual(dataflow["canonical_streams"], sorted(dataflow_capabilities.DATAFLOW_STREAMS))
            self.assertEqual(geometry["canonical_streams"], sorted(dataflow_capabilities.GEOMETRY_COLLECTION_STREAMS))
            self.assertEqual(len(dataflow["derived_relations"]), 6)
            self.assertEqual(len(geometry["derived_relations"]), 2)
            self.assertIn("GeometrySource", geometry["boundary"])

    def test_incomplete_schema9_streams_keep_each_family_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            streams = [
                *dataflow_capabilities.DATAFLOW_STREAMS[:-1],
                *dataflow_capabilities.GEOMETRY_COLLECTION_STREAMS,
            ]
            (root / "systems_manifest.json").write_text(json.dumps({
                "schema_version": 9,
                "success": True,
                "files": streams,
            }), encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({
                "schema_version": 12,
                "systems_schema_version": 9,
                "derived_schema_version": 25,
                "files": [],
            }), encoding="utf-8")

            dataflow_capabilities.install(capabilities)
            manifest = capabilities.build_manifest(root)
            dataflow = next(row for row in manifest["families"] if row["family"] == "dataflow")
            geometry = next(row for row in manifest["families"] if row["family"] == "geometry_collection")

            self.assertEqual(dataflow["contract_coverage"], "first_class")
            self.assertEqual(dataflow["corpus_coverage"], "external_or_excluded")
            self.assertFalse(dataflow["available_in_corpus"])
            self.assertEqual(geometry["contract_coverage"], "first_class")
            self.assertEqual(geometry["corpus_coverage"], "first_class")
            self.assertTrue(geometry["available_in_corpus"])


if __name__ == "__main__":
    unittest.main()
