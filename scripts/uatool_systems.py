#!/usr/bin/env python3
"""Systems schema support: cinematics, audio, input, tables and gameplay data."""
from __future__ import annotations

import collections
import json
from pathlib import Path

SYSTEMS_SCHEMA_VERSION = 2
MAX_STRUCTURED_ROWS_PER_ASSET = 65536

JSONL_FILES = (
    "systems_assets.jsonl",
    "systems_properties.jsonl",
    "systems_references.jsonl",
    "level_sequences.jsonl",
    "movie_scene_bindings.jsonl",
    "movie_scene_tracks.jsonl",
    "movie_scene_sections.jsonl",
    "movie_scene_channels.jsonl",
    "audio_assets.jsonl",
    "sound_cue_nodes.jsonl",
    "metasound_nodes.jsonl",
    "metasound_edges.jsonl",
    "input_actions.jsonl",
    "input_mapping_contexts.jsonl",
    "input_mappings.jsonl",
    "input_processors.jsonl",
    "gameplay_data_assets.jsonl",
    "gameplay_tags.jsonl",
    "data_table_rows.jsonl",
    "data_table_fields.jsonl",
    "curve_tables.jsonl",
    "curve_table_rows.jsonl",
    "curve_table_keys.jsonl",
    "primary_data_assets.jsonl",
    "gameplay_tag_settings.jsonl",
    "gameplay_tag_sources.jsonl",
    "gameplay_tag_dictionary.jsonl",
    "gameplay_tag_redirects.jsonl",
)
RAW_FILES = ("systems_manifest.json", *JSONL_FILES)

