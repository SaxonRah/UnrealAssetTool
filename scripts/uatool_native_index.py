#!/usr/bin/env python3
"""SQLite cache integration and query/report surfaces for native schema 1."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import uatool_native as reflected_native
import uatool_native_ast as native_ast
import uatool_native_join as native_join
import uatool_native_freshness as native_freshness

SCHEMA_VERSION = 1

_SQL = """
CREATE TABLE IF NOT EXISTS native_index_meta(
 key TEXT PRIMARY KEY,
 value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS native_reflected_types(
 type_path TEXT PRIMARY KEY,
 module_name TEXT NOT NULL,
 kind TEXT NOT NULL,
 name TEXT NOT NULL,
 cpp_name TEXT NOT NULL,
 json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS native_reflected_types_module_idx
 ON native_reflected_types(module_name,kind);
CREATE INDEX IF NOT EXISTS native_reflected_types_cpp_idx
 ON native_reflected_types(cpp_name);

CREATE TABLE IF NOT EXISTS native_reflected_functions(
 function_path TEXT PRIMARY KEY,
 module_name TEXT NOT NULL,
 owner_path TEXT NOT NULL,
 owner_kind TEXT NOT NULL,
 name TEXT NOT NULL,
 parameter_count INTEGER NOT NULL,
 delegate INTEGER NOT NULL,
 multicast_delegate INTEGER NOT NULL,
 json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS native_reflected_functions_owner_idx
 ON native_reflected_functions(owner_path,name);
CREATE INDEX IF NOT EXISTS native_reflected_functions_name_idx
 ON native_reflected_functions(name);
CREATE INDEX IF NOT EXISTS native_reflected_functions_module_idx
 ON native_reflected_functions(module_name,name);

CREATE TABLE IF NOT EXISTS native_reflected_function_parameters(
 function_path TEXT NOT NULL,
 parameter_index INTEGER NOT NULL,
 parameter_name TEXT NOT NULL,
 parameter_kind TEXT NOT NULL,
 cpp_type TEXT NOT NULL,
 const_parameter INTEGER NOT NULL,
 reference_parameter INTEGER NOT NULL,
 json TEXT NOT NULL,
 PRIMARY KEY(function_path,parameter_index)
);
CREATE INDEX IF NOT EXISTS native_reflected_parameters_kind_idx
 ON native_reflected_function_parameters(parameter_kind,cpp_type);

CREATE TABLE IF NOT EXISTS native_compiler_symbols(
 occurrence_id TEXT PRIMARY KEY,
 symbol_id TEXT NOT NULL,
 clang_usr TEXT NOT NULL,
 clang_kind TEXT NOT NULL,
 kind TEXT NOT NULL,
 name TEXT NOT NULL,
 qualified_name TEXT NOT NULL,
 type_spelling TEXT NOT NULL,
 source_path TEXT NOT NULL,
 translation_unit TEXT NOT NULL,
 language TEXT NOT NULL,
 line INTEGER NOT NULL,
 column INTEGER NOT NULL,
 offset INTEGER NOT NULL,
 is_definition INTEGER NOT NULL,
 compatibility_overrides_json TEXT NOT NULL,
 evidence TEXT NOT NULL,
 json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS native_compiler_symbols_symbol_idx
 ON native_compiler_symbols(symbol_id,is_definition);
CREATE INDEX IF NOT EXISTS native_compiler_symbols_usr_idx
 ON native_compiler_symbols(clang_usr);
CREATE INDEX IF NOT EXISTS native_compiler_symbols_qualified_idx
 ON native_compiler_symbols(qualified_name);
CREATE INDEX IF NOT EXISTS native_compiler_symbols_name_idx
 ON native_compiler_symbols(name);
CREATE INDEX IF NOT EXISTS native_compiler_symbols_source_idx
 ON native_compiler_symbols(source_path,line);
CREATE INDEX IF NOT EXISTS native_compiler_symbols_tu_idx
 ON native_compiler_symbols(translation_unit);

CREATE TABLE IF NOT EXISTS native_compiler_parameters(
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
 PRIMARY KEY(
   function_occurrence_id,
   parameter_index,
   name,
   type_spelling
 )
);
CREATE INDEX IF NOT EXISTS native_compiler_parameters_symbol_idx
 ON native_compiler_parameters(function_symbol_id,parameter_index);

CREATE TABLE IF NOT EXISTS native_compiler_calls(
 call_id TEXT PRIMARY KEY,
 caller_symbol_id TEXT NOT NULL,
 caller_occurrence_id TEXT NOT NULL,
 target_symbol_id TEXT NOT NULL,
 target_usr TEXT NOT NULL,
 target_kind TEXT NOT NULL,
 target_name TEXT NOT NULL,
 target_type_spelling TEXT NOT NULL,
 source_path TEXT NOT NULL,
 translation_unit TEXT NOT NULL,
 language TEXT NOT NULL,
 line INTEGER NOT NULL,
 column INTEGER NOT NULL,
 offset INTEGER NOT NULL,
 resolution TEXT NOT NULL,
 compatibility_overrides_json TEXT NOT NULL,
 evidence TEXT NOT NULL,
 json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS native_compiler_calls_caller_idx
 ON native_compiler_calls(caller_symbol_id,source_path,line);
CREATE INDEX IF NOT EXISTS native_compiler_calls_caller_occurrence_idx
 ON native_compiler_calls(caller_occurrence_id);
CREATE INDEX IF NOT EXISTS native_compiler_calls_target_idx
 ON native_compiler_calls(target_symbol_id);
CREATE INDEX IF NOT EXISTS native_compiler_calls_target_usr_idx
 ON native_compiler_calls(target_usr);
CREATE INDEX IF NOT EXISTS native_compiler_calls_target_name_idx
 ON native_compiler_calls(target_name);
CREATE INDEX IF NOT EXISTS native_compiler_calls_tu_idx
 ON native_compiler_calls(translation_unit);

CREATE TABLE IF NOT EXISTS native_type_joins(
 join_id TEXT PRIMARY KEY,
 reflected_type_path TEXT NOT NULL UNIQUE,
 reflected_kind TEXT NOT NULL,
 reflected_module_name TEXT NOT NULL,
 reflected_cpp_name TEXT NOT NULL,
 source_symbol_id TEXT NOT NULL,
 source_clang_usr TEXT NOT NULL,
 source_occurrence_id TEXT NOT NULL,
 source_occurrence_ids_json TEXT NOT NULL,
 source_path TEXT NOT NULL,
 source_line INTEGER NOT NULL,
 source_qualified_name TEXT NOT NULL,
 compatibility_overrides_json TEXT NOT NULL,
 proof TEXT NOT NULL,
 evidence TEXT NOT NULL,
 json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS native_type_joins_symbol_idx
 ON native_type_joins(source_symbol_id);
CREATE INDEX IF NOT EXISTS native_type_joins_usr_idx
 ON native_type_joins(source_clang_usr);
CREATE INDEX IF NOT EXISTS native_type_joins_source_idx
 ON native_type_joins(source_path,source_line);

CREATE TABLE IF NOT EXISTS native_function_joins(
 join_id TEXT PRIMARY KEY,
 reflected_function_path TEXT NOT NULL UNIQUE,
 reflected_owner_path TEXT NOT NULL,
 reflected_module_name TEXT NOT NULL,
 reflected_name TEXT NOT NULL,
 reflected_parameter_signature_json TEXT NOT NULL,
 accepted_source_parameter_types_json TEXT NOT NULL,
 source_symbol_id TEXT NOT NULL,
 source_clang_usr TEXT NOT NULL,
 source_occurrence_id TEXT NOT NULL,
 source_occurrence_ids_json TEXT NOT NULL,
 source_path TEXT NOT NULL,
 source_line INTEGER NOT NULL,
 source_qualified_name TEXT NOT NULL,
 source_parameter_signature_json TEXT NOT NULL,
 compatibility_overrides_json TEXT NOT NULL,
 proof TEXT NOT NULL,
 evidence TEXT NOT NULL,
 json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS native_function_joins_owner_idx
 ON native_function_joins(reflected_owner_path,reflected_name);
CREATE INDEX IF NOT EXISTS native_function_joins_symbol_idx
 ON native_function_joins(source_symbol_id);
CREATE INDEX IF NOT EXISTS native_function_joins_usr_idx
 ON native_function_joins(source_clang_usr);
CREATE INDEX IF NOT EXISTS native_function_joins_qualified_idx
 ON native_function_joins(source_qualified_name);
CREATE INDEX IF NOT EXISTS native_function_joins_source_idx
 ON native_function_joins(source_path,source_line);

CREATE TABLE IF NOT EXISTS native_join_diagnostics(
 diagnostic_index INTEGER PRIMARY KEY,
 kind TEXT NOT NULL,
 reflected_type_path TEXT NOT NULL,
 reflected_function_path TEXT NOT NULL,
 owner_path TEXT NOT NULL,
 module_name TEXT NOT NULL,
 status TEXT NOT NULL,
 reason TEXT NOT NULL,
 candidate_symbol_ids_json TEXT NOT NULL,
 json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS native_join_diagnostics_type_idx
 ON native_join_diagnostics(reflected_type_path,status);
CREATE INDEX IF NOT EXISTS native_join_diagnostics_function_idx
 ON native_join_diagnostics(reflected_function_path,status);
CREATE INDEX IF NOT EXISTS native_join_diagnostics_status_idx
 ON native_join_diagnostics(kind,status);
"""


_TABLES = (
    "native_reflected_types",
    "native_reflected_functions",
    "native_reflected_function_parameters",
    "native_compiler_symbols",
    "native_compiler_parameters",
    "native_compiler_calls",
    "native_type_joins",
    "native_function_joins",
    "native_join_diagnostics",
)


def _j(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _rows(path: Path) -> list[dict]:
    result: list[dict] = []
    if not path.is_file():
        return result
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"invalid JSON in {path}:{line_number}: {exc}"
                ) from exc
            if not isinstance(value, dict):
                raise RuntimeError(
                    f"expected JSON object in {path}:{line_number}"
                )
            result.append(value)
    return result


def _read_manifest(path: Path, label: str) -> dict:
    if not path.is_file():
        raise RuntimeError(f"{label} manifest missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} manifest invalid: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} manifest root is not an object: {path}")
    return value


def _excluded_source(path: str) -> bool:
    normalized = "/" + str(path or "").replace("\\", "/").strip("/").lower() + "/"
    return any(
        f"/{part}/" in normalized
        for part in ("engine", "intermediate", "binaries", "saved")
    )


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SQL)


def _validate_ast(output: Path) -> dict:
    manifest = _read_manifest(output / native_ast.MANIFEST, "native AST")
    if int(manifest.get("schema_version", 0) or 0) != native_ast.SCHEMA_VERSION:
        raise RuntimeError(
            "native AST schema version mismatch: "
            f"{manifest.get('schema_version')!r}"
        )
    if manifest.get("pass") != "UnrealAssetToolNativeAST":
        raise RuntimeError(
            f"unexpected native AST pass {manifest.get('pass')!r}"
        )
    if manifest.get("ruleset") != native_ast.RULESET:
        raise RuntimeError(
            "native AST ruleset is stale or missing; recapture with the "
            "current uatool ast-capture"
        )
    if (
        manifest.get("parameter_owner_policy")
        != native_ast.PARAMETER_OWNER_POLICY
    ):
        raise RuntimeError(
            "native AST parameter ownership policy mismatch"
        )
    if manifest.get("call_owner_policy") != native_ast.CALL_OWNER_POLICY:
        raise RuntimeError(
            "native AST call ownership policy mismatch"
        )
    compiler_inputs = manifest.get("compiler_input_snapshot")
    if compiler_inputs is not None:
        compiler_input_error = native_freshness.validation_error(
            compiler_inputs
        )
        if compiler_input_error:
            raise RuntimeError(
                "native AST compiler input snapshot invalid: "
                f"{compiler_input_error}"
            )
        if manifest.get("compiler_inputs_unchanged") is False:
            raise RuntimeError(
                "native AST compiler inputs changed during capture"
            )

    if not manifest.get("success"):
        raise RuntimeError(
            f"native AST capture failed: {manifest.get('error', '')}"
        )
    expected_tus = int(manifest.get("project_owned_translation_units", 0) or 0)
    resolved_tus = manifest.get("compiler_resolved_translation_units")
    if resolved_tus is not None and int(resolved_tus or 0) != expected_tus:
        raise RuntimeError(
            "native AST translation-unit coverage incomplete: "
            f"{resolved_tus}/{expected_tus}"
        )
    owner_mismatch_count = manifest.get(
        "parameter_owner_mismatches_rejected"
    )
    if owner_mismatch_count is None:
        raise RuntimeError(
            "native AST parameter ownership rejection count missing"
        )
    if int(owner_mismatch_count or 0) < 0:
        raise RuntimeError(
            "native AST parameter ownership rejection count invalid"
        )
    suppressed_calls = manifest.get(
        "nested_callable_calls_suppressed"
    )
    if suppressed_calls is None:
        raise RuntimeError(
            "native AST nested callable call suppression count missing"
        )
    if int(suppressed_calls or 0) < 0:
        raise RuntimeError(
            "native AST nested callable call suppression count invalid"
        )

    normalized = manifest.get("normalized_counts")
    if not isinstance(normalized, dict):
        raise RuntimeError(
            "native AST normalized_counts missing; compiler-resolved "
            "JSONL schema 1 is required"
        )
    return manifest


def load_authoritative_inputs(
    reflected_output: Path,
    compiler_output: Path,
    join_output: Path,
) -> dict:
    reflected_output = Path(reflected_output).expanduser().resolve()
    compiler_output = Path(compiler_output).expanduser().resolve()
    join_output = Path(join_output).expanduser().resolve()

    reflected_error = reflected_native.validation_error(reflected_output)
    if reflected_error:
        raise RuntimeError(
            f"reflected native input invalid: {reflected_error}"
        )
    reflected_manifest = _read_manifest(
        reflected_output / reflected_native.MANIFEST_FILE,
        "reflected native",
    )
    compiler_manifest = _validate_ast(compiler_output)
    join_error = native_join.validation_error(join_output)
    if join_error:
        raise RuntimeError(f"native join input invalid: {join_error}")
    join_manifest = _read_manifest(
        join_output / native_join.MANIFEST,
        "native join",
    )

    data = {
        "reflected_types": _rows(
            reflected_output / "native_types.jsonl"
        ),
        "reflected_functions": _rows(
            reflected_output / "native_functions.jsonl"
        ),
        "reflected_function_parameters": _rows(
            reflected_output / "native_function_parameters.jsonl"
        ),
        "compiler_symbols": _rows(
            compiler_output / native_ast.SYMBOLS
        ),
        "compiler_parameters": _rows(
            compiler_output / native_ast.PARAMETERS
        ),
        "compiler_calls": _rows(
            compiler_output / native_ast.CALLS
        ),
        "type_joins": _rows(
            join_output / native_join.TYPE_JOINS
        ),
        "function_joins": _rows(
            join_output / native_join.FUNCTION_JOINS
        ),
        "join_diagnostics": _rows(
            join_output / native_join.DIAGNOSTICS
        ),
    }

    normalized = compiler_manifest.get("normalized_counts", {})
    for key, manifest_key in (
        ("compiler_symbols", "symbols"),
        ("compiler_parameters", "parameters"),
        ("compiler_calls", "calls"),
    ):
        actual = len(data[key])
        expected = int(normalized.get(manifest_key, -1))
        if actual != expected:
            raise RuntimeError(
                f"native AST count mismatch for {manifest_key}: "
                f"manifest={expected} actual={actual}"
            )

    symbol_ids = {
        str(row.get("symbol_id", "") or "")
        for row in data["compiler_symbols"]
        if row.get("symbol_id")
    }
    occurrence_ids = [
        str(row.get("occurrence_id", "") or "")
        for row in data["compiler_symbols"]
    ]
    if any(not value for value in occurrence_ids):
        raise RuntimeError("native compiler symbol lacks occurrence_id")
    if len(occurrence_ids) != len(set(occurrence_ids)):
        raise RuntimeError("native compiler occurrence_id values are not unique")

    for row in data["compiler_symbols"]:
        if _excluded_source(str(row.get("source_path", ""))):
            raise RuntimeError(
                "excluded Engine/build source leaked into compiler symbols: "
                f"{row.get('source_path', '')}"
            )
    occurrence_set = set(occurrence_ids)
    parameter_keys: list[tuple[str, int, str, str]] = []
    parameter_slots: list[tuple[str, int]] = []
    negative_parameter_index_rows = 0
    for row in data["compiler_parameters"]:
        occurrence_id = str(
            row.get("function_occurrence_id", "") or ""
        )
        if occurrence_id not in occurrence_set:
            raise RuntimeError(
                "compiler parameter references unknown function occurrence: "
                f"{occurrence_id}"
            )
        parameter_index = int(row.get("parameter_index", 0) or 0)
        if parameter_index < 0:
            negative_parameter_index_rows += 1
        parameter_keys.append((
            occurrence_id,
            parameter_index,
            str(row.get("name", "") or ""),
            str(row.get("type_spelling", "") or ""),
        ))
        parameter_slots.append((occurrence_id, parameter_index))

    if len(parameter_keys) != len(set(parameter_keys)):
        raise RuntimeError(
            "native compiler parameter canonical identity is not unique"
        )

    slot_counts: dict[tuple[str, int], int] = {}
    for slot in parameter_slots:
        slot_counts[slot] = slot_counts.get(slot, 0) + 1
    duplicate_parameter_slots = sum(
        1 for count in slot_counts.values() if count > 1
    )
    duplicate_parameter_slot_rows = sum(
        count - 1 for count in slot_counts.values() if count > 1
    )
    data["parameter_identity_stats"] = {
        "rows": len(parameter_keys),
        "negative_index_rows": negative_parameter_index_rows,
        "duplicate_index_slots": duplicate_parameter_slots,
        "rows_beyond_unique_index_slots": duplicate_parameter_slot_rows,
    }

    call_ids = [
        str(row.get("call_id", "") or "")
        for row in data["compiler_calls"]
    ]
    if any(not value for value in call_ids):
        raise RuntimeError("native compiler call lacks call_id")
    if len(call_ids) != len(set(call_ids)):
        raise RuntimeError("native compiler call_id values are not unique")
    symbol_usrs = {
        str(row.get("clang_usr", "") or "")
        for row in data["compiler_symbols"]
        if row.get("clang_usr")
    }
    project_target_calls = 0
    materialized_target_id_calls = 0
    materialized_target_usr_calls = 0
    unmaterialized_project_target_calls = 0
    for row in data["compiler_calls"]:
        caller = str(row.get("caller_symbol_id", "") or "")
        target = str(row.get("target_symbol_id", "") or "")
        target_usr = str(row.get("target_usr", "") or "")
        if caller not in symbol_ids:
            raise RuntimeError(
                f"compiler call references unknown caller symbol: {caller}"
            )
        if target:
            project_target_calls += 1
            if target in symbol_ids:
                materialized_target_id_calls += 1
            elif target_usr and target_usr in symbol_usrs:
                materialized_target_usr_calls += 1
            else:
                # target_symbol_id is created from the compiler-resolved
                # referenced cursor whenever that cursor has a project-relative
                # expansion location. Canonical symbol rows use a stricter
                # authored/traversal filter, so generated/macro/template cursors
                # may intentionally have a stable project target identity
                # without a first-class symbol row. Preserve that evidence
                # instead of manufacturing or requiring a synthetic symbol.
                unmaterialized_project_target_calls += 1
        if _excluded_source(str(row.get("source_path", ""))):
            raise RuntimeError(
                "excluded Engine/build source leaked into compiler calls: "
                f"{row.get('source_path', '')}"
            )

    data["call_target_stats"] = {
        "project_target_calls": project_target_calls,
        "materialized_by_symbol_id": materialized_target_id_calls,
        "materialized_by_clang_usr": materialized_target_usr_calls,
        "unmaterialized_project_targets": (
            unmaterialized_project_target_calls
        ),
    }

    reflected_type_paths = {
        str(row.get("type_path", "") or "")
        for row in data["reflected_types"]
        if row.get("type_path")
    }
    reflected_function_paths = {
        str(row.get("function_path", "") or "")
        for row in data["reflected_functions"]
        if row.get("function_path")
    }

    joined_type_paths: set[str] = set()
    for row in data["type_joins"]:
        reflected_path = str(
            row.get("reflected_type_path", "") or ""
        )
        source_symbol_id = str(
            row.get("source_symbol_id", "") or ""
        )
        if reflected_path not in reflected_type_paths:
            raise RuntimeError(
                "type join references unknown reflected type: "
                f"{reflected_path}"
            )
        if source_symbol_id not in symbol_ids:
            raise RuntimeError(
                "type join references unknown compiler symbol: "
                f"{source_symbol_id}"
            )
        if reflected_path in joined_type_paths:
            raise RuntimeError(
                f"duplicate type join for reflected path: {reflected_path}"
            )
        joined_type_paths.add(reflected_path)

    joined_function_paths: set[str] = set()
    for row in data["function_joins"]:
        reflected_path = str(
            row.get("reflected_function_path", "") or ""
        )
        source_symbol_id = str(
            row.get("source_symbol_id", "") or ""
        )
        if reflected_path not in reflected_function_paths:
            raise RuntimeError(
                "function join references unknown reflected function: "
                f"{reflected_path}"
            )
        if source_symbol_id not in symbol_ids:
            raise RuntimeError(
                "function join references unknown compiler symbol: "
                f"{source_symbol_id}"
            )
        if reflected_path in joined_function_paths:
            raise RuntimeError(
                "duplicate function join for reflected path: "
                f"{reflected_path}"
            )
        joined_function_paths.add(reflected_path)

    data["manifests"] = {
        "reflected": reflected_manifest,
        "compiler": compiler_manifest,
        "join": join_manifest,
    }
    data["sources"] = {
        "reflected": reflected_output,
        "compiler": compiler_output,
        "join": join_output,
    }
    return data


def _expected_counts(data: dict) -> dict[str, int]:
    return {
        "native_reflected_types": len(data["reflected_types"]),
        "native_reflected_functions": len(data["reflected_functions"]),
        "native_reflected_function_parameters": len(
            data["reflected_function_parameters"]
        ),
        "native_compiler_symbols": len(data["compiler_symbols"]),
        "native_compiler_parameters": len(data["compiler_parameters"]),
        "native_compiler_calls": len(data["compiler_calls"]),
        "native_type_joins": len(data["type_joins"]),
        "native_function_joins": len(data["function_joins"]),
        "native_join_diagnostics": len(data["join_diagnostics"]),
    }


def _verify_database_counts(
    conn: sqlite3.Connection,
    expected: dict[str, int],
) -> None:
    for table, wanted in expected.items():
        actual = int(
            conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        )
        if actual != wanted:
            raise RuntimeError(
                f"native database count mismatch for {table}: "
                f"expected={wanted} actual={actual}"
            )


def load_database(
    conn: sqlite3.Connection,
    reflected_output: Path,
    compiler_output: Path,
    join_output: Path,
) -> dict[str, int]:
    data = load_authoritative_inputs(
        reflected_output,
        compiler_output,
        join_output,
    )

    # Native SQLite rows are a disposable projection of authoritative JSONL.
    # Rebuild only the native cache tables on every explicit import so cache
    # schema fixes migrate old uat.db files without touching standard tables.
    for table in reversed(_TABLES):
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute("DROP TABLE IF EXISTS native_index_meta")
    create_schema(conn)

    conn.executemany(
        """INSERT INTO native_reflected_types
           VALUES(?,?,?,?,?,?)""",
        [
            (
                row.get("type_path", ""),
                row.get("module_name", ""),
                row.get("kind", ""),
                row.get("name", ""),
                row.get("cpp_name", ""),
                _j(row),
            )
            for row in data["reflected_types"]
        ],
    )
    conn.executemany(
        """INSERT INTO native_reflected_functions
           VALUES(?,?,?,?,?,?,?,?,?)""",
        [
            (
                row.get("function_path", ""),
                row.get("module_name", ""),
                row.get("owner_path", ""),
                row.get("owner_kind", ""),
                row.get("name", ""),
                int(row.get("parameter_count", 0) or 0),
                int(bool(row.get("delegate"))),
                int(bool(row.get("multicast_delegate"))),
                _j(row),
            )
            for row in data["reflected_functions"]
        ],
    )
    conn.executemany(
        """INSERT INTO native_reflected_function_parameters
           VALUES(?,?,?,?,?,?,?,?)""",
        [
            (
                row.get("function_path", ""),
                int(row.get("parameter_index", 0) or 0),
                row.get("parameter_name", ""),
                row.get("parameter_kind", ""),
                row.get("cpp_type", ""),
                int(bool(row.get("const_parameter"))),
                int(bool(row.get("reference_parameter"))),
                _j(row),
            )
            for row in data["reflected_function_parameters"]
        ],
    )
    conn.executemany(
        """INSERT INTO native_compiler_symbols
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                row.get("occurrence_id", ""),
                row.get("symbol_id", ""),
                row.get("clang_usr", ""),
                row.get("clang_kind", ""),
                row.get("kind", ""),
                row.get("name", ""),
                row.get("qualified_name", ""),
                row.get("type_spelling", ""),
                row.get("source_path", ""),
                row.get("translation_unit", ""),
                row.get("language", ""),
                int(row.get("line", 0) or 0),
                int(row.get("column", 0) or 0),
                int(row.get("offset", 0) or 0),
                int(bool(row.get("is_definition"))),
                _j(row.get("compatibility_overrides", [])),
                row.get("evidence", ""),
                _j(row),
            )
            for row in data["compiler_symbols"]
        ],
    )
    conn.executemany(
        """INSERT INTO native_compiler_parameters
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                row.get("function_occurrence_id", ""),
                int(row.get("parameter_index", 0) or 0),
                row.get("function_symbol_id", ""),
                row.get("name", ""),
                row.get("type_spelling", ""),
                row.get("source_path", ""),
                row.get("translation_unit", ""),
                row.get("language", ""),
                int(row.get("line", 0) or 0),
                int(row.get("column", 0) or 0),
                _j(row.get("compatibility_overrides", [])),
                row.get("evidence", ""),
                _j(row),
            )
            for row in data["compiler_parameters"]
        ],
    )
    conn.executemany(
        """INSERT INTO native_compiler_calls
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                row.get("call_id", ""),
                row.get("caller_symbol_id", ""),
                row.get("caller_occurrence_id", ""),
                row.get("target_symbol_id", ""),
                row.get("target_usr", ""),
                row.get("target_kind", ""),
                row.get("target_name", ""),
                row.get("target_type_spelling", ""),
                row.get("source_path", ""),
                row.get("translation_unit", ""),
                row.get("language", ""),
                int(row.get("line", 0) or 0),
                int(row.get("column", 0) or 0),
                int(row.get("offset", 0) or 0),
                row.get("resolution", ""),
                _j(row.get("compatibility_overrides", [])),
                row.get("evidence", ""),
                _j(row),
            )
            for row in data["compiler_calls"]
        ],
    )
    conn.executemany(
        """INSERT INTO native_type_joins
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                row.get("join_id", ""),
                row.get("reflected_type_path", ""),
                row.get("reflected_kind", ""),
                row.get("reflected_module_name", ""),
                row.get("reflected_cpp_name", ""),
                row.get("source_symbol_id", ""),
                row.get("source_clang_usr", ""),
                row.get("source_occurrence_id", ""),
                _j(row.get("source_occurrence_ids", [])),
                row.get("source_path", ""),
                int(row.get("source_line", 0) or 0),
                row.get("source_qualified_name", ""),
                _j(row.get("compatibility_overrides", [])),
                row.get("proof", ""),
                row.get("evidence", ""),
                _j(row),
            )
            for row in data["type_joins"]
        ],
    )
    conn.executemany(
        """INSERT INTO native_function_joins
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                row.get("join_id", ""),
                row.get("reflected_function_path", ""),
                row.get("reflected_owner_path", ""),
                row.get("reflected_module_name", ""),
                row.get("reflected_name", ""),
                _j(row.get("reflected_parameter_signature", [])),
                _j(row.get("accepted_source_parameter_types", [])),
                row.get("source_symbol_id", ""),
                row.get("source_clang_usr", ""),
                row.get("source_occurrence_id", ""),
                _j(row.get("source_occurrence_ids", [])),
                row.get("source_path", ""),
                int(row.get("source_line", 0) or 0),
                row.get("source_qualified_name", ""),
                _j(row.get("source_parameter_signature", [])),
                _j(row.get("compatibility_overrides", [])),
                row.get("proof", ""),
                row.get("evidence", ""),
                _j(row),
            )
            for row in data["function_joins"]
        ],
    )
    conn.executemany(
        """INSERT INTO native_join_diagnostics
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        [
            (
                index,
                row.get("kind", ""),
                row.get("reflected_type_path", ""),
                row.get("reflected_function_path", ""),
                row.get("owner_path", ""),
                row.get("module_name", ""),
                row.get("status", ""),
                row.get("reason", ""),
                _j(row.get("candidate_symbol_ids", [])),
                _j(row),
            )
            for index, row in enumerate(data["join_diagnostics"])
        ],
    )

    counts = _expected_counts(data)
    meta = {
        "schema_version": str(SCHEMA_VERSION),
        "reflected_source": data["sources"]["reflected"].as_posix(),
        "compiler_source": data["sources"]["compiler"].as_posix(),
        "join_source": data["sources"]["join"].as_posix(),
        "reflected_manifest_json": _j(data["manifests"]["reflected"]),
        "compiler_manifest_json": _j(data["manifests"]["compiler"]),
        "join_manifest_json": _j(data["manifests"]["join"]),
        "counts_json": _j(counts),
        "parameter_identity_stats_json": _j(
            data["parameter_identity_stats"]
        ),
        "compiler_capture_stats_json": _j({
            "ruleset": str(
                data["manifests"]["compiler"].get("ruleset", "") or ""
            ),
            "parameter_owner_policy": str(
                data["manifests"]["compiler"].get(
                    "parameter_owner_policy", ""
                ) or ""
            ),
            "call_owner_policy": str(
                data["manifests"]["compiler"].get(
                    "call_owner_policy", ""
                ) or ""
            ),
            "parameter_owner_mismatches_rejected": int(
                data["manifests"]["compiler"].get(
                    "parameter_owner_mismatches_rejected", 0
                ) or 0
            ),
            "nested_callable_calls_suppressed": int(
                data["manifests"]["compiler"].get(
                    "nested_callable_calls_suppressed", 0
                ) or 0
            ),
        }),
        "call_target_stats_json": _j(data["call_target_stats"]),
    }
    conn.executemany(
        "INSERT INTO native_index_meta(key,value) VALUES(?,?)",
        sorted(meta.items()),
    )
    _verify_database_counts(conn, counts)
    return counts


def import_database(
    database: Path,
    reflected_output: Path,
    compiler_output: Path,
    join_output: Path,
) -> dict[str, int]:
    database = Path(database).expanduser().resolve()
    if not database.is_file():
        raise RuntimeError(
            "standard uat.db does not exist; build/pack the normal .uatool "
            f"output first: {database}"
        )
    conn = sqlite3.connect(database)
    try:
        counts = load_database(
            conn,
            reflected_output,
            compiler_output,
            join_output,
        )
        conn.commit()
        conn.execute("PRAGMA optimize")
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def read_parameter_identity_stats(database: Path) -> dict[str, int]:
    database = Path(database).expanduser().resolve()
    conn = sqlite3.connect(database)
    try:
        row = conn.execute(
            """SELECT value FROM native_index_meta
               WHERE key='parameter_identity_stats_json'"""
        ).fetchone()
        if row is None:
            return {}
        value = _json_value(row[0], {})
        if not isinstance(value, dict):
            return {}
        return {
            str(key): int(count or 0)
            for key, count in value.items()
        }
    finally:
        conn.close()


def _compiler_capture_stats_from_conn(
    conn: sqlite3.Connection,
) -> dict:
    row = conn.execute(
        """SELECT value FROM native_index_meta
           WHERE key='compiler_capture_stats_json'"""
    ).fetchone()
    if row is not None:
        value = _json_value(row[0], {})
        if isinstance(value, dict):
            return value

    # Compatibility with a cache imported immediately before this derived
    # convenience key existed: the full authoritative compiler manifest was
    # already retained in native_index_meta.
    row = conn.execute(
        """SELECT value FROM native_index_meta
           WHERE key='compiler_manifest_json'"""
    ).fetchone()
    if row is None:
        return {}
    manifest = _json_value(row[0], {})
    if not isinstance(manifest, dict):
        return {}
    return {
        "ruleset": str(manifest.get("ruleset", "") or ""),
        "parameter_owner_policy": str(
            manifest.get("parameter_owner_policy", "") or ""
        ),
        "call_owner_policy": str(
            manifest.get("call_owner_policy", "") or ""
        ),
        "parameter_owner_mismatches_rejected": int(
            manifest.get("parameter_owner_mismatches_rejected", 0) or 0
        ),
        "nested_callable_calls_suppressed": int(
            manifest.get("nested_callable_calls_suppressed", 0) or 0
        ),
    }


def read_compiler_capture_stats(database: Path) -> dict:
    database = Path(database).expanduser().resolve()
    conn = sqlite3.connect(database)
    try:
        return _compiler_capture_stats_from_conn(conn)
    finally:
        conn.close()


def read_call_target_stats(database: Path) -> dict[str, int]:
    database = Path(database).expanduser().resolve()
    conn = sqlite3.connect(database)
    try:
        row = conn.execute(
            """SELECT value FROM native_index_meta
               WHERE key='call_target_stats_json'"""
        ).fetchone()
        if row is None:
            return {}
        value = _json_value(row[0], {})
        if not isinstance(value, dict):
            return {}
        return {
            str(key): int(count or 0)
            for key, count in value.items()
        }
    finally:
        conn.close()


def has_native_index(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='native_compiler_symbols'"""
    ).fetchone()
    if not row:
        return False
    return bool(
        conn.execute(
            "SELECT 1 FROM native_compiler_symbols LIMIT 1"
        ).fetchone()
    )


def query(
    conn: sqlite3.Connection,
    print_rows,
    pattern: str,
    limit: int,
) -> None:
    if not has_native_index(conn):
        return

    print("\n[native reflected types]")
    print_rows(
        conn.execute(
            """SELECT type_path,module_name,kind,cpp_name
               FROM native_reflected_types
               WHERE type_path LIKE ? OR module_name LIKE ?
                  OR name LIKE ? OR cpp_name LIKE ?
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, limit),
        ),
        ("type_path", "module_name", "kind", "cpp_name"),
    )

    print("\n[native type joins]")
    print_rows(
        conn.execute(
            """SELECT reflected_type_path,reflected_cpp_name,
                      source_qualified_name,source_path,source_line,
                      source_clang_usr,proof
               FROM native_type_joins
               WHERE reflected_type_path LIKE ?
                  OR reflected_module_name LIKE ?
                  OR reflected_cpp_name LIKE ?
                  OR source_symbol_id LIKE ?
                  OR source_clang_usr LIKE ?
                  OR source_qualified_name LIKE ?
                  OR source_path LIKE ?
               LIMIT ?""",
            (
                pattern, pattern, pattern, pattern,
                pattern, pattern, pattern, limit,
            ),
        ),
        (
            "reflected_type_path",
            "reflected_cpp_name",
            "source_qualified_name",
            "source_path",
            "source_line",
            "source_clang_usr",
            "proof",
        ),
    )

    print("\n[native reflected functions]")
    print_rows(
        conn.execute(
            """SELECT function_path,owner_path,module_name,name,
                      parameter_count,delegate
               FROM native_reflected_functions
               WHERE function_path LIKE ? OR owner_path LIKE ?
                  OR module_name LIKE ? OR name LIKE ?
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, limit),
        ),
        (
            "function_path",
            "owner_path",
            "module_name",
            "name",
            "parameter_count",
            "delegate",
        ),
    )

    print("\n[native function joins]")
    print_rows(
        conn.execute(
            """SELECT reflected_function_path,source_qualified_name,
                      source_path,source_line,source_clang_usr,proof
               FROM native_function_joins
               WHERE reflected_function_path LIKE ?
                  OR reflected_owner_path LIKE ?
                  OR reflected_name LIKE ?
                  OR source_symbol_id LIKE ?
                  OR source_clang_usr LIKE ?
                  OR source_qualified_name LIKE ?
                  OR source_path LIKE ?
               LIMIT ?""",
            (
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                limit,
            ),
        ),
        (
            "reflected_function_path",
            "source_qualified_name",
            "source_path",
            "source_line",
            "source_clang_usr",
            "proof",
        ),
    )

    print("\n[native compiler symbols]")
    print_rows(
        conn.execute(
            """SELECT symbol_id,clang_usr,kind,qualified_name,
                      source_path,line,is_definition
               FROM native_compiler_symbols
               WHERE symbol_id LIKE ? OR clang_usr LIKE ?
                  OR name LIKE ? OR qualified_name LIKE ?
                  OR source_path LIKE ? OR translation_unit LIKE ?
               LIMIT ?""",
            (
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                limit,
            ),
        ),
        (
            "symbol_id",
            "clang_usr",
            "kind",
            "qualified_name",
            "source_path",
            "line",
            "is_definition",
        ),
    )

    print("\n[native compiler calls]")
    print_rows(
        conn.execute(
            """SELECT c.call_id,c.source_path,c.line,
                      COALESCE(
                        (SELECT s.qualified_name
                         FROM native_compiler_symbols s
                         WHERE s.symbol_id=c.caller_symbol_id
                         ORDER BY s.is_definition DESC,s.source_path,s.line
                         LIMIT 1),
                        c.caller_symbol_id
                      ) AS caller,
                      COALESCE(
                        (SELECT s.qualified_name
                         FROM native_compiler_symbols s
                         WHERE s.symbol_id=c.target_symbol_id
                         ORDER BY s.is_definition DESC,s.source_path,s.line
                         LIMIT 1),
                        (SELECT s.qualified_name
                         FROM native_compiler_symbols s
                         WHERE c.target_usr<>'' AND s.clang_usr=c.target_usr
                         ORDER BY s.is_definition DESC,s.source_path,s.line
                         LIMIT 1),
                        c.target_name
                      ) AS callee,
                      CASE WHEN EXISTS(
                        SELECT 1 FROM native_compiler_symbols s
                        WHERE s.symbol_id=c.target_symbol_id
                           OR (c.target_usr<>'' AND s.clang_usr=c.target_usr)
                      ) THEN 1 ELSE 0 END AS target_materialized,
                      c.target_usr,c.resolution,c.translation_unit
               FROM native_compiler_calls c
               WHERE c.call_id LIKE ?
                  OR c.caller_symbol_id LIKE ?
                  OR c.target_symbol_id LIKE ?
                  OR c.target_usr LIKE ?
                  OR c.target_name LIKE ?
                  OR c.source_path LIKE ?
                  OR c.translation_unit LIKE ?
                  OR EXISTS(
                       SELECT 1 FROM native_compiler_symbols s
                       WHERE s.symbol_id=c.caller_symbol_id
                         AND (s.qualified_name LIKE ? OR s.name LIKE ?)
                  )
                  OR EXISTS(
                       SELECT 1 FROM native_compiler_symbols s
                       WHERE (
                            s.symbol_id=c.target_symbol_id
                            OR (c.target_usr<>'' AND s.clang_usr=c.target_usr)
                       )
                         AND (s.qualified_name LIKE ? OR s.name LIKE ?)
                  )
               LIMIT ?""",
            (
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                limit,
            ),
        ),
        (
            "call_id",
            "source_path",
            "line",
            "caller",
            "callee",
            "target_materialized",
            "target_usr",
            "resolution",
            "translation_unit",
        ),
    )

    print("\n[native join diagnostics]")
    print_rows(
        conn.execute(
            """SELECT kind,reflected_type_path,reflected_function_path,
                      status,reason
               FROM native_join_diagnostics
               WHERE reflected_type_path LIKE ?
                  OR reflected_function_path LIKE ?
                  OR owner_path LIKE ? OR module_name LIKE ?
                  OR status LIKE ? OR reason LIKE ?
               LIMIT ?""",
            (
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                pattern,
                limit,
            ),
        ),
        (
            "kind",
            "reflected_type_path",
            "reflected_function_path",
            "status",
            "reason",
        ),
    )


