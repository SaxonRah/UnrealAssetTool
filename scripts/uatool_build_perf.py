#!/usr/bin/env python3
"""Cross-project Unreal build acceleration for UnrealAssetTool.

The canonical plugin is temporarily staged under <Target>/Plugins so UBT can
resolve it. Historically that staging directory was deleted after every scan,
which also deleted the plugin's Binaries/Intermediate and forced a cold compile
on the next run. This module preserves those build products under Saved and
restores them for the next invocation.

When the target already has a valid, up-to-date Editor runtime manifest, building
the whole Editor target again is unnecessary for a scanner-only source change.
We first build only UnrealAssetTool with forced unity and adaptive-unity exclusion
disabled for that isolated module build, then fall back to the old full-target
build if the module-only path fails.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import uatool_bundle_perf as bundle_perf
import uatool_sqlite_perf as sqlite_perf
import uatool_validation_perf as validation_perf
import uatool_blueprint_enums as blueprint_enums
import uatool_blueprint_enum_edges as blueprint_enum_edges
import uatool_chooser_derived as chooser_derived
import uatool_chooser_graph as chooser_graph
import uatool_mover_report as mover_report
import uatool_gameplay_camera_report as gameplay_camera_report
import uatool_gameplay_camera_selection_report as gameplay_camera_selection_report
import uatool_gameplay_camera_director_report as gameplay_camera_director_report
import uatool_gameplay_camera_behavior as gameplay_camera_behavior
import uatool_gameplay_camera_behavior_graph as gameplay_camera_behavior_graph
import uatool_mover_behavior as mover_behavior
import uatool_systems as systems
import uatool_systems_mover as systems_mover
import uatool_systems_gameplay_cameras as systems_gameplay_cameras
import uatool_project_graph as project_graph
import uatool_mover_graph as mover_graph
import uatool_gameplay_camera_graph as gameplay_camera_graph
import uatool_runtime as runtime

CACHE_DIR_NAME = "UnrealAssetToolBuildCache"
CACHE_DIRS = ("Binaries", "Intermediate")
NATIVE_INPUT_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx",
    ".h", ".hh", ".hpp", ".inl",
    ".cs", ".uplugin", ".uproject",
}
SKIP_INPUT_DIRS = {"binaries", "deriveddatacache", "intermediate", "saved", ".git", ".vs"}


def _cache_enabled() -> bool:
    value = os.environ.get("UATOOL_BUILD_CACHE", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _runtime_manifest(core, project: Path, editor: Path) -> Path | None:
    manifest = core.project_runtime_manifest(project, editor)
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data.get("BuildId"), str) or not data.get("BuildId"):
        return None
    return manifest


def _is_below(path: Path, root: Path | None) -> bool:
    if root is None:
        return False
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _target_native_inputs_newer_than(
    project: Path,
    timestamp: float,
    *,
    active_plugin_root: Path | None,
) -> list[Path]:
    """Return target-owned native/build inputs newer than a runtime manifest.

    The staged UnrealAssetTool source is intentionally excluded: it is exactly
    what the module-only invocation is about to compile. Native project modules
    and all other project plugins remain part of the freshness gate.
    """
    project_dir = project.parent.resolve()
    active_plugin_root = active_plugin_root.resolve() if active_plugin_root else None
    newer: list[Path] = []

    candidates = [project]
    for top_name in ("Source", "Plugins"):
        top = project_dir / top_name
        if not top.is_dir():
            continue
        for root, dirs, files in os.walk(top):
            root_path = Path(root)
            dirs[:] = [name for name in dirs if name.lower() not in SKIP_INPUT_DIRS]
            if _is_below(root_path, active_plugin_root):
                dirs[:] = []
                continue
            for name in files:
                path = root_path / name
                if path.suffix.lower() in NATIVE_INPUT_SUFFIXES:
                    candidates.append(path)

    for path in candidates:
        if _is_below(path, active_plugin_root):
            continue
        try:
            if path.stat().st_mtime > timestamp:
                newer.append(path)
        except OSError:
            continue
    newer.sort(key=lambda item: str(item).lower())
    return newer


def _module_only_is_safe(core, project: Path, editor: Path, active_plugin_root: Path | None) -> bool:
    manifest = _runtime_manifest(core, project, editor)
    if manifest is None:
        print("target runtime manifest missing/invalid; full Editor target build required")
        return False
    try:
        manifest_mtime = manifest.stat().st_mtime
    except OSError:
        return False
    newer = _target_native_inputs_newer_than(
        project,
        manifest_mtime,
        active_plugin_root=active_plugin_root,
    )
    if not newer:
        return True
    print(
        "target native/build inputs changed after runtime manifest; "
        "full Editor target build required"
    )
    for path in newer[:8]:
        print(f"  newer target input: {path}")
    if len(newer) > 8:
        print(f"  ... {len(newer) - 8} more")
    return False


def _run_timed(command: list[str], label: str) -> int:
    print(f"{label}:", subprocess.list2cmdline(command))
    started = time.perf_counter()
    result = subprocess.run(command, check=False).returncode
    elapsed = time.perf_counter() - started
    print(f"{label} elapsed: {elapsed:.2f}s")
    return result


def _optimized_build_project(
    core,
    project: Path,
    editor: Path,
    build_script_arg: str | None,
    active_plugin_root: Path | None = None,
) -> int:
    build_script = core.resolve_build_script(editor, build_script_arg)
    target = f"{project.stem}Editor"
    configuration = core.editor_configuration(editor)

    # The staged scanner appears as a changed/untracked working set in many
    # target projects, which causes adaptive unity to exclude every handwritten
    # UnrealAssetTool .cpp even when -ForceUnity is present. This invocation is
    # already restricted to -Module=UnrealAssetTool, so disable adaptive unity
    # only for this scanner build and keep the target project's normal policy
    # untouched for ordinary builds.
    module_command = [
        str(build_script),
        f"-Target={target} Win64 {configuration}",
        f"-Module={core.MODULE_NAME}",
        f"-Project={project}",
        "-WaitMutex",
        "-NoHotReloadFromIDE",
        "-ForceUnity",
        "-DisableAdaptiveUnity",
    ]

    if _module_only_is_safe(core, project, editor, active_plugin_root):
        print("target runtime manifest is current; skipping full Editor target rebuild")
        result = _run_timed(module_command, "building UnrealAssetTool module")
        if result == 0:
            return 0
        print("module-only build failed; falling back to full Editor target build")

    target_command = [
        str(build_script),
        f"-Target={target} Win64 {configuration}",
        f"-Project={project}",
        "-WaitMutex",
        "-NoHotReloadFromIDE",
    ]
    result = _run_timed(target_command, "building target")
    if result != 0:
        return result

    # A normal project-plugin target build usually emitted the module already.
    # Avoid a redundant second UBT invocation when the real DLL is present.
    try:
        core.resolve_plugin_binary(project, editor, active_plugin_root)
        print("full target build already produced UnrealAssetTool; module rebuild not needed")
        return 0
    except RuntimeError:
        pass

    return _run_timed(module_command, "building UnrealAssetTool module")


def _cache_root(project: Path) -> Path:
    return project.parent / "Saved" / CACHE_DIR_NAME


def _restore_cache(cache_root: Path, stage_root: Path) -> None:
    if not _cache_enabled() or not cache_root.is_dir():
        return
    restored = []
    for name in CACHE_DIRS:
        source = cache_root / name
        target = stage_root / name
        if not source.exists():
            continue
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(source), str(target))
        restored.append(name)
    if restored:
        print(f"restored staged plugin build cache: {cache_root} ({', '.join(restored)})")


def _save_cache(cache_root: Path, stage_root: Path) -> None:
    if not _cache_enabled():
        return
    cache_root.mkdir(parents=True, exist_ok=True)
    saved = []
    for name in CACHE_DIRS:
        source = stage_root / name
        target = cache_root / name
        if not source.exists():
            continue
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(source), str(target))
        saved.append(name)
    # Keep all UBT-declared build products, including PDBs. A missing output can
    # turn a would-be warm no-op into a relink/rebuild; the cache exists to favor
    # speed, while upload/output size is addressed independently by schema 14.
    if saved:
        print(f"saved staged plugin build cache: {cache_root} ({', '.join(saved)})")


def install(core) -> None:
    """Patch uatool_core's staging/build/bundle globals in place."""
    base_stage = core.stage_invoking_plugin_checkout

    @contextmanager
    def cached_stage(project: Path):
        canonical = core.plugin_root().resolve()
        with base_stage(project) as active_root:
            active_root = Path(active_root).resolve()
            # Project-local canonical builds already persist naturally.
            if active_root == canonical:
                yield active_root
                return

            cache_root = _cache_root(project)
            _restore_cache(cache_root, active_root)
            try:
                yield active_root
            finally:
                _save_cache(cache_root, active_root)

    core.stage_invoking_plugin_checkout = cached_stage
    core.build_project = lambda project, editor, build_script_arg=None, active_plugin_root=None: _optimized_build_project(
        core, project, editor, build_script_arg, active_plugin_root
    )

    # These policies/installers must run before the composition root captures
    # core globals. Blueprint enum support is installed here after canonical
    # cleanup has already installed logical compact-pin expansion.
    bundle_perf.install(core)
    sqlite_perf.install(core)
    validation_perf.install()
    systems_mover.install(systems)
    systems_gameplay_cameras.install(systems)
    mover_behavior.install(core, runtime)
    mover_graph.install(project_graph)
    gameplay_camera_graph.install(project_graph)
    blueprint_enums.install(core, runtime)
    blueprint_enum_edges.install(core)
    chooser_derived.install(core, runtime)
    gameplay_camera_behavior.install(core, runtime)
    chooser_graph.install(project_graph)
    gameplay_camera_behavior_graph.install(project_graph)
    mover_report.install(runtime)
    gameplay_camera_report.install(runtime)
    gameplay_camera_selection_report.install(runtime)
    gameplay_camera_director_report.install(runtime)