_SQL = """
CREATE TABLE systems_assets(
 systems_path TEXT PRIMARY KEY,systems_kind TEXT NOT NULL,family TEXT NOT NULL,class_path TEXT NOT NULL,
 package_name TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX systems_assets_kind_idx ON systems_assets(family,systems_kind);
CREATE TABLE systems_properties(
 asset_path TEXT NOT NULL,owner_path TEXT NOT NULL,owner_kind TEXT NOT NULL,owner_class TEXT NOT NULL,
 declaring_type TEXT NOT NULL,property_name TEXT NOT NULL,property_type TEXT NOT NULL,cpp_type TEXT NOT NULL,
 value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(asset_path,owner_path,declaring_type,property_name));
CREATE INDEX systems_properties_owner_idx ON systems_properties(owner_path,property_name);
CREATE TABLE systems_references(
 asset_path TEXT NOT NULL,owner_path TEXT NOT NULL,owner_kind TEXT NOT NULL,root_property TEXT NOT NULL,
 property_path TEXT NOT NULL,reference_kind TEXT NOT NULL,target_path TEXT NOT NULL,target_class TEXT NOT NULL,
 json TEXT NOT NULL);
CREATE INDEX systems_references_source_idx ON systems_references(asset_path,owner_path);
CREATE INDEX systems_references_target_idx ON systems_references(target_path,target_class);
CREATE TABLE level_sequences(
 sequence_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,class_path TEXT NOT NULL,movie_scene_path TEXT NOT NULL,
 binding_count INTEGER NOT NULL,track_count INTEGER NOT NULL,section_count INTEGER NOT NULL,channel_count INTEGER NOT NULL,
 display_rate TEXT NOT NULL,tick_resolution TEXT NOT NULL,playback_range TEXT NOT NULL,json TEXT NOT NULL);
CREATE TABLE movie_scene_bindings(
 sequence_path TEXT NOT NULL,binding_index INTEGER NOT NULL,binding_kind TEXT NOT NULL,source_index INTEGER NOT NULL,
 source_property TEXT NOT NULL,struct_type TEXT NOT NULL,guid TEXT NOT NULL,name TEXT NOT NULL,parent_guid TEXT NOT NULL,
 object_template_path TEXT NOT NULL,object_template_class TEXT NOT NULL,possessed_object_class TEXT NOT NULL,
 track_count INTEGER NOT NULL,raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(sequence_path,binding_index));
CREATE INDEX movie_scene_bindings_guid_idx ON movie_scene_bindings(sequence_path,guid);
CREATE TABLE movie_scene_tracks(
 sequence_path TEXT NOT NULL,track_index INTEGER NOT NULL,track_path TEXT NOT NULL,track_class TEXT NOT NULL,
 track_name TEXT NOT NULL,outer_path TEXT NOT NULL,binding_guid TEXT NOT NULL,section_count INTEGER NOT NULL,
 display_name TEXT NOT NULL,json TEXT NOT NULL,PRIMARY KEY(sequence_path,track_index));
CREATE INDEX movie_scene_tracks_path_idx ON movie_scene_tracks(track_path);
CREATE INDEX movie_scene_tracks_class_idx ON movie_scene_tracks(track_class);
CREATE TABLE movie_scene_sections(
 sequence_path TEXT NOT NULL,section_index INTEGER NOT NULL,section_path TEXT NOT NULL,section_class TEXT NOT NULL,
 section_name TEXT NOT NULL,track_path TEXT NOT NULL,range TEXT NOT NULL,row_index TEXT NOT NULL,
 overlap_priority TEXT NOT NULL,pre_roll_frames TEXT NOT NULL,post_roll_frames TEXT NOT NULL,active TEXT NOT NULL,
 locked TEXT NOT NULL,channel_count INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(sequence_path,section_index));
CREATE INDEX movie_scene_sections_track_idx ON movie_scene_sections(track_path);
CREATE INDEX movie_scene_sections_class_idx ON movie_scene_sections(section_class);
CREATE TABLE movie_scene_channels(
 sequence_path TEXT NOT NULL,section_path TEXT NOT NULL,channel_index INTEGER NOT NULL,property_path TEXT NOT NULL,
 channel_type TEXT NOT NULL,key_count INTEGER NOT NULL,value_count INTEGER NOT NULL,default_value TEXT NOT NULL,
 raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(sequence_path,section_path,channel_index));
CREATE INDEX movie_scene_channels_type_idx ON movie_scene_channels(channel_type);
CREATE TABLE audio_assets(
 audio_path TEXT PRIMARY KEY,audio_kind TEXT NOT NULL,class_path TEXT NOT NULL,package_name TEXT NOT NULL,
 duration TEXT NOT NULL,volume_multiplier TEXT NOT NULL,pitch_multiplier TEXT NOT NULL,num_channels TEXT NOT NULL,
 sample_rate TEXT NOT NULL,attenuation_path TEXT NOT NULL,sound_cue_node_count INTEGER NOT NULL,
 metasound_node_count INTEGER NOT NULL,metasound_edge_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX audio_assets_kind_idx ON audio_assets(audio_kind);
CREATE TABLE sound_cue_nodes(
 sound_cue_path TEXT NOT NULL,node_index INTEGER NOT NULL,node_path TEXT NOT NULL,node_class TEXT NOT NULL,
 node_name TEXT NOT NULL,child_count INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(sound_cue_path,node_index));
CREATE INDEX sound_cue_nodes_class_idx ON sound_cue_nodes(node_class);
CREATE TABLE metasound_nodes(
 asset_path TEXT NOT NULL,node_index INTEGER NOT NULL,property_path TEXT NOT NULL,struct_type TEXT NOT NULL,
 node_id TEXT NOT NULL,class_id TEXT NOT NULL,name TEXT NOT NULL,interface TEXT NOT NULL,style TEXT NOT NULL,
 raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(asset_path,node_index));
CREATE INDEX metasound_nodes_id_idx ON metasound_nodes(asset_path,node_id);
CREATE TABLE metasound_edges(
 asset_path TEXT NOT NULL,edge_index INTEGER NOT NULL,property_path TEXT NOT NULL,struct_type TEXT NOT NULL,
 from_node_id TEXT NOT NULL,from_vertex_id TEXT NOT NULL,to_node_id TEXT NOT NULL,to_vertex_id TEXT NOT NULL,
 raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(asset_path,edge_index));
CREATE TABLE input_actions(
 action_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,class_path TEXT NOT NULL,value_type TEXT NOT NULL,
 consume_input TEXT NOT NULL,trigger_when_paused TEXT NOT NULL,reserve_all_mappings TEXT NOT NULL,
 consume_legacy_keys TEXT NOT NULL,trigger_count INTEGER NOT NULL,modifier_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE input_mapping_contexts(
 context_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,class_path TEXT NOT NULL,mapping_count INTEGER NOT NULL,
 description TEXT NOT NULL,json TEXT NOT NULL);
CREATE TABLE input_mappings(
 context_path TEXT NOT NULL,mapping_index INTEGER NOT NULL,struct_type TEXT NOT NULL,action_path TEXT NOT NULL,
 action_class TEXT NOT NULL,key TEXT NOT NULL,trigger_count INTEGER NOT NULL,modifier_count INTEGER NOT NULL,
 player_mappable_options TEXT NOT NULL,setting_behavior TEXT NOT NULL,raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,
 json TEXT NOT NULL,PRIMARY KEY(context_path,mapping_index));
CREATE INDEX input_mappings_action_idx ON input_mappings(action_path,key);
CREATE TABLE input_processors(
 asset_path TEXT NOT NULL,owner_scope TEXT NOT NULL,mapping_index INTEGER NOT NULL,processor_kind TEXT NOT NULL,
 processor_index INTEGER NOT NULL,processor_path TEXT NOT NULL,processor_class TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(asset_path,owner_scope,mapping_index,processor_kind,processor_index));
CREATE INDEX input_processors_class_idx ON input_processors(processor_class);
CREATE TABLE gameplay_data_assets(
 asset_path TEXT PRIMARY KEY,gameplay_kind TEXT NOT NULL,class_path TEXT NOT NULL,package_name TEXT NOT NULL,
 row_struct TEXT NOT NULL,row_count INTEGER NOT NULL,primary_asset_rules TEXT NOT NULL,json TEXT NOT NULL);
CREATE TABLE gameplay_tags(
 table_path TEXT NOT NULL,tag_index INTEGER NOT NULL,row_name TEXT NOT NULL,tag TEXT NOT NULL,comment TEXT NOT NULL,
 row_struct TEXT NOT NULL,json TEXT NOT NULL,PRIMARY KEY(table_path,tag_index));
CREATE INDEX gameplay_tags_tag_idx ON gameplay_tags(tag);

CREATE TABLE data_table_rows(
 table_path TEXT NOT NULL,table_kind TEXT NOT NULL,row_index INTEGER NOT NULL,row_name TEXT NOT NULL,
 row_path TEXT NOT NULL,row_struct TEXT NOT NULL,field_count INTEGER NOT NULL,declared_field_count INTEGER NOT NULL,
 truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(table_path,row_index));
CREATE INDEX data_table_rows_name_idx ON data_table_rows(row_name,table_path);
CREATE TABLE data_table_fields(
 table_path TEXT NOT NULL,row_index INTEGER NOT NULL,row_name TEXT NOT NULL,row_path TEXT NOT NULL,
 field_index INTEGER NOT NULL,field_name TEXT NOT NULL,declaring_type TEXT NOT NULL,property_type TEXT NOT NULL,
 cpp_type TEXT NOT NULL,value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(table_path,row_index,field_index));
CREATE INDEX data_table_fields_name_idx ON data_table_fields(field_name,table_path);
CREATE INDEX data_table_fields_value_idx ON data_table_fields(table_path,row_name);
CREATE TABLE curve_tables(
 table_path TEXT PRIMARY KEY,table_kind TEXT NOT NULL,class_path TEXT NOT NULL,package_name TEXT NOT NULL,
 curve_mode TEXT NOT NULL,row_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX curve_tables_kind_idx ON curve_tables(table_kind,curve_mode);
CREATE TABLE curve_table_rows(
 table_path TEXT NOT NULL,row_index INTEGER NOT NULL,row_name TEXT NOT NULL,row_path TEXT NOT NULL,
 curve_mode TEXT NOT NULL,key_count INTEGER NOT NULL,default_value REAL,pre_infinity_extrap INTEGER NOT NULL,
 post_infinity_extrap INTEGER NOT NULL,simple_interp_mode INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(table_path,row_index));
CREATE INDEX curve_table_rows_name_idx ON curve_table_rows(row_name,table_path);
CREATE TABLE curve_table_keys(
 table_path TEXT NOT NULL,row_index INTEGER NOT NULL,row_name TEXT NOT NULL,row_path TEXT NOT NULL,
 key_index INTEGER NOT NULL,curve_mode TEXT NOT NULL,time REAL,value REAL,interp_mode INTEGER NOT NULL,
 tangent_mode INTEGER NOT NULL,tangent_weight_mode INTEGER NOT NULL,arrive_tangent REAL,leave_tangent REAL,
 arrive_tangent_weight REAL,leave_tangent_weight REAL,json TEXT NOT NULL,
 PRIMARY KEY(table_path,row_index,key_index));
CREATE INDEX curve_table_keys_time_idx ON curve_table_keys(table_path,row_name,time);
CREATE TABLE primary_data_assets(
 asset_path TEXT PRIMARY KEY,asset_kind TEXT NOT NULL,class_path TEXT NOT NULL,package_name TEXT NOT NULL,
 primary_asset_id_valid INTEGER NOT NULL,primary_asset_type TEXT NOT NULL,primary_asset_name TEXT NOT NULL,
 primary_asset_id TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX primary_data_assets_id_idx ON primary_data_assets(primary_asset_type,primary_asset_name);
CREATE TABLE gameplay_tag_settings(
 settings_path TEXT PRIMARY KEY,class_path TEXT NOT NULL,config_file_name TEXT NOT NULL,
 import_tags_from_config TEXT NOT NULL,warn_on_invalid_tags TEXT NOT NULL,fast_replication TEXT NOT NULL,
 invalid_tag_characters TEXT NOT NULL,gameplay_tag_table_list TEXT NOT NULL,restricted_config_files TEXT NOT NULL,
 num_bits_for_container_size INTEGER NOT NULL,net_index_first_bit_segment INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE gameplay_tag_sources(
 source_index INTEGER PRIMARY KEY,source_name TEXT NOT NULL,source_type TEXT NOT NULL,config_file TEXT NOT NULL,
 source_tag_list_path TEXT NOT NULL,source_restricted_tag_list_path TEXT NOT NULL,tag_count INTEGER NOT NULL,
 owners_json TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX gameplay_tag_sources_name_idx ON gameplay_tag_sources(source_name,source_type);
CREATE TABLE gameplay_tag_dictionary(
 tag TEXT PRIMARY KEY,tag_index INTEGER NOT NULL,parent_tag TEXT NOT NULL,comment TEXT NOT NULL,explicit INTEGER NOT NULL,
 restricted INTEGER NOT NULL,allow_non_restricted_children INTEGER NOT NULL,depth INTEGER NOT NULL,
 sources_json TEXT NOT NULL,json TEXT NOT NULL);
CREATE UNIQUE INDEX gameplay_tag_dictionary_index_idx ON gameplay_tag_dictionary(tag_index);
CREATE INDEX gameplay_tag_dictionary_parent_idx ON gameplay_tag_dictionary(parent_tag);
CREATE TABLE gameplay_tag_redirects(
 redirect_index INTEGER PRIMARY KEY,source_name TEXT NOT NULL,old_tag TEXT NOT NULL,new_tag TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX gameplay_tag_redirects_old_idx ON gameplay_tag_redirects(old_tag,new_tag);
"""


