#!/usr/bin/env python3
"""Read-only evidence report for Gameplay Camera director Blueprint logic.

This report intentionally does not invent camera semantics. It joins the existing
Blueprint semantic nodes/statements/dependencies, exact Blueprint object
relations, Chooser tables, Blueprint call edges, and implemented-interface facts
so we can see how a BlueprintCameraDirector builds its chooser context and where
interface-supplied camera properties come from.
"""
from __future__ import annotations

import argparse
import json
import re
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
    "gait",
    "stance",
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
CAMERA_PROPERTY_FUNCTION = "Get_PropertiesForCamera"


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


def _class_to_blueprint(class_path: str) -> str:
    """Normalize generated/skeleton Blueprint classes to Blueprint object paths."""
    value = str(class_path or "")
    if not value.startswith("/Game/") or "." not in value:
        return ""
    package, obj = value.rsplit(".", 1)
    if obj.startswith("SKEL_"):
        obj = obj[5:]
    elif obj.startswith("REINST_"):
        obj = obj[7:]
        obj = re.sub(r"_C_\d+$", "_C", obj)
    if obj.endswith("_C"):
        obj = obj[:-2]
    return f"{package}.{obj}"


def _implemented_interface_paths(blueprint: dict) -> set[str]:
    result: set[str] = set()
    values = blueprint.get("implemented_interfaces", [])
    if not isinstance(values, list):
        return result
    for item in values:
        if isinstance(item, dict):
            value = str(item.get("interface_class", "") or "")
        else:
            value = str(item or "")
        if not value:
            continue
        result.add(value)
        normalized = _class_to_blueprint(value)
        if normalized:
            result.add(normalized)
    return result


