#!/usr/bin/env python3
"""Read-only evidence reports for ZoneGraph and Mass in an existing scan.

These commands are intentionally diagnostic. They do not claim semantic ownership
or promote relationships. The broad report discovers relevant UE 5.8 evidence;
the focused report narrows an existing corpus around serialization-critical Mass
and ZoneGraph families before a first-class systems schema is designed.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
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

# Focuses intentionally use exact engine/project identifiers as anchors and more
# general field/type words only as detail signals. A row is never selected merely
# because it contains "Traits", "Points", or "Lanes"; it must first be tied to a
# relevant Mass/ZoneGraph object or authored City Sample system.
FOCUS_DEFINITIONS = {
    "mass-config": {
        "description": "MassEntityConfigAsset composition, traits, inheritance and references",
        "anchors": (
            "/script/massspawner.massentityconfigasset",
            "massentityconfigasset",
            "fmassentityconfig",
            "masscrowdagentconfig",
            "masscrowdpuppetconfig",
            "massplayercharacteragentconfig",
            "citysampleintersectionagentconfig",
            "masstrafficvehicleagentconfig",
            "masstrafficparkedvehicleagentconfig",
            "_trafficvehicleagentconfig",
            "_parkedvehicleagentconfig",
            "_traileragentconfig",
        ),
        "details": (
            "traits",
            "trait",
            "parent",
            "baseconfig",
            "entityconfig",
            "template",
            "tsoftobjectptr<umassentityconfigasset>",
            "tobjectptr<umassentityconfigasset>",
        ),
    },
    "mass-spawner": {
        "description": "MassSpawner entity types, counts, generators and configured asset topology",
        "anchors": (
            "/script/massspawner.massspawner",
            "bp_masscrowdspawner",
            "bp_masstrafficvehiclespawner",
            "bp_masstraffictrailerspawner",
            "bp_masstrafficparkedvehiclespawner",
            "bp_masstrafficintersectionspawner",
            "massentityzonegraphspawnpointsgenerator",
            "masstrafficvehiclespawndatagenerator",
            "masstrafficparkedvehiclespawndatagenerator",
            "masstrafficintersectionspawndatagenerator",
        ),
        "details": (
            "entitytypes",
            "entitytype",
            "spawndatagenerators",
            "spawndatagenerator",
            "entityconfig",
            "count",
            "proportion",
            "density",
            "generator",
            "spawn",
        ),
    },
    "mass-agent": {
        "description": "Actor-side MassAgent/MassTraffic components and authored entity configuration",
        "anchors": (
            "/script/massactors.massagentcomponent",
            "massagentcomponent",
            ":massagent",
            "masstrafficvehiclecomponent",
            ":masstrafficvehicle",
        ),
        "details": (
            "entityconfig",
            "agentconfig",
            "massagent",
            "massentity",
            "config",
            "template",
        ),
    },
    "zone-shape": {
        "description": "ZoneShape authored shape points, tags, lane profiles and routing state",
        "anchors": (
            "/script/zonegraph.zoneshape",
            "/script/zonegraph.zoneshapecomponent",
            "zoneshapecomponent",
            "zoneshape_",
            "citysamplecityzoneshapes",
            "citysamplefreewayzoneshapes",
        ),
        "details": (
            "points",
            "point",
            "laneprofiles",
            "laneprofile",
            "fzonelaneprofileref",
            "tags",
            "fzonegraphtag",
            "shapetype",
            "fzoneshapetype",
            "polygonroutingtype",
            "routing",
            "connections",
            "laneconnections",
        ),
    },
    "zone-data": {
        "description": "ZoneGraphData generated/storage topology including lanes, points and links",
        "anchors": (
            "/script/zonegraph.zonegraphdata",
            "zonegraphdata",
            "zonegraphstorage",
            "fzonegraphstorage",
        ),
        "details": (
            "lanes",
            "lane",
            "lanelinks",
            "lanelink",
            "lanepoints",
            "lanepoint",
            "laneprofiles",
            "laneprofile",
            "bounds",
            "tags",
            "storage",
            "builddata",
        ),
    },
    "bridge": {
        "description": "Exact Mass to ZoneGraph bridge objects, annotations, builders and tags",
        "anchors": (
            "massentityzonegraphspawnpointsgenerator",
            "zonegraphcrowdlaneannotations",
            "zonegraphdisturbanceannotation",
            "smartobjectzoneannotations",
            "zonegraphcloscrowdlanetest",
            "zonegraphclosecrowdlanetest",
            "zonegraphtagfor",
            "masstrafficbuilderbaseactor",
            "masstrafficzonegraphdatamodifier",
            "bp_masstrafficcitytrafficbuilder",
            "bp_masstrafficfreewaytrafficbuilder",
        ),
        "details": (
            "lane",
            "tag",
            "filter",
            "generator",
            "annotation",
            "zonegraphdata",
            "massentity",
            "spawn",
            "build",
        ),
    },
}

FOCUS_NAMES = tuple(FOCUS_DEFINITIONS)


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


def _focus_hits(text: str, definition: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    lowered = text.lower()
    anchors = tuple(value for value in definition["anchors"] if value in lowered)
    if not anchors:
        return (), ()
    details = tuple(value for value in definition["details"] if value in lowered)
    return anchors, details


def _focus_counter_value(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _focus_bucket() -> dict:
    return {
        "matched_rows": 0,
        "high_signal_rows": 0,
        "anchor_counts": collections.Counter(),
        "detail_counts": collections.Counter(),
        "property_counts": collections.Counter(),
        "cpp_type_counts": collections.Counter(),
        "class_counts": collections.Counter(),
        "relation_counts": collections.Counter(),
        "stream_counts": collections.Counter(),
        "examples": collections.defaultdict(lambda: {"high": [], "other": []}),
    }


def build_focus_report(
    output: Path,
    rows,
    *,
    include_source: bool = True,
    focuses: tuple[str, ...] | list[str] | None = None,
    example_limit: int = 40,
) -> dict:
    """Classify existing rows into serialization-critical evidence families.

    The corpus is streamed once. Rows need an exact family anchor; generic detail
    terms only rank already-matching rows so authored property/reference evidence
    is shown ahead of noisy package/file presence rows.
    """
    output = Path(output).expanduser().resolve()
    selected = tuple(focuses or FOCUS_NAMES)
    invalid = [name for name in selected if name not in FOCUS_DEFINITIONS]
    if invalid:
        raise ValueError(f"unknown focus: {', '.join(invalid)}")

    streams = list(BASE_STREAMS)
    if include_source:
        streams.extend(SOURCE_STREAMS)

    buckets = {name: _focus_bucket() for name in selected}
    stream_totals = collections.Counter()

    for filename in streams:
        path = output / filename
        if not path.is_file():
            continue
        for row in _iter_rows(rows, path):
            stream_totals[filename] += 1
            text = _row_text(row)
            for name in selected:
                anchors, details = _focus_hits(text, FOCUS_DEFINITIONS[name])
                if not anchors:
                    continue
                bucket = buckets[name]
                bucket["matched_rows"] += 1
                bucket["stream_counts"][filename] += 1
                bucket["anchor_counts"].update(anchors)
                bucket["detail_counts"].update(details)
                if details:
                    bucket["high_signal_rows"] += 1

                prop = _focus_counter_value(row, ("property_path", "property_name", "root_property"))
                if prop:
                    bucket["property_counts"][prop] += 1
                cpp_type = _focus_counter_value(row, ("cpp_type", "property_type", "struct_type"))
                if cpp_type:
                    bucket["cpp_type_counts"][cpp_type] += 1
                class_value = _focus_counter_value(
                    row,
                    (
                        "class_path", "component_class", "owner_class", "target_class",
                        "referenced_object_class", "baseline_class", "actor_class",
                    ),
                )
                if class_value:
                    bucket["class_counts"][class_value] += 1
                relation = str(row.get("relation", "") or "")
                if relation:
                    bucket["relation_counts"][relation] += 1

                target = "high" if details else "other"
                examples = bucket["examples"][filename][target]
                if len(examples) < example_limit:
                    examples.append(
                        {
                            "anchors": list(anchors),
                            "details": list(details),
                            "row": row,
                        }
                    )

    normalized = {}
    for name, bucket in buckets.items():
        examples = {}
        for filename, groups in bucket["examples"].items():
            high = groups["high"][:example_limit]
            remaining = max(0, example_limit - len(high))
            examples[filename] = high + groups["other"][:remaining]
        normalized[name] = {
            **{key: value for key, value in bucket.items() if key != "examples"},
            "examples": examples,
        }

    return {
        "output": str(output),
        "include_source": bool(include_source),
        "focuses": selected,
        "stream_totals": stream_totals,
        "buckets": normalized,
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


def _print_report_impl(report: dict, *, row_limit: int = 30) -> None:
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


def _print_focus_report_impl(report: dict, *, row_limit: int = 40) -> None:
    print("=== ZONEGRAPH + MASS FOCUSED EVIDENCE REPORT ===")
    print(report.get("output", ""))
    print("diagnostic_only=True semantic_promotion=False")
    print(f"include_source={bool(report.get('include_source', False))}")
    print("focuses=" + ",".join(report.get("focuses", ())))

    for name in report.get("focuses", ()):
        definition = FOCUS_DEFINITIONS[name]
        bucket = report.get("buckets", {}).get(name, {})
        print(f"\n########################################################################")
        print(f"FOCUS: {name}")
        print(definition["description"])
        print(
            f"matched_rows={int(bucket.get('matched_rows', 0) or 0)} "
            f"high_signal_rows={int(bucket.get('high_signal_rows', 0) or 0)}"
        )
        _print_counter("Anchor hits", bucket.get("anchor_counts", collections.Counter()), 80)
        _print_counter("Serialization/detail signals", bucket.get("detail_counts", collections.Counter()), 100)
        _print_counter("Property names/paths", bucket.get("property_counts", collections.Counter()), 160)
        _print_counter("Reflected C++/property types", bucket.get("cpp_type_counts", collections.Counter()), 160)
        _print_counter("Classes", bucket.get("class_counts", collections.Counter()), 160)
        _print_counter("Project/reference relations", bucket.get("relation_counts", collections.Counter()), 100)
        _print_counter("Matched streams", bucket.get("stream_counts", collections.Counter()), 40)

        print("\n[High-signal row examples by stream]")
        examples_by_stream = bucket.get("examples", {})
        for filename in BASE_STREAMS + SOURCE_STREAMS:
            examples = examples_by_stream.get(filename, []) or []
            if not examples:
                continue
            print(f"\n--- {filename} ---")
            for index, example in enumerate(examples[:row_limit]):
                anchors = ", ".join(example.get("anchors", []) or [])
                details = ", ".join(example.get("details", []) or []) or "<anchor-only>"
                raw = json.dumps(
                    example.get("row", {}),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                print(f"[{index}] anchors={anchors}")
                print(f"  details={details}")
                print("  " + _short(raw, 5000))

    print("\n========================================================================")


def render_report(report: dict, *, row_limit: int = 30) -> str:
    """Render the broad report independently of the process console encoding."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_report_impl(report, row_limit=row_limit)
    return buffer.getvalue()


