#!/usr/bin/env python3
"""Exact static Blueprint delegate binding provenance.

Structural schema 13 captures the authoritative delegate member reference and
CreateDelegate endpoint identity. This module joins that native evidence through
canonical delegate-typed data edges into Bind/Assign nodes.

It intentionally models authored topology only. It does not model runtime
multicast subscriber sets, binding order/lifetime, broadcast execution, or
delegate object state.
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

import uatool_core as core

DELEGATE_BINDING_SCHEMA_VERSION = 3
DERIVED_FILES = ("blueprint_delegate_bindings.jsonl",)

_SQL = """
CREATE TABLE blueprint_delegate_bindings(
 binding_id TEXT PRIMARY KEY,schema_version INTEGER NOT NULL,
 blueprint_path TEXT NOT NULL,graph_id TEXT NOT NULL,
 bind_node_id TEXT NOT NULL,bind_operation TEXT NOT NULL,
 dispatcher_owner TEXT NOT NULL,dispatcher_name TEXT NOT NULL,
 dispatcher_member_guid TEXT NOT NULL,dispatcher_self_context TEXT NOT NULL,
 dispatcher_local_scope TEXT NOT NULL,dispatcher_member_scope TEXT NOT NULL,
 source_node_id TEXT NOT NULL,source_operation TEXT NOT NULL,
 source_pin_id TEXT NOT NULL,target_pin_id TEXT NOT NULL,
 source_resolution_basis TEXT NOT NULL,source_reroute_node_ids_json TEXT NOT NULL,
 source_route_json TEXT NOT NULL,
 endpoint_kind TEXT NOT NULL,endpoint_name TEXT NOT NULL,
 endpoint_id TEXT NOT NULL,endpoint_path TEXT NOT NULL,
 endpoint_blueprint_path TEXT NOT NULL,endpoint_graph_id TEXT NOT NULL,
 endpoint_local_resolution TEXT NOT NULL,endpoint_candidate_function_ids_json TEXT NOT NULL,
 selected_function_guid TEXT NOT NULL,selected_function_path TEXT NOT NULL,
 selected_function_scope_class TEXT NOT NULL,
 resolution_basis TEXT NOT NULL,evidence_kind TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX bp_delegate_bind_dispatcher_idx
 ON blueprint_delegate_bindings(dispatcher_owner,dispatcher_name);
CREATE INDEX bp_delegate_bind_endpoint_idx
 ON blueprint_delegate_bindings(endpoint_kind,endpoint_path,endpoint_id);
CREATE INDEX bp_delegate_bind_blueprint_idx
 ON blueprint_delegate_bindings(blueprint_path,graph_id);
"""


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _id(*parts: str) -> str:
    basis = "\x1f".join(str(part or "") for part in parts)
    return "bpdelegate:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


def _guid_key(value: str) -> str:
    value = str(value or "").strip().lower()
    for token in ("{", "}", "(", ")", "-", " "):
        value = value.replace(token, "")
    if len(value) == 32 and all(ch in "0123456789abcdef" for ch in value):
        return value
    return ""


def _node_guid_key(node: dict) -> str:
    node_id = str(node.get("node_id", "") or "")
    marker = "::node::"
    return _guid_key(node_id.rsplit(marker, 1)[1] if marker in node_id else "")


def _semantic(node: dict) -> dict:
    value = node.get("semantic", {})
    return value if isinstance(value, dict) else {}


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def derive(output: Path, rows) -> tuple[list[dict], dict]:
    output = Path(output)
    raw_nodes = list(rows(output / "blueprint_nodes.jsonl"))
    pins = list(core.iter_blueprint_pin_rows(output))

    node_by_id = {
        str(node.get("node_id", "") or ""): node
        for node in raw_nodes
        if node.get("node_id")
    }
    pin_by_id = {
        str(pin.get("pin_id", "") or ""): pin
        for pin in pins
        if pin.get("pin_id")
    }

    guid_nodes_by_blueprint: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for node in raw_nodes:
        blueprint_path = str(node.get("blueprint_path", "") or "")
        guid = _node_guid_key(node)
        if blueprint_path and guid:
            guid_nodes_by_blueprint[(blueprint_path, guid)].append(node)

    function_rows = list(rows(output / "blueprint_functions.jsonl"))
    functions_by_resolved: dict[str, list[dict]] = collections.defaultdict(list)
    for function in function_rows:
        resolved = str(function.get("resolved_function", "") or "")
        if resolved:
            functions_by_resolved[resolved].append(function)

    incoming_delegate_edges: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in rows(output / "blueprint_edges.jsonl"):
        if str(edge.get("edge_kind", "") or "") != "data":
            continue
        target_pin_id = str(edge.get("target_pin_id", "") or "")
        target_pin = pin_by_id.get(target_pin_id, {})
        pin_type = target_pin.get("type", {}) if isinstance(target_pin.get("type"), dict) else {}
        category = str(pin_type.get("category", "") or "").lower()
        if category not in {"delegate", "mcdelegate", "multicastdelegate"}:
            continue
        target_node_id = str(edge.get("target_node_id", "") or "")
        if target_node_id:
            incoming_delegate_edges[target_node_id].append(edge)

    def resolve_delegate_source(edge: dict, bind_node_id: str) -> tuple[dict, list[str], list[dict]]:
        current = edge
        seen: set[str] = set()
        reroutes_backwards: list[str] = []
        route_backwards: list[dict] = []

        while True:
            source_node_id = str(current.get("source_node_id", "") or "")
            source_node = node_by_id.get(source_node_id)
            if source_node is None:
                raise RuntimeError(
                    f"delegate binding source node missing: {bind_node_id} <- {source_node_id}"
                )

            route_backwards.append({
                "source_node_id": source_node_id,
                "source_pin_id": str(current.get("source_pin_id", "") or ""),
                "target_node_id": str(current.get("target_node_id", "") or ""),
                "target_pin_id": str(current.get("target_pin_id", "") or ""),
            })

            source_operation = str(source_node.get("operation", "") or "")
            if source_operation != "reroute":
                return (
                    source_node,
                    list(reversed(reroutes_backwards)),
                    list(reversed(route_backwards)),
                )

            if source_node_id in seen:
                raise RuntimeError(
                    f"delegate binding reroute cycle: {bind_node_id} <- {source_node_id}"
                )
            seen.add(source_node_id)
            reroutes_backwards.append(source_node_id)

            upstream = incoming_delegate_edges.get(source_node_id, [])
            if len(upstream) != 1:
                raise RuntimeError(
                    f"delegate binding reroute lacks unique delegate input: "
                    f"{bind_node_id} <- {source_node_id} incoming={len(upstream)}"
                )
            current = upstream[0]

    stats = collections.Counter()
    result: list[dict] = []

    for bind_node in raw_nodes:
        bind_operation = str(bind_node.get("operation", "") or "")
        if bind_operation not in {"delegate_bind", "delegate_assign"}:
            continue

        stats["bind_assign_nodes"] += 1
        bind_node_id = str(bind_node.get("node_id", "") or "")
        blueprint_path = str(bind_node.get("blueprint_path", "") or "")
        graph_id = str(bind_node.get("graph_id", "") or "")
        sem = _semantic(bind_node)

        dispatcher_owner = str(sem.get("delegate_owner", "") or "")
        dispatcher_name = str(sem.get("delegate_name", "") or "")
        dispatcher_guid = str(sem.get("delegate_member_guid", "") or "")
        dispatcher_self = sem.get("delegate_self_context")
        dispatcher_local = sem.get("delegate_local_scope")
        dispatcher_scope = str(sem.get("delegate_member_scope", "") or "")

        if not dispatcher_owner or not dispatcher_name:
            raise RuntimeError(
                f"delegate binding lacks exact dispatcher owner/name: {bind_node_id}"
            )
        if not dispatcher_guid:
            raise RuntimeError(
                f"delegate binding lacks structural-schema-13 member GUID: {bind_node_id}"
            )

        incoming = incoming_delegate_edges.get(bind_node_id, [])
        stats["delegate_input_edges"] += len(incoming)
        if not incoming:
            # An authored Bind/Assign node is only a resolved subscription when
            # a canonical delegate-typed data route reaches its delegate pin.
            # Keep zero-input sites visible in structural/semantic evidence,
            # but do not fabricate an endpoint or binding row.
            stats["unbound_bind_assign_nodes"] += 1
            stats[f"unbound_operation:{bind_operation}"] += 1
            continue

        for edge in incoming:
            source_node, source_reroute_node_ids, source_route = resolve_delegate_source(
                edge, bind_node_id
            )
            source_node_id = str(source_node.get("node_id", "") or "")
            source_operation = str(source_node.get("operation", "") or "")
            source_resolution_basis = (
                "transparent_reroute_chain"
                if source_reroute_node_ids else
                "direct"
            )
            stats[f"source_resolution:{source_resolution_basis}"] += 1
            stats["reroute_hops"] += len(source_reroute_node_ids)

            endpoint_kind = ""
            endpoint_name = ""
            endpoint_id = ""
            endpoint_path = ""
            endpoint_blueprint_path = ""
            endpoint_graph_id = ""
            endpoint_local_resolution = ""
            endpoint_candidate_function_ids: list[str] = []
            selected_function_guid_raw = ""
            selected_function_path = ""
            selected_function_scope_class = ""
            resolution_basis = ""

            if source_operation == "delegate_create":
                source_sem = _semantic(source_node)
                selected_name = str(source_sem.get("selected_function", "") or "")
                selected_function_guid_raw = str(
                    source_sem.get("selected_function_guid", "") or ""
                )
                selected_guid = _guid_key(selected_function_guid_raw)
                selected_function_path = str(
                    source_sem.get("selected_function_path", "") or ""
                )
                selected_function_scope_class = str(
                    source_sem.get("selected_function_scope_class", "") or ""
                )

                guid_candidates = (
                    guid_nodes_by_blueprint.get((blueprint_path, selected_guid), [])
                    if selected_guid else []
                )
                exact_event = None
                if len(guid_candidates) == 1:
                    candidate_operation = str(
                        guid_candidates[0].get("operation", "") or ""
                    )
                    if candidate_operation in {"custom_event", "event"}:
                        exact_event = guid_candidates[0]
                elif len(guid_candidates) > 1:
                    raise RuntimeError(
                        f"CreateDelegate selected GUID is not unique in Blueprint: "
                        f"{source_node_id} -> {selected_guid}"
                    )

                if exact_event is not None:
                    endpoint_operation = str(exact_event.get("operation", "") or "")
                    endpoint_kind = (
                        "custom_event" if endpoint_operation == "custom_event" else "event"
                    )
                    endpoint_name = str(
                        exact_event.get("symbol", "") or selected_name
                    )
                    endpoint_id = str(exact_event.get("node_id", "") or "")
                    endpoint_path = endpoint_id
                    endpoint_blueprint_path = str(
                        exact_event.get("blueprint_path", "") or ""
                    )
                    endpoint_graph_id = str(exact_event.get("graph_id", "") or "")
                    endpoint_local_resolution = "exact_captured_event_node"
                    resolution_basis = "selected_guid"
                    stats["create_delegate_event"] += 1
                elif selected_function_path:
                    # Structural schema 13 records SelectedFunctionPath directly
                    # from UE's resolved UFunction::GetPathName(). That path is
                    # authoritative endpoint identity even when more than one
                    # captured Blueprint function row maps back to the same
                    # generated/skeleton UFunction path.
                    candidates = functions_by_resolved.get(selected_function_path, [])
                    candidate_ids = sorted(
                        {
                            str(function.get("function_id", "") or "")
                            for function in candidates
                            if function.get("function_id")
                        }
                    )
                    endpoint_kind = "function"
                    endpoint_name = selected_name
                    endpoint_id = selected_function_path
                    endpoint_path = selected_function_path
                    endpoint_blueprint_path = (
                        str(candidates[0].get("blueprint_path", "") or "")
                        if candidates
                        and len(
                            {
                                str(function.get("blueprint_path", "") or "")
                                for function in candidates
                            }
                        ) == 1
                        else ""
                    )
                    endpoint_graph_id = candidate_ids[0] if len(candidate_ids) == 1 else ""
                    endpoint_local_resolution = (
                        "unique_captured_function"
                        if len(candidate_ids) == 1
                        else "multiple_captured_function_rows"
                        if candidate_ids
                        else "no_captured_function_row"
                    )
                    endpoint_candidate_function_ids = candidate_ids
                    resolution_basis = "selected_function_path"
                    stats["create_delegate_function"] += 1
                    stats[f"function_local:{endpoint_local_resolution}"] += 1
                else:
                    raise RuntimeError(
                        f"CreateDelegate lacks exact endpoint identity: {source_node_id}"
                    )
                stats["create_delegate_sources"] += 1

            elif source_operation in {"custom_event", "event"}:
                endpoint_kind = (
                    "custom_event" if source_operation == "custom_event" else "event"
                )
                endpoint_name = str(source_node.get("symbol", "") or "")
                endpoint_id = source_node_id
                endpoint_path = source_node_id
                endpoint_blueprint_path = str(source_node.get("blueprint_path", "") or "")
                endpoint_graph_id = str(source_node.get("graph_id", "") or "")
                endpoint_local_resolution = "exact_captured_event_node"
                resolution_basis = "direct_event_node"
                stats["direct_event_sources"] += 1
            else:
                raise RuntimeError(
                    f"delegate bind/assign has unsupported canonical delegate source "
                    f"{source_operation}: {bind_node_id} <- {source_node_id}"
                )

            source_pin_id = str(source_route[0].get("source_pin_id", "") or "")
            target_pin_id = str(edge.get("target_pin_id", "") or "")
            binding_id = _id(
                blueprint_path,
                graph_id,
                bind_node_id,
                dispatcher_owner,
                dispatcher_name.casefold(),
                dispatcher_guid,
                source_node_id,
                source_pin_id,
                target_pin_id,
                *source_reroute_node_ids,
                endpoint_kind,
                endpoint_id,
                endpoint_path,
            )
            row = {
                "binding_id": binding_id,
                "schema_version": DELEGATE_BINDING_SCHEMA_VERSION,
                "blueprint_path": blueprint_path,
                "graph_id": graph_id,
                "bind_node_id": bind_node_id,
                "bind_operation": bind_operation,
                "dispatcher_owner": dispatcher_owner,
                "dispatcher_name": dispatcher_name,
                "dispatcher_member_guid": dispatcher_guid,
                "dispatcher_self_context": dispatcher_self,
                "dispatcher_local_scope": dispatcher_local,
                "dispatcher_member_scope": dispatcher_scope,
                "source_node_id": source_node_id,
                "source_operation": source_operation,
                "source_pin_id": source_pin_id,
                "target_pin_id": target_pin_id,
                "source_resolution_basis": source_resolution_basis,
                "source_reroute_node_ids": source_reroute_node_ids,
                "source_route": source_route,
                "endpoint_kind": endpoint_kind,
                "endpoint_name": endpoint_name,
                "endpoint_id": endpoint_id,
                "endpoint_path": endpoint_path,
                "endpoint_blueprint_path": endpoint_blueprint_path,
                "endpoint_graph_id": endpoint_graph_id,
                "endpoint_local_resolution": endpoint_local_resolution,
                "endpoint_candidate_function_ids": endpoint_candidate_function_ids,
                "selected_function_guid": selected_function_guid_raw,
                "selected_function_path": selected_function_path,
                "selected_function_scope_class": selected_function_scope_class,
                "resolution_basis": resolution_basis,
                "evidence_kind": "exact_authored_delegate_binding",
            }
            result.append(row)
            stats["bindings"] += 1
            stats[f"operation:{bind_operation}"] += 1
            stats[f"endpoint:{endpoint_kind}"] += 1
            stats[f"basis:{resolution_basis}"] += 1

    result.sort(
        key=lambda row: (
            row["blueprint_path"],
            row["graph_id"],
            row["bind_node_id"],
            row["dispatcher_owner"],
            row["dispatcher_name"].casefold(),
            row["source_node_id"],
            row["binding_id"],
        )
    )
    return result, dict(stats)


def validation_error(output: Path, rows) -> str | None:
    output = Path(output)
    path = output / DERIVED_FILES[0]
    if not path.is_file():
        return f"{DERIVED_FILES[0]} missing"
    try:
        expected, _stats = derive(output, rows)
    except RuntimeError as exc:
        return str(exc)
    actual = list(rows(path))
    if actual != expected:
        return (
            "Blueprint delegate bindings do not exactly match structural-schema-13 "
            "dispatcher/endpoint evidence and canonical delegate data edges"
        )

    ids = [str(row.get("binding_id", "") or "") for row in actual]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        return "Blueprint delegate bindings contain missing/duplicate ids"
    for row in actual:
        if int(row.get("schema_version", 0) or 0) != DELEGATE_BINDING_SCHEMA_VERSION:
            return f"unexpected Blueprint delegate binding schema: {row.get('schema_version')!r}"
        if str(row.get("source_resolution_basis", "") or "") not in {
            "direct",
            "transparent_reroute_chain",
        }:
            return f"unexpected Blueprint delegate source basis: {row.get('source_resolution_basis')!r}"
        route = row.get("source_route", [])
        reroutes = row.get("source_reroute_node_ids", [])
        if not isinstance(route, list) or not route:
            return f"delegate binding lacks exact source route: {row.get('binding_id')}"
        if not isinstance(reroutes, list):
            return f"delegate binding reroute provenance invalid: {row.get('binding_id')}"
        if str(route[0].get("source_node_id", "") or "") != str(row.get("source_node_id", "") or ""):
            return f"delegate binding source route origin mismatch: {row.get('binding_id')}"
        if str(route[-1].get("target_node_id", "") or "") != str(row.get("bind_node_id", "") or ""):
            return f"delegate binding source route target mismatch: {row.get('binding_id')}"
        expected_basis = "transparent_reroute_chain" if reroutes else "direct"
        if str(row.get("source_resolution_basis", "") or "") != expected_basis:
            return f"delegate binding source basis/provenance mismatch: {row.get('binding_id')}"
        if str(row.get("bind_operation", "") or "") not in {
            "delegate_bind",
            "delegate_assign",
        }:
            return f"unexpected Blueprint delegate bind operation: {row.get('bind_operation')!r}"
        if str(row.get("resolution_basis", "") or "") not in {
            "selected_guid",
            "selected_function_path",
            "direct_event_node",
        }:
            return f"unexpected Blueprint delegate endpoint basis: {row.get('resolution_basis')!r}"
        if not str(row.get("dispatcher_owner", "") or ""):
            return f"delegate binding lacks dispatcher owner: {row.get('binding_id')}"
        if not str(row.get("dispatcher_member_guid", "") or ""):
            return f"delegate binding lacks member GUID: {row.get('binding_id')}"
    return None


def load_database(conn, output: Path, rows) -> None:
    for row in rows(Path(output) / DERIVED_FILES[0]):
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_delegate_bindings VALUES "
            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("binding_id", ""),
                int(row.get("schema_version", 0) or 0),
                row.get("blueprint_path", ""),
                row.get("graph_id", ""),
                row.get("bind_node_id", ""),
                row.get("bind_operation", ""),
                row.get("dispatcher_owner", ""),
                row.get("dispatcher_name", ""),
                row.get("dispatcher_member_guid", ""),
                _j(row.get("dispatcher_self_context")),
                _j(row.get("dispatcher_local_scope")),
                row.get("dispatcher_member_scope", ""),
                row.get("source_node_id", ""),
                row.get("source_operation", ""),
                row.get("source_pin_id", ""),
                row.get("target_pin_id", ""),
                row.get("source_resolution_basis", ""),
                _j(row.get("source_reroute_node_ids", [])),
                _j(row.get("source_route", [])),
                row.get("endpoint_kind", ""),
                row.get("endpoint_name", ""),
                row.get("endpoint_id", ""),
                row.get("endpoint_path", ""),
                row.get("endpoint_blueprint_path", ""),
                row.get("endpoint_graph_id", ""),
                row.get("endpoint_local_resolution", ""),
                _j(row.get("endpoint_candidate_function_ids", [])),
                row.get("selected_function_guid", ""),
                row.get("selected_function_path", ""),
                row.get("selected_function_scope_class", ""),
                row.get("resolution_basis", ""),
                row.get("evidence_kind", ""),
                _j(row),
            ),
        )


def query(conn, print_rows, pattern: str, limit: int) -> None:
    print("\n[Blueprint delegate bindings]")
    print_rows(
        conn.execute(
            """SELECT bind_operation,blueprint_path,dispatcher_owner,dispatcher_name,
                      endpoint_kind,endpoint_name,endpoint_path,resolution_basis
               FROM blueprint_delegate_bindings
               WHERE blueprint_path LIKE ? OR dispatcher_owner LIKE ?
                  OR dispatcher_name LIKE ? OR endpoint_name LIKE ?
                  OR endpoint_path LIKE ?
               LIMIT ?""",
            (pattern, pattern, pattern, pattern, pattern, limit),
        ),
        (
            "bind_operation",
            "blueprint_path",
            "dispatcher_owner",
            "dispatcher_name",
            "endpoint_kind",
            "endpoint_name",
            "endpoint_path",
            "resolution_basis",
        ),
    )
