#!/usr/bin/env python3
"""Read-only coverage report for generic Blueprint semantic derivation."""
from __future__ import annotations

import collections
from pathlib import Path


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
