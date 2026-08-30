#!/usr/bin/env python3
"""VFX schema 1 integrity and topology validation."""
from __future__ import annotations

import collections
from pathlib import Path

from uatool_vfx_defs import VFX_SCHEMA_VERSION, RAW_FILES, read_manifest, _rows


def _count_rows(output: Path) -> dict[str, int]:
    return {
        filename.removesuffix(".jsonl"): sum(1 for _ in _rows(output / filename))
        for filename in RAW_FILES[1:]
    }


def _validate_variable_type_rows(rows: list[dict], label: str) -> str | None:
    for row in rows:
        type_value = str(row.get("type", ""))
        type_handle = str(row.get("type_handle", ""))
        if type_handle and type_value != type_handle:
            return f"{label} canonical type does not match live type handle"
    return None


def _topology_error(output: Path) -> str | None:
    systems = list(_rows(output / "niagara_systems.jsonl"))
    handles = list(_rows(output / "niagara_system_emitters.jsonl"))
    emitters = list(_rows(output / "niagara_emitters.jsonl"))
    versions = list(_rows(output / "niagara_emitter_versions.jsonl"))
    renderers = list(_rows(output / "niagara_renderers.jsonl"))
    stages = list(_rows(output / "niagara_simulation_stages.jsonl"))
    stateless = list(_rows(output / "niagara_stateless_emitters.jsonl"))
    stateless_modules = list(_rows(output / "niagara_stateless_modules.jsonl"))
    stateless_renderers = list(_rows(output / "niagara_stateless_renderers.jsonl"))
    channels = list(_rows(output / "niagara_data_channels.jsonl"))
    channel_variables = list(_rows(output / "niagara_data_channel_variables.jsonl"))
    parameter_collections = list(_rows(output / "niagara_parameter_collections.jsonl"))
    collection_parameters = list(_rows(output / "niagara_parameter_collection_parameters.jsonl"))
    cascade_systems = list(_rows(output / "cascade_systems.jsonl"))
    cascade_emitters = list(_rows(output / "cascade_emitters.jsonl"))
    cascade_lods = list(_rows(output / "cascade_lods.jsonl"))

    handles_by_system = collections.Counter(str(row.get("system_path", "")) for row in handles)
    for row in systems:
        path = str(row.get("system_path", ""))
        if int(row.get("emitter_count", 0)) != handles_by_system[path]:
            return f"Niagara system emitter count mismatch: {path}"

    versions_by_emitter = collections.Counter(str(row.get("emitter_path", "")) for row in versions)
    for row in emitters:
        path = str(row.get("emitter_path", ""))
        if int(row.get("version_count", 0)) != versions_by_emitter[path]:
            return f"Niagara emitter version count mismatch: {path}"

    renderers_by_version = collections.Counter(
        (str(row.get("emitter_path", "")), int(row.get("version_index", 0)))
        for row in renderers
    )
    stages_by_version = collections.Counter(
        (str(row.get("emitter_path", "")), int(row.get("version_index", 0)))
        for row in stages
    )
    for row in versions:
        key = (str(row.get("emitter_path", "")), int(row.get("version_index", 0)))
        if int(row.get("renderer_count", 0)) != renderers_by_version[key]:
            return f"Niagara renderer count mismatch: {key[0]} version {key[1]}"
        if int(row.get("simulation_stage_count", 0)) != stages_by_version[key]:
            return f"Niagara simulation-stage count mismatch: {key[0]} version {key[1]}"

    stateless_modules_by_emitter = collections.Counter(
        str(row.get("emitter_path", "")) for row in stateless_modules
    )
    stateless_renderers_by_emitter = collections.Counter(
        str(row.get("emitter_path", "")) for row in stateless_renderers
    )
    for row in stateless:
        path = str(row.get("emitter_path", ""))
        if int(row.get("module_count", 0)) != stateless_modules_by_emitter[path]:
            return f"Niagara stateless module count mismatch: {path}"
        if int(row.get("renderer_count", 0)) != stateless_renderers_by_emitter[path]:
            return f"Niagara stateless renderer count mismatch: {path}"

    variables_by_channel = collections.Counter(
        str(row.get("data_channel_path", "")) for row in channel_variables
    )
    for row in channels:
        path = str(row.get("data_channel_path", ""))
        if int(row.get("variable_count", 0)) != variables_by_channel[path]:
            return f"Niagara Data Channel variable count mismatch: {path}"

    type_error = _validate_variable_type_rows(
        channel_variables,
        "Niagara Data Channel variable",
    )
    if type_error:
        return type_error

    parameters_by_collection = collections.Counter(
        str(row.get("collection_path", "")) for row in collection_parameters
    )
    for row in parameter_collections:
        path = str(row.get("collection_path", ""))
        if int(row.get("parameter_count", 0)) != parameters_by_collection[path]:
            return f"Niagara Parameter Collection parameter count mismatch: {path}"

    type_error = _validate_variable_type_rows(
        collection_parameters,
        "Niagara Parameter Collection parameter",
    )
    if type_error:
        return type_error

    cascade_emitters_by_system = collections.Counter(
        str(row.get("system_path", "")) for row in cascade_emitters
    )
    for row in cascade_systems:
        path = str(row.get("system_path", ""))
        if int(row.get("emitter_count", 0)) != cascade_emitters_by_system[path]:
            return f"Cascade emitter count mismatch: {path}"

    cascade_lods_by_emitter = collections.Counter(
        (str(row.get("system_path", "")), int(row.get("emitter_index", 0)))
        for row in cascade_lods
    )
    for row in cascade_emitters:
        key = (str(row.get("system_path", "")), int(row.get("emitter_index", 0)))
        if int(row.get("lod_count", 0)) != cascade_lods_by_emitter[key]:
            return f"Cascade LOD count mismatch: {key[0]} emitter {key[1]}"

    return None


def validation_error(output: Path) -> str | None:
    output = Path(output)
    manifest = read_manifest(output)
    if manifest is None:
        return "vfx_manifest.json missing or invalid"
    if int(manifest.get("schema_version", 0) or 0) != VFX_SCHEMA_VERSION:
        return f"unsupported VFX schema {manifest.get('schema_version')}"
    if not bool(manifest.get("success", False)):
        return str(manifest.get("error", "VFX pass failed") or "VFX pass failed")

    expected_files = list(RAW_FILES[1:])
    if manifest.get("files") != expected_files:
        return "VFX manifest file list does not match schema 1"

    for filename in expected_files:
        if not (output / filename).is_file():
            return f"VFX output missing {filename}"

    try:
        actual_counts = _count_rows(output)
    except RuntimeError as exc:
        return str(exc)

    manifest_counts = manifest.get("counts", {})
    if not isinstance(manifest_counts, dict):
        return "VFX manifest counts missing or invalid"

    for key, actual in actual_counts.items():
        declared = int(manifest_counts.get(key, -1) or 0)
        if declared != actual:
            return f"VFX count mismatch for {key}: manifest={declared} actual={actual}"

    try:
        return _topology_error(output)
    except (RuntimeError, TypeError, ValueError) as exc:
        return f"VFX topology validation failed: {exc}"
