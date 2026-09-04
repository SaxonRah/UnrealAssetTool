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

INTERPROCEDURAL_SCHEMA_VERSION = 3
DERIVED_FILES = (
    "blueprint_interprocedural_execution_edges.jsonl",
    "blueprint_interprocedural_execution_terminals.jsonl",
    "blueprint_interprocedural_data_routes.jsonl",
    "blueprint_interprocedural_function_execution_edges.jsonl",
    "blueprint_interprocedural_function_execution_terminals.jsonl",
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

CREATE TABLE blueprint_interprocedural_data_routes(
 route_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL,route_kind TEXT NOT NULL,
 macro_node_id TEXT NOT NULL,macro_graph_id TEXT NOT NULL,
 caller_blueprint_path TEXT NOT NULL,caller_graph_id TEXT NOT NULL,
 call_pin_id TEXT NOT NULL,call_pin_name TEXT NOT NULL,
 interface_pin_id TEXT NOT NULL,interface_pin_name TEXT NOT NULL,
 value_kind TEXT NOT NULL,caller_source_count INTEGER NOT NULL,
 body_consumer_count INTEGER NOT NULL,internal_source_count INTEGER NOT NULL,
 dependency_count INTEGER NOT NULL,caller_consumer_count INTEGER NOT NULL,
 bridge_ready INTEGER NOT NULL,authored_default_value TEXT NOT NULL,
 authored_default_object TEXT NOT NULL,authored_default_text TEXT NOT NULL,
 evidence_kind TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX bp_interproc_data_macro_idx
 ON blueprint_interprocedural_data_routes(macro_node_id,route_kind);
CREATE INDEX bp_interproc_data_call_pin_idx
 ON blueprint_interprocedural_data_routes(call_pin_id);

CREATE TABLE blueprint_interprocedural_function_execution_edges(
 function_edge_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL,edge_kind TEXT NOT NULL,
 call_node_id TEXT NOT NULL,target_function_id TEXT NOT NULL,
 caller_blueprint_path TEXT NOT NULL,caller_graph_id TEXT NOT NULL,caller_block_id TEXT NOT NULL,
 source_blueprint_path TEXT NOT NULL,source_graph_id TEXT NOT NULL,source_block_id TEXT NOT NULL,
 source_node_id TEXT NOT NULL,target_blueprint_path TEXT NOT NULL,target_graph_id TEXT NOT NULL,
 target_block_id TEXT NOT NULL,target_node_id TEXT NOT NULL,
 continuation_node_id TEXT NOT NULL,continuation_pin_id TEXT NOT NULL,continuation_pin_name TEXT NOT NULL,
 return_frontier_block_count INTEGER NOT NULL,call_binding_count INTEGER NOT NULL,
 purity_override INTEGER NOT NULL,evidence_kind TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX bp_interproc_fn_exec_call_idx
 ON blueprint_interprocedural_function_execution_edges(call_node_id,edge_kind);
CREATE INDEX bp_interproc_fn_exec_source_idx
 ON blueprint_interprocedural_function_execution_edges(source_block_id,edge_kind);
CREATE INDEX bp_interproc_fn_exec_target_idx
 ON blueprint_interprocedural_function_execution_edges(target_block_id,edge_kind);

CREATE TABLE blueprint_interprocedural_function_execution_terminals(
 terminal_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL,terminal_kind TEXT NOT NULL,
 call_node_id TEXT NOT NULL,target_function_id TEXT NOT NULL,
 caller_blueprint_path TEXT NOT NULL,caller_graph_id TEXT NOT NULL,caller_block_id TEXT NOT NULL,
 target_blueprint_path TEXT NOT NULL,target_graph_id TEXT NOT NULL,
 entry_block_id TEXT NOT NULL,entry_node_id TEXT NOT NULL,
 return_frontier_block_count INTEGER NOT NULL,return_frontier_block_ids_json TEXT NOT NULL,
 call_binding_count INTEGER NOT NULL,purity_override INTEGER NOT NULL,
 canonical_outgoing_exec_count INTEGER NOT NULL,evidence_kind TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX bp_interproc_fn_terminal_call_idx
 ON blueprint_interprocedural_function_execution_terminals(call_node_id);
CREATE INDEX bp_interproc_fn_terminal_target_idx
 ON blueprint_interprocedural_function_execution_terminals(target_function_id);
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


def derive(output: Path, rows) -> tuple[list[dict], list[dict], list[dict]]:
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
    canonical_data_incoming_by_pin: dict[str, list[dict]] = collections.defaultdict(list)
    canonical_data_outgoing_by_pin: dict[str, list[dict]] = collections.defaultdict(list)
    for raw_edge in rows(output / "blueprint_edges.jsonl"):
        edge_kind = str(raw_edge.get("edge_kind", "") or "")
        source_pin_id = str(raw_edge.get("source_pin_id", "") or "")
        target_pin_id = str(raw_edge.get("target_pin_id", "") or "")
        if edge_kind == "execution":
            if source_pin_id:
                canonical_exec_by_source_pin[source_pin_id].append(raw_edge)
            continue
        if edge_kind != "data":
            continue
        if source_pin_id:
            canonical_data_outgoing_by_pin[source_pin_id].append(raw_edge)
        if target_pin_id:
            canonical_data_incoming_by_pin[target_pin_id].append(raw_edge)

    dependency_by_sink_pin: dict[str, list[dict]] = collections.defaultdict(list)
    dependency_path = output / "blueprint_data_dependencies.jsonl"
    if dependency_path.is_file():
        for dependency in rows(dependency_path):
            sink_pin_id = str(dependency.get("sink_pin_id", "") or "")
            if sink_pin_id:
                dependency_by_sink_pin[sink_pin_id].append(dependency)

    proof_by_macro: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in semantic_edges:
        relation = str(edge.get("relation", "") or "")
        if relation in {"maps_to_macro_graph", "binds_macro_input", "binds_macro_output"}:
            proof_by_macro[str(edge.get("source_node_id", "") or "")].append(edge)

    interprocedural_edges: list[dict] = []
    terminals: list[dict] = []
    data_routes: list[dict] = []

    def edge_endpoint(edge: dict, *, source: bool) -> dict:
        prefix = "source" if source else "target"
        node_id = str(edge.get(f"{prefix}_node_id", "") or "")
        pin_id = str(edge.get(f"{prefix}_pin_id", "") or "")
        pin = pin_by_id.get(pin_id, {})
        return {
            "node_id": node_id,
            "pin_id": pin_id,
            "pin_name": str(edge.get(f"{prefix}_pin_name", "") or pin.get("name", "") or ""),
            "blueprint_path": str(pin.get("blueprint_path", "") or ""),
            "graph_id": str(pin.get("graph_id", "") or ""),
        }

    def sorted_endpoints(edges: list[dict], *, source: bool) -> list[dict]:
        values = [edge_endpoint(edge, source=source) for edge in edges]
        return sorted(
            values,
            key=lambda value: (
                value["blueprint_path"], value["graph_id"], value["node_id"],
                value["pin_id"], value["pin_name"],
            ),
        )

    def pin_has_authored_value(pin: dict) -> bool:
        return bool(
            str(pin.get("default_object", "") or "")
            or str(pin.get("default_value", "") or "")
            or str(pin.get("default_text", "") or "")
        )

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

        data_bindings = [
            edge for edge in proof
            if str(edge.get("relation", "") or "") in {"binds_macro_input", "binds_macro_output"}
            and str(edge.get("pin_category", "") or "").lower() != "exec"
        ]
        for binding in data_bindings:
            relation = str(binding.get("relation", "") or "")
            call_pin_id = str(binding.get("source_pin_id", "") or "")
            interface_pin_id = str(binding.get("target_pin_id", "") or "")
            call_pin = pin_by_id.get(call_pin_id)
            interface_pin = pin_by_id.get(interface_pin_id)
            if call_pin is None or interface_pin is None:
                raise RuntimeError(
                    f"macro data proof references missing pin: {macro_node_id} "
                    f"call={call_pin_id!r} interface={interface_pin_id!r}"
                )
            if _pin_is_exec(call_pin) or _pin_is_exec(interface_pin):
                raise RuntimeError(f"macro data proof references exec pin: {macro_node_id}")

            interface_graph_id = str(interface_pin.get("graph_id", "") or "")
            if interface_graph_id != macro_graph_id:
                raise RuntimeError(
                    f"macro data interface graph mismatch: {macro_node_id} "
                    f"expected={macro_graph_id} actual={interface_graph_id}"
                )

            caller_blueprint_path = str(call_pin.get("blueprint_path", "") or "")
            caller_graph_id = str(call_pin.get("graph_id", "") or "")
            call_pin_name = str(binding.get("source_pin_name", "") or call_pin.get("name", "") or "")
            interface_pin_name = str(
                binding.get("target_pin_name", "") or interface_pin.get("name", "") or ""
            )
            route_kind = "macro_data_input" if relation == "binds_macro_input" else "macro_data_output"
            caller_sources: list[dict] = []
            body_consumers: list[dict] = []
            internal_sources: list[dict] = []
            dependencies: list[dict] = []
            caller_consumers: list[dict] = []
            value_kind = ""
            bridge_ready = False

            if relation == "binds_macro_input":
                incoming = canonical_data_incoming_by_pin.get(call_pin_id, [])
                body = canonical_data_outgoing_by_pin.get(interface_pin_id, [])
                caller_sources = sorted_endpoints(incoming, source=True)
                body_consumers = sorted_endpoints(body, source=False)
                if caller_sources:
                    value_kind = "connected_source"
                elif pin_has_authored_value(call_pin):
                    value_kind = "authored_value"
                else:
                    value_kind = "no_value_evidence"
                bridge_ready = value_kind != "no_value_evidence" and bool(body_consumers)
            elif relation == "binds_macro_output":
                internal = canonical_data_incoming_by_pin.get(interface_pin_id, [])
                deps = dependency_by_sink_pin.get(interface_pin_id, [])
                consumers = canonical_data_outgoing_by_pin.get(call_pin_id, [])
                internal_sources = sorted_endpoints(internal, source=True)
                dependencies = sorted(
                    [
                        {
                            "dependency_id": str(dep.get("dependency_id", "") or ""),
                            "text": str(dep.get("text", "") or ""),
                            "source_count": int(dep.get("source_count", 0) or 0),
                            "truncated": bool(dep.get("truncated", False)),
                            "cycle": bool(dep.get("cycle", False)),
                        }
                        for dep in deps
                    ],
                    key=lambda value: (value["dependency_id"], value["text"]),
                )
                caller_consumers = sorted_endpoints(consumers, source=False)
                value_kind = "derived_output"
                bridge_ready = bool(internal_sources and dependencies and caller_consumers)
            else:
                continue

            route_id = _id(
                "bpinterdata:",
                route_kind, macro_node_id, macro_graph_id, call_pin_id, interface_pin_id,
            )
            data_routes.append({
                "route_id": route_id,
                "schema_version": INTERPROCEDURAL_SCHEMA_VERSION,
                "route_kind": route_kind,
                "macro_node_id": macro_node_id,
                "macro_graph_id": macro_graph_id,
                "caller_blueprint_path": caller_blueprint_path,
                "caller_graph_id": caller_graph_id,
                "call_pin_id": call_pin_id,
                "call_pin_name": call_pin_name,
                "interface_pin_id": interface_pin_id,
                "interface_pin_name": interface_pin_name,
                "value_kind": value_kind,
                "caller_sources": caller_sources,
                "caller_source_count": len(caller_sources),
                "body_consumers": body_consumers,
                "body_consumer_count": len(body_consumers),
                "internal_sources": internal_sources,
                "internal_source_count": len(internal_sources),
                "dependencies": dependencies,
                "dependency_count": len(dependencies),
                "caller_consumers": caller_consumers,
                "caller_consumer_count": len(caller_consumers),
                "bridge_ready": bool(bridge_ready),
                "authored_default_value": str(call_pin.get("default_value", "") or ""),
                "authored_default_object": str(call_pin.get("default_object", "") or ""),
                "authored_default_text": str(call_pin.get("default_text", "") or ""),
                "evidence_kind": "macro_interface_exact_joined_data_provenance",
            })

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
    data_routes.sort(key=lambda row: (
        row["caller_blueprint_path"], row["caller_graph_id"], row["macro_node_id"],
        row["route_kind"], row["call_pin_id"], row["route_id"],
    ))
    return interprocedural_edges, terminals, data_routes


def derive_function_execution(output: Path, rows) -> tuple[list[dict], list[dict], dict]:
    """Materialize exact direct internal Blueprint function call/return topology.

    Eligibility follows the accepted function-target audit:
      - uniquely captured internal target,
      - not interface dispatch/declaration,
      - call node itself is impure,
      - not latent,
      - caller block and callee entry block are exact,
      - callee has an entry-reachable terminal block frontier,
      - every connected caller continuation maps to the caller graph.

    Pure target metadata may coexist with an impure call node; UE supports a
    node-level purity override and the call-site node governs exec participation.
    """
    output = Path(output)
    functions = {
        str(row.get("function_id", "") or ""): row
        for row in rows(output / "blueprint_functions.jsonl")
        if row.get("function_id")
    }
    blueprints = {
        str(row.get("object_path", "") or ""): row
        for row in rows(output / "blueprints.jsonl")
        if row.get("object_path")
    }
    call_bindings_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    bindings_path = output / "blueprint_call_bindings.jsonl"
    if bindings_path.is_file():
        for binding in rows(bindings_path):
            call_node_id = str(binding.get("call_node_id", "") or "")
            if call_node_id:
                call_bindings_by_node[call_node_id].append(binding)

    block_by_node, duplicates = _block_membership(output, rows)
    if duplicates:
        sample = ", ".join(sorted(duplicates)[:5])
        raise RuntimeError(f"Blueprint execution node belongs to multiple blocks: {sample}")

    block_by_id: dict[str, dict] = {}
    blocks_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    for block in rows(output / "blueprint_execution_blocks.jsonl"):
        block_id = str(block.get("block_id", "") or "")
        graph_id = str(block.get("graph_id", "") or "")
        if block_id:
            block_by_id[block_id] = block
        if graph_id:
            blocks_by_graph[graph_id].append(block)

    block_outgoing: dict[str, list[str]] = collections.defaultdict(list)
    for edge in rows(output / "blueprint_execution_block_edges.jsonl"):
        source_block_id = str(edge.get("source_block_id", "") or "")
        target_block_id = str(edge.get("target_block_id", "") or "")
        if source_block_id and target_block_id:
            block_outgoing[source_block_id].append(target_block_id)

    raw_exec_by_source_node: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in rows(output / "blueprint_edges.jsonl"):
        if str(edge.get("edge_kind", "") or "") != "execution":
            continue
        source_node_id = str(edge.get("source_node_id", "") or "")
        if source_node_id:
            raw_exec_by_source_node[source_node_id].append(edge)

    BPTYPE_INTERFACE = 3
    execution_edges: list[dict] = []
    terminals: list[dict] = []
    stats = collections.Counter()

    for call in rows(output / "blueprint_call_edges.jsonl"):
        stats["calls"] += 1
        if str(call.get("resolution", "") or "") != "internal":
            continue
        stats["internal"] += 1

        call_node_id = str(call.get("call_node_id", "") or "")
        target_function_id = str(call.get("target_function_id", "") or "")
        target = functions.get(target_function_id)
        if target is None:
            raise RuntimeError(
                f"internal Blueprint function call lacks target function row: {call_node_id}"
            )

        target_bp_path = str(
            call.get("target_blueprint_path", "")
            or target.get("blueprint_path", "")
            or ""
        )
        target_bp = blueprints.get(target_bp_path)
        if target_bp is None:
            raise RuntimeError(
                f"internal Blueprint function target lacks Blueprint row: {target_bp_path}"
            )
        try:
            target_bp_type = int(target_bp.get("blueprint_type", -1))
        except (TypeError, ValueError):
            raise RuntimeError(
                f"internal Blueprint function target has invalid Blueprint type: {target_bp_path}"
            )

        if bool(call.get("interface_call", False)) or target_bp_type == BPTYPE_INTERFACE:
            stats["excluded_interface"] += 1
            continue
        if bool(call.get("latent", False)):
            stats["excluded_latent"] += 1
            continue
        if bool(call.get("pure", False)):
            stats["excluded_pure"] += 1
            continue

        stats["direct_impure"] += 1
        caller_graph_id = str(call.get("graph_id", "") or "")
        caller_blueprint_path = str(call.get("blueprint_path", "") or "")
        caller_block = block_by_node.get(call_node_id)
        if caller_block is None:
            stats["excluded_unreachable_callsite"] += 1
            continue
        caller_block_id = str(caller_block.get("block_id", "") or "")
        if str(caller_block.get("graph_id", "") or "") != caller_graph_id:
            raise RuntimeError(
                f"function caller block graph mismatch: {call_node_id}"
            )

        entry_node_id = str(target.get("entry_node_id", "") or "")
        entry_block = block_by_node.get(entry_node_id)
        if entry_block is None:
            raise RuntimeError(
                f"direct internal function lacks entry execution block: {target_function_id}"
            )
        entry_block_id = str(entry_block.get("block_id", "") or "")
        if str(entry_block.get("graph_id", "") or "") != target_function_id:
            raise RuntimeError(
                f"function entry block graph mismatch: {target_function_id}"
            )

        reachable: set[str] = set()
        pending = [entry_block_id]
        while pending:
            block_id = pending.pop()
            if not block_id or block_id in reachable:
                continue
            block = block_by_id.get(block_id)
            if block is None:
                raise RuntimeError(
                    f"function reachable block is missing: {target_function_id}:{block_id}"
                )
            if str(block.get("graph_id", "") or "") != target_function_id:
                continue
            reachable.add(block_id)
            for target_block_id in block_outgoing.get(block_id, []):
                if target_block_id not in reachable:
                    pending.append(target_block_id)

        frontier = sorted(
            block_id for block_id in reachable
            if not [
                target_block_id
                for target_block_id in block_outgoing.get(block_id, [])
                if str(block_by_id.get(target_block_id, {}).get("graph_id", "") or "")
                    == target_function_id
            ]
        )
        if not frontier:
            raise RuntimeError(
                f"direct internal function lacks reachable return frontier: {target_function_id}"
            )

        target_blueprint_path = str(target.get("blueprint_path", "") or target_bp_path)
        call_binding_count = len(call_bindings_by_node.get(call_node_id, []))
        target_pure = bool(target.get("blueprint_pure", False))
        purity_override = bool(target_pure and not bool(call.get("pure", False)))

        enter_id = _id(
            "bpinterfnexec:",
            "function_enter", call_node_id, caller_block_id, entry_block_id,
        )
        execution_edges.append({
            "function_edge_id": enter_id,
            "schema_version": INTERPROCEDURAL_SCHEMA_VERSION,
            "edge_kind": "function_enter",
            "call_node_id": call_node_id,
            "target_function_id": target_function_id,
            "caller_blueprint_path": caller_blueprint_path,
            "caller_graph_id": caller_graph_id,
            "caller_block_id": caller_block_id,
            "source_blueprint_path": caller_blueprint_path,
            "source_graph_id": caller_graph_id,
            "source_block_id": caller_block_id,
            "source_node_id": call_node_id,
            "target_blueprint_path": target_blueprint_path,
            "target_graph_id": target_function_id,
            "target_block_id": entry_block_id,
            "target_node_id": entry_node_id,
            "continuation_node_id": "",
            "continuation_pin_id": "",
            "continuation_pin_name": "",
            "return_frontier_block_count": len(frontier),
            "call_binding_count": call_binding_count,
            "purity_override": purity_override,
            "evidence_kind": "exact_internal_function_entry_block",
        })
        stats["function_enter"] += 1

        outgoing = sorted(
            raw_exec_by_source_node.get(call_node_id, []),
            key=lambda edge: (
                str(edge.get("target_node_id", "") or ""),
                str(edge.get("target_pin_id", "") or ""),
            ),
        )
        if not outgoing:
            terminal_id = _id(
                "bpinterfnterm:",
                call_node_id, target_function_id, caller_block_id, *frontier,
            )
            terminals.append({
                "terminal_id": terminal_id,
                "schema_version": INTERPROCEDURAL_SCHEMA_VERSION,
                "terminal_kind": "function_call_no_continuation",
                "call_node_id": call_node_id,
                "target_function_id": target_function_id,
                "caller_blueprint_path": caller_blueprint_path,
                "caller_graph_id": caller_graph_id,
                "caller_block_id": caller_block_id,
                "target_blueprint_path": target_blueprint_path,
                "target_graph_id": target_function_id,
                "entry_block_id": entry_block_id,
                "entry_node_id": entry_node_id,
                "return_frontier_block_count": len(frontier),
                "return_frontier_block_ids": frontier,
                "call_binding_count": call_binding_count,
                "purity_override": purity_override,
                "canonical_outgoing_exec_count": 0,
                "evidence_kind": "exact_internal_function_no_caller_continuation",
            })
            stats["function_terminal"] += 1
            stats["terminal_frontier_blocks"] += len(frontier)
            continue

        stats["connected_calls"] += 1
        for raw_edge in outgoing:
            continuation_node_id = str(raw_edge.get("target_node_id", "") or "")
            continuation_pin_id = str(raw_edge.get("target_pin_id", "") or "")
            continuation_pin_name = str(raw_edge.get("target_pin_name", "") or "")
            continuation_block = block_by_node.get(continuation_node_id)
            if continuation_block is None:
                raise RuntimeError(
                    f"function continuation node lacks execution block: {continuation_node_id}"
                )
            continuation_block_id = str(continuation_block.get("block_id", "") or "")
            if str(continuation_block.get("graph_id", "") or "") != caller_graph_id:
                raise RuntimeError(
                    f"function continuation graph mismatch: {call_node_id}"
                )
            continuation_blueprint_path = str(
                continuation_block.get("blueprint_path", "") or caller_blueprint_path
            )

            for frontier_block_id in frontier:
                frontier_block = block_by_id.get(frontier_block_id, {})
                frontier_node_id = str(frontier_block.get("exit_node_id", "") or "")
                edge_id = _id(
                    "bpinterfnexec:",
                    "function_return", call_node_id, target_function_id,
                    frontier_block_id, continuation_block_id,
                    continuation_node_id, continuation_pin_id,
                )
                execution_edges.append({
                    "function_edge_id": edge_id,
                    "schema_version": INTERPROCEDURAL_SCHEMA_VERSION,
                    "edge_kind": "function_return",
                    "call_node_id": call_node_id,
                    "target_function_id": target_function_id,
                    "caller_blueprint_path": caller_blueprint_path,
                    "caller_graph_id": caller_graph_id,
                    "caller_block_id": caller_block_id,
                    "source_blueprint_path": target_blueprint_path,
                    "source_graph_id": target_function_id,
                    "source_block_id": frontier_block_id,
                    "source_node_id": frontier_node_id,
                    "target_blueprint_path": continuation_blueprint_path,
                    "target_graph_id": caller_graph_id,
                    "target_block_id": continuation_block_id,
                    "target_node_id": continuation_node_id,
                    "continuation_node_id": continuation_node_id,
                    "continuation_pin_id": continuation_pin_id,
                    "continuation_pin_name": continuation_pin_name,
                    "return_frontier_block_count": len(frontier),
                    "call_binding_count": call_binding_count,
                    "purity_override": purity_override,
                    "evidence_kind": "reachable_function_frontier_canonical_continuation",
                })
                stats["function_return"] += 1

    execution_edges.sort(key=lambda row: (
        row["caller_blueprint_path"], row["caller_graph_id"], row["call_node_id"],
        row["edge_kind"], row["source_block_id"], row["target_block_id"],
        row["continuation_pin_id"], row["function_edge_id"],
    ))
    terminals.sort(key=lambda row: (
        row["caller_blueprint_path"], row["caller_graph_id"], row["call_node_id"],
        row["terminal_id"],
    ))
    return execution_edges, terminals, dict(stats)


def validation_error(output: Path, rows) -> str | None:
    output = Path(output)
    for filename in DERIVED_FILES:
        if not (output / filename).is_file():
            return f"Blueprint interprocedural stream missing: {filename}"

    try:
        expected_edges, expected_terminals, expected_data_routes = derive(output, rows)
    except RuntimeError as exc:
        return str(exc)

    actual_edges = list(rows(output / DERIVED_FILES[0]))
    actual_terminals = list(rows(output / DERIVED_FILES[1]))
    actual_data_routes = list(rows(output / DERIVED_FILES[2]))

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
    if actual_data_routes != expected_data_routes:
        return (
            "Blueprint interprocedural data routes do not exactly match "
            "schema-4 macro proofs and canonical data provenance"
        )

    edge_ids = [str(row.get("interprocedural_edge_id", "") or "") for row in actual_edges]
    terminal_ids = [str(row.get("terminal_id", "") or "") for row in actual_terminals]
    route_ids = [str(row.get("route_id", "") or "") for row in actual_data_routes]
    if any(not value for value in edge_ids) or len(edge_ids) != len(set(edge_ids)):
        return "Blueprint interprocedural execution edges contain missing/duplicate ids"
    if any(not value for value in terminal_ids) or len(terminal_ids) != len(set(terminal_ids)):
        return "Blueprint interprocedural execution terminals contain missing/duplicate ids"
    if any(not value for value in route_ids) or len(route_ids) != len(set(route_ids)):
        return "Blueprint interprocedural data routes contain missing/duplicate ids"

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

    for row in actual_data_routes:
        if int(row.get("schema_version", 0) or 0) != INTERPROCEDURAL_SCHEMA_VERSION:
            return f"unexpected Blueprint interprocedural data schema: {row.get('schema_version')!r}"
        kind = str(row.get("route_kind", "") or "")
        if kind not in {"macro_data_input", "macro_data_output"}:
            return f"unexpected Blueprint interprocedural data route kind: {kind!r}"
        if not str(row.get("call_pin_id", "") or "") or not str(row.get("interface_pin_id", "") or ""):
            return f"Blueprint interprocedural data route lacks exact pin identity: {row.get('route_id')}"
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
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
    for row in rows(Path(output) / DERIVED_FILES[2]):
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_interprocedural_data_routes VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("route_id", ""), int(row.get("schema_version", 0) or 0),
                row.get("route_kind", ""), row.get("macro_node_id", ""),
                row.get("macro_graph_id", ""), row.get("caller_blueprint_path", ""),
                row.get("caller_graph_id", ""), row.get("call_pin_id", ""),
                row.get("call_pin_name", ""), row.get("interface_pin_id", ""),
                row.get("interface_pin_name", ""), row.get("value_kind", ""),
                int(row.get("caller_source_count", 0) or 0),
                int(row.get("body_consumer_count", 0) or 0),
                int(row.get("internal_source_count", 0) or 0),
                int(row.get("dependency_count", 0) or 0),
                int(row.get("caller_consumer_count", 0) or 0),
                1 if row.get("bridge_ready", False) else 0,
                row.get("authored_default_value", ""), row.get("authored_default_object", ""),
                row.get("authored_default_text", ""), row.get("evidence_kind", ""), _j(row),
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
    print("\n[Blueprint interprocedural data routes]")
    print_rows(
        conn.execute(
            """SELECT route_kind,caller_blueprint_path,call_pin_name,interface_pin_name,
                      value_kind,caller_source_count,body_consumer_count,internal_source_count,
                      dependency_count,caller_consumer_count,bridge_ready
               FROM blueprint_interprocedural_data_routes
               WHERE caller_blueprint_path LIKE ? OR route_kind LIKE ? OR call_pin_name LIKE ?
                  OR interface_pin_name LIKE ? OR value_kind LIKE ?
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, pattern, limit),
        ),
        (
            "route_kind", "caller_blueprint_path", "call_pin_name", "interface_pin_name",
            "value_kind", "caller_source_count", "body_consumer_count", "internal_source_count",
            "dependency_count", "caller_consumer_count", "bridge_ready",
        ),
    )
