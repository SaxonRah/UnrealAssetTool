#!/usr/bin/env python3
"""Canonical authored Landscape/Foliage/HLOD support for world-geometry schema 1."""
from __future__ import annotations

import json
import os
from pathlib import Path

import uatool_world_geometry_capture as capture

WORLD_GEOMETRY_SCHEMA_VERSION = 1
MANIFEST_FILE = "world_geometry_manifest.json"
CANONICAL_PASS = "UnrealAssetToolWorldGeometry"
JSONL_FILES = (
    "world_geometry_landscapes.jsonl",
    "world_geometry_landscape_components.jsonl",
    "world_geometry_landscape_weightmaps.jsonl",
    "world_geometry_landscape_layer_allocations.jsonl",
    "world_geometry_landscape_layer_infos.jsonl",
    "world_geometry_grass_types.jsonl",
    "world_geometry_grass_varieties.jsonl",
    "world_geometry_foliage_types.jsonl",
    "world_geometry_foliage_actors.jsonl",
    "world_geometry_foliage_infos.jsonl",
    "world_geometry_foliage_instances.jsonl",
    "world_geometry_hlod_layers.jsonl",
)
RAW_FILES = (MANIFEST_FILE, *JSONL_FILES)

_SQL = """
CREATE TABLE world_geometry_landscapes(
 landscape_path TEXT PRIMARY KEY,class_path TEXT NOT NULL,package_name TEXT NOT NULL,
 component_count INTEGER NOT NULL,collision_component_count INTEGER NOT NULL,
 landscape_material_path TEXT NOT NULL,landscape_hole_material_path TEXT NOT NULL,
 authored_settings_json TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX world_geometry_landscapes_material_idx ON world_geometry_landscapes(landscape_material_path);

CREATE TABLE world_geometry_landscape_components(
 component_path TEXT PRIMARY KEY,landscape_path TEXT NOT NULL,component_index INTEGER NOT NULL,
 component_class TEXT NOT NULL,section_base_x TEXT NOT NULL,section_base_y TEXT NOT NULL,
 component_size_quads TEXT NOT NULL,num_subsections TEXT NOT NULL,subsection_size_quads TEXT NOT NULL,
 heightmap_texture_path TEXT NOT NULL,heightmap_texture_class TEXT NOT NULL,
 authored_settings_json TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX world_geometry_landscape_components_owner_idx ON world_geometry_landscape_components(landscape_path,component_index);
CREATE INDEX world_geometry_landscape_components_heightmap_idx ON world_geometry_landscape_components(heightmap_texture_path);

CREATE TABLE world_geometry_landscape_weightmaps(
 component_path TEXT NOT NULL,texture_index INTEGER NOT NULL,landscape_path TEXT NOT NULL,
 texture_path TEXT NOT NULL,texture_class TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(component_path,texture_index));
CREATE INDEX world_geometry_landscape_weightmaps_target_idx ON world_geometry_landscape_weightmaps(texture_path);

CREATE TABLE world_geometry_landscape_layer_allocations(
 component_path TEXT NOT NULL,allocation_index INTEGER NOT NULL,landscape_path TEXT NOT NULL,
 component_index INTEGER NOT NULL,struct_type TEXT NOT NULL,layer_info_path TEXT NOT NULL,
 weightmap_texture_index TEXT NOT NULL,weightmap_texture_channel TEXT NOT NULL,
 fields_json TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(component_path,allocation_index));
CREATE INDEX world_geometry_landscape_alloc_layer_idx ON world_geometry_landscape_layer_allocations(layer_info_path);

CREATE TABLE world_geometry_landscape_layer_infos(
 layer_info_path TEXT PRIMARY KEY,class_path TEXT NOT NULL,package_name TEXT NOT NULL,
 layer_name TEXT NOT NULL,physical_material_path TEXT NOT NULL,no_weight_blend TEXT NOT NULL,
 hardness TEXT NOT NULL,json TEXT NOT NULL);

CREATE TABLE world_geometry_grass_types(
 grass_type_path TEXT PRIMARY KEY,class_path TEXT NOT NULL,package_name TEXT NOT NULL,
 enable_density_scaling TEXT NOT NULL,grass_variety_count INTEGER NOT NULL,json TEXT NOT NULL);

CREATE TABLE world_geometry_grass_varieties(
 grass_type_path TEXT NOT NULL,variety_index INTEGER NOT NULL,struct_type TEXT NOT NULL,
 grass_mesh_path TEXT NOT NULL,authored_settings_json TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(grass_type_path,variety_index));
CREATE INDEX world_geometry_grass_variety_mesh_idx ON world_geometry_grass_varieties(grass_mesh_path);

CREATE TABLE world_geometry_foliage_types(
 foliage_type_path TEXT PRIMARY KEY,class_path TEXT NOT NULL,package_name TEXT NOT NULL,
 mesh_path TEXT NOT NULL,mesh_class TEXT NOT NULL,component_class TEXT NOT NULL,
 include_in_hlod TEXT NOT NULL,density TEXT NOT NULL,radius TEXT NOT NULL,
 align_to_normal TEXT NOT NULL,cull_distance TEXT NOT NULL,
 authored_settings_json TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX world_geometry_foliage_type_mesh_idx ON world_geometry_foliage_types(mesh_path);

CREATE TABLE world_geometry_foliage_actors(
 foliage_actor_path TEXT PRIMARY KEY,class_path TEXT NOT NULL,package_name TEXT NOT NULL,
 foliage_info_count INTEGER NOT NULL,capture_mode TEXT NOT NULL,json TEXT NOT NULL);

CREATE TABLE world_geometry_foliage_infos(
 foliage_actor_path TEXT NOT NULL,map_index INTEGER NOT NULL,foliage_type_path TEXT NOT NULL,
 foliage_type_class TEXT NOT NULL,implementation_type INTEGER NOT NULL,
 foliage_type_update_guid TEXT NOT NULL,instance_count INTEGER NOT NULL,
 placed_instance_count INTEGER NOT NULL,capture_mode TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(foliage_actor_path,map_index));
CREATE INDEX world_geometry_foliage_info_type_idx ON world_geometry_foliage_infos(foliage_type_path);

CREATE TABLE world_geometry_foliage_instances(
 foliage_actor_path TEXT NOT NULL,map_index INTEGER NOT NULL,instance_index INTEGER NOT NULL,
 foliage_type_path TEXT NOT NULL,instance_struct TEXT NOT NULL,capture_mode TEXT NOT NULL,
 location_json TEXT NOT NULL,rotation_json TEXT NOT NULL,pre_align_rotation_json TEXT NOT NULL,
 draw_scale3d_json TEXT NOT NULL,z_offset REAL NOT NULL,flags INTEGER NOT NULL,base_id INTEGER NOT NULL,
 base_component_path TEXT NOT NULL,base_component_class TEXT NOT NULL,
 procedural_guid TEXT NOT NULL,procedural_guid_valid INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(foliage_actor_path,map_index,instance_index));
CREATE INDEX world_geometry_foliage_instance_type_idx ON world_geometry_foliage_instances(foliage_type_path);

CREATE TABLE world_geometry_hlod_layers(
 hlod_layer_path TEXT PRIMARY KEY,class_path TEXT NOT NULL,package_name TEXT NOT NULL,
 layer_type TEXT NOT NULL,cell_size TEXT NOT NULL,loading_range TEXT NOT NULL,
 parent_layer_path TEXT NOT NULL,parent_layer_class TEXT NOT NULL,
 linked_layer_path TEXT NOT NULL,linked_layer_class TEXT NOT NULL,
 builder_settings_path TEXT NOT NULL,builder_settings_class TEXT NOT NULL,
 authored_settings_json TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX world_geometry_hlod_parent_idx ON world_geometry_hlod_layers(parent_layer_path);
"""

