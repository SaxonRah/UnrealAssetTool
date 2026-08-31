#!/usr/bin/env python3
"""Compact read-only Blueprint program report over existing canonical/derived facts.

This is a retrieval/view layer, not a new schema. It intentionally contains no
Mover/GAS/SmartObject-specific logic. The goal is to make one Blueprint's
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


def _components_for(output: Path, rows, blueprint_path: str) -> list[dict]:
    """Read canonical SCS components from the owning blueprints.jsonl row.

    Components are intentionally embedded in blueprints.jsonl in the canonical
    scan. blueprint_components is a SQLite projection, not an authoritative
    standalone JSONL stream. Keep the old standalone lookup as a compatibility
    fallback for any historical/local outputs that happened to contain it.
    """
    path = output / "blueprints.jsonl"
    if path.is_file():
        for blueprint in rows(path):
            if str(blueprint.get("object_path", "") or "") != blueprint_path:
                continue
            value = blueprint.get("components", [])
            if isinstance(value, list):
                result = []
                for item in value:
                    if not isinstance(item, dict):
                        continue
                    row = dict(item)
                    row.setdefault("blueprint_path", blueprint_path)
                    result.append(row)
                return result
            break
    return _rows_for(output, rows, "blueprint_components.jsonl", blueprint_path)


def _optional_name(value) -> str:
    value = str(value or "")
    return "" if value in {"", "None"} else value


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


def _reachable_blocks(
    blocks_by_graph: dict[str, list[dict]],
    roots_by_graph: dict[str, list[dict]],
    outgoing: dict[str, list[dict]],
) -> dict[str, set[str]]:
    """Return execution blocks reachable from explicit derived graph roots.

    A graph with no roots is left without a reachability set rather than having
    every block mislabeled as dead. For rooted graphs this is an exact traversal
    of derived execution-block edges and therefore exposes disconnected/dead
    executable islands without guessing from graph layout.
    """
    result: dict[str, set[str]] = {}
    for graph_id, blocks in blocks_by_graph.items():
        graph_roots = roots_by_graph.get(graph_id, [])
        if not graph_roots:
            continue

        valid_blocks = {
            str(block.get("block_id", "") or "")
            for block in blocks
            if block.get("block_id")
        }
        pending = [
            str(root.get("block_id", "") or "")
            for root in graph_roots
            if str(root.get("block_id", "") or "") in valid_blocks
        ]
        reachable: set[str] = set()
        while pending:
            block_id = pending.pop()
            if not block_id or block_id in reachable:
                continue
            reachable.add(block_id)
            for edge in outgoing.get(block_id, []):
                target = str(edge.get("target_block_id", "") or "")
                if target in valid_blocks and target not in reachable:
                    pending.append(target)
        result[graph_id] = reachable
    return result


def _target_label(edge: dict, labels: dict[str, str]) -> str:
    return labels.get(str(edge.get("target_block_id", "") or ""), "B?")


def _edge_sort_key(edge: dict) -> tuple:
    kind = str(edge.get("control_kind", "") or "")
    if kind == "branch":
        polarity = edge.get("condition_polarity")
        return (0, 0 if polarity is True else 1, str(edge.get("target_block_id", "") or ""))
    if kind in {"switch_case", "switch_default"}:
        return (
            1,
            1 if kind == "switch_default" else 0,
            str(edge.get("case_name", "") or edge.get("source_pin_display_name", "") or edge.get("source_pin_name", "")),
            str(edge.get("target_block_id", "") or ""),
        )
    if kind == "sequence":
        index = edge.get("sequence_index")
        return (2, int(index) if index is not None else 1 << 30, str(edge.get("target_block_id", "") or ""))
    return (
        3,
        str(edge.get("source_pin_display_name", "") or edge.get("source_pin_name", "") or ""),
        str(edge.get("target_block_id", "") or ""),
    )


def _control_summary(edges: list[dict], labels: dict[str, str]) -> str:
    """Render one block's outgoing control topology without losing provenance.

    blueprint_control_edges.jsonl is a one-to-one semantic decoration of the
    authoritative execution-block edge set. When present, compact the repeated
    per-edge control metadata into one readable branch/switch/sequence clause.
    Historical outputs without control rows retain the previous pin->block view.
    """
    if not edges:
        return ""

    ordered = sorted(edges, key=_edge_sort_key)
    kinds = {str(edge.get("control_kind", "") or "") for edge in ordered}

    if kinds == {"branch"}:
        conditions = {
            str(edge.get("condition_text", "") or "")
            for edge in ordered
            if edge.get("condition_text")
        }
        condition = next(iter(conditions)) if len(conditions) == 1 else ""
        branches = []
        for edge in ordered:
            polarity = edge.get("condition_polarity")
            label = "true" if polarity is True else "false" if polarity is False else "?"
            branches.append(f"{label}->{_target_label(edge, labels)}")
        prefix = f"if {_short(condition, 180)}: " if condition else "branch: "
        return prefix + ", ".join(branches)

    if kinds and kinds <= {"switch_case", "switch_default"}:
        selectors = {
            str(edge.get("selector_text", "") or "")
            for edge in ordered
            if edge.get("selector_text")
        }
        selector = next(iter(selectors)) if len(selectors) == 1 else ""
        cases = []
        for edge in ordered:
            if str(edge.get("control_kind", "") or "") == "switch_default":
                case = "default"
            else:
                case = str(
                    edge.get("case_name", "")
                    or edge.get("source_pin_display_name", "")
                    or edge.get("source_pin_name", "")
                    or "case"
                )
            cases.append(f"{case}->{_target_label(edge, labels)}")
        prefix = f"switch {_short(selector, 150)}: " if selector else "switch: "
        return prefix + ", ".join(cases)

    if kinds == {"sequence"}:
        outputs = []
        for edge in ordered:
            index = edge.get("sequence_index")
            token = str(index) if index is not None else "?"
            outputs.append(f"[{token}]->{_target_label(edge, labels)}")
        return "sequence: " + ", ".join(outputs)

    bits = []
    for edge in ordered:
        target = _target_label(edge, labels)
        kind = str(edge.get("control_kind", "") or "")
        if kind == "branch":
            polarity = edge.get("condition_polarity")
            label = "true" if polarity is True else "false" if polarity is False else "branch"
            bits.append(f"{label}->{target}")
        elif kind in {"switch_case", "switch_default"}:
            case = "default" if kind == "switch_default" else str(
                edge.get("case_name", "")
                or edge.get("source_pin_display_name", "")
                or edge.get("source_pin_name", "")
                or "case"
            )
            bits.append(f"{case}->{target}")
        elif kind == "sequence":
            index = edge.get("sequence_index")
            bits.append(f"[{index if index is not None else '?'}]->{target}")
        else:
            pin = str(edge.get("source_pin_display_name", "") or edge.get("source_pin_name", "") or "")
            bits.append(f"{pin or 'next'}->{target}")
    return ", ".join(bits)


def build_report(
    output: Path,
    rows,
    blueprint_path: str,
    *,
    statement_limit: int = 240,
    property_limit: int = 120,
) -> dict:
    output = Path(output).expanduser().resolve()
    blueprint_path = str(blueprint_path or "").strip()
    if not blueprint_path:
        raise RuntimeError("Blueprint path is empty")

    semantic_nodes = _rows_for(output, rows, "blueprint_semantic_nodes.jsonl", blueprint_path)
    if not semantic_nodes:
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
    control_edges = _rows_for(output, rows, "blueprint_control_edges.jsonl", blueprint_path)
    roots = _rows_for(output, rows, "blueprint_execution_roots.jsonl", blueprint_path)
    semantic_edges = _rows_for(output, rows, "blueprint_semantic_edges.jsonl", blueprint_path)
    components = _components_for(output, rows, blueprint_path)
    component_properties = _rows_for(output, rows, "blueprint_component_properties.jsonl", blueprint_path)

    # The control stream is guaranteed one-to-one with execution block edges by
    # its own derived validator. Prefer it only when present for this Blueprint;
    # otherwise preserve report compatibility with historical bundles.
    report_edges = control_edges if control_edges else block_edges

    graph_names = sorted({
        str(row.get("graph_name", "") or "")
        for row in semantic_nodes
        if row.get("graph_name")
    })

    blocks_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    for block in blocks:
        blocks_by_graph[str(block.get("graph_id", "") or "")].append(block)

    block_label: dict[str, str] = {}
    for graph_blocks in blocks_by_graph.values():
        graph_blocks.sort(key=lambda row: (
            int(row.get("block_index", 0) or 0),
            str(row.get("block_id", "") or ""),
        ))
        for index, block in enumerate(graph_blocks):
            block_label[str(block.get("block_id", "") or "")] = f"B{index}"

    roots_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    for root in roots:
        roots_by_graph[str(root.get("graph_id", "") or "")].append(root)
    for values in roots_by_graph.values():
        values.sort(key=lambda row: (
            str(row.get("root_kind", "") or ""),
            str(row.get("root_name", "") or ""),
            str(row.get("block_id", "") or ""),
            str(row.get("root_id", "") or ""),
        ))

    statements_by_block: dict[str, list[dict]] = collections.defaultdict(list)
    loose_statements: list[dict] = []
    for statement in statements:
        block_id = str(statement.get("block_id", "") or "")
        if block_id:
            statements_by_block[block_id].append(statement)
        else:
            loose_statements.append(statement)
    for values in statements_by_block.values():
        values.sort(key=lambda row: (
            int(row.get("block_position", -1) or -1),
            str(row.get("node_id", "") or ""),
        ))

    outgoing: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in report_edges:
        outgoing[str(edge.get("source_block_id", "") or "")].append(edge)

    reachable_by_graph = _reachable_blocks(blocks_by_graph, roots_by_graph, outgoing)
    unreachable_block_count = 0
    for graph_id, graph_blocks in blocks_by_graph.items():
        reachable = reachable_by_graph.get(graph_id)
        if reachable is None:
            continue
        unreachable_block_count += sum(
            1
            for block in graph_blocks
            if str(block.get("block_id", "") or "") not in reachable
        )

    endpoint_rows = [
        edge for edge in semantic_edges
        if str(edge.get("target_kind", "") or "") != "node"
    ]
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
        "root_count": len(roots),
        "control_edge_count": len(control_edges),
        "uses_control_semantics": bool(control_edges),
        "unreachable_block_count": unreachable_block_count,
        "function_count": len(functions),
        "event_count": len(events),
        "component_count": len(components),
        "component_property_count": len(component_properties),
        "functions": sorted(functions, key=lambda row: (
            str(row.get("graph_name", "") or ""),
            str(row.get("name", "") or ""),
        )),
        "events": sorted(events, key=lambda row: (
            str(row.get("graph_name", "") or ""),
            str(row.get("name", "") or ""),
        )),
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
        "roots_by_graph": roots_by_graph,
        "reachable_by_graph": reachable_by_graph,
        "statement_limit": max(0, statement_limit),
    }


def print_report(report: dict) -> None:
    print("=== BLUEPRINT PROGRAM REPORT ===")
    print(report["blueprint_path"])
    control_text = (
        f" control_edges={report.get('control_edge_count', 0)}"
        if report.get("uses_control_semantics")
        else ""
    )
    print(
        "graphs={graphs} nodes={nodes} statements={statements} blocks={blocks} roots={roots} "
        "unreachable_blocks={unreachable} functions={functions} events={events} "
        "components={components} component_overrides={overrides}{control}".format(
            graphs=len(report.get("graph_names", [])),
            nodes=report.get("semantic_node_count", 0),
            statements=report.get("statement_count", 0),
            blocks=report.get("block_count", 0),
            roots=report.get("root_count", 0),
            unreachable=report.get("unreachable_block_count", 0),
            functions=report.get("function_count", 0),
            events=report.get("event_count", 0),
            components=report.get("component_count", 0),
            overrides=report.get("component_property_count", 0),
            control=control_text,
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
        parent = _optional_name(row.get("parent_component_or_variable", ""))
        attach = _optional_name(row.get("attach_to", ""))
        if parent:
            bits.append(f"parent={parent}")
        if attach:
            bits.append(f"attach={attach}")
        if bool(row.get("is_root", False)):
            bits.append("scs_root")
        print("  " + " | ".join(bits))

    print("\n[component authored overrides]")
    properties = report.get("component_properties", [])
    if not properties:
        print("<none>")
    for row in properties:
        value = str(row.get("referenced_object_path", "") or row.get("value", "") or "")
        suffix = f"[{int(row.get('array_index', 0) or 0)}]" if int(row.get("array_index", 0) or 0) else ""
        print(f"  {row.get('component_name','')}.{row.get('property_name','')}{suffix} = {_short(value)}")
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
    roots_by_graph = report.get("roots_by_graph", {})
    reachable_by_graph = report.get("reachable_by_graph", {})
    uses_control_semantics = bool(report.get("uses_control_semantics"))
    remaining = int(report.get("statement_limit", 0) or 0)

    all_graphs = []
    for graph_id, blocks in blocks_by_graph.items():
        graph_name = str(blocks[0].get("graph_name", "") or "") if blocks else ""
        all_graphs.append((graph_name, graph_id, blocks))
    all_graphs.sort(key=lambda item: (item[0], item[1]))

    for graph_name, graph_id, blocks in all_graphs:
        print(f"\n  graph {graph_name or graph_id}")
        graph_roots = roots_by_graph.get(graph_id, [])
        reachable = reachable_by_graph.get(graph_id)
        if graph_roots:
            root_bits = []
            for root in graph_roots:
                target = labels.get(str(root.get("block_id", "") or ""), "B?")
                kind = str(root.get("root_kind", "") or "root")
                name = str(root.get("root_name", "") or "")
                root_bits.append(f"{kind}:{name}->{target}" if name else f"{kind}->{target}")
            print("    roots: " + ", ".join(root_bits))

        ordered_blocks = sorted(blocks, key=lambda row: (
            int(row.get("block_index", 0) or 0),
            str(row.get("block_id", "") or ""),
        ))
        for block in ordered_blocks:
            block_id = str(block.get("block_id", "") or "")
            label = labels.get(block_id, "B?")
            status = " [unreachable]" if reachable is not None and block_id not in reachable else ""
            block_outgoing = outgoing.get(block_id, [])
            if uses_control_semantics:
                summary = _control_summary(block_outgoing, labels)
                edge_text = (" | " + summary) if summary else ""
            else:
                edge_bits = []
                for edge in sorted(block_outgoing, key=lambda row: (
                    str(row.get("source_pin_name", "") or ""),
                    str(row.get("target_block_id", "") or ""),
                )):
                    target = labels.get(str(edge.get("target_block_id", "") or ""), "B?")
                    pin = str(edge.get("source_pin_name", "") or "")
                    edge_bits.append(f"{pin or 'next'}->{target}")
                edge_text = (" | " + ", ".join(edge_bits)) if edge_bits else ""
            print(f"    {label}{status}{edge_text}")
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
