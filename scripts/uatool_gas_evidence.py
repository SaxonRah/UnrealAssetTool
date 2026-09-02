#!/usr/bin/env python3
"""Read-only Gameplay Ability System evidence reports over an existing corpus."""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
import sys

import uatool_gas_capture as gas_capture
import uatool_systems_gas as systems_gas

MARKERS = (
    "/script/gameplayabilities", "gameplayability", "abilitysystemcomponent",
    "attributeset", "fgameplayattribute", "gameplayeffect", "gameplaycue",
    "abilitytask", "gameplaymodmagnitudecalculation",
    "gameplayeffectexecutioncalculation", "gameplayeffectcustomapplicationrequirement",
    "gameplaytagresponsetable", "lyragameplayability", "lyraabilitysystemcomponent",
    "lyraabilityset", "lyraattributeset", "lyrahealthset", "lyracombatset",
    "lyragameplaytagrelationshipmapping", "gamefeatureaction_addabilities",
)

# Potentially huge derived graph/semantic streams are opt-in. The default pass
# is deliberately limited to authored/canonical data and does not run derive.
CANONICAL_STREAMS = (
    "assets.jsonl", "blueprints.jsonl", "blueprint_defaults.jsonl",
    "blueprint_component_properties.jsonl", "blueprint_state_values.jsonl",
    "blueprint_node_properties.jsonl", "blueprint_node_references.jsonl",
    "data_tables.jsonl", "data_table_rows.jsonl", "data_table_fields.jsonl",
    "primary_data_assets.jsonl", "gameplay_tag_dictionary.jsonl",
    "world_actors.jsonl", "world_components.jsonl", "world_instance_properties.jsonl",
    "world_references.jsonl", "systems_assets.jsonl", "systems_properties.jsonl",
    "systems_references.jsonl",
)
DERIVED_STREAMS = (
    "blueprint_semantic_nodes.jsonl", "blueprint_semantic_statements.jsonl",
    "project_nodes.jsonl", "project_edges.jsonl",
)
SOURCE_STREAMS = ("source_chunks.jsonl",)

FOCUS_DEFINITIONS = {
    "ability": {
        "description": "GameplayAbility assets/classes, authored policies, tags, triggers, cost and cooldown references",
        "anchors": (
            "/script/gameplayabilities.gameplayability",
            "/script/gameplayabilitieseditor.gameplayabilityblueprint",
            "gameplayabilityblueprint", "lyragameplayability",
        ),
        "details": (
            "abilitytags", "activationownedtags", "activationrequiredtags", "activationblockedtags",
            "cancelabilitieswithtag", "blockabilitieswithtag", "replicationpolicy", "instancingpolicy",
            "netexecutionpolicy", "netsecuritypolicy", "costgameplayeffectclass",
            "cooldowngameplayeffectclass", "abilitytriggers", "triggers",
        ),
    },
    "effect": {
        "description": "GameplayEffect definitions, GEComponents, modifiers, executions, duration/period, cues and stacking",
        "anchors": (
            "/script/gameplayabilities.gameplayeffect", "gameplayeffectcomponent",
            "abilitiesgameplayeffectcomponent", "additionaleffectsgameplayeffectcomponent",
            "assettagsgameplayeffectcomponent", "blockabilitytagsgameplayeffectcomponent",
            "cancelabilitytagsgameplayeffectcomponent", "chancetoapplygameplayeffectcomponent",
            "customcanapplygameplayeffectcomponent", "immunitygameplayeffectcomponent",
            "removeothergameplayeffectcomponent", "targettagrequirementsgameplayeffectcomponent",
            "targettagsgameplayeffectcomponent",
        ),
        "details": (
            "durationpolicy", "durationmagnitude", "period", "modifiers", "modifierop",
            "magnitude", "executions", "calculationclass", "gameplaycues", "stacking",
            "stacklimitcount", "components", "inheritable", "tags",
        ),
    },
    "ability-system": {
        "description": "AbilitySystemComponent templates/instances and authored component policy/state",
        "anchors": (
            "/script/gameplayabilities.abilitysystemcomponent", "abilitysystemcomponent",
            "lyraabilitysystemcomponent",
        ),
        "details": ("replicationmode", "defaultstartingdata", "spawnedattributes", "attribute", "effect", "tag"),
    },
    "attribute": {
        "description": "AttributeSet classes/data plus FGameplayAttribute/FGameplayAttributeData references",
        "anchors": (
            "/script/gameplayabilities.attributeset", "attributeset", "fgameplayattribute",
            "fgameplayattributedata", "lyraattributeset", "lyrahealthset", "lyracombatset",
        ),
        "details": ("basevalue", "currentvalue", "attribute", "health", "damage", "healing", "clamp"),
    },
    "cue-task": {
        "description": "Gameplay Cue handlers/tags and AbilityTask execution helpers",
        "anchors": (
            "gameplaycuenotify", "gameplaycueset", "gameplaycuefunctionlibrary", "gameplaycue.",
            "/script/gameplayabilities.abilitytask", "abilitytask_",
        ),
        "details": ("gameplaycuetag", "cue", "montage", "event", "delegate", "wait", "targetdata"),
    },
    "granting": {
        "description": "Lyra/GameFeature ability grants, ability sets and tag-relationship assets",
        "anchors": (
            "lyraabilityset", "gamefeatureaction_addabilities",
            "lyragameplaytagrelationshipmapping", "abilitiesgameplayeffectcomponent",
        ),
        "details": (
            "grantedgameplayabilities", "grantedgameplayeffects", "grantedattributesets",
            "abilityset", "effect", "attributeset", "inputtag", "tagrelationship",
        ),
    },
}
FOCUS_NAMES = tuple(FOCUS_DEFINITIONS)


