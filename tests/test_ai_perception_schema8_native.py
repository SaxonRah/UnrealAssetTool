from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AIPerceptionSchema8NativeTest(unittest.TestCase):
    def test_native_scanner_is_reflection_only_and_synchronously_published(self) -> None:
        scanner = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp").read_text(encoding="utf-8")
        native = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsAIPerception.inl").read_text(encoding="utf-8")
        policy = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsAIPerceptionPolicy.inl").read_text(encoding="utf-8")
        build = (ROOT / "Source/UnrealAssetTool/UnrealAssetTool.Build.cs").read_text(encoding="utf-8")

        self.assertIn('#include "UnrealAssetToolSystemsAIPerception.inl"', scanner)
        self.assertIn('#include "UnrealAssetToolSystemsAIPerceptionPolicy.inl"', scanner)
        self.assertIn('#include "UObject/UObjectGlobals.h"', scanner)
        self.assertIn("#define ScanGASProjectModel ScanGASSmartObjectsAndAIPerceptionProjectModels", scanner)
        self.assertIn("#define FFileHelper FAIPerceptionSystemsFileHelperProxy", scanner)
        self.assertIn("#undef FFileHelper", scanner)
        self.assertIn("#undef ScanGASProjectModel", scanner)

        self.assertIn("Blueprint->GeneratedClass.Get()", native)
        self.assertIn('ClassInheritsName(Class, TEXT("AIPerceptionComponent"))', native)
        self.assertIn('ClassInheritsName(Class, TEXT("AIPerceptionStimuliSourceComponent"))', native)
        self.assertIn('ClassInheritsName(Config->GetClass(), TEXT("AISenseConfig"))', native)
        self.assertIn("differs_from_class_default", native)
        self.assertIn("Property->Identical", native)
        self.assertIn("RegisterAsSourceForSenses", native)
        self.assertIn("SenseRow->SetBoolField(TEXT(\"is_null\"), Sense == nullptr)", native)

        # The real ContentExamples schema-8 gate proved that FAssetData::GetAsset()
        # in the broad systems pass did not rediscover the two already-proven
        # Blueprint templates. The full pass now uses the exact-path loading
        # primitive that succeeded in the focused commandlet and publishes
        # discovery-stage counters for future diagnosis.
        self.assertIn("ScanAIPerceptionProjectModelExactLoad", policy)
        self.assertIn("StaticLoadObject(UObject::StaticClass(), nullptr, *BlueprintPath)", policy)
        self.assertIn("UBlueprint::StaticClass()->GetClassPathName()", policy)
        for counter in (
            "ai_perception_blueprint_candidates",
            "ai_perception_scoped_blueprint_candidates",
            "ai_perception_loaded_blueprints",
            "ai_perception_generated_classes",
            "ai_perception_scanned_blueprints",
        ):
            self.assertIn(f'TEXT("{counter}")', policy)

        self.assertIn("FSmartObjectSystemsFileHelperProxy::SaveStringToFile", policy)
        self.assertIn("UpgradeSystemsManifestToSchema8", policy)
        self.assertIn('TEXT("ai_perception_truncated_properties")', policy)
        self.assertIn('TEXT("ai_perception_property_depth_limit_hits")', policy)
        self.assertIn('TEXT("ai_perception_property_row_limit_hits")', policy)
        self.assertIn('TEXT("ai_perception_container_element_limit_hits")', policy)
        self.assertNotIn("OnEnginePreExit", policy)
        self.assertNotIn("OnExit", policy)

        self.assertNotIn('"AIModule"', build)
        self.assertNotIn("Perception/AIPerception", native)
        self.assertNotIn("AISenseConfig_", native)


if __name__ == "__main__":
    unittest.main()
