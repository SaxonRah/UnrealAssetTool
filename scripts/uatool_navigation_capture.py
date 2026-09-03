#!/usr/bin/env python3
"""Focused UE 5.8 authored Navigation class/default/config evidence capture."""
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
    "navigation_capture_manifest.json",
    "navigation_classes.jsonl",
    "navigation_cdo_properties.jsonl",
    "navigation_cdo_references.jsonl",
)

REQUIRED_CLASSES = {
    "/Script/NavigationSystem.NavArea",
    "/Script/NavigationSystem.NavArea_Default",
    "/Script/NavigationSystem.NavArea_Null",
    "/Script/NavigationSystem.NavArea_Obstacle",
    "/Script/NavigationSystem.NavigationSystemV1",
    "/Script/Engine.NavigationSystemConfig",
    "/Script/NavigationSystem.NavigationInvokerComponent",
    "/Script/NavigationSystem.NavModifierComponent",
    "/Script/NavigationSystem.NavModifierVolume",
    "/Script/AIModule.NavLinkProxy",
    "/Script/NavigationSystem.NavLinkCustomComponent",
    "/Script/NavigationSystem.NavMeshBoundsVolume",
    "/Script/NavigationSystem.RecastNavMesh",
}

KEY_TOKENS = (
    "defaultcost",
    "fixedareaenteringcost",
    "supportedagents",
    "supportedagentsmask",
    "generationradius",
    "removalradius",
    "invokerpriority",
    "areaclass",
    "pointlinks",
    "segmentlinks",
    "smartlink",
    "linkdirection",
    "defaultagentname",
    "generatenavigationonlyaroundnavigationinvokers",
    "agentadius",
    "agentradius",
    "agentheight",
    "agentstepheight",
    "defaultqueryextent",
    "runtimegeneration",
    "cellsize",
    "cellheight",
    "tilesizeuu",
)


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield value


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def _resolve_output(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "navigation-native-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.navigation-native-capture.zip"


def _resolve_report(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.navigation-native-capture.txt"


def _manifest(output: Path) -> dict:
    path = output / "navigation_capture_manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid navigation_capture_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("navigation_capture_manifest.json root is not an object")
    return value


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"Navigation capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def validate_capture(output: Path) -> dict:
    manifest = _manifest(output)
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(f"Navigation capture expected manifest schema 1, got {manifest.get('schema_version')}")
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"Navigation capture failed: {manifest.get('error', '')}")
    if not bool(manifest.get("diagnostic_only", False)):
        raise RuntimeError("Navigation capture must remain diagnostic_only=true")
    if bool(manifest.get("semantic_promotion", True)) or bool(manifest.get("schema_promotion", True)):
        raise RuntimeError("Navigation capture must not promote semantic/schema state")
    if bool(manifest.get("runtime_state_captured", True)):
        raise RuntimeError("Navigation capture must remain runtime_state_captured=false")
    if bool(manifest.get("generated_navmesh_instances_captured", True)):
        raise RuntimeError("Navigation capture must not capture generated NavMesh instances")
    if bool(manifest.get("generated_navmesh_promoted", True)):
        raise RuntimeError("Navigation capture must not promote generated NavMesh state")

    classes = list(_rows(output / "navigation_classes.jsonl"))
    properties = list(_rows(output / "navigation_cdo_properties.jsonl"))
    references = list(_rows(output / "navigation_cdo_references.jsonl"))
    class_paths = [str(row.get("class_path", "") or "") for row in classes]
    if not class_paths or class_paths != sorted(set(class_paths)):
        raise RuntimeError("Navigation classes must be non-empty, unique and sorted")
    missing = sorted(REQUIRED_CLASSES - set(class_paths))
    if missing:
        raise RuntimeError("Navigation capture missing required classes: " + ", ".join(missing))
    class_set = set(class_paths)

    for row in properties:
        if str(row.get("class_path", "") or "") not in class_set:
            raise RuntimeError("Navigation CDO property has unresolved class")
        if not str(row.get("property_path", "") or ""):
            raise RuntimeError("Navigation CDO property has blank property_path")
    for row in references:
        if str(row.get("class_path", "") or "") not in class_set:
            raise RuntimeError("Navigation CDO reference has unresolved class")
        if not str(row.get("target_path", "") or ""):
            raise RuntimeError("Navigation CDO reference has blank target_path")

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    physical = {
        "classes": len(classes),
        "area_classes": sum(1 for row in classes if row.get("kind") == "nav_area"),
        "cdo_properties": len(properties),
        "cdo_references": len(references),
        "config_properties": sum(1 for row in properties if bool(row.get("config_property", False))),
        "truncated_values": sum(1 for row in properties if bool(row.get("truncated", False))),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            raise RuntimeError(f"Navigation count mismatch for {key}: manifest={counts.get(key)} actual={actual}")
    if int(counts.get("missing_expected_classes", -1)) != 0:
        raise RuntimeError("Navigation capture reports missing expected UE 5.8 classes")
    return manifest


def semantic_report(output: Path, manifest: dict) -> str:
    classes = list(_rows(output / "navigation_classes.jsonl"))
    properties = list(_rows(output / "navigation_cdo_properties.jsonl"))
    references = list(_rows(output / "navigation_cdo_references.jsonl"))
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}

    class_kinds = collections.Counter(str(row.get("kind", "") or "<blank>") for row in classes)
    area_classes = [str(row.get("class_path", "") or "") for row in classes if row.get("kind") == "nav_area"]
    key_rows = [
        row for row in properties
        if any(token in str(row.get("property_path", "") or "").lower() for token in KEY_TOKENS)
    ]
    config_rows = [row for row in properties if bool(row.get("config_property", False))]

    lines = [
        "UnrealAssetTool focused UE 5.8 authored Navigation native/default/config evidence capture",
        "diagnostic_only: True",
        "semantic_promotion: False",
        "schema_promotion: False",
        "runtime_state_captured: False",
        "generated_navmesh_instances_captured: False",
        "generated_navmesh_promoted: False",
        f"classes: {len(classes)}",
        f"area_classes: {len(area_classes)}",
        f"cdo_properties: {len(properties)}",
        f"cdo_references: {len(references)}",
        f"config_properties: {len(config_rows)}",
        f"truncated_values: {int(counts.get('truncated_values', 0) or 0)}",
        f"depth_limit_hits: {int(counts.get('depth_limit_hits', 0) or 0)}",
        f"container_limit_hits: {int(counts.get('container_limit_hits', 0) or 0)}",
        "",
        "[class kinds]",
    ]
    for value, count in class_kinds.most_common():
        lines.append(f"  {count:5d}  {value}")
    lines.append("")
    lines.append("[discovered NavArea classes]")
    lines.extend(f"  {value}" for value in area_classes)
    lines.append("")
    lines.append("[high-value CDO/config properties]")
    if not key_rows:
        lines.append("  <none>")
    for row in key_rows[:500]:
        flags = []
        if row.get("config_property"): flags.append("config")
        if row.get("edit_property"): flags.append("edit")
        suffix = f" [{' '.join(flags)}]" if flags else ""
        value = str(row.get("value", "") or "")
        if len(value) > 1200:
            value = value[:1199] + "…"
        lines.append(f"  {row.get('class_path','')} :: {row.get('property_path','')} = {value}{suffix}")
    lines.append("")
    lines.append("[exact CDO reference targets]")
    for row in references[:500]:
        lines.append(f"  {row.get('class_path','')} :: {row.get('property_path','')} -> {row.get('target_path','')}")
    lines.append("")
    lines.append("[capture assessment]")
    lines.append("  This capture describes native authored defaults/project-applied config only. Existing world schema remains authoritative for placed NavMeshBoundsVolume/NavLinkProxy transforms and instance overrides.")
    lines.append("  Generated RecastNavMesh instances, tiles, polys, runtime path queries, dirty-tile history and path-following state are intentionally absent.")
    lines.append("  Use the real values above together with navigation-evidence output before choosing systems schema 11 vs world-schema evolution/split ownership.")
    return "\n".join(lines) + "\n"


def _capture_cli(core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool navigation-capture",
        description="capture UE 5.8 authored Navigation native class defaults and project-applied config without scanning generated NavMesh state",
    )
    parser.add_argument("project", help="path to the UE 5.8 .uproject used to host the commandlet")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument("--no-build", action="store_true", help="reuse already-built plugin module")
    parser.add_argument("--output", help="focused capture directory")
    parser.add_argument("--archive", help="focused capture ZIP")
    parser.add_argument("--report", help="semantic inspection report path")
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    editor = core_module.require_editor(args.editor)
    output = _resolve_output(project, args.output)
    archive = _resolve_archive(project, args.archive)
    report_path = _resolve_report(project, args.report)

    if output.exists():
        print(f"removing previous Navigation native capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    overall_started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(project, editor, args.build_script, args.no_build, active_root)
        command = [
            str(editor),
            str(project),
            "-run=UnrealAssetToolNavigation",
            f"-Output={output}",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-UTF8Output",
        ]
        print("running focused authored Navigation native capture:", subprocess.list2cmdline(command))
        started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"focused authored Navigation editor elapsed: {time.perf_counter() - started:.2f}s")

    if all((output / filename).is_file() for filename in CAPTURE_FILES):
        _write_archive(output, archive)
        print(f"focused authored Navigation raw archive: {archive}")
    if result != 0:
        raise RuntimeError(f"focused authored Navigation commandlet failed with exit code {result}; upload the raw archive if it was produced")

    manifest = validate_capture(output)
    report = semantic_report(output, manifest)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")
    print(f"focused authored Navigation report: {report_path}")
    print(f"focused authored Navigation total elapsed: {time.perf_counter() - overall_started:.2f}s")
    print("normal project/world scan was not run")
    print("derive was not run")
    return 0


def install(runtime_module=None, core_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if core_module is None:
        import uatool_core as core_module
    if getattr(runtime_module, "_navigation_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "navigation-capture":
            try:
                return _capture_cli(core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 58
        return original_main()

    runtime_module.main = main
    runtime_module._navigation_capture_installed = True
