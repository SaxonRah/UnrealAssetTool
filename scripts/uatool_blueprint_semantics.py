#!/usr/bin/env python3
"""Generic Blueprint semantic derivation over canonical UnrealAssetTool facts.

This layer is intentionally gameplay-domain neutral. It normalizes Blueprint
nodes into broad program roles, preserves canonical exec/data topology exactly,
and joins Control Rig editor wrappers to the authoritative RigVM model through
the already-derived rigvm_editor_links stream. Project-authored macro instances
are also joined to uniquely captured macro graphs and exact tunnel-interface
pins when canonical graph/pin evidence proves those bindings.

Mover, GAS, Smart Objects, and other gameplay systems should consume these
facts instead of adding K2-node special cases here.
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

SEMANTIC_SCHEMA_VERSION = 4
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


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _sid(prefix: str, *parts: str) -> str:
    basis = "\x1f".join(str(part or "") for part in parts)
    return prefix + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


# operation -> semantic_kind, primary_effect, access_kind, symbol_kind
#
# These are generic program roles. They intentionally describe *what kind of
# operation a reflected node is* without asserting gameplay-domain meaning.
_OPERATION_MODEL = {
    "function_entry": ("boundary", "control", "", "function"),
    "function_result": ("boundary", "control", "", "function"),
    "function_call": ("call", "call", "", "function"),
    "custom_event": ("event", "event", "", "event"),
    "event": ("event", "event", "", "event"),
    "variable_get": ("symbol_access", "read", "read", "variable"),
    "variable_set": ("symbol_access", "write", "write", "variable"),
    "variable_set_ref": ("symbol_access", "write", "write", "variable"),
    "variable_reference": ("symbol_access", "reference", "reference", "variable"),
    "property_access": ("symbol_access", "read", "read", "property_path"),
    "dynamic_cast": ("type_operation", "cast", "", "class"),
    "cast_byte_to_enum": ("conversion", "cast", "", "enum"),
    "spawn_actor": ("construction", "spawn", "", "class"),
    "add_component_by_class": ("construction", "construct", "", "class"),
    "create_object": ("construction", "construct", "", "class"),
    "create_widget": ("construction", "construct", "", "class"),
    "macro_instance": ("call", "call", "", "macro"),
    "async_action": ("async_call", "call", "", "function"),
    "gameplay_task_call": ("async_call", "call", "", "function"),
    "ai_move_to": ("async_call", "call", "", "function"),
    "mover_play_montage": ("call", "call", "", "function"),
    "anim_play_montage": ("call", "call", "", "function"),
    "in_app_purchase_query": ("async_call", "call", "", "function"),
    "in_app_purchase_checkout": ("async_call", "call", "", "function"),
    "in_app_purchase_finalize": ("async_call", "call", "", "function"),
    "switch": ("control", "branch", "", ""),
    "select": ("value_operation", "select", "", ""),
    "execution_sequence": ("control", "sequence", "", ""),
    "branch": ("control", "branch", "", ""),
    "map_for_each": ("control", "loop", "", "map"),
    "timeline": ("control", "sequence", "", "timeline"),
    "reroute": ("flow", "passthrough", "", ""),
    "tunnel": ("boundary", "control", "", ""),
    "self": ("value_source", "value", "", "object"),
    "comment": ("annotation", "annotation", "", ""),
    "make_struct": ("structure", "construct", "", "struct"),
    "break_struct": ("structure", "decompose", "", "struct"),
    "set_fields_in_struct": ("structure", "write", "write", "struct"),
    "struct_operation": ("structure", "transform", "", "struct"),
    "make_array": ("collection", "construct", "", "array"),
    "array_get": ("collection", "read", "read", "array"),
    "make_map": ("collection", "construct", "", "map"),
    "enum_equal": ("comparison", "compare", "", "enum"),
    "enum_not_equal": ("comparison", "compare", "", "enum"),
    "enum_to_string": ("conversion", "convert", "", "enum"),
    "format_text": ("value_operation", "format", "", "text"),
    "convert_asset": ("conversion", "convert", "", "object"),
    "load_asset": ("asset_access", "load", "read", "object"),
    "load_asset_class": ("asset_access", "load", "read", "class"),
    "get_class_defaults": ("type_operation", "read", "read", "class"),
    "delegate_bind": ("delegate", "bind", "write", "delegate"),
    "delegate_assign": ("delegate", "bind", "write", "delegate"),
    "delegate_unbind": ("delegate", "unbind", "write", "delegate"),
    "delegate_create": ("delegate", "construct", "", "delegate"),
    "delegate_call": ("delegate", "call", "", "delegate"),
    "delegate_clear": ("delegate", "clear", "write", "delegate"),
    "input_key": ("event", "event", "", "input"),
    "input_debug_key": ("event", "event", "", "input"),
    "legacy_input_action": ("event", "event", "", "input_action"),
    "enhanced_input_event": ("event", "event", "", "input_action"),
    "enhanced_input_value": ("value_source", "read", "read", "input_action"),
    "get_subsystem": ("value_source", "read", "read", "subsystem"),
    "get_engine_subsystem": ("value_source", "read", "read", "subsystem"),
    "get_editor_subsystem": ("value_source", "read", "read", "subsystem"),
    "get_subsystem_from_player_controller": ("value_source", "read", "read", "subsystem"),
    "data_table_row": ("data_access", "read", "read", "data_table"),
    "evaluate_chooser": ("selection", "select", "", "chooser"),
    "chooser_context_parameters": ("value_source", "read", "read", "chooser_context"),
    "evaluate_proxy": ("selection", "select", "", "proxy"),
    "evaluate_live_link_frame": ("data_access", "read", "read", "live_link"),
    "anim_node_reference": ("animation", "reference", "reference", "animation_node"),
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
    if operation == "control_rig_node":
        # A ControlRigGraphNode is an editor wrapper. It becomes modeled only
        # when the authoritative RigVM bridge resolves it below.
        return "classified", "operation", "", "", False
    # Many AnimGraph node classes are already scanner-normalized under stable
    # anim_* operation names. Preserve that broad semantic role without guessing
    # a finer effect that the scanner did not establish.
    if operation.startswith("anim_"):
        return "animation", "animation", "", "", False
    return "classified", "operation", "", "", False


def _rigvm_model(link: dict) -> tuple[str, str, str, str]:
    operation = str(link.get("rigvm_operation", "") or "")
    resolved_function = str(link.get("resolved_function_name", "") or "")
    template = str(link.get("template_notation", "") or "")

    if operation == "rigvm_function_entry":
        return "boundary", "control", "", "function"
    if operation == "rigvm_function_return":
        return "boundary", "control", "", "function"
    if operation == "rigvm_reroute":
        return "flow", "passthrough", "", ""
    if operation == "rigvm_variable":
        # Directional read/write semantics live in RigVM pins. At wrapper-node
        # level we can state exact variable/reference identity without guessing.
        return "symbol_access", "reference", "reference", "variable"
    if operation == "rigvm_function_reference":
        return "call", "call", "", "function"
    if operation == "rigvm_library":
        return "call", "call", "", "rigvm_library"
    if operation in {"rigvm_dispatch", "rigvm_unit"} and (resolved_function or (template and template != "None")):
        return "call", "call", "", "function"
    return "rig_operation", "execute", "", "rigvm_node"


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
    if operation in ("variable_get", "variable_set", "variable_set_ref", "variable_reference"):
        return "variable", f"{owner}::{symbol}" if owner and symbol else symbol or owner
    if operation == "property_access":
        return "property_path", str(sem.get("access_path", "") or sem.get("text_path", "") or symbol)
    if operation in ("event", "custom_event"):
        return "event", f"{owner}::{symbol}" if owner and symbol else symbol or owner
    if operation in ("input_key", "input_debug_key"):
        return "input", symbol
    if operation in ("legacy_input_action", "enhanced_input_event", "enhanced_input_value"):
        return "input_action", str(sem.get("input_action", "") or sem.get("input_action_name", "") or owner or symbol)
    if operation in ("delegate_bind", "delegate_assign", "delegate_unbind", "delegate_create", "delegate_call", "delegate_clear"):
        delegate = str(sem.get("delegate_name", "") or symbol)
        delegate_owner = str(sem.get("delegate_owner", "") or owner)
        return "delegate", f"{delegate_owner}::{delegate}" if delegate_owner and delegate else delegate or delegate_owner
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
        "variable_set_ref": "writes",
        "variable_reference": "references",
        "property_access": "reads",
        "dynamic_cast": "casts_to",
        "spawn_actor": "spawns",
        "macro_instance": "invokes_macro",
        "delegate_bind": "binds_delegate",
        "delegate_assign": "binds_delegate",
        "delegate_unbind": "unbinds_delegate",
        "delegate_create": "creates_delegate",
        "delegate_call": "calls_delegate",
        "delegate_clear": "clears_delegate",
        "input_key": "receives_input",
        "input_debug_key": "receives_input",
        "legacy_input_action": "receives_input",
        "enhanced_input_event": "receives_input",
        "enhanced_input_value": "reads_input",
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
        "control_rig_node": "maps_to_rigvm_node",
    }.get(operation, access_kind or ("references" if target_kind else ""))


def _load_rigvm_links(output: Path, rows) -> dict[str, dict]:
    path = output / "rigvm_editor_links.jsonl"
    links: dict[str, dict] = {}
    if not path.is_file():
        return links
    for link in rows(path):
        node_id = str(link.get("node_id", "") or "")
        if not node_id:
            continue
        if node_id in links:
            raise RuntimeError(f"duplicate RigVM editor link node_id: {node_id}")
        links[node_id] = link
    return links


def _pin_is_output(pin: dict) -> bool:
    return str(pin.get("direction", "") or "").lower() in {"output", "egpd_output", "1"}


def _macro_pin_type_signature(pin: dict) -> tuple:
    pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
    return (
        str(pin_type.get("category", "") or ""),
        str(pin_type.get("subcategory", "") or ""),
        str(pin_type.get("subcategory_object", "") or ""),
        int(pin_type.get("container_type", 0) or 0),
        bool(pin_type.get("is_reference", False)),
        bool(pin_type.get("is_const", False)),
    )


def _derive_macro_bridges(
    raw_nodes: list[dict],
    raw_pins: list[dict],
    raw_graphs: list[dict],
) -> dict[str, dict]:
    graph_rows_by_path: dict[str, list[dict]] = collections.defaultdict(list)
    for graph in raw_graphs:
        graph_path = str(graph.get("graph_path", "") or "")
        if graph_path:
            graph_rows_by_path[graph_path].append(graph)

    nodes_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    for node in raw_nodes:
        graph_id = str(node.get("graph_id", "") or "")
        if graph_id:
            nodes_by_graph[graph_id].append(node)

    pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for pin in raw_pins:
        node_id = str(pin.get("node_id", "") or "")
        if node_id:
            pins_by_node[node_id].append(pin)

    def tunnel_shape(node: dict) -> str:
        pins = pins_by_node.get(str(node.get("node_id", "") or ""), [])
        inputs = sum(int(not _pin_is_output(pin)) for pin in pins)
        outputs = sum(int(_pin_is_output(pin)) for pin in pins)
        if inputs and outputs:
            return "bidirectional"
        if outputs:
            return "output_only"
        if inputs:
            return "input_only"
        return "pinless"

    bridges: dict[str, dict] = {}
    for node in raw_nodes:
        if str(node.get("operation", "") or "") != "macro_instance":
            continue
        node_id = str(node.get("node_id", "") or "")
        sem = node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {}
        macro_graph = str(sem.get("macro_graph", "") or "")
        source_blueprint = str(sem.get("source_blueprint", "") or "")
        bridge = {
            "status": "missing_graph_identity",
            "macro_graph": macro_graph,
            "source_blueprint": source_blueprint,
            "graph_id": "",
            "interface_status": "unavailable",
            "interface_pin_count": 0,
            "binding_count": 0,
            "bindings": [],
        }
        if not macro_graph:
            bridges[node_id] = bridge
            continue

        graph_candidates = graph_rows_by_path.get(macro_graph, [])
        if not graph_candidates:
            bridge["status"] = "external_or_unscanned"
            bridges[node_id] = bridge
            continue
        if len(graph_candidates) != 1:
            bridge["status"] = "ambiguous_captured_graph_path"
            bridges[node_id] = bridge
            continue

        graph = graph_candidates[0]
        graph_id = str(graph.get("graph_id", "") or "")
        bridge["status"] = "matched"
        bridge["graph_id"] = graph_id

        tunnels = [
            candidate for candidate in nodes_by_graph.get(graph_id, [])
            if str(candidate.get("operation", "") or "") == "tunnel"
        ]
        entries = [candidate for candidate in tunnels if tunnel_shape(candidate) == "output_only"]
        exits = [candidate for candidate in tunnels if tunnel_shape(candidate) == "input_only"]
        if len(entries) != 1 or len(exits) != 1:
            bridge["interface_status"] = "unresolved_roles"
            bridges[node_id] = bridge
            continue

        bridge["interface_status"] = "exact_roles"
        entry_pins = [
            pin for pin in pins_by_node.get(str(entries[0].get("node_id", "") or ""), [])
            if _pin_is_output(pin)
        ]
        exit_pins = [
            pin for pin in pins_by_node.get(str(exits[0].get("node_id", "") or ""), [])
            if not _pin_is_output(pin)
        ]
        instance_pins = list(pins_by_node.get(node_id, []))
        bridge["interface_pin_count"] = len(instance_pins)

        bindings: list[dict] = []
        for instance_pin in instance_pins:
            relation = "binds_macro_output" if _pin_is_output(instance_pin) else "binds_macro_input"
            candidates = exit_pins if _pin_is_output(instance_pin) else entry_pins
            pin_name = str(instance_pin.get("name", "") or "")
            same_name = [
                candidate for candidate in candidates
                if str(candidate.get("name", "") or "") == pin_name
            ]
            exact = [
                candidate for candidate in same_name
                if _macro_pin_type_signature(candidate) == _macro_pin_type_signature(instance_pin)
            ]
            if len(exact) != 1:
                continue
            target_pin = exact[0]
            pin_type = instance_pin.get("type", {}) if isinstance(instance_pin.get("type"), dict) else {}
            bindings.append({
                "relation": relation,
                "source_pin_id": str(instance_pin.get("pin_id", "") or ""),
                "target_pin_id": str(target_pin.get("pin_id", "") or ""),
                "source_pin_name": pin_name,
                "target_pin_name": str(target_pin.get("name", "") or ""),
                "pin_category": str(pin_type.get("category", "") or ""),
            })

        bridge["bindings"] = bindings
        bridge["binding_count"] = len(bindings)
        bridge["interface_status"] = (
            "exact_bindings" if len(bindings) == len(instance_pins) else "partial_bindings"
        )
        bridges[node_id] = bridge

    return bridges


def derive(output: Path, rows) -> tuple[list[dict], list[dict], list[dict]]:
    output = Path(output)
    raw_nodes = list(rows(output / "blueprint_nodes.jsonl"))
    raw_pins = list(rows(output / "blueprint_pins.jsonl"))
    raw_edges = list(rows(output / "blueprint_edges.jsonl"))
    raw_graphs = list(rows(output / "blueprint_graphs.jsonl"))
    rigvm_links = _load_rigvm_links(output, rows)
    macro_bridges = _derive_macro_bridges(raw_nodes, raw_pins, raw_graphs)

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
        rigvm_link = rigvm_links.get(node_id) if operation == "control_rig_node" else None
        rigvm_matched = bool(
            rigvm_link
            and str(rigvm_link.get("status", "") or "") == "matched"
            and str(rigvm_link.get("rigvm_object_id", "") or "")
        )
        if rigvm_matched:
            kind, effect, access, symbol_kind = _rigvm_model(rigvm_link)

        pins = pins_by_node.get(node_id, [])
        exec_in = exec_out = data_in = data_out = connected_in = connected_out = literal_in = 0
        for pin in pins:
            direction = str(pin.get("direction", "") or "").lower()
            pin_type = pin.get("type", {})
            pin_type = pin_type if isinstance(pin_type, dict) else {}
            is_exec = str(pin_type.get("category", "") or "").lower() == "exec"
            linked = int(pin.get("linked_count", 0) or 0)
            if direction in {"input", "egpd_input", "0"}:
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
            elif direction in {"output", "egpd_output", "1"}:
                connected_out += int(linked > 0)
                if is_exec:
                    exec_out += 1
                else:
                    data_out += 1

        sem = node.get("semantic", {})
        sem = sem if isinstance(sem, dict) else {}
        target_kind, target = _target_for(node, symbol_kind)
        if rigvm_matched:
            target_kind = "rigvm_node"
            target = str(rigvm_link.get("rigvm_object_id", "") or "")

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
        if operation == "control_rig_node":
            row.update({
                "rigvm_bridge_status": str((rigvm_link or {}).get("status", "") or "missing"),
                "rigvm_confidence": str((rigvm_link or {}).get("confidence", "") or ""),
                "rigvm_object_id": str((rigvm_link or {}).get("rigvm_object_id", "") or ""),
                "rigvm_operation": str((rigvm_link or {}).get("rigvm_operation", "") or ""),
                "rigvm_class": str((rigvm_link or {}).get("rigvm_class", "") or ""),
                "rigvm_function": str((rigvm_link or {}).get("resolved_function_name", "") or ""),
                "rigvm_template": str((rigvm_link or {}).get("template_notation", "") or ""),
            })
        if operation == "macro_instance":
            macro_bridge = macro_bridges.get(node_id, {})
            row.update({
                "macro_bridge_status": str(macro_bridge.get("status", "") or "missing_graph_identity"),
                "macro_graph_id": str(macro_bridge.get("graph_id", "") or ""),
                "macro_source_blueprint": str(macro_bridge.get("source_blueprint", "") or ""),
                "macro_interface_status": str(macro_bridge.get("interface_status", "") or "unavailable"),
                "macro_interface_pin_count": int(macro_bridge.get("interface_pin_count", 0) or 0),
                "macro_interface_binding_count": int(macro_bridge.get("binding_count", 0) or 0),
            })
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
        if node["target_kind"] and node["target"]:
            relation = _endpoint_relation(node["operation"], node["access_kind"], node["target_kind"])
            if relation:
                add_edge(
                    blueprint_path=node["blueprint_path"], graph_id=node["graph_id"],
                    source_node_id=node["node_id"], relation=relation,
                    target_kind=node["target_kind"], target=node["target"],
                    evidence_kind="node_semantic",
                )

        macro_bridge = macro_bridges.get(node["node_id"])
        if macro_bridge and str(macro_bridge.get("status", "") or "") == "matched":
            graph_id = str(macro_bridge.get("graph_id", "") or "")
            if graph_id:
                add_edge(
                    blueprint_path=node["blueprint_path"], graph_id=node["graph_id"],
                    source_node_id=node["node_id"], relation="maps_to_macro_graph",
                    target_kind="blueprint_graph", target=graph_id,
                    evidence_kind="macro_graph_exact",
                )
            for binding in macro_bridge.get("bindings", []):
                target_pin_id = str(binding.get("target_pin_id", "") or "")
                if not target_pin_id:
                    continue
                add_edge(
                    blueprint_path=node["blueprint_path"], graph_id=node["graph_id"],
                    source_node_id=node["node_id"], relation=str(binding.get("relation", "") or ""),
                    target_kind="blueprint_pin", target=target_pin_id,
                    source_pin_id=str(binding.get("source_pin_id", "") or ""),
                    target_pin_id=target_pin_id,
                    source_pin_name=str(binding.get("source_pin_name", "") or ""),
                    target_pin_name=str(binding.get("target_pin_name", "") or ""),
                    pin_category=str(binding.get("pin_category", "") or ""),
                    evidence_kind="macro_interface_exact",
                )

        if node.get("rigvm_object_id"):
            exact = (
                ("has_rigvm_operation", "rigvm_operation", node.get("rigvm_operation", "")),
                ("uses_rigvm_class", "class", node.get("rigvm_class", "")),
                ("invokes_rigvm_function", "function", node.get("rigvm_function", "")),
            )
            for relation, target_kind, target in exact:
                add_edge(
                    blueprint_path=node["blueprint_path"], graph_id=node["graph_id"],
                    source_node_id=node["node_id"], relation=relation,
                    target_kind=target_kind, target=str(target or ""),
                    evidence_kind="rigvm_editor_link",
                )
            template = str(node.get("rigvm_template", "") or "")
            if template and template != "None":
                add_edge(
                    blueprint_path=node["blueprint_path"], graph_id=node["graph_id"],
                    source_node_id=node["node_id"], relation="uses_rigvm_template",
                    target_kind="rigvm_template", target=template,
                    evidence_kind="rigvm_editor_link",
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

    node_by_id = {str(row.get("node_id", "") or ""): row for row in semantic_nodes}
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

    raw_pins = list(rows(output / "blueprint_pins.jsonl"))
    raw_graphs = list(rows(output / "blueprint_graphs.jsonl"))
    macro_bridges = _derive_macro_bridges(raw_nodes, raw_pins, raw_graphs)

    expected_macro_edges = set()
    for raw in raw_nodes:
        if str(raw.get("operation", "") or "") != "macro_instance":
            continue
        node_id = str(raw.get("node_id", "") or "")
        bridge = macro_bridges.get(node_id, {})
        semantic = node_by_id[node_id]
        expected_fields = {
            "macro_bridge_status": str(bridge.get("status", "") or "missing_graph_identity"),
            "macro_graph_id": str(bridge.get("graph_id", "") or ""),
            "macro_source_blueprint": str(bridge.get("source_blueprint", "") or ""),
            "macro_interface_status": str(bridge.get("interface_status", "") or "unavailable"),
            "macro_interface_pin_count": int(bridge.get("interface_pin_count", 0) or 0),
            "macro_interface_binding_count": int(bridge.get("binding_count", 0) or 0),
        }
        for field, expected in expected_fields.items():
            if semantic.get(field) != expected:
                return f"Blueprint macro semantic field mismatch: {node_id} {field}"

        if str(bridge.get("status", "") or "") == "matched" and bridge.get("graph_id"):
            expected_macro_edges.add((
                node_id, "maps_to_macro_graph", "blueprint_graph",
                str(bridge.get("graph_id", "") or ""), "", "",
            ))
        for binding in bridge.get("bindings", []):
            expected_macro_edges.add((
                node_id, str(binding.get("relation", "") or ""), "blueprint_pin",
                str(binding.get("target_pin_id", "") or ""),
                str(binding.get("source_pin_id", "") or ""),
                str(binding.get("target_pin_id", "") or ""),
            ))

    actual_macro_edges = {
        (
            str(edge.get("source_node_id", "") or ""),
            str(edge.get("relation", "") or ""),
            str(edge.get("target_kind", "") or ""),
            str(edge.get("target", "") or ""),
            str(edge.get("source_pin_id", "") or ""),
            str(edge.get("target_pin_id", "") or ""),
        )
        for edge in edges
        if str(edge.get("relation", "") or "") in {
            "maps_to_macro_graph", "binds_macro_input", "binds_macro_output"
        }
    }
    if expected_macro_edges != actual_macro_edges:
        return "Blueprint macro semantic proof edges do not exactly match canonical graph/pin evidence"

    rigvm_links = _load_rigvm_links(output, rows)
    edge_keys = {
        (
            str(edge.get("source_node_id", "") or ""),
            str(edge.get("relation", "") or ""),
            str(edge.get("target_kind", "") or ""),
            str(edge.get("target", "") or ""),
        )
        for edge in edges
    }
    for raw in raw_nodes:
        if str(raw.get("operation", "") or "") != "control_rig_node":
            continue
        node_id = str(raw.get("node_id", "") or "")
        semantic = node_by_id[node_id]
        link = rigvm_links.get(node_id)
        matched = bool(
            link
            and str(link.get("status", "") or "") == "matched"
            and str(link.get("rigvm_object_id", "") or "")
        )
        if matched:
            rigvm_object_id = str(link.get("rigvm_object_id", "") or "")
            if semantic.get("semantic_kind") == "classified":
                return f"matched Control Rig node remained semantic fallback: {node_id}"
            if semantic.get("target_kind") != "rigvm_node" or semantic.get("target") != rigvm_object_id:
                return f"Control Rig semantic RigVM target mismatch: {node_id}"
            if (node_id, "maps_to_rigvm_node", "rigvm_node", rigvm_object_id) not in edge_keys:
                return f"Control Rig semantic RigVM edge missing: {node_id}"
        elif semantic.get("semantic_kind") != "classified":
            return f"unmatched Control Rig node was marked modeled: {node_id}"

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
               OR json LIKE ?
            LIMIT ?
            """,
            (pattern,) * 10 + (limit,),
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
