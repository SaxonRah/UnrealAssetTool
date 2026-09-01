#!/usr/bin/env python3
"""Persist conservative UE Chooser decision semantics as derived data."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import uatool_chooser_decisions as chooser_decisions

CHOOSER_DECISION_SCHEMA_VERSION = 1
DERIVED_FILES = (
    "chooser_decisions.jsonl",
    "chooser_decision_predicates.jsonl",
)

_SQL = """
CREATE TABLE chooser_decisions(
 decision_id TEXT PRIMARY KEY,chooser_path TEXT NOT NULL,row_index INTEGER NOT NULL,
 output_object_type TEXT NOT NULL,disabled INTEGER NOT NULL,condition_text TEXT NOT NULL,
 predicate_count INTEGER NOT NULL,effective_predicate_count INTEGER NOT NULL,
 modeled_column_count INTEGER NOT NULL,fully_modeled INTEGER NOT NULL,fully_decoded INTEGER NOT NULL,
 result_struct_type TEXT NOT NULL,result_raw_value TEXT NOT NULL,result_reference_count INTEGER NOT NULL,
 result_references_json TEXT NOT NULL,json TEXT NOT NULL,
 UNIQUE(chooser_path,row_index)
);
CREATE INDEX chooser_decisions_chooser_idx ON chooser_decisions(chooser_path,row_index);
CREATE INDEX chooser_decisions_condition_idx ON chooser_decisions(condition_text);
CREATE TABLE chooser_decision_predicates(
 decision_id TEXT NOT NULL,chooser_path TEXT NOT NULL,row_index INTEGER NOT NULL,column_index INTEGER NOT NULL,
 context_index INTEGER NOT NULL,property_name TEXT NOT NULL,binding_chain_json TEXT NOT NULL,
 enum_path TEXT NOT NULL,comparison TEXT NOT NULL,raw_value_name TEXT NOT NULL,display_value TEXT NOT NULL,
 numeric_value TEXT NOT NULL,match_any INTEGER NOT NULL,known_comparison INTEGER NOT NULL,decoded INTEGER NOT NULL,
 text TEXT NOT NULL,raw_value TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(decision_id,column_index)
);
CREATE INDEX chooser_predicates_property_idx ON chooser_decision_predicates(property_name,comparison,display_value);
CREATE INDEX chooser_predicates_enum_idx ON chooser_decision_predicates(enum_path,raw_value_name);
"""


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _id(chooser_path: str, row_index: int) -> str:
    basis = f"{chooser_path}\x1f{int(row_index)}"
    return "chooser_decision:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield value


def _write(path: Path, values: list[dict]) -> int:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(_j(value) + "\n")
    return len(values)


def derive(output: Path, rows=None) -> tuple[list[dict], list[dict]]:
    output = Path(output)
    rows = rows or _rows
    tables = {
        str(row.get("chooser_path", "") or ""): row
        for row in rows(output / "chooser_tables.jsonl")
        if str(row.get("chooser_path", "") or "")
    }
    interpreted = chooser_decisions.decisions_for_output(output, rows)
    decisions: list[dict] = []
    predicates: list[dict] = []
    for source in interpreted:
        chooser_path = str(source.get("chooser_path", "") or "")
        row_index = int(source.get("row_index", 0) or 0)
        decision_id = _id(chooser_path, row_index)
        table = tables.get(chooser_path, {})
        source_predicates = [p for p in source.get("predicates", []) if isinstance(p, dict)]
        result_references = [r for r in source.get("result_references", []) if isinstance(r, dict)]
        decision = {
            "decision_id": decision_id,
            "schema_version": CHOOSER_DECISION_SCHEMA_VERSION,
            "chooser_path": chooser_path,
            "row_index": row_index,
            "output_object_type": str(table.get("output_object_type", "") or ""),
            "disabled": bool(source.get("disabled", False)),
            "condition_text": str(source.get("condition_text", "") or "always"),
            "predicate_count": len(source_predicates),
            "effective_predicate_count": int(source.get("effective_predicate_count", 0) or 0),
            "modeled_column_count": int(source.get("modeled_column_count", 0) or 0),
            "fully_modeled": bool(source.get("fully_modeled", False)),
            "fully_decoded": bool(source.get("fully_decoded", False)),
            "result_struct_type": str(source.get("result_struct_type", "") or ""),
            "result_raw_value": str(source.get("result_raw_value", "") or ""),
            "result_reference_count": len(result_references),
            "result_references": result_references,
        }
        decisions.append(decision)
        for predicate in source_predicates:
            predicates.append({
                "decision_id": decision_id,
                "schema_version": CHOOSER_DECISION_SCHEMA_VERSION,
                "chooser_path": chooser_path,
                "row_index": row_index,
                "column_index": int(predicate.get("column_index", 0) or 0),
                "context_index": int(predicate.get("context_index", 0) or 0),
                "property_name": str(predicate.get("property_name", "") or ""),
                "binding_chain": list(predicate.get("binding_chain", [])) if isinstance(predicate.get("binding_chain", []), list) else [],
                "enum_path": str(predicate.get("enum_path", "") or ""),
                "comparison": str(predicate.get("comparison", "") or ""),
                "raw_value_name": str(predicate.get("raw_value_name", "") or ""),
                "display_value": str(predicate.get("display_value", "") or ""),
                "numeric_value": str(predicate.get("numeric_value", "") or ""),
                "match_any": bool(predicate.get("match_any", False)),
                "known_comparison": bool(predicate.get("known_comparison", False)),
                "decoded": bool(predicate.get("decoded", False)),
                "text": str(predicate.get("text", "") or ""),
                "raw_value": str(predicate.get("raw_value", "") or ""),
            })
    decisions.sort(key=lambda row: (row["chooser_path"], row["row_index"], row["decision_id"]))
    predicates.sort(key=lambda row: (row["chooser_path"], row["row_index"], row["column_index"], row["decision_id"]))
    return decisions, predicates


def validation_error(output: Path, rows=None) -> str | None:
    output = Path(output)
    rows = rows or _rows
    decisions = list(rows(output / DERIVED_FILES[0]))
    predicates = list(rows(output / DERIVED_FILES[1]))
    tables = {
        str(row.get("chooser_path", "") or ""): row
        for row in rows(output / "chooser_tables.jsonl")
        if str(row.get("chooser_path", "") or "")
    }
    expected_count = sum(int(row.get("result_count", 0) or 0) for row in tables.values())
    if len(decisions) != expected_count:
        return f"Chooser decision count mismatch: expected={expected_count} actual={len(decisions)}"
    ids = [str(row.get("decision_id", "") or "") for row in decisions]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        return "Chooser decision ids are blank or duplicated"
    by_id = {str(row.get("decision_id", "")): row for row in decisions}
    seen_rows: set[tuple[str, int]] = set()
    predicate_counts: dict[str, int] = {}
    effective_counts: dict[str, int] = {}
    for row in predicates:
        decision_id = str(row.get("decision_id", "") or "")
        if decision_id not in by_id:
            return f"Chooser predicate references unknown decision: {decision_id}"
        predicate_counts[decision_id] = predicate_counts.get(decision_id, 0) + 1
        if not bool(row.get("match_any", False)):
            effective_counts[decision_id] = effective_counts.get(decision_id, 0) + 1
        comparison = str(row.get("comparison", "") or "")
        if bool(row.get("known_comparison", False)) and comparison not in chooser_decisions.KNOWN_COMPARISONS:
            return f"Chooser predicate marks unknown comparison as known: {comparison}"
    for row in decisions:
        chooser_path = str(row.get("chooser_path", "") or "")
        row_index = int(row.get("row_index", 0) or 0)
        key = (chooser_path, row_index)
        if key in seen_rows:
            return f"duplicate Chooser decision row: {chooser_path}[{row_index}]"
        seen_rows.add(key)
        table = tables.get(chooser_path)
        if table is None:
            return f"Chooser decision references unknown table: {chooser_path}"
        if row_index < 0 or row_index >= int(table.get("result_count", 0) or 0):
            return f"Chooser decision row out of range: {chooser_path}[{row_index}]"
        decision_id = str(row.get("decision_id", "") or "")
        if int(row.get("predicate_count", 0) or 0) != predicate_counts.get(decision_id, 0):
            return f"Chooser predicate count mismatch for {decision_id}"
        if int(row.get("effective_predicate_count", 0) or 0) != effective_counts.get(decision_id, 0):
            return f"Chooser effective predicate count mismatch for {decision_id}"
        refs = row.get("result_references", []) if isinstance(row.get("result_references", []), list) else []
        if int(row.get("result_reference_count", 0) or 0) != len(refs):
            return f"Chooser result reference count mismatch for {decision_id}"
    return None


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def load_database(conn, output: Path, rows=None) -> None:
    rows = rows or _rows
    for row in rows(Path(output) / DERIVED_FILES[0]):
        conn.execute(
            "INSERT OR REPLACE INTO chooser_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("decision_id", ""), row.get("chooser_path", ""), int(row.get("row_index", 0) or 0),
                row.get("output_object_type", ""), int(bool(row.get("disabled", False))), row.get("condition_text", ""),
                int(row.get("predicate_count", 0) or 0), int(row.get("effective_predicate_count", 0) or 0),
                int(row.get("modeled_column_count", 0) or 0), int(bool(row.get("fully_modeled", False))),
                int(bool(row.get("fully_decoded", False))), row.get("result_struct_type", ""), row.get("result_raw_value", ""),
                int(row.get("result_reference_count", 0) or 0), _j(row.get("result_references", [])), _j(row),
            ),
        )
    for row in rows(Path(output) / DERIVED_FILES[1]):
        conn.execute(
            "INSERT OR REPLACE INTO chooser_decision_predicates VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("decision_id", ""), row.get("chooser_path", ""), int(row.get("row_index", 0) or 0),
                int(row.get("column_index", 0) or 0), int(row.get("context_index", 0) or 0), row.get("property_name", ""),
                _j(row.get("binding_chain", [])), row.get("enum_path", ""), row.get("comparison", ""),
                row.get("raw_value_name", ""), row.get("display_value", ""), row.get("numeric_value", ""),
                int(bool(row.get("match_any", False))), int(bool(row.get("known_comparison", False))), int(bool(row.get("decoded", False))),
                row.get("text", ""), row.get("raw_value", ""), _j(row),
            ),
        )


def query_table(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='chooser_decisions'").fetchone():
        return
    print("\n[Chooser decisions]")
    print_rows(
        conn.execute(
            """SELECT chooser_path,row_index,condition_text,fully_modeled,fully_decoded,result_reference_count
               FROM chooser_decisions
               WHERE chooser_path LIKE ? OR condition_text LIKE ? OR result_raw_value LIKE ? LIMIT ?""",
            (pattern, pattern, pattern, limit),
        ),
        ("chooser_path", "row_index", "condition_text", "fully_modeled", "fully_decoded", "result_reference_count"),
    )
    print("\n[Chooser decision predicates]")
    print_rows(
        conn.execute(
            """SELECT chooser_path,row_index,column_index,property_name,comparison,display_value,match_any,decoded
               FROM chooser_decision_predicates
               WHERE chooser_path LIKE ? OR property_name LIKE ? OR display_value LIKE ? OR enum_path LIKE ? LIMIT ?""",
            (pattern, pattern, pattern, pattern, limit),
        ),
        ("chooser_path", "row_index", "column_index", "property_name", "comparison", "display_value", "match_any", "decoded"),
    )


def _update_manifest(output: Path, decision_count: int, predicate_count: int) -> None:
    path = output / "manifest.json"
    if not path.is_file():
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid manifest.json while recording Chooser decisions: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("invalid manifest.json root while recording Chooser decisions")
    manifest["chooser_decision_schema_version"] = CHOOSER_DECISION_SCHEMA_VERSION
    declared = manifest.get("derived_counts", {})
    declared = declared if isinstance(declared, dict) else {}
    declared["chooser_decisions"] = int(decision_count)
    declared["chooser_decision_predicates"] = int(predicate_count)
    manifest["derived_counts"] = declared
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def install(core_module, runtime_module) -> None:
    if getattr(core_module, "_chooser_derived_installed", False):
        return
    original_create_schema = core_module.create_schema
    original_derive_output = core_module.derive_output
    original_build_database = core_module.build_database
    original_query = core_module.query

    def create_schema_wrapper(conn):
        original_create_schema(conn)
        create_schema(conn)

    def derive_output_wrapper(output):
        output = Path(output).expanduser().resolve()
        counts = dict(original_derive_output(output))
        decision_rows, predicate_rows = derive(output, runtime_module._rows)
        decision_count = _write(output / DERIVED_FILES[0], decision_rows)
        predicate_count = _write(output / DERIVED_FILES[1], predicate_rows)
        error = validation_error(output, runtime_module._rows)
        if error:
            raise RuntimeError(f"Chooser decision derived incomplete: {error}")
        _update_manifest(output, decision_count, predicate_count)
        counts["chooser_decisions"] = decision_count
        counts["chooser_decision_predicates"] = predicate_count
        return counts

    def build_database_wrapper(output):
        db = original_build_database(output)
        conn = sqlite3.connect(db)
        try:
            load_database(conn, Path(output), runtime_module._rows)
            conn.commit()
        finally:
            conn.close()
        return db

    def query_wrapper(args):
        result = int(original_query(args))
        root = Path(args.output).expanduser().resolve()
        db = root if root.suffix.lower() == ".db" else root / core_module.DB_NAME
        if db.is_file():
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                query_table(conn, core_module._print_rows, f"%{args.term}%", args.limit)
            finally:
                conn.close()
        return result

    core_module.create_schema = create_schema_wrapper
    core_module.derive_output = derive_output_wrapper
    core_module.build_database = build_database_wrapper
    core_module.query = query_wrapper
    core_module.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((*core_module.DEFAULT_BUNDLE_FILES, *DERIVED_FILES)))
    core_module._chooser_derived_installed = True
