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
import uatool_ai_perception_capabilities as ai_capabilities


class AIPerceptionCapabilitiesTest(unittest.TestCase):
    def test_schema8_and_schema24_verification_promote_first_class_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            streams = list(ai_capabilities.AI_PERCEPTION_STREAMS)
            (root / "systems_manifest.json").write_text(json.dumps({
                "schema_version": 8,
                "success": True,
                "files": streams,
                "counts": {},
            }), encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({
                "schema_version": 12,
                "systems_schema_version": 8,
                "derived_schema_version": 24,
                "files": [],
            }), encoding="utf-8")
            (root / "systems_schema8_acceptance.json").write_text(json.dumps({
                "systems_schema_version": 8,
                "project": "E:/TheDigitalGame/ue/ContentExamples/ContentExamples.uproject",
            }), encoding="utf-8")
            (root / "ai_perception_graph_verification.json").write_text(json.dumps({
                "verified": True,
                "derived_schema_version": 24,
                "verified_exact_semantic_edge_count": 9,
            }), encoding="utf-8")
            for name in streams:
                (root / name).write_text("", encoding="utf-8")

            ai_capabilities.install(capabilities)
            manifest = capabilities.build_manifest(root)
            rows = [row for row in manifest["families"] if row["family"] == "ai_perception"]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["contract_coverage"], "first_class")
            self.assertEqual(row["corpus_coverage"], "first_class")
            self.assertTrue(row["available_in_corpus"])
            self.assertEqual(row["canonical_streams"], sorted(streams))
            self.assertEqual(len(row["derived_relations"]), 6)
            self.assertFalse(row["runtime_state_captured"])
            self.assertTrue(row["acceptance"]["accepted"])
            self.assertTrue(row["acceptance"]["verification"])
            self.assertEqual(row["acceptance"]["corpus_provenance"], "ContentExamples.uproject")

    def test_missing_schema8_stream_keeps_corpus_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            streams = list(ai_capabilities.AI_PERCEPTION_STREAMS[:-1])
            (root / "systems_manifest.json").write_text(json.dumps({
                "schema_version": 8,
                "success": True,
                "files": streams,
            }), encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({
                "schema_version": 12,
                "systems_schema_version": 8,
                "derived_schema_version": 24,
                "files": [],
            }), encoding="utf-8")

            ai_capabilities.install(capabilities)
            manifest = capabilities.build_manifest(root)
            row = next(row for row in manifest["families"] if row["family"] == "ai_perception")
            self.assertEqual(row["contract_coverage"], "first_class")
            self.assertEqual(row["corpus_coverage"], "external_or_excluded")
            self.assertFalse(row["available_in_corpus"])


if __name__ == "__main__":
    unittest.main()
