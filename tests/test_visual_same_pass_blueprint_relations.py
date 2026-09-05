import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_core as core


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


class VisualSamePassBlueprintRelationsTests(unittest.TestCase):
    def test_clean_derive_uses_same_pass_blueprint_relations(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            blueprint = "/Game/Test/BP_Test.BP_Test"
            material = "/Game/Test/M_Test.M_Test"

            write_jsonl(output / "assets.jsonl", [
                {
                    "object_path": blueprint,
                    "package_name": "/Game/Test/BP_Test",
                    "class_path": "/Script/Engine.Blueprint",
                },
                {
                    "object_path": material,
                    "package_name": "/Game/Test/M_Test",
                    "class_path": "/Script/Engine.Material",
                },
            ])
            write_jsonl(output / "blueprints.jsonl", [
                {
                    "object_path": blueprint,
                    "generated_class": blueprint + "_C",
                    "variables": [],
                    "components": [],
                    "implemented_interfaces": [],
                },
            ])
            write_jsonl(output / "blueprint_state_values.jsonl", [
                {
                    "blueprint_path": blueprint,
                    "owner_kind": "class_default",
                    "owner_id": blueprint + "_C",
                    "property_path": "Brush.ResourceObject",
                    "referenced_object_path": material,
                    "referenced_object_class": "/Script/Engine.Material",
                },
            ])

            # Reproduce the clean-output condition that exposed #118: there is
            # no useful previous derived Blueprint relation file to consume.
            write_jsonl(output / "blueprint_relations.jsonl", [])

            counts = core.derive_output(output)

            blueprint_relations = list(core.iter_jsonl(output / "blueprint_relations.jsonl"))
            self.assertTrue(any(
                row.get("blueprint_path") == blueprint
                and row.get("relation") == "state_references_object"
                and row.get("target") == material
                for row in blueprint_relations
            ))

            visual_relations = list(core.iter_jsonl(output / "visual_relations.jsonl"))
            self.assertEqual(counts["visual_relations"], len(visual_relations))
            self.assertTrue(any(
                row.get("system") == "blueprint"
                and row.get("asset_path") == blueprint
                and row.get("relation") == "uses_material"
                and row.get("target") == material
                for row in visual_relations
            ))


if __name__ == "__main__":
    unittest.main()
