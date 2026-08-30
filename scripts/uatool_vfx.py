#!/usr/bin/env python3
"""Canonical VFX schema 1 support for UnrealAssetTool."""
from __future__ import annotations

import json
from pathlib import Path

VFX_SCHEMA_VERSION = 1
RAW_FILES = (
    "vfx_manifest.json",
    "vfx_assets.jsonl",
    "vfx_properties.jsonl",
    "vfx_references.jsonl",
    "niagara_systems.jsonl",
    "niagara_system_emitters.jsonl",
    "niagara_emitters.jsonl",
    "niagara_emitter_versions.jsonl",
    "niagara_renderers.jsonl",
    "niagara_simulation_stages.jsonl",
    "niagara_scripts.jsonl",
    "niagara_data_channels.jsonl",
    "niagara_data_channel_variables.jsonl",
    "niagara_effect_types.jsonl",
    "cascade_systems.jsonl",
    "cascade_emitters.jsonl",
    "cascade_lods.jsonl",
    "cascade_modules.jsonl",
)

_SQL = """
CREATE TABLE vfx_assets(
 vfx_path TEXT PRIMARY KEY,vfx_kind TEXT NOT NULL,family TEXT NOT NULL,class_path TEXT NOT NULL,
 package_name TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX vfx_assets_kind_idx ON vfx_assets(vfx_kind,family);
CREATE TABLE vfx_properties(
 asset_path TEXT NOT NULL,owner_path TEXT NOT NULL,owner_kind TEXT NOT NULL,owner_class TEXT NOT NULL,
 declaring_type TEXT NOT NULL,property_name TEXT NOT NULL,property_type TEXT NOT NULL,cpp_type TEXT NOT NULL,
 value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(asset_path,owner_path,declaring_type,property_name));
CREATE INDEX vfx_properties_owner_idx ON vfx_properties(owner_path,property_name);
CREATE TABLE vfx_references(
 asset_path TEXT NOT NULL,owner_path TEXT NOT NULL,owner_kind TEXT NOT NULL,root_property TEXT NOT NULL,
 property_path TEXT NOT NULL,reference_kind TEXT NOT NULL,target_path TEXT NOT NULL,target_class TEXT NOT NULL,
 json TEXT NOT NULL);
CREATE INDEX vfx_references_source_idx ON vfx_references(asset_path,owner_path);
CREATE INDEX vfx_references_target_idx ON vfx_references(target_path,target_class);
CREATE TABLE niagara_systems(
 system_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,emitter_count INTEGER NOT NULL,effect_type_path TEXT NOT NULL,json TEXT NOT NULL);
CREATE TABLE niagara_system_emitters(
 system_path TEXT NOT NULL,emitter_index INTEGER NOT NULL,name TEXT NOT NULL,id TEXT NOT NULL,id_name TEXT NOT NULL,
 enabled INTEGER,emitter_mode TEXT NOT NULL,emitter_path TEXT NOT NULL,emitter_class TEXT NOT NULL,
 emitter_version TEXT NOT NULL,stateless_emitter_path TEXT NOT NULL,stateless_emitter_class TEXT NOT NULL,
 truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(system_path,emitter_index));
CREATE INDEX niagara_system_emitters_target_idx ON niagara_system_emitters(emitter_path);
CREATE TABLE niagara_emitters(
 emitter_path TEXT PRIMARY KEY,asset_path TEXT NOT NULL,class_path TEXT NOT NULL,version_count INTEGER NOT NULL,
 exposed_version TEXT NOT NULL,versioning_enabled INTEGER,json TEXT NOT NULL);
CREATE TABLE niagara_emitter_versions(
 emitter_path TEXT NOT NULL,version_index INTEGER NOT NULL,asset_path TEXT NOT NULL,version TEXT NOT NULL,
 sim_target TEXT NOT NULL,calculate_bounds_mode TEXT NOT NULL,determinism INTEGER,local_space INTEGER,
 renderer_count INTEGER NOT NULL,simulation_stage_count INTEGER NOT NULL,event_handler_count INTEGER NOT NULL,
 truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(emitter_path,version_index));
CREATE TABLE niagara_renderers(
 emitter_path TEXT NOT NULL,version_index INTEGER NOT NULL,renderer_index INTEGER NOT NULL,asset_path TEXT NOT NULL,
 renderer_path TEXT NOT NULL,renderer_class TEXT NOT NULL,enabled INTEGER,sort_order_hint TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(emitter_path,version_index,renderer_index));
CREATE INDEX niagara_renderers_class_idx ON niagara_renderers(renderer_class);
CREATE TABLE niagara_simulation_stages(
 emitter_path TEXT NOT NULL,version_index INTEGER NOT NULL,stage_index INTEGER NOT NULL,asset_path TEXT NOT NULL,
 stage_path TEXT NOT NULL,stage_class TEXT NOT NULL,script_usage_id TEXT NOT NULL,iteration_source TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(emitter_path,version_index,stage_index));
CREATE TABLE niagara_scripts(
 script_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,usage TEXT NOT NULL,usage_id TEXT NOT NULL,
 exposed_version TEXT NOT NULL,version_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE niagara_data_channels(
 data_channel_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,definition_path TEXT NOT NULL,
 definition_class TEXT NOT NULL,variable_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE niagara_data_channel_variables(
 data_channel_path TEXT NOT NULL,variable_index INTEGER NOT NULL,name TEXT NOT NULL,type TEXT NOT NULL,
 truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(data_channel_path,variable_index));
CREATE TABLE niagara_effect_types(
 effect_type_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,update_frequency TEXT NOT NULL,cull_reaction TEXT NOT NULL,json TEXT NOT NULL);
CREATE TABLE cascade_systems(
 system_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,emitter_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE cascade_emitters(
 system_path TEXT NOT NULL,emitter_index INTEGER NOT NULL,emitter_path TEXT NOT NULL,emitter_class TEXT NOT NULL,
 emitter_name TEXT NOT NULL,lod_count INTEGER NOT NULL,significance_level TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(system_path,emitter_index));
CREATE TABLE cascade_lods(
 system_path TEXT NOT NULL,emitter_index INTEGER NOT NULL,lod_index INTEGER NOT NULL,lod_path TEXT NOT NULL,
 level TEXT NOT NULL,enabled INTEGER,module_array_count INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(system_path,emitter_index,lod_index));
CREATE TABLE cascade_modules(
 system_path TEXT NOT NULL,emitter_index INTEGER NOT NULL,lod_index INTEGER NOT NULL,module_index INTEGER NOT NULL,
 role TEXT NOT NULL,module_path TEXT NOT NULL,module_class TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(system_path,emitter_index,lod_index,module_index));
CREATE INDEX cascade_modules_class_idx ON cascade_modules(module_class,role);
"""


