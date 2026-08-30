#!/usr/bin/env python3
"""Canonical VFX schema 1 support for UnrealAssetTool."""
from __future__ import annotations

import collections
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
    "niagara_stateless_emitters.jsonl",
    "niagara_stateless_modules.jsonl",
    "niagara_stateless_renderers.jsonl",
    "niagara_scripts.jsonl",
    "niagara_data_channels.jsonl",
    "niagara_data_channel_variables.jsonl",
    "niagara_parameter_collections.jsonl",
    "niagara_parameter_collection_parameters.jsonl",
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
 system_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,emitter_count INTEGER NOT NULL,
 effect_type_path TEXT NOT NULL,json TEXT NOT NULL);

CREATE TABLE niagara_system_emitters(
 system_path TEXT NOT NULL,emitter_index INTEGER NOT NULL,name TEXT NOT NULL,id TEXT NOT NULL,id_name TEXT NOT NULL,
 enabled INTEGER,emitter_mode TEXT NOT NULL,emitter_path TEXT NOT NULL,emitter_class TEXT NOT NULL,
 emitter_version TEXT NOT NULL,stateless_emitter_path TEXT NOT NULL,stateless_emitter_class TEXT NOT NULL,
 truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(system_path,emitter_index));
CREATE INDEX niagara_system_emitters_target_idx ON niagara_system_emitters(emitter_path);
CREATE INDEX niagara_system_emitters_stateless_target_idx ON niagara_system_emitters(stateless_emitter_path);

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

CREATE TABLE niagara_stateless_emitters(
 emitter_path TEXT PRIMARY KEY,asset_path TEXT NOT NULL,class_path TEXT NOT NULL,module_count INTEGER NOT NULL,
 renderer_count INTEGER NOT NULL,deterministic INTEGER,random_seed TEXT NOT NULL,fixed_bounds TEXT NOT NULL,json TEXT NOT NULL);

CREATE TABLE niagara_stateless_modules(
 emitter_path TEXT NOT NULL,module_index INTEGER NOT NULL,asset_path TEXT NOT NULL,module_path TEXT NOT NULL,
 module_class TEXT NOT NULL,enabled INTEGER,json TEXT NOT NULL,PRIMARY KEY(emitter_path,module_index));
CREATE INDEX niagara_stateless_modules_class_idx ON niagara_stateless_modules(module_class);

CREATE TABLE niagara_stateless_renderers(
 emitter_path TEXT NOT NULL,renderer_index INTEGER NOT NULL,asset_path TEXT NOT NULL,renderer_path TEXT NOT NULL,
 renderer_class TEXT NOT NULL,enabled INTEGER,sort_order_hint TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(emitter_path,renderer_index));
CREATE INDEX niagara_stateless_renderers_class_idx ON niagara_stateless_renderers(renderer_class);

CREATE TABLE niagara_scripts(
 script_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,usage TEXT NOT NULL,usage_id TEXT NOT NULL,
 exposed_version TEXT NOT NULL,version_count INTEGER NOT NULL,json TEXT NOT NULL);

CREATE TABLE niagara_data_channels(
 data_channel_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,definition_path TEXT NOT NULL,
 definition_class TEXT NOT NULL,variable_count INTEGER NOT NULL,json TEXT NOT NULL);

CREATE TABLE niagara_data_channel_variables(
 data_channel_path TEXT NOT NULL,variable_index INTEGER NOT NULL,version TEXT NOT NULL,name TEXT NOT NULL,
 type TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(data_channel_path,variable_index));

CREATE TABLE niagara_parameter_collections(
 collection_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,namespace TEXT NOT NULL,parameter_count INTEGER NOT NULL,
 source_collection_path TEXT NOT NULL,source_collection_class TEXT NOT NULL,default_instance_path TEXT NOT NULL,
 default_instance_class TEXT NOT NULL,json TEXT NOT NULL);

CREATE TABLE niagara_parameter_collection_parameters(
 collection_path TEXT NOT NULL,parameter_index INTEGER NOT NULL,name TEXT NOT NULL,type TEXT NOT NULL,
 truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(collection_path,parameter_index));

CREATE TABLE niagara_effect_types(
 effect_type_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,update_frequency TEXT NOT NULL,
 cull_reaction TEXT NOT NULL,json TEXT NOT NULL);

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


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"Expected object row in {path}:{line_number}")
            yield value


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
