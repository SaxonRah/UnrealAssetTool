#!/usr/bin/env python3
"""UnrealAssetTool launcher, SQLite packer, and text query utility."""

from __future__ import annotations

import argparse
import collections
from contextlib import contextmanager
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Iterator

import uatool_native as native_cpp

DB_NAME = "uat.db"
MODULE_NAME = "UnrealAssetTool"
BLUEPRINT_CALL_BINDING_SCHEMA_VERSION = 2

WORLD_RAW_FILES = (
    "world_manifest.json",
    "worlds.jsonl",
    "world_levels.jsonl",
    "world_actors.jsonl",
    "world_components.jsonl",
    "world_instance_properties.jsonl",
    "world_references.jsonl",
    "world_data_layers.jsonl",
    "world_partition_actor_descs.jsonl",
)


def iter_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc


def require_editor(editor_arg: str) -> Path:
    """Return exactly the Unreal Editor executable supplied by the user."""
    editor = Path(editor_arg).expanduser().resolve()
    if not editor.is_file():
        raise FileNotFoundError(
            "Unreal editor executable does not exist:\n"
            f"  {editor}\n"
            "Pass the exact UnrealEditor-Cmd.exe path with --editor."
        )
    return editor


def plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent


def plugin_descriptor(root: Path | None = None) -> Path:
    """Return the UnrealAssetTool descriptor for a plugin root."""
    descriptor = (root or plugin_root()) / "UnrealAssetTool.uplugin"
    if not descriptor.is_file():
        raise FileNotFoundError(
            "UnrealAssetTool.uplugin was not found beside this launcher:\n"
            f"  {descriptor}"
        )
    return descriptor


@contextmanager
def stage_invoking_plugin_checkout(project: Path):
    """Expose this canonical checkout to a target as a temporary project plugin.

    UBT reliably discovers module rules for plugins below <Project>/Plugins.
    Rather than depending on foreign-plugin target modes, cross-project scans
    stage only this checkout's descriptor and Source tree at the conventional
    target-project location for the duration of build + commandlet execution.

    If the target already has UnrealAssetTool plugin directories, move them
    completely outside Plugins first and restore them byte-for-byte afterward.
    The canonical project itself needs no staging.
    """
    canonical = plugin_root().resolve()
    project_dir = project.parent.resolve()
    plugins_root = project_dir / "Plugins"

    try:
        canonical.relative_to(plugins_root.resolve())
        # The invoking checkout is already a project-local plugin for this target.
        print(f"using project-local canonical plugin: {canonical}")
        yield canonical
        return
    except (ValueError, FileNotFoundError):
        pass

    plugins_root.mkdir(parents=True, exist_ok=True)
    stage_root = plugins_root / MODULE_NAME
    backup_root = project_dir / "Saved" / "UnrealAssetToolCrossProjectBackup" / str(os.getpid())
    moved: list[tuple[Path, Path]] = []

    # Move every existing same-named plugin directory completely outside Plugins.
    # Renaming only the descriptor or directory inside Plugins is insufficient
    # because UBT recursively discovers *.uplugin files below that tree.
    descriptors = sorted(plugins_root.rglob(f"{MODULE_NAME}.uplugin"))
    seen_roots: set[Path] = set()
    for descriptor in descriptors:
        plugin_dir = descriptor.parent.resolve()
        if plugin_dir in seen_roots:
            continue
        seen_roots.add(plugin_dir)

        relative = plugin_dir.relative_to(plugins_root.resolve())
        backup = backup_root / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise RuntimeError(
                "Cannot back up target-project UnrealAssetTool plugin because "
                f"the temporary backup path already exists:\n  {backup}"
            )
        print(f"temporarily moving target plugin out of Plugins: {plugin_dir}")
        shutil.move(str(plugin_dir), str(backup))
        moved.append((plugin_dir, backup))

    try:
        if stage_root.exists():
            raise RuntimeError(
                "Cross-project staging path is unexpectedly occupied after "
                f"duplicate-plugin backup:\n  {stage_root}"
            )

        stage_root.mkdir(parents=True, exist_ok=False)
        shutil.copy2(canonical / "UnrealAssetTool.uplugin", stage_root / "UnrealAssetTool.uplugin")
        shutil.copytree(canonical / "Source", stage_root / "Source")

        print(f"staged canonical plugin for target: {stage_root}")
        print(f"canonical plugin source: {canonical}")
        yield stage_root
    finally:
        if stage_root.exists():
            print(f"removing staged target plugin: {stage_root}")
            shutil.rmtree(stage_root, ignore_errors=False)

        for original, backup in reversed(moved):
            if backup.exists():
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(backup), str(original))
                print(f"restored target plugin: {original}")

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


def editor_configuration(editor: Path) -> str:
    """Infer only the build configuration encoded by the exact editor filename.

    This does not discover an engine installation. Unreal's unsuffixed
    UnrealEditor[ -Cmd ].exe is the Development editor. Configuration-specific
    executables encode their configuration in the filename.
    """
    name = editor.name.lower()
    if "-debuggame" in name:
        return "DebugGame"
    if "-debug" in name:
        return "Debug"
    if "-test" in name:
        return "Test"
    if "-shipping" in name:
        return "Shipping"
    return "Development"



def editor_module_configuration(editor: Path) -> str:
    """Return the binary naming configuration for Editor/plugin modules.

    A DebugGame Editor target keeps Editor/plugin modules in Development form,
    so UnrealAssetTool is built as UnrealEditor-UnrealAssetTool.dll while the
    project's game module remains DebugGame.
    """
    configuration = editor_configuration(editor)
    return "Development" if configuration == "DebugGame" else configuration




def runtime_manifest_name(editor: Path) -> str:
    """Return the module-manifest filename consumed by the running Editor."""
    configuration = editor_configuration(editor)
    if configuration == "Development":
        return "UnrealEditor.modules"
    return f"UnrealEditor-Win64-{configuration}.modules"


def project_runtime_manifest(project: Path, editor: Path) -> Path:
    return project.parent / "Binaries" / "Win64" / runtime_manifest_name(editor)


def plugin_runtime_manifest(editor: Path, root: Path | None = None) -> Path:
    return (root or plugin_root()) / "Binaries" / "Win64" / runtime_manifest_name(editor)


def plugin_binary_candidates(root: Path | None = None) -> list[Path]:
    binaries = (root or plugin_root()) / "Binaries" / "Win64"
    if not binaries.is_dir():
        return []
    return sorted(
        path
        for path in binaries.glob(f"UnrealEditor-{MODULE_NAME}*.dll")
        if path.is_file()
    )


def _module_from_manifest(manifest: Path, root: Path) -> Path | None:
    """Resolve UnrealAssetTool's DLL exactly as Unreal recorded it."""
    if not manifest.is_file():
        return None
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    modules = data.get("Modules")
    if not isinstance(modules, dict):
        return None

    filename = modules.get(MODULE_NAME)
    if not isinstance(filename, str) or not filename:
        return None

    candidate = root / "Binaries" / "Win64" / filename
    return candidate if candidate.is_file() else None


def resolve_plugin_binary(project: Path, editor: Path, root: Path | None = None) -> Path:
    """Return the DLL UBT actually produced for UnrealAssetTool.

    Do not infer DebugGame plugin-module naming. UE 5.8 can emit either the
    unsuffixed Editor-module form or a Win64-DebugGame-suffixed form depending
    on how the plugin participates in the target. Generated module manifests
    are authoritative.
    """
    root = (root or plugin_root()).resolve()

    plugin_manifest = plugin_runtime_manifest(editor, root)
    from_plugin_manifest = _module_from_manifest(plugin_manifest, root)
    if from_plugin_manifest is not None:
        print(f"module resolved from plugin manifest: {from_plugin_manifest}")
        return from_plugin_manifest

    project_manifest = project_runtime_manifest(project, editor)
    from_project_manifest = _module_from_manifest(project_manifest, root)
    if from_project_manifest is not None:
        print(f"module resolved from project manifest: {from_project_manifest}")
        return from_project_manifest

    candidates = plugin_binary_candidates(root)
    if len(candidates) == 1:
        print(f"module resolved from unique UBT output: {candidates[0]}")
        return candidates[0]

    if not candidates:
        raise RuntimeError(
            "UBT completed, but no UnrealAssetTool Editor DLL was found under:\n"
            f"  {root / 'Binaries' / 'Win64'}"
        )

    candidate_text = "\n".join(f"  {path}" for path in candidates)
    raise RuntimeError(
        "UBT produced multiple UnrealAssetTool DLLs and no generated module "
        "manifest identified which one the running Editor should load.\n"
        f"Candidates:\n{candidate_text}"
    )


def ensure_plugin_runtime_manifest(
    project: Path,
    editor: Path,
    root: Path | None = None,
    binary: Path | None = None,
) -> Path:
    """Make the staged/local plugin manifest agree with target BuildId + real DLL."""
    root = (root or plugin_root()).resolve()
    source = project_runtime_manifest(project, editor)
    target = plugin_runtime_manifest(editor, root)
    binary = binary or resolve_plugin_binary(project, editor, root)

    if not source.is_file():
        raise RuntimeError(
            "The target project's runtime module manifest is missing.\n"
            f"Expected: {source}\n"
            "Build the full Editor target for this project once, then rerun the scan."
        )

    try:
        source_data = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Could not read target runtime module manifest:\n  {source}"
        ) from exc

    build_id = source_data.get("BuildId")
    if not isinstance(build_id, str) or not build_id:
        raise RuntimeError(
            "Target runtime module manifest has no usable BuildId:\n"
            f"  {source}"
        )

    desired = {
        "BuildId": build_id,
        "Modules": {
            MODULE_NAME: binary.name,
        },
    }

    current = None
    if target.is_file():
        try:
            current = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current = None

    if current != desired:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(desired, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"runtime module manifest repaired: {target}")
    else:
        print(f"runtime module manifest ready: {target}")

    print(f"runtime module DLL: {binary.name}")
    print(f"runtime BuildId source: {source}")
    return target


def resolve_build_script(editor: Path, override: str | None) -> Path:
    if override:
        build_script = Path(override).expanduser().resolve()
    else:
        # The editor path is explicit. We do not search for an engine. For a
        # normal Launcher or source build, UnrealEditor-Cmd.exe lives at:
        #   <EngineRoot>/Engine/Binaries/Win64/UnrealEditor-Cmd.exe
        # so Engine is exactly three parents above the executable.
        try:
            engine_dir = editor.parents[2]
        except IndexError as exc:
            raise FileNotFoundError(
                "Could not derive Engine/Build/BatchFiles/Build.bat from --editor. "
                "Pass --build-script explicitly."
            ) from exc
        build_script = engine_dir / "Build" / "BatchFiles" / "Build.bat"

    if not build_script.is_file():
        raise FileNotFoundError(
            "Unreal build script does not exist:\n"
            f"  {build_script}\n"
            "Pass it explicitly with --build-script if your custom engine uses a nonstandard layout."
        )
    return build_script



def build_project(
    project: Path,
    editor: Path,
    build_script_arg: str | None = None,
    active_plugin_root: Path | None = None,
) -> int:
    """Build target readiness first, then UnrealAssetTool explicitly.

    The full Editor target produces the project's native DebugGame modules and
    matching runtime BuildId. The second incremental UBT invocation explicitly
    builds UnrealAssetTool from this checkout.
    """
    build_script = resolve_build_script(editor, build_script_arg)
    target = f"{project.stem}Editor"
    configuration = editor_configuration(editor)

    target_command = [
        str(build_script),
        f"-Target={target} Win64 {configuration}",
        f"-Project={project}",
        "-WaitMutex",
        "-NoHotReloadFromIDE",
    ]
    print("building target:", subprocess.list2cmdline(target_command))
    result = subprocess.run(target_command, check=False).returncode
    if result != 0:
        return result

    module_command = [
        str(build_script),
        f"-Target={target} Win64 {configuration}",
        f"-Module={MODULE_NAME}",
        f"-Project={project}",
        "-WaitMutex",
        "-NoHotReloadFromIDE",
    ]
    print("building module:", subprocess.list2cmdline(module_command))
    return subprocess.run(module_command, check=False).returncode




