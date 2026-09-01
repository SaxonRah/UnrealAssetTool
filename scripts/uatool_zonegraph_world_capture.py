#!/usr/bin/env python3
"""Focused canonical capture for authored placed ZoneShape actors."""
from __future__ import annotations

import argparse
import collections
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

CAPTURE_FILES = (
    "zonegraph_world_manifest.json",
    "zonegraph_shapes.jsonl",
    "zonegraph_shape_points.jsonl",
)

ZONE_SHAPE_CLASS = "/Script/ZoneGraph.ZoneShape"
ZONE_SHAPE_COMPONENT_CLASS = "/Script/ZoneGraph.ZoneShapeComponent"


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield row


def discover_zonegraph_worlds(corpus: Path) -> tuple[list[str], set[str]]:
    corpus = Path(corpus)
    actor_file = corpus / "world_actors.jsonl"
    component_file = corpus / "world_components.jsonl"
    if not actor_file.is_file() or not component_file.is_file():
        raise RuntimeError(
            "focused ZoneGraph capture requires existing canonical world_actors.jsonl "
            "and world_components.jsonl"
        )

    worlds: set[str] = set()
    expected_shapes: set[str] = set()
    for row in _rows(actor_file):
        if str(row.get("actor_class", "")) != ZONE_SHAPE_CLASS:
            continue
        world_path = str(row.get("world_path", "") or "")
        actor_path = str(row.get("actor_path", "") or "")
        if world_path:
            worlds.add(world_path)
        if actor_path:
            expected_shapes.add(actor_path)

    for row in _rows(component_file):
        if str(row.get("component_class", "")) != ZONE_SHAPE_COMPONENT_CLASS:
            continue
        world_path = str(row.get("world_path", "") or "")
        actor_path = str(row.get("actor_path", "") or "")
        if world_path:
            worlds.add(world_path)
        if actor_path:
            expected_shapes.add(actor_path)

    if not worlds or not expected_shapes:
        raise RuntimeError(
            "existing world corpus contains no exact /Script/ZoneGraph.ZoneShape "
            "actors/components to drive focused capture"
        )
    return sorted(worlds), expected_shapes


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def _resolve_corpus(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool"


def _resolve_output(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "zonegraph-world-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return project.parent / ".uatool" / f"{project.stem}.zonegraph-world-capture.zip"


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"focused ZoneGraph capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _validate_capture(output: Path, expected_shapes: set[str]) -> dict:
    manifest_path = output / "zonegraph_world_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("focused ZoneGraph capture did not produce zonegraph_world_manifest.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid zonegraph_world_manifest.json: {exc}") from exc
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(
            f"focused ZoneGraph capture expected manifest schema 1, got {manifest.get('schema_version')}"
        )
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"focused ZoneGraph capture failed: {manifest.get('error', '')}")
    if bool(manifest.get("generated_lane_topology", True)):
        raise RuntimeError("focused ZoneGraph manifest must not claim generated lane topology")

    shapes = list(_rows(output / "zonegraph_shapes.jsonl"))
    points = list(_rows(output / "zonegraph_shape_points.jsonl"))
    shape_paths = [str(row.get("shape_path", "") or "") for row in shapes]
    if any(not path for path in shape_paths):
        raise RuntimeError("focused ZoneGraph shape has blank shape_path")
    if len(shape_paths) != len(set(shape_paths)):
        raise RuntimeError("focused ZoneGraph capture contains duplicate shape_path rows")

    captured_shapes = set(shape_paths)
    if captured_shapes != expected_shapes:
        missing = sorted(expected_shapes - captured_shapes)
        extra = sorted(captured_shapes - expected_shapes)
        detail = []
        if missing:
            detail.append(f"missing={len(missing)} first={missing[0]}")
        if extra:
            detail.append(f"extra={len(extra)} first={extra[0]}")
        raise RuntimeError(
            "focused ZoneGraph shape set does not match existing canonical world evidence: "
            + "; ".join(detail)
        )

    grouped: dict[str, list[int]] = collections.defaultdict(list)
    for row in points:
        shape_path = str(row.get("shape_path", "") or "")
        if shape_path not in captured_shapes:
            raise RuntimeError(f"ZoneGraph point references unknown shape: {shape_path}")
        grouped[shape_path].append(int(row.get("point_index", -1)))

    for shape in shapes:
        path = str(shape.get("shape_path", ""))
        if "ZoneShape" not in str(shape.get("class_path", "")):
            raise RuntimeError(f"unexpected ZoneShape actor class: {path} -> {shape.get('class_path')}")
        if "ZoneShapeComponent" not in str(shape.get("component_class", "")):
            raise RuntimeError(
                f"unexpected ZoneShape component class: {path} -> {shape.get('component_class')}"
            )
        if bool(shape.get("generated_lane_topology", True)):
            raise RuntimeError(f"ZoneShape row claims generated lane topology: {path}")
        indices = sorted(grouped.get(path, []))
        if indices != list(range(len(indices))):
            raise RuntimeError(f"ZoneGraph point indices are not contiguous for {path}")
        if int(shape.get("point_count", -1)) != len(indices):
            raise RuntimeError(f"ZoneGraph shape point_count mismatch: {path}")

    counts = manifest.get("counts", {}) if isinstance(manifest, dict) else {}
    if int(counts.get("zonegraph_shapes", -1)) != len(shapes):
        raise RuntimeError("ZoneGraph manifest shape count does not match physical rows")
    if int(counts.get("zonegraph_shape_points", -1)) != len(points):
        raise RuntimeError("ZoneGraph manifest point count does not match physical rows")
    if int(counts.get("worlds_requested", -1)) != int(counts.get("worlds_loaded", -2)):
        raise RuntimeError("ZoneGraph focused capture did not load every requested world")
    return manifest


def _capture_cli(runtime_module, core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool zonegraph-world-capture",
        description=(
            "load only worlds already known to contain placed ZoneShape actors and normalize "
            "authored ZoneShape/point state; generated ZoneGraph lane topology is not captured"
        ),
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument("--no-build", action="store_true", help="reuse already-built plugin module")
    parser.add_argument("--corpus", help="existing canonical corpus; defaults to <Project>/.uatool")
    parser.add_argument("--output", help="focused capture directory")
    parser.add_argument("--archive", help="focused capture ZIP")
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    editor = core_module.require_editor(args.editor)
    corpus = _resolve_corpus(project, args.corpus)
    output = _resolve_output(project, args.output)
    archive = _resolve_archive(project, args.archive)
    worlds, expected_shapes = discover_zonegraph_worlds(corpus)

    print(
        "focused ZoneGraph source evidence: "
        f"worlds={len(worlds)} expected_shapes={len(expected_shapes)} corpus={corpus}"
    )
    if output.exists():
        print(f"removing previous focused ZoneGraph capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    world_list = output / "zonegraph_worlds.txt"
    world_list.write_text("".join(f"{world}\n" for world in worlds), encoding="utf-8", newline="\n")

    overall_started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(
            project,
            editor,
            args.build_script,
            args.no_build,
            active_root,
        )

        command = [
            str(editor),
            str(project),
            "-run=UnrealAssetToolZoneGraphWorld",
            f"-Output={output}",
            f"-WorldList={world_list}",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-UTF8Output",
        ]
        print("running focused authored ZoneGraph capture:", subprocess.list2cmdline(command))
        capture_started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"focused ZoneGraph editor elapsed: {time.perf_counter() - capture_started:.2f}s")

    # Preserve raw evidence even if semantic/invariant validation finds a real
    # corpus problem. This keeps a failed focused run shareable without rerunning Unreal.
    _write_archive(output, archive)
    print(f"raw focused ZoneGraph archive: {archive}")

    manifest = _validate_capture(output, expected_shapes)
    counts = manifest.get("counts", {})
    print("focused authored ZoneGraph counts:")
    print(f"  worlds_requested: {int(counts.get('worlds_requested', 0) or 0)}")
    print(f"  worlds_loaded: {int(counts.get('worlds_loaded', 0) or 0)}")
    print(f"  zonegraph_shapes: {int(counts.get('zonegraph_shapes', 0) or 0)}")
    print(f"  zonegraph_shape_points: {int(counts.get('zonegraph_shape_points', 0) or 0)}")
    print("  generated_lane_topology: False")
    print(f"focused ZoneGraph capture archive: {archive}")
    print(f"focused ZoneGraph capture total elapsed: {time.perf_counter() - overall_started:.2f}s")
    if result != 0:
        print(
            f"note: editor returned {result} after writing a valid focused ZoneGraph capture; "
            "the validated manifest/archive are authoritative"
        )
    return 0


def install(runtime_module, core_module, systems_module) -> None:
    if getattr(systems_module, "__name__", "") != "uatool_systems":
        return
    if getattr(runtime_module, "_zonegraph_world_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "zonegraph-world-capture":
            try:
                return _capture_cli(runtime_module, core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 38
        return original_main()

    runtime_module.main = main
    runtime_module._zonegraph_world_capture_installed = True
