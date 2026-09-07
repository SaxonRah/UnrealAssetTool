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

import uatool_native as reflected_native
import uatool_native_ast as native_ast
import uatool_native_join as native_join


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
        newline="\n",
    )


def make_reflected(root: Path) -> None:
    streams = {
        "native_modules.jsonl": [
            {
                "module_name": "HRRAI",
                "build_cs": "Plugins/HR_RAI/Source/HRRAI/HRRAI.Build.cs",
                "owner_kind": "project_plugin",
                "owner_name": "HR_RAI",
                "loaded": True,
            }
        ],
        "native_types.jsonl": [
            {
                "type_path": "/Script/HRRAI.HRThing",
                "module_name": "HRRAI",
                "kind": "class",
                "name": "HRThing",
                "cpp_name": "UHRThing",
            }
        ],
        "native_interfaces.jsonl": [],
        "native_functions.jsonl": [
            {
                "function_path": "/Script/HRRAI.HRThing.DoThing",
                "module_name": "HRRAI",
                "owner_path": "/Script/HRRAI.HRThing",
                "owner_kind": "class",
                "name": "DoThing",
                "parameter_count": 1,
            }
        ],
        "native_function_parameters.jsonl": [
            {
                "function_path": "/Script/HRRAI.HRThing.DoThing",
                "parameter_index": 0,
                "parameter_name": "Value",
                "parameter_kind": "input",
                "cpp_type": "FString",
                "const_parameter": True,
                "reference_parameter": True,
            }
        ],
        "native_properties.jsonl": [],
        "native_enums.jsonl": [],
        "native_enum_values.jsonl": [],
    }
    for filename, rows in streams.items():
        write_jsonl(root / filename, rows)

    manifest = {
        "schema_version": 1,
        "pass": reflected_native.PASS_NAME,
        "success": True,
        "error": "",
        "files": list(reflected_native.JSONL_FILES),
        "modules": ["HRRAI"],
        "counts": {
            "modules": 1,
            "loaded_modules": 1,
            "types": 1,
            "classes": 1,
            "structs": 0,
            "interfaces": 0,
            "functions": 1,
            "function_parameters": 1,
            "properties": 0,
            "enums": 0,
            "enum_values": 0,
        },
    }
    (root / reflected_native.MANIFEST_FILE).write_text(
        json.dumps(manifest) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def make_ast(
    root: Path,
    *,
    method_type: str = "const FString &",
    add_ambiguous_method: bool = False,
    wrong_module_record: bool = False,
) -> None:
    record_path = (
        "Plugins/Other/Source/HRRAI/Public/HRThing.h"
        if wrong_module_record
        else "Plugins/HR_RAI/Source/HRRAI/Public/HRThing.h"
    )
    symbols = [
        {
            "symbol_id": "type-symbol",
            "occurrence_id": "type-occurrence",
            "clang_usr": "c:@S@UHRThing",
            "kind": "record",
            "language": "cpp",
            "name": "UHRThing",
            "qualified_name": "UHRThing",
            "source_path": record_path,
            "line": 10,
            "offset": 100,
            "is_definition": True,
            "compatibility_overrides": [],
        },
        {
            "symbol_id": "method-symbol",
            "occurrence_id": "method-occurrence",
            "clang_usr": "c:@S@UHRThing@F@DoThing#&1$@S@FString#",
            "kind": "method",
            "language": "cpp",
            "name": "DoThing",
            "qualified_name": "UHRThing::DoThing",
            "source_path": "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
            "line": 25,
            "offset": 300,
            "is_definition": True,
            "compatibility_overrides": ["-Wno-invalid-constexpr"],
        },
    ]
    parameters = [
        {
            "function_symbol_id": "method-symbol",
            "function_occurrence_id": "method-occurrence",
            "parameter_index": 0,
            "name": "Value",
            "type_spelling": method_type,
            "source_path": "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
            "translation_unit": "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
            "language": "cpp",
        }
    ]
    if add_ambiguous_method:
        symbols.append({
            "symbol_id": "method-symbol-2",
            "occurrence_id": "method-occurrence-2",
            "clang_usr": "c:@S@UHRThing@F@DoThing#ambiguous",
            "kind": "method",
            "language": "cpp",
            "name": "DoThing",
            "qualified_name": "UHRThing::DoThing",
            "source_path": "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
            "line": 35,
            "offset": 500,
            "is_definition": True,
            "compatibility_overrides": [],
        })
        parameters.append({
            "function_symbol_id": "method-symbol-2",
            "function_occurrence_id": "method-occurrence-2",
            "parameter_index": 0,
            "name": "Value",
            "type_spelling": method_type,
            "source_path": "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
            "translation_unit": "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
            "language": "cpp",
        })

    write_jsonl(root / native_ast.SYMBOLS, symbols)
    write_jsonl(root / native_ast.PARAMETERS, parameters)
    write_jsonl(root / native_ast.CALLS, [])
    (root / native_ast.MANIFEST).write_text(
        json.dumps({
            "schema_version": 1,
            "pass": "UnrealAssetToolNativeAST",
            "success": True,
            "error": "",
            "evidence": "libclang_cursor_all_translation_units",
            "normalized_counts": {
                "symbols": len(symbols),
                "parameters": len(parameters),
                "calls": 0,
            },
        }) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class NativeJoinSchema1Test(unittest.TestCase):
    def test_exact_type_and_function_join(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reflected = root / "reflected"
            ast = root / "ast"
            output = root / "join"
            reflected.mkdir()
            ast.mkdir()
            make_reflected(reflected)
            make_ast(ast)

            manifest = native_join.capture(reflected, ast, output)
            self.assertTrue(manifest["success"])
            self.assertEqual(manifest["counts"]["joined_types"], 1)
            self.assertEqual(manifest["counts"]["joined_functions"], 1)
            self.assertIsNone(native_join.validation_error(output))

            type_rows = native_join._rows(output / native_join.TYPE_JOINS)
            function_rows = native_join._rows(
                output / native_join.FUNCTION_JOINS
            )
            self.assertEqual(type_rows[0]["source_clang_usr"], "c:@S@UHRThing")
            self.assertEqual(
                function_rows[0]["reflected_parameter_signature"],
                ["const FString&"],
            )
            self.assertEqual(
                function_rows[0]["accepted_source_parameter_types"],
                [["const FString&"]],
            )
            self.assertEqual(
                function_rows[0]["source_parameter_signature"],
                ["const FString&"],
            )
            self.assertEqual(
                function_rows[0]["compatibility_overrides"],
                ["-Wno-invalid-constexpr"],
            )

    def test_validation_rejects_pre_projection_ruleset_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reflected = root / "reflected"
            ast = root / "ast"
            output = root / "join"
            reflected.mkdir()
            ast.mkdir()
            make_reflected(reflected)
            make_ast(ast)

            native_join.capture(reflected, ast, output)
            manifest_path = output / native_join.MANIFEST
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            manifest.pop("ruleset", None)
            manifest["proof_policy"]["functions"] = (
                "proven owner type + exact qualified function name + "
                "exact parameter signature + "
                "single libclang USR-backed semantic identity"
            )
            manifest_path.write_text(
                json.dumps(manifest) + "\n",
                encoding="utf-8",
                newline="\n",
            )

            self.assertEqual(
                native_join.validation_error(output),
                (
                    "native join ruleset is stale or missing; regenerate "
                    "with the current uatool native-join from the retained "
                    "reflected and compiler inputs"
                ),
            )

    def test_module_scope_prevents_same_name_join(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reflected = root / "reflected"
            ast = root / "ast"
            output = root / "join"
            reflected.mkdir()
            ast.mkdir()
            make_reflected(reflected)
            make_ast(ast, wrong_module_record=True)

            manifest = native_join.capture(reflected, ast, output)
            self.assertEqual(manifest["counts"]["joined_types"], 0)
            self.assertEqual(manifest["counts"]["unmatched_types"], 1)
            self.assertEqual(manifest["counts"]["joined_functions"], 0)

    def test_out_parameter_projects_to_reference(self) -> None:
        row = {
            "cpp_type": "FString",
            "property_class": "StrProperty",
            "parameter_kind": "out",
            "const_parameter": False,
            "reference_parameter": False,
        }
        self.assertEqual(
            native_join._reflected_parameter_source_types(row),
            ["FString&"],
        )

    def test_input_fstring_models_reflection_erasure_without_guessing(self) -> None:
        row = {
            "cpp_type": "FString",
            "property_class": "StrProperty",
            "parameter_kind": "input",
            "const_parameter": False,
            "reference_parameter": False,
        }
        accepted = native_join._reflected_parameter_source_types(row)
        self.assertEqual(accepted, ["FString", "const FString&"])
        self.assertTrue(
            native_join._signature_matches_projection(
                ["const FString&"],
                [accepted],
            )
        )
        self.assertTrue(
            native_join._signature_matches_projection(
                ["FString"],
                [accepted],
            )
        )

    def test_signature_mismatch_is_not_joined(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reflected = root / "reflected"
            ast = root / "ast"
            output = root / "join"
            reflected.mkdir()
            ast.mkdir()
            make_reflected(reflected)
            make_ast(ast, method_type="int32")

            manifest = native_join.capture(reflected, ast, output)
            self.assertEqual(manifest["counts"]["joined_types"], 1)
            self.assertEqual(manifest["counts"]["joined_functions"], 0)
            self.assertEqual(manifest["counts"]["unmatched_functions"], 1)

    def test_ambiguous_exact_overload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reflected = root / "reflected"
            ast = root / "ast"
            output = root / "join"
            reflected.mkdir()
            ast.mkdir()
            make_reflected(reflected)
            make_ast(ast, add_ambiguous_method=True)

            manifest = native_join.capture(reflected, ast, output)
            self.assertEqual(manifest["counts"]["joined_functions"], 0)
            self.assertEqual(manifest["counts"]["ambiguous_functions"], 1)

    def test_cpp_type_normalization_is_conservative(self) -> None:
        self.assertEqual(
            native_join._normalize_cpp_type(" const  FString & "),
            "const FString&",
        )
        self.assertEqual(
            native_join._normalize_cpp_type(
                "TArray< struct FHRThing * >"
            ),
            "TArray<FHRThing*>",
        )

    def test_canonical_cli_exposes_native_join(self) -> None:
        source = (SCRIPTS / "uatool.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_native_join as native_join", source)
        self.assertIn('sys.argv[1] == "native-join"', source)
        self.assertIn("native_join.capture(", source)
        self.assertIn("native_join.validation_error(output)", source)


if __name__ == "__main__":
    unittest.main()
