#!/usr/bin/env python3
"""Compact read-only Blueprint program report over existing canonical/derived facts.

This is a retrieval/view layer, not a new schema.  It intentionally contains no
Mover/GAS/SmartObject-specific logic.  The goal is to make one Blueprint's
program readable enough for human/AI inspection while retaining exact source
identities in the underlying JSONL.
"""
from __future__ import annotations

import collections
from pathlib import Path


def _rows_for(output: Path, rows, filename: str, blueprint_path: str) -> list[dict]:
    path = output / filename
    if not path.is_file():
        return []
    return [
        row for row in rows(path)
        if str(row.get("blueprint_path", "") or "") == blueprint_path
    ]


def _short(value: str, max_chars: int = 180) -> str:
    value = " ".join(str(value or "").split())
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "…"


def _param_names(value) -> str:
    if not isinstance(value, list):
        return ""
    names = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "") or "")
        if name:
            names.append(name)
    return ", ".join(names)


def build_report(output: Path, rows, blueprint_path: str, *, statement_limit: int = 240, property_limit: int = 120) -> dict:
    output = Path(output).expanduser().resolve()
    blueprint_path = str(blueprint_path or "").strip()
    if not blueprint_path:
        raise RuntimeError("Blueprint path is empty")

    semantic_nodes = _rows_for(output, rows, "blueprint_semantic_nodes.jsonl", blueprint_path)
    if not semantic_nodes:
        # Give a useful exact-match diagnostic without loading a database.
        candidates = []
        needle = blueprint_path.lower()
        path = output / "blueprint_semantic_nodes.jsonl"
        if path.is_file():
            seen = set()
            for row in rows(path):
                candidate = str(row.get("blueprint_path", "") or "")
                if candidate and needle in candidate.lower() and candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
                    if len(candidates) >= 12:
                        break
        suffix = ""
        if candidates:
            suffix = "\nCandidates:\n" + "\n".join(f"  {item}" for item in candidates)
        raise RuntimeError(f"Blueprint not found in semantic nodes: {blueprint_path}{suffix}")

    functions = _rows_for(output, rows, "blueprint_functions.jsonl", blueprint_path)
    events = _rows_for(output, rows, "blueprint_events.jsonl", blueprint_path)
    statements = _rows_for(output, rows, "blueprint_semantic_statements.jsonl", blueprint_path)
    blocks = _rows_for(output, rows, "blueprint_semantic_blocks.jsonl", blueprint_path)
    block_edges = _rows_for(output, rows, "blueprint_execution_block_edges.jsonl", blueprint_path)
    roots = _rows_for(output, rows, "blueprint_execution_roots.jsonl", blueprint_path)
    semantic_edges = _rows_for(output, rows, "blueprint_semantic_edges.jsonl", blueprint_path)
    components = _rows_for(output, rows, "blueprint_components.jsonl", blueprint_path)
    component_properties = _rows_for(output, rows, "blueprint_component_properties.jsonl", blueprint_path)

    graph_names = sorted({str(row.get("graph_name", "") or "") for row in semantic_nodes if row.get("graph_name")})

    # Build stable short labels per graph so the report does not read like GUID soup.
    blocks_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    for block in blocks:
        blocks_by_graph[str(block.get("graph_id", "") or "")].append(block)
    block_label: dict[str, str] = {}
    for graph_id, graph_blocks in blocks_by_graph.items():
        graph_blocks.sort(key=lambda row: (int(row.get("block_index", 0) or 0), str(row.get("block_id", "") or "")))
        for index, block in enumerate(graph_blocks):
            block_label[str(block.get("block_id", "") or "")] = f"B{index}"

    statements_by_block: dict[str, list[dict]] = collections.defaultdict(list)
    loose_statements: list[dict] = []
    for statement in statements:
        block_id = str(statement.get("block_id", "") or "")
        if block_id:
            statements_by_block[block_id].append(statement)
        else:
            loose_statements.append(statement)
    for values in statements_by_block.values():
        values.sort(key=lambda row: (int(row.get("block_position", -1) or -1), str(row.get("node_id", "") or "")))

    outgoing: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in block_edges:
        outgoing[str(edge.get("source_block_id", "") or "")].append(edge)

    # Unique non-node semantic endpoints are the best compact read/write/call inventory.
    endpoint_rows = [edge for edge in semantic_edges if str(edge.get("target_kind", "") or "") != "node"]
    endpoint_groups: dict[str, list[str]] = collections.defaultdict(list)
    endpoint_seen: dict[str, set[str]] = collections.defaultdict(set)
    for edge in endpoint_rows:
        relation = str(edge.get("relation", "") or "")
        target = str(edge.get("target", "") or "")
        if relation and target and target not in endpoint_seen[relation]:
            endpoint_seen[relation].add(target)
            endpoint_groups[relation].append(target)
    for values in endpoint_groups.values():
        values.sort()

    # Component properties are already authored-delta records, so they are useful
    # without dumping the entire reflected component object.
    component_properties.sort(key=lambda row: (
        str(row.get("component_name", "") or ""),
        str(row.get("property_name", "") or ""),
        int(row.get("array_index", 0) or 0),
    ))

    return {
        "blueprint_path": blueprint_path,
        "graph_names": graph_names,
        "semantic_node_count": len(semantic_nodes),
        "statement_count": len(statements),
        "block_count": len(blocks),
        "function_count": len(functions),
        "event_count": len(events),
        "component_count": len(components),
        "component_property_count": len(component_properties),
        "functions": sorted(functions, key=lambda row: (str(row.get("graph_name", "") or ""), str(row.get("name", "") or ""))),
        "events": sorted(events, key=lambda row: (str(row.get("graph_name", "") or ""), str(row.get("name", "") or ""))),
        "components": sorted(components, key=lambda row: str(row.get("variable_name", "") or "")),
        "component_properties": component_properties[: max(0, property_limit)],
        "component_properties_truncated": len(component_properties) > max(0, property_limit),
        "endpoint_groups": dict(sorted(endpoint_groups.items())),
        "blocks_by_graph": blocks_by_graph,
        "block_label": block_label,
        "statements_by_block": statements_by_block,
        "loose_statements": loose_statements,
        "outgoing": outgoing,
        "roots": roots,
        "statement_limit": max(0, statement_limit),
    }