def _row_dict(row) -> dict:
    if row is None:
        return {}
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return dict(row)


def _json_value(value: str, fallback):
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback
    return parsed


def _representative_symbol(
    conn: sqlite3.Connection,
    symbol_id: str,
) -> dict:
    row = conn.execute(
        """SELECT * FROM native_compiler_symbols
           WHERE symbol_id=?
           ORDER BY is_definition DESC,source_path,line,column,occurrence_id
           LIMIT 1""",
        (symbol_id,),
    ).fetchone()
    return _row_dict(row)


def _symbol_brief(
    conn: sqlite3.Connection,
    symbol_id: str,
) -> dict:
    row = _representative_symbol(conn, symbol_id)
    if not row:
        return {}
    return {
        "symbol_id": row["symbol_id"],
        "occurrence_id": row["occurrence_id"],
        "clang_usr": row["clang_usr"],
        "kind": row["kind"],
        "name": row["name"],
        "qualified_name": row["qualified_name"],
        "type_spelling": row["type_spelling"],
        "source_path": row["source_path"],
        "line": row["line"],
        "column": row["column"],
        "is_definition": bool(row["is_definition"]),
        "compatibility_overrides": _json_value(
            row["compatibility_overrides_json"], []
        ),
        "evidence": row["evidence"],
    }


