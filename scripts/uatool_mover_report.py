#!/usr/bin/env python3
"""Read-only report of canonical Mover/ChaosMover evidence in an existing scan."""
from __future__ import annotations

import argparse
import collections
from pathlib import Path
import sys

MOVER_MARKERS = ("/script/mover.", "/script/chaosmover.")


def _is_mover_type(value: object) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in MOVER_MARKERS)


def _rows_for(rows, path: Path):
    if not path.is_file():
        return []
    return [row for row in rows(path) if isinstance(row, dict)]


def _component_rows(blueprints: list[dict]) -> list[dict]:
    result: list[dict] = []
    for blueprint in blueprints:
        bp_path = str(blueprint.get("object_path", "") or blueprint.get("blueprint_path", "") or "")
        for component in blueprint.get("components", []) or []:
            if not isinstance(component, dict):
                continue
            component_class = str(component.get("component_class", "") or "")
            if not _is_mover_type(component_class):
                continue
            row = dict(component)
            row["blueprint_path"] = bp_path
            result.append(row)
    result.sort(key=lambda row: (
        str(row.get("blueprint_path", "") or ""),
        str(row.get("variable_name", "") or ""),
        str(row.get("component_class", "") or ""),
    ))
    return result


def build_report(output: Path, rows) -> dict:
    output = Path(output).expanduser().resolve()
    blueprints = _rows_for(rows, output / "blueprints.jsonl")
    component_properties = _rows_for(rows, output / "blueprint_component_properties.jsonl")
    node_references = _rows_for(rows, output / "blueprint_node_references.jsonl")
    defaults = _rows_for(rows, output / "blueprint_defaults.jsonl")
    state_values = _rows_for(rows, output / "blueprint_state_values.jsonl")
    world_components = _rows_for(rows, output / "world_components.jsonl")
    world_properties = _rows_for(rows, output / "world_instance_properties.jsonl")
    world_references = _rows_for(rows, output / "world_references.jsonl")

    mover_components = _component_rows(blueprints)
    component_keys = {
        (
            str(row.get("blueprint_path", "") or ""),
            str(row.get("variable_name", "") or ""),
        )
        for row in mover_components
    }
    mover_blueprints = [
        row for row in blueprints
        if _is_mover_type(row.get("parent_class", ""))
        or _is_mover_type(row.get("generated_class", ""))
    ]
    mover_blueprints.sort(key=lambda row: str(row.get("object_path", "") or ""))
    mover_bp_paths = {
        str(row.get("object_path", "") or row.get("blueprint_path", "") or "")
        for row in mover_blueprints
    }
    mover_bp_paths.update(bp for bp, _ in component_keys if bp)

    authored_component_properties = []
    for row in component_properties:
        bp = str(row.get("blueprint_path", "") or "")
        name = str(row.get("component_name", "") or row.get("owner_name", "") or "")
        owner_class = str(row.get("component_class", "") or row.get("owner_class", "") or "")
        ref_class = str(row.get("referenced_object_class", "") or "")
        if (bp, name) in component_keys or _is_mover_type(owner_class) or _is_mover_type(ref_class):
            authored_component_properties.append(row)
    authored_component_properties.sort(key=lambda row: (
        str(row.get("blueprint_path", "") or ""),
        str(row.get("component_name", "") or row.get("owner_name", "") or ""),
        str(row.get("property_path", "") or row.get("property_name", "") or ""),
        int(row.get("array_index", 0) or 0),
    ))

    mover_defaults = [
        row for row in defaults
        if str(row.get("blueprint_path", "") or "") in mover_bp_paths
        or _is_mover_type(row.get("owner_class", ""))
        or _is_mover_type(row.get("referenced_object_class", ""))
    ]
    mover_state_values = [
        row for row in state_values
        if str(row.get("blueprint_path", "") or "") in mover_bp_paths
        or _is_mover_type(row.get("owner_class", ""))
        or _is_mover_type(row.get("referenced_object_class", ""))
    ]
    mover_node_references = [
        row for row in node_references
        if str(row.get("blueprint_path", "") or "") in mover_bp_paths
        and (_is_mover_type(row.get("target_class", "")) or _is_mover_type(row.get("owner_class", "")))
    ]

    mover_world_components = [
        row for row in world_components if _is_mover_type(row.get("component_class", ""))
    ]
    world_component_ids = {
        str(row.get("component_id", "") or row.get("component_path", "") or "")
        for row in mover_world_components
    }
    mover_world_properties = [
        row for row in world_properties
        if str(row.get("owner_id", "") or "") in world_component_ids
        or _is_mover_type(row.get("owner_class", ""))
        or _is_mover_type(row.get("referenced_object_class", ""))
    ]
    mover_world_references = [
        row for row in world_references
        if str(row.get("owner_id", "") or "") in world_component_ids
        or _is_mover_type(row.get("owner_class", ""))
        or _is_mover_type(row.get("target_class", ""))
    ]

    referenced_classes = collections.Counter()
    property_roots = collections.Counter()
    property_paths = collections.Counter()
    for row in authored_component_properties + mover_defaults + mover_state_values + mover_world_properties:
        ref_class = str(row.get("referenced_object_class", "") or "")
        if ref_class:
            referenced_classes[ref_class] += 1
        root = str(row.get("root_property", "") or row.get("property_name", "") or "")
        if root:
            property_roots[root] += 1
        path = str(row.get("property_path", "") or row.get("property_name", "") or "")
        if path:
            property_paths[path] += 1
    for row in mover_world_references + mover_node_references:
        target_class = str(row.get("target_class", "") or row.get("referenced_object_class", "") or "")
        if target_class:
            referenced_classes[target_class] += 1

    return {
        "output": str(output),
        "mover_blueprints": mover_blueprints,
        "mover_components": mover_components,
        "component_properties": authored_component_properties,
        "defaults": mover_defaults,
        "state_values": mover_state_values,
        "node_references": mover_node_references,
        "world_components": mover_world_components,
        "world_properties": mover_world_properties,
        "world_references": mover_world_references,
        "referenced_classes": referenced_classes,
        "property_roots": property_roots,
        "property_paths": property_paths,
    }


