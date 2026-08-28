#!/usr/bin/env python3
"""UnrealAssetTool launcher, SQLite packer, and text query utility."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Iterator

DB_NAME = "uat.db"
MODULE_NAME = "UnrealAssetTool"


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


def expected_plugin_binary(editor: Path) -> Path:
    binaries = plugin_root() / "Binaries" / "Win64"
    configuration = editor_configuration(editor)
    if configuration == "Development":
        filename = f"UnrealEditor-{MODULE_NAME}.dll"
    else:
        filename = f"UnrealEditor-{MODULE_NAME}-Win64-{configuration}.dll"
    return binaries / filename


def expected_module_manifest(editor: Path) -> Path:
    binaries = plugin_root() / "Binaries" / "Win64"
    configuration = editor_configuration(editor)
    if configuration == "Development":
        filename = "UnrealEditor.modules"
    else:
        filename = f"UnrealEditor-Win64-{configuration}.modules"
    return binaries / filename


def module_manifest_binary(editor: Path) -> Path | None:
    """Return the DLL that Unreal's manifest maps to our module, if valid."""
    manifest = expected_module_manifest(editor)
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
    binary = manifest.parent / filename
    return binary if binary.is_file() else None


def plugin_binary_candidates() -> list[Path]:
    binaries = plugin_root() / "Binaries" / "Win64"
    if not binaries.is_dir():
        return []
    return sorted(binaries.glob(f"*{MODULE_NAME}*.dll"))


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


def project_target_receipt_candidates(project: Path, editor: Path) -> list[Path]:
    """Return the normal receipt paths for the selected Editor target/configuration."""
    target = f"{project.stem}Editor"
    binaries = project.parent / "Binaries" / "Win64"
    configuration = editor_configuration(editor)
    if configuration == "Development":
        return [
            binaries / f"{target}.target",
            binaries / f"{target}-Win64-Development.target",
        ]
    return [binaries / f"{target}-Win64-{configuration}.target"]


def project_target_receipt(project: Path, editor: Path) -> Path | None:
    for candidate in project_target_receipt_candidates(project, editor):
        if candidate.is_file():
            return candidate
    return None


def build_project(project: Path, editor: Path, build_script_arg: str | None = None) -> int:
    """Build the complete Editor target, not only the UATool module.

    Commandlet startup loads the project's native game/editor modules before
    UnrealAssetTool runs. Building only -Module=UnrealAssetTool can therefore
    produce a perfectly valid plugin DLL while leaving a Blueprint-heavy sample
    unable to start because its small native project module/target receipt was
    never built. A full target build is incremental, so UBT also becomes our
    source-freshness check for UATool.
    """
    build_script = resolve_build_script(editor, build_script_arg)
    target = f"{project.stem}Editor"
    configuration = editor_configuration(editor)
    command = [
        str(build_script),
        f"-Target={target} Win64 {configuration}",
        f"-Project={project}",
        "-WaitMutex",
        "-NoHotReloadFromIDE",
    ]
    print("building:", subprocess.list2cmdline(command))
    return subprocess.run(command, check=False).returncode


def ensure_plugin_binary(project: Path, editor: Path, build_script_arg: str | None, no_build: bool) -> None:
    configuration = editor_configuration(editor)
    expected_binary = expected_plugin_binary(editor)
    receipt = project_target_receipt(project, editor)

    if no_build:
        missing = []
        if not expected_binary.is_file():
            missing.append(f"UATool module binary: {expected_binary}")
        if receipt is None:
            candidates = ", ".join(str(path) for path in project_target_receipt_candidates(project, editor))
            missing.append(f"project Editor target receipt (expected one of: {candidates})")
        if missing:
            raise RuntimeError(
                "The selected project/editor configuration is not ready for a no-build scan.\n"
                f"Selected editor configuration: {configuration}\n"
                + "\n".join(f"Missing: {item}" for item in missing)
                + "\nRun `uatool.py build ...` first, or omit --no-build."
            )
        return

    # Always ask UBT to build the complete target. This is normally very cheap
    # when everything is up to date, while also rebuilding stale UATool source
    # and creating any missing project game/editor modules and target receipt.
    result = build_project(project, editor, build_script_arg)
    if result != 0:
        raise RuntimeError(f"Unreal build failed with exit code {result}")

    if not expected_binary.is_file():
        existing = plugin_binary_candidates()
        existing_text = ""
        if existing:
            existing_text = "\nModule DLLs currently present:\n" + "\n".join(f"  {path}" for path in existing)
        raise RuntimeError(
            "The full Editor target built successfully, but the exact UATool binary for the selected editor configuration is missing.\n"
            f"Expected: {expected_binary}"
            f"{existing_text}"
        )

    receipt = project_target_receipt(project, editor)
    if receipt is None:
        candidates = "\n".join(f"  {path}" for path in project_target_receipt_candidates(project, editor))
        raise RuntimeError(
            "The full Editor target built successfully, but no project target receipt was produced.\n"
            "Expected one of:\n"
            f"{candidates}"
        )

    manifest_binary = module_manifest_binary(editor)
    if manifest_binary is not None:
        print(f"module ready: {manifest_binary}")
    else:
        # Project targets can load project-plugin modules through the target
        # receipt even when UBT does not emit a plugin-local .modules manifest.
        print(f"module ready: {expected_binary}")
    print(f"target receipt: {receipt}")

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



