#!/usr/bin/env python3
"""Derive exact Mover transition behavior from normalized Mover + Blueprint facts."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

DERIVED_FILES = (
    "mover_transition_behaviors.jsonl",
    "mover_transition_routes.jsonl",
)
BEHAVIOR_SCHEMA_VERSION = 1

_SQL = """
CREATE TABLE mover_transition_behaviors(
 behavior_id TEXT PRIMARY KEY,transition_blueprint_path TEXT NOT NULL,graph_id TEXT NOT NULL,
 graph_name TEXT NOT NULL,branch_node_id TEXT NOT NULL,branch_output TEXT NOT NULL,
 condition_polarity INTEGER NOT NULL,condition_dependency_id TEXT NOT NULL,
 condition_text TEXT NOT NULL,condition_raw_text TEXT NOT NULL,result_node_id TEXT NOT NULL,
 result_dependency_id TEXT NOT NULL,next_mode TEXT NOT NULL,expression_node_count INTEGER NOT NULL,
 function_calls_json TEXT NOT NULL,object_refs_json TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX mover_transition_behaviors_bp_idx ON mover_transition_behaviors(transition_blueprint_path,next_mode);
CREATE TABLE mover_transition_routes(
 route_id TEXT PRIMARY KEY,blueprint_path TEXT NOT NULL,component_path TEXT NOT NULL,
 source_mode_name TEXT NOT NULL,source_mode_path TEXT NOT NULL,transition_path TEXT NOT NULL,
 transition_blueprint_path TEXT NOT NULL,target_mode_name TEXT NOT NULL,target_mode_path TEXT NOT NULL,
 behavior_id TEXT NOT NULL,condition_text TEXT NOT NULL,condition_polarity INTEGER NOT NULL,
 branch_output TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX mover_transition_routes_component_idx ON mover_transition_routes(component_path,source_mode_name,target_mode_name);
CREATE INDEX mover_transition_routes_transition_idx ON mover_transition_routes(transition_blueprint_path);
"""


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("\x1f".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield value


def _write(path: Path, rows: list[dict]) -> int:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(_j(row) + "\n")
    return len(rows)


def _input_map(expr: dict) -> dict[str, dict]:
    return {
        str(item.get("pin", "")): item
        for item in expr.get("inputs", [])
        if isinstance(item, dict) and item.get("pin")
    }


def _literal_text(value) -> str:
    text = str(value if value is not None else "")
    tag = re.fullmatch(r'\(TagName="([^"]+)"\)', text)
    if tag:
        return json.dumps(tag.group(1), ensure_ascii=False)
    if text.lower() in {"true", "false"}:
        return text.lower()
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return format(number, ".12g")


def _format_input(item: dict) -> str:
    sources = item.get("sources", [])
    if isinstance(sources, list) and sources:
        rendered = [_format_expression(source) for source in sources if isinstance(source, dict)]
        if len(rendered) == 1:
            return rendered[0]
        if rendered:
            return "[" + ", ".join(rendered) + "]"
    if "literal" in item:
        return _literal_text(item.get("literal"))
    return "?"


def _format_expression(expr: dict) -> str:
    if not isinstance(expr, dict):
        return "?"
    kind = str(expr.get("kind", ""))
    operation = str(expr.get("operation", ""))
    label = str(expr.get("label", ""))
    output_pin = str(expr.get("output_pin", ""))
    inputs = _input_map(expr)

    if kind == "boundary" or operation == "function_entry":
        return output_pin or label or "input"

    if operation == "break_struct":
        values = list(inputs.values())
        base = _format_input(values[0]) if values else "?"
        return f"{base}.{output_pin}" if output_pin else base

    if operation == "dynamic_cast":
        obj = _format_input(inputs.get("Object", next(iter(inputs.values()), {})))
        return f"as {label}({obj})" if label else f"cast({obj})"

    if operation == "function_call":
        args = {name: _format_input(item) for name, item in inputs.items()}
        a = args.get("A", "?")
        b = args.get("B", "?")
        if label == "BooleanAND":
            return f"({a} and {b})"
        if label == "BooleanOR":
            return f"({a} or {b})"
        if label == "Not_PreBool":
            return f"not ({a})"
        comparisons = (
            ("GreaterEqual_", ">="), ("LessEqual_", "<="),
            ("Greater_", ">"), ("Less_", "<"),
            ("EqualEqual_", "=="), ("NotEqual_", "!="),
        )
        for prefix, symbol in comparisons:
            if label.startswith(prefix):
                return f"({a} {symbol} {b})"
        if label == "VSizeXY":
            return f"length_xy({a})"
        if label == "HasGameplayTag":
            owner = args.get("self", "?")
            tag = args.get("TagToFind", "?")
            exact = args.get("bExactMatch", "false")
            return f"has_gameplay_tag({owner}, {tag}, exact={exact})"
        if label == "IsCrouching":
            return f"is_crouching({args.get('self', '?')})"

        visible = []
        for name, value in args.items():
            if name == "self" and value == "/Script/Engine.Default__KismetMathLibrary":
                continue
            visible.append(f"{name}={value}")
        return f"{label or operation}({', '.join(visible)})"

    if operation == "make_struct":
        rendered = ", ".join(f"{name}={_format_input(item)}" for name, item in inputs.items())
        return f"{label or 'make_struct'}({rendered})"

    rendered = ", ".join(f"{name}={_format_input(item)}" for name, item in inputs.items())
    return f"{label or operation or kind}({rendered})" if rendered else (label or operation or kind or "?")


def _next_mode(result_dependency: dict) -> str:
    expr = result_dependency.get("expression", {})
    if not isinstance(expr, dict) or str(expr.get("operation", "")) != "make_struct":
        return ""
    label = str(expr.get("label", ""))
    if "TransitionEvalResult" not in label:
        return ""
    for item in expr.get("inputs", []):
        if isinstance(item, dict) and str(item.get("pin", "")) == "NextMode" and "literal" in item:
            return str(item.get("literal", ""))
    return ""


def derive(output: Path, rows=None) -> tuple[list[dict], list[dict]]:
    output = Path(output)
    rows = rows or _rows
    transition_bps = {
        str(row.get("blueprint_path", ""))
        for row in rows(output / "mover_blueprints.jsonl")
        if str(row.get("mover_kind", "")) == "movement_transition"
    }
    dependencies = [
        row for row in rows(output / "blueprint_data_dependencies.jsonl")
        if str(row.get("blueprint_path", "")) in transition_bps and str(row.get("graph_name", "")) == "Evaluate"
    ]
    nodes = {
        str(row.get("node_id", "")): row
        for row in rows(output / "blueprint_nodes.jsonl")
        if str(row.get("blueprint_path", "")) in transition_bps and str(row.get("graph_name", "")) == "Evaluate"
    }
    exec_edges = [
        row for row in rows(output / "blueprint_edges.jsonl")
        if str(row.get("blueprint_path", "")) in transition_bps
        and str(row.get("graph_name", "")) == "Evaluate"
        and str(row.get("edge_kind", "")) == "execution"
    ]

    conditions_by_node = {
        str(row.get("sink_node_id", "")): row
        for row in dependencies
        if str(row.get("sink_operation", "")) == "branch" and str(row.get("sink_pin_name", "")) == "Condition"
    }
    results_by_node = {
        str(row.get("sink_node_id", "")): row
        for row in dependencies
        if str(row.get("sink_operation", "")) == "function_result" and str(row.get("sink_pin_name", "")) == "ReturnValue"
    }

    behaviors: list[dict] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for edge in exec_edges:
        branch_node = str(edge.get("source_node_id", ""))
        result_node = str(edge.get("target_node_id", ""))
        branch_output = str(edge.get("source_pin_name", ""))
        if branch_output not in {"then", "else"}:
            continue
        condition = conditions_by_node.get(branch_node)
        result = results_by_node.get(result_node)
        node = nodes.get(branch_node, {})
        if not condition or not result:
            continue
        if str(node.get("operation", "")) != "branch" or str(node.get("node_class", "")) != "/Script/BlueprintGraph.K2Node_IfThenElse":
            continue
        next_mode = _next_mode(result)
        if not next_mode:
            continue
        bp = str(edge.get("blueprint_path", ""))
        pair = (bp, branch_node, result_node)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        expression = condition.get("expression", {}) if isinstance(condition.get("expression", {}), dict) else {}
        behavior_id = _id("mover_behavior", bp, branch_node, branch_output, result_node, next_mode)
        behaviors.append({
            "behavior_id": behavior_id,
            "schema_version": BEHAVIOR_SCHEMA_VERSION,
            "transition_blueprint_path": bp,
            "graph_id": str(edge.get("graph_id", "")),
            "graph_name": "Evaluate",
            "branch_node_id": branch_node,
            "branch_output": branch_output,
            "condition_polarity": branch_output == "then",
            "condition_dependency_id": str(condition.get("dependency_id", "")),
            "condition_text": _format_expression(expression),
            "condition_raw_text": str(condition.get("text", "")),
            "condition_expression": expression,
            "result_node_id": result_node,
            "result_dependency_id": str(result.get("dependency_id", "")),
            "result_raw_text": str(result.get("text", "")),
            "next_mode": next_mode,
            "expression_node_count": int(condition.get("expression_node_count", 0) or 0),
            "function_calls": list(condition.get("function_calls", [])) if isinstance(condition.get("function_calls", []), list) else [],
            "object_refs": list(condition.get("object_refs", [])) if isinstance(condition.get("object_refs", []), list) else [],
        })

    behaviors.sort(key=lambda row: (row["transition_blueprint_path"], row["behavior_id"]))
    behavior_by_asset: dict[str, list[dict]] = {}
    for row in behaviors:
        behavior_by_asset.setdefault(row["transition_blueprint_path"], []).append(row)

    modes = list(rows(output / "mover_modes.jsonl"))
    mode_by_path = {str(row.get("mode_path", "")): row for row in modes}
    modes_by_component_name: dict[tuple[str, str], list[dict]] = {}
    for row in modes:
        key = (str(row.get("component_path", "")), str(row.get("mode_name", "")))
        modes_by_component_name.setdefault(key, []).append(row)

    routes: list[dict] = []
    for transition in rows(output / "mover_transitions.jsonl"):
        if str(transition.get("owner_kind", "")) != "mover_mode":
            continue
        source_mode = mode_by_path.get(str(transition.get("owner_path", "")))
        asset = str(transition.get("transition_asset_path", ""))
        if not source_mode or not asset:
            continue
        component = str(source_mode.get("component_path", ""))
        for behavior in behavior_by_asset.get(asset, []):
            targets = modes_by_component_name.get((component, str(behavior.get("next_mode", ""))), [])
            if len(targets) != 1:
                continue
            target_mode = targets[0]
            route_id = _id(
                "mover_route",
                component,
                str(source_mode.get("mode_path", "")),
                str(transition.get("transition_path", "")),
                str(target_mode.get("mode_path", "")),
                str(behavior.get("behavior_id", "")),
            )
            routes.append({
                "route_id": route_id,
                "schema_version": BEHAVIOR_SCHEMA_VERSION,
                "blueprint_path": str(source_mode.get("blueprint_path", "")),
                "component_path": component,
                "source_mode_name": str(source_mode.get("mode_name", "")),
                "source_mode_path": str(source_mode.get("mode_path", "")),
                "transition_path": str(transition.get("transition_path", "")),
                "transition_blueprint_path": asset,
                "target_mode_name": str(target_mode.get("mode_name", "")),
                "target_mode_path": str(target_mode.get("mode_path", "")),
                "behavior_id": str(behavior.get("behavior_id", "")),
                "condition_text": str(behavior.get("condition_text", "")),
                "condition_polarity": bool(behavior.get("condition_polarity", False)),
                "branch_output": str(behavior.get("branch_output", "")),
            })
    routes.sort(key=lambda row: (row["component_path"], row["source_mode_name"], row["target_mode_name"], row["route_id"]))
    return behaviors, routes


def validation_error(output: Path, rows=None) -> str | None:
    output = Path(output)
    rows = rows or _rows
    behaviors = list(rows(output / DERIVED_FILES[0]))
    routes = list(rows(output / DERIVED_FILES[1]))
    behavior_ids = [str(row.get("behavior_id", "")) for row in behaviors]
    if any(not value for value in behavior_ids) or len(behavior_ids) != len(set(behavior_ids)):
        return "Mover transition behavior ids are blank or duplicated"
    transition_bps = {
        str(row.get("blueprint_path", ""))
        for row in rows(output / "mover_blueprints.jsonl")
        if str(row.get("mover_kind", "")) == "movement_transition"
    }
    for row in behaviors:
        if str(row.get("transition_blueprint_path", "")) not in transition_bps:
            return f"Mover behavior references unknown transition Blueprint: {row.get('transition_blueprint_path')}"
        if str(row.get("branch_output", "")) not in {"then", "else"}:
            return f"Mover behavior has unsupported branch output: {row.get('branch_output')}"
        if not str(row.get("condition_dependency_id", "")) or not str(row.get("result_dependency_id", "")):
            return f"Mover behavior lacks dependency provenance: {row.get('behavior_id')}"
        if not str(row.get("condition_text", "")) or not str(row.get("next_mode", "")):
            return f"Mover behavior lacks condition/next mode: {row.get('behavior_id')}"

    mode_rows = list(rows(output / "mover_modes.jsonl"))
    mode_by_path = {str(row.get("mode_path", "")): row for row in mode_rows}
    transition_paths = {str(row.get("transition_path", "")) for row in rows(output / "mover_transitions.jsonl")}
    behavior_set = set(behavior_ids)
    route_ids = [str(row.get("route_id", "")) for row in routes]
    if any(not value for value in route_ids) or len(route_ids) != len(set(route_ids)):
        return "Mover transition route ids are blank or duplicated"
    for row in routes:
        if str(row.get("behavior_id", "")) not in behavior_set:
            return f"Mover route references unknown behavior: {row.get('route_id')}"
        source = mode_by_path.get(str(row.get("source_mode_path", "")))
        target = mode_by_path.get(str(row.get("target_mode_path", "")))
        if not source or not target:
            return f"Mover route references unknown mode: {row.get('route_id')}"
        if str(source.get("component_path", "")) != str(target.get("component_path", "")) or str(source.get("component_path", "")) != str(row.get("component_path", "")):
            return f"Mover route crosses component boundary: {row.get('route_id')}"
        if str(target.get("mode_name", "")) != str(row.get("target_mode_name", "")):
            return f"Mover route target mode mismatch: {row.get('route_id')}"
        if str(row.get("transition_path", "")) not in transition_paths:
            return f"Mover route references unknown transition instance: {row.get('route_id')}"
    return None


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def load_database(conn, output: Path, rows=None) -> None:
    rows = rows or _rows
    for r in rows(Path(output) / DERIVED_FILES[0]):
        conn.execute("INSERT OR REPLACE INTO mover_transition_behaviors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("behavior_id", ""), r.get("transition_blueprint_path", ""), r.get("graph_id", ""), r.get("graph_name", ""),
            r.get("branch_node_id", ""), r.get("branch_output", ""), int(bool(r.get("condition_polarity", False))),
            r.get("condition_dependency_id", ""), r.get("condition_text", ""), r.get("condition_raw_text", ""),
            r.get("result_node_id", ""), r.get("result_dependency_id", ""), r.get("next_mode", ""),
            int(r.get("expression_node_count", 0) or 0), _j(r.get("function_calls", [])), _j(r.get("object_refs", [])), _j(r)))
    for r in rows(Path(output) / DERIVED_FILES[1]):
        conn.execute("INSERT OR REPLACE INTO mover_transition_routes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("route_id", ""), r.get("blueprint_path", ""), r.get("component_path", ""), r.get("source_mode_name", ""),
            r.get("source_mode_path", ""), r.get("transition_path", ""), r.get("transition_blueprint_path", ""),
            r.get("target_mode_name", ""), r.get("target_mode_path", ""), r.get("behavior_id", ""), r.get("condition_text", ""),
            int(bool(r.get("condition_polarity", False))), r.get("branch_output", ""), _j(r)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mover_transition_behaviors'").fetchone():
        return
    print("\n[Mover transition behavior]")
    print_rows(conn.execute(
        """SELECT transition_blueprint_path,condition_text,next_mode,branch_output,expression_node_count
           FROM mover_transition_behaviors
           WHERE transition_blueprint_path LIKE ? OR condition_text LIKE ? OR next_mode LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("transition_blueprint_path", "condition_text", "next_mode", "branch_output", "expression_node_count"))
    print("\n[Mover transition routes]")
    print_rows(conn.execute(
        """SELECT blueprint_path,source_mode_name,transition_blueprint_path,target_mode_name,condition_text
           FROM mover_transition_routes
           WHERE blueprint_path LIKE ? OR source_mode_name LIKE ? OR transition_blueprint_path LIKE ? OR target_mode_name LIKE ? OR condition_text LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("blueprint_path", "source_mode_name", "transition_blueprint_path", "target_mode_name", "condition_text"))


def install(core, runtime) -> None:
    if getattr(core, "_mover_behavior_installed", False):
        return
    base_create_schema = core.create_schema
    base_derive_output = core.derive_output
    base_build_database = core.build_database
    base_query = core.query

    def create_schema_wrapper(conn):
        base_create_schema(conn)
        create_schema(conn)

    def derive_output_wrapper(output):
        output = Path(output).expanduser().resolve()
        counts = dict(base_derive_output(output))
        behaviors, routes = derive(output, runtime._rows)
        local_counts = {
            DERIVED_FILES[0].removesuffix(".jsonl"): runtime._write(output / DERIVED_FILES[0], behaviors),
            DERIVED_FILES[1].removesuffix(".jsonl"): runtime._write(output / DERIVED_FILES[1], routes),
        }
        error = validation_error(output, runtime._rows)
        if error:
            raise RuntimeError(f"Mover behavior derived incomplete: {error}")
        counts.update(local_counts)
        manifest_path = output / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            declared = manifest.get("derived_counts", {})
            declared = declared if isinstance(declared, dict) else {}
            declared.update(local_counts)
            manifest["derived_counts"] = declared
            manifest["mover_behavior_schema_version"] = BEHAVIOR_SCHEMA_VERSION
            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return counts

    def build_database_wrapper(output):
        output = Path(output).expanduser().resolve()
        error = validation_error(output, runtime._rows)
        if error:
            raise RuntimeError(f"Mover behavior derived incomplete: {error}")
        db = base_build_database(output)
        conn = sqlite3.connect(db)
        try:
            load_database(conn, output, runtime._rows)
            conn.commit()
        finally:
            conn.close()
        return db

    def query_wrapper(args):
        result = int(base_query(args))
        root = Path(args.output).expanduser().resolve()
        db = root if root.suffix.lower() == ".db" else root / core.DB_NAME
        if db.is_file():
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                query(conn, core._print_rows, f"%{args.term}%", args.limit)
            finally:
                conn.close()
        return result

    core.create_schema = create_schema_wrapper
    core.derive_output = derive_output_wrapper
    core.build_database = build_database_wrapper
    core.query = query_wrapper
    core.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((*core.DEFAULT_BUNDLE_FILES, *DERIVED_FILES)))
    core._mover_behavior_installed = True
