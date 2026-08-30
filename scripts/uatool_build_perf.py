#!/usr/bin/env python3
"""Cross-project Unreal build acceleration for UnrealAssetTool.

The canonical plugin is temporarily staged under <Target>/Plugins so UBT can
resolve it. Historically that staging directory was deleted after every scan,
which also deleted the plugin's Binaries/Intermediate and forced a cold compile
on the next run. This module preserves those build products under Saved and
restores them for the next invocation.

When the target already has a valid Editor runtime manifest, building the whole
Editor target again is unnecessary for a scanner-only source change. We first
build only UnrealAssetTool with UBT's ForceUnity option, then fall back to the
old full-target build if the module-only path fails.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

CACHE_DIR_NAME = "UnrealAssetToolBuildCache"
CACHE_DIRS = ("Binaries", "Intermediate")


def _cache_enabled() -> bool:
    value = os.environ.get("UATOOL_BUILD_CACHE", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _runtime_manifest_ready(core, project: Path, editor: Path) -> bool:
    manifest = core.project_runtime_manifest(project, editor)
    if not manifest.is_file():
        return False
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data.get("BuildId"), str) and bool(data.get("BuildId"))


def _run_timed(command: list[str], label: str) -> int:
    print(f"{label}:", subprocess.list2cmdline(command))
    started = time.perf_counter()
    result = subprocess.run(command, check=False).returncode
    elapsed = time.perf_counter() - started
    print(f"{label} elapsed: {elapsed:.2f}s")
    return result


def _optimized_build_project(core, project: Path, editor: Path, build_script_arg: str | None, active_plugin_root: Path | None = None) -> int:
    build_script = core.resolve_build_script(editor, build_script_arg)
    target = f"{project.stem}Editor"
    configuration = core.editor_configuration(editor)

    module_command = [
        str(build_script),
        f"-Target={target} Win64 {configuration}",
        f"-Module={core.MODULE_NAME}",
        f"-Project={project}",
        "-WaitMutex",
        "-NoHotReloadFromIDE",
        "-ForceUnity",
    ]

    if _runtime_manifest_ready(core, project, editor):
        print("target runtime manifest ready; skipping full Editor target rebuild")
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
    # The runtime scanner never needs standalone PDBs. Removing only PDB output
    # keeps the persistent cache smaller without discarding object/PCH inputs that
    # make the next compile incremental.
    binaries = cache_root / "Binaries"
    if binaries.is_dir():
        for pdb in binaries.rglob("*.pdb"):
            try:
                pdb.unlink()
            except OSError:
                pass
    if saved:
        print(f"saved staged plugin build cache: {cache_root} ({', '.join(saved)})")


def install(core) -> None:
    """Patch uatool_core's staging/build globals in place."""
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
