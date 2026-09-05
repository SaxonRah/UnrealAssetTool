#!/usr/bin/env python3
"""Focused canonical capture for authored placed ZoneShape actors."""
from __future__ import annotations

import argparse
import collections
import json
import os
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


def _resolve_report(project: Path, value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return project.parent / ".uatool" / f"{project.stem}.zonegraph-world-capture.txt"


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


def promote_capture(systems_module, corpus: Path, capture: Path) -> dict:
    """Overlay validated world-owned ZoneGraph rows onto the current systems schema.

    The current corpus remains the source for every non-ZoneGraph systems stream.
    This deliberately does not run Unreal or derive.
    """
    corpus = Path(corpus).expanduser().resolve()
    capture = Path(capture).expanduser().resolve()

    manifest_path = corpus / "systems_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("current corpus is missing systems_manifest.json")
    try:
        current_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid current systems_manifest.json: {exc}") from exc
    if not isinstance(current_manifest, dict):
        raise RuntimeError("current systems_manifest.json root is not an object")

    current_schema = int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0)
    if int(current_manifest.get("schema_version", 0) or 0) != current_schema:
        raise RuntimeError(
            "ZoneGraph promotion requires the current composed systems schema: "
            f"manifest={current_manifest.get('schema_version')} scripts={current_schema}"
        )

    current_error = systems_module.validation_error(corpus)
    if current_error:
        raise RuntimeError(
            "current systems corpus must validate before ZoneGraph promotion: "
            f"{current_error}"
        )

    worlds, expected_shapes = discover_zonegraph_worlds(corpus)
    zone_manifest = _validate_capture(capture, expected_shapes)
    shapes = list(_rows(capture / "zonegraph_shapes.jsonl"))
    points = list(_rows(capture / "zonegraph_shape_points.jsonl"))

    stage = corpus / ".zonegraph-world-promote-staging"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    try:
        raw_files = tuple(getattr(systems_module, "RAW_FILES", ()))
        if "systems_manifest.json" not in raw_files:
            raise RuntimeError("current systems module RAW_FILES lacks systems_manifest.json")
        for filename in raw_files:
            source = corpus / filename
            if not source.is_file():
                raise RuntimeError(f"current systems corpus missing {filename}")
            shutil.copy2(source, stage / filename)

        for filename in ("zonegraph_shapes.jsonl", "zonegraph_shape_points.jsonl"):
            source = capture / filename
            if not source.is_file():
                raise RuntimeError(f"focused ZoneGraph capture missing {filename}")
            shutil.copy2(source, stage / filename)

        staged_manifest_path = stage / "systems_manifest.json"
        staged_manifest = json.loads(staged_manifest_path.read_text(encoding="utf-8"))
        counts = staged_manifest.get("counts")
        if not isinstance(counts, dict):
            raise RuntimeError("current systems manifest counts missing or invalid")
        counts["zonegraph_shapes"] = len(shapes)
        counts["zonegraph_shape_points"] = len(points)
        staged_manifest["zonegraph_authored_source"] = (
            "focused_world_placed_actor_reflection"
        )
        staged_manifest["zonegraph_world_manifest_schema"] = int(
            zone_manifest.get("schema_version", 0) or 0
        )
        staged_manifest["zonegraph_worlds_requested"] = len(worlds)
        staged_manifest["zonegraph_expected_shape_count"] = len(expected_shapes)
        staged_manifest["generated_lane_topology"] = False
        staged_manifest_path.write_text(
            json.dumps(staged_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        staged_error = systems_module.validation_error(stage)
        if staged_error:
            raise RuntimeError(
                "current-schema systems tree failed after ZoneGraph overlay: "
                f"{staged_error}"
            )

        # Prepare every replacement before committing anything. The systems
        # manifest is replaced last and remains the commit marker.
        replacements = (
            "zonegraph_shapes.jsonl",
            "zonegraph_shape_points.jsonl",
        )
        prepared: list[tuple[Path, Path]] = []
        for filename in replacements:
            temp = corpus / f".{filename}.zonegraph-promote.tmp"
            shutil.copy2(stage / filename, temp)
            prepared.append((temp, corpus / filename))

        zone_manifest_temp = corpus / ".zonegraph_world_manifest.json.zonegraph-promote.tmp"
        shutil.copy2(capture / "zonegraph_world_manifest.json", zone_manifest_temp)

        systems_manifest_temp = corpus / ".systems_manifest.json.zonegraph-promote.tmp"
        shutil.copy2(staged_manifest_path, systems_manifest_temp)

        for temp, destination in prepared:
            os.replace(temp, destination)
        os.replace(zone_manifest_temp, corpus / "zonegraph_world_manifest.json")
        os.replace(systems_manifest_temp, corpus / "systems_manifest.json")
    finally:
        if stage.exists():
            shutil.rmtree(stage)

    final_error = systems_module.validation_error(corpus)
    if final_error:
        raise RuntimeError(
            "promoted current systems corpus failed validation: "
            f"{final_error}"
        )

    return {
        "systems_schema_version": current_schema,
        "zonegraph_worlds": len(worlds),
        "zonegraph_shapes": len(shapes),
        "zonegraph_shape_points": len(points),
        "exact_shape_set_match": True,
        "generated_lane_topology": False,
        "capture": str(capture),
        "corpus": str(corpus),
    }


def _promote_cli(systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool zonegraph-world-promote",
        description=(
            "overlay an already validated focused authored ZoneGraph capture onto "
            "the current composed systems schema; does not run Unreal or derive"
        ),
    )
    parser.add_argument("project", help="path to .uproject; used to resolve defaults")
    parser.add_argument(
        "--corpus",
        help="current canonical corpus; defaults to <Project>/.uatool",
    )
    parser.add_argument(
        "--capture",
        help=(
            "existing focused ZoneGraph capture directory; defaults to "
            "<corpus>/zonegraph-world-capture"
        ),
    )
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    corpus = _resolve_corpus(project, args.corpus)
    capture = (
        Path(args.capture).expanduser().resolve()
        if args.capture
        else corpus / "zonegraph-world-capture"
    )
    result = promote_capture(systems_module, corpus, capture)
    print(f"promoted focused ZoneGraph into current systems schema: {corpus}")
    print(f"  systems_schema: {result['systems_schema_version']}")
    print(f"  zonegraph_worlds: {result['zonegraph_worlds']}")
    print(f"  zonegraph_shapes: {result['zonegraph_shapes']}")
    print(f"  zonegraph_shape_points: {result['zonegraph_shape_points']}")
    print(f"  exact_shape_set_match: {result['exact_shape_set_match']}")
    print(f"  generated_lane_topology: {result['generated_lane_topology']}")
    print("  Unreal launched: False")
    print("  derive run: False")
    return 0


def _short(value, limit: int = 180) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _counter_lines(label: str, rows: list[dict], field: str, limit: int = 8) -> list[str]:
    counts = collections.Counter(str(row.get(field, "") or "<blank>") for row in rows)
    result = [f"{label}:"]
    for value, count in counts.most_common(limit):
        result.append(f"  {count}: {_short(value)}")
    if len(counts) > limit:
        result.append(f"  ... {len(counts) - limit} more distinct values")
    return result


def _semantic_report(output: Path, manifest: dict, expected_shapes: set[str]) -> str:
    shapes = list(_rows(output / "zonegraph_shapes.jsonl"))
    points = list(_rows(output / "zonegraph_shape_points.jsonl"))
    counts = manifest.get("counts", {}) if isinstance(manifest, dict) else {}
    lines = [
        "UnrealAssetTool focused authored ZoneGraph capture",
        f"worlds_requested: {int(counts.get('worlds_requested', 0) or 0)}",
        f"worlds_loaded: {int(counts.get('worlds_loaded', 0) or 0)}",
        f"expected_shapes_from_world_corpus: {len(expected_shapes)}",
        f"zonegraph_shapes: {len(shapes)}",
        f"zonegraph_shape_points: {len(points)}",
        "exact_shape_set_match: True",
        "generated_lane_topology: False",
        f"truncated_point_rows: {sum(1 for row in points if bool(row.get('truncated', False)))}",
    ]

    point_counts = [int(row.get("point_count", 0) or 0) for row in shapes]
    if point_counts:
        lines.append(f"shape_point_count_range: {min(point_counts)}..{max(point_counts)}")

    shape_fields = (
        "shape_type",
        "lane_profile",
        "tags",
        "reverse_lane_profile",
        "polygon_routing_type",
        "relative_location",
        "relative_rotation",
        "per_point_lane_profiles",
    )
    lines.append("\n[shape field coverage]")
    for field in shape_fields:
        nonblank = sum(1 for row in shapes if str(row.get(field, "") or ""))
        lines.append(f"{field}: {nonblank}/{len(shapes)}")

    point_fields = (
        "position",
        "rotation",
        "tangent_length",
        "point_type",
        "lane_profile",
        "reverse_lane_profile",
        "lane_connection_restrictions",
        "inner_turn_radius",
    )
    lines.append("\n[point field coverage]")
    for field in point_fields:
        nonblank = sum(1 for row in points if str(row.get(field, "") or ""))
        lines.append(f"{field}: {nonblank}/{len(points)}")

    lines.append("")
    lines.extend(_counter_lines("[shape_type values]", shapes, "shape_type"))
    lines.append("")
    lines.extend(_counter_lines("[point_type values]", points, "point_type"))
    lines.append("")
    lines.extend(_counter_lines("[point reverse_lane_profile values]", points, "reverse_lane_profile"))

    if shapes:
        first = shapes[0]
        last = shapes[-1]
        lines.extend([
            "\n[sample shapes]",
            "first: " + " | ".join(
                f"{field}={_short(first.get(field, ''))}"
                for field in ("world_path", "shape_path", "point_count", "shape_type", "lane_profile", "tags")
            ),
            "last: " + " | ".join(
                f"{field}={_short(last.get(field, ''))}"
                for field in ("world_path", "shape_path", "point_count", "shape_type", "lane_profile", "tags")
            ),
        ])
    if points:
        first = points[0]
        last = points[-1]
        fields = (
            "shape_path",
            "point_index",
            "position",
            "rotation",
            "tangent_length",
            "point_type",
            "lane_profile",
            "reverse_lane_profile",
            "lane_connection_restrictions",
            "inner_turn_radius",
        )
        lines.extend([
            "\n[sample points]",
            "first: " + " | ".join(f"{field}={_short(first.get(field, ''))}" for field in fields),
            "last: " + " | ".join(f"{field}={_short(last.get(field, ''))}" for field in fields),
        ])
    return "\n".join(lines) + "\n"


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
    parser.add_argument("--report", help="semantic inspection report path")
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    editor = core_module.require_editor(args.editor)
    corpus = _resolve_corpus(project, args.corpus)
    output = _resolve_output(project, args.output)
    archive = _resolve_archive(project, args.archive)
    report_path = _resolve_report(project, args.report)
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
    report = _semantic_report(output, manifest, expected_shapes)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(f"focused ZoneGraph inspection report: {report_path}")
    print(report, end="")
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
        if len(sys.argv) > 1 and sys.argv[1] == "zonegraph-world-promote":
            try:
                return _promote_cli(systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 41
        return original_main()

    runtime_module.main = main
    runtime_module._zonegraph_world_capture_installed = True
