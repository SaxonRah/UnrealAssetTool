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

import uatool_core as core
import uatool_native as native


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


class NativeCppSchema1Test(unittest.TestCase):
    def test_schema1_manifest_and_counts_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            streams = {
                "native_modules.jsonl": [
                    {
                        "module_name": "hyperreality",
                        "build_cs": "Source/hyperreality/hyperreality.Build.cs",
                        "owner_kind": "project",
                        "owner_name": "hyperreality",
                        "loaded": True,
                    }
                ],
                "native_types.jsonl": [
                    {
                        "type_path": "/Script/hyperreality.HRThing",
                        "module_name": "hyperreality",
                        "kind": "class",
                    },
                    {
                        "type_path": "/Script/hyperreality.HRValue",
                        "module_name": "hyperreality",
                        "kind": "script_struct",
                    },
                ],
                "native_interfaces.jsonl": [],
                "native_functions.jsonl": [
                    {
                        "function_path": "/Script/hyperreality.HRThing.DoThing",
                        "module_name": "hyperreality",
                    }
                ],
                "native_function_parameters.jsonl": [
                    {
                        "function_path": "/Script/hyperreality.HRThing.DoThing",
                        "parameter_index": 0,
                        "parameter_name": "Value",
                        "parameter_kind": "input",
                    }
                ],
                "native_properties.jsonl": [
                    {
                        "owner_kind": "class",
                        "owner_path": "/Script/hyperreality.HRThing",
                        "property_name": "State",
                    }
                ],
                "native_enums.jsonl": [
                    {
                        "enum_path": "/Script/hyperreality.EHRState",
                        "module_name": "hyperreality",
                    }
                ],
                "native_enum_values.jsonl": [
                    {
                        "enum_path": "/Script/hyperreality.EHRState",
                        "value_index": 0,
                        "name": "Idle",
                    }
                ],
            }
            for filename, rows in streams.items():
                write_jsonl(root / filename, rows)

            manifest = {
                "schema_version": 1,
                "pass": native.PASS_NAME,
                "success": True,
                "error": "",
                "files": list(native.JSONL_FILES),
                "modules": ["hyperreality"],
                "counts": {
                    "modules": 1,
                    "loaded_modules": 1,
                    "types": 2,
                    "classes": 1,
                    "structs": 1,
                    "interfaces": 0,
                    "functions": 1,
                    "function_parameters": 1,
                    "properties": 1,
                    "enums": 1,
                    "enum_values": 1,
                },
            }
            (root / native.MANIFEST_FILE).write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            self.assertIsNone(native.validation_error(root))

    def test_count_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for filename in native.JSONL_FILES:
                write_jsonl(root / filename, [])
            manifest = {
                "schema_version": 1,
                "pass": native.PASS_NAME,
                "success": True,
                "files": list(native.JSONL_FILES),
                "modules": [],
                "counts": {
                    "modules": 1,
                    "loaded_modules": 0,
                    "types": 0,
                    "classes": 0,
                    "structs": 0,
                    "interfaces": 0,
                    "functions": 0,
                    "function_parameters": 0,
                    "properties": 0,
                    "enums": 0,
                    "enum_values": 0,
                },
            }
            (root / native.MANIFEST_FILE).write_text(
                json.dumps(manifest) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                native.validation_error(root),
                "native count mismatch for modules: manifest=1 actual=0",
            )

    def test_native_streams_are_portable_bundle_members(self) -> None:
        self.assertIn(native.MANIFEST_FILE, core.DEFAULT_BUNDLE_FILES)
        for filename in native.JSONL_FILES:
            self.assertIn(filename, core.DEFAULT_BUNDLE_FILES)

    def test_scanner_is_project_module_scoped_and_excludes_tool_stage(self) -> None:
        source = (
            ROOT
            / "Source"
            / "UnrealAssetTool"
            / "Private"
            / "UnrealAssetToolNativeScanner.cpp"
        ).read_text(encoding="utf-8")

        self.assertIn('FPaths::Combine(ProjectDir, TEXT("Source"))', source)
        self.assertIn('FPaths::Combine(ProjectDir, TEXT("Plugins"))', source)
        self.assertIn("IsUnder(BuildFile, ToolPluginDir)", source)
        self.assertIn('static const FString Prefix(TEXT("/Script/"))', source)
        self.assertIn("Modules.Contains(ModuleName)", source)
        self.assertNotIn("GetDerivedClasses(", source)

    def test_structural_pass_invokes_native_scanner_without_extra_commandlet(self) -> None:
        source = (
            ROOT
            / "Source"
            / "UnrealAssetTool"
            / "Private"
            / "UnrealAssetToolCommandlet.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn("UnrealAssetToolNative::Scan(", source)
        self.assertIn('FParse::Param(*Params, TEXT("NativeOnly"))', source)
        self.assertIn("native-only capture complete", source)

        launcher = (SCRIPTS / "uatool_core.py").read_text(encoding="utf-8")
        self.assertIn("native C++ pass incomplete", launcher)
        self.assertIn('sub.add_parser(\n        "native-capture"', launcher)
        self.assertIn('"-NativeOnly"', launcher)
        self.assertNotIn("-run=UnrealAssetToolNative", launcher)


if __name__ == "__main__":
    unittest.main()
