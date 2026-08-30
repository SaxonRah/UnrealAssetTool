#!/usr/bin/env python3
"""Content-breadth support for animation schema 1."""

from __future__ import annotations

import json
from pathlib import Path

BREADTH_SCHEMA_VERSION = 1

RAW_FILES = (
    "animation_breadth_manifest.json",
    "pose_assets.jsonl",
    "pose_asset_tracks.jsonl",
    "pose_asset_poses.jsonl",
    "pose_asset_transforms.jsonl",
    "pose_asset_curve_values.jsonl",
    "skeleton_slot_groups.jsonl",
    "skeleton_slots.jsonl",
    "chooser_tables.jsonl",
    "chooser_columns.jsonl",
    "chooser_results.jsonl",
    "chooser_context.jsonl",
    "proxy_tables.jsonl",
    "proxy_entries.jsonl",
    "proxy_table_inheritance.jsonl",
    "ik_rigs.jsonl",
    "ik_rig_bones.jsonl",
    "ik_rig_chains.jsonl",
    "ik_rig_goals.jsonl",
    "ik_rig_solvers.jsonl",
    "ik_retargeters.jsonl",
    "ik_retarget_ops.jsonl",
    "ik_retarget_poses.jsonl",
    "animation_struct_references.jsonl",
)

