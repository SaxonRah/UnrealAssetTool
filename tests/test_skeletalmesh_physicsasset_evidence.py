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

import uatool_skeletalmesh_physicsasset_evidence as evidence


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(value, separators=(",", ":")) + "\n" for value in values),
        encoding="utf-8",
    )


def rows(path: Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            yield json.loads(line)


class SkeletalMeshPhysicsAssetEvidenceTest(unittest.TestCase):
    def test_exact_identity_and_consumers_do_not_imply_owned_internals(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mesh = "/Game/Characters/SK_Test.SK_Test"
            physics = "/Game/Characters/PHYS_Test.PHYS_Test"
            write_jsonl(root / "assets.jsonl", [
                {"object_path": mesh, "class_path": evidence.SKELETAL_MESH_CLASS},
                {"object_path": physics, "class_path": evidence.PHYSICS_ASSET_CLASS},
            ])
            write_jsonl(root / "animation_assets.jsonl", [])
            write_jsonl(root / "animation_optional_assets.jsonl", [])
            write_jsonl(root / "animation_properties.jsonl", [])
            write_jsonl(root / "animation_references.jsonl", [
                {
                    "asset_path": "/Game/Animation/PS_Test.PS_Test",
                    "owner_path": "/Game/Animation/PS_Test.PS_Test",
                    "property_path": "PreviewMesh",
                    "target_path": mesh,
                    "target_class": evidence.SKELETAL_MESH_CLASS,
                },
                {
                    "asset_path": "/Game/Animation/ABP_Test.ABP_Test",
                    "owner_path": "/Game/Animation/ABP_Test.ABP_Test",
                    "property_path": "OverridePhysicsAsset",
                    "target_path": physics,
                    "target_class": evidence.PHYSICS_ASSET_CLASS,
                },
            ])

            report = evidence.build_report(root, rows, include_source=False)
            proof = report["proof"]
            self.assertEqual(proof["unique_skeletal_mesh_assets"], 1)
            self.assertEqual(proof["unique_physics_asset_assets"], 1)
            self.assertEqual(proof["skeletal_mesh_exact_incoming_reference_rows"], 1)
            self.assertEqual(proof["physics_asset_exact_incoming_reference_rows"], 1)
            self.assertEqual(proof["skeletal_mesh_owned_animation_property_rows"], 0)
            self.assertEqual(proof["physics_asset_owned_animation_property_rows"], 0)
            self.assertEqual(proof["skeletal_mesh_animation_classified_assets"], 0)
            self.assertEqual(proof["physics_asset_animation_classified_assets"], 0)
            self.assertTrue(any("does not classify/load" in gap for gap in report["gaps"]))
            self.assertTrue(any("focused native load/capture" in gap for gap in report["gaps"]))

    def test_owned_animation_rows_are_counted_only_for_exact_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mesh = "/Game/Characters/SK_Test.SK_Test"
            physics = "/Game/Characters/PHYS_Test.PHYS_Test"
            write_jsonl(root / "assets.jsonl", [
                {"object_path": mesh, "class_path": evidence.SKELETAL_MESH_CLASS},
                {"object_path": physics, "class_path": evidence.PHYSICS_ASSET_CLASS},
            ])
            write_jsonl(root / "animation_assets.jsonl", [
                {"animation_path": mesh, "class_path": evidence.SKELETAL_MESH_CLASS},
                {"animation_path": physics, "class_path": evidence.PHYSICS_ASSET_CLASS},
            ])
            write_jsonl(root / "animation_properties.jsonl", [
                {"asset_path": mesh, "owner_path": mesh, "property_name": "LODInfo", "value": "(...)"},
                {"asset_path": physics, "owner_path": physics, "property_name": "SkeletalBodySetups", "value": "(...)"},
                {"asset_path": "/Game/Other.Other", "owner_path": "/Game/Other.Other", "property_name": "PhysicsAsset", "value": physics},
            ])
            write_jsonl(root / "animation_references.jsonl", [])

            report = evidence.build_report(root, rows, include_source=False)
            proof = report["proof"]
            self.assertEqual(proof["skeletal_mesh_animation_classified_assets"], 1)
            self.assertEqual(proof["physics_asset_animation_classified_assets"], 1)
            self.assertEqual(proof["skeletal_mesh_owned_animation_property_rows"], 1)
            self.assertEqual(proof["physics_asset_owned_animation_property_rows"], 1)
            self.assertEqual(proof["lodinfo_owners"], 1)
            self.assertEqual(proof["skeletalbodysetup_owners"], 1)

    def test_facade_installs_read_only_command(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_skeletalmesh_physicsasset_evidence as _skeletalmesh_physicsasset_evidence", facade)
        self.assertIn("_skeletalmesh_physicsasset_evidence.install(_runtime)", facade)
        source = (SCRIPTS / "uatool_skeletalmesh_physicsasset_evidence.py").read_text(encoding="utf-8")
        self.assertIn('SKELETAL_MESH_CLASS = "/Script/Engine.SkeletalMesh"', source)
        self.assertIn('PHYSICS_ASSET_CLASS = "/Script/Engine.PhysicsAsset"', source)
        self.assertIn('"diagnostic_only": True', source)
        self.assertIn('"schema_promotion": False', source)
        self.assertIn('"runtime_state_captured": False', source)


if __name__ == "__main__":
    unittest.main()
