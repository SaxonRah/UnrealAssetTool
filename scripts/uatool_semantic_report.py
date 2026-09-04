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

    def pin_type_key(pin: dict) -> str:
        pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
        signature = {
            "category": str(pin_type.get("category", "") or ""),
            "subcategory": str(pin_type.get("subcategory", "") or ""),
            "subcategory_object": str(pin_type.get("subcategory_object", "") or ""),
            "container_type": int(pin_type.get("container_type", 0) or 0),
            "is_reference": bool(pin_type.get("is_reference", False)),
            "is_const": bool(pin_type.get("is_const", False)),
        }
        return json.dumps(signature, sort_keys=True, separators=(",", ":"))

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
    interprocedural_edges = (
        list(rows(interprocedural_edge_path)) if interprocedural_edge_path.is_file() else []
    )
    interprocedural_terminals = (
        list(rows(interprocedural_terminal_path)) if interprocedural_terminal_path.is_file() else []
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

    print("\n[Blueprint interprocedural execution streams]")
    print(
        f"edges={int(report.get('interprocedural_execution_edge_count', 0) or 0)} "
        f"expected_edges={int(report.get('interprocedural_expected_edge_count', 0) or 0)} "
        f"terminals={int(report.get('interprocedural_execution_terminal_count', 0) or 0)} "
        f"aligned={bool(report.get('interprocedural_stream_alignment', False))}"
    )
    section("interprocedural execution edge kinds", "interprocedural_execution_edge_kinds")
    section("interprocedural execution terminal kinds", "interprocedural_execution_terminal_kinds")

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
