#!/usr/bin/env python3
"""Offline promotion, real-corpus acceptance and exact graph verification for mesh schema 1."""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

import uatool_staticmesh_schema as mesh_schema
import uatool_staticmesh_graph as graph
import uatool_staticmesh_model as model

ACCEPTANCE_MANIFEST = "staticmesh_schema1_acceptance.json"
GRAPH_EXPECTATIONS_MANIFEST = "staticmesh_schema1_graph_expectations.json"
GRAPH_VERIFICATION_MANIFEST = "staticmesh_schema1_graph_verification.json"

REPRESENTATIVE_MINIMUMS = {
    "static_meshes": 307,
    "static_mesh_lods": 413,
    "static_mesh_material_slots": 389,
    "static_mesh_sockets": 9,
    "static_mesh_body_setups": 307,
    "static_mesh_collision_shapes": 297,
    "nanite_enabled_static_meshes": 77,
    "multi_lod_static_meshes": 29,
}


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} root is not an object")
    return value


def _write_json(path: Path, value: dict) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _corpus(value: str) -> Path:
    result = Path(value).expanduser().resolve()
    if not result.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {result}")
    return result


def _counts(corpus: Path) -> dict[str, int]:
    manifest = _read_json(corpus / mesh_schema.MANIFEST_FILE)
    counts = manifest.get("counts", {})
    if not isinstance(counts, dict):
        raise RuntimeError("staticmesh_manifest counts missing or invalid")
    return {str(key): int(value or 0) for key, value in counts.items()}


def _expectations(corpus: Path, rows) -> dict:
    data = model.build_model(corpus, rows)
    edges = {(spec["source"], spec["relation"], spec["target"]) for spec in data["edge_specs"]}
    relation_counts = collections.Counter(relation for _, relation, _ in edges)
    return {
        "schema_version": 1,
        "target_derived_schema_version": graph.TARGET_DERIVED_SCHEMA_VERSION,
        "edge_quality": "exact_semantic",
        "runtime_state_captured": False,
        "expected_exact_semantic_edge_count": len(edges),
        "expected_relation_counts": {relation: int(relation_counts.get(relation, 0)) for relation in sorted(model.RELATIONS)},
        "expected_edges": [
            {"source": source, "relation": relation, "target": target}
            for source, relation, target in sorted(edges)
        ],
    }


def _require_representative_shape(corpus: Path, rows) -> dict[str, int]:
    error = mesh_schema.validation_error(corpus, require_present=True)
    if error:
        raise RuntimeError(f"mesh schema 1 StaticMesh corpus invalid: {error}")
    counts = _counts(corpus)
    missing = [
        f"{key}<{minimum}"
        for key, minimum in REPRESENTATIVE_MINIMUMS.items()
        if int(counts.get(key, 0)) < minimum
    ]
    if missing:
        raise RuntimeError("ContentExamples mesh-schema-1 representative corpus incomplete: " + ", ".join(missing))

    roots = list(rows(corpus / "static_meshes.jsonl"))
    lods = list(rows(corpus / "static_mesh_lods.jsonl"))
    shapes = list(rows(corpus / "static_mesh_collision_shapes.jsonl"))
    if len(roots) != int(counts.get("static_meshes", 0)):
        raise RuntimeError("StaticMesh representative root count mismatch")
    if any(int(row.get("lod_count", 0) or 0) < 1 for row in roots):
        raise RuntimeError("representative StaticMesh corpus contains a root without an authored SourceModel")
    if not any(int(row.get("lod_index", 0) or 0) > 0 for row in lods):
        raise RuntimeError("representative StaticMesh multi-LOD authored topology missing")
    if len({str(row.get("shape_type", "")) for row in shapes if row.get("shape_type")}) < 3:
        raise RuntimeError("representative StaticMesh collision-shape variety is insufficient")
    if not any(bool(row.get("nanite_enabled", False)) for row in roots):
        raise RuntimeError("representative StaticMesh Nanite-authored state missing")
    if not any(int(row.get("socket_count", 0) or 0) > 0 for row in roots):
        raise RuntimeError("representative StaticMesh socket topology missing")

    sidecar = _read_json(corpus / mesh_schema.MANIFEST_FILE)
    for flag in ("runtime_state_captured", "render_buffers_captured", "nanite_resources_captured", "runtime_physics_state_captured", "maps_loaded"):
        if bool(sidecar.get(flag, True)):
            raise RuntimeError(f"authored-only boundary violated: {flag}=true")
    return counts


