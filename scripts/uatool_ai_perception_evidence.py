#!/usr/bin/env python3
"""Read-only AI Perception evidence inventory over an existing UnrealAssetTool corpus.

This diagnostic deliberately does not define systems schema 8. It inventories
what current canonical/derived rows can prove about authored perception
components, sense configuration, stimuli sources, and gameplay usage so a later
focused UE 5.8.2 capture can be designed from evidence rather than names.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
from pathlib import Path
import re
import sys

BASE_STREAMS = (
    "assets.jsonl",
    "blueprints.jsonl",
    "blueprint_component_properties.jsonl",
    "blueprint_defaults.jsonl",
    "blueprint_state_values.jsonl",
    "blueprint_node_references.jsonl",
    "blueprint_semantic_nodes.jsonl",
    "blueprint_semantic_statements.jsonl",
    "behavior_trees.jsonl",
    "statetree_nodes.jsonl",
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

MARKERS = (
    "/script/aimodule.aiperceptioncomponent",
    "/script/aimodule.aiperceptionstimulisourcecomponent",
    "/script/aimodule.aisenseconfig",
    "/script/aimodule.aisense_",
    "aiperceptioncomponent",
    "aiperceptionstimulisourcecomponent",
    "sensesconfig",
    "dominantsense",
    "registerassourceforsenses",
    "ontargetperceptionupdated",
    "onperceptionupdated",
)

FOCUS_DEFINITIONS = {
    "component": {
        "description": "Authored AI Perception components and listener-level configuration",
        "anchors": (
            "/script/aimodule.aiperceptioncomponent",
            "aiperceptioncomponent",
        ),
        "details": (
            "sensesconfig",
            "dominantsense",
            "maxactiveage",
            "forgetstaleactors",
            "perceptionupdated",
            "targetperceptionupdated",
        ),
    },
    "sense_config": {
        "description": "Authored sense config objects/arrays and sense-specific defaults",
        "anchors": (
            "/script/aimodule.aisenseconfig",
            "aisenseconfig_sight",
            "aisenseconfig_hearing",
            "aisenseconfig_damage",
            "aisenseconfig_prediction",
            "aisenseconfig_team",
            "aisenseconfig_touch",
            "sensesconfig",
        ),
        "details": (
            "sightradius",
            "losesightradius",
            "peripheralvisionangle",
            "autosuccessrange",
            "detectionbyaffiliation",
            "hearingrange",
            "loshearingrange",
            "maxage",
            "startsenabled",
            "implementation",
        ),
    },
    "stimuli_source": {
        "description": "Authored perception stimuli-source components and registered senses",
        "anchors": (
            "/script/aimodule.aiperceptionstimulisourcecomponent",
            "aiperceptionstimulisourcecomponent",
            "registerassourceforsenses",
            "autoregisterassource",
        ),
        "details": (
            "registerassourceforsenses",
            "autoregisterassource",
            "/script/aimodule.aisense_",
            "aisense_sight",
            "aisense_hearing",
            "aisense_damage",
        ),
    },
    "usage": {
        "description": "Blueprint/C++-reflected authored logic consuming AI Perception",
        "anchors": (
            "ontargetperceptionupdated",
            "ontargetperceptioninfoUpdated".lower(),
            "onperceptionupdated",
            "getperceivedactors",
            "getcurrentlyperceivedactors",
            "getactorsperception",
            "setdominantsense",
            "setsenseenabled",
            "requeststimuliListenerupdate".lower(),
            "registerstimulisource",
        ),
        "details": (
            "event",
            "function",
            "delegate",
            "perception",
            "stimulus",
            "sense",
            "actor",
        ),
    },
}
FOCUS_NAMES = tuple(FOCUS_DEFINITIONS)
SENSE_PATH_RE = re.compile(r"/Script/AIModule\.(?:AISenseConfig_[A-Za-z0-9_]+|AISense_[A-Za-z0-9_]+)", re.IGNORECASE)


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
    return tuple(value for value in values if value in lowered)


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
        raise ValueError(f"unknown AI Perception focus: {', '.join(invalid)}")
    if example_limit < 1:
        raise ValueError("example_limit must be >= 1")

    streams = list(BASE_STREAMS)
    if include_source:
        streams.extend(SOURCE_STREAMS)
    buckets = {name: _bucket() for name in selected}
    proof = collections.Counter()
    marker_counts = collections.Counter()
    stream_totals = collections.Counter()

    perception_components: set[str] = set()
    stimuli_components: set[str] = set()
    dominant_sense_owners: set[str] = set()
    sense_config_owners: set[str] = set()
    stimuli_sense_owners: set[str] = set()
    sense_classes: set[str] = set()
    usage_rows = 0

    for filename in streams:
        path = output / filename
        if not path.is_file():
            continue
        for row in _iter_rows(rows, path):
            stream_totals[filename] += 1
            text = _row_text(row)
            lowered = text.lower()
            marker_counts.update(_hits(text, MARKERS))
            class_value = _value(row, (
                "class_path", "class", "component_class", "owner_class", "target_class",
                "referenced_object_class", "actor_class", "node_class", "instance_class",
            ))
            prop = _value(row, (
                "property_path", "property_name", "root_property", "source_property", "field_name",
            ))
            owner = _value(row, (
                "component_path", "owner_path", "asset_path", "blueprint_path", "actor_path", "object_path",
            ))

            for match in SENSE_PATH_RE.findall(text):
                sense_classes.add(match)

            if filename == "world_components.jsonl":
                class_lower = class_value.lower()
                component = str(row.get("component_path", "") or "")
                if "aiperceptionstimulisourcecomponent" in class_lower and component:
                    stimuli_components.add(component)
                elif "aiperceptioncomponent" in class_lower and component:
                    perception_components.add(component)

            prop_lower = prop.lower()
            perception_context = (
                "aiperceptioncomponent" in lowered
                or "/script/aimodule.aisense_" in lowered
                or "/script/aimodule.aisenseconfig" in lowered
            )
            if prop_lower.endswith("dominantsense") and perception_context:
                dominant_sense_owners.add(owner or f"{filename}:{prop}")
            if ("sensesconfig" in prop_lower or "aisenseconfig" in lowered) and perception_context:
                sense_config_owners.add(owner or f"{filename}:{prop}")
            if (
                "registerassourceforsenses" in prop_lower
                or "registerassourceforsenses" in lowered
            ) and (
                "aiperceptionstimulisourcecomponent" in lowered
                or "/script/aimodule.aisense_" in lowered
            ):
                stimuli_sense_owners.add(owner or f"{filename}:{prop}")

            usage_anchors = FOCUS_DEFINITIONS["usage"]["anchors"]
            if any(anchor in lowered for anchor in usage_anchors):
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
                if prop:
                    bucket["property_counts"][prop] += 1
                relation = str(row.get("relation", "") or "")
                if relation:
                    bucket["relation_counts"][relation] += 1
                group = "high" if details else "other"
                examples = bucket["examples"][filename][group]
                if len(examples) < example_limit:
                    examples.append({"anchors": list(anchors), "details": list(details), "row": row})

    proof.update({
        "unique_perception_components": len(perception_components),
        "unique_stimuli_source_components": len(stimuli_components),
        "dominant_sense_rows": len(dominant_sense_owners),
        "sense_config_rows": len(sense_config_owners),
        "stimuli_registered_sense_rows": len(stimuli_sense_owners),
        "usage_rows": usage_rows,
        "unique_sense_classes": len(sense_classes),
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

    gaps = []
    if perception_components and not sense_config_owners:
        gaps.append(
            "AI Perception components are proven, but current canonical rows do not expose anchored SensesConfig internals; focused UE reflection capture is required."
        )
    if perception_components and not dominant_sense_owners:
        gaps.append(
            "AI Perception components are proven, but DominantSense authorship is not recovered from current canonical rows."
        )
    if stimuli_components and not stimuli_sense_owners:
        gaps.append(
            "AI Perception stimuli-source components are proven, but their registered-sense arrays are not recovered from current canonical rows."
        )
    if not perception_components:
        gaps.append(
            "No placed AI Perception component is proven in this corpus; do not design schema 8 from this project alone."
        )
    if not sense_classes:
        gaps.append(
            "No concrete AISense/AISenseConfig class is proven in the inspected rows; a representative perception-authored project is required."
        )

    return {
        "output": str(output),
        "diagnostic_only": True,
        "semantic_promotion": False,
        "runtime_state_captured": False,
        "include_source": bool(include_source),
        "focuses": selected,
        "stream_totals": stream_totals,
        "marker_counts": marker_counts,
        "proof": proof,
        "perception_components": sorted(perception_components),
        "stimuli_source_components": sorted(stimuli_components),
        "sense_classes": sorted(sense_classes, key=str.lower),
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
    print("=== AI PERCEPTION EVIDENCE REPORT ===")
    print(report.get("output", ""))
    print("diagnostic_only=True semantic_promotion=False runtime_state_captured=False")
    print(f"include_source={bool(report.get('include_source', False))}")
    print("focuses=" + ",".join(report.get("focuses", ())))
    _print_counter("Corpus proof", collections.Counter(report.get("proof", {})), 80)

    if report.get("sense_classes"):
        print("\n[Concrete sense/config classes]")
        for value in report["sense_classes"]:
            print("  " + value)
    if report.get("perception_components"):
        print("\n[Placed AI Perception components]")
        for value in report["perception_components"][:100]:
            print("  " + value)
    if report.get("stimuli_source_components"):
        print("\n[Placed stimuli-source components]")
        for value in report["stimuli_source_components"][:100]:
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
        prog="uatool ai-perception-evidence",
        description="inventory existing authored AI Perception evidence without changing the corpus or claiming schema 8",
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
        print(f"wrote AI Perception evidence report: {report_path}")
    _write_console_safe(rendered)
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_ai_perception_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "ai-perception-evidence":
            try:
                return _cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 51
        return original_main()

    runtime_module.main = main
    runtime_module._ai_perception_evidence_installed = True