def _j(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def _nullable_bool(value):
    return None if value is None else int(bool(value))


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def read_manifest(output: Path) -> dict | None:
    path = Path(output) / "vfx_manifest.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def validation_error(output: Path) -> str | None:
    output = Path(output)
    manifest = read_manifest(output)
    if manifest is None:
        return "vfx_manifest.json missing or invalid"
    if int(manifest.get("schema_version", 0) or 0) != VFX_SCHEMA_VERSION:
        return f"unsupported VFX schema {manifest.get('schema_version')}"
    if not bool(manifest.get("success", False)):
        return str(manifest.get("error", "VFX pass failed") or "VFX pass failed")
    for filename in RAW_FILES[1:]:
        if not (output / filename).is_file():
            return f"VFX output missing {filename}"
    return None


def load_database(conn, output: Path, rows) -> None:
    for r in rows(output / "vfx_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO vfx_assets VALUES(?,?,?,?,?,?)",(
            r.get("vfx_path",""),r.get("vfx_kind",""),r.get("family",""),r.get("class_path",""),r.get("package_name",""),_j(r)))
    for r in rows(output / "vfx_properties.jsonl"):
        conn.execute("INSERT OR REPLACE INTO vfx_properties VALUES(?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("asset_path",""),r.get("owner_path",""),r.get("owner_kind",""),r.get("owner_class",""),
            r.get("declaring_type",""),r.get("property_name",""),r.get("property_type",""),r.get("cpp_type",""),
            r.get("value",""),int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "vfx_references.jsonl"):
        conn.execute("INSERT INTO vfx_references VALUES(?,?,?,?,?,?,?,?,?)",(
            r.get("asset_path",""),r.get("owner_path",""),r.get("owner_kind",""),r.get("root_property",""),
            r.get("property_path",""),r.get("reference_kind",""),r.get("target_path",""),r.get("target_class",""),_j(r)))
    for r in rows(output / "niagara_systems.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_systems VALUES(?,?,?,?,?)",(
            r.get("system_path",""),r.get("package_name",""),int(r.get("emitter_count",0)),r.get("effect_type_path",""),_j(r)))
    for r in rows(output / "niagara_system_emitters.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_system_emitters VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("system_path",""),int(r.get("emitter_index",0)),r.get("name",""),r.get("id",""),r.get("id_name",""),
            _nullable_bool(r.get("enabled")),r.get("emitter_mode",""),r.get("emitter_path",""),r.get("emitter_class",""),
            r.get("emitter_version",""),r.get("stateless_emitter_path",""),r.get("stateless_emitter_class",""),
            int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "niagara_emitters.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_emitters VALUES(?,?,?,?,?,?,?)",(
            r.get("emitter_path",""),r.get("asset_path",""),r.get("class_path",""),int(r.get("version_count",0)),
            r.get("exposed_version",""),_nullable_bool(r.get("versioning_enabled")),_j(r)))
    for r in rows(output / "niagara_emitter_versions.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_emitter_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("emitter_path",""),int(r.get("version_index",0)),r.get("asset_path",""),r.get("version",""),
            r.get("sim_target",""),r.get("calculate_bounds_mode",""),_nullable_bool(r.get("determinism")),
            _nullable_bool(r.get("local_space")),int(r.get("renderer_count",0)),int(r.get("simulation_stage_count",0)),
            int(r.get("event_handler_count",0)),int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "niagara_renderers.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_renderers VALUES(?,?,?,?,?,?,?,?,?)",(
            r.get("emitter_path",""),int(r.get("version_index",0)),int(r.get("renderer_index",0)),r.get("asset_path",""),
            r.get("renderer_path",""),r.get("renderer_class",""),_nullable_bool(r.get("enabled")),r.get("sort_order_hint",""),_j(r)))
    for r in rows(output / "niagara_simulation_stages.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_simulation_stages VALUES(?,?,?,?,?,?,?,?,?)",(
            r.get("emitter_path",""),int(r.get("version_index",0)),int(r.get("stage_index",0)),r.get("asset_path",""),
            r.get("stage_path",""),r.get("stage_class",""),r.get("script_usage_id",""),r.get("iteration_source",""),_j(r)))
    for r in rows(output / "niagara_scripts.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_scripts VALUES(?,?,?,?,?,?,?)",(
            r.get("script_path",""),r.get("package_name",""),r.get("usage",""),r.get("usage_id",""),
            r.get("exposed_version",""),int(r.get("version_count",0)),_j(r)))
    for r in rows(output / "niagara_data_channels.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_data_channels VALUES(?,?,?,?,?,?)",(
            r.get("data_channel_path",""),r.get("package_name",""),r.get("definition_path",""),
            r.get("definition_class",""),int(r.get("variable_count",0)),_j(r)))
    for r in rows(output / "niagara_data_channel_variables.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_data_channel_variables VALUES(?,?,?,?,?,?)",(
            r.get("data_channel_path",""),int(r.get("variable_index",0)),r.get("name",""),r.get("type",""),
            int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "niagara_effect_types.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_effect_types VALUES(?,?,?,?,?)",(
            r.get("effect_type_path",""),r.get("package_name",""),r.get("update_frequency",""),r.get("cull_reaction",""),_j(r)))
    for r in rows(output / "cascade_systems.jsonl"):
        conn.execute("INSERT OR REPLACE INTO cascade_systems VALUES(?,?,?,?)",(
            r.get("system_path",""),r.get("package_name",""),int(r.get("emitter_count",0)),_j(r)))
    for r in rows(output / "cascade_emitters.jsonl"):
        conn.execute("INSERT OR REPLACE INTO cascade_emitters VALUES(?,?,?,?,?,?,?,?)",(
            r.get("system_path",""),int(r.get("emitter_index",0)),r.get("emitter_path",""),r.get("emitter_class",""),
            r.get("emitter_name",""),int(r.get("lod_count",0)),r.get("significance_level",""),_j(r)))
    for r in rows(output / "cascade_lods.jsonl"):
        conn.execute("INSERT OR REPLACE INTO cascade_lods VALUES(?,?,?,?,?,?,?,?)",(
            r.get("system_path",""),int(r.get("emitter_index",0)),int(r.get("lod_index",0)),r.get("lod_path",""),
            r.get("level",""),_nullable_bool(r.get("enabled")),int(r.get("module_array_count",0)),_j(r)))
    for r in rows(output / "cascade_modules.jsonl"):
        conn.execute("INSERT OR REPLACE INTO cascade_modules VALUES(?,?,?,?,?,?,?,?)",(
            r.get("system_path",""),int(r.get("emitter_index",0)),int(r.get("lod_index",0)),int(r.get("module_index",0)),
            r.get("role",""),r.get("module_path",""),r.get("module_class",""),_j(r)))


def query(conn, print_rows, q: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='vfx_assets'").fetchone():
        return
    print("\n[vfx assets]")
    print_rows(conn.execute(
        "SELECT vfx_path,vfx_kind,family,class_path FROM vfx_assets WHERE vfx_path LIKE ? OR vfx_kind LIKE ? OR class_path LIKE ? LIMIT ?",
        (q,q,q,limit)),("vfx_path","vfx_kind","family","class_path"))
    print("\n[niagara systems]")
    print_rows(conn.execute(
        "SELECT system_path,emitter_count,effect_type_path FROM niagara_systems WHERE system_path LIKE ? OR effect_type_path LIKE ? LIMIT ?",
        (q,q,limit)),("system_path","emitter_count","effect_type_path"))
    print("\n[niagara renderers]")
    print_rows(conn.execute(
        "SELECT emitter_path,version_index,renderer_index,renderer_class FROM niagara_renderers WHERE emitter_path LIKE ? OR renderer_class LIKE ? LIMIT ?",
        (q,q,limit)),("emitter_path","version_index","renderer_index","renderer_class"))
    print("\n[cascade modules]")
    print_rows(conn.execute(
        "SELECT system_path,emitter_index,lod_index,role,module_class FROM cascade_modules WHERE system_path LIKE ? OR module_class LIKE ? OR role LIKE ? LIMIT ?",
        (q,q,q,limit)),("system_path","emitter_index","lod_index","role","module_class"))
    print("\n[vfx references]")
    print_rows(conn.execute(
        "SELECT asset_path,owner_kind,property_path,target_class,target_path FROM vfx_references WHERE asset_path LIKE ? OR property_path LIKE ? OR target_path LIKE ? OR target_class LIKE ? LIMIT ?",
        (q,q,q,q,limit)),("asset_path","owner_kind","property_path","target_class","target_path"))