def render_focus_report(report: dict, *, row_limit: int = 40) -> str:
    """Render the focused report independently of the process console encoding."""
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_focus_report_impl(report, row_limit=row_limit)
    return buffer.getvalue()


def _write_console_safe(text: str, stream=None) -> None:
    """Write arbitrary report text without failing on legacy Windows encodings."""
    stream = sys.stdout if stream is None else stream
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        escaped = text.encode(encoding, errors="backslashreplace").decode(encoding)
        stream.write(escaped)
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


def print_report(report: dict, *, row_limit: int = 30, stream=None) -> None:
    _write_console_safe(render_report(report, row_limit=row_limit), stream=stream)


def print_focus_report(report: dict, *, row_limit: int = 40, stream=None) -> None:
    _write_console_safe(render_focus_report(report, row_limit=row_limit), stream=stream)


def _write_utf8_report(path: Path | None, rendered: str) -> None:
    if path is None:
        return
    report_path = path.expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(rendered, encoding="utf-8", newline="\n")


def _broad_cli(runtime_module, argv: list[str]) -> int:
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
        help="also scan source_chunks.jsonl for project/plugin evidence",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="also write the complete report as UTF-8 text",
    )
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    output = Path(args.output).expanduser().resolve()
    report = build_report(
        output,
        runtime_module._rows,
        include_source=args.include_source,
        example_limit=args.limit,
    )
    rendered = render_report(report, row_limit=args.limit)
    _write_utf8_report(args.report, rendered)
    _write_console_safe(rendered)
    return 0