def _row_text(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _iter_rows(rows, path: Path):
    if not path.is_file():
        return
    for row in rows(path):
        if isinstance(row, dict):
            yield row


def _hits(text: str, values: tuple[str, ...]) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(value for value in values if value in lowered)


def _streams(*, include_derived: bool, include_source: bool) -> list[str]:
    result = list(CANONICAL_STREAMS)
    if include_derived:
        result.extend(DERIVED_STREAMS)
    if include_source:
        result.extend(SOURCE_STREAMS)
    return result


def _counter_value(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def build_report(output: Path, rows, *, include_derived: bool = False,
                 include_source: bool = False, example_limit: int = 12) -> dict:
    output = Path(output).expanduser().resolve()
    stream_stats: dict[str, dict] = {}
    marker_counts = collections.Counter()
    examples: dict[str, list[dict]] = {}
    for filename in _streams(include_derived=include_derived, include_source=include_source):
        path = output / filename
        total = matched = 0
        sample: list[dict] = []
        for row in _iter_rows(rows, path) or ():
            total += 1
            markers = _hits(_row_text(row), MARKERS)
            if not markers:
                continue
            matched += 1
            marker_counts.update(markers)
            if len(sample) < example_limit:
                sample.append({"markers": list(markers), "row": row})
        stream_stats[filename] = {"exists": path.is_file(), "total_rows": total, "matched_rows": matched}
        if sample:
            examples[filename] = sample
    return {
        "output": str(output), "diagnostic_only": True, "semantic_promotion": False,
        "include_derived": include_derived, "include_source": include_source,
        "stream_stats": stream_stats, "marker_counts": marker_counts, "examples": examples,
    }


def build_focus_report(output: Path, rows, *, include_derived: bool = False,
                       include_source: bool = False, focuses=None,
                       example_limit: int = 10) -> dict:
    output = Path(output).expanduser().resolve()
    selected = tuple(focuses or FOCUS_NAMES)
    invalid = [name for name in selected if name not in FOCUS_DEFINITIONS]
    if invalid:
        raise ValueError(f"unknown focus: {', '.join(invalid)}")
    buckets = {
        name: {
            "matched_rows": 0, "high_signal_rows": 0,
            "stream_counts": collections.Counter(), "anchor_counts": collections.Counter(),
            "detail_counts": collections.Counter(), "property_counts": collections.Counter(),
            "class_counts": collections.Counter(), "cpp_type_counts": collections.Counter(),
            "examples": collections.defaultdict(list),
        }
        for name in selected
    }
    for filename in _streams(include_derived=include_derived, include_source=include_source):
        path = output / filename
        for row in _iter_rows(rows, path) or ():
            text = _row_text(row)
            for name in selected:
                definition = FOCUS_DEFINITIONS[name]
                anchors = _hits(text, definition["anchors"])
                if not anchors:
                    continue
                details = _hits(text, definition["details"])
                bucket = buckets[name]
                bucket["matched_rows"] += 1
                bucket["high_signal_rows"] += int(bool(details))
                bucket["stream_counts"][filename] += 1
                bucket["anchor_counts"].update(anchors)
                bucket["detail_counts"].update(details)
                prop = _counter_value(row, ("property_path", "property_name", "root_property"))
                if prop:
                    bucket["property_counts"][prop] += 1
                cls = _counter_value(row, (
                    "class_path", "parent_class", "generated_class", "component_class",
                    "owner_class", "target_class", "referenced_object_class", "actor_class",
                ))
                if cls:
                    bucket["class_counts"][cls] += 1
                cpp_type = _counter_value(row, ("cpp_type", "property_type", "struct_type"))
                if cpp_type:
                    bucket["cpp_type_counts"][cpp_type] += 1
                sample = bucket["examples"][filename]
                if len(sample) < example_limit:
                    sample.append({"anchors": list(anchors), "details": list(details), "row": row})
    return {
        "output": str(output), "diagnostic_only": True, "semantic_promotion": False,
        "include_derived": include_derived, "include_source": include_source,
        "focuses": selected, "buckets": buckets,
    }


def _top(counter, limit: int = 12):
    return list(counter.most_common(limit))


def _sample_text(value: dict, max_chars: int = 1000) -> str:
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return text if len(text) <= max_chars else text[:max_chars] + "..."


def render_report(report: dict, *, example_limit: int = 12) -> str:
    lines = [
        "=== UATOOL GAS EVIDENCE ===", f"output: {report['output']}",
        "diagnostic_only: True", "semantic_promotion: False",
        f"include_derived: {report['include_derived']}", f"include_source: {report['include_source']}",
        "", "[streams]",
    ]
    for filename, stats in report["stream_stats"].items():
        if stats["exists"]:
            lines.append(f"{filename}: matched={stats['matched_rows']} total={stats['total_rows']}")
    lines.extend(("", "[markers]"))
    lines.extend(f"{count:8d}  {value}" for value, count in _top(report["marker_counts"], 30))
    for filename, samples in report["examples"].items():
        lines.extend(("", f"[{filename} examples]"))
        lines.extend(_sample_text(item) for item in samples[:example_limit])
    lines.append("===========================")
    return "\n".join(lines) + "\n"


def render_focus_report(report: dict, *, example_limit: int = 10) -> str:
    lines = [
        "=== UATOOL GAS FOCUS ===", f"output: {report['output']}",
        "diagnostic_only: True", "semantic_promotion: False",
        f"include_derived: {report['include_derived']}", f"include_source: {report['include_source']}",
    ]
    for name in report["focuses"]:
        definition = FOCUS_DEFINITIONS[name]
        bucket = report["buckets"][name]
        lines.extend(("", f"[{name}] {definition['description']}",
                      f"matched_rows={bucket['matched_rows']} high_signal_rows={bucket['high_signal_rows']}"))
        for label, counter in (
            ("streams", bucket["stream_counts"]), ("anchors", bucket["anchor_counts"]),
            ("details", bucket["detail_counts"]), ("classes", bucket["class_counts"]),
            ("properties", bucket["property_counts"]), ("cpp_types", bucket["cpp_type_counts"]),
        ):
            values = _top(counter)
            if values:
                lines.append(label + ":")
                lines.extend(f"  {count:8d}  {value}" for value, count in values)
        for filename, samples in bucket["examples"].items():
            if samples:
                lines.append(f"examples {filename}:")
                lines.extend("  " + _sample_text(item) for item in samples[:example_limit])
    lines.append("========================")
    return "\n".join(lines) + "\n"


def _write_report(path_value: str | None, text: str) -> None:
    if not path_value:
        return
    path = Path(path_value).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    print(f"report: {path}")


def _add_common(parser: argparse.ArgumentParser, *, default_limit: int) -> None:
    parser.add_argument("output", help="existing .uatool corpus")
    parser.add_argument("--include-derived", action="store_true", help="also scan derived semantic/project graph streams")
    parser.add_argument("--include-source", action="store_true", help="also scan source_chunks.jsonl")
    parser.add_argument("--limit", type=int, default=default_limit)
    parser.add_argument("--report")


def _evidence_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool gas-evidence")
    _add_common(parser, default_limit=12)
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    report = build_report(Path(args.output), runtime_module._rows,
                          include_derived=args.include_derived, include_source=args.include_source,
                          example_limit=args.limit)
    text = render_report(report, example_limit=args.limit)
    _write_report(args.report, text)
    print(text, end="")
    return 0


def _focus_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool gas-focus")
    _add_common(parser, default_limit=10)
    parser.add_argument("--focus", action="append", choices=FOCUS_NAMES)
    args = parser.parse_args(argv)
    if args.limit < 1:
        parser.error("--limit must be >= 1")
    report = build_focus_report(Path(args.output), runtime_module._rows,
                                include_derived=args.include_derived, include_source=args.include_source,
                                focuses=tuple(args.focus) if args.focus else None,
                                example_limit=args.limit)
    text = render_focus_report(report, example_limit=args.limit)
    _write_report(args.report, text)
    print(text, end="")
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_gas_evidence_installed", False):
        return

    # This installer is reached from the canonical build/runtime composition
    # after schema-5 Mass/ZoneGraph has been installed. Promote the same systems
    # module additively to schema 6 before any user-facing CLI captures globals.
    import uatool_systems as systems_module
    systems_gas.install(systems_module)

    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "gas-evidence":
            try:
                return _evidence_cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 41
        if len(sys.argv) > 1 and sys.argv[1] == "gas-focus":
            try:
                return _focus_cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 42
        return original_main()

    runtime_module.main = main
    runtime_module._gas_evidence_installed = True

    # Compose the native focused capture after this wrapper so gas-capture falls
    # back through gas-evidence/gas-focus and ultimately the canonical runtime.
    import uatool_core as core_module
    gas_capture.install(runtime_module, core_module)
