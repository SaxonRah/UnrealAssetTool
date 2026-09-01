#!/usr/bin/env python3
"""Read-only evidence report for ZoneGraph and Mass in an existing scan.

This module is intentionally diagnostic.  It does not claim semantic ownership or
promote relationships.  It streams broad keyword matches out of already-canonical
and already-derived UnrealAssetTool rows so a real corpus can establish which UE
5.8 classes/properties/references deserve first-class normalization.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys

import uatool_systems as systems
import uatool_systems_input_validation as input_validation

# Deliberately broad enough to catch City Sample custom/plugin classes, but avoid
# the bare word "mass" because it is common English and creates excessive noise.
MARKERS = (
    "/script/mass",
    "massentity",
    "massspawner",
    "masstraffic",
    "masscrowd",
    "masstrait",
    "massprocessor",
    "massrepresentation",
    "massmovement",
    "massnavigation",
    "massagent",
    "masssimulation",
    "massstatetree",
    "masscommander",
    "massavoidance",
    "/script/zonegraph",
    "zonegraph",
    "zoneshape",
    "zonelane",
    "zoneannotation",
)

BASE_STREAMS = (
    "assets.jsonl",
    "files.jsonl",
    "blueprints.jsonl",
    "blueprint_component_properties.jsonl",
    "blueprint_defaults.jsonl",
    "blueprint_state_values.jsonl",
    "blueprint_node_references.jsonl",
    "blueprint_semantic_nodes.jsonl",
    "blueprint_semantic_statements.jsonl",
    "data_table_fields.jsonl",
    "gameplay_tag_dictionary.jsonl",
    "world_actors.jsonl",
    "world_components.jsonl",
    "world_instance_properties.jsonl",
    "world_references.jsonl",
    "systems_assets.jsonl",
    "systems_properties.jsonl",
    "systems_references.jsonl",
    "project_nodes.jsonl",
    "project_edges.jsonl",
)

SOURCE_STREAMS = ("source_chunks.jsonl",)

CLASS_KEYS = {
    "class",
    "class_path",
    "asset_class",
    "parent_class",
    "generated_class",
    "component_class",
    "owner_class",
    "target_class",
    "referenced_object_class",
    "native_class",
    "object_class",
    "struct_type",
    "property_type",
    "cpp_type",
}
PROPERTY_KEYS = {
    "property_name",
    "property_path",
    "root_property",
    "source_property",
    "declaring_property",
}
PATH_KEYS = {
    "asset_path",
    "object_path",
    "systems_path",
    "blueprint_path",
    "component_path",
    "owner_path",
    "target_path",
    "referenced_object_path",
    "package_name",
    "filename",
    "path",
}


def _row_text(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _markers_in_text(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(marker for marker in MARKERS if marker in lowered)


def _walk_values(value, path: str = ""):
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            yield from _walk_values(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            yield from _walk_values(child, child_path)
    elif isinstance(value, (str, int, float, bool)) or value is None:
        yield path, "" if value is None else str(value)


def _leaf_key(path: str) -> str:
    leaf = path.rsplit(".", 1)[-1]
    if "[" in leaf:
        leaf = leaf.split("[", 1)[0]
    return leaf.lower()


def _collect_matched_values(
    row: dict,
    class_values: collections.Counter,
    property_values: collections.Counter,
    path_values: collections.Counter,
    matched_value_keys: collections.Counter,
) -> None:
    for key_path, value in _walk_values(row):
        if not value or not _markers_in_text(value):
            continue
        key = _leaf_key(key_path)
        matched_value_keys[key_path] += 1
        if key in CLASS_KEYS or "class" in key or key.endswith("type"):
            class_values[value] += 1
        if key in PROPERTY_KEYS or "property" in key:
            property_values[value] += 1
        if key in PATH_KEYS or key.endswith("_path") or key.endswith("path"):
            path_values[value] += 1


def _iter_rows(rows, path: Path):
    if not path.is_file():
        return
    for row in rows(path):
        if isinstance(row, dict):
            yield row


def build_report(
    output: Path,
    rows,
    *,
    include_source: bool = False,
    example_limit: int = 30,
) -> dict:
    output = Path(output).expanduser().resolve()
    streams = list(BASE_STREAMS)
    if include_source:
        streams.extend(SOURCE_STREAMS)

    stream_stats: dict[str, dict] = {}
    marker_counts = collections.Counter()
    class_values = collections.Counter()
    property_values = collections.Counter()
    path_values = collections.Counter()
    matched_value_keys = collections.Counter()
    relation_counts = collections.Counter()

    for filename in streams:
        path = output / filename
        total = 0
        matched = 0
        examples: list[dict] = []
        if path.is_file():
            for row in _iter_rows(rows, path):
                total += 1
                text = _row_text(row)
                markers = _markers_in_text(text)
                if not markers:
                    continue
                matched += 1
                marker_counts.update(markers)
                _collect_matched_values(
                    row,
                    class_values,
                    property_values,
                    path_values,
                    matched_value_keys,
                )
                relation = str(row.get("relation", "") or "")
                if relation:
                    relation_counts[relation] += 1
                if len(examples) < example_limit:
                    examples.append({"markers": list(markers), "row": row})
        stream_stats[filename] = {
            "exists": path.is_file(),
            "total_rows": total,
            "matched_rows": matched,
            "examples": examples,
        }

    return {
        "output": str(output),
        "include_source": bool(include_source),
        "stream_stats": stream_stats,
        "marker_counts": marker_counts,
        "class_values": class_values,
        "property_values": property_values,
        "path_values": path_values,
        "matched_value_keys": matched_value_keys,
        "relation_counts": relation_counts,
    }


def _short(value: object, limit: int = 1200) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _print_counter(title: str, counter: collections.Counter, limit: int = 100) -> None:
    print(f"\n[{title}]")
    if not counter:
        print("<none>")
        return
    for value, count in counter.most_common(limit):
        print(f"  {count:7d}  {_short(value, 600)}")
    if len(counter) > limit:
        print(f"  … {len(counter) - limit} more")


def print_report(report: dict, *, row_limit: int = 30) -> None:
    print("=== ZONEGRAPH + MASS EVIDENCE REPORT ===")
    print(report.get("output", ""))
    print("diagnostic_only=True semantic_promotion=False")
    print(f"include_source={bool(report.get('include_source', False))}")

    stats = report.get("stream_stats", {})
    total_rows = sum(int(item.get("total_rows", 0) or 0) for item in stats.values())
    matched_rows = sum(int(item.get("matched_rows", 0) or 0) for item in stats.values())
    print(f"streams={len(stats)} total_rows={total_rows} matched_rows={matched_rows}")

    print("\n[Stream counts]")
    for filename, item in stats.items():
        exists = bool(item.get("exists", False))
        print(
            f"  {filename:42s} exists={str(exists):5s} "
            f"rows={int(item.get('total_rows', 0) or 0):9d} "
            f"matched={int(item.get('matched_rows', 0) or 0):7d}"
        )

    _print_counter("Matched markers", report.get("marker_counts", collections.Counter()), 80)
    _print_counter("Matched classes/types", report.get("class_values", collections.Counter()), 160)
    _print_counter("Matched property names/paths", report.get("property_values", collections.Counter()), 160)
    _print_counter("Matched asset/object/package paths", report.get("path_values", collections.Counter()), 200)
    _print_counter("Matched project-edge relations", report.get("relation_counts", collections.Counter()), 100)
    _print_counter("Matched JSON key paths", report.get("matched_value_keys", collections.Counter()), 160)

    print("\n[Matched row examples by stream]")
    for filename, item in stats.items():
        examples = item.get("examples", []) or []
        if not examples:
            continue
        print(f"\n--- {filename} ({item.get('matched_rows', 0)} matched) ---")
        for index, example in enumerate(examples[:row_limit]):
            row = example.get("row", {})
            markers = ", ".join(example.get("markers", []) or [])
            raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            print(f"[{index}] markers={markers}")
            print("  " + _short(raw, 2400))
        if int(item.get("matched_rows", 0) or 0) > len(examples[:row_limit]):
            remaining = int(item.get("matched_rows", 0) or 0) - len(examples[:row_limit])
            print(f"  … {remaining} additional matched rows not printed")

    print("========================================")


def install(runtime_module) -> None:
    input_validation.install(systems)
    if getattr(runtime_module, "_zonegraph_mass_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "zonegraph-mass-evidence":
            parser = argparse.ArgumentParser(
                prog="uatool zonegraph-mass-evidence",
                description=(
                    "stream broad ZoneGraph/Mass evidence from an existing scan without "
                    "promoting any semantic relationships"
                ),
            )
            parser.add_argument("output", help="source .uatool directory")
            parser.add_argument(
                "--limit",
                type=int,
                default=30,
                help="maximum matching rows printed per stream",
            )
            parser.add_argument(
                "--include-source",
                action="store_true",
                help="also scan source_chunks.jsonl for City Sample/custom plugin evidence",
            )
            args = parser.parse_args(sys.argv[2:])
            if args.limit < 1:
                parser.error("--limit must be >= 1")
            output = Path(args.output).expanduser().resolve()
            report = build_report(
                output,
                runtime_module._rows,
                include_source=args.include_source,
                example_limit=args.limit,
            )
            print_report(report, row_limit=args.limit)
            return 0
        return original_main()

    runtime_module.main = main
    runtime_module._zonegraph_mass_evidence_installed = True
