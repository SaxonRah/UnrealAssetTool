from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "Source" / "UnrealAssetTool" / "Private" / "UnrealAssetToolAIPerceptionCommandlet.cpp"


class AIPerceptionUE58CompileContractTest(unittest.TestCase):
    def test_blueprint_generated_class_is_explicitly_unwrapped(self) -> None:
        source = SOURCE.read_text(encoding="utf-8")
        self.assertIn(
            "UClass* GeneratedClass = Blueprint ? Blueprint->GeneratedClass.Get() : Cast<UClass>(AssetObject);",
            source,
        )
        self.assertNotIn(
            "UClass* GeneratedClass = Blueprint ? Blueprint->GeneratedClass : Cast<UClass>(AssetObject);",
            source,
        )


if __name__ == "__main__":
    unittest.main()
