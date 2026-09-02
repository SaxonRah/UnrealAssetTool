#!/usr/bin/env python3
"""Read-only Dataflow / Geometry Collection / Chaos authoring evidence inventory.

This diagnostic does not define a new systems schema. It inventories what the
current canonical/derived corpus can already prove about authored UDataflow
graph assets, Geometry Collection assets/components, destruction settings,
Dataflow ownership links, RestCollection links, Chaos support assets, and
Blueprint/source usage. A focused UE 5.8.2 reflection pass should be designed
from this evidence rather than from API/header names alone.
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
    "/script/dataflowengine.dataflow",
    "/script/geometrycollectionengine.geometrycollection",
    "geometrycollectioncomponent",
    "geometrycollectioncache",
    "chaoscachecollection",
    "fieldsystem",
    "dataflowasset",
    "dataflowterminal",
    "restcollection",
    "damagethreshold",
    "damagemodel",
    "sizespecificdata",
    "damagepropagationdata",
    "clusterconnectiontype",
    "cluster_group_index",
    "clusterGroupIndex".lower(),
    "onchaosbreakevent",
    "onchaosphysicscollision",
    "applyexternalstrain",
    "applyphysicsfield",
)

FOCUS_DEFINITIONS = {
    "dataflow_graph": {
        "description": "Authored Dataflow graph assets and any currently recoverable graph/state evidence",
        "anchors": (
            "/script/dataflowengine.dataflow",
            "dataflowasset",
            "dataflowterminal",
        ),
        "details": (
            "node",
            "pin",
            "connection",
            "input",
            "output",
            "terminal",
            "subgraph",
            "variable",
            "dataflowasset",
        ),
    },
    "geometry_collection": {
        "description": "Geometry Collection assets and authored destruction/default settings",
        "anchors": (
            "/script/geometrycollectionengine.geometrycollection",
            "geometrycollection",
        ),
        "details": (
            "dataflowasset",
            "dataflowterminal",
            "damagethreshold",
            "damagemodel",
            "damagepropagationdata",
            "sizespecificdata",
            "cluster",
            "physicsmaterial",
            "removal",
            "proxy",
        ),
    },
    "destruction_component": {
        "description": "Placed/Blueprint GeometryCollectionComponent authored state and RestCollection linkage",
        "anchors": (
            "geometrycollectioncomponent",
            "restcollection",
        ),
        "details": (
            "restcollection",
            "damagethreshold",
            "damagemodel",
            "damagepropagationdata",
            "cache",
            "collision",
            "replication",
            "onewayinteraction",
        ),
    },
    "chaos_support": {
        "description": "Authored Chaos destruction support assets such as caches, fields and solver-facing content",
        "anchors": (
            "geometrycollectioncache",
            "chaoscachecollection",
            "chaoscachemanager",
            "fieldsystem",
            "chaossolver",
        ),
        "details": (
            "cache",
            "field",
            "strain",
            "anchor",
            "solver",
            "breaking",
            "collision",
            "removal",
        ),
    },
    "usage": {
        "description": "Blueprint/source authored logic that consumes Geometry Collection or Chaos destruction APIs",
        "anchors": (
            "setrestcollection",
            "setdamagethreshold",
            "applyexternalstrain",
            "applyphysicsfield",
            "onchaosbreakevent",
            "onchaosphysicscollision",
            "onchaosremovalevent",
            "geometrycollectioncomponent",
        ),
        "details": (
            "call",
            "event",
            "delegate",
            "function",
            "strain",
            "damage",
            "collision",
            "field",
        ),
    },
}
FOCUS_NAMES = tuple(FOCUS_DEFINITIONS)


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


def _asset_family(class_path: str) -> str:
    value = (class_path or "").lower()
    if value.endswith(".dataflow") or "/script/dataflowengine.dataflow" in value:
        return "dataflow"
    if value.endswith(".geometrycollection") or "/script/geometrycollectionengine.geometrycollection" in value:
        return "geometry_collection"
    if "geometrycollectioncache" in value:
        return "geometry_collection_cache"
    if "chaoscachecollection" in value:
        return "chaos_cache_collection"
    if "fieldsystem" in value and "component" not in value and "actor" not in value:
        return "field_system"
    return ""


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
        raise ValueError(f"unknown Dataflow/Chaos focus: {', '.join(invalid)}")
    if example_limit < 1:
        raise ValueError("example_limit must be >= 1")

    streams = list(BASE_STREAMS)
    if include_source:
        streams.extend(SOURCE_STREAMS)

    buckets = {name: _bucket() for name in selected}
    marker_counts = collections.Counter()
    stream_totals = collections.Counter()

    asset_paths: dict[str, set[str]] = collections.defaultdict(set)
    asset_classes: dict[str, str] = {}
    placed_gc_components: set[str] = set()
    blueprint_gc_components: set[str] = set()
    dataflow_link_owners: set[str] = set()
    dataflow_terminal_owners: set[str] = set()
    rest_collection_owners: set[str] = set()
    damage_setting_owners: set[str] = set()
    usage_keys: set[str] = set()
    exact_reference_rows = 0

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
            ))
            prop = _value(row, (
                "property_path", "property_name", "root_property", "source_property", "field_name",
            ))
            owner = _value(row, (
                "component_path", "owner_path", "owner_id", "object_path", "asset_path",
                "blueprint_path", "actor_path", "systems_path",
            ))

            if filename == "assets.jsonl":
                object_path = str(row.get("object_path", "") or "")
                class_path = str(row.get("class_path", "") or "")
                if object_path:
                    asset_classes[object_path] = class_path
                family = _asset_family(class_path)
                if family and object_path:
                    asset_paths[family].add(object_path)

            class_lower = class_value.lower()
            if filename == "world_components.jsonl" and "geometrycollectioncomponent" in class_lower:
                component = str(row.get("component_path", "") or owner)
                if component:
                    placed_gc_components.add(component)
            if filename in ("blueprint_component_properties.jsonl", "blueprint_state_values.jsonl"):
                if "geometrycollectioncomponent" in class_lower:
                    component = owner or f"{filename}:{line_number}"
                    blueprint_gc_components.add(component)

            prop_lower = prop.lower()
            if "dataflowasset" in prop_lower:
                dataflow_link_owners.add(owner or f"{filename}:{line_number}")
            if "dataflowterminal" in prop_lower:
                dataflow_terminal_owners.add(owner or f"{filename}:{line_number}")
            if "restcollection" in prop_lower:
                rest_collection_owners.add(owner or f"{filename}:{line_number}")
            if any(token in prop_lower for token in (
                "damagethreshold", "damagemodel", "damagepropagationdata", "sizespecificdata",
                "clusterconnectiontype", "clustergroupindex",
            )):
                damage_setting_owners.add(owner or f"{filename}:{line_number}")

            if filename in ("world_references.jsonl", "systems_references.jsonl", "blueprint_node_references.jsonl"):
                if any(token in lowered for token in (
                    "dataflow", "geometrycollection", "fieldsystem", "chaoscache",
                )):
                    exact_reference_rows += 1

            usage_anchors = FOCUS_DEFINITIONS["usage"]["anchors"]
            if any(anchor in lowered for anchor in usage_anchors):
                usage_keys.add(f"{filename}:{line_number}")

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
                relation = str(row.get("relation", "") or "")
                if relation:
                    bucket["relation_counts"][relation] += 1
                group = "high" if details else "other"
                examples = bucket["examples"][filename][group]
                if len(examples) < example_limit:
                    examples.append({"anchors": list(anchors), "details": list(details), "row": row})

    proof = collections.Counter({
        "unique_dataflow_assets": len(asset_paths["dataflow"]),
        "unique_geometry_collection_assets": len(asset_paths["geometry_collection"]),
        "unique_geometry_collection_cache_assets": len(asset_paths["geometry_collection_cache"]),
        "unique_chaos_cache_collection_assets": len(asset_paths["chaos_cache_collection"]),
        "unique_field_system_assets": len(asset_paths["field_system"]),
        "unique_placed_geometry_collection_components": len(placed_gc_components),
        "unique_blueprint_geometry_collection_components": len(blueprint_gc_components),
        "dataflow_asset_link_owners": len(dataflow_link_owners),
        "dataflow_terminal_owners": len(dataflow_terminal_owners),
        "rest_collection_link_owners": len(rest_collection_owners),
        "damage_authoring_owners": len(damage_setting_owners),
        "exact_reference_rows": exact_reference_rows,
        "usage_rows": len(usage_keys),
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

    gaps: list[str] = []
    if not asset_paths["geometry_collection"]:
        gaps.append(
            "No Geometry Collection asset is proven in this corpus; do not design a destruction-authoring schema from this project alone."
        )
    if asset_paths["geometry_collection"] and not asset_paths["dataflow"]:
        gaps.append(
            "Geometry Collection assets are proven but no authored UDataflow asset is proven; this corpus may cover legacy/fracture authoring without the Dataflow graph substrate."
        )
    if asset_paths["dataflow"]:
        gaps.append(
            "UDataflow asset identity is visible, but the current canonical corpus has no dedicated Dataflow node/pin/edge extractor; focused native graph capture is required before schema design."
        )
    if asset_paths["geometry_collection"] and not dataflow_link_owners:
        gaps.append(
            "Geometry Collection assets are visible, but current canonical rows do not prove their DataflowAsset ownership/reference surface."
        )
    if (placed_gc_components or blueprint_gc_components) and not rest_collection_owners:
        gaps.append(
            "GeometryCollectionComponent authored instances/templates are visible, but RestCollection linkage is not recovered as an anchored property row."
        )
    if asset_paths["geometry_collection"] and not damage_setting_owners:
        gaps.append(
            "Geometry Collection assets are visible, but destruction defaults such as damage/cluster settings are not anchored in current canonical rows."
        )

    return {
        "output": str(output),
        "diagnostic_only": True,
        "semantic_promotion": False,
        "runtime_state_captured": False,
        "schema_promotion": False,
        "include_source": bool(include_source),
        "focuses": selected,
        "stream_totals": stream_totals,
        "marker_counts": marker_counts,
        "proof": proof,
        "assets": {key: sorted(value) for key, value in sorted(asset_paths.items())},
        "asset_classes": dict(sorted(asset_classes.items())),
        "placed_geometry_collection_components": sorted(placed_gc_components),
        "blueprint_geometry_collection_components": sorted(blueprint_gc_components),
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
    print("=== DATAFLOW / GEOMETRY COLLECTION / CHAOS EVIDENCE REPORT ===")
    print(report.get("output", ""))
    print("diagnostic_only=True semantic_promotion=False schema_promotion=False runtime_state_captured=False")
    print(f"include_source={bool(report.get('include_source', False))}")
    print("focuses=" + ",".join(report.get("focuses", ())))
    _print_counter("Corpus proof", collections.Counter(report.get("proof", {})), 80)

    assets = report.get("assets", {})
    for family in (
        "dataflow", "geometry_collection", "geometry_collection_cache", "chaos_cache_collection", "field_system",
    ):
        values = assets.get(family, []) or []
        if not values:
            continue
        print(f"\n[{family} assets]")
        for value in values[:200]:
            print("  " + value)

    for title, key in (
        ("Placed GeometryCollectionComponent instances", "placed_geometry_collection_components"),
        ("Blueprint GeometryCollectionComponent templates", "blueprint_geometry_collection_components"),
    ):
        values = report.get(key, []) or []
        if values:
            print(f"\n[{title}]")
            for value in values[:200]:
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
        prog="uatool dataflow-chaos-evidence",
        description=(
            "inventory existing Dataflow / Geometry Collection / Chaos destruction authoring evidence "
            "without changing the corpus or defining a new schema"
        ),
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
        print(f"wrote Dataflow/Chaos evidence report: {report_path}")
    _write_console_safe(rendered)
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_dataflow_chaos_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "dataflow-chaos-evidence":
            try:
                return _cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 52
        return original_main()

    runtime_module.main = main
    runtime_module._dataflow_chaos_evidence_installed = True
