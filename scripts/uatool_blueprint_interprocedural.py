#!/usr/bin/env python3
"""Canonical interprocedural Blueprint execution edges for exact macro calls.

Graph-local execution blocks remain authoritative and unchanged. This layer adds
only proven cross-graph control-flow edges for project-authored macros whose
schema-4 semantic proof edges bind the call site to a uniquely captured macro
graph and exact exec interface pins.

Unconnected macro output exec pins are represented separately as terminal
endpoints rather than fabricated edges.
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

import uatool_core as core

INTERPROCEDURAL_SCHEMA_VERSION = 1
DERIVED_FILES = (
    "blueprint_interprocedural_execution_edges.jsonl",
    "blueprint_interprocedural_execution_terminals.jsonl",
)

_SQL = """
CREATE TABLE blueprint_interprocedural_execution_edges(
 interprocedural_edge_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL,edge_kind TEXT NOT NULL,
 macro_node_id TEXT NOT NULL,macro_graph_id TEXT NOT NULL,
 caller_blueprint_path TEXT NOT NULL,caller_graph_id TEXT NOT NULL,caller_block_id TEXT NOT NULL,
 source_blueprint_path TEXT NOT NULL,source_graph_id TEXT NOT NULL,source_block_id TEXT NOT NULL,
 source_node_id TEXT NOT NULL,source_pin_id TEXT NOT NULL,source_pin_name TEXT NOT NULL,
 target_blueprint_path TEXT NOT NULL,target_graph_id TEXT NOT NULL,target_block_id TEXT NOT NULL,
 target_node_id TEXT NOT NULL,target_pin_id TEXT NOT NULL,target_pin_name TEXT NOT NULL,
 call_pin_id TEXT NOT NULL,call_pin_name TEXT NOT NULL,
 interface_pin_id TEXT NOT NULL,interface_pin_name TEXT NOT NULL,
 continuation_pin_id TEXT NOT NULL,continuation_pin_name TEXT NOT NULL,
 evidence_kind TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX bp_interproc_exec_macro_idx
 ON blueprint_interprocedural_execution_edges(macro_node_id,edge_kind);
CREATE INDEX bp_interproc_exec_source_idx
 ON blueprint_interprocedural_execution_edges(source_block_id,edge_kind);
CREATE INDEX bp_interproc_exec_target_idx
 ON blueprint_interprocedural_execution_edges(target_block_id,edge_kind);
CREATE INDEX bp_interproc_exec_caller_idx
 ON blueprint_interprocedural_execution_edges(caller_blueprint_path,caller_graph_id,caller_block_id);

CREATE TABLE blueprint_interprocedural_execution_terminals(
 terminal_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL,terminal_kind TEXT NOT NULL,
 macro_node_id TEXT NOT NULL,macro_graph_id TEXT NOT NULL,
 caller_blueprint_path TEXT NOT NULL,caller_graph_id TEXT NOT NULL,caller_block_id TEXT NOT NULL,
 exit_blueprint_path TEXT NOT NULL,exit_graph_id TEXT NOT NULL,exit_block_id TEXT NOT NULL,
 exit_node_id TEXT NOT NULL,call_pin_id TEXT NOT NULL,call_pin_name TEXT NOT NULL,
 interface_pin_id TEXT NOT NULL,interface_pin_name TEXT NOT NULL,
 canonical_outgoing_exec_count INTEGER NOT NULL,evidence_kind TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX bp_interproc_terminal_macro_idx
 ON blueprint_interprocedural_execution_terminals(macro_node_id,call_pin_id);
CREATE INDEX bp_interproc_terminal_exit_idx
 ON blueprint_interprocedural_execution_terminals(exit_block_id);
"""


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _id(prefix: str, *parts: str) -> str:
    basis = "\x1f".join(str(part or "") for part in parts)
    return prefix + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


def _pin_is_exec(pin: dict) -> bool:
    pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
    return str(pin_type.get("category", "") or "").lower() == "exec"


def _block_membership(output: Path, rows) -> tuple[dict[str, dict], set[str]]:
    by_node: dict[str, dict] = {}
    duplicates: set[str] = set()
    for block in rows(output / "blueprint_execution_blocks.jsonl"):
        block_id = str(block.get("block_id", "") or "")
        if not block_id:
            continue
        node_ids = block.get("node_ids", []) if isinstance(block.get("node_ids"), list) else []
        for value in node_ids:
            node_id = str(value or "")
            if not node_id:
                continue
            previous = by_node.get(node_id)
            if previous is not None and str(previous.get("block_id", "") or "") != block_id:
                duplicates.add(node_id)
            by_node[node_id] = block
    return by_node, duplicates


def derive(output: Path, rows) -> tuple[list[dict], list[dict]]:
    output = Path(output)

    semantic_edges = list(rows(output / "blueprint_semantic_edges.jsonl"))
    pins = list(core.iter_blueprint_pin_rows(output))
    pin_by_id = {
        str(pin.get("pin_id", "") or ""): pin
        for pin in pins
        if pin.get("pin_id")
    }
    block_by_node, duplicate_block_nodes = _block_membership(output, rows)
    if duplicate_block_nodes:
        sample = ", ".join(sorted(duplicate_block_nodes)[:5])
        raise RuntimeError(f"Blueprint execution node belongs to multiple blocks: {sample}")

    canonical_exec_by_source_pin: dict[str, list[dict]] = collections.defaultdict(list)
    for raw_edge in rows(output / "blueprint_edges.jsonl"):
        if str(raw_edge.get("edge_kind", "") or "") != "execution":
            continue
        source_pin_id = str(raw_edge.get("source_pin_id", "") or "")
        if source_pin_id:
            canonical_exec_by_source_pin[source_pin_id].append(raw_edge)

    proof_by_macro: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in semantic_edges:
        relation = str(edge.get("relation", "") or "")
        if relation in {"maps_to_macro_graph", "binds_macro_input", "binds_macro_output"}:
            proof_by_macro[str(edge.get("source_node_id", "") or "")].append(edge)

    interprocedural_edges: list[dict] = []
    terminals: list[dict] = []

    for macro_node_id in sorted(proof_by_macro):
        proof = proof_by_macro[macro_node_id]
        graph_proofs = [
            edge for edge in proof
            if str(edge.get("relation", "") or "") == "maps_to_macro_graph"
        ]
        if len(graph_proofs) != 1:
            raise RuntimeError(
                f"exact macro proof has {len(graph_proofs)} graph mappings: {macro_node_id}"
            )
        macro_graph_id = str(graph_proofs[0].get("target", "") or "")
        if not macro_graph_id:
            raise RuntimeError(f"exact macro graph proof lacks target graph: {macro_node_id}")

        caller_block = block_by_node.get(macro_node_id)
        exec_bindings = [
            edge for edge in proof
            if str(edge.get("relation", "") or "") in {"binds_macro_input", "binds_macro_output"}
            and str(edge.get("pin_category", "") or "").lower() == "exec"
        ]
        if exec_bindings and caller_block is None:
            raise RuntimeError(f"executable macro instance lacks caller block: {macro_node_id}")
        if caller_block is None:
            # A data-only exact macro has no interprocedural execution rows.
            continue

        caller_block_id = str(caller_block.get("block_id", "") or "")
        caller_blueprint_path = str(caller_block.get("blueprint_path", "") or "")
        caller_graph_id = str(caller_block.get("graph_id", "") or "")

        for binding in exec_bindings:
            relation = str(binding.get("relation", "") or "")
            call_pin_id = str(binding.get("source_pin_id", "") or "")
            interface_pin_id = str(binding.get("target_pin_id", "") or "")
            call_pin = pin_by_id.get(call_pin_id)
            interface_pin = pin_by_id.get(interface_pin_id)
            if call_pin is None or interface_pin is None:
                raise RuntimeError(
                    f"macro exec proof references missing pin: {macro_node_id} "
                    f"call={call_pin_id!r} interface={interface_pin_id!r}"
                )
            if not _pin_is_exec(call_pin) or not _pin_is_exec(interface_pin):
                raise RuntimeError(f"macro exec proof references non-exec pin: {macro_node_id}")

            interface_node_id = str(interface_pin.get("node_id", "") or "")
            interface_block = block_by_node.get(interface_node_id)
            if interface_block is None:
                raise RuntimeError(
                    f"macro exec interface node lacks execution block: {interface_node_id}"
                )
            interface_graph_id = str(interface_block.get("graph_id", "") or "")
            if interface_graph_id != macro_graph_id:
                raise RuntimeError(
                    f"macro exec interface graph mismatch: {macro_node_id} "
                    f"expected={macro_graph_id} actual={interface_graph_id}"
                )

            interface_block_id = str(interface_block.get("block_id", "") or "")
            interface_blueprint_path = str(interface_block.get("blueprint_path", "") or "")
            call_pin_name = str(binding.get("source_pin_name", "") or call_pin.get("name", "") or "")
            interface_pin_name = str(
                binding.get("target_pin_name", "") or interface_pin.get("name", "") or ""
            )

            if relation == "binds_macro_input":
                edge_id = _id(
                    "bpinterexec:",
                    "macro_enter", macro_node_id, caller_block_id, interface_block_id,
                    call_pin_id, interface_pin_id,
                )
                interprocedural_edges.append({
                    "interprocedural_edge_id": edge_id,
                    "schema_version": INTERPROCEDURAL_SCHEMA_VERSION,
                    "edge_kind": "macro_enter",
                    "macro_node_id": macro_node_id,
                    "macro_graph_id": macro_graph_id,
                    "caller_blueprint_path": caller_blueprint_path,
                    "caller_graph_id": caller_graph_id,
                    "caller_block_id": caller_block_id,
                    "source_blueprint_path": caller_blueprint_path,
                    "source_graph_id": caller_graph_id,
                    "source_block_id": caller_block_id,
                    "source_node_id": macro_node_id,
                    "source_pin_id": call_pin_id,
                    "source_pin_name": call_pin_name,
                    "target_blueprint_path": interface_blueprint_path,
                    "target_graph_id": interface_graph_id,
                    "target_block_id": interface_block_id,
                    "target_node_id": interface_node_id,
                    "target_pin_id": interface_pin_id,
                    "target_pin_name": interface_pin_name,
                    "call_pin_id": call_pin_id,
                    "call_pin_name": call_pin_name,
                    "interface_pin_id": interface_pin_id,
                    "interface_pin_name": interface_pin_name,
                    "continuation_pin_id": "",
                    "continuation_pin_name": "",
                    "evidence_kind": "macro_interface_exact_block_membership",
                })
                continue

            if relation != "binds_macro_output":
                continue

            outgoing = canonical_exec_by_source_pin.get(call_pin_id, [])
            if not outgoing:
                terminal_id = _id(
                    "bpinterterm:",
                    macro_node_id, macro_graph_id, interface_block_id,
                    call_pin_id, interface_pin_id,
                )
                terminals.append({
                    "terminal_id": terminal_id,
                    "schema_version": INTERPROCEDURAL_SCHEMA_VERSION,
                    "terminal_kind": "macro_exit_unconnected",
                    "macro_node_id": macro_node_id,
                    "macro_graph_id": macro_graph_id,
                    "caller_blueprint_path": caller_blueprint_path,
                    "caller_graph_id": caller_graph_id,
                    "caller_block_id": caller_block_id,
                    "exit_blueprint_path": interface_blueprint_path,
                    "exit_graph_id": interface_graph_id,
                    "exit_block_id": interface_block_id,
                    "exit_node_id": interface_node_id,
                    "call_pin_id": call_pin_id,
                    "call_pin_name": call_pin_name,
                    "interface_pin_id": interface_pin_id,
                    "interface_pin_name": interface_pin_name,
                    "canonical_outgoing_exec_count": 0,
                    "evidence_kind": "macro_interface_exact_no_canonical_continuation",
                })
                continue

            for raw_edge in sorted(
                outgoing,
                key=lambda edge: (
                    str(edge.get("target_node_id", "") or ""),
                    str(edge.get("target_pin_id", "") or ""),
                ),
            ):
                continuation_node_id = str(raw_edge.get("target_node_id", "") or "")
                continuation_pin_id = str(raw_edge.get("target_pin_id", "") or "")
                continuation_block = block_by_node.get(continuation_node_id)
                if continuation_block is None:
                    raise RuntimeError(
                        f"macro continuation node lacks execution block: {continuation_node_id}"
                    )
                continuation_graph_id = str(continuation_block.get("graph_id", "") or "")
                if continuation_graph_id != caller_graph_id:
                    raise RuntimeError(
                        f"macro continuation graph mismatch: {macro_node_id} "
                        f"expected={caller_graph_id} actual={continuation_graph_id}"
                    )
                continuation_block_id = str(continuation_block.get("block_id", "") or "")
                continuation_blueprint_path = str(
                    continuation_block.get("blueprint_path", "") or ""
                )
                continuation_pin_name = str(raw_edge.get("target_pin_name", "") or "")

                edge_id = _id(
                    "bpinterexec:",
                    "macro_return", macro_node_id, interface_block_id,
                    continuation_block_id, call_pin_id, interface_pin_id,
                    continuation_pin_id,
                )
                interprocedural_edges.append({
                    "interprocedural_edge_id": edge_id,
                    "schema_version": INTERPROCEDURAL_SCHEMA_VERSION,
                    "edge_kind": "macro_return",
                    "macro_node_id": macro_node_id,
                    "macro_graph_id": macro_graph_id,
                    "caller_blueprint_path": caller_blueprint_path,
                    "caller_graph_id": caller_graph_id,
                    "caller_block_id": caller_block_id,
                    "source_blueprint_path": interface_blueprint_path,
                    "source_graph_id": interface_graph_id,
                    "source_block_id": interface_block_id,
                    "source_node_id": interface_node_id,
                    "source_pin_id": interface_pin_id,
                    "source_pin_name": interface_pin_name,
                    "target_blueprint_path": continuation_blueprint_path,
                    "target_graph_id": continuation_graph_id,
                    "target_block_id": continuation_block_id,
                    "target_node_id": continuation_node_id,
                    "target_pin_id": continuation_pin_id,
                    "target_pin_name": continuation_pin_name,
                    "call_pin_id": call_pin_id,
                    "call_pin_name": call_pin_name,
                    "interface_pin_id": interface_pin_id,
                    "interface_pin_name": interface_pin_name,
                    "continuation_pin_id": continuation_pin_id,
                    "continuation_pin_name": continuation_pin_name,
                    "evidence_kind": "macro_interface_exact_canonical_execution",
                })

    interprocedural_edges.sort(key=lambda row: (
        row["caller_blueprint_path"], row["caller_graph_id"], row["macro_node_id"],
        row["edge_kind"], row["call_pin_id"], row["target_block_id"],
        row["continuation_pin_id"], row["interprocedural_edge_id"],
    ))
    terminals.sort(key=lambda row: (
        row["caller_blueprint_path"], row["caller_graph_id"], row["macro_node_id"],
        row["call_pin_id"], row["terminal_id"],
    ))
    return interprocedural_edges, terminals


def validation_error(output: Path, rows) -> str | None:
    output = Path(output)
    for filename in DERIVED_FILES:
        if not (output / filename).is_file():
            return f"Blueprint interprocedural stream missing: {filename}"

    try:
        expected_edges, expected_terminals = derive(output, rows)
    except RuntimeError as exc:
        return str(exc)

    actual_edges = list(rows(output / DERIVED_FILES[0]))
    actual_terminals = list(rows(output / DERIVED_FILES[1]))

    if actual_edges != expected_edges:
        return (
            "Blueprint interprocedural execution edges do not exactly match "
            "schema-4 macro proofs and canonical execution topology"
        )
    if actual_terminals != expected_terminals:
        return (
            "Blueprint interprocedural execution terminals do not exactly match "
            "schema-4 macro proofs and canonical execution topology"
        )

    edge_ids = [str(row.get("interprocedural_edge_id", "") or "") for row in actual_edges]
    terminal_ids = [str(row.get("terminal_id", "") or "") for row in actual_terminals]
    if any(not value for value in edge_ids) or len(edge_ids) != len(set(edge_ids)):
        return "Blueprint interprocedural execution edges contain missing/duplicate ids"
    if any(not value for value in terminal_ids) or len(terminal_ids) != len(set(terminal_ids)):
        return "Blueprint interprocedural execution terminals contain missing/duplicate ids"

    for row in actual_edges:
        if int(row.get("schema_version", 0) or 0) != INTERPROCEDURAL_SCHEMA_VERSION:
            return f"unexpected Blueprint interprocedural edge schema: {row.get('schema_version')!r}"
        if str(row.get("edge_kind", "") or "") not in {"macro_enter", "macro_return"}:
            return f"unexpected Blueprint interprocedural edge kind: {row.get('edge_kind')!r}"
        if not str(row.get("source_block_id", "") or "") or not str(row.get("target_block_id", "") or ""):
            return f"Blueprint interprocedural edge lacks block endpoint: {row.get('interprocedural_edge_id')}"

    for row in actual_terminals:
        if int(row.get("schema_version", 0) or 0) != INTERPROCEDURAL_SCHEMA_VERSION:
            return f"unexpected Blueprint interprocedural terminal schema: {row.get('schema_version')!r}"
        if str(row.get("terminal_kind", "") or "") != "macro_exit_unconnected":
            return f"unexpected Blueprint interprocedural terminal kind: {row.get('terminal_kind')!r}"
        if int(row.get("canonical_outgoing_exec_count", -1)) != 0:
            return f"Blueprint macro terminal has canonical continuation: {row.get('terminal_id')}"
    return None


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def load_database(conn, output: Path, rows) -> None:
    for row in rows(Path(output) / DERIVED_FILES[0]):
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_interprocedural_execution_edges VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("interprocedural_edge_id", ""), int(row.get("schema_version", 0) or 0),
                row.get("edge_kind", ""), row.get("macro_node_id", ""), row.get("macro_graph_id", ""),
                row.get("caller_blueprint_path", ""), row.get("caller_graph_id", ""),
                row.get("caller_block_id", ""), row.get("source_blueprint_path", ""),
                row.get("source_graph_id", ""), row.get("source_block_id", ""),
                row.get("source_node_id", ""), row.get("source_pin_id", ""),
                row.get("source_pin_name", ""), row.get("target_blueprint_path", ""),
                row.get("target_graph_id", ""), row.get("target_block_id", ""),
                row.get("target_node_id", ""), row.get("target_pin_id", ""),
                row.get("target_pin_name", ""), row.get("call_pin_id", ""),
                row.get("call_pin_name", ""), row.get("interface_pin_id", ""),
                row.get("interface_pin_name", ""), row.get("continuation_pin_id", ""),
                row.get("continuation_pin_name", ""), row.get("evidence_kind", ""), _j(row),
            ),
        )
    for row in rows(Path(output) / DERIVED_FILES[1]):
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_interprocedural_execution_terminals VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("terminal_id", ""), int(row.get("schema_version", 0) or 0),
                row.get("terminal_kind", ""), row.get("macro_node_id", ""), row.get("macro_graph_id", ""),
                row.get("caller_blueprint_path", ""), row.get("caller_graph_id", ""),
                row.get("caller_block_id", ""), row.get("exit_blueprint_path", ""),
                row.get("exit_graph_id", ""), row.get("exit_block_id", ""),
                row.get("exit_node_id", ""), row.get("call_pin_id", ""),
                row.get("call_pin_name", ""), row.get("interface_pin_id", ""),
                row.get("interface_pin_name", ""), int(row.get("canonical_outgoing_exec_count", 0) or 0),
                row.get("evidence_kind", ""), _j(row),
            ),
        )


def query(conn, print_rows, pattern: str, limit: int) -> None:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' "
        "AND name='blueprint_interprocedural_execution_edges'"
    ).fetchone()
    if not exists:
        return
    print("\n[Blueprint interprocedural execution]")
    print_rows(
        conn.execute(
            """SELECT edge_kind,caller_blueprint_path,caller_block_id,source_block_id,target_block_id,
                      call_pin_name,interface_pin_name,continuation_pin_name
               FROM blueprint_interprocedural_execution_edges
               WHERE caller_blueprint_path LIKE ? OR edge_kind LIKE ? OR call_pin_name LIKE ?
                  OR interface_pin_name LIKE ? OR continuation_pin_name LIKE ?
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, pattern, limit),
        ),
        (
            "edge_kind", "caller_blueprint_path", "caller_block_id", "source_block_id",
            "target_block_id", "call_pin_name", "interface_pin_name", "continuation_pin_name",
        ),
    )
    print("\n[Blueprint interprocedural terminals]")
    print_rows(
        conn.execute(
            """SELECT terminal_kind,caller_blueprint_path,caller_block_id,exit_block_id,
                      call_pin_name,interface_pin_name
               FROM blueprint_interprocedural_execution_terminals
               WHERE caller_blueprint_path LIKE ? OR terminal_kind LIKE ?
                  OR call_pin_name LIKE ? OR interface_pin_name LIKE ?
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, limit),
        ),
        (
            "terminal_kind", "caller_blueprint_path", "caller_block_id", "exit_block_id",
            "call_pin_name", "interface_pin_name",
        ),
    )
