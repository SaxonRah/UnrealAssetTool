#!/usr/bin/env python3
"""Promote independently accepted systems-schema-5 captures into the canonical corpus.

The isolated systems capture owns asset/config/Blueprint-side systems facts. Placed
ZoneShape actors are world-owned, so their accepted focused world capture overlays
only the two ZoneGraph streams. Promotion is explicit and Python-only: it never
launches Unreal or derive, and the composed tree must pass the normal systems
schema validator before the canonical manifest is replaced.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import uatool_zonegraph_world_capture as zonegraph_world_capture

ACCEPTANCE_MANIFEST = "systems_schema5_acceptance.json"
ZONEGRAPH_FILES = ("zonegraph_shapes.jsonl", "zonegraph_shape_points.jsonl")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} root is not an object")
    return value


def _count_rows(path: Path) -> int:
    return sum(1 for _ in zonegraph_world_capture._rows(path))


def _default_paths(project: Path, corpus_value: str | None, systems_value: str | None, zone_value: str | None):
    corpus = Path(corpus_value).expanduser().resolve() if corpus_value else project.parent / ".uatool"
    systems_capture = (
        Path(systems_value).expanduser().resolve()
        if systems_value
        else corpus / "systems-schema5-capture"
    )
    zonegraph_capture = (
        Path(zone_value).expanduser().resolve()
        if zone_value
        else corpus / "zonegraph-world-capture"
    )
    return corpus, systems_capture, zonegraph_capture


def _compose(
    systems_module,
    corpus: Path,
    systems_capture: Path,
    zonegraph_capture: Path,
    stage: Path,
) -> dict:
    if int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0) != 5:
        raise RuntimeError("systems-schema5-accept requires composed systems schema 5")

    error = systems_module.validation_error(systems_capture)
    if error:
        raise RuntimeError(f"isolated systems capture is not valid schema 5: {error}")

    worlds, expected_shapes = zonegraph_world_capture.discover_zonegraph_worlds(corpus)
    zone_manifest = zonegraph_world_capture._validate_capture(zonegraph_capture, expected_shapes)

    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    for filename in systems_module.RAW_FILES:
        source = systems_capture / filename
        if not source.is_file():
            raise RuntimeError(f"isolated systems capture missing {filename}")
        shutil.copy2(source, stage / filename)

    for filename in ZONEGRAPH_FILES:
        source = zonegraph_capture / filename
        if not source.is_file():
            raise RuntimeError(f"focused ZoneGraph capture missing {filename}")
        shutil.copy2(source, stage / filename)

    manifest_path = stage / "systems_manifest.json"
    manifest = _read_json(manifest_path)
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("systems_manifest.json counts missing or invalid")

    shapes = list(zonegraph_world_capture._rows(stage / "zonegraph_shapes.jsonl"))
    points = list(zonegraph_world_capture._rows(stage / "zonegraph_shape_points.jsonl"))
    counts["zonegraph_shapes"] = len(shapes)
    counts["zonegraph_shape_points"] = len(points)
    manifest["zonegraph_authored_source"] = "focused_world_placed_actor_reflection"
    manifest["zonegraph_world_manifest_schema"] = int(zone_manifest.get("schema_version", 0) or 0)
    manifest["zonegraph_worlds_requested"] = len(worlds)
    manifest["zonegraph_expected_shape_count"] = len(expected_shapes)
    manifest["generated_lane_topology"] = False
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    error = systems_module.validation_error(stage)
    if error:
        raise RuntimeError(f"composed schema-5 corpus failed validation: {error}")

    if len(shapes) != len(expected_shapes):
        raise RuntimeError(
            f"composed ZoneGraph shape count mismatch: expected={len(expected_shapes)} actual={len(shapes)}"
        )
    if any(bool(row.get("generated_lane_topology", True)) for row in shapes):
        raise RuntimeError("composed ZoneGraph shape row claims generated lane topology")
    truncated_points = sum(1 for row in points if bool(row.get("truncated", False)))
    if truncated_points:
        raise RuntimeError(f"composed ZoneGraph capture has truncated point rows: {truncated_points}")

    return {
        "systems_schema_version": 5,
        "systems_capture": str(systems_capture),
        "zonegraph_capture": str(zonegraph_capture),
        "zonegraph_world_manifest_schema": int(zone_manifest.get("schema_version", 0) or 0),
        "zonegraph_worlds": len(worlds),
        "zonegraph_shapes": len(shapes),
        "zonegraph_shape_points": len(points),
        "zonegraph_exact_shape_set_match": True,
        "generated_lane_topology": False,
        "systems_manifest_counts": counts,
    }


def _promote(corpus: Path, stage: Path, raw_files: tuple[str, ...], acceptance: dict) -> None:
    corpus.mkdir(parents=True, exist_ok=True)
    promoted = [name for name in raw_files if name != "systems_manifest.json"]
    # JSONL streams land first. The schema-5 manifest is the commit marker and is
    # replaced last, so a successful manifest never advertises files that were
    # not already promoted.
    for filename in promoted:
        source = stage / filename
        temp = corpus / f".{filename}.schema5-accept.tmp"
        shutil.copy2(source, temp)
        os.replace(temp, corpus / filename)

    manifest_temp = corpus / ".systems_manifest.json.schema5-accept.tmp"
    shutil.copy2(stage / "systems_manifest.json", manifest_temp)
    os.replace(manifest_temp, corpus / "systems_manifest.json")

    zone_manifest_source = Path(acceptance["zonegraph_capture"]) / "zonegraph_world_manifest.json"
    zone_manifest_temp = corpus / ".zonegraph_world_manifest.json.schema5-accept.tmp"
    shutil.copy2(zone_manifest_source, zone_manifest_temp)
    os.replace(zone_manifest_temp, corpus / "zonegraph_world_manifest.json")

    acceptance_path = corpus / ACCEPTANCE_MANIFEST
    acceptance_temp = corpus / f".{ACCEPTANCE_MANIFEST}.tmp"
    acceptance_temp.write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(acceptance_temp, acceptance_path)


def accept_schema5(
    systems_module,
    project: Path,
    *,
    corpus: Path,
    systems_capture: Path,
    zonegraph_capture: Path,
) -> dict:
    stage = corpus / ".systems-schema5-accept-staging"
    acceptance = _compose(systems_module, corpus, systems_capture, zonegraph_capture, stage)
    try:
        _promote(corpus, stage, tuple(systems_module.RAW_FILES), acceptance)
        error = systems_module.validation_error(corpus)
        if error:
            raise RuntimeError(f"promoted canonical systems schema 5 failed validation: {error}")
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return acceptance


def _cli(runtime_module, systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool systems-schema5-accept",
        description=(
            "compose the accepted isolated systems capture with the accepted authored ZoneGraph "
            "world capture and promote only canonical systems-schema-5 files; does not run Unreal or derive"
        ),
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--corpus", help="canonical corpus; defaults to <Project>/.uatool")
    parser.add_argument("--systems-capture", help="isolated systems capture directory")
    parser.add_argument("--zonegraph-capture", help="focused authored ZoneGraph capture directory")
    args = parser.parse_args(argv)

    project = Path(args.project).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    corpus, systems_capture, zonegraph_capture = _default_paths(
        project, args.corpus, args.systems_capture, args.zonegraph_capture
    )

    result = accept_schema5(
        systems_module,
        project,
        corpus=corpus,
        systems_capture=systems_capture,
        zonegraph_capture=zonegraph_capture,
    )
    print(f"accepted canonical systems schema 5: {corpus}")
    print(f"acceptance manifest: {corpus / ACCEPTANCE_MANIFEST}")
    print(f"  zonegraph_worlds: {result['zonegraph_worlds']}")
    print(f"  zonegraph_shapes: {result['zonegraph_shapes']}")
    print(f"  zonegraph_shape_points: {result['zonegraph_shape_points']}")
    print("  exact_shape_set_match: True")
    print("  generated_lane_topology: False")
    print("derive was not run")
    return 0


def install(runtime_module, systems_module) -> None:
    if getattr(systems_module, "__name__", "") != "uatool_systems":
        return
    if getattr(runtime_module, "_systems_schema5_accept_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "systems-schema5-accept":
            try:
                return _cli(runtime_module, systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 39
        return original_main()

    runtime_module.main = main
    runtime_module._systems_schema5_accept_installed = True
