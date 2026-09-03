#!/usr/bin/env python3
"""Read-only authored Navigation evidence inventory.

This diagnostic does not define a new systems/world schema. It inventories what
the current canonical/derived corpus can already prove about authored UE 5.8
Navigation inputs: area classes/defaults, modifier actors/components, simple and
smart links, navigation invokers, supported-agent/project settings, bounds
volumes and authored Blueprint/source use.

Generated Recast/NavMesh data is deliberately treated as boundary evidence, not
as a semantic source for authored navigation topology.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
from pathlib import Path
import sys

BASE_STREAMS = (
    "files.jsonl",
    "assets.jsonl",
    "asset_dependencies.jsonl",
    "blueprints.jsonl",
    "blueprint_component_properties.jsonl",
    "blueprint_state_values.jsonl",
    "blueprint_node_properties.jsonl",
    "blueprint_node_references.jsonl",
    "blueprint_semantic_nodes.jsonl",
    "blueprint_semantic_statements.jsonl",
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

MARKERS = (
    "/script/navigationsystem.",
    "/script/aimodule.navlinkproxy",
    "navmeshboundsvolume",
    "navmodifiervolume",
    "navmodifiercomponent",
    "navigationinvokercomponent",
    "navlinkproxy",
    "navlinkcustomcomponent",
    "navarea",
    "pointlinks",
    "segmentlinks",
    "smartlink",
    "areaclass",
    "areaclasstoreplace",
    "defaultcost",
    "fixedareaenteringcost",
    "supportedagents",
    "supportedagentsmask",
    "defaultagentname",
    "agentradius",
    "agentheight",
    "agentstepheight",
    "agentmaxslope",
    "defaultqueryextent",
    "generationradius",
    "removalradius",
    "runtimegeneration",
    "recastnavmesh",
)

FOCUS_DEFINITIONS = {
    "areas": {
        "description": "Navigation Area classes/defaults and supported-agent restrictions",
        "anchors": ("navarea", "defaultcost", "fixedareaenteringcost"),
        "details": (
            "defaultcost", "fixedareaenteringcost", "supportedagents", "supportedagentsbits",
            "drawcolor", "bSupportsAgent".lower(),
        ),
    },
    "modifiers": {
        "description": "NavModifierVolume/NavModifierComponent authored area application and replacement state",
        "anchors": ("navmodifiervolume", "navmodifiercomponent", "areaclasstoreplace"),
        "details": ("areaclass", "areaclasstoreplace", "includeagentheight", "failsafetolerance"),
    },
    "links": {
        "description": "NavLinkProxy simple/segment/smart-link authored topology and area policy",
        "anchors": ("navlinkproxy", "navlinkcustomcomponent", "pointlinks", "segmentlinks", "smartlink"),
        "details": (
            "pointlinks", "segmentlinks", "left", "right", "direction", "areaclass",
            "supportedagents", "smartlinkcomp", "smartlinkisrelevant", "enabledareaclass", "disabledareaclass",
        ),
    },
    "invokers": {
        "description": "NavigationInvokerComponent authored generation/removal radii and agent selection",
        "anchors": ("navigationinvokercomponent", "generationradius", "removalradius"),
        "details": ("generationradius", "removalradius", "supportedagents", "priority"),
    },
    "system_agents": {
        "description": "Navigation System/project settings and supported-agent configuration",
        "anchors": ("navigationsystemv1", "supportedagents", "defaultagentname", "navdataconfig"),
        "details": (
            "supportedagents", "supportedagentsmask", "defaultagentname", "agentradius", "agentheight",
            "agentstepheight", "agentmaxslope", "defaultqueryextent", "runtimegeneration",
            "navigationdataclassname", "navdatasclassname",
        ),
    },
    "bounds_usage": {
        "description": "NavMeshBoundsVolume placement plus authored Blueprint/source navigation API use",
        "anchors": (
            "navmeshboundsvolume", "projectpointtonavigation", "findpathto", "findpathsync",
            "getrandomreachablepoint", "getrandompointinnavigableradius", "navigationinvoker",
        ),
        "details": ("call", "function", "event", "actor", "component", "bounds", "navigation"),
    },
}
FOCUS_NAMES = tuple(FOCUS_DEFINITIONS)

EXACT_CLASS_KINDS = {
    "/script/navigationsystem.navmeshboundsvolume": "navmesh_bounds_volume",
    "/script/navigationsystem.navmodifiervolume": "nav_modifier_volume",
    "/script/navigationsystem.navmodifiercomponent": "nav_modifier_component",
    "/script/navigationsystem.navigationinvokercomponent": "navigation_invoker_component",
    "/script/aimodule.navlinkproxy": "nav_link_proxy",
    "/script/navigationsystem.navlinkcustomcomponent": "nav_link_custom_component",
    "/script/navigationsystem.recastnavmesh": "recast_navmesh_generated",
    "/script/navigationsystem.navigationsystemv1": "navigation_system",
}


def _row_text(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iter_rows(rows, path: Path):
    if not path.is_file():
        return
    for row in rows(path):
        if isinstance(row, dict):
            yield row


def _value(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _hits(text: str, values) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(value for value in values if value.lower() in lowered)


def _bucket() -> dict:
    return {
        "matched_rows": 0,
        "high_signal_rows": 0,
        "anchor_counts": collections.Counter(),
        "detail_counts": collections.Counter(),
        "stream_counts": collections.Counter(),
        "class_counts": collections.Counter(),
        "property_counts": collections.Counter(),
        "relation_counts": collections.Counter(),
        "examples": collections.defaultdict(lambda: {"high": [], "other": []}),
    }


def _normalized_class(value: str) -> str:
    return str(value or "").strip().lower()


def _class_kind(value: str) -> str:
    return EXACT_CLASS_KINDS.get(_normalized_class(value), "")


def build_report(
    output: Path,
    rows,
    *,
    include_source: bool = True,
    focuses: tuple[str, ...] | list[str] | None = None,
    example_limit: int = 30,
) -> dict:
    output = Path(output).expanduser().resolve()
    selected = tuple(focuses or FOCUS_NAMES)
    invalid = [name for name in selected if name not in FOCUS_DEFINITIONS]
    if invalid:
        raise ValueError(f"unknown Navigation focus: {', '.join(invalid)}")
    if example_limit < 1:
        raise ValueError("example_limit must be >= 1")

    streams = list(BASE_STREAMS)
    if include_source:
        streams.extend(SOURCE_STREAMS)

    buckets = {name: _bucket() for name in selected}
    marker_counts = collections.Counter()
    stream_totals = collections.Counter()
    exact_class_rows = collections.Counter()

    exact_objects: dict[str, set[str]] = collections.defaultdict(set)
    nav_area_blueprints: set[str] = set()
    modifier_area_owners: set[str] = set()
    link_topology_owners: set[str] = set()
    invoker_setting_owners: set[str] = set()
    supported_agent_owners: set[str] = set()
    nav_system_setting_owners: set[str] = set()
    navigation_reference_rows = 0
    navigation_usage_rows: set[str] = set()
    generated_navigation_rows = 0

    for filename in streams:
        path = output / filename
        if not path.is_file():
            continue
        for line_number, row in enumerate(_iter_rows(rows, path), 1):
            stream_totals[filename] += 1
            text = _row_text(row)
            lowered = text.lower()
            marker_counts.update(_hits(text, MARKERS))

            class_value = _value(row, (
                "class_path", "class", "asset_class", "component_class", "owner_class",
                "target_class", "referenced_object_class", "actor_class", "node_class",
                "generated_class", "parent_class",
            ))
            prop = _value(row, (
                "property_path", "property_name", "root_property", "source_property", "field_name", "name",
            ))
            owner = _value(row, (
                "component_path", "owner_path", "owner_id", "object_path", "asset_path", "blueprint_path",
                "actor_path", "systems_path", "source", "path",
            ))
            relation = str(row.get("relation", "") or "")

            kind = _class_kind(class_value)
            if kind:
                exact_class_rows[kind] += 1
                identity = owner or f"{filename}:{line_number}"
                exact_objects[kind].add(identity)
                if kind == "recast_navmesh_generated":
                    generated_navigation_rows += 1

            if filename == "blueprints.jsonl":
                parent = _normalized_class(_value(row, ("parent_class", "parent_class_path", "native_parent_class")))
                if parent in {
                    "/script/navigationsystem.navarea",
                    "/script/navigationsystem.navarea_default",
                    "/script/navigationsystem.navarea_obstacle",
                    "/script/navigationsystem.navarea_null",
                }:
                    bp = _value(row, ("blueprint_path", "asset_path", "object_path"))
                    if bp:
                        nav_area_blueprints.add(bp)

            prop_lower = prop.lower()
            if prop_lower in {"areaclass", "areaclasstoreplace"} or "areaclass" in prop_lower:
                if any(token in lowered for token in ("navmodifier", "navmodifiervolume", "navmodifiercomponent")):
                    modifier_area_owners.add(owner or f"{filename}:{line_number}")
            if any(token in prop_lower for token in (
                "pointlinks", "segmentlinks", "smartlink", "left", "right", "direction",
                "enabledareaclass", "disabledareaclass",
            )) and any(token in lowered for token in ("navlink", "smartlink")):
                link_topology_owners.add(owner or f"{filename}:{line_number}")
            if any(token in prop_lower for token in ("generationradius", "removalradius")):
                invoker_setting_owners.add(owner or f"{filename}:{line_number}")
            if any(token in prop_lower for token in ("supportedagents", "supportedagentsmask")):
                supported_agent_owners.add(owner or f"{filename}:{line_number}")
            if any(token in prop_lower for token in (
                "defaultagentname", "supportedagents", "agentradius", "agentheight", "agentstepheight",
                "agentmaxslope", "defaultqueryextent", "runtimegeneration",
            )) and any(token in lowered for token in ("navigationsystem", "recastnavmesh", "navdata", "supportedagents")):
                nav_system_setting_owners.add(owner or f"{filename}:{line_number}")

            if filename in ("world_references.jsonl", "systems_references.jsonl", "blueprint_node_references.jsonl"):
                if any(token in lowered for token in (
                    "navigationsystem", "navarea", "navlink", "navmodifier", "navigationinvoker", "recastnavmesh",
                )):
                    navigation_reference_rows += 1

            if filename in (
                "blueprint_semantic_nodes.jsonl", "blueprint_semantic_statements.jsonl",
                "blueprint_node_properties.jsonl", "blueprint_node_references.jsonl", "source_chunks.jsonl",
            ) and any(token in lowered for token in FOCUS_DEFINITIONS["bounds_usage"]["anchors"]):
                navigation_usage_rows.add(f"{filename}:{line_number}")

            if "recastnavmesh" in lowered and kind != "recast_navmesh_generated":
                generated_navigation_rows += 1

            for name in selected:
                definition = FOCUS_DEFINITIONS[name]
                anchors = _hits(text, definition["anchors"])
                if not anchors:
                    continue
                details = _hits(text, definition["details"])
                bucket = buckets[name]
                bucket["matched_rows"] += 1
                bucket["stream_counts"][filename] += 1
                bucket["anchor_counts"].update(anchors)
                bucket["detail_counts"].update(details)
                if details:
                    bucket["high_signal_rows"] += 1
                if class_value:
                    bucket["class_counts"][class_value] += 1
                if prop:
                    bucket["property_counts"][prop] += 1
                if relation:
                    bucket["relation_counts"][relation] += 1
                group = "high" if details else "other"
                examples = bucket["examples"][filename][group]
                if len(examples) < example_limit:
                    examples.append({"anchors": list(anchors), "details": list(details), "row": row})

    proof = collections.Counter({
        "unique_navmesh_bounds_volumes": len(exact_objects["navmesh_bounds_volume"]),
        "unique_nav_modifier_volumes": len(exact_objects["nav_modifier_volume"]),
        "unique_nav_modifier_components": len(exact_objects["nav_modifier_component"]),
        "unique_nav_link_proxies": len(exact_objects["nav_link_proxy"]),
        "unique_nav_link_custom_components": len(exact_objects["nav_link_custom_component"]),
        "unique_navigation_invoker_components": len(exact_objects["navigation_invoker_component"]),
        "unique_navigation_system_objects": len(exact_objects["navigation_system"]),
        "unique_recast_navmesh_objects": len(exact_objects["recast_navmesh_generated"]),
        "unique_nav_area_blueprints": len(nav_area_blueprints),
        "modifier_area_owners": len(modifier_area_owners),
        "link_topology_owners": len(link_topology_owners),
        "invoker_setting_owners": len(invoker_setting_owners),
        "supported_agent_owners": len(supported_agent_owners),
        "navigation_system_setting_owners": len(nav_system_setting_owners),
        "navigation_reference_rows": navigation_reference_rows,
        "navigation_usage_rows": len(navigation_usage_rows),
        "generated_navigation_rows": generated_navigation_rows,
    })

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

    authored_actor_count = (
        len(exact_objects["navmesh_bounds_volume"])
        + len(exact_objects["nav_modifier_volume"])
        + len(exact_objects["nav_link_proxy"])
    )
    authored_component_count = (
        len(exact_objects["nav_modifier_component"])
        + len(exact_objects["navigation_invoker_component"])
        + len(exact_objects["nav_link_custom_component"])
    )

    gaps: list[str] = []
    if not authored_actor_count and not authored_component_count and not nav_area_blueprints and not nav_system_setting_owners:
        gaps.append(
            "No authored Navigation actor/component/area/config evidence is proven in this corpus; use a more representative project before schema design."
        )
    if (exact_objects["nav_modifier_volume"] or exact_objects["nav_modifier_component"]) and not modifier_area_owners:
        gaps.append(
            "Navigation modifiers are proven, but their AreaClass/AreaClassToReplace authored state is not anchored in current canonical property rows; focused native reflection is required."
        )
    if exact_objects["nav_link_proxy"] and not link_topology_owners:
        gaps.append(
            "NavLinkProxy actors are proven, but PointLinks/SegmentLinks/smart-link endpoints and area policy are not normalized in current rows; focused native link capture is required."
        )
    if exact_objects["navigation_invoker_component"] and not invoker_setting_owners:
        gaps.append(
            "NavigationInvokerComponent is proven, but generation/removal radii are not anchored in current rows; focused native/default-state capture is required."
        )
    if nav_area_blueprints and not any(
        token in marker_counts for token in ("defaultcost", "fixedareaenteringcost", "supportedagents")
    ):
        gaps.append(
            "NavArea-derived Blueprint classes are proven, but traversal cost/agent defaults are not recovered as dedicated facts."
        )
    if exact_objects["navmesh_bounds_volume"] and not (
        exact_objects["nav_modifier_volume"] or exact_objects["nav_link_proxy"] or nav_area_blueprints or nav_system_setting_owners
    ):
        gaps.append(
            "NavMeshBoundsVolume placement alone proves navigation coverage intent but is insufficient to design a first-class authored Navigation schema."
        )
    if generated_navigation_rows:
        gaps.append(
            "Generated Recast/NavMesh evidence is present and must remain boundary-only; do not promote tile/poly/generated connectivity into the authored Navigation model."
        )

    return {
        "output": str(output),
        "diagnostic_only": True,
        "semantic_promotion": False,
        "schema_promotion": False,
        "runtime_state_captured": False,
        "generated_navmesh_promoted": False,
        "include_source": bool(include_source),
        "focuses": selected,
        "stream_totals": stream_totals,
        "marker_counts": marker_counts,
        "exact_class_rows": exact_class_rows,
        "proof": proof,
        "exact_objects": {key: sorted(value) for key, value in sorted(exact_objects.items())},
        "nav_area_blueprints": sorted(nav_area_blueprints),
        "gaps": gaps,
        "buckets": normalized,
    }


def _short(value: object, limit: int = 4000) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _print_counter(title: str, counter: collections.Counter, limit: int = 80) -> None:
    print(f"\n[{title}]")
    if not counter:
        print("<none>")
        return
    for value, count in counter.most_common(limit):
        print(f"  {count:7d}  {_short(value, 700)}")


def _print_impl(report: dict, *, row_limit: int = 30) -> None:
    print("=== AUTHORED NAVIGATION EVIDENCE REPORT ===")
    print(report.get("output", ""))
    print(
        "diagnostic_only=True semantic_promotion=False schema_promotion=False "
        "runtime_state_captured=False generated_navmesh_promoted=False"
    )
    print(f"include_source={bool(report.get('include_source', False))}")
    print("focuses=" + ",".join(report.get("focuses", ())))
    _print_counter("Corpus proof", collections.Counter(report.get("proof", {})), 80)
    _print_counter("Exact authored/generated class rows", collections.Counter(report.get("exact_class_rows", {})), 80)

    exact_objects = report.get("exact_objects", {})
    for family in (
        "navmesh_bounds_volume", "nav_modifier_volume", "nav_modifier_component", "nav_link_proxy",
        "nav_link_custom_component", "navigation_invoker_component", "navigation_system", "recast_navmesh_generated",
    ):
        values = exact_objects.get(family, []) or []
        if not values:
            continue
        print(f"\n[{family} objects]")
        for value in values[:200]:
            print("  " + value)

    if report.get("nav_area_blueprints"):
        print("\n[NavArea-derived Blueprints]")
        for value in report["nav_area_blueprints"][:200]:
            print("  " + value)

    print("\n[Evidence gaps / next capture requirements]")
    gaps = report.get("gaps", [])
    if not gaps:
        print("  <none identified by this diagnostic>")
    for gap in gaps:
        print("  - " + gap)

    for name in report.get("focuses", ()):
        definition = FOCUS_DEFINITIONS[name]
        bucket = report.get("buckets", {}).get(name, {})
        print("\n########################################################################")
        print(f"FOCUS: {name}")
        print(definition["description"])
        print(
            f"matched_rows={int(bucket.get('matched_rows', 0) or 0)} "
            f"high_signal_rows={int(bucket.get('high_signal_rows', 0) or 0)}"
        )
        _print_counter("Anchor hits", bucket.get("anchor_counts", collections.Counter()))
        _print_counter("Detail signals", bucket.get("detail_counts", collections.Counter()))
        _print_counter("Classes", bucket.get("class_counts", collections.Counter()), 120)
        _print_counter("Property names/paths", bucket.get("property_counts", collections.Counter()), 120)
        _print_counter("Project/reference relations", bucket.get("relation_counts", collections.Counter()))
        _print_counter("Matched streams", bucket.get("stream_counts", collections.Counter()), 40)

        print("\n[High-signal row examples by stream]")
        examples_by_stream = bucket.get("examples", {})
        for filename in BASE_STREAMS + SOURCE_STREAMS:
            examples = examples_by_stream.get(filename, []) or []
            if not examples:
                continue
            print(f"\n--- {filename} ---")
            for index, example in enumerate(examples[:row_limit]):
                print(f"[{index}] anchors={', '.join(example.get('anchors', []) or [])}")
                print(f"  details={', '.join(example.get('details', []) or []) or '<anchor-only>'}")
                raw = json.dumps(example.get("row", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                print("  " + _short(raw))
    print("\n========================================================================")


def render_report(report: dict, *, row_limit: int = 30) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _print_impl(report, row_limit=row_limit)
    return buffer.getvalue()


def _write_console_safe(text: str, stream=None) -> None:
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


def _cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool navigation-evidence",
        description="inventory existing authored Navigation evidence without changing the corpus or defining a new schema",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("--focus", action="append", choices=FOCUS_NAMES, help="limit to one or more evidence families")
    parser.add_argument("--no-source", action="store_true", help="skip source_chunks.jsonl")
    parser.add_argument("--row-limit", type=int, default=30, help="maximum example rows printed per focus/stream")
    parser.add_argument("--report", help="optional UTF-8 report path")
    args = parser.parse_args(argv)
    if args.row_limit < 1:
        parser.error("--row-limit must be >= 1")
    output = Path(args.output).expanduser().resolve()
    if not output.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {output}")
    report = build_report(
        output,
        runtime_module._rows,
        include_source=not args.no_source,
        focuses=tuple(args.focus) if args.focus else None,
        example_limit=max(args.row_limit, 30),
    )
    rendered = render_report(report, row_limit=args.row_limit)
    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"wrote Navigation evidence report: {report_path}")
    _write_console_safe(rendered)
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_navigation_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "navigation-evidence":
            try:
                return _cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 57
        return original_main()

    runtime_module.main = main
    runtime_module._navigation_evidence_installed = True
