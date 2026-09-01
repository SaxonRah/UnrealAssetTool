#!/usr/bin/env python3
"""Read-only report of canonical Gameplay Cameras evidence in an existing scan."""
from __future__ import annotations

import argparse
import collections
from pathlib import Path
import sys

CAMERA_MARKER = "/script/gameplaycameras."


def _rows_for(rows, path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [row for row in rows(path) if isinstance(row, dict)]


def _contains_camera(value: object) -> bool:
    if isinstance(value, dict):
        return any(_contains_camera(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_camera(item) for item in value)
    return CAMERA_MARKER in str(value or "").lower()


def _first(row: dict, *names: str) -> str:
    for name in names:
        value = str(row.get(name, "") or "")
        if value:
            return value
    return ""


def _class_of(row: dict) -> str:
    return _first(
        row,
        "class_path",
        "asset_class_path",
        "asset_class",
        "component_class",
        "owner_class",
        "target_class",
        "referenced_object_class",
        "object_class",
        "node_class",
    )


def _path_of(row: dict) -> str:
    return _first(
        row,
        "object_path",
        "asset_path",
        "systems_path",
        "target_path",
        "target_object_path",
        "referenced_object_path",
        "component_path",
        "owner_path",
    )


def _blueprint_components(blueprints: list[dict]) -> list[dict]:
    result: list[dict] = []
    for blueprint in blueprints:
        bp_path = _first(blueprint, "object_path", "blueprint_path")
        for component in blueprint.get("components", []) or []:
            if not isinstance(component, dict):
                continue
            if CAMERA_MARKER not in str(component.get("component_class", "") or "").lower():
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


def _matching_rows(values: list[dict], *, extra=None) -> list[dict]:
    result = []
    for row in values:
        if _contains_camera(row) or (extra is not None and extra(row)):
            result.append(row)
    return result


def build_report(output: Path, rows) -> dict:
    output = Path(output).expanduser().resolve()

    assets = _rows_for(rows, output / "assets.jsonl")
    blueprints = _rows_for(rows, output / "blueprints.jsonl")
    component_properties = _rows_for(rows, output / "blueprint_component_properties.jsonl")
    node_properties = _rows_for(rows, output / "blueprint_node_properties.jsonl")
    node_references = _rows_for(rows, output / "blueprint_node_references.jsonl")
    defaults = _rows_for(rows, output / "blueprint_defaults.jsonl")
    state_values = _rows_for(rows, output / "blueprint_state_values.jsonl")
    systems_assets = _rows_for(rows, output / "systems_assets.jsonl")
    systems_properties = _rows_for(rows, output / "systems_properties.jsonl")
    systems_references = _rows_for(rows, output / "systems_references.jsonl")
    world_components = _rows_for(rows, output / "world_components.jsonl")
    world_properties = _rows_for(rows, output / "world_instance_properties.jsonl")
    world_references = _rows_for(rows, output / "world_references.jsonl")

    camera_assets = _matching_rows(assets)
    camera_blueprints = [
        row for row in blueprints
        if _contains_camera(row.get("parent_class", ""))
        or _contains_camera(row.get("generated_class", ""))
    ]
    camera_components = _blueprint_components(blueprints)
    component_keys = {
        (
            str(row.get("blueprint_path", "") or ""),
            str(row.get("variable_name", "") or ""),
        )
        for row in camera_components
    }

    def component_match(row: dict) -> bool:
        return (
            str(row.get("blueprint_path", "") or ""),
            str(row.get("component_name", "") or row.get("owner_name", "") or ""),
        ) in component_keys

    camera_component_properties = _matching_rows(component_properties, extra=component_match)
    camera_node_properties = _matching_rows(node_properties)
    camera_node_references = _matching_rows(node_references)
    camera_defaults = _matching_rows(defaults)
    camera_state_values = _matching_rows(state_values)
    camera_systems_assets = _matching_rows(systems_assets)
    camera_systems_properties = _matching_rows(systems_properties)
    camera_systems_references = _matching_rows(systems_references)
    camera_world_components = _matching_rows(world_components)
    camera_world_properties = _matching_rows(world_properties)
    camera_world_references = _matching_rows(world_references)

    referenced_classes = collections.Counter()
    property_roots = collections.Counter()
    asset_classes = collections.Counter()
    component_classes = collections.Counter()

    for row in camera_assets + camera_systems_assets:
        cls = _class_of(row)
        if cls:
            asset_classes[cls] += 1

    for row in camera_components + camera_world_components:
        cls = _class_of(row)
        if cls:
            component_classes[cls] += 1

    property_rows = (
        camera_component_properties
        + camera_node_properties
        + camera_defaults
        + camera_state_values
        + camera_systems_properties
        + camera_world_properties
    )
    for row in property_rows:
        root = _first(row, "root_property", "property_name")
        if root:
            property_roots[root] += 1
        cls = _first(row, "referenced_object_class", "object_class", "target_class")
        if cls:
            referenced_classes[cls] += 1

    for row in (
        camera_node_references
        + camera_systems_references
        + camera_world_references
    ):
        cls = _first(row, "target_class", "referenced_object_class", "object_class")
        if cls:
            referenced_classes[cls] += 1

    return {
        "output": str(output),
        "assets": camera_assets,
        "blueprints": camera_blueprints,
        "components": camera_components,
        "component_properties": camera_component_properties,
        "node_properties": camera_node_properties,
        "node_references": camera_node_references,
        "defaults": camera_defaults,
        "state_values": camera_state_values,
        "systems_assets": camera_systems_assets,
        "systems_properties": camera_systems_properties,
        "systems_references": camera_systems_references,
        "world_components": camera_world_components,
        "world_properties": camera_world_properties,
        "world_references": camera_world_references,
        "asset_classes": asset_classes,
        "component_classes": component_classes,
        "property_roots": property_roots,
        "referenced_classes": referenced_classes,
    }


def _short(value: object, limit: int = 280) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _print_counter(title: str, counter: collections.Counter, limit: int = 80) -> None:
    print(f"\n[{title}]")
    if not counter:
        print("<none>")
        return
    for name, count in counter.most_common(limit):
        print(f"  {count:5d}  {name}")


def _print_rows(title: str, values: list[dict], *, limit: int) -> None:
    print(f"\n[{title}]")
    if not values:
        print("<none>")
        return
    for row in values[:limit]:
        path = _path_of(row)
        cls = _class_of(row)
        prop = _first(row, "property_path", "property_name", "root_property")
        target = _first(row, "target_path", "target_object_path", "referenced_object_path", "object_path")
        value = _first(row, "value", "raw_value")
        bits = []
        if path:
            bits.append(path)
        if cls:
            bits.append(f"class={cls}")
        if prop:
            bits.append(f"property={prop}")
        if target and target != path:
            bits.append(f"target={target}")
        if value:
            bits.append(f"value={_short(value)}")
        if not bits:
            bits.append(_short(row))
        print("  " + " | ".join(bits))
    if len(values) > limit:
        print(f"  … {len(values) - limit} more")


def print_report(report: dict, *, limit: int = 250) -> None:
    print("=== GAMEPLAY CAMERAS EVIDENCE REPORT ===")
    print(report.get("output", ""))
    print(
        "assets={assets} blueprints={blueprints} components={components} component_properties={component_props} "
        "node_properties={node_props} node_references={node_refs} defaults={defaults} state_values={state} "
        "systems_assets={systems_assets} systems_properties={systems_props} systems_references={systems_refs} "
        "world_components={world_components} world_properties={world_props} world_references={world_refs}".format(
            assets=len(report.get("assets", [])),
            blueprints=len(report.get("blueprints", [])),
            components=len(report.get("components", [])),
            component_props=len(report.get("component_properties", [])),
            node_props=len(report.get("node_properties", [])),
            node_refs=len(report.get("node_references", [])),
            defaults=len(report.get("defaults", [])),
            state=len(report.get("state_values", [])),
            systems_assets=len(report.get("systems_assets", [])),
            systems_props=len(report.get("systems_properties", [])),
            systems_refs=len(report.get("systems_references", [])),
            world_components=len(report.get("world_components", [])),
            world_props=len(report.get("world_properties", [])),
            world_refs=len(report.get("world_references", [])),
        )
    )

    print("\n[Gameplay Camera Blueprint components]")
    values = report.get("components", [])
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

    _print_rows("Gameplay Camera Asset Registry evidence", report.get("assets", []), limit=limit)
    _print_rows("Authored Gameplay Camera component properties", report.get("component_properties", []), limit=limit)
    _print_rows("Gameplay Camera node references", report.get("node_references", []), limit=limit)
    _print_rows("Gameplay Camera systems assets", report.get("systems_assets", []), limit=limit)
    _print_rows("Gameplay Camera systems properties", report.get("systems_properties", []), limit=limit)
    _print_rows("Gameplay Camera systems references", report.get("systems_references", []), limit=limit)
    _print_rows("Gameplay Camera world components", report.get("world_components", []), limit=limit)
    _print_rows("Gameplay Camera world references", report.get("world_references", []), limit=limit)

    _print_counter("Gameplay Camera asset classes", report.get("asset_classes", collections.Counter()))
    _print_counter("Gameplay Camera component classes", report.get("component_classes", collections.Counter()))
    _print_counter("Gameplay Camera property roots", report.get("property_roots", collections.Counter()))
    _print_counter("Gameplay Camera referenced classes", report.get("referenced_classes", collections.Counter()))
    print("========================================")


def install(runtime_module) -> None:
    if getattr(runtime_module, "_gameplay_camera_report_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "gameplay-camera-report":
            parser = argparse.ArgumentParser(
                prog="uatool gameplay-camera-report",
                description="report canonical Gameplay Cameras evidence from an existing scan",
            )
            parser.add_argument("output", help="source .uatool directory")
            parser.add_argument("--limit", type=int, default=250, help="maximum detailed rows per section")
            args = parser.parse_args(sys.argv[2:])
            if args.limit < 1:
                parser.error("--limit must be >= 1")
            output = Path(args.output).expanduser().resolve()
            report = build_report(output, runtime_module._rows)
            print_report(report, limit=args.limit)
            return 0
        return original_main()

    runtime_module.main = main
    runtime_module._gameplay_camera_report_installed = True
