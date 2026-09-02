from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolGASCommandlet.cpp"


class GASCandidateSelectionTest(unittest.TestCase):
    def test_candidate_text_uses_class_metadata_only(self) -> None:
        text = CPP.read_text(encoding="utf-8")
        start = text.index("static FString CandidateText")
        end = text.index("static FString ExportProperty", start)
        candidate = text[start:end]
        self.assertIn("Asset.AssetClassPath.ToString()", candidate)
        self.assertIn('AssetTag(Asset, TEXT("ParentClass"))', candidate)
        self.assertIn('AssetTag(Asset, TEXT("NativeParentClass"))', candidate)
        self.assertIn('AssetTag(Asset, TEXT("GeneratedClass"))', candidate)
        self.assertNotIn("Asset.GetSoftObjectPath()", candidate)
        self.assertNotIn("Asset.PackageName", candidate)
        self.assertNotIn("Asset.AssetName", candidate)

    def test_bare_attribute_set_is_not_a_candidate_anchor(self) -> None:
        text = CPP.read_text(encoding="utf-8")
        start = text.index("static bool ContainsCandidateAnchor")
        end = text.index("static FString AssetTag", start)
        anchors = text[start:end]
        self.assertNotIn('TEXT("attributeset")', anchors)
        self.assertIn('TEXT("/script/gameplayabilities")', anchors)
        self.assertIn('TEXT("lyraattributeset")', anchors)

    def test_metadata_attribute_classification_requires_gas_or_lyra_anchor(self) -> None:
        text = CPP.read_text(encoding="utf-8")
        start = text.index("static FString ClassifyMetadata")
        end = text.index("static bool ContainsCandidateAnchor", start)
        classifier = text[start:end]
        self.assertNotIn('Lower.Contains(TEXT("attributeset"))', classifier)
        self.assertIn('Lower.Contains(TEXT("/script/gameplayabilities.attributeset"))', classifier)
        self.assertIn('Lower.Contains(TEXT("lyraattributeset"))', classifier)


if __name__ == "__main__":
    unittest.main()
