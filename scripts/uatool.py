#!/usr/bin/env python3
"""UnrealAssetTool launcher, SQLite packer, and text query utility."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Iterator

DB_NAME = "uat.db"


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


def read_uproject(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def find_editor(project: Path, engine: str | None, editor: str | None) -> Path:
    if editor:
        candidate = Path(editor).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"Unreal editor command executable not found: {candidate}")

    roots: list[Path] = []
    if engine:
        roots.append(Path(engine).expanduser())
    if os.environ.get("UE_ENGINE_ROOT"):
        roots.append(Path(os.environ["UE_ENGINE_ROOT"]).expanduser())

    try:
        association = str(read_uproject(project).get("EngineAssociation", "")).strip()
    except Exception:
        association = ""

    if association:
        version = association
        if version.startswith("UE_"):
            version = version[3:]
        roots.extend(
            [
                Path(f"C:/Program Files/Epic Games/UE_{version}"),
                Path(f"C:/Program Files/Epic Games/{association}"),
            ]
        )

    for root in roots:
        candidate = root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
        if candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        "Could not locate UnrealEditor-Cmd.exe. Pass --engine <UE root> or "
        "--editor <full path to UnrealEditor-Cmd.exe>, or set UE_ENGINE_ROOT."
    )


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
            title TEXT NOT NULL,
            comment TEXT NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            json TEXT NOT NULL
        );
        CREATE INDEX bp_nodes_blueprint_idx ON blueprint_nodes(blueprint_path, graph_name);
        CREATE INDEX bp_nodes_title_idx ON blueprint_nodes(title);

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
                "INSERT INTO blueprint_nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row.get("node_id", ""),
                    row.get("blueprint_path", ""),
                    row.get("graph_name", ""),
                    row.get("graph_kind", ""),
                    row.get("node_class", ""),
                    row.get("title", ""),
                    row.get("comment", ""),
                    int(row.get("x", 0)),
                    int(row.get("y", 0)),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
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

    editor = find_editor(project, args.engine, args.editor)
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

    print("running:", subprocess.list2cmdline(command))
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        return result.returncode

    db_path = build_database(output)
    print(f"database: {db_path}")
    return 0


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
            SELECT blueprint_path, graph_name, title, node_class
            FROM blueprint_nodes
            WHERE title LIKE ? OR comment LIKE ? OR node_class LIKE ?
            LIMIT ?
            """,
            (f"%{term}%", f"%{term}%", f"%{term}%", limit),
        )
        _print_rows(rows, ("blueprint_path", "graph_name", "title", "node_class"))

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

    p_scan = sub.add_parser("scan", help="run the Unreal commandlet and build uat.db")
    p_scan.add_argument("project", help="path to .uproject")
    p_scan.add_argument("--engine", help="Unreal Engine root, e.g. G:/UE_5.8")
    p_scan.add_argument("--editor", help="full path to UnrealEditor-Cmd.exe")
    p_scan.add_argument("--output", help="output directory; default: <project>/.uatool")
    p_scan.add_argument("--include-generated", action="store_true", help="include Binaries/Intermediate/Saved/etc in filesystem metadata")
    p_scan.add_argument("--include-engine", action="store_true", help="include Engine-owned assets, not only project/plugin assets")
    p_scan.set_defaults(func=scan)

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
