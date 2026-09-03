#!/usr/bin/env python3
"""Read-only UE 5.8 Motion Warping evidence inventory.

This diagnostic proves only exact authored evidence already present in a
canonical UnrealAssetTool corpus. It does not define a new schema and never
treats live warp targets/root-motion-modifier state as authored content.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
from pathlib import Path
import sys

MOTION_WARPING_COMPONENT = "/Script/MotionWarping.MotionWarpingComponent"
MOTION_WARPING_NOTIFY_STATE = "/Script/MotionWarping.AnimNotifyState_MotionWarping"
ROOT_MOTION_MODIFIER_PREFIX = "/Script/MotionWarping.RootMotionModifier"
TARGET_FUNCTIONS = {
    "AddOrUpdateWarpTarget",
    "AddOrUpdateWarpTargetFromComponent",
    "AddOrUpdateWarpTargetFromLocation",
    "AddOrUpdateWarpTargetFromLocationAndRotation",
    "AddOrUpdateWarpTargetFromTransform",
    "RemoveWarpTarget",
    "RemoveWarpTargets",
    "RemoveAllWarpTargets",
    "FindWarpTarget",
}
TARGET_NAME_PINS = {"WarpTargetName", "WarpTargetNames"}

STREAMS = (
    "animation_notifies.jsonl",
    "animation_properties.jsonl",
    "animation_references.jsonl",
    "blueprints.jsonl",
    "blueprint_components.jsonl",
    "blueprint_component_properties.jsonl",
    "blueprint_state_values.jsonl",
    "blueprint_nodes.jsonl",
    "blueprint_pins.jsonl",
    "blueprint_node_properties.jsonl",
    "blueprint_node_references.jsonl",
    "blueprint_semantic_nodes.jsonl",
    "blueprint_semantic_statements.jsonl",
    "world_components.jsonl",
    "world_instance_properties.jsonl",
    "world_references.jsonl",
    "project_edges.jsonl",
)


def _iter_rows(rows, path: Path):
    if not path.is_file():
        return
    for row in rows(path):
        if isinstance(row, dict):
            yield row


def _semantic(row: dict) -> dict:
    value = row.get("semantic", {})
    return value if isinstance(value, dict) else {}


def _first(row: dict, semantic: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
        value = semantic.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _class_value(row: dict) -> str:
    semantic = _semantic(row)
    return _first(
        row, semantic,
        "component_class", "class_path", "class", "owner_class", "actor_class",
        "node_class", "target_class", "referenced_object_class",
    )


def _component_identity(row: dict) -> str:
    return str(
        row.get("component_path")
        or row.get("template_path")
        or row.get("object_path")
        or (
            f"{row.get('blueprint_path','')}::component::{row.get('variable_name') or row.get('component_name','')}"
            if row.get("blueprint_path") else ""
        )
        or ""
    )


def _node_call(row: dict) -> tuple[str, str]:
    semantic = _semantic(row)
    operation = _first(row, semantic, "operation")
    if operation != "function_call":
        return "", ""
    owner = _first(row, semantic, "member_parent_class", "owner", "owner_class")
    name = _first(row, semantic, "member_name", "symbol", "function_name")
    if owner == MOTION_WARPING_COMPONENT and name in TARGET_FUNCTIONS:
        return owner, name
    return "", ""


def build_report(output: Path, rows, *, example_limit: int = 40) -> dict:
    output = Path(output).expanduser().resolve()
    if example_limit < 1:
        raise ValueError("example_limit must be >= 1")

    stream_totals = collections.Counter()
    exact_components: dict[str, dict] = {}
    notify_rows: list[dict] = []
    notify_objects: set[str] = set()
    notify_owned_properties: list[dict] = []
    notify_owned_references: list[dict] = []
    modifier_class_rows: list[dict] = []
    call_nodes: dict[str, dict] = {}
    call_function_counts = collections.Counter()
    call_pin_literals: list[dict] = []
    call_pin_objects: list[dict] = []
    supporting_rows = collections.Counter()
    examples: dict[str, list[dict]] = collections.defaultdict(list)

    # Pass 1: exact components, exact notify windows and exact Blueprint calls.
    for filename in STREAMS:
        path = output / filename
        if not path.is_file():
            continue
        for row in _iter_rows(rows, path):
            stream_totals[filename] += 1
            cls = _class_value(row)

            if cls == MOTION_WARPING_COMPONENT and filename in {
                "blueprint_components.jsonl", "blueprint_component_properties.jsonl",
                "blueprint_state_values.jsonl", "world_components.jsonl",
                "world_instance_properties.jsonl",
            }:
                identity = _component_identity(row) or f"{filename}:{stream_totals[filename]}"
                exact_components.setdefault(identity, {
                    "identity": identity,
                    "stream": filename,
                    "class_path": cls,
                    "blueprint_path": str(row.get("blueprint_path", "") or ""),
                    "actor_path": str(row.get("actor_path", "") or ""),
                    "component_name": str(row.get("variable_name") or row.get("component_name", "") or ""),
                })
                supporting_rows["motion_warping_component_rows"] += 1
                if len(examples["components"]) < example_limit:
                    examples["components"].append(row)

            if filename == "animation_notifies.jsonl" and str(row.get("notify_state_class", "") or "") == MOTION_WARPING_NOTIFY_STATE:
                notify_rows.append(row)
                obj = str(row.get("notify_state_object", "") or "")
                if obj:
                    notify_objects.add(obj)
                if len(examples["notify_windows"]) < example_limit:
                    examples["notify_windows"].append(row)

            if cls.startswith(ROOT_MOTION_MODIFIER_PREFIX):
                modifier_class_rows.append(row)
                if len(examples["modifier_class_rows"]) < example_limit:
                    examples["modifier_class_rows"].append(row)

            if filename in {"blueprint_nodes.jsonl", "blueprint_semantic_nodes.jsonl"}:
                owner, function = _node_call(row)
                if owner and function:
                    node_id = str(row.get("node_id", "") or row.get("id", "") or "")
                    if node_id:
                        call_nodes[node_id] = row
                    call_function_counts[function] += 1
                    if len(examples["calls"]) < example_limit:
                        examples["calls"].append(row)

    # Pass 2: test whether notify-state owned config/modifier objects are already
    # reachable through animation property/reference storage.
    for filename in ("animation_properties.jsonl", "animation_references.jsonl"):
        path = output / filename
        if not path.is_file():
            continue
        for row in _iter_rows(rows, path):
            owner = str(row.get("owner_path", "") or "")
            owner_class = str(row.get("owner_class", "") or row.get("target_class", "") or "")
            is_notify_owned = any(owner == obj or owner.startswith(obj + ".") or owner.startswith(obj + ":") for obj in notify_objects)
            is_modifier = owner_class.startswith(ROOT_MOTION_MODIFIER_PREFIX) or str(row.get("target_class", "") or "").startswith(ROOT_MOTION_MODIFIER_PREFIX)
            if is_notify_owned:
                if filename == "animation_properties.jsonl":
                    notify_owned_properties.append(row)
                else:
                    notify_owned_references.append(row)
                if len(examples["notify_owned"]) < example_limit:
                    examples["notify_owned"].append(row)
            if is_modifier:
                modifier_class_rows.append(row)
                if len(examples["modifier_class_rows"]) < example_limit:
                    examples["modifier_class_rows"].append(row)

    # Pass 3: exact literal/object evidence on pins belonging to exact Motion
    # Warping function-call nodes. Runtime._rows transparently expands compact
    # blueprint_pins storage when the corpus has already been canonical-cleaned.
    if call_nodes:
        path = output / "blueprint_pins.jsonl"
        if path.is_file():
            for row in _iter_rows(rows, path):
                node_id = str(row.get("node_id", "") or "")
                if node_id not in call_nodes:
                    continue
                pin_name = str(row.get("name") or row.get("pin_name", "") or "")
                if pin_name in TARGET_NAME_PINS:
                    default_value = str(row.get("default_value", "") or "")
                    default_object = str(row.get("default_object", "") or row.get("default_value_object", "") or "")
                    entry = {
                        "node_id": node_id,
                        "pin_name": pin_name,
                        "default_value": default_value,
                        "default_object": default_object,
                        "blueprint_path": str(row.get("blueprint_path", "") or ""),
                        "graph_name": str(row.get("graph_name", "") or ""),
                    }
                    if default_value:
                        call_pin_literals.append(entry)
                    if default_object:
                        call_pin_objects.append(entry)
                    if len(examples["target_name_pins"]) < example_limit:
                        examples["target_name_pins"].append(row)

    components_by_stream = collections.Counter(value["stream"] for value in exact_components.values())
    assets_with_windows = {str(row.get("asset_path", "") or "") for row in notify_rows if row.get("asset_path")}
    window_names = collections.Counter(str(row.get("notify_name", "") or "") for row in notify_rows)
    modifier_classes = collections.Counter()
    for row in modifier_class_rows:
        cls = _class_value(row) or str(row.get("owner_class", "") or row.get("target_class", "") or "")
        if cls.startswith(ROOT_MOTION_MODIFIER_PREFIX):
            modifier_classes[cls] += 1

    proof = {
        "motion_warping_components": len(exact_components),
        "motion_warping_component_rows": int(supporting_rows["motion_warping_component_rows"]),
        "motion_warping_notify_windows": len(notify_rows),
        "animation_assets_with_motion_warping_windows": len(assets_with_windows),
        "notify_state_objects": len(notify_objects),
        "notify_owned_property_rows": len(notify_owned_properties),
        "notify_owned_reference_rows": len(notify_owned_references),
        "root_motion_modifier_rows": len(modifier_class_rows),
        "exact_target_management_calls": int(sum(call_function_counts.values())),
        "target_name_literal_pins": len(call_pin_literals),
        "target_name_object_pins": len(call_pin_objects),
    }

    gaps: list[str] = []
    if not exact_components and not notify_rows and not call_nodes:
        gaps.append("No exact Motion Warping authored evidence exists in this corpus; use a more representative project.")
    if notify_rows and not (notify_owned_properties or notify_owned_references or modifier_class_rows):
        gaps.append(
            "Motion Warping windows are proven, but current animation property/reference storage does not expose their root-motion-modifier template/config internals; focused native authored capture is required."
        )
    if call_nodes and not call_pin_literals:
        gaps.append(
            "MotionWarpingComponent target-management calls are proven, but no literal WarpTargetName pins were recovered; use pin/data-dependency evidence before attempting name-symbol joins."
        )
    if notify_rows and call_nodes and not modifier_class_rows:
        gaps.append(
            "Do not join Blueprint warp-target names to animation windows yet: the authored modifier WarpTargetName is not proven in current canonical rows."
        )

    return {
        "output": str(output),
        "diagnostic_only": True,
        "semantic_promotion": False,
        "schema_promotion": False,
        "runtime_state_captured": False,
        "live_warp_targets_captured": False,
        "root_motion_evaluated": False,
        "proof": proof,
        "components_by_stream": components_by_stream,
        "call_function_counts": call_function_counts,
        "window_names": window_names,
        "modifier_classes": modifier_classes,
        "exact_components": [exact_components[key] for key in sorted(exact_components)],
        "notify_windows": notify_rows,
        "target_name_literals": call_pin_literals,
        "gaps": gaps,
        "stream_totals": stream_totals,
        "examples": dict(examples),
    }


def _counter_lines(counter) -> list[str]:
    if not counter:
        return ["  <none>"]
    return [f"  {int(count):7d}  {name}" for name, count in collections.Counter(counter).most_common()]


def render_report(report: dict, *, row_limit: int = 30) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        print("=== MOTION WARPING EVIDENCE REPORT ===")
        print(report["output"])
        print(
            "diagnostic_only=True semantic_promotion=False schema_promotion=False "
            "runtime_state_captured=False live_warp_targets_captured=False root_motion_evaluated=False"
        )
        print("\n[Corpus proof]")
        for key, value in report["proof"].items():
            print(f"  {key}: {value}")
        print("\n[MotionWarpingComponent provenance]")
        print("\n".join(_counter_lines(report["components_by_stream"])))
        print("\n[Exact target-management calls]")
        print("\n".join(_counter_lines(report["call_function_counts"])))
        print("\n[Motion Warping notify names]")
        print("\n".join(_counter_lines(report["window_names"])))
        print("\n[Root-motion modifier classes already visible]")
        print("\n".join(_counter_lines(report["modifier_classes"])))
        print("\n[Evidence gaps / next capture requirements]")
        if not report["gaps"]:
            print("  <none identified by this diagnostic>")
        else:
            for gap in report["gaps"]:
                print("  - " + gap)
        for group in ("components", "notify_windows", "notify_owned", "modifier_class_rows", "calls", "target_name_pins"):
            values = report["examples"].get(group, [])
            if not values:
                continue
            print(f"\n[{group} examples]")
            for row in values[:row_limit]:
                print("  " + json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        print("\n========================================================================")
    return out.getvalue()


def _write_console_safe(text: str) -> None:
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        sys.stdout.write(text.encode(encoding, errors="backslashreplace").decode(encoding))


def _cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool motion-warping-evidence",
        description="inventory exact Motion Warping evidence already present in a .uatool corpus",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("--row-limit", type=int, default=30)
    parser.add_argument("--report", help="optional UTF-8 report path")
    args = parser.parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    if not output.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {output}")
    report = build_report(output, runtime_module._rows, example_limit=max(args.row_limit, 30))
    text = render_report(report, row_limit=args.row_limit)
    if args.report:
        target = Path(args.report).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote Motion Warping evidence report: {target}")
    _write_console_safe(text)
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_motion_warping_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "motion-warping-evidence":
            try:
                return _cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 70
        return original_main()

    runtime_module.main = main
    runtime_module._motion_warping_evidence_installed = True
