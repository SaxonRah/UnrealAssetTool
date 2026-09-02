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

        self.assertIn('SaveSystemsManifest(OutputDir, Counts, true, FString())', driver)
        self.assertIn('FFileHelper::SaveStringToFile', driver)
        self.assertIn('struct FSmartObjectSystemsFileHelperProxy', policy)
        self.assertIn('UpgradeSystemsManifestToSchema7(Path)', policy)
        self.assertIn('#define FFileHelper FSmartObjectSystemsFileHelperProxy', scanner)
        self.assertLess(
            scanner.index('#define FFileHelper FSmartObjectSystemsFileHelperProxy'),
            scanner.index('#include "UnrealAssetToolSystemsDriver.inl"'),
        )
        self.assertLess(
            scanner.index('#include "UnrealAssetToolSystemsDriver.inl"'),
            scanner.index('#undef FFileHelper'),
        )

    def test_schema7_publication_has_no_multicast_order_dependency(self) -> None:
        policy = (PRIVATE / "UnrealAssetToolSystemsSmartObjectsPolicy.inl").read_text(encoding="utf-8")
        self.assertNotIn('GetOnPostEngineInit().AddStatic', policy)
        self.assertNotIn('OnEnginePreExit.AddStatic', policy)
        self.assertNotIn('OnPreExit.AddStatic', policy)
        self.assertNotIn('OnExit.AddStatic', policy)


if __name__ == "__main__":
    unittest.main()