def ensure_plugin_binary(
    project: Path,
    editor: Path,
    build_script_arg: str | None,
    no_build: bool,
    active_plugin_root: Path | None = None,
) -> Path:
    configuration = editor_configuration(editor)
    active_plugin_root = (active_plugin_root or plugin_root()).resolve()

    print(f"editor target configuration: {configuration}")
    print(f"active plugin root: {active_plugin_root}")

    if not no_build:
        result = build_project(project, editor, build_script_arg, active_plugin_root)
        if result != 0:
            raise RuntimeError(f"Unreal build failed with exit code {result}")

    try:
        binary = resolve_plugin_binary(project, editor, active_plugin_root)
    except RuntimeError:
        if no_build:
            raise RuntimeError(
                f"{MODULE_NAME} is not built for the selected target.\n"
                "Run without --no-build so UBT can build the staged/project-local module."
            )
        raise

    print(f"module ready: {binary}")
    ensure_plugin_runtime_manifest(
        project,
        editor,
        active_plugin_root,
        binary,
    )
    return binary


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;

        CREATE TABLE meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE files (
            path TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            extension TEXT NOT NULL,
            size INTEGER NOT NULL,
            modified_utc TEXT NOT NULL,
            json TEXT NOT NULL
        );

        CREATE TABLE source_chunks (
            id INTEGER PRIMARY KEY,
            path TEXT NOT NULL,
            start_line INTEGER NOT NULL,
            end_line INTEGER NOT NULL,
            text TEXT NOT NULL
        );
        CREATE INDEX source_chunks_path_idx ON source_chunks(path, start_line);

        CREATE TABLE assets (
            object_path TEXT PRIMARY KEY,
            asset_name TEXT NOT NULL,
            package_name TEXT NOT NULL,
            package_path TEXT NOT NULL,
            class_path TEXT NOT NULL,
            disk_path TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX assets_package_idx ON assets(package_name);
        CREATE INDEX assets_class_idx ON assets(class_path);

        CREATE TABLE asset_dependencies (
            source_package TEXT NOT NULL,
            target_package TEXT NOT NULL,
            category TEXT NOT NULL,
            PRIMARY KEY(source_package, target_package, category)
        );
        CREATE INDEX asset_deps_target_idx ON asset_dependencies(target_package);

        CREATE TABLE blueprints (
            object_path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_class TEXT NOT NULL,
            generated_class TEXT NOT NULL,
            blueprint_type INTEGER NOT NULL,
            graph_count INTEGER NOT NULL,
            json TEXT NOT NULL
        );

        CREATE TABLE blueprint_graphs (
            graph_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            graph_path TEXT NOT NULL,
            graph_kind TEXT NOT NULL,
            graph_system TEXT NOT NULL,
            graph_class TEXT NOT NULL,
            schema_class TEXT NOT NULL,
            outer_path TEXT NOT NULL,
            outer_class TEXT NOT NULL,
            parent_node_guid TEXT NOT NULL,
            parent_graph_path TEXT NOT NULL,
            node_count INTEGER NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_graphs_blueprint_idx ON blueprint_graphs(blueprint_path, graph_name);
        CREATE INDEX bp_graphs_system_idx ON blueprint_graphs(graph_system, graph_kind);

        CREATE TABLE blueprint_interfaces (
            blueprint_path TEXT NOT NULL,
            interface_class TEXT NOT NULL,
            interface_name TEXT NOT NULL,
            graphs_json TEXT NOT NULL,
            PRIMARY KEY(blueprint_path, interface_class)
        );
        CREATE INDEX bp_interfaces_class_idx ON blueprint_interfaces(interface_class);

        CREATE TABLE blueprint_variables (
            blueprint_path TEXT NOT NULL,
            name TEXT NOT NULL,
            guid TEXT NOT NULL,
            category TEXT NOT NULL,
            default_value TEXT NOT NULL,
            property_flags INTEGER NOT NULL,
            type_json TEXT NOT NULL,
            PRIMARY KEY(blueprint_path, name)
        );
        CREATE INDEX bp_variables_name_idx ON blueprint_variables(name);

        CREATE TABLE blueprint_components (
            blueprint_path TEXT NOT NULL,
            variable_name TEXT NOT NULL,
            component_class TEXT NOT NULL,
            template_path TEXT NOT NULL,
            parent_component_or_variable TEXT NOT NULL,
            parent_owner_class TEXT NOT NULL,
            attach_to TEXT NOT NULL,
            guid TEXT NOT NULL,
            is_root INTEGER NOT NULL,
            PRIMARY KEY(blueprint_path, variable_name)
        );
        CREATE INDEX bp_components_class_idx ON blueprint_components(component_class);
        CREATE INDEX bp_components_parent_idx ON blueprint_components(blueprint_path, parent_component_or_variable);

        CREATE TABLE blueprint_nodes (
            node_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            graph_kind TEXT NOT NULL,
            node_class TEXT NOT NULL,
            operation TEXT NOT NULL,
            symbol TEXT NOT NULL,
            owner TEXT NOT NULL,
            title TEXT NOT NULL,
            comment TEXT NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_nodes_blueprint_idx ON blueprint_nodes(blueprint_path, graph_name);
        CREATE INDEX bp_nodes_title_idx ON blueprint_nodes(title);
        CREATE INDEX bp_nodes_operation_idx ON blueprint_nodes(operation);
        CREATE INDEX bp_nodes_symbol_idx ON blueprint_nodes(symbol);
        CREATE INDEX bp_nodes_owner_idx ON blueprint_nodes(owner);

        CREATE TABLE blueprint_pins (
            pin_id TEXT PRIMARY KEY,
            node_id TEXT NOT NULL,
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            pin_index INTEGER NOT NULL,
            name TEXT NOT NULL,
            direction TEXT NOT NULL,
            pin_category TEXT NOT NULL,
            pin_subcategory TEXT NOT NULL,
            pin_subcategory_object TEXT NOT NULL,
            container_type INTEGER NOT NULL,
            default_value TEXT NOT NULL,
            default_object TEXT NOT NULL,
            default_text TEXT NOT NULL,
            hidden INTEGER NOT NULL,
            not_connectable INTEGER NOT NULL,
            linked_count INTEGER NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_pins_node_idx ON blueprint_pins(node_id, pin_index);
        CREATE INDEX bp_pins_category_idx ON blueprint_pins(pin_category, direction);
        CREATE INDEX bp_pins_default_object_idx ON blueprint_pins(default_object);

        CREATE TABLE blueprint_node_properties (
            node_id TEXT NOT NULL,
            blueprint_path TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            node_class TEXT NOT NULL,
            property_name TEXT NOT NULL,
            property_path TEXT NOT NULL,
            owner_class TEXT NOT NULL,
            declaring_type TEXT NOT NULL,
            depth INTEGER NOT NULL,
            property_type TEXT NOT NULL,
            cpp_type TEXT NOT NULL,
            value TEXT NOT NULL,
            object_path TEXT NOT NULL,
            object_class TEXT NOT NULL,
            property_flags INTEGER NOT NULL,
            truncated INTEGER NOT NULL,
            PRIMARY KEY(node_id, declaring_type, property_path)
        );
        CREATE INDEX bp_node_props_node_idx ON blueprint_node_properties(node_id);
        CREATE INDEX bp_node_props_name_idx ON blueprint_node_properties(property_name);
        CREATE INDEX bp_node_props_path_idx ON blueprint_node_properties(property_path);
        CREATE INDEX bp_node_props_object_idx ON blueprint_node_properties(object_path);

        CREATE TABLE blueprint_node_references (
            node_id TEXT NOT NULL,
            blueprint_path TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            node_class TEXT NOT NULL,
            property_path TEXT NOT NULL,
            target_object_path TEXT NOT NULL,
            target_class TEXT NOT NULL,
            node_owned INTEGER NOT NULL,
            PRIMARY KEY(node_id, property_path, target_object_path)
        );
        CREATE INDEX bp_node_refs_target_idx ON blueprint_node_references(target_object_path);
        CREATE INDEX bp_node_refs_node_idx ON blueprint_node_references(node_id);

        CREATE TABLE blueprint_bindings (
            node_id TEXT NOT NULL,
            blueprint_path TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            node_class TEXT NOT NULL,
            binding_object TEXT NOT NULL,
            binding_key TEXT NOT NULL,
            target_property TEXT NOT NULL,
            access_path TEXT NOT NULL,
            property_path_json TEXT NOT NULL,
            compiled_context TEXT NOT NULL,
            pin_type TEXT NOT NULL,
            promoted_pin_type TEXT NOT NULL,
            raw_value TEXT NOT NULL,
            PRIMARY KEY(node_id, binding_key)
        );
        CREATE INDEX bp_bindings_node_idx ON blueprint_bindings(node_id);
        CREATE INDEX bp_bindings_access_idx ON blueprint_bindings(access_path);
        CREATE INDEX bp_bindings_target_idx ON blueprint_bindings(target_property);

        CREATE TABLE blueprint_defaults (
            blueprint_path TEXT NOT NULL,
            class_path TEXT NOT NULL,
            property_name TEXT NOT NULL,
            declaring_class TEXT NOT NULL,
            array_index INTEGER NOT NULL,
            property_type TEXT NOT NULL,
            cpp_type TEXT NOT NULL,
            value TEXT NOT NULL,
            parent_value TEXT NOT NULL,
            referenced_object_path TEXT NOT NULL,
            referenced_object_class TEXT NOT NULL,
            declared_here INTEGER NOT NULL,
            property_flags INTEGER NOT NULL,
            PRIMARY KEY(blueprint_path, property_name, array_index)
        );
        CREATE INDEX bp_defaults_name_idx ON blueprint_defaults(property_name);
        CREATE INDEX bp_defaults_object_idx ON blueprint_defaults(referenced_object_path);

        CREATE TABLE blueprint_component_properties (
            blueprint_path TEXT NOT NULL,
            component_name TEXT NOT NULL,
            component_class TEXT NOT NULL,
            template_path TEXT NOT NULL,
            property_name TEXT NOT NULL,
            declaring_class TEXT NOT NULL,
            array_index INTEGER NOT NULL,
            property_type TEXT NOT NULL,
            cpp_type TEXT NOT NULL,
            value TEXT NOT NULL,
            class_default_value TEXT NOT NULL,
            referenced_object_path TEXT NOT NULL,
            referenced_object_class TEXT NOT NULL,
            property_flags INTEGER NOT NULL,
            PRIMARY KEY(blueprint_path, component_name, property_name, array_index)
        );
        CREATE INDEX bp_component_props_name_idx ON blueprint_component_properties(property_name);
        CREATE INDEX bp_component_props_component_idx ON blueprint_component_properties(blueprint_path, component_name);

        CREATE TABLE blueprint_state_values (
            blueprint_path TEXT NOT NULL,
            owner_kind TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            owner_class TEXT NOT NULL,
            baseline_class TEXT NOT NULL,
            root_property TEXT NOT NULL,
            property_name TEXT NOT NULL,
            property_path TEXT NOT NULL,
            depth INTEGER NOT NULL,
            container_kind TEXT NOT NULL,
            property_type TEXT NOT NULL,
            cpp_type TEXT NOT NULL,
            value TEXT NOT NULL,
            baseline_value TEXT NOT NULL,
            baseline_present INTEGER NOT NULL,
            referenced_object_path TEXT NOT NULL,
            referenced_object_class TEXT NOT NULL,
            baseline_object_path TEXT NOT NULL,
            baseline_object_class TEXT NOT NULL,
            property_flags INTEGER NOT NULL,
            truncated INTEGER NOT NULL,
            PRIMARY KEY(blueprint_path, owner_kind, owner_id, property_path)
        );
        CREATE INDEX bp_state_values_owner_idx ON blueprint_state_values(blueprint_path, owner_kind, owner_name);
        CREATE INDEX bp_state_values_path_idx ON blueprint_state_values(property_path);
        CREATE INDEX bp_state_values_object_idx ON blueprint_state_values(referenced_object_path);

        CREATE TABLE blueprint_timelines (
            timeline_path TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            timeline_name TEXT NOT NULL,
            timeline_class TEXT NOT NULL,
            guid TEXT NOT NULL,
            length TEXT NOT NULL,
            length_mode TEXT NOT NULL,
            auto_play TEXT NOT NULL,
            loop TEXT NOT NULL,
            replicated TEXT NOT NULL,
            ignore_time_dilation TEXT NOT NULL,
            tick_group TEXT NOT NULL,
            update_function TEXT NOT NULL,
            finished_function TEXT NOT NULL,
            direction_property TEXT NOT NULL,
            variable_name TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_timelines_blueprint_idx ON blueprint_timelines(blueprint_path);

        CREATE TABLE blueprint_timeline_tracks (
            timeline_path TEXT NOT NULL,
            blueprint_path TEXT NOT NULL,
            track_index INTEGER NOT NULL,
            track_type TEXT NOT NULL,
            track_struct TEXT NOT NULL,
            track_name TEXT NOT NULL,
            property_name TEXT NOT NULL,
            function_name TEXT NOT NULL,
            external_curve TEXT NOT NULL,
            curve_path TEXT NOT NULL,
            curve_class TEXT NOT NULL,
            raw_value TEXT NOT NULL,
            PRIMARY KEY(timeline_path, track_type, track_index)
        );
        CREATE INDEX bp_timeline_tracks_blueprint_idx ON blueprint_timeline_tracks(blueprint_path, timeline_path);

        CREATE TABLE blueprint_timeline_keys (
            timeline_path TEXT NOT NULL,
            blueprint_path TEXT NOT NULL,
            timeline_name TEXT NOT NULL,
            track_index INTEGER NOT NULL,
            track_type TEXT NOT NULL,
            track_name TEXT NOT NULL,
            curve_path TEXT NOT NULL,
            curve_class TEXT NOT NULL,
            channel_index INTEGER NOT NULL,
            channel_name TEXT NOT NULL,
            key_index INTEGER NOT NULL,
            time REAL NOT NULL,
            value REAL NOT NULL,
            interp_mode INTEGER NOT NULL,
            tangent_mode INTEGER NOT NULL,
            tangent_weight_mode INTEGER NOT NULL,
            arrive_tangent REAL NOT NULL,
            leave_tangent REAL NOT NULL,
            arrive_tangent_weight REAL NOT NULL,
            leave_tangent_weight REAL NOT NULL,
            PRIMARY KEY(timeline_path, track_type, track_index, channel_index, key_index)
        );
        CREATE INDEX bp_timeline_keys_blueprint_idx ON blueprint_timeline_keys(blueprint_path, timeline_path);
        CREATE INDEX bp_timeline_keys_time_idx ON blueprint_timeline_keys(timeline_path, time);

        CREATE TABLE blueprint_widgets (
            widget_path TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            widget_tree TEXT NOT NULL,
            widget_name TEXT NOT NULL,
            widget_class TEXT NOT NULL,
            parent_widget_path TEXT NOT NULL,
            slot_path TEXT NOT NULL,
            slot_class TEXT NOT NULL,
            properties_json TEXT NOT NULL,
            slot_properties_json TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_widgets_blueprint_idx ON blueprint_widgets(blueprint_path, parent_widget_path);
        CREATE INDEX bp_widgets_class_idx ON blueprint_widgets(widget_class);

        CREATE TABLE blueprint_widget_properties (
            blueprint_path TEXT NOT NULL,
            owner_kind TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            owner_class TEXT NOT NULL,
            baseline_class TEXT NOT NULL,
            root_property TEXT NOT NULL,
            property_name TEXT NOT NULL,
            property_path TEXT NOT NULL,
            depth INTEGER NOT NULL,
            container_kind TEXT NOT NULL,
            property_type TEXT NOT NULL,
            cpp_type TEXT NOT NULL,
            value TEXT NOT NULL,
            baseline_value TEXT NOT NULL,
            baseline_present INTEGER NOT NULL,
            referenced_object_path TEXT NOT NULL,
            referenced_object_class TEXT NOT NULL,
            baseline_object_path TEXT NOT NULL,
            baseline_object_class TEXT NOT NULL,
            property_flags INTEGER NOT NULL,
            truncated INTEGER NOT NULL,
            PRIMARY KEY(blueprint_path, owner_kind, owner_id, property_path)
        );
        CREATE INDEX bp_widget_props_owner_idx ON blueprint_widget_properties(blueprint_path, owner_kind, owner_name);
        CREATE INDEX bp_widget_props_path_idx ON blueprint_widget_properties(property_path);
        CREATE INDEX bp_widget_props_object_idx ON blueprint_widget_properties(referenced_object_path);

        CREATE TABLE blueprint_widget_bindings (
            blueprint_path TEXT NOT NULL,
            binding_index INTEGER NOT NULL,
            binding_struct TEXT NOT NULL,
            object_name TEXT NOT NULL,
            property_name TEXT NOT NULL,
            function_name TEXT NOT NULL,
            source_property TEXT NOT NULL,
            source_path TEXT NOT NULL,
            kind TEXT NOT NULL,
            member_guid TEXT NOT NULL,
            raw_value TEXT NOT NULL,
            PRIMARY KEY(blueprint_path, binding_index)
        );
        CREATE INDEX bp_widget_bindings_target_idx ON blueprint_widget_bindings(object_name, property_name);

        CREATE TABLE blueprint_widget_animations (
            animation_path TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            animation_name TEXT NOT NULL,
            animation_class TEXT NOT NULL,
            display_label TEXT NOT NULL,
            movie_scene TEXT NOT NULL,
            animation_bindings TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_widget_animations_blueprint_idx ON blueprint_widget_animations(blueprint_path);

        CREATE TABLE blueprint_widget_animation_bindings (
            animation_path TEXT NOT NULL,
            blueprint_path TEXT NOT NULL,
            animation_name TEXT NOT NULL,
            binding_index INTEGER NOT NULL,
            binding_struct TEXT NOT NULL,
            widget_name TEXT NOT NULL,
            slot_widget_name TEXT NOT NULL,
            animation_guid TEXT NOT NULL,
            is_root_widget TEXT NOT NULL,
            dynamic_binding TEXT NOT NULL,
            PRIMARY KEY(animation_path, binding_index)
        );
        CREATE INDEX bp_widget_anim_bindings_blueprint_idx ON blueprint_widget_animation_bindings(blueprint_path, widget_name);

        CREATE TABLE behavior_trees (
            behavior_tree_path TEXT PRIMARY KEY,
            class_path TEXT NOT NULL,
            root_node_id TEXT NOT NULL,
            blackboard_path TEXT NOT NULL,
            root_decorator_count INTEGER NOT NULL,
            root_decorator_logic TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX behavior_trees_blackboard_idx ON behavior_trees(blackboard_path);

        CREATE TABLE behavior_tree_nodes (
            node_id TEXT PRIMARY KEY,
            behavior_tree_path TEXT NOT NULL,
            node_kind TEXT NOT NULL,
            class_path TEXT NOT NULL,
            class_name TEXT NOT NULL,
            name TEXT NOT NULL,
            display_name TEXT NOT NULL,
            parent_node_id TEXT NOT NULL,
            child_index INTEGER NOT NULL,
            attached_to TEXT NOT NULL,
            attachment_kind TEXT NOT NULL,
            attachment_index INTEGER NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX behavior_tree_nodes_tree_idx ON behavior_tree_nodes(behavior_tree_path, node_kind);
        CREATE INDEX behavior_tree_nodes_class_idx ON behavior_tree_nodes(class_path);

        CREATE TABLE behavior_tree_edges (
            behavior_tree_path TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            edge_kind TEXT NOT NULL,
            child_index INTEGER NOT NULL,
            decorator_logic TEXT NOT NULL,
            decorator_ids_json TEXT NOT NULL,
            PRIMARY KEY(behavior_tree_path, source_node_id, target_node_id, edge_kind, child_index)
        );
        CREATE INDEX behavior_tree_edges_source_idx ON behavior_tree_edges(source_node_id);

        CREATE TABLE blackboards (
            blackboard_path TEXT PRIMARY KEY,
            class_path TEXT NOT NULL,
            parent_blackboard_path TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE TABLE blackboard_keys (
            key_id TEXT PRIMARY KEY,
            blackboard_path TEXT NOT NULL,
            key_index INTEGER NOT NULL,
            name TEXT NOT NULL,
            key_type_path TEXT NOT NULL,
            key_type_class TEXT NOT NULL,
            instance_synced TEXT NOT NULL,
            raw_value TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX blackboard_keys_bb_idx ON blackboard_keys(blackboard_path, name);

        CREATE TABLE eqs_queries (
            eqs_path TEXT PRIMARY KEY,
            class_path TEXT NOT NULL,
            option_count INTEGER NOT NULL,
            json TEXT NOT NULL
        );
        CREATE TABLE eqs_options (
            option_id TEXT PRIMARY KEY,
            eqs_path TEXT NOT NULL,
            option_index INTEGER NOT NULL,
            class_path TEXT NOT NULL,
            generator_id TEXT NOT NULL,
            test_count INTEGER NOT NULL,
            json TEXT NOT NULL
        );
        CREATE TABLE eqs_generators (
            generator_id TEXT PRIMARY KEY,
            eqs_path TEXT NOT NULL,
            option_id TEXT NOT NULL,
            option_index INTEGER NOT NULL,
            class_path TEXT NOT NULL,
            class_name TEXT NOT NULL,
            item_type TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE TABLE eqs_tests (
            test_id TEXT PRIMARY KEY,
            eqs_path TEXT NOT NULL,
            option_id TEXT NOT NULL,
            option_index INTEGER NOT NULL,
            test_index INTEGER NOT NULL,
            class_path TEXT NOT NULL,
            class_name TEXT NOT NULL,
            test_purpose TEXT NOT NULL,
            filter_type TEXT NOT NULL,
            scoring_equation TEXT NOT NULL,
            weight_modifier TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX eqs_tests_query_idx ON eqs_tests(eqs_path, option_index, test_index);

        CREATE TABLE statetrees (
            statetree_path TEXT PRIMARY KEY,
            class_path TEXT NOT NULL,
            editor_data_path TEXT NOT NULL,
            editor_data_class TEXT NOT NULL,
            last_compiled_editor_data_hash TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE TABLE statetree_states (
            state_id TEXT PRIMARY KEY,
            statetree_path TEXT NOT NULL,
            state_object_path TEXT NOT NULL,
            parent_state_id TEXT NOT NULL,
            child_index INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            state_type TEXT NOT NULL,
            selection_behavior TEXT NOT NULL,
            enabled TEXT NOT NULL,
            tag TEXT NOT NULL,
            tasks_completion TEXT NOT NULL,
            required_event TEXT NOT NULL,
            linked_asset TEXT NOT NULL,
            linked_subtree TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX statetree_states_tree_idx ON statetree_states(statetree_path, parent_state_id, child_index);
        CREATE TABLE statetree_nodes (
            node_id TEXT PRIMARY KEY,
            statetree_path TEXT NOT NULL,
            state_id TEXT NOT NULL,
            role TEXT NOT NULL,
            node_index INTEGER NOT NULL,
            guid TEXT NOT NULL,
            expression_indent TEXT NOT NULL,
            expression_operand TEXT NOT NULL,
            instance_object_path TEXT NOT NULL,
            instance_object_class TEXT NOT NULL,
            raw_node TEXT NOT NULL,
            raw_instance TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX statetree_nodes_tree_idx ON statetree_nodes(statetree_path, state_id, role);
        CREATE TABLE statetree_transitions (
            transition_id TEXT PRIMARY KEY,
            statetree_path TEXT NOT NULL,
            source_state_id TEXT NOT NULL,
            transition_index INTEGER NOT NULL,
            trigger TEXT NOT NULL,
            event_tag TEXT NOT NULL,
            state TEXT NOT NULL,
            priority TEXT NOT NULL,
            fallback TEXT NOT NULL,
            enabled TEXT NOT NULL,
            delay_enabled TEXT NOT NULL,
            delay TEXT NOT NULL,
            raw_value TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX statetree_transitions_tree_idx ON statetree_transitions(statetree_path, source_state_id);
        CREATE TABLE statetree_bindings (
            statetree_path TEXT NOT NULL,
            binding_index INTEGER NOT NULL,
            binding_struct TEXT NOT NULL,
            source_path TEXT NOT NULL,
            target_path TEXT NOT NULL,
            output_binding TEXT NOT NULL,
            raw_value TEXT NOT NULL,
            PRIMARY KEY(statetree_path, binding_index)
        );

        CREATE TABLE ai_properties (
            asset_path TEXT NOT NULL,
            system TEXT NOT NULL,
            owner_kind TEXT NOT NULL,
            owner_id TEXT NOT NULL,
            owner_class TEXT NOT NULL,
            declaring_type TEXT NOT NULL,
            property_name TEXT NOT NULL,
            property_type TEXT NOT NULL,
            cpp_type TEXT NOT NULL,
            value TEXT NOT NULL,
            object_path TEXT NOT NULL,
            object_class TEXT NOT NULL,
            property_flags INTEGER NOT NULL,
            truncated INTEGER NOT NULL,
            PRIMARY KEY(asset_path, owner_id, declaring_type, property_name)
        );
        CREATE INDEX ai_properties_asset_idx ON ai_properties(asset_path, owner_kind);
        CREATE INDEX ai_properties_object_idx ON ai_properties(object_path);

        CREATE TABLE ai_relations (
            relation_id TEXT PRIMARY KEY,
            asset_path TEXT NOT NULL,
            system TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            target TEXT NOT NULL,
            detail_json TEXT NOT NULL
        );
        CREATE INDEX ai_relations_source_idx ON ai_relations(source_id, relation);
        CREATE INDEX ai_relations_target_idx ON ai_relations(target, relation);
        CREATE TABLE ai_summaries (
            asset_path TEXT PRIMARY KEY,
            system TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            node_count INTEGER NOT NULL,
            relation_count INTEGER NOT NULL,
            text TEXT NOT NULL,
            json TEXT NOT NULL
        );

        CREATE TABLE pcg_graphs (
            pcg_path TEXT PRIMARY KEY, class_path TEXT NOT NULL, parent_graph_path TEXT NOT NULL, embedded INTEGER NOT NULL,
            embedded_subgraphs_json TEXT NOT NULL, node_count INTEGER NOT NULL, pin_count INTEGER NOT NULL, edge_count INTEGER NOT NULL,
            user_parameters TEXT NOT NULL, default_grid TEXT NOT NULL, json TEXT NOT NULL
        );
        CREATE TABLE pcg_nodes (
            node_id TEXT PRIMARY KEY, pcg_path TEXT NOT NULL, node_class TEXT NOT NULL, node_name TEXT NOT NULL,
            node_title TEXT NOT NULL, position_x TEXT NOT NULL, position_y TEXT NOT NULL, settings_path TEXT NOT NULL,
            settings_class TEXT NOT NULL, settings_name TEXT NOT NULL, enabled TEXT NOT NULL, json TEXT NOT NULL
        );
        CREATE INDEX pcg_nodes_graph_idx ON pcg_nodes(pcg_path, settings_class);
        CREATE TABLE pcg_pins (
            pin_id TEXT PRIMARY KEY, pcg_path TEXT NOT NULL, node_id TEXT NOT NULL, direction TEXT NOT NULL,
            pin_index INTEGER NOT NULL, label TEXT NOT NULL, allowed_types TEXT NOT NULL, pin_status TEXT NOT NULL,
            allow_multiple_data TEXT NOT NULL, invisible TEXT NOT NULL, raw_properties TEXT NOT NULL, json TEXT NOT NULL
        );
        CREATE INDEX pcg_pins_node_idx ON pcg_pins(node_id, direction, pin_index);
        CREATE TABLE pcg_edges (
            edge_id TEXT PRIMARY KEY, pcg_path TEXT NOT NULL, source_pin_id TEXT NOT NULL, target_pin_id TEXT NOT NULL,
            source_node_id TEXT NOT NULL, target_node_id TEXT NOT NULL, json TEXT NOT NULL
        );
        CREATE INDEX pcg_edges_source_idx ON pcg_edges(pcg_path, source_node_id);
        CREATE TABLE pcg_properties (
            asset_path TEXT NOT NULL, system TEXT NOT NULL, owner_kind TEXT NOT NULL, owner_id TEXT NOT NULL,
            owner_class TEXT NOT NULL, declaring_type TEXT NOT NULL, property_name TEXT NOT NULL, property_type TEXT NOT NULL,
            cpp_type TEXT NOT NULL, value TEXT NOT NULL, object_path TEXT NOT NULL, object_class TEXT NOT NULL,
            property_flags INTEGER NOT NULL, truncated INTEGER NOT NULL,
            PRIMARY KEY(asset_path, owner_id, declaring_type, property_name)
        );
        CREATE INDEX pcg_properties_object_idx ON pcg_properties(object_path);
        CREATE TABLE pcg_parameters (
            parameter_id TEXT PRIMARY KEY, pcg_path TEXT NOT NULL, owner_kind TEXT NOT NULL, owner_id TEXT NOT NULL,
            property_name TEXT NOT NULL, value TEXT NOT NULL, object_path TEXT NOT NULL, json TEXT NOT NULL
        );

        CREATE TABLE materials (
            material_path TEXT PRIMARY KEY, material_kind TEXT NOT NULL, class_path TEXT NOT NULL, expression_count INTEGER NOT NULL,
            parent_path TEXT NOT NULL, material_domain TEXT NOT NULL, blend_mode TEXT NOT NULL, shading_model TEXT NOT NULL, json TEXT NOT NULL
        );
        CREATE INDEX materials_parent_idx ON materials(parent_path);
        CREATE TABLE material_expressions (
            expression_id TEXT PRIMARY KEY, material_path TEXT NOT NULL, expression_class TEXT NOT NULL, expression_name TEXT NOT NULL,
            editor_x TEXT NOT NULL, editor_y TEXT NOT NULL, description TEXT NOT NULL, parameter_name TEXT NOT NULL,
            function_path TEXT NOT NULL, texture_path TEXT NOT NULL, default_value TEXT NOT NULL, value TEXT NOT NULL, json TEXT NOT NULL
        );
        CREATE INDEX material_expr_asset_idx ON material_expressions(material_path, expression_class);
        CREATE INDEX material_expr_parameter_idx ON material_expressions(parameter_name);
        CREATE TABLE material_edges (
            material_path TEXT NOT NULL, source_expression_id TEXT NOT NULL, source_output_index TEXT NOT NULL, source_output_name TEXT NOT NULL,
            target_expression_id TEXT NOT NULL, target_input_name TEXT NOT NULL, target_input_index INTEGER NOT NULL, edge_kind TEXT NOT NULL,
            PRIMARY KEY(material_path, source_expression_id, target_expression_id, target_input_name, target_input_index)
        );
        CREATE INDEX material_edges_target_idx ON material_edges(material_path, target_expression_id);
        CREATE TABLE material_properties (
            asset_path TEXT NOT NULL, system TEXT NOT NULL, owner_kind TEXT NOT NULL, owner_id TEXT NOT NULL,
            owner_class TEXT NOT NULL, declaring_type TEXT NOT NULL, property_name TEXT NOT NULL, property_type TEXT NOT NULL,
            cpp_type TEXT NOT NULL, value TEXT NOT NULL, object_path TEXT NOT NULL, object_class TEXT NOT NULL,
            property_flags INTEGER NOT NULL, truncated INTEGER NOT NULL,
            PRIMARY KEY(asset_path, owner_id, declaring_type, property_name)
        );
        CREATE INDEX material_properties_object_idx ON material_properties(object_path);
        CREATE TABLE material_parameters (
            parameter_id TEXT PRIMARY KEY, material_path TEXT NOT NULL, expression_id TEXT NOT NULL, parameter_name TEXT NOT NULL,
            parameter_kind TEXT NOT NULL, default_value TEXT NOT NULL, value TEXT NOT NULL, object_path TEXT NOT NULL, json TEXT NOT NULL
        );
        CREATE INDEX material_parameters_asset_idx ON material_parameters(material_path, parameter_name);

        CREATE TABLE visual_relations (
            relation_id TEXT PRIMARY KEY, system TEXT NOT NULL, asset_path TEXT NOT NULL, source_kind TEXT NOT NULL, source_id TEXT NOT NULL,
            relation TEXT NOT NULL, target_kind TEXT NOT NULL, target TEXT NOT NULL, detail_json TEXT NOT NULL
        );
        CREATE INDEX visual_relations_source_idx ON visual_relations(source_id, relation);
        CREATE INDEX visual_relations_target_idx ON visual_relations(target, relation);
        CREATE TABLE pcg_graph_context (pcg_path TEXT PRIMARY KEY, text TEXT NOT NULL, json TEXT NOT NULL);
        CREATE TABLE material_graph_context (material_path TEXT PRIMARY KEY, text TEXT NOT NULL, json TEXT NOT NULL);
        CREATE TABLE visual_summaries (
            asset_path TEXT PRIMARY KEY, system TEXT NOT NULL, asset_class TEXT NOT NULL, node_count INTEGER NOT NULL,
            relation_count INTEGER NOT NULL, text TEXT NOT NULL, json TEXT NOT NULL
        );

        CREATE TABLE blueprint_functions (
            function_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            graph_path TEXT NOT NULL,
            name TEXT NOT NULL,
            owner TEXT NOT NULL,
            resolved_function TEXT NOT NULL,
            function_flags INTEGER NOT NULL,
            has_exec INTEGER NOT NULL,
            pure_shape INTEGER NOT NULL,
            blueprint_pure INTEGER NOT NULL,
            const_function INTEGER NOT NULL,
            blueprint_callable INTEGER NOT NULL,
            static_function INTEGER NOT NULL,
            event_function INTEGER NOT NULL,
            result_node_count INTEGER NOT NULL,
            inputs_json TEXT NOT NULL,
            outputs_json TEXT NOT NULL,
            locals_json TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_functions_blueprint_idx ON blueprint_functions(blueprint_path, name);
        CREATE INDEX bp_functions_resolved_idx ON blueprint_functions(resolved_function);

        CREATE TABLE blueprint_call_edges (
            call_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            caller_function_id TEXT NOT NULL,
            call_node_id TEXT NOT NULL,
            target_function TEXT NOT NULL,
            target_name TEXT NOT NULL,
            target_owner TEXT NOT NULL,
            target_blueprint_path TEXT NOT NULL,
            target_function_id TEXT NOT NULL,
            resolution TEXT NOT NULL,
            candidate_count INTEGER NOT NULL,
            candidate_function_ids_json TEXT NOT NULL,
            pure INTEGER NOT NULL,
            const_function INTEGER NOT NULL,
            latent INTEGER NOT NULL,
            interface_call INTEGER NOT NULL,
            function_flags INTEGER NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_call_edges_caller_idx ON blueprint_call_edges(blueprint_path, caller_function_id);
        CREATE INDEX bp_call_edges_target_idx ON blueprint_call_edges(target_blueprint_path, target_function_id);
        CREATE INDEX bp_call_edges_resolution_idx ON blueprint_call_edges(resolution, target_name);

        CREATE TABLE blueprint_call_bindings (
            binding_id TEXT PRIMARY KEY,
            call_id TEXT NOT NULL,
            call_node_id TEXT NOT NULL,
            caller_blueprint_path TEXT NOT NULL,
            caller_graph_id TEXT NOT NULL,
            caller_function_id TEXT NOT NULL,
            target_blueprint_path TEXT NOT NULL,
            target_function_id TEXT NOT NULL,
            direction TEXT NOT NULL,
            call_pin_id TEXT NOT NULL,
            call_pin_name TEXT NOT NULL,
            parameter_name TEXT NOT NULL,
            parameter_pin_ids_json TEXT NOT NULL,
            match_kind TEXT NOT NULL,
            split_suffix TEXT NOT NULL,
            call_pin_type_json TEXT NOT NULL,
            parameter_type_json TEXT NOT NULL,
            dependency_ids_json TEXT NOT NULL,
            consumer_pin_ids_json TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_call_bindings_call_idx ON blueprint_call_bindings(call_id, direction);
        CREATE INDEX bp_call_bindings_target_idx ON blueprint_call_bindings(target_function_id, parameter_name);
        CREATE INDEX bp_call_bindings_pin_idx ON blueprint_call_bindings(call_pin_id);

        CREATE TABLE blueprint_data_dependencies (
            dependency_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            sink_node_id TEXT NOT NULL,
            sink_operation TEXT NOT NULL,
            sink_label TEXT NOT NULL,
            sink_pin_id TEXT NOT NULL,
            sink_pin_name TEXT NOT NULL,
            source_count INTEGER NOT NULL,
            expression_node_count INTEGER NOT NULL,
            truncated INTEGER NOT NULL,
            cycle INTEGER NOT NULL,
            variable_reads_json TEXT NOT NULL,
            function_calls_json TEXT NOT NULL,
            object_refs_json TEXT NOT NULL,
            expression_json TEXT NOT NULL,
            text TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_data_deps_sink_idx ON blueprint_data_dependencies(blueprint_path, sink_node_id, sink_pin_name);
        CREATE INDEX bp_data_deps_graph_idx ON blueprint_data_dependencies(graph_id, sink_operation);

        CREATE TABLE blueprint_execution_blocks (
            block_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            block_index INTEGER NOT NULL,
            entry_node_id TEXT NOT NULL,
            exit_node_id TEXT NOT NULL,
            node_count INTEGER NOT NULL,
            node_ids_json TEXT NOT NULL,
            operations_json TEXT NOT NULL,
            labels_json TEXT NOT NULL,
            text TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_exec_blocks_graph_idx ON blueprint_execution_blocks(graph_id, block_index);

        CREATE TABLE blueprint_execution_block_edges (
            edge_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            source_block_id TEXT NOT NULL,
            target_block_id TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            source_pin_name TEXT NOT NULL,
            target_pin_name TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_exec_block_edges_source_idx ON blueprint_execution_block_edges(source_block_id);
        CREATE INDEX bp_exec_block_edges_target_idx ON blueprint_execution_block_edges(target_block_id);

        CREATE TABLE blueprint_execution_roots (
            root_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            root_node_id TEXT NOT NULL,
            root_kind TEXT NOT NULL,
            root_name TEXT NOT NULL,
            block_id TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_exec_roots_graph_idx ON blueprint_execution_roots(graph_id, root_kind);

        CREATE TABLE anim_state_machines (
            machine_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            host_graph_id TEXT NOT NULL,
            host_graph_name TEXT NOT NULL,
            name TEXT NOT NULL,
            editor_graph_path TEXT NOT NULL,
            machine_graph_id TEXT NOT NULL,
            entry_node_id TEXT NOT NULL,
            entry_state TEXT NOT NULL,
            entry_state_id TEXT NOT NULL,
            state_count INTEGER NOT NULL,
            transition_count INTEGER NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX anim_state_machines_bp_idx ON anim_state_machines(blueprint_path, name);

        CREATE TABLE anim_states (
            state_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            machine_graph_id TEXT NOT NULL,
            machine_name TEXT NOT NULL,
            state_kind TEXT NOT NULL,
            name TEXT NOT NULL,
            bound_graph TEXT NOT NULL,
            always_reset_on_entry INTEGER NOT NULL,
            state_type INTEGER NOT NULL,
            global_alias INTEGER NOT NULL,
            aliased_states_json TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX anim_states_machine_idx ON anim_states(machine_graph_id, state_kind, name);

        CREATE TABLE anim_transitions (
            transition_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            machine_graph_id TEXT NOT NULL,
            machine_name TEXT NOT NULL,
            previous_state TEXT NOT NULL,
            previous_state_id TEXT NOT NULL,
            next_state TEXT NOT NULL,
            next_state_id TEXT NOT NULL,
            bidirectional INTEGER NOT NULL,
            disabled INTEGER NOT NULL,
            automatic_rule INTEGER NOT NULL,
            automatic_rule_trigger_time REAL NOT NULL,
            crossfade_duration REAL NOT NULL,
            priority_order INTEGER NOT NULL,
            logic_type INTEGER NOT NULL,
            min_time_before_reentry REAL NOT NULL,
            only_evaluate_when_active INTEGER NOT NULL,
            shared_rules INTEGER NOT NULL,
            shared_rules_name TEXT NOT NULL,
            shared_crossfade INTEGER NOT NULL,
            shared_crossfade_name TEXT NOT NULL,
            rule_graph TEXT NOT NULL,
            custom_transition_graph TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX anim_transitions_machine_idx ON anim_transitions(machine_graph_id, previous_state, next_state);

        CREATE TABLE blueprint_events (
            event_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            node_class TEXT NOT NULL,
            operation TEXT NOT NULL,
            event_kind TEXT NOT NULL,
            name TEXT NOT NULL,
            owner TEXT NOT NULL,
            component_name TEXT NOT NULL,
            delegate_name TEXT NOT NULL,
            delegate_owner TEXT NOT NULL,
            input_name TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_events_blueprint_idx ON blueprint_events(blueprint_path, event_kind);
        CREATE INDEX bp_events_component_idx ON blueprint_events(component_name, delegate_name);
        CREATE INDEX bp_events_input_idx ON blueprint_events(input_name);

        CREATE TABLE rigvm_editor_links (
            node_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            model_node_path TEXT NOT NULL,
            status TEXT NOT NULL,
            confidence TEXT NOT NULL,
            score INTEGER NOT NULL,
            candidate_count INTEGER NOT NULL,
            rigvm_object_id TEXT NOT NULL,
            rigvm_operation TEXT NOT NULL,
            rigvm_class TEXT NOT NULL,
            resolved_function_name TEXT NOT NULL,
            template_notation TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX rigvm_editor_links_target_idx ON rigvm_editor_links(rigvm_object_id);
        CREATE INDEX rigvm_editor_links_status_idx ON rigvm_editor_links(status, confidence);

        CREATE TABLE blueprint_relations (
            relation_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            target TEXT NOT NULL,
            owner TEXT NOT NULL,
            detail_json TEXT NOT NULL
        );
        CREATE INDEX bp_relations_source_idx ON blueprint_relations(source_id, relation);
        CREATE INDEX bp_relations_target_idx ON blueprint_relations(target, relation);
        CREATE INDEX bp_relations_blueprint_idx ON blueprint_relations(blueprint_path, relation);

        CREATE TABLE blueprint_graph_context (
            graph_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            graph_path TEXT NOT NULL,
            graph_kind TEXT NOT NULL,
            graph_system TEXT NOT NULL,
            node_count INTEGER NOT NULL,
            execution_edge_count INTEGER NOT NULL,
            data_edge_count INTEGER NOT NULL,
            truncated INTEGER NOT NULL,
            text TEXT NOT NULL
        );
        CREATE INDEX bp_graph_context_blueprint_idx ON blueprint_graph_context(blueprint_path, graph_name);

        CREATE TABLE blueprint_summaries (
            blueprint_path TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_class TEXT NOT NULL,
            generated_class TEXT NOT NULL,
            variable_count INTEGER NOT NULL,
            component_count INTEGER NOT NULL,
            interface_count INTEGER NOT NULL,
            function_count INTEGER NOT NULL,
            event_count INTEGER NOT NULL,
            default_count INTEGER NOT NULL,
            component_override_count INTEGER NOT NULL,
            state_value_count INTEGER NOT NULL,
            timeline_count INTEGER NOT NULL,
            timeline_track_count INTEGER NOT NULL,
            timeline_key_count INTEGER NOT NULL,
            widget_count INTEGER NOT NULL,
            widget_property_count INTEGER NOT NULL,
            widget_binding_count INTEGER NOT NULL,
            widget_animation_count INTEGER NOT NULL,
            widget_animation_binding_count INTEGER NOT NULL,
            graph_count INTEGER NOT NULL,
            graph_system_counts_json TEXT NOT NULL,
            operation_counts_json TEXT NOT NULL,
            relation_counts_json TEXT NOT NULL,
            text TEXT NOT NULL
        );

        CREATE TABLE rigvm_objects (
            object_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            kind TEXT NOT NULL,
            class_path TEXT NOT NULL,
            name TEXT NOT NULL,
            outer_object_id TEXT NOT NULL,
            outer_class TEXT NOT NULL,
            operation TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX rigvm_objects_blueprint_idx ON rigvm_objects(blueprint_path, kind);
        CREATE INDEX rigvm_objects_class_idx ON rigvm_objects(class_path);
        CREATE INDEX rigvm_objects_operation_idx ON rigvm_objects(operation);

        CREATE TABLE rigvm_properties (
            object_id TEXT NOT NULL,
            blueprint_path TEXT NOT NULL,
            kind TEXT NOT NULL,
            class_path TEXT NOT NULL,
            declaring_type TEXT NOT NULL,
            property_name TEXT NOT NULL,
            property_path TEXT NOT NULL,
            property_type TEXT NOT NULL,
            cpp_type TEXT NOT NULL,
            value TEXT NOT NULL,
            object_path TEXT NOT NULL,
            object_class TEXT NOT NULL,
            property_flags INTEGER NOT NULL,
            truncated INTEGER NOT NULL,
            PRIMARY KEY(object_id, declaring_type, property_path)
        );
        CREATE INDEX rigvm_props_object_idx ON rigvm_properties(object_id);
        CREATE INDEX rigvm_props_name_idx ON rigvm_properties(property_name);
        CREATE INDEX rigvm_props_value_idx ON rigvm_properties(value);

        CREATE TABLE rigvm_references (
            source_object_id TEXT NOT NULL,
            blueprint_path TEXT NOT NULL,
            source_kind TEXT NOT NULL,
            source_class TEXT NOT NULL,
            property_path TEXT NOT NULL,
            target_object_id TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            target_class TEXT NOT NULL,
            PRIMARY KEY(source_object_id, property_path, target_object_id)
        );
        CREATE INDEX rigvm_refs_source_idx ON rigvm_references(source_object_id);
        CREATE INDEX rigvm_refs_target_idx ON rigvm_references(target_object_id);
        CREATE INDEX rigvm_refs_blueprint_idx ON rigvm_references(blueprint_path);

        CREATE TABLE rigvm_pins (
            pin_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            class_path TEXT NOT NULL,
            name TEXT NOT NULL,
            outer_object_id TEXT NOT NULL,
            display_name TEXT NOT NULL,
            direction TEXT NOT NULL,
            cpp_type TEXT NOT NULL,
            cpp_type_object_path TEXT NOT NULL,
            default_value TEXT NOT NULL,
            default_value_type TEXT NOT NULL,
            default_value_object TEXT NOT NULL,
            custom_widget_name TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX rigvm_pins_blueprint_idx ON rigvm_pins(blueprint_path, outer_object_id);
        CREATE INDEX rigvm_pins_type_idx ON rigvm_pins(cpp_type, direction);

        CREATE TABLE rigvm_links (
            link_id TEXT PRIMARY KEY,
            blueprint_path TEXT NOT NULL,
            class_path TEXT NOT NULL,
            source_pin_path TEXT NOT NULL,
            target_pin_path TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX rigvm_links_blueprint_idx ON rigvm_links(blueprint_path);
        CREATE INDEX rigvm_links_source_idx ON rigvm_links(source_pin_path);
        CREATE INDEX rigvm_links_target_idx ON rigvm_links(target_pin_path);

        CREATE TABLE blueprint_edges (
            blueprint_path TEXT NOT NULL,
            graph_id TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            source_node_id TEXT NOT NULL,
            source_pin_id TEXT NOT NULL,
            source_pin_name TEXT NOT NULL,
            target_node_id TEXT NOT NULL,
            target_pin_id TEXT NOT NULL,
            target_pin_name TEXT NOT NULL,
            pin_category TEXT NOT NULL,
            edge_kind TEXT NOT NULL,
            PRIMARY KEY(source_pin_id, target_pin_id)
        );
        CREATE INDEX bp_edges_source_node_idx ON blueprint_edges(source_node_id);
        CREATE INDEX bp_edges_target_node_idx ON blueprint_edges(target_node_id);
        CREATE INDEX bp_edges_kind_idx ON blueprint_edges(edge_kind, pin_category);

        CREATE TABLE worlds (
            world_path TEXT PRIMARY KEY,
            world_name TEXT NOT NULL,
            package_name TEXT NOT NULL,
            package_path TEXT NOT NULL,
            persistent_level_path TEXT NOT NULL,
            world_partitioned INTEGER NOT NULL,
            world_partition_path TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX worlds_package_idx ON worlds(package_name);
        CREATE INDEX worlds_partitioned_idx ON worlds(world_partitioned);

        CREATE TABLE world_levels (
            world_path TEXT NOT NULL,
            level_path TEXT NOT NULL,
            level_name TEXT NOT NULL,
            level_package TEXT NOT NULL,
            level_kind TEXT NOT NULL,
            streaming_owner_path TEXT NOT NULL,
            streaming_class TEXT NOT NULL,
            target_world_package TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX world_levels_world_idx ON world_levels(world_path, level_kind);
        CREATE INDEX world_levels_target_idx ON world_levels(target_world_package);

        CREATE TABLE world_actors (
            actor_path TEXT PRIMARY KEY,
            world_path TEXT NOT NULL,
            level_path TEXT NOT NULL,
            actor_guid TEXT NOT NULL,
            actor_instance_guid TEXT NOT NULL,
            actor_name TEXT NOT NULL,
            actor_label TEXT NOT NULL,
            actor_class TEXT NOT NULL,
            archetype_path TEXT NOT NULL,
            generated_class TEXT NOT NULL,
            blueprint_asset TEXT NOT NULL,
            folder TEXT NOT NULL,
            folder_guid TEXT NOT NULL,
            attach_parent_actor_path TEXT NOT NULL,
            attach_parent_socket TEXT NOT NULL,
            owner_actor_path TEXT NOT NULL,
            child_actor_parent_path TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            transform_json TEXT NOT NULL,
            spatially_loaded INTEGER NOT NULL,
            runtime_grid TEXT NOT NULL,
            data_layer_instance_names_json TEXT NOT NULL,
            data_layer_assets_json TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX world_actors_world_idx ON world_actors(world_path, level_path);
        CREATE INDEX world_actors_guid_idx ON world_actors(world_path, actor_guid);
        CREATE INDEX world_actors_class_idx ON world_actors(actor_class);
        CREATE INDEX world_actors_blueprint_idx ON world_actors(blueprint_asset);
        CREATE INDEX world_actors_parent_idx ON world_actors(attach_parent_actor_path);

        CREATE TABLE world_components (
            component_path TEXT PRIMARY KEY,
            world_path TEXT NOT NULL,
            actor_path TEXT NOT NULL,
            component_name TEXT NOT NULL,
            component_class TEXT NOT NULL,
            archetype_path TEXT NOT NULL,
            creation_method INTEGER NOT NULL,
            tags_json TEXT NOT NULL,
            is_scene_component INTEGER NOT NULL,
            attach_parent_component_path TEXT NOT NULL,
            attach_socket TEXT NOT NULL,
            relative_transform_json TEXT NOT NULL,
            world_transform_json TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX world_components_actor_idx ON world_components(actor_path);
        CREATE INDEX world_components_class_idx ON world_components(component_class);
        CREATE INDEX world_components_parent_idx ON world_components(attach_parent_component_path);

        CREATE TABLE world_instance_properties (
            world_path TEXT NOT NULL,
            actor_path TEXT NOT NULL,
            owner_kind TEXT NOT NULL,
            owner_path TEXT NOT NULL,
            owner_class TEXT NOT NULL,
            baseline_path TEXT NOT NULL,
            baseline_class TEXT NOT NULL,
            property_name TEXT NOT NULL,
            property_path TEXT NOT NULL,
            property_type TEXT NOT NULL,
            cpp_type TEXT NOT NULL,
            property_flags TEXT NOT NULL,
            value TEXT NOT NULL,
            baseline_value TEXT NOT NULL,
            value_truncated INTEGER NOT NULL,
            baseline_value_truncated INTEGER NOT NULL,
            json TEXT NOT NULL,
            PRIMARY KEY(owner_path, property_path)
        );
        CREATE INDEX world_props_actor_idx ON world_instance_properties(actor_path);
        CREATE INDEX world_props_name_idx ON world_instance_properties(property_name);
        CREATE INDEX world_props_owner_class_idx ON world_instance_properties(owner_class);

        CREATE TABLE world_references (
            world_path TEXT NOT NULL,
            actor_path TEXT NOT NULL,
            owner_kind TEXT NOT NULL,
            owner_path TEXT NOT NULL,
            root_property TEXT NOT NULL,
            property_path TEXT NOT NULL,
            reference_kind TEXT NOT NULL,
            target_path TEXT NOT NULL,
            target_class TEXT NOT NULL,
            target_kind TEXT NOT NULL,
            authored_override INTEGER NOT NULL,
            json TEXT NOT NULL,
            PRIMARY KEY(owner_path, property_path, reference_kind, target_path)
        );
        CREATE INDEX world_refs_actor_idx ON world_references(actor_path);
        CREATE INDEX world_refs_target_idx ON world_references(target_path);
        CREATE INDEX world_refs_kind_idx ON world_references(target_kind, reference_kind);

        CREATE TABLE world_data_layers (
            instance_path TEXT PRIMARY KEY,
            world_path TEXT NOT NULL,
            instance_name TEXT NOT NULL,
            data_layer_name TEXT NOT NULL,
            full_name TEXT NOT NULL,
            short_name TEXT NOT NULL,
            parent_instance_path TEXT NOT NULL,
            runtime INTEGER NOT NULL,
            initially_loaded_in_editor INTEGER NOT NULL,
            initially_visible INTEGER NOT NULL,
            asset_path TEXT NOT NULL,
            asset_class TEXT NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX world_data_layers_world_idx ON world_data_layers(world_path);
        CREATE INDEX world_data_layers_parent_idx ON world_data_layers(parent_instance_path);
        CREATE INDEX world_data_layers_asset_idx ON world_data_layers(asset_path);

        CREATE TABLE world_partition_actor_descs (
            world_path TEXT NOT NULL,
            actor_guid TEXT NOT NULL,
            actor_name TEXT NOT NULL,
            actor_label TEXT NOT NULL,
            actor_package TEXT NOT NULL,
            actor_soft_path TEXT NOT NULL,
            native_class TEXT NOT NULL,
            folder TEXT NOT NULL,
            folder_guid TEXT NOT NULL,
            parent_actor_guid TEXT NOT NULL,
            transform_json TEXT NOT NULL,
            editor_bounds_json TEXT NOT NULL,
            spatially_loaded INTEGER NOT NULL,
            editor_only INTEGER NOT NULL,
            runtime_only INTEGER NOT NULL,
            hlod_relevant INTEGER NOT NULL,
            data_layer_instance_names_json TEXT NOT NULL,
            actor_reference_guids_json TEXT NOT NULL,
            tags_json TEXT NOT NULL,
            runtime_grid TEXT NOT NULL,
            runtime_bounds_json TEXT NOT NULL,
            json TEXT NOT NULL,
            PRIMARY KEY(world_path, actor_guid)
        );
        CREATE INDEX wp_desc_package_idx ON world_partition_actor_descs(actor_package);
        CREATE INDEX wp_desc_class_idx ON world_partition_actor_descs(native_class);
        CREATE INDEX wp_desc_parent_idx ON world_partition_actor_descs(world_path, parent_actor_guid);
        """
    )

    try:
        conn.execute(
            "CREATE VIRTUAL TABLE source_fts USING fts5(path, text, content='source_chunks', content_rowid='id')"
        )
        conn.executescript(
            """
            CREATE TRIGGER source_chunks_ai AFTER INSERT ON source_chunks BEGIN
              INSERT INTO source_fts(rowid, path, text) VALUES (new.id, new.path, new.text);
            END;
            CREATE TRIGGER source_chunks_ad AFTER DELETE ON source_chunks BEGIN
              INSERT INTO source_fts(source_fts, rowid, path, text) VALUES('delete', old.id, old.path, old.text);
            END;
            CREATE TRIGGER source_chunks_au AFTER UPDATE ON source_chunks BEGIN
              INSERT INTO source_fts(source_fts, rowid, path, text) VALUES('delete', old.id, old.path, old.text);
              INSERT INTO source_fts(rowid, path, text) VALUES (new.id, new.path, new.text);
            END;
            """
        )
    except sqlite3.OperationalError:
        # Some Python SQLite builds omit FTS5. Queries fall back to LIKE.
        pass


def _legacy_graph_system(row: dict) -> str:
    graph_class = str(row.get("graph_class", ""))
    schema_class = str(row.get("schema_class", ""))
    combined = f"{graph_class} {schema_class}"
    if "ControlRig" in combined:
        return "control_rig"
    if "BlendStack" in combined:
        return "blend_stack"
    if "AnimGraph" in combined or "Animation" in combined:
        return "animation"
    if "WidgetGraphSchema" in combined:
        return "umg"
    if "EdGraphSchema_K2" in combined:
        return "k2"
    return "graph"


def _legacy_graph_id(row: dict) -> str:
    return f'{row.get("blueprint_path", "")}::legacy_graph::{row.get("graph_name", "")}'


def iter_blueprint_graph_rows(output: Path) -> Iterator[dict]:
    path = output / "blueprint_graphs.jsonl"
    if path.exists() and path.stat().st_size:
        yield from iter_jsonl(path)
        return

    seen: set[str] = set()
    for node in iter_jsonl(output / "blueprint_nodes.jsonl"):
        graph_id = node.get("graph_id") or _legacy_graph_id(node)
        if graph_id in seen:
            continue
        seen.add(graph_id)
        yield {
            "graph_id": graph_id,
            "blueprint_path": node.get("blueprint_path", ""),
            "graph_name": node.get("graph_name", ""),
            "graph_path": node.get("graph_path", ""),
            "graph_kind": node.get("graph_kind", ""),
            "graph_system": node.get("graph_system") or _legacy_graph_system(node),
            "graph_class": node.get("graph_class", ""),
            "schema_class": node.get("schema_class", ""),
            "outer_path": "",
            "outer_class": "",
            "parent_node_guid": "",
            "parent_graph_path": "",
            "node_count": 0,
        }


def iter_blueprint_pin_rows(output: Path) -> Iterator[dict]:
    path = output / "blueprint_pins.jsonl"
    if path.exists() and path.stat().st_size:
        yield from iter_jsonl(path)
        return

    # Schema <=5 stored pins inline on each node. Derive normalized rows so old
    # scans (including the Content Examples collision corpus) remain packable.
    seen: set[str] = set()
    for node in iter_jsonl(output / "blueprint_nodes.jsonl"):
        graph_id = node.get("graph_id") or _legacy_graph_id(node)
        for index, pin in enumerate(node.get("pins", [])):
            pin_id = pin.get("pin_id", "")
            if not pin_id or pin_id in seen:
                continue
            seen.add(pin_id)
            pin_type = pin.get("type", {}) if isinstance(pin.get("type", {}), dict) else {}
            yield {
                **pin,
                "pin_id": pin_id,
                "node_id": node.get("node_id", ""),
                "blueprint_path": node.get("blueprint_path", ""),
                "graph_id": graph_id,
                "graph_name": node.get("graph_name", ""),
                "pin_index": index,
                "linked_count": 0,
                "type": pin_type,
            }



DERIVED_SCHEMA_VERSION = 7


def _write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
            count += 1
    return count


def _parse_xy(text: str) -> tuple[float, float] | None:
    match = re.search(r"X=([-+0-9.eE]+).*?Y=([-+0-9.eE]+)", text or "")
    if not match:
        return None
    try:
        return float(match.group(1)), float(match.group(2))
    except ValueError:
        return None


def _graph_match_tokens(graph: dict) -> list[str]:
    tokens: list[str] = []
    for key in ("graph_path", "outer_path"):
        value = str(graph.get(key, ""))
        if ":" in value:
            value = value.split(":", 1)[1]
        for part in value.split("."):
            part = part.strip()
            if not part:
                continue
            if part.endswith("_SubGraph"):
                part = part[:-9]
            if part == "Rig Graph":
                part = "RigVMModel"
            if len(part) >= 3 and part not in tokens:
                tokens.append(part)
    graph_name = str(graph.get("graph_name", "")).strip()
    if graph_name.endswith("_SubGraph"):
        graph_name = graph_name[:-9]
    if graph_name == "Rig Graph":
        graph_name = "RigVMModel"
    if graph_name and graph_name not in tokens:
        tokens.append(graph_name)
    return tokens

def _rigvm_name_matches(editor_name: str, rig_name: str) -> bool:
    if not editor_name or not rig_name:
        return False
    return (
        editor_name == rig_name
        or rig_name.startswith(editor_name + "_")
        or rig_name.startswith(editor_name + " ")
        or rig_name.startswith(editor_name)
        or editor_name.startswith(rig_name)
    )


def _rigvm_graph_segments(object_id: str) -> list[str]:
    value = object_id.split(":", 1)[1] if ":" in object_id else object_id
    return [part for part in value.split(".") if part]


def _editor_graph_scope_tokens(graph: dict) -> list[str]:
    tokens = _graph_match_tokens(graph)
    # Exact path segments carry more information than generic substring
    # matching.  In particular they distinguish Add from Add_2 and nested
    # SequenceExecution graphs that otherwise have identical node layouts.
    return [token for token in tokens if token and token != "ContainedGraph"]


def derive_rigvm_editor_links(output: Path) -> list[dict]:
    """Join ControlRig editor nodes to their underlying RigVM model nodes.

    Matching is deliberately graph-first.  A whole editor Control Rig graph is
    compared with each RigVM graph scope in the same Blueprint, using node
    names, node positions, exact graph hierarchy segments and node counts.  We
    then match individual editor nodes only inside the uniquely selected model
    graph.  This avoids collisions between repeated Entry/Return/Sequence nodes
    in different nested RigVM graphs.
    """
    graphs = {row.get("graph_id", ""): row for row in iter_blueprint_graph_rows(output)}

    editor_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    seen_editor_nodes: set[str] = set()
    for row in iter_jsonl(output / "blueprint_nodes.jsonl"):
        if row.get("operation") != "control_rig_node":
            continue
        node_id = row.get("node_id", "")
        if node_id in seen_editor_nodes:
            continue
        seen_editor_nodes.add(node_id)
        editor_by_graph[row.get("graph_id", "")].append(row)

    rig_graphs_by_bp: dict[str, list[dict]] = collections.defaultdict(list)
    rig_nodes_by_scope: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    for row in iter_jsonl(output / "rigvm_objects.jsonl"):
        bp = row.get("blueprint_path", "")
        if row.get("kind") == "graph":
            rig_graphs_by_bp[bp].append(row)
        elif row.get("kind") == "node":
            rig_nodes_by_scope[(bp, row.get("outer_object_id", ""))].append(row)

    rows: list[dict] = []
    for graph_id, editor_nodes in editor_by_graph.items():
        if not editor_nodes:
            continue
        bp = editor_nodes[0].get("blueprint_path", "")
        graph = graphs.get(graph_id, {})
        graph_tokens = _editor_graph_scope_tokens(graph)

        scope_scores: list[tuple[int, int, int, dict, list[dict], list[str]]] = []
        for rig_graph in rig_graphs_by_bp.get(bp, []):
            rig_graph_id = rig_graph.get("object_id", "")
            rig_nodes = rig_nodes_by_scope.get((bp, rig_graph_id), [])
            if not rig_nodes:
                continue

            matched_editor_nodes = 0
            node_score = 0
            for editor_node in editor_nodes:
                semantic = editor_node.get("semantic", {}) if isinstance(editor_node.get("semantic"), dict) else {}
                editor_name = str(semantic.get("model_node_path", "") or editor_node.get("symbol", ""))
                sx = float(editor_node.get("x", 0))
                sy = float(editor_node.get("y", 0))
                best = None
                for rig_node in rig_nodes:
                    rig_name = str(rig_node.get("name", ""))
                    if editor_name == rig_name:
                        score = 100
                    elif _rigvm_name_matches(editor_name, rig_name):
                        score = 55
                    else:
                        continue
                    position = _parse_xy(str(rig_node.get("position", "")))
                    if position:
                        distance = ((position[0] - sx) ** 2 + (position[1] - sy) ** 2) ** 0.5
                        if distance <= 1.0:
                            score += 80
                        elif distance <= 5.0:
                            score += 50
                        elif distance <= 30.0:
                            score += 15
                        elif distance > 200.0:
                            score -= 20
                    if best is None or score > best:
                        best = score
                if best is not None:
                    matched_editor_nodes += 1
                    node_score += best

            rig_segments = _rigvm_graph_segments(rig_graph_id)
            exact_context_hits = sum(1 for token in graph_tokens if token in rig_segments)
            scope_score = node_score + exact_context_hits * 100
            scope_score -= abs(len(editor_nodes) - len(rig_nodes)) * 5
            scope_scores.append((
                matched_editor_nodes,
                scope_score,
                exact_context_hits,
                rig_graph,
                rig_nodes,
                graph_tokens,
            ))

        scope_scores.sort(key=lambda item: (-item[0], -item[1], item[3].get("object_id", "")))
        chosen_scope = None
        scope_tied = False
        if scope_scores:
            best_key = (scope_scores[0][0], scope_scores[0][1])
            best_scopes = [item for item in scope_scores if (item[0], item[1]) == best_key]
            if len(best_scopes) == 1:
                chosen_scope = best_scopes[0]
            else:
                scope_tied = True

        for editor_node in editor_nodes:
            node_id = editor_node.get("node_id", "")
            semantic = editor_node.get("semantic", {}) if isinstance(editor_node.get("semantic"), dict) else {}
            editor_name = str(semantic.get("model_node_path", "") or editor_node.get("symbol", ""))
            sx = float(editor_node.get("x", 0))
            sy = float(editor_node.get("y", 0))

            status = "unmatched"
            confidence = "none"
            chosen: dict = {}
            best_score = 0
            candidate_count = 0
            match_basis: list[str] = []
            rigvm_graph_id = ""
            scope_score = 0

            if chosen_scope is not None:
                _, scope_score, exact_hits, rig_graph, rig_nodes, _ = chosen_scope
                rigvm_graph_id = rig_graph.get("object_id", "")
                candidates: list[tuple[int, float, dict, list[str]]] = []
                for rig_node in rig_nodes:
                    rig_name = str(rig_node.get("name", ""))
                    basis: list[str] = []
                    if editor_name == rig_name:
                        score = 100
                        basis.append("model_name")
                    elif _rigvm_name_matches(editor_name, rig_name):
                        score = 50
                        basis.append("model_name_prefix")
                    else:
                        continue

                    distance = float("inf")
                    position = _parse_xy(str(rig_node.get("position", "")))
                    if position:
                        distance = ((position[0] - sx) ** 2 + (position[1] - sy) ** 2) ** 0.5
                        if distance <= 1.0:
                            score += 100
                            basis.append("position_exact")
                        elif distance <= 5.0:
                            score += 60
                            basis.append("position_near")
                        elif distance <= 30.0:
                            score += 20
                            basis.append("position_tolerant")
                        else:
                            score -= min(30, int(distance / 100.0))
                    candidates.append((score, distance, rig_node, basis))

                candidates.sort(key=lambda item: (-item[0], item[1], item[2].get("object_id", "")))
                if candidates:
                    best_score = candidates[0][0]
                    best_distance = candidates[0][1]
                    tied = [item for item in candidates if item[0] == best_score and abs(item[1] - best_distance) < 1e-6]
                    candidate_count = len(tied)
                    if len(tied) == 1:
                        status = "matched"
                        confidence = "high"
                        chosen = tied[0][2]
                        match_basis = tied[0][3] + ["graph_scope", f"graph_context:{exact_hits}"]
                    else:
                        status = "ambiguous"
            elif scope_tied:
                status = "ambiguous"
                candidate_count = len(scope_scores)

            rows.append({
                "node_id": node_id,
                "blueprint_path": bp,
                "graph_id": graph_id,
                "graph_name": editor_node.get("graph_name", ""),
                "model_node_path": editor_name,
                "status": status,
                "confidence": confidence,
                "score": best_score,
                "scope_score": scope_score,
                "candidate_count": candidate_count,
                "match_basis": match_basis,
                "rigvm_graph_id": rigvm_graph_id,
                "rigvm_object_id": chosen.get("object_id", ""),
                "rigvm_operation": chosen.get("operation", ""),
                "rigvm_class": chosen.get("class_path", ""),
                "resolved_function_name": chosen.get("resolved_function_name", ""),
                "template_notation": chosen.get("template_notation", ""),
            })
    return rows


def _pin_type_fields(pin: dict) -> dict:
    pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
    return {
        "category": pin.get("pin_category", pin_type.get("category", "")),
        "subcategory": pin.get("pin_subcategory", pin_type.get("subcategory", "")),
        "subcategory_object": pin.get("pin_subcategory_object", pin_type.get("subcategory_object", "")),
        "container_type": int(pin.get("container_type", pin_type.get("container_type", 0)) or 0),
    }


def _pin_signature(pin: dict) -> dict:
    return {
        "name": pin.get("name", ""),
        "type": _pin_type_fields(pin),
        "default_value": pin.get("default_value", ""),
        "default_object": pin.get("default_object", ""),
        "default_text": pin.get("default_text", ""),
    }


def _is_exec_pin(pin: dict) -> bool:
    return str(_pin_type_fields(pin).get("category", "")).lower() == "exec"


def _pin_direction_is_output(pin: dict) -> bool:
    return str(pin.get("direction", "")).lower() in {"output", "egpd_output", "1"}


def derive_blueprint_functions(output: Path) -> list[dict]:
    nodes_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    for node in iter_jsonl(output / "blueprint_nodes.jsonl"):
        nodes_by_graph[node.get("graph_id", "")].append(node)
    pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for pin in iter_blueprint_pin_rows(output):
        pins_by_node[pin.get("node_id", "")].append(pin)

    rows: list[dict] = []
    for graph in iter_blueprint_graph_rows(output):
        gid = graph.get("graph_id", "")
        graph_nodes = nodes_by_graph.get(gid, [])
        entries = [n for n in graph_nodes if n.get("operation") == "function_entry"]
        if not entries:
            continue
        entries.sort(key=lambda n: n.get("node_id", ""))
        entry = entries[0]
        results = sorted((n for n in graph_nodes if n.get("operation") == "function_result"), key=lambda n: n.get("node_id", ""))
        entry_sem = entry.get("semantic", {}) if isinstance(entry.get("semantic"), dict) else {}

        inputs = [
            _pin_signature(pin)
            for pin in pins_by_node.get(entry.get("node_id", ""), [])
            if _pin_direction_is_output(pin) and not _is_exec_pin(pin) and pin.get("name") != "OutputDelegate"
        ]
        outputs: list[dict] = []
        output_seen: set[tuple] = set()
        for result in results:
            for pin in pins_by_node.get(result.get("node_id", ""), []):
                if _pin_direction_is_output(pin) or _is_exec_pin(pin):
                    continue
                signature = _pin_signature(pin)
                key = (signature["name"], json.dumps(signature["type"], sort_keys=True))
                if key not in output_seen:
                    output_seen.add(key)
                    outputs.append(signature)

        has_exec = any(_is_exec_pin(pin) for pin in pins_by_node.get(entry.get("node_id", ""), []))
        if not has_exec:
            has_exec = any(_is_exec_pin(pin) for result in results for pin in pins_by_node.get(result.get("node_id", ""), []))
        locals_value = entry_sem.get("local_variables", [])
        locals_list = locals_value if isinstance(locals_value, list) else []
        name = str(entry.get("symbol", "") or graph.get("graph_name", ""))
        function_flags = int(entry_sem.get("function_flags", 0) or 0)
        rows.append({
            "function_id": gid,
            "blueprint_path": graph.get("blueprint_path", ""),
            "graph_id": gid,
            "graph_name": graph.get("graph_name", ""),
            "graph_path": graph.get("graph_path", ""),
            "graph_kind": graph.get("graph_kind", ""),
            "graph_system": graph.get("graph_system", ""),
            "name": name,
            "owner": entry.get("owner", ""),
            "resolved_function": entry_sem.get("resolved_function", ""),
            "function_flags": function_flags,
            "has_exec": has_exec,
            # UE keeps exec pins on function entry/result nodes even for
            # BlueprintPure functions. Preserve the structural fact separately
            # from the authoritative UFunction flags.
            "pure_shape": not has_exec,
            "blueprint_pure": bool(function_flags & 0x10000000),
            "const_function": bool(function_flags & 0x40000000),
            "blueprint_callable": bool(function_flags & 0x04000000),
            "static_function": bool(function_flags & 0x00002000),
            "event_function": bool(function_flags & 0x08000000),
            "entry_node_id": entry.get("node_id", ""),
            "result_node_ids": [n.get("node_id", "") for n in results],
            "result_node_count": len(results),
            "inputs": inputs,
            "outputs": outputs,
            "locals": locals_list,
        })
    return rows


def _node_property_lookup(output: Path) -> dict[str, dict[str, dict]]:
    result: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    for row in iter_jsonl(output / "blueprint_node_properties.jsonl"):
        node_id = row.get("node_id", "")
        path = row.get("property_path", "") or row.get("property_name", "")
        if node_id and path and path not in result[node_id]:
            result[node_id][path] = row
    return result


def _property_value(props: dict[str, dict], *names: str) -> str:
    for name in names:
        row = props.get(name)
        if row:
            return str(row.get("object_path", "") or row.get("value", ""))
    return ""


def derive_blueprint_events(output: Path) -> list[dict]:
    properties = _node_property_lookup(output)
    pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for pin in iter_blueprint_pin_rows(output):
        pins_by_node[pin.get("node_id", "")].append(pin)

    rows: list[dict] = []
    event_ops = {"event", "custom_event", "enhanced_input_event", "legacy_input_action", "input_key"}
    for node in iter_jsonl(output / "blueprint_nodes.jsonl"):
        op = node.get("operation", "")
        if op not in event_ops:
            continue
        node_id = node.get("node_id", "")
        props = properties.get(node_id, {})
        node_class = str(node.get("node_class", ""))
        sem = node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {}

        event_kind = "event"
        if "ComponentBoundEvent" in node_class:
            event_kind = "component_bound"
        elif "InputAxisEvent" in node_class:
            event_kind = "input_axis"
        elif op == "custom_event":
            event_kind = "custom"
        elif op == "enhanced_input_event":
            event_kind = "enhanced_input"
        elif op == "legacy_input_action":
            event_kind = "input_action"
        elif op == "input_key":
            event_kind = "input_key"
        elif sem.get("override_function"):
            event_kind = "override"

        component_name = _property_value(props, "ComponentPropertyName")
        delegate_name = _property_value(props, "DelegatePropertyName")
        delegate_owner = _property_value(props, "DelegateOwnerClass")
        input_name = (
            str(sem.get("input_action", "") or sem.get("action_name", ""))
            or _property_value(props, "InputActionName", "InputAxisName", "InputKey")
        )
        name = delegate_name if event_kind == "component_bound" and delegate_name else str(node.get("symbol", "") or node.get("title", ""))

        parameters = [
            _pin_signature(pin)
            for pin in pins_by_node.get(node_id, [])
            if _pin_direction_is_output(pin) and not _is_exec_pin(pin) and pin.get("name") != "OutputDelegate"
        ]
        rows.append({
            "event_id": node_id,
            "blueprint_path": node.get("blueprint_path", ""),
            "graph_id": node.get("graph_id", ""),
            "graph_name": node.get("graph_name", ""),
            "node_class": node_class,
            "operation": op,
            "event_kind": event_kind,
            "name": name,
            "owner": node.get("owner", ""),
            "component_name": component_name,
            "delegate_name": delegate_name,
            "delegate_owner": delegate_owner,
            "input_name": input_name,
            "override_function": bool(sem.get("override_function", False)),
            "parameters": parameters,
            "consume_input": _property_value(props, "bConsumeInput"),
            "execute_when_paused": _property_value(props, "bExecuteWhenPaused"),
            "override_parent_binding": _property_value(props, "bOverrideParentBinding"),
        })
    return rows

def _blueprint_object_path_from_class_path(class_path: str) -> str:
    """Best-effort conversion from generated/skeleton class path to Blueprint object path."""
    if not class_path or not class_path.startswith("/Game/") or "." not in class_path:
        return ""
    package, obj = class_path.rsplit(".", 1)
    if obj.startswith("SKEL_"):
        obj = obj[5:]
    elif obj.startswith("REINST_"):
        obj = obj[7:]
        obj = re.sub(r"_C_\\d+$", "_C", obj)
    if obj.endswith("_C"):
        obj = obj[:-2]
    return f"{package}.{obj}"


def derive_blueprint_call_edges(output: Path, functions: list[dict]) -> list[dict]:
    """Resolve Blueprint function-call nodes to local definitions where possible.

    Function paths can legitimately collide for interface implementations and
    overrides.  We therefore preserve all candidates and only report a unique
    internal target when the owning Blueprint can be resolved unambiguously.
    """
    by_resolved: dict[str, list[dict]] = collections.defaultdict(list)
    by_bp_name: dict[tuple[str, str], list[dict]] = collections.defaultdict(list)
    caller_by_graph = {row.get("graph_id", ""): row for row in functions}
    for row in functions:
        resolved = str(row.get("resolved_function", ""))
        if resolved:
            by_resolved[resolved].append(row)
        by_bp_name[(str(row.get("blueprint_path", "")), str(row.get("name", "")))].append(row)

    rows: list[dict] = []
    for node in iter_jsonl(output / "blueprint_nodes.jsonl"):
        if node.get("operation") != "function_call":
            continue
        sem = node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {}
        resolved = str(sem.get("resolved_function", ""))
        target_name = str(sem.get("function_name", "") or node.get("symbol", ""))
        target_owner = str(sem.get("function_owner", "") or node.get("owner", ""))
        target_bp = _blueprint_object_path_from_class_path(target_owner)

        candidates = list(by_resolved.get(resolved, [])) if resolved else []
        if target_bp:
            owner_candidates = [row for row in candidates if row.get("blueprint_path") == target_bp]
            if owner_candidates:
                candidates = owner_candidates
            elif not candidates:
                candidates = list(by_bp_name.get((target_bp, target_name), []))

        unique = candidates[0] if len(candidates) == 1 else None
        if unique:
            resolution = "internal"
        elif candidates:
            resolution = "ambiguous_internal"
        elif resolved:
            resolution = "external"
        else:
            resolution = "unresolved"

        caller = caller_by_graph.get(node.get("graph_id", ""))
        candidate_ids = [str(row.get("function_id", "")) for row in candidates]
        rows.append({
            "call_id": node.get("node_id", ""),
            "blueprint_path": node.get("blueprint_path", ""),
            "graph_id": node.get("graph_id", ""),
            "graph_name": node.get("graph_name", ""),
            "caller_function_id": caller.get("function_id", "") if caller else "",
            "call_node_id": node.get("node_id", ""),
            "target_function": resolved,
            "target_name": target_name,
            "target_owner": target_owner,
            "target_blueprint_path": unique.get("blueprint_path", "") if unique else target_bp,
            "target_function_id": unique.get("function_id", "") if unique else "",
            "resolution": resolution,
            "candidate_count": len(candidates),
            "candidate_function_ids": candidate_ids,
            "pure": bool(sem.get("pure", False)),
            "const_function": bool(sem.get("const", False)),
            "latent": bool(sem.get("latent", False)),
            "interface_call": bool(sem.get("interface_call", False)),
            "function_flags": int(sem.get("function_flags", 0) or 0),
        })
    return rows


def derive_blueprint_call_bindings(
    output: Path,
    functions: list[dict],
    call_edges: list[dict],
    data_dependencies: list[dict],
) -> list[dict]:
    """Bridge uniquely resolved Blueprint calls across function boundaries.

    The canonical pin graph stops at a function-call node.  For calls that
    resolve to exactly one project Blueprint function, this derived view maps:
      caller input pin -> callee function-entry parameter pin
      callee function-result parameter pin -> caller output pin

    Split struct pins are mapped to their parent parameter and retain the raw
    suffix instead of guessing a member hierarchy. Ambiguous interface/
    override calls deliberately produce no bindings.
    """
    function_by_id = {str(row.get("function_id", "")): row for row in functions}

    pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    pin_by_id: dict[str, dict] = {}
    for pin in iter_blueprint_pin_rows(output):
        node_id = str(pin.get("node_id", ""))
        pin_id = str(pin.get("pin_id", ""))
        if node_id:
            pins_by_node[node_id].append(pin)
        if pin_id:
            pin_by_id[pin_id] = pin

    outgoing_by_pin: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in iter_jsonl(output / "blueprint_edges.jsonl"):
        if edge.get("edge_kind") != "data":
            continue
        source_pin_id = str(edge.get("source_pin_id", ""))
        if source_pin_id:
            outgoing_by_pin[source_pin_id].append(edge)

    dependency_by_sink_pin: dict[str, list[str]] = collections.defaultdict(list)
    for dependency in data_dependencies:
        sink_pin_id = str(dependency.get("sink_pin_id", ""))
        dependency_id = str(dependency.get("dependency_id", ""))
        if sink_pin_id and dependency_id:
            dependency_by_sink_pin[sink_pin_id].append(dependency_id)

    def is_exec_pin(pin: dict) -> bool:
        pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
        return str(pin_type.get("category", "")).lower() == "exec"

    def is_input_pin(pin: dict) -> bool:
        return str(pin.get("direction", "")).lower() in {"input", "egpd_input", "0"}

    def normalized_type(pin_type: dict) -> dict:
        pin_type = pin_type if isinstance(pin_type, dict) else {}
        return {
            "category": str(pin_type.get("category", "") or ""),
            "subcategory": str(pin_type.get("subcategory", "") or ""),
            "subcategory_object": str(pin_type.get("subcategory_object", "") or ""),
            "container_type": int(pin_type.get("container_type", 0) or 0),
            "is_reference": bool(pin_type.get("is_reference", False)),
            "is_const": bool(pin_type.get("is_const", False)),
        }

    def value_type_key(pin_type: dict) -> tuple:
        normalized = normalized_type(pin_type)
        return (
            normalized["category"],
            normalized["subcategory"],
            normalized["subcategory_object"],
            normalized["container_type"],
        )

    def qualifiers(pin_type: dict) -> dict:
        normalized = normalized_type(pin_type)
        return {
            "is_reference": normalized["is_reference"],
            "is_const": normalized["is_const"],
        }

    def parameter_records(function: dict, direction: str) -> list[dict]:
        if direction == "argument":
            node_ids = [str(function.get("entry_node_id", ""))]
            signature = function.get("inputs", []) if isinstance(function.get("inputs"), list) else []
            want_output = True
        else:
            node_ids = [str(value) for value in function.get("result_node_ids", [])]
            signature = function.get("outputs", []) if isinstance(function.get("outputs"), list) else []
            want_output = False

        signature_by_name = {
            str(item.get("name", "")): item
            for item in signature
            if isinstance(item, dict) and item.get("name")
        }
        pin_ids_by_name: dict[str, list[str]] = collections.defaultdict(list)
        for node_id in node_ids:
            for pin in pins_by_node.get(node_id, []):
                if is_exec_pin(pin):
                    continue
                if _pin_direction_is_output(pin) != want_output:
                    continue
                name = str(pin.get("name", ""))
                if direction == "argument" and name == "OutputDelegate":
                    continue
                if name:
                    pin_ids_by_name[name].append(str(pin.get("pin_id", "")))

        result: list[dict] = []
        for name, item in signature_by_name.items():
            result.append({
                "name": name,
                "type": item.get("type", {}) if isinstance(item.get("type"), dict) else {},
                "pin_ids": [value for value in pin_ids_by_name.get(name, []) if value],
            })
        return result

    def match_parameter(call_pin_name: str, parameters: list[dict]) -> tuple[dict | None, str, str]:
        exact = [item for item in parameters if item.get("name") == call_pin_name]
        if len(exact) == 1:
            return exact[0], "exact", ""

        # UE names split struct pins as Parent_Member. Prefer the longest parent
        # parameter so similarly prefixed parameters remain deterministic.
        split = [
            item for item in parameters
            if item.get("name") and call_pin_name.startswith(str(item.get("name")) + "_")
        ]
        split.sort(key=lambda item: (-len(str(item.get("name", ""))), str(item.get("name", ""))))
        if split:
            parent = split[0]
            parent_name = str(parent.get("name", ""))
            return parent, "split_struct", call_pin_name[len(parent_name) + 1:]
        return None, "", ""

    rows: list[dict] = []
    for call in call_edges:
        if call.get("resolution") != "internal":
            continue
        target_function_id = str(call.get("target_function_id", ""))
        target = function_by_id.get(target_function_id)
        if not target:
            continue

        call_node_id = str(call.get("call_node_id", ""))
        argument_parameters = parameter_records(target, "argument")
        return_parameters = parameter_records(target, "return")

        for call_pin in pins_by_node.get(call_node_id, []):
            if is_exec_pin(call_pin):
                continue
            direction = "argument" if is_input_pin(call_pin) else "return"
            parameters = argument_parameters if direction == "argument" else return_parameters
            call_pin_name = str(call_pin.get("name", ""))
            parameter, match_kind, split_suffix = match_parameter(call_pin_name, parameters)
            if not parameter:
                # Context pins such as self/Target are not function parameters.
                continue

            call_pin_id = str(call_pin.get("pin_id", ""))
            parameter_pin_ids = [str(value) for value in parameter.get("pin_ids", []) if value]
            parameter_pins = [
                pin_by_id[pin_id]
                for pin_id in parameter_pin_ids
                if pin_id in pin_by_id
            ]
            parameter_pin_types = [
                pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
                for pin in parameter_pins
            ]
            if direction == "argument":
                dependency_ids = list(dependency_by_sink_pin.get(call_pin_id, []))
                consumer_pin_ids = sorted({
                    str(edge.get("target_pin_id", ""))
                    for parameter_pin_id in parameter_pin_ids
                    for edge in outgoing_by_pin.get(parameter_pin_id, [])
                    if edge.get("target_pin_id")
                })
            else:
                dependency_ids = sorted({
                    dependency_id
                    for parameter_pin_id in parameter_pin_ids
                    for dependency_id in dependency_by_sink_pin.get(parameter_pin_id, [])
                })
                consumer_pin_ids = sorted({
                    str(edge.get("target_pin_id", ""))
                    for edge in outgoing_by_pin.get(call_pin_id, [])
                    if edge.get("target_pin_id")
                })

            basis = "\x1f".join((call_node_id, direction, call_pin_id, str(parameter.get("name", ""))))
            binding_id = "bind:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]
            call_pin_type = call_pin.get("type", {}) if isinstance(call_pin.get("type"), dict) else {}
            parameter_type = parameter.get("type", {}) if isinstance(parameter.get("type"), dict) else {}

            if match_kind == "exact":
                parameter_identity_kind = "exact_parameter"
                member_identity_exact = True
                value_type_basis = "call_signature_parameter_pin"
                value_type_compatible = bool(
                    parameter_pin_ids
                    and len(parameter_pins) == len(parameter_pin_ids)
                    and value_type_key(call_pin_type) == value_type_key(parameter_type)
                    and all(
                        value_type_key(pin_type) == value_type_key(parameter_type)
                        for pin_type in parameter_pin_types
                    )
                )
            else:
                parameter_identity_kind = "split_parent_projection"
                member_identity_exact = False
                value_type_basis = "signature_parent_parameter_pin"
                value_type_compatible = bool(
                    parameter_pin_ids
                    and len(parameter_pins) == len(parameter_pin_ids)
                    and all(
                        value_type_key(pin_type) == value_type_key(parameter_type)
                        for pin_type in parameter_pin_types
                    )
                )

            qualifier_surfaces = {
                "call_pin": qualifiers(call_pin_type),
                "signature": qualifiers(parameter_type),
                "parameter_pins": [qualifiers(pin_type) for pin_type in parameter_pin_types],
            }
            rows.append({
                "binding_id": binding_id,
                "schema_version": BLUEPRINT_CALL_BINDING_SCHEMA_VERSION,
                "call_id": call.get("call_id", ""),
                "call_node_id": call_node_id,
                "caller_blueprint_path": call.get("blueprint_path", ""),
                "caller_graph_id": call.get("graph_id", ""),
                "caller_function_id": call.get("caller_function_id", ""),
                "target_blueprint_path": call.get("target_blueprint_path", ""),
                "target_function_id": target_function_id,
                "direction": direction,
                "call_pin_id": call_pin_id,
                "call_pin_name": call_pin_name,
                "parameter_name": parameter.get("name", ""),
                "parameter_pin_ids": parameter_pin_ids,
                "match_kind": match_kind,
                "split_suffix": split_suffix,
                "parameter_identity_kind": parameter_identity_kind,
                "member_identity_exact": member_identity_exact,
                "call_pin_type": call_pin_type,
                "parameter_type": parameter_type,
                "parameter_pin_types": parameter_pin_types,
                "value_type_compatible": value_type_compatible,
                "value_type_basis": value_type_basis,
                "qualifier_surfaces": qualifier_surfaces,
                "dependency_ids": dependency_ids,
                "consumer_pin_ids": consumer_pin_ids,
            })
    return rows


_STRUCT_NODE_OPERATIONS = {
    "/Script/BlueprintGraph.K2Node_MakeStruct": "make_struct",
    "/Script/BlueprintGraph.K2Node_BreakStruct": "break_struct",
    "/Script/BlueprintGraph.K2Node_SetFieldsInStruct": "set_fields_in_struct",
}


def _effective_blueprint_operation(node: dict) -> str:
    """Return corrected semantic operation for legacy schema-10 struct nodes.

    Scanner schema 11 emits these operations canonically.  Schema 10 labeled
    the three struct-operation classes as variable_reference because they
    inherit UK2Node_Variable.  Keep derive/pack backward-compatible without
    mutating old canonical scans.
    """
    node_class = str(node.get("node_class", ""))
    return _STRUCT_NODE_OPERATIONS.get(node_class, str(node.get("operation", "")))


def _node_struct_type(node: dict) -> str:
    semantic = node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {}
    struct_type = str(semantic.get("struct_type", ""))
    if struct_type:
        return struct_type

    # Legacy schema-10 fallback: exact struct type is still retained on pins.
    operation = _effective_blueprint_operation(node)
    pins = node.get("pins", []) if isinstance(node.get("pins"), list) else []
    preferred_direction = "output" if operation == "make_struct" else "input"
    for pin in pins:
        if not isinstance(pin, dict):
            continue
        pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
        if str(pin_type.get("category", "")) != "struct":
            continue
        if str(pin.get("direction", "")).lower() == preferred_direction:
            value = str(pin_type.get("subcategory_object", ""))
            if value:
                return value
    for pin in pins:
        if not isinstance(pin, dict):
            continue
        pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
        if str(pin_type.get("category", "")) == "struct":
            value = str(pin_type.get("subcategory_object", ""))
            if value:
                return value
    return ""


def _struct_type_short_name(path: str) -> str:
    if not path:
        return "struct"
    return path.rsplit(".", 1)[-1].rsplit("/", 1)[-1]


def _data_dependency_node_label(node: dict) -> str:
    operation = _effective_blueprint_operation(node)
    if operation in {"make_struct", "break_struct", "set_fields_in_struct"}:
        struct_name = _struct_type_short_name(_node_struct_type(node))
        prefix = {
            "make_struct": "Make",
            "break_struct": "Break",
            "set_fields_in_struct": "Set fields in",
        }[operation]
        return f"{prefix} {struct_name}"

    symbol = str(node.get("symbol", ""))
    if symbol and symbol != "None":
        return symbol
    return str(
        node.get("title", "")
        or operation
        or node.get("node_class", "").rsplit(".", 1)[-1]
    )


def _render_data_expression(expr: dict, depth: int = 0, max_depth: int = 8) -> str:
    """Render a compact deterministic expression summary for retrieval."""
    if not isinstance(expr, dict):
        return ""
    if depth >= max_depth:
        return "..."

    kind = str(expr.get("kind", ""))
    if kind == "multi":
        parts = [
            _render_data_expression(child, depth + 1, max_depth)
            for child in expr.get("sources", [])
            if isinstance(child, dict)
        ]
        rendered = [part for part in parts if part]
        return "multi(" + ", ".join(rendered) + ")"

    label = str(expr.get("label", "") or expr.get("operation", "") or kind)
    output_pin = str(expr.get("output_pin", ""))
    if kind in {"boundary", "cycle", "truncated", "missing"}:
        suffix = f".{output_pin}" if output_pin else ""
        return f"{kind}:{label}{suffix}"

    args: list[str] = []
    for item in expr.get("inputs", []):
        if not isinstance(item, dict):
            continue
        pin_name = str(item.get("pin", ""))
        if "literal" in item:
            value = str(item.get("literal", ""))
            args.append(f"{pin_name}={value}")
            continue
        child_text = [
            _render_data_expression(child, depth + 1, max_depth)
            for child in item.get("sources", [])
            if isinstance(child, dict)
        ]
        child_text = [value for value in child_text if value]
        if child_text:
            rendered_sources = child_text[0] if len(child_text) == 1 else "multi(" + ", ".join(child_text) + ")"
            args.append(f"{pin_name}={rendered_sources}")

    suffix = f".{output_pin}" if output_pin else ""
    if args:
        return f"{label}({', '.join(args)}){suffix}"
    return f"{label}{suffix}"


def derive_blueprint_data_dependencies(
    output: Path,
    *,
    max_depth: int = 24,
    max_nodes: int = 64,
) -> list[dict]:
    """Collapse upstream pure data graphs feeding executable Blueprint inputs.

    Raw pin/data edges remain authoritative.  This derived view starts at
    connected data inputs on execution-bearing nodes and graph result nodes,
    then recursively follows upstream data edges through pure/data-only nodes.
    Side-effecting/execution-bearing producers become explicit boundary leaves.
    Cycles and safety-limit truncation are retained rather than guessed through.
    """
    nodes: dict[str, dict] = {}
    for row in iter_jsonl(output / "blueprint_nodes.jsonl"):
        node_id = str(row.get("node_id", ""))
        if node_id:
            nodes[node_id] = row

    pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for row in iter_blueprint_pin_rows(output):
        node_id = str(row.get("node_id", ""))
        if node_id:
            pins_by_node[node_id].append(row)

    incoming_by_pin: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in iter_jsonl(output / "blueprint_edges.jsonl"):
        if edge.get("edge_kind") != "data":
            continue
        target_pin_id = str(edge.get("target_pin_id", ""))
        if target_pin_id:
            incoming_by_pin[target_pin_id].append(edge)

    def is_exec_pin(pin: dict) -> bool:
        pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
        return str(pin_type.get("category", "")).lower() == "exec"

    def is_input_pin(pin: dict) -> bool:
        return str(pin.get("direction", "")).lower() in {"input", "egpd_input", "0"}

    node_has_exec: dict[str, bool] = {
        node_id: any(is_exec_pin(pin) for pin in pin_rows)
        for node_id, pin_rows in pins_by_node.items()
    }

    result_operations = {
        "function_result",
        "anim_graph_root",
        "anim_state_result",
        "anim_transition_result",
    }

    def has_significant_default(pin: dict) -> bool:
        return bool(
            pin.get("default_object", "")
            or pin.get("default_value", "")
            or pin.get("default_text", "")
        )

    def trace_edge(
        edge: dict,
        state: dict,
        depth: int,
        stack: set[str],
    ) -> dict:
        source_node_id = str(edge.get("source_node_id", ""))
        source_pin_name = str(edge.get("source_pin_name", ""))
        node = nodes.get(source_node_id)
        if node is None:
            return {
                "kind": "missing",
                "node_id": source_node_id,
                "output_pin": source_pin_name,
            }

        label = _data_dependency_node_label(node)
        operation = _effective_blueprint_operation(node)

        # UK2Node_VariableSet exposes Output_Get as a value getter specifically
        # so authored graphs can read the variable without a separate Get node.
        # Treating that pin as an execution-bearing setter boundary loses the
        # read semantics and can manufacture a false dependency cycle when a
        # graph toggles a variable from its own Output_Get value.
        if operation == "variable_set" and source_pin_name == "Output_Get":
            variable = str(node.get("symbol", ""))
            if variable:
                state["variable_reads"].add(variable)
            return {
                "kind": "expression",
                "node_id": source_node_id,
                "operation": "variable_get",
                "label": variable or label,
                "output_pin": "",
            }

        if source_node_id in stack:
            state["cycle"] = True
            return {
                "kind": "cycle",
                "node_id": source_node_id,
                "operation": operation,
                "label": label,
                "output_pin": source_pin_name,
            }

        if depth >= max_depth or state["node_count"] >= max_nodes:
            state["truncated"] = True
            return {
                "kind": "truncated",
                "node_id": source_node_id,
                "operation": operation,
                "label": label,
                "output_pin": source_pin_name,
            }

        state["node_count"] += 1
        semantic = node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {}
        pure = (
            not node_has_exec.get(source_node_id, False)
            or (operation == "function_call" and bool(semantic.get("pure", False)))
        )
        result = {
            "kind": "expression" if pure else "boundary",
            "node_id": source_node_id,
            "operation": operation,
            "label": label,
            "output_pin": source_pin_name,
        }

        if operation == "variable_get":
            variable = str(node.get("symbol", ""))
            if variable:
                state["variable_reads"].add(variable)
        elif operation == "function_call":
            function = str(semantic.get("resolved_function", "") or node.get("symbol", ""))
            if function:
                state["function_calls"].add(function)

        if not pure:
            return result

        inputs: list[dict] = []
        child_stack = set(stack)
        child_stack.add(source_node_id)
        for pin in sorted(
            pins_by_node.get(source_node_id, []),
            key=lambda item: int(item.get("pin_index", 0)),
        ):
            if not is_input_pin(pin) or is_exec_pin(pin):
                continue

            incoming = incoming_by_pin.get(str(pin.get("pin_id", "")), [])
            if incoming:
                inputs.append({
                    "pin": pin.get("name", ""),
                    "sources": [
                        trace_edge(child, state, depth + 1, child_stack)
                        for child in incoming
                    ],
                })
                continue

            if has_significant_default(pin):
                value = str(
                    pin.get("default_object", "")
                    or pin.get("default_value", "")
                    or pin.get("default_text", "")
                )
                object_path = str(pin.get("default_object", ""))
                if object_path:
                    state["object_refs"].add(object_path)
                pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
                inputs.append({
                    "pin": pin.get("name", ""),
                    "literal": value,
                    "object": object_path,
                    "type": pin_type.get("category", ""),
                })

        if inputs:
            result["inputs"] = inputs
        return result

    rows: list[dict] = []
    for sink_node_id, node in nodes.items():
        sink_operation = _effective_blueprint_operation(node)
        if not (
            node_has_exec.get(sink_node_id, False)
            or sink_operation in result_operations
        ):
            continue

        for pin in sorted(
            pins_by_node.get(sink_node_id, []),
            key=lambda item: int(item.get("pin_index", 0)),
        ):
            if not is_input_pin(pin) or is_exec_pin(pin):
                continue

            sink_pin_id = str(pin.get("pin_id", ""))
            incoming = incoming_by_pin.get(sink_pin_id, [])
            if not incoming:
                # Unconnected defaults remain directly available in the
                # canonical pin record; this view is specifically provenance.
                continue

            state = {
                "node_count": 0,
                "truncated": False,
                "cycle": False,
                "variable_reads": set(),
                "function_calls": set(),
                "object_refs": set(),
            }
            trees = [
                trace_edge(edge, state, 0, {sink_node_id})
                for edge in incoming
            ]
            expression = trees[0] if len(trees) == 1 else {
                "kind": "multi",
                "sources": trees,
            }
            dependency_id = hashlib.sha1(
                f"{sink_pin_id}\x1fdata_dependency".encode("utf-8")
            ).hexdigest()
            rows.append({
                "dependency_id": dependency_id,
                "blueprint_path": node.get("blueprint_path", ""),
                "graph_id": node.get("graph_id", ""),
                "graph_name": node.get("graph_name", ""),
                "sink_node_id": sink_node_id,
                "sink_operation": sink_operation,
                "sink_label": _data_dependency_node_label(node),
                "sink_pin_id": sink_pin_id,
                "sink_pin_name": pin.get("name", ""),
                "source_count": len(incoming),
                "expression_node_count": int(state["node_count"]),
                "truncated": bool(state["truncated"]),
                "cycle": bool(state["cycle"]),
                "variable_reads": sorted(state["variable_reads"]),
                "function_calls": sorted(state["function_calls"]),
                "object_refs": sorted(state["object_refs"]),
                "expression": expression,
                "text": _render_data_expression(expression),
            })

    return rows


def derive_blueprint_execution_program(
    output: Path,
    functions: list[dict],
    events: list[dict],
) -> tuple[list[dict], list[dict], list[dict]]:
    """Collapse raw exec-pin wiring into deterministic Blueprint basic blocks."""
    nodes: dict[str, dict] = {}
    nodes_by_graph: dict[str, list[str]] = collections.defaultdict(list)
    for node in iter_jsonl(output / "blueprint_nodes.jsonl"):
        node_id = str(node.get("node_id", ""))
        if not node_id:
            continue
        nodes[node_id] = node
        nodes_by_graph[str(node.get("graph_id", ""))].append(node_id)

    exec_edges_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    incoming: dict[str, list[dict]] = collections.defaultdict(list)
    outgoing: dict[str, list[dict]] = collections.defaultdict(list)
    for edge in iter_jsonl(output / "blueprint_edges.jsonl"):
        if edge.get("edge_kind") != "execution":
            continue
        gid = str(edge.get("graph_id", ""))
        exec_edges_by_graph[gid].append(edge)
        incoming[str(edge.get("target_node_id", ""))].append(edge)
        outgoing[str(edge.get("source_node_id", ""))].append(edge)

    root_meta: dict[str, tuple[str, str]] = {}
    for fn in functions:
        nid = str(fn.get("entry_node_id", ""))
        if nid:
            root_meta[nid] = ("pure_function" if fn.get("blueprint_pure", False) else "function", str(fn.get("name", "")))
    for event in events:
        nid = str(event.get("event_id", ""))
        if nid:
            root_meta[nid] = (str(event.get("event_kind", "event")), str(event.get("name", "")))

    block_rows: list[dict] = []
    edge_rows: list[dict] = []
    root_rows: list[dict] = []

    program_graph_ids = set(exec_edges_by_graph)
    for root_node in root_meta:
        root_graph = str(nodes.get(root_node, {}).get("graph_id", ""))
        if root_graph:
            program_graph_ids.add(root_graph)

    for graph_id in sorted(program_graph_ids):
        graph_edges = exec_edges_by_graph.get(graph_id, [])
        exec_nodes: set[str] = set()
        for edge in graph_edges:
            exec_nodes.add(str(edge.get("source_node_id", "")))
            exec_nodes.add(str(edge.get("target_node_id", "")))
        graph_roots = sorted(nid for nid in root_meta if nodes.get(nid, {}).get("graph_id") == graph_id)
        exec_nodes.update(graph_roots)
        if not exec_nodes:
            continue

        starts: set[str] = set(graph_roots)
        for nid in exec_nodes:
            preds = incoming.get(nid, [])
            if len(preds) != 1:
                starts.add(nid)
                continue
            pred = str(preds[0].get("source_node_id", ""))
            if len(outgoing.get(pred, [])) != 1:
                starts.add(nid)

        block_for_node: dict[str, str] = {}
        blocks: list[tuple[str, list[str]]] = []

        def build_block(start: str) -> None:
            if start in block_for_node:
                return
            members: list[str] = []
            local_seen: set[str] = set()
            current = start
            while current and current not in block_for_node and current not in local_seen:
                local_seen.add(current)
                members.append(current)
                outs = outgoing.get(current, [])
                if len(outs) != 1:
                    break
                nxt = str(outs[0].get("target_node_id", ""))
                if not nxt or nxt in starts or len(incoming.get(nxt, [])) != 1:
                    break
                current = nxt
            digest = hashlib.sha1(f"{graph_id}|{start}".encode("utf-8")).hexdigest()[:20]
            block_id = f"block:{digest}"
            for nid in members:
                block_for_node[nid] = block_id
            blocks.append((block_id, members))

        for start in sorted(starts):
            build_block(start)
        # Closed cycles can have no natural start. Seed remaining nodes
        # deterministically so every executable node belongs to exactly one block.
        for nid in sorted(exec_nodes):
            build_block(nid)

        block_index = {bid: i for i, (bid, _) in enumerate(blocks)}
        for block_id, members in blocks:
            first_node = nodes.get(members[0], {}) if members else {}
            last_node = nodes.get(members[-1], {}) if members else {}
            ops = [str(nodes.get(nid, {}).get("operation", "")) for nid in members]
            labels = [str(nodes.get(nid, {}).get("symbol", "") or nodes.get(nid, {}).get("title", "")) for nid in members]
            block_rows.append({
                "block_id": block_id,
                "blueprint_path": first_node.get("blueprint_path", ""),
                "graph_id": graph_id,
                "graph_name": first_node.get("graph_name", ""),
                "block_index": block_index[block_id],
                "entry_node_id": members[0] if members else "",
                "exit_node_id": members[-1] if members else "",
                "node_count": len(members),
                "node_ids": members,
                "operations": ops,
                "labels": labels,
                "text": " -> ".join(f"{op}:{label}" if label else op for op, label in zip(ops, labels)),
            })

        seen_block_edges: set[tuple[str, str, str, str]] = set()
        for edge in graph_edges:
            source_node = str(edge.get("source_node_id", ""))
            target_node = str(edge.get("target_node_id", ""))
            source_block = block_for_node.get(source_node, "")
            target_block = block_for_node.get(target_node, "")
            if not source_block or not target_block or source_block == target_block:
                continue
            key = (source_block, target_block, str(edge.get("source_pin_name", "")), str(edge.get("target_pin_name", "")))
            if key in seen_block_edges:
                continue
            seen_block_edges.add(key)
            digest = hashlib.sha1(("|".join(key)).encode("utf-8")).hexdigest()[:20]
            source = nodes.get(source_node, {})
            edge_rows.append({
                "edge_id": f"block_edge:{digest}",
                "blueprint_path": source.get("blueprint_path", ""),
                "graph_id": graph_id,
                "source_block_id": source_block,
                "target_block_id": target_block,
                "source_node_id": source_node,
                "target_node_id": target_node,
                "source_pin_name": edge.get("source_pin_name", ""),
                "target_pin_name": edge.get("target_pin_name", ""),
            })

        for root_node in graph_roots:
            root_kind, root_name = root_meta[root_node]
            block_id = block_for_node.get(root_node, "")
            digest = hashlib.sha1(f"{graph_id}|{root_node}".encode("utf-8")).hexdigest()[:20]
            node = nodes.get(root_node, {})
            root_rows.append({
                "root_id": f"exec_root:{digest}",
                "blueprint_path": node.get("blueprint_path", ""),
                "graph_id": graph_id,
                "graph_name": node.get("graph_name", ""),
                "root_node_id": root_node,
                "root_kind": root_kind,
                "root_name": root_name,
                "block_id": block_id,
            })

    return block_rows, edge_rows, root_rows


def derive_anim_state_machines(output: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """Normalize AnimBP state machines, states/aliases/conduits, and transitions."""
    graphs = list(iter_blueprint_graph_rows(output))
    graph_by_path = {str(g.get("graph_path", "")): g for g in graphs}
    nodes = list(iter_jsonl(output / "blueprint_nodes.jsonl"))
    nodes_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    for node in nodes:
        nodes_by_graph[str(node.get("graph_id", ""))].append(node)

    machine_rows: list[dict] = []
    state_rows: list[dict] = []
    transition_rows: list[dict] = []
    state_id_by_graph_name: dict[tuple[str, str], str] = {}

    state_ops = {"anim_state": "state", "anim_conduit": "conduit", "anim_state_alias": "alias"}
    for node in nodes:
        op = str(node.get("operation", ""))
        if op not in state_ops:
            continue
        sem = node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {}
        if op == "anim_state":
            name = str(sem.get("state_name", "") or node.get("symbol", ""))
            bound_graph = str(sem.get("bound_graph", ""))
        elif op == "anim_conduit":
            name = str(sem.get("conduit_name", "") or node.get("symbol", ""))
            bound_graph = str(sem.get("bound_graph", ""))
        else:
            name = str(sem.get("alias_name", "") or node.get("symbol", ""))
            bound_graph = ""
        state_id = str(node.get("node_id", ""))
        state_id_by_graph_name[(str(node.get("graph_id", "")), name)] = state_id
        state_rows.append({
            "state_id": state_id,
            "blueprint_path": node.get("blueprint_path", ""),
            "machine_graph_id": node.get("graph_id", ""),
            "machine_name": node.get("graph_name", ""),
            "state_kind": state_ops[op],
            "name": name,
            "bound_graph": bound_graph,
            "always_reset_on_entry": bool(sem.get("always_reset_on_entry", False)),
            "state_type": int(sem.get("state_type", 0) or 0),
            "global_alias": bool(sem.get("global_alias", False)),
            "aliased_states": sem.get("aliased_states", []) if isinstance(sem.get("aliased_states", []), list) else [],
        })

    for node in nodes:
        if node.get("operation") != "anim_transition":
            continue
        sem = node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {}
        graph_id = str(node.get("graph_id", ""))
        previous = str(sem.get("previous_state", ""))
        nxt = str(sem.get("next_state", ""))
        transition_rows.append({
            "transition_id": node.get("node_id", ""),
            "blueprint_path": node.get("blueprint_path", ""),
            "machine_graph_id": graph_id,
            "machine_name": node.get("graph_name", ""),
            "previous_state": previous,
            "previous_state_id": state_id_by_graph_name.get((graph_id, previous), ""),
            "next_state": nxt,
            "next_state_id": state_id_by_graph_name.get((graph_id, nxt), ""),
            "bidirectional": bool(sem.get("bidirectional", False)),
            "disabled": bool(sem.get("disabled", False)),
            "automatic_rule": bool(sem.get("automatic_rule", False)),
            "automatic_rule_trigger_time": sem.get("automatic_rule_trigger_time", -1),
            "crossfade_duration": sem.get("crossfade_duration", 0),
            "priority_order": int(sem.get("priority_order", 0) or 0),
            "logic_type": int(sem.get("logic_type", 0) or 0),
            "min_time_before_reentry": sem.get("min_time_before_reentry", -1),
            "only_evaluate_when_active": bool(sem.get("only_evaluate_when_active", False)),
            "shared_rules": bool(sem.get("shared_rules", False)),
            "shared_rules_name": sem.get("shared_rules_name", ""),
            "shared_crossfade": bool(sem.get("shared_crossfade", False)),
            "shared_crossfade_name": sem.get("shared_crossfade_name", ""),
            "rule_graph": sem.get("rule_graph", ""),
            "custom_transition_graph": sem.get("custom_transition_graph", ""),
        })

    for node in nodes:
        if node.get("operation") != "anim_state_machine":
            continue
        sem = node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {}
        editor_graph = str(sem.get("editor_state_machine_graph", ""))
        machine_graph = graph_by_path.get(editor_graph, {})
        machine_graph_id = str(machine_graph.get("graph_id", ""))
        entry_nodes = [n for n in nodes_by_graph.get(machine_graph_id, []) if n.get("operation") == "anim_state_entry"]
        entry = entry_nodes[0] if entry_nodes else {}
        entry_sem = entry.get("semantic", {}) if isinstance(entry.get("semantic"), dict) else {}
        entry_name = str(entry_sem.get("target_state", "") or entry.get("symbol", ""))
        machine_rows.append({
            "machine_id": node.get("node_id", ""),
            "blueprint_path": node.get("blueprint_path", ""),
            "host_graph_id": node.get("graph_id", ""),
            "host_graph_name": node.get("graph_name", ""),
            "name": sem.get("state_machine_name", "") or node.get("symbol", ""),
            "editor_graph_path": editor_graph,
            "machine_graph_id": machine_graph_id,
            "entry_node_id": entry.get("node_id", ""),
            "entry_state": entry_name,
            "entry_state_id": state_id_by_graph_name.get((machine_graph_id, entry_name), ""),
            "state_count": sum(1 for r in state_rows if r.get("machine_graph_id") == machine_graph_id),
            "transition_count": sum(1 for r in transition_rows if r.get("machine_graph_id") == machine_graph_id),
        })

    return machine_rows, state_rows, transition_rows

def _relation_id(parts: tuple[str, ...]) -> str:
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"rel:{digest}"


def derive_blueprint_relations(
    output: Path,
    rigvm_links: list[dict],
    functions: list[dict] | None = None,
    events: list[dict] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    seen: set[tuple[str, ...]] = set()
    node_graph: dict[str, str] = {}
    for node in iter_jsonl(output / "blueprint_nodes.jsonl"):
        node_graph.setdefault(node.get("node_id", ""), node.get("graph_id", ""))

    def add(blueprint: str, graph_id: str, source_kind: str, source_id: str,
            relation: str, target_kind: str, target: str, owner: str = "", detail: dict | None = None) -> None:
        if not source_id or not relation or not target:
            return
        key = (blueprint, graph_id, source_kind, source_id, relation, target_kind, target, owner)
        if key in seen:
            return
        seen.add(key)
        rows.append({
            "relation_id": _relation_id(key),
            "blueprint_path": blueprint,
            "graph_id": graph_id,
            "source_kind": source_kind,
            "source_id": source_id,
            "relation": relation,
            "target_kind": target_kind,
            "target": target,
            "owner": owner,
            "detail": detail or {},
        })

    for bp in iter_jsonl(output / "blueprints.jsonl"):
        bp_path = bp.get("object_path", "")
        for var in bp.get("variables", []):
            add(bp_path, "", "blueprint", bp_path, "declares_variable", "variable", var.get("name", ""))
        for comp in bp.get("components", []):
            add(bp_path, "", "blueprint", bp_path, "owns_component", "component", comp.get("variable_name", ""), comp.get("component_class", ""))
        for interface in bp.get("implemented_interfaces", []):
            if isinstance(interface, dict):
                target = interface.get("interface_class", "") or interface.get("class", "") or interface.get("name", "")
            else:
                target = str(interface)
            add(bp_path, "", "blueprint", bp_path, "implements_interface", "class", target)

    for node in iter_jsonl(output / "blueprint_nodes.jsonl"):
        bp = node.get("blueprint_path", "")
        gid = node.get("graph_id", "")
        nid = node.get("node_id", "")
        op = _effective_blueprint_operation(node)
        sem = node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {}
        symbol = str(node.get("symbol", ""))
        owner = str(node.get("owner", ""))
        if op == "function_call":
            add(bp, gid, "node", nid, "calls_interface_function" if sem.get("interface_call") else "calls_function", "function", sem.get("resolved_function", "") or symbol, owner)
        elif op == "variable_get":
            add(bp, gid, "node", nid, "reads_variable", "variable", symbol, sem.get("variable_source_class", "") or owner)
        elif op == "variable_set":
            add(bp, gid, "node", nid, "writes_variable", "variable", symbol, sem.get("variable_source_class", "") or owner)
        elif op == "variable_reference":
            add(bp, gid, "node", nid, "references_variable", "variable", symbol, owner)
        elif op == "macro_instance":
            add(bp, gid, "node", nid, "invokes_macro", "graph", sem.get("macro_graph", "") or symbol, sem.get("source_blueprint", "") or owner)
        elif op == "dynamic_cast":
            add(bp, gid, "node", nid, "casts_to", "class", sem.get("target_class", "") or symbol)
        elif op == "property_access":
            add(bp, gid, "node", nid, "accesses_property_path", "property_path", sem.get("access_path", "") or symbol)
        elif op in {"delegate_bind", "delegate_assign"}:
            add(bp, gid, "node", nid, "binds_delegate", "delegate", sem.get("delegate_name", "") or symbol, sem.get("delegate_owner", "") or owner)
        elif op == "delegate_unbind":
            add(bp, gid, "node", nid, "unbinds_delegate", "delegate", sem.get("delegate_name", "") or symbol, sem.get("delegate_owner", "") or owner)
        elif op == "delegate_clear":
            add(bp, gid, "node", nid, "clears_delegate", "delegate", sem.get("delegate_name", "") or symbol, sem.get("delegate_owner", "") or owner)
        elif op == "delegate_call":
            add(bp, gid, "node", nid, "calls_delegate", "delegate", sem.get("delegate_name", "") or symbol, sem.get("delegate_owner", "") or owner)
        elif op == "delegate_create":
            add(
                bp, gid, "node", nid, "creates_delegate", "function",
                sem.get("selected_function_path", "") or sem.get("selected_function", "") or symbol,
                sem.get("selected_function_owner", ""),
            )
        elif op == "anim_transition":
            add(bp, gid, "node", nid, "transitions_to_state", "anim_state", sem.get("next_state", ""), detail={"previous_state": sem.get("previous_state", "")})
        elif op == "anim_save_cached_pose":
            add(bp, gid, "node", nid, "defines_cached_pose", "cached_pose", sem.get("cache_name", "") or symbol)
        elif op == "anim_use_cached_pose":
            add(bp, gid, "node", nid, "uses_cached_pose", "cached_pose", sem.get("cache_name", "") or symbol, detail={"save_node_guid": sem.get("save_node_guid", "")})
        elif op == "anim_linked_layer":
            add(bp, gid, "node", nid, "links_anim_layer", "anim_layer", sem.get("layer_name", "") or symbol)
        elif op == "anim_linked_graph":
            add(bp, gid, "node", nid, "links_anim_graph", "function", sem.get("function_name", "") or symbol)

        asset_keys = (
            "animation_asset", "blend_space", "pose_asset", "mirror_data_table",
            "rig_definition_asset", "control_rig_class", "data_table", "chooser_asset",
            "proxy_asset", "physics_asset", "physics_control_asset", "blend_profile",
        )
        for key in asset_keys:
            value = sem.get(key)
            if isinstance(value, str) and value:
                add(bp, gid, "node", nid, "uses_asset", "object", value, detail={"semantic_key": key})
        for fn_key in ("initial_update_function", "become_relevant_function", "update_function"):
            value = sem.get(fn_key)
            if isinstance(value, str) and value:
                add(bp, gid, "node", nid, fn_key.replace("_function", "_callback"), "function", value)

    for function in functions or []:
        add(
            function.get("blueprint_path", ""),
            function.get("graph_id", ""),
            "blueprint",
            function.get("blueprint_path", ""),
            "defines_function",
            "function",
            function.get("name", ""),
            function.get("owner", ""),
            {
                "function_id": function.get("function_id", ""),
                "inputs": function.get("inputs", []),
                "outputs": function.get("outputs", []),
                "has_exec": function.get("has_exec", False),
            },
        )

    for event in events or []:
        event_kind = event.get("event_kind", "")
        if event_kind == "component_bound":
            component = event.get("component_name", "")
            delegate = event.get("delegate_name", "")
            target = f"{component}.{delegate}" if component and delegate else (delegate or component)
            add(
                event.get("blueprint_path", ""), event.get("graph_id", ""), "node", event.get("event_id", ""),
                "handles_delegate", "delegate", target, event.get("delegate_owner", ""),
                {"component": component, "delegate": delegate, "parameters": event.get("parameters", [])},
            )
        elif event_kind in {"enhanced_input", "input_action", "input_axis", "input_key"}:
            add(
                event.get("blueprint_path", ""), event.get("graph_id", ""), "node", event.get("event_id", ""),
                "handles_input", "input", event.get("input_name", "") or event.get("name", ""),
                detail={"event_kind": event_kind, "parameters": event.get("parameters", [])},
            )
        elif event_kind in {"custom", "override", "event"}:
            add(
                event.get("blueprint_path", ""), event.get("graph_id", ""), "node", event.get("event_id", ""),
                "defines_event", "event", event.get("name", ""), event.get("owner", ""),
                {"event_kind": event_kind, "parameters": event.get("parameters", [])},
            )

    for ref in iter_jsonl(output / "blueprint_node_references.jsonl"):
        if ref.get("node_owned"):
            continue
        add(ref.get("blueprint_path", ""), node_graph.get(ref.get("node_id", ""), ""), "node", ref.get("node_id", ""), "references_object", "object", ref.get("target_object_path", ""), ref.get("target_class", ""), {"property_path": ref.get("property_path", "")})

    for pin in iter_blueprint_pin_rows(output):
        default_object = pin.get("default_object", "")
        if default_object:
            add(pin.get("blueprint_path", ""), pin.get("graph_id", ""), "node", pin.get("node_id", ""), "pin_default_object", "object", default_object, detail={"pin": pin.get("name", "")})

    for binding in iter_jsonl(output / "blueprint_bindings.jsonl"):
        target = binding.get("access_path", "")
        if target:
            add(binding.get("blueprint_path", ""), node_graph.get(binding.get("node_id", ""), ""), "node", binding.get("node_id", ""), "binds_property_path", "property_path", target, detail={"target_property": binding.get("target_property", "")})

    for default in iter_jsonl(output / "blueprint_defaults.jsonl"):
        obj = default.get("referenced_object_path", "")
        if obj:
            add(default.get("blueprint_path", ""), "", "blueprint", default.get("blueprint_path", ""), "default_references_object", "object", obj, default.get("referenced_object_class", ""), {"property": default.get("property_name", "")})

    for prop in iter_jsonl(output / "blueprint_component_properties.jsonl"):
        source_id = f"{prop.get('blueprint_path','')}::component::{prop.get('component_name','')}"
        obj = prop.get("referenced_object_path", "")
        if obj:
            add(prop.get("blueprint_path", ""), "", "component", source_id, "override_references_object", "object", obj, prop.get("referenced_object_class", ""), {"property": prop.get("property_name", "")})

    for timeline in iter_jsonl(output / "blueprint_timelines.jsonl"):
        source_id = timeline.get("timeline_path", "")
        if timeline.get("update_function"):
            add(timeline.get("blueprint_path", ""), "", "timeline", source_id, "calls_update_function", "function", timeline.get("update_function", ""))
        if timeline.get("finished_function"):
            add(timeline.get("blueprint_path", ""), "", "timeline", source_id, "calls_finished_function", "function", timeline.get("finished_function", ""))
    for track in iter_jsonl(output / "blueprint_timeline_tracks.jsonl"):
        source_id = track.get("timeline_path", "")
        if track.get("curve_path"):
            add(track.get("blueprint_path", ""), "", "timeline", source_id, "uses_curve", "object", track.get("curve_path", ""), track.get("curve_class", ""), {"track": track.get("track_name", ""), "type": track.get("track_type", "")})
        if track.get("function_name"):
            add(track.get("blueprint_path", ""), "", "timeline", source_id, "calls_track_function", "function", track.get("function_name", ""), detail={"track": track.get("track_name", "")})

    for widget in iter_jsonl(output / "blueprint_widgets.jsonl"):
        if widget.get("parent_widget_path"):
            add(widget.get("blueprint_path", ""), "", "widget", widget.get("widget_path", ""), "parent_widget", "widget", widget.get("parent_widget_path", ""))
    for binding in iter_jsonl(output / "blueprint_widget_bindings.jsonl"):
        source_id = f"{binding.get('blueprint_path','')}::widget_binding::{binding.get('binding_index',0)}"
        target = binding.get("function_name", "") or binding.get("source_path", "") or binding.get("source_property", "")
        if target:
            add(binding.get("blueprint_path", ""), "", "widget_binding", source_id, "binds_to", "function" if binding.get("function_name") else "property_path", target, detail={"widget": binding.get("object_name", ""), "property": binding.get("property_name", "")})

    for state in iter_jsonl(output / "blueprint_state_values.jsonl"):
        obj = state.get("referenced_object_path", "")
        if obj:
            add(
                state.get("blueprint_path", ""), "", state.get("owner_kind", "state"), state.get("owner_id", ""),
                "state_references_object", "object", obj, state.get("referenced_object_class", ""),
                {"property_path": state.get("property_path", "")},
            )

    for prop in iter_jsonl(output / "blueprint_widget_properties.jsonl"):
        obj = prop.get("referenced_object_path", "")
        if obj:
            add(
                prop.get("blueprint_path", ""), "", prop.get("owner_kind", "widget"), prop.get("owner_id", ""),
                "widget_references_object", "object", obj, prop.get("referenced_object_class", ""),
                {"property_path": prop.get("property_path", "")},
            )

    for binding in iter_jsonl(output / "blueprint_widget_animation_bindings.jsonl"):
        source = binding.get("animation_path", "")
        widget = binding.get("widget_name", "")
        if widget:
            add(
                binding.get("blueprint_path", ""), "", "widget_animation", source,
                "animates_widget", "widget", widget, detail={
                    "slot_widget": binding.get("slot_widget_name", ""),
                    "animation_guid": binding.get("animation_guid", ""),
                    "is_root_widget": binding.get("is_root_widget", ""),
                },
            )

    for link in rigvm_links:
        if link.get("status") == "matched":
            add(link.get("blueprint_path", ""), link.get("graph_id", ""), "node", link.get("node_id", ""), "maps_to_rigvm_node", "rigvm_node", link.get("rigvm_object_id", ""), link.get("rigvm_class", ""), {"operation": link.get("rigvm_operation", ""), "confidence": link.get("confidence", "")})

    return rows


def _compact_semantic(semantic: dict) -> str:
    if not semantic:
        return ""
    preferred = (
        "target_class", "resolved_function", "function_name", "access_path", "delegate_name",
        "macro_graph", "previous_state", "next_state", "cache_name", "layer_name",
        "animation_asset", "blend_space", "pose_asset", "mirror_data_table", "rig_definition_asset",
        "data_table", "row_name", "chooser_asset", "proxy_asset", "update_function",
        "become_relevant_function", "initial_update_function",
    )
    parts = []
    for key in preferred:
        value = semantic.get(key)
        if value not in (None, "", [], {}):
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            parts.append(f"{key}={value}")
    return "; ".join(parts[:8])


def derive_graph_context(
    output: Path,
    rigvm_links: list[dict],
    functions: list[dict] | None = None,
    events: list[dict] | None = None,
    max_chars: int = 524288,
) -> list[dict]:
    rig_by_node = {row.get("node_id", ""): row for row in rigvm_links if row.get("status") == "matched"}
    function_by_graph = {row.get("graph_id", ""): row for row in (functions or [])}
    event_by_node = {row.get("event_id", ""): row for row in (events or [])}
    rig_pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for pin in iter_jsonl(output / "rigvm_pins.jsonl"):
        rig_pins_by_node[pin.get("outer_object_id", "")].append(pin)
    nodes_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    seen_node_ids: set[str] = set()
    for row in iter_jsonl(output / "blueprint_nodes.jsonl"):
        copy = dict(row)
        copy.pop("pins", None)
        node_id = copy.get("node_id", "")
        if node_id in seen_node_ids:
            continue
        seen_node_ids.add(node_id)
        nodes_by_graph[copy.get("graph_id", "")].append(copy)
    pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for row in iter_blueprint_pin_rows(output):
        pins_by_node[row.get("node_id", "")].append(row)
    edges_by_graph: dict[str, list[dict]] = collections.defaultdict(list)
    for row in iter_jsonl(output / "blueprint_edges.jsonl"):
        edges_by_graph[row.get("graph_id", "")].append(row)

    out: list[dict] = []
    for graph in iter_blueprint_graph_rows(output):
        gid = graph.get("graph_id", "")
        nodes = nodes_by_graph.get(gid, [])
        aliases = {node.get("node_id", ""): f"n{i}" for i, node in enumerate(nodes)}
        lines = [
            f"Blueprint: {graph.get('blueprint_path','')}",
            f"Graph: {graph.get('graph_name','')} [{graph.get('graph_system','')}/{graph.get('graph_kind','')}]",
            f"Path: {graph.get('graph_path','')}",
        ]
        function = function_by_graph.get(gid)
        if function:
            def fmt_params(values: list[dict]) -> str:
                return ", ".join(
                    f"{p.get('name','')}:{p.get('type',{}).get('category','')}"
                    for p in values
                )
            lines.append(
                f"Function: {function.get('name','')}({fmt_params(function.get('inputs', []))})"
                + (f" -> ({fmt_params(function.get('outputs', []))})" if function.get('outputs') else "")
                + f" | exec={function.get('has_exec', False)} | locals={len(function.get('locals', []))}"
            )
        lines.append("Nodes:")
        for node in nodes:
            nid = node.get("node_id", "")
            label = node.get("symbol", "") or node.get("title", "")
            line = f"  {aliases[nid]} {_effective_blueprint_operation(node)} {label}".rstrip()
            event = event_by_node.get(nid)
            if event:
                if event.get("event_kind") == "component_bound":
                    line += f" | event={event.get('component_name','')}.{event.get('delegate_name','')}"
                    if event.get("delegate_owner"):
                        line += f" owner={event.get('delegate_owner','')}"
                elif event.get("input_name"):
                    line += f" | event={event.get('event_kind','')}:{event.get('input_name','')}"
                else:
                    line += f" | event={event.get('event_kind','')}:{event.get('name','')}"
            sem_text = _compact_semantic(node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {})
            if sem_text:
                line += f" | {sem_text}"
            rig = rig_by_node.get(nid)
            if rig:
                rig_bits = [rig.get("rigvm_operation", ""), rig.get("resolved_function_name", ""), rig.get("template_notation", "")]
                line += " | RigVM=" + " | ".join(bit for bit in rig_bits if bit)
                rig_defaults = []
                for rpin in rig_pins_by_node.get(rig.get("rigvm_object_id", ""), []):
                    direction = str(rpin.get("direction", "")).lower()
                    if "input" not in direction and direction not in {"", "0", "io"}:
                        continue
                    value = rpin.get("default_value_object", "") or rpin.get("default_value", "")
                    if value not in (None, ""):
                        rig_defaults.append(f"{rpin.get('name','')}={value}")
                if rig_defaults:
                    line += " | RigDefaults: " + ", ".join(rig_defaults[:10])
            defaults = []
            for pin in pins_by_node.get(nid, []):
                if pin.get("direction") not in ("input", "EGPD_Input", "0"):
                    continue
                if int(pin.get("linked_count", 0)) > 0:
                    continue
                value = pin.get("default_object", "") or pin.get("default_value", "") or pin.get("default_text", "")
                if value:
                    defaults.append(f"{pin.get('name','')}={value}")
            if defaults:
                line += " | defaults: " + ", ".join(defaults[:8])
            lines.append(line)
        execution = []
        data = []
        for edge in edges_by_graph.get(gid, []):
            src = aliases.get(edge.get("source_node_id", ""), "?")
            dst = aliases.get(edge.get("target_node_id", ""), "?")
            text = f"  {src}.{edge.get('source_pin_name','')} -> {dst}.{edge.get('target_pin_name','')}"
            (execution if edge.get("edge_kind") == "execution" else data).append(text)
        if execution:
            lines.append("Execution flow:")
            lines.extend(execution)
        if data:
            lines.append("Data flow:")
            lines.extend(data)
        text = "\n".join(lines)
        truncated = len(text) > max_chars
        if truncated:
            text = text[:max_chars] + "\n...[truncated]"
        out.append({
            "graph_id": gid,
            "blueprint_path": graph.get("blueprint_path", ""),
            "graph_name": graph.get("graph_name", ""),
            "graph_path": graph.get("graph_path", ""),
            "graph_kind": graph.get("graph_kind", ""),
            "graph_system": graph.get("graph_system", ""),
            "node_count": len(nodes),
            "execution_edge_count": len(execution),
            "data_edge_count": len(data),
            "truncated": truncated,
            "text": text,
        })
    return out


def derive_blueprint_summaries(
    output: Path,
    relations: list[dict],
    functions: list[dict] | None = None,
    events: list[dict] | None = None,
) -> list[dict]:
    graphs_by_bp: dict[str, list[dict]] = collections.defaultdict(list)
    for graph in iter_blueprint_graph_rows(output):
        graphs_by_bp[graph.get("blueprint_path", "")].append(graph)
    ops_by_bp: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    seen_nodes: set[str] = set()
    for node in iter_jsonl(output / "blueprint_nodes.jsonl"):
        node_id = node.get("node_id", "")
        if node_id in seen_nodes:
            continue
        seen_nodes.add(node_id)
        ops_by_bp[node.get("blueprint_path", "")][_effective_blueprint_operation(node)] += 1
    rel_by_bp: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for rel in relations:
        rel_by_bp[rel.get("blueprint_path", "")][rel.get("relation", "")] += 1

    function_counts = collections.Counter(row.get("blueprint_path", "") for row in (functions or []))
    pure_function_counts = collections.Counter(
        row.get("blueprint_path", "") for row in (functions or []) if row.get("blueprint_pure", False)
    )
    event_counts = collections.Counter(row.get("blueprint_path", "") for row in (events or []))
    stream_counts: dict[str, collections.Counter] = {}
    for filename, key in (
        ("blueprint_defaults.jsonl", "default_count"),
        ("blueprint_component_properties.jsonl", "component_override_count"),
        ("blueprint_state_values.jsonl", "state_value_count"),
        ("blueprint_timelines.jsonl", "timeline_count"),
        ("blueprint_timeline_tracks.jsonl", "timeline_track_count"),
        ("blueprint_timeline_keys.jsonl", "timeline_key_count"),
        ("blueprint_widgets.jsonl", "widget_count"),
        ("blueprint_widget_properties.jsonl", "widget_property_count"),
        ("blueprint_widget_bindings.jsonl", "widget_binding_count"),
        ("blueprint_widget_animations.jsonl", "widget_animation_count"),
        ("blueprint_widget_animation_bindings.jsonl", "widget_animation_binding_count"),
    ):
        stream_counts[key] = collections.Counter(row.get("blueprint_path", "") for row in iter_jsonl(output / filename))

    out = []
    for bp in iter_jsonl(output / "blueprints.jsonl"):
        path = bp.get("object_path", "")
        graphs = graphs_by_bp.get(path, [])
        variables = [v.get("name", "") for v in bp.get("variables", [])]
        components = [c.get("variable_name", "") for c in bp.get("components", [])]
        interfaces = []
        for i in bp.get("implemented_interfaces", []):
            interfaces.append(str(i.get("interface_class", "") if isinstance(i, dict) else i))
        op_counts = ops_by_bp.get(path, collections.Counter())
        graph_systems = collections.Counter(g.get("graph_system", "") for g in graphs)
        text = "\n".join([
            f"Blueprint: {path}",
            f"Parent: {bp.get('parent_class','')}",
            f"Generated class: {bp.get('generated_class','')}",
            f"Variables ({len(variables)}): {', '.join(variables[:80])}",
            f"Components ({len(components)}): {', '.join(components[:80])}",
            f"Interfaces ({len(interfaces)}): {', '.join(interfaces[:40])}",
            f"Functions: {function_counts[path]} ({pure_function_counts[path]} pure) | Events: {event_counts[path]} | Defaults: {stream_counts['default_count'][path]} | Component overrides: {stream_counts['component_override_count'][path]}",
            f"Timelines: {stream_counts['timeline_count'][path]} ({stream_counts['timeline_key_count'][path]} keys) | Widgets: {stream_counts['widget_count'][path]} ({stream_counts['widget_property_count'][path]} changed properties)",
            "Graphs: " + ", ".join(f"{g.get('graph_name','')}[{g.get('graph_system','')}/{g.get('graph_kind','')}]" for g in graphs[:120]),
            "Operations: " + ", ".join(f"{k}={v}" for k, v in op_counts.most_common(60)),
            "Relations: " + ", ".join(f"{k}={v}" for k, v in rel_by_bp.get(path, collections.Counter()).most_common(40)),
        ])
        out.append({
            "blueprint_path": path,
            "name": bp.get("name", ""),
            "parent_class": bp.get("parent_class", ""),
            "generated_class": bp.get("generated_class", ""),
            "variable_count": len(variables),
            "component_count": len(components),
            "interface_count": len(interfaces),
            "function_count": function_counts[path],
            "event_count": event_counts[path],
            "default_count": stream_counts["default_count"][path],
            "component_override_count": stream_counts["component_override_count"][path],
            "state_value_count": stream_counts["state_value_count"][path],
            "timeline_count": stream_counts["timeline_count"][path],
            "timeline_track_count": stream_counts["timeline_track_count"][path],
            "timeline_key_count": stream_counts["timeline_key_count"][path],
            "widget_count": stream_counts["widget_count"][path],
            "widget_property_count": stream_counts["widget_property_count"][path],
            "widget_binding_count": stream_counts["widget_binding_count"][path],
            "widget_animation_count": stream_counts["widget_animation_count"][path],
            "widget_animation_binding_count": stream_counts["widget_animation_binding_count"][path],
            "graph_count": len(graphs),
            "graph_system_counts": dict(graph_systems),
            "operation_counts": dict(op_counts),
            "relation_counts": dict(rel_by_bp.get(path, collections.Counter())),
            "text": text[:524288],
        })
    return out



def _ai_relation(asset_path: str, system: str, source_kind: str, source_id: str, relation: str,
                 target_kind: str, target: str, detail: dict | None = None) -> dict:
    basis = "|".join((asset_path, system, source_kind, source_id, relation, target_kind, target, json.dumps(detail or {}, sort_keys=True)))
    return {
        "relation_id": hashlib.sha1(basis.encode("utf-8")).hexdigest(),
        "asset_path": asset_path,
        "system": system,
        "source_kind": source_kind,
        "source_id": source_id,
        "relation": relation,
        "target_kind": target_kind,
        "target": target,
        "detail": detail or {},
    }


_EMPTY_GUID = "00000000000000000000000000000000"


def _statetree_node_is_empty(row: dict) -> bool:
    raw_node = str(row.get("raw_node", "") or "")
    raw_instance = str(row.get("raw_instance", "") or "")
    return (
        not row.get("instance_object_path")
        and not row.get("instance_object_class")
        and raw_node in ("", "None")
        and raw_instance in ("", "None")
    )


def _extract_unreal_assignment(text: str, field: str) -> str:
    if not text:
        return ""
    needle = field + "="
    start = text.find(needle)
    if start < 0:
        return ""
    i = start + len(needle)
    while i < len(text) and text[i].isspace():
        i += 1
    if i >= len(text):
        return ""

    if text[i] == '"':
        j = i + 1
        escaped = False
        while j < len(text):
            ch = text[j]
            if ch == '"' and not escaped:
                return text[i:j + 1]
            if ch == "\\" and not escaped:
                escaped = True
            else:
                escaped = False
            j += 1
        return text[i:]

    if text[i] == "(":
        depth = 0
        in_quote = False
        escaped = False
        j = i
        while j < len(text):
            ch = text[j]
            if in_quote:
                if ch == '"' and not escaped:
                    in_quote = False
                if ch == "\\" and not escaped:
                    escaped = True
                else:
                    escaped = False
            else:
                if ch == '"':
                    in_quote = True
                elif ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        return text[i:j + 1]
            j += 1
        return text[i:]

    j = i
    while j < len(text) and text[j] not in ",)":
        j += 1
    return text[i:j].strip()


def _normalize_statetree_binding_row(row: dict) -> dict:
    normalized = dict(row)
    raw = str(row.get("raw_value", "") or "")
    source = _extract_unreal_assignment(raw, "SourcePropertyPath")
    target = _extract_unreal_assignment(raw, "TargetPropertyPath")
    if source:
        normalized["source_path"] = source
    if target:
        normalized["target_path"] = target
    return normalized


def _property_path_detail(path: str) -> dict:
    struct_match = re.search(r"StructID=([0-9A-Fa-f]{32})", path or "")
    segments = re.findall(r'(?:^|[\(,])Name="([^"]+)"', path or "")
    return {
        "struct_id": struct_match.group(1) if struct_match else "",
        "segments": segments,
    }


def _object_path_from_export(value: str) -> str:
    match = re.search(r"'([^']+)'", value or "")
    return match.group(1) if match else ""


def derive_ai_relations(output: Path) -> list[dict]:
    relations: list[dict] = []
    generated_to_bp: dict[str, str] = {}
    asset_classes: dict[str, str] = {}
    for bp in iter_jsonl(output / "blueprints.jsonl"):
        gc = bp.get("generated_class", "")
        if gc:
            generated_to_bp[gc] = bp.get("object_path", bp.get("blueprint_path", ""))
    for asset in iter_jsonl(output / "assets.jsonl"):
        asset_classes[asset.get("object_path", "")] = asset.get("class_path", "")

    tree_blackboard = {
        row.get("behavior_tree_path", ""): row.get("blackboard_path", "")
        for row in iter_jsonl(output / "behavior_trees.jsonl")
    }
    bb_parent = {
        row.get("blackboard_path", ""): row.get("parent_blackboard_path", "")
        for row in iter_jsonl(output / "blackboards.jsonl")
    }
    bb_key_lookup: dict[tuple[str, str], str] = {}
    for key in iter_jsonl(output / "blackboard_keys.jsonl"):
        bb_key_lookup[(key.get("blackboard_path", ""), key.get("name", ""))] = key.get("key_id", "")

    def resolve_blackboard_key(blackboard: str, key_name: str) -> tuple[str, str]:
        seen: set[str] = set()
        current = blackboard
        while current and current not in seen:
            seen.add(current)
            key_id = bb_key_lookup.get((current, key_name), "")
            if key_id:
                return key_id, current
            current = bb_parent.get(current, "")
        return "", ""

    for tree in iter_jsonl(output / "behavior_trees.jsonl"):
        asset = tree.get("behavior_tree_path", "")
        bb = tree.get("blackboard_path", "")
        if bb:
            relations.append(_ai_relation(asset, "behavior_tree", "behavior_tree", asset, "uses_blackboard", "blackboard", bb))
        root = tree.get("root_node_id", "")
        if root:
            relations.append(_ai_relation(asset, "behavior_tree", "behavior_tree", asset, "has_root", "behavior_tree_node", root))

    for edge in iter_jsonl(output / "behavior_tree_edges.jsonl"):
        asset = edge.get("behavior_tree_path", "")
        relations.append(_ai_relation(
            asset, "behavior_tree", "behavior_tree_node", edge.get("source_node_id", ""),
            edge.get("edge_kind", "child"), "behavior_tree_node", edge.get("target_node_id", ""),
            {"child_index": edge.get("child_index", -1), "decorator_ids": edge.get("decorator_ids", []),
             "decorator_logic": edge.get("decorator_logic", "")},
        ))

    for node in iter_jsonl(output / "behavior_tree_nodes.jsonl"):
        cls = node.get("class_path", "")
        bp = generated_to_bp.get(cls)
        if bp:
            relations.append(_ai_relation(
                node.get("behavior_tree_path", ""), "behavior_tree", "behavior_tree_node", node.get("node_id", ""),
                "implemented_by_blueprint", "blueprint", bp, {"class": cls},
            ))

    for bb in iter_jsonl(output / "blackboards.jsonl"):
        parent = bb.get("parent_blackboard_path", "")
        if parent:
            relations.append(_ai_relation(
                bb.get("blackboard_path", ""), "blackboard", "blackboard", bb.get("blackboard_path", ""),
                "inherits_blackboard", "blackboard", parent,
            ))
    for key in iter_jsonl(output / "blackboard_keys.jsonl"):
        relations.append(_ai_relation(
            key.get("blackboard_path", ""), "blackboard", "blackboard", key.get("blackboard_path", ""),
            "declares_key", "blackboard_key", key.get("key_id", ""),
            {"name": key.get("name", ""), "type": key.get("key_type_class", "")},
        ))

    for opt in iter_jsonl(output / "eqs_options.jsonl"):
        asset = opt.get("eqs_path", "")
        relations.append(_ai_relation(
            asset, "eqs", "eqs_query", asset, "has_option", "eqs_option", opt.get("option_id", ""),
            {"option_index": opt.get("option_index", 0)},
        ))
        if opt.get("generator_id"):
            relations.append(_ai_relation(
                asset, "eqs", "eqs_option", opt.get("option_id", ""),
                "uses_generator", "eqs_generator", opt.get("generator_id", ""),
            ))
    for test in iter_jsonl(output / "eqs_tests.jsonl"):
        relations.append(_ai_relation(
            test.get("eqs_path", ""), "eqs", "eqs_option", test.get("option_id", ""),
            "uses_test", "eqs_test", test.get("test_id", ""), {"test_index": test.get("test_index", 0)},
        ))

    for state in iter_jsonl(output / "statetree_states.jsonl"):
        asset = state.get("statetree_path", "")
        sid = state.get("state_id", "")
        parent = state.get("parent_state_id", "")
        if parent:
            relations.append(_ai_relation(
                asset, "statetree", "statetree_state", parent, "has_child_state", "statetree_state", sid,
                {"child_index": state.get("child_index", 0)},
            ))
        else:
            relations.append(_ai_relation(
                asset, "statetree", "statetree", asset, "has_root_state", "statetree_state", sid,
                {"child_index": state.get("child_index", 0)},
            ))
        if state.get("linked_asset"):
            relations.append(_ai_relation(
                asset, "statetree", "statetree_state", sid, "links_statetree", "statetree", state.get("linked_asset", ""),
            ))

    for node in iter_jsonl(output / "statetree_nodes.jsonl"):
        if _statetree_node_is_empty(node):
            continue
        asset = node.get("statetree_path", "")
        sid = node.get("state_id", "")
        relations.append(_ai_relation(
            asset, "statetree", "statetree_state" if sid else "statetree", sid or asset,
            "has_" + node.get("role", "node"), "statetree_node", node.get("node_id", ""),
        ))
        cls = node.get("instance_object_class", "")
        bp = generated_to_bp.get(cls)
        if bp:
            relations.append(_ai_relation(
                asset, "statetree", "statetree_node", node.get("node_id", ""),
                "implemented_by_blueprint", "blueprint", bp, {"class": cls},
            ))

    for tr in iter_jsonl(output / "statetree_transitions.jsonl"):
        asset = tr.get("statetree_path", "")
        transition_id = tr.get("transition_id", "")
        target_spec = tr.get("state", "")
        link_type = _extract_unreal_assignment(target_spec, "LinkType")
        target_name = _extract_unreal_assignment(target_spec, "Name").strip('"')
        target_state_id = _extract_unreal_assignment(target_spec, "ID")
        relations.append(_ai_relation(
            asset, "statetree", "statetree_state", tr.get("source_state_id", ""),
            "has_transition", "statetree_transition", transition_id,
            {"trigger": tr.get("trigger", ""), "target": target_spec, "target_name": target_name,
             "target_state_id": target_state_id, "link_type": link_type, "event_tag": tr.get("event_tag", "")},
        ))
        if target_state_id and target_state_id != _EMPTY_GUID:
            relations.append(_ai_relation(
                asset, "statetree", "statetree_transition", transition_id,
                "transitions_to", "statetree_state", target_state_id,
                {"name": target_name, "link_type": link_type, "trigger": tr.get("trigger", "")},
            ))

    for binding_row in iter_jsonl(output / "statetree_bindings.jsonl"):
        binding = _normalize_statetree_binding_row(binding_row)
        source_path = binding.get("source_path", "")
        target_path = binding.get("target_path", "")
        source_detail = _property_path_detail(source_path)
        target_detail = _property_path_detail(target_path)
        relations.append(_ai_relation(
            binding.get("statetree_path", ""), "statetree", "statetree", binding.get("statetree_path", ""),
            "property_binding", "property_path", target_path,
            {"source_path": source_path, "source_struct_id": source_detail["struct_id"],
             "source_segments": source_detail["segments"], "target_struct_id": target_detail["struct_id"],
             "target_segments": target_detail["segments"], "output_binding": binding.get("output_binding", "")},
        ))

    for prop in iter_jsonl(output / "ai_properties.jsonl"):
        asset = prop.get("asset_path", "")
        target = prop.get("object_path", "")
        if target and target in asset_classes and target != asset:
            cls = asset_classes.get(target, prop.get("object_class", ""))
            skip_generic = (
                (prop.get("system") == "behavior_tree" and target == tree_blackboard.get(asset, ""))
                or (prop.get("system") == "blackboard" and prop.get("property_name") == "Parent")
                or prop.get("property_name") == "LinkedAsset"
            )
            if not skip_generic and any(token in cls for token in ("BehaviorTree", "BlackboardData", "EnvQuery", "StateTree")):
                relations.append(_ai_relation(
                    asset, prop.get("system", ""), prop.get("owner_kind", "ai_object"), prop.get("owner_id", ""),
                    "references_ai_asset", "ai_asset", target,
                    {"property": prop.get("property_name", ""), "class": cls},
                ))

        if prop.get("system") == "behavior_tree":
            value = prop.get("value", "")
            match = re.search(r'SelectedKeyName=(?:"([^"]+)"|([^,\)]+))', value)
            if match:
                key_name = (match.group(1) or match.group(2) or "").strip()
                bb = tree_blackboard.get(asset, "")
                key_id, declaring_bb = resolve_blackboard_key(bb, key_name)
                if key_id:
                    relations.append(_ai_relation(
                        asset, "behavior_tree", prop.get("owner_kind", "behavior_tree_node"), prop.get("owner_id", ""),
                        "references_blackboard_key", "blackboard_key", key_id,
                        {"key_name": key_name, "property": prop.get("property_name", ""),
                         "declaring_blackboard": declaring_bb, "inherited": bool(declaring_bb and declaring_bb != bb)},
                    ))

            if prop.get("property_name") == "EQSRequest" or prop.get("cpp_type") == "FEQSParametrizedQueryExecutionRequest":
                query_export = _extract_unreal_assignment(value, "QueryTemplate")
                query_path = _object_path_from_export(query_export)
                if query_path:
                    relations.append(_ai_relation(
                        asset, "behavior_tree", prop.get("owner_kind", "behavior_tree_node"), prop.get("owner_id", ""),
                        "runs_eqs_query", "eqs_query", query_path, {"property": prop.get("property_name", "")},
                    ))

    ai_asset_paths = {
        path for path, cls in asset_classes.items()
        if any(token in cls for token in ("BehaviorTree", "BlackboardData", "EnvQuery", "StateTree"))
    }
    for bp_rel in iter_jsonl(output / "blueprint_relations.jsonl"):
        target = bp_rel.get("target", "")
        if target in ai_asset_paths:
            bp = bp_rel.get("blueprint_path", "")
            relations.append(_ai_relation(
                target, "cross_system", "blueprint", bp, "references_ai_asset", "ai_asset", target,
                {"blueprint_relation": bp_rel.get("relation", ""), "source_id": bp_rel.get("source_id", "")},
            ))

    return list({r["relation_id"]: r for r in relations}.values())

def derive_ai_summaries(output: Path, relations: list[dict]) -> list[dict]:
    by_asset_rel: dict[str, list[dict]] = collections.defaultdict(list)
    for rel in relations:
        by_asset_rel[rel.get("asset_path", "")].append(rel)
    assets: dict[str, tuple[str, str]] = {}
    for row in iter_jsonl(output / "behavior_trees.jsonl"):
        assets[row.get("behavior_tree_path", "")] = ("behavior_tree", row.get("class_path", ""))
    for row in iter_jsonl(output / "blackboards.jsonl"):
        assets[row.get("blackboard_path", "")] = ("blackboard", row.get("class_path", ""))
    for row in iter_jsonl(output / "eqs_queries.jsonl"):
        assets[row.get("eqs_path", "")] = ("eqs", row.get("class_path", ""))
    for row in iter_jsonl(output / "statetrees.jsonl"):
        assets[row.get("statetree_path", "")] = ("statetree", row.get("class_path", ""))

    node_counts = collections.Counter()
    for row in iter_jsonl(output / "behavior_tree_nodes.jsonl"):
        node_counts[row.get("behavior_tree_path", "")] += 1
    for row in iter_jsonl(output / "eqs_generators.jsonl"):
        node_counts[row.get("eqs_path", "")] += 1
    for row in iter_jsonl(output / "eqs_tests.jsonl"):
        node_counts[row.get("eqs_path", "")] += 1
    for row in iter_jsonl(output / "statetree_states.jsonl"):
        node_counts[row.get("statetree_path", "")] += 1
    for row in iter_jsonl(output / "statetree_nodes.jsonl"):
        if not _statetree_node_is_empty(row):
            node_counts[row.get("statetree_path", "")] += 1

    summaries=[]
    for asset,(system,cls) in sorted(assets.items()):
        rels=by_asset_rel.get(asset,[])
        lines=[f"{system}: {asset}", f"class: {cls}", f"nodes: {node_counts[asset]}", f"relations: {len(rels)}"]
        for rel in rels[:120]:
            lines.append(f"{rel['source_kind']} {rel['source_id']} --{rel['relation']}--> {rel['target_kind']} {rel['target']}")
        summaries.append({"asset_path":asset,"system":system,"asset_class":cls,"node_count":node_counts[asset],
                          "relation_count":len(rels),"text":"\n".join(lines)})
    return summaries


def _extract_unreal_object_paths(text: str) -> list[str]:
    if not text:
        return []
    out = []
    seen = set()
    for match in re.finditer(r"(/[A-Za-z0-9_./-]+\.[A-Za-z0-9_]+)", text):
        value = match.group(1).rstrip("'\")]}>,;")
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _asset_class_maps(output: Path) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    classes = {}
    package_to_object = {}
    for row in iter_jsonl(output / "assets.jsonl"):
        obj = row.get("object_path", "")
        cls = row.get("class_path", "")
        pkg = row.get("package_name", "")
        if obj:
            classes[obj] = cls
        if pkg and obj:
            package_to_object[pkg] = obj
    generated_to_bp = {}
    for row in iter_jsonl(output / "blueprints.jsonl"):
        bp = row.get("object_path", "") or row.get("blueprint_path", "")
        gen = row.get("generated_class", "")
        if bp and gen:
            generated_to_bp[gen] = bp
    return classes, package_to_object, generated_to_bp


def derive_visual(
    output: Path,
    blueprint_relation_rows: list[dict] | None = None,
) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict], list[dict]]:
    classes, package_to_object, generated_to_bp = _asset_class_maps(output)
    relations = []
    seen = set()
    def add(system, asset, sk, sid, rel, tk, target, detail=None):
        if not target:
            return
        key=(system,asset,sk,sid,rel,tk,target,json.dumps(detail or {},sort_keys=True,separators=(",",":")))
        if key in seen:
            return
        seen.add(key)
        relations.append({"relation_id": hashlib.sha1("|".join(map(str,key)).encode()).hexdigest(), "system":system,
                          "asset_path":asset,"source_kind":sk,"source_id":sid,"relation":rel,"target_kind":tk,
                          "target":target,"detail":detail or {}})

    pcg_nodes = list(iter_jsonl(output / "pcg_nodes.jsonl"))
    pcg_pins = list(iter_jsonl(output / "pcg_pins.jsonl"))
    pcg_edges = list(iter_jsonl(output / "pcg_edges.jsonl"))
    pcg_props = list(iter_jsonl(output / "pcg_properties.jsonl"))
    pcg_params=[]
    for g in iter_jsonl(output / "pcg_graphs.jsonl"):
        asset=g.get("pcg_path","")
        if g.get("parent_graph_path"):
            add("pcg",g.get("parent_graph_path",""),"pcg_graph",g.get("parent_graph_path",""),"contains_embedded_graph","pcg_graph",asset)
    for n in pcg_nodes:
        asset=n.get("pcg_path",""); nid=n.get("node_id","")
        add("pcg",asset,"pcg_graph",asset,"contains_node","pcg_node",nid)
        if n.get("settings_path"):
            add("pcg",asset,"pcg_node",nid,"uses_settings","pcg_settings",n["settings_path"],{"class":n.get("settings_class","")})
    pin_by_id={p.get("pin_id",""):p for p in pcg_pins}
    for e in pcg_edges:
        asset=e.get("pcg_path",""); src=e.get("source_node_id",""); dst=e.get("target_node_id","")
        sp=pin_by_id.get(e.get("source_pin_id",""),{}); tp=pin_by_id.get(e.get("target_pin_id",""),{})
        add("pcg",asset,"pcg_node",src,"data_flows_to","pcg_node",dst,{"source_pin":sp.get("label",""),"target_pin":tp.get("label","")})
    for p in pcg_props:
        asset=p.get("asset_path",""); owner=p.get("owner_id",""); obj=p.get("object_path",""); prop=p.get("property_name","")
        if "parameter" in prop.lower() and p.get("value",""):
            pid=hashlib.sha1(f"{asset}|{owner}|{prop}".encode()).hexdigest()
            pcg_params.append({"parameter_id":pid,"pcg_path":asset,"owner_kind":p.get("owner_kind",""),"owner_id":owner,
                               "property_name":prop,"value":p.get("value",""),"object_path":obj})
        targets = [obj] if obj else []
        targets.extend(_extract_unreal_object_paths(p.get("value","")))
        for raw_target in dict.fromkeys(t for t in targets if t):
            target = generated_to_bp.get(raw_target,raw_target)
            target_cls=classes.get(target, classes.get(raw_target, p.get("object_class","") if raw_target == obj else ""))
            if target_cls == "/Script/PCG.PCGGraph":
                # Reflected PCG node/settings objects retain ownership pointers
                # back to their containing graph (InputPins, OutputPins,
                # SettingsInterface, Nodes, etc.). Those are not subgraph uses.
                # Only a reference to a *different* PCG graph is a subgraph edge.
                if target != asset or "subgraph" in prop.lower():
                    add("pcg",asset,p.get("owner_kind","pcg_object"),owner,"uses_subgraph","pcg_graph",target,{"property":prop})
            elif target in generated_to_bp.values() or raw_target in generated_to_bp:
                add("pcg",asset,p.get("owner_kind","pcg_object"),owner,"uses_blueprint","blueprint",target,{"property":prop})
            elif target_cls.startswith("/Script/Engine.Material"):
                add("pcg",asset,p.get("owner_kind","pcg_object"),owner,"uses_material","material",target,{"property":prop})

    materials=list(iter_jsonl(output / "materials.jsonl"))
    exprs=list(iter_jsonl(output / "material_expressions.jsonl"))
    medges=list(iter_jsonl(output / "material_edges.jsonl"))
    mprops=list(iter_jsonl(output / "material_properties.jsonl"))
    mparams=[]
    for m in materials:
        asset=m.get("material_path","")
        if m.get("parent_path"):
            add("material",asset,"material",asset,"inherits_from","material",m["parent_path"])
    for e in exprs:
        asset=e.get("material_path",""); eid=e.get("expression_id",""); cls=e.get("expression_class","")
        add("material",asset,"material",asset,"contains_expression","material_expression",eid,{"class":cls})
        if e.get("function_path"):
            add("material",asset,"material_expression",eid,"calls_material_function","material_function",e["function_path"])
        if e.get("texture_path"):
            add("material",asset,"material_expression",eid,"uses_texture","asset",e["texture_path"])
        pname=e.get("parameter_name","")
        if pname:
            kind=cls.rsplit('.',1)[-1].replace('MaterialExpression','')
            obj=e.get("texture_path","") or e.get("function_path","")
            pid=hashlib.sha1(f"{asset}|{eid}|{pname}".encode()).hexdigest()
            mparams.append({"parameter_id":pid,"material_path":asset,"expression_id":eid,"parameter_name":pname,
                            "parameter_kind":kind,"default_value":e.get("default_value",""),"value":e.get("value",""),"object_path":obj})
    for e in medges:
        asset=e.get("material_path",""); src=e.get("source_expression_id",""); dst=e.get("target_expression_id","")
        rel="feeds_material_output" if e.get("edge_kind")=="material_output" or dst.startswith("$output:") else "feeds_expression"
        tk="material_output" if dst.startswith("$output:") else "material_expression"
        add("material",asset,"material_expression",src,rel,tk,dst,{"target_input":e.get("target_input_name",""),"source_output_index":e.get("source_output_index","")})
    for p in mprops:
        asset=p.get("asset_path",""); owner=p.get("owner_id",""); prop=p.get("property_name",""); obj=p.get("object_path","")
        if p.get("owner_kind") in ("instance","function_instance") and "parameter" in prop.lower() and p.get("value",""):
            pid=hashlib.sha1(f"{asset}|{owner}|{prop}".encode()).hexdigest()
            mparams.append({"parameter_id":pid,"material_path":asset,"expression_id":"","parameter_name":prop,
                            "parameter_kind":"instance_override_group","default_value":"","value":p.get("value",""),"object_path":obj})
        targets = [obj] if obj else []
        targets.extend(_extract_unreal_object_paths(p.get("value","")))
        for target in dict.fromkeys(t for t in targets if t):
            cls=classes.get(target,p.get("object_class","") if target == obj else "")
            if cls in ("/Script/Engine.MaterialFunction","/Script/Engine.MaterialFunctionInstance"):
                relation="references_material_function"
                low=prop.lower()
                if "blend" in low: relation="uses_material_blend"
                elif "layer" in low: relation="uses_material_layer"
                add("material",asset,p.get("owner_kind","material_object"),owner,relation,"material_function",target,{"property":prop})
            elif "Texture" in cls:
                add("material",asset,p.get("owner_kind","material_object"),owner,"references_texture","asset",target,{"property":prop})

    # Promote Blueprint -> visual assets from factual Blueprint relations. Normal
    # derive_output() passes the same-pass in-memory rows so this step never
    # depends on stale derived state from a previous run. The disk fallback is
    # retained for callers that intentionally invoke derive_visual() alone.
    blueprint_relation_rows = (
        blueprint_relation_rows
        if blueprint_relation_rows is not None
        else list(iter_jsonl(output / "blueprint_relations.jsonl"))
    )
    for r in blueprint_relation_rows:
        target=r.get("target",""); cls=classes.get(target,"")
        if cls == "/Script/PCG.PCGGraph":
            add("blueprint",r.get("blueprint_path",r.get("asset_path","")),r.get("source_kind","blueprint_node"),r.get("source_id",""),"uses_pcg_graph","pcg_graph",target,{"via":r.get("relation","")})
        elif cls.startswith("/Script/Engine.Material"):
            add("blueprint",r.get("blueprint_path",r.get("asset_path","")),r.get("source_kind","blueprint_node"),r.get("source_id",""),"uses_material","material",target,{"via":r.get("relation","")})

    # Contexts.
    node_by_asset=collections.defaultdict(list)
    for n in pcg_nodes: node_by_asset[n.get("pcg_path","")].append(n)
    edge_by_asset=collections.defaultdict(list)
    for e in pcg_edges: edge_by_asset[e.get("pcg_path","")].append(e)
    pcg_context=[]
    for g in iter_jsonl(output / "pcg_graphs.jsonl"):
        asset=g.get("pcg_path",""); lines=[f"PCG: {asset}",f"Nodes: {len(node_by_asset[asset])} Edges: {len(edge_by_asset[asset])}"]
        for n in node_by_asset[asset][:160]:
            lines.append(f"node {n.get('node_id','')} settings={n.get('settings_class','')} title={n.get('node_title','')}")
        for e in edge_by_asset[asset][:240]:
            sp=pin_by_id.get(e.get('source_pin_id',''),{}); tp=pin_by_id.get(e.get('target_pin_id',''),{})
            lines.append(f"flow {e.get('source_node_id','')}[{sp.get('label','')}] -> {e.get('target_node_id','')}[{tp.get('label','')}]")
        pcg_context.append({"pcg_path":asset,"text":"\n".join(lines)})

    expr_by_asset=collections.defaultdict(list)
    for e in exprs: expr_by_asset[e.get("material_path","")].append(e)
    medge_by_asset=collections.defaultdict(list)
    for e in medges: medge_by_asset[e.get("material_path","")].append(e)
    material_context=[]
    for m in materials:
        asset=m.get("material_path",""); lines=[f"Material: {asset}",f"Kind: {m.get('material_kind','')} Expressions: {len(expr_by_asset[asset])}"]
        if m.get('parent_path'): lines.append(f"Parent: {m['parent_path']}")
        for e in expr_by_asset[asset][:200]:
            extra=[]
            if e.get('parameter_name'): extra.append(f"param={e['parameter_name']}")
            if e.get('function_path'): extra.append(f"function={e['function_path']}")
            if e.get('texture_path'): extra.append(f"texture={e['texture_path']}")
            lines.append(f"expr {e.get('expression_id','')} class={e.get('expression_class','')} {' '.join(extra)}")
        for e in medge_by_asset[asset][:320]:
            lines.append(f"wire {e.get('source_expression_id','')}:{e.get('source_output_index','')} -> {e.get('target_expression_id','')}.{e.get('target_input_name','')}")
        material_context.append({"material_path":asset,"text":"\n".join(lines)})

    rel_by_asset=collections.defaultdict(list)
    for r in relations: rel_by_asset[r.get("asset_path","")].append(r)
    visual_summaries=[]
    all_assets={g.get("pcg_path",""):("pcg","/Script/PCG.PCGGraph",len(node_by_asset[g.get("pcg_path","")])) for g in iter_jsonl(output / "pcg_graphs.jsonl")}
    all_assets.update({m.get("material_path",""):("material",m.get("class_path",""),len(expr_by_asset[m.get("material_path","")])) for m in materials})
    for asset,(system,cls,ncount) in all_assets.items():
        rels=rel_by_asset[asset]
        lines=[f"{system}: {asset}",f"class: {cls}",f"nodes: {ncount}",f"relations: {len(rels)}"]
        for r in rels[:120]: lines.append(f"{r['source_kind']} {r['source_id']} --{r['relation']}--> {r['target_kind']} {r['target']}")
        visual_summaries.append({"asset_path":asset,"system":system,"asset_class":cls,"node_count":ncount,"relation_count":len(rels),"text":"\n".join(lines)})
    return relations, pcg_params, mparams, pcg_context, material_context, visual_summaries

def derive_output(output: Path) -> dict[str, int]:
    output = output.resolve()
    rigvm_links = derive_rigvm_editor_links(output)
    functions = derive_blueprint_functions(output)
    events = derive_blueprint_events(output)
    call_edges = derive_blueprint_call_edges(output, functions)
    data_dependencies = derive_blueprint_data_dependencies(output)
    call_bindings = derive_blueprint_call_bindings(output, functions, call_edges, data_dependencies)
    execution_blocks, execution_block_edges, execution_roots = derive_blueprint_execution_program(output, functions, events)
    anim_state_machines, anim_states, anim_transitions = derive_anim_state_machines(output)
    relations = derive_blueprint_relations(output, rigvm_links, functions, events)
    graph_context = derive_graph_context(output, rigvm_links, functions, events)
    summaries = derive_blueprint_summaries(output, relations, functions, events)
    ai_relations = derive_ai_relations(output)
    ai_summaries = derive_ai_summaries(output, ai_relations)
    visual_relations, pcg_parameters, material_parameters, pcg_context, material_context, visual_summaries = derive_visual(
        output, relations
    )
    counts = {
        "rigvm_editor_links": _write_jsonl(output / "rigvm_editor_links.jsonl", rigvm_links),
        "blueprint_functions": _write_jsonl(output / "blueprint_functions.jsonl", functions),
        "blueprint_events": _write_jsonl(output / "blueprint_events.jsonl", events),
        "blueprint_call_edges": _write_jsonl(output / "blueprint_call_edges.jsonl", call_edges),
        "blueprint_call_bindings": _write_jsonl(output / "blueprint_call_bindings.jsonl", call_bindings),
        "blueprint_data_dependencies": _write_jsonl(output / "blueprint_data_dependencies.jsonl", data_dependencies),
        "blueprint_execution_blocks": _write_jsonl(output / "blueprint_execution_blocks.jsonl", execution_blocks),
        "blueprint_execution_block_edges": _write_jsonl(output / "blueprint_execution_block_edges.jsonl", execution_block_edges),
        "blueprint_execution_roots": _write_jsonl(output / "blueprint_execution_roots.jsonl", execution_roots),
        "anim_state_machines": _write_jsonl(output / "anim_state_machines.jsonl", anim_state_machines),
        "anim_states": _write_jsonl(output / "anim_states.jsonl", anim_states),
        "anim_transitions": _write_jsonl(output / "anim_transitions.jsonl", anim_transitions),
        "blueprint_relations": _write_jsonl(output / "blueprint_relations.jsonl", relations),
        "blueprint_graph_context": _write_jsonl(output / "blueprint_graph_context.jsonl", graph_context),
        "blueprint_summaries": _write_jsonl(output / "blueprint_summaries.jsonl", summaries),
        "ai_relations": _write_jsonl(output / "ai_relations.jsonl", ai_relations),
        "ai_summaries": _write_jsonl(output / "ai_summaries.jsonl", ai_summaries),
        "pcg_parameters": _write_jsonl(output / "pcg_parameters.jsonl", pcg_parameters),
        "material_parameters": _write_jsonl(output / "material_parameters.jsonl", material_parameters),
        "visual_relations": _write_jsonl(output / "visual_relations.jsonl", visual_relations),
        "pcg_graph_context": _write_jsonl(output / "pcg_graph_context.jsonl", pcg_context),
        "material_graph_context": _write_jsonl(output / "material_graph_context.jsonl", material_context),
        "visual_summaries": _write_jsonl(output / "visual_summaries.jsonl", visual_summaries),
    }
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["derived_schema_version"] = DERIVED_SCHEMA_VERSION
        derived_counts = manifest.get("derived_counts", {})
        if not isinstance(derived_counts, dict):
            derived_counts = {}
        derived_counts.update(counts)
        manifest["derived_counts"] = derived_counts
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return counts

def build_database(output: Path) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    db_path = output / DB_NAME
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)

        manifest_path = output / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for key, value in manifest.items():
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    (key, json.dumps(value, ensure_ascii=False)),
                )

        world_manifest_path = output / "world_manifest.json"
        if world_manifest_path.exists():
            world_manifest = json.loads(world_manifest_path.read_text(encoding="utf-8"))
            for key, value in world_manifest.items():
                conn.execute(
                    "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
                    (f"world.{key}", json.dumps(value, ensure_ascii=False)),
                )

        for row in iter_jsonl(output / "files.jsonl"):
            conn.execute(
                "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row.get("path", ""),
                    row.get("kind", ""),
                    row.get("extension", ""),
                    int(row.get("size", 0)),
                    row.get("modified_utc", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "source_chunks.jsonl"):
            conn.execute(
                "INSERT INTO source_chunks(path, start_line, end_line, text) VALUES (?, ?, ?, ?)",
                (
                    row.get("path", ""),
                    int(row.get("start_line", 0)),
                    int(row.get("end_line", 0)),
                    row.get("text", ""),
                ),
            )

        for row in iter_jsonl(output / "assets.jsonl"):
            conn.execute(
                "INSERT INTO assets VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("object_path", ""),
                    row.get("asset_name", ""),
                    row.get("package_name", ""),
                    row.get("package_path", ""),
                    row.get("class_path", ""),
                    row.get("disk_path", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "asset_dependencies.jsonl"):
            conn.execute(
                "INSERT OR IGNORE INTO asset_dependencies VALUES (?, ?, ?)",
                (
                    row.get("source_package", ""),
                    row.get("target_package", ""),
                    row.get("category", ""),
                ),
            )

        for row in iter_jsonl(output / "blueprints.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprints VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("object_path", ""),
                    row.get("name", ""),
                    row.get("parent_class", ""),
                    row.get("generated_class", ""),
                    int(row.get("blueprint_type", 0)),
                    int(row.get("graph_count", 0)),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )
            blueprint_path = row.get("object_path", "")
            for variable in row.get("variables", []):
                conn.execute(
                    "INSERT OR REPLACE INTO blueprint_variables VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        blueprint_path,
                        variable.get("name", ""),
                        variable.get("guid", ""),
                        variable.get("category", ""),
                        variable.get("default_value", ""),
                        int(variable.get("property_flags", 0)),
                        json.dumps(variable.get("type", {}), ensure_ascii=False, separators=(",", ":")),
                    ),
                )
            for component in row.get("components", []):
                conn.execute(
                    "INSERT OR REPLACE INTO blueprint_components VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        blueprint_path,
                        component.get("variable_name", ""),
                        component.get("component_class", ""),
                        component.get("template", ""),
                        component.get("parent_component_or_variable", ""),
                        component.get("parent_owner_class", ""),
                        component.get("attach_to", ""),
                        component.get("guid", ""),
                        1 if component.get("is_root", False) else 0,
                    ),
                )

        for row in iter_blueprint_graph_rows(output):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_graphs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("graph_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("graph_name", ""),
                    row.get("graph_path", ""),
                    row.get("graph_kind", ""),
                    row.get("graph_system", ""),
                    row.get("graph_class", ""),
                    row.get("schema_class", ""),
                    row.get("outer_path", ""),
                    row.get("outer_class", ""),
                    row.get("parent_node_guid", ""),
                    row.get("parent_graph_path", ""),
                    int(row.get("node_count", 0)),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_interfaces.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_interfaces VALUES (?, ?, ?, ?)",
                (
                    row.get("blueprint_path", ""),
                    row.get("interface_class", ""),
                    row.get("interface_name", ""),
                    json.dumps(row.get("graphs", []), ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_nodes.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("node_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("graph_name", ""),
                    row.get("graph_kind", ""),
                    row.get("node_class", ""),
                    row.get("operation", ""),
                    row.get("symbol", ""),
                    row.get("owner", ""),
                    row.get("title", ""),
                    row.get("comment", ""),
                    int(row.get("x", 0)),
                    int(row.get("y", 0)),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        pin_to_node: dict[str, tuple[str, str]] = {}
        for row in iter_blueprint_pin_rows(output):
            pin_type = row.get("type", {}) if isinstance(row.get("type", {}), dict) else {}
            pin_id = row.get("pin_id", "")
            node_id = row.get("node_id", "")
            pin_to_node[pin_id] = (node_id, row.get("name", ""))
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_pins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pin_id,
                    node_id,
                    row.get("blueprint_path", ""),
                    row.get("graph_id", ""),
                    row.get("graph_name", ""),
                    int(row.get("pin_index", 0)),
                    row.get("name", ""),
                    row.get("direction", ""),
                    pin_type.get("category", ""),
                    pin_type.get("subcategory", ""),
                    pin_type.get("subcategory_object", ""),
                    int(pin_type.get("container_type", 0) or 0),
                    row.get("default_value", ""),
                    row.get("default_object", ""),
                    row.get("default_text", ""),
                    1 if row.get("hidden", False) else 0,
                    1 if row.get("not_connectable", False) else 0,
                    int(row.get("linked_count", 0)),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_node_properties.jsonl"):
            property_name = row.get("property_name", "")
            property_path = row.get("property_path", property_name)
            owner_class = row.get("owner_class", "")
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_node_properties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("node_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("graph_name", ""),
                    row.get("node_class", ""),
                    property_name,
                    property_path,
                    owner_class,
                    row.get("declaring_type", owner_class),
                    int(row.get("depth", 0)),
                    row.get("property_type", ""),
                    row.get("cpp_type", ""),
                    row.get("value", ""),
                    row.get("object_path", ""),
                    row.get("object_class", ""),
                    int(row.get("property_flags", 0)),
                    1 if row.get("truncated", False) else 0,
                ),
            )

        for row in iter_jsonl(output / "blueprint_node_references.jsonl"):
            conn.execute(
                "INSERT OR IGNORE INTO blueprint_node_references VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("node_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("graph_name", ""),
                    row.get("node_class", ""),
                    row.get("property_path", ""),
                    row.get("target_object_path", ""),
                    row.get("target_class", ""),
                    1 if row.get("node_owned", False) else 0,
                ),
            )

        for row in iter_jsonl(output / "blueprint_bindings.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("node_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("graph_name", ""),
                    row.get("node_class", ""),
                    row.get("binding_object", ""),
                    row.get("binding_key", ""),
                    row.get("target_property", ""),
                    row.get("access_path", ""),
                    json.dumps(row.get("property_path", []), ensure_ascii=False, separators=(",", ":")),
                    row.get("compiled_context", ""),
                    row.get("pin_type", ""),
                    row.get("promoted_pin_type", ""),
                    row.get("raw_value", ""),
                ),
            )

        for row in iter_jsonl(output / "blueprint_defaults.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_defaults VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("blueprint_path", ""), row.get("class_path", ""), row.get("property_name", ""),
                    row.get("declaring_class", ""), int(row.get("array_index", 0)), row.get("property_type", ""),
                    row.get("cpp_type", ""), row.get("value", ""), row.get("parent_value", ""),
                    row.get("referenced_object_path", ""), row.get("referenced_object_class", ""),
                    1 if row.get("declared_here", False) else 0, int(row.get("property_flags", 0)),
                ),
            )

        for row in iter_jsonl(output / "blueprint_component_properties.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_component_properties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("blueprint_path", ""), row.get("component_name", ""), row.get("component_class", ""),
                    row.get("template_path", ""), row.get("property_name", ""), row.get("declaring_class", ""),
                    int(row.get("array_index", 0)), row.get("property_type", ""), row.get("cpp_type", ""),
                    row.get("value", ""), row.get("class_default_value", ""), row.get("referenced_object_path", ""),
                    row.get("referenced_object_class", ""), int(row.get("property_flags", 0)),
                ),
            )

        for row in iter_jsonl(output / "blueprint_state_values.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_state_values VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("blueprint_path", ""), row.get("owner_kind", ""), row.get("owner_id", ""),
                    row.get("owner_name", ""), row.get("owner_class", ""), row.get("baseline_class", ""),
                    row.get("root_property", ""), row.get("property_name", ""), row.get("property_path", ""),
                    int(row.get("depth", 0)), row.get("container_kind", ""), row.get("property_type", ""),
                    row.get("cpp_type", ""), row.get("value", ""), row.get("baseline_value", ""),
                    1 if row.get("baseline_present", False) else 0, row.get("referenced_object_path", ""),
                    row.get("referenced_object_class", ""), row.get("baseline_object_path", ""),
                    row.get("baseline_object_class", ""), int(row.get("property_flags", 0)),
                    1 if row.get("truncated", False) else 0,
                ),
            )

        for row in iter_jsonl(output / "blueprint_timelines.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_timelines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("timeline_path", ""), row.get("blueprint_path", ""), row.get("timeline_name", ""),
                    row.get("timeline_class", ""), row.get("guid", ""), row.get("length", ""), row.get("length_mode", ""),
                    row.get("auto_play", ""), row.get("loop", ""), row.get("replicated", ""), row.get("ignore_time_dilation", ""),
                    row.get("tick_group", ""), row.get("update_function", ""), row.get("finished_function", ""), row.get("direction_property", ""),
                    row.get("variable_name", ""), json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_timeline_tracks.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_timeline_tracks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("timeline_path", ""), row.get("blueprint_path", ""), int(row.get("track_index", 0)),
                    row.get("track_type", ""), row.get("track_struct", ""), row.get("track_name", ""), row.get("property_name", ""),
                    row.get("function_name", ""), row.get("external_curve", ""), row.get("curve_path", ""),
                    row.get("curve_class", ""), row.get("raw_value", ""),
                ),
            )

        for row in iter_jsonl(output / "blueprint_timeline_keys.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_timeline_keys VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("timeline_path", ""), row.get("blueprint_path", ""), row.get("timeline_name", ""),
                    int(row.get("track_index", 0)), row.get("track_type", ""), row.get("track_name", ""),
                    row.get("curve_path", ""), row.get("curve_class", ""), int(row.get("channel_index", 0)),
                    row.get("channel_name", ""), int(row.get("key_index", 0)), float(row.get("time", 0.0)),
                    float(row.get("value", 0.0)), int(row.get("interp_mode", 0)), int(row.get("tangent_mode", 0)),
                    int(row.get("tangent_weight_mode", 0)), float(row.get("arrive_tangent", 0.0)),
                    float(row.get("leave_tangent", 0.0)), float(row.get("arrive_tangent_weight", 0.0)),
                    float(row.get("leave_tangent_weight", 0.0)),
                ),
            )

        for row in iter_jsonl(output / "blueprint_widgets.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_widgets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("widget_path", ""), row.get("blueprint_path", ""), row.get("widget_tree", ""),
                    row.get("widget_name", ""), row.get("widget_class", ""), row.get("parent_widget_path", ""),
                    row.get("slot_path", ""), row.get("slot_class", ""),
                    json.dumps(row.get("properties", {}), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("slot_properties", {}), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_widget_properties.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_widget_properties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("blueprint_path", ""), row.get("owner_kind", ""), row.get("owner_id", ""),
                    row.get("owner_name", ""), row.get("owner_class", ""), row.get("baseline_class", ""),
                    row.get("root_property", ""), row.get("property_name", ""), row.get("property_path", ""),
                    int(row.get("depth", 0)), row.get("container_kind", ""), row.get("property_type", ""),
                    row.get("cpp_type", ""), row.get("value", ""), row.get("baseline_value", ""),
                    1 if row.get("baseline_present", False) else 0, row.get("referenced_object_path", ""),
                    row.get("referenced_object_class", ""), row.get("baseline_object_path", ""),
                    row.get("baseline_object_class", ""), int(row.get("property_flags", 0)),
                    1 if row.get("truncated", False) else 0,
                ),
            )

        for row in iter_jsonl(output / "blueprint_widget_bindings.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_widget_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("blueprint_path", ""), int(row.get("binding_index", 0)), row.get("binding_struct", ""),
                    row.get("object_name", ""), row.get("property_name", ""), row.get("function_name", ""),
                    row.get("source_property", ""), row.get("source_path", ""), row.get("kind", ""),
                    row.get("member_guid", ""), row.get("raw_value", ""),
                ),
            )

        for row in iter_jsonl(output / "blueprint_widget_animations.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_widget_animations VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("animation_path", ""), row.get("blueprint_path", ""), row.get("animation_name", ""),
                    row.get("animation_class", ""), row.get("display_label", ""), row.get("movie_scene", ""),
                    row.get("animation_bindings", ""), json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_widget_animation_bindings.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_widget_animation_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("animation_path", ""), row.get("blueprint_path", ""), row.get("animation_name", ""),
                    int(row.get("binding_index", 0)), row.get("binding_struct", ""), row.get("widget_name", ""),
                    row.get("slot_widget_name", ""), row.get("animation_guid", ""), row.get("is_root_widget", ""),
                    row.get("dynamic_binding", ""),
                ),
            )

        for row in iter_jsonl(output / "behavior_trees.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO behavior_trees VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row.get("behavior_tree_path", ""), row.get("class_path", ""), row.get("root_node_id", ""),
                 row.get("blackboard_path", ""), int(row.get("root_decorator_count", 0)), row.get("root_decorator_logic", ""),
                 json.dumps(row, ensure_ascii=False, separators=(",", ":"))),
            )
        for row in iter_jsonl(output / "behavior_tree_nodes.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO behavior_tree_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row.get("node_id", ""), row.get("behavior_tree_path", ""), row.get("node_kind", ""), row.get("class_path", ""),
                 row.get("class_name", ""), row.get("name", ""), row.get("display_name", ""), row.get("parent_node_id", ""),
                 int(row.get("child_index", -1)), row.get("attached_to", ""), row.get("attachment_kind", ""),
                 int(row.get("attachment_index", -1)), json.dumps(row, ensure_ascii=False, separators=(",", ":"))),
            )
        for row in iter_jsonl(output / "behavior_tree_edges.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO behavior_tree_edges VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row.get("behavior_tree_path", ""), row.get("source_node_id", ""), row.get("target_node_id", ""),
                 row.get("edge_kind", ""), int(row.get("child_index", -1)), row.get("decorator_logic", ""),
                 json.dumps(row.get("decorator_ids", []), ensure_ascii=False, separators=(",", ":"))),
            )
        for row in iter_jsonl(output / "blackboards.jsonl"):
            conn.execute("INSERT OR REPLACE INTO blackboards VALUES (?, ?, ?, ?)",
                         (row.get("blackboard_path", ""), row.get("class_path", ""), row.get("parent_blackboard_path", ""),
                          json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        for row in iter_jsonl(output / "blackboard_keys.jsonl"):
            conn.execute("INSERT OR REPLACE INTO blackboard_keys VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("key_id", ""), row.get("blackboard_path", ""), int(row.get("key_index", 0)), row.get("name", ""),
                          row.get("key_type_path", ""), row.get("key_type_class", ""), row.get("instance_synced", ""), row.get("raw_value", ""),
                          json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        for row in iter_jsonl(output / "eqs_queries.jsonl"):
            conn.execute("INSERT OR REPLACE INTO eqs_queries VALUES (?, ?, ?, ?)",
                         (row.get("eqs_path", ""), row.get("class_path", ""), int(row.get("option_count", 0)),
                          json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        for row in iter_jsonl(output / "eqs_options.jsonl"):
            conn.execute("INSERT OR REPLACE INTO eqs_options VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (row.get("option_id", ""), row.get("eqs_path", ""), int(row.get("option_index", 0)), row.get("class_path", ""),
                          row.get("generator_id", ""), int(row.get("test_count", 0)), json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        for row in iter_jsonl(output / "eqs_generators.jsonl"):
            conn.execute("INSERT OR REPLACE INTO eqs_generators VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("generator_id", ""), row.get("eqs_path", ""), row.get("option_id", ""), int(row.get("option_index", 0)),
                          row.get("class_path", ""), row.get("class_name", ""), row.get("item_type", ""),
                          json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        for row in iter_jsonl(output / "eqs_tests.jsonl"):
            conn.execute("INSERT OR REPLACE INTO eqs_tests VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("test_id", ""), row.get("eqs_path", ""), row.get("option_id", ""), int(row.get("option_index", 0)),
                          int(row.get("test_index", 0)), row.get("class_path", ""), row.get("class_name", ""), row.get("test_purpose", ""),
                          row.get("filter_type", ""), row.get("scoring_equation", ""), row.get("weight_modifier", ""),
                          json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        for row in iter_jsonl(output / "statetrees.jsonl"):
            conn.execute("INSERT OR REPLACE INTO statetrees VALUES (?, ?, ?, ?, ?, ?)",
                         (row.get("statetree_path", ""), row.get("class_path", ""), row.get("editor_data_path", ""), row.get("editor_data_class", ""),
                          row.get("last_compiled_editor_data_hash", ""), json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        for row in iter_jsonl(output / "statetree_states.jsonl"):
            conn.execute("INSERT OR REPLACE INTO statetree_states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("state_id", ""), row.get("statetree_path", ""), row.get("state_object_path", ""), row.get("parent_state_id", ""),
                          int(row.get("child_index", 0)), row.get("name", ""), row.get("description", ""), row.get("state_type", ""),
                          row.get("selection_behavior", ""), row.get("enabled", ""), row.get("tag", ""), row.get("tasks_completion", ""),
                          row.get("required_event", ""), row.get("linked_asset", ""), row.get("linked_subtree", ""),
                          json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        for row in iter_jsonl(output / "statetree_nodes.jsonl"):
            if _statetree_node_is_empty(row):
                continue
            conn.execute("INSERT OR REPLACE INTO statetree_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("node_id", ""), row.get("statetree_path", ""), row.get("state_id", ""), row.get("role", ""), int(row.get("node_index", 0)),
                          row.get("guid", ""), row.get("expression_indent", ""), row.get("expression_operand", ""), row.get("instance_object_path", ""),
                          row.get("instance_object_class", ""), row.get("raw_node", ""), row.get("raw_instance", ""),
                          json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        for row in iter_jsonl(output / "statetree_transitions.jsonl"):
            conn.execute("INSERT OR REPLACE INTO statetree_transitions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("transition_id", ""), row.get("statetree_path", ""), row.get("source_state_id", ""), int(row.get("transition_index", 0)),
                          row.get("trigger", ""), row.get("event_tag", ""), row.get("state", ""), row.get("priority", ""), row.get("fallback", ""),
                          row.get("enabled", ""), row.get("delay_enabled", ""), row.get("delay", ""), row.get("raw_value", ""),
                          json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
        for binding_row in iter_jsonl(output / "statetree_bindings.jsonl"):
            row = _normalize_statetree_binding_row(binding_row)
            conn.execute("INSERT OR REPLACE INTO statetree_bindings VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (row.get("statetree_path", ""), int(row.get("binding_index", 0)), row.get("binding_struct", ""), row.get("source_path", ""),
                          row.get("target_path", ""), row.get("output_binding", ""), row.get("raw_value", "")))
        for row in iter_jsonl(output / "ai_properties.jsonl"):
            conn.execute("INSERT OR REPLACE INTO ai_properties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("asset_path", ""), row.get("system", ""), row.get("owner_kind", ""), row.get("owner_id", ""), row.get("owner_class", ""),
                          row.get("declaring_type", ""), row.get("property_name", ""), row.get("property_type", ""), row.get("cpp_type", ""), row.get("value", ""),
                          row.get("object_path", ""), row.get("object_class", ""), int(row.get("property_flags", 0)), 1 if row.get("truncated", False) else 0))
        for row in iter_jsonl(output / "ai_relations.jsonl"):
            conn.execute("INSERT OR REPLACE INTO ai_relations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("relation_id", ""), row.get("asset_path", ""), row.get("system", ""), row.get("source_kind", ""), row.get("source_id", ""),
                          row.get("relation", ""), row.get("target_kind", ""), row.get("target", ""),
                          json.dumps(row.get("detail", {}), ensure_ascii=False, separators=(",", ":"))))
        for row in iter_jsonl(output / "ai_summaries.jsonl"):
            conn.execute("INSERT OR REPLACE INTO ai_summaries VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (row.get("asset_path", ""), row.get("system", ""), row.get("asset_class", ""), int(row.get("node_count", 0)),
                          int(row.get("relation_count", 0)), row.get("text", ""), json.dumps(row, ensure_ascii=False, separators=(",", ":"))))


        for row in iter_jsonl(output / "pcg_graphs.jsonl"):
            conn.execute("INSERT OR REPLACE INTO pcg_graphs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("pcg_path",""),row.get("class_path",""),row.get("parent_graph_path",""),1 if row.get("embedded",False) else 0,
                          json.dumps(row.get("embedded_subgraphs",[]),ensure_ascii=False,separators=(",",":")),int(row.get("node_count",0)),int(row.get("pin_count",0)),
                          int(row.get("edge_count",0)),row.get("user_parameters",""),row.get("default_grid",""),json.dumps(row,ensure_ascii=False,separators=(",",":"))))
        for row in iter_jsonl(output / "pcg_nodes.jsonl"):
            conn.execute("INSERT OR REPLACE INTO pcg_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("node_id",""),row.get("pcg_path",""),row.get("node_class",""),row.get("node_name",""),row.get("node_title",""),
                          row.get("position_x",""),row.get("position_y",""),row.get("settings_path",""),row.get("settings_class",""),row.get("settings_name",""),
                          row.get("enabled",""),json.dumps(row,ensure_ascii=False,separators=(",",":"))))
        for row in iter_jsonl(output / "pcg_pins.jsonl"):
            conn.execute("INSERT OR REPLACE INTO pcg_pins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("pin_id",""),row.get("pcg_path",""),row.get("node_id",""),row.get("direction",""),int(row.get("pin_index",-1)),
                          row.get("label",""),row.get("allowed_types",""),row.get("pin_status",""),row.get("allow_multiple_data",""),row.get("invisible",""),
                          row.get("raw_properties",""),json.dumps(row,ensure_ascii=False,separators=(",",":"))))
        for row in iter_jsonl(output / "pcg_edges.jsonl"):
            conn.execute("INSERT OR REPLACE INTO pcg_edges VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (row.get("edge_id",""),row.get("pcg_path",""),row.get("source_pin_id",""),row.get("target_pin_id",""),row.get("source_node_id",""),
                          row.get("target_node_id",""),json.dumps(row,ensure_ascii=False,separators=(",",":"))))
        for filename,table in (("pcg_properties.jsonl","pcg_properties"),("material_properties.jsonl","material_properties")):
            for row in iter_jsonl(output / filename):
                conn.execute(f"INSERT OR REPLACE INTO {table} VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                             (row.get("asset_path",""),row.get("system",""),row.get("owner_kind",""),row.get("owner_id",""),row.get("owner_class",""),
                              row.get("declaring_type",""),row.get("property_name",""),row.get("property_type",""),row.get("cpp_type",""),row.get("value",""),
                              row.get("object_path",""),row.get("object_class",""),int(row.get("property_flags",0)),1 if row.get("truncated",False) else 0))
        for row in iter_jsonl(output / "pcg_parameters.jsonl"):
            conn.execute("INSERT OR REPLACE INTO pcg_parameters VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("parameter_id",""),row.get("pcg_path",""),row.get("owner_kind",""),row.get("owner_id",""),row.get("property_name",""),
                          row.get("value",""),row.get("object_path",""),json.dumps(row,ensure_ascii=False,separators=(",",":"))))
        for row in iter_jsonl(output / "materials.jsonl"):
            conn.execute("INSERT OR REPLACE INTO materials VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("material_path",""),row.get("material_kind",""),row.get("class_path",""),int(row.get("expression_count",0)),row.get("parent_path",""),
                          row.get("material_domain",""),row.get("blend_mode",""),row.get("shading_model",""),json.dumps(row,ensure_ascii=False,separators=(",",":"))))
        for row in iter_jsonl(output / "material_expressions.jsonl"):
            conn.execute("INSERT OR REPLACE INTO material_expressions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("expression_id",""),row.get("material_path",""),row.get("expression_class",""),row.get("expression_name",""),row.get("editor_x",""),
                          row.get("editor_y",""),row.get("description",""),row.get("parameter_name",""),row.get("function_path",""),row.get("texture_path",""),
                          row.get("default_value",""),row.get("value",""),json.dumps(row,ensure_ascii=False,separators=(",",":"))))
        for row in iter_jsonl(output / "material_edges.jsonl"):
            conn.execute("INSERT OR REPLACE INTO material_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("material_path",""),row.get("source_expression_id",""),row.get("source_output_index",""),row.get("source_output_name",""),
                          row.get("target_expression_id",""),row.get("target_input_name",""),int(row.get("target_input_index",0)),row.get("edge_kind","")))
        for row in iter_jsonl(output / "material_parameters.jsonl"):
            conn.execute("INSERT OR REPLACE INTO material_parameters VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("parameter_id",""),row.get("material_path",""),row.get("expression_id",""),row.get("parameter_name",""),row.get("parameter_kind",""),
                          row.get("default_value",""),row.get("value",""),row.get("object_path",""),json.dumps(row,ensure_ascii=False,separators=(",",":"))))
        for row in iter_jsonl(output / "visual_relations.jsonl"):
            conn.execute("INSERT OR REPLACE INTO visual_relations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                         (row.get("relation_id",""),row.get("system",""),row.get("asset_path",""),row.get("source_kind",""),row.get("source_id",""),row.get("relation",""),
                          row.get("target_kind",""),row.get("target",""),json.dumps(row.get("detail",{}),ensure_ascii=False,separators=(",",":"))))
        for row in iter_jsonl(output / "pcg_graph_context.jsonl"):
            conn.execute("INSERT OR REPLACE INTO pcg_graph_context VALUES (?, ?, ?)",(row.get("pcg_path",""),row.get("text",""),json.dumps(row,ensure_ascii=False,separators=(",",":"))))
        for row in iter_jsonl(output / "material_graph_context.jsonl"):
            conn.execute("INSERT OR REPLACE INTO material_graph_context VALUES (?, ?, ?)",(row.get("material_path",""),row.get("text",""),json.dumps(row,ensure_ascii=False,separators=(",",":"))))
        for row in iter_jsonl(output / "visual_summaries.jsonl"):
            conn.execute("INSERT OR REPLACE INTO visual_summaries VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (row.get("asset_path",""),row.get("system",""),row.get("asset_class",""),int(row.get("node_count",0)),int(row.get("relation_count",0)),row.get("text",""),
                          json.dumps(row,ensure_ascii=False,separators=(",",":"))))

        for row in iter_jsonl(output / "blueprint_functions.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_functions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("function_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""),
                    row.get("graph_name", ""), row.get("graph_path", ""), row.get("name", ""), row.get("owner", ""),
                    row.get("resolved_function", ""), int(row.get("function_flags", 0)),
                    1 if row.get("has_exec", False) else 0, 1 if row.get("pure_shape", False) else 0,
                    1 if row.get("blueprint_pure", False) else 0,
                    1 if row.get("const_function", False) else 0,
                    1 if row.get("blueprint_callable", False) else 0,
                    1 if row.get("static_function", False) else 0,
                    1 if row.get("event_function", False) else 0,
                    int(row.get("result_node_count", 0)),
                    json.dumps(row.get("inputs", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("outputs", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("locals", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_events.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("event_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""),
                    row.get("graph_name", ""), row.get("node_class", ""), row.get("operation", ""),
                    row.get("event_kind", ""), row.get("name", ""), row.get("owner", ""),
                    row.get("component_name", ""), row.get("delegate_name", ""), row.get("delegate_owner", ""),
                    row.get("input_name", ""),
                    json.dumps(row.get("parameters", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_call_edges.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_call_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("call_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""), row.get("graph_name", ""),
                    row.get("caller_function_id", ""), row.get("call_node_id", ""), row.get("target_function", ""),
                    row.get("target_name", ""), row.get("target_owner", ""), row.get("target_blueprint_path", ""),
                    row.get("target_function_id", ""), row.get("resolution", ""), int(row.get("candidate_count", 0)),
                    json.dumps(row.get("candidate_function_ids", []), ensure_ascii=False, separators=(",", ":")),
                    1 if row.get("pure", False) else 0, 1 if row.get("const_function", False) else 0,
                    1 if row.get("latent", False) else 0, 1 if row.get("interface_call", False) else 0,
                    int(row.get("function_flags", 0)), json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_call_bindings.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_call_bindings VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("binding_id", ""), row.get("call_id", ""), row.get("call_node_id", ""),
                    row.get("caller_blueprint_path", ""), row.get("caller_graph_id", ""), row.get("caller_function_id", ""),
                    row.get("target_blueprint_path", ""), row.get("target_function_id", ""), row.get("direction", ""),
                    row.get("call_pin_id", ""), row.get("call_pin_name", ""), row.get("parameter_name", ""),
                    json.dumps(row.get("parameter_pin_ids", []), ensure_ascii=False, separators=(",", ":")),
                    row.get("match_kind", ""), row.get("split_suffix", ""),
                    json.dumps(row.get("call_pin_type", {}), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("parameter_type", {}), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("dependency_ids", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("consumer_pin_ids", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_data_dependencies.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_data_dependencies VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("dependency_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""), row.get("graph_name", ""),
                    row.get("sink_node_id", ""), row.get("sink_operation", ""), row.get("sink_label", ""),
                    row.get("sink_pin_id", ""), row.get("sink_pin_name", ""), int(row.get("source_count", 0)),
                    int(row.get("expression_node_count", 0)), 1 if row.get("truncated", False) else 0,
                    1 if row.get("cycle", False) else 0,
                    json.dumps(row.get("variable_reads", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("function_calls", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("object_refs", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("expression", {}), ensure_ascii=False, separators=(",", ":")),
                    row.get("text", ""), json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_execution_blocks.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_execution_blocks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("block_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""), row.get("graph_name", ""),
                    int(row.get("block_index", 0)), row.get("entry_node_id", ""), row.get("exit_node_id", ""),
                    int(row.get("node_count", 0)), json.dumps(row.get("node_ids", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("operations", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("labels", []), ensure_ascii=False, separators=(",", ":")), row.get("text", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_execution_block_edges.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_execution_block_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("edge_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""),
                    row.get("source_block_id", ""), row.get("target_block_id", ""), row.get("source_node_id", ""),
                    row.get("target_node_id", ""), row.get("source_pin_name", ""), row.get("target_pin_name", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_execution_roots.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_execution_roots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("root_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""), row.get("graph_name", ""),
                    row.get("root_node_id", ""), row.get("root_kind", ""), row.get("root_name", ""), row.get("block_id", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "anim_state_machines.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO anim_state_machines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("machine_id", ""), row.get("blueprint_path", ""), row.get("host_graph_id", ""), row.get("host_graph_name", ""),
                    row.get("name", ""), row.get("editor_graph_path", ""), row.get("machine_graph_id", ""), row.get("entry_node_id", ""),
                    row.get("entry_state", ""), row.get("entry_state_id", ""), int(row.get("state_count", 0)), int(row.get("transition_count", 0)),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "anim_states.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO anim_states VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("state_id", ""), row.get("blueprint_path", ""), row.get("machine_graph_id", ""), row.get("machine_name", ""),
                    row.get("state_kind", ""), row.get("name", ""), row.get("bound_graph", ""),
                    1 if row.get("always_reset_on_entry", False) else 0, int(row.get("state_type", 0)),
                    1 if row.get("global_alias", False) else 0,
                    json.dumps(row.get("aliased_states", []), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "anim_transitions.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO anim_transitions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("transition_id", ""), row.get("blueprint_path", ""), row.get("machine_graph_id", ""), row.get("machine_name", ""),
                    row.get("previous_state", ""), row.get("previous_state_id", ""), row.get("next_state", ""), row.get("next_state_id", ""),
                    1 if row.get("bidirectional", False) else 0, 1 if row.get("disabled", False) else 0,
                    1 if row.get("automatic_rule", False) else 0, float(row.get("automatic_rule_trigger_time", -1) or 0),
                    float(row.get("crossfade_duration", 0) or 0), int(row.get("priority_order", 0)), int(row.get("logic_type", 0)),
                    float(row.get("min_time_before_reentry", -1) or 0), 1 if row.get("only_evaluate_when_active", False) else 0,
                    1 if row.get("shared_rules", False) else 0, row.get("shared_rules_name", ""),
                    1 if row.get("shared_crossfade", False) else 0, row.get("shared_crossfade_name", ""),
                    row.get("rule_graph", ""), row.get("custom_transition_graph", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "rigvm_editor_links.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO rigvm_editor_links VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("node_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""), row.get("graph_name", ""),
                    row.get("model_node_path", ""), row.get("status", ""), row.get("confidence", ""), int(row.get("score", 0)),
                    int(row.get("candidate_count", 0)), row.get("rigvm_object_id", ""), row.get("rigvm_operation", ""),
                    row.get("rigvm_class", ""), row.get("resolved_function_name", ""), row.get("template_notation", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_relations.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_relations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("relation_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""),
                    row.get("source_kind", ""), row.get("source_id", ""), row.get("relation", ""),
                    row.get("target_kind", ""), row.get("target", ""), row.get("owner", ""),
                    json.dumps(row.get("detail", {}), ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_graph_context.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_graph_context VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("graph_id", ""), row.get("blueprint_path", ""), row.get("graph_name", ""), row.get("graph_path", ""),
                    row.get("graph_kind", ""), row.get("graph_system", ""), int(row.get("node_count", 0)),
                    int(row.get("execution_edge_count", 0)), int(row.get("data_edge_count", 0)),
                    1 if row.get("truncated", False) else 0, row.get("text", ""),
                ),
            )

        for row in iter_jsonl(output / "blueprint_summaries.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO blueprint_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("blueprint_path", ""), row.get("name", ""), row.get("parent_class", ""), row.get("generated_class", ""),
                    int(row.get("variable_count", 0)), int(row.get("component_count", 0)), int(row.get("interface_count", 0)),
                    int(row.get("function_count", 0)), int(row.get("event_count", 0)), int(row.get("default_count", 0)),
                    int(row.get("component_override_count", 0)), int(row.get("state_value_count", 0)), int(row.get("timeline_count", 0)),
                    int(row.get("timeline_track_count", 0)), int(row.get("timeline_key_count", 0)), int(row.get("widget_count", 0)),
                    int(row.get("widget_property_count", 0)), int(row.get("widget_binding_count", 0)),
                    int(row.get("widget_animation_count", 0)), int(row.get("widget_animation_binding_count", 0)),
                    int(row.get("graph_count", 0)), json.dumps(row.get("graph_system_counts", {}), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("operation_counts", {}), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(row.get("relation_counts", {}), ensure_ascii=False, separators=(",", ":")), row.get("text", ""),
                ),
            )

        for row in iter_jsonl(output / "rigvm_objects.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO rigvm_objects VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("object_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("kind", ""),
                    row.get("class_path", ""),
                    row.get("name", ""),
                    row.get("outer_object_id", ""),
                    row.get("outer_class", ""),
                    row.get("operation", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "rigvm_properties.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO rigvm_properties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("object_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("kind", ""),
                    row.get("class_path", ""),
                    row.get("declaring_type", ""),
                    row.get("property_name", ""),
                    row.get("property_path", row.get("property_name", "")),
                    row.get("property_type", ""),
                    row.get("cpp_type", ""),
                    row.get("value", ""),
                    row.get("object_path", ""),
                    row.get("object_class", ""),
                    int(row.get("property_flags", 0)),
                    1 if row.get("truncated", False) else 0,
                ),
            )

        for row in iter_jsonl(output / "rigvm_references.jsonl"):
            conn.execute(
                "INSERT OR IGNORE INTO rigvm_references VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("source_object_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("source_kind", ""),
                    row.get("source_class", ""),
                    row.get("property_path", ""),
                    row.get("target_object_id", ""),
                    row.get("target_kind", ""),
                    row.get("target_class", ""),
                ),
            )

        for row in iter_jsonl(output / "rigvm_pins.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO rigvm_pins VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("pin_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("class_path", ""),
                    row.get("name", ""),
                    row.get("outer_object_id", ""),
                    row.get("display_name", ""),
                    row.get("direction", ""),
                    row.get("cpp_type", ""),
                    row.get("cpp_type_object_path", ""),
                    row.get("default_value", ""),
                    row.get("default_value_type", ""),
                    row.get("default_value_object", ""),
                    row.get("custom_widget_name", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "rigvm_links.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO rigvm_links VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row.get("link_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("class_path", ""),
                    row.get("source_pin_path", ""),
                    row.get("target_pin_path", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )

        for row in iter_jsonl(output / "blueprint_edges.jsonl"):
            source_pin_id = row.get("source_pin_id", "")
            target_pin_id = row.get("target_pin_id", "")
            source_node_id, source_pin_name = pin_to_node.get(source_pin_id, ("", ""))
            target_node_id, target_pin_name = pin_to_node.get(target_pin_id, ("", ""))
            conn.execute(
                "INSERT OR IGNORE INTO blueprint_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("blueprint_path", ""),
                    row.get("graph_id", ""),
                    row.get("graph_name", ""),
                    row.get("source_node_id", source_node_id),
                    source_pin_id,
                    row.get("source_pin_name", source_pin_name),
                    row.get("target_node_id", target_node_id),
                    target_pin_id,
                    row.get("target_pin_name", target_pin_name),
                    row.get("pin_category", ""),
                    row.get("edge_kind", "execution" if row.get("pin_category", "") == "exec" else "data"),
                ),
            )


        # Schema 12 world/map canonical facts.
        def compact_json(value) -> str:
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

        for row in iter_jsonl(output / "worlds.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO worlds VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("world_path", ""), row.get("world_name", ""), row.get("package_name", ""),
                    row.get("package_path", ""), row.get("persistent_level_path", ""),
                    1 if row.get("world_partitioned", False) else 0, row.get("world_partition_path", ""),
                    compact_json(row),
                ),
            )

        for row in iter_jsonl(output / "world_levels.jsonl"):
            conn.execute(
                "INSERT INTO world_levels VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("world_path", ""), row.get("level_path", ""), row.get("level_name", ""),
                    row.get("level_package", ""), row.get("level_kind", ""), row.get("streaming_owner_path", ""),
                    row.get("streaming_class", ""), row.get("target_world_package", ""), compact_json(row),
                ),
            )

        for row in iter_jsonl(output / "world_actors.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO world_actors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("actor_path", ""), row.get("world_path", ""), row.get("level_path", ""),
                    row.get("actor_guid", ""), row.get("actor_instance_guid", ""), row.get("actor_name", ""),
                    row.get("actor_label", ""), row.get("actor_class", ""), row.get("archetype_path", ""),
                    row.get("generated_class", ""), row.get("blueprint_asset", ""), row.get("folder", ""),
                    row.get("folder_guid", ""), row.get("attach_parent_actor_path", ""), row.get("attach_parent_socket", ""),
                    row.get("owner_actor_path", ""), row.get("child_actor_parent_path", ""),
                    compact_json(row.get("tags", [])), compact_json(row.get("transform", {})),
                    1 if row.get("spatially_loaded", False) else 0, row.get("runtime_grid", ""),
                    compact_json(row.get("data_layer_instance_names", [])), compact_json(row.get("data_layer_assets", [])),
                    compact_json(row),
                ),
            )

        for row in iter_jsonl(output / "world_components.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO world_components VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("component_path", ""), row.get("world_path", ""), row.get("actor_path", ""),
                    row.get("component_name", ""), row.get("component_class", ""), row.get("archetype_path", ""),
                    int(row.get("creation_method", 0)), compact_json(row.get("tags", [])),
                    1 if row.get("is_scene_component", False) else 0, row.get("attach_parent_component_path", ""),
                    row.get("attach_socket", ""), compact_json(row.get("relative_transform", {})),
                    compact_json(row.get("world_transform", {})), compact_json(row),
                ),
            )

        for row in iter_jsonl(output / "world_instance_properties.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO world_instance_properties VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("world_path", ""), row.get("actor_path", ""), row.get("owner_kind", ""),
                    row.get("owner_path", ""), row.get("owner_class", ""), row.get("baseline_path", ""),
                    row.get("baseline_class", ""), row.get("property_name", ""), row.get("property_path", ""),
                    row.get("property_type", ""), row.get("cpp_type", ""), str(row.get("property_flags", "")),
                    row.get("value", ""), row.get("baseline_value", ""),
                    1 if row.get("value_truncated", False) else 0,
                    1 if row.get("baseline_value_truncated", False) else 0,
                    compact_json(row),
                ),
            )

        for row in iter_jsonl(output / "world_references.jsonl"):
            conn.execute(
                "INSERT OR IGNORE INTO world_references VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("world_path", ""), row.get("actor_path", ""), row.get("owner_kind", ""),
                    row.get("owner_path", ""), row.get("root_property", ""), row.get("property_path", ""),
                    row.get("reference_kind", ""), row.get("target_path", ""), row.get("target_class", ""),
                    row.get("target_kind", ""), 1 if row.get("authored_override", False) else 0,
                    compact_json(row),
                ),
            )

        for row in iter_jsonl(output / "world_data_layers.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO world_data_layers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("instance_path", ""), row.get("world_path", ""), row.get("instance_name", ""),
                    row.get("data_layer_name", ""), row.get("full_name", ""), row.get("short_name", ""),
                    row.get("parent_instance_path", ""), 1 if row.get("runtime", False) else 0,
                    1 if row.get("initially_loaded_in_editor", False) else 0,
                    1 if row.get("initially_visible", False) else 0,
                    row.get("asset_path", ""), row.get("asset_class", ""), compact_json(row),
                ),
            )

        for row in iter_jsonl(output / "world_partition_actor_descs.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO world_partition_actor_descs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("world_path", ""), row.get("actor_guid", ""), row.get("actor_name", ""),
                    row.get("actor_label", ""), row.get("actor_package", ""), row.get("actor_soft_path", ""),
                    row.get("native_class", ""), row.get("folder", ""), row.get("folder_guid", ""),
                    row.get("parent_actor_guid", ""), compact_json(row.get("transform", {})),
                    compact_json(row.get("editor_bounds", {})), 1 if row.get("spatially_loaded", False) else 0,
                    1 if row.get("editor_only", False) else 0, 1 if row.get("runtime_only", False) else 0,
                    1 if row.get("hlod_relevant", False) else 0,
                    compact_json(row.get("data_layer_instance_names", [])),
                    compact_json(row.get("actor_reference_guids", [])), compact_json(row.get("tags", [])),
                    row.get("runtime_grid", ""), compact_json(row.get("runtime_bounds", {})), compact_json(row),
                ),
            )

        conn.commit()
    finally:
        conn.close()
    return db_path


def newest_project_log(project: Path) -> Path | None:
    logs_dir = project.parent / "Saved" / "Logs"
    if not logs_dir.is_dir():
        return None
    logs = [path for path in logs_dir.glob("*.log") if path.is_file()]
    if not logs:
        return None
    try:
        return max(logs, key=lambda path: path.stat().st_mtime_ns)
    except OSError:
        return None



WORLD_COMPLETION_COUNT_FILES = {
    "worlds.jsonl": "worlds",
    "world_levels.jsonl": "levels",
    "world_actors.jsonl": "actors",
    "world_components.jsonl": "components",
    "world_instance_properties.jsonl": "instance_overrides",
    "world_references.jsonl": "references",
    "world_data_layers.jsonl": "data_layers",
    "world_partition_actor_descs.jsonl": "world_partition_actor_descs",
}


def _json_object(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _nonblank_line_count(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def world_pass_completion_error(output: Path) -> str | None:
    """Return None only when a nonzero editor exit happened after canonical completion.

    scan() deletes these manifests before launching the current invocation, so
    their presence here cannot be satisfied by an older successful run.
    """
    output = Path(output)

    structural = _json_object(output / "manifest.json")
    if structural is None:
        return "current structural manifest is missing or invalid"
    if int(structural.get("schema_version", 0) or 0) != 13:
        return (
            "current structural manifest is not schema 13: "
            f"{structural.get('schema_version')!r}"
        )

    world = _json_object(output / "world_manifest.json")
    if world is None:
        return "current world manifest is missing or invalid"
    if int(world.get("schema_version", 0) or 0) != 12:
        return f"current world manifest is not schema 12: {world.get('schema_version')!r}"
    if int(world.get("structural_schema_baseline", 0) or 0) != 13:
        return (
            "world structural baseline mismatch: "
            f"{world.get('structural_schema_baseline')!r}"
        )

    declared_files = world.get("files", [])
    if not isinstance(declared_files, list):
        return "world manifest files list is invalid"
    declared = {str(name) for name in declared_files}
    counts = world.get("counts", {})
    if not isinstance(counts, dict):
        return "world manifest counts object is invalid"

    for filename, count_name in WORLD_COMPLETION_COUNT_FILES.items():
        if filename not in declared:
            return f"world manifest does not declare {filename}"
        path = output / filename
        if not path.is_file():
            return f"world output is missing {filename}"
        try:
            expected = int(counts.get(count_name, -1))
            actual = _nonblank_line_count(path)
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            return f"could not validate {filename}: {exc}"
        if expected < 0:
            return f"world manifest is missing count {count_name}"
        if actual != expected:
            return (
                f"world output count mismatch for {filename}: "
                f"rows={actual} manifest={expected}"
            )

    for filename in ("vfx_manifest.json", "systems_manifest.json"):
        sidecar = _json_object(output / filename)
        if sidecar is None:
            return f"current {filename} is missing or invalid"
        if not bool(sidecar.get("success", False)):
            return f"current {filename} reports failure"

    return None


def report_editor_failure(project: Path, returncode: int) -> None:
    print(
        f"ERROR: Unreal editor exited with code {returncode} before UnrealAssetTool completed.",
        file=sys.stderr,
    )
    latest_log = newest_project_log(project)
    if latest_log is not None:
        print(f"latest Unreal log: {latest_log}", file=sys.stderr)


DEFAULT_BUNDLE_FILES = (
    "manifest.json",
    "world_manifest.json",
    "worlds.jsonl",
    "world_levels.jsonl",
    "world_actors.jsonl",
    "world_components.jsonl",
    "world_instance_properties.jsonl",
    "world_references.jsonl",
    "world_data_layers.jsonl",
    "world_partition_actor_descs.jsonl",
    "files.jsonl",
    "source_chunks.jsonl",
    "native_manifest.json",
    "native_modules.jsonl",
    "native_types.jsonl",
    "native_interfaces.jsonl",
    "native_functions.jsonl",
    "native_function_parameters.jsonl",
    "native_properties.jsonl",
    "native_enums.jsonl",
    "native_enum_values.jsonl",
    "assets.jsonl",
    "asset_dependencies.jsonl",
    "behavior_trees.jsonl",
    "behavior_tree_nodes.jsonl",
    "behavior_tree_edges.jsonl",
    "blackboards.jsonl",
    "blackboard_keys.jsonl",
    "eqs_queries.jsonl",
    "eqs_options.jsonl",
    "eqs_generators.jsonl",
    "eqs_tests.jsonl",
    "statetrees.jsonl",
    "statetree_states.jsonl",
    "statetree_nodes.jsonl",
    "statetree_transitions.jsonl",
    "statetree_bindings.jsonl",
    "ai_properties.jsonl",
    "ai_relations.jsonl",
    "ai_summaries.jsonl",
    "pcg_graphs.jsonl",
    "pcg_nodes.jsonl",
    "pcg_pins.jsonl",
    "pcg_edges.jsonl",
    "pcg_properties.jsonl",
    "pcg_parameters.jsonl",
    "materials.jsonl",
    "material_expressions.jsonl",
    "material_edges.jsonl",
    "material_properties.jsonl",
    "material_parameters.jsonl",
    "visual_relations.jsonl",
    "pcg_graph_context.jsonl",
    "material_graph_context.jsonl",
    "visual_summaries.jsonl",
    "blueprints.jsonl",
    "blueprint_graphs.jsonl",
    "blueprint_nodes.jsonl",
    "blueprint_pins.jsonl",
    "blueprint_edges.jsonl",
    "blueprint_interfaces.jsonl",
    "blueprint_node_properties.jsonl",
    "blueprint_node_references.jsonl",
    "blueprint_bindings.jsonl",
    "blueprint_defaults.jsonl",
    "blueprint_component_properties.jsonl",
    "blueprint_state_values.jsonl",
    "blueprint_timelines.jsonl",
    "blueprint_timeline_tracks.jsonl",
    "blueprint_timeline_keys.jsonl",
    "blueprint_widgets.jsonl",
    "blueprint_widget_properties.jsonl",
    "blueprint_widget_bindings.jsonl",
    "blueprint_widget_animations.jsonl",
    "blueprint_widget_animation_bindings.jsonl",
    "blueprint_functions.jsonl",
    "blueprint_events.jsonl",
    "blueprint_call_edges.jsonl",
    "blueprint_call_bindings.jsonl",
    "blueprint_data_dependencies.jsonl",
    "blueprint_execution_blocks.jsonl",
    "blueprint_execution_block_edges.jsonl",
    "blueprint_execution_roots.jsonl",
    "anim_state_machines.jsonl",
    "anim_states.jsonl",
    "anim_transitions.jsonl",
    "blueprint_relations.jsonl",
    "blueprint_graph_context.jsonl",
    "blueprint_summaries.jsonl",
    "rigvm_editor_links.jsonl",
    "rigvm_objects.jsonl",
    "rigvm_pins.jsonl",
    "rigvm_links.jsonl",
    "rigvm_references.jsonl",
)


def create_upload_bundle(
    output: Path,
    destination: Path | None = None,
    *,
    include_raw_rigvm: bool = False,
) -> Path:
    output = output.resolve()
    if destination is None:
        destination = output / "uatool-upload.zip"
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    names = list(DEFAULT_BUNDLE_FILES)
    if include_raw_rigvm:
        names.append("rigvm_properties.jsonl")

    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
    ) as archive:
        for name in names:
            path = output / name
            if path.is_file():
                archive.write(path, arcname=name)

    return destination


def scan(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Not a .uproject file: {project}")

    output = Path(args.output).expanduser() if args.output else project.parent / ".uatool"
    if not output.is_absolute():
        output = (project.parent / output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    # A failed run must never be mistaken for a successful fresh scan simply
    # because manifest.json was left behind by an older invocation.
    manifest_path = output / "manifest.json"
    world_manifest_path = output / "world_manifest.json"
    vfx_manifest_path = output / "vfx_manifest.json"
    systems_manifest_path = output / "systems_manifest.json"
    native_manifest_path = output / "native_manifest.json"
    for stale_manifest in (
        manifest_path,
        world_manifest_path,
        vfx_manifest_path,
        systems_manifest_path,
        native_manifest_path,
    ):
        if stale_manifest.exists():
            stale_manifest.unlink()

    editor = require_editor(args.editor)

    command = [
        str(editor),
        str(project),
        "-run=UnrealAssetTool",
        f"-Output={output}",
        f"-EnablePlugins={MODULE_NAME}",
        "-unattended",
        "-RUNNINGUNATTENDEDSCRIPT",
        "-nop4",
        "-nosplash",
        "-NoShaderCompile",
        "-stdout",
        "-FullStdOutLogOutput",
        "-forcelogflush",
    ]
    if args.include_generated:
        command.append("-IncludeGenerated")
    if args.include_engine:
        command.append("-IncludeEngine")
    if args.include_self:
        command.append("-IncludeSelf")
    if args.include_raw_rigvm_properties:
        command.append("-IncludeRawRigVMProperties")

    world_command = [
        str(editor),
        str(project),
        "-run=UnrealAssetToolWorld",
        f"-Output={output}",
        f"-EnablePlugins={MODULE_NAME}",
        "-unattended",
        "-RUNNINGUNATTENDEDSCRIPT",
        "-nop4",
        "-nosplash",
        "-nullrhi",
        "-NoShaderCompile",
        "-stdout",
        "-FullStdOutLogOutput",
        "-forcelogflush",
    ]

    with stage_invoking_plugin_checkout(project) as active_plugin_root:
        ensure_plugin_binary(
            project,
            editor,
            args.build_script,
            args.no_build,
            active_plugin_root,
        )

        print("running structural pass:", subprocess.list2cmdline(command))
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            report_editor_failure(project, result.returncode)
            return result.returncode

        native_error = native_cpp.validation_error(output)
        if native_error:
            print(f"ERROR: native C++ pass incomplete: {native_error}", file=sys.stderr)
            latest_log = newest_project_log(project)
            if latest_log is not None:
                print(f"latest Unreal log: {latest_log}", file=sys.stderr)
            return 24

        print("running world pass:", subprocess.list2cmdline(world_command))
        world_result = subprocess.run(world_command, check=False)
        if world_result.returncode != 0:
            completion_error = world_pass_completion_error(output)
            if completion_error:
                print(
                    f"ERROR: Unreal world pass exited with code {world_result.returncode}: "
                    f"{completion_error}.",
                    file=sys.stderr,
                )
                report_editor_failure(project, world_result.returncode)
                return world_result.returncode
            print(
                "WARNING: Unreal editor exited nonzero after the current world/VFX/systems "
                f"canonical outputs had completed and reconciled (code {world_result.returncode}); "
                "continuing through normal validators to recover a post-completion teardown crash.",
                file=sys.stderr,
            )
            latest_log = newest_project_log(project)
            if latest_log is not None:
                print(f"latest Unreal log: {latest_log}", file=sys.stderr)

    if not manifest_path.is_file():
        print(
            "ERROR: Unreal exited successfully but UnrealAssetTool did not write manifest.json. "
            "The commandlet was not completed, so no database will be packed.",
            file=sys.stderr,
        )
        latest_log = newest_project_log(project)
        if latest_log is not None:
            print(f"latest Unreal log: {latest_log}", file=sys.stderr)
        return 20

    if not world_manifest_path.is_file():
        print(
            "ERROR: Unreal exited successfully but UnrealAssetToolWorld did not write world_manifest.json. "
            "The world pass was not completed, so no database will be packed.",
            file=sys.stderr,
        )
        latest_log = newest_project_log(project)
        if latest_log is not None:
            print(f"latest Unreal log: {latest_log}", file=sys.stderr)
        return 21

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        world_manifest = json.loads(world_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: could not read schema manifests: {exc}", file=sys.stderr)
        return 22

    structural_schema = int(manifest.get("schema_version", 0) or 0)
    world_schema = int(world_manifest.get("schema_version", 0) or 0)
    world_structural_baseline = int(world_manifest.get("structural_schema_baseline", 0) or 0)
    if structural_schema != 13 or world_schema != 12 or world_structural_baseline != structural_schema:
        print(
            "ERROR: structural-schema-13/world-schema-12 pass mismatch: "
            f"structural={structural_schema} world={world_schema} "
            f"world_structural_baseline={world_structural_baseline}",
            file=sys.stderr,
        )
        return 23

    native_manifest = native_cpp.read_manifest(output) or {}
    manifest["native_schema_version"] = int(
        native_manifest.get("schema_version", 0) or 0
    )
    manifest["native_counts"] = native_manifest.get("counts", {})
    manifest["native_files"] = native_manifest.get("files", [])
    manifest["native_pass"] = native_manifest.get("pass", native_cpp.PASS_NAME)

    manifest["world_schema_version"] = world_schema
    manifest["world_counts"] = world_manifest.get("counts", {})
    manifest["world_files"] = world_manifest.get("files", [])
    manifest["world_pass"] = world_manifest.get("pass", "UnrealAssetToolWorld")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    derived_counts = derive_output(output)
    print("derived:", ", ".join(f"{key}={value}" for key, value in derived_counts.items()))
    db_path = build_database(output)
    print(f"database: {db_path}")
    bundle_path = None
    if not args.no_bundle:
        bundle_path = create_upload_bundle(
            output,
            project.parent / f"{project.stem}.uatool.zip",
            include_raw_rigvm=args.bundle_include_raw_rigvm,
        )
        print(f"upload bundle: {bundle_path}")

    structural_counts = manifest.get("counts", {}) if isinstance(manifest, dict) else {}
    world_counts = world_manifest.get("counts", {}) if isinstance(world_manifest, dict) else {}
    native_counts = native_manifest.get("counts", {}) if isinstance(native_manifest, dict) else {}

    def count_line(counts: dict, names: tuple[str, ...]) -> str:
        return " ".join(f"{name}={counts.get(name, 0)}" for name in names)

    print()
    print("=== UATOOL FINAL SUMMARY ===")
    print("structural scan complete: " + count_line(structural_counts, ("files", "assets", "blueprints", "blueprint_graphs", "blueprint_nodes", "blueprint_pins", "blueprint_edges")))
    print("world scan complete: " + count_line(world_counts, ("worlds", "levels", "streaming_relationships", "actors", "components", "instance_overrides", "references", "data_layers", "world_partition_worlds", "world_partition_initialized_for_scan", "world_partition_actor_descs")))
    print("native C++ scan complete: " + count_line(native_counts, ("modules", "loaded_modules", "classes", "structs", "functions", "function_parameters", "properties", "enums", "enum_values")))
    print("derived complete: " + count_line(derived_counts, ("blueprint_call_bindings", "blueprint_data_dependencies", "blueprint_relations", "ai_relations", "visual_relations")))
    print(f"schemas: structural={manifest.get('schema_version', 0)} native={manifest.get('native_schema_version', 0)} world={world_manifest.get('schema_version', 0)} derived={manifest.get('derived_schema_version', 0)}")
    print(f"database: {db_path}")
    if bundle_path is not None:
        print(f"upload bundle: {bundle_path}")
    print("============================")
    return 0


def build(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Not a .uproject file: {project}")
    editor = require_editor(args.editor)
    with stage_invoking_plugin_checkout(project) as active_plugin_root:
        return build_project(project, editor, args.build_script, active_plugin_root)


def pack(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    derive_output(output)
    db_path = build_database(output)
    print(db_path)
    return 0


def derive(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    counts = derive_output(output)
    print(", ".join(f"{key}={value}" for key, value in counts.items()))
    return 0


def bundle(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
    derive_output(output)
    destination = Path(args.destination).expanduser() if args.destination else None
    bundle_path = create_upload_bundle(
        output,
        destination,
        include_raw_rigvm=args.include_raw_rigvm,
    )
    print(bundle_path)
    return 0


def _print_rows(rows: Iterable[sqlite3.Row], fields: tuple[str, ...]) -> None:
    for row in rows:
        print(" | ".join(str(row[field]) for field in fields))


def query(args: argparse.Namespace) -> int:
    root = Path(args.output).expanduser().resolve()
    db_path = root if root.suffix.lower() == ".db" else root / DB_NAME
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    term = args.term
    limit = args.limit

    try:
        print("[AI summaries]")
        rows = conn.execute(
            """
            SELECT asset_path, system, asset_class, substr(text,1,1200) AS text
            FROM ai_summaries
            WHERE asset_path LIKE ? OR system LIKE ? OR asset_class LIKE ? OR text LIKE ?
            LIMIT ?
            """, (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit))
        _print_rows(rows, ("asset_path", "system", "asset_class", "text"))

        print("\n[AI relations]")
        rows = conn.execute(
            """
            SELECT asset_path, system, source_kind, relation, target_kind, target
            FROM ai_relations
            WHERE asset_path LIKE ? OR source_id LIKE ? OR relation LIKE ? OR target LIKE ? OR detail_json LIKE ?
            LIMIT ?
            """, (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit))
        _print_rows(rows, ("asset_path", "system", "source_kind", "relation", "target_kind", "target"))

        print("\n[Behavior Tree nodes]")
        rows = conn.execute(
            """SELECT behavior_tree_path, node_kind, class_name, display_name, attached_to
               FROM behavior_tree_nodes
               WHERE behavior_tree_path LIKE ? OR node_kind LIKE ? OR class_path LIKE ? OR display_name LIKE ? OR name LIKE ?
               LIMIT ?""", (f"%{term}%",)*5 + (limit,))
        _print_rows(rows, ("behavior_tree_path", "node_kind", "class_name", "display_name", "attached_to"))

        print("\n[Blackboard keys]")
        rows = conn.execute(
            """SELECT blackboard_path, name, key_type_class, instance_synced
               FROM blackboard_keys WHERE blackboard_path LIKE ? OR name LIKE ? OR key_type_class LIKE ? OR raw_value LIKE ? LIMIT ?""",
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit))
        _print_rows(rows, ("blackboard_path", "name", "key_type_class", "instance_synced"))

        print("\n[EQS generators/tests]")
        rows = conn.execute(
            """SELECT eqs_path, 'generator' AS kind, class_name AS name, item_type AS detail FROM eqs_generators
               WHERE eqs_path LIKE ? OR class_path LIKE ? OR class_name LIKE ? OR item_type LIKE ?
               UNION ALL
               SELECT eqs_path, 'test', class_name, test_purpose || ' ' || filter_type || ' ' || scoring_equation FROM eqs_tests
               WHERE eqs_path LIKE ? OR class_path LIKE ? OR class_name LIKE ? OR test_purpose LIKE ?
               LIMIT ?""",
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit))
        _print_rows(rows, ("eqs_path", "kind", "name", "detail"))

        print("\n[StateTree states/nodes]")
        rows = conn.execute(
            """SELECT statetree_path, 'state' AS kind, name, state_type AS detail FROM statetree_states
               WHERE statetree_path LIKE ? OR name LIKE ? OR description LIKE ? OR state_type LIKE ? OR tag LIKE ?
               UNION ALL
               SELECT statetree_path, role, instance_object_class, substr(raw_node,1,300) FROM statetree_nodes
               WHERE statetree_path LIKE ? OR role LIKE ? OR instance_object_class LIKE ? OR raw_node LIKE ? OR raw_instance LIKE ?
               LIMIT ?""",
            (f"%{term}%",)*10 + (limit,))
        _print_rows(rows, ("statetree_path", "kind", "name", "detail"))

        print("\n[AI object properties]")
        rows = conn.execute(
            """SELECT asset_path, system, owner_kind, property_name, object_path, substr(value,1,300) AS value
               FROM ai_properties WHERE asset_path LIKE ? OR owner_class LIKE ? OR property_name LIKE ? OR value LIKE ? OR object_path LIKE ? LIMIT ?""",
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit))
        _print_rows(rows, ("asset_path", "system", "owner_kind", "property_name", "object_path", "value"))

        print("\n[PCG graphs/nodes]")
        rows = conn.execute(
            """SELECT n.pcg_path, n.node_name, n.settings_class, n.node_title, n.node_id
               FROM pcg_nodes n
               WHERE n.pcg_path LIKE ? OR n.node_id LIKE ? OR n.node_name LIKE ? OR n.node_title LIKE ? OR n.settings_class LIKE ?
               LIMIT ?""",
            (f"%{term}%",)*5 + (limit,))
        _print_rows(rows, ("pcg_path", "node_name", "settings_class", "node_title", "node_id"))

        print("\n[PCG parameters]")
        rows = conn.execute(
            """SELECT pcg_path, owner_kind, property_name, substr(value,1,400) AS value, object_path
               FROM pcg_parameters WHERE pcg_path LIKE ? OR property_name LIKE ? OR value LIKE ? OR object_path LIKE ? LIMIT ?""",
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit))
        _print_rows(rows, ("pcg_path", "owner_kind", "property_name", "value", "object_path"))

        print("\n[Material expressions/parameters]")
        rows = conn.execute(
            """SELECT material_path, expression_class, parameter_name, function_path, texture_path, expression_id
               FROM material_expressions
               WHERE material_path LIKE ? OR expression_class LIKE ? OR parameter_name LIKE ? OR function_path LIKE ? OR texture_path LIKE ? OR expression_id LIKE ?
               LIMIT ?""",
            (f"%{term}%",)*6 + (limit,))
        _print_rows(rows, ("material_path", "expression_class", "parameter_name", "function_path", "texture_path", "expression_id"))

        print("\n[Visual relations]")
        rows = conn.execute(
            """SELECT system, asset_path, source_kind, relation, target_kind, target
               FROM visual_relations
               WHERE system LIKE ? OR asset_path LIKE ? OR source_id LIKE ? OR relation LIKE ? OR target LIKE ? OR detail_json LIKE ?
               LIMIT ?""",
            (f"%{term}%",)*6 + (limit,))
        _print_rows(rows, ("system", "asset_path", "source_kind", "relation", "target_kind", "target"))

        print("\n[PCG/material graph context]")
        rows = conn.execute(
            """SELECT pcg_path AS asset_path, 'pcg' AS system, substr(text,1,1200) AS text FROM pcg_graph_context
               WHERE pcg_path LIKE ? OR text LIKE ?
               UNION ALL
               SELECT material_path, 'material', substr(text,1,1200) FROM material_graph_context
               WHERE material_path LIKE ? OR text LIKE ?
               LIMIT ?""",
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit))
        _print_rows(rows, ("asset_path", "system", "text"))

        print("\n[blueprint summaries]")
        rows = conn.execute(
            """
            SELECT blueprint_path, parent_class, substr(text, 1, 800) AS text
            FROM blueprint_summaries
            WHERE blueprint_path LIKE ? OR name LIKE ? OR parent_class LIKE ? OR generated_class LIKE ? OR text LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "parent_class", "text"))

        print("\n[blueprint graph context]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, graph_system, substr(text, 1, 1200) AS text
            FROM blueprint_graph_context
            WHERE blueprint_path LIKE ? OR graph_name LIKE ? OR graph_path LIKE ? OR text LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "graph_name", "graph_system", "text"))

        print("\n[blueprint call graph]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, target_name, target_owner, resolution,
                   target_blueprint_path, pure, latent
            FROM blueprint_call_edges
            WHERE blueprint_path LIKE ? OR graph_name LIKE ? OR target_name LIKE ? OR target_owner LIKE ?
               OR target_blueprint_path LIKE ? OR target_function LIKE ? OR resolution LIKE ?
            LIMIT ?
            """,
            (f"%{term}%",)*7 + (limit,),
        )
        _print_rows(rows, ("blueprint_path", "graph_name", "target_name", "target_owner", "resolution", "target_blueprint_path", "pure", "latent"))

        print("\n[blueprint call bindings]")
        rows = conn.execute(
            """
            SELECT caller_blueprint_path, direction, call_pin_name, parameter_name, match_kind,
                   target_blueprint_path, target_function_id, split_suffix
            FROM blueprint_call_bindings
            WHERE caller_blueprint_path LIKE ? OR call_pin_name LIKE ? OR parameter_name LIKE ?
               OR target_blueprint_path LIKE ? OR target_function_id LIKE ? OR split_suffix LIKE ?
            LIMIT ?
            """,
            (f"%{term}%",)*6 + (limit,),
        )
        _print_rows(rows, ("caller_blueprint_path", "direction", "call_pin_name", "parameter_name",
                           "match_kind", "target_blueprint_path", "target_function_id", "split_suffix"))

        print("\n[blueprint data dependencies]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, sink_operation, sink_label, sink_pin_name,
                   expression_node_count, truncated, cycle, substr(text,1,1400) AS text
            FROM blueprint_data_dependencies
            WHERE blueprint_path LIKE ? OR graph_name LIKE ? OR sink_operation LIKE ? OR sink_label LIKE ?
               OR sink_pin_name LIKE ? OR variable_reads_json LIKE ? OR function_calls_json LIKE ?
               OR object_refs_json LIKE ? OR text LIKE ?
            LIMIT ?
            """,
            (f"%{term}%",)*9 + (limit,),
        )
        _print_rows(rows, ("blueprint_path", "graph_name", "sink_operation", "sink_label", "sink_pin_name",
                           "expression_node_count", "truncated", "cycle", "text"))

        print("\n[blueprint execution blocks]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, block_index, node_count, entry_node_id, exit_node_id, substr(text,1,1200) AS text
            FROM blueprint_execution_blocks
            WHERE blueprint_path LIKE ? OR graph_name LIKE ? OR text LIKE ? OR operations_json LIKE ? OR labels_json LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "graph_name", "block_index", "node_count", "entry_node_id", "exit_node_id", "text"))

        print("\n[AnimBP state machines]")
        rows = conn.execute(
            """
            SELECT blueprint_path, name, entry_state, state_count, transition_count, machine_graph_id
            FROM anim_state_machines
            WHERE blueprint_path LIKE ? OR name LIKE ? OR entry_state LIKE ? OR editor_graph_path LIKE ? OR machine_graph_id LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "name", "entry_state", "state_count", "transition_count", "machine_graph_id"))

        print("\n[AnimBP transitions]")
        rows = conn.execute(
            """
            SELECT blueprint_path, machine_name, previous_state, next_state, crossfade_duration,
                   automatic_rule, disabled, rule_graph
            FROM anim_transitions
            WHERE blueprint_path LIKE ? OR machine_name LIKE ? OR previous_state LIKE ? OR next_state LIKE ?
               OR shared_rules_name LIKE ? OR rule_graph LIKE ?
            LIMIT ?
            """,
            (f"%{term}%",)*6 + (limit,),
        )
        _print_rows(rows, ("blueprint_path", "machine_name", "previous_state", "next_state", "crossfade_duration", "automatic_rule", "disabled", "rule_graph"))

        print("\n[blueprint relations]")
        rows = conn.execute(
            """
            SELECT blueprint_path, relation, source_id, target_kind, target, owner
            FROM blueprint_relations
            WHERE relation LIKE ? OR source_id LIKE ? OR target LIKE ? OR owner LIKE ? OR detail_json LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "relation", "source_id", "target_kind", "target", "owner"))

        print("[blueprint graphs]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, graph_kind, graph_system, graph_class
            FROM blueprint_graphs
            WHERE graph_name LIKE ? OR graph_path LIKE ? OR graph_kind LIKE ?
               OR graph_system LIKE ? OR graph_class LIKE ? OR schema_class LIKE ?
            LIMIT ?
            """,
            (
                f"%{term}%", f"%{term}%", f"%{term}%",
                f"%{term}%", f"%{term}%", f"%{term}%", limit,
            ),
        )
        _print_rows(rows, ("blueprint_path", "graph_name", "graph_kind", "graph_system", "graph_class"))

        print("[blueprint nodes]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, operation, symbol, owner, title
            FROM blueprint_nodes
            WHERE title LIKE ? OR comment LIKE ? OR node_class LIKE ?
               OR operation LIKE ? OR symbol LIKE ? OR owner LIKE ?
            LIMIT ?
            """,
            (
                f"%{term}%", f"%{term}%", f"%{term}%",
                f"%{term}%", f"%{term}%", f"%{term}%", limit,
            ),
        )
        _print_rows(rows, ("blueprint_path", "graph_name", "operation", "symbol", "owner", "title"))

        print("\n[blueprint pins]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, node_id, name, direction, pin_category,
                   default_value, default_object
            FROM blueprint_pins
            WHERE name LIKE ? OR pin_category LIKE ? OR pin_subcategory LIKE ?
               OR pin_subcategory_object LIKE ? OR default_value LIKE ? OR default_object LIKE ?
            LIMIT ?
            """,
            (
                f"%{term}%", f"%{term}%", f"%{term}%",
                f"%{term}%", f"%{term}%", f"%{term}%", limit,
            ),
        )
        _print_rows(
            rows,
            ("blueprint_path", "graph_name", "node_id", "name", "direction", "pin_category", "default_value", "default_object"),
        )

        print("\n[blueprint interfaces]")
        rows = conn.execute(
            """
            SELECT blueprint_path, interface_class, interface_name
            FROM blueprint_interfaces
            WHERE interface_class LIKE ? OR interface_name LIKE ? OR graphs_json LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "interface_class", "interface_name"))

        print("\n[blueprint variables]")
        rows = conn.execute(
            """
            SELECT blueprint_path, name, category, default_value, type_json
            FROM blueprint_variables
            WHERE name LIKE ? OR category LIKE ? OR default_value LIKE ? OR type_json LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "name", "category", "default_value", "type_json"))

        print("\n[blueprint components]")
        rows = conn.execute(
            """
            SELECT blueprint_path, variable_name, component_class,
                   parent_component_or_variable, attach_to, is_root
            FROM blueprint_components
            WHERE variable_name LIKE ? OR component_class LIKE ? OR template_path LIKE ?
               OR parent_component_or_variable LIKE ? OR parent_owner_class LIKE ? OR attach_to LIKE ?
            LIMIT ?
            """,
            (
                f"%{term}%", f"%{term}%", f"%{term}%",
                f"%{term}%", f"%{term}%", f"%{term}%", limit,
            ),
        )
        _print_rows(
            rows,
            ("blueprint_path", "variable_name", "component_class", "parent_component_or_variable", "attach_to", "is_root"),
        )

        print("\n[blueprint defaults]")
        rows = conn.execute(
            """
            SELECT blueprint_path, property_name, cpp_type, referenced_object_path, substr(value,1,240) AS value
            FROM blueprint_defaults
            WHERE property_name LIKE ? OR cpp_type LIKE ? OR value LIKE ? OR parent_value LIKE ? OR referenced_object_path LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "property_name", "cpp_type", "referenced_object_path", "value"))

        print("\n[component overrides]")
        rows = conn.execute(
            """
            SELECT blueprint_path, component_name, property_name, referenced_object_path, substr(value,1,240) AS value
            FROM blueprint_component_properties
            WHERE component_name LIKE ? OR component_class LIKE ? OR property_name LIKE ? OR value LIKE ? OR referenced_object_path LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "component_name", "property_name", "referenced_object_path", "value"))

        print("\n[flattened blueprint state]")
        rows = conn.execute(
            """
            SELECT blueprint_path, owner_kind, owner_name, property_path, cpp_type,
                   referenced_object_path, substr(value,1,240) AS value
            FROM blueprint_state_values
            WHERE owner_name LIKE ? OR owner_class LIKE ? OR property_path LIKE ? OR cpp_type LIKE ?
               OR value LIKE ? OR referenced_object_path LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "owner_kind", "owner_name", "property_path", "cpp_type", "referenced_object_path", "value"))

        print("\n[blueprint functions]")
        rows = conn.execute(
            """
            SELECT blueprint_path, name, resolved_function, blueprint_pure, const_function, blueprint_callable, has_exec, inputs_json, outputs_json
            FROM blueprint_functions
            WHERE name LIKE ? OR resolved_function LIKE ? OR owner LIKE ?
               OR inputs_json LIKE ? OR outputs_json LIKE ? OR locals_json LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "name", "resolved_function", "blueprint_pure", "const_function", "blueprint_callable", "has_exec", "inputs_json", "outputs_json"))

        print("\n[blueprint events]")
        rows = conn.execute(
            """
            SELECT blueprint_path, event_kind, name, component_name, delegate_name, delegate_owner, input_name
            FROM blueprint_events
            WHERE event_kind LIKE ? OR name LIKE ? OR component_name LIKE ? OR delegate_name LIKE ?
               OR delegate_owner LIKE ? OR input_name LIKE ? OR parameters_json LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "event_kind", "name", "component_name", "delegate_name", "delegate_owner", "input_name"))

        print("\n[timelines]")
        rows = conn.execute(
            """
            SELECT blueprint_path, timeline_name, length, auto_play, loop, update_function, finished_function
            FROM blueprint_timelines
            WHERE timeline_name LIKE ? OR update_function LIKE ? OR finished_function LIKE ? OR direction_property LIKE ? OR json LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "timeline_name", "length", "auto_play", "loop", "update_function", "finished_function"))

        print("\n[timeline keys]")
        rows = conn.execute(
            """
            SELECT blueprint_path, timeline_name, track_name, channel_name, key_index, time, value, interp_mode
            FROM blueprint_timeline_keys
            WHERE timeline_name LIKE ? OR track_name LIKE ? OR channel_name LIKE ? OR curve_path LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "timeline_name", "track_name", "channel_name", "key_index", "time", "value", "interp_mode"))

        print("\n[widgets]")
        rows = conn.execute(
            """
            SELECT blueprint_path, widget_name, widget_class, parent_widget_path, slot_class
            FROM blueprint_widgets
            WHERE widget_name LIKE ? OR widget_class LIKE ? OR parent_widget_path LIKE ? OR properties_json LIKE ? OR slot_properties_json LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "widget_name", "widget_class", "parent_widget_path", "slot_class"))

        print("\n[widget properties]")
        rows = conn.execute(
            """
            SELECT blueprint_path, owner_kind, owner_name, property_path, cpp_type, referenced_object_path,
                   substr(value,1,240) AS value
            FROM blueprint_widget_properties
            WHERE owner_name LIKE ? OR owner_class LIKE ? OR property_path LIKE ? OR cpp_type LIKE ?
               OR value LIKE ? OR referenced_object_path LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "owner_kind", "owner_name", "property_path", "cpp_type", "referenced_object_path", "value"))

        print("\n[widget animation bindings]")
        rows = conn.execute(
            """
            SELECT blueprint_path, animation_name, widget_name, slot_widget_name, animation_guid
            FROM blueprint_widget_animation_bindings
            WHERE animation_name LIKE ? OR widget_name LIKE ? OR slot_widget_name LIKE ? OR dynamic_binding LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "animation_name", "widget_name", "slot_widget_name", "animation_guid"))

        print("\n[blueprint node properties]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, property_path, cpp_type, object_path,
                   substr(value, 1, 240) AS value
            FROM blueprint_node_properties
            WHERE property_name LIKE ? OR property_path LIKE ? OR cpp_type LIKE ?
               OR value LIKE ? OR object_path LIKE ? OR object_class LIKE ?
               OR declaring_type LIKE ? OR node_class LIKE ?
            LIMIT ?
            """,
            (
                f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%",
                f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit,
            ),
        )
        _print_rows(
            rows,
            ("blueprint_path", "graph_name", "property_path", "cpp_type", "object_path", "value"),
        )

        print("\n[blueprint node references]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, property_path, target_object_path, target_class
            FROM blueprint_node_references
            WHERE property_path LIKE ? OR target_object_path LIKE ? OR target_class LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(
            rows,
            ("blueprint_path", "graph_name", "property_path", "target_object_path", "target_class"),
        )

        print("\n[blueprint bindings]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, target_property, access_path, binding_key
            FROM blueprint_bindings
            WHERE binding_key LIKE ? OR target_property LIKE ? OR access_path LIKE ?
               OR compiled_context LIKE ? OR pin_type LIKE ? OR promoted_pin_type LIKE ?
               OR raw_value LIKE ? OR node_class LIKE ?
            LIMIT ?
            """,
            (
                f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%",
                f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit,
            ),
        )
        _print_rows(
            rows,
            ("blueprint_path", "graph_name", "target_property", "access_path", "binding_key"),
        )

        print("\n[control rig editor -> RigVM]")
        rows = conn.execute(
            """
            SELECT blueprint_path, graph_name, model_node_path, status, rigvm_operation, resolved_function_name
            FROM rigvm_editor_links
            WHERE model_node_path LIKE ? OR rigvm_object_id LIKE ? OR rigvm_operation LIKE ? OR resolved_function_name LIKE ? OR template_notation LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "graph_name", "model_node_path", "status", "rigvm_operation", "resolved_function_name"))

        print("\n[rigvm objects]")
        rows = conn.execute(
            """
            SELECT blueprint_path, kind, operation, name, class_path
            FROM rigvm_objects
            WHERE name LIKE ? OR class_path LIKE ? OR operation LIKE ? OR outer_object_id LIKE ?
               OR json LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "kind", "operation", "name", "class_path"))

        print("\n[rigvm properties]")
        rows = conn.execute(
            """
            SELECT blueprint_path, kind, property_path, cpp_type, object_path,
                   substr(value, 1, 240) AS value
            FROM rigvm_properties
            WHERE property_name LIKE ? OR property_path LIKE ? OR cpp_type LIKE ?
               OR value LIKE ? OR object_path LIKE ? OR object_class LIKE ?
               OR declaring_type LIKE ? OR class_path LIKE ?
            LIMIT ?
            """,
            (
                f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%",
                f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit,
            ),
        )
        _print_rows(
            rows,
            ("blueprint_path", "kind", "property_path", "cpp_type", "object_path", "value"),
        )

        print("\n[rigvm references]")
        rows = conn.execute(
            """
            SELECT blueprint_path, source_kind, property_path, target_kind, target_object_id
            FROM rigvm_references
            WHERE source_object_id LIKE ? OR source_class LIKE ? OR property_path LIKE ?
               OR target_object_id LIKE ? OR target_class LIKE ? OR target_kind LIKE ?
            LIMIT ?
            """,
            (
                f"%{term}%", f"%{term}%", f"%{term}%",
                f"%{term}%", f"%{term}%", f"%{term}%", limit,
            ),
        )
        _print_rows(
            rows,
            ("blueprint_path", "source_kind", "property_path", "target_kind", "target_object_id"),
        )

        print("\n[rigvm pins]")
        rows = conn.execute(
            """
            SELECT blueprint_path, outer_object_id, name, direction, cpp_type, default_value
            FROM rigvm_pins
            WHERE name LIKE ? OR display_name LIKE ? OR direction LIKE ? OR cpp_type LIKE ?
               OR cpp_type_object_path LIKE ? OR default_value LIKE ? OR default_value_object LIKE ?
            LIMIT ?
            """,
            (
                f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%",
                f"%{term}%", f"%{term}%", f"%{term}%", limit,
            ),
        )
        _print_rows(rows, ("blueprint_path", "outer_object_id", "name", "direction", "cpp_type", "default_value"))

        print("\n[rigvm links]")
        rows = conn.execute(
            """
            SELECT blueprint_path, source_pin_path, target_pin_path
            FROM rigvm_links
            WHERE source_pin_path LIKE ? OR target_pin_path LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "source_pin_path", "target_pin_path"))

        print("\n[assets]")
        rows = conn.execute(
            """
            SELECT object_path, class_path
            FROM assets
            WHERE object_path LIKE ? OR class_path LIKE ? OR json LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("object_path", "class_path"))

        print("\n[source]")
        has_fts = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_fts'"
        ).fetchone()
        if has_fts:
            try:
                rows = conn.execute(
                    """
                    SELECT path, snippet(source_fts, 1, '[', ']', ' … ', 24) AS text
                    FROM source_fts
                    WHERE source_fts MATCH ?
                    LIMIT ?
                    """,
                    (term, limit),
                )
                _print_rows(rows, ("path", "text"))
            except sqlite3.OperationalError:
                has_fts = False
        if not has_fts:
            rows = conn.execute(
                """
                SELECT path, substr(text, 1, 240) AS text
                FROM source_chunks
                WHERE text LIKE ? OR path LIKE ?
                LIMIT ?
                """,
                (f"%{term}%", f"%{term}%", limit),
            )
            _print_rows(rows, ("path", "text"))
    finally:
        conn.close()
    return 0


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uatool", description="UnrealAssetTool project indexer")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="build if needed, run the Unreal commandlet, and build uat.db")
    p_scan.add_argument("project", help="path to .uproject")
    p_scan.add_argument("--editor", required=True, help="exact path to UnrealEditor-Cmd.exe")
    p_scan.add_argument("--build-script", help="optional exact path to Engine/Build/BatchFiles/Build.bat")
    p_scan.add_argument("--no-build", action="store_true", help="do not build automatically when the plugin DLL is missing")
    p_scan.add_argument("--output", help="output directory; default: <project>/.uatool")
    p_scan.add_argument("--include-generated", action="store_true", help="include Binaries/Intermediate/Saved/etc in filesystem metadata")
    p_scan.add_argument("--include-engine", action="store_true", help="include Engine-owned assets, not only project/plugin assets")
    p_scan.add_argument("--include-self", action="store_true", help="include the UnrealAssetTool plugin itself (debugging only)")
    p_scan.add_argument("--include-raw-rigvm-properties", action="store_true", help="emit the very large raw RigVM reflection property stream")
    p_scan.add_argument("--no-bundle", action="store_true", help="do not create the upload-ready ZIP after a successful scan")
    p_scan.add_argument("--bundle-include-raw-rigvm", action="store_true", help="include rigvm_properties.jsonl in the upload ZIP")
    p_scan.set_defaults(func=scan)

    p_build = sub.add_parser("build", help="build the project's Editor target so UnrealAssetTool can load")
    p_build.add_argument("project", help="path to .uproject")
    p_build.add_argument("--editor", required=True, help="exact path to UnrealEditor-Cmd.exe")
    p_build.add_argument("--build-script", help="optional exact path to Engine/Build/BatchFiles/Build.bat")
    p_build.set_defaults(func=build)

    p_pack = sub.add_parser("pack", help="rebuild uat.db from existing JSONL output")
    p_pack.add_argument("output", help="directory containing manifest.json and JSONL files")
    p_pack.set_defaults(func=pack)

    p_derive = sub.add_parser("derive", help="regenerate AI-oriented derived Blueprint/RigVM views without running Unreal")
    p_derive.add_argument("output", help="directory containing manifest.json and JSONL files")
    p_derive.set_defaults(func=derive)

    p_bundle = sub.add_parser("bundle", help="create a compact upload ZIP from existing JSONL output")
    p_bundle.add_argument("output", help="directory containing manifest.json and JSONL files")
    p_bundle.add_argument("--destination", help="ZIP path; default: <output>/uatool-upload.zip")
    p_bundle.add_argument("--include-raw-rigvm", action="store_true", help="include rigvm_properties.jsonl")
    p_bundle.set_defaults(func=bundle)

    p_query = sub.add_parser("query", help="quickly search the generated index")
    p_query.add_argument("output", help=".uatool directory or uat.db")
    p_query.add_argument("term", help="search term")
    p_query.add_argument("--limit", type=int, default=20)
    p_query.set_defaults(func=query)

    return parser


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"uatool: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
