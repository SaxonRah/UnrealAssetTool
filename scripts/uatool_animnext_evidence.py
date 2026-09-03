#!/usr/bin/env python3
"""Read-only AnimNext / Unreal Animation Framework (UAF) evidence inventory.

UE 5.8 exposes the forward-looking animation framework primarily through the
Experimental UAF plugins, while many public types/editor strings still retain
AnimNext names. This diagnostic intentionally recognizes both naming families.

It does not define a new schema, does not launch Unreal, and does not promote
semantic coverage. It inventories what an existing corpus can already prove
about UAF/AnimNext assets, RigVM topology, shared variables/bindings, component
usage and exact references so a focused native capture can be designed from
real authored evidence rather than API names alone.
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
    "rigvm_objects.jsonl",
    "rigvm_pins.jsonl",
    "rigvm_links.jsonl",
    "rigvm_properties.jsonl",
    "rigvm_references.jsonl",
    "rigvm_editor_links.jsonl",
    "project_nodes.jsonl",
    "project_edges.jsonl",
)
SOURCE_STREAMS = ("source_chunks.jsonl",)

# Current UE 5.8 names plus conservative legacy aliases. Exact class identities
# are used for family counts; unknown /Script/UAF* or /Script/AnimNext* assets
# remain visible in the `other_uaf_animnext` bucket instead of being guessed.
ASSET_CLASS_FAMILIES = {
    "/script/uafanimgraph.uafanimgraph": "anim_graph",
    "/script/uaf.uafsystem": "system",
    "/script/uaf.uafsharedvariables": "shared_variables",
    "/script/uaf.uafblendmask": "blend_mask",
    "/script/uaf.uafblendprofile": "blend_profile",
    "/script/animnext.animnextanimationgraph": "anim_graph",
    "/script/animnext.animnextmodule": "system",
    "/script/animnext.animnextsharedvariables": "shared_variables",
    "/script/animnext.animnextdatainterface": "legacy_data_interface",
    "/script/animnext.animnextparameterblock": "legacy_parameter_block",
}

UAF_COMPONENT_TOKENS = (
    "/script/uaf.uafcomponent",
    "animnextcomponent",
    "uafcomponent",
)

MARKERS = (
    "/script/uaf.",
    "/script/uafanimgraph.",
    "/script/uafanimnode.",
    "/script/animnext.",
    "animnext",
    "uafcomponent",
    "uafsystem",
    "uafanimgraph",
    "uafsharedvariables",
    "uafblendmask",
    "uafblendprofile",
    "traitstack",
    "traitshareddata",
    "entrypoint",
    "sharedvariables",
    "variablebinding",
    "propertybinding",
)

FOCUS_DEFINITIONS = {
    "assets": {
        "description": "UAF/AnimNext authored asset identity and class distribution",
        "anchors": (
            "/script/uaf.",
            "/script/uafanimgraph.",
            "/script/animnext.",
            "uafanimgraph",
            "uafsystem",
            "uafsharedvariables",
            "animnextanimationgraph",
            "animnextmodule",
        ),
        "details": (
            "asset",
            "class",
            "package",
            "sharedvariables",
            "blendmask",
            "blendprofile",
        ),
    },
    "rigvm_graph": {
        "description": "Existing generic RigVM graph/object/pin/link coverage for UAF/AnimNext assets",
        "anchors": (
            "uaf",
            "animnext",
            "rigvm",
        ),
        "details": (
            "pin",
            "link",
            "node",
            "graph",
            "controller",
            "function",
            "dispatch",
            "entrypoint",
        ),
    },
    "variables_bindings": {
        "description": "Authored shared variables, variable entries/defaults and property/reference bindings",
        "anchors": (
            "sharedvariables",
            "variableentry",
            "variablereference",
            "variablebinding",
            "propertybinding",
            "animnextvariable",
            "uafsharedvariables",
        ),
        "details": (
            "default",
            "type",
            "name",
            "source",
            "target",
            "binding",
            "reference",
        ),
    },
    "traits_entrypoints": {
        "description": "Anim graph entry points, trait stacks/shared data and authored trait-facing state",
        "anchors": (
            "entrypoint",
            "traitstack",
            "traitshareddata",
            "trait",
            "animnextgraph",
            "uafanimgraph",
        ),
        "details": (
            "sequenceplayer",
            "blend",
            "subgraph",
            "passthrough",
            "injection",
            "pose",
            "timeline",
            "result",
        ),
    },
    "usage": {
        "description": "Blueprint/world/source usage of UAF/AnimNext assets and components",
        "anchors": (
            "uafcomponent",
            "animnextcomponent",
            "uafsystem",
            "uafanimgraph",
            "animnext",
        ),
        "details": (
            "component",
            "set",
            "get",
            "call",
            "event",
            "function",
            "asset",
            "graph",
            "system",
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


def _asset_family(class_path: str) -> str:
    value = (class_path or "").lower()
    exact = ASSET_CLASS_FAMILIES.get(value)
    if exact:
        return exact
    if value.startswith("/script/uaf") or value.startswith("/script/animnext"):
        return "other_uaf_animnext"
    return ""


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


def _mentions_known_asset(text: str, known_assets: set[str]) -> bool:
    if not known_assets:
        return False
    lowered = text.lower()
    return any(asset.lower() in lowered for asset in known_assets)


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
        raise ValueError(f"unknown AnimNext/UAF focus: {', '.join(invalid)}")
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
    known_uaf_assets: set[str] = set()

    # Asset identity is authoritative for the proof counters. Read it first so
    # later RigVM/reference rows can be attributed to exact known UAF assets.
    for row in _iter_rows(rows, output / "assets.jsonl"):
        object_path = str(row.get("object_path", "") or "")
        class_path = str(row.get("class_path", "") or "")
        if object_path:
            asset_classes[object_path] = class_path
        family = _asset_family(class_path)
        if family and object_path:
            asset_paths[family].add(object_path)
            known_uaf_assets.add(object_path)

    component_owners: set[str] = set()
    rigvm_object_rows: set[str] = set()
    rigvm_pin_rows: set[str] = set()
    rigvm_link_rows: set[str] = set()
    rigvm_property_rows: set[str] = set()
    rigvm_reference_rows: set[str] = set()
    exact_reference_rows: set[str] = set()
    variable_binding_rows: set[str] = set()
    entry_point_rows: set[str] = set()
    trait_rows: set[str] = set()
    usage_rows: set[str] = set()

    rigvm_stream_sets = {
        "rigvm_objects.jsonl": rigvm_object_rows,
        "rigvm_pins.jsonl": rigvm_pin_rows,
        "rigvm_links.jsonl": rigvm_link_rows,
        "rigvm_properties.jsonl": rigvm_property_rows,
        "rigvm_references.jsonl": rigvm_reference_rows,
        "rigvm_editor_links.jsonl": rigvm_link_rows,
    }

    for filename in streams:
        path = output / filename
        if not path.is_file():
            continue
        for line_number, row in enumerate(_iter_rows(rows, path), 1):
            stream_totals[filename] += 1
            text = _row_text(row)
            lowered = text.lower()
            marker_counts.update(_hits(text, MARKERS))
            key = f"{filename}:{line_number}"

            class_value = _value(row, (
                "class_path", "class", "asset_class", "component_class", "owner_class",
                "target_class", "referenced_object_class", "actor_class", "node_class",
            ))
            prop = _value(row, (
                "property_path", "property_name", "root_property", "source_property", "field_name", "name",
            ))
            owner = _value(row, (
                "component_path", "owner_path", "owner_id", "object_path", "asset_path",
                "blueprint_path", "actor_path", "systems_path", "source_path",
            ))

            class_lower = class_value.lower()
            if any(token in class_lower for token in UAF_COMPONENT_TOKENS):
                component_owners.add(owner or key)

            if filename in rigvm_stream_sets and _mentions_known_asset(text, known_uaf_assets):
                rigvm_stream_sets[filename].add(key)

            if filename in ("world_references.jsonl", "systems_references.jsonl", "blueprint_node_references.jsonl", "rigvm_references.jsonl"):
                if _mentions_known_asset(text, known_uaf_assets) or "/script/uaf" in lowered or "/script/animnext" in lowered:
                    exact_reference_rows.add(key)

            if any(token in lowered for token in (
                "sharedvariables", "variableentry", "variablereference", "variablebinding", "propertybinding", "animnextvariable",
            )):
                variable_binding_rows.add(key)
            if "entrypoint" in lowered or "entry point" in lowered:
                entry_point_rows.add(key)
            if any(token in lowered for token in ("traitstack", "traitshareddata", "animnexttrait", "uafanimnode")):
                trait_rows.add(key)
            if any(token in lowered for token in ("uafcomponent", "animnextcomponent", "/script/uaf.", "/script/uafanimgraph.", "/script/animnext.")):
                usage_rows.add(key)

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
        "unique_uaf_anim_graph_assets": len(asset_paths["anim_graph"]),
        "unique_uaf_system_assets": len(asset_paths["system"]),
        "unique_uaf_shared_variables_assets": len(asset_paths["shared_variables"]),
        "unique_uaf_blend_mask_assets": len(asset_paths["blend_mask"]),
        "unique_uaf_blend_profile_assets": len(asset_paths["blend_profile"]),
        "unique_legacy_animnext_data_interface_assets": len(asset_paths["legacy_data_interface"]),
        "unique_legacy_animnext_parameter_block_assets": len(asset_paths["legacy_parameter_block"]),
        "unique_other_uaf_animnext_assets": len(asset_paths["other_uaf_animnext"]),
        "unique_uaf_animnext_assets_total": len(known_uaf_assets),
        "unique_uaf_animnext_component_owners": len(component_owners),
        "rigvm_objects_for_uaf_assets": len(rigvm_object_rows),
        "rigvm_pins_for_uaf_assets": len(rigvm_pin_rows),
        "rigvm_links_for_uaf_assets": len(rigvm_link_rows),
        "rigvm_properties_for_uaf_assets": len(rigvm_property_rows),
        "rigvm_references_for_uaf_assets": len(rigvm_reference_rows),
        "exact_reference_rows": len(exact_reference_rows),
        "variable_binding_rows": len(variable_binding_rows),
        "entry_point_rows": len(entry_point_rows),
        "trait_rows": len(trait_rows),
        "usage_rows": len(usage_rows),
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
    if not known_uaf_assets and not component_owners:
        gaps.append(
            "No authored UAF/AnimNext asset or component is proven in this corpus; do not design an AnimNext/UAF schema from this project alone."
        )
    if known_uaf_assets and not (rigvm_object_rows or rigvm_pin_rows or rigvm_link_rows):
        gaps.append(
            "UAF/AnimNext asset identity is proven, but existing compact RigVM streams do not expose graph topology for those assets; a focused native UAF/RigVM capture is required before schema design."
        )
    if (rigvm_object_rows or rigvm_pin_rows or rigvm_link_rows):
        gaps.append(
            "Existing RigVM rows overlap UAF/AnimNext assets; verify graph ownership, entry points, trait/static-graph data and variable semantics before deciding whether to extend the shared RigVM model or add a UAF-specific graph layer."
        )
    if (asset_paths["anim_graph"] or asset_paths["system"]) and not entry_point_rows:
        gaps.append(
            "Anim graph/system assets are proven but no authored entry-point rows are visible in the current corpus; focused capture should inspect entry-point identity and graph ownership."
        )
    if (asset_paths["shared_variables"] or asset_paths["system"] or asset_paths["anim_graph"]) and not variable_binding_rows:
        gaps.append(
            "UAF variable-bearing assets are proven but shared-variable/default/binding semantics are not visible as anchored rows; focused capture should inspect variable entries, defaults and bindings."
        )
    if component_owners and not exact_reference_rows:
        gaps.append(
            "UAF/AnimNext component usage is visible but exact authored asset references are not proven by current reference streams."
        )

    return {
        "output": str(output),
        "diagnostic_only": True,
        "semantic_promotion": False,
        "schema_promotion": False,
        "runtime_state_captured": False,
        "terminology": "UE 5.8 Unreal Animation Framework (UAF), with AnimNext identifiers retained where the engine still uses them",
        "include_source": bool(include_source),
        "focuses": selected,
        "stream_totals": stream_totals,
        "marker_counts": marker_counts,
        "proof": proof,
        "assets": {key: sorted(value) for key, value in sorted(asset_paths.items())},
        "asset_classes": dict(sorted(asset_classes.items())),
        "component_owners": sorted(component_owners),
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
    print("=== ANIMNEXT / UNREAL ANIMATION FRAMEWORK (UAF) EVIDENCE REPORT ===")
    print(report.get("output", ""))
    print(report.get("terminology", ""))
    print("diagnostic_only=True semantic_promotion=False schema_promotion=False runtime_state_captured=False")
    print(f"include_source={bool(report.get('include_source', False))}")
    print("focuses=" + ",".join(report.get("focuses", ())))
    _print_counter("Corpus proof", collections.Counter(report.get("proof", {})), 80)

    assets = report.get("assets", {})
    for family in (
        "anim_graph", "system", "shared_variables", "blend_mask", "blend_profile",
        "legacy_data_interface", "legacy_parameter_block", "other_uaf_animnext",
    ):
        values = assets.get(family, []) or []
        if not values:
            continue
        print(f"\n[{family} assets]")
        for value in values[:300]:
            print("  " + value)

    components = report.get("component_owners", []) or []
    if components:
        print("\n[UAF / AnimNext component owners]")
        for value in components[:300]:
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
        prog="uatool animnext-evidence",
        description=(
            "inventory existing UE 5.8 UAF/AnimNext authored evidence without changing the corpus "
            "or defining a new schema"
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
        print(f"wrote AnimNext/UAF evidence report: {report_path}")
    _write_console_safe(rendered)
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_animnext_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "animnext-evidence":
            try:
                return _cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 54
        return original_main()

    runtime_module.main = main
    runtime_module._animnext_evidence_installed = True
