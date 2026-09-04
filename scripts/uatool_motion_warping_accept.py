#!/usr/bin/env python3
"""Real-corpus acceptance and exact graph verification for animation schema 4 Motion Warping."""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

import uatool_motion_warping_schema as schema
import uatool_motion_warping_graph as graph
import uatool_motion_warping_model as model

ACCEPTANCE_MANIFEST = "animation_schema4_motion_warping_acceptance.json"
GRAPH_EXPECTATIONS_MANIFEST = "animation_schema4_motion_warping_graph_expectations.json"
GRAPH_VERIFICATION_MANIFEST = "animation_schema4_motion_warping_graph_verification.json"

REPRESENTATIVE_EXACT_COUNTS = {
    "motion_warping_windows": 145,
    "motion_warping_modifiers": 145,
    "motion_warping_modifier_properties": 2565,
    "motion_warping_skew_warp_modifiers": 135,
    "motion_warping_precomputed_warp_modifiers": 10,
    "motion_warping_unique_target_names": 4,
}

REPRESENTATIVE_RELATION_COUNTS = {
    "animation_asset_has_motion_warping_window": 145,
    "motion_warping_window_owns_modifier": 145,
    "motion_warping_modifier_targets_name": 145,
    "motion_warping_modifier_uses_warp_point_bone_name": 105,
    "motion_warping_modifier_uses_easing_curve": 0,
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
    manifest = _read_json(corpus / schema.MANIFEST_FILE)
    counts = manifest.get("counts", {})
    if not isinstance(counts, dict):
        raise RuntimeError("Motion Warping manifest counts missing or invalid")
    return {str(key): int(value or 0) for key, value in counts.items()}


def _expectations(corpus: Path, rows) -> dict:
    data = model.build_model(corpus, rows)
    edges = {(spec["source"], spec["relation"], spec["target"]) for spec in data["edge_specs"]}
    relation_counts = collections.Counter(relation for _, relation, _ in edges)
    return {
        "schema_version": 1,
        "animation_schema_version": schema.PUBLIC_ANIMATION_SCHEMA_VERSION,
        "motion_warping_schema_version": schema.MOTION_WARPING_SCHEMA_VERSION,
        "target_derived_schema_version": graph.TARGET_DERIVED_SCHEMA_VERSION,
        "edge_quality": "exact_semantic",
        "runtime_state_captured": False,
        "expected_exact_semantic_edge_count": len(edges),
        "expected_relation_counts": {
            relation: int(relation_counts.get(relation, 0))
            for relation in sorted(model.RELATIONS)
        },
        "expected_edges": [
            {"source": source, "relation": relation, "target": target}
            for source, relation, target in sorted(edges)
        ],
    }


def _require_representative_shape(corpus: Path, rows) -> dict[str, int]:
    error = schema.validation_error(corpus, require_present=True)
    if error:
        raise RuntimeError(f"animation schema 4 Motion Warping corpus invalid: {error}")
    counts = _counts(corpus)
    mismatches = [
        f"{key}={counts.get(key,0)} expected={expected}"
        for key, expected in REPRESENTATIVE_EXACT_COUNTS.items()
        if int(counts.get(key, 0)) != expected
    ]
    if mismatches:
        raise RuntimeError("GASP Motion Warping representative corpus changed: " + ", ".join(mismatches))

    windows = list(rows(corpus / "motion_warping_windows.jsonl"))
    modifiers = list(rows(corpus / "motion_warping_modifiers.jsonl"))
    properties = list(rows(corpus / "motion_warping_modifier_properties.jsonl"))
    if len({str(row.get("asset_path", "")) for row in windows}) != 72:
        raise RuntimeError("GASP Motion Warping representative asset count must be 72")
    if {str(row.get("asset_class", "")) for row in windows} != {"/Script/Engine.AnimMontage"}:
        raise RuntimeError("GASP Motion Warping representative windows must all be AnimMontage")
    if {str(row.get("warp_target_name", "")) for row in modifiers} != {
        "FrontLedge", "BackFloor", "BackLedge", "SmartObject"
    }:
        raise RuntimeError("GASP Motion Warping representative target-name vocabulary changed")
    if not any(str(row.get("property_name", "")) == "TranslationWarpingCurve" for row in properties):
        raise RuntimeError("PrecomputedWarp translation curve evidence missing")
    if not any(str(row.get("property_name", "")) == "SteeringSettings" for row in properties):
        raise RuntimeError("PrecomputedWarp steering settings evidence missing")
    sidecar = _read_json(corpus / schema.MANIFEST_FILE)
    for flag in (
        "runtime_state_captured", "live_warp_targets_captured",
        "active_root_motion_modifiers_captured", "root_motion_evaluated",
        "maps_loaded", "motion_warping_module_linked",
    ):
        if bool(sidecar.get(flag, True)):
            raise RuntimeError(f"authored-only boundary violated: {flag}=true")
    return counts


def accept(corpus: Path, rows) -> dict:
    counts = _require_representative_shape(corpus, rows)
    expectations = _expectations(corpus, rows)
    if int(expectations["expected_exact_semantic_edge_count"]) != 540:
        raise RuntimeError(
            "GASP Motion Warping graph expectation changed: "
            f"{expectations['expected_exact_semantic_edge_count']} expected=540"
        )
    relation_counts = expectations["expected_relation_counts"]
    for relation, expected in REPRESENTATIVE_RELATION_COUNTS.items():
        if int(relation_counts.get(relation, 0)) != expected:
            raise RuntimeError(
                f"GASP Motion Warping relation expectation changed for {relation}: "
                f"{relation_counts.get(relation,0)} expected={expected}"
            )

    top = _read_json(corpus / "manifest.json")
    result = {
        "acceptance_schema_version": 1,
        "animation_schema_version": schema.PUBLIC_ANIMATION_SCHEMA_VERSION,
        "motion_warping_schema_version": schema.MOTION_WARPING_SCHEMA_VERSION,
        "structural_schema_version": int(top.get("schema_version", 0) or 0),
        "world_schema_version": int(top.get("world_schema_version", 0) or 0),
        "target_derived_schema_version": graph.TARGET_DERIVED_SCHEMA_VERSION,
        "representative_content": "Game Animation Sample UE 5.8.2 authored Motion Warping",
        "canonical_pass": "UnrealAssetToolMotionWarping",
        "runtime_state_captured": False,
        "live_warp_targets_captured": False,
        "active_root_motion_modifiers_captured": False,
        "root_motion_evaluated": False,
        "maps_loaded": False,
        "motion_warping_module_linked": False,
        "counts": counts,
        "expected_relation_counts": relation_counts,
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
        raise RuntimeError(
            f"Motion Warping graph verification requires derived schema "
            f"{graph.TARGET_DERIVED_SCHEMA_VERSION}; got {actual_version}"
        )

    expected = model.expected_edge_keys(corpus, rows)
    project_path = corpus / "project_edges.jsonl"
    if not project_path.is_file():
        raise RuntimeError("project_edges.jsonl missing; run derive first")
    actual_rows = [
        row for row in rows(project_path)
        if str(row.get("relation", "")) in model.RELATIONS
    ]
    actual = {
        (str(row.get("source", "")), str(row.get("relation", "")), str(row.get("target", "")))
        for row in actual_rows
    }
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        parts = []
        if missing:
            parts.append(f"missing={len(missing)} first={missing[0]}")
        if extra:
            parts.append(f"extra={len(extra)} first={extra[0]}")
        raise RuntimeError("Motion Warping exact graph edge set mismatch: " + "; ".join(parts))

    relation_counts = collections.Counter()
    for row in actual_rows:
        relation = str(row.get("relation", ""))
        relation_counts[relation] += 1
        if str(row.get("edge_quality", "")) != "exact_semantic":
            raise RuntimeError(f"Motion Warping relation is not exact_semantic: {relation}")
        expected_stream = model.RELATION_STREAMS[relation]
        evidence = row.get("evidence", []) if isinstance(row.get("evidence", []), list) else []
        if not any(
            isinstance(item, dict)
            and str(item.get("stream", "")) == expected_stream
            and str(item.get("quality", "")) == "exact_semantic"
            for item in evidence
        ):
            raise RuntimeError(f"Motion Warping relation lacks canonical evidence stream: {relation}")

    expected_counts = expectations.get("expected_relation_counts", {})
    for relation in sorted(model.RELATIONS):
        if int(expected_counts.get(relation, 0) or 0) != int(relation_counts.get(relation, 0)):
            raise RuntimeError(
                f"Motion Warping relation count mismatch for {relation}: "
                f"expected={expected_counts.get(relation,0)} actual={relation_counts.get(relation,0)}"
            )

    result = {
        "schema_version": 1,
        "verified": True,
        "animation_schema_version": schema.PUBLIC_ANIMATION_SCHEMA_VERSION,
        "motion_warping_schema_version": schema.MOTION_WARPING_SCHEMA_VERSION,
        "derived_schema_version": actual_version,
        "edge_quality": "exact_semantic",
        "verified_exact_semantic_edge_count": len(actual),
        "relation_counts": {
            relation: int(relation_counts.get(relation, 0))
            for relation in sorted(model.RELATIONS)
        },
        "runtime_state_captured": False,
    }
    _write_json(corpus / GRAPH_VERIFICATION_MANIFEST, result)
    return result


def _promote_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool motion-warping-schema4-promote")
    parser.add_argument("corpus")
    parser.add_argument(
        "--capture",
        help="focused motion-warping-native-capture directory; defaults to <corpus>/motion-warping-native-capture",
    )
    args = parser.parse_args(argv)
    corpus = _corpus(args.corpus)
    capture_dir = (
        Path(args.capture).expanduser().resolve()
        if args.capture else corpus / "motion-warping-native-capture"
    )
    result = schema.promote_capture(corpus, capture_dir)
    print(f"promoted focused Motion Warping capture to animation schema 4: {corpus}")
    for key in sorted(result["counts"]):
        print(f"  {key}: {result['counts'][key]}")
    print("  runtime_state_captured: False")
    print("  root_motion_evaluated: False")
    return 0


def _accept_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool animation-schema4-accept")
    parser.add_argument("corpus")
    args = parser.parse_args(argv)
    corpus = _corpus(args.corpus)
    result = accept(corpus, runtime_module._rows)
    print(f"accepted GASP animation schema 4 Motion Warping corpus: {corpus}")
    print(f"  animation_schema_version: {result['animation_schema_version']}")
    print(f"  motion_warping_schema_version: {result['motion_warping_schema_version']}")
    for key in sorted(result["counts"]):
        if key.startswith("motion_warping_"):
            print(f"  {key}: {result['counts'][key]}")
    print(f"  expected_exact_semantic_edges: {result['expected_exact_semantic_edge_count']}")
    print("  runtime_state_captured: False")
    return 0


def _verify_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool animation-schema4-graph-verify")
    parser.add_argument("corpus")
    args = parser.parse_args(argv)
    corpus = _corpus(args.corpus)
    result = verify(corpus, runtime_module._rows)
    print(
        f"verified animation schema 4 derived-schema-{graph.TARGET_DERIVED_SCHEMA_VERSION} "
        f"Motion Warping project graph: {corpus}"
    )
    print(f"  exact_semantic_edges: {result['verified_exact_semantic_edge_count']}")
    for relation, count in sorted(result["relation_counts"].items()):
        print(f"  {relation}: {count}")
    print("  runtime_state_captured: False")
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_motion_warping_schema4_accept_installed", False):
        return
    try:
        import uatool_core as core
        core.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((
            *core.DEFAULT_BUNDLE_FILES,
            ACCEPTANCE_MANIFEST,
            GRAPH_EXPECTATIONS_MANIFEST,
            GRAPH_VERIFICATION_MANIFEST,
        )))
    except Exception:
        pass
    original_main = runtime_module.main

    def main():
        command = sys.argv[1] if len(sys.argv) > 1 else ""
        try:
            if command == "motion-warping-schema4-promote":
                return _promote_cli(runtime_module, sys.argv[2:])
            if command == "animation-schema4-accept":
                return _accept_cli(runtime_module, sys.argv[2:])
            if command == "animation-schema4-graph-verify":
                return _verify_cli(runtime_module, sys.argv[2:])
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 72
        return original_main()

    runtime_module.main = main
    runtime_module._motion_warping_schema4_accept_installed = True