def _symbol_brief_by_usr(
    conn: sqlite3.Connection,
    clang_usr: str,
) -> dict:
    if not clang_usr:
        return {}
    row = conn.execute(
        """SELECT symbol_id FROM native_compiler_symbols
           WHERE clang_usr=?
           ORDER BY is_definition DESC,source_path,line,column,occurrence_id
           LIMIT 1""",
        (clang_usr,),
    ).fetchone()
    if row is None:
        return {}
    return _symbol_brief(conn, str(row["symbol_id"]))


def _resolve_reflected_function(
    conn: sqlite3.Connection,
    term: str,
) -> tuple[str, list[dict]]:
    rows = conn.execute(
        """SELECT function_path,owner_path,module_name,name,json
           FROM native_reflected_functions
           WHERE function_path=? OR name=?
           ORDER BY function_path""",
        (term, term),
    ).fetchall()
    by_path = {
        str(row["function_path"]): _row_dict(row)
        for row in rows
    }
    if len(by_path) == 1:
        return "resolved", list(by_path.values())
    if len(by_path) > 1:
        return "ambiguous", list(by_path.values())
    return "not_found", []


def _resolve_source_symbol(
    conn: sqlite3.Connection,
    term: str,
) -> tuple[str, list[dict]]:
    rows = conn.execute(
        """SELECT symbol_id FROM native_compiler_symbols
           WHERE symbol_id=? OR clang_usr=? OR qualified_name=? OR name=?
           ORDER BY symbol_id""",
        (term, term, term, term),
    ).fetchall()
    symbol_ids = sorted({
        str(row["symbol_id"])
        for row in rows
        if row["symbol_id"]
    })
    candidates = [
        _symbol_brief(conn, symbol_id)
        for symbol_id in symbol_ids
    ]
    if len(candidates) == 1:
        return "resolved", candidates
    if len(candidates) > 1:
        return "ambiguous", candidates
    return "not_found", []


