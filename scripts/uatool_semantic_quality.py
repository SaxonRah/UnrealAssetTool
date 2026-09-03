#!/usr/bin/env python3
"""Read-only Blueprint semantic-quality diagnostics for real-corpus acceptance.

This module does not add a schema and does not reinterpret gameplay domains. It
uses the existing generic Blueprint semantic/statement/control streams to:

* rank exact Blueprint paths by authored semantic complexity so representative
  quality cases can be chosen without asset-name guessing;
* audit one exact Blueprint for structural/provenance invariants; and
* print bounded high-signal statements/control clauses for human semantic-
  coherence review.

Runtime execution is never simulated or inferred.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
from pathlib import Path
import sys

BOUNDARY_OPERATIONS = {
    "function_entry",
    "function_result",
    "event",
    "custom_event",
    "anim_graph_root",
    "anim_state_result",
    "anim_transition_result",
}
HIGH_SIGNAL_OPERATIONS = {
    "branch",
    "switch",
    "execution_sequence",
    "function_call",
    "variable_set",
    "spawn_actor",
    "dynamic_cast",
    "set_fields_in_struct",
    "macro_instance",
    "event",
    "custom_event",
    "enhanced_input_event",
    "input_key",
    "input_debug_key",
    "delegate_bind",
    "delegate_assign",
    "timeline",
}
CALL_OPERATIONS = {"function_call"}
WRITE_OPERATIONS = {"variable_set", "set_fields_in_struct"}
CONTROL_OPERATIONS = {"branch", "switch", "execution_sequence"}


def _meaningful(value: object) -> str:
    text = str(value or "").strip()
    return "" if text in {"", "None", "none", "NULL", "null"} else text


def _iter_rows(rows, path: Path):
    if not path.is_file():
        return
    for row in rows(path):
        if isinstance(row, dict):
            yield row


def _rows_for(output: Path, rows, filename: str, blueprint_path: str) -> list[dict]:
    return [
        row for row in _iter_rows(rows, output / filename)
        if str(row.get("blueprint_path", "") or "") == blueprint_path
    ]


def _blueprint_rows(output: Path, rows) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for row in _iter_rows(rows, output / "blueprints.jsonl"):
        path = _meaningful(row.get("object_path"))
        if path:
            result[path] = row
    return result


def _component_classes(blueprint: dict) -> list[str]:
    values = blueprint.get("components", []) if isinstance(blueprint.get("components", []), list) else []
    return sorted({
        _meaningful(item.get("component_class"))
        for item in values if isinstance(item, dict) and _meaningful(item.get("component_class"))
    })


def _aggregate(output: Path, rows) -> dict[str, dict]:
    output = Path(output).expanduser().resolve()
    blueprints = _blueprint_rows(output, rows)
    data: dict[str, dict] = {}

    def rec(path: str) -> dict:
        if path not in data:
            bp = blueprints.get(path, {})
            data[path] = {
                "blueprint_path": path,
                "parent_class": _meaningful(bp.get("parent_class")),
                "generated_class": _meaningful(bp.get("generated_class")),
                "component_classes": _component_classes(bp),
                "node_count": 0,
                "modeled_node_count": 0,
                "fallback_node_count": 0,
                "opaque_node_count": 0,
                "exec_node_count": 0,
                "statement_count": 0,
                "dependency_statement_count": 0,
                "literal_statement_count": 0,
                "call_count": 0,
                "write_count": 0,
                "branch_count": 0,
                "switch_count": 0,
                "sequence_count": 0,
                "control_edge_count": 0,
                "event_count": 0,
                "function_count": 0,
                "delegate_relation_count": 0,
                "operation_counts": collections.Counter(),
            }
        return data[path]

    for row in _iter_rows(rows, output / "blueprint_semantic_nodes.jsonl"):
        path = _meaningful(row.get("blueprint_path"))
        if not path:
            continue
        item = rec(path)
        item["node_count"] += 1
        if bool(row.get("opaque", False)):
            item["opaque_node_count"] += 1
        elif str(row.get("semantic_kind", "") or "") == "classified":
            item["fallback_node_count"] += 1
        else:
            item["modeled_node_count"] += 1
        if bool(row.get("has_exec_flow", False)):
            item["exec_node_count"] += 1
        op = str(row.get("operation", "") or "")
        if op:
            item["operation_counts"][op] += 1

    for row in _iter_rows(rows, output / "blueprint_semantic_statements.jsonl"):
        path = _meaningful(row.get("blueprint_path"))
        if not path:
            continue
        item = rec(path)
        item["statement_count"] += 1
        if int(row.get("dependency_count", 0) or 0) > 0:
            item["dependency_statement_count"] += 1
        if int(row.get("literal_count", 0) or 0) > 0:
            item["literal_statement_count"] += 1
        op = str(row.get("operation", "") or "")
        if op in CALL_OPERATIONS:
            item["call_count"] += 1
        if op in WRITE_OPERATIONS:
            item["write_count"] += 1
        if op == "branch":
            item["branch_count"] += 1
        elif op == "switch":
            item["switch_count"] += 1
        elif op == "execution_sequence":
            item["sequence_count"] += 1

    for row in _iter_rows(rows, output / "blueprint_control_edges.jsonl"):
        path = _meaningful(row.get("blueprint_path"))
        if path:
            rec(path)["control_edge_count"] += 1

    for row in _iter_rows(rows, output / "blueprint_events.jsonl"):
        path = _meaningful(row.get("blueprint_path"))
        if path:
            rec(path)["event_count"] += 1

    for row in _iter_rows(rows, output / "blueprint_functions.jsonl"):
        path = _meaningful(row.get("blueprint_path"))
        if path:
            rec(path)["function_count"] += 1

    delegate_relations = {"binds_delegate", "calls_delegate", "adds_delegate", "removes_delegate"}
    for row in _iter_rows(rows, output / "blueprint_semantic_edges.jsonl"):
        path = _meaningful(row.get("blueprint_path"))
        relation = str(row.get("relation", "") or "")
        if path and relation in delegate_relations:
            rec(path)["delegate_relation_count"] += 1

    for path, bp in blueprints.items():
        if path in data:
            item = data[path]
            item["parent_class"] = _meaningful(bp.get("parent_class"))
            item["generated_class"] = _meaningful(bp.get("generated_class"))
            item["component_classes"] = _component_classes(bp)

    for item in data.values():
        item["operation_counts"] = dict(sorted(item["operation_counts"].items()))
        # The score is discovery-only. It intentionally rewards authored control,
        # data dependencies and side-effectful statements without assigning a
        # gameplay-domain interpretation.
        item["quality_candidate_score"] = (
            int(item["statement_count"])
            + 2 * int(item["dependency_statement_count"])
            + int(item["literal_statement_count"])
            + 2 * int(item["call_count"])
            + 2 * int(item["write_count"])
            + 3 * int(item["branch_count"])
            + 3 * int(item["switch_count"])
            + 2 * int(item["sequence_count"])
            + int(item["control_edge_count"])
            + int(item["event_count"])
            + int(item["function_count"])
            + 3 * int(item["delegate_relation_count"])
        )
    return data


def candidate_report(output: Path, rows, *, limit: int = 30, contains: str = "") -> dict:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    output = Path(output).expanduser().resolve()
    data = _aggregate(output, rows)
    needle = str(contains or "").lower()
    candidates = [
        item for item in data.values()
        if int(item.get("statement_count", 0) or 0) > 0
        and (not needle or needle in str(item.get("blueprint_path", "")).lower())
    ]
    candidates.sort(key=lambda item: (
        -int(item.get("quality_candidate_score", 0) or 0),
        -int(item.get("statement_count", 0) or 0),
        str(item.get("blueprint_path", "")),
    ))
    return {
        "output": str(output),
        "diagnostic_only": True,
        "schema_promotion": False,
        "runtime_state_captured": False,
        "candidate_count": len(candidates),
        "candidates": candidates[:limit],
    }


def _node_should_have_statement(node: dict) -> bool:
    return bool(node.get("has_exec_flow", False)) or str(node.get("operation", "") or "") in BOUNDARY_OPERATIONS


def _control_endpoint_key(row: dict) -> tuple[str, ...]:
    return (
        str(row.get("source_block_id", "") or ""),
        str(row.get("target_block_id", "") or ""),
        str(row.get("source_node_id", "") or ""),
        str(row.get("target_node_id", "") or ""),
        str(row.get("source_pin_name", "") or ""),
        str(row.get("target_pin_name", "") or ""),
    )


def quality_case(output: Path, rows, blueprint_path: str, *, example_limit: int = 40) -> dict:
    if example_limit < 1:
        raise ValueError("example_limit must be >= 1")
    output = Path(output).expanduser().resolve()
    blueprint_path = _meaningful(blueprint_path)
    if not blueprint_path:
        raise ValueError("blueprint_path is empty")

    blueprints = _blueprint_rows(output, rows)
    if blueprint_path not in blueprints:
        raise RuntimeError(f"Blueprint not found in blueprints.jsonl: {blueprint_path}")

    nodes = _rows_for(output, rows, "blueprint_semantic_nodes.jsonl", blueprint_path)
    statements = _rows_for(output, rows, "blueprint_semantic_statements.jsonl", blueprint_path)
    blocks = _rows_for(output, rows, "blueprint_semantic_blocks.jsonl", blueprint_path)
    control_edges = _rows_for(output, rows, "blueprint_control_edges.jsonl", blueprint_path)
    block_edges = _rows_for(output, rows, "blueprint_execution_block_edges.jsonl", blueprint_path)
    dependencies = _rows_for(output, rows, "blueprint_data_dependencies.jsonl", blueprint_path)
    semantic_edges = _rows_for(output, rows, "blueprint_semantic_edges.jsonl", blueprint_path)
    events = _rows_for(output, rows, "blueprint_events.jsonl", blueprint_path)
    functions = _rows_for(output, rows, "blueprint_functions.jsonl", blueprint_path)

    if not nodes:
        raise RuntimeError(f"Blueprint has no semantic nodes in current derive: {blueprint_path}")

    node_by_id = {
        str(row.get("node_id", "") or ""): row
        for row in nodes if row.get("node_id")
    }
    statement_by_node = {
        str(row.get("node_id", "") or ""): row
        for row in statements if row.get("node_id")
    }
    block_ids = {str(row.get("block_id", "") or "") for row in blocks if row.get("block_id")}

    expected_statement_nodes = {
        node_id for node_id, node in node_by_id.items()
        if _node_should_have_statement(node)
    }
    actual_statement_nodes = set(statement_by_node)
    missing_statement_nodes = sorted(expected_statement_nodes - actual_statement_nodes)
    orphan_statement_nodes = sorted(actual_statement_nodes - set(node_by_id))

    fallback_nodes = [
        row for row in nodes
        if not bool(row.get("opaque", False))
        and str(row.get("semantic_kind", "") or "") == "classified"
    ]
    opaque_nodes = [row for row in nodes if bool(row.get("opaque", False))]

    missing_control_blocks = []
    for row in control_edges:
        source = str(row.get("source_block_id", "") or "")
        target = str(row.get("target_block_id", "") or "")
        if source not in block_ids or target not in block_ids:
            missing_control_blocks.append({"source": source, "target": target})

    # blueprint_control_edges is a one-to-one semantic decoration of the
    # authoritative execution-block edge set. Cardinality alone is insufficient:
    # schema 2 also requires exact source/target node+exec-pin endpoint identity.
    control_cardinality_mismatch = bool(control_edges) and len(control_edges) != len(block_edges)
    control_identity_mismatch = bool(control_edges) and (
        {_control_endpoint_key(row) for row in control_edges}
        != {_control_endpoint_key(row) for row in block_edges}
    )

    missing_call_identity = []
    missing_write_identity = []
    dependency_render_gaps = []
    for row in statements:
        node_id = str(row.get("node_id", "") or "")
        op = str(row.get("operation", "") or "")
        if op in CALL_OPERATIONS and not (_meaningful(row.get("symbol")) or _meaningful(row.get("target"))):
            missing_call_identity.append(node_id)
        if op in WRITE_OPERATIONS and not (_meaningful(row.get("symbol")) or _meaningful(row.get("target"))):
            missing_write_identity.append(node_id)
        dep_count = int(row.get("dependency_count", 0) or 0)
        if dep_count > 0:
            inputs = row.get("inputs", []) if isinstance(row.get("inputs", []), list) else []
            rendered = [
                item for item in inputs
                if isinstance(item, dict)
                and str(item.get("source_kind", "") or "") == "dependency"
                and _meaningful(item.get("expression_text"))
            ]
            if len(rendered) < dep_count:
                dependency_render_gaps.append(node_id)

    missing_branch_conditions = []
    missing_switch_selectors = []
    for row in control_edges:
        kind = str(row.get("control_kind", "") or "")
        if kind == "branch" and not _meaningful(row.get("condition_text")):
            missing_branch_conditions.append(str(row.get("source_block_id", "") or ""))
        if kind in {"switch_case", "switch_default"} and not _meaningful(row.get("selector_text")):
            missing_switch_selectors.append(str(row.get("source_block_id", "") or ""))

    defect_counts = {
        "fallback_nodes": len(fallback_nodes),
        "opaque_nodes": len(opaque_nodes),
        "missing_statement_nodes": len(missing_statement_nodes),
        "orphan_statement_nodes": len(orphan_statement_nodes),
        "missing_control_blocks": len(missing_control_blocks),
        "control_cardinality_mismatch": int(control_cardinality_mismatch),
        "control_identity_mismatch": int(control_identity_mismatch),
        "missing_call_identity": len(missing_call_identity),
        "missing_write_identity": len(missing_write_identity),
        "dependency_render_gaps": len(dependency_render_gaps),
    }
    structural_quality_ok = not any(defect_counts.values())

    operation_counts = collections.Counter(str(row.get("operation", "") or "") for row in statements)
    relation_counts = collections.Counter(str(row.get("relation", "") or "") for row in semantic_edges)
    endpoint_relations = collections.Counter(
        str(row.get("relation", "") or "")
        for row in semantic_edges
        if str(row.get("target_kind", "") or "") != "node"
    )

    high_signal = [
        row for row in statements
        if str(row.get("operation", "") or "") in HIGH_SIGNAL_OPERATIONS
        or int(row.get("dependency_count", 0) or 0) > 0
    ]
    high_signal.sort(key=lambda row: (
        str(row.get("graph_name", "") or ""),
        str(row.get("block_id", "") or ""),
        int(row.get("block_position", -1) or -1),
        str(row.get("node_id", "") or ""),
    ))

    controls = sorted(control_edges, key=lambda row: (
        str(row.get("graph_name", "") or ""),
        str(row.get("source_block_id", "") or ""),
        str(row.get("control_kind", "") or ""),
        str(row.get("case_name", "") or row.get("source_pin_name", "") or ""),
        str(row.get("target_block_id", "") or ""),
        str(row.get("target_pin_name", "") or ""),
    ))

    aggregate = _aggregate(output, rows).get(blueprint_path, {})
    bp = blueprints[blueprint_path]
    return {
        "output": str(output),
        "blueprint_path": blueprint_path,
        "parent_class": _meaningful(bp.get("parent_class")),
        "generated_class": _meaningful(bp.get("generated_class")),
        "component_classes": _component_classes(bp),
        "diagnostic_only": True,
        "schema_promotion": False,
        "runtime_state_captured": False,
        "human_semantic_review_required": True,
        "structural_quality_ok": bool(structural_quality_ok),
        "defect_counts": defect_counts,
        "counts": {
            "semantic_nodes": len(nodes),
            "semantic_statements": len(statements),
            "semantic_blocks": len(blocks),
            "control_edges": len(control_edges),
            "execution_block_edges": len(block_edges),
            "data_dependencies": len(dependencies),
            "semantic_edges": len(semantic_edges),
            "events": len(events),
            "functions": len(functions),
            "dependency_statements": sum(int(int(row.get("dependency_count", 0) or 0) > 0) for row in statements),
            "literal_statements": sum(int(int(row.get("literal_count", 0) or 0) > 0) for row in statements),
        },
        "candidate_score": int(aggregate.get("quality_candidate_score", 0) or 0),
        "operation_counts": dict(sorted(operation_counts.items())),
        "relation_counts": dict(sorted(relation_counts.items())),
        "endpoint_relation_counts": dict(sorted(endpoint_relations.items())),
        "missing_statement_nodes": missing_statement_nodes[:example_limit],
        "orphan_statement_nodes": orphan_statement_nodes[:example_limit],
        "missing_call_identity": missing_call_identity[:example_limit],
        "missing_write_identity": missing_write_identity[:example_limit],
        "dependency_render_gaps": dependency_render_gaps[:example_limit],
        "missing_branch_conditions": sorted(set(missing_branch_conditions))[:example_limit],
        "missing_switch_selectors": sorted(set(missing_switch_selectors))[:example_limit],
        "high_signal_statements": high_signal[:example_limit],
        "control_examples": controls[:example_limit],
    }


def _short(value: object, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def render_candidates(report: dict) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print("=== BLUEPRINT SEMANTIC QUALITY CANDIDATES ===")
        print(report["output"])
        print("diagnostic_only=True")
        print("schema_promotion=False")
        print("runtime_state_captured=False")
        print(f"candidate_count={report['candidate_count']}")
        print()
        for index, item in enumerate(report.get("candidates", []), 1):
            top_ops = sorted(
                item.get("operation_counts", {}).items(),
                key=lambda pair: (-int(pair[1]), str(pair[0])),
            )[:8]
            print(
                f"[{index:02d}] score={item.get('quality_candidate_score',0)} "
                f"statements={item.get('statement_count',0)} deps={item.get('dependency_statement_count',0)} "
                f"control={item.get('control_edge_count',0)} calls={item.get('call_count',0)} "
                f"writes={item.get('write_count',0)} branches={item.get('branch_count',0)} "
                f"switches={item.get('switch_count',0)} delegates={item.get('delegate_relation_count',0)}"
            )
            print("  " + item.get("blueprint_path", ""))
            if item.get("parent_class"):
                print("  parent=" + item["parent_class"])
            if item.get("component_classes"):
                print("  components=" + ", ".join(item["component_classes"][:12]))
            if top_ops:
                print("  operations=" + ", ".join(f"{name}:{count}" for name, count in top_ops))
        print("=============================================")
    return buffer.getvalue()


def render_case(report: dict) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print("=== BLUEPRINT SEMANTIC QUALITY CASE ===")
        print(report["blueprint_path"])
        print(f"parent={report.get('parent_class','')}")
        print(f"generated={report.get('generated_class','')}")
        if report.get("component_classes"):
            print("components=" + ", ".join(report["component_classes"]))
        print("diagnostic_only=True")
        print("schema_promotion=False")
        print("runtime_state_captured=False")
        print("human_semantic_review_required=True")
        print(f"structural_quality_ok={report['structural_quality_ok']}")
        print("counts: " + " ".join(f"{k}={v}" for k, v in report["counts"].items()))
        print("defects: " + " ".join(f"{k}={v}" for k, v in report["defect_counts"].items()))

        print("\n[operation counts]")
        for name, count in report.get("operation_counts", {}).items():
            if count:
                print(f"  {count:5d} {name}")

        print("\n[endpoint relation counts]")
        values = report.get("endpoint_relation_counts", {})
        if not values:
            print("  <none>")
        for name, count in values.items():
            if name:
                print(f"  {count:5d} {name}")

        print("\n[high-signal statements]")
        statements = report.get("high_signal_statements", [])
        if not statements:
            print("  <none>")
        for row in statements:
            print(
                f"  {row.get('graph_name','')} block={row.get('block_id','')} pos={row.get('block_position',-1)} "
                f"op={row.get('operation','')} deps={row.get('dependency_count',0)} literals={row.get('literal_count',0)}"
            )
            print("    " + _short(row.get("text", ""), 360))

        print("\n[control examples]")
        controls = report.get("control_examples", [])
        if not controls:
            print("  <none>")
        for row in controls:
            kind = str(row.get("control_kind", "") or "")
            detail = ""
            if kind == "branch":
                detail = f" condition={_short(row.get('condition_text',''),180)} polarity={row.get('condition_polarity')}"
            elif kind in {"switch_case", "switch_default"}:
                detail = (
                    f" selector={_short(row.get('selector_text',''),160)} "
                    f"case={row.get('case_name','') or ('default' if kind == 'switch_default' else '')}"
                )
            elif kind == "sequence":
                detail = f" index={row.get('sequence_index')}"
            target_pin = _meaningful(row.get("target_pin_name"))
            target = str(row.get("target_block_id", "") or "")
            if target_pin:
                target += f".{target_pin}"
            source_pin = _meaningful(row.get("source_pin_display_name") or row.get("source_pin_name"))
            if source_pin and kind == "flow":
                detail += f" source_pin={source_pin}"
            print(
                f"  {row.get('graph_name','')} {row.get('source_block_id','')} -> {target} "
                f"[{kind}]{detail}"
            )

        print("\n[review rule]")
        print("  Structural quality is machine-checkable. Semantic coherence is accepted only after the displayed")
        print("  statements/control are reviewed against authored Blueprint intent; this report never claims runtime execution.")
        print("=======================================")
    return buffer.getvalue()


def _write_report(path_value: str | None, text: str) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote Blueprint semantic-quality report: {path}")


def _candidates_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool semantic-quality-candidates",
        description="rank exact Blueprint paths for semantic-quality review from an existing derived corpus",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--contains", default="", help="optional case-insensitive Blueprint path substring filter")
    parser.add_argument("--report", help="optional UTF-8 report path")
    args = parser.parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    if not output.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {output}")
    report = candidate_report(output, runtime_module._rows, limit=args.limit, contains=args.contains)
    text = render_candidates(report)
    _write_report(args.report, text)
    print(text, end="")
    return 0


def _case_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool semantic-quality-case",
        description="audit and render one exact Blueprint semantic-quality case from an existing derive",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("blueprint_path", help="exact Blueprint asset path")
    parser.add_argument("--example-limit", type=int, default=40)
    parser.add_argument("--report", help="optional UTF-8 report path")
    args = parser.parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    if not output.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {output}")
    report = quality_case(output, runtime_module._rows, args.blueprint_path, example_limit=args.example_limit)
    text = render_case(report)
    _write_report(args.report, text)
    print(text, end="")
    return 0 if report["structural_quality_ok"] else 61


def install(runtime_module) -> None:
    if getattr(runtime_module, "_semantic_quality_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "semantic-quality-candidates":
            try:
                return _candidates_cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 60
        if len(sys.argv) > 1 and sys.argv[1] == "semantic-quality-case":
            try:
                return _case_cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 61
        return original_main()

    runtime_module.main = main
    runtime_module._semantic_quality_installed = True
