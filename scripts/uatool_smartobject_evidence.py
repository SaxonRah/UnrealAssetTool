#!/usr/bin/env python3
"""Read-only Smart Objects evidence inventory over an existing UnrealAssetTool corpus.

This module is intentionally diagnostic. It discovers what current canonical and
derived streams can already prove about Smart Objects and highlights the authored
facts that require a focused Unreal reflection capture before a first-class schema
is designed. It never promotes a Smart Object relation or changes a corpus.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
from pathlib import Path
import sys

MARKERS = (
    "/script/smartobjectsmodule",
    "/script/masssmartobjects",
    "smartobjectdefinition",
    "smartobjectcomponent",
    "smartobjectslot",
    "smartobjectbehavior",
    "smartobjectpersistentcollection",
    "smartobjectzoneannotations",
    "smartobject",
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
    "behavior_trees.jsonl",
    "blackboards.jsonl",
    "eqs_queries.jsonl",
    "statetrees.jsonl",
    "statetree_states.jsonl",
    "statetree_nodes.jsonl",
    "statetree_transitions.jsonl",
    "statetree_bindings.jsonl",
    "ai_properties.jsonl",
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

FOCUS_DEFINITIONS = {
    "definition": {
        "description": "SmartObjectDefinition assets and authored definition state",
        "anchors": (
            "/script/smartobjectsmodule.smartobjectdefinition",
            "smartobjectdefinition_",
            "smartobjectdefinition",
        ),
        "details": (
            "slots",
            "slot",
            "behavior",
            "behaviordefinition",
            "user",
            "activity",
            "tags",
            "tagquery",
            "entrance",
            "transform",
        ),
    },
    "slot": {
        "description": "Authored Smart Object slots, slot definitions and per-slot state",
        "anchors": (
            "smartobjectslot",
            "fsmartobjectslot",
            ".slots",
            "slots[",
        ),
        "details": (
            "offset",
            "rotation",
            "transform",
            "behavior",
            "behaviordefinition",
            "user",
            "activity",
            "tags",
            "tagquery",
            "entrance",
        ),
    },
    "behavior": {
        "description": "Smart Object behavior definitions and StateTree/Mass integrations",
        "anchors": (
            "smartobjectbehaviordefinition",
            "smartobjectstatetreebehaviordefinition",
            "/script/masssmartobjects",
            "smartobjectzoneannotations",
        ),
        "details": (
            "statetree",
            "behavior",
            "definition",
            "slot",
            "tags",
            "mass",
        ),
    },
    "placement": {
        "description": "Placed/authored SmartObject components, actors and definition references",
        "anchors": (
            "/script/smartobjectsmodule.smartobjectcomponent",
            "smartobjectcomponent",
            "smartobjectpersistentcollection",
            "smartobject_wall",
            "smartobject_bench",
        ),
        "details": (
            "definition",
            "smartobjectdefinition",
            "component",
            "actor",
            "world",
            "transform",
            "tags",
        ),
    },
    "usage": {
        "description": "Blueprint/StateTree authored logic that finds, claims, uses or releases Smart Objects",
        "anchors": (
            "findsmartobject",
            "claimsmartobject",
            "usesmartobject",
            "releasesmartobject",
            "smartobjectclaim",
            "smartobjectrequest",
            "smartobjecthandle",
            "smartobject actor",
            "slot handle",
            "slot to be claimed",
            "slottobeclaimed",
        ),
        "details": (
            "statetree",
            "task",
            "condition",
            "function",
            "property",
            "binding",
            "claim",
            "release",
            "use",
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


def _hits(text: str, values) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(value for value in values if value in lowered)


def _counter_value(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
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
        raise ValueError(f"unknown Smart Object focus: {', '.join(invalid)}")
    if example_limit < 1:
        raise ValueError("example_limit must be >= 1")

    streams = list(BASE_STREAMS)
    if include_source:
        streams.extend(SOURCE_STREAMS)
    buckets = {name: _bucket() for name in selected}
    stream_totals = collections.Counter()
    marker_counts = collections.Counter()

    # Corpus-level proof counters are intentionally narrow. These are diagnostic
    # signals, not a public schema contract.
    proof = collections.Counter()
    definitions: set[str] = set()
    definition_classes = collections.Counter()
    placed_components: set[str] = set()
    placed_actors: set[str] = set()
    definition_refs: set[tuple[str, str]] = set()
    slot_internal_rows = 0
    behavior_internal_rows = 0
    usage_rows = 0

    for filename in streams:
        path = output / filename
        if not path.is_file():
            continue
        for row in _iter_rows(rows, path):
            stream_totals[filename] += 1
            text = _row_text(row)
            lowered = text.lower()
            markers = _hits(text, MARKERS)
            if markers:
                marker_counts.update(markers)

            class_value = _counter_value(
                row,
                (
                    "class_path", "class", "component_class", "owner_class", "target_class",
                    "referenced_object_class", "actor_class", "node_class", "instance_class",
                ),
            )

            if filename == "assets.jsonl" and "smartobjectdefinition" in class_value.lower():
                value = str(row.get("object_path", "") or "")
                if value:
                    definitions.add(value)
                    definition_classes[class_value] += 1
                    proof["definition_assets"] += 1
            if filename == "world_components.jsonl" and "smartobjectcomponent" in class_value.lower():
                value = str(row.get("component_path", "") or "")
                if value:
                    placed_components.add(value)
                    proof["placed_smartobject_components"] += 1
            if filename == "world_actors.jsonl" and "smartobject" in lowered:
                value = str(row.get("actor_path", "") or "")
                if value:
                    placed_actors.add(value)
            if filename in {"world_references.jsonl", "systems_references.jsonl", "blueprint_node_references.jsonl"}:
                target = _counter_value(row, ("target_path", "referenced_object_path", "target_object_path"))
                target_class = _counter_value(row, ("target_class", "referenced_object_class", "target_object_class"))
                if target and (
                    target in definitions
                    or "smartobjectdefinition" in target.lower()
                    or "smartobjectdefinition" in target_class.lower()
                ):
                    owner = _counter_value(row, ("owner_path", "actor_path", "asset_path", "blueprint_path"))
                    definition_refs.add((owner, target))
                    proof["exact_definition_references"] += 1

            # Evidence for internals must be tied to definition/slot/behavior
            # anchors, not merely to a filename containing SmartObject.
            definition_anchor = (
                "smartobjectdefinition" in lowered
                or "/script/smartobjectsmodule.smartobjectdefinition" in lowered
            )
            if definition_anchor and any(token in lowered for token in ("slots[", ".slots", '"slots"', "smartobjectslot")):
                slot_internal_rows += 1
            if definition_anchor and "behavior" in lowered:
                behavior_internal_rows += 1
            if any(anchor in lowered for anchor in FOCUS_DEFINITIONS["usage"]["anchors"]):
                usage_rows += 1

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
                prop = _counter_value(row, ("property_path", "property_name", "root_property", "source_property"))
                if prop:
                    bucket["property_counts"][prop] += 1
                relation = str(row.get("relation", "") or "")
                if relation:
                    bucket["relation_counts"][relation] += 1
                group = "high" if details else "other"
                examples = bucket["examples"][filename][group]
                if len(examples) < example_limit:
                    examples.append({
                        "anchors": list(anchors),
                        "details": list(details),
                        "row": row,
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

    proof.update({
        "unique_definition_assets": len(definitions),
        "unique_placed_smartobject_components": len(placed_components),
        "unique_smartobject_named_actors": len(placed_actors),
        "unique_exact_definition_references": len(definition_refs),
        "definition_slot_internal_rows": slot_internal_rows,
        "definition_behavior_internal_rows": behavior_internal_rows,
        "usage_rows": usage_rows,
    })

    gaps = []
    if definitions and slot_internal_rows == 0:
        gaps.append(
            "SmartObjectDefinition assets are proven, but current canonical rows do not expose authored slot internals; focused Unreal reflection capture is required."
        )
    if definitions and behavior_internal_rows == 0:
        gaps.append(
            "SmartObjectDefinition assets are proven, but current canonical rows do not expose behavior-definition internals; focused Unreal reflection capture is required."
        )
    if not placed_components:
        gaps.append(
            "No canonical world SmartObjectComponent rows were proven in this corpus; placement/component coverage needs a world that loads authored Smart Objects."
        )
    if not definitions:
        gaps.append(
            "No SmartObjectDefinition asset is proven in this corpus; do not design first-class normalization from this project alone."
        )

    return {
        "output": str(output),
        "diagnostic_only": True,
        "semantic_promotion": False,
        "include_source": bool(include_source),
        "focuses": selected,
        "stream_totals": stream_totals,
        "marker_counts": marker_counts,
        "proof": proof,
        "definitions": sorted(definitions),
        "definition_classes": definition_classes,
        "placed_components": sorted(placed_components),
        "placed_actors": sorted(placed_actors),
        "definition_references": [
            {"owner": owner, "definition": target}
            for owner, target in sorted(definition_refs)
        ],
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
    print("=== SMART OBJECTS EVIDENCE REPORT ===")
    print(report.get("output", ""))
    print("diagnostic_only=True semantic_promotion=False")
    print(f"include_source={bool(report.get('include_source', False))}")
    print("focuses=" + ",".join(report.get("focuses", ())))

    proof = report.get("proof", collections.Counter())
    _print_counter("Corpus proof", collections.Counter(proof), 80)
    if report.get("definitions"):
        print("\n[SmartObjectDefinition assets]")
        for value in report["definitions"]:
            print("  " + value)
    if report.get("placed_components"):
        print("\n[Placed SmartObject components]")
        for value in report["placed_components"][:100]:
            print("  " + value)
    if report.get("definition_references"):
        print("\n[Exact definition references]")
        for row in report["definition_references"][:100]:
            print(f"  {row.get('owner','')} -> {row.get('definition','')}")

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
                raw = json.dumps(
                    example.get("row", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
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


def _write_report(path_value: str | None, text: str) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote Smart Objects evidence report: {path}")


def _cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool smartobject-evidence",
        description="inventory existing Smart Objects evidence without changing the corpus or claiming a schema",
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
    _write_report(args.report, rendered)
    _write_console_safe(rendered)
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_smartobject_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "smartobject-evidence":
            try:
                return _cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 50
        return original_main()

    runtime_module.main = main
    runtime_module._smartobject_evidence_installed = True