def _join_dict(row) -> dict:
    value = _row_dict(row)
    if not value:
        return {}
    for key in (
        "reflected_parameter_signature_json",
        "accepted_source_parameter_types_json",
        "source_occurrence_ids_json",
        "source_parameter_signature_json",
        "compatibility_overrides_json",
    ):
        if key in value:
            value[key.removesuffix("_json")] = _json_value(
                value.pop(key), []
            )
    value.pop("json", None)
    return value


def _diagnostics_for_function(
    conn: sqlite3.Connection,
    function_path: str,
) -> list[dict]:
    rows = conn.execute(
        """SELECT json FROM native_join_diagnostics
           WHERE reflected_function_path=?
           ORDER BY diagnostic_index""",
        (function_path,),
    ).fetchall()
    return [
        _json_value(row["json"], {})
        for row in rows
    ]


def _call_edge(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    direction: str,
) -> dict:
    value = {
        "call_id": row["call_id"],
        "source_path": row["source_path"],
        "line": row["line"],
        "column": row["column"],
        "translation_unit": row["translation_unit"],
        "resolution": row["resolution"],
        "compatibility_overrides": _json_value(
            row["compatibility_overrides_json"], []
        ),
    }
    if direction == "callee":
        target_symbol_id = str(row["target_symbol_id"] or "")
        target_usr = str(row["target_usr"] or "")
        target = (
            _symbol_brief(conn, target_symbol_id)
            if target_symbol_id
            else {}
        )
        target_resolution_basis = "symbol_id" if target else ""
        if not target and target_usr:
            target = _symbol_brief_by_usr(conn, target_usr)
            if target:
                target_resolution_basis = "clang_usr"
        if not target_resolution_basis and target_symbol_id:
            target_resolution_basis = "unmaterialized_project_cursor"
        elif not target_resolution_basis:
            target_resolution_basis = "external_or_unmaterialized"
        value.update({
            "target_symbol_id": target_symbol_id,
            "target_usr": target_usr,
            "target_name": (
                target.get("qualified_name")
                or row["target_name"]
            ),
            "target_kind": row["target_kind"],
            "target_type_spelling": row["target_type_spelling"],
            "project_owned_target": bool(target_symbol_id),
            "target_materialized": bool(target),
            "target_resolution_basis": target_resolution_basis,
            "target_source_path": target.get("source_path", ""),
            "target_source_line": target.get("line", 0),
        })
    else:
        caller_symbol_id = str(row["caller_symbol_id"] or "")
        caller = _symbol_brief(conn, caller_symbol_id)
        value.update({
            "caller_symbol_id": caller_symbol_id,
            "caller_usr": caller.get("clang_usr", ""),
            "caller_name": (
                caller.get("qualified_name")
                or caller.get("name", "")
                or caller_symbol_id
            ),
            "caller_source_path": caller.get("source_path", ""),
            "caller_source_line": caller.get("line", 0),
        })
    return value


