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
import uatool_smartobject_capabilities as smart_capabilities


def write_json(root: Path, filename: str, value: dict) -> None:
    (root / filename).write_text(json.dumps(value), encoding="utf-8", newline="\n")


class SmartObjectCapabilitiesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        smart_capabilities.install(capabilities)

    def test_schema7_verified_corpus_is_first_class(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root, "manifest.json", {
                "schema_version": 12,
                "derived_schema_version": 23,
                "files": [],
            })
            write_json(root, "systems_manifest.json", {
                "schema_version": 7,
                "success": True,
                "files": list(smart_capabilities.SMARTOBJECT_STREAMS),
            })
            write_json(root, "systems_schema7_acceptance.json", {
                "systems_schema_version": 7,
                "project": "N:/EpicVault/Projects/CitySample/CitySample.uproject",
            })
            write_json(root, "smartobject_graph_verification.json", {
                "verified": True,
                "derived_schema_version": 23,
                "verified_exact_semantic_edge_count": 7,
            })

            manifest = capabilities.build_manifest(root)
            rows = [row for row in manifest["families"] if row["family"] == "smart_objects"]
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["contract_coverage"], "first_class")
            self.assertEqual(row["corpus_coverage"], "first_class")
            self.assertTrue(row["available_in_corpus"])
            self.assertEqual(row["canonical_pass"], "systems")
            self.assertEqual(row["canonical_streams"], sorted(smart_capabilities.SMARTOBJECT_STREAMS))
            self.assertEqual(len(row["derived_relations"]), 6)
            self.assertTrue(row["acceptance"]["accepted"])
            self.assertTrue(row["acceptance"]["verification"])
            self.assertEqual(row["acceptance"]["corpus_provenance"], "CitySample.uproject")
            self.assertFalse(row["runtime_state_captured"])

    def test_older_schema_does_not_claim_corpus_availability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root, "manifest.json", {
                "schema_version": 12,
                "derived_schema_version": 22,
                "files": [],
            })
            write_json(root, "systems_manifest.json", {
                "schema_version": 6,
                "success": True,
                "files": [],
            })

            manifest = capabilities.build_manifest(root)
            row = next(row for row in manifest["families"] if row["family"] == "smart_objects")
            self.assertEqual(row["contract_coverage"], "first_class")
            self.assertEqual(row["corpus_coverage"], "external_or_excluded")
            self.assertFalse(row["available_in_corpus"])
            self.assertFalse(row["acceptance"]["accepted"])
            self.assertFalse(row["acceptance"]["verification"])

    def test_canonical_facade_installs_extension(self) -> None:
        import uatool  # noqa: F401
        self.assertTrue(getattr(capabilities, "_smartobject_capabilities_installed", False))


if __name__ == "__main__":
    unittest.main()
