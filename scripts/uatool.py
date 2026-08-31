#!/usr/bin/env python3
"""Canonical UnrealAssetTool CLI composition root."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import uatool_core as core
import uatool_runtime as runtime
import uatool_vfx as vfx
import uatool_vfx_stitch as vfx_stitch
import uatool_systems as systems
import uatool_blueprint_semantics as blueprint_semantics
import uatool_blueprint_statements as blueprint_statements
import uatool_project_graph as project_graph
import uatool_project_graph_finalize as project_graph_finalize
import uatool_project_neighborhoods as neighborhood_policy
import uatool_project_neighborhood_compact as neighborhood_compact
import uatool_canonical_cleanup as canonical_cleanup
import uatool_derived_freshness as derived_freshness
import uatool_build_perf as build_perf
import uatool_verify_bundle as bundle_verify

# Schema 17 adds generic Blueprint semantic statements/basic-block summaries on
# top of schema-16 semantic nodes/flow.  Statements join the existing recursive
# data-dependency expressions and execution blocks rather than duplicating K2
# traversal or adding gameplay-domain parsers.
FINAL_DERIVED_SCHEMA_VERSION = 17
project_graph.DERIVED_SCHEMA_VERSION = FINAL_DERIVED_SCHEMA_VERSION
SCRIPT_DIR = Path(__file__).resolve().parent

# Patch core build/staging globals before capturing the composed pipeline.
build_perf.install(core)

# uatool_runtime installs the structural/world/animation/derived-schema-11
# pipeline into uatool_core. This composition root adds independently versioned
# VFX, systems, generic Blueprint semantics/statements, and the final typed
# project graph without creating alternate public launchers.
_base_create_schema = core.create_schema
_base_derive_output = core.derive_output
_base_build_database = core.build_database
_base_query = core.query
_base_scan = core.scan


def create_schema(conn) -> None:
    _base_create_schema(conn)

    # uat.db is a disposable cache rebuilt from authoritative JSONL. During a
    # from-scratch pack, durable WAL journaling only duplicates write traffic.
    # Build it in bulk with journaling/sync disabled, then restore a normal
    # persistent mode after the database is complete.
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-262144")

    vfx.create_schema(conn)
    vfx_stitch.create_schema(conn)
    systems.create_schema(conn)
    blueprint_semantics.create_schema(conn)
    blueprint_statements.create_schema(conn)
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
    if version < vfx_stitch.DERIVED_SCHEMA_VERSION:
        raise RuntimeError(
            f"VFX derived incomplete: expected derived schema >= {vfx_stitch.DERIVED_SCHEMA_VERSION}, got {version}"
        )


def _require_blueprint_semantics(output: Path) -> None:
    error = blueprint_semantics.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"Blueprint semantic derived incomplete: {error}")


def _require_blueprint_statements(output: Path) -> None:
    error = blueprint_statements.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"Blueprint statement derived incomplete: {error}")


def _require_project_graph(output: Path) -> None:
    error = project_graph.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"project graph incomplete: {error}")
    error = project_graph_finalize.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"project graph incomplete: {error}")
    error = neighborhood_compact.validation_error(output, runtime._rows)
    if error:
        raise RuntimeError(f"project graph incomplete: {error}")
    manifest = _require_declared_counts(output, project_graph.DERIVED_FILES, "project graph")
    version = int(manifest.get("derived_schema_version", 0) or 0)
    if version != FINAL_DERIVED_SCHEMA_VERSION:
        raise RuntimeError(
            f"project graph incomplete: expected derived schema {FINAL_DERIVED_SCHEMA_VERSION}, got {version}"
        )


def _derived_is_fresh(output: Path) -> bool:
    return derived_freshness.is_fresh(
        output,
        schema_version=FINAL_DERIVED_SCHEMA_VERSION,
        script_dir=SCRIPT_DIR,
    )


def _declared_derived_counts(output: Path) -> dict[str, int]:
    manifest = _read_top_manifest(output)
    declared = manifest.get("derived_counts", {})
    if not isinstance(declared, dict):
        return {}
    result: dict[str, int] = {}
    for key, value in declared.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _semantic_coverage_counts(semantic_nodes: list[dict]) -> tuple[int, int, int]:
    opaque = sum(int(bool(row.get("opaque", False))) for row in semantic_nodes)
    fallback = sum(
        int(not bool(row.get("opaque", False)) and str(row.get("semantic_kind", "") or "") == "classified")
        for row in semantic_nodes
    )
    modeled = len(semantic_nodes) - opaque - fallback
    return modeled, fallback, opaque


def derive_output(output):
    output = Path(output).expanduser().resolve()

    cleanup = canonical_cleanup.apply(output)
    cleanup_error = canonical_cleanup.validation_error(output)
    if cleanup_error:
        raise RuntimeError(f"canonical cleanup incomplete: {cleanup_error}")
    if cleanup.get("material_expression_guids", 0):
        print(
            "canonical cleanup: removed generated MaterialExpressionGuid rows="
            f"{cleanup['material_expression_guids']}"
        )
    if cleanup.get("blueprint_nodes_rewritten", 0):
        print(
            "canonical cleanup: removed redundant inline Blueprint pins="
            f"{cleanup.get('inline_blueprint_pins', 0)} "
            f"from nodes={cleanup['blueprint_nodes_rewritten']}"
        )

    # A freshness stamp exists only after a complete raw + derived validation.
    # Canonical cleanup runs first: if it changed a raw file, its metadata no
    # longer matches the stamp and this fast path automatically misses.
    if _derived_is_fresh(output):
        print(f"derived output current: reusing validated schema {FINAL_DERIVED_SCHEMA_VERSION}")
        return _declared_derived_counts(output)

    # Raw specialist passes are prerequisites for the unified graph. Gate before
    # rewriting derived files so failed/old scans cannot look fresh.
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

    semantic_nodes, semantic_edges, semantic_graphs = blueprint_semantics.derive(output, runtime._rows)
    semantic_counts = {
        "blueprint_semantic_nodes": runtime._write(output / "blueprint_semantic_nodes.jsonl", semantic_nodes),
        "blueprint_semantic_edges": runtime._write(output / "blueprint_semantic_edges.jsonl", semantic_edges),
        "blueprint_semantic_graphs": runtime._write(output / "blueprint_semantic_graphs.jsonl", semantic_graphs),
    }
    counts.update(semantic_counts)

    statement_rows, semantic_blocks = blueprint_statements.derive(output, runtime._rows)
    statement_counts = {
        "blueprint_semantic_statements": runtime._write(output / "blueprint_semantic_statements.jsonl", statement_rows),
        "blueprint_semantic_blocks": runtime._write(output / "blueprint_semantic_blocks.jsonl", semantic_blocks),
    }
    counts.update(statement_counts)

    project_nodes, project_edges, _ = project_graph.derive(output, runtime._rows)
    project_nodes, project_edges, _ = project_graph_finalize.finalize(
        output, runtime._rows, project_nodes, project_edges
    )
    project_neighborhoods = neighborhood_policy.rebuild(
        project_nodes,
        project_edges,
        quality_rank=project_graph.QUALITY_RANK,
        coverage_rank=project_graph.COVERAGE_RANK,
        max_depth=project_graph.MAX_NEIGHBOR_DEPTH,
        max_edges=project_graph.MAX_NEIGHBOR_EDGES,
        max_chars=project_graph.MAX_NEIGHBOR_CHARS,
        compact=True,
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
    error = neighborhood_compact.validation_error(output, runtime._rows)
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

        modeled_nodes, fallback_nodes, opaque_nodes = _semantic_coverage_counts(semantic_nodes)
        classified_nodes = modeled_nodes + fallback_nodes
        manifest["blueprint_semantic_schema_version"] = blueprint_semantics.SEMANTIC_SCHEMA_VERSION
        manifest["blueprint_semantic_summary"] = {
            "node_count": len(semantic_nodes),
            "classified_node_count": classified_nodes,
            "modeled_node_count": modeled_nodes,
            "fallback_node_count": fallback_nodes,
            "opaque_node_count": opaque_nodes,
            "graph_count": len(semantic_graphs),
            "edge_count": len(semantic_edges),
            "coverage": (classified_nodes / len(semantic_nodes)) if semantic_nodes else 1.0,
            "modeled_coverage": (modeled_nodes / len(semantic_nodes)) if semantic_nodes else 1.0,
        }
        manifest["blueprint_statement_schema_version"] = blueprint_statements.STATEMENT_SCHEMA_VERSION
        manifest["blueprint_statement_summary"] = {
            "statement_count": len(statement_rows),
            "block_count": len(semantic_blocks),
            "dependency_statement_count": sum(int(bool(row.get("dependency_count", 0))) for row in statement_rows),
            "literal_statement_count": sum(int(bool(row.get("literal_count", 0))) for row in statement_rows),
        }
        manifest["derived_schema_version"] = FINAL_DERIVED_SCHEMA_VERSION
        declared = manifest.get("derived_counts", {})
        declared = declared if isinstance(declared, dict) else {}
        declared.update(vfx_counts)
        declared.update(semantic_counts)
        declared.update(statement_counts)
        declared.update(project_counts)
        manifest["derived_counts"] = declared
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    _require_vfx_derived(output)
    _require_blueprint_semantics(output)
    _require_blueprint_statements(output)
    _require_project_graph(output)
    derived_freshness.mark_fresh(
        output,
        schema_version=FINAL_DERIVED_SCHEMA_VERSION,
        script_dir=SCRIPT_DIR,
    )
    modeled_nodes, fallback_nodes, opaque_nodes = _semantic_coverage_counts(semantic_nodes)
    print(
        "blueprint semantics: "
        f"nodes={len(semantic_nodes)} modeled={modeled_nodes} fallback={fallback_nodes} opaque={opaque_nodes} "
        f"graphs={len(semantic_graphs)} edges={len(semantic_edges)}"
    )
    print(
        "blueprint statements: "
        f"statements={len(statement_rows)} blocks={len(semantic_blocks)} "
        f"with_dependencies={sum(int(bool(row.get('dependency_count', 0))) for row in statement_rows)} "
        f"with_literals={sum(int(bool(row.get('literal_count', 0))) for row in statement_rows)}"
    )
    return counts


def build_database(output):
    output = Path(output).expanduser().resolve()
    fresh = _derived_is_fresh(output)

    # A freshness stamp is written only after all raw and derived validation has
    # succeeded. If it is current, reparsing those same streams immediately
    # before a disposable SQLite rebuild adds no safety. The conservative path
    # remains for direct/old/stale build_database callers.
    if not fresh:
        _require_vfx(output)
        _require_systems(output)
        _require_vfx_derived(output)
        _require_blueprint_semantics(output)
        _require_blueprint_statements(output)
        _require_project_graph(output)

    db = _base_build_database(output)
    conn = sqlite3.connect(db)
    try:
        vfx.load_database(conn, output, runtime._rows)
        vfx_stitch.load_database(conn, output, runtime._rows)
        systems.load_database(conn, output, runtime._rows)
        blueprint_semantics.load_database(conn, output, runtime._rows)
        blueprint_statements.load_database(conn, output, runtime._rows)
        # project_neighborhoods loads compact JSON and an empty text field.
        # Readable text is reconstructed only when queried, avoiding another
        # hundreds-of-megabytes copy of neighborhood paths in uat.db.
        project_graph.load_database(conn, output, runtime._rows)
        conn.commit()
        conn.execute("PRAGMA optimize")
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA synchronous=NORMAL")
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
            neighborhood_compact.query(
                conn,
                core._print_rows,
                pattern,
                args.limit,
                max_chars=project_graph.MAX_NEIGHBOR_CHARS,
            )
            blueprint_statements.query(conn, core._print_rows, pattern, args.limit)
            blueprint_semantics.query(conn, core._print_rows, pattern, args.limit)
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
    semantic_summary = top_manifest.get("blueprint_semantic_summary", {})
    semantic_summary = semantic_summary if isinstance(semantic_summary, dict) else {}
    statement_summary = top_manifest.get("blueprint_statement_summary", {})
    statement_summary = statement_summary if isinstance(statement_summary, dict) else {}

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
    if semantic_summary:
        modeled_coverage = float(semantic_summary.get("modeled_coverage", 0.0) or 0.0) * 100.0
        print(
            "blueprint semantic complete: "
            f"nodes={semantic_summary.get('node_count', 0)} "
            f"modeled={semantic_summary.get('modeled_node_count', 0)} "
            f"fallback={semantic_summary.get('fallback_node_count', 0)} "
            f"opaque={semantic_summary.get('opaque_node_count', 0)} "
            f"graphs={semantic_summary.get('graph_count', 0)} "
            f"edges={semantic_summary.get('edge_count', 0)} modeled_coverage={modeled_coverage:.2f}%"
        )
    if statement_summary:
        print(
            "blueprint statement complete: "
            f"statements={statement_summary.get('statement_count', 0)} "
            f"blocks={statement_summary.get('block_count', 0)} "
            f"with_dependencies={statement_summary.get('dependency_statement_count', 0)} "
            f"with_literals={statement_summary.get('literal_statement_count', 0)}"
        )
    print(
        "final derived complete: "
        + " ".join(
            f"{name}={dc.get(name, 0)}"
            for name in (
                "blueprint_semantic_nodes", "blueprint_semantic_edges", "blueprint_semantic_graphs",
                "blueprint_semantic_statements", "blueprint_semantic_blocks",
                "vfx_relations", "vfx_context", "vfx_summaries",
                "project_nodes", "project_edges", "project_neighborhoods",
            )
        )
    )
    print(
        f"schemas: vfx={vfx_manifest.get('schema_version', 0)} "
        f"systems={systems_manifest.get('schema_version', 0)} "
        f"bp_semantic={top_manifest.get('blueprint_semantic_schema_version', 0)} "
        f"bp_statement={top_manifest.get('blueprint_statement_schema_version', 0)} "
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
        if "canonical cleanup incomplete:" in message:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 29
        if "Blueprint semantic derived incomplete:" in message:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 31
        if "Blueprint statement derived incomplete:" in message:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 32
        raise
    if result != 0:
        return result

    output = runtime._output(args)
    if not _derived_is_fresh(output):
        # This should be rare: the composed derive writes the stamp only after
        # all raw/derived validators pass. Keep a conservative diagnostic path
        # for old/unexpected outputs without imposing the full parse on every
        # successful normal scan.
        error = canonical_cleanup.validation_error(output)
        if error:
            print(f"ERROR: canonical cleanup incomplete: {error}", file=sys.stderr)
            return 29
        error = vfx.validation_error(output)
        if error:
            print(f"ERROR: VFX scan incomplete: {error}", file=sys.stderr)
            return 25
        error = systems.validation_error(output)
        if error:
            print(f"ERROR: systems scan incomplete: {error}", file=sys.stderr)
            return 27
        try:
            _require_vfx_derived(output)
            _require_blueprint_semantics(output)
            _require_blueprint_statements(output)
            _require_project_graph(output)
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            message = str(exc)
            if "Blueprint semantic derived incomplete:" in message:
                return 31
            if "Blueprint statement derived incomplete:" in message:
                return 32
            return 28 if "project graph incomplete:" in message else 26
        derived_freshness.mark_fresh(
            output,
            schema_version=FINAL_DERIVED_SCHEMA_VERSION,
            script_dir=SCRIPT_DIR,
        )

    _combined_summary(args)
    return 0


core.create_schema = create_schema
core.derive_output = derive_output
core.build_database = build_database
core.query = query
core.scan = scan
core.DERIVED_SCHEMA_VERSION = FINAL_DERIVED_SCHEMA_VERSION
core.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((
    *core.DEFAULT_BUNDLE_FILES,
    *vfx.RAW_FILES,
    *vfx_stitch.DERIVED_FILES,
    *systems.RAW_FILES,
    *blueprint_semantics.DERIVED_FILES,
    *blueprint_statements.DERIVED_FILES,
    *project_graph.DERIVED_FILES,
)))


def _verify_bundle_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool verify-bundle",
        description="validate an existing UnrealAssetTool bundle without rescanning Unreal",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("bundle", help="bundle ZIP to validate")
    parser.add_argument("--baseline", help="optional previous bundle ZIP for exact member diff")
    parser.add_argument(
        "--expect-blueprint-pin-sha256",
        help="optional expected canonical logical Blueprint-pin SHA-256",
    )
    parser.add_argument(
        "--expect-changed",
        nargs="*",
        help="optional exact set of archive members allowed to differ from --baseline",
    )
    args = parser.parse_args(argv)
    if args.expect_changed is not None and not args.baseline:
        parser.error("--expect-changed requires --baseline")
    result = bundle_verify.verify_bundle(
        Path(args.output),
        Path(args.bundle),
        baseline=Path(args.baseline) if args.baseline else None,
        expect_blueprint_pin_sha256=args.expect_blueprint_pin_sha256,
        expect_changed=set(args.expect_changed) if args.expect_changed is not None else None,
    )
    bundle_verify.print_report(result)
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "verify-bundle":
        try:
            return _verify_bundle_cli(sys.argv[2:])
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 30
    return int(runtime.main())


if __name__ == "__main__":
    raise SystemExit(main())