def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root is not an object: {path}")
    return value

def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield value

def _write_json(path: Path, value: dict) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)

def _write_jsonl(path: Path, values: list[dict]) -> int:
    temp = path.with_name(f".{path.name}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in values:
            handle.write(_j(row) + "\n")
    os.replace(temp, path)
    return len(values)

def _path_key(value: object):
    text = str(value or "")
    return (text.casefold(), text)

def _fields(row: dict) -> dict:
    value = row.get("fields", {})
    return dict(value) if isinstance(value, dict) else {}

def _refs(row: dict) -> dict:
    value = row.get("object_references", {})
    return dict(value) if isinstance(value, dict) else {}

def _canonical_rows(capture_dir: Path) -> dict[str, list[dict]]:
    raw_roots = list(_rows(capture_dir / "landscape_roots.jsonl"))
    raw_components = list(_rows(capture_dir / "landscape_components.jsonl"))
    raw_allocations = list(_rows(capture_dir / "landscape_weightmap_allocations.jsonl"))
    raw_layer_infos = list(_rows(capture_dir / "landscape_layer_infos.jsonl"))
    raw_grass_types = list(_rows(capture_dir / "landscape_grass_types.jsonl"))
    raw_grass_varieties = list(_rows(capture_dir / "landscape_grass_varieties.jsonl"))
    raw_foliage_types = list(_rows(capture_dir / "foliage_types.jsonl"))
    raw_foliage_actors = list(_rows(capture_dir / "foliage_actors.jsonl"))
    raw_foliage_infos = list(_rows(capture_dir / "foliage_actor_type_infos.jsonl"))
    raw_foliage_instances = list(_rows(capture_dir / "foliage_instances.jsonl"))
    raw_hlod_layers = list(_rows(capture_dir / "hlod_layers.jsonl"))
    raw_properties = list(_rows(capture_dir / "world_geometry_properties.jsonl"))

    property_map: dict[str, dict[str, dict]] = {}
    for row in raw_properties:
        owner = str(row.get("owner_path", "")); name = str(row.get("property_name", ""))
        if owner and name:
            property_map.setdefault(owner, {})[name] = {
                "property_type": str(row.get("property_type", "")),
                "cpp_type": str(row.get("cpp_type", "")),
                "value": str(row.get("value", "")),
                **({"target_path": str(row.get("target_path", ""))} if row.get("target_path") else {}),
                **({"target_class": str(row.get("target_class", ""))} if row.get("target_class") else {}),
            }

    component_count_by_root: dict[str, int] = {}
    for row in raw_components:
        owner = str(row.get("landscape_path", ""))
        component_count_by_root[owner] = component_count_by_root.get(owner, 0) + 1

    landscapes = []
    for row in raw_roots:
        path = str(row.get("landscape_path", ""))
        landscapes.append({
            "landscape_path": path,
            "class_path": str(row.get("class_path", "")),
            "package_name": str(row.get("package_name", "")),
            "component_count": int(component_count_by_root.get(path, 0)),
            "collision_component_count": int(row.get("collision_component_count", 0) or 0),
            "landscape_material_path": str(row.get("landscape_material_path", "")),
            "landscape_hole_material_path": str(row.get("landscape_hole_material_path", "")),
            "authored_settings": _fields(row),
        })

    components = []; weightmaps = []
    for row in raw_components:
        fields = _fields(row); landscape = str(row.get("landscape_path", "")); component = str(row.get("component_path", ""))
        components.append({
            "landscape_path": landscape, "component_path": component,
            "component_class": str(row.get("component_class", "")),
            "component_index": int(row.get("component_index", 0) or 0),
            "section_base_x": str(fields.get("SectionBaseX", "")), "section_base_y": str(fields.get("SectionBaseY", "")),
            "component_size_quads": str(fields.get("ComponentSizeQuads", "")), "num_subsections": str(fields.get("NumSubsections", "")),
            "subsection_size_quads": str(fields.get("SubsectionSizeQuads", "")),
            "heightmap_texture_path": str(row.get("heightmap_texture_path", "")),
            "heightmap_texture_class": str(row.get("heightmap_texture_class", "")),
            "authored_settings": fields,
        })
        textures = row.get("weightmap_textures", [])
        if not isinstance(textures, list): textures = []
        for texture_index, texture in enumerate(textures):
            texture = texture if isinstance(texture, dict) else {}
            weightmaps.append({"landscape_path": landscape, "component_path": component, "texture_index": texture_index,
                               "texture_path": str(texture.get("path", "")), "texture_class": str(texture.get("class", ""))})

    allocations = []
    for row in raw_allocations:
        fields = _fields(row); refs = _refs(row)
        allocations.append({
            "landscape_path": str(row.get("landscape_path", "")), "component_path": str(row.get("component_path", "")),
            "component_index": int(row.get("component_index", 0) or 0), "allocation_index": int(row.get("allocation_index", 0) or 0),
            "struct_type": str(row.get("struct_type", "")), "layer_info_path": str(refs.get("LayerInfo", "")),
            "weightmap_texture_index": str(fields.get("WeightmapTextureIndex", "")),
            "weightmap_texture_channel": str(fields.get("WeightmapTextureChannel", "")), "fields": fields,
        })

    layer_infos = [{
        "layer_info_path": str(row.get("layer_info_path", "")), "class_path": str(row.get("class_path", "")),
        "package_name": str(row.get("package_name", "")), "layer_name": str(row.get("layer_name", "")),
        "physical_material_path": str(row.get("physical_material_path", "")), "no_weight_blend": str(row.get("no_weight_blend", "")),
        "hardness": str(row.get("hardness", "")), "authored_settings": property_map.get(str(row.get("layer_info_path", "")), {}),
    } for row in raw_layer_infos]

    grass_types = [{
        "grass_type_path": str(row.get("grass_type_path", "")), "class_path": str(row.get("class_path", "")),
        "package_name": str(row.get("package_name", "")), "enable_density_scaling": str(row.get("enable_density_scaling", "")),
        "grass_variety_count": int(row.get("grass_variety_count", 0) or 0),
        "authored_settings": property_map.get(str(row.get("grass_type_path", "")), {}),
    } for row in raw_grass_types]

    grass_varieties = []
    for row in raw_grass_varieties:
        refs = _refs(row)
        grass_varieties.append({"grass_type_path": str(row.get("grass_type_path", "")), "variety_index": int(row.get("variety_index", 0) or 0),
                                "struct_type": str(row.get("struct_type", "")), "grass_mesh_path": str(refs.get("GrassMesh", "")),
                                "authored_settings": _fields(row)})

    foliage_types = [{
        "foliage_type_path": str(row.get("foliage_type_path", "")), "class_path": str(row.get("class_path", "")),
        "package_name": str(row.get("package_name", "")), "mesh_path": str(row.get("mesh_path", "")),
        "mesh_class": str(row.get("mesh_class", "")), "component_class": str(row.get("component_class", "")),
        "include_in_hlod": str(row.get("include_in_hlod", "")), "density": str(row.get("density", "")),
        "radius": str(row.get("radius", "")), "align_to_normal": str(row.get("align_to_normal", "")),
        "cull_distance": str(row.get("cull_distance", "")),
        "authored_settings": property_map.get(str(row.get("foliage_type_path", "")), {}),
    } for row in raw_foliage_types]

    foliage_actors = [{
        "foliage_actor_path": str(row.get("foliage_actor_path", "")), "class_path": str(row.get("class_path", "")),
        "package_name": str(row.get("package_name", "")), "foliage_info_count": int(row.get("foliage_info_count", 0) or 0),
        "capture_mode": str(row.get("foliage_info_capture_mode", "")),
    } for row in raw_foliage_actors]

    foliage_infos = [{
        "foliage_actor_path": str(row.get("foliage_actor_path", "")), "map_index": int(row.get("map_index", 0) or 0),
        "foliage_type_path": str(row.get("foliage_type_path", "")), "foliage_type_class": str(row.get("foliage_type_class", "")),
        "implementation_type": int(row.get("implementation_type", 0) or 0), "foliage_type_update_guid": str(row.get("foliage_type_update_guid", "")),
        "instance_count": int(row.get("instance_count", 0) or 0), "placed_instance_count": int(row.get("placed_instance_count", 0) or 0),
        "capture_mode": str(row.get("capture_mode", "")),
    } for row in raw_foliage_infos]

    foliage_instances = [{
        "foliage_actor_path": str(row.get("foliage_actor_path", "")), "map_index": int(row.get("map_index", 0) or 0),
        "instance_index": int(row.get("instance_index", 0) or 0), "foliage_type_path": str(row.get("foliage_type_path", "")),
        "instance_struct": str(row.get("instance_struct", "")), "capture_mode": str(row.get("capture_mode", "")),
        "location": dict(row.get("location", {})) if isinstance(row.get("location"), dict) else {},
        "rotation": dict(row.get("rotation", {})) if isinstance(row.get("rotation"), dict) else {},
        "pre_align_rotation": dict(row.get("pre_align_rotation", {})) if isinstance(row.get("pre_align_rotation"), dict) else {},
        "draw_scale3d": dict(row.get("draw_scale3d", {})) if isinstance(row.get("draw_scale3d"), dict) else {},
        "z_offset": float(row.get("z_offset", 0.0) or 0.0), "flags": int(row.get("flags", 0) or 0),
        "base_id": int(row.get("base_id", -1) if row.get("base_id") is not None else -1),
        "base_component_path": str(row.get("base_component_path", "")), "base_component_class": str(row.get("base_component_class", "")),
        "procedural_guid": str(row.get("procedural_guid", "")), "procedural_guid_valid": bool(row.get("procedural_guid_valid", False)),
    } for row in raw_foliage_instances]

    hlod_layers = []
    for row in raw_hlod_layers:
        fields = _fields(row)
        hlod_layers.append({
            "hlod_layer_path": str(row.get("hlod_layer_path", "")), "class_path": str(row.get("class_path", "")),
            "package_name": str(row.get("package_name", "")), "layer_type": str(fields.get("LayerType", "")),
            "cell_size": str(fields.get("CellSize", "")), "loading_range": str(fields.get("LoadingRange", "")),
            "parent_layer_path": str(row.get("parentlayer_path", "")), "parent_layer_class": str(row.get("parentlayer_class", "")),
            "linked_layer_path": str(row.get("linkedlayer_path", "")), "linked_layer_class": str(row.get("linkedlayer_class", "")),
            "builder_settings_path": str(row.get("hlodbuildersettings_path", "")), "builder_settings_class": str(row.get("hlodbuildersettings_class", "")),
            "authored_settings": property_map.get(str(row.get("hlod_layer_path", "")), {}),
        })

    landscapes.sort(key=lambda r: _path_key(r["landscape_path"])); components.sort(key=lambda r: (*_path_key(r["landscape_path"]), r["component_index"], _path_key(r["component_path"])))
    weightmaps.sort(key=lambda r: (*_path_key(r["component_path"]), r["texture_index"])); allocations.sort(key=lambda r: (*_path_key(r["component_path"]), r["allocation_index"]))
    layer_infos.sort(key=lambda r: _path_key(r["layer_info_path"])); grass_types.sort(key=lambda r: _path_key(r["grass_type_path"])); grass_varieties.sort(key=lambda r: (*_path_key(r["grass_type_path"]), r["variety_index"]))
    foliage_types.sort(key=lambda r: _path_key(r["foliage_type_path"])); foliage_actors.sort(key=lambda r: _path_key(r["foliage_actor_path"])); foliage_infos.sort(key=lambda r: (*_path_key(r["foliage_actor_path"]), r["map_index"]))
    foliage_instances.sort(key=lambda r: (*_path_key(r["foliage_actor_path"]), r["map_index"], r["instance_index"])); hlod_layers.sort(key=lambda r: _path_key(r["hlod_layer_path"]))
    return {
        "world_geometry_landscapes.jsonl": landscapes, "world_geometry_landscape_components.jsonl": components,
        "world_geometry_landscape_weightmaps.jsonl": weightmaps, "world_geometry_landscape_layer_allocations.jsonl": allocations,
        "world_geometry_landscape_layer_infos.jsonl": layer_infos, "world_geometry_grass_types.jsonl": grass_types,
        "world_geometry_grass_varieties.jsonl": grass_varieties, "world_geometry_foliage_types.jsonl": foliage_types,
        "world_geometry_foliage_actors.jsonl": foliage_actors, "world_geometry_foliage_infos.jsonl": foliage_infos,
        "world_geometry_foliage_instances.jsonl": foliage_instances, "world_geometry_hlod_layers.jsonl": hlod_layers,
    }

def _manifest_counts(canonical: dict[str, list[dict]]) -> dict[str, int]:
    counts = {name.removesuffix(".jsonl"): len(values) for name, values in canonical.items()}
    counts.update({
        "landscape_components_with_heightmap": sum(bool(r.get("heightmap_texture_path")) for r in canonical["world_geometry_landscape_components.jsonl"]),
        "landscape_weightmap_texture_refs": sum(bool(r.get("texture_path")) for r in canonical["world_geometry_landscape_weightmaps.jsonl"]),
        "landscape_allocations_with_layer_info": sum(bool(r.get("layer_info_path")) for r in canonical["world_geometry_landscape_layer_allocations.jsonl"]),
        "grass_varieties_with_mesh": sum(bool(r.get("grass_mesh_path")) for r in canonical["world_geometry_grass_varieties.jsonl"]),
        "foliage_types_with_mesh": sum(bool(r.get("mesh_path")) for r in canonical["world_geometry_foliage_types.jsonl"]),
        "foliage_infos_native_editor_array": sum(r.get("capture_mode") == "native_editor_array" for r in canonical["world_geometry_foliage_infos.jsonl"]),
        "foliage_instances_native_editor_array": sum(r.get("capture_mode") == "native_editor_array" for r in canonical["world_geometry_foliage_instances.jsonl"]),
        "hlod_parent_layer_refs": sum(bool(r.get("parent_layer_path")) for r in canonical["world_geometry_hlod_layers.jsonl"]),
        "hlod_linked_layer_refs": sum(bool(r.get("linked_layer_path")) for r in canonical["world_geometry_hlod_layers.jsonl"]),
        "hlod_builder_settings_refs": sum(bool(r.get("builder_settings_path")) for r in canonical["world_geometry_hlod_layers.jsonl"]),
    })
    return {str(k): int(v) for k, v in counts.items()}

def promote_capture(corpus: Path, capture_dir: Path) -> dict:
    corpus = Path(corpus).expanduser().resolve(); capture_dir = Path(capture_dir).expanduser().resolve()
    if not corpus.is_dir(): raise FileNotFoundError(f"corpus directory does not exist: {corpus}")
    capture_manifest = capture.validate_capture(capture_dir)
    if not bool(capture_manifest.get("foliage_native_api_captured", False)):
        raise RuntimeError("world-geometry capture did not complete native foliage authoring refinement")
    canonical = _canonical_rows(capture_dir)
    for filename, values in canonical.items(): _write_jsonl(corpus / filename, values)
    counts = _manifest_counts(canonical)
    manifest = {
        "schema_version": WORLD_GEOMETRY_SCHEMA_VERSION, "pass": CANONICAL_PASS, "success": True,
        "engine_version": str(capture_manifest.get("engine_version", "")),
        "runtime_state_captured": False, "generated_geometry_captured": False, "render_resources_captured": False,
        "world_runtime_streaming_state_captured": False, "maps_loaded": False, "foliage_native_api_captured": True,
        "foliage_instance_capture_mode": str(capture_manifest.get("foliage_instance_capture_mode", "")),
        "counts": counts, "files": list(JSONL_FILES),
    }
    _write_json(corpus / MANIFEST_FILE, manifest)
    top_path = corpus / "manifest.json"; top = _read_json(top_path)
    if top is not None:
        top["world_geometry_schema_version"] = WORLD_GEOMETRY_SCHEMA_VERSION; top["world_geometry_counts"] = counts
        top["world_geometry_files"] = list(JSONL_FILES); top["world_geometry_pass"] = CANONICAL_PASS
        passes = top.get("canonical_passes", []); passes = list(passes) if isinstance(passes, list) else []
        if "world_geometry" not in passes: passes.append("world_geometry")
        top["canonical_passes"] = passes; _write_json(top_path, top)
    error = validation_error(corpus, require_present=True)
    if error: raise RuntimeError(f"promoted world-geometry schema 1 is invalid: {error}")
    try:
        import uatool_derived_freshness as freshness
        freshness.invalidate(corpus)
    except Exception: pass
    return manifest

def validation_error(output: Path, require_present: bool = True) -> str | None:
    output = Path(output).expanduser().resolve(); path = output / MANIFEST_FILE
    if not path.is_file(): return f"{MANIFEST_FILE} missing" if require_present else None
    try: manifest = _read_json(path)
    except Exception as exc: return str(exc)
    if int(manifest.get("schema_version", 0) or 0) != WORLD_GEOMETRY_SCHEMA_VERSION: return f"expected world-geometry schema {WORLD_GEOMETRY_SCHEMA_VERSION}, got {manifest.get('schema_version')}"
    if not bool(manifest.get("success", False)): return f"world-geometry pass unsuccessful: {manifest.get('error', '')}"
    for flag in ("runtime_state_captured","generated_geometry_captured","render_resources_captured","world_runtime_streaming_state_captured","maps_loaded"):
        if bool(manifest.get(flag, True)): return f"authored-only boundary violated: {flag}=true"
    if not bool(manifest.get("foliage_native_api_captured", False)): return "native foliage authoring boundary was not captured"
    files = manifest.get("files", [])
    if not isinstance(files, list) or set(files) != set(JSONL_FILES): return "world-geometry manifest file set mismatch"
    counts = manifest.get("counts", {})
    if not isinstance(counts, dict): return "world-geometry manifest counts missing or invalid"
    try: canonical = {name: list(_rows(output / name)) for name in JSONL_FILES}
    except Exception as exc: return str(exc)
    for name, values in canonical.items():
        if not (output / name).is_file(): return f"{name} missing"
        key = name.removesuffix(".jsonl")
        if int(counts.get(key, -1)) != len(values): return f"count mismatch for {key}: manifest={counts.get(key)} actual={len(values)}"
    roots = canonical["world_geometry_landscapes.jsonl"]; components = canonical["world_geometry_landscape_components.jsonl"]
    weightmaps = canonical["world_geometry_landscape_weightmaps.jsonl"]; allocations = canonical["world_geometry_landscape_layer_allocations.jsonl"]
    grass_types = canonical["world_geometry_grass_types.jsonl"]; grass_varieties = canonical["world_geometry_grass_varieties.jsonl"]
    foliage_actors = canonical["world_geometry_foliage_actors.jsonl"]; foliage_infos = canonical["world_geometry_foliage_infos.jsonl"]; foliage_instances = canonical["world_geometry_foliage_instances.jsonl"]
    root_paths = {str(r.get("landscape_path", "")) for r in roots}; component_paths = {str(r.get("component_path", "")) for r in components}
    if len(root_paths) != len(roots) or "" in root_paths: return "Landscape root identities are not unique/nonblank"
    if len(component_paths) != len(components) or "" in component_paths: return "Landscape component identities are not unique/nonblank"
    if any(str(r.get("landscape_path", "")) not in root_paths for r in components): return "Landscape component owner does not resolve"
    if len({(r.get("component_path"), int(r.get("texture_index", 0) or 0)) for r in weightmaps}) != len(weightmaps): return "Landscape weightmap identities are not unique"
    if any(str(r.get("component_path", "")) not in component_paths for r in weightmaps): return "Landscape weightmap component does not resolve"
    if len({(r.get("component_path"), int(r.get("allocation_index", 0) or 0)) for r in allocations}) != len(allocations): return "Landscape layer-allocation identities are not unique"
    if any(str(r.get("component_path", "")) not in component_paths for r in allocations): return "Landscape layer allocation component does not resolve"
    grass_paths = {str(r.get("grass_type_path", "")) for r in grass_types}
    if any(str(r.get("grass_type_path", "")) not in grass_paths for r in grass_varieties): return "Grass variety owner does not resolve"
    actor_paths = {str(r.get("foliage_actor_path", "")) for r in foliage_actors}
    info_keys = {(str(r.get("foliage_actor_path", "")), int(r.get("map_index", 0) or 0)) for r in foliage_infos}
    if len(actor_paths) != len(foliage_actors) or "" in actor_paths: return "Foliage actor identities are not unique/nonblank"
    if len(info_keys) != len(foliage_infos): return "Foliage info identities are not unique"
    if any(str(r.get("foliage_actor_path", "")) not in actor_paths for r in foliage_infos): return "Foliage info actor does not resolve"
    if any(str(r.get("capture_mode", "")) != "native_editor_array" for r in foliage_infos): return "Foliage info is not native editor-array evidence"
    instance_keys = {(str(r.get("foliage_actor_path", "")), int(r.get("map_index", 0) or 0), int(r.get("instance_index", 0) or 0)) for r in foliage_instances}
    if len(instance_keys) != len(foliage_instances): return "Foliage instance identities are not unique"
    if any((str(r.get("foliage_actor_path", "")), int(r.get("map_index", 0) or 0)) not in info_keys for r in foliage_instances): return "Foliage instance info owner does not resolve"
    if any(str(r.get("capture_mode", "")) != "native_editor_array" for r in foliage_instances): return "Foliage instance is not native editor-array evidence"
    actual_by_info = {}
    for r in foliage_instances:
        key = (str(r.get("foliage_actor_path", "")), int(r.get("map_index", 0) or 0)); actual_by_info[key] = actual_by_info.get(key, 0) + 1
    for r in foliage_infos:
        key = (str(r.get("foliage_actor_path", "")), int(r.get("map_index", 0) or 0))
        if int(r.get("instance_count", -1)) != int(actual_by_info.get(key, 0)): return f"Foliage info instance count mismatch for {key}"
    return None

def create_schema(conn) -> None:
    conn.executescript(_SQL)

def load_database(conn, output: Path, rows) -> None:
    for r in rows(Path(output) / "world_geometry_landscapes.jsonl"):
        conn.execute("INSERT INTO world_geometry_landscapes VALUES(?,?,?,?,?,?,?,?,?)", (r["landscape_path"],r["class_path"],r["package_name"],int(r["component_count"]),int(r["collision_component_count"]),r["landscape_material_path"],r["landscape_hole_material_path"],_j(r.get("authored_settings",{})),_j(r)))
    for r in rows(Path(output) / "world_geometry_landscape_components.jsonl"):
        conn.execute("INSERT INTO world_geometry_landscape_components VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (r["component_path"],r["landscape_path"],int(r["component_index"]),r["component_class"],r["section_base_x"],r["section_base_y"],r["component_size_quads"],r["num_subsections"],r["subsection_size_quads"],r["heightmap_texture_path"],r["heightmap_texture_class"],_j(r.get("authored_settings",{})),_j(r)))
    for r in rows(Path(output) / "world_geometry_landscape_weightmaps.jsonl"):
        conn.execute("INSERT INTO world_geometry_landscape_weightmaps VALUES(?,?,?,?,?,?)", (r["component_path"],int(r["texture_index"]),r["landscape_path"],r["texture_path"],r["texture_class"],_j(r)))
    for r in rows(Path(output) / "world_geometry_landscape_layer_allocations.jsonl"):
        conn.execute("INSERT INTO world_geometry_landscape_layer_allocations VALUES(?,?,?,?,?,?,?,?,?,?)", (r["component_path"],int(r["allocation_index"]),r["landscape_path"],int(r["component_index"]),r["struct_type"],r["layer_info_path"],r["weightmap_texture_index"],r["weightmap_texture_channel"],_j(r.get("fields",{})),_j(r)))
    for r in rows(Path(output) / "world_geometry_landscape_layer_infos.jsonl"):
        conn.execute("INSERT INTO world_geometry_landscape_layer_infos VALUES(?,?,?,?,?,?,?,?)", (r["layer_info_path"],r["class_path"],r["package_name"],r["layer_name"],r["physical_material_path"],r["no_weight_blend"],r["hardness"],_j(r)))
    for r in rows(Path(output) / "world_geometry_grass_types.jsonl"):
        conn.execute("INSERT INTO world_geometry_grass_types VALUES(?,?,?,?,?,?)", (r["grass_type_path"],r["class_path"],r["package_name"],r["enable_density_scaling"],int(r["grass_variety_count"]),_j(r)))
    for r in rows(Path(output) / "world_geometry_grass_varieties.jsonl"):
        conn.execute("INSERT INTO world_geometry_grass_varieties VALUES(?,?,?,?,?,?)", (r["grass_type_path"],int(r["variety_index"]),r["struct_type"],r["grass_mesh_path"],_j(r.get("authored_settings",{})),_j(r)))
    for r in rows(Path(output) / "world_geometry_foliage_types.jsonl"):
        conn.execute("INSERT INTO world_geometry_foliage_types VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (r["foliage_type_path"],r["class_path"],r["package_name"],r["mesh_path"],r["mesh_class"],r["component_class"],r["include_in_hlod"],r["density"],r["radius"],r["align_to_normal"],r["cull_distance"],_j(r.get("authored_settings",{})),_j(r)))
    for r in rows(Path(output) / "world_geometry_foliage_actors.jsonl"):
        conn.execute("INSERT INTO world_geometry_foliage_actors VALUES(?,?,?,?,?,?)", (r["foliage_actor_path"],r["class_path"],r["package_name"],int(r["foliage_info_count"]),r["capture_mode"],_j(r)))
    for r in rows(Path(output) / "world_geometry_foliage_infos.jsonl"):
        conn.execute("INSERT INTO world_geometry_foliage_infos VALUES(?,?,?,?,?,?,?,?,?,?)", (r["foliage_actor_path"],int(r["map_index"]),r["foliage_type_path"],r["foliage_type_class"],int(r["implementation_type"]),r["foliage_type_update_guid"],int(r["instance_count"]),int(r["placed_instance_count"]),r["capture_mode"],_j(r)))
    for r in rows(Path(output) / "world_geometry_foliage_instances.jsonl"):
        conn.execute("INSERT INTO world_geometry_foliage_instances VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (r["foliage_actor_path"],int(r["map_index"]),int(r["instance_index"]),r["foliage_type_path"],r["instance_struct"],r["capture_mode"],_j(r.get("location",{})),_j(r.get("rotation",{})),_j(r.get("pre_align_rotation",{})),_j(r.get("draw_scale3d",{})),float(r["z_offset"]),int(r["flags"]),int(r["base_id"]),r["base_component_path"],r["base_component_class"],r["procedural_guid"],int(bool(r["procedural_guid_valid"])),_j(r)))
    for r in rows(Path(output) / "world_geometry_hlod_layers.jsonl"):
        conn.execute("INSERT INTO world_geometry_hlod_layers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (r["hlod_layer_path"],r["class_path"],r["package_name"],r["layer_type"],r["cell_size"],r["loading_range"],r["parent_layer_path"],r["parent_layer_class"],r["linked_layer_path"],r["linked_layer_class"],r["builder_settings_path"],r["builder_settings_class"],_j(r.get("authored_settings",{})),_j(r)))

def query(conn, print_rows, pattern: str, limit: int) -> None:
    sql = """SELECT 'world_geometry_landscape' kind,landscape_path path,class_path detail FROM world_geometry_landscapes WHERE landscape_path LIKE ?
             UNION ALL SELECT 'world_geometry_foliage_type',foliage_type_path,mesh_path FROM world_geometry_foliage_types WHERE foliage_type_path LIKE ? OR mesh_path LIKE ?
             UNION ALL SELECT 'world_geometry_hlod_layer',hlod_layer_path,layer_type FROM world_geometry_hlod_layers WHERE hlod_layer_path LIKE ? LIMIT ?"""
    print_rows(conn.execute(sql, (pattern, pattern, pattern, pattern, limit)).fetchall())
