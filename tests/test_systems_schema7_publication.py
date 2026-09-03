from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "Source/UnrealAssetTool/Private"


class SystemsSchema7PublicationTest(unittest.TestCase):
    def test_schema7_wraps_the_authoritative_driver_manifest_write(self) -> None:
        scanner = (PRIVATE / "UnrealAssetToolSystemsScanner.cpp").read_text(encoding="utf-8")
        driver = (PRIVATE / "UnrealAssetToolSystemsDriver.inl").read_text(encoding="utf-8")
        policy = (PRIVATE / "UnrealAssetToolSystemsSmartObjectsPolicy.inl").read_text(encoding="utf-8")
        ai_policy = (PRIVATE / "UnrealAssetToolSystemsAIPerceptionPolicy.inl").read_text(encoding="utf-8")
        dataflow_policy = (PRIVATE / "UnrealAssetToolSystemsDataflowChaosPolicy.inl").read_text(encoding="utf-8")
        uaf_policy = (PRIVATE / "UnrealAssetToolSystemsUAFPolicy.inl").read_text(encoding="utf-8")

        self.assertIn('SaveSystemsManifest(OutputDir, Counts, true, FString())', driver)
        self.assertIn('FFileHelper::SaveStringToFile', driver)
        self.assertIn('struct FSmartObjectSystemsFileHelperProxy', policy)
        self.assertIn('UpgradeSystemsManifestToSchema7(Path)', policy)
        self.assertIn('FSmartObjectSystemsFileHelperProxy::SaveStringToFile', ai_policy)
        self.assertIn('FAIPerceptionSystemsFileHelperProxy::SaveStringToFile', dataflow_policy)
        self.assertIn('FDataflowChaosSystemsFileHelperProxy::SaveStringToFile', uaf_policy)
        self.assertIn('#define FFileHelper ', scanner)
        self.assertLess(
            scanner.index('#define FFileHelper '),
            scanner.index('#include "UnrealAssetToolSystemsDriver.inl"'),
        )
        self.assertLess(
            scanner.index('#include "UnrealAssetToolSystemsDriver.inl"'),
            scanner.index('#undef FFileHelper'),
        )

    def test_schema7_publication_has_no_multicast_order_dependency(self) -> None:
        policy = (PRIVATE / "UnrealAssetToolSystemsSmartObjectsPolicy.inl").read_text(encoding="utf-8")
        ai_policy = (PRIVATE / "UnrealAssetToolSystemsAIPerceptionPolicy.inl").read_text(encoding="utf-8")
        dataflow_policy = (PRIVATE / "UnrealAssetToolSystemsDataflowChaosPolicy.inl").read_text(encoding="utf-8")
        uaf_policy = (PRIVATE / "UnrealAssetToolSystemsUAFPolicy.inl").read_text(encoding="utf-8")
        for text in ('GetOnPostEngineInit().AddStatic', 'OnEnginePreExit.AddStatic', 'OnPreExit.AddStatic', 'OnExit.AddStatic'):
            self.assertNotIn(text, policy)
            self.assertNotIn(text, ai_policy)
            self.assertNotIn(text, dataflow_policy)
            self.assertNotIn(text, uaf_policy)


if __name__ == "__main__":
    unittest.main()
