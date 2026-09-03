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
import uatool_uaf_capabilities as uaf_capabilities


class UAFCapabilitiesTest(unittest.TestCase):
    def test_schema10_and_schema26_verification_promote_animnext_first_class(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            streams = list(uaf_capabilities.UAF_STREAMS)
            (root / "systems_manifest.json").write_text(json.dumps({
                "schema_version": 10,
                "success": True,
                "files": streams,
                "counts": {},
            }), encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({
                "schema_version": 12,
                "systems_schema_version": 10,
                "derived_schema_version": 26,
                "files": [],
            }), encoding="utf-8")
            (root / "systems_schema10_acceptance.json").write_text(json.dumps({
                "systems_schema_version": 10,
                "project": "E:/TheDigitalGame/ue/GameAnimationSample/GameAnimationSample.uproject",
            }), encoding="utf-8")
            (root / "uaf_graph_verification.json").write_text(json.dumps({
                "verified": True,
                "derived_schema_version": 26,
                "verified_exact_semantic_edge_count": 213,
            }), encoding="utf-8")
            for name in streams:
                (root / name).write_text("", encoding="utf-8")

            uaf_capabilities.install(capabilities)
            manifest = capabilities.build_manifest(root)
            row = next(row for row in manifest["families"] if row["family"] == "animnext")

            self.assertEqual(row["contract_coverage"], "first_class")
            self.assertEqual(row["corpus_coverage"], "first_class")
            self.assertTrue(row["available_in_corpus"])
            self.assertFalse(row["runtime_state_captured"])
            self.assertEqual(row["canonical_streams"], sorted(uaf_capabilities.UAF_STREAMS))
            self.assertEqual(len(row["derived_relations"]), 14)
            self.assertTrue(row["acceptance"]["accepted"])
            self.assertTrue(row["acceptance"]["verification"])
            self.assertEqual(row["acceptance"]["corpus_provenance"], "GameAnimationSample.uproject")
            self.assertIn("loaded UObject classes", row["boundary"])

    def test_missing_schema10_stream_keeps_corpus_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            streams = list(uaf_capabilities.UAF_STREAMS[:-1])
            (root / "systems_manifest.json").write_text(json.dumps({
                "schema_version": 10,
                "success": True,
                "files": streams,
            }), encoding="utf-8")
            (root / "manifest.json").write_text(json.dumps({
                "schema_version": 12,
                "systems_schema_version": 10,
                "derived_schema_version": 26,
                "files": [],
            }), encoding="utf-8")

            uaf_capabilities.install(capabilities)
            manifest = capabilities.build_manifest(root)
            row = next(row for row in manifest["families"] if row["family"] == "animnext")

            self.assertEqual(row["contract_coverage"], "first_class")
            self.assertEqual(row["corpus_coverage"], "external_or_excluded")
            self.assertFalse(row["available_in_corpus"])
            self.assertFalse(row["acceptance"]["accepted"])
            self.assertFalse(row["acceptance"]["verification"])

    def test_canonical_facade_installs_uaf_capabilities(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_uaf_capabilities as _uaf_capabilities", facade)
        self.assertIn("_uaf_capabilities.install(_capabilities)", facade)


if __name__ == "__main__":
    unittest.main()
