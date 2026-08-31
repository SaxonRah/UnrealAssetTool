#!/usr/bin/env python3
"""Decorate Blueprint execution edges with user-defined enum branch metadata."""
from __future__ import annotations

import collections
from pathlib import Path

import uatool_blueprint_enums as blueprint_enums
import uatool_blueprint_enum_inference as blueprint_enum_inference


def _decorate_execution_edges(output: Path, rows: list[dict], core_module) -> list[dict]:
    """Attach readable enum metadata while preserving the raw exec-pin name.

    UE serializes user-defined enum switch branches with names such as
    NewEnumerator1. The source switch node also owns a typed enum data pin, so
    the canonical enum table can resolve that raw token without guessing. If a
    node exposes multiple enum types that could explain the same raw token, the
    edge is deliberately left undecorated rather than choosing ambiguously.
    """
    output = Path(output)
    if not (output / "blueprint_enum_entries.jsonl").is_file():
        return rows

    lookup = blueprint_enums._entry_lookup(output)
    if not lookup:
        return rows

    enum_paths_by_node: dict[str, set[str]] = collections.defaultdict(set)
    for pin in core_module.iter_blueprint_pin_rows(output):
        node_id = str(pin.get("node_id", "") or "")
        enum_path = blueprint_enums._pin_enum_path(pin)
        if node_id and enum_path:
            enum_paths_by_node[node_id].add(enum_path)

    for row in rows:
        source_node_id = str(row.get("source_node_id", "") or "")
        raw_name = str(row.get("source_pin_name", "") or "")
        if not source_node_id or not raw_name:
            continue

        matches: list[tuple[str, dict]] = []
        for enum_path in sorted(enum_paths_by_node.get(source_node_id, ())):
            entry = lookup.get((enum_path, raw_name))
            if entry is not None:
                matches.append((enum_path, entry))
        if len(matches) != 1:
            continue

        enum_path, entry = matches[0]
        row["source_pin_enum_path"] = enum_path
        row["source_pin_enum_index"] = int(entry.get("enum_index", 0) or 0)
        row["source_pin_enum_value"] = int(entry.get("numeric_value", 0) or 0)
        row["source_pin_authored_name"] = str(entry.get("authored_name", "") or raw_name)
        row["source_pin_display_name"] = str(
            entry.get("display_name", "") or entry.get("authored_name", "") or raw_name
        )
    return rows


def _decorate_report(report: dict) -> dict:
    """Use display labels in the human report without mutating derived rows."""
    outgoing = report.get("outgoing", {})
    if not isinstance(outgoing, dict):
        return report

    rendered: dict[str, list[dict]] = {}
    for block_id, edges in outgoing.items():
        rendered_edges: list[dict] = []
        for edge in edges or []:
            if not isinstance(edge, dict):
                continue
            display_name = str(edge.get("source_pin_display_name", "") or "")
            if not display_name:
                rendered_edges.append(edge)
                continue
            clone = dict(edge)
            clone["source_pin_raw_name"] = str(edge.get("source_pin_name", "") or "")
            clone["source_pin_name"] = display_name
            rendered_edges.append(clone)
        rendered[str(block_id)] = rendered_edges
    report["outgoing"] = rendered
    return report


def install(core_module) -> None:
    if getattr(core_module, "_blueprint_enum_edge_support_installed", False):
        return

    import uatool_blueprint_program_report as program_report

    # Dependency-expression rendering is part of the same readable enum layer.
    # Install conservative literal inference before any derive/report work runs.
    blueprint_enum_inference.install()

    original_execution = core_module.derive_blueprint_execution_program
    original_build_report = program_report.build_report

    def derive_execution(output, functions, events):
        blocks, edges, roots = original_execution(output, functions, events)
        return (
            blocks,
            _decorate_execution_edges(Path(output), edges, core_module),
            roots,
        )

    def build_report(*args, **kwargs):
        return _decorate_report(original_build_report(*args, **kwargs))

    core_module.derive_blueprint_execution_program = derive_execution
    program_report.build_report = build_report
    core_module._blueprint_enum_edge_support_installed = True