DERIVED_SCHEMA_VERSION = 1


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

def derive_rigvm_editor_links(output: Path) -> list[dict]:
    graphs = {row.get("graph_id", ""): row for row in iter_blueprint_graph_rows(output)}
    rig_by_bp_name: dict[str, dict[str, list[dict]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    rig_by_bp_pos: dict[str, dict[tuple[int, int], list[dict]]] = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in iter_jsonl(output / "rigvm_objects.jsonl"):
        if row.get("kind") != "node":
            continue
        bp = row.get("blueprint_path", "")
        rig_by_bp_name[bp][str(row.get("name", ""))].append(row)
        pos = _parse_xy(str(row.get("position", "")))
        if pos:
            rig_by_bp_pos[bp][(round(pos[0]), round(pos[1]))].append(row)

    rows: list[dict] = []
    seen_editor_nodes: set[str] = set()
    for source in iter_jsonl(output / "blueprint_nodes.jsonl"):
        if source.get("operation") != "control_rig_node":
            continue
        node_id = source.get("node_id", "")
        if node_id in seen_editor_nodes:
            continue
        seen_editor_nodes.add(node_id)
        semantic = source.get("semantic", {}) if isinstance(source.get("semantic"), dict) else {}
        model_name = str(semantic.get("model_node_path", "") or source.get("symbol", ""))
        graph = graphs.get(source.get("graph_id", ""), {})
        tokens = _graph_match_tokens(graph)
        sx, sy = float(source.get("x", 0)), float(source.get("y", 0))
        bp = source.get("blueprint_path", "")

        candidate_map: dict[str, dict] = {}
        for candidate in rig_by_bp_name.get(bp, {}).get(model_name, []):
            candidate_map[candidate.get("object_id", "")] = candidate
        for candidate in rig_by_bp_pos.get(bp, {}).get((round(sx), round(sy)), []):
            candidate_map[candidate.get("object_id", "")] = candidate

        scored: list[tuple[int, dict, list[str]]] = []
        for candidate in candidate_map.values():
            score = 0
            basis: list[str] = []
            name = str(candidate.get("name", ""))
            outer = str(candidate.get("outer_object_id", ""))
            pos = _parse_xy(str(candidate.get("position", "")))
            if pos and abs(pos[0] - sx) < 0.51 and abs(pos[1] - sy) < 0.51:
                score += 100
                basis.append("position")
            if model_name and name == model_name:
                score += 50
                basis.append("model_name")
            elif model_name and (name.startswith(model_name) or model_name.startswith(name)):
                score += 20
                basis.append("model_name_prefix")
            token_hits = sum(1 for token in tokens if token.lower() in outer.lower())
            if token_hits:
                score += token_hits * 15
                basis.append(f"graph_context:{token_hits}")
            if score:
                scored.append((score, candidate, basis))

        scored.sort(key=lambda item: (-item[0], item[1].get("object_id", "")))
        best_score = scored[0][0] if scored else 0
        best = [item for item in scored if item[0] == best_score]
        status = "unmatched"
        chosen: dict = {}
        basis: list[str] = []
        if len(best) == 1 and best_score >= 50:
            status = "matched"
            chosen = best[0][1]
            basis = best[0][2]
        elif len(best) > 1 and best_score >= 50:
            status = "ambiguous"
        confidence = "none"
        if status == "matched":
            confidence = "high" if best_score >= 100 else "medium"
        rows.append({
            "node_id": node_id,
            "blueprint_path": bp,
            "graph_id": source.get("graph_id", ""),
            "graph_name": source.get("graph_name", ""),
            "model_node_path": model_name,
            "status": status,
            "confidence": confidence,
            "score": best_score,
            "candidate_count": len(best),
            "match_basis": basis,
            "rigvm_object_id": chosen.get("object_id", ""),
            "rigvm_operation": chosen.get("operation", ""),
            "rigvm_class": chosen.get("class_path", ""),
            "resolved_function_name": chosen.get("resolved_function_name", ""),
            "template_notation": chosen.get("template_notation", ""),
        })
    return rows

def _relation_id(parts: tuple[str, ...]) -> str:
    digest = hashlib.sha1("\x1f".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"rel:{digest}"


def derive_blueprint_relations(output: Path, rigvm_links: list[dict]) -> list[dict]:
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
        op = node.get("operation", "")
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
        elif op == "delegate_call":
            add(bp, gid, "node", nid, "calls_delegate", "delegate", sem.get("delegate_name", "") or symbol, sem.get("delegate_owner", "") or owner)
        elif op == "delegate_create":
            add(bp, gid, "node", nid, "creates_delegate", "function", sem.get("selected_function", "") or symbol)
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


def derive_graph_context(output: Path, rigvm_links: list[dict], max_chars: int = 524288) -> list[dict]:
    rig_by_node = {row.get("node_id", ""): row for row in rigvm_links if row.get("status") == "matched"}
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
            "Nodes:",
        ]
        for node in nodes:
            nid = node.get("node_id", "")
            label = node.get("symbol", "") or node.get("title", "")
            line = f"  {aliases[nid]} {node.get('operation','')} {label}".rstrip()
            sem_text = _compact_semantic(node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {})
            if sem_text:
                line += f" | {sem_text}"
            rig = rig_by_node.get(nid)
            if rig:
                rig_bits = [rig.get("rigvm_operation", ""), rig.get("resolved_function_name", ""), rig.get("template_notation", "")]
                line += " | RigVM=" + " | ".join(bit for bit in rig_bits if bit)
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


def derive_blueprint_summaries(output: Path, relations: list[dict]) -> list[dict]:
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
        ops_by_bp[node.get("blueprint_path", "")][node.get("operation", "")] += 1
    rel_by_bp: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for rel in relations:
        rel_by_bp[rel.get("blueprint_path", "")][rel.get("relation", "")] += 1

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
            "graph_count": len(graphs),
            "graph_system_counts": dict(graph_systems),
            "operation_counts": dict(op_counts),
            "relation_counts": dict(rel_by_bp.get(path, collections.Counter())),
            "text": text[:524288],
        })
    return out