def build_report(
    conn: sqlite3.Connection,
    term: str,
    *,
    include_callers: bool = True,
    include_callees: bool = True,
    limit: int = 80,
) -> dict:
    if limit < 0:
        raise ValueError("limit must be >= 0")
    if conn.row_factory is not sqlite3.Row:
        conn.row_factory = sqlite3.Row
    if not has_native_index(conn):
        return {
            "query": term,
            "status": "no_native_index",
            "message": "uat.db has no imported native semantic rows",
        }

    reflected_status, reflected_candidates = _resolve_reflected_function(
        conn, term
    )
    if reflected_status == "ambiguous":
        return {
            "query": term,
            "status": "ambiguous",
            "candidate_kind": "reflected_function",
            "candidates": reflected_candidates,
        }

    reflected_function = (
        reflected_candidates[0]
        if reflected_status == "resolved"
        else {}
    )
    symbol_id = ""
    join = {}

    if reflected_function:
        function_path = str(reflected_function["function_path"])
        join_row = conn.execute(
            """SELECT * FROM native_function_joins
               WHERE reflected_function_path=?""",
            (function_path,),
        ).fetchone()
        join = _join_dict(join_row)
        if not join:
            return {
                "query": term,
                "status": "unresolved",
                "reflected_function": _json_value(
                    reflected_function["json"], {}
                ),
                "diagnostics": _diagnostics_for_function(
                    conn, function_path
                ),
            }
        symbol_id = str(join["source_symbol_id"])
    else:
        source_status, source_candidates = _resolve_source_symbol(
            conn, term
        )
        if source_status == "ambiguous":
            return {
                "query": term,
                "status": "ambiguous",
                "candidate_kind": "compiler_symbol",
                "candidates": source_candidates,
            }
        if source_status != "resolved":
            return {
                "query": term,
                "status": "not_found",
            }
        symbol_id = str(source_candidates[0]["symbol_id"])
        reverse_join = conn.execute(
            """SELECT * FROM native_function_joins
               WHERE source_symbol_id=?
               ORDER BY reflected_function_path
               LIMIT 1""",
            (symbol_id,),
        ).fetchone()
        join = _join_dict(reverse_join)
        if join:
            reflected_row = conn.execute(
                """SELECT json FROM native_reflected_functions
                   WHERE function_path=?""",
                (join["reflected_function_path"],),
            ).fetchone()
            if reflected_row:
                reflected_function = {
                    "json": reflected_row["json"],
                }

    source = _symbol_brief(conn, symbol_id)
    if not source:
        return {
            "query": term,
            "status": "broken_join",
            "source_symbol_id": symbol_id,
            "join": join,
        }

    occurrence_rows = conn.execute(
        """SELECT occurrence_id,source_path,line,column,is_definition,
                  translation_unit,compatibility_overrides_json,evidence
           FROM native_compiler_symbols
           WHERE symbol_id=?
           ORDER BY is_definition DESC,source_path,line,column,occurrence_id""",
        (symbol_id,),
    ).fetchall()
    occurrences = [
        {
            "occurrence_id": row["occurrence_id"],
            "source_path": row["source_path"],
            "line": row["line"],
            "column": row["column"],
            "is_definition": bool(row["is_definition"]),
            "translation_unit": row["translation_unit"],
            "compatibility_overrides": _json_value(
                row["compatibility_overrides_json"], []
            ),
            "evidence": row["evidence"],
        }
        for row in occurrence_rows
    ]

    parameters = [
        _json_value(row["json"], {})
        for row in conn.execute(
            """SELECT json FROM native_compiler_parameters
               WHERE function_occurrence_id=?
               ORDER BY parameter_index,line,column,name,type_spelling""",
            (source["occurrence_id"],),
        ).fetchall()
    ]

    result = {
        "query": term,
        "status": "joined" if join else "source",
        "reflected_function": (
            _json_value(reflected_function.get("json", ""), {})
            if reflected_function
            else {}
        ),
        "join": join,
        "source": source,
        "occurrences": occurrences,
        "parameters": parameters,
        "callee_count": 0,
        "caller_count": 0,
        "callees": [],
        "callers": [],
    }

    if include_callees:
        result["callee_count"] = int(
            conn.execute(
                """SELECT COUNT(*) FROM native_compiler_calls
                   WHERE caller_symbol_id=?""",
                (symbol_id,),
            ).fetchone()[0]
        )
        call_rows = conn.execute(
            """SELECT * FROM native_compiler_calls
               WHERE caller_symbol_id=?
               ORDER BY source_path,line,column,call_id
               LIMIT ?""",
            (symbol_id, limit),
        ).fetchall()
        result["callees"] = [
            _call_edge(conn, row, "callee")
            for row in call_rows
        ]

    if include_callers:
        source_usr = str(source.get("clang_usr", "") or "")
        result["caller_count"] = int(
            conn.execute(
                """SELECT COUNT(*) FROM native_compiler_calls
                   WHERE target_symbol_id=?
                      OR (?<>'' AND target_usr=?)""",
                (symbol_id, source_usr, source_usr),
            ).fetchone()[0]
        )
        call_rows = conn.execute(
            """SELECT * FROM native_compiler_calls
               WHERE target_symbol_id=?
                  OR (?<>'' AND target_usr=?)
               ORDER BY source_path,line,column,call_id
               LIMIT ?""",
            (symbol_id, source_usr, source_usr, limit),
        ).fetchall()
        result["callers"] = [
            _call_edge(conn, row, "caller")
            for row in call_rows
        ]

    return result


