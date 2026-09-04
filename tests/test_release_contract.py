from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_capabilities as capabilities
import uatool_version as version


class ReleaseContractTest(unittest.TestCase):
    def test_plugin_descriptor_matches_beta_contract(self) -> None:
        descriptor = json.loads((ROOT / "UnrealAssetTool.uplugin").read_text(encoding="utf-8"))
        self.assertEqual(descriptor["Version"], version.PLUGIN_VERSION)
        self.assertEqual(descriptor["VersionName"], version.RELEASE_VERSION)
        self.assertTrue(descriptor["IsBetaVersion"])

    def test_cli_version_surfaces_match_contract(self) -> None:
        simple = subprocess.run(
            [sys.executable, str(SCRIPTS / "uatool.py"), "--version"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        self.assertEqual(
            simple.stdout.strip(),
            f"UnrealAssetTool {version.RELEASE_VERSION}",
        )

        detailed = subprocess.run(
            [sys.executable, str(SCRIPTS / "uatool.py"), "version", "--json"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(detailed.stdout)
        self.assertEqual(payload["version"], version.RELEASE_VERSION)
        self.assertTrue(payload["beta"])
        self.assertEqual(payload["engine_target"], version.ENGINE_TARGET)
        self.assertEqual(payload["validated_engine"], version.VALIDATED_ENGINE)
        self.assertEqual(payload["schemas"], version.CURRENT_SCHEMAS)

    def test_capability_release_metadata_matches_contract(self) -> None:
        self.assertEqual(capabilities.RELEASE_LINE, version.RELEASE_VERSION)
        self.assertEqual(capabilities.VALIDATED_ENGINE, version.VALIDATED_ENGINE)

    def test_current_facing_docs_match_schema_baseline(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        schema = (ROOT / "docs" / "schema.md").read_text(encoding="utf-8")
        coverage = (ROOT / "docs" / "coverage.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
        cross_project = (ROOT / "docs" / "cross-project-workflow.md").read_text(encoding="utf-8")
        release_contract = (ROOT / "docs" / "release-contract.md").read_text(encoding="utf-8")

        for text in (readme, schema, release_contract):
            self.assertIn(version.RELEASE_VERSION, text)

        compact_docs = (coverage, cross_project, release_contract)
        for name, value in version.CURRENT_SCHEMAS.items():
            if name in {"capabilities", "mesh", "world_geometry"}:
                continue
            token = f"{name}={value}"
            self.assertTrue(
                any(token in text.replace(" ", "") for text in compact_docs),
                msg=f"missing current schema token {token}",
            )

        self.assertIn("derived schema:    40", architecture)
        self.assertIn("systems schema:    11", architecture)
        self.assertIn("animation schema:   4", architecture)

    def test_release_contract_preserves_nonclaims(self) -> None:
        text = (ROOT / "docs" / "release-contract.md").read_text(encoding="utf-8")
        for phrase in (
            "no Blueprint VM execution",
            "no runtime delegate subscriber set/order/lifetime or broadcast execution",
            "no runtime Mover simulation",
            "no live GAS specs",
            "no Niagara/particle simulation",
        ):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