def derive_output(output: Path) -> dict[str, int]:
    output = output.resolve()
    rigvm_links = derive_rigvm_editor_links(output)
    relations = derive_blueprint_relations(output, rigvm_links)
    graph_context = derive_graph_context(output, rigvm_links)
    summaries = derive_blueprint_summaries(output, relations)
    counts = {
        "rigvm_editor_links": _write_jsonl(output / "rigvm_editor_links.jsonl", rigvm_links),
        "blueprint_relations": _write_jsonl(output / "blueprint_relations.jsonl", relations),
        "blueprint_graph_context": _write_jsonl(output / "blueprint_graph_context.jsonl", graph_context),
        "blueprint_summaries": _write_jsonl(output / "blueprint_summaries.jsonl", summaries),
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
                "INSERT OR REPLACE INTO blueprint_summaries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("blueprint_path", ""), row.get("name", ""), row.get("parent_class", ""), row.get("generated_class", ""),
                    int(row.get("variable_count", 0)), int(row.get("component_count", 0)), int(row.get("interface_count", 0)),
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
    "files.jsonl",
    "source_chunks.jsonl",
    "assets.jsonl",
    "asset_dependencies.jsonl",
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
    "blueprint_timelines.jsonl",
    "blueprint_timeline_tracks.jsonl",
    "blueprint_widgets.jsonl",
    "blueprint_widget_bindings.jsonl",
    "blueprint_widget_animations.jsonl",
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
    if manifest_path.exists():
        manifest_path.unlink()

    editor = require_editor(args.editor)
    ensure_plugin_binary(project, editor, args.build_script, args.no_build)

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

    print("running:", subprocess.list2cmdline(command))
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        report_editor_failure(project, result.returncode)
        return result.returncode

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

    derived_counts = derive_output(output)
    print("derived:", ", ".join(f"{key}={value}" for key, value in derived_counts.items()))
    db_path = build_database(output)
    print(f"database: {db_path}")
    if not args.no_bundle:
        bundle_path = create_upload_bundle(
            output,
            project.parent / f"{project.stem}.uatool.zip",
            include_raw_rigvm=args.bundle_include_raw_rigvm,
        )
        print(f"upload bundle: {bundle_path}")
    return 0


def build(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Not a .uproject file: {project}")
    editor = require_editor(args.editor)
    return build_project(project, editor, args.build_script)


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
        print("[blueprint summaries]")
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