def _focus_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool zonegraph-mass-focus",
        description=(
            "mine focused serialization evidence for Mass/ZoneGraph from an existing "
            "scan without rescanning, deriving, or promoting semantics"
        ),
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument(
        "--focus",
        action="append",
        choices=FOCUS_NAMES,
        help="one evidence family to include; repeatable; defaults to all families",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="maximum matching rows printed per focus per stream",
    )
    parser.add_argument(
        "--no-source",
        action="store_true",
        help="skip source_chunks.jsonl; source evidence is included by default",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="also write the complete focused report as UTF-8 text",
    )
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    output = Path(args.output).expanduser().resolve()
    report = build_focus_report(
        output,
        runtime_module._rows,
        include_source=not args.no_source,
        focuses=tuple(args.focus) if args.focus else None,
        example_limit=args.limit,
    )
    rendered = render_focus_report(report, row_limit=args.limit)
    _write_utf8_report(args.report, rendered)
    _write_console_safe(rendered)
    return 0


def install(runtime_module) -> None:
    input_validation.install(systems)
    if getattr(runtime_module, "_zonegraph_mass_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "zonegraph-mass-evidence":
            return _broad_cli(runtime_module, sys.argv[2:])
        if len(sys.argv) > 1 and sys.argv[1] == "zonegraph-mass-focus":
            return _focus_cli(runtime_module, sys.argv[2:])
        return original_main()

    runtime_module.main = main
    runtime_module._zonegraph_mass_evidence_installed = True
