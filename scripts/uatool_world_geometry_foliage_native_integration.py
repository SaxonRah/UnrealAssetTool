#!/usr/bin/env python3
"""Compose native UE Foliage editor-placement evidence into focused world geometry capture."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

import uatool_world_geometry_capture as capture


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="uatool landscape-foliage-hlod-capture",
        description="capture exact UE 5.8 authored Landscape/Foliage/HLOD state without render/generated/runtime geometry",
    )
    parser.add_argument("project", help="path to the UE 5.8 .uproject used to host the commandlet")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument("--no-build", action="store_true", help="reuse already-built plugin module")
    parser.add_argument("--include-engine", action="store_true", help="also inspect matching engine/plugin candidates outside project content")
    parser.add_argument("--output", help="focused capture directory")
    parser.add_argument("--archive", help="focused capture ZIP")
    parser.add_argument("--report", help="semantic inspection report path")
    return parser


def _native_counts(output: Path) -> tuple[int, int]:
    infos = list(capture._rows(output / "foliage_actor_type_infos.jsonl"))
    instances = list(capture._rows(output / "foliage_instances.jsonl"))
    native_infos = sum(bool(row.get("instances_captured_via_native_api")) for row in infos)
    native_instances = sum(str(row.get("capture_mode", "")) == "native_editor_array" for row in instances)
    return native_infos, native_instances


def install(core_module) -> None:
    if getattr(capture, "_world_geometry_native_foliage_installed", False):
        return

    original_report = capture.semantic_report

    def semantic_report(output: Path, manifest: dict) -> str:
        text = original_report(output, manifest)
        native_infos, native_instances = _native_counts(Path(output))
        reflected_line = (
            "  foliage_infos_with_reflected_instance_array: "
            f"{sum(bool(row.get('instances_reflected_as_struct_array')) for row in capture._rows(Path(output) / 'foliage_actor_type_infos.jsonl'))}"
        )
        native_lines = (
            f"{reflected_line}\n"
            f"  foliage_infos_with_native_editor_array: {native_infos}\n"
            f"  foliage_instances_from_native_editor_array: {native_instances}"
        )
        if reflected_line in text:
            text = text.replace(reflected_line, native_lines, 1)
        text = text.replace(
            "  FoliageType settings and mesh references are asset-owned; InstancedFoliageActor info/instance rows are accepted as placement evidence only when the reflected serialized editor container is structurally visible.",
            "  FoliageType settings and mesh references are asset-owned; InstancedFoliageActor placement is captured from the public native AInstancedFoliageActor/FFoliageInfo editor-authoring API when the protected FoliageInfos container is not reflected.",
        )
        text = text.replace(
            "  If foliage_info_maps_opaque is nonzero, do not substitute FoliageInstancedStaticMeshComponent transforms for missing authored foliage-info topology.",
            "  Native foliage instance rows come only from FFoliageInfo::Instances (editor-only placed instances); FoliageInstancedStaticMeshComponent render-instance transforms are never substituted for authored placement topology.",
        )
        return text

    def capture_cli(active_core_module, argv: list[str]) -> int:
        args = _parser().parse_args(argv)
        project = capture._resolve_project(args.project)
        editor = active_core_module.require_editor(args.editor)
        output = capture._resolve_output(project, args.output)
        archive = capture._resolve_archive(project, args.archive)
        report_path = capture._resolve_report(project, args.report)

        if output.exists():
            print(f"removing previous world-geometry native capture: {output}")
            shutil.rmtree(output)
        output.mkdir(parents=True, exist_ok=True)

        started = time.perf_counter()
        with active_core_module.stage_invoking_plugin_checkout(project) as active_root:
            active_root = Path(active_root).resolve()
            active_core_module.ensure_plugin_binary(
                project, editor, args.build_script, args.no_build, active_root
            )

            base_command = [
                str(editor), str(project), "-run=UnrealAssetToolWorldGeometry", f"-Output={output}",
                "-unattended", "-nop4", "-nosplash", "-nullrhi", "-nosound", "-UTF8Output",
            ]
            if args.include_engine:
                base_command.append("-IncludeEngine")
            print("world-geometry capture:", subprocess.list2cmdline(base_command))
            result = subprocess.run(base_command, cwd=str(project.parent))
            if result.returncode:
                if all((output / filename).is_file() for filename in capture.CAPTURE_FILES):
                    capture._write_archive(output, archive)
                    print(f"raw world-geometry capture archive preserved after commandlet failure: {archive}")
                raise RuntimeError(
                    f"UnrealAssetToolWorldGeometry commandlet failed with exit code {result.returncode}"
                )

            foliage_command = [
                str(editor), str(project), "-run=UnrealAssetToolWorldGeometryFoliage", f"-Output={output}",
                "-unattended", "-nop4", "-nosplash", "-nullrhi", "-nosound", "-UTF8Output",
            ]
            if args.include_engine:
                foliage_command.append("-IncludeEngine")
            print("native foliage placement refinement:", subprocess.list2cmdline(foliage_command))
            foliage_result = subprocess.run(foliage_command, cwd=str(project.parent))
            if foliage_result.returncode:
                if all((output / filename).is_file() for filename in capture.CAPTURE_FILES):
                    capture._write_archive(output, archive)
                    print(f"raw world-geometry capture archive preserved after native foliage failure: {archive}")
                raise RuntimeError(
                    "UnrealAssetToolWorldGeometryFoliage commandlet failed with exit code "
                    f"{foliage_result.returncode}"
                )

        try:
            manifest = capture.validate_capture(output)
            if not bool(manifest.get("foliage_native_api_captured", False)):
                raise RuntimeError("world-geometry capture missing native foliage refinement marker")
            capture._write_archive(output, archive)
            text = semantic_report(output, manifest)
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(text, encoding="utf-8", newline="\n")
        except Exception:
            if all((output / filename).is_file() for filename in capture.CAPTURE_FILES):
                capture._write_archive(output, archive)
                print(f"raw world-geometry capture archive preserved after validation failure: {archive}")
            raise

        native_infos, native_instances = _native_counts(output)
        print(text, end="")
        print(
            "native foliage refinement complete: "
            f"foliage_infos={native_infos} foliage_instances={native_instances}"
        )
        print(f"world-geometry capture archive: {archive}")
        print(f"world-geometry capture report: {report_path}")
        print(f"world-geometry capture elapsed: {time.perf_counter() - started:.2f}s")
        return 0

    capture.semantic_report = semantic_report
    capture._capture_cli = capture_cli
    capture._world_geometry_native_foliage_installed = True
