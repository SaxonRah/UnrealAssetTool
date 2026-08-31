#!/usr/bin/env python3
"""Derive generic semantic annotations for Blueprint execution block edges.

The existing execution-block graph remains authoritative. This layer preserves a
one-to-one row for every block edge and adds deterministic control meaning where
the source node proves it: branch predicate/polarity, switch selector/case, and
sequence output order. Unsupported shapes remain explicit generic flow rather
than being guessed.

This is an independently versioned derived layer. It is installed before the
canonical composition root captures core globals, so it participates in derive,
SQLite, query, bundle membership, freshness and manifest counts without adding a
second public launcher or requiring another Unreal scan.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

CONTROL_FLOW_SCHEMA_VERSION = 1
DERIVED_FILES = ("blueprint_control_edges.jsonl",)

_SQL = """
CREATE TABLE blueprint_control_edges(
 control_edge_id TEXT PRIMARY KEY,blueprint_path TEXT NOT NULL,graph_id TEXT NOT NULL,graph_name TEXT NOT NULL,
 source_block_id TEXT NOT NULL,target_block_id TEXT NOT NULL,source_node_id TEXT NOT NULL,
 source_operation TEXT NOT NULL,source_pin_name TEXT NOT NULL,source_pin_display_name TEXT NOT NULL,
 control_kind TEXT NOT NULL,condition_dependency_id TEXT NOT NULL,condition_text TEXT NOT NULL,
 condition_polarity INTEGER,selector_dependency_id TEXT NOT NULL,selector_text TEXT NOT NULL,
 case_name TEXT NOT NULL,case_raw_name TEXT NOT NULL,sequence_index INTEGER,json TEXT NOT NULL);