def _short(value: object, limit: int = 240) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _print_counter(title: str, counter: collections.Counter, limit: int = 80) -> None:
    print(f"\n[{title}]")
    if not counter:
        print("<none>")
        return
    for name, count in counter.most_common(limit):
        print(f"  {count:5d}  {name}")
    if len(counter) > limit:
        print(f"  … {len(counter) - limit} more")


def print_report(report: dict, *, limit: int = 200) -> None:
    print("=== MOVER EVIDENCE REPORT ===")
    print(report.get("output", ""))
    print(
        "mover_blueprints={bp} mover_components={components} component_properties={props} "
        "defaults={defaults} state_values={state} node_references={node_refs} "
        "world_components={world_components} world_properties={world_props} world_references={world_refs}".format(
            bp=len(report.get("mover_blueprints", [])),
            components=len(report.get("mover_components", [])),
            props=len(report.get("component_properties", [])),
            defaults=len(report.get("defaults", [])),
            state=len(report.get("state_values", [])),
            node_refs=len(report.get("node_references", [])),
            world_components=len(report.get("world_components", [])),
            world_props=len(report.get("world_properties", [])),
            world_refs=len(report.get("world_references", [])),
        )
    )

    print("\n[Mover-derived Blueprints]")
    values = report.get("mover_blueprints", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        print(
            "  {path} | parent={parent} | generated={generated}".format(
                path=row.get("object_path", "") or row.get("blueprint_path", ""),
                parent=row.get("parent_class", ""),
                generated=row.get("generated_class", ""),
            )
        )

    print("\n[Mover components]")
    values = report.get("mover_components", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        print(
            "  {bp} :: {name} | {cls} | parent={parent} | root={root}".format(
                bp=row.get("blueprint_path", ""),
                name=row.get("variable_name", ""),
                cls=row.get("component_class", ""),
                parent=row.get("parent_component_or_variable", ""),
                root=bool(row.get("is_root", False)),
            )
        )

    print("\n[Authored Mover component properties]")
    values = report.get("component_properties", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        value = row.get("referenced_object_path", "") or row.get("value", "")
        print(
            "  {bp} :: {component} :: {path} | type={cpp} | ref_class={ref_class} | value={value}".format(
                bp=row.get("blueprint_path", ""),
                component=row.get("component_name", "") or row.get("owner_name", ""),
                path=row.get("property_path", "") or row.get("property_name", ""),
                cpp=row.get("cpp_type", "") or row.get("property_type", ""),
                ref_class=row.get("referenced_object_class", ""),
                value=_short(value),
            )
        )
    if len(values) > limit:
        print(f"  … {len(values) - limit} more")

    _print_counter("Mover property roots", report.get("property_roots", collections.Counter()))
    _print_counter("Mover referenced classes", report.get("referenced_classes", collections.Counter()))
    _print_counter("Mover property paths", report.get("property_paths", collections.Counter()), limit=120)

    print("================================")


def install(runtime_module) -> None:
    if getattr(runtime_module, "_mover_report_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "mover-report":
            parser = argparse.ArgumentParser(
                prog="uatool mover-report",
                description="report canonical Mover/ChaosMover evidence from an existing scan",
            )
            parser.add_argument("output", help="source .uatool directory")
            parser.add_argument("--limit", type=int, default=200, help="maximum detailed rows to print")
            args = parser.parse_args(sys.argv[2:])
            if args.limit < 1:
                parser.error("--limit must be >= 1")
            output = Path(args.output).expanduser().resolve()
            report = build_report(output, runtime_module._rows)
            print_report(report, limit=args.limit)
            return 0
        return original_main()

    runtime_module.main = main
    runtime_module._mover_report_installed = True