def build_audit(
    conn: sqlite3.Connection,
    *,
    limit: int = 100,
) -> dict:
    if limit < 0:
        raise ValueError("limit must be >= 0")
    if conn.row_factory is not sqlite3.Row:
        conn.row_factory = sqlite3.Row
    if not has_native_index(conn):
        return {
            "status": "no_native_index",
            "message": "uat.db has no imported native semantic rows",
        }

    compiler_capture = _compiler_capture_stats_from_conn(conn)

    joined_rows = conn.execute(
        """SELECT reflected_function_path,source_symbol_id,
                  source_qualified_name,source_path,source_line,proof
           FROM native_function_joins
           ORDER BY reflected_function_path
           LIMIT ?""",
        (limit,),
    ).fetchall()
    joined_functions = [_row_dict(row) for row in joined_rows]

    unresolved_rows = conn.execute(
        """SELECT reflected_function_path,status,reason,json
           FROM native_join_diagnostics
           WHERE kind='function_join'
           ORDER BY reflected_function_path
           LIMIT ?""",
        (limit,),
    ).fetchall()
    unresolved_functions = [
        {
            "reflected_function_path": row["reflected_function_path"],
            "status": row["status"],
            "reason": row["reason"],
            "diagnostic": _json_value(row["json"], {}),
        }
        for row in unresolved_rows
    ]

    duplicate_groups = conn.execute(
        """SELECT function_occurrence_id,parameter_index,
                  MIN(function_symbol_id) AS function_symbol_id,
                  COUNT(*) AS row_count
           FROM native_compiler_parameters
           GROUP BY function_occurrence_id,parameter_index
           HAVING COUNT(*) > 1
           ORDER BY row_count DESC,function_occurrence_id,parameter_index
           LIMIT ?""",
        (limit,),
    ).fetchall()
    duplicate_parameter_slots: list[dict] = []
    for group in duplicate_groups:
        rows = conn.execute(
            """SELECT name,type_spelling,source_path,line,column,
                      translation_unit,evidence
               FROM native_compiler_parameters
               WHERE function_occurrence_id=? AND parameter_index=?
               ORDER BY line,column,name,type_spelling""",
            (
                group["function_occurrence_id"],
                group["parameter_index"],
            ),
        ).fetchall()
        symbol = _symbol_brief(
            conn,
            str(group["function_symbol_id"] or ""),
        )
        duplicate_parameter_slots.append({
            "function_occurrence_id": group["function_occurrence_id"],
            "function_symbol_id": group["function_symbol_id"],
            "function_name": (
                symbol.get("qualified_name")
                or symbol.get("name", "")
            ),
            "parameter_index": group["parameter_index"],
            "row_count": group["row_count"],
            "rows": [_row_dict(row) for row in rows],
        })

    target_groups = conn.execute(
        """SELECT c.target_symbol_id,c.target_usr,c.target_kind,
                  c.target_name,c.target_type_spelling,
                  COUNT(*) AS call_count,
                  COUNT(DISTINCT c.caller_symbol_id) AS caller_symbol_count,
                  MIN(c.source_path) AS sample_source_path,
                  MIN(c.line) AS sample_line
           FROM native_compiler_calls c
           WHERE c.target_symbol_id <> ''
             AND NOT EXISTS(
                 SELECT 1 FROM native_compiler_symbols s
                 WHERE s.symbol_id=c.target_symbol_id
             )
             AND NOT EXISTS(
                 SELECT 1 FROM native_compiler_symbols s
                 WHERE c.target_usr<>'' AND s.clang_usr=c.target_usr
             )
           GROUP BY c.target_symbol_id,c.target_usr,c.target_kind,
                    c.target_name,c.target_type_spelling
           ORDER BY call_count DESC,c.target_name,c.target_symbol_id
           LIMIT ?""",
        (limit,),
    ).fetchall()
    unmaterialized_project_targets = [
        _row_dict(row)
        for row in target_groups
    ]

    counts = {
        "joined_functions": int(
            conn.execute(
                "SELECT COUNT(*) FROM native_function_joins"
            ).fetchone()[0]
        ),
        "function_diagnostics": int(
            conn.execute(
                """SELECT COUNT(*) FROM native_join_diagnostics
                   WHERE kind='function_join'"""
            ).fetchone()[0]
        ),
        "duplicate_parameter_slots": int(
            conn.execute(
                """SELECT COUNT(*) FROM (
                     SELECT 1 FROM native_compiler_parameters
                     GROUP BY function_occurrence_id,parameter_index
                     HAVING COUNT(*) > 1
                   )"""
            ).fetchone()[0]
        ),
        "unmaterialized_project_target_calls": int(
            conn.execute(
                """SELECT COUNT(*) FROM native_compiler_calls c
                   WHERE c.target_symbol_id <> ''
                     AND NOT EXISTS(
                         SELECT 1 FROM native_compiler_symbols s
                         WHERE s.symbol_id=c.target_symbol_id
                     )
                     AND NOT EXISTS(
                         SELECT 1 FROM native_compiler_symbols s
                         WHERE c.target_usr<>'' AND s.clang_usr=c.target_usr
                     )"""
            ).fetchone()[0]
        ),
        "unmaterialized_project_target_identities": int(
            conn.execute(
                """SELECT COUNT(*) FROM (
                     SELECT c.target_symbol_id,c.target_usr,c.target_kind,
                            c.target_name,c.target_type_spelling
                     FROM native_compiler_calls c
                     WHERE c.target_symbol_id <> ''
                       AND NOT EXISTS(
                           SELECT 1 FROM native_compiler_symbols s
                           WHERE s.symbol_id=c.target_symbol_id
                       )
                       AND NOT EXISTS(
                           SELECT 1 FROM native_compiler_symbols s
                           WHERE c.target_usr<>'' AND s.clang_usr=c.target_usr
                       )
                     GROUP BY c.target_symbol_id,c.target_usr,c.target_kind,
                              c.target_name,c.target_type_spelling
                   )"""
            ).fetchone()[0]
        ),
    }
    return {
        "status": "ok",
        "limit": limit,
        "counts": counts,
        "compiler_capture": compiler_capture,
        "joined_functions": joined_functions,
        "unresolved_functions": unresolved_functions,
        "duplicate_parameter_slots": duplicate_parameter_slots,
        "unmaterialized_project_targets": unmaterialized_project_targets,
    }


