from __future__ import annotations

import contextlib
import io
import json
import sqlite3
import subprocess
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
        "ruleset": native_ast.RULESET,
        "parameter_owner_policy": native_ast.PARAMETER_OWNER_POLICY,
        "call_owner_policy": native_ast.CALL_OWNER_POLICY,
        "pass": "UnrealAssetToolNativeAST",
        "success": True,
        "error": "",
        "project_owned_translation_units": 2,
        "compiler_resolved_translation_units": 2,
        "failed_translation_units": [],
        "parameter_owner_mismatches_rejected": 0,
        "nested_callable_calls_suppressed": 0,
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

    def test_cli_initializes_missing_standard_database(self) -> None:
        self.db.unlink()
        output = self.root / "standard"
        run = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS / "uatool.py"),
                "native-index",
                str(output),
                "--reflected",
                str(self.reflected),
                "--compiler",
                str(self.compiler),
                "--joins",
                str(self.joins),
            ],
            cwd=str(ROOT),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(run.returncode, 0, run.stdout)
        database = output / "uat.db"
        self.assertTrue(database.is_file())
        self.assertIn(
            "initialized standard database cache:",
            run.stdout,
        )
        self.assertIn("native index imported:", run.stdout)

        conn = sqlite3.connect(database)
        try:
            self.assertIsNotNone(
                conn.execute(
                    """SELECT 1 FROM sqlite_master
                       WHERE type='table' AND name='assets'"""
                ).fetchone()
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM native_compiler_symbols"
                ).fetchone()[0],
                4,
            )
        finally:
            conn.close()

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

    def test_parameter_cache_uses_authoritative_canonical_identity(self) -> None:
        parameters_path = self.compiler / native_ast.PARAMETERS
        parameters = native_index._rows(parameters_path)
        parameters.extend([
            {
                "function_symbol_id": "do-symbol",
                "function_occurrence_id": "do-occurrence",
                "parameter_index": -1,
                "name": "GeneratedA",
                "type_spelling": "int32",
                "source_path": (
                    "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp"
                ),
                "translation_unit": (
                    "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp"
                ),
                "language": "cpp",
                "line": 26,
                "column": 5,
                "compatibility_overrides": [],
                "evidence": "libclang_cursor_schema1",
            },
            {
                "function_symbol_id": "do-symbol",
                "function_occurrence_id": "do-occurrence",
                "parameter_index": -1,
                "name": "GeneratedB",
                "type_spelling": "float",
                "source_path": (
                    "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp"
                ),
                "translation_unit": (
                    "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp"
                ),
                "language": "cpp",
                "line": 27,
                "column": 5,
                "compatibility_overrides": [],
                "evidence": "libclang_cursor_schema1",
            },
        ])
        write_jsonl(parameters_path, parameters)
        manifest_path = self.compiler / native_ast.MANIFEST
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        manifest["normalized_counts"]["parameters"] = len(parameters)
        manifest_path.write_text(
            json.dumps(manifest) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        # Recreate the exact narrower cache key used by the first field
        # validation build. Explicit import must migrate this disposable native
        # table instead of requiring the user to delete uat.db.
        conn = sqlite3.connect(self.db)
        try:
            conn.execute("DROP TABLE native_compiler_parameters")
            conn.execute(
                """CREATE TABLE native_compiler_parameters(
                   function_occurrence_id TEXT NOT NULL,
                   parameter_index INTEGER NOT NULL,
                   function_symbol_id TEXT NOT NULL,
                   name TEXT NOT NULL,
                   type_spelling TEXT NOT NULL,
                   source_path TEXT NOT NULL,
                   translation_unit TEXT NOT NULL,
                   language TEXT NOT NULL,
                   line INTEGER NOT NULL,
                   column INTEGER NOT NULL,
                   compatibility_overrides_json TEXT NOT NULL,
                   evidence TEXT NOT NULL,
                   json TEXT NOT NULL,
                   PRIMARY KEY(function_occurrence_id,parameter_index)
                )"""
            )
            conn.execute(
                """CREATE TABLE IF NOT EXISTS standard_sentinel(
                   value TEXT PRIMARY KEY
                )"""
            )
            conn.execute(
                "INSERT INTO standard_sentinel(value) VALUES('keep')"
            )
            conn.commit()
        finally:
            conn.close()

        counts = native_index.import_database(
            self.db,
            self.reflected,
            self.compiler,
            self.joins,
        )
        self.assertEqual(counts["native_compiler_parameters"], 3)

        conn = sqlite3.connect(self.db)
        try:
            rows = conn.execute(
                """SELECT parameter_index,name,type_spelling
                   FROM native_compiler_parameters
                   WHERE function_occurrence_id='do-occurrence'
                   ORDER BY parameter_index,line,column,name,type_spelling"""
            ).fetchall()
            self.assertEqual(
                rows,
                [
                    (-1, "GeneratedA", "int32"),
                    (-1, "GeneratedB", "float"),
                    (0, "Value", "int32"),
                ],
            )
            pk_columns = [
                row[1]
                for row in sorted(
                    (
                        row
                        for row in conn.execute(
                            "PRAGMA table_info(native_compiler_parameters)"
                        ).fetchall()
                        if row[5]
                    ),
                    key=lambda row: row[5],
                )
            ]
            self.assertEqual(
                pk_columns,
                [
                    "function_occurrence_id",
                    "parameter_index",
                    "name",
                    "type_spelling",
                ],
            )
            self.assertEqual(
                conn.execute(
                    "SELECT value FROM standard_sentinel"
                ).fetchone()[0],
                "keep",
            )
            stats = json.loads(
                conn.execute(
                    """SELECT value FROM native_index_meta
                       WHERE key='parameter_identity_stats_json'"""
                ).fetchone()[0]
            )
        finally:
            conn.close()

        self.assertEqual(stats["rows"], 3)
        self.assertEqual(stats["negative_index_rows"], 2)
        self.assertEqual(stats["duplicate_index_slots"], 1)
        self.assertEqual(
            stats["rows_beyond_unique_index_slots"],
            1,
        )

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

    def test_project_target_without_materialized_symbol_is_preserved(self) -> None:
        calls_path = self.compiler / native_ast.CALLS
        calls = native_index._rows(calls_path)
        calls.append({
            "call_id": "call-dangling",
            "caller_symbol_id": "do-symbol",
            "caller_occurrence_id": "do-occurrence",
            "source_path": (
                "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp"
            ),
            "translation_unit": (
                "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp"
            ),
            "language": "cpp",
            "line": 32,
            "column": 5,
            "offset": 320,
            "target_symbol_id": "nonmaterialized-target",
            "target_usr": "c:@F@GeneratedThunk#",
            "target_kind": "FunctionDecl",
            "target_name": "GeneratedThunk",
            "target_type_spelling": "void ()",
            "resolution": "compiler_resolved",
            "compatibility_overrides": [],
            "evidence": "libclang_cursor_schema1",
        })
        write_jsonl(calls_path, calls)
        manifest_path = self.compiler / native_ast.MANIFEST
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        manifest["normalized_counts"]["calls"] = len(calls)
        manifest_path.write_text(
            json.dumps(manifest) + "\n",
            encoding="utf-8",
            newline="\n",
        )

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
                include_callers=False,
                include_callees=True,
                limit=20,
            )
            meta = json.loads(
                conn.execute(
                    """SELECT value FROM native_index_meta
                       WHERE key='call_target_stats_json'"""
                ).fetchone()[0]
            )
        finally:
            conn.close()

        dangling = [
            edge
            for edge in report["callees"]
            if edge["call_id"] == "call-dangling"
        ]
        self.assertEqual(len(dangling), 1)
        self.assertTrue(dangling[0]["project_owned_target"])
        self.assertFalse(dangling[0]["target_materialized"])
        self.assertEqual(
            dangling[0]["target_resolution_basis"],
            "unmaterialized_project_cursor",
        )
        self.assertEqual(
            dangling[0]["target_name"],
            "GeneratedThunk",
        )
        self.assertEqual(
            meta["unmaterialized_project_targets"],
            1,
        )

    def test_mismatched_project_target_id_resolves_by_exact_usr(self) -> None:
        calls_path = self.compiler / native_ast.CALLS
        calls = native_index._rows(calls_path)
        calls.append({
            "call_id": "call-usr-fallback",
            "caller_symbol_id": "do-symbol",
            "caller_occurrence_id": "do-occurrence",
            "source_path": (
                "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp"
            ),
            "translation_unit": (
                "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp"
            ),
            "language": "cpp",
            "line": 33,
            "column": 5,
            "offset": 330,
            "target_symbol_id": "different-cursor-kind-id",
            "target_usr": "c:@F@hrsim_helper#I#",
            "target_kind": "FunctionDecl",
            "target_name": "hrsim_helper",
            "target_type_spelling": "void (int)",
            "resolution": "compiler_resolved",
            "compatibility_overrides": [],
            "evidence": "libclang_cursor_schema1",
        })
        write_jsonl(calls_path, calls)
        manifest_path = self.compiler / native_ast.MANIFEST
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        manifest["normalized_counts"]["calls"] = len(calls)
        manifest_path.write_text(
            json.dumps(manifest) + "\n",
            encoding="utf-8",
            newline="\n",
        )

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
                include_callers=False,
                include_callees=True,
                limit=20,
            )
            meta = json.loads(
                conn.execute(
                    """SELECT value FROM native_index_meta
                       WHERE key='call_target_stats_json'"""
                ).fetchone()[0]
            )
        finally:
            conn.close()

        fallback = [
            edge
            for edge in report["callees"]
            if edge["call_id"] == "call-usr-fallback"
        ]
        self.assertEqual(len(fallback), 1)
        self.assertTrue(fallback[0]["project_owned_target"])
        self.assertTrue(fallback[0]["target_materialized"])
        self.assertEqual(
            fallback[0]["target_resolution_basis"],
            "clang_usr",
        )
        self.assertEqual(
            fallback[0]["target_source_path"],
            "Plugins/HR_RAI/Source/HRRAI/Private/hrsim_test.c",
        )
        self.assertEqual(
            meta["materialized_by_clang_usr"],
            1,
        )

    def test_audit_reports_join_parameter_and_target_anomalies(self) -> None:
        native_index.import_database(
            self.db,
            self.reflected,
            self.compiler,
            self.joins,
        )
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute(
                """INSERT INTO native_compiler_parameters
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "do-occurrence",
                    0,
                    "do-symbol",
                    "AliasValue",
                    "float",
                    "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
                    "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
                    "cpp",
                    26,
                    22,
                    "[]",
                    "libclang_cursor_schema1",
                    json.dumps({
                        "function_symbol_id": "do-symbol",
                        "function_occurrence_id": "do-occurrence",
                        "parameter_index": 0,
                        "name": "AliasValue",
                        "type_spelling": "float",
                    }),
                ),
            )
            conn.execute(
                """INSERT INTO native_compiler_calls
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "call-audit-unmaterialized",
                    "do-symbol",
                    "do-occurrence",
                    "project-cursor-only",
                    "c:@F@ProjectThunk#",
                    "FunctionDecl",
                    "ProjectThunk",
                    "void ()",
                    "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
                    "Plugins/HR_RAI/Source/HRRAI/Private/HRThing.cpp",
                    "cpp",
                    35,
                    7,
                    350,
                    "compiler_resolved",
                    "[]",
                    "libclang_cursor_schema1",
                    "{}",
                ),
            )
            report = native_index.build_audit(conn, limit=100)
        finally:
            conn.close()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["counts"]["joined_functions"], 1)
        self.assertEqual(report["counts"]["function_diagnostics"], 1)
        self.assertEqual(
            report["counts"]["duplicate_parameter_slots"],
            1,
        )
        self.assertEqual(
            report["counts"]["unmaterialized_project_target_calls"],
            1,
        )
        self.assertEqual(
            report["counts"]["unmaterialized_project_target_identities"],
            1,
        )
        self.assertEqual(
            report["joined_functions"][0]["source_qualified_name"],
            "UHRThing::DoThing",
        )
        self.assertEqual(
            report["duplicate_parameter_slots"][0]["function_name"],
            "UHRThing::DoThing",
        )
        self.assertEqual(
            report["duplicate_parameter_slots"][0]["row_count"],
            2,
        )
        self.assertEqual(
            report["unmaterialized_project_targets"][0]["target_name"],
            "ProjectThunk",
        )

    def test_source_only_report_labels_absent_reflected_join(self) -> None:
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
                "UHRThing::Caller",
                include_callers=False,
                include_callees=False,
            )
        finally:
            conn.close()

        self.assertEqual(report["status"], "source")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            native_index.print_report(report)
        self.assertIn(
            "Reflected join: <none; exact compiler symbol is source-only>",
            output.getvalue(),
        )

    def test_canonical_launcher_exposes_native_index_audit(self) -> None:
        launcher = (SCRIPTS / "uatool.py").read_text(encoding="utf-8")
        self.assertIn('prog="uatool native-index-audit"', launcher)
        self.assertIn(
            'sys.argv[1] == "native-index-audit"',
            launcher,
        )
        self.assertIn("native_index.build_audit(", launcher)
        self.assertIn("native_index.print_audit(report)", launcher)

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
