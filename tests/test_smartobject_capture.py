from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_smartobject_capture as capture


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


class SmartObjectCaptureTest(unittest.TestCase):
    def _fixture(self, output: Path, *, runtime_state: bool = False) -> None:
        definition = "/Game/AI/SO_Def.SO_Def"
        behavior = definition + ":Behavior_0"
        assets = [{
            "asset_path": definition,
            "package_name": "/Game/AI/SO_Def",
            "asset_name": "SO_Def",
            "asset_class": "/Script/SmartObjectsModule.SmartObjectDefinition",
            "loaded_object_class": "/Script/SmartObjectsModule.SmartObjectDefinition",
            "loaded": True,
            "is_definition": True,
        }]
        objects = [
            {
                "source_path": definition,
                "object_path": definition,
                "object_kind": "definition_asset",
                "object_class": "/Script/SmartObjectsModule.SmartObjectDefinition",
                "outer_path": "/Game/AI/SO_Def",
                "native_class": True,
            },
            {
                "source_path": definition,
                "object_path": behavior,
                "object_kind": "nested_object",
                "object_class": "/Script/SmartObjectsModule.SmartObjectStateTreeBehaviorDefinition",
                "outer_path": definition,
                "native_class": True,
            },
        ]
        properties = [
            {
                "source_path": definition,
                "owner_path": definition,
                "owner_kind": "definition_asset",
                "owner_class": "/Script/SmartObjectsModule.SmartObjectDefinition",
                "declaring_type": "/Script/SmartObjectsModule.SmartObjectDefinition",
                "root_property": "Slots",
                "property_name": "Slots",
                "property_path": "Slots",
                "property_type": "ArrayProperty",
                "cpp_type": "TArray<FSmartObjectSlotDefinition>",
                "container_kind": "array",
                "depth": 0,
                "element_count": 1,
                "value": "((...))",
                "truncated": False,
            },
            {
                "source_path": definition,
                "owner_path": definition,
                "owner_kind": "definition_asset",
                "owner_class": "/Script/SmartObjectsModule.SmartObjectDefinition",
                "declaring_type": "/Script/SmartObjectsModule.SmartObjectSlotDefinition",
                "root_property": "Slots",
                "property_name": "BehaviorDefinitions",
                "property_path": "Slots[0].BehaviorDefinitions",
                "property_type": "ArrayProperty",
                "cpp_type": "TArray<TObjectPtr<USmartObjectBehaviorDefinition>>",
                "container_kind": "array",
                "depth": 2,
                "element_count": 1,
                "value": "(...)\n",
                "truncated": False,
            },
            {
                "source_path": definition,
                "owner_path": definition,
                "owner_kind": "definition_asset",
                "owner_class": "/Script/SmartObjectsModule.SmartObjectDefinition",
                "declaring_type": "/Script/SmartObjectsModule.SmartObjectSlotDefinition",
                "root_property": "Slots",
                "property_name": "BehaviorDefinitions",
                "property_path": "Slots[0].BehaviorDefinitions[0]",
                "property_type": "ObjectProperty",
                "cpp_type": "TObjectPtr<USmartObjectBehaviorDefinition>",
                "container_kind": "object",
                "depth": 3,
                "value": behavior,
                "truncated": False,
            },
            {
                "source_path": definition,
                "owner_path": behavior,
                "owner_kind": "nested_object",
                "owner_class": "/Script/SmartObjectsModule.SmartObjectStateTreeBehaviorDefinition",
                "declaring_type": "/Script/SmartObjectsModule.SmartObjectStateTreeBehaviorDefinition",
                "root_property": "StateTreeReference",
                "property_name": "StateTreeReference",
                "property_path": "StateTreeReference",
                "property_type": "StructProperty",
                "cpp_type": "FStateTreeReference",
                "container_kind": "struct",
                "depth": 0,
                "value": "(...)\n",
                "truncated": False,
            },
        ]
        references = [{
            "source_path": definition,
            "owner_path": definition,
            "owner_kind": "definition_asset",
            "owner_class": "/Script/SmartObjectsModule.SmartObjectDefinition",
            "root_property": "Slots",
            "property_path": "Slots[0].BehaviorDefinitions[0]",
            "reference_kind": "hard_object",
            "target_path": behavior,
            "target_class": "/Script/SmartObjectsModule.SmartObjectStateTreeBehaviorDefinition",
        }]
        write_jsonl(output / "smartobject_assets.jsonl", assets)
        write_jsonl(output / "smartobject_objects.jsonl", objects)
        write_jsonl(output / "smartobject_properties.jsonl", properties)
        write_jsonl(output / "smartobject_references.jsonl", references)
        (output / "smartobject_capture_manifest.json").write_text(
            json.dumps({
                "schema_version": 1,
                "schema_name": "smartobject_capture",
                "pass": "UnrealAssetToolSmartObject",
                "success": True,
                "error": "",
                "diagnostic_only": True,
                "semantic_promotion": False,
                "runtime_state_captured": runtime_state,
                "counts": {
                    "assets_considered": 20,
                    "candidate_assets": 1,
                    "loaded_assets": 1,
                    "definition_assets": 1,
                    "smartobject_objects": 2,
                    "nested_objects": 1,
                    "smartobject_properties": 4,
                    "smartobject_references": 1,
                    "truncated_properties": 0,
                    "property_depth_limit_hits": 0,
                    "property_row_limit_hits": 0,
                    "container_element_limit_hits": 0,
                },
            }, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )

    def test_validate_and_report_prove_recursive_slot_and_behavior_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            self._fixture(output)
            manifest = capture._validate_capture(output)
            report = capture._semantic_report(output, manifest)
            self.assertIn("definition_assets: 1", report)
            self.assertIn("slot_property_rows: 3", report)
            self.assertIn("behavior_objects: 1", report)
            self.assertIn("behavior_references: 1", report)
            self.assertIn("PASS: recursive definition reflection exposed Smart Object slot structure.", report)
            self.assertIn("PASS: behavior-definition evidence is present", report)
            self.assertIn("runtime claims, occupancy, reservations and subsystem handles were not captured", report)

    def test_runtime_state_claim_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td)
            self._fixture(output, runtime_state=True)
            with self.assertRaisesRegex(RuntimeError, "runtime_state_captured=false"):
                capture._validate_capture(output)

    def test_archive_contains_complete_raw_capture_contract(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            output = root / "capture"
            output.mkdir()
            self._fixture(output)
            archive = root / "capture.zip"
            capture._write_archive(output, archive)
            self.assertTrue(archive.is_file())
            import zipfile
            with zipfile.ZipFile(archive) as bundle:
                self.assertEqual(set(bundle.namelist()), set(capture.CAPTURE_FILES))

    def test_install_preserves_unrelated_runtime_commands(self) -> None:
        runtime = types.SimpleNamespace(main=lambda: 17)
        core = types.SimpleNamespace()
        capture.install(runtime, core)
        self.assertTrue(runtime._smartobject_capture_installed)
        with mock.patch.object(sys, "argv", ["uatool.py", "query"]):
            self.assertEqual(runtime.main(), 17)

    def test_canonical_facade_wires_capture_and_build_has_no_smartobjects_dependency(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_smartobject_capture as _smartobject_capture", facade)
        self.assertIn("_smartobject_capture.install(_runtime)", facade)
        build_cs = (ROOT / "Source" / "UnrealAssetTool" / "UnrealAssetTool.Build.cs").read_text(encoding="utf-8")
        self.assertNotIn('"SmartObjectsModule"', build_cs)
        source = (
            ROOT / "Source" / "UnrealAssetTool" / "Private" / "UnrealAssetToolSmartObjectCommandlet.cpp"
        ).read_text(encoding="utf-8")
        self.assertNotIn("SmartObjectDefinition.h", source)
        self.assertIn("WalkPropertyValue", source)
        self.assertIn("GetObjectsWithOuter", source)


if __name__ == "__main__":
    unittest.main()
