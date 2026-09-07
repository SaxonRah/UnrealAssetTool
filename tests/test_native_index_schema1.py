from __future__ import annotations

import contextlib
import io
import json
import sqlite3
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
import uatool_native_index as native_index
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
                "native": True,
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
                "delegate": False,
                "multicast_delegate": False,
            },
            {
                "function_path": (
                    "/Script/HRRAI.HRThing."
                    "Changed__DelegateSignature"
                ),
                "module_name": "HRRAI",
                "owner_path": "/Script/HRRAI.HRThing",
                "owner_kind": "class",
                "name": "Changed__DelegateSignature",
                "parameter_count": 0,
                "delegate": True,
                "multicast_delegate": True,
            },
        ],
        "native_function_parameters.jsonl": [
            {
                "function_path": "/Script/HRRAI.HRThing.DoThing",
                "parameter_index": 0,
                "parameter_name": "Value",
                "parameter_kind": "input",
                "property_class": "IntProperty",
                "cpp_type": "int32",
                "const_parameter": False,
                "reference_parameter": False,
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
            "functions": 2,
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


def make_ast(root: Path) -> None:
    header = "Plugins/HR_RAI/Source/HRRAI/Public/HRThing.h"
    source = "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp"
    runtime = "Plugins/HR_RAI/Source/HRRAI/Private/hrsim_test.c"
    symbols = [
        {
            "symbol_id": "type-symbol",
            "occurrence_id": "type-occurrence",
            "clang_usr": "c:@S@UHRThing",
            "clang_kind": "StructDecl",
            "kind": "record",
            "language": "cpp",
            "name": "UHRThing",
            "qualified_name": "UHRThing",
            "type_spelling": "UHRThing",
            "source_path": header,
            "translation_unit": source,
            "line": 10,
            "column": 1,
            "offset": 100,
            "is_definition": True,
            "compatibility_overrides": [],
            "evidence": "libclang_cursor_schema1",
        },
        {
            "symbol_id": "do-symbol",
            "occurrence_id": "do-occurrence",
            "clang_usr": "c:@S@UHRThing@F@DoThing#I#",
            "clang_kind": "CXXMethod",
            "kind": "method",
            "language": "cpp",
            "name": "DoThing",
            "qualified_name": "UHRThing::DoThing",
            "type_spelling": "void (int32)",
            "source_path": source,
            "translation_unit": source,
            "line": 25,
            "column": 1,
            "offset": 250,
            "is_definition": True,
            "compatibility_overrides": ["-Wno-invalid-constexpr"],
            "evidence": "libclang_cursor_schema1",
        },
        {
            "symbol_id": "helper-symbol",
            "occurrence_id": "helper-occurrence",
            "clang_usr": "c:@F@hrsim_helper#I#",
            "clang_kind": "FunctionDecl",
            "kind": "function",
            "language": "c",
            "name": "hrsim_helper",
            "qualified_name": "hrsim_helper",
            "type_spelling": "void (int)",
            "source_path": runtime,
            "translation_unit": runtime,
            "line": 8,
            "column": 1,
            "offset": 80,
            "is_definition": True,
            "compatibility_overrides": [],
            "evidence": "libclang_cursor_schema1",
        },
        {
            "symbol_id": "caller-symbol",
            "occurrence_id": "caller-occurrence",
            "clang_usr": "c:@S@UHRThing@F@Caller#",
            "clang_kind": "CXXMethod",
            "kind": "method",
            "language": "cpp",
            "name": "Caller",
            "qualified_name": "UHRThing::Caller",
            "type_spelling": "void ()",
            "source_path": source,
            "translation_unit": source,
            "line": 40,
            "column": 1,
            "offset": 400,
            "is_definition": True,
            "compatibility_overrides": [],
            "evidence": "libclang_cursor_schema1",
        },
    ]
    parameters = [
        {
            "function_symbol_id": "do-symbol",
            "function_occurrence_id": "do-occurrence",
            "parameter_index": 0,
            "name": "Value",
            "type_spelling": "int32",
            "source_path": source,
            "translation_unit": source,
            "language": "cpp",
            "line": 25,
            "column": 20,
            "compatibility_overrides": ["-Wno-invalid-constexpr"],
            "evidence": "libclang_cursor_schema1",
        }
    ]
    calls = [
        {
            "call_id": "call-out",
            "caller_symbol_id": "do-symbol",
            "caller_occurrence_id": "do-occurrence",
            "source_path": source,
            "translation_unit": source,
            "language": "cpp",
            "line": 31,
            "column": 5,
            "offset": 310,
            "target_symbol_id": "helper-symbol",
            "target_usr": "c:@F@hrsim_helper#I#",
            "target_kind": "FunctionDecl",
            "target_name": "hrsim_helper",
            "target_type_spelling": "void (int)",
            "resolution": "compiler_resolved",
            "compatibility_overrides": ["-Wno-invalid-constexpr"],
            "evidence": "libclang_cursor_schema1",
        },
        {
            "call_id": "call-in",
            "caller_symbol_id": "caller-symbol",
            "caller_occurrence_id": "caller-occurrence",
            "source_path": source,
            "translation_unit": source,
            "language": "cpp",
            "line": 44,
            "column": 5,
            "offset": 440,
            "target_symbol_id": "do-symbol",
            "target_usr": "c:@S@UHRThing@F@DoThing#I#",
            "target_kind": "CXXMethod",
            "target_name": "DoThing",
            "target_type_spelling": "void (int32)",
            "resolution": "compiler_resolved",
            "compatibility_overrides": [],
            "evidence": "libclang_cursor_schema1",
        },
    ]
    write_jsonl(root / native_ast.SYMBOLS, symbols)
    write_jsonl(root / native_ast.PARAMETERS, parameters)
    write_jsonl(root / native_ast.CALLS, calls)
    write_jsonl(root / native_ast.DIAGNOSTICS, [])

    manifest = {
        "schema_version": native_ast.SCHEMA_VERSION,
        "pass": "UnrealAssetToolNativeAST",
        "success": True,
        "error": "",
        "project_owned_translation_units": 2,
        "compiler_resolved_translation_units": 2,
        "failed_translation_units": [],
        "normalized_counts": {
            "symbols": len(symbols),
            "parameters": len(parameters),
            "calls": len(calls),
        },
        "evidence": "libclang_cursor_all_translation_units",
    }
    (root / native_ast.MANIFEST).write_text(
        json.dumps(manifest) + "\n",
        encoding="utf-8",
        newline="\n",
    )


class NativeIndexSchema1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.reflected = self.root / "reflected"
        self.compiler = self.root / "compiler"
        self.joins = self.root / "joins"
        self.reflected.mkdir()
        self.compiler.mkdir()
        self.joins.mkdir()
        make_reflected(self.reflected)
        make_ast(self.compiler)
        native_join.capture(
            self.reflected,
            self.compiler,
            self.joins,
        )

        self.db = self.root / "uat.db"
        conn = sqlite3.connect(self.db)
        native_index.create_schema(conn)
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_import_preserves_authoritative_row_counts(self) -> None:
        counts = native_index.import_database(
            self.db,
            self.reflected,
            self.compiler,
            self.joins,
        )
        self.assertEqual(
            counts,
            {
                "native_reflected_types": 1,
                "native_reflected_functions": 2,
                "native_reflected_function_parameters": 1,
                "native_compiler_symbols": 4,
                "native_compiler_parameters": 1,
                "native_compiler_calls": 2,
                "native_type_joins": 1,
                "native_function_joins": 1,
                "native_join_diagnostics": 1,
            },
        )

        conn = sqlite3.connect(self.db)
        try:
            for table, expected in counts.items():
                actual = conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                self.assertEqual(actual, expected, table)
        finally:
            conn.close()

    def test_reflected_function_reaches_source_and_calls(self) -> None:
        native_index.import_database(
            self.db,
            self.reflected,
            self.compiler,
            self.joins,
        )
        conn = sqlite3.connect(self.db)
        try:
            report = native_index.build_report(
                conn,
                "/Script/HRRAI.HRThing.DoThing",
                include_callers=True,
                include_callees=True,
                limit=20,
            )
        finally:
            conn.close()

        self.assertEqual(report["status"], "joined")
        self.assertEqual(
            report["source"]["qualified_name"],
            "UHRThing::DoThing",
        )
        self.assertEqual(
            report["source"]["source_path"],
            "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
        )
        self.assertEqual(
            report["source"]["compatibility_overrides"],
            ["-Wno-invalid-constexpr"],
        )
        self.assertEqual(report["callee_count"], 1)
        self.assertEqual(
            report["callees"][0]["target_name"],
            "hrsim_helper",
        )
        self.assertTrue(
            report["callees"][0]["project_owned_target"]
        )
        self.assertEqual(report["caller_count"], 1)
        self.assertEqual(
            report["callers"][0]["caller_name"],
            "UHRThing::Caller",
        )

    def test_delegate_signature_remains_visibly_unresolved(self) -> None:
        native_index.import_database(
            self.db,
            self.reflected,
            self.compiler,
            self.joins,
        )
        conn = sqlite3.connect(self.db)
        try:
            report = native_index.build_report(
                conn,
                (
                    "/Script/HRRAI.HRThing."
                    "Changed__DelegateSignature"
                ),
            )
        finally:
            conn.close()

        self.assertEqual(report["status"], "unresolved")
        self.assertEqual(len(report["diagnostics"]), 1)
        self.assertEqual(
            report["diagnostics"][0]["reason"],
            "no exact owner/name/parameter-signature compiler method",
        )

    def test_exact_source_qualified_name_reverse_joins(self) -> None:
        native_index.import_database(
            self.db,
            self.reflected,
            self.compiler,
            self.joins,
        )
        conn = sqlite3.connect(self.db)
        try:
            report = native_index.build_report(
                conn,
                "UHRThing::DoThing",
            )
        finally:
            conn.close()

        self.assertEqual(report["status"], "joined")
        self.assertEqual(
            report["reflected_function"]["function_path"],
            "/Script/HRRAI.HRThing.DoThing",
        )

    def test_generic_query_finds_join_and_call_neighborhood(self) -> None:
        native_index.import_database(
            self.db,
            self.reflected,
            self.compiler,
            self.joins,
        )
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        captured: list[dict] = []

        def collect(cursor, fields) -> None:
            for row in cursor:
                captured.append({
                    field: row[field]
                    for field in fields
                })

        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output):
                native_index.query(
                    conn,
                    collect,
                    "%UHRThing::DoThing%",
                    20,
                )
        finally:
            conn.close()

        text = output.getvalue()
        self.assertIn("[native function joins]", text)
        self.assertIn("[native compiler calls]", text)
        self.assertTrue(
            any(
                row.get("source_qualified_name")
                == "UHRThing::DoThing"
                for row in captured
            )
        )
        self.assertTrue(
            any(
                row.get("caller") == "UHRThing::DoThing"
                and row.get("callee") == "hrsim_helper"
                for row in captured
            )
        )


if __name__ == "__main__":
    unittest.main()
