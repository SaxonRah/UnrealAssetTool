#!/usr/bin/env python3
"""Exact joins between reflected native schema 1 and compiler source schema 1."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import uatool_native as reflected_native
import uatool_native_ast as native_ast

SCHEMA_VERSION = 1
PASS_NAME = "UnrealAssetToolNativeJoin"
MANIFEST = "native_join_manifest.json"
TYPE_JOINS = "native_type_joins.jsonl"
FUNCTION_JOINS = "native_function_joins.jsonl"
DIAGNOSTICS = "native_join_diagnostics.jsonl"

OUTPUT_FILES = (TYPE_JOINS, FUNCTION_JOINS, DIAGNOSTICS)


def _stable_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _rows(path: Path) -> list[dict]:
    result: list[dict] = []
    if not path.is_file():
        return result
    with path.open("r", encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError(
                    f"expected JSON object in {path}:{line_number}"
                )
            result.append(value)
    return result


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(
                json.dumps(row, sort_keys=True, separators=(",", ":"))
                + "\n"
            )


def _validate_ast_input(output: Path) -> dict:
    manifest_path = output / native_ast.MANIFEST
    if not manifest_path.is_file():
        raise RuntimeError("native AST manifest missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if int(manifest.get("schema_version", 0) or 0) != native_ast.SCHEMA_VERSION:
        raise RuntimeError(
            "native AST schema version mismatch: "
            f"{manifest.get('schema_version')}"
        )
    if manifest.get("pass") != "UnrealAssetToolNativeAST":
        raise RuntimeError(
            f"unexpected native AST pass {manifest.get('pass')!r}"
        )
    if not manifest.get("success"):
        raise RuntimeError(
            f"native AST capture failed: {manifest.get('error', '')}"
        )
    for filename in (
        native_ast.SYMBOLS,
        native_ast.PARAMETERS,
        native_ast.CALLS,
    ):
        if not (output / filename).is_file():
            raise RuntimeError(f"native AST stream missing: {filename}")
    return manifest


def _module_source_root(build_cs: str) -> str:
    path = str(build_cs or "").replace("\\", "/").strip("/")
    if not path.lower().endswith(".build.cs"):
        return ""
    parent = path.rsplit("/", 1)[0] if "/" in path else ""
    return parent.rstrip("/") + "/" if parent else ""


def _inside_module(source_path: str, module_root: str) -> bool:
    source = str(source_path or "").replace("\\", "/")
    return bool(module_root) and source.lower().startswith(module_root.lower())


def _normalize_cpp_type(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\b(class|struct|enum)\s+", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*::\s*", "::", text)
    text = re.sub(r"\s*([<>,*&])\s*", r"\1", text)
    text = re.sub(r"\s*\[\s*", "[", text)
    text = re.sub(r"\s*\]\s*", "]", text)
    return text.strip()


def _reflected_parameter_type(row: dict) -> str:
    """Canonical reflected spelling before UHT passing-mode projection."""
    text = str(row.get("cpp_type", "") or "")
    normalized = _normalize_cpp_type(text)
    if bool(row.get("const_parameter")) and not normalized.startswith("const "):
        normalized = "const " + normalized
    if bool(row.get("reference_parameter")) and not normalized.endswith("&"):
        normalized += "&"
    return _normalize_cpp_type(normalized)


def _reflected_parameter_source_types(row: dict) -> list[str]:
    """Exact authored spellings that project to this reflected parameter.

    Reflection preserves property type and Parm/OutParm/ReferenceParm/ConstParm
    state, but UHT does not preserve every authored C++ passing convention.
    In schema 1 we model only erasures proven by the real corpus and normal
    UFUNCTION thunk semantics:
      - out/inout parameters are authored as references;
      - explicit ReferenceParm remains a reference;
      - an input FString reflected as StrProperty may be authored by value or
        as const FString&, both of which project to the same reflected shape.

    Candidate source methods still must collapse to one libclang USR identity;
    these alternatives never choose between overloads heuristically.
    """
    base = _normalize_cpp_type(str(row.get("cpp_type", "") or ""))
    if bool(row.get("const_parameter")) and not base.startswith("const "):
        base = "const " + base
    base = _normalize_cpp_type(base)

    parameter_kind = str(row.get("parameter_kind", "") or "")
    if parameter_kind in {"out", "inout"} or bool(
        row.get("reference_parameter")
    ):
        value = base if base.endswith("&") else base + "&"
        return [_normalize_cpp_type(value)]

    if (
        str(row.get("property_class", "") or "") == "StrProperty"
        and not bool(row.get("const_parameter"))
    ):
        return sorted({
            base,
            _normalize_cpp_type(f"const {base}&"),
        })

    return [base]


def _signature_matches_projection(
    source_signature: list[str],
    reflected_options: list[list[str]],
) -> bool:
    return (
        len(source_signature) == len(reflected_options)
        and all(
            source_type in accepted
            for source_type, accepted in zip(
                source_signature, reflected_options
            )
        )
    )


def _source_parameter_signature(
    occurrence_id: str,
    source_parameters: list[dict],
) -> list[str]:
    rows = [
        row
        for row in source_parameters
        if row.get("function_occurrence_id") == occurrence_id
    ]
    rows.sort(key=lambda row: int(row.get("parameter_index", 0) or 0))
    return [
        _normalize_cpp_type(str(row.get("type_spelling", "") or ""))
        for row in rows
    ]


def _proof_compatibility(symbol_rows: list[dict]) -> list[str]:
    values: set[str] = set()
    for row in symbol_rows:
        for value in row.get("compatibility_overrides") or []:
            values.add(str(value))
    return sorted(values)


def _representative_occurrence(rows: list[dict]) -> dict:
    definitions = [row for row in rows if row.get("is_definition")]
    pool = definitions or rows
    return sorted(
        pool,
        key=lambda row: (
            str(row.get("source_path", "")).lower(),
            int(row.get("offset", 0) or 0),
            str(row.get("occurrence_id", "")),
        ),
    )[0]


def capture(
    reflected_output: Path,
    ast_output: Path,
    output: Path,
) -> dict:
    reflected_output = Path(reflected_output).expanduser().resolve()
    ast_output = Path(ast_output).expanduser().resolve()
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    reflected_error = reflected_native.validation_error(reflected_output)
    if reflected_error:
        raise RuntimeError(
            f"reflected native input invalid: {reflected_error}"
        )
    reflected_manifest = reflected_native.read_manifest(reflected_output) or {}
    ast_manifest = _validate_ast_input(ast_output)

    modules = _rows(reflected_output / "native_modules.jsonl")
    reflected_types = _rows(reflected_output / "native_types.jsonl")
    reflected_functions = _rows(reflected_output / "native_functions.jsonl")
    reflected_parameters = _rows(
        reflected_output / "native_function_parameters.jsonl"
    )

    source_symbols = _rows(ast_output / native_ast.SYMBOLS)
    source_parameters = _rows(ast_output / native_ast.PARAMETERS)

    module_roots = {
        str(row.get("module_name", "")): _module_source_root(
            str(row.get("build_cs", ""))
        )
        for row in modules
        if row.get("module_name")
    }

    type_joins: list[dict] = []
    function_joins: list[dict] = []
    diagnostics: list[dict] = []

    type_join_by_path: dict[str, dict] = {}
    type_row_by_path = {
        str(row.get("type_path", "")): row
        for row in reflected_types
        if row.get("type_path")
    }

    record_symbols = [
        row for row in source_symbols
        if row.get("kind") == "record"
        and row.get("language") == "cpp"
        and row.get("clang_usr")
    ]

    for reflected in sorted(
        reflected_types,
        key=lambda row: str(row.get("type_path", "")),
    ):
        type_path = str(reflected.get("type_path", ""))
        module_name = str(reflected.get("module_name", ""))
        cpp_name = str(reflected.get("cpp_name", "") or "")
        module_root = module_roots.get(module_name, "")

        candidates = [
            row for row in record_symbols
            if _inside_module(str(row.get("source_path", "")), module_root)
            and (
                str(row.get("qualified_name", "")) == cpp_name
                or (
                    "::" not in cpp_name
                    and str(row.get("name", "")) == cpp_name
                    and str(row.get("qualified_name", "")) == cpp_name
                )
            )
        ]
        by_symbol: dict[str, list[dict]] = {}
        for row in candidates:
            by_symbol.setdefault(str(row.get("symbol_id", "")), []).append(row)
        by_symbol.pop("", None)

        if len(by_symbol) != 1:
            diagnostics.append({
                "kind": "type_join",
                "reflected_type_path": type_path,
                "reflected_cpp_name": cpp_name,
                "module_name": module_name,
                "status": "unmatched" if not by_symbol else "ambiguous",
                "reason": (
                    "no exact module-scoped compiler record"
                    if not by_symbol
                    else "multiple exact compiler semantic identities"
                ),
                "candidate_symbol_ids": sorted(by_symbol),
            })
            continue

        source_symbol_id, occurrence_rows = next(iter(by_symbol.items()))
        representative = _representative_occurrence(occurrence_rows)
        join = {
            "join_id": _stable_id(
                f"type|{type_path}|{source_symbol_id}"
            ),
            "reflected_type_path": type_path,
            "reflected_kind": str(reflected.get("kind", "")),
            "reflected_module_name": module_name,
            "reflected_cpp_name": cpp_name,
            "source_symbol_id": source_symbol_id,
            "source_clang_usr": str(
                representative.get("clang_usr", "")
            ),
            "source_occurrence_id": str(
                representative.get("occurrence_id", "")
            ),
            "source_occurrence_ids": sorted({
                str(row.get("occurrence_id", ""))
                for row in occurrence_rows
                if row.get("occurrence_id")
            }),
            "source_path": str(representative.get("source_path", "")),
            "source_line": int(representative.get("line", 0) or 0),
            "source_qualified_name": str(
                representative.get("qualified_name", "")
            ),
            "compatibility_overrides": _proof_compatibility(
                occurrence_rows
            ),
            "proof": (
                "module_source_scope+exact_cpp_name+"
                "single_libclang_usr_identity"
            ),
            "evidence": "reflected_native_schema1+libclang_cursor_schema1",
        }
        type_joins.append(join)
        type_join_by_path[type_path] = join

    reflected_params_by_function: dict[str, list[dict]] = {}
    for row in reflected_parameters:
        reflected_params_by_function.setdefault(
            str(row.get("function_path", "")), []
        ).append(row)

    methods = [
        row for row in source_symbols
        if row.get("language") == "cpp"
        and row.get("kind") in {
            "method",
            "function",
            "function_template",
        }
        and row.get("clang_usr")
    ]

    for reflected in sorted(
        reflected_functions,
        key=lambda row: str(row.get("function_path", "")),
    ):
        function_path = str(reflected.get("function_path", ""))
        owner_path = str(reflected.get("owner_path", ""))
        function_name = str(reflected.get("name", "") or "")
        owner_join = type_join_by_path.get(owner_path)
        owner_type = type_row_by_path.get(owner_path)

        if owner_join is None or owner_type is None:
            diagnostics.append({
                "kind": "function_join",
                "reflected_function_path": function_path,
                "owner_path": owner_path,
                "status": "unmatched",
                "reason": "owner type has no proven compiler join",
            })
            continue

        owner_cpp_name = str(owner_type.get("cpp_name", "") or "")
        expected_qualified = f"{owner_cpp_name}::{function_name}"
        module_root = module_roots.get(
            str(reflected.get("module_name", "")), ""
        )

        reflected_params = sorted(
            [
                row
                for row in reflected_params_by_function.get(
                    function_path, []
                )
                if row.get("parameter_kind") != "return"
            ],
            key=lambda row: int(row.get("parameter_index", 0) or 0),
        )
        reflected_signature = [
            _reflected_parameter_type(row)
            for row in reflected_params
        ]
        accepted_source_types = [
            _reflected_parameter_source_types(row)
            for row in reflected_params
        ]

        named_candidates = [
            row for row in methods
            if _inside_module(str(row.get("source_path", "")), module_root)
            and str(row.get("qualified_name", "")) == expected_qualified
        ]

        matches_by_symbol: dict[str, list[tuple[dict, list[str]]]] = {}
        observed_signatures: set[tuple[str, ...]] = set()
        for candidate in named_candidates:
            signature = _source_parameter_signature(
                str(candidate.get("occurrence_id", "")),
                source_parameters,
            )
            observed_signatures.add(tuple(signature))
            if _signature_matches_projection(
                signature,
                accepted_source_types,
            ):
                matches_by_symbol.setdefault(
                    str(candidate.get("symbol_id", "")), []
                ).append((candidate, signature))
        matches_by_symbol.pop("", None)

        if len(matches_by_symbol) != 1:
            diagnostics.append({
                "kind": "function_join",
                "reflected_function_path": function_path,
                "owner_path": owner_path,
                "reflected_name": function_name,
                "status": (
                    "unmatched"
                    if not matches_by_symbol
                    else "ambiguous"
                ),
                "reason": (
                    "no exact owner/name/parameter-signature compiler method"
                    if not matches_by_symbol
                    else "multiple exact compiler semantic identities"
                ),
                "reflected_parameter_signature": reflected_signature,
                "accepted_source_parameter_types": accepted_source_types,
                "observed_parameter_signatures": [
                    list(value)
                    for value in sorted(observed_signatures)
                ],
                "candidate_symbol_ids": sorted(matches_by_symbol),
            })
            continue

        source_symbol_id, matched = next(
            iter(matches_by_symbol.items())
        )
        occurrence_rows = [row for row, _ in matched]
        representative = _representative_occurrence(occurrence_rows)
        join = {
            "join_id": _stable_id(
                f"function|{function_path}|{source_symbol_id}"
            ),
            "reflected_function_path": function_path,
            "reflected_owner_path": owner_path,
            "reflected_module_name": str(
                reflected.get("module_name", "")
            ),
            "reflected_name": function_name,
            "reflected_parameter_signature": reflected_signature,
            "accepted_source_parameter_types": accepted_source_types,
            "source_symbol_id": source_symbol_id,
            "source_clang_usr": str(
                representative.get("clang_usr", "")
            ),
            "source_occurrence_id": str(
                representative.get("occurrence_id", "")
            ),
            "source_occurrence_ids": sorted({
                str(row.get("occurrence_id", ""))
                for row in occurrence_rows
                if row.get("occurrence_id")
            }),
            "source_path": str(representative.get("source_path", "")),
            "source_line": int(representative.get("line", 0) or 0),
            "source_qualified_name": str(
                representative.get("qualified_name", "")
            ),
            "source_parameter_signature": list(matched[0][1]),
            "compatibility_overrides": _proof_compatibility(
                occurrence_rows
            ),
            "proof": (
                "proven_owner_type+exact_qualified_name+"
                "reflection_projection_parameter_match+"
                "single_libclang_usr_identity"
            ),
            "evidence": "reflected_native_schema1+libclang_cursor_schema1",
        }
        function_joins.append(join)

    type_joins.sort(
        key=lambda row: row["reflected_type_path"]
    )
    function_joins.sort(
        key=lambda row: row["reflected_function_path"]
    )
    diagnostics.sort(
        key=lambda row: (
            row.get("kind", ""),
            row.get("reflected_type_path", ""),
            row.get("reflected_function_path", ""),
        )
    )

    _write_jsonl(output / TYPE_JOINS, type_joins)
    _write_jsonl(output / FUNCTION_JOINS, function_joins)
    _write_jsonl(output / DIAGNOSTICS, diagnostics)

    type_unmatched = sum(
        1 for row in diagnostics
        if row.get("kind") == "type_join"
        and row.get("status") == "unmatched"
    )
    type_ambiguous = sum(
        1 for row in diagnostics
        if row.get("kind") == "type_join"
        and row.get("status") == "ambiguous"
    )
    function_unmatched = sum(
        1 for row in diagnostics
        if row.get("kind") == "function_join"
        and row.get("status") == "unmatched"
    )
    function_ambiguous = sum(
        1 for row in diagnostics
        if row.get("kind") == "function_join"
        and row.get("status") == "ambiguous"
    )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pass": PASS_NAME,
        "success": True,
        "error": "",
        "capture_scope": (
            "exact joins between reflected native schema 1 and "
            "compiler-resolved project-owned libclang source schema 1"
        ),
        "reflected_input": reflected_output.as_posix(),
        "reflected_schema_version": reflected_manifest.get(
            "schema_version", 0
        ),
        "compiler_input": ast_output.as_posix(),
        "compiler_schema_version": ast_manifest.get(
            "schema_version", 0
        ),
        "compiler_evidence": ast_manifest.get("evidence", ""),
        "files": list(OUTPUT_FILES),
        "counts": {
            "reflected_types": len(reflected_types),
            "joined_types": len(type_joins),
            "unmatched_types": type_unmatched,
            "ambiguous_types": type_ambiguous,
            "reflected_functions": len(reflected_functions),
            "joined_functions": len(function_joins),
            "unmatched_functions": function_unmatched,
            "ambiguous_functions": function_ambiguous,
            "diagnostics": len(diagnostics),
        },
        "proof_policy": {
            "types": (
                "module source scope + exact cpp_name + "
                "single libclang USR-backed semantic identity"
            ),
            "functions": (
                "proven owner type + exact qualified function name + "
                "exact reflected-to-source parameter projection + "
                "single libclang USR-backed semantic identity"
            ),
            "fuzzy_matching": False,
        },
    }
    (output / MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def validation_error(output: Path) -> str | None:
    output = Path(output)
    manifest_path = output / MANIFEST
    if not manifest_path.is_file():
        return f"{MANIFEST} missing"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return f"{MANIFEST} invalid"
    if int(manifest.get("schema_version", 0) or 0) != SCHEMA_VERSION:
        return "native join schema version mismatch"
    if manifest.get("pass") != PASS_NAME:
        return f"unexpected native join pass {manifest.get('pass')!r}"
    if not manifest.get("success"):
        return f"native join failed: {manifest.get('error', '')}"

    counts = manifest.get("counts", {})
    expected = {
        TYPE_JOINS: "joined_types",
        FUNCTION_JOINS: "joined_functions",
        DIAGNOSTICS: "diagnostics",
    }
    for filename, count_key in expected.items():
        path = output / filename
        if not path.is_file():
            return f"native join stream missing: {filename}"
        actual = len(_rows(path))
        if int(counts.get(count_key, -1)) != actual:
            return (
                f"native join count mismatch for {count_key}: "
                f"manifest={counts.get(count_key)} actual={actual}"
            )
    return None


def print_summary(manifest: dict) -> None:
    counts = manifest.get("counts", {})
    print(
        "native joins: "
        f"types={counts.get('joined_types', 0)}/"
        f"{counts.get('reflected_types', 0)} "
        f"functions={counts.get('joined_functions', 0)}/"
        f"{counts.get('reflected_functions', 0)} "
        f"type_unmatched={counts.get('unmatched_types', 0)} "
        f"type_ambiguous={counts.get('ambiguous_types', 0)} "
        f"function_unmatched={counts.get('unmatched_functions', 0)} "
        f"function_ambiguous={counts.get('ambiguous_functions', 0)}"
    )