_SQL = """
CREATE TABLE pose_assets(
    pose_asset_path TEXT PRIMARY KEY,
    skeleton_path TEXT NOT NULL,
    source_animation_path TEXT NOT NULL,
    additive INTEGER NOT NULL,
    base_pose_index INTEGER NOT NULL,
    pose_count INTEGER NOT NULL,
    track_count INTEGER NOT NULL,
    curve_count INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX pose_assets_skeleton_idx ON pose_assets(skeleton_path);
CREATE INDEX pose_assets_source_idx ON pose_assets(source_animation_path);
CREATE TABLE pose_asset_tracks(
    pose_asset_path TEXT NOT NULL,
    track_index INTEGER NOT NULL,
    track_name TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(pose_asset_path,track_index)
);
CREATE INDEX pose_asset_tracks_name_idx ON pose_asset_tracks(track_name);
CREATE TABLE pose_asset_poses(
    pose_asset_path TEXT NOT NULL,
    pose_index INTEGER NOT NULL,
    pose_name TEXT NOT NULL,
    full_transform_count INTEGER NOT NULL,
    full_curve_count INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(pose_asset_path,pose_index)
);
CREATE INDEX pose_asset_poses_name_idx ON pose_asset_poses(pose_name);
CREATE TABLE pose_asset_transforms(
    pose_asset_path TEXT NOT NULL,
    pose_index INTEGER NOT NULL,
    track_index INTEGER NOT NULL,
    track_name TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(pose_asset_path,pose_index,track_index)
);
CREATE INDEX pose_asset_transforms_track_idx ON pose_asset_transforms(track_name,pose_asset_path);
CREATE TABLE pose_asset_curve_values(
    pose_asset_path TEXT NOT NULL,
    pose_index INTEGER NOT NULL,
    curve_index INTEGER NOT NULL,
    curve_name TEXT NOT NULL,
    raw_value REAL,
    full_value REAL,
    json TEXT NOT NULL,
    PRIMARY KEY(pose_asset_path,pose_index,curve_index)
);
CREATE INDEX pose_asset_curve_values_name_idx ON pose_asset_curve_values(curve_name,pose_asset_path);

CREATE TABLE skeleton_slot_groups(
    skeleton_path TEXT NOT NULL,
    group_index INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    slot_count INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(skeleton_path,group_index)
);
CREATE TABLE skeleton_slots(
    skeleton_path TEXT NOT NULL,
    group_index INTEGER NOT NULL,
    slot_index INTEGER NOT NULL,
    group_name TEXT NOT NULL,
    slot_name TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(skeleton_path,group_index,slot_index)
);
CREATE INDEX skeleton_slots_name_idx ON skeleton_slots(slot_name,group_name);

CREATE TABLE chooser_tables(
    chooser_path TEXT PRIMARY KEY,
    column_count INTEGER NOT NULL,
    result_count INTEGER NOT NULL,
    context_count INTEGER NOT NULL,
    disabled_row_count INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE chooser_columns(
    chooser_path TEXT NOT NULL,
    column_index INTEGER NOT NULL,
    struct_type TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    truncated INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(chooser_path,column_index)
);
CREATE INDEX chooser_columns_type_idx ON chooser_columns(struct_type);
CREATE TABLE chooser_results(
    chooser_path TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    struct_type TEXT NOT NULL,
    disabled INTEGER NOT NULL,
    raw_value TEXT NOT NULL,
    truncated INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(chooser_path,row_index)
);
CREATE INDEX chooser_results_type_idx ON chooser_results(struct_type);
CREATE TABLE chooser_context(
    chooser_path TEXT NOT NULL,
    context_index INTEGER NOT NULL,
    struct_type TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    truncated INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(chooser_path,context_index)
);

CREATE TABLE proxy_tables(
    proxy_table_path TEXT PRIMARY KEY,
    entry_count INTEGER NOT NULL,
    inherit_table_count INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE proxy_entries(
    proxy_table_path TEXT NOT NULL,
    entry_index INTEGER NOT NULL,
    proxy_path TEXT NOT NULL,
    value_struct_type TEXT NOT NULL,
    value_raw TEXT NOT NULL,
    truncated INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(proxy_table_path,entry_index)
);
CREATE INDEX proxy_entries_proxy_idx ON proxy_entries(proxy_path);
CREATE TABLE proxy_table_inheritance(
    proxy_table_path TEXT NOT NULL,
    inherit_index INTEGER NOT NULL,
    parent_table_path TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(proxy_table_path,inherit_index)
);

CREATE TABLE ik_rigs(
    ik_rig_path TEXT PRIMARY KEY,
    preview_mesh_path TEXT NOT NULL,
    skeleton_mesh_path TEXT NOT NULL,
    root_bone TEXT NOT NULL,
    pelvis_bone TEXT NOT NULL,
    bone_count INTEGER NOT NULL,
    chain_count INTEGER NOT NULL,
    goal_count INTEGER NOT NULL,
    solver_count INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE ik_rig_bones(
    ik_rig_path TEXT NOT NULL,
    bone_index INTEGER NOT NULL,
    bone_name TEXT NOT NULL,
    parent_index INTEGER NOT NULL,
    excluded INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(ik_rig_path,bone_index)
);
CREATE INDEX ik_rig_bones_name_idx ON ik_rig_bones(bone_name);
CREATE TABLE ik_rig_chains(
    ik_rig_path TEXT NOT NULL,
    chain_index INTEGER NOT NULL,
    chain_name TEXT NOT NULL,
    start_bone TEXT NOT NULL,
    end_bone TEXT NOT NULL,
    ik_goal_name TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(ik_rig_path,chain_index)
);
CREATE INDEX ik_rig_chains_name_idx ON ik_rig_chains(chain_name,ik_goal_name);
CREATE TABLE ik_rig_goals(
    ik_rig_path TEXT NOT NULL,
    goal_index INTEGER NOT NULL,
    goal_name TEXT NOT NULL,
    bone_name TEXT NOT NULL,
    goal_path TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(ik_rig_path,goal_index)
);
CREATE INDEX ik_rig_goals_name_idx ON ik_rig_goals(goal_name,bone_name);
CREATE TABLE ik_rig_solvers(
    ik_rig_path TEXT NOT NULL,
    solver_index INTEGER NOT NULL,
    struct_type TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    truncated INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(ik_rig_path,solver_index)
);
CREATE INDEX ik_rig_solvers_type_idx ON ik_rig_solvers(struct_type);

CREATE TABLE ik_retargeters(
    retargeter_path TEXT PRIMARY KEY,
    source_ik_rig_path TEXT NOT NULL,
    target_ik_rig_path TEXT NOT NULL,
    op_count INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX ik_retargeters_source_idx ON ik_retargeters(source_ik_rig_path);
CREATE INDEX ik_retargeters_target_idx ON ik_retargeters(target_ik_rig_path);
CREATE TABLE ik_retarget_ops(
    retargeter_path TEXT NOT NULL,
    op_index INTEGER NOT NULL,
    struct_type TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    truncated INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(retargeter_path,op_index)
);
CREATE INDEX ik_retarget_ops_type_idx ON ik_retarget_ops(struct_type);
CREATE TABLE ik_retarget_poses(
    retargeter_path TEXT NOT NULL,
    side TEXT NOT NULL,
    pose_index INTEGER NOT NULL,
    pose_name TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    truncated INTEGER NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(retargeter_path,side,pose_index)
);
CREATE INDEX ik_retarget_poses_name_idx ON ik_retarget_poses(pose_name,side);

CREATE TABLE animation_struct_references(
    owner_path TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_index INTEGER NOT NULL,
    reference_kind TEXT NOT NULL,
    target_path TEXT NOT NULL,
    target_class TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(owner_path,source_kind,source_index,target_path,target_class)
);
CREATE INDEX animation_struct_refs_target_idx ON animation_struct_references(target_path,target_class);
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


def prepare_output(output: Path) -> None:
    """Merge the breadth companion manifest into public animation schema 1."""
    output = Path(output)
    animation_manifest = _read_json(output / "animation_manifest.json")
    breadth_manifest = _read_json(output / "animation_breadth_manifest.json")
    if animation_manifest is None or breadth_manifest is None:
        return
    counts = animation_manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    breadth_counts = breadth_manifest.get("counts", {})
    if isinstance(breadth_counts, dict):
        counts.update(breadth_counts)
    animation_manifest["counts"] = counts
    animation_manifest["breadth_schema_version"] = int(breadth_manifest.get("schema_version", 0) or 0)
    files = [str(v) for v in (animation_manifest.get("files", []) or [])]
    for filename in RAW_FILES:
        if filename != "animation_breadth_manifest.json" and filename not in files:
            files.append(filename)
    animation_manifest["files"] = files
    (output / "animation_manifest.json").write_text(
        json.dumps(animation_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _nullable_float(value):
    return None if value is None else float(value)


def load_database(conn, output: Path, rows) -> None:
    for row in rows(output / "pose_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_assets VALUES(?,?,?,?,?,?,?,?,?)", (
            row.get("pose_asset_path", ""), row.get("skeleton_path", ""), row.get("source_animation_path", ""),
            int(bool(row.get("additive", False))), int(row.get("base_pose_index", -1)), int(row.get("pose_count", 0)),
            int(row.get("track_count", 0)), int(row.get("curve_count", 0)), _j(row)))
    for row in rows(output / "pose_asset_tracks.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_asset_tracks VALUES(?,?,?,?)", (
            row.get("pose_asset_path", ""), int(row.get("track_index", 0)), row.get("track_name", ""), _j(row)))
    for row in rows(output / "pose_asset_poses.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_asset_poses VALUES(?,?,?,?,?,?)", (
            row.get("pose_asset_path", ""), int(row.get("pose_index", 0)), row.get("pose_name", ""),
            int(row.get("full_transform_count", 0)), int(row.get("full_curve_count", 0)), _j(row)))
    for row in rows(output / "pose_asset_transforms.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_asset_transforms VALUES(?,?,?,?,?)", (
            row.get("pose_asset_path", ""), int(row.get("pose_index", 0)), int(row.get("track_index", 0)),
            row.get("track_name", ""), _j(row)))
    for row in rows(output / "pose_asset_curve_values.jsonl"):
        conn.execute("INSERT OR REPLACE INTO pose_asset_curve_values VALUES(?,?,?,?,?,?,?)", (
            row.get("pose_asset_path", ""), int(row.get("pose_index", 0)), int(row.get("curve_index", 0)),
            row.get("curve_name", ""), _nullable_float(row.get("raw_value")), _nullable_float(row.get("full_value")), _j(row)))
    for row in rows(output / "skeleton_slot_groups.jsonl"):
        conn.execute("INSERT OR REPLACE INTO skeleton_slot_groups VALUES(?,?,?,?,?)", (
            row.get("skeleton_path", ""), int(row.get("group_index", 0)), row.get("group_name", ""),
            int(row.get("slot_count", 0)), _j(row)))
    for row in rows(output / "skeleton_slots.jsonl"):
        conn.execute("INSERT OR REPLACE INTO skeleton_slots VALUES(?,?,?,?,?,?)", (
            row.get("skeleton_path", ""), int(row.get("group_index", 0)), int(row.get("slot_index", 0)),
            row.get("group_name", ""), row.get("slot_name", ""), _j(row)))
    for row in rows(output / "chooser_tables.jsonl"):
        conn.execute("INSERT OR REPLACE INTO chooser_tables VALUES(?,?,?,?,?,?)", (
            row.get("chooser_path", ""), int(row.get("column_count", 0)), int(row.get("result_count", 0)),
            int(row.get("context_count", 0)), int(row.get("disabled_row_count", 0)), _j(row)))
    for filename, table, owner_key, index_key, disabled in (
        ("chooser_columns.jsonl", "chooser_columns", "asset_path", "index", False),
        ("chooser_results.jsonl", "chooser_results", "asset_path", "index", True),
        ("chooser_context.jsonl", "chooser_context", "asset_path", "index", False),
    ):
        for row in rows(output / filename):
            if table == "chooser_results":
                conn.execute("INSERT OR REPLACE INTO chooser_results VALUES(?,?,?,?,?,?,?)", (
                    row.get(owner_key, ""), int(row.get(index_key, 0)), row.get("struct_type", ""),
                    int(bool(row.get("disabled", False))), row.get("raw_value", ""), int(bool(row.get("truncated", False))), _j(row)))
            else:
                conn.execute(f"INSERT OR REPLACE INTO {table} VALUES(?,?,?,?,?,?)", (
                    row.get(owner_key, ""), int(row.get(index_key, 0)), row.get("struct_type", ""),
                    row.get("raw_value", ""), int(bool(row.get("truncated", False))), _j(row)))
    for row in rows(output / "proxy_tables.jsonl"):
        conn.execute("INSERT OR REPLACE INTO proxy_tables VALUES(?,?,?,?)", (
            row.get("proxy_table_path", ""), int(row.get("entry_count", 0)), int(row.get("inherit_table_count", 0)), _j(row)))
    for row in rows(output / "proxy_entries.jsonl"):
        conn.execute("INSERT OR REPLACE INTO proxy_entries VALUES(?,?,?,?,?,?,?)", (
            row.get("proxy_table_path", ""), int(row.get("entry_index", 0)), row.get("proxy_path", ""),
            row.get("value_struct_type", ""), row.get("value_raw", ""), int(bool(row.get("truncated", False))), _j(row)))
    for row in rows(output / "proxy_table_inheritance.jsonl"):
        conn.execute("INSERT OR REPLACE INTO proxy_table_inheritance VALUES(?,?,?,?)", (
            row.get("proxy_table_path", ""), int(row.get("inherit_index", 0)), row.get("parent_table_path", ""), _j(row)))
    for row in rows(output / "ik_rigs.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ik_rigs VALUES(?,?,?,?,?,?,?,?,?,?)", (
            row.get("ik_rig_path", ""), row.get("preview_mesh_path", ""), row.get("skeleton_mesh_path", ""),
            row.get("root_bone", ""), row.get("pelvis_bone", ""), int(row.get("bone_count", 0)),
            int(row.get("chain_count", 0)), int(row.get("goal_count", 0)), int(row.get("solver_count", 0)), _j(row)))
    for row in rows(output / "ik_rig_bones.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ik_rig_bones VALUES(?,?,?,?,?,?)", (
            row.get("ik_rig_path", ""), int(row.get("bone_index", 0)), row.get("bone_name", ""),
            int(row.get("parent_index", -1)), int(bool(row.get("excluded", False))), _j(row)))
    for row in rows(output / "ik_rig_chains.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ik_rig_chains VALUES(?,?,?,?,?,?,?)", (
            row.get("ik_rig_path", ""), int(row.get("chain_index", 0)), row.get("chain_name", ""),
            row.get("start_bone", ""), row.get("end_bone", ""), row.get("ik_goal_name", ""), _j(row)))
    for row in rows(output / "ik_rig_goals.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ik_rig_goals VALUES(?,?,?,?,?,?)", (
            row.get("ik_rig_path", ""), int(row.get("goal_index", 0)), row.get("goal_name", ""),
            row.get("bone_name", ""), row.get("goal_path", ""), _j(row)))
    for row in rows(output / "ik_rig_solvers.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ik_rig_solvers VALUES(?,?,?,?,?,?)", (
            row.get("asset_path", ""), int(row.get("index", 0)), row.get("struct_type", ""), row.get("raw_value", ""),
            int(bool(row.get("truncated", False))), _j(row)))
    for row in rows(output / "ik_retargeters.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ik_retargeters VALUES(?,?,?,?,?)", (
            row.get("retargeter_path", ""), row.get("source_ik_rig_path", ""), row.get("target_ik_rig_path", ""),
            int(row.get("op_count", 0)), _j(row)))
    for row in rows(output / "ik_retarget_ops.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ik_retarget_ops VALUES(?,?,?,?,?,?)", (
            row.get("asset_path", ""), int(row.get("index", 0)), row.get("struct_type", ""), row.get("raw_value", ""),
            int(bool(row.get("truncated", False))), _j(row)))
    for row in rows(output / "ik_retarget_poses.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ik_retarget_poses VALUES(?,?,?,?,?,?,?)", (
            row.get("retargeter_path", ""), row.get("side", ""), int(row.get("pose_index", 0)), row.get("pose_name", ""),
            row.get("raw_value", ""), int(bool(row.get("truncated", False))), _j(row)))
    for row in rows(output / "animation_struct_references.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_struct_references VALUES(?,?,?,?,?,?,?)", (
            row.get("owner_path", ""), row.get("source_kind", ""), int(row.get("source_index", 0)),
            row.get("reference_kind", ""), row.get("target_path", ""), row.get("target_class", ""), _j(row)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='pose_assets'").fetchone():
        return
    print("\n[pose assets]")
    print_rows(conn.execute(
        "SELECT pose_asset_path,skeleton_path,source_animation_path,pose_count,track_count,curve_count FROM pose_assets "
        "WHERE pose_asset_path LIKE ? OR skeleton_path LIKE ? OR source_animation_path LIKE ? OR json LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, limit)),
        ("pose_asset_path", "skeleton_path", "source_animation_path", "pose_count", "track_count", "curve_count"))
    print("\n[chooser / proxy]")
    print_rows(conn.execute(
        "SELECT chooser_path,row_index,struct_type,disabled,substr(raw_value,1,600) raw_value FROM chooser_results "
        "WHERE chooser_path LIKE ? OR struct_type LIKE ? OR raw_value LIKE ? LIMIT ?",
        (pattern, pattern, pattern, limit)),
        ("chooser_path", "row_index", "struct_type", "disabled", "raw_value"))
    print_rows(conn.execute(
        "SELECT proxy_table_path,entry_index,proxy_path,value_struct_type,substr(value_raw,1,600) value_raw FROM proxy_entries "
        "WHERE proxy_table_path LIKE ? OR proxy_path LIKE ? OR value_struct_type LIKE ? OR value_raw LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, limit)),
        ("proxy_table_path", "entry_index", "proxy_path", "value_struct_type", "value_raw"))
    print("\n[IK rigs / retargeters]")
    print_rows(conn.execute(
        "SELECT ik_rig_path,chain_name,start_bone,end_bone,ik_goal_name FROM ik_rig_chains "
        "WHERE ik_rig_path LIKE ? OR chain_name LIKE ? OR start_bone LIKE ? OR end_bone LIKE ? OR ik_goal_name LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("ik_rig_path", "chain_name", "start_bone", "end_bone", "ik_goal_name"))
    print_rows(conn.execute(
        "SELECT retargeter_path,op_index,struct_type,substr(raw_value,1,600) raw_value FROM ik_retarget_ops "
        "WHERE retargeter_path LIKE ? OR struct_type LIKE ? OR raw_value LIKE ? LIMIT ?",
        (pattern, pattern, pattern, limit)),
        ("retargeter_path", "op_index", "struct_type", "raw_value"))
    print("\n[animation struct references]")
    print_rows(conn.execute(
        "SELECT owner_path,source_kind,source_index,target_path,target_class FROM animation_struct_references "
        "WHERE owner_path LIKE ? OR source_kind LIKE ? OR target_path LIKE ? OR target_class LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, limit)),
        ("owner_path", "source_kind", "source_index", "target_path", "target_class"))


def validation_error(output: Path) -> str | None:
    output = Path(output)
    manifest = _read_json(output / "animation_breadth_manifest.json")
    if manifest is None:
        return "UnrealAssetToolAnimationBreadth did not write animation_breadth_manifest.json"
    if int(manifest.get("schema_version", 0) or 0) != BREADTH_SCHEMA_VERSION:
        return f"unexpected breadth animation schema {manifest.get('schema_version')!r}"
    if not bool(manifest.get("success", False)):
        return str(manifest.get("error", "breadth animation scan failed"))
    for filename in manifest.get("files", []) or []:
        if not (output / str(filename)).is_file():
            return f"breadth animation manifest lists missing output file: {filename}"
    return None
