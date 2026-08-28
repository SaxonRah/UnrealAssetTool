#!/usr/bin/env python3
"""UnrealAssetTool launcher, SQLite packer, and text query utility."""

from __future__ import annotations

import argparse
import json
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
    db_path = build_database(output)
    print(db_path)
    return 0


def bundle(args: argparse.Namespace) -> int:
    output = Path(args.output).expanduser().resolve()
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