def promote(corpus: Path, capture_dir: Path) -> dict:
    return mesh_schema.promote_capture(corpus, capture_dir)


def accept(corpus: Path, rows) -> dict:
    counts = _require_representative_shape(corpus, rows)
    expectations = _expectations(corpus, rows)
    if int(expectations["expected_exact_semantic_edge_count"]) <= 0:
        raise RuntimeError("mesh schema 1 acceptance produced no exact semantic graph edges")
    result = {
        "acceptance_schema_version": 1,
        "mesh_schema_version": mesh_schema.MESH_SCHEMA_VERSION,
        "structural_schema_version": int(_read_json(corpus / "manifest.json").get("schema_version", 0) or 0),
        "target_derived_schema_version": graph.TARGET_DERIVED_SCHEMA_VERSION,
        "representative_content": "ContentExamples UE 5.8.2 authored StaticMesh topology",
        "canonical_pass": "UnrealAssetToolStaticMesh",
        "runtime_state_captured": False,
        "render_buffers_captured": False,
        "nanite_resources_captured": False,
        "runtime_physics_state_captured": False,
        "maps_loaded": False,
        "counts": counts,
        "expected_relation_counts": expectations["expected_relation_counts"],
        "expected_exact_semantic_edge_count": expectations["expected_exact_semantic_edge_count"],
    }
    _write_json(corpus / ACCEPTANCE_MANIFEST, result)
    _write_json(corpus / GRAPH_EXPECTATIONS_MANIFEST, expectations)
    return result


def verify(corpus: Path, rows) -> dict:
    expectations = _read_json(corpus / GRAPH_EXPECTATIONS_MANIFEST)
    top = _read_json(corpus / "manifest.json")
    actual_version = int(top.get("derived_schema_version", 0) or 0)
    if actual_version != graph.TARGET_DERIVED_SCHEMA_VERSION:
        raise RuntimeError(f"StaticMesh graph verification requires derived schema {graph.TARGET_DERIVED_SCHEMA_VERSION}; got {actual_version}")

    expected = model.expected_edge_keys(corpus, rows)
    project_path = corpus / "project_edges.jsonl"
    if not project_path.is_file():
        raise RuntimeError("project_edges.jsonl missing; run derive first")
    actual_rows = [row for row in rows(project_path) if str(row.get("relation", "")) in model.RELATIONS]
    actual = {
        (str(row.get("source", "")), str(row.get("relation", "")), str(row.get("target", "")))
        for row in actual_rows
    }
    if actual != expected:
        missing = sorted(expected - actual); extra = sorted(actual - expected)
        parts = []
        if missing: parts.append(f"missing={len(missing)} first={missing[0]}")
        if extra: parts.append(f"extra={len(extra)} first={extra[0]}")
        raise RuntimeError("StaticMesh exact graph edge set mismatch: " + "; ".join(parts))

    relation_counts = collections.Counter()
    for row in actual_rows:
        relation = str(row.get("relation", "")); relation_counts[relation] += 1
        if str(row.get("edge_quality", "")) != "exact_semantic":
            raise RuntimeError(f"StaticMesh relation is not exact_semantic: {relation}")
        expected_stream = model.RELATION_STREAMS[relation]
        evidence = row.get("evidence", []) if isinstance(row.get("evidence", []), list) else []
        if not any(isinstance(item, dict) and str(item.get("stream", "")) == expected_stream for item in evidence):
            raise RuntimeError(f"StaticMesh relation lacks canonical evidence stream: {relation}")

    expected_counts = expectations.get("expected_relation_counts", {})
    for relation in sorted(model.RELATIONS):
        if int(expected_counts.get(relation, 0) or 0) != int(relation_counts.get(relation, 0)):
            raise RuntimeError(
                f"StaticMesh relation count mismatch for {relation}: "
                f"expected={expected_counts.get(relation,0)} actual={relation_counts.get(relation,0)}"
            )

    result = {
        "schema_version": 1,
        "verified": True,
        "mesh_schema_version": mesh_schema.MESH_SCHEMA_VERSION,
        "derived_schema_version": actual_version,
        "edge_quality": "exact_semantic",
        "verified_exact_semantic_edge_count": len(actual),
        "relation_counts": {relation: int(relation_counts.get(relation, 0)) for relation in sorted(model.RELATIONS)},
        "runtime_state_captured": False,
    }
    _write_json(corpus / GRAPH_VERIFICATION_MANIFEST, result)
    return result


