#!/usr/bin/env python3
"""Raw animation-schema indexing support for the canonical UnrealAssetTool CLI."""

from __future__ import annotations

import json
from pathlib import Path


ANIMATION_SCHEMA_VERSION = 1
DEEP_SCHEMA_VERSION = 1

BASE_RAW_FILES = (
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
DEEP_RAW_FILES = (
    "animation_deep_manifest.json",
    "animation_curves.jsonl",
    "animation_curve_keys.jsonl",
    "pose_search_interaction_assets.jsonl",
    "pose_search_interaction_items.jsonl",
    "pose_search_normalization_sets.jsonl",
    "pose_search_normalization_databases.jsonl",
    "mirror_data_tables.jsonl",
    "mirror_data_table_rows.jsonl",
)
RAW_FILES = BASE_RAW_FILES + DEEP_RAW_FILES

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
CREATE INDEX animation_assets_kind_idx ON animation_assets(animation_kind,class_path);
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
    PRIMARY KEY(asset_path,notify_index)
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
    PRIMARY KEY(asset_path,source,marker_index)
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
    PRIMARY KEY(asset_path,slot_index,segment_index)
);
CREATE INDEX animation_segments_target_idx ON animation_segments(animation_path);

CREATE TABLE skeleton_bones(
    skeleton_path TEXT NOT NULL,
    bone_index INTEGER NOT NULL,
    bone_name TEXT NOT NULL,
    parent_index INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(skeleton_path,bone_index)
);
CREATE INDEX skeleton_bones_name_idx ON skeleton_bones(bone_name);

CREATE TABLE skeleton_sockets(
    skeleton_path TEXT NOT NULL,
    socket_index INTEGER NOT NULL,
    socket_name TEXT NOT NULL,
    bone_name TEXT NOT NULL,
    socket_path TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(skeleton_path,socket_index)
);
CREATE INDEX skeleton_sockets_name_idx ON skeleton_sockets(socket_name,bone_name);

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
    PRIMARY KEY(database_path,asset_index)
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
    PRIMARY KEY(schema_path,channel_index)
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
    PRIMARY KEY(owner_path,declaring_type,property_name)
);
CREATE INDEX animation_properties_asset_idx ON animation_properties(asset_path,owner_kind);
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
    PRIMARY KEY(owner_path,property_path,reference_kind,target_path)
);
CREATE INDEX animation_references_asset_idx ON animation_references(asset_path);
CREATE INDEX animation_references_target_idx ON animation_references(target_path);

CREATE TABLE animation_curves(
    asset_path TEXT NOT NULL,
    curve_index INTEGER NOT NULL,
    curve_name TEXT NOT NULL,
    curve_type TEXT NOT NULL,
    curve_type_flags INTEGER NOT NULL,
    key_count INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(asset_path,curve_type,curve_index)
);
CREATE INDEX animation_curves_name_idx ON animation_curves(curve_name,curve_type);

CREATE TABLE animation_curve_keys(
    asset_path TEXT NOT NULL,
    curve_name TEXT NOT NULL,
    curve_type TEXT NOT NULL,
    component TEXT NOT NULL,
    key_index INTEGER NOT NULL,
    time REAL NOT NULL,
    value REAL NOT NULL,
    interp_mode INTEGER NOT NULL,
    tangent_mode INTEGER NOT NULL,
    tangent_weight_mode INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(asset_path,curve_name,curve_type,component,key_index)
);
CREATE INDEX animation_curve_keys_curve_idx ON animation_curve_keys(curve_name,asset_path);