def print_audit(report: dict) -> None:
    print("=== NATIVE INDEX AUDIT ===")
    print(f"Status: {report.get('status', '')}")
    if report.get("status") != "ok":
        print(report.get("message", ""))
        return

    counts = report.get("counts", {})
    capture = report.get("compiler_capture", {})
    if capture:
        print(
            "Compiler capture: "
            f"ruleset={capture.get('ruleset', '')} "
            "parameter_owner_mismatches_rejected="
            f"{capture.get('parameter_owner_mismatches_rejected', 0)} "
            "nested_callable_calls_suppressed="
            f"{capture.get('nested_callable_calls_suppressed', 0)}"
        )

    print(
        "Counts: "
        f"joined_functions={counts.get('joined_functions', 0)} "
        f"function_diagnostics={counts.get('function_diagnostics', 0)} "
        f"duplicate_parameter_slots={counts.get('duplicate_parameter_slots', 0)} "
        "unmaterialized_project_target_calls="
        f"{counts.get('unmaterialized_project_target_calls', 0)} "
        "unmaterialized_project_target_identities="
        f"{counts.get('unmaterialized_project_target_identities', 0)}"
    )

    joined = report.get("joined_functions", [])
    print(
        f"Joined reflected functions: {counts.get('joined_functions', 0)} "
        f"(showing {len(joined)})"
    )
    for row in joined:
        print(
            "  "
            f"{row.get('reflected_function_path', '')} -> "
            f"{row.get('source_qualified_name', '')} "
            f"[{row.get('source_path', '')}:"
            f"{row.get('source_line', 0)}]"
        )

    unresolved = report.get("unresolved_functions", [])
    print(
        f"Function join diagnostics: "
        f"{counts.get('function_diagnostics', 0)} "
        f"(showing {len(unresolved)})"
    )
    for row in unresolved:
        print(
            "  "
            f"{row.get('reflected_function_path', '')}: "
            f"{row.get('status', '')} - {row.get('reason', '')}"
        )

    duplicates = report.get("duplicate_parameter_slots", [])
    print(
        f"Duplicate numeric parameter-index slots: "
        f"{counts.get('duplicate_parameter_slots', 0)} "
        f"(showing {len(duplicates)})"
    )
    for group in duplicates:
        print(
            "  "
            f"{group.get('function_name', '')} "
            f"[occurrence={group.get('function_occurrence_id', '')}] "
            f"index={group.get('parameter_index', 0)} "
            f"rows={group.get('row_count', 0)}"
        )
        for row in group.get("rows", []):
            print(
                "    "
                f"{row.get('name', '')}: {row.get('type_spelling', '')} "
                f"[{row.get('source_path', '')}:"
                f"{row.get('line', 0)}]"
            )

    targets = report.get("unmaterialized_project_targets", [])
    print(
        "Unmaterialized project call targets: "
        f"{counts.get('unmaterialized_project_target_calls', 0)} calls / "
        f"{counts.get('unmaterialized_project_target_identities', 0)} "
        f"identities (showing {len(targets)})"
    )
    for row in targets:
        print(
            "  "
            f"{row.get('target_name', '')} "
            f"[{row.get('target_kind', '')}] "
            f"id={row.get('target_symbol_id', '')} "
            f"usr={row.get('target_usr', '') or '<none>'} "
            f"calls={row.get('call_count', 0)} "
            f"callers={row.get('caller_symbol_count', 0)} "
            f"sample={row.get('sample_source_path', '')}:"
            f"{row.get('sample_line', 0)}"
        )


