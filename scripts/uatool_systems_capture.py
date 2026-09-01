#!/usr/bin/env python3
"""Isolated systems-only capture using the canonical UnrealAssetTool launcher."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

CAPTURE_FILES = (
    "systems_manifest.json",
    "systems_assets.jsonl",
    "systems_properties.jsonl",
    "systems_references.jsonl",
    "mass_entity_configs.jsonl",
    "mass_entity_traits.jsonl",
    "mass_spawners.jsonl",
    "mass_spawner_entity_types.jsonl",
    "mass_spawner_generators.jsonl",
    "mass_spawn_generator_assets.jsonl",
    "mass_agent_components.jsonl",
    "zonegraph_shapes.jsonl",
    "zonegraph_shape_points.jsonl",
)


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def _resolve_output(project: Path, value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return project.parent / ".uatool" / "systems-schema5-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return project.parent / ".uatool" / f"{project.stem}.systems-schema5-capture.zip"


def _write_capture_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"systems capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _print_schema5_counts(output: Path) -> None:
    manifest_path = output / "systems_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = manifest.get("counts", {}) if isinstance(manifest, dict) else {}
    keys = (
        "mass_entity_configs",
        "mass_entity_traits",
        "mass_spawners",
        "mass_spawner_entity_types",
        "mass_spawner_generators",
        "mass_spawn_generator_assets",
        "mass_agent_components",
        "zonegraph_shapes",
        "zonegraph_shape_points",
    )
    print("systems schema 5 capture counts:")
    for key in keys:
        print(f"  {key}: {int(counts.get(key, 0) or 0)}")


def _capture_cli(runtime_module, core_module, systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool systems-capture",
        description=(
            "build/reuse UnrealAssetTool and run only the systems scanner; "
            "no world, animation, VFX, database pack, or derive"
        ),
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="reuse the already-built staged plugin module without invoking UBT",
    )
    parser.add_argument(
        "--output",
        help="capture directory; defaults to <Project>/.uatool/systems-schema5-capture",
    )
    parser.add_argument(
        "--archive",
        help="output ZIP; defaults to <Project>/.uatool/<Project>.systems-schema5-capture.zip",
    )
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    editor = core_module.require_editor(args.editor)
    output = _resolve_output(project, args.output)
    archive = _resolve_archive(project, args.archive)

    if output.exists():
        print(f"removing previous isolated systems capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

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
            "-UnrealAssetToolSystemsOnly",
            f"-Output={output}",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-UTF8Output",
        ]
        print("running isolated systems capture:", subprocess.list2cmdline(command))
        capture_started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"isolated systems editor elapsed: {time.perf_counter() - capture_started:.2f}s")

    manifest_path = output / "systems_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            "isolated editor run did not produce systems_manifest.json; "
            f"editor exit code was {result}"
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid systems_manifest.json: {exc}") from exc
    if int(manifest.get("schema_version", 0) or 0) != 5:
        raise RuntimeError(
            f"isolated systems capture expected schema 5, got {manifest.get('schema_version')}"
        )
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"isolated systems capture failed: {manifest.get('error', '')}")

    error = systems_module.validation_error(output)
    if error:
        raise RuntimeError(f"isolated systems capture validation failed: {error}")

    _write_capture_archive(output, archive)
    _print_schema5_counts(output)
    print(f"systems capture archive: {archive}")
    print(f"systems capture total elapsed: {time.perf_counter() - overall_started:.2f}s")
    if result != 0:
        print(
            f"note: editor returned {result} after writing a valid systems capture; "
            "the validated manifest/archive are authoritative"
        )
    return 0


def install(runtime_module, core_module, systems_module) -> None:
    # Synthetic schema-unit-test objects also call the schema installer. Only
    # patch the real public systems module into the canonical runtime CLI.
    if getattr(systems_module, "__name__", "") != "uatool_systems":
        return
    if getattr(runtime_module, "_systems_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "systems-capture":
            try:
                return _capture_cli(runtime_module, core_module, systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 37
        return original_main()

    runtime_module.main = main
    runtime_module._systems_capture_installed = True