CREATE TABLE pose_search_interaction_assets(
    interaction_path TEXT PRIMARY KEY,
    class_path TEXT NOT NULL,
    package_name TEXT NOT NULL,
    item_count INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE pose_search_interaction_items(
    interaction_path TEXT NOT NULL,
    item_index INTEGER NOT NULL,
    role TEXT NOT NULL,
    animation_path TEXT NOT NULL,
    animation_class TEXT NOT NULL,
    preview_mesh_path TEXT NOT NULL,
    origin TEXT NOT NULL,
    warping_weight_rotation TEXT NOT NULL,
    warping_weight_translation TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(interaction_path,item_index)
);
CREATE INDEX pose_search_interaction_item_anim_idx ON pose_search_interaction_items(animation_path);

CREATE TABLE pose_search_normalization_sets(
    normalization_set_path TEXT PRIMARY KEY,
    class_path TEXT NOT NULL,
    package_name TEXT NOT NULL,
    database_count INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE pose_search_normalization_databases(
    normalization_set_path TEXT NOT NULL,
    database_index INTEGER NOT NULL,
    database_path TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(normalization_set_path,database_index)
);
CREATE INDEX pose_search_normalization_database_target_idx ON pose_search_normalization_databases(database_path);

CREATE TABLE mirror_data_tables(
    mirror_table_path TEXT PRIMARY KEY,
    class_path TEXT NOT NULL,
    package_name TEXT NOT NULL,
    skeleton_path TEXT NOT NULL,
    mirror_axis INTEGER NOT NULL,
    row_count INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE mirror_data_table_rows(
    mirror_table_path TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    row_name TEXT NOT NULL,
    name TEXT NOT NULL,
    mirrored_name TEXT NOT NULL,
    mirror_entry_type INTEGER NOT NULL,
    enabled INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(mirror_table_path,row_index)
);
CREATE INDEX mirror_data_table_rows_name_idx ON mirror_data_table_rows(name,mirrored_name);
"""


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def _j(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _iter_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc


def _write_jsonl(path: Path, values: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(_j(value) + "\n")


def prepare_output(output: Path, rows) -> None:
    """Normalize schema-1 raw output after both Unreal animation passes finish."""
    output = Path(output)

    assets = list(rows(output / "animation_assets.jsonl"))
    class_by_path = {str(row.get("animation_path", "")): str(row.get("class_path", "")) for row in assets}
    changed_assets = False
    for row in assets:
        if row.get("class_path") == "/Script/ProxyTable.ProxyAsset" and row.get("animation_kind") != "proxy_asset":
            row["animation_kind"] = "proxy_asset"
            changed_assets = True
    if changed_assets:
        _write_jsonl(output / "animation_assets.jsonl", assets)

    optional = list(rows(output / "animation_optional_assets.jsonl"))
    changed_optional = False
    for row in optional:
        if row.get("class_path") == "/Script/ProxyTable.ProxyAsset":
            if row.get("asset_kind") != "proxy_asset":
                row["asset_kind"] = "proxy_asset"
                changed_optional = True
            if row.get("family") != "proxy_asset":
                row["family"] = "proxy_asset"
                changed_optional = True
    if changed_optional:
        _write_jsonl(output / "animation_optional_assets.jsonl", optional)

    axes = list(rows(output / "blend_space_axes.jsonl"))
    normalized_axes = []
    for row in axes:
        path = str(row.get("blend_space_path", ""))
        class_path = class_by_path.get(path, "")
        axis_index = int(row.get("axis_index", 0))
        display_name = str(row.get("display_name", ""))
        if class_path == "/Script/Engine.BlendSpace1D":
            if axis_index == 0:
                normalized_axes.append(row)
            continue
        if display_name and display_name != "None":
            normalized_axes.append(row)
    if len(normalized_axes) != len(axes):
        _write_jsonl(output / "blend_space_axes.jsonl", normalized_axes)

    base_manifest = _read_json(output / "animation_manifest.json")
    deep_manifest = _read_json(output / "animation_deep_manifest.json")
    if base_manifest is None or deep_manifest is None:
        return
    counts = base_manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    deep_counts = deep_manifest.get("counts", {})
    if isinstance(deep_counts, dict):
        counts.update(deep_counts)
    counts["blend_space_axes"] = len(normalized_axes)
    base_manifest["counts"] = counts
    base_manifest["deep_schema_version"] = int(deep_manifest.get("schema_version", 0) or 0)
    files = [str(v) for v in (base_manifest.get("files", []) or [])]
    for filename in DEEP_RAW_FILES:
        if filename != "animation_deep_manifest.json" and filename not in files:
            files.append(filename)
    base_manifest["files"] = files
    (output / "animation_manifest.json").write_text(
        json.dumps(base_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def load_database(conn, output: Path, rows) -> None:
    prepare_output(output, rows)

    for row in rows(output / "animation_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_assets VALUES(?,?,?,?,?,?,?)", (
            row.get("animation_path", ""), row.get("animation_kind", ""), row.get("class_path", ""),
            row.get("package_name", ""), row.get("skeleton_path", ""),
            float(row.get("play_length", 0) or 0), _j(row)))
    for row in rows(output / "animation_notifies.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_notifies VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            row.get("asset_path", ""), int(row.get("notify_index", 0)), row.get("notify_name", ""),
            float(row.get("trigger_time", 0) or 0), float(row.get("end_trigger_time", 0) or 0),
            float(row.get("duration", 0) or 0), int(row.get("track_index", 0)),
            row.get("notify_class", ""), row.get("notify_state_class", ""),
            int(bool(row.get("branching_point", False))), _j(row)))
    for row in rows(output / "animation_sync_markers.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_sync_markers VALUES(?,?,?,?,?,?,?)", (
            row.get("asset_path", ""), int(row.get("marker_index", 0)), row.get("marker_name", ""),
            float(row.get("time", 0) or 0), int(row.get("track_index", 0)), row.get("source", ""), _j(row)))
    for row in rows(output / "animation_segments.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_segments VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            row.get("asset_path", ""), int(row.get("slot_index", 0)), row.get("slot_name", ""),
            int(row.get("segment_index", 0)), row.get("animation_path", ""),
            float(row.get("start_pos", 0) or 0), float(row.get("anim_start_time", 0) or 0),
            float(row.get("anim_end_time", 0) or 0), float(row.get("anim_play_rate", 0) or 0),
            int(row.get("looping_count", 0)), _j(row)))
    for row in rows(output / "skeleton_bones.jsonl"):
        conn.execute("INSERT OR REPLACE INTO skeleton_bones VALUES(?,?,?,?,?)", (
            row.get("skeleton_path", ""), int(row.get("bone_index", 0)), row.get("bone_name", ""),
            int(row.get("parent_index", -1)), _j(row)))
    for row in rows(output / "skeleton_sockets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO skeleton_sockets VALUES(?,?,?,?,?,?)", (
            row.get("skeleton_path", ""), int(row.get("socket_index", 0)), row.get("socket_name", ""),
            row.get("bone_name", ""), row.get("socket_path", ""), _j(row)))
    for row in rows(output / "pose_search_databases.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_search_databases VALUES(?,?,?,?,?,?)", (
            row.get("database_path", ""), row.get("schema_path", ""), row.get("preview_mesh_path", ""),
            row.get("search_mode", ""), int(row.get("animation_asset_count", 0)), _j(row)))
    for row in rows(output / "pose_search_database_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_search_database_assets VALUES(?,?,?,?,?,?)", (
            row.get("database_path", ""), int(row.get("asset_index", 0)), row.get("animation_path", ""),
            row.get("animation_class", ""), row.get("raw_value", ""), _j(row)))
    for row in rows(output / "pose_search_schemas.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_search_schemas VALUES(?,?,?,?,?,?)", (
            row.get("schema_path", ""), row.get("class_path", ""), row.get("sample_rate", ""),
            int(row.get("channel_count", 0)), int(row.get("skeleton_role_count", 0)), _j(row)))
    for row in rows(output / "pose_search_channels.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_search_channels VALUES(?,?,?,?,?)", (
            row.get("schema_path", ""), int(row.get("channel_index", 0)), row.get("channel_path", ""),
            row.get("channel_class", ""), _j(row)))
    for row in rows(output / "animation_properties.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_properties VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            row.get("asset_path", ""), row.get("owner_path", ""), row.get("owner_kind", ""),
            row.get("owner_class", ""), row.get("declaring_type", ""), row.get("property_name", ""),
            row.get("property_type", ""), row.get("cpp_type", ""), row.get("value", ""),
            int(bool(row.get("truncated", False))), _j(row)))
    for row in rows(output / "animation_references.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_references VALUES(?,?,?,?,?,?,?,?,?)", (
            row.get("asset_path", ""), row.get("owner_path", ""), row.get("owner_kind", ""),
            row.get("root_property", ""), row.get("property_path", ""), row.get("reference_kind", ""),
            row.get("target_path", ""), row.get("target_class", ""), _j(row)))

    for row in rows(output / "animation_curves.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_curves VALUES(?,?,?,?,?,?,?)", (
            row.get("asset_path", ""), int(row.get("curve_index", 0)), row.get("curve_name", ""),
            row.get("curve_type", ""), int(row.get("curve_type_flags", 0)), int(row.get("key_count", 0)), _j(row)))
    for row in rows(output / "animation_curve_keys.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_curve_keys VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            row.get("asset_path", ""), row.get("curve_name", ""), row.get("curve_type", ""),
            row.get("component", ""), int(row.get("key_index", 0)), float(row.get("time", 0) or 0),
            float(row.get("value", 0) or 0), int(row.get("interp_mode", 0)), int(row.get("tangent_mode", 0)),
            int(row.get("tangent_weight_mode", 0)), _j(row)))
    for row in rows(output / "pose_search_interaction_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_search_interaction_assets VALUES(?,?,?,?,?)", (
            row.get("interaction_path", ""), row.get("class_path", ""), row.get("package_name", ""),
            int(row.get("item_count", 0)), _j(row)))
    for row in rows(output / "pose_search_interaction_items.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_search_interaction_items VALUES(?,?,?,?,?,?,?,?,?,?)", (
            row.get("interaction_path", ""), int(row.get("item_index", 0)), row.get("role", ""),
            row.get("animation_path", ""), row.get("animation_class", ""), row.get("preview_mesh_path", ""),
            row.get("origin", ""), row.get("warping_weight_rotation", ""),
            row.get("warping_weight_translation", ""), _j(row)))
    for row in rows(output / "pose_search_normalization_sets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_search_normalization_sets VALUES(?,?,?,?,?)", (
            row.get("normalization_set_path", ""), row.get("class_path", ""), row.get("package_name", ""),
            int(row.get("database_count", 0)), _j(row)))
    for row in rows(output / "pose_search_normalization_databases.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_search_normalization_databases VALUES(?,?,?,?)", (
            row.get("normalization_set_path", ""), int(row.get("database_index", 0)),
            row.get("database_path", ""), _j(row)))
    for row in rows(output / "mirror_data_tables.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mirror_data_tables VALUES(?,?,?,?,?,?,?)", (
            row.get("mirror_table_path", ""), row.get("class_path", ""), row.get("package_name", ""),
            row.get("skeleton_path", ""), int(row.get("mirror_axis", 0)), int(row.get("row_count", 0)), _j(row)))
    for row in rows(output / "mirror_data_table_rows.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mirror_data_table_rows VALUES(?,?,?,?,?,?,?,?)", (
            row.get("mirror_table_path", ""), int(row.get("row_index", 0)), row.get("row_name", ""),
            row.get("name", ""), row.get("mirrored_name", ""), int(row.get("mirror_entry_type", 0)),
            int(bool(row.get("enabled", False))), _j(row)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='animation_assets'").fetchone():
        return
    print("\n[animation assets]")
    print_rows(conn.execute(
        "SELECT animation_kind,animation_path,skeleton_path,play_length FROM animation_assets "
        "WHERE animation_path LIKE ? OR animation_kind LIKE ? OR class_path LIKE ? OR skeleton_path LIKE ? OR json LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("animation_kind", "animation_path", "skeleton_path", "play_length"))

    print("\n[pose search]")
    print_rows(conn.execute(
        "SELECT d.database_path,d.schema_path,a.asset_index,a.animation_path FROM pose_search_databases d "
        "LEFT JOIN pose_search_database_assets a ON a.database_path=d.database_path "
        "WHERE d.database_path LIKE ? OR d.schema_path LIKE ? OR a.animation_path LIKE ? OR d.json LIKE ? OR a.json LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("database_path", "schema_path", "asset_index", "animation_path"))

    print("\n[pose search interactions / normalization]")
    print_rows(conn.execute(
        "SELECT i.interaction_path,i.item_index,i.role,i.animation_path FROM pose_search_interaction_items i "
        "WHERE i.interaction_path LIKE ? OR i.role LIKE ? OR i.animation_path LIKE ? OR i.json LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, limit)),
        ("interaction_path", "item_index", "role", "animation_path"))
    print_rows(conn.execute(
        "SELECT normalization_set_path,database_index,database_path FROM pose_search_normalization_databases "
        "WHERE normalization_set_path LIKE ? OR database_path LIKE ? OR json LIKE ? LIMIT ?",
        (pattern, pattern, pattern, limit)),
        ("normalization_set_path", "database_index", "database_path"))

    print("\n[animation curves]")
    print_rows(conn.execute(
        "SELECT asset_path,curve_name,curve_type,key_count FROM animation_curves "
        "WHERE asset_path LIKE ? OR curve_name LIKE ? OR curve_type LIKE ? OR json LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, limit)),
        ("asset_path", "curve_name", "curve_type", "key_count"))

    print("\n[animation notifies / markers]")
    print_rows(conn.execute(
        "SELECT asset_path,notify_name,trigger_time,duration,notify_class FROM animation_notifies "
        "WHERE asset_path LIKE ? OR notify_name LIKE ? OR notify_class LIKE ? OR notify_state_class LIKE ? OR json LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("asset_path", "notify_name", "trigger_time", "duration", "notify_class"))

    print("\n[mirror data tables]")
    print_rows(conn.execute(
        "SELECT r.mirror_table_path,r.name,r.mirrored_name,r.mirror_entry_type,r.enabled FROM mirror_data_table_rows r "
        "WHERE r.mirror_table_path LIKE ? OR r.name LIKE ? OR r.mirrored_name LIKE ? OR r.json LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, limit)),
        ("mirror_table_path", "name", "mirrored_name", "mirror_entry_type", "enabled"))

    print("\n[animation references]")
    print_rows(conn.execute(
        "SELECT asset_path,owner_kind,property_path,reference_kind,target_path,target_class FROM animation_references "
        "WHERE asset_path LIKE ? OR owner_path LIKE ? OR property_path LIKE ? OR target_path LIKE ? OR target_class LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("asset_path", "owner_kind", "property_path", "reference_kind", "target_path", "target_class"))


def read_manifest(output: Path) -> dict | None:
    output = Path(output)
    prepare_output(output, _iter_jsonl)
    return _read_json(output / "animation_manifest.json")


def validation_error(output: Path) -> str | None:
    output = Path(output)
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

    deep = _read_json(output / "animation_deep_manifest.json")
    if deep is None:
        return "UnrealAssetToolAnimationDeep did not write animation_deep_manifest.json"
    if int(deep.get("schema_version", 0) or 0) != DEEP_SCHEMA_VERSION:
        return f"unexpected deep animation schema {deep.get('schema_version')!r}"
    if not bool(deep.get("success", False)):
        return str(deep.get("error", "deep animation scan failed"))
    for filename in deep.get("files", []) or []:
        if not (output / str(filename)).is_file():
            return f"deep animation manifest lists missing output file: {filename}"
    return None
