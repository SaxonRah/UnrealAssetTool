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
        self.assertIn('#define FFileHelper FSmartObjectSystemsFileHelperProxy', scanner)
        self.assertLess(
            scanner.index('#define FFileHelper FSmartObjectSystemsFileHelperProxy'),
            scanner.index('#include "UnrealAssetToolSystemsDriver.inl"'),
        )
        self.assertLess(
            scanner.index('#include "UnrealAssetToolSystemsDriver.inl"'),
            scanner.index('#undef FFileHelper'),
        )

        self.assertIn('struct FSmartObjectSystemsFileHelperProxy', policy)
        self.assertIn('FFileHelper::SaveStringToFile(String, Filename, EncodingOptions)', policy)
        self.assertIn('return UpgradeSystemsManifestToSchema7(Path);', policy)
        self.assertIn('Root->SetNumberField(TEXT("schema_version"), 7)', policy)
        self.assertIn('smartobject_definitions.jsonl', policy)
        self.assertIn('smartobject_behavior_properties.jsonl', policy)

    def test_schema7_publication_has_no_multicast_order_dependency(self) -> None:
        policy = (PRIVATE / "UnrealAssetToolSystemsSmartObjectsPolicy.inl").read_text(encoding="utf-8")
        finalize = (PRIVATE / "UnrealAssetToolSystemsFinalize.inl").read_text(encoding="utf-8")

        self.assertNotIn('FinalizeSmartObjectSchema7Manifest', policy)
        self.assertNotIn('OnEnginePreExit.AddStatic(&FinalizeSmartObjectSchema7Manifest)', policy)
        self.assertNotIn('GetOnPostEngineInit().AddStatic(&FinalizeSmartObjectSchema7Manifest)', finalize)
        self.assertIn('OnEnginePreExit.AddStatic(&FinalizeSystemsOnlyWriterBuffers)', finalize)


if __name__ == "__main__":
    unittest.main()
