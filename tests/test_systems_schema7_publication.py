from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = ROOT / "Source/UnrealAssetTool/Private"


class SystemsSchema7PublicationTest(unittest.TestCase):
    def test_schema7_promotion_runs_after_shared_driver_scan_on_post_engine_init(self) -> None:
        scanner = (PRIVATE / "UnrealAssetToolSystemsScanner.cpp").read_text(encoding="utf-8")
        driver = (PRIVATE / "UnrealAssetToolSystemsDriver.inl").read_text(encoding="utf-8")
        finalize = (PRIVATE / "UnrealAssetToolSystemsFinalize.inl").read_text(encoding="utf-8")
        policy = (PRIVATE / "UnrealAssetToolSystemsSmartObjectsPolicy.inl").read_text(encoding="utf-8")

        self.assertLess(
            scanner.index('#include "UnrealAssetToolSystemsDriver.inl"'),
            scanner.index('#include "UnrealAssetToolSystemsFinalize.inl"'),
        )
        self.assertIn(
            'FCoreDelegates::GetOnPostEngineInit().AddStatic(&OnPostEngineInit);',
            driver,
        )
        self.assertIn(
            'FCoreDelegates::GetOnPostEngineInit().AddStatic(&FinalizeSmartObjectSchema7Manifest);',
            finalize,
        )
        self.assertIn('SaveSystemsManifest(OutputDir, Counts, true, FString())', driver)
        self.assertIn('UpgradeSystemsManifestToSchema7()', policy)
        self.assertIn('Root->SetNumberField(TEXT("schema_version"), 7)', policy)

    def test_schema7_publication_does_not_depend_only_on_pre_exit(self) -> None:
        finalize = (PRIVATE / "UnrealAssetToolSystemsFinalize.inl").read_text(encoding="utf-8")
        self.assertIn('GetOnPostEngineInit()', finalize)
        self.assertIn('FinalizeSmartObjectSchema7Manifest', finalize)


if __name__ == "__main__":
    unittest.main()
