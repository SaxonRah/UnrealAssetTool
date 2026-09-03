#!/usr/bin/env python3
"""Isolated systems-schema-10 capture over Epic's installed UAF representative content."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import uatool_systems_capture as capture


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def _cli(core_module, systems_module, argv: list[str]) -> int:
    capture.configure_for_systems(systems_module)
    parser = argparse.ArgumentParser(
        prog="uatool uaf-systems-capture",
        description="run systems schema 10 with only installed UAF representative engine content admitted in addition to project content",
    )
    parser.add_argument("project", help="host .uproject")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--build-script", help="optional Build.bat path")
    parser.add_argument("--no-build", action="store_true", help="reuse already-built plugin module")
    parser.add_argument("--output", help="output directory")
    parser.add_argument("--archive", help="output ZIP")
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    editor = core_module.require_editor(args.editor)
    output = Path(args.output).expanduser().resolve() if args.output else project.parent / ".uatool" / "uaf-systems-schema10-capture"
    archive = Path(args.archive).expanduser().resolve() if args.archive else project.parent / ".uatool" / f"{project.stem}.uaf-systems-schema10-capture.zip"
    if output.exists():
        print(f"removing previous isolated UAF systems capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(project, editor, args.build_script, args.no_build, active_root)
        command = [
            str(editor), str(project),
            "-run=UnrealAssetToolSystems",
            "-UAFEngineContent",
            "-EnablePlugins=UAF,UAFAnimGraph,UAFSharedAssets",
            f"-Output={output}",
            "-unattended", "-nop4", "-nosplash", "-nullrhi", "-nosound", "-UTF8Output",
        ]
        print("running commandlet-backed UAF systems capture:", subprocess.list2cmdline(command))
        result = subprocess.run(command, check=False).returncode

    manifest_path = output / "systems_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(f"UAF systems editor run produced no systems_manifest.json; exit code {result}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_schema = int(manifest.get("schema_version", 0) or 0)
    if actual_schema != 10:
        raise RuntimeError(f"UAF systems capture expected schema 10, got {actual_schema}")
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"UAF systems capture failed: {manifest.get('error', '')}")

    capture._write_capture_archive(output, archive)
    print(f"raw UAF systems capture archive: {archive}")
    error = systems_module.validation_error(output)
    if error:
        raise RuntimeError(f"UAF systems schema-10 validation failed: {error}; raw archive preserved at {archive}")
    if result != 0:
        raise RuntimeError(f"UAF systems commandlet returned {result} after writing a valid schema-10 capture; raw archive preserved at {archive}")

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    print("UAF systems schema 10 counts:")
    for key in (
        "uaf_candidates", "uaf_scoped_candidates", "uaf_loaded_assets", "uaf_assets",
        "uaf_entries", "uaf_variables", "uaf_components", "uaf_entry_points",
        "uaf_rigvm_graphs", "uaf_rigvm_nodes", "uaf_rigvm_pins", "uaf_rigvm_links",
        "uaf_variable_usages", "uaf_truncated_values",
    ):
        print(f"  {key}: {int(counts.get(key, 0) or 0)}")
    print(f"UAF systems capture total elapsed: {time.perf_counter() - started:.2f}s")
    print("normal structural/world/animation/VFX scan was not run")
    print("derive was not run")
    return 0


def install(runtime_module, core_module, systems_module) -> None:
    if getattr(runtime_module, "_uaf_systems_capture_installed", False):
        return
    original_main = runtime_module.main
    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "uaf-systems-capture":
            try:
                return _cli(core_module, systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 54
        return original_main()
    runtime_module.main = main
    runtime_module._uaf_systems_capture_installed = True