def _j(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
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
    path = Path(output) / "systems_manifest.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _count_rows(path: Path) -> int:
    return sum(1 for _ in _rows(path))


def validation_error(output: Path) -> str | None:
    output = Path(output)
    manifest = read_manifest(output)
    if not manifest:
        return "systems_manifest.json missing or invalid"
    if int(manifest.get("schema_version", 0) or 0) != SYSTEMS_SCHEMA_VERSION:
        return f"expected systems schema {SYSTEMS_SCHEMA_VERSION}, got {manifest.get('schema_version', 0)}"
    if manifest.get("pass") != "UnrealAssetToolSystems":
        return f"unexpected systems pass {manifest.get('pass')!r}"
    if not bool(manifest.get("success", False)):
        return f"systems scanner failed: {manifest.get('error', '')}"

    files = manifest.get("files", [])
    if not isinstance(files, list) or tuple(files) != JSONL_FILES:
        return f"systems manifest file list does not match schema {SYSTEMS_SCHEMA_VERSION}"
    counts = manifest.get("counts", {})
    if not isinstance(counts, dict):
        return "systems manifest counts missing or invalid"
    for filename in JSONL_FILES:
        path = output / filename
        if not path.is_file():
            return f"systems stream missing: {filename}"
        key = filename.removesuffix(".jsonl")
        actual = _count_rows(path)
        if int(counts.get(key, -1)) != actual:
            return f"systems count mismatch for {key}: manifest={counts.get(key)} actual={actual}"

    sequences = list(_rows(output / "level_sequences.jsonl"))
    bindings = list(_rows(output / "movie_scene_bindings.jsonl"))
    tracks = list(_rows(output / "movie_scene_tracks.jsonl"))
    sections = list(_rows(output / "movie_scene_sections.jsonl"))
    channels = list(_rows(output / "movie_scene_channels.jsonl"))
    binding_counts = collections.Counter(str(r.get("sequence_path", "")) for r in bindings)
    track_counts = collections.Counter(str(r.get("sequence_path", "")) for r in tracks)
    section_counts = collections.Counter(str(r.get("sequence_path", "")) for r in sections)
    channel_counts = collections.Counter(str(r.get("sequence_path", "")) for r in channels)
    sections_by_track = collections.Counter(str(r.get("track_path", "")) for r in sections if r.get("track_path"))
    channels_by_section = collections.Counter(str(r.get("section_path", "")) for r in channels)
    for row in sequences:
        path = str(row.get("sequence_path", ""))
        for field, actual in (
            ("binding_count", binding_counts[path]),
            ("track_count", track_counts[path]),
            ("section_count", section_counts[path]),
            ("channel_count", channel_counts[path]),
        ):
            if int(row.get(field, 0)) != actual:
                return f"LevelSequence {field} mismatch: {path} declared={row.get(field)} actual={actual}"
    for row in tracks:
        path = str(row.get("track_path", ""))
        if int(row.get("section_count", 0)) != sections_by_track[path]:
            return f"MovieScene track section_count mismatch: {path}"
    for row in sections:
        path = str(row.get("section_path", ""))
        if int(row.get("channel_count", 0)) != channels_by_section[path]:
            return f"MovieScene section channel_count mismatch: {path}"

    cue_nodes = collections.Counter(str(r.get("sound_cue_path", "")) for r in _rows(output / "sound_cue_nodes.jsonl"))
    meta_nodes = collections.Counter(str(r.get("asset_path", "")) for r in _rows(output / "metasound_nodes.jsonl"))
    meta_edges = collections.Counter(str(r.get("asset_path", "")) for r in _rows(output / "metasound_edges.jsonl"))
    for row in _rows(output / "audio_assets.jsonl"):
        path = str(row.get("audio_path", ""))
        if int(row.get("sound_cue_node_count", 0)) != cue_nodes[path]:
            return f"SoundCue node_count mismatch: {path}"
        if int(row.get("metasound_node_count", 0)) != meta_nodes[path]:
            return f"MetaSound node_count mismatch: {path}"
        if int(row.get("metasound_edge_count", 0)) != meta_edges[path]:
            return f"MetaSound edge_count mismatch: {path}"

    mappings = list(_rows(output / "input_mappings.jsonl"))
    processors = list(_rows(output / "input_processors.jsonl"))
    mapping_counts = collections.Counter(str(r.get("context_path", "")) for r in mappings)
    for row in _rows(output / "input_mapping_contexts.jsonl"):
        path = str(row.get("context_path", ""))
        if int(row.get("mapping_count", 0)) != mapping_counts[path]:
            return f"InputMappingContext mapping_count mismatch: {path}"
    action_proc = collections.Counter(
        (str(r.get("asset_path", "")), str(r.get("processor_kind", "")))
        for r in processors if r.get("owner_scope") == "action"
    )
    for row in _rows(output / "input_actions.jsonl"):
        path = str(row.get("action_path", ""))
        if int(row.get("trigger_count", 0)) != action_proc[(path, "trigger")]:
            return f"InputAction trigger_count mismatch: {path}"
        if int(row.get("modifier_count", 0)) != action_proc[(path, "modifier")]:
            return f"InputAction modifier_count mismatch: {path}"
    mapping_proc = collections.Counter(
        (str(r.get("asset_path", "")), int(r.get("mapping_index", -1)), str(r.get("processor_kind", "")))
        for r in processors if r.get("owner_scope") == "mapping"
    )
    for row in mappings:
        key = (str(row.get("context_path", "")), int(row.get("mapping_index", -1)))
        if int(row.get("trigger_count", 0)) != mapping_proc[(key[0], key[1], "trigger")]:
            return f"input mapping trigger_count mismatch: {key}"
        if int(row.get("modifier_count", 0)) != mapping_proc[(key[0], key[1], "modifier")]:
            return f"input mapping modifier_count mismatch: {key}"

    tags_by_table = collections.Counter(str(r.get("table_path", "")) for r in _rows(output / "gameplay_tags.jsonl"))
    data_rows = list(_rows(output / "data_table_rows.jsonl"))
    data_fields = list(_rows(output / "data_table_fields.jsonl"))
    rows_by_table = collections.Counter(str(r.get("table_path", "")) for r in data_rows)
    fields_by_row = collections.Counter(
        (str(r.get("table_path", "")), int(r.get("row_index", -1))) for r in data_fields
    )
    data_table_kinds = {"data_table", "composite_data_table", "gameplay_tag_table", "common_input_action_table"}
    for row in _rows(output / "gameplay_data_assets.jsonl"):
        path = str(row.get("asset_path", ""))
        kind = str(row.get("gameplay_kind", ""))
        declared = int(row.get("row_count", 0))
        if kind == "gameplay_tag_table" and declared != tags_by_table[path]:
            return f"gameplay tag table row_count mismatch: {path}"
        if kind in data_table_kinds and min(declared, MAX_STRUCTURED_ROWS_PER_ASSET) != rows_by_table[path]:
            return f"data table row_count mismatch: {path} declared={declared} actual={rows_by_table[path]}"
    seen_data_rows: set[tuple[str, int]] = set()
    for row in data_rows:
        key = (str(row.get("table_path", "")), int(row.get("row_index", -1)))
        if key in seen_data_rows:
            return f"duplicate data table row identity: {key}"
        seen_data_rows.add(key)
        if int(row.get("field_count", 0)) != fields_by_row[key]:
            return f"data table field_count mismatch: {key}"
        if int(row.get("field_count", 0)) > int(row.get("declared_field_count", 0)):
            return f"data table field_count exceeds declared fields: {key}"

    curve_tables = list(_rows(output / "curve_tables.jsonl"))
    curve_rows = list(_rows(output / "curve_table_rows.jsonl"))
    curve_keys = list(_rows(output / "curve_table_keys.jsonl"))
    curve_rows_by_table = collections.Counter(str(r.get("table_path", "")) for r in curve_rows)
    curve_keys_by_table = collections.Counter(str(r.get("table_path", "")) for r in curve_keys)
    declared_curve_keys_by_table = collections.Counter()
    for row in curve_rows:
        declared_curve_keys_by_table[str(row.get("table_path", ""))] += int(row.get("key_count", 0))
    for table in curve_tables:
        path = str(table.get("table_path", ""))
        declared_rows = int(table.get("row_count", 0))
        if min(declared_rows, MAX_STRUCTURED_ROWS_PER_ASSET) != curve_rows_by_table[path]:
            return f"curve table row_count mismatch: {path}"
        declared_keys = declared_curve_keys_by_table[path]
        actual_keys = curve_keys_by_table[path]
        if actual_keys != min(declared_keys, MAX_STRUCTURED_ROWS_PER_ASSET):
            return f"curve table key_count mismatch: {path} declared={declared_keys} actual={actual_keys}"

    primary_assets = list(_rows(output / "primary_data_assets.jsonl"))
    primary_paths = [str(r.get("asset_path", "")) for r in primary_assets]
    if len(primary_paths) != len(set(primary_paths)):
        return "duplicate primary data asset path"
    valid_ids = [str(r.get("primary_asset_id", "")) for r in primary_assets if r.get("primary_asset_id_valid")]
    if any(not value for value in valid_ids):
        return "valid PrimaryDataAsset has empty primary_asset_id"

    tag_settings = list(_rows(output / "gameplay_tag_settings.jsonl"))
    if len(tag_settings) != 1:
        return f"expected exactly one gameplay tag settings row, got {len(tag_settings)}"
    tag_sources = list(_rows(output / "gameplay_tag_sources.jsonl"))
    source_indices = [int(r.get("source_index", -1)) for r in tag_sources]
    if source_indices != list(range(len(tag_sources))):
        return "gameplay tag source indices are not contiguous/deterministic"
    source_names = {str(r.get("source_name", "")) for r in tag_sources}
    dictionary = list(_rows(output / "gameplay_tag_dictionary.jsonl"))
    tags = [str(r.get("tag", "")) for r in dictionary]
    if len(tags) != len(set(tags)) or any(not tag for tag in tags):
        return "gameplay tag dictionary contains duplicate/blank tags"
    tag_indices = [int(r.get("tag_index", -1)) for r in dictionary]
    if tag_indices != list(range(len(dictionary))):
        return "gameplay tag dictionary indices are not contiguous/deterministic"
    for row in dictionary:
        sources = row.get("sources", [])
        if not isinstance(sources, list):
            return f"gameplay tag dictionary sources invalid: {row.get('tag')}"
        unknown = {str(source) for source in sources if str(source) not in source_names}
        if unknown:
            return f"gameplay tag dictionary references unknown sources for {row.get('tag')}: {sorted(unknown)!r}"
    redirects = list(_rows(output / "gameplay_tag_redirects.jsonl"))
    redirect_indices = [int(r.get("redirect_index", -1)) for r in redirects]
    if redirect_indices != list(range(len(redirects))):
        return "gameplay tag redirect indices are not contiguous/deterministic"
    return None


def load_database(conn, output: Path, rows=None) -> None:
    rows = rows or _rows
    for r in rows(output / "systems_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO systems_assets VALUES(?,?,?,?,?,?)",(
            r.get("systems_path", ""),r.get("systems_kind", ""),r.get("family", ""),r.get("class_path", ""),r.get("package_name", ""),_j(r)))
    for r in rows(output / "systems_properties.jsonl"):
        conn.execute("INSERT OR REPLACE INTO systems_properties VALUES(?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("asset_path", ""),r.get("owner_path", ""),r.get("owner_kind", ""),r.get("owner_class", ""),r.get("declaring_type", ""),
            r.get("property_name", ""),r.get("property_type", ""),r.get("cpp_type", ""),r.get("value", ""),int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "systems_references.jsonl"):
        conn.execute("INSERT INTO systems_references VALUES(?,?,?,?,?,?,?,?,?)",(
            r.get("asset_path", ""),r.get("owner_path", ""),r.get("owner_kind", ""),r.get("root_property", ""),r.get("property_path", ""),
            r.get("reference_kind", ""),r.get("target_path", ""),r.get("target_class", ""),_j(r)))
    for r in rows(output / "level_sequences.jsonl"):
        conn.execute("INSERT OR REPLACE INTO level_sequences VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("sequence_path", ""),r.get("package_name", ""),r.get("class_path", ""),r.get("movie_scene_path", ""),int(r.get("binding_count",0)),
            int(r.get("track_count",0)),int(r.get("section_count",0)),int(r.get("channel_count",0)),r.get("display_rate", ""),r.get("tick_resolution", ""),
            r.get("playback_range", ""),_j(r)))
    for r in rows(output / "movie_scene_bindings.jsonl"):
        conn.execute("INSERT OR REPLACE INTO movie_scene_bindings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("sequence_path", ""),int(r.get("binding_index",0)),r.get("binding_kind", ""),int(r.get("source_index",0)),r.get("source_property", ""),
            r.get("struct_type", ""),r.get("guid", ""),r.get("name", ""),r.get("parent_guid", ""),r.get("object_template_path", ""),
            r.get("object_template_class", ""),r.get("possessed_object_class", ""),int(r.get("track_count",0)),r.get("raw_value", ""),
            int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "movie_scene_tracks.jsonl"):
        conn.execute("INSERT OR REPLACE INTO movie_scene_tracks VALUES(?,?,?,?,?,?,?,?,?,?)",(
            r.get("sequence_path", ""),int(r.get("track_index",0)),r.get("track_path", ""),r.get("track_class", ""),r.get("track_name", ""),
            r.get("outer_path", ""),r.get("binding_guid", ""),int(r.get("section_count",0)),r.get("display_name", ""),_j(r)))
    for r in rows(output / "movie_scene_sections.jsonl"):
        conn.execute("INSERT OR REPLACE INTO movie_scene_sections VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("sequence_path", ""),int(r.get("section_index",0)),r.get("section_path", ""),r.get("section_class", ""),r.get("section_name", ""),
            r.get("track_path", ""),r.get("range", ""),r.get("row_index", ""),r.get("overlap_priority", ""),r.get("pre_roll_frames", ""),
            r.get("post_roll_frames", ""),r.get("active", ""),r.get("locked", ""),int(r.get("channel_count",0)),_j(r)))
    for r in rows(output / "movie_scene_channels.jsonl"):
        conn.execute("INSERT OR REPLACE INTO movie_scene_channels VALUES(?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("sequence_path", ""),r.get("section_path", ""),int(r.get("channel_index",0)),r.get("property_path", ""),r.get("channel_type", ""),
            int(r.get("key_count",0)),int(r.get("value_count",0)),r.get("default_value", ""),r.get("raw_value", ""),int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "audio_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO audio_assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("audio_path", ""),r.get("audio_kind", ""),r.get("class_path", ""),r.get("package_name", ""),r.get("duration", ""),
            r.get("volume_multiplier", ""),r.get("pitch_multiplier", ""),r.get("num_channels", ""),r.get("sample_rate", ""),r.get("attenuation_path", ""),
            int(r.get("sound_cue_node_count",0)),int(r.get("metasound_node_count",0)),int(r.get("metasound_edge_count",0)),_j(r)))
    for r in rows(output / "sound_cue_nodes.jsonl"):
        conn.execute("INSERT OR REPLACE INTO sound_cue_nodes VALUES(?,?,?,?,?,?,?)",(
            r.get("sound_cue_path", ""),int(r.get("node_index",0)),r.get("node_path", ""),r.get("node_class", ""),r.get("node_name", ""),int(r.get("child_count",0)),_j(r)))
    for r in rows(output / "metasound_nodes.jsonl"):
        conn.execute("INSERT OR REPLACE INTO metasound_nodes VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("asset_path", ""),int(r.get("node_index",0)),r.get("property_path", ""),r.get("struct_type", ""),r.get("node_id", ""),r.get("class_id", ""),
            r.get("name", ""),r.get("interface", ""),r.get("style", ""),r.get("raw_value", ""),int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "metasound_edges.jsonl"):
        conn.execute("INSERT OR REPLACE INTO metasound_edges VALUES(?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("asset_path", ""),int(r.get("edge_index",0)),r.get("property_path", ""),r.get("struct_type", ""),r.get("from_node_id", ""),
            r.get("from_vertex_id", ""),r.get("to_node_id", ""),r.get("to_vertex_id", ""),r.get("raw_value", ""),int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "input_actions.jsonl"):
        conn.execute("INSERT OR REPLACE INTO input_actions VALUES(?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("action_path", ""),r.get("package_name", ""),r.get("class_path", ""),r.get("value_type", ""),r.get("consume_input", ""),
            r.get("trigger_when_paused", ""),r.get("reserve_all_mappings", ""),r.get("consume_legacy_keys", ""),int(r.get("trigger_count",0)),
            int(r.get("modifier_count",0)),_j(r)))
    for r in rows(output / "input_mapping_contexts.jsonl"):
        conn.execute("INSERT OR REPLACE INTO input_mapping_contexts VALUES(?,?,?,?,?,?)",(
            r.get("context_path", ""),r.get("package_name", ""),r.get("class_path", ""),int(r.get("mapping_count",0)),r.get("description", ""),_j(r)))
    for r in rows(output / "input_mappings.jsonl"):
        conn.execute("INSERT OR REPLACE INTO input_mappings VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("context_path", ""),int(r.get("mapping_index",0)),r.get("struct_type", ""),r.get("action_path", ""),r.get("action_class", ""),r.get("key", ""),
            int(r.get("trigger_count",0)),int(r.get("modifier_count",0)),r.get("player_mappable_options", ""),r.get("setting_behavior", ""),r.get("raw_value", ""),
            int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "input_processors.jsonl"):
        conn.execute("INSERT OR REPLACE INTO input_processors VALUES(?,?,?,?,?,?,?,?)",(
            r.get("asset_path", ""),r.get("owner_scope", ""),int(r.get("mapping_index",-1)),r.get("processor_kind", ""),int(r.get("processor_index",0)),
            r.get("processor_path", ""),r.get("processor_class", ""),_j(r)))
    for r in rows(output / "gameplay_data_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_data_assets VALUES(?,?,?,?,?,?,?,?)",(
            r.get("asset_path", ""),r.get("gameplay_kind", ""),r.get("class_path", ""),r.get("package_name", ""),r.get("row_struct", ""),
            int(r.get("row_count",0)),r.get("primary_asset_rules", ""),_j(r)))
    for r in rows(output / "gameplay_tags.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_tags VALUES(?,?,?,?,?,?,?)",(
            r.get("table_path", ""),int(r.get("tag_index",0)),r.get("row_name", ""),r.get("tag", ""),r.get("comment", ""),r.get("row_struct", ""),_j(r)))
    for r in rows(output / "data_table_rows.jsonl"):
        conn.execute("INSERT OR REPLACE INTO data_table_rows VALUES(?,?,?,?,?,?,?,?,?,?)",(
            r.get("table_path", ""),r.get("table_kind", ""),int(r.get("row_index",0)),r.get("row_name", ""),r.get("row_path", ""),r.get("row_struct", ""),
            int(r.get("field_count",0)),int(r.get("declared_field_count",0)),int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "data_table_fields.jsonl"):
        conn.execute("INSERT OR REPLACE INTO data_table_fields VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("table_path", ""),int(r.get("row_index",0)),r.get("row_name", ""),r.get("row_path", ""),int(r.get("field_index",0)),r.get("field_name", ""),
            r.get("declaring_type", ""),r.get("property_type", ""),r.get("cpp_type", ""),r.get("value", ""),int(bool(r.get("truncated",False))),_j(r)))
    for r in rows(output / "curve_tables.jsonl"):
        conn.execute("INSERT OR REPLACE INTO curve_tables VALUES(?,?,?,?,?,?,?)",(
            r.get("table_path", ""),r.get("table_kind", ""),r.get("class_path", ""),r.get("package_name", ""),r.get("curve_mode", ""),int(r.get("row_count",0)),_j(r)))
    for r in rows(output / "curve_table_rows.jsonl"):
        conn.execute("INSERT OR REPLACE INTO curve_table_rows VALUES(?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("table_path", ""),int(r.get("row_index",0)),r.get("row_name", ""),r.get("row_path", ""),r.get("curve_mode", ""),int(r.get("key_count",0)),
            r.get("default_value"),int(r.get("pre_infinity_extrap",0)),int(r.get("post_infinity_extrap",0)),int(r.get("simple_interp_mode",-1)),_j(r)))
    for r in rows(output / "curve_table_keys.jsonl"):
        conn.execute("INSERT OR REPLACE INTO curve_table_keys VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("table_path", ""),int(r.get("row_index",0)),r.get("row_name", ""),r.get("row_path", ""),int(r.get("key_index",0)),r.get("curve_mode", ""),
            r.get("time"),r.get("value"),int(r.get("interp_mode",-1)),int(r.get("tangent_mode",-1)),int(r.get("tangent_weight_mode",-1)),
            r.get("arrive_tangent"),r.get("leave_tangent"),r.get("arrive_tangent_weight"),r.get("leave_tangent_weight"),_j(r)))
    for r in rows(output / "primary_data_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO primary_data_assets VALUES(?,?,?,?,?,?,?,?,?)",(
            r.get("asset_path", ""),r.get("asset_kind", ""),r.get("class_path", ""),r.get("package_name", ""),int(bool(r.get("primary_asset_id_valid",False))),
            r.get("primary_asset_type", ""),r.get("primary_asset_name", ""),r.get("primary_asset_id", ""),_j(r)))
    for r in rows(output / "gameplay_tag_settings.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_tag_settings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("settings_path", ""),r.get("class_path", ""),r.get("config_file_name", ""),r.get("import_tags_from_config", ""),r.get("warn_on_invalid_tags", ""),
            r.get("fast_replication", ""),r.get("invalid_tag_characters", ""),r.get("gameplay_tag_table_list", ""),r.get("restricted_config_files", ""),
            int(r.get("num_bits_for_container_size",0)),int(r.get("net_index_first_bit_segment",0)),_j(r)))
    for r in rows(output / "gameplay_tag_sources.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_tag_sources VALUES(?,?,?,?,?,?,?,?,?)",(
            int(r.get("source_index",0)),r.get("source_name", ""),r.get("source_type", ""),r.get("config_file", ""),r.get("source_tag_list_path", ""),
            r.get("source_restricted_tag_list_path", ""),int(r.get("tag_count",0)),json.dumps(r.get("owners",[]),ensure_ascii=False,separators=(",",":")),_j(r)))
    for r in rows(output / "gameplay_tag_dictionary.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_tag_dictionary VALUES(?,?,?,?,?,?,?,?,?,?)",(
            r.get("tag", ""),int(r.get("tag_index",0)),r.get("parent_tag", ""),r.get("comment", ""),int(bool(r.get("explicit",False))),int(bool(r.get("restricted",False))),
            int(bool(r.get("allow_non_restricted_children",False))),int(r.get("depth",0)),json.dumps(r.get("sources",[]),ensure_ascii=False,separators=(",",":")),_j(r)))
    for r in rows(output / "gameplay_tag_redirects.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_tag_redirects VALUES(?,?,?,?,?)",(
            int(r.get("redirect_index",0)),r.get("source_name", ""),r.get("old_tag", ""),r.get("new_tag", ""),_j(r)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='systems_assets'").fetchone():
        return
    print("\n[systems assets]")
    print_rows(conn.execute(
        "SELECT systems_path,systems_kind,family,class_path FROM systems_assets WHERE systems_path LIKE ? OR systems_kind LIKE ? OR family LIKE ? OR class_path LIKE ? LIMIT ?",
        (pattern,pattern,pattern,pattern,limit)),("systems_path","systems_kind","family","class_path"))
    print("\n[level sequences]")
    print_rows(conn.execute(
        "SELECT sequence_path,binding_count,track_count,section_count,channel_count,playback_range FROM level_sequences WHERE sequence_path LIKE ? OR movie_scene_path LIKE ? OR playback_range LIKE ? LIMIT ?",
        (pattern,pattern,pattern,limit)),("sequence_path","binding_count","track_count","section_count","channel_count","playback_range"))
    print("\n[audio assets]")
    print_rows(conn.execute(
        "SELECT audio_path,audio_kind,sound_cue_node_count,metasound_node_count,metasound_edge_count FROM audio_assets WHERE audio_path LIKE ? OR audio_kind LIKE ? OR class_path LIKE ? LIMIT ?",
        (pattern,pattern,pattern,limit)),("audio_path","audio_kind","sound_cue_node_count","metasound_node_count","metasound_edge_count"))
    print("\n[input mappings]")
    print_rows(conn.execute(
        "SELECT context_path,mapping_index,action_path,key,trigger_count,modifier_count FROM input_mappings WHERE context_path LIKE ? OR action_path LIKE ? OR key LIKE ? OR raw_value LIKE ? LIMIT ?",
        (pattern,pattern,pattern,pattern,limit)),("context_path","mapping_index","action_path","key","trigger_count","modifier_count"))
    print("\n[data table rows]")
    print_rows(conn.execute(
        "SELECT table_path,row_name,row_struct,field_count,truncated FROM data_table_rows WHERE table_path LIKE ? OR row_name LIKE ? OR row_struct LIKE ? LIMIT ?",
        (pattern,pattern,pattern,limit)),("table_path","row_name","row_struct","field_count","truncated"))
    print("\n[data table fields]")
    print_rows(conn.execute(
        "SELECT table_path,row_name,field_name,cpp_type,substr(value,1,600) value,truncated FROM data_table_fields WHERE table_path LIKE ? OR row_name LIKE ? OR field_name LIKE ? OR value LIKE ? LIMIT ?",
        (pattern,pattern,pattern,pattern,limit)),("table_path","row_name","field_name","cpp_type","value","truncated"))
    print("\n[curve table rows]")
    print_rows(conn.execute(
        "SELECT table_path,row_name,curve_mode,key_count,default_value FROM curve_table_rows WHERE table_path LIKE ? OR row_name LIKE ? OR curve_mode LIKE ? LIMIT ?",
        (pattern,pattern,pattern,limit)),("table_path","row_name","curve_mode","key_count","default_value"))
    print("\n[primary data assets]")
    print_rows(conn.execute(
        "SELECT asset_path,class_path,primary_asset_type,primary_asset_name,primary_asset_id_valid FROM primary_data_assets WHERE asset_path LIKE ? OR class_path LIKE ? OR primary_asset_type LIKE ? OR primary_asset_name LIKE ? LIMIT ?",
        (pattern,pattern,pattern,pattern,limit)),("asset_path","class_path","primary_asset_type","primary_asset_name","primary_asset_id_valid"))
    print("\n[gameplay tag dictionary]")
    print_rows(conn.execute(
        "SELECT tag,parent_tag,comment,explicit,restricted,depth,sources_json FROM gameplay_tag_dictionary WHERE tag LIKE ? OR parent_tag LIKE ? OR comment LIKE ? OR sources_json LIKE ? LIMIT ?",
        (pattern,pattern,pattern,pattern,limit)),("tag","parent_tag","comment","explicit","restricted","depth","sources_json"))
    print("\n[gameplay tag sources]")
    print_rows(conn.execute(
        "SELECT source_name,source_type,config_file,tag_count,owners_json FROM gameplay_tag_sources WHERE source_name LIKE ? OR source_type LIKE ? OR config_file LIKE ? OR owners_json LIKE ? LIMIT ?",
        (pattern,pattern,pattern,pattern,limit)),("source_name","source_type","config_file","tag_count","owners_json"))
    print("\n[gameplay tag redirects]")
    print_rows(conn.execute(
        "SELECT source_name,old_tag,new_tag FROM gameplay_tag_redirects WHERE source_name LIKE ? OR old_tag LIKE ? OR new_tag LIKE ? LIMIT ?",
        (pattern,pattern,pattern,limit)),("source_name","old_tag","new_tag"))
