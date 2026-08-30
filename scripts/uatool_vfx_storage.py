#!/usr/bin/env python3
"""VFX schema 1 SQLite storage and query helpers."""
from __future__ import annotations

from uatool_vfx_defs import _j, _nullable_bool

def load_database(conn, output: Path, rows) -> None:
    for r in rows(output / "vfx_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO vfx_assets VALUES(?,?,?,?,?,?)", (
            r.get("vfx_path",""),r.get("vfx_kind",""),r.get("family",""),
            r.get("class_path",""),r.get("package_name",""),_j(r)))

    for r in rows(output / "vfx_properties.jsonl"):
        conn.execute("INSERT OR REPLACE INTO vfx_properties VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("asset_path",""),r.get("owner_path",""),r.get("owner_kind",""),
            r.get("owner_class",""),r.get("declaring_type",""),r.get("property_name",""),
            r.get("property_type",""),r.get("cpp_type",""),r.get("value",""),
            int(bool(r.get("truncated",False))),_j(r)))

    for r in rows(output / "vfx_references.jsonl"):
        conn.execute("INSERT INTO vfx_references VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("asset_path",""),r.get("owner_path",""),r.get("owner_kind",""),
            r.get("root_property",""),r.get("property_path",""),r.get("reference_kind",""),
            r.get("target_path",""),r.get("target_class",""),_j(r)))

    for r in rows(output / "niagara_systems.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_systems VALUES(?,?,?,?,?)", (
            r.get("system_path",""),r.get("package_name",""),int(r.get("emitter_count",0)),
            r.get("effect_type_path",""),_j(r)))

    for r in rows(output / "niagara_system_emitters.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_system_emitters VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("system_path",""),int(r.get("emitter_index",0)),r.get("name",""),
            r.get("id",""),r.get("id_name",""),_nullable_bool(r.get("enabled")),
            r.get("emitter_mode",""),r.get("emitter_path",""),r.get("emitter_class",""),
            r.get("emitter_version",""),r.get("stateless_emitter_path",""),
            r.get("stateless_emitter_class",""),int(bool(r.get("truncated",False))),_j(r)))

    for r in rows(output / "niagara_emitters.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_emitters VALUES(?,?,?,?,?,?,?)", (
            r.get("emitter_path",""),r.get("asset_path",""),r.get("class_path",""),
            int(r.get("version_count",0)),r.get("exposed_version",""),
            _nullable_bool(r.get("versioning_enabled")),_j(r)))

    for r in rows(output / "niagara_emitter_versions.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_emitter_versions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("emitter_path",""),int(r.get("version_index",0)),r.get("asset_path",""),
            r.get("version",""),r.get("sim_target",""),r.get("calculate_bounds_mode",""),
            _nullable_bool(r.get("determinism")),_nullable_bool(r.get("local_space")),
            int(r.get("renderer_count",0)),int(r.get("simulation_stage_count",0)),
            int(r.get("event_handler_count",0)),int(bool(r.get("truncated",False))),_j(r)))

    for r in rows(output / "niagara_renderers.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_renderers VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("emitter_path",""),int(r.get("version_index",0)),int(r.get("renderer_index",0)),
            r.get("asset_path",""),r.get("renderer_path",""),r.get("renderer_class",""),
            _nullable_bool(r.get("enabled")),r.get("sort_order_hint",""),_j(r)))

    for r in rows(output / "niagara_simulation_stages.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_simulation_stages VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("emitter_path",""),int(r.get("version_index",0)),int(r.get("stage_index",0)),
            r.get("asset_path",""),r.get("stage_path",""),r.get("stage_class",""),
            r.get("script_usage_id",""),r.get("iteration_source",""),_j(r)))

    for r in rows(output / "niagara_stateless_emitters.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_stateless_emitters VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("emitter_path",""),r.get("asset_path",""),r.get("class_path",""),
            int(r.get("module_count",0)),int(r.get("renderer_count",0)),
            _nullable_bool(r.get("deterministic")),r.get("random_seed",""),
            r.get("fixed_bounds",""),_j(r)))

    for r in rows(output / "niagara_stateless_modules.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_stateless_modules VALUES(?,?,?,?,?,?,?)", (
            r.get("emitter_path",""),int(r.get("module_index",0)),r.get("asset_path",""),
            r.get("module_path",""),r.get("module_class",""),
            _nullable_bool(r.get("enabled")),_j(r)))

    for r in rows(output / "niagara_stateless_renderers.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_stateless_renderers VALUES(?,?,?,?,?,?,?,?)", (
            r.get("emitter_path",""),int(r.get("renderer_index",0)),r.get("asset_path",""),
            r.get("renderer_path",""),r.get("renderer_class",""),
            _nullable_bool(r.get("enabled")),r.get("sort_order_hint",""),_j(r)))

    for r in rows(output / "niagara_scripts.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_scripts VALUES(?,?,?,?,?,?,?)", (
            r.get("script_path",""),r.get("package_name",""),r.get("usage",""),
            r.get("usage_id",""),r.get("exposed_version",""),int(r.get("version_count",0)),_j(r)))

    for r in rows(output / "niagara_data_channels.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_data_channels VALUES(?,?,?,?,?,?)", (
            r.get("data_channel_path",""),r.get("package_name",""),r.get("definition_path",""),
            r.get("definition_class",""),int(r.get("variable_count",0)),_j(r)))

    for r in rows(output / "niagara_data_channel_variables.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_data_channel_variables VALUES(?,?,?,?,?,?,?)", (
            r.get("data_channel_path",""),int(r.get("variable_index",0)),r.get("version",""),
            r.get("name",""),r.get("type",""),int(bool(r.get("truncated",False))),_j(r)))

    for r in rows(output / "niagara_parameter_collections.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_parameter_collections VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("collection_path",""),r.get("package_name",""),r.get("namespace",""),
            int(r.get("parameter_count",0)),r.get("source_collection_path",""),
            r.get("source_collection_class",""),r.get("default_instance_path",""),
            r.get("default_instance_class",""),_j(r)))

    for r in rows(output / "niagara_parameter_collection_parameters.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_parameter_collection_parameters VALUES(?,?,?,?,?,?)", (
            r.get("collection_path",""),int(r.get("parameter_index",0)),r.get("name",""),
            r.get("type",""),int(bool(r.get("truncated",False))),_j(r)))

    for r in rows(output / "niagara_effect_types.jsonl"):
        conn.execute("INSERT OR REPLACE INTO niagara_effect_types VALUES(?,?,?,?,?)", (
            r.get("effect_type_path",""),r.get("package_name",""),
            r.get("update_frequency",""),r.get("cull_reaction",""),_j(r)))

    for r in rows(output / "cascade_systems.jsonl"):
        conn.execute("INSERT OR REPLACE INTO cascade_systems VALUES(?,?,?,?)", (
            r.get("system_path",""),r.get("package_name",""),int(r.get("emitter_count",0)),_j(r)))

    for r in rows(output / "cascade_emitters.jsonl"):
        conn.execute("INSERT OR REPLACE INTO cascade_emitters VALUES(?,?,?,?,?,?,?,?)", (
            r.get("system_path",""),int(r.get("emitter_index",0)),r.get("emitter_path",""),
            r.get("emitter_class",""),r.get("emitter_name",""),int(r.get("lod_count",0)),
            r.get("significance_level",""),_j(r)))

    for r in rows(output / "cascade_lods.jsonl"):
        conn.execute("INSERT OR REPLACE INTO cascade_lods VALUES(?,?,?,?,?,?,?,?)", (
            r.get("system_path",""),int(r.get("emitter_index",0)),int(r.get("lod_index",0)),
            r.get("lod_path",""),r.get("level",""),_nullable_bool(r.get("enabled")),
            int(r.get("module_array_count",0)),_j(r)))

    for r in rows(output / "cascade_modules.jsonl"):
        conn.execute("INSERT OR REPLACE INTO cascade_modules VALUES(?,?,?,?,?,?,?,?)", (
            r.get("system_path",""),int(r.get("emitter_index",0)),int(r.get("lod_index",0)),
            int(r.get("module_index",0)),r.get("role",""),r.get("module_path",""),
            r.get("module_class",""),_j(r)))


