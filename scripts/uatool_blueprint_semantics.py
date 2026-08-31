#!/usr/bin/env python3
"""Generic Blueprint semantic derivation over canonical UnrealAssetTool facts.

This layer deliberately does not know about Mover, GAS, Smart Objects, or other
gameplay domains. It normalizes every Blueprint node into a compact semantic
role, projects canonical execution/data edges into a uniform semantic graph,
and adds symbol/type/asset endpoint relations from exact scanner semantics.

Domain-specific models should consume these facts instead of reparsing K2 node
classes or reflected property blobs themselves.
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

SEMANTIC_SCHEMA_VERSION = 1
DERIVED_FILES = (
    "blueprint_semantic_nodes.jsonl",
    "blueprint_semantic_edges.jsonl",
    "blueprint_semantic_graphs.jsonl",
)

_SQL = """
CREATE TABLE blueprint_semantic_nodes(
 semantic_node_id TEXT PRIMARY KEY,node_id TEXT NOT NULL,blueprint_path TEXT NOT NULL,
 graph_id TEXT NOT NULL,graph_name TEXT NOT NULL,graph_kind TEXT NOT NULL,graph_system TEXT NOT NULL,
 node_class TEXT NOT NULL,operation TEXT NOT NULL,semantic_kind TEXT NOT NULL,primary_effect TEXT NOT NULL,
 access_kind TEXT NOT NULL,symbol_kind TEXT NOT NULL,symbol TEXT NOT NULL,owner TEXT NOT NULL,
 target_kind TEXT NOT NULL,target TEXT NOT NULL,opaque INTEGER NOT NULL,has_exec_flow INTEGER NOT NULL,
 exec_input_count INTEGER NOT NULL,exec_output_count INTEGER NOT NULL,data_input_count INTEGER NOT NULL,
 data_output_count INTEGER NOT NULL,connected_input_count INTEGER NOT NULL,connected_output_count INTEGER NOT NULL,
 literal_input_count INTEGER NOT NULL,pure TEXT NOT NULL,latent TEXT NOT NULL,interface_call TEXT NOT NULL,json TEXT NOT NULL
);
CREATE UNIQUE INDEX bp_sem_nodes_node_idx ON blueprint_semantic_nodes(node_id);
CREATE INDEX bp_sem_nodes_blueprint_idx ON blueprint_semantic_nodes(blueprint_path,graph_id);
CREATE INDEX bp_sem_nodes_kind_idx ON blueprint_semantic_nodes(semantic_kind,primary_effect);
CREATE INDEX bp_sem_nodes_symbol_idx ON blueprint_semantic_nodes(symbol_kind,symbol,owner);
CREATE INDEX bp_sem_nodes_target_idx ON blueprint_semantic_nodes(target_kind,target);

