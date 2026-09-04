#!/usr/bin/env python3
"""Read-only coverage report for generic Blueprint semantic derivation."""
from __future__ import annotations

import collections
import json
from pathlib import Path

import uatool_core as core


def build_report(output: Path, rows, *, limit: int = 25) -> dict:
    output = Path(output).expanduser().resolve()
    semantic_path = output / "blueprint_semantic_nodes.jsonl"
    if not semantic_path.is_file():
        raise RuntimeError(f"Blueprint semantic nodes are missing: {semantic_path}")

    all_nodes = list(rows(semantic_path))
    fallback = [
        row for row in all_nodes
        if not bool(row.get("opaque", False))
        and str(row.get("semantic_kind", "") or "") == "classified"
    ]
    opaque = [row for row in all_nodes if bool(row.get("opaque", False))]
    modeled = len(all_nodes) - len(fallback) - len(opaque)

    def top(counter: collections.Counter, n: int = limit) -> list[tuple[str, int]]:
        return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[:n]

    fallback_operations = collections.Counter(str(row.get("operation", "") or "<empty>") for row in fallback)
    fallback_classes = collections.Counter(str(row.get("node_class", "") or "<empty>") for row in fallback)
    fallback_blueprints = collections.Counter(str(row.get("blueprint_path", "") or "<empty>") for row in fallback)
    fallback_graphs = collections.Counter(
        f"{row.get('blueprint_path','')} :: {row.get('graph_name','')}"
        for row in fallback
    )
    opaque_classes = collections.Counter(str(row.get("node_class", "") or "<empty>") for row in opaque)

    raw_nodes_path = output / "blueprint_nodes.jsonl"
    raw_nodes = list(rows(raw_nodes_path)) if raw_nodes_path.is_file() else []
    raw_macro_nodes = [
        row for row in raw_nodes
        if str(row.get("operation", "") or "") == "macro_instance"
    ]
    semantic_macro_nodes = [
        row for row in all_nodes
        if str(row.get("operation", "") or "") == "macro_instance"
    ]
    semantic_macro_ids = {
        str(row.get("node_id", "") or "")
        for row in semantic_macro_nodes
        if row.get("node_id")
    }

    graph_path = output / "blueprint_graphs.jsonl"
    graph_rows = list(rows(graph_path)) if graph_path.is_file() else []
    graph_path_counts = collections.Counter(
        str(row.get("graph_path", "") or "")
        for row in graph_rows
        if row.get("graph_path")
    )

    macro_status = collections.Counter()
    matched_macro_graphs = collections.Counter()
    external_macro_graphs = collections.Counter()
    macro_source_blueprints = collections.Counter()
    missing_macro_semantic_nodes = 0
    for row in raw_macro_nodes:
        node_id = str(row.get("node_id", "") or "")
        if node_id and node_id not in semantic_macro_ids:
            missing_macro_semantic_nodes += 1

        sem = row.get("semantic", {}) if isinstance(row.get("semantic"), dict) else {}
        macro_graph = str(sem.get("macro_graph", "") or "")
        source_blueprint = str(sem.get("source_blueprint", "") or "")
        if source_blueprint:
            macro_source_blueprints[source_blueprint] += 1

        if not macro_graph:
            macro_status["missing_graph_identity"] += 1
            continue

        match_count = int(graph_path_counts.get(macro_graph, 0) or 0)
        if match_count == 1:
            macro_status["matched"] += 1
            matched_macro_graphs[macro_graph] += 1
        elif match_count > 1:
            macro_status["ambiguous_captured_graph_path"] += 1
        else:
            macro_status["external_or_unscanned"] += 1
            external_macro_graphs[macro_graph] += 1

    duplicate_captured_macro_graph_paths = sum(
        1 for _path, count in graph_path_counts.items() if count > 1
    )

    graph_by_path = {
        str(row.get("graph_path", "") or ""): row
        for row in graph_rows
        if row.get("graph_path") and graph_path_counts.get(str(row.get("graph_path", "") or ""), 0) == 1
    }
    nodes_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    for row in raw_nodes:
        graph_id = str(row.get("graph_id", "") or "")
        if graph_id:
            nodes_by_graph[graph_id].append(row)

    pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for pin in core.iter_blueprint_pin_rows(output):
        node_id = str(pin.get("node_id", "") or "")
        if node_id:
            pins_by_node[node_id].append(pin)

    def pin_is_output(pin: dict) -> bool:
        return str(pin.get("direction", "") or "").lower() in {"output", "egpd_output", "1"}

    def type_key(pin_type: dict) -> str:
        pin_type = pin_type if isinstance(pin_type, dict) else {}
        signature = {
            "category": str(pin_type.get("category", "") or ""),
            "subcategory": str(pin_type.get("subcategory", "") or ""),
            "subcategory_object": str(pin_type.get("subcategory_object", "") or ""),
            "container_type": int(pin_type.get("container_type", 0) or 0),
            "is_reference": bool(pin_type.get("is_reference", False)),
            "is_const": bool(pin_type.get("is_const", False)),
        }
        return json.dumps(signature, sort_keys=True, separators=(",", ":"))

    def pin_type_key(pin: dict) -> str:
        return type_key(pin.get("type", {}) if isinstance(pin.get("type"), dict) else {})

    TYPE_FIELDS = (
        "category",
        "subcategory",
        "subcategory_object",
        "container_type",
        "is_reference",
        "is_const",
    )

    def normalized_type(pin_type: dict) -> dict:
        pin_type = pin_type if isinstance(pin_type, dict) else {}
        return {
            "category": str(pin_type.get("category", "") or ""),
            "subcategory": str(pin_type.get("subcategory", "") or ""),
            "subcategory_object": str(pin_type.get("subcategory_object", "") or ""),
            "container_type": int(pin_type.get("container_type", 0) or 0),
            "is_reference": bool(pin_type.get("is_reference", False)),
            "is_const": bool(pin_type.get("is_const", False)),
        }

    def type_diff_fields(left: dict, right: dict) -> tuple[str, ...]:
        a = normalized_type(left)
        b = normalized_type(right)
        return tuple(field for field in TYPE_FIELDS if a[field] != b[field])

    VALUE_TYPE_FIELDS = (
        "category",
        "subcategory",
        "subcategory_object",
        "container_type",
    )

    def value_type_key(pin_type: dict) -> tuple:
        normalized = normalized_type(pin_type)
        return tuple(normalized[field] for field in VALUE_TYPE_FIELDS)

    def tunnel_shape(node: dict) -> str:
        pins = pins_by_node.get(str(node.get("node_id", "") or ""), [])
        inputs = sum(int(not pin_is_output(pin)) for pin in pins)
        outputs = sum(int(pin_is_output(pin)) for pin in pins)
        if inputs and outputs:
            return "bidirectional"
        if outputs:
            return "output_only"
        if inputs:
            return "input_only"
        return "pinless"

    matched_graph_paths = {
        str((row.get("semantic", {}) if isinstance(row.get("semantic"), dict) else {}).get("macro_graph", "") or "")
        for row in raw_macro_nodes
        if graph_path_counts.get(
            str((row.get("semantic", {}) if isinstance(row.get("semantic"), dict) else {}).get("macro_graph", "") or ""),
            0,
        ) == 1
    }
    macro_interface_shapes = collections.Counter()
    macro_interface_graph_status = collections.Counter()
    macro_interface_graph_details: dict[str, dict] = {}
    for macro_graph in sorted(path for path in matched_graph_paths if path):
        graph = graph_by_path.get(macro_graph)
        if not graph:
            continue
        graph_id = str(graph.get("graph_id", "") or "")
        tunnels = [
            node for node in nodes_by_graph.get(graph_id, [])
            if str(node.get("operation", "") or "") == "tunnel"
        ]
        shapes = collections.Counter(tunnel_shape(node) for node in tunnels)
        shape_key = (
            f"output_only={int(shapes.get('output_only', 0))} "
            f"input_only={int(shapes.get('input_only', 0))} "
            f"bidirectional={int(shapes.get('bidirectional', 0))} "
            f"pinless={int(shapes.get('pinless', 0))}"
        )
        macro_interface_shapes[shape_key] += 1
        entries = [node for node in tunnels if tunnel_shape(node) == "output_only"]
        exits = [node for node in tunnels if tunnel_shape(node) == "input_only"]
        status = "exact_roles" if len(entries) == 1 and len(exits) == 1 else "unresolved_roles"
        macro_interface_graph_status[status] += 1
        macro_interface_graph_details[macro_graph] = {
            "status": status,
            "entry": entries[0] if len(entries) == 1 else None,
            "exit": exits[0] if len(exits) == 1 else None,
        }

    semantic_edge_path = output / "blueprint_semantic_edges.jsonl"
    semantic_edges = list(rows(semantic_edge_path)) if semantic_edge_path.is_file() else []
    macro_proof_relations = {"maps_to_macro_graph", "binds_macro_input", "binds_macro_output"}
    macro_semantic_proof_edges = collections.Counter(
        str(edge.get("relation", "") or "")
        for edge in semantic_edges
        if str(edge.get("relation", "") or "") in macro_proof_relations
    )

    pin_by_id = {
        str(pin.get("pin_id", "") or ""): pin
        for node_pins in pins_by_node.values()
        for pin in node_pins
        if pin.get("pin_id")
    }

    execution_blocks_path = output / "blueprint_execution_blocks.jsonl"
    execution_blocks = list(rows(execution_blocks_path)) if execution_blocks_path.is_file() else []
    block_by_node: dict[str, str] = {}
    block_graph_by_node: dict[str, str] = {}
    duplicate_block_nodes: set[str] = set()
    for block in execution_blocks:
        block_id = str(block.get("block_id", "") or "")
        graph_id = str(block.get("graph_id", "") or "")
        node_ids = block.get("node_ids", []) if isinstance(block.get("node_ids"), list) else []
        for node_id_value in node_ids:
            node_id = str(node_id_value or "")
            if not node_id:
                continue
            if node_id in block_by_node and block_by_node[node_id] != block_id:
                duplicate_block_nodes.add(node_id)
            block_by_node[node_id] = block_id
            block_graph_by_node[node_id] = graph_id

    raw_blueprint_edges = list(rows(output / "blueprint_edges.jsonl"))
    execution_block_edges_path = output / "blueprint_execution_block_edges.jsonl"
    execution_block_edges = (
        list(rows(execution_block_edges_path))
        if execution_block_edges_path.is_file()
        else []
    )
    blocks_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    block_by_id: dict[str, dict] = {}
    for block in execution_blocks:
        block_id = str(block.get("block_id", "") or "")
        graph_id = str(block.get("graph_id", "") or "")
        if block_id:
            block_by_id[block_id] = block
        if graph_id:
            blocks_by_graph[graph_id].append(block)
    block_outgoing: dict[str, list[str]] = collections.defaultdict(list)
    for block_edge in execution_block_edges:
        source_block_id = str(block_edge.get("source_block_id", "") or "")
        target_block_id = str(block_edge.get("target_block_id", "") or "")
        if source_block_id and target_block_id:
            block_outgoing[source_block_id].append(target_block_id)

    raw_exec_edges = [
        edge for edge in raw_blueprint_edges
        if str(edge.get("edge_kind", "") or "") == "execution"
    ]
    raw_data_edges = [
        edge for edge in raw_blueprint_edges
        if str(edge.get("edge_kind", "") or "") == "data"
    ]
    exec_outgoing_by_pin: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in raw_exec_edges:
        source_pin_id = str(edge.get("source_pin_id", "") or "")
        if source_pin_id:
            exec_outgoing_by_pin[source_pin_id].append(edge)

    data_incoming_by_pin: dict[str, list[dict]] = collections.defaultdict(list)
    data_outgoing_by_pin: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in raw_data_edges:
        source_pin_id = str(edge.get("source_pin_id", "") or "")
        target_pin_id = str(edge.get("target_pin_id", "") or "")
        if source_pin_id:
            data_outgoing_by_pin[source_pin_id].append(edge)
        if target_pin_id:
            data_incoming_by_pin[target_pin_id].append(edge)

    dependency_by_sink_pin: dict[str, list[dict]] = collections.defaultdict(list)
    dependency_path = output / "blueprint_data_dependencies.jsonl"
    if dependency_path.is_file():
        for dependency in rows(dependency_path):
            sink_pin_id = str(dependency.get("sink_pin_id", "") or "")
            if sink_pin_id:
                dependency_by_sink_pin[sink_pin_id].append(dependency)

    def pin_has_authored_value(pin: dict) -> bool:
        return bool(
            str(pin.get("default_object", "") or "")
            or str(pin.get("default_value", "") or "")
            or str(pin.get("default_text", "") or "")
        )

    proof_edges_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in semantic_edges:
        relation = str(edge.get("relation", "") or "")
        if relation in macro_proof_relations:
            proof_edges_by_node[str(edge.get("source_node_id", "") or "")].append(edge)

    macro_data_status = collections.Counter()
    macro_data_mismatches = collections.Counter()
    macro_data_input_binding_count = 0
    macro_data_input_connected_source_count = 0
    macro_data_input_authored_value_count = 0
    macro_data_input_no_value_count = 0
    macro_data_input_body_consumer_edge_count = 0
    macro_data_input_used_binding_count = 0
    macro_data_input_bridge_ready_count = 0
    macro_data_output_binding_count = 0
    macro_data_output_internal_source_edge_count = 0
    macro_data_output_dependency_count = 0
    macro_data_output_caller_consumer_edge_count = 0
    macro_data_output_used_binding_count = 0
    macro_data_output_bridge_ready_count = 0

    for macro_node in raw_macro_nodes:
        node_id = str(macro_node.get("node_id", "") or "")
        proof = proof_edges_by_node.get(node_id, [])
        for edge in proof:
            relation = str(edge.get("relation", "") or "")
            pin_category = str(edge.get("pin_category", "") or "").lower()
            if relation not in {"binds_macro_input", "binds_macro_output"} or pin_category == "exec":
                continue

            call_pin_id = str(edge.get("source_pin_id", "") or "")
            interface_pin_id = str(edge.get("target_pin_id", "") or "")
            call_pin = pin_by_id.get(call_pin_id)
            interface_pin = pin_by_id.get(interface_pin_id)
            if call_pin is None or interface_pin is None:
                macro_data_mismatches[
                    f"{node_id} :: {relation} :: missing_pin "
                    f"call={call_pin_id or '<missing>'} interface={interface_pin_id or '<missing>'}"
                ] += 1
                continue

            if relation == "binds_macro_input":
                macro_data_input_binding_count += 1
                incoming = data_incoming_by_pin.get(call_pin_id, [])
                body_consumers = data_outgoing_by_pin.get(interface_pin_id, [])
                has_value = False
                if incoming:
                    macro_data_input_connected_source_count += 1
                    macro_data_status["input_connected_source"] += 1
                    has_value = True
                elif pin_has_authored_value(call_pin):
                    macro_data_input_authored_value_count += 1
                    macro_data_status["input_authored_value"] += 1
                    has_value = True
                else:
                    macro_data_input_no_value_count += 1
                    macro_data_status["input_no_value_evidence"] += 1

                macro_data_input_body_consumer_edge_count += len(body_consumers)
                if body_consumers:
                    macro_data_input_used_binding_count += 1
                    macro_data_status["input_used_by_macro_body"] += 1
                else:
                    macro_data_status["input_unused_by_macro_body"] += 1

                if has_value and body_consumers:
                    macro_data_input_bridge_ready_count += 1
                    macro_data_status["input_bridge_ready"] += 1
                continue

            macro_data_output_binding_count += 1
            internal_sources = data_incoming_by_pin.get(interface_pin_id, [])
            dependencies = dependency_by_sink_pin.get(interface_pin_id, [])
            caller_consumers = data_outgoing_by_pin.get(call_pin_id, [])
            macro_data_output_internal_source_edge_count += len(internal_sources)
            macro_data_output_dependency_count += len(dependencies)
            macro_data_output_caller_consumer_edge_count += len(caller_consumers)

            if internal_sources:
                macro_data_status["output_has_internal_source"] += 1
            else:
                macro_data_status["output_missing_internal_source"] += 1
            if dependencies:
                macro_data_status["output_has_dependency_provenance"] += 1
            else:
                macro_data_status["output_missing_dependency_provenance"] += 1
            if caller_consumers:
                macro_data_output_used_binding_count += 1
                macro_data_status["output_has_caller_consumer"] += 1
            else:
                macro_data_status["output_unused_by_caller"] += 1

            if internal_sources and dependencies and caller_consumers:
                macro_data_output_bridge_ready_count += 1
                macro_data_status["output_bridge_ready"] += 1

    macro_exec_status = collections.Counter()
    macro_exec_mismatches = collections.Counter()
    macro_exec_exact_instance_count = 0
    macro_exec_data_only_instance_count = 0
    macro_exec_input_binding_count = 0
    macro_exec_exact_entry_bridge_count = 0
    macro_exec_output_binding_count = 0
    macro_exec_connected_output_count = 0
    macro_exec_terminal_output_count = 0
    macro_exec_exact_return_bridge_count = 0
    macro_exec_duplicate_block_node_count = len(duplicate_block_nodes)

    for macro_node in raw_macro_nodes:
        node_id = str(macro_node.get("node_id", "") or "")
        proof = proof_edges_by_node.get(node_id, [])
        graph_edges = [edge for edge in proof if str(edge.get("relation", "") or "") == "maps_to_macro_graph"]
        if len(graph_edges) != 1:
            continue
        target_graph_id = str(graph_edges[0].get("target", "") or "")

        input_exec = [
            edge for edge in proof
            if str(edge.get("relation", "") or "") == "binds_macro_input"
            and str(edge.get("pin_category", "") or "").lower() == "exec"
        ]
        output_exec = [
            edge for edge in proof
            if str(edge.get("relation", "") or "") == "binds_macro_output"
            and str(edge.get("pin_category", "") or "").lower() == "exec"
        ]
        if not input_exec and not output_exec:
            macro_exec_data_only_instance_count += 1
            macro_exec_status["data_only_instance"] += 1
            continue

        macro_exec_exact_instance_count += 1
        caller_block = block_by_node.get(node_id, "")
        if not caller_block:
            macro_exec_status["missing_caller_block"] += 1
            macro_exec_mismatches[f"{node_id} :: missing_caller_block"] += 1

        for edge in input_exec:
            macro_exec_input_binding_count += 1
            target_pin_id = str(edge.get("target_pin_id", "") or "")
            target_pin = pin_by_id.get(target_pin_id, {})
            entry_node_id = str(target_pin.get("node_id", "") or "")
            entry_block = block_by_node.get(entry_node_id, "")
            entry_graph_id = block_graph_by_node.get(entry_node_id, "")
            if (
                caller_block
                and entry_block
                and entry_graph_id == target_graph_id
                and node_id not in duplicate_block_nodes
                and entry_node_id not in duplicate_block_nodes
            ):
                macro_exec_exact_entry_bridge_count += 1
                macro_exec_status["exact_entry_block_bridge"] += 1
            else:
                macro_exec_status["unresolved_entry_block_bridge"] += 1
                macro_exec_mismatches[
                    f"{node_id} :: input:{edge.get('source_pin_name','')} :: "
                    f"entry_node={entry_node_id or '<missing>'} :: "
                    f"entry_graph={entry_graph_id or '<missing>'} :: target_graph={target_graph_id}"
                ] += 1

        for edge in output_exec:
            macro_exec_output_binding_count += 1
            target_pin_id = str(edge.get("target_pin_id", "") or "")
            target_pin = pin_by_id.get(target_pin_id, {})
            exit_node_id = str(target_pin.get("node_id", "") or "")
            exit_block = block_by_node.get(exit_node_id, "")
            exit_graph_id = block_graph_by_node.get(exit_node_id, "")
            source_pin_id = str(edge.get("source_pin_id", "") or "")
            outgoing = exec_outgoing_by_pin.get(source_pin_id, [])
            if not outgoing:
                macro_exec_terminal_output_count += 1
                if exit_block and exit_graph_id == target_graph_id and exit_node_id not in duplicate_block_nodes:
                    macro_exec_status["terminal_output_exact_exit_block"] += 1
                else:
                    macro_exec_status["terminal_output_unresolved_exit_block"] += 1
                    macro_exec_mismatches[
                        f"{node_id} :: output:{edge.get('source_pin_name','')} :: terminal :: "
                        f"exit_node={exit_node_id or '<missing>'} :: "
                        f"exit_graph={exit_graph_id or '<missing>'} :: target_graph={target_graph_id}"
                    ] += 1
                continue

            macro_exec_connected_output_count += 1
            for raw_edge in outgoing:
                continuation_node_id = str(raw_edge.get("target_node_id", "") or "")
                continuation_block = block_by_node.get(continuation_node_id, "")
                if (
                    exit_block
                    and exit_graph_id == target_graph_id
                    and continuation_block
                    and exit_node_id not in duplicate_block_nodes
                    and continuation_node_id not in duplicate_block_nodes
                ):
                    macro_exec_exact_return_bridge_count += 1
                    macro_exec_status["exact_return_block_bridge"] += 1
                else:
                    macro_exec_status["unresolved_return_block_bridge"] += 1
                    macro_exec_mismatches[
                        f"{node_id} :: output:{edge.get('source_pin_name','')} :: "
                        f"exit_node={exit_node_id or '<missing>'} :: "
                        f"continuation_node={continuation_node_id or '<missing>'}"
                    ] += 1

    macro_binding_status = collections.Counter()
    macro_binding_mismatches = collections.Counter()
    macro_binding_instance_count = 0
    macro_binding_resolved_instance_count = 0
    macro_binding_pin_count = 0
    macro_binding_exact_pin_count = 0
    for row in raw_macro_nodes:
        sem = row.get("semantic", {}) if isinstance(row.get("semantic"), dict) else {}
        macro_graph = str(sem.get("macro_graph", "") or "")
        detail = macro_interface_graph_details.get(macro_graph)
        if detail is None:
            continue
        macro_binding_instance_count += 1
        if detail.get("status") != "exact_roles":
            macro_binding_status["unresolved_interface_roles"] += 1
            continue
        macro_binding_resolved_instance_count += 1

        entry = detail.get("entry") or {}
        exit_node = detail.get("exit") or {}
        entry_pins = [
            pin for pin in pins_by_node.get(str(entry.get("node_id", "") or ""), [])
            if pin_is_output(pin)
        ]
        exit_pins = [
            pin for pin in pins_by_node.get(str(exit_node.get("node_id", "") or ""), [])
            if not pin_is_output(pin)
        ]
        interface_by_direction = {
            "input": entry_pins,
            "output": exit_pins,
        }

        for pin in pins_by_node.get(str(row.get("node_id", "") or ""), []):
            direction = "output" if pin_is_output(pin) else "input"
            candidates = interface_by_direction[direction]
            name = str(pin.get("name", "") or "")
            macro_binding_pin_count += 1
            same_name = [candidate for candidate in candidates if str(candidate.get("name", "") or "") == name]
            exact = [candidate for candidate in same_name if pin_type_key(candidate) == pin_type_key(pin)]
            if len(exact) == 1:
                macro_binding_exact_pin_count += 1
                macro_binding_status["exact_pin_binding"] += 1
            elif len(exact) > 1:
                macro_binding_status["ambiguous_exact_pin_binding"] += 1
                macro_binding_mismatches[f"{macro_graph} :: {direction} :: {name} :: ambiguous"] += 1
            elif same_name:
                macro_binding_status["name_match_type_mismatch"] += 1
                macro_binding_mismatches[f"{macro_graph} :: {direction} :: {name} :: type_mismatch"] += 1
            else:
                macro_binding_status["missing_interface_pin"] += 1
                macro_binding_mismatches[f"{macro_graph} :: {direction} :: {name} :: missing"] += 1

    interprocedural_edge_path = output / "blueprint_interprocedural_execution_edges.jsonl"
    interprocedural_terminal_path = output / "blueprint_interprocedural_execution_terminals.jsonl"
    interprocedural_data_path = output / "blueprint_interprocedural_data_routes.jsonl"
    function_interprocedural_edge_path = (
        output / "blueprint_interprocedural_function_execution_edges.jsonl"
    )
    function_interprocedural_terminal_path = (
        output / "blueprint_interprocedural_function_execution_terminals.jsonl"
    )
    function_interprocedural_data_path = (
        output / "blueprint_interprocedural_function_data_routes.jsonl"
    )
    delegate_binding_path = output / "blueprint_delegate_bindings.jsonl"
    interprocedural_edges = (
        list(rows(interprocedural_edge_path)) if interprocedural_edge_path.is_file() else []
    )
    interprocedural_terminals = (
        list(rows(interprocedural_terminal_path)) if interprocedural_terminal_path.is_file() else []
    )
    interprocedural_data_routes = (
        list(rows(interprocedural_data_path)) if interprocedural_data_path.is_file() else []
    )
    function_interprocedural_edges = (
        list(rows(function_interprocedural_edge_path))
        if function_interprocedural_edge_path.is_file()
        else []
    )
    function_interprocedural_terminals = (
        list(rows(function_interprocedural_terminal_path))
        if function_interprocedural_terminal_path.is_file()
        else []
    )
    function_interprocedural_data_routes = (
        list(rows(function_interprocedural_data_path))
        if function_interprocedural_data_path.is_file()
        else []
    )
    delegate_binding_rows = (
        list(rows(delegate_binding_path))
        if delegate_binding_path.is_file()
        else []
    )
    interprocedural_data_kinds = collections.Counter(
        str(row.get("route_kind", "") or "<empty>") for row in interprocedural_data_routes
    )
    interprocedural_data_value_kinds = collections.Counter(
        str(row.get("value_kind", "") or "<empty>") for row in interprocedural_data_routes
    )
    interprocedural_data_ready_count = sum(
        int(bool(row.get("bridge_ready", False))) for row in interprocedural_data_routes
    )
    interprocedural_expected_data_route_count = (
        macro_data_input_binding_count + macro_data_output_binding_count
    )
    interprocedural_data_stream_alignment = bool(
        len(interprocedural_data_routes) == interprocedural_expected_data_route_count
        and int(interprocedural_data_kinds.get("macro_data_input", 0))
            == macro_data_input_binding_count
        and int(interprocedural_data_kinds.get("macro_data_output", 0))
            == macro_data_output_binding_count
        and int(interprocedural_data_value_kinds.get("connected_source", 0))
            == macro_data_input_connected_source_count
        and int(interprocedural_data_value_kinds.get("authored_value", 0))
            == macro_data_input_authored_value_count
        and int(interprocedural_data_value_kinds.get("no_value_evidence", 0))
            == macro_data_input_no_value_count
        and sum(int(row.get("body_consumer_count", 0) or 0) for row in interprocedural_data_routes)
            == macro_data_input_body_consumer_edge_count
        and sum(int(row.get("internal_source_count", 0) or 0) for row in interprocedural_data_routes)
            == macro_data_output_internal_source_edge_count
        and sum(int(row.get("dependency_count", 0) or 0) for row in interprocedural_data_routes)
            == macro_data_output_dependency_count
        and sum(int(row.get("caller_consumer_count", 0) or 0) for row in interprocedural_data_routes)
            == macro_data_output_caller_consumer_edge_count
        and interprocedural_data_ready_count
            == macro_data_input_bridge_ready_count + macro_data_output_bridge_ready_count
    )
    interprocedural_edge_kinds = collections.Counter(
        str(row.get("edge_kind", "") or "<empty>") for row in interprocedural_edges
    )
    interprocedural_terminal_kinds = collections.Counter(
        str(row.get("terminal_kind", "") or "<empty>") for row in interprocedural_terminals
    )
    interprocedural_expected_edge_count = (
        macro_exec_exact_entry_bridge_count + macro_exec_exact_return_bridge_count
    )
    interprocedural_stream_alignment = bool(
        len(interprocedural_edges) == interprocedural_expected_edge_count
        and int(interprocedural_edge_kinds.get("macro_enter", 0))
            == macro_exec_exact_entry_bridge_count
        and int(interprocedural_edge_kinds.get("macro_return", 0))
            == macro_exec_exact_return_bridge_count
        and len(interprocedural_terminals) == macro_exec_terminal_output_count
    )

    function_rows_path = output / "blueprint_functions.jsonl"
    call_edges_path = output / "blueprint_call_edges.jsonl"
    call_bindings_path = output / "blueprint_call_bindings.jsonl"
    blueprint_rows_path = output / "blueprints.jsonl"
    function_rows = list(rows(function_rows_path)) if function_rows_path.is_file() else []
    call_edges = list(rows(call_edges_path)) if call_edges_path.is_file() else []
    call_bindings = list(rows(call_bindings_path)) if call_bindings_path.is_file() else []
    blueprint_rows = list(rows(blueprint_rows_path)) if blueprint_rows_path.is_file() else []

    function_by_id = {
        str(row.get("function_id", "") or ""): row
        for row in function_rows
        if row.get("function_id")
    }
    blueprint_by_path = {
        str(row.get("object_path", "") or ""): row
        for row in blueprint_rows
        if row.get("object_path")
    }
    bindings_by_call: dict[str, list[dict]] = collections.defaultdict(list)
    for binding in call_bindings:
        call_node_id = str(binding.get("call_node_id", "") or "")
        if call_node_id:
            bindings_by_call[call_node_id].append(binding)

    exec_outgoing_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in raw_exec_edges:
        source_node_id = str(edge.get("source_node_id", "") or "")
        if source_node_id:
            exec_outgoing_by_node[source_node_id].append(edge)

    # Scanner serializes UBlueprint::BlueprintType as EBlueprintType's ordinal.
    # UE 5.8 declares BPTYPE_Interface after Normal, Const and MacroLibrary.
    BPTYPE_INTERFACE = 3

    delegate_operations = {
        "delegate_bind",
        "delegate_assign",
        "delegate_unbind",
        "delegate_create",
        "delegate_call",
        "delegate_clear",
    }
    delegate_nodes = [
        node for node in raw_nodes
        if str(node.get("operation", "") or "") in delegate_operations
    ]
    delegate_node_by_id = {
        str(node.get("node_id", "") or ""): node
        for node in delegate_nodes
        if node.get("node_id")
    }
    raw_node_by_id = {
        str(node.get("node_id", "") or ""): node
        for node in raw_nodes
        if node.get("node_id")
    }
    delegate_operation_counts = collections.Counter(
        str(node.get("operation", "") or "<empty>")
        for node in delegate_nodes
    )
    delegate_dispatcher_identity_status = collections.Counter()
    delegate_dispatcher_operations = collections.Counter()
    delegate_dispatcher_identities: dict[tuple[str, str], collections.Counter] = collections.defaultdict(collections.Counter)
    delegate_mismatches = collections.Counter()
    delegate_dispatcher_node_count = 0
    delegate_exact_dispatcher_identity_count = 0
    delegate_member_guid_count = 0
    delegate_self_context_count = 0
    delegate_external_context_count = 0

    def delegate_semantic(node: dict) -> dict:
        value = node.get("semantic", {})
        return value if isinstance(value, dict) else {}

    for node in delegate_nodes:
        operation = str(node.get("operation", "") or "")
        if operation == "delegate_create":
            continue
        delegate_dispatcher_node_count += 1
        sem = delegate_semantic(node)
        delegate_name = str(sem.get("delegate_name", "") or "")
        delegate_owner = str(sem.get("delegate_owner", "") or "")
        if str(sem.get("delegate_member_guid", "") or ""):
            delegate_member_guid_count += 1
        if sem.get("delegate_self_context") is True:
            delegate_self_context_count += 1
        elif sem.get("delegate_self_context") is False:
            delegate_external_context_count += 1
        if delegate_name and delegate_owner:
            status = "exact_owner_and_name"
            delegate_exact_dispatcher_identity_count += 1
            identity = (delegate_owner, delegate_name.casefold())
            delegate_dispatcher_identities[identity][operation] += 1
            delegate_dispatcher_operations[
                f"{operation} :: {delegate_owner}::{delegate_name}"
            ] += 1
        elif delegate_name:
            status = "name_only"
        elif delegate_owner:
            status = "owner_only"
        else:
            status = "missing_identity"
        delegate_dispatcher_identity_status[status] += 1
        if status != "exact_owner_and_name":
            delegate_mismatches[
                f"{node.get('node_id','')} :: {operation} :: dispatcher_{status}"
            ] += 1

    def guid_key(value: str) -> str:
        value = str(value or "").strip().lower()
        for token in ("{", "}", "(", ")", "-", " "):
            value = value.replace(token, "")
        if len(value) == 32 and all(ch in "0123456789abcdef" for ch in value):
            return value
        return ""

    def node_guid_key(node: dict) -> str:
        node_id = str(node.get("node_id", "") or "")
        marker = "::node::"
        return guid_key(node_id.rsplit(marker, 1)[1] if marker in node_id else "")

    guid_nodes_by_blueprint: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    event_name_nodes_by_blueprint: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for node in raw_nodes:
        bp = str(node.get("blueprint_path", "") or "")
        guid = node_guid_key(node)
        if bp and guid:
            guid_nodes_by_blueprint[(bp, guid)].append(node)
        if str(node.get("operation", "") or "") in {"custom_event", "event"}:
            name = str(node.get("symbol", "") or "")
            if bp and name:
                event_name_nodes_by_blueprint[(bp, name.casefold())].append(node)

    function_name_rows_by_blueprint: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for function in function_rows:
        bp = str(function.get("blueprint_path", "") or "")
        name = str(function.get("name", "") or "")
        if bp and name:
            function_name_rows_by_blueprint[(bp, name.casefold())].append(function)

    function_rows_by_resolved: dict[str, list[dict]] = collections.defaultdict(list)
    for function in function_rows:
        resolved = str(function.get("resolved_function", "") or "")
        if resolved:
            function_rows_by_resolved[resolved].append(function)

    delegate_create_status = collections.Counter()
    delegate_create_function_local_resolution = collections.Counter()
    delegate_create_target_operations = collections.Counter()
    delegate_create_selected_name_count = 0
    delegate_create_selected_guid_count = 0
    delegate_create_exact_endpoint_count = 0
    delegate_create_examples: list[dict] = []
    delegate_create_status_by_node: dict[str, str] = {}

    create_nodes = [
        node for node in delegate_nodes
        if str(node.get("operation", "") or "") == "delegate_create"
    ]
    for node in create_nodes:
        node_id = str(node.get("node_id", "") or "")
        bp = str(node.get("blueprint_path", "") or "")
        sem = delegate_semantic(node)
        selected_name = str(sem.get("selected_function", "") or "")
        selected_guid_raw = str(sem.get("selected_function_guid", "") or "")
        selected_guid = guid_key(selected_guid_raw)
        selected_function_path = str(sem.get("selected_function_path", "") or "")
        selected_scope_class = str(sem.get("selected_function_scope_class", "") or "")
        if selected_name:
            delegate_create_selected_name_count += 1
        if selected_guid_raw:
            delegate_create_selected_guid_count += 1

        guid_candidates = (
            guid_nodes_by_blueprint.get((bp, selected_guid), [])
            if selected_guid else []
        )
        status = ""
        target_operation = ""
        target_node_id = ""
        if len(guid_candidates) == 1:
            candidate = guid_candidates[0]
            target_operation = str(candidate.get("operation", "") or "<empty>")
            target_node_id = str(candidate.get("node_id", "") or "")
            candidate_name = str(candidate.get("symbol", "") or "")
            if (
                selected_name
                and candidate_name
                and selected_name.casefold() == candidate_name.casefold()
            ):
                status = (
                    "exact_guid_name_match"
                    if selected_name == candidate_name
                    else "exact_guid_name_case_variant"
                )
                delegate_create_exact_endpoint_count += 1
            elif selected_name and candidate_name:
                status = "exact_guid_name_mismatch"
                delegate_mismatches[
                    f"{node_id} :: create :: selected_name={selected_name} "
                    f"guid_target_name={candidate_name}"
                ] += 1
            else:
                status = "exact_guid_only"
                delegate_create_exact_endpoint_count += 1
        elif len(guid_candidates) > 1:
            status = "ambiguous_guid"
            delegate_mismatches[f"{node_id} :: create :: ambiguous_selected_guid"] += 1
        else:
            resolved_function_candidates = (
                function_rows_by_resolved.get(selected_function_path, [])
                if selected_function_path else []
            )
            if selected_function_path:
                # Structural schema 13 records this path from the exact
                # UFunction selected by UE. Multiple derived function rows may
                # map back to the same generated/skeleton UFunction; that is a
                # local-row multiplicity diagnostic, not endpoint ambiguity.
                status = "exact_function_path"
                target_operation = "function"
                candidate_ids = sorted(
                    {
                        str(candidate.get("function_id", "") or "")
                        for candidate in resolved_function_candidates
                        if candidate.get("function_id")
                    }
                )
                target_node_id = (
                    candidate_ids[0] if len(candidate_ids) == 1 else selected_function_path
                )
                local_status = (
                    "unique_captured_function"
                    if len(candidate_ids) == 1
                    else "multiple_captured_function_rows"
                    if candidate_ids
                    else "no_captured_function_row"
                )
                delegate_create_function_local_resolution[local_status] += 1
                delegate_create_exact_endpoint_count += 1
            else:
                event_candidates = (
                    event_name_nodes_by_blueprint.get((bp, selected_name.casefold()), [])
                    if selected_name else []
                )
                function_candidates = (
                    function_name_rows_by_blueprint.get((bp, selected_name.casefold()), [])
                    if selected_name else []
                )
                name_candidate_count = len(event_candidates) + len(function_candidates)
                if name_candidate_count == 1:
                    status = "unique_name_candidate"
                    if event_candidates:
                        target_operation = str(event_candidates[0].get("operation", "") or "<empty>")
                        target_node_id = str(event_candidates[0].get("node_id", "") or "")
                    else:
                        target_operation = "function"
                        target_node_id = str(function_candidates[0].get("function_id", "") or "")
                elif name_candidate_count > 1:
                    status = "ambiguous_name_candidate"
                elif selected_guid_raw and not selected_guid:
                    status = "unparsed_guid_unresolved"
                elif selected_name or selected_guid_raw:
                    status = "unresolved"
                else:
                    status = "missing_selected_endpoint"
        delegate_create_status[status] += 1
        delegate_create_status_by_node[node_id] = status
        if target_operation:
            delegate_create_target_operations[target_operation] += 1
        if len(delegate_create_examples) < limit:
            delegate_create_examples.append({
                "node_id": node_id,
                "blueprint_path": bp,
                "selected_function": selected_name,
                "selected_function_guid": selected_guid_raw,
                "selected_function_path": selected_function_path,
                "selected_scope_class": selected_scope_class,
                "status": status,
                "target_operation": target_operation,
                "target_node_id": target_node_id,
            })

    delegate_data_source_status = collections.Counter()
    delegate_data_source_operations = collections.Counter()
    delegate_bind_assign_node_count = 0
    delegate_bind_assign_delegate_input_edge_count = 0
    delegate_create_to_bind_assign_edge_count = 0
    delegate_exact_bound_endpoint_chain_count = 0
    delegate_input_edges_by_target: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in raw_data_edges:
        target_pin_id = str(edge.get("target_pin_id", "") or "")
        target_pin = pin_by_id.get(target_pin_id, {})
        pin_type = (
            target_pin.get("type", {})
            if isinstance(target_pin.get("type"), dict)
            else {}
        )
        category = str(pin_type.get("category", "") or "").lower()
        if category not in {"delegate", "mcdelegate", "multicastdelegate"}:
            continue
        target_node_id = str(edge.get("target_node_id", "") or "")
        if target_node_id:
            delegate_input_edges_by_target[target_node_id].append(edge)

    for node in delegate_nodes:
        operation = str(node.get("operation", "") or "")
        if operation not in {"delegate_bind", "delegate_assign"}:
            continue
        delegate_bind_assign_node_count += 1
        node_id = str(node.get("node_id", "") or "")
        incoming = delegate_input_edges_by_target.get(node_id, [])
        delegate_bind_assign_delegate_input_edge_count += len(incoming)
        create_sources = 0
        for edge in incoming:
            source_node_id = str(edge.get("source_node_id", "") or "")
            source_node = raw_node_by_id.get(source_node_id, {})
            source_operation = str(source_node.get("operation", "") or "<missing>")
            delegate_data_source_operations[source_operation] += 1
            if source_operation == "delegate_create":
                create_sources += 1
                delegate_create_to_bind_assign_edge_count += 1
                if delegate_create_status_by_node.get(source_node_id, "").startswith("exact_"):
                    delegate_exact_bound_endpoint_chain_count += 1
        if not incoming:
            delegate_data_source_status["no_delegate_input_edge"] += 1
        elif create_sources == len(incoming) == 1:
            delegate_data_source_status["single_create_delegate_source"] += 1
        elif create_sources:
            delegate_data_source_status["mixed_or_multiple_with_create"] += 1
        else:
            delegate_data_source_status["non_create_delegate_source"] += 1

    delegate_binding_operation_counts = collections.Counter(
        str(row.get("bind_operation", "") or "<empty>")
        for row in delegate_binding_rows
    )
    delegate_binding_basis_counts = collections.Counter(
        str(row.get("resolution_basis", "") or "<empty>")
        for row in delegate_binding_rows
    )
    delegate_binding_endpoint_kinds = collections.Counter(
        str(row.get("endpoint_kind", "") or "<empty>")
        for row in delegate_binding_rows
    )
    delegate_binding_create_route_count = int(
        delegate_binding_basis_counts.get("selected_guid", 0)
        + delegate_binding_basis_counts.get("selected_function_path", 0)
    )
    delegate_binding_direct_route_count = int(
        delegate_binding_basis_counts.get("direct_event_node", 0)
    )
    delegate_binding_expected_direct_route_count = max(
        0,
        delegate_bind_assign_delegate_input_edge_count
        - delegate_create_to_bind_assign_edge_count,
    )
    delegate_binding_alignment = bool(
        len(delegate_binding_rows) == delegate_bind_assign_delegate_input_edge_count
        and delegate_binding_create_route_count == delegate_create_to_bind_assign_edge_count
        and delegate_binding_create_route_count == delegate_exact_bound_endpoint_chain_count
        and delegate_binding_direct_route_count == delegate_binding_expected_direct_route_count
        and int(delegate_binding_operation_counts.get("delegate_bind", 0))
            + int(delegate_binding_operation_counts.get("delegate_assign", 0))
            == len(delegate_binding_rows)
    )

    event_rows_path = output / "blueprint_events.jsonl"
    event_rows = list(rows(event_rows_path)) if event_rows_path.is_file() else []
    component_bound_events = [
        event for event in event_rows
        if str(event.get("event_kind", "") or "") == "component_bound"
    ]
    delegate_component_event_status = collections.Counter()
    delegate_component_event_exact_identity_count = 0
    delegate_component_event_join_count = 0
    for event in component_bound_events:
        delegate_name = str(event.get("delegate_name", "") or "")
        delegate_owner = str(event.get("delegate_owner", "") or "")
        if delegate_name and delegate_owner:
            delegate_component_event_exact_identity_count += 1
            identity = (delegate_owner, delegate_name.casefold())
            if identity in delegate_dispatcher_identities:
                delegate_component_event_status["exact_dispatcher_join"] += 1
                delegate_component_event_join_count += 1
            else:
                delegate_component_event_status["exact_identity_no_dispatcher_node"] += 1
        elif delegate_name:
            delegate_component_event_status["name_only"] += 1
        elif delegate_owner:
            delegate_component_event_status["owner_only"] += 1
        else:
            delegate_component_event_status["missing_identity"] += 1

    delegate_dispatcher_shapes = collections.Counter()
    delegate_call_identity_status = collections.Counter()
    for identity, operations in delegate_dispatcher_identities.items():
        shape = " ".join(
            f"{operation}={int(operations.get(operation, 0))}"
            for operation in (
                "delegate_bind",
                "delegate_assign",
                "delegate_unbind",
                "delegate_call",
                "delegate_clear",
            )
        )
        delegate_dispatcher_shapes[shape] += 1
        call_count = int(operations.get("delegate_call", 0) or 0)
        if call_count:
            has_binding = bool(
                operations.get("delegate_bind", 0)
                or operations.get("delegate_assign", 0)
            )
            delegate_call_identity_status[
                "call_identity_has_binding_site"
                if has_binding
                else "call_identity_without_binding_site"
            ] += call_count

    function_call_resolution = collections.Counter()
    function_internal_kinds = collections.Counter()
    function_call_mismatches = collections.Counter()
    function_call_internal_count = 0
    function_call_internal_target_count = 0
    function_call_interface_count = 0
    function_call_pure_internal_count = 0
    function_call_latent_internal_count = 0
    function_call_direct_impure_count = 0
    function_call_purity_override_count = 0
    function_call_suspicious_purity_count = 0
    function_call_unknown_blueprint_type_count = 0
    function_direct_exact_caller_block_count = 0
    function_direct_exact_entry_block_count = 0
    function_direct_result_node_count = 0
    function_direct_exact_result_block_count = 0
    function_direct_explicit_result_call_count = 0
    function_direct_void_call_count = 0
    function_direct_reachable_terminal_block_count = 0
    function_direct_calls_with_terminal_frontier = 0
    function_direct_reachable_result_node_count = 0
    function_direct_unreachable_result_node_count = 0
    function_direct_unreachable_callsite_count = 0
    function_direct_no_return_frontier_count = 0
    function_direct_connected_continuation_count = 0
    function_direct_terminal_call_count = 0
    function_direct_exact_continuation_block_count = 0
    function_direct_bridge_ready_count = 0
    function_direct_bridge_ready_connected_call_count = 0
    function_direct_bridge_ready_terminal_call_count = 0
    function_direct_expected_enter_edge_count = 0
    function_direct_expected_return_edge_count = 0
    function_direct_expected_terminal_record_count = 0
    function_direct_bridge_ready_return_frontier_block_count = 0
    function_direct_binding_count = 0

    for call in call_edges:
        resolution = str(call.get("resolution", "") or "<empty>")
        function_call_resolution[resolution] += 1
        if resolution != "internal":
            continue

        function_call_internal_count += 1
        call_node_id = str(call.get("call_node_id", "") or "")
        target_function_id = str(call.get("target_function_id", "") or "")
        target = function_by_id.get(target_function_id)
        if target is None:
            function_call_mismatches[f"{call_node_id} :: missing_target_function:{target_function_id}"] += 1
            continue
        function_call_internal_target_count += 1

        target_bp_path = str(call.get("target_blueprint_path", "") or target.get("blueprint_path", "") or "")
        target_bp = blueprint_by_path.get(target_bp_path)
        target_bp_type = None
        if target_bp is not None:
            try:
                target_bp_type = int(target_bp.get("blueprint_type", -1))
            except (TypeError, ValueError):
                target_bp_type = None
        if target_bp_type is None:
            function_call_unknown_blueprint_type_count += 1

        interface_call = bool(call.get("interface_call", False))
        interface_declaration = target_bp_type == BPTYPE_INTERFACE
        call_pure = bool(call.get("pure", False))
        target_pure = bool(target.get("blueprint_pure", False))
        latent = bool(call.get("latent", False))

        if target_pure and not call_pure:
            # UK2Node_CallFunction supports a node-level purity override. The
            # call-site node's actual compiler purity governs whether the call
            # participates in exec flow; retain the target's default-pure fact
            # as provenance rather than treating the disagreement as corruption.
            function_call_purity_override_count += 1
            function_internal_kinds["pure_target_impure_call_node"] += 1
        elif call_pure and not target_pure:
            # A pure call node targeting a function that is not BlueprintPure is
            # not the documented toggle direction and remains suspicious.
            function_call_suspicious_purity_count += 1
            function_call_mismatches[
                f"{call_node_id} :: pure_call_node_targets_nonpure_function"
            ] += 1

        if interface_call or interface_declaration:
            function_call_interface_count += 1
            function_internal_kinds["interface_dispatch_or_declaration"] += 1
            continue
        if latent:
            function_call_latent_internal_count += 1
            function_internal_kinds["latent_internal"] += 1
            continue
        if call_pure:
            function_call_pure_internal_count += 1
            function_internal_kinds["pure_internal"] += 1
            continue

        function_call_direct_impure_count += 1
        function_internal_kinds["direct_impure_internal"] += 1
        function_direct_binding_count += len(bindings_by_call.get(call_node_id, []))

        caller_block = block_by_node.get(call_node_id, "")
        caller_graph_id = str(call.get("graph_id", "") or "")
        caller_ok = bool(
            caller_block
            and block_graph_by_node.get(call_node_id, "") == caller_graph_id
            and call_node_id not in duplicate_block_nodes
        )
        if caller_ok:
            function_direct_exact_caller_block_count += 1
        else:
            # An impure call node can exist as disconnected/dead authored graph
            # content. Absence from the executable block program means it is not
            # an execution bridge candidate, not that capture is corrupt.
            function_direct_unreachable_callsite_count += 1
            function_internal_kinds["direct_impure_unreachable_callsite"] += 1

        entry_node_id = str(target.get("entry_node_id", "") or "")
        entry_block = block_by_node.get(entry_node_id, "")
        entry_ok = bool(
            entry_node_id
            and entry_block
            and block_graph_by_node.get(entry_node_id, "") == target_function_id
            and entry_node_id not in duplicate_block_nodes
        )
        if entry_ok:
            function_direct_exact_entry_block_count += 1
        else:
            function_call_mismatches[
                f"{call_node_id} :: missing_or_ambiguous_entry_block:{entry_node_id or '<missing>'}"
            ] += 1

        result_node_ids = [
            str(value or "")
            for value in (
                target.get("result_node_ids", [])
                if isinstance(target.get("result_node_ids"), list)
                else []
            )
            if value
        ]
        function_direct_result_node_count += len(result_node_ids)
        if result_node_ids:
            function_direct_explicit_result_call_count += 1
        else:
            function_direct_void_call_count += 1

        entry_block_id = str(entry_block or "")
        reachable: set[str] = set()
        pending = [entry_block_id] if entry_block_id else []
        while pending:
            block_id = pending.pop()
            if not block_id or block_id in reachable:
                continue
            block = block_by_id.get(block_id)
            if block is None or str(block.get("graph_id", "") or "") != target_function_id:
                continue
            reachable.add(block_id)
            for target_block_id in block_outgoing.get(block_id, []):
                if target_block_id not in reachable:
                    pending.append(target_block_id)

        terminal_blocks = sorted(
            block_id for block_id in reachable
            if not [
                target_block_id
                for target_block_id in block_outgoing.get(block_id, [])
                if str(block_by_id.get(target_block_id, {}).get("graph_id", "") or "")
                    == target_function_id
            ]
        )
        function_direct_reachable_terminal_block_count += len(terminal_blocks)
        return_frontier_ok = bool(entry_ok and terminal_blocks)
        if return_frontier_ok:
            function_direct_calls_with_terminal_frontier += 1
        else:
            function_direct_no_return_frontier_count += 1
            function_internal_kinds["direct_impure_no_return_frontier"] += 1

        result_ok_count = 0
        for result_node_id in result_node_ids:
            result_block = block_by_node.get(result_node_id, "")
            if (
                result_block
                and result_block in reachable
                and block_graph_by_node.get(result_node_id, "") == target_function_id
                and result_node_id not in duplicate_block_nodes
            ):
                result_ok_count += 1
                function_direct_reachable_result_node_count += 1
            else:
                function_direct_unreachable_result_node_count += 1
                function_internal_kinds["declared_result_not_on_reachable_exec_path"] += 1
        function_direct_exact_result_block_count += result_ok_count

        outgoing = exec_outgoing_by_node.get(call_node_id, [])
        if not outgoing:
            function_direct_terminal_call_count += 1
        continuation_ok_count = 0
        for edge in outgoing:
            continuation_node_id = str(edge.get("target_node_id", "") or "")
            function_direct_connected_continuation_count += 1
            continuation_block = block_by_node.get(continuation_node_id, "")
            if (
                continuation_block
                and block_graph_by_node.get(continuation_node_id, "") == caller_graph_id
                and continuation_node_id not in duplicate_block_nodes
            ):
                continuation_ok_count += 1
            else:
                function_call_mismatches[
                    f"{call_node_id} :: missing_or_ambiguous_continuation_block:{continuation_node_id or '<missing>'}"
                ] += 1
        function_direct_exact_continuation_block_count += continuation_ok_count

        continuation_shape_ok = (not outgoing) or continuation_ok_count == len(outgoing)
        if caller_ok and entry_ok and return_frontier_ok and continuation_shape_ok:
            function_direct_bridge_ready_count += 1
            function_direct_expected_enter_edge_count += 1
            function_internal_kinds["direct_impure_bridge_ready"] += 1
            if outgoing:
                function_direct_bridge_ready_connected_call_count += 1
                function_direct_expected_return_edge_count += len(terminal_blocks) * len(outgoing)
            else:
                function_direct_bridge_ready_terminal_call_count += 1
                function_direct_expected_terminal_record_count += 1
                function_direct_bridge_ready_return_frontier_block_count += len(terminal_blocks)
        else:
            function_internal_kinds["direct_impure_not_bridge_ready"] += 1

    function_call_by_node = {
        str(row.get("call_node_id", "") or ""): row
        for row in call_edges
        if row.get("call_node_id")
    }

    function_data_target_kinds = collections.Counter()
    function_data_directions = collections.Counter()
    function_data_match_kinds = collections.Counter()
    function_data_status = collections.Counter()
    function_data_mismatches = collections.Counter()
    function_data_binding_count = len(call_bindings)
    function_data_binding_schema_versions = collections.Counter(
        int(binding.get("schema_version", 0) or 0)
        for binding in call_bindings
    )
    function_data_binding_schema_current = bool(
        call_bindings
        and function_data_binding_schema_versions
            == collections.Counter({core.BLUEPRINT_CALL_BINDING_SCHEMA_VERSION: len(call_bindings)})
    )
    function_data_parameter_identity_count = 0
    function_data_member_identity_exact_count = 0
    function_data_split_parent_projection_count = 0
    function_data_value_type_verified_count = 0
    function_data_type_verified_count = 0
    function_data_qualifier_difference_count = 0
    function_data_exact_call_signature_equal_count = 0
    function_data_exact_signature_pin_equal_count = 0
    function_data_exact_call_pin_equal_count = 0
    function_data_type_diff_fields = collections.Counter()
    function_data_type_surface_shapes = collections.Counter()
    function_data_split_member_resolved_count = 0
    function_data_split_member_unresolved_count = 0
    function_data_split_parent_pin_count = 0
    function_data_split_exact_name_candidate_count = 0
    function_data_split_suffix_candidate_count = 0
    function_data_split_prefixed_candidate_count = 0
    function_data_split_candidate_shapes = collections.Counter()
    function_data_split_candidate_examples: list[dict] = []

    function_data_argument_count = 0
    function_data_argument_connected_value_count = 0
    function_data_argument_authored_value_count = 0
    function_data_argument_no_value_count = 0
    function_data_argument_body_consumer_count = 0
    function_data_argument_unused_count = 0
    function_data_argument_binding_verified_count = 0
    function_data_argument_route_ready_count = 0

    function_data_return_count = 0
    function_data_return_dependency_count = 0
    function_data_return_authored_value_pin_count = 0
    function_data_return_missing_provenance_binding_count = 0
    function_data_return_caller_consumer_count = 0
    function_data_return_unused_count = 0
    function_data_return_binding_verified_count = 0
    function_data_return_route_ready_count = 0
    function_data_expected_route_count = 0
    function_data_expected_argument_route_count = 0
    function_data_expected_return_route_count = 0
    function_data_expected_split_projection_count = 0

    def function_target_kind(call: dict, target: dict | None) -> str:
        if target is None:
            return "missing_target"
        target_bp_path = str(
            call.get("target_blueprint_path", "")
            or target.get("blueprint_path", "")
            or ""
        )
        target_bp = blueprint_by_path.get(target_bp_path)
        target_bp_type = None
        if target_bp is not None:
            try:
                target_bp_type = int(target_bp.get("blueprint_type", -1))
            except (TypeError, ValueError):
                target_bp_type = None
        if bool(call.get("interface_call", False)) or target_bp_type == BPTYPE_INTERFACE:
            return "interface_dispatch_or_declaration"
        if bool(call.get("latent", False)):
            return "latent_internal"
        if bool(call.get("pure", False)):
            return "pure_internal"
        return (
            "direct_impure_reachable"
            if str(call.get("call_node_id", "") or "") in block_by_node
            else "direct_impure_unreachable"
        )

    def parameter_candidate_pins(target: dict, direction: str, call_pin_name: str) -> list[dict]:
        if direction == "argument":
            node_ids = [str(target.get("entry_node_id", "") or "")]
            want_output = True
        else:
            node_ids = [
                str(value or "")
                for value in (
                    target.get("result_node_ids", [])
                    if isinstance(target.get("result_node_ids"), list)
                    else []
                )
                if value
            ]
            want_output = False
        result: list[dict] = []
        for node_id in node_ids:
            for pin in pins_by_node.get(node_id, []):
                if pin_is_output(pin) != want_output:
                    continue
                pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
                if str(pin_type.get("category", "") or "").lower() == "exec":
                    continue
                if str(pin.get("name", "") or "") == call_pin_name:
                    result.append(pin)
        return result

    for binding in call_bindings:
        call_node_id = str(binding.get("call_node_id", "") or "")
        call = function_call_by_node.get(call_node_id)
        if call is None:
            function_data_mismatches[f"{call_node_id} :: missing_call_edge"] += 1
            continue
        target_function_id = str(binding.get("target_function_id", "") or "")
        target = function_by_id.get(target_function_id)
        if target is None:
            function_data_mismatches[
                f"{call_node_id} :: missing_target_function:{target_function_id}"
            ] += 1
            continue

        target_kind = function_target_kind(call, target)
        function_data_target_kinds[target_kind] += 1

        direction = str(binding.get("direction", "") or "")
        match_kind = str(binding.get("match_kind", "") or "")
        function_data_directions[direction or "<empty>"] += 1
        function_data_match_kinds[match_kind or "<empty>"] += 1
        if direction not in {"argument", "return"}:
            function_data_mismatches[
                f"{call_node_id} :: unexpected_direction:{direction or '<empty>'}"
            ] += 1
            continue

        call_pin_id = str(binding.get("call_pin_id", "") or "")
        call_pin_name = str(binding.get("call_pin_name", "") or "")
        call_pin = pin_by_id.get(call_pin_id)
        if call_pin is None:
            function_data_mismatches[
                f"{call_node_id} :: {direction}:{call_pin_name} :: missing_call_pin:{call_pin_id}"
            ] += 1
            continue

        parameter_pin_ids = [
            str(value or "")
            for value in (
                binding.get("parameter_pin_ids", [])
                if isinstance(binding.get("parameter_pin_ids"), list)
                else []
            )
            if value
        ]
        exact_parameter_pins = [
            pin_by_id[pin_id]
            for pin_id in parameter_pin_ids
            if pin_id in pin_by_id
        ]

        identity_ok = False
        type_ok = False
        if match_kind == "exact":
            identity_ok = bool(parameter_pin_ids) and len(exact_parameter_pins) == len(parameter_pin_ids)
            expected_type = binding.get("parameter_type", {})
            call_type = binding.get("call_pin_type", {})
            call_signature_equal = type_key(call_type) == type_key(expected_type)
            signature_pin_equal = bool(
                identity_ok
                and all(pin_type_key(pin) == type_key(expected_type) for pin in exact_parameter_pins)
            )
            call_pin_equal = bool(
                identity_ok
                and all(pin_type_key(pin) == type_key(call_type) for pin in exact_parameter_pins)
            )
            if call_signature_equal:
                function_data_exact_call_signature_equal_count += 1
            if signature_pin_equal:
                function_data_exact_signature_pin_equal_count += 1
            if call_pin_equal:
                function_data_exact_call_pin_equal_count += 1

            shape = (
                f"call_signature={'same' if call_signature_equal else 'diff'} "
                f"signature_pin={'same' if signature_pin_equal else 'diff'} "
                f"call_pin={'same' if call_pin_equal else 'diff'}"
            )
            function_data_type_surface_shapes[shape] += 1

            if not call_signature_equal:
                for field in type_diff_fields(call_type, expected_type):
                    function_data_type_diff_fields[f"call_vs_signature:{field}"] += 1
            if identity_ok:
                for pin in exact_parameter_pins:
                    pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
                    if type_key(pin_type) != type_key(expected_type):
                        for field in type_diff_fields(expected_type, pin_type):
                            function_data_type_diff_fields[f"signature_vs_pin:{field}"] += 1
                    if type_key(pin_type) != type_key(call_type):
                        for field in type_diff_fields(call_type, pin_type):
                            function_data_type_diff_fields[f"call_vs_pin:{field}"] += 1

            value_type_ok = bool(
                identity_ok
                and value_type_key(call_type) == value_type_key(expected_type)
                and all(
                    value_type_key(
                        pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
                    ) == value_type_key(expected_type)
                    for pin in exact_parameter_pins
                )
            )
            type_ok = value_type_ok
            if identity_ok:
                function_data_member_identity_exact_count += 1
            if value_type_ok:
                function_data_value_type_verified_count += 1
                if not (call_signature_equal and signature_pin_equal and call_pin_equal):
                    function_data_qualifier_difference_count += 1
                    function_data_status["qualifier_presentation_differs"] += 1
            if not identity_ok:
                function_data_mismatches[
                    f"{call_node_id} :: {direction}:{call_pin_name} :: exact_parameter_pin_missing"
                ] += 1
            elif not value_type_ok:
                function_data_mismatches[
                    f"{call_node_id} :: {direction}:{call_pin_name} :: structural_value_type_mismatch"
                ] += 1
        elif match_kind == "split_struct":
            member_pins = parameter_candidate_pins(target, direction, call_pin_name)
            exact_parameter_pins = member_pins
            identity_ok = bool(member_pins)
            if direction == "argument" and len(member_pins) != 1:
                identity_ok = False

            parent_pins = [
                pin_by_id[pin_id]
                for pin_id in parameter_pin_ids
                if pin_id in pin_by_id
            ]
            function_data_split_parent_pin_count += int(bool(parent_pins))

            parameter_name = str(binding.get("parameter_name", "") or "")
            split_suffix = str(binding.get("split_suffix", "") or "")
            if direction == "argument":
                node_ids = [str(target.get("entry_node_id", "") or "")]
                want_output = True
            else:
                node_ids = [
                    str(value or "")
                    for value in (
                        target.get("result_node_ids", [])
                        if isinstance(target.get("result_node_ids"), list)
                        else []
                    )
                    if value
                ]
                want_output = False

            raw_candidate_pins = []
            for node_id in node_ids:
                for candidate in pins_by_node.get(node_id, []):
                    if pin_is_output(candidate) != want_output:
                        continue
                    candidate_type = candidate.get("type", {}) if isinstance(candidate.get("type"), dict) else {}
                    if str(candidate_type.get("category", "") or "").lower() == "exec":
                        continue
                    raw_candidate_pins.append(candidate)

            exact_name_candidates = [
                pin for pin in raw_candidate_pins
                if str(pin.get("name", "") or "") == call_pin_name
            ]
            suffix_candidates = [
                pin for pin in raw_candidate_pins
                if split_suffix and str(pin.get("name", "") or "") == split_suffix
            ]
            prefixed_candidates = [
                pin for pin in raw_candidate_pins
                if parameter_name
                and str(pin.get("name", "") or "").startswith(parameter_name + "_")
            ]
            function_data_split_exact_name_candidate_count += len(exact_name_candidates)
            function_data_split_suffix_candidate_count += len(suffix_candidates)
            function_data_split_prefixed_candidate_count += len(prefixed_candidates)
            function_data_split_candidate_shapes[
                (
                    f"parent={'yes' if parent_pins else 'no'} "
                    f"exact={len(exact_name_candidates)} "
                    f"suffix={len(suffix_candidates)} "
                    f"prefixed={len(prefixed_candidates)} "
                    f"raw_nonexec={len(raw_candidate_pins)}"
                )
            ] += 1
            if len(function_data_split_candidate_examples) < limit:
                function_data_split_candidate_examples.append({
                    "call_node_id": call_node_id,
                    "direction": direction,
                    "call_pin_name": call_pin_name,
                    "parameter_name": parameter_name,
                    "split_suffix": split_suffix,
                    "parent_pin_names": sorted(
                        str(pin.get("name", "") or "") for pin in parent_pins
                    ),
                    "raw_pin_names": sorted(
                        str(pin.get("name", "") or "") for pin in raw_candidate_pins
                    ),
                })

            # UE keeps these members split only at the call site in the
            # representative GASP corpus. The callee boundary exposes the exact
            # unsplit parent parameter. Treat that as an authored parent
            # projection, not as a missing child-pin defect.
            expected_type = binding.get("parameter_type", {})
            parent_identity_ok = bool(
                parameter_pin_ids
                and len(parent_pins) == len(parameter_pin_ids)
            )
            parent_value_type_ok = bool(
                parent_identity_ok
                and all(
                    value_type_key(
                        pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
                    ) == value_type_key(expected_type)
                    for pin in parent_pins
                )
            )
            identity_ok = parent_identity_ok
            type_ok = parent_value_type_ok
            exact_parameter_pins = parent_pins

            if parent_identity_ok:
                function_data_split_parent_projection_count += 1
                function_data_status["split_parent_projection"] += 1
            else:
                function_data_mismatches[
                    f"{call_node_id} :: {direction}:{call_pin_name} :: split_parent_parameter_missing"
                ] += 1
            if parent_value_type_ok:
                function_data_value_type_verified_count += 1
            elif parent_identity_ok:
                function_data_mismatches[
                    f"{call_node_id} :: {direction}:{call_pin_name} :: split_parent_value_type_mismatch"
                ] += 1

            # Keep the diagnostic counts from the first pass explicit: no
            # exact member pin is claimed unless one is actually captured.
            if member_pins:
                function_data_split_member_resolved_count += 1
                function_data_status["split_member_exact_pin_resolved"] += 1
            else:
                function_data_split_member_unresolved_count += 1
                function_data_status["split_member_identity_not_captured"] += 1
        else:
            function_data_mismatches[
                f"{call_node_id} :: {direction}:{call_pin_name} :: unexpected_match_kind:{match_kind or '<empty>'}"
            ] += 1

        if identity_ok:
            function_data_parameter_identity_count += 1
            function_data_status["parameter_identity_verified"] += 1
        if type_ok:
            function_data_type_verified_count += 1
            function_data_status["value_type_verified"] += 1

        binding_contract_kind = str(binding.get("parameter_identity_kind", "") or "")
        binding_contract_type = binding.get("value_type_compatible")
        if binding_contract_kind:
            expected_kind = (
                "exact_parameter" if match_kind == "exact"
                else "split_parent_projection" if match_kind == "split_struct"
                else ""
            )
            if expected_kind and binding_contract_kind != expected_kind:
                function_data_mismatches[
                    f"{call_node_id} :: {direction}:{call_pin_name} :: binding_identity_contract_mismatch"
                ] += 1
        if binding_contract_type is not None and bool(binding_contract_type) != bool(type_ok):
            function_data_mismatches[
                f"{call_node_id} :: {direction}:{call_pin_name} :: binding_value_type_contract_mismatch"
            ] += 1

        implementation_target = target_kind not in {
            "interface_dispatch_or_declaration",
            "latent_internal",
            "missing_target",
        }
        if implementation_target:
            function_data_expected_route_count += 1
            if direction == "argument":
                function_data_expected_argument_route_count += 1
            else:
                function_data_expected_return_route_count += 1
            if match_kind == "split_struct":
                function_data_expected_split_projection_count += 1

        if direction == "argument":
            function_data_argument_count += 1
            dependency_ids = [
                str(value or "")
                for value in (
                    binding.get("dependency_ids", [])
                    if isinstance(binding.get("dependency_ids"), list)
                    else []
                )
                if value
            ]
            incoming = data_incoming_by_pin.get(call_pin_id, [])
            has_connected_value = bool(dependency_ids or incoming)
            has_authored_value = pin_has_authored_value(call_pin)
            if has_connected_value:
                function_data_argument_connected_value_count += 1
                function_data_status["argument_connected_value"] += 1
                has_value = True
            elif has_authored_value:
                function_data_argument_authored_value_count += 1
                function_data_status["argument_authored_value"] += 1
                has_value = True
            else:
                function_data_argument_no_value_count += 1
                function_data_status["argument_no_value_evidence"] += 1
                has_value = False

            consumers = [
                edge
                for pin in exact_parameter_pins
                for edge in data_outgoing_by_pin.get(str(pin.get("pin_id", "") or ""), [])
            ]
            function_data_argument_body_consumer_count += len(consumers)
            if consumers:
                function_data_status["argument_used_by_callee"] += 1
            else:
                function_data_argument_unused_count += 1
                function_data_status["argument_unused_by_callee"] += 1

            binding_verified = bool(implementation_target and identity_ok and type_ok and has_value)
            if binding_verified:
                function_data_argument_binding_verified_count += 1
                function_data_status["argument_binding_verified"] += 1
            member_route_exact = match_kind == "exact"
            if binding_verified and consumers and member_route_exact:
                function_data_argument_route_ready_count += 1
                function_data_status["argument_route_ready"] += 1
            elif binding_verified and consumers and match_kind == "split_struct":
                function_data_status["argument_split_projection_not_member_route"] += 1
            continue

        function_data_return_count += 1
        dependency_rows_by_pin = {
            str(pin.get("pin_id", "") or ""): dependency_by_sink_pin.get(
                str(pin.get("pin_id", "") or ""), []
            )
            for pin in exact_parameter_pins
        }
        dependency_count = sum(len(values) for values in dependency_rows_by_pin.values())
        function_data_return_dependency_count += dependency_count
        authored_result_pin_count = sum(
            int(pin_has_authored_value(pin))
            for pin in exact_parameter_pins
        )
        function_data_return_authored_value_pin_count += authored_result_pin_count

        provenance_complete = bool(exact_parameter_pins) and all(
            dependency_rows_by_pin.get(str(pin.get("pin_id", "") or ""))
            or pin_has_authored_value(pin)
            for pin in exact_parameter_pins
        )
        if provenance_complete:
            function_data_status["return_internal_provenance_complete"] += 1
        else:
            function_data_return_missing_provenance_binding_count += 1
            function_data_status["return_internal_provenance_incomplete"] += 1

        caller_consumers = data_outgoing_by_pin.get(call_pin_id, [])
        function_data_return_caller_consumer_count += len(caller_consumers)
        if caller_consumers:
            function_data_status["return_used_by_caller"] += 1
        else:
            function_data_return_unused_count += 1
            function_data_status["return_unused_by_caller"] += 1

        binding_verified = bool(
            implementation_target and identity_ok and type_ok and provenance_complete
        )
        if binding_verified:
            function_data_return_binding_verified_count += 1
            function_data_status["return_binding_verified"] += 1
        member_route_exact = match_kind == "exact"
        if binding_verified and caller_consumers and member_route_exact:
            function_data_return_route_ready_count += 1
            function_data_status["return_route_ready"] += 1
        elif binding_verified and caller_consumers and match_kind == "split_struct":
            function_data_status["return_split_projection_not_member_route"] += 1

    function_interprocedural_data_route_kinds = collections.Counter(
        str(row.get("route_kind", "") or "<empty>")
        for row in function_interprocedural_data_routes
    )
    function_interprocedural_data_identity_kinds = collections.Counter(
        str(row.get("parameter_identity_kind", "") or "<empty>")
        for row in function_interprocedural_data_routes
    )
    function_interprocedural_data_boundary_ready_count = sum(
        int(bool(row.get("boundary_ready", False)))
        for row in function_interprocedural_data_routes
    )
    function_interprocedural_data_member_ready_count = sum(
        int(bool(row.get("member_route_ready", False)))
        for row in function_interprocedural_data_routes
    )
    function_interprocedural_data_alignment = bool(
        len(function_interprocedural_data_routes) == function_data_expected_route_count
        and int(function_interprocedural_data_route_kinds.get("function_argument", 0))
            == function_data_expected_argument_route_count
        and int(function_interprocedural_data_route_kinds.get("function_return", 0))
            == function_data_expected_return_route_count
        and int(
            function_interprocedural_data_identity_kinds.get(
                "split_parent_projection", 0
            )
        ) == function_data_expected_split_projection_count
        and function_interprocedural_data_boundary_ready_count
            == function_data_argument_binding_verified_count
                + function_data_return_binding_verified_count
        and function_interprocedural_data_member_ready_count
            == function_data_argument_route_ready_count
                + function_data_return_route_ready_count
    )

    function_interprocedural_edge_kinds = collections.Counter(
        str(row.get("edge_kind", "") or "<empty>")
        for row in function_interprocedural_edges
    )
    function_interprocedural_terminal_kinds = collections.Counter(
        str(row.get("terminal_kind", "") or "<empty>")
        for row in function_interprocedural_terminals
    )
    function_interprocedural_stream_alignment = bool(
        int(function_interprocedural_edge_kinds.get("function_enter", 0))
            == function_direct_expected_enter_edge_count
        and int(function_interprocedural_edge_kinds.get("function_return", 0))
            == function_direct_expected_return_edge_count
        and len(function_interprocedural_edges)
            == function_direct_expected_enter_edge_count + function_direct_expected_return_edge_count
        and len(function_interprocedural_terminals)
            == function_direct_expected_terminal_record_count
        and int(
            function_interprocedural_terminal_kinds.get(
                "function_call_no_continuation", 0
            )
        ) == function_direct_expected_terminal_record_count
    )

    control_rig_nodes = [row for row in all_nodes if str(row.get("operation", "") or "") == "control_rig_node"]
    control_rig_ids = {str(row.get("node_id", "") or "") for row in control_rig_nodes if row.get("node_id")}
    rigvm_path = output / "rigvm_editor_links.jsonl"
    rigvm_links = list(rows(rigvm_path)) if rigvm_path.is_file() else []
    rigvm_link_ids = [str(row.get("node_id", "") or "") for row in rigvm_links if row.get("node_id")]
    rigvm_link_id_set = set(rigvm_link_ids)
    matched_links = [
        row for row in rigvm_links
        if str(row.get("status", "") or "") == "matched"
        and str(row.get("rigvm_object_id", "") or "")
    ]
    matched_node_ids = {str(row.get("node_id", "") or "") for row in matched_links if row.get("node_id")}

    rigvm_status = collections.Counter(str(row.get("status", "") or "<empty>") for row in rigvm_links)
    rigvm_confidence = collections.Counter(str(row.get("confidence", "") or "<empty>") for row in rigvm_links)
    rigvm_operations = collections.Counter(str(row.get("rigvm_operation", "") or "<empty>") for row in matched_links)
    rigvm_classes = collections.Counter(str(row.get("rigvm_class", "") or "<empty>") for row in matched_links)
    rigvm_functions = collections.Counter(
        str(row.get("resolved_function_name", "") or "<empty>")
        for row in matched_links
        if row.get("resolved_function_name")
    )
    rigvm_templates = collections.Counter(
        str(row.get("template_notation", "") or "<empty>")
        for row in matched_links
        if row.get("template_notation")
    )

    return {
        "node_count": len(all_nodes),
        "modeled_count": modeled,
        "fallback_count": len(fallback),
        "opaque_count": len(opaque),
        "fallback_exec_count": sum(int(bool(row.get("has_exec_flow", False))) for row in fallback),
        "fallback_data_only_count": sum(int(not bool(row.get("has_exec_flow", False))) for row in fallback),
        "fallback_operations": top(fallback_operations),
        "fallback_classes": top(fallback_classes),
        "fallback_blueprints": top(fallback_blueprints),
        "fallback_graphs": top(fallback_graphs),
        "opaque_classes": top(opaque_classes),
        "macro_instance_count": len(raw_macro_nodes),
        "macro_semantic_node_count": len(semantic_macro_nodes),
        "macro_missing_semantic_node_count": missing_macro_semantic_nodes,
        "macro_matched_count": int(macro_status.get("matched", 0)),
        "macro_external_count": int(macro_status.get("external_or_unscanned", 0)),
        "macro_missing_graph_identity_count": int(macro_status.get("missing_graph_identity", 0)),
        "macro_ambiguous_graph_path_count": int(macro_status.get("ambiguous_captured_graph_path", 0)),
        "macro_duplicate_captured_graph_path_count": duplicate_captured_macro_graph_paths,
        "macro_status": top(macro_status),
        "matched_macro_graphs": top(matched_macro_graphs),
        "external_macro_graphs": top(external_macro_graphs),
        "macro_source_blueprints": top(macro_source_blueprints),
        "macro_interface_graph_count": len(macro_interface_graph_details),
        "macro_interface_exact_role_graph_count": int(macro_interface_graph_status.get("exact_roles", 0)),
        "macro_interface_unresolved_role_graph_count": int(macro_interface_graph_status.get("unresolved_roles", 0)),
        "macro_interface_shapes": top(macro_interface_shapes),
        "macro_interface_graph_status": top(macro_interface_graph_status),
        "macro_binding_instance_count": macro_binding_instance_count,
        "macro_binding_resolved_instance_count": macro_binding_resolved_instance_count,
        "macro_binding_pin_count": macro_binding_pin_count,
        "macro_binding_exact_pin_count": macro_binding_exact_pin_count,
        "macro_binding_status": top(macro_binding_status),
        "macro_binding_mismatches": top(macro_binding_mismatches),
        "macro_semantic_proof_edges": top(macro_semantic_proof_edges),
        "macro_semantic_proof_edge_count": sum(macro_semantic_proof_edges.values()),
        "macro_data_input_binding_count": macro_data_input_binding_count,
        "macro_data_input_connected_source_count": macro_data_input_connected_source_count,
        "macro_data_input_authored_value_count": macro_data_input_authored_value_count,
        "macro_data_input_no_value_count": macro_data_input_no_value_count,
        "macro_data_input_body_consumer_edge_count": macro_data_input_body_consumer_edge_count,
        "macro_data_input_used_binding_count": macro_data_input_used_binding_count,
        "macro_data_input_bridge_ready_count": macro_data_input_bridge_ready_count,
        "macro_data_output_binding_count": macro_data_output_binding_count,
        "macro_data_output_internal_source_edge_count": macro_data_output_internal_source_edge_count,
        "macro_data_output_dependency_count": macro_data_output_dependency_count,
        "macro_data_output_caller_consumer_edge_count": macro_data_output_caller_consumer_edge_count,
        "macro_data_output_used_binding_count": macro_data_output_used_binding_count,
        "macro_data_output_bridge_ready_count": macro_data_output_bridge_ready_count,
        "macro_data_status": top(macro_data_status),
        "macro_data_mismatches": top(macro_data_mismatches),
        "macro_exec_exact_instance_count": macro_exec_exact_instance_count,
        "macro_exec_data_only_instance_count": macro_exec_data_only_instance_count,
        "macro_exec_input_binding_count": macro_exec_input_binding_count,
        "macro_exec_exact_entry_bridge_count": macro_exec_exact_entry_bridge_count,
        "macro_exec_output_binding_count": macro_exec_output_binding_count,
        "macro_exec_connected_output_count": macro_exec_connected_output_count,
        "macro_exec_terminal_output_count": macro_exec_terminal_output_count,
        "macro_exec_exact_return_bridge_count": macro_exec_exact_return_bridge_count,
        "macro_exec_duplicate_block_node_count": macro_exec_duplicate_block_node_count,
        "macro_exec_status": top(macro_exec_status),
        "macro_exec_mismatches": top(macro_exec_mismatches),
        "interprocedural_execution_edge_count": len(interprocedural_edges),
        "interprocedural_execution_edge_kinds": top(interprocedural_edge_kinds),
        "interprocedural_execution_terminal_count": len(interprocedural_terminals),
        "interprocedural_execution_terminal_kinds": top(interprocedural_terminal_kinds),
        "interprocedural_expected_edge_count": interprocedural_expected_edge_count,
        "interprocedural_stream_alignment": interprocedural_stream_alignment,
        "interprocedural_data_route_count": len(interprocedural_data_routes),
        "interprocedural_expected_data_route_count": interprocedural_expected_data_route_count,
        "interprocedural_data_ready_count": interprocedural_data_ready_count,
        "interprocedural_data_kinds": top(interprocedural_data_kinds),
        "interprocedural_data_value_kinds": top(interprocedural_data_value_kinds),
        "interprocedural_data_stream_alignment": interprocedural_data_stream_alignment,
        "delegate_node_count": len(delegate_nodes),
        "delegate_operation_counts": top(delegate_operation_counts),
        "delegate_dispatcher_node_count": delegate_dispatcher_node_count,
        "delegate_exact_dispatcher_identity_count": delegate_exact_dispatcher_identity_count,
        "delegate_member_guid_count": delegate_member_guid_count,
        "delegate_self_context_count": delegate_self_context_count,
        "delegate_external_context_count": delegate_external_context_count,
        "delegate_dispatcher_identity_status": top(delegate_dispatcher_identity_status),
        "delegate_dispatcher_operations": top(delegate_dispatcher_operations),
        "delegate_dispatcher_shapes": top(delegate_dispatcher_shapes),
        "delegate_create_count": len(create_nodes),
        "delegate_create_selected_name_count": delegate_create_selected_name_count,
        "delegate_create_selected_guid_count": delegate_create_selected_guid_count,
        "delegate_create_exact_endpoint_count": delegate_create_exact_endpoint_count,
        "delegate_create_status": top(delegate_create_status),
        "delegate_create_target_operations": top(delegate_create_target_operations),
        "delegate_create_function_local_resolution": top(delegate_create_function_local_resolution),
        "delegate_create_examples": delegate_create_examples,
        "delegate_bind_assign_node_count": delegate_bind_assign_node_count,
        "delegate_bind_assign_delegate_input_edge_count": delegate_bind_assign_delegate_input_edge_count,
        "delegate_create_to_bind_assign_edge_count": delegate_create_to_bind_assign_edge_count,
        "delegate_exact_bound_endpoint_chain_count": delegate_exact_bound_endpoint_chain_count,
        "delegate_data_source_status": top(delegate_data_source_status),
        "delegate_data_source_operations": top(delegate_data_source_operations),
        "delegate_binding_route_count": len(delegate_binding_rows),
        "delegate_binding_operation_counts": top(delegate_binding_operation_counts),
        "delegate_binding_basis_counts": top(delegate_binding_basis_counts),
        "delegate_binding_endpoint_kinds": top(delegate_binding_endpoint_kinds),
        "delegate_binding_create_route_count": delegate_binding_create_route_count,
        "delegate_binding_direct_route_count": delegate_binding_direct_route_count,
        "delegate_binding_expected_direct_route_count": delegate_binding_expected_direct_route_count,
        "delegate_binding_alignment": delegate_binding_alignment,
        "delegate_component_bound_event_count": len(component_bound_events),
        "delegate_component_event_exact_identity_count": delegate_component_event_exact_identity_count,
        "delegate_component_event_join_count": delegate_component_event_join_count,
        "delegate_component_event_status": top(delegate_component_event_status),
        "delegate_call_identity_status": top(delegate_call_identity_status),
        "delegate_mismatch_count": sum(delegate_mismatches.values()),
        "delegate_mismatches": top(delegate_mismatches),
        "function_data_binding_count": function_data_binding_count,
        "function_data_binding_schema_versions": top(function_data_binding_schema_versions),
        "function_data_binding_schema_current": function_data_binding_schema_current,
        "function_data_target_kinds": top(function_data_target_kinds),
        "function_data_directions": top(function_data_directions),
        "function_data_match_kinds": top(function_data_match_kinds),
        "function_data_status": top(function_data_status),
        "function_data_mismatches": top(function_data_mismatches),
        "function_data_mismatch_count": sum(function_data_mismatches.values()),
        "function_data_parameter_identity_count": function_data_parameter_identity_count,
        "function_data_member_identity_exact_count": function_data_member_identity_exact_count,
        "function_data_split_parent_projection_count": function_data_split_parent_projection_count,
        "function_data_value_type_verified_count": function_data_value_type_verified_count,
        "function_data_type_verified_count": function_data_type_verified_count,
        "function_data_qualifier_difference_count": function_data_qualifier_difference_count,
        "function_data_exact_call_signature_equal_count": function_data_exact_call_signature_equal_count,
        "function_data_exact_signature_pin_equal_count": function_data_exact_signature_pin_equal_count,
        "function_data_exact_call_pin_equal_count": function_data_exact_call_pin_equal_count,
        "function_data_type_diff_fields": top(function_data_type_diff_fields),
        "function_data_type_surface_shapes": top(function_data_type_surface_shapes),
        "function_data_split_member_resolved_count": function_data_split_member_resolved_count,
        "function_data_split_member_unresolved_count": function_data_split_member_unresolved_count,
        "function_data_split_parent_pin_count": function_data_split_parent_pin_count,
        "function_data_split_exact_name_candidate_count": function_data_split_exact_name_candidate_count,
        "function_data_split_suffix_candidate_count": function_data_split_suffix_candidate_count,
        "function_data_split_prefixed_candidate_count": function_data_split_prefixed_candidate_count,
        "function_data_split_candidate_shapes": top(function_data_split_candidate_shapes),
        "function_data_split_candidate_examples": function_data_split_candidate_examples,
        "function_data_argument_count": function_data_argument_count,
        "function_data_argument_connected_value_count": function_data_argument_connected_value_count,
        "function_data_argument_authored_value_count": function_data_argument_authored_value_count,
        "function_data_argument_no_value_count": function_data_argument_no_value_count,
        "function_data_argument_body_consumer_count": function_data_argument_body_consumer_count,
        "function_data_argument_unused_count": function_data_argument_unused_count,
        "function_data_argument_binding_verified_count": function_data_argument_binding_verified_count,
        "function_data_argument_route_ready_count": function_data_argument_route_ready_count,
        "function_data_return_count": function_data_return_count,
        "function_data_return_dependency_count": function_data_return_dependency_count,
        "function_data_return_authored_value_pin_count": function_data_return_authored_value_pin_count,
        "function_data_return_missing_provenance_binding_count": function_data_return_missing_provenance_binding_count,
        "function_data_return_caller_consumer_count": function_data_return_caller_consumer_count,
        "function_data_return_unused_count": function_data_return_unused_count,
        "function_data_return_binding_verified_count": function_data_return_binding_verified_count,
        "function_data_return_route_ready_count": function_data_return_route_ready_count,
        "function_data_expected_route_count": function_data_expected_route_count,
        "function_data_expected_argument_route_count": function_data_expected_argument_route_count,
        "function_data_expected_return_route_count": function_data_expected_return_route_count,
        "function_data_expected_split_projection_count": function_data_expected_split_projection_count,
        "function_interprocedural_data_route_count": len(function_interprocedural_data_routes),
        "function_interprocedural_data_route_kinds": top(function_interprocedural_data_route_kinds),
        "function_interprocedural_data_identity_kinds": top(function_interprocedural_data_identity_kinds),
        "function_interprocedural_data_boundary_ready_count": function_interprocedural_data_boundary_ready_count,
        "function_interprocedural_data_member_ready_count": function_interprocedural_data_member_ready_count,
        "function_interprocedural_data_alignment": function_interprocedural_data_alignment,
        "function_call_count": len(call_edges),
        "function_call_resolution": top(function_call_resolution),
        "function_call_internal_count": function_call_internal_count,
        "function_call_internal_target_count": function_call_internal_target_count,
        "function_call_interface_count": function_call_interface_count,
        "function_call_pure_internal_count": function_call_pure_internal_count,
        "function_call_latent_internal_count": function_call_latent_internal_count,
        "function_call_direct_impure_count": function_call_direct_impure_count,
        "function_call_purity_override_count": function_call_purity_override_count,
        "function_call_suspicious_purity_count": function_call_suspicious_purity_count,
        "function_call_unknown_blueprint_type_count": function_call_unknown_blueprint_type_count,
        "function_internal_kinds": top(function_internal_kinds),
        "function_call_mismatches": top(function_call_mismatches),
        "function_direct_exact_caller_block_count": function_direct_exact_caller_block_count,
        "function_direct_exact_entry_block_count": function_direct_exact_entry_block_count,
        "function_direct_result_node_count": function_direct_result_node_count,
        "function_direct_exact_result_block_count": function_direct_exact_result_block_count,
        "function_direct_explicit_result_call_count": function_direct_explicit_result_call_count,
        "function_direct_void_call_count": function_direct_void_call_count,
        "function_direct_reachable_terminal_block_count": function_direct_reachable_terminal_block_count,
        "function_direct_calls_with_terminal_frontier": function_direct_calls_with_terminal_frontier,
        "function_direct_reachable_result_node_count": function_direct_reachable_result_node_count,
        "function_direct_unreachable_result_node_count": function_direct_unreachable_result_node_count,
        "function_direct_unreachable_callsite_count": function_direct_unreachable_callsite_count,
        "function_direct_no_return_frontier_count": function_direct_no_return_frontier_count,
        "function_direct_connected_continuation_count": function_direct_connected_continuation_count,
        "function_direct_terminal_call_count": function_direct_terminal_call_count,
        "function_direct_exact_continuation_block_count": function_direct_exact_continuation_block_count,
        "function_direct_bridge_ready_count": function_direct_bridge_ready_count,
        "function_direct_bridge_ready_connected_call_count": function_direct_bridge_ready_connected_call_count,
        "function_direct_bridge_ready_terminal_call_count": function_direct_bridge_ready_terminal_call_count,
        "function_direct_expected_enter_edge_count": function_direct_expected_enter_edge_count,
        "function_direct_expected_return_edge_count": function_direct_expected_return_edge_count,
        "function_direct_expected_terminal_record_count": function_direct_expected_terminal_record_count,
        "function_direct_bridge_ready_return_frontier_block_count": function_direct_bridge_ready_return_frontier_block_count,
        "function_direct_binding_count": function_direct_binding_count,
        "function_interprocedural_edge_count": len(function_interprocedural_edges),
        "function_interprocedural_terminal_count": len(function_interprocedural_terminals),
        "function_interprocedural_edge_kinds": top(function_interprocedural_edge_kinds),
        "function_interprocedural_terminal_kinds": top(function_interprocedural_terminal_kinds),
        "function_interprocedural_stream_alignment": function_interprocedural_stream_alignment,
        "control_rig_node_count": len(control_rig_nodes),
        "rigvm_link_count": len(rigvm_links),
        "rigvm_duplicate_link_node_ids": len(rigvm_link_ids) - len(rigvm_link_id_set),
        "rigvm_matched_count": len(matched_links),
        "rigvm_unmatched_control_rig_count": len(control_rig_ids - matched_node_ids),
        "rigvm_missing_link_count": len(control_rig_ids - rigvm_link_id_set),
        "rigvm_extra_link_count": len(rigvm_link_id_set - control_rig_ids),
        "rigvm_status": top(rigvm_status),
        "rigvm_confidence": top(rigvm_confidence),
        "rigvm_operations": top(rigvm_operations),
        "rigvm_classes": top(rigvm_classes),
        "rigvm_functions": top(rigvm_functions),
        "rigvm_templates": top(rigvm_templates),
    }


