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
    print("===================================")