CREATE TABLE blueprint_semantic_edges(
 semantic_edge_id TEXT PRIMARY KEY,blueprint_path TEXT NOT NULL,graph_id TEXT NOT NULL,
 source_node_id TEXT NOT NULL,relation TEXT NOT NULL,target_kind TEXT NOT NULL,target TEXT NOT NULL,
 source_pin_id TEXT NOT NULL,target_pin_id TEXT NOT NULL,source_pin_name TEXT NOT NULL,target_pin_name TEXT NOT NULL,
 pin_category TEXT NOT NULL,evidence_kind TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX bp_sem_edges_source_idx ON blueprint_semantic_edges(source_node_id,relation);
CREATE INDEX bp_sem_edges_target_idx ON blueprint_semantic_edges(target_kind,target,relation);
CREATE INDEX bp_sem_edges_blueprint_idx ON blueprint_semantic_edges(blueprint_path,graph_id);

CREATE TABLE blueprint_semantic_graphs(
 graph_id TEXT PRIMARY KEY,blueprint_path TEXT NOT NULL,graph_name TEXT NOT NULL,graph_kind TEXT NOT NULL,
 graph_system TEXT NOT NULL,node_count INTEGER NOT NULL,classified_node_count INTEGER NOT NULL,
 opaque_node_count INTEGER NOT NULL,semantic_edge_count INTEGER NOT NULL,execution_flow_count INTEGER NOT NULL,
 data_flow_count INTEGER NOT NULL,endpoint_relation_count INTEGER NOT NULL,coverage REAL NOT NULL,
 operation_counts_json TEXT NOT NULL,semantic_kind_counts_json TEXT NOT NULL,
 opaque_node_class_counts_json TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX bp_sem_graphs_blueprint_idx ON blueprint_semantic_graphs(blueprint_path,graph_kind);
CREATE INDEX bp_sem_graphs_coverage_idx ON blueprint_semantic_graphs(coverage,opaque_node_count);
"""


def _j(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def _sid(prefix: str, *parts: str) -> str:
    basis = "\x1f".join(str(part or "") for part in parts)
    return prefix + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


# operation -> semantic_kind, primary_effect, access_kind, symbol_kind
_OPERATION_MODEL = {
    "function_entry": ("boundary", "control", "", "function"),
    "function_result": ("boundary", "control", "", "function"),
    "function_call": ("call", "call", "", "function"),
    "custom_event": ("event", "event", "", "event"),
    "event": ("event", "event", "", "event"),
    "variable_get": ("symbol_access", "read", "read", "variable"),
    "variable_set": ("symbol_access", "write", "write", "variable"),
    "variable_reference": ("symbol_access", "reference", "reference", "variable"),
    "dynamic_cast": ("type_operation", "cast", "", "class"),
    "spawn_actor": ("construction", "spawn", "", "class"),
    "macro_instance": ("call", "call", "", "macro"),
    "switch": ("control", "branch", "", ""),
    "select": ("value_operation", "select", "", ""),
    "execution_sequence": ("control", "sequence", "", ""),
    "branch": ("control", "branch", "", ""),
    "reroute": ("flow", "passthrough", "", ""),
    "tunnel": ("boundary", "control", "", ""),
    "self": ("value_source", "value", "", "object"),
    "comment": ("annotation", "annotation", "", ""),
    "make_struct": ("structure", "construct", "", "struct"),
    "break_struct": ("structure", "decompose", "", "struct"),
    "set_fields_in_struct": ("structure", "write", "write", "struct"),
    "struct_operation": ("structure", "transform", "", "struct"),
    "anim_state_machine": ("animation", "control", "", "animation_state_machine"),
    "anim_state_entry": ("animation", "control", "", "animation_state"),
    "anim_transition": ("animation", "branch", "", "animation_transition"),
    "anim_state": ("animation", "control", "", "animation_state"),
    "anim_conduit": ("animation", "branch", "", "animation_conduit"),
    "anim_state_alias": ("animation", "reference", "", "animation_state_alias"),
    "anim_save_cached_pose": ("animation", "write", "write", "pose_cache"),
    "anim_use_cached_pose": ("animation", "read", "read", "pose_cache"),
    "anim_linked_layer": ("animation", "call", "", "animation_layer"),
    "anim_linked_input_pose": ("animation", "value", "", "animation_pose"),
    "anim_slot": ("animation", "reference", "", "animation_slot"),
    "anim_sequence_player": ("animation", "read", "read", "animation_asset"),
    "anim_graph_root": ("animation", "control", "", ""),
    "anim_transition_result": ("animation", "control", "", ""),
    "anim_state_result": ("animation", "control", "", ""),
}


def _bool_text(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return ""


def _node_model(operation: str) -> tuple[str, str, str, str, bool]:
    operation = str(operation or "node")
    if operation in _OPERATION_MODEL:
        kind, effect, access, symbol_kind = _OPERATION_MODEL[operation]
        return kind, effect, access, symbol_kind, False
    if operation == "node":
        return "opaque", "opaque", "", "", True
    # Scanner-recognized future operations remain classified rather than being
    # silently demoted just because this vocabulary has not named them yet.
    if operation.startswith("anim_"):
        return "animation", "animation", "", "", False
    return "classified", "operation", "", "", False


def _target_for(node: dict, symbol_kind: str) -> tuple[str, str]:
    operation = str(node.get("operation", "") or "")
    symbol = str(node.get("symbol", "") or "")
    owner = str(node.get("owner", "") or "")
    sem = node.get("semantic", {})
    sem = sem if isinstance(sem, dict) else {}

    if operation in ("function_call", "function_entry", "function_result"):
        target = str(sem.get("resolved_function", "") or "")
        if not target and symbol:
            target = f"{owner}::{symbol}" if owner else symbol
        return "function", target
    if operation in ("variable_get", "variable_set", "variable_reference"):
        return "variable", f"{owner}::{symbol}" if owner and symbol else symbol or owner
    if operation in ("event", "custom_event"):
        return "event", f"{owner}::{symbol}" if owner and symbol else symbol or owner
    if operation == "dynamic_cast":
        return "class", str(sem.get("target_class", "") or owner)
    if operation == "spawn_actor":
        return "class", str(sem.get("spawn_class", "") or owner)
    if operation == "macro_instance":
        return "graph", str(sem.get("macro_graph", "") or symbol)
    if operation in ("make_struct", "break_struct", "set_fields_in_struct", "struct_operation"):
        return "struct", str(sem.get("struct_type", "") or owner or symbol)
    if operation == "self":
        return "object", owner
    if operation == "anim_sequence_player":
        return "animation_asset", str(sem.get("animation_asset", "") or owner)
    if operation == "anim_slot":
        return "animation_slot", str(sem.get("slot_name", "") or symbol)
    if operation in ("anim_save_cached_pose", "anim_use_cached_pose"):
        return "pose_cache", str(sem.get("cache_name", "") or symbol)
    if operation == "anim_linked_layer":
        return "animation_layer", str(sem.get("layer_name", "") or symbol)
    if operation == "anim_linked_input_pose":
        return "animation_pose", str(sem.get("pose_name", "") or symbol)
    if operation == "anim_state_machine":
        return "animation_state_machine", str(sem.get("state_machine_name", "") or symbol)
    if operation in ("anim_state", "anim_state_entry"):
        return "animation_state", str(sem.get("state_name", "") or sem.get("target_state", "") or symbol)
    if operation == "anim_transition":
        previous = str(sem.get("previous_state", "") or "")
        nxt = str(sem.get("next_state", "") or "")
        return "animation_transition", f"{previous}->{nxt}" if previous or nxt else symbol
    if symbol_kind and symbol:
        return symbol_kind, f"{owner}::{symbol}" if owner else symbol
    return "", ""


def _endpoint_relation(operation: str, access_kind: str, target_kind: str) -> str:
    return {
        "function_call": "calls",
        "function_entry": "defines_function",
        "function_result": "returns_from_function",
        "custom_event": "receives_event",
        "event": "receives_event",
        "variable_get": "reads",
        "variable_set": "writes",
        "variable_reference": "references",
        "dynamic_cast": "casts_to",
        "spawn_actor": "spawns",
        "macro_instance": "invokes_macro",
        "make_struct": "constructs",
        "break_struct": "decomposes",
        "set_fields_in_struct": "writes",
        "struct_operation": "transforms",
        "self": "references",
        "anim_sequence_player": "reads_animation",
        "anim_slot": "uses_animation_slot",
        "anim_save_cached_pose": "writes_pose_cache",
        "anim_use_cached_pose": "reads_pose_cache",
        "anim_linked_layer": "invokes_animation_layer",
        "anim_linked_input_pose": "uses_animation_pose",
        "anim_state_machine": "defines_animation_state_machine",
        "anim_state": "defines_animation_state",
        "anim_state_entry": "enters_animation_state",
        "anim_transition": "defines_animation_transition",
    }.get(operation, access_kind or ("references" if target_kind else ""))


def derive(output: Path, rows) -> tuple[list[dict], list[dict], list[dict]]:
    output = Path(output)
    raw_nodes = list(rows(output / "blueprint_nodes.jsonl"))
    raw_pins = list(rows(output / "blueprint_pins.jsonl"))
    raw_edges = list(rows(output / "blueprint_edges.jsonl"))

    pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for pin in raw_pins:
        node_id = str(pin.get("node_id", "") or "")
        if node_id:
            pins_by_node[node_id].append(pin)

    semantic_nodes: list[dict] = []
    node_ids: set[str] = set()
    graph_meta: dict[str, dict] = {}

    for node in raw_nodes:
        node_id = str(node.get("node_id", "") or "")
        if not node_id:
            raise RuntimeError("canonical Blueprint node missing node_id")
        if node_id in node_ids:
            raise RuntimeError(f"duplicate canonical Blueprint node_id: {node_id}")
        node_ids.add(node_id)
        operation = str(node.get("operation", "node") or "node")
        kind, effect, access, symbol_kind, opaque = _node_model(operation)
        pins = pins_by_node.get(node_id, [])
        exec_in = exec_out = data_in = data_out = connected_in = connected_out = literal_in = 0
        for pin in pins:
            direction = str(pin.get("direction", "") or "")
            pin_type = pin.get("type", {})
            pin_type = pin_type if isinstance(pin_type, dict) else {}
            is_exec = str(pin_type.get("category", "") or "") == "exec"
            linked = int(pin.get("linked_count", 0) or 0)
            if direction == "input":
                connected_in += int(linked > 0)
                if is_exec:
                    exec_in += 1
                else:
                    data_in += 1
                    if linked <= 0 and any(
                        str(pin.get(field, "") or "")
                        for field in ("default_value", "default_object", "default_text")
                    ):
                        literal_in += 1
            elif direction == "output":
                connected_out += int(linked > 0)
                if is_exec:
                    exec_out += 1
                else:
                    data_out += 1

        sem = node.get("semantic", {})
        sem = sem if isinstance(sem, dict) else {}
        target_kind, target = _target_for(node, symbol_kind)
        row = {
            "semantic_node_id": _sid("bpsemnode:", node_id),
            "node_id": node_id,
            "blueprint_path": str(node.get("blueprint_path", "") or ""),
            "graph_id": str(node.get("graph_id", "") or ""),
            "graph_name": str(node.get("graph_name", "") or ""),
            "graph_kind": str(node.get("graph_kind", "") or ""),
            "graph_system": str(node.get("graph_system", "") or ""),
            "node_class": str(node.get("node_class", "") or ""),
            "operation": operation,
            "semantic_kind": kind,
            "primary_effect": effect,
            "access_kind": access,
            "symbol_kind": symbol_kind,
            "symbol": str(node.get("symbol", "") or ""),
            "owner": str(node.get("owner", "") or ""),
            "target_kind": target_kind,
            "target": target,
            "opaque": bool(opaque),
            "has_exec_flow": bool(exec_in or exec_out),
            "exec_input_count": exec_in,
            "exec_output_count": exec_out,
            "data_input_count": data_in,
            "data_output_count": data_out,
            "connected_input_count": connected_in,
            "connected_output_count": connected_out,
            "literal_input_count": literal_in,
            "pure": _bool_text(sem.get("pure")),
            "latent": _bool_text(sem.get("latent")),
            "interface_call": _bool_text(sem.get("interface_call")),
        }
        semantic_nodes.append(row)
        graph_id = row["graph_id"]
        if graph_id and graph_id not in graph_meta:
            graph_meta[graph_id] = {
                "blueprint_path": row["blueprint_path"],
                "graph_name": row["graph_name"],
                "graph_kind": row["graph_kind"],
                "graph_system": row["graph_system"],
            }

    semantic_nodes.sort(key=lambda r: (r["blueprint_path"], r["graph_id"], r["node_id"]))
    semantic_by_id = {r["node_id"]: r for r in semantic_nodes}

    semantic_edges: list[dict] = []
    seen_edge_ids: set[str] = set()

    def add_edge(
        *, blueprint_path: str, graph_id: str, source_node_id: str, relation: str,
        target_kind: str, target: str, source_pin_id: str = "", target_pin_id: str = "",
        source_pin_name: str = "", target_pin_name: str = "", pin_category: str = "",
        evidence_kind: str,
    ) -> None:
        if not source_node_id or not relation or not target:
            return
        edge_id = _sid(
            "bpsemedge:", source_node_id, relation, target_kind, target,
            source_pin_id, target_pin_id, evidence_kind,
        )
        if edge_id in seen_edge_ids:
            return
        seen_edge_ids.add(edge_id)
        semantic_edges.append({
            "semantic_edge_id": edge_id,
            "blueprint_path": blueprint_path,
            "graph_id": graph_id,
            "source_node_id": source_node_id,
            "relation": relation,
            "target_kind": target_kind,
            "target": target,
            "source_pin_id": source_pin_id,
            "target_pin_id": target_pin_id,
            "source_pin_name": source_pin_name,
            "target_pin_name": target_pin_name,
            "pin_category": pin_category,
            "evidence_kind": evidence_kind,
        })

    for edge in raw_edges:
        edge_kind = str(edge.get("edge_kind", "") or "")
        relation = "controls_execution_of" if edge_kind == "execution" else "provides_value_to"
        add_edge(
            blueprint_path=str(edge.get("blueprint_path", "") or ""),
            graph_id=str(edge.get("graph_id", "") or ""),
            source_node_id=str(edge.get("source_node_id", "") or ""),
            relation=relation,
            target_kind="node",
            target=str(edge.get("target_node_id", "") or ""),
            source_pin_id=str(edge.get("source_pin_id", "") or ""),
            target_pin_id=str(edge.get("target_pin_id", "") or ""),
            source_pin_name=str(edge.get("source_pin_name", "") or ""),
            target_pin_name=str(edge.get("target_pin_name", "") or ""),
            pin_category=str(edge.get("pin_category", "") or ""),
            evidence_kind="blueprint_edge",
        )

    for node in semantic_nodes:
        if not node["target_kind"] or not node["target"]:
            continue
        relation = _endpoint_relation(node["operation"], node["access_kind"], node["target_kind"])
        if relation:
            add_edge(
                blueprint_path=node["blueprint_path"], graph_id=node["graph_id"],
                source_node_id=node["node_id"], relation=relation,
                target_kind=node["target_kind"], target=node["target"],
                evidence_kind="node_semantic",
            )

    semantic_edges.sort(key=lambda r: (
        r["blueprint_path"], r["graph_id"], r["source_node_id"],
        r["relation"], r["target_kind"], r["target"], r["source_pin_id"], r["target_pin_id"],
    ))

    nodes_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    edges_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    for row in semantic_nodes:
        nodes_by_graph[row["graph_id"]].append(row)
    for row in semantic_edges:
        edges_by_graph[row["graph_id"]].append(row)

    semantic_graphs: list[dict] = []
    for graph_id in sorted(nodes_by_graph):
        graph_nodes = nodes_by_graph[graph_id]
        graph_edges = edges_by_graph.get(graph_id, [])
        opaque = [row for row in graph_nodes if row["opaque"]]
        classified = len(graph_nodes) - len(opaque)
        operation_counts = collections.Counter(row["operation"] for row in graph_nodes)
        kind_counts = collections.Counter(row["semantic_kind"] for row in graph_nodes)
        opaque_class_counts = collections.Counter(row["node_class"] for row in opaque)
        meta = graph_meta.get(graph_id, {})
        semantic_graphs.append({
            "graph_id": graph_id,
            "blueprint_path": str(meta.get("blueprint_path", "") or ""),
            "graph_name": str(meta.get("graph_name", "") or ""),
            "graph_kind": str(meta.get("graph_kind", "") or ""),
            "graph_system": str(meta.get("graph_system", "") or ""),
            "node_count": len(graph_nodes),
            "classified_node_count": classified,
            "opaque_node_count": len(opaque),
            "semantic_edge_count": len(graph_edges),
            "execution_flow_count": sum(1 for edge in graph_edges if edge["relation"] == "controls_execution_of"),
            "data_flow_count": sum(1 for edge in graph_edges if edge["relation"] == "provides_value_to"),
            "endpoint_relation_count": sum(1 for edge in graph_edges if edge["target_kind"] != "node"),
            "coverage": (classified / len(graph_nodes)) if graph_nodes else 1.0,
            "operation_counts": dict(sorted(operation_counts.items())),
            "semantic_kind_counts": dict(sorted(kind_counts.items())),
            "opaque_node_class_counts": dict(sorted(opaque_class_counts.items())),
        })

    return semantic_nodes, semantic_edges, semantic_graphs


def validation_error(output: Path, rows) -> str | None:
    output = Path(output)
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        return "manifest.json missing"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "manifest.json invalid"
    if int(manifest.get("blueprint_semantic_schema_version", 0) or 0) != SEMANTIC_SCHEMA_VERSION:
        return f"unexpected Blueprint semantic schema {manifest.get('blueprint_semantic_schema_version')!r}"
    declared = manifest.get("derived_counts", {})
    if not isinstance(declared, dict):
        return "derived_counts missing or invalid"

    for filename in DERIVED_FILES:
        path = output / filename
        if not path.is_file():
            return f"Blueprint semantic stream missing: {filename}"
        key = filename.removesuffix(".jsonl")
        actual = sum(1 for _ in rows(path))
        if int(declared.get(key, -1)) != actual:
            return f"Blueprint semantic count mismatch for {key}: manifest={declared.get(key)} actual={actual}"

    raw_nodes = list(rows(output / "blueprint_nodes.jsonl"))
    semantic_nodes = list(rows(output / DERIVED_FILES[0]))
    raw_ids = [str(row.get("node_id", "") or "") for row in raw_nodes]
    semantic_ids = [str(row.get("node_id", "") or "") for row in semantic_nodes]
    if len(raw_ids) != len(set(raw_ids)):
        return "canonical Blueprint nodes contain duplicate node_id"
    if len(semantic_ids) != len(set(semantic_ids)):
        return "Blueprint semantic nodes contain duplicate node_id"
    if set(raw_ids) != set(semantic_ids):
        return "Blueprint semantic node coverage does not exactly match canonical Blueprint nodes"

    node_by_id = {str(row.get("node_id", "")): row for row in semantic_nodes}
    raw_flow = collections.Counter()
    for edge in rows(output / "blueprint_edges.jsonl"):
        relation = "controls_execution_of" if edge.get("edge_kind") == "execution" else "provides_value_to"
        raw_flow[(
            str(edge.get("source_node_id", "") or ""), relation,
            str(edge.get("target_node_id", "") or ""),
            str(edge.get("source_pin_id", "") or ""), str(edge.get("target_pin_id", "") or ""),
        )] += 1

    semantic_flow = collections.Counter()
    edges = list(rows(output / DERIVED_FILES[1]))
    edge_ids: set[str] = set()
    for edge in edges:
        edge_id = str(edge.get("semantic_edge_id", "") or "")
        if not edge_id or edge_id in edge_ids:
            return f"duplicate or missing Blueprint semantic edge id: {edge_id!r}"
        edge_ids.add(edge_id)
        source = str(edge.get("source_node_id", "") or "")
        if source not in node_by_id:
            return f"Blueprint semantic edge source node missing: {source}"
        if edge.get("target_kind") == "node":
            target = str(edge.get("target", "") or "")
            if target not in node_by_id:
                return f"Blueprint semantic edge target node missing: {target}"
            semantic_flow[(
                source, str(edge.get("relation", "") or ""), target,
                str(edge.get("source_pin_id", "") or ""), str(edge.get("target_pin_id", "") or ""),
            )] += 1
    if raw_flow != semantic_flow:
        return "Blueprint semantic flow edges do not exactly reconstruct canonical Blueprint edges"

    graphs = list(rows(output / DERIVED_FILES[2]))
    graph_ids = [str(row.get("graph_id", "") or "") for row in graphs]
    if len(graph_ids) != len(set(graph_ids)):
        return "duplicate Blueprint semantic graph summary"
    nodes_by_graph = collections.Counter(str(row.get("graph_id", "") or "") for row in semantic_nodes)
    edges_by_graph = collections.Counter(str(row.get("graph_id", "") or "") for row in edges)
    for graph in graphs:
        graph_id = str(graph.get("graph_id", "") or "")
        if int(graph.get("node_count", -1)) != nodes_by_graph[graph_id]:
            return f"Blueprint semantic graph node_count mismatch: {graph_id}"
        if int(graph.get("semantic_edge_count", -1)) != edges_by_graph[graph_id]:
            return f"Blueprint semantic graph semantic_edge_count mismatch: {graph_id}"
        classified = int(graph.get("classified_node_count", -1))
        opaque = int(graph.get("opaque_node_count", -1))
        if classified + opaque != int(graph.get("node_count", -1)):
            return f"Blueprint semantic graph classified/opaque mismatch: {graph_id}"
    if set(graph_ids) != set(nodes_by_graph):
        return "Blueprint semantic graph summaries do not exactly cover Blueprint graphs with nodes"
    return None


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def load_database(conn, output: Path, rows) -> None:
    for row in rows(Path(output) / DERIVED_FILES[0]):
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_semantic_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("semantic_node_id", ""), row.get("node_id", ""), row.get("blueprint_path", ""),
                row.get("graph_id", ""), row.get("graph_name", ""), row.get("graph_kind", ""),
                row.get("graph_system", ""), row.get("node_class", ""), row.get("operation", ""),
                row.get("semantic_kind", ""), row.get("primary_effect", ""), row.get("access_kind", ""),
                row.get("symbol_kind", ""), row.get("symbol", ""), row.get("owner", ""),
                row.get("target_kind", ""), row.get("target", ""), int(bool(row.get("opaque", False))),
                int(bool(row.get("has_exec_flow", False))), int(row.get("exec_input_count", 0) or 0),
                int(row.get("exec_output_count", 0) or 0), int(row.get("data_input_count", 0) or 0),
                int(row.get("data_output_count", 0) or 0), int(row.get("connected_input_count", 0) or 0),
                int(row.get("connected_output_count", 0) or 0), int(row.get("literal_input_count", 0) or 0),
                row.get("pure", ""), row.get("latent", ""), row.get("interface_call", ""), _j(row),
            ),
        )
    for row in rows(Path(output) / DERIVED_FILES[1]):
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_semantic_edges VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("semantic_edge_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""),
                row.get("source_node_id", ""), row.get("relation", ""), row.get("target_kind", ""),
                row.get("target", ""), row.get("source_pin_id", ""), row.get("target_pin_id", ""),
                row.get("source_pin_name", ""), row.get("target_pin_name", ""), row.get("pin_category", ""),
                row.get("evidence_kind", ""), _j(row),
            ),
        )
    for row in rows(Path(output) / DERIVED_FILES[2]):
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_semantic_graphs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("graph_id", ""), row.get("blueprint_path", ""), row.get("graph_name", ""),
                row.get("graph_kind", ""), row.get("graph_system", ""), int(row.get("node_count", 0) or 0),
                int(row.get("classified_node_count", 0) or 0), int(row.get("opaque_node_count", 0) or 0),
                int(row.get("semantic_edge_count", 0) or 0), int(row.get("execution_flow_count", 0) or 0),
                int(row.get("data_flow_count", 0) or 0), int(row.get("endpoint_relation_count", 0) or 0),
                float(row.get("coverage", 0.0) or 0.0), _j(row.get("operation_counts", {})),
                _j(row.get("semantic_kind_counts", {})), _j(row.get("opaque_node_class_counts", {})), _j(row),
            ),
        )


def query(conn, print_rows, pattern: str, limit: int) -> None:
    print("\n[blueprint semantic nodes]")
    print_rows(
        conn.execute(
            """
            SELECT blueprint_path,graph_name,operation,semantic_kind,primary_effect,symbol,owner,target_kind,target
            FROM blueprint_semantic_nodes
            WHERE blueprint_path LIKE ? OR graph_name LIKE ? OR operation LIKE ? OR semantic_kind LIKE ?
               OR primary_effect LIKE ? OR symbol LIKE ? OR owner LIKE ? OR target LIKE ? OR node_class LIKE ?
            LIMIT ?
            """,
            (pattern,) * 9 + (limit,),
        ),
        ("blueprint_path", "graph_name", "operation", "semantic_kind", "primary_effect", "symbol", "owner", "target_kind", "target"),
    )
    print("\n[blueprint semantic edges]")
    print_rows(
        conn.execute(
            """
            SELECT blueprint_path,source_node_id,relation,target_kind,target,source_pin_name,target_pin_name
            FROM blueprint_semantic_edges
            WHERE blueprint_path LIKE ? OR source_node_id LIKE ? OR relation LIKE ? OR target_kind LIKE ?
               OR target LIKE ? OR source_pin_name LIKE ? OR target_pin_name LIKE ?
            LIMIT ?
            """,
            (pattern,) * 7 + (limit,),
        ),
        ("blueprint_path", "source_node_id", "relation", "target_kind", "target", "source_pin_name", "target_pin_name"),
    )
    print("\n[blueprint semantic coverage]")
    print_rows(
        conn.execute(
            """
            SELECT blueprint_path,graph_name,graph_kind,node_count,classified_node_count,opaque_node_count,
                   ROUND(coverage*100.0,2) coverage_percent,opaque_node_class_counts_json
            FROM blueprint_semantic_graphs
            WHERE blueprint_path LIKE ? OR graph_name LIKE ? OR graph_kind LIKE ? OR graph_system LIKE ?
               OR operation_counts_json LIKE ? OR opaque_node_class_counts_json LIKE ?
            LIMIT ?
            """,
            (pattern,) * 6 + (limit,),
        ),
        ("blueprint_path", "graph_name", "graph_kind", "node_count", "classified_node_count",
         "opaque_node_count", "coverage_percent", "opaque_node_class_counts_json"),
    )