def print_report(report: dict) -> None:
    print("=== BLUEPRINT PROGRAM REPORT ===")
    print(report["blueprint_path"])
    print(
        "graphs={graphs} nodes={nodes} statements={statements} blocks={blocks} "
        "functions={functions} events={events} components={components} component_overrides={overrides}".format(
            graphs=len(report.get("graph_names", [])),
            nodes=report.get("semantic_node_count", 0),
            statements=report.get("statement_count", 0),
            blocks=report.get("block_count", 0),
            functions=report.get("function_count", 0),
            events=report.get("event_count", 0),
            components=report.get("component_count", 0),
            overrides=report.get("component_property_count", 0),
        )
    )

    print("\n[components]")
    components = report.get("components", [])
    if not components:
        print("<none>")
    for row in components:
        bits = [
            str(row.get("variable_name", "") or "<unnamed>"),
            str(row.get("component_class", "") or "<unknown class>"),
        ]
        parent = str(row.get("parent_component_or_variable", "") or "")
        attach = str(row.get("attach_to", "") or "")
        if parent:
            bits.append(f"parent={parent}")
        if attach:
            bits.append(f"attach={attach}")
        if bool(row.get("is_root", False)):
            bits.append("root")
        print("  " + " | ".join(bits))

    print("\n[component authored overrides]")
    properties = report.get("component_properties", [])
    if not properties:
        print("<none>")
    for row in properties:
        value = str(row.get("referenced_object_path", "") or row.get("value", "") or "")
        suffix = f"[{int(row.get('array_index', 0) or 0)}]" if int(row.get("array_index", 0) or 0) else ""
        print(
            f"  {row.get('component_name','')}.{row.get('property_name','')}{suffix} = {_short(value)}"
        )
    if report.get("component_properties_truncated"):
        print("  … component override output truncated by --property-limit")

    print("\n[events]")
    events = report.get("events", [])
    if not events:
        print("<none>")
    for row in events:
        params = _param_names(row.get("parameters", []))
        extra = []
        if row.get("component_name"):
            extra.append(f"component={row.get('component_name')}")
        if row.get("input_name"):
            extra.append(f"input={row.get('input_name')}")
        tail = (" | " + " | ".join(extra)) if extra else ""
        print(f"  {row.get('graph_name','')} :: {row.get('name','')}({params}) [{row.get('event_kind','')}]" + tail)

    print("\n[functions]")
    functions = report.get("functions", [])
    if not functions:
        print("<none>")
    for row in functions:
        inputs = _param_names(row.get("inputs", []))
        outputs = _param_names(row.get("outputs", []))
        flags = []
        if row.get("blueprint_pure"):
            flags.append("pure")
        if row.get("const_function"):
            flags.append("const")
        if row.get("static_function"):
            flags.append("static")
        flag_text = f" [{' '.join(flags)}]" if flags else ""
        out_text = f" -> ({outputs})" if outputs else ""
        print(f"  {row.get('graph_name','')} :: {row.get('name','')}({inputs}){out_text}{flag_text}")

    print("\n[semantic endpoints]")
    groups = report.get("endpoint_groups", {})
    if not groups:
        print("<none>")
    priority = [
        "reads", "writes", "calls", "receives_event", "receives_input",
        "reads_input", "spawns", "casts_to", "invokes_macro",
        "binds_delegate", "calls_delegate", "maps_to_rigvm_node",
        "invokes_rigvm_function", "uses_rigvm_template", "uses_rigvm_class",
    ]
    ordered = [key for key in priority if key in groups] + [key for key in groups if key not in priority]
    for relation in ordered:
        values = groups[relation]
        print(f"  {relation} ({len(values)}):")
        for target in values[:80]:
            print(f"    {_short(target, 220)}")
        if len(values) > 80:
            print(f"    … {len(values) - 80} more")

    print("\n[execution program]")
    blocks_by_graph = report.get("blocks_by_graph", {})
    labels = report.get("block_label", {})
    statements_by_block = report.get("statements_by_block", {})
    outgoing = report.get("outgoing", {})
    remaining = int(report.get("statement_limit", 0) or 0)

    all_graphs = []
    for graph_id, blocks in blocks_by_graph.items():
        graph_name = str(blocks[0].get("graph_name", "") or "") if blocks else ""
        all_graphs.append((graph_name, graph_id, blocks))
    all_graphs.sort(key=lambda item: (item[0], item[1]))

    for graph_name, graph_id, blocks in all_graphs:
        print(f"\n  graph {graph_name or graph_id}")
        ordered_blocks = sorted(blocks, key=lambda row: (int(row.get("block_index", 0) or 0), str(row.get("block_id", "") or "")))
        for block in ordered_blocks:
            block_id = str(block.get("block_id", "") or "")
            label = labels.get(block_id, "B?")
            edge_bits = []
            for edge in sorted(outgoing.get(block_id, []), key=lambda row: (str(row.get("source_pin_name", "") or ""), str(row.get("target_block_id", "") or ""))):
                target = labels.get(str(edge.get("target_block_id", "") or ""), "B?")
                pin = str(edge.get("source_pin_name", "") or "")
                edge_bits.append(f"{pin or 'next'}->{target}")
            edge_text = (" | " + ", ".join(edge_bits)) if edge_bits else ""
            print(f"    {label}{edge_text}")
            for statement in statements_by_block.get(block_id, []):
                if remaining <= 0:
                    print("      … statement output truncated by --statement-limit")
                    break
                print(f"      {_short(str(statement.get('text','') or ''), 320)}")
                remaining -= 1
            if remaining <= 0:
                break
        if remaining <= 0:
            break

    loose = report.get("loose_statements", [])
    if loose and remaining > 0:
        print("\n  statements outside execution blocks")
        for statement in loose:
            if remaining <= 0:
                print("    … statement output truncated by --statement-limit")
                break
            print(f"    {statement.get('graph_name','')} :: {_short(str(statement.get('text','') or ''), 320)}")
            remaining -= 1

    print("================================")