def print_report(report: dict) -> None:
    total = int(report.get("node_count", 0) or 0)
    modeled = int(report.get("modeled_count", 0) or 0)
    fallback = int(report.get("fallback_count", 0) or 0)
    opaque = int(report.get("opaque_count", 0) or 0)
    modeled_pct = (100.0 * modeled / total) if total else 100.0

    print("=== BLUEPRINT SEMANTIC COVERAGE ===")
    print(
        f"nodes={total} modeled={modeled} fallback={fallback} opaque={opaque} "
        f"modeled_coverage={modeled_pct:.2f}%"
    )
    print(
        "fallback flow: "
        f"exec={int(report.get('fallback_exec_count', 0) or 0)} "
        f"data_only={int(report.get('fallback_data_only_count', 0) or 0)}"
    )

    def section(title: str, key: str) -> None:
        print(f"\n[{title}]")
        values = report.get(key, [])
        if not values:
            print("<none>")
            return
        for name, count in values:
            print(f"{count:6d}  {name}")

    section("fallback operations", "fallback_operations")
    section("fallback node classes", "fallback_classes")
    section("fallback blueprints", "fallback_blueprints")
    section("fallback graphs", "fallback_graphs")
    if opaque:
        section("opaque node classes", "opaque_classes")

    macro_instances = int(report.get("macro_instance_count", 0) or 0)
    macro_matched = int(report.get("macro_matched_count", 0) or 0)
    macro_pct = (100.0 * macro_matched / macro_instances) if macro_instances else 100.0
    print("\n[Macro Instance -> Macro Graph bridge]")
    print(
        f"macro_instances={macro_instances} "
        f"semantic_nodes={int(report.get('macro_semantic_node_count', 0) or 0)} "
        f"exact_graph_matches={macro_matched} "
        f"exact_match_coverage={macro_pct:.2f}% "
        f"external_or_unscanned={int(report.get('macro_external_count', 0) or 0)} "
        f"missing_graph_identity={int(report.get('macro_missing_graph_identity_count', 0) or 0)} "
        f"ambiguous_graph_paths={int(report.get('macro_ambiguous_graph_path_count', 0) or 0)} "
        f"missing_semantic_nodes={int(report.get('macro_missing_semantic_node_count', 0) or 0)} "
        f"duplicate_captured_graph_paths={int(report.get('macro_duplicate_captured_graph_path_count', 0) or 0)}"
    )
    section("Macro bridge status", "macro_status")
    section("matched macro graphs", "matched_macro_graphs")
    section("external/unscanned macro graphs", "external_macro_graphs")
    section("macro source Blueprints", "macro_source_blueprints")

    binding_pins = int(report.get("macro_binding_pin_count", 0) or 0)
    exact_binding_pins = int(report.get("macro_binding_exact_pin_count", 0) or 0)
    binding_pct = (100.0 * exact_binding_pins / binding_pins) if binding_pins else 100.0
    print("\n[Macro Graph interface evidence]")
    print(
        f"matched_macro_graphs={int(report.get('macro_interface_graph_count', 0) or 0)} "
        f"exact_role_graphs={int(report.get('macro_interface_exact_role_graph_count', 0) or 0)} "
        f"unresolved_role_graphs={int(report.get('macro_interface_unresolved_role_graph_count', 0) or 0)} "
        f"matched_instances={int(report.get('macro_binding_instance_count', 0) or 0)} "
        f"resolved_interface_instances={int(report.get('macro_binding_resolved_instance_count', 0) or 0)} "
        f"instance_pins={binding_pins} exact_pin_bindings={exact_binding_pins} "
        f"exact_pin_binding_coverage={binding_pct:.2f}%"
    )
    section("macro tunnel direction shapes", "macro_interface_shapes")
    section("macro interface graph status", "macro_interface_graph_status")
    section("macro pin binding status", "macro_binding_status")
    section("macro pin binding mismatches", "macro_binding_mismatches")

    print("\n[Macro semantic proof edges]")
    print(f"proof_edges={int(report.get('macro_semantic_proof_edge_count', 0) or 0)}")
    section("macro semantic proof relations", "macro_semantic_proof_edges")

    print("\n[Macro interprocedural data provenance evidence]")
    print(
        f"data_input_bindings={int(report.get('macro_data_input_binding_count', 0) or 0)} "
        f"connected_input_sources={int(report.get('macro_data_input_connected_source_count', 0) or 0)} "
        f"authored_input_values={int(report.get('macro_data_input_authored_value_count', 0) or 0)} "
        f"inputs_without_value_evidence={int(report.get('macro_data_input_no_value_count', 0) or 0)} "
        f"used_input_bindings={int(report.get('macro_data_input_used_binding_count', 0) or 0)} "
        f"input_body_consumer_edges={int(report.get('macro_data_input_body_consumer_edge_count', 0) or 0)} "
        f"input_bridge_ready={int(report.get('macro_data_input_bridge_ready_count', 0) or 0)}"
    )
    print(
        f"data_output_bindings={int(report.get('macro_data_output_binding_count', 0) or 0)} "
        f"internal_output_source_edges={int(report.get('macro_data_output_internal_source_edge_count', 0) or 0)} "
        f"output_dependencies={int(report.get('macro_data_output_dependency_count', 0) or 0)} "
        f"caller_output_consumer_edges={int(report.get('macro_data_output_caller_consumer_edge_count', 0) or 0)} "
        f"used_output_bindings={int(report.get('macro_data_output_used_binding_count', 0) or 0)} "
        f"output_bridge_ready={int(report.get('macro_data_output_bridge_ready_count', 0) or 0)}"
    )
    section("macro data provenance status", "macro_data_status")
    section("macro data provenance mismatches", "macro_data_mismatches")

    print("\n[Macro interprocedural execution evidence]")
    print(
        f"executable_exact_instances={int(report.get('macro_exec_exact_instance_count', 0) or 0)} "
        f"data_only_exact_instances={int(report.get('macro_exec_data_only_instance_count', 0) or 0)} "
        f"exec_input_bindings={int(report.get('macro_exec_input_binding_count', 0) or 0)} "
        f"exact_entry_block_bridges={int(report.get('macro_exec_exact_entry_bridge_count', 0) or 0)} "
        f"exec_output_bindings={int(report.get('macro_exec_output_binding_count', 0) or 0)} "
        f"connected_exec_outputs={int(report.get('macro_exec_connected_output_count', 0) or 0)} "
        f"terminal_exec_outputs={int(report.get('macro_exec_terminal_output_count', 0) or 0)} "
        f"exact_return_block_bridges={int(report.get('macro_exec_exact_return_bridge_count', 0) or 0)} "
        f"duplicate_block_nodes={int(report.get('macro_exec_duplicate_block_node_count', 0) or 0)}"
    )
    section("macro execution bridge status", "macro_exec_status")
    section("macro execution bridge mismatches", "macro_exec_mismatches")

    print("\n[Blueprint interprocedural data routes]")
    print(
        f"routes={int(report.get('interprocedural_data_route_count', 0) or 0)} "
        f"expected_routes={int(report.get('interprocedural_expected_data_route_count', 0) or 0)} "
        f"bridge_ready={int(report.get('interprocedural_data_ready_count', 0) or 0)} "
        f"aligned={bool(report.get('interprocedural_data_stream_alignment', False))}"
    )
    section("interprocedural data route kinds", "interprocedural_data_kinds")
    section("interprocedural data value kinds", "interprocedural_data_value_kinds")

    print("\n[Blueprint interprocedural execution streams]")
    print(
        f"edges={int(report.get('interprocedural_execution_edge_count', 0) or 0)} "
        f"expected_edges={int(report.get('interprocedural_expected_edge_count', 0) or 0)} "
        f"terminals={int(report.get('interprocedural_execution_terminal_count', 0) or 0)} "
        f"aligned={bool(report.get('interprocedural_stream_alignment', False))}"
    )
    section("interprocedural execution edge kinds", "interprocedural_execution_edge_kinds")
    section("interprocedural execution terminal kinds", "interprocedural_execution_terminal_kinds")

    print("\n[Blueprint delegate/dispatcher evidence]")
    print(
        f"nodes={int(report.get('delegate_node_count', 0) or 0)} "
        f"dispatcher_nodes={int(report.get('delegate_dispatcher_node_count', 0) or 0)} "
        f"exact_dispatcher_identity={int(report.get('delegate_exact_dispatcher_identity_count', 0) or 0)} "
        f"member_guids={int(report.get('delegate_member_guid_count', 0) or 0)} "
        f"self_context={int(report.get('delegate_self_context_count', 0) or 0)} "
        f"external_context={int(report.get('delegate_external_context_count', 0) or 0)} "
        f"create_nodes={int(report.get('delegate_create_count', 0) or 0)} "
        f"create_with_name={int(report.get('delegate_create_selected_name_count', 0) or 0)} "
        f"create_with_guid={int(report.get('delegate_create_selected_guid_count', 0) or 0)} "
        f"exact_create_endpoints={int(report.get('delegate_create_exact_endpoint_count', 0) or 0)} "
        f"mismatches={int(report.get('delegate_mismatch_count', 0) or 0)}"
    )
    section("delegate operations", "delegate_operation_counts")
    section("delegate dispatcher identity status", "delegate_dispatcher_identity_status")
    section("delegate dispatcher shapes", "delegate_dispatcher_shapes")
    section("delegate create endpoint status", "delegate_create_status")
    section("delegate create endpoint operations", "delegate_create_target_operations")
    section(
        "delegate create function local resolution",
        "delegate_create_function_local_resolution",
    )
    print("\n[Delegate bind/assign canonical data evidence]")
    print(
        f"bind_assign_nodes={int(report.get('delegate_bind_assign_node_count', 0) or 0)} "
        f"delegate_input_edges={int(report.get('delegate_bind_assign_delegate_input_edge_count', 0) or 0)} "
        f"create_to_bind_edges={int(report.get('delegate_create_to_bind_assign_edge_count', 0) or 0)} "
        f"exact_bound_endpoint_chains={int(report.get('delegate_exact_bound_endpoint_chain_count', 0) or 0)}"
    )
    section("delegate data source status", "delegate_data_source_status")
    section("delegate data source operations", "delegate_data_source_operations")
    print("\n[Blueprint authored delegate bindings]")
    print(
        f"routes={int(report.get('delegate_binding_route_count', 0) or 0)} "
        f"expected_routes={int(report.get('delegate_bind_assign_delegate_input_edge_count', 0) or 0)} "
        f"create_routes={int(report.get('delegate_binding_create_route_count', 0) or 0)} "
        f"expected_create_routes={int(report.get('delegate_create_to_bind_assign_edge_count', 0) or 0)} "
        f"direct_routes={int(report.get('delegate_binding_direct_route_count', 0) or 0)} "
        f"expected_direct_routes={int(report.get('delegate_binding_expected_direct_route_count', 0) or 0)} "
        f"aligned={bool(report.get('delegate_binding_alignment', False))}"
    )
    section("delegate binding operations", "delegate_binding_operation_counts")
    section("delegate binding endpoint basis", "delegate_binding_basis_counts")
    section("delegate binding endpoint kinds", "delegate_binding_endpoint_kinds")

    print("\n[Component-bound delegate events]")
    print(
        f"events={int(report.get('delegate_component_bound_event_count', 0) or 0)} "
        f"exact_identity={int(report.get('delegate_component_event_exact_identity_count', 0) or 0)} "
        f"joined_dispatcher_identity={int(report.get('delegate_component_event_join_count', 0) or 0)}"
    )
    section("component-bound delegate event status", "delegate_component_event_status")
    section("delegate call identity status", "delegate_call_identity_status")
    print("\n[delegate create endpoint examples]")
    delegate_examples = report.get("delegate_create_examples", [])
    if not delegate_examples:
        print("<none>")
    else:
        for example in delegate_examples:
            print(
                f"{example.get('node_id','')} :: selected={example.get('selected_function','')} "
                f"guid={example.get('selected_function_guid','')} "
                f"path={example.get('selected_function_path','')} "
                f"scope={example.get('selected_scope_class','')} "
                f"status={example.get('status','')} "
                f"target_op={example.get('target_operation','')} "
                f"target={example.get('target_node_id','')}"
            )
    section("delegate audit mismatches", "delegate_mismatches")

    print("\n[Blueprint function interprocedural data binding audit]")
    print(
        f"bindings={int(report.get('function_data_binding_count', 0) or 0)} "
        f"binding_schema_current={bool(report.get('function_data_binding_schema_current', False))} "
        f"parameter_identity_verified={int(report.get('function_data_parameter_identity_count', 0) or 0)} "
        f"exact_member_identity={int(report.get('function_data_member_identity_exact_count', 0) or 0)} "
        f"split_parent_projections={int(report.get('function_data_split_parent_projection_count', 0) or 0)} "
        f"value_type_verified={int(report.get('function_data_value_type_verified_count', 0) or 0)} "
        f"qualifier_differences={int(report.get('function_data_qualifier_difference_count', 0) or 0)} "
        f"split_member_resolved={int(report.get('function_data_split_member_resolved_count', 0) or 0)} "
        f"split_member_unresolved={int(report.get('function_data_split_member_unresolved_count', 0) or 0)} "
        f"mismatches={int(report.get('function_data_mismatch_count', 0) or 0)}"
    )
    print(
        "exact type surfaces: "
        f"call_signature_equal={int(report.get('function_data_exact_call_signature_equal_count', 0) or 0)} "
        f"signature_pin_equal={int(report.get('function_data_exact_signature_pin_equal_count', 0) or 0)} "
        f"call_pin_equal={int(report.get('function_data_exact_call_pin_equal_count', 0) or 0)}"
    )
    section("function binding schema versions", "function_data_binding_schema_versions")
    section("function exact type surface shapes", "function_data_type_surface_shapes")
    section("function exact type differing fields", "function_data_type_diff_fields")
    print(
        "split candidates: "
        f"parent_pins={int(report.get('function_data_split_parent_pin_count', 0) or 0)} "
        f"exact_name_candidates={int(report.get('function_data_split_exact_name_candidate_count', 0) or 0)} "
        f"suffix_candidates={int(report.get('function_data_split_suffix_candidate_count', 0) or 0)} "
        f"prefixed_candidates={int(report.get('function_data_split_prefixed_candidate_count', 0) or 0)}"
    )
    section("function split candidate shapes", "function_data_split_candidate_shapes")
    print("\n[function split candidate examples]")
    examples = report.get("function_data_split_candidate_examples", [])
    if not examples:
        print("<none>")
    else:
        for example in examples:
            print(
                f"{example.get('call_node_id','')} :: {example.get('direction','')}:"
                f"{example.get('call_pin_name','')} -> {example.get('parameter_name','')} "
                f"suffix={example.get('split_suffix','')} "
                f"parent={example.get('parent_pin_names',[])} "
                f"raw={example.get('raw_pin_names',[])}"
            )
    section("function data target kinds", "function_data_target_kinds")
    section("function data directions", "function_data_directions")
    section("function data match kinds", "function_data_match_kinds")
    print("\n[Function argument provenance]")
    print(
        f"arguments={int(report.get('function_data_argument_count', 0) or 0)} "
        f"connected_values={int(report.get('function_data_argument_connected_value_count', 0) or 0)} "
        f"authored_values={int(report.get('function_data_argument_authored_value_count', 0) or 0)} "
        f"without_value_evidence={int(report.get('function_data_argument_no_value_count', 0) or 0)} "
        f"body_consumer_edges={int(report.get('function_data_argument_body_consumer_count', 0) or 0)} "
        f"unused_arguments={int(report.get('function_data_argument_unused_count', 0) or 0)} "
        f"binding_verified={int(report.get('function_data_argument_binding_verified_count', 0) or 0)} "
        f"route_ready={int(report.get('function_data_argument_route_ready_count', 0) or 0)}"
    )
    print("\n[Function return provenance]")
    print(
        f"returns={int(report.get('function_data_return_count', 0) or 0)} "
        f"dependency_rows={int(report.get('function_data_return_dependency_count', 0) or 0)} "
        f"authored_result_pin_values={int(report.get('function_data_return_authored_value_pin_count', 0) or 0)} "
        f"incomplete_internal_provenance={int(report.get('function_data_return_missing_provenance_binding_count', 0) or 0)} "
        f"caller_consumer_edges={int(report.get('function_data_return_caller_consumer_count', 0) or 0)} "
        f"unused_returns={int(report.get('function_data_return_unused_count', 0) or 0)} "
        f"binding_verified={int(report.get('function_data_return_binding_verified_count', 0) or 0)} "
        f"route_ready={int(report.get('function_data_return_route_ready_count', 0) or 0)}"
    )
    section("function data binding status", "function_data_status")
    section("function data binding mismatches", "function_data_mismatches")

    print("\n[Blueprint function interprocedural data routes]")
    print(
        f"routes={int(report.get('function_interprocedural_data_route_count', 0) or 0)} "
        f"expected_routes={int(report.get('function_data_expected_route_count', 0) or 0)} "
        f"boundary_ready={int(report.get('function_interprocedural_data_boundary_ready_count', 0) or 0)} "
        f"expected_boundary_ready={int(report.get('function_data_argument_binding_verified_count', 0) or 0) + int(report.get('function_data_return_binding_verified_count', 0) or 0)} "
        f"member_ready={int(report.get('function_interprocedural_data_member_ready_count', 0) or 0)} "
        f"expected_member_ready={int(report.get('function_data_argument_route_ready_count', 0) or 0) + int(report.get('function_data_return_route_ready_count', 0) or 0)} "
        f"aligned={bool(report.get('function_interprocedural_data_alignment', False))}"
    )
    section("function interprocedural data route kinds", "function_interprocedural_data_route_kinds")
    section("function interprocedural data identity kinds", "function_interprocedural_data_identity_kinds")

    print("\n[Blueprint function call target audit]")
    print(
        f"calls={int(report.get('function_call_count', 0) or 0)} "
        f"internal={int(report.get('function_call_internal_count', 0) or 0)} "
        f"internal_targets={int(report.get('function_call_internal_target_count', 0) or 0)} "
        f"interface_or_declaration={int(report.get('function_call_interface_count', 0) or 0)} "
        f"pure_internal={int(report.get('function_call_pure_internal_count', 0) or 0)} "
        f"latent_internal={int(report.get('function_call_latent_internal_count', 0) or 0)} "
        f"direct_impure_internal={int(report.get('function_call_direct_impure_count', 0) or 0)} "
        f"purity_overrides={int(report.get('function_call_purity_override_count', 0) or 0)} "
        f"suspicious_purity={int(report.get('function_call_suspicious_purity_count', 0) or 0)} "
        f"unknown_target_blueprint_type={int(report.get('function_call_unknown_blueprint_type_count', 0) or 0)}"
    )
    section("function call resolution", "function_call_resolution")
    section("internal function call kinds", "function_internal_kinds")

    print("\n[Direct internal function execution evidence]")
    print(
        f"direct_impure_calls={int(report.get('function_call_direct_impure_count', 0) or 0)} "
        f"exact_caller_blocks={int(report.get('function_direct_exact_caller_block_count', 0) or 0)} "
        f"exact_entry_blocks={int(report.get('function_direct_exact_entry_block_count', 0) or 0)} "
        f"explicit_result_calls={int(report.get('function_direct_explicit_result_call_count', 0) or 0)} "
        f"result_nodes={int(report.get('function_direct_result_node_count', 0) or 0)} "
        f"exact_result_blocks={int(report.get('function_direct_exact_result_block_count', 0) or 0)} "
        f"void_calls={int(report.get('function_direct_void_call_count', 0) or 0)} "
        f"reachable_terminal_frontiers={int(report.get('function_direct_calls_with_terminal_frontier', 0) or 0)} "
        f"reachable_terminal_blocks={int(report.get('function_direct_reachable_terminal_block_count', 0) or 0)} "
        f"reachable_result_nodes={int(report.get('function_direct_reachable_result_node_count', 0) or 0)} "
        f"declared_results_off_exec_path={int(report.get('function_direct_unreachable_result_node_count', 0) or 0)} "
        f"unreachable_callsites={int(report.get('function_direct_unreachable_callsite_count', 0) or 0)} "
        f"no_return_frontier={int(report.get('function_direct_no_return_frontier_count', 0) or 0)} "
        f"connected_continuations={int(report.get('function_direct_connected_continuation_count', 0) or 0)} "
        f"terminal_calls={int(report.get('function_direct_terminal_call_count', 0) or 0)} "
        f"exact_continuation_blocks={int(report.get('function_direct_exact_continuation_block_count', 0) or 0)} "
        f"call_bindings={int(report.get('function_direct_binding_count', 0) or 0)} "
        f"bridge_ready_calls={int(report.get('function_direct_bridge_ready_count', 0) or 0)} "
        f"bridge_ready_connected={int(report.get('function_direct_bridge_ready_connected_call_count', 0) or 0)} "
        f"bridge_ready_terminal={int(report.get('function_direct_bridge_ready_terminal_call_count', 0) or 0)} "
        f"expected_enters={int(report.get('function_direct_expected_enter_edge_count', 0) or 0)} "
        f"expected_returns={int(report.get('function_direct_expected_return_edge_count', 0) or 0)} "
        f"expected_terminal_records={int(report.get('function_direct_expected_terminal_record_count', 0) or 0)}"
    )
    section("function target/block audit mismatches", "function_call_mismatches")

    print("\n[Blueprint function interprocedural execution streams]")
    print(
        f"edges={int(report.get('function_interprocedural_edge_count', 0) or 0)} "
        f"expected_enters={int(report.get('function_direct_expected_enter_edge_count', 0) or 0)} "
        f"expected_returns={int(report.get('function_direct_expected_return_edge_count', 0) or 0)} "
        f"terminals={int(report.get('function_interprocedural_terminal_count', 0) or 0)} "
        f"expected_terminals={int(report.get('function_direct_expected_terminal_record_count', 0) or 0)} "
        f"aligned={bool(report.get('function_interprocedural_stream_alignment', False))}"
    )
    section("function interprocedural edge kinds", "function_interprocedural_edge_kinds")
    section("function interprocedural terminal kinds", "function_interprocedural_terminal_kinds")

    control_rig = int(report.get("control_rig_node_count", 0) or 0)
    rigvm_links = int(report.get("rigvm_link_count", 0) or 0)
    matched = int(report.get("rigvm_matched_count", 0) or 0)
    matched_pct = (100.0 * matched / control_rig) if control_rig else 100.0
    print("\n[Control Rig -> RigVM bridge]")
    print(
        f"control_rig_nodes={control_rig} links={rigvm_links} matched={matched} "
        f"matched_coverage={matched_pct:.2f}% "
        f"unmatched_control_rig={int(report.get('rigvm_unmatched_control_rig_count', 0) or 0)} "
        f"missing_links={int(report.get('rigvm_missing_link_count', 0) or 0)} "
        f"extra_links={int(report.get('rigvm_extra_link_count', 0) or 0)} "
        f"duplicate_link_node_ids={int(report.get('rigvm_duplicate_link_node_ids', 0) or 0)}"
    )
    section("RigVM link status", "rigvm_status")
    section("RigVM link confidence", "rigvm_confidence")
    section("matched RigVM operations", "rigvm_operations")
    section("matched RigVM classes", "rigvm_classes")
    section("matched RigVM functions", "rigvm_functions")
    section("matched RigVM templates", "rigvm_templates")
    print("===================================")