def _call_target_interface(call: dict) -> str:
    owner = str(call.get("target_owner", "") or "")
    return _class_to_blueprint(owner)


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
    functions = _rows_for(rows, output / "blueprint_functions.jsonl")
    call_edges = _rows_for(rows, output / "blueprint_call_edges.jsonl")

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
    for row in dependencies:
        node_id = str(row.get("sink_node_id", "") or "")
        if node_id:
            deps_by_sink.setdefault(node_id, []).append(row)
    for values in deps_by_sink.values():
        values.sort(key=lambda row: (str(row.get("sink_pin_name", "") or ""), str(row.get("dependency_id", "") or "")))

    pins_by_node: dict[str, list[dict]] = {}
    for row in pins:
        node_id = str(row.get("node_id", "") or "")
        if node_id:
            pins_by_node.setdefault(node_id, []).append(row)
    for values in pins_by_node.values():
        values.sort(key=lambda row: int(row.get("pin_index", 0) or 0))

    statement_by_node = {str(row.get("node_id", "") or ""): row for row in statements if row.get("node_id")}
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

    # Follow the exact director-side function call to its statically known
    # implementation candidates. Interface dispatch is intentionally not forced
    # to one target when multiple Blueprint classes implement the interface.
    camera_property_calls = [
        row for row in call_edges
        if str(row.get("blueprint_path", "") or "") in director_paths
        and str(row.get("target_name", "") or "") == CAMERA_PROPERTY_FUNCTION
    ]
    camera_property_calls.sort(key=lambda row: (
        str(row.get("blueprint_path", "") or ""),
        str(row.get("graph_name", "") or ""),
        str(row.get("call_node_id", "") or ""),
    ))

    function_by_id = {
        str(row.get("function_id", "") or ""): row
        for row in functions
        if row.get("function_id")
    }
    blueprints_by_path = {_bp_path(row): row for row in blueprints if _bp_path(row)}
    functions_by_bp_name: dict[tuple[str, str], list[dict]] = {}
    for row in functions:
        key = (str(row.get("blueprint_path", "") or ""), str(row.get("name", "") or ""))
        functions_by_bp_name.setdefault(key, []).append(row)

    implementation_candidates: list[dict] = []
    seen_candidates: set[tuple[str, str, str]] = set()
    for call in camera_property_calls:
        interface_bp = _call_target_interface(call)
        candidate_ids = [str(value or "") for value in call.get("candidate_function_ids", [])] if isinstance(call.get("candidate_function_ids"), list) else []
        candidates = [function_by_id[value] for value in candidate_ids if value in function_by_id]

        # If generic call-edge resolution has no candidates for dynamic interface
        # dispatch, derive the statically valid implementation set from exact
        # implemented_interfaces + function-name facts.
        if not candidates and interface_bp:
            for bp_path, bp in blueprints_by_path.items():
                if interface_bp not in _implemented_interface_paths(bp):
                    continue
                candidates.extend(functions_by_bp_name.get((bp_path, CAMERA_PROPERTY_FUNCTION), []))

        # Preserve a declaration row only when it is already a call-edge
        # candidate; do not manufacture the interface Blueprint as an executable
        # implementation.
        for function in candidates:
            bp_path = str(function.get("blueprint_path", "") or "")
            function_id = str(function.get("function_id", "") or "")
            bp = blueprints_by_path.get(bp_path, {})
            implemented = _implemented_interface_paths(bp)
            kind = "implements_interface" if interface_bp and interface_bp in implemented else "candidate"
            key = (str(call.get("call_id", "") or ""), bp_path, function_id)
            if key in seen_candidates:
                continue
            seen_candidates.add(key)

            graph_id = str(function.get("graph_id", "") or function_id)
            result_nodes = {
                str(value or "") for value in function.get("result_node_ids", [])
                if value
            } if isinstance(function.get("result_node_ids"), list) else set()
            candidate_statements = [
                row for row in statements
                if str(row.get("blueprint_path", "") or "") == bp_path
                and str(row.get("graph_id", "") or "") == graph_id
            ]
            candidate_statements.sort(key=lambda row: (
                str(row.get("block_id", "") or ""),
                int(row.get("block_position", -1) or -1),
                str(row.get("node_id", "") or ""),
            ))
            candidate_dependencies = [
                row for row in dependencies
                if str(row.get("blueprint_path", "") or "") == bp_path
                and str(row.get("graph_id", "") or "") == graph_id
                and (
                    str(row.get("sink_node_id", "") or "") in result_nodes
                    or _contains_terms(row.get("text", ""))
                    or _contains_terms(row.get("expression", {}))
                )
            ]
            candidate_dependencies.sort(key=lambda row: (
                0 if str(row.get("sink_node_id", "") or "") in result_nodes else 1,
                str(row.get("sink_node_id", "") or ""),
                str(row.get("sink_pin_name", "") or ""),
                str(row.get("dependency_id", "") or ""),
            ))
            implementation_candidates.append({
                "call_id": str(call.get("call_id", "") or ""),
                "interface_blueprint_path": interface_bp,
                "implementation_kind": kind,
                "blueprint_path": bp_path,
                "function_id": function_id,
                "graph_id": graph_id,
                "graph_name": str(function.get("graph_name", "") or ""),
                "function_name": str(function.get("name", "") or ""),
                "resolved_function": str(function.get("resolved_function", "") or ""),
                "outputs": function.get("outputs", []) if isinstance(function.get("outputs"), list) else [],
                "statements": candidate_statements,
                "dependencies": candidate_dependencies,
            })

    implementation_candidates.sort(key=lambda row: (
        str(row.get("blueprint_path", "") or ""),
        str(row.get("graph_name", "") or ""),
        str(row.get("function_id", "") or ""),
    ))

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
        "camera_property_calls": camera_property_calls,
        "implementation_candidates": implementation_candidates,
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
        "evaluation_nodes={evals} relevant_nodes={nodes} relevant_dependencies={deps} relevant_statements={stmts} "
        "camera_property_calls={calls} implementation_candidates={candidates}".format(
            directors=len(report.get("directors", [])),
            links=len(report.get("director_chooser_links", [])),
            choosers=len(report.get("selected_choosers", set())),
            evals=len(report.get("evaluation_nodes", [])),
            nodes=len(report.get("relevant_nodes", [])),
            deps=len(report.get("relevant_dependencies", [])),
            stmts=len(report.get("relevant_statements", [])),
            calls=len(report.get("camera_property_calls", [])),
            candidates=len(report.get("implementation_candidates", [])),
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

    print("\n[Camera property interface calls]")
    values = report.get("camera_property_calls", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        print(
            "  {node} | target={target} | owner={owner} | interface={interface} | resolution={resolution} | candidates={count}".format(
                node=row.get("call_node_id", ""),
                target=row.get("target_name", ""),
                owner=row.get("target_owner", ""),
                interface=bool(row.get("interface_call", False)),
                resolution=row.get("resolution", ""),
                count=row.get("candidate_count", 0),
            )
        )
        candidate_ids = row.get("candidate_function_ids", [])
        if isinstance(candidate_ids, list) and candidate_ids:
            print("      candidate_function_ids: " + ", ".join(str(value) for value in candidate_ids))

    print("\n[Get_PropertiesForCamera implementation candidates]")
    values = report.get("implementation_candidates", [])
    if not values:
        print("<none statically proven>")
    for row in values[:limit]:
        print(
            "  {bp}::{name} | graph={graph} | kind={kind} | interface={interface}".format(
                bp=row.get("blueprint_path", ""),
                name=row.get("function_name", ""),
                graph=row.get("graph_name", ""),
                kind=row.get("implementation_kind", ""),
                interface=row.get("interface_blueprint_path", ""),
            )
        )
        outputs = row.get("outputs", [])
        if isinstance(outputs, list) and outputs:
            print("      outputs: " + _short(outputs, 900))
        dependencies = row.get("dependencies", [])
        if dependencies:
            print("      return/relevant dependencies:")
            for dep in dependencies[:limit]:
                _print_dependency(dep, indent="        ")
        statements = row.get("statements", [])
        if statements:
            print("      function statements:")
            for statement in statements[:limit]:
                print(
                    "        {block}:{pos} | {op} | {text}".format(
                        block=statement.get("block_id", ""),
                        pos=statement.get("block_position", -1),
                        op=statement.get("operation", ""),
                        text=_short(statement.get("text", ""), 1200),
                    )
                )

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
