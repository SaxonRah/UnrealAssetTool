#!/usr/bin/env python3
"""Read-only evidence report for Gameplay Camera director Blueprint logic.

This report intentionally does not invent camera semantics. It joins the existing
Blueprint semantic nodes/statements/dependencies, exact Blueprint object
relations, and Chooser tables so we can see how a BlueprintCameraDirector builds
its chooser context before evaluating a camera-rig Chooser.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

CAMERA_DIRECTOR_MARKERS = (
    "/script/gameplaycameras.blueprintcameradirector",
    "cameradirector",
)
CAMERA_TERMS = (
    "characterpropertiesforcamera",
    "camerastyle",
    "cameramode",
    "movementmode",
    "chooser",
)
INTERESTING_OPERATIONS = {
    "evaluate_chooser",
    "chooser_context_parameters",
    "make_struct",
    "set_fields_in_struct",
    "break_struct",
    "variable_get",
    "variable_set",
    "function_call",
    "dynamic_cast",
}


def _rows_for(rows, path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [row for row in rows(path) if isinstance(row, dict)]


def _bp_path(row: dict) -> str:
    return str(row.get("object_path", "") or row.get("blueprint_path", "") or "")


def _is_director_blueprint(row: dict) -> bool:
    text = " ".join((
        _bp_path(row),
        str(row.get("parent_class", "") or ""),
        str(row.get("generated_class", "") or ""),
    )).lower()
    return any(marker in text for marker in CAMERA_DIRECTOR_MARKERS)


def _contains_terms(value) -> bool:
    if isinstance(value, str):
        text = value.lower()
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True).lower()
        except (TypeError, ValueError):
            text = str(value).lower()
    return any(term in text for term in CAMERA_TERMS)


def _node_text(row: dict) -> str:
    return " ".join((
        str(row.get("operation", "") or ""),
        str(row.get("symbol", "") or ""),
        str(row.get("owner", "") or ""),
        str(row.get("target", "") or ""),
        str(row.get("label", "") or ""),
    ))


def _short(value, limit: int = 500) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def build_report(output: Path, rows) -> dict:
    output = Path(output).expanduser().resolve()

    blueprints = _rows_for(rows, output / "blueprints.jsonl")
    relations = _rows_for(rows, output / "blueprint_relations.jsonl")
    chooser_tables = _rows_for(rows, output / "chooser_tables.jsonl")
    semantic_nodes = _rows_for(rows, output / "blueprint_semantic_nodes.jsonl")
    statements = _rows_for(rows, output / "blueprint_semantic_statements.jsonl")
    dependencies = _rows_for(rows, output / "blueprint_data_dependencies.jsonl")
    pins = _rows_for(rows, output / "blueprint_pins.jsonl")
    blocks = _rows_for(rows, output / "blueprint_semantic_blocks.jsonl")

    directors = [row for row in blueprints if _is_director_blueprint(row)]
    director_paths = {_bp_path(row) for row in directors if _bp_path(row)}
    chooser_paths = {
        str(row.get("chooser_path", "") or "")
        for row in chooser_tables
        if row.get("chooser_path")
    }

    director_chooser_links = [
        row for row in relations
        if str(row.get("blueprint_path", "") or row.get("asset_path", "") or "") in director_paths
        and str(row.get("target", "") or "") in chooser_paths
    ]
    selected_choosers = {
        str(row.get("target", "") or "") for row in director_chooser_links
        if row.get("target")
    }

    nodes = [row for row in semantic_nodes if str(row.get("blueprint_path", "") or "") in director_paths]
    stmts = [row for row in statements if str(row.get("blueprint_path", "") or "") in director_paths]
    deps = [row for row in dependencies if str(row.get("blueprint_path", "") or "") in director_paths]
    director_pins = [row for row in pins if str(row.get("blueprint_path", "") or "") in director_paths]
    director_blocks = [row for row in blocks if str(row.get("blueprint_path", "") or "") in director_paths]

    eval_nodes = [
        row for row in nodes
        if str(row.get("operation", "") or "") == "evaluate_chooser"
        or any(path and path.lower() in _node_text(row).lower() for path in selected_choosers)
    ]
    eval_node_ids = {str(row.get("node_id", "") or "") for row in eval_nodes if row.get("node_id")}

    deps_by_sink: dict[str, list[dict]] = {}
    for row in deps:
        node_id = str(row.get("sink_node_id", "") or "")
        if node_id:
            deps_by_sink.setdefault(node_id, []).append(row)
    for values in deps_by_sink.values():
        values.sort(key=lambda row: (str(row.get("sink_pin_name", "") or ""), str(row.get("dependency_id", "") or "")))

    pins_by_node: dict[str, list[dict]] = {}
    for row in director_pins:
        node_id = str(row.get("node_id", "") or "")
        if node_id:
            pins_by_node.setdefault(node_id, []).append(row)
    for values in pins_by_node.values():
        values.sort(key=lambda row: int(row.get("pin_index", 0) or 0))

    statement_by_node = {str(row.get("node_id", "") or ""): row for row in stmts if row.get("node_id")}
    block_by_id = {str(row.get("block_id", "") or ""): row for row in director_blocks if row.get("block_id")}

    relevant_node_ids: set[str] = set(eval_node_ids)
    for row in nodes:
        operation = str(row.get("operation", "") or "")
        if operation in INTERESTING_OPERATIONS and _contains_terms(row):
            relevant_node_ids.add(str(row.get("node_id", "") or ""))
        elif _contains_terms(_node_text(row)):
            relevant_node_ids.add(str(row.get("node_id", "") or ""))
    for row in deps:
        if _contains_terms(row.get("text", "")) or _contains_terms(row.get("expression", {})):
            relevant_node_ids.add(str(row.get("sink_node_id", "") or ""))
    relevant_node_ids.discard("")

    relevant_nodes = [row for row in nodes if str(row.get("node_id", "") or "") in relevant_node_ids]
    relevant_nodes.sort(key=lambda row: (
        str(row.get("graph_name", "") or ""),
        str(row.get("operation", "") or ""),
        str(row.get("node_id", "") or ""),
    ))

    relevant_dependencies = [
        row for row in deps
        if str(row.get("sink_node_id", "") or "") in relevant_node_ids
        or _contains_terms(row.get("text", ""))
        or _contains_terms(row.get("expression", {}))
    ]
    relevant_dependencies.sort(key=lambda row: (
        str(row.get("graph_name", "") or ""),
        str(row.get("sink_node_id", "") or ""),
        str(row.get("sink_pin_name", "") or ""),
        str(row.get("dependency_id", "") or ""),
    ))

    relevant_statements = [
        row for row in stmts
        if str(row.get("node_id", "") or "") in relevant_node_ids
        or _contains_terms(row.get("text", ""))
    ]
    relevant_statements.sort(key=lambda row: (
        str(row.get("graph_name", "") or ""),
        str(row.get("block_id", "") or ""),
        int(row.get("block_position", -1) or -1),
        str(row.get("node_id", "") or ""),
    ))

    relevant_block_ids = {
        str(row.get("block_id", "") or "")
        for row in relevant_statements
        if row.get("block_id")
    }
    relevant_blocks = [block_by_id[value] for value in sorted(relevant_block_ids) if value in block_by_id]

    return {
        "output": str(output),
        "directors": directors,
        "director_paths": director_paths,
        "director_chooser_links": director_chooser_links,
        "selected_choosers": selected_choosers,
        "evaluation_nodes": eval_nodes,
        "relevant_nodes": relevant_nodes,
        "relevant_dependencies": relevant_dependencies,
        "relevant_statements": relevant_statements,
        "relevant_blocks": relevant_blocks,
        "dependencies_by_sink": deps_by_sink,
        "pins_by_node": pins_by_node,
        "statement_by_node": statement_by_node,
    }


def _print_pin(pin: dict, indent: str = "      ") -> None:
    pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
    print(
        indent + "pin {name} | dir={direction} | type={category} | linked={linked} | default={default}".format(
            name=pin.get("name", ""),
            direction=pin.get("direction", ""),
            category=pin_type.get("category", ""),
            linked=pin.get("linked_count", 0),
            default=_short(pin.get("default_object", "") or pin.get("default_value", "") or pin.get("default_text", ""), 180),
        )
    )


def _print_dependency(dep: dict, indent: str = "      ") -> None:
    print(
        indent + "dependency {dep} | pin={pin} | text={text}".format(
            dep=dep.get("dependency_id", ""),
            pin=dep.get("sink_pin_name", ""),
            text=_short(dep.get("text", ""), 700),
        )
    )
    expression = dep.get("expression", {})
    if isinstance(expression, dict) and expression:
        print(indent + "  expression: " + _short(expression, 1400))
    calls = dep.get("function_calls", [])
    if isinstance(calls, list) and calls:
        print(indent + "  calls: " + ", ".join(str(value) for value in calls))
    refs = dep.get("object_refs", [])
    if isinstance(refs, list) and refs:
        print(indent + "  object_refs: " + ", ".join(str(value) for value in refs))


def print_report(report: dict, *, limit: int = 400) -> None:
    print("=== GAMEPLAY CAMERA DIRECTOR REPORT ===")
    print(report.get("output", ""))
    print(
        "directors={directors} chooser_links={links} chooser_assets={choosers} "
        "evaluation_nodes={evals} relevant_nodes={nodes} relevant_dependencies={deps} relevant_statements={stmts}".format(
            directors=len(report.get("directors", [])),
            links=len(report.get("director_chooser_links", [])),
            choosers=len(report.get("selected_choosers", set())),
            evals=len(report.get("evaluation_nodes", [])),
            nodes=len(report.get("relevant_nodes", [])),
            deps=len(report.get("relevant_dependencies", [])),
            stmts=len(report.get("relevant_statements", [])),
        )
    )

    print("\n[Director Blueprints]")
    for row in report.get("directors", [])[:limit]:
        print(
            "  {path} | parent={parent} | generated={generated}".format(
                path=_bp_path(row),
                parent=row.get("parent_class", ""),
                generated=row.get("generated_class", ""),
            )
        )

    print("\n[Director -> Chooser links]")
    values = report.get("director_chooser_links", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        print(
            "  {bp} -> {target} | relation={relation} | source_id={source}".format(
                bp=row.get("blueprint_path", "") or row.get("asset_path", ""),
                target=row.get("target", ""),
                relation=row.get("relation", ""),
                source=row.get("source_id", ""),
            )
        )

    print("\n[Chooser evaluation nodes]")
    values = report.get("evaluation_nodes", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        node_id = str(row.get("node_id", "") or "")
        print(
            "  {node} | graph={graph} | op={op} | symbol={symbol} | target={target}".format(
                node=node_id,
                graph=row.get("graph_name", ""),
                op=row.get("operation", ""),
                symbol=row.get("symbol", ""),
                target=row.get("target", ""),
            )
        )
        statement = report.get("statement_by_node", {}).get(node_id)
        if statement:
            print("      statement: " + _short(statement.get("text", ""), 900))
        for pin in report.get("pins_by_node", {}).get(node_id, []):
            _print_pin(pin)
        for dep in report.get("dependencies_by_sink", {}).get(node_id, []):
            _print_dependency(dep)

    print("\n[Camera-property semantic nodes]")
    eval_ids = {str(row.get("node_id", "") or "") for row in report.get("evaluation_nodes", [])}
    values = [row for row in report.get("relevant_nodes", []) if str(row.get("node_id", "") or "") not in eval_ids]
    if not values:
        print("<none beyond evaluation nodes>")
    for row in values[:limit]:
        node_id = str(row.get("node_id", "") or "")
        print(
            "  {node} | graph={graph} | op={op} | symbol={symbol} | owner={owner} | target={target}".format(
                node=node_id,
                graph=row.get("graph_name", ""),
                op=row.get("operation", ""),
                symbol=row.get("symbol", ""),
                owner=row.get("owner", ""),
                target=row.get("target", ""),
            )
        )
        statement = report.get("statement_by_node", {}).get(node_id)
        if statement:
            print("      statement: " + _short(statement.get("text", ""), 900))
        for dep in report.get("dependencies_by_sink", {}).get(node_id, []):
            _print_dependency(dep)

    print("\n[Relevant statements]")
    values = report.get("relevant_statements", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        print(
            "  {graph} | block={block}:{pos} | {op} | {text}".format(
                graph=row.get("graph_name", ""),
                block=row.get("block_id", ""),
                pos=row.get("block_position", -1),
                op=row.get("operation", ""),
                text=_short(row.get("text", ""), 1200),
            )
        )

    print("\n[Relevant dependency expressions]")
    values = report.get("relevant_dependencies", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        print(
            "  {graph} | node={node} | op={op} | pin={pin}".format(
                graph=row.get("graph_name", ""),
                node=row.get("sink_node_id", ""),
                op=row.get("sink_operation", ""),
                pin=row.get("sink_pin_name", ""),
            )
        )
        _print_dependency(row, indent="    ")

    print("\n[Relevant execution blocks]")
    values = report.get("relevant_blocks", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        print(
            "  {graph} | block={block} | statements={count} | {text}".format(
                graph=row.get("graph_name", ""),
                block=row.get("block_id", ""),
                count=row.get("statement_count", 0),
                text=_short(row.get("text", ""), 1500),
            )
        )

    print("=======================================")


def install(runtime_module) -> None:
    if getattr(runtime_module, "_gameplay_camera_director_report_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "gameplay-camera-director-report":
            parser = argparse.ArgumentParser(
                prog="uatool gameplay-camera-director-report",
                description="report Blueprint evidence that builds Gameplay Camera chooser context",
            )
            parser.add_argument("output", help="source .uatool directory")
            parser.add_argument("--limit", type=int, default=400, help="maximum rows per detailed section")
            args = parser.parse_args(sys.argv[2:])
            if args.limit < 1:
                parser.error("--limit must be >= 1")
            report = build_report(Path(args.output), runtime_module._rows)
            print_report(report, limit=args.limit)
            return 0
        return original_main()

    runtime_module.main = main
    runtime_module._gameplay_camera_director_report_installed = True
