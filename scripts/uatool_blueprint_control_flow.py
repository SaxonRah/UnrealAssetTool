#!/usr/bin/env python3
"""Derive generic semantic annotations for Blueprint execution block edges.

The existing execution-block graph remains authoritative. This layer preserves a
one-to-one row for every block edge and adds deterministic control meaning where
the source node proves it: branch predicate/polarity, switch selector/case, and
sequence output order. Unsupported shapes remain explicit generic flow rather
than being guessed.
"""
from __future__ import annotations

import hashlib
import json
import re
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


def _input(statement: dict, *names: str) -> dict | None:
    wanted = {name.lower() for name in names}
    for item in statement.get("inputs", []):
        if not isinstance(item, dict):
            continue
        if str(item.get("pin_name", "") or "").lower() in wanted:
            return item
    return None


def _input_text(item: dict | None) -> str:
    if not item:
        return ""
    if str(item.get("source_kind", "")) == "dependency":
        return str(item.get("expression_text", "") or "")
    return str(item.get("literal", "") or "")


def _dependency_id(item: dict | None) -> str:
    if not item or str(item.get("source_kind", "")) != "dependency":
        return ""
    return str(item.get("dependency_id", "") or "")


def _sequence_index(pin: str) -> int | None:
    match = re.fullmatch(r"then[_ ]?(\d+)", str(pin or ""), flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def derive(output: Path, rows=None) -> list[dict]:
    output = Path(output)
    rows = rows or _rows
    block_edges = list(rows(output / "blueprint_execution_block_edges.jsonl"))
    semantic_nodes = {
        str(row.get("node_id", "") or ""): row
        for row in rows(output / "blueprint_semantic_nodes.jsonl")
        if row.get("node_id")
    }
    statements = {
        str(row.get("node_id", "") or ""): row
        for row in rows(output / "blueprint_semantic_statements.jsonl")
        if row.get("node_id")
    }

    result: list[dict] = []
    for edge in block_edges:
        source_node_id = str(edge.get("source_node_id", "") or "")
        node = semantic_nodes.get(source_node_id, {})
        statement = statements.get(source_node_id, {})
        operation = str(node.get("operation", "") or statement.get("operation", "") or "")
        raw_pin = str(edge.get("source_pin_name", "") or "")
        display_pin = str(edge.get("source_pin_display_name", "") or raw_pin)

        control_kind = "flow"
        condition_dependency_id = ""
        condition_text = ""
        condition_polarity = None
        selector_dependency_id = ""
        selector_text = ""
        case_name = ""
        case_raw_name = ""
        sequence_index = None

        if operation == "branch" and raw_pin.lower() in {"then", "else"}:
            control_kind = "branch"
            condition = _input(statement, "Condition")
            condition_dependency_id = _dependency_id(condition)
            condition_text = _input_text(condition)
            condition_polarity = raw_pin.lower() == "then"
        elif operation == "switch":
            selection = _input(statement, "Selection", "Index")
            selector_dependency_id = _dependency_id(selection)
            selector_text = _input_text(selection)
            case_raw_name = raw_pin
            case_name = display_pin or raw_pin
            control_kind = "switch_default" if raw_pin.lower() == "default" else "switch_case"
        elif operation == "execution_sequence":
            sequence_index = _sequence_index(raw_pin)
            control_kind = "sequence" if sequence_index is not None else "flow"

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
            "source_operation": operation,
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

    base_keys = {
        (
            str(row.get("blueprint_path", "")), str(row.get("graph_id", "")),
            str(row.get("source_block_id", "")), str(row.get("target_block_id", "")),
            str(row.get("source_node_id", "")), str(row.get("source_pin_name", "")),
        )
        for row in base
    }
    control_keys = {
        (
            str(row.get("blueprint_path", "")), str(row.get("graph_id", "")),
            str(row.get("source_block_id", "")), str(row.get("target_block_id", "")),
            str(row.get("source_node_id", "")), str(row.get("source_pin_name", "")),
        )
        for row in control
    }
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
            "INSERT OR REPLACE INTO blueprint_control_edges VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("control_edge_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""),
                row.get("graph_name", ""), row.get("source_block_id", ""), row.get("target_block_id", ""),
                row.get("source_node_id", ""), row.get("source_operation", ""), row.get("source_pin_name", ""),
                row.get("source_pin_display_name", ""), row.get("control_kind", ""),
                row.get("condition_dependency_id", ""), row.get("condition_text", ""),
                None if row.get("condition_polarity") is None else int(bool(row.get("condition_polarity"))),
                row.get("selector_dependency_id", ""), row.get("selector_text", ""), row.get("case_name", ""),
                row.get("case_raw_name", ""), row.get("sequence_index"), _j(row),
            ),
        )


def query(conn, print_rows, pattern: str, limit: int) -> None:
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