def _promote_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool staticmesh-schema1-promote")
    parser.add_argument("corpus")
    parser.add_argument("--capture", help="focused staticmesh-native-capture directory; defaults to <corpus>/staticmesh-native-capture")
    args = parser.parse_args(argv)
    corpus = _corpus(args.corpus)
    capture_dir = Path(args.capture).expanduser().resolve() if args.capture else corpus / "staticmesh-native-capture"
    result = promote(corpus, capture_dir)
    print(f"promoted focused StaticMesh capture to mesh schema 1: {corpus}")
    for key in sorted(result["counts"]):
        print(f"  {key}: {result['counts'][key]}")
    print("  structural_schema_unchanged: True")
    print("  runtime_state_captured: False")
    return 0


def _accept_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool staticmesh-schema1-accept")
    parser.add_argument("corpus")
    args = parser.parse_args(argv)
    corpus = _corpus(args.corpus)
    result = accept(corpus, runtime_module._rows)
    print(f"accepted ContentExamples mesh schema 1 StaticMesh corpus: {corpus}")
    print(f"  mesh_schema_version: {result['mesh_schema_version']}")
    print(f"  structural_schema_version: {result['structural_schema_version']}")
    for key in sorted(result["counts"]):
        if key.startswith("static_mesh") or key in ("nanite_enabled_static_meshes", "multi_lod_static_meshes"):
            print(f"  {key}: {result['counts'][key]}")
    print(f"  expected_exact_semantic_edges: {result['expected_exact_semantic_edge_count']}")
    print("  runtime_state_captured: False")
    return 0


def _verify_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool staticmesh-graph-verify")
    parser.add_argument("corpus")
    args = parser.parse_args(argv)
    corpus = _corpus(args.corpus)
    result = verify(corpus, runtime_module._rows)
    print(f"verified mesh schema 1 derived-schema-{graph.TARGET_DERIVED_SCHEMA_VERSION} StaticMesh project graph: {corpus}")
    print(f"  exact_semantic_edges: {result['verified_exact_semantic_edge_count']}")
    for relation, count in sorted(result["relation_counts"].items()):
        if count:
            print(f"  {relation}: {count}")
    print("  runtime_state_captured: False")
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_staticmesh_schema1_accept_installed", False):
        return
    try:
        import uatool_core as core
        core.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((
            *core.DEFAULT_BUNDLE_FILES,
            ACCEPTANCE_MANIFEST, GRAPH_EXPECTATIONS_MANIFEST, GRAPH_VERIFICATION_MANIFEST,
        )))
    except Exception:
        pass
    original_main = runtime_module.main

    def main():
        command = sys.argv[1] if len(sys.argv) > 1 else ""
        try:
            if command == "staticmesh-schema1-promote":
                return _promote_cli(runtime_module, sys.argv[2:])
            if command == "staticmesh-schema1-accept":
                return _accept_cli(runtime_module, sys.argv[2:])
            if command == "staticmesh-graph-verify":
                return _verify_cli(runtime_module, sys.argv[2:])
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 66
        return original_main()

    runtime_module.main = main
    runtime_module._staticmesh_schema1_accept_installed = True
