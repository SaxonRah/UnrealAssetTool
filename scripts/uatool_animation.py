#!/usr/bin/env python3
"""Raw animation-schema indexing support for the canonical UnrealAssetTool CLI."""

from __future__ import annotations

import json
from pathlib import Path


ANIMATION_SCHEMA_VERSION = 1
RAW_FILES = (
    "animation_manifest.json",
    "animation_assets.jsonl",
    "animation_notifies.jsonl",
    "animation_sync_markers.jsonl",
    "montage_sections.jsonl",
    "animation_segments.jsonl",
    "blend_space_axes.jsonl",
    "blend_space_samples.jsonl",
    "skeletons.jsonl",
    "skeleton_bones.jsonl",
    "skeleton_sockets.jsonl",
    "pose_search_databases.jsonl",
    "pose_search_database_assets.jsonl",
    "pose_search_schemas.jsonl",
    "pose_search_channels.jsonl",
    "pose_search_schema_skeletons.jsonl",
    "animation_optional_assets.jsonl",
    "animation_properties.jsonl",
    "animation_references.jsonl",
)

_SQL = """
CREATE TABLE animation_assets(
    animation_path TEXT PRIMARY KEY,
    animation_kind TEXT NOT NULL,
    class_path TEXT NOT NULL,
    package_name TEXT NOT NULL,
    skeleton_path TEXT NOT NULL,
    play_length REAL NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX animation_assets_kind_idx ON animation_assets(animation_kind, class_path);
CREATE INDEX animation_assets_skeleton_idx ON animation_assets(skeleton_path);

CREATE TABLE animation_notifies(
    asset_path TEXT NOT NULL,
    notify_index INTEGER NOT NULL,
    notify_name TEXT NOT NULL,
    trigger_time REAL NOT NULL,
    end_trigger_time REAL NOT NULL,
    duration REAL NOT NULL,
    track_index INTEGER NOT NULL,
    notify_class TEXT NOT NULL,
    notify_state_class TEXT NOT NULL,
    branching_point INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(asset_path, notify_index)
);
CREATE INDEX animation_notifies_name_idx ON animation_notifies(notify_name);

CREATE TABLE animation_sync_markers(
    asset_path TEXT NOT NULL,
    marker_index INTEGER NOT NULL,
    marker_name TEXT NOT NULL,
    time REAL NOT NULL,
    track_index INTEGER NOT NULL,
    source TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(asset_path, source, marker_index)
);
CREATE INDEX animation_markers_name_idx ON animation_sync_markers(marker_name);

CREATE TABLE animation_segments(
    asset_path TEXT NOT NULL,
    slot_index INTEGER NOT NULL,
    slot_name TEXT NOT NULL,
    segment_index INTEGER NOT NULL,
    animation_path TEXT NOT NULL,
    start_pos REAL NOT NULL,
    anim_start_time REAL NOT NULL,
    anim_end_time REAL NOT NULL,
    anim_play_rate REAL NOT NULL,
    looping_count INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(asset_path, slot_index, segment_index)
);
CREATE INDEX animation_segments_target_idx ON animation_segments(animation_path);

CREATE TABLE skeleton_bones(
    skeleton_path TEXT NOT NULL,
    bone_index INTEGER NOT NULL,
    bone_name TEXT NOT NULL,
    parent_index INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(skeleton_path, bone_index)
);
CREATE INDEX skeleton_bones_name_idx ON skeleton_bones(bone_name);

CREATE TABLE skeleton_sockets(
    skeleton_path TEXT NOT NULL,
    socket_index INTEGER NOT NULL,
    socket_name TEXT NOT NULL,
    bone_name TEXT NOT NULL,
    socket_path TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(skeleton_path, socket_index)
);
CREATE INDEX skeleton_sockets_name_idx ON skeleton_sockets(socket_name, bone_name);

CREATE TABLE pose_search_databases(
    database_path TEXT PRIMARY KEY,
    schema_path TEXT NOT NULL,
    preview_mesh_path TEXT NOT NULL,
    search_mode TEXT NOT NULL,
    animation_asset_count INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX pose_search_database_schema_idx ON pose_search_databases(schema_path);

CREATE TABLE pose_search_database_assets(
    database_path TEXT NOT NULL,
    asset_index INTEGER NOT NULL,
    animation_path TEXT NOT NULL,
    animation_class TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(database_path, asset_index)
);
CREATE INDEX pose_search_database_asset_target_idx ON pose_search_database_assets(animation_path);

CREATE TABLE pose_search_schemas(
    schema_path TEXT PRIMARY KEY,
    class_path TEXT NOT NULL,
    sample_rate TEXT NOT NULL,
    channel_count INTEGER NOT NULL,
    skeleton_role_count INTEGER NOT NULL,
    json TEXT NOT NULL
);

CREATE TABLE pose_search_channels(
    schema_path TEXT NOT NULL,
    channel_index INTEGER NOT NULL,
    channel_path TEXT NOT NULL,
    channel_class TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(schema_path, channel_index)
);
CREATE INDEX pose_search_channels_class_idx ON pose_search_channels(channel_class);

CREATE TABLE animation_properties(
    asset_path TEXT NOT NULL,
    owner_path TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    owner_class TEXT NOT NULL,
    declaring_type TEXT NOT NULL,
    property_name TEXT NOT NULL,
    property_type TEXT NOT NULL,
    cpp_type TEXT NOT NULL,
    value TEXT NOT NULL,
    truncated INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(owner_path, declaring_type, property_name)
);
CREATE INDEX animation_properties_asset_idx ON animation_properties(asset_path, owner_kind);
CREATE INDEX animation_properties_name_idx ON animation_properties(property_name);

CREATE TABLE animation_references(
    asset_path TEXT NOT NULL,
    owner_path TEXT NOT NULL,
    owner_kind TEXT NOT NULL,
    root_property TEXT NOT NULL,
    property_path TEXT NOT NULL,
    reference_kind TEXT NOT NULL,
    target_path TEXT NOT NULL,
    target_class TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(owner_path, property_path, reference_kind, target_path)
);
CREATE INDEX animation_references_asset_idx ON animation_references(asset_path);
CREATE INDEX animation_references_target_idx ON animation_references(target_path);
"""


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def _j(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def load_database(conn, output: Path, rows) -> None:
    for row in rows(output / "animation_assets.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO animation_assets VALUES(?,?,?,?,?,?,?)",
            (
                row.get("animation_path", ""), row.get("animation_kind", ""),
                row.get("class_path", ""), row.get("package_name", ""),
                row.get("skeleton_path", ""), float(row.get("play_length", 0) or 0), _j(row),
            ),
        )
    for row in rows(output / "animation_notifies.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO animation_notifies VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("asset_path", ""), int(row.get("notify_index", 0)), row.get("notify_name", ""),
                float(row.get("trigger_time", 0) or 0), float(row.get("end_trigger_time", 0) or 0),
                float(row.get("duration", 0) or 0), int(row.get("track_index", 0)),
                row.get("notify_class", ""), row.get("notify_state_class", ""),
                int(bool(row.get("branching_point", False))), _j(row),
            ),
        )
    for row in rows(output / "animation_sync_markers.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO animation_sync_markers VALUES(?,?,?,?,?,?,?)",
            (
                row.get("asset_path", ""), int(row.get("marker_index", 0)), row.get("marker_name", ""),
                float(row.get("time", 0) or 0), int(row.get("track_index", 0)), row.get("source", ""), _j(row),
            ),
        )
    for row in rows(output / "animation_segments.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO animation_segments VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("asset_path", ""), int(row.get("slot_index", 0)), row.get("slot_name", ""),
                int(row.get("segment_index", 0)), row.get("animation_path", ""),
                float(row.get("start_pos", 0) or 0), float(row.get("anim_start_time", 0) or 0),
                float(row.get("anim_end_time", 0) or 0), float(row.get("anim_play_rate", 0) or 0),
                int(row.get("looping_count", 0)), _j(row),
            ),
        )
    for row in rows(output / "skeleton_bones.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO skeleton_bones VALUES(?,?,?,?,?)",
            (row.get("skeleton_path", ""), int(row.get("bone_index", 0)), row.get("bone_name", ""), int(row.get("parent_index", -1)), _j(row)),
        )
    for row in rows(output / "skeleton_sockets.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO skeleton_sockets VALUES(?,?,?,?,?,?)",
            (row.get("skeleton_path", ""), int(row.get("socket_index", 0)), row.get("socket_name", ""), row.get("bone_name", ""), row.get("socket_path", ""), _j(row)),
        )
    for row in rows(output / "pose_search_databases.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO pose_search_databases VALUES(?,?,?,?,?,?)",
            (row.get("database_path", ""), row.get("schema_path", ""), row.get("preview_mesh_path", ""), row.get("search_mode", ""), int(row.get("animation_asset_count", 0)), _j(row)),
        )
    for row in rows(output / "pose_search_database_assets.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO pose_search_database_assets VALUES(?,?,?,?,?,?)",
            (row.get("database_path", ""), int(row.get("asset_index", 0)), row.get("animation_path", ""), row.get("animation_class", ""), row.get("raw_value", ""), _j(row)),
        )
    for row in rows(output / "pose_search_schemas.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO pose_search_schemas VALUES(?,?,?,?,?,?)",
            (row.get("schema_path", ""), row.get("class_path", ""), row.get("sample_rate", ""), int(row.get("channel_count", 0)), int(row.get("skeleton_role_count", 0)), _j(row)),
        )
    for row in rows(output / "pose_search_channels.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO pose_search_channels VALUES(?,?,?,?,?)",
            (row.get("schema_path", ""), int(row.get("channel_index", 0)), row.get("channel_path", ""), row.get("channel_class", ""), _j(row)),
        )
    for row in rows(output / "animation_properties.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO animation_properties VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("asset_path", ""), row.get("owner_path", ""), row.get("owner_kind", ""), row.get("owner_class", ""),
                row.get("declaring_type", ""), row.get("property_name", ""), row.get("property_type", ""), row.get("cpp_type", ""),
                row.get("value", ""), int(bool(row.get("truncated", False))), _j(row),
            ),
        )
    for row in rows(output / "animation_references.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO animation_references VALUES(?,?,?,?,?,?,?,?,?)",
            (
                row.get("asset_path", ""), row.get("owner_path", ""), row.get("owner_kind", ""), row.get("root_property", ""),
                row.get("property_path", ""), row.get("reference_kind", ""), row.get("target_path", ""), row.get("target_class", ""), _j(row),
            ),
        )


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='animation_assets'").fetchone():
        return
    print("\n[animation assets]")
    print_rows(
        conn.execute(
            "SELECT animation_kind,animation_path,skeleton_path,play_length FROM animation_assets "
            "WHERE animation_path LIKE ? OR animation_kind LIKE ? OR class_path LIKE ? OR skeleton_path LIKE ? OR json LIKE ? LIMIT ?",
            (pattern, pattern, pattern, pattern, pattern, limit),
        ),
        ("animation_kind", "animation_path", "skeleton_path", "play_length"),
    )
    print("\n[pose search]")
    print_rows(
        conn.execute(
            "SELECT d.database_path,d.schema_path,a.asset_index,a.animation_path FROM pose_search_databases d "
            "LEFT JOIN pose_search_database_assets a ON a.database_path=d.database_path "
            "WHERE d.database_path LIKE ? OR d.schema_path LIKE ? OR a.animation_path LIKE ? OR d.json LIKE ? OR a.json LIKE ? LIMIT ?",
            (pattern, pattern, pattern, pattern, pattern, limit),
        ),
        ("database_path", "schema_path", "asset_index", "animation_path"),
    )
    print("\n[animation notifies / markers]")
    print_rows(
        conn.execute(
            "SELECT asset_path,notify_name,trigger_time,duration,notify_class FROM animation_notifies "
            "WHERE asset_path LIKE ? OR notify_name LIKE ? OR notify_class LIKE ? OR notify_state_class LIKE ? OR json LIKE ? LIMIT ?",
            (pattern, pattern, pattern, pattern, pattern, limit),
        ),
        ("asset_path", "notify_name", "trigger_time", "duration", "notify_class"),
    )
    print("\n[animation references]")
    print_rows(
        conn.execute(
            "SELECT asset_path,owner_kind,property_path,reference_kind,target_path,target_class FROM animation_references "
            "WHERE asset_path LIKE ? OR owner_path LIKE ? OR property_path LIKE ? OR target_path LIKE ? OR target_class LIKE ? LIMIT ?",
            (pattern, pattern, pattern, pattern, pattern, limit),
        ),
        ("asset_path", "owner_kind", "property_path", "reference_kind", "target_path", "target_class"),
    )


def read_manifest(output: Path) -> dict | None:
    path = output / "animation_manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def validation_error(output: Path) -> str | None:
    manifest = read_manifest(output)
    if manifest is None:
        return "UnrealAssetToolAnimation did not write animation_manifest.json"
    if int(manifest.get("schema_version", 0) or 0) != ANIMATION_SCHEMA_VERSION:
        return f"unexpected animation schema {manifest.get('schema_version')!r}"
    if not bool(manifest.get("success", False)):
        return str(manifest.get("error", "animation scan failed"))
    for filename in manifest.get("files", []) or []:
        if not (output / str(filename)).is_file():
            return f"animation manifest lists missing output file: {filename}"
    return None
