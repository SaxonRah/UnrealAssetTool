#!/usr/bin/env python3
"""Canonical UnrealAssetTool CLI composition root."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import uatool_core as core
import uatool_runtime as runtime
import uatool_vfx as vfx
import uatool_vfx_stitch as vfx_stitch
import uatool_systems as systems
import uatool_project_graph as project_graph
import uatool_project_graph_finalize as project_graph_finalize

# uatool_runtime installs the structural/world/animation/derived-schema-11
# pipeline into uatool_core. This composition root adds independently versioned
# VFX, remaining systems, and the final typed project graph without creating
# alternate public launchers.
_base_create_schema = core.create_schema
_base_derive_output = core.derive_output
_base_build_database = core.build_database
_base_query = core.query
_base_scan = core.scan


def create_schema(conn) -> None:
    _base_create_schema(conn)
    vfx.create_schema(conn)
    vfx_stitch.create_schema(conn)
    systems.create_schema(conn)
    project_graph.create_schema(conn)


def _read_top_manifest(output: Path) -> dict:
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("manifest.json missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid manifest.json: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("manifest.json root is not an object")
    return manifest


def _require_vfx(output: Path) -> None:
    error = vfx.validation_error(output)
    if error:
        raise RuntimeError(f"VFX scan incomplete: {error}")


def _require_systems(output: Path) -> None:
    error = systems.validation_error(output)
    if error:
        raise RuntimeError(f"systems scan incomplete: {error}")


def _require_declared_counts(output: Path, filenames: tuple[str, ...], prefix: str) -> dict:
    manifest = _read_top_manifest(output)
    declared = manifest.get("derived_counts", {})
    if not isinstance(declared, dict):
        raise RuntimeError(f"{prefix} incomplete: derived_counts missing or invalid")
    for filename in filenames:
        key = filename.removesuffix(".jsonl")
        actual = sum(1 for _ in runtime._rows(output / filename))
        if int(declared.get(key, -1)) != actual:
            raise RuntimeError(
                f"{prefix} incomplete: count mismatch for {key}: "
                f"manifest={declared.get(key)} actual={actual}"
            )
    return manifest


def _require_vfx_derived(output: Path) -> None:
    error = vfx_stitch.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"VFX derived incomplete: {error}")
    manifest = _require_declared_counts(output, vfx_stitch.DERIVED_FILES, "VFX derived")
    version = int(manifest.get("derived_schema_version", 0) or 0)
    # VFX relations were introduced in schema 12 and remain valid members of
    # later derived schemas. Do not make their validator reject schema 13+.
    if version < vfx_stitch.DERIVED_SCHEMA_VERSION:
        raise RuntimeError(
            f"VFX derived incomplete: expected derived schema >= {vfx_stitch.DERIVED_SCHEMA_VERSION}, got {version}"
        )


def _require_project_graph(output: Path) -> None:
    error = project_graph.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"project graph incomplete: {error}")
    error = project_graph_finalize.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"project graph incomplete: {error}")
    manifest = _require_declared_counts(output, project_graph.DERIVED_FILES, "project graph")
    version = int(manifest.get("derived_schema_version", 0) or 0)
    if version != project_graph.DERIVED_SCHEMA_VERSION:
        raise RuntimeError(
            f"project graph incomplete: expected derived schema {project_graph.DERIVED_SCHEMA_VERSION}, got {version}"
        )


def derive_output(output):
    output = Path(output).expanduser().resolve()
    # Raw specialist passes are prerequisites for the unified graph. Gate before
    # rewriting any derived files so failed/old scans cannot look fresh.
    _require_vfx(output)
    _require_systems(output)
    counts = dict(_base_derive_output(output))

    vfx_relations, vfx_context, vfx_summaries = vfx_stitch.derive(output, runtime._rows)
    vfx_counts = {
        "vfx_relations": runtime._write(output / "vfx_relations.jsonl", vfx_relations),
        "vfx_context": runtime._write(output / "vfx_context.jsonl", vfx_context),
        "vfx_summaries": runtime._write(output / "vfx_summaries.jsonl", vfx_summaries),
    }
    error = vfx_stitch.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"VFX derived incomplete: {error}")
    counts.update(vfx_counts)

    project_nodes, project_edges, _ = project_graph.derive(output, runtime._rows)
    project_nodes, project_edges, project_neighborhoods = project_graph_finalize.finalize(
        output, runtime._rows, project_nodes, project_edges
    )
    project_counts = {
        "project_nodes": runtime._write(output / "project_nodes.jsonl", project_nodes),
        "project_edges": runtime._write(output / "project_edges.jsonl", project_edges),
        "project_neighborhoods": runtime._write(output / "project_neighborhoods.jsonl", project_neighborhoods),
    }
    error = project_graph.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"project graph incomplete: {error}")
    error = project_graph_finalize.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"project graph incomplete: {error}")
    counts.update(project_counts)

    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        vfx_manifest = vfx.read_manifest(output)
        if vfx_manifest:
            manifest["vfx_schema_version"] = int(vfx_manifest.get("schema_version", 0) or 0)
            manifest["vfx_counts"] = vfx_manifest.get("counts", {})
            manifest["vfx_files"] = vfx_manifest.get("files", [])
            manifest["vfx_pass"] = vfx_manifest.get("pass", "UnrealAssetToolVFX")

        systems_manifest = systems.read_manifest(output)
        if systems_manifest:
            manifest["systems_schema_version"] = int(systems_manifest.get("schema_version", 0) or 0)
            manifest["systems_counts"] = systems_manifest.get("counts", {})
            manifest["systems_files"] = systems_manifest.get("files", [])
            manifest["systems_pass"] = systems_manifest.get("pass", "UnrealAssetToolSystems")

        manifest["derived_schema_version"] = project_graph.DERIVED_SCHEMA_VERSION
        declared = manifest.get("derived_counts", {})
        declared = declared if isinstance(declared, dict) else {}
        declared.update(vfx_counts)
        declared.update(project_counts)
        manifest["derived_counts"] = declared
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    _require_vfx_derived(output)
    _require_project_graph(output)
    return counts


def build_database(output):
    output = Path(output).expanduser().resolve()
    _require_vfx(output)
    _require_systems(output)
    _require_vfx_derived(output)
    _require_project_graph(output)
    db = _base_build_database(output)
    conn = sqlite3.connect(db)
    try:
        vfx.load_database(conn, output, runtime._rows)
        vfx_stitch.load_database(conn, output, runtime._rows)
        systems.load_database(conn, output, runtime._rows)
        project_graph.load_database(conn, output, runtime._rows)
        conn.commit()
    finally:
        conn.close()
    return db


def query(args):
    result = int(_base_query(args))
    root = Path(args.output).expanduser().resolve()
    db = root if root.suffix.lower() == ".db" else root / core.DB_NAME
    if db.is_file():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            pattern = f"%{args.term}%"
            project_graph.query(conn, core._print_rows, pattern, args.limit)
            systems.query(conn, core._print_rows, pattern, args.limit)
            vfx_stitch.query(conn, core._print_rows, pattern, args.limit)
            vfx.query(conn, core._print_rows, pattern, args.limit)
        finally:
            conn.close()
    return result


def _combined_summary(args) -> None:
    output = runtime._output(args)
    vfx_manifest = vfx.read_manifest(output) or {}
    systems_manifest = systems.read_manifest(output) or {}
    top_manifest = {}
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        try:
            top_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            top_manifest = {}

    vc = vfx_manifest.get("counts", {}) if isinstance(vfx_manifest.get("counts", {}), dict) else {}
    sc = systems_manifest.get("counts", {}) if isinstance(systems_manifest.get("counts", {}), dict) else {}
    dc = top_manifest.get("derived_counts", {}) if isinstance(top_manifest.get("derived_counts", {}), dict) else {}

    print(
        "vfx scan complete: "
        + " ".join(
            f"{name}={vc.get(name, 0)}"
            for name in (
                "vfx_assets", "niagara_systems", "niagara_system_emitters", "niagara_emitters",
                "niagara_stateless_emitters", "niagara_data_channels", "niagara_parameter_collections",
                "cascade_systems",
            )
        )
    )
    print(
        "systems scan complete: "
        + " ".join(
            f"{name}={sc.get(name, 0)}"
            for name in (
                "systems_assets", "level_sequences", "movie_scene_tracks", "movie_scene_sections",
                "movie_scene_channels", "audio_assets", "metasound_nodes", "metasound_edges",
                "input_actions", "input_mapping_contexts", "input_mappings", "gameplay_tags",
            )
        )
    )
    print(
        "final derived complete: "
        + " ".join(
            f"{name}={dc.get(name, 0)}"
            for name in (
                "vfx_relations", "vfx_context", "vfx_summaries",
                "project_nodes", "project_edges", "project_neighborhoods",
            )
        )
    )
    print(
        f"schemas: vfx={vfx_manifest.get('schema_version', 0)} "
        f"systems={systems_manifest.get('schema_version', 0)} "
        f"derived={top_manifest.get('derived_schema_version', 0)}"
    )


def scan(args):
    try:
        result = int(_base_scan(args))
    except RuntimeError as exc:
        message = str(exc)
        if "VFX scan incomplete:" in message:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 25
        if "VFX derived incomplete:" in message:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 26
        if "systems scan incomplete:" in message:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 27
        if "project graph incomplete:" in message:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 28
        raise
    if result != 0:
        return result

    error = vfx.validation_error(runtime._output(args))
    if error:
        print(f"ERROR: VFX scan incomplete: {error}", file=sys.stderr)
        return 25
    error = systems.validation_error(runtime._output(args))
    if error:
        print(f"ERROR: systems scan incomplete: {error}", file=sys.stderr)
        return 27
    try:
        _require_vfx_derived(runtime._output(args))
        _require_project_graph(runtime._output(args))
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 28 if "project graph incomplete:" in str(exc) else 26
    _combined_summary(args)
    return 0


core.create_schema = create_schema
core.derive_output = derive_output
core.build_database = build_database
core.query = query
core.scan = scan
core.DERIVED_SCHEMA_VERSION = project_graph.DERIVED_SCHEMA_VERSION
core.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((
    *core.DEFAULT_BUNDLE_FILES,
    *vfx.RAW_FILES,
    *vfx_stitch.DERIVED_FILES,
    *systems.RAW_FILES,
    *project_graph.DERIVED_FILES,
)))


def main():
    return int(runtime.main())


if __name__ == "__main__":
    raise SystemExit(main())
