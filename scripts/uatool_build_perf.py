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

Cross-project staging and freshness checks are plugin-root aware. Large Unreal
projects can contain many gigabytes below Plugins/*/Content; walking those trees
to find descriptors or native build inputs can dominate wall-clock time while
remaining invisible to UBT's own timing. We stop at plugin roots, inspect only
plugin descriptors and Source trees, and time staging/cache filesystem work.
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
import uatool_zonegraph_mass_evidence as zonegraph_mass_evidence
import uatool_mover_behavior as mover_behavior
import uatool_systems as systems
import uatool_systems_mover as systems_mover
import uatool_systems_gameplay_cameras as systems_gameplay_cameras
import uatool_systems_mass_zonegraph as systems_mass_zonegraph
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
SKIP_INPUT_DIRS = {
    "binaries",
    "content",
    "deriveddatacache",
    "intermediate",
    "resources",
    "saved",
    ".git",
    ".vs",
}
PLUGIN_DISCOVERY_PRUNE_DIRS = SKIP_INPUT_DIRS | {"config", "documentation", "screenshots"}


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


def _discover_plugin_roots(plugins_root: Path, descriptor_name: str | None = None) -> list[Path]:
    """Discover plugin roots without walking inside already identified plugins.

    Unreal plugins are rooted by a *.uplugin descriptor. Once a directory has a
    descriptor, Content/Source/etc. belong to that plugin and cannot contain a
    separately discoverable project plugin for UBT purposes. Category folders
    above plugin roots are still traversed, so layouts such as
    Plugins/Runtime/Foo/Foo.uplugin remain supported.
    """
    plugins_root = Path(plugins_root)
    if not plugins_root.is_dir():
        return []

    wanted = descriptor_name.lower() if descriptor_name else None
    pending = [plugins_root]
    found: list[Path] = []
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue

        descriptors = [
            entry for entry in entries
            if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".uplugin")
        ]
        if descriptors:
            if wanted is None or any(entry.name.lower() == wanted for entry in descriptors):
                found.append(current.resolve())
            # A directory containing a descriptor is a plugin root. Do not walk
            # its Content/Source trees looking for unrelated descriptors.
            continue

        children = [
            Path(entry.path)
            for entry in entries
            if entry.is_dir(follow_symlinks=False)
            and entry.name.lower() not in PLUGIN_DISCOVERY_PRUNE_DIRS
        ]
        children.sort(key=lambda path: str(path).lower(), reverse=True)
        pending.extend(children)

    return sorted(set(found), key=lambda path: str(path).lower())


def _iter_native_tree(root: Path, active_plugin_root: Path | None):
    if not root.is_dir():
        return
    for walk_root, dirs, files in os.walk(root):
        root_path = Path(walk_root)
        dirs[:] = [name for name in dirs if name.lower() not in SKIP_INPUT_DIRS]
        if _is_below(root_path, active_plugin_root):
            dirs[:] = []
            continue
        for name in files:
            path = root_path / name
            if path.suffix.lower() in NATIVE_INPUT_SUFFIXES:
                yield path


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

    For Plugins we inspect descriptor files plus each plugin's Source subtree;
    plugin Content/Resources are not native build inputs and are intentionally
    never traversed.
    """
    project_dir = project.parent.resolve()
    active_plugin_root = active_plugin_root.resolve() if active_plugin_root else None
    candidates: list[Path] = [project]

    candidates.extend(_iter_native_tree(project_dir / "Source", active_plugin_root) or ())

    plugins_root = project_dir / "Plugins"
    discovery_started = time.perf_counter()
    plugin_roots = _discover_plugin_roots(plugins_root)
    discovery_elapsed = time.perf_counter() - discovery_started
    if plugins_root.is_dir():
        print(f"plugin-root discovery elapsed: {discovery_elapsed:.2f}s roots={len(plugin_roots)}")

    for plugin_root in plugin_roots:
        if _is_below(plugin_root, active_plugin_root):
            continue
        try:
            descriptors = sorted(plugin_root.glob("*.uplugin"), key=lambda path: str(path).lower())
        except OSError:
            descriptors = []
        candidates.extend(descriptors)
        candidates.extend(_iter_native_tree(plugin_root / "Source", active_plugin_root) or ())

    newer: list[Path] = []
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

    started = time.perf_counter()
    newer = _target_native_inputs_newer_than(
        project,
        manifest_mtime,
        active_plugin_root=active_plugin_root,
    )
    print(f"target native freshness check elapsed: {time.perf_counter() - started:.2f}s")
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
    started = time.perf_counter()
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
    elapsed = time.perf_counter() - started
    if restored:
        print(
            f"restored staged plugin build cache: {cache_root} "
            f"({', '.join(restored)}) elapsed={elapsed:.2f}s"
        )
    else:
        print(f"staged plugin build cache restore elapsed: {elapsed:.2f}s (nothing restored)")


def _save_cache(cache_root: Path, stage_root: Path) -> None:
    if not _cache_enabled():
        return
    started = time.perf_counter()
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
    elapsed = time.perf_counter() - started
    if saved:
        print(
            f"saved staged plugin build cache: {cache_root} "
            f"({', '.join(saved)}) elapsed={elapsed:.2f}s"
        )
    else:
        print(f"staged plugin build cache save elapsed: {elapsed:.2f}s (nothing saved)")


@contextmanager
def _optimized_stage(core, project: Path):
    """Stage the canonical checkout without recursively walking plugin payloads."""
    canonical = core.plugin_root().resolve()
    project_dir = project.parent.resolve()
    plugins_root = project_dir / "Plugins"

    try:
        canonical.relative_to(plugins_root.resolve())
        print(f"using project-local canonical plugin: {canonical}")
        yield canonical
        return
    except (ValueError, FileNotFoundError):
        pass

    plugins_root.mkdir(parents=True, exist_ok=True)
    stage_root = plugins_root / core.MODULE_NAME
    backup_root = project_dir / "Saved" / "UnrealAssetToolCrossProjectBackup" / str(os.getpid())
    moved: list[tuple[Path, Path]] = []

    scan_started = time.perf_counter()
    existing_roots = _discover_plugin_roots(plugins_root, f"{core.MODULE_NAME}.uplugin")
    print(
        f"plugin staging duplicate scan elapsed: {time.perf_counter() - scan_started:.2f}s "
        f"matches={len(existing_roots)}"
    )

    for plugin_dir in existing_roots:
        relative = plugin_dir.relative_to(plugins_root.resolve())
        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise RuntimeError(
                "Cannot back up target-project UnrealAssetTool plugin because "
                f"the temporary backup path already exists:\n  {backup}"
            )
        print(f"temporarily moving target plugin out of Plugins: {plugin_dir}")
        move_started = time.perf_counter()
        shutil.move(str(plugin_dir), str(backup))
        print(f"target plugin backup move elapsed: {time.perf_counter() - move_started:.2f}s")
        moved.append((plugin_dir, backup))

    try:
        if stage_root.exists():
            raise RuntimeError(
                "Cross-project staging path is unexpectedly occupied after "
                f"duplicate-plugin backup:\n  {stage_root}"
            )

        copy_started = time.perf_counter()
        stage_root.mkdir(parents=True, exist_ok=False)
        shutil.copy2(canonical / "UnrealAssetTool.uplugin", stage_root / "UnrealAssetTool.uplugin")
        shutil.copytree(canonical / "Source", stage_root / "Source")
        print(f"plugin staging source copy elapsed: {time.perf_counter() - copy_started:.2f}s")
        print(f"staged canonical plugin for target: {stage_root}")
        print(f"canonical plugin source: {canonical}")
        yield stage_root
    finally:
        if stage_root.exists():
            print(f"removing staged target plugin: {stage_root}")
            cleanup_started = time.perf_counter()
            shutil.rmtree(stage_root, ignore_errors=False)
            print(f"plugin staging cleanup elapsed: {time.perf_counter() - cleanup_started:.2f}s")

        for original, backup in reversed(moved):
            if backup.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                restore_started = time.perf_counter()
                shutil.move(str(backup), str(original))
                print(
                    f"restored target plugin: {original} "
                    f"elapsed={time.perf_counter() - restore_started:.2f}s"
                )

        if backup_root.exists():
            # Remove only empty scaffolding created by this invocation.
            current = backup_root
            saved_boundary = project_dir / "Saved"
            while current != saved_boundary and current.exists():
                try:
                    current.rmdir()
                except OSError:
                    break
                current = current.parent


def install(core) -> None:
    """Patch uatool_core's staging/build/bundle globals in place."""

    @contextmanager
    def cached_stage(project: Path):
        canonical = core.plugin_root().resolve()
        with _optimized_stage(core, project) as active_root:
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
    systems_mass_zonegraph.install(systems)
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
    zonegraph_mass_evidence.install(runtime)
