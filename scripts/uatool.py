#!/usr/bin/env python3
"""UnrealAssetTool launcher, SQLite packer, and text query utility."""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
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


def build_project(project: Path, editor: Path, build_script_arg: str | None = None) -> int:
    build_script = resolve_build_script(editor, build_script_arg)
    target = f"{project.stem}Editor"
    configuration = editor_configuration(editor)
    command = [
        str(build_script),
        f"-Target={target} Win64 {configuration}",
        f"-Module={MODULE_NAME}",
        f"-Project={project}",
        "-WaitMutex",
        "-NoHotReloadFromIDE",
    ]
    print("building:", subprocess.list2cmdline(command))
    return subprocess.run(command, check=False).returncode


def ensure_plugin_binary(project: Path, editor: Path, build_script_arg: str | None, no_build: bool) -> None:
    configuration = editor_configuration(editor)
    expected_binary = expected_plugin_binary(editor)
    expected_manifest = expected_module_manifest(editor)
    manifest_binary = module_manifest_binary(editor)

    # The manifest is authoritative: Unreal's module manager uses it to map the
    # module name to a DLL. A stray DLL for another configuration is not enough.
    if manifest_binary is not None:
        return

    existing = plugin_binary_candidates()
    existing_text = ""
    if existing:
        existing_text = "\nExisting module binaries (not valid for this selected editor unless its manifest maps them):\n" + "\n".join(
            f"  {path}" for path in existing
        )

    reason = (
        f"Selected editor configuration: {configuration}\n"
        f"Expected module manifest: {expected_manifest}\n"
        f"Expected module binary:   {expected_binary}"
    )

    if no_build:
        raise RuntimeError(
            f"{MODULE_NAME} is not loadable by the selected editor.\n"
            f"{reason}"
            f"{existing_text}\n"
            "Build the matching configuration first, or omit --no-build so scan can build it automatically."
        )

    print(f"{MODULE_NAME}: module is not loadable by the selected editor")
    print(reason)
    if existing:
        print("module DLLs currently present:")
        for path in existing:
            print(f"  {path.name}")
    print(f"building {project.stem}Editor Win64 {configuration} module {MODULE_NAME}")

    result = build_project(project, editor, build_script_arg)
    if result != 0:
        raise RuntimeError(f"Unreal build failed with exit code {result}")

    manifest_binary = module_manifest_binary(editor)
    if manifest_binary is None:
        raise RuntimeError(
            "The build completed, but Unreal still has no valid module-manifest mapping for "
            f"{MODULE_NAME}.\nExpected manifest: {expected_manifest}\n"
            f"Expected binary:   {expected_binary}"
        )
    print(f"module ready: {manifest_binary}")


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

        CREATE TABLE blueprint_edges (
            blueprint_path TEXT NOT NULL,
            graph_name TEXT NOT NULL,
            source_pin_id TEXT NOT NULL,
            target_pin_id TEXT NOT NULL,
            pin_category TEXT NOT NULL,
            PRIMARY KEY(source_pin_id, target_pin_id)
        );
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
                "INSERT INTO blueprints VALUES (?, ?, ?, ?, ?, ?, ?)",
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

        for row in iter_jsonl(output / "blueprint_nodes.jsonl"):
            conn.execute(
                "INSERT INTO blueprint_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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

        for row in iter_jsonl(output / "blueprint_edges.jsonl"):
            conn.execute(
                "INSERT OR IGNORE INTO blueprint_edges VALUES (?, ?, ?, ?, ?)",
                (
                    row.get("blueprint_path", ""),
                    row.get("graph_name", ""),
                    row.get("source_pin_id", ""),
                    row.get("target_pin_id", ""),
                    row.get("pin_category", ""),
                ),
            )

        conn.commit()
    finally:
        conn.close()
    return db_path


def scan(args: argparse.Namespace) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Not a .uproject file: {project}")

    output = Path(args.output).expanduser() if args.output else project.parent / ".uatool"
    if not output.is_absolute():
        output = (project.parent / output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    editor = require_editor(args.editor)
    ensure_plugin_binary(project, editor, args.build_script, args.no_build)

    command = [
        str(editor),
        str(project),
        "-run=UnrealAssetTool",
        f"-Output={output}",
        "-unattended",
        "-nop4",
        "-nosplash",
        "-NoShaderCompile",
    ]
    if args.include_generated:
        command.append("-IncludeGenerated")
    if args.include_engine:
        command.append("-IncludeEngine")
    if args.include_self:
        command.append("-IncludeSelf")

    print("running:", subprocess.list2cmdline(command))
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        return result.returncode

    db_path = build_database(output)
    print(f"database: {db_path}")
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
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", f"%{term}%", limit),
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
    p_scan.set_defaults(func=scan)

    p_build = sub.add_parser("build", help="build the project's Editor target so UnrealAssetTool can load")
    p_build.add_argument("project", help="path to .uproject")
    p_build.add_argument("--editor", required=True, help="exact path to UnrealEditor-Cmd.exe")
    p_build.add_argument("--build-script", help="optional exact path to Engine/Build/BatchFiles/Build.bat")
    p_build.set_defaults(func=build)

    p_pack = sub.add_parser("pack", help="rebuild uat.db from existing JSONL output")
    p_pack.add_argument("output", help="directory containing manifest.json and JSONL files")
    p_pack.set_defaults(func=pack)

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