CREATE INDEX bp_control_edges_graph_idx ON blueprint_control_edges(blueprint_path,graph_id,source_block_id);
CREATE INDEX bp_control_edges_kind_idx ON blueprint_control_edges(control_kind,source_operation);
"""


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _id(*parts: str) -> str:
    basis = "\x1f".join(str(part or "") for part in parts)
    return "bpctrl:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


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


def _sequence_index(pin: str) -> int | None:
    match = re.fullmatch(r"then[_ ]?(\d+)", str(pin or ""), flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _dependency_maps(dependencies: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    conditions: dict[str, dict] = {}
    selectors: dict[str, dict] = {}
    for row in dependencies:
        node_id = str(row.get("sink_node_id", "") or "")
        pin_name = str(row.get("sink_pin_name", "") or "")
        operation = str(row.get("sink_operation", "") or "")
        if not node_id:
            continue
        if operation == "branch" and pin_name == "Condition":
            conditions[node_id] = row
        elif operation == "switch" and pin_name in {"Selection", "Index"}:
            selectors[node_id] = row
    return conditions, selectors


def _node_classes(output: Path, rows) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in rows(output / "blueprint_nodes.jsonl"):
        node_id = str(row.get("node_id", "") or "")
        if node_id:
            result[node_id] = str(row.get("node_class", "") or "")
    return result


def derive(output: Path, rows=None) -> list[dict]:
    output = Path(output)
    rows = rows or _rows
    block_edges = list(rows(output / "blueprint_execution_block_edges.jsonl"))
    dependencies = list(rows(output / "blueprint_data_dependencies.jsonl"))
    conditions, selectors = _dependency_maps(dependencies)
    node_classes = _node_classes(output, rows)

    result: list[dict] = []
    for edge in block_edges:
        source_node_id = str(edge.get("source_node_id", "") or "")
        raw_pin = str(edge.get("source_pin_name", "") or "")
        display_pin = str(edge.get("source_pin_display_name", "") or raw_pin)
        node_class = node_classes.get(source_node_id, "")

        control_kind = "flow"
        source_operation = ""
        condition_dependency_id = ""
        condition_text = ""
        condition_polarity = None
        selector_dependency_id = ""
        selector_text = ""
        case_name = ""
        case_raw_name = ""
        sequence_index = None

        condition = conditions.get(source_node_id)
        selector = selectors.get(source_node_id)
        if condition is not None and raw_pin.lower() in {"then", "else"}:
            source_operation = "branch"
            control_kind = "branch"
            condition_dependency_id = str(condition.get("dependency_id", "") or "")
            condition_text = str(condition.get("text", "") or "")
            condition_polarity = raw_pin.lower() == "then"
        elif selector is not None or "K2Node_Switch" in node_class:
            source_operation = "switch"
            if selector is not None:
                selector_dependency_id = str(selector.get("dependency_id", "") or "")
                selector_text = str(selector.get("text", "") or "")
            case_raw_name = raw_pin
            case_name = display_pin or raw_pin
            control_kind = "switch_default" if raw_pin.lower() == "default" else "switch_case"
        else:
            sequence_index = _sequence_index(raw_pin)
            if sequence_index is not None or node_class.endswith("K2Node_ExecutionSequence"):
                source_operation = "execution_sequence"
                if sequence_index is not None:
                    control_kind = "sequence"

        result.append({
            "control_edge_id": _id(
                str(edge.get("blueprint_path", "")),
                str(edge.get("graph_id", "")),
                str(edge.get("source_block_id", "")),
                str(edge.get("target_block_id", "")),
                source_node_id,
                raw_pin,
            ),
            "schema_version": CONTROL_FLOW_SCHEMA_VERSION,
            "blueprint_path": str(edge.get("blueprint_path", "") or ""),
            "graph_id": str(edge.get("graph_id", "") or ""),
            "graph_name": str(edge.get("graph_name", "") or ""),
            "source_block_id": str(edge.get("source_block_id", "") or ""),
            "target_block_id": str(edge.get("target_block_id", "") or ""),
            "source_node_id": source_node_id,
            "source_node_class": node_class,
            "source_operation": source_operation,
            "source_pin_name": raw_pin,
            "source_pin_display_name": display_pin,
            "control_kind": control_kind,
            "condition_dependency_id": condition_dependency_id,
            "condition_text": condition_text,
            "condition_polarity": condition_polarity,
            "selector_dependency_id": selector_dependency_id,
            "selector_text": selector_text,
            "case_name": case_name,
            "case_raw_name": case_raw_name,
            "sequence_index": sequence_index,
        })

    result.sort(key=lambda row: (
        row["blueprint_path"], row["graph_id"], row["source_block_id"],
        row["source_pin_name"], row["target_block_id"], row["control_edge_id"],
    ))
    return result


def validation_error(output: Path, rows=None) -> str | None:
    output = Path(output)
    rows = rows or _rows
    base = list(rows(output / "blueprint_execution_block_edges.jsonl"))
    control = list(rows(output / "blueprint_control_edges.jsonl"))
    if len(base) != len(control):
        return f"Blueprint control-edge count mismatch: base={len(base)} control={len(control)}"

    def key(row: dict) -> tuple[str, ...]:
        return (
            str(row.get("blueprint_path", "")), str(row.get("graph_id", "")),
            str(row.get("source_block_id", "")), str(row.get("target_block_id", "")),
            str(row.get("source_node_id", "")), str(row.get("source_pin_name", "")),
        )

    base_keys = {key(row) for row in base}
    control_keys = {key(row) for row in control}
    if base_keys != control_keys:
        return "Blueprint control edges do not preserve the execution-block edge set"
    if len(control_keys) != len(control):
        return "Blueprint control edges contain duplicate source/target/pin identities"

    for row in control:
        kind = str(row.get("control_kind", ""))
        if kind not in {"flow", "branch", "switch_case", "switch_default", "sequence"}:
            return f"unexpected Blueprint control kind: {kind!r}"
        if kind == "branch":
            if row.get("condition_polarity") not in {True, False}:
                return f"branch control edge lacks polarity: {row.get('control_edge_id')}"
            if not str(row.get("condition_text", "")):
                return f"branch control edge lacks condition text: {row.get('control_edge_id')}"
        if kind in {"switch_case", "switch_default"} and not str(row.get("case_name", "")):
            return f"switch control edge lacks case identity: {row.get('control_edge_id')}"
        if kind == "sequence" and row.get("sequence_index") is None:
            return f"sequence control edge lacks output index: {row.get('control_edge_id')}"
    return None


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def load_database(conn, output: Path, rows=None) -> None:
    rows = rows or _rows
    for row in rows(Path(output) / "blueprint_control_edges.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_control_edges VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("control_edge_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""),
                row.get("graph_name", ""), row.get("source_block_id", ""), row.get("target_block_id", ""),
                row.get("source_node_id", ""), row.get("source_node_class", ""), row.get("source_operation", ""),
                row.get("source_pin_name", ""), row.get("source_pin_display_name", ""), row.get("control_kind", ""),
                row.get("condition_dependency_id", ""), row.get("condition_text", ""),
                None if row.get("condition_polarity") is None else int(bool(row.get("condition_polarity"))),
                row.get("selector_dependency_id", ""), row.get("selector_text", ""), row.get("case_name", ""),
                row.get("case_raw_name", ""), row.get("sequence_index"), _j(row),
            ),
        )


def query_table(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='blueprint_control_edges'").fetchone():
        return
    print("\n[Blueprint control edges]")
    print_rows(
        conn.execute(
            """SELECT blueprint_path,graph_name,source_block_id,target_block_id,control_kind,
                      source_pin_display_name,condition_text,selector_text,case_name,sequence_index
               FROM blueprint_control_edges
               WHERE blueprint_path LIKE ? OR graph_name LIKE ? OR control_kind LIKE ?
                  OR condition_text LIKE ? OR selector_text LIKE ? OR case_name LIKE ?
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, pattern, pattern, limit),
        ),
        (
            "blueprint_path", "graph_name", "source_block_id", "target_block_id", "control_kind",
            "source_pin_display_name", "condition_text", "selector_text", "case_name", "sequence_index",
        ),
    )


def _update_manifest(output: Path, count: int) -> None:
    path = output / "manifest.json"
    if not path.is_file():
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid manifest.json while recording Blueprint control flow: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("invalid manifest.json root while recording Blueprint control flow")
    manifest["blueprint_control_flow_schema_version"] = CONTROL_FLOW_SCHEMA_VERSION
    declared = manifest.get("derived_counts", {})
    declared = declared if isinstance(declared, dict) else {}
    declared["blueprint_control_edges"] = int(count)
    manifest["derived_counts"] = declared
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def install(core_module) -> None:
    if getattr(core_module, "_blueprint_control_flow_installed", False):
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
        values = derive(output, core_module.iter_jsonl)
        count = _write(output / DERIVED_FILES[0], values)
        error = validation_error(output, core_module.iter_jsonl)
        if error:
            raise RuntimeError(f"Blueprint control flow derived incomplete: {error}")
        _update_manifest(output, count)
        counts["blueprint_control_edges"] = count
        return counts

    def build_database_wrapper(output):
        db = original_build_database(output)
        conn = sqlite3.connect(db)
        try:
            load_database(conn, Path(output), core_module.iter_jsonl)
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
    core_module._blueprint_control_flow_installed = True