def query(conn, print_rows, q: str, limit: int) -> None:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vfx_assets'"
    ).fetchone():
        return

    print("\n[vfx assets]")
    print_rows(conn.execute(
        "SELECT vfx_path,vfx_kind,family,class_path FROM vfx_assets "
        "WHERE vfx_path LIKE ? OR vfx_kind LIKE ? OR class_path LIKE ? LIMIT ?",
        (q,q,q,limit)),
        ("vfx_path","vfx_kind","family","class_path"))

    print("\n[niagara systems]")
    print_rows(conn.execute(
        "SELECT system_path,emitter_count,effect_type_path FROM niagara_systems "
        "WHERE system_path LIKE ? OR effect_type_path LIKE ? LIMIT ?",
        (q,q,limit)),
        ("system_path","emitter_count","effect_type_path"))

    print("\n[niagara renderers]")
    print_rows(conn.execute(
        "SELECT emitter_path,version_index,renderer_index,renderer_class FROM niagara_renderers "
        "WHERE emitter_path LIKE ? OR renderer_class LIKE ? LIMIT ?",
        (q,q,limit)),
        ("emitter_path","version_index","renderer_index","renderer_class"))

    print("\n[niagara stateless modules]")
    print_rows(conn.execute(
        "SELECT emitter_path,module_index,module_class,enabled FROM niagara_stateless_modules "
        "WHERE emitter_path LIKE ? OR module_class LIKE ? LIMIT ?",
        (q,q,limit)),
        ("emitter_path","module_index","module_class","enabled"))

    print("\n[niagara data channels]")
    print_rows(conn.execute(
        "SELECT data_channel_path,definition_class,variable_count FROM niagara_data_channels "
        "WHERE data_channel_path LIKE ? OR definition_class LIKE ? LIMIT ?",
        (q,q,limit)),
        ("data_channel_path","definition_class","variable_count"))

    print("\n[niagara parameter collections]")
    print_rows(conn.execute(
        "SELECT collection_path,namespace,parameter_count,source_collection_path "
        "FROM niagara_parameter_collections "
        "WHERE collection_path LIKE ? OR namespace LIKE ? OR source_collection_path LIKE ? LIMIT ?",
        (q,q,q,limit)),
        ("collection_path","namespace","parameter_count","source_collection_path"))

    print("\n[cascade modules]")
    print_rows(conn.execute(
        "SELECT system_path,emitter_index,lod_index,role,module_class FROM cascade_modules "
        "WHERE system_path LIKE ? OR module_class LIKE ? OR role LIKE ? LIMIT ?",
        (q,q,q,limit)),
        ("system_path","emitter_index","lod_index","role","module_class"))

    print("\n[vfx references]")
    print_rows(conn.execute(
        "SELECT asset_path,owner_kind,property_path,target_class,target_path FROM vfx_references "
        "WHERE asset_path LIKE ? OR owner_path LIKE ? OR property_path LIKE ? "
        "OR target_class LIKE ? OR target_path LIKE ? LIMIT ?",
        (q,q,q,q,q,limit)),
        ("asset_path","owner_kind","property_path","target_class","target_path"))
