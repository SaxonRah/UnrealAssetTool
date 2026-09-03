#!/usr/bin/env python3
"""Real-corpus acceptance and exact graph verification for animation schema 3."""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

import uatool_animation_mesh_physics as mesh_physics
import uatool_animation_mesh_physics_graph as graph
import uatool_animation_mesh_physics_model as model

ACCEPTANCE_MANIFEST = "animation_schema3_acceptance.json"
GRAPH_EXPECTATIONS_MANIFEST = "animation_schema3_graph_expectations.json"
GRAPH_VERIFICATION_MANIFEST = "animation_schema3_graph_verification.json"

REPRESENTATIVE_MINIMUMS = {
    "skeletal_meshes": 45,
    "skeletal_mesh_lods": 77,
    "skeletal_mesh_materials": 134,
    "skeletal_mesh_morph_targets": 186,
    "skeletal_mesh_clothing_assets": 11,
    "skeletal_mesh_clothing_configs": 11,
    "physics_assets": 28,
    "physics_bodies": 263,
    "physics_body_shapes": 289,
    "physics_constraints": 221,
    "physics_constraint_profiles": 10,
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


def _canonical_counts(corpus: Path) -> dict[str, int]:
    manifest = _read_json(corpus / "animation_mesh_physics_manifest.json")
    counts = manifest.get("counts", {})
    if not isinstance(counts, dict):
        raise RuntimeError("animation_mesh_physics_manifest counts missing or invalid")
    return {str(k): int(v or 0) for k, v in counts.items()}


def _require_representative_shape(corpus: Path, rows) -> dict:
    error = mesh_physics.validation_error(corpus, require_present=True)
    if error:
        raise RuntimeError(f"animation schema 3 canonical mesh/physics invalid: {error}")
    animation = _read_json(corpus / "animation_manifest.json")
    if int(animation.get("schema_version", 0) or 0) != 3:
        raise RuntimeError(f"animation schema 3 acceptance requires public animation schema 3; got {animation.get('schema_version')!r}")
    if int(animation.get("mesh_physics_schema_version", 0) or 0) != 1:
        raise RuntimeError("animation schema 3 acceptance requires mesh_physics_schema_version=1")

    counts = _canonical_counts(corpus)
    missing = [
        f"{key}<{minimum}"
        for key, minimum in REPRESENTATIVE_MINIMUMS.items()
        if int(counts.get(key, 0)) < minimum
    ]
    if missing:
        raise RuntimeError("ContentExamples animation-schema-3 representative corpus incomplete: " + ", ".join(missing))

    if int(counts.get("physics_physical_animation_profiles", -1)) < 0 or int(counts.get("physics_collision_disable_pairs", -1)) < 0:
        raise RuntimeError("supported zero-count profile/collision streams are missing from the manifest")

    bodies = list(rows(corpus / "physics_bodies.jsonl"))
    constraints = list(rows(corpus / "physics_constraints.jsonl"))
    shapes = list(rows(corpus / "physics_body_shapes.jsonl"))
    if not any(str(row.get("bone_name", "")) for row in bodies):
        raise RuntimeError("representative PhysicsAsset body->bone evidence missing")
    if not any(str(row.get("constraint_bone1", "")) and str(row.get("constraint_bone2", "")) for row in constraints):
        raise RuntimeError("representative PhysicsAsset constraint endpoints missing")
    if len({str(row.get("shape_type", "")) for row in shapes if row.get("shape_type")}) < 2:
        raise RuntimeError("representative PhysicsAsset collision-shape variety is insufficient")

    sidecar = _read_json(corpus / "animation_mesh_physics_manifest.json")
    for flag in ("runtime_state_captured", "render_buffers_captured", "cloth_simulation_state_captured", "chaos_runtime_state_captured", "maps_loaded"):
        if bool(sidecar.get(flag, True)):
            raise RuntimeError(f"authored-only boundary violated: {flag}=true")
    return counts


def _expectations(corpus: Path, rows) -> dict:
    data = model.build_model(corpus, rows)
    edges = {
        (spec["source"], spec["relation"], spec["target"])
        for spec in data["edge_specs"]
    }
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


def accept(corpus: Path, rows) -> dict:
    counts = _require_representative_shape(corpus, rows)
    expectations = _expectations(corpus, rows)
    if int(expectations["expected_exact_semantic_edge_count"]) <= 0:
        raise RuntimeError("animation schema 3 acceptance produced no exact semantic graph edges")
    result = {
        "acceptance_schema_version": 1,
        "animation_schema_version": 3,
        "mesh_physics_schema_version": 1,
        "target_derived_schema_version": graph.TARGET_DERIVED_SCHEMA_VERSION,
        "representative_content": "ContentExamples UE 5.8.2 authored SkeletalMesh / PhysicsAsset topology",
        "canonical_pass": "UnrealAssetToolAnimationMeshPhysics",
        "runtime_state_captured": False,
        "render_buffers_captured": False,
        "cloth_simulation_state_captured": False,
        "chaos_runtime_state_captured": False,
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
        raise RuntimeError(f"animation schema 3 graph verification requires derived schema {graph.TARGET_DERIVED_SCHEMA_VERSION}; got {actual_version}")

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
        raise RuntimeError("animation schema 3 exact graph edge set mismatch: " + "; ".join(parts))

    relation_counts = collections.Counter()
    for row in actual_rows:
        relation = str(row.get("relation", "")); relation_counts[relation] += 1
        if str(row.get("edge_quality", "")) != "exact_semantic":
            raise RuntimeError(f"animation schema 3 relation is not exact_semantic: {relation}")
        expected_stream = model.RELATION_STREAMS[relation]
        evidence = row.get("evidence", []) if isinstance(row.get("evidence", []), list) else []
        if not any(isinstance(item, dict) and str(item.get("stream", "")) == expected_stream for item in evidence):
            raise RuntimeError(f"animation schema 3 relation lacks canonical evidence stream: {relation}")

    expected_counts = expectations.get("expected_relation_counts", {})
    for relation in sorted(model.RELATIONS):
        if int(expected_counts.get(relation, 0) or 0) != int(relation_counts.get(relation, 0)):
            raise RuntimeError(f"animation schema 3 relation count mismatch for {relation}: expected={expected_counts.get(relation,0)} actual={relation_counts.get(relation,0)}")

    result = {
        "schema_version": 1,
        "verified": True,
        "animation_schema_version": 3,
        "mesh_physics_schema_version": 1,
        "derived_schema_version": actual_version,
        "edge_quality": "exact_semantic",
        "verified_exact_semantic_edge_count": len(actual),
        "relation_counts": {relation: int(relation_counts.get(relation, 0)) for relation in sorted(model.RELATIONS)},
        "runtime_state_captured": False,
    }
    _write_json(corpus / GRAPH_VERIFICATION_MANIFEST, result)
    return result


def _accept_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool animation-schema3-accept")
    parser.add_argument("corpus")
    args = parser.parse_args(argv)
    corpus = _corpus(args.corpus)
    result = accept(corpus, runtime_module._rows)
    print(f"accepted ContentExamples animation schema 3: {corpus}")
    print(f"  animation_schema_version: {result['animation_schema_version']}")
    print(f"  mesh_physics_schema_version: {result['mesh_physics_schema_version']}")
    for key in sorted(result["counts"]):
        if key.startswith("skeletal_mesh") or key.startswith("physics_"):
            print(f"  {key}: {result['counts'][key]}")
    print(f"  expected_exact_semantic_edges: {result['expected_exact_semantic_edge_count']}")
    print("  runtime_state_captured: False")
    return 0


def _verify_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool animation-schema3-graph-verify")
    parser.add_argument("corpus")
    args = parser.parse_args(argv)
    corpus = _corpus(args.corpus)
    result = verify(corpus, runtime_module._rows)
    print(f"verified animation schema 3 derived-schema-{graph.TARGET_DERIVED_SCHEMA_VERSION} project graph: {corpus}")
    print(f"  exact_semantic_edges: {result['verified_exact_semantic_edge_count']}")
    for relation, count in sorted(result["relation_counts"].items()):
        if count:
            print(f"  {relation}: {count}")
    print("  runtime_state_captured: False")
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_animation_schema3_accept_installed", False):
        return
    try:
        import uatool_core as core
        core.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((*core.DEFAULT_BUNDLE_FILES, ACCEPTANCE_MANIFEST, GRAPH_EXPECTATIONS_MANIFEST, GRAPH_VERIFICATION_MANIFEST)))
    except Exception:
        pass
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "animation-schema3-accept":
            try:
                return _accept_cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr); return 64
        if len(sys.argv) > 1 and sys.argv[1] == "animation-schema3-graph-verify":
            try:
                return _verify_cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr); return 65
        return original_main()

    runtime_module.main = main
    runtime_module._animation_schema3_accept_installed = True
