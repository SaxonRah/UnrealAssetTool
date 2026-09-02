#!/usr/bin/env python3
"""Focused UE reflection capture for authored AI Perception Blueprint templates."""
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
    "ai_perception_capture_manifest.json",
    "ai_perception_focus_assets.txt",
    "ai_perception_assets.jsonl",
    "ai_perception_objects.jsonl",
    "ai_perception_properties.jsonl",
    "ai_perception_references.jsonl",
)
PERCEPTION_CLASS = "/script/aimodule.aiperceptioncomponent"
STIMULI_CLASS = "/script/aimodule.aiperceptionstimulisourcecomponent"


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


def _resolve_corpus(project: Path, value: str | None) -> Path:
    corpus = Path(value).expanduser().resolve() if value else project.parent / ".uatool"
    if not corpus.is_dir():
        raise FileNotFoundError(f"existing UnrealAssetTool corpus does not exist: {corpus}")
    return corpus


def _resolve_output(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "ai-perception-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.ai-perception-capture.zip"


def _resolve_report(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.ai-perception-capture.txt"


def _discover_focus_assets(corpus: Path) -> list[str]:
    assets: set[str] = set()
    for row in _rows(corpus / "blueprints.jsonl") or ():
        components = row.get("components", [])
        if not isinstance(components, list):
            continue
        if any(
            isinstance(component, dict)
            and str(component.get("component_class", "") or "").lower() in {PERCEPTION_CLASS, STIMULI_CLASS}
            for component in components
        ):
            path = str(row.get("object_path", "") or "")
            if path:
                assets.add(path)
    for filename in ("blueprint_component_properties.jsonl", "blueprint_state_values.jsonl"):
        for row in _rows(corpus / filename) or ():
            text = json.dumps(row, ensure_ascii=False, sort_keys=True).lower()
            if PERCEPTION_CLASS not in text and STIMULI_CLASS not in text:
                continue
            path = str(row.get("blueprint_path", "") or "")
            if path:
                assets.add(path)
    return sorted(assets)


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"focused AI Perception capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _read_manifest(output: Path) -> dict:
    path = output / "ai_perception_capture_manifest.json"
    if not path.is_file():
        raise RuntimeError("focused AI Perception capture did not produce ai_perception_capture_manifest.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid ai_perception_capture_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("ai_perception_capture_manifest.json root is not an object")
    return value


def _focus_rows(output: Path) -> list[str]:
    return [
        line.strip()
        for line in (output / "ai_perception_focus_assets.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _validate_capture(output: Path) -> dict:
    manifest = _read_manifest(output)
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(f"focused AI Perception capture expected manifest schema 1, got {manifest.get('schema_version')}")
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"focused AI Perception capture failed: {manifest.get('error', '')}")
    if not bool(manifest.get("diagnostic_only", False)):
        raise RuntimeError("focused AI Perception manifest must remain diagnostic_only=true")
    if bool(manifest.get("semantic_promotion", True)):
        raise RuntimeError("focused AI Perception manifest must remain semantic_promotion=false")
    if bool(manifest.get("runtime_state_captured", True)):
        raise RuntimeError("focused AI Perception manifest must remain runtime_state_captured=false")

    focus = _focus_rows(output)
    assets = list(_rows(output / "ai_perception_assets.jsonl"))
    objects = list(_rows(output / "ai_perception_objects.jsonl"))
    properties = list(_rows(output / "ai_perception_properties.jsonl"))
    references = list(_rows(output / "ai_perception_references.jsonl"))
    if len(focus) != len(set(focus)) or any(not value for value in focus):
        raise RuntimeError("focused AI Perception focus list contains blank or duplicate assets")
    asset_paths = [str(row.get("asset_path", "") or "") for row in assets]
    if asset_paths != focus:
        raise RuntimeError("focused AI Perception asset rows do not exactly match nominated focus assets")
    object_paths = [str(row.get("object_path", "") or "") for row in objects]
    if any(not value for value in object_paths) or len(object_paths) != len(set(object_paths)):
        raise RuntimeError("focused AI Perception objects contain blank or duplicate object paths")
    asset_set = set(asset_paths)
    object_set = set(object_paths)
    valid_kinds = {"perception_component_template", "stimuli_source_component_template", "sense_config"}
    for row in objects:
        if str(row.get("source_path", "") or "") not in asset_set:
            raise RuntimeError(f"focused AI Perception object has unresolved source: {row.get('object_path')}")
        if str(row.get("object_kind", "") or "") not in valid_kinds:
            raise RuntimeError(f"focused AI Perception object has invalid kind: {row.get('object_kind')}")
        if not str(row.get("object_class", "") or ""):
            raise RuntimeError(f"focused AI Perception object has blank class: {row.get('object_path')}")
    for row in properties:
        if str(row.get("source_path", "") or "") not in asset_set or str(row.get("owner_path", "") or "") not in object_set:
            raise RuntimeError(f"focused AI Perception property has unresolved source/owner: {row.get('property_path')}")
        if not str(row.get("property_path", "") or "") or not str(row.get("root_property", "") or ""):
            raise RuntimeError("focused AI Perception property has blank path/root")
    for row in references:
        if str(row.get("source_path", "") or "") not in asset_set or str(row.get("owner_path", "") or "") not in object_set:
            raise RuntimeError(f"focused AI Perception reference has unresolved source/owner: {row.get('property_path')}")
        if not str(row.get("target_path", "") or ""):
            raise RuntimeError("focused AI Perception reference has blank target")

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    physical = {
        "focus_assets": len(focus),
        "loaded_assets": sum(int(bool(row.get("loaded", False))) for row in assets),
        "blueprint_assets": sum(int(bool(row.get("is_blueprint", False))) for row in assets),
        "perception_components": sum(int(row.get("object_kind") == "perception_component_template") for row in objects),
        "stimuli_source_components": sum(int(row.get("object_kind") == "stimuli_source_component_template") for row in objects),
        "sense_configs": sum(int(row.get("object_kind") == "sense_config") for row in objects),
        "objects": len(objects),
        "properties": len(properties),
        "references": len(references),
        "truncated_properties": sum(int(bool(row.get("truncated", False))) for row in properties),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            raise RuntimeError(f"focused AI Perception count mismatch for {key}: manifest={counts.get(key)} actual={actual}")
    return manifest


def _counter_lines(title: str, values, limit: int = 60) -> list[str]:
    counter = collections.Counter(values)
    lines = [title]
    if not counter:
        return [title, "  <none>"]
    for value, count in counter.most_common(limit):
        lines.append(f"  {count:7d}  {value}")
    return lines


def _semantic_report(output: Path, manifest: dict) -> str:
    focus = _focus_rows(output)
    objects = list(_rows(output / "ai_perception_objects.jsonl"))
    properties = list(_rows(output / "ai_perception_properties.jsonl"))
    references = list(_rows(output / "ai_perception_references.jsonl"))
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    changed = [row for row in properties if bool(row.get("differs_from_class_default", False))]
    lines = [
        "UnrealAssetTool focused AI Perception evidence capture",
        "diagnostic_only: True",
        "semantic_promotion: False",
        "runtime_state_captured: False",
        f"focus_assets: {len(focus)}",
        f"loaded_assets: {int(counts.get('loaded_assets', 0) or 0)}",
        f"blueprint_assets: {int(counts.get('blueprint_assets', 0) or 0)}",
        f"perception_component_templates: {int(counts.get('perception_components', 0) or 0)}",
        f"stimuli_source_component_templates: {int(counts.get('stimuli_source_components', 0) or 0)}",
        f"sense_configs: {int(counts.get('sense_configs', 0) or 0)}",
        f"objects: {len(objects)}",
        f"properties: {len(properties)}",
        f"properties_different_from_class_default: {len(changed)}",
        f"references: {len(references)}",
        f"truncated_properties: {int(counts.get('truncated_properties', 0) or 0)}",
        f"property_depth_limit_hits: {int(counts.get('property_depth_limit_hits', 0) or 0)}",
        f"property_row_limit_hits: {int(counts.get('property_row_limit_hits', 0) or 0)}",
        f"container_element_limit_hits: {int(counts.get('container_element_limit_hits', 0) or 0)}",
        "",
        "[focus assets]",
        *(f"  {value}" for value in focus),
        "",
    ]
    lines.extend(_counter_lines("[captured object classes]", (str(row.get("object_class", "") or "<blank>") for row in objects)))
    lines.append("")
    lines.extend(_counter_lines("[changed authored/default property paths]", (f"{row.get('object_kind','')} :: {row.get('property_path','')} = {row.get('value','')}" for row in changed), 100))
    lines.append("")
    lines.extend(_counter_lines("[reference targets]", (f"{row.get('property_path','')} -> {row.get('target_path','')}" for row in references), 100))
    lines.extend(("", "[capture assessment]"))
    if int(counts.get("perception_components", 0) or 0) > 0:
        lines.append("  PASS: authored Blueprint AI Perception component template was loaded and reflected.")
    else:
        lines.append("  BLOCKED: no authored AI Perception component template was loaded.")
    if int(counts.get("sense_configs", 0) or 0) > 0:
        lines.append("  PASS: nested AISenseConfig UObject state was loaded and reflected.")
    else:
        lines.append("  BLOCKED: no nested AISenseConfig UObject was captured.")
    if int(counts.get("stimuli_source_components", 0) or 0) > 0:
        lines.append("  PASS: authored stimuli-source component template was loaded and reflected.")
    else:
        lines.append("  NOTE: no stimuli-source component template was captured in the nominated assets.")
    if any(int(counts.get(key, 0) or 0) for key in ("property_depth_limit_hits", "property_row_limit_hits", "container_element_limit_hits")):
        lines.append("  WARNING: reflection traversal hit one or more safety limits; inspect raw rows before normalization.")
    lines.append("  Boundary: authored Blueprint template/default state only; listeners, stimuli history, perceived actors and runtime perception-system state were not captured.")
    return "\n".join(lines) + "\n"


def _capture_cli(core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool ai-perception-capture",
        description="run a focused UE reflection pass over corpus-proven AI Perception Blueprint templates",
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--corpus", help="existing .uatool corpus used to nominate Blueprint assets")
    parser.add_argument("--asset", action="append", default=[], help="additional exact Blueprint asset object path")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument("--no-build", action="store_true", help="reuse already-built plugin module")
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
    focus = sorted(set((*_discover_focus_assets(corpus), *(str(value).strip() for value in args.asset if str(value).strip()))))
    if not focus:
        raise RuntimeError("existing corpus nominated no AI Perception Blueprint assets; focused capture refused")

    if output.exists():
        print(f"removing previous focused AI Perception capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    focus_file = output / "ai_perception_focus_assets.txt"
    focus_file.write_text("".join(value + "\n" for value in focus), encoding="utf-8", newline="\n")
    print(f"focused AI Perception nominated Blueprint assets: {len(focus)}")
    for value in focus:
        print(f"  {value}")

    overall_started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(project, editor, args.build_script, args.no_build, active_root)
        command = [
            str(editor),
            str(project),
            "-run=UnrealAssetToolAIPerception",
            f"-Output={output}",
            f"-FocusFile={focus_file}",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-UTF8Output",
        ]
        print("running focused AI Perception capture:", subprocess.list2cmdline(command))
        started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"focused AI Perception editor elapsed: {time.perf_counter() - started:.2f}s")

    _write_archive(output, archive)
    print(f"focused AI Perception raw archive: {archive}")
    if result != 0:
        raise RuntimeError(f"focused AI Perception editor commandlet failed with exit code {result}; raw archive preserved")

    manifest = _validate_capture(output)
    report = _semantic_report(output, manifest)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")
    print(f"focused AI Perception report: {report_path}")
    print(f"focused AI Perception total elapsed: {time.perf_counter() - overall_started:.2f}s")
    print("normal project scan was not run")
    print("derive was not run")
    return 0


def install(runtime_module=None, core_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if core_module is None:
        import uatool_core as core_module
    if getattr(runtime_module, "_ai_perception_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "ai-perception-capture":
            try:
                return _capture_cli(core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 52
        return original_main()

    runtime_module.main = main
    runtime_module._ai_perception_capture_installed = True