def print_report(report: dict) -> None:
    print("=== NATIVE PROGRAM REPORT ===")
    print(f"Query: {report.get('query', '')}")
    print(f"Status: {report.get('status', '')}")

    status = report.get("status")
    if status == "no_native_index":
        print(report.get("message", ""))
        return
    if status == "not_found":
        print("No exact reflected function or compiler symbol matched.")
        return
    if status == "ambiguous":
        print(
            "Exact lookup is ambiguous; no semantic identity was chosen."
        )
        for candidate in report.get("candidates", []):
            if "function_path" in candidate:
                print(f"  {candidate.get('function_path', '')}")
            else:
                print(
                    "  "
                    f"{candidate.get('qualified_name', '')} "
                    f"[{candidate.get('symbol_id', '')}] "
                    f"{candidate.get('source_path', '')}:"
                    f"{candidate.get('line', 0)}"
                )
        return
    if status == "unresolved":
        reflected = report.get("reflected_function", {})
        print(
            "Reflected: "
            f"{reflected.get('function_path', report.get('query', ''))}"
        )
        print("Source join: unresolved")
        for diagnostic in report.get("diagnostics", []):
            print(
                "  "
                f"{diagnostic.get('status', '')}: "
                f"{diagnostic.get('reason', '')}"
            )
            observed = diagnostic.get("observed_parameter_signatures")
            if observed:
                print(f"  observed signatures: {_j(observed)}")
        return

    reflected = report.get("reflected_function", {})
    if reflected:
        print(
            "Reflected: "
            f"{reflected.get('function_path', '')}"
        )

    join = report.get("join", {})
    if join:
        print(f"Join proof: {join.get('proof', '')}")
    elif status == "source":
        print(
            "Reflected join: <none; exact compiler symbol is source-only>"
        )

    source = report.get("source", {})
    print(
        "Source: "
        f"{source.get('qualified_name') or source.get('name', '')}"
    )
    print(f"Symbol ID: {source.get('symbol_id', '')}")
    print(f"Clang USR: {source.get('clang_usr', '')}")
    print(
        "Definition: "
        f"{source.get('source_path', '')}:"
        f"{source.get('line', 0)}"
    )
    print(f"Type: {source.get('type_spelling', '')}")
    overrides = source.get("compatibility_overrides", [])
    print(
        "Compatibility overrides: "
        + (", ".join(overrides) if overrides else "<none>")
    )

    parameters = report.get("parameters", [])
    print(f"Parameters: {len(parameters)}")
    for row in parameters:
        print(
            "  "
            f"[{row.get('parameter_index', 0)}] "
            f"{row.get('name', '')}: "
            f"{row.get('type_spelling', '')}"
        )

    if "callees" in report:
        print(
            f"Callees: {report.get('callee_count', 0)} "
            f"(showing {len(report.get('callees', []))})"
        )
        for edge in report.get("callees", []):
            ownership = (
                "project"
                if edge.get("project_owned_target")
                else "external"
            )
            materialized = (
                edge.get("target_resolution_basis", "")
                if edge.get("target_materialized")
                else "unmaterialized"
            )
            print(
                "  "
                f"{edge.get('source_path', '')}:"
                f"{edge.get('line', 0)} -> "
                f"{edge.get('target_name', '')} "
                f"[{ownership}; {materialized}]"
            )

    if "callers" in report:
        print(
            f"Callers: {report.get('caller_count', 0)} "
            f"(showing {len(report.get('callers', []))})"
        )
        for edge in report.get("callers", []):
            print(
                "  "
                f"{edge.get('source_path', '')}:"
                f"{edge.get('line', 0)} <- "
                f"{edge.get('caller_name', '')}"
            )
