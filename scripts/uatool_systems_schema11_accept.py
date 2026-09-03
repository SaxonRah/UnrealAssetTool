#!/usr/bin/env python3
"""Accept systems schema 11 authored Navigation evidence and verify derived schema 27."""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import sys
from pathlib import Path

import uatool_navigation_graph as navigation_graph

ACCEPTANCE_MANIFEST = "systems_schema11_acceptance.json"
GRAPH_EXPECTATIONS_MANIFEST = "navigation_graph_expectations.json"
GRAPH_VERIFICATION_MANIFEST = "navigation_graph_verification.json"
TARGET_DERIVED_SCHEMA_VERSION = 27


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} root is not an object")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def _expectations(root: Path, rows) -> dict:
    edges = navigation_graph.expected_edge_keys(root, rows)
    relation_counts = collections.Counter(relation for _, relation, _ in edges)
    return {
        "schema_version": 1,
        "systems_schema_version": 11,
        "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
        "edge_quality": "exact_semantic",
        "runtime_state_captured": False,
        "generated_navmesh_instances_captured": False,
        "expected_relation_counts": {
            relation: int(relation_counts.get(relation, 0))
            for relation in sorted(navigation_graph.RELATION_STREAMS)
        },
        "expected_exact_semantic_edge_count": len(edges),
        "expected_edges": [
            {"source": source, "relation": relation, "target": target}
            for source, relation, target in sorted(edges)
        ],
    }


def accept_schema11(systems_module, project: Path, capture: Path, corpus: Path) -> dict:
    if int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0) != 11:
        raise RuntimeError("systems-schema11-accept requires composed systems schema 11")
    manifest = _read_json(capture / "systems_manifest.json")
    if int(manifest.get("schema_version", 0) or 0) != 11 or not bool(manifest.get("success", False)):
        raise RuntimeError("isolated Navigation systems capture is not a successful schema-11 manifest")
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    if int(counts.get("navigation_truncated_values", -1)) != 0:
        raise RuntimeError(
            f"Navigation schema-11 acceptance requires zero truncation; got {counts.get('navigation_truncated_values')}"
        )
    if int(counts.get("navigation_missing_expected_classes", -1)) != 0:
        raise RuntimeError(
            "Navigation schema-11 acceptance requires all expected UE 5.8 classes; "
            f"got missing={counts.get('navigation_missing_expected_classes')}"
        )
    required_minimums = {
        "navigation_areas": 7,
        "navigation_area_agent_mappings": 16,
        "navigation_systems": 2,
        "navigation_agents": 1,
        "navigation_link_defaults": 2,
        "navigation_modifier_defaults": 2,
        "navigation_invoker_defaults": 1,
        "navigation_bounds_defaults": 1,
        "navigation_recast_defaults": 1,
    }
    incomplete = [
        f"{key}<{minimum}"
        for key, minimum in required_minimums.items()
        if int(counts.get(key, 0) or 0) < minimum
    ]
    if incomplete:
        raise RuntimeError("Navigation schema-11 representative capture is incomplete: " + ", ".join(incomplete))
    error = systems_module.validation_error(capture)
    if error:
        raise RuntimeError(f"isolated Navigation systems capture failed schema-11 validation: {error}")

    if corpus.exists():
        shutil.rmtree(corpus)
    corpus.mkdir(parents=True, exist_ok=True)
    for filename in systems_module.RAW_FILES:
        source = capture / filename
        if not source.is_file():
            raise RuntimeError(f"Navigation schema-11 capture missing canonical file: {filename}")
        shutil.copy2(source, corpus / filename)
    error = systems_module.validation_error(corpus)
    if error:
        raise RuntimeError(f"promoted Navigation systems corpus failed validation: {error}")

    expectations = _expectations(corpus, systems_module._rows)
    if expectations["expected_exact_semantic_edge_count"] <= 0:
        raise RuntimeError("Navigation schema-11 acceptance produced no exact semantic graph edges")
    acceptance = {
        "acceptance_schema_version": 1,
        "systems_schema_version": 11,
        "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
        "project": str(project),
        "systems_capture": str(capture),
        "partial_corpus": True,
        "canonical_passes": ["systems"],
        "representative_content": "UE 5.8.2 native Navigation/AIModule authored defaults and ContentExamples project-applied config",
        "runtime_state_captured": False,
        "generated_navmesh_instances_captured": False,
        "generated_navmesh_promoted": False,
        "world_placement_authority": "world schema 12",
        "expected_exact_semantic_edge_count": expectations["expected_exact_semantic_edge_count"],
        "expected_relation_counts": expectations["expected_relation_counts"],
        "systems_manifest_counts": counts,
    }
    _write_json(corpus / ACCEPTANCE_MANIFEST, acceptance)
    _write_json(corpus / GRAPH_EXPECTATIONS_MANIFEST, expectations)
    _write_json(corpus / "manifest.json", {
        "schema_version": 0,
        "schema_name": "partial_canonical_corpus",
        "success": True,
        "partial_corpus": True,
        "canonical_passes": ["systems"],
        "systems_schema_version": 11,
        "systems_counts": counts,
        "systems_files": manifest.get("files", []),
        "systems_pass": manifest.get("pass", "UnrealAssetToolSystems"),
        "runtime_state_captured": False,
        "generated_navmesh_instances_captured": False,
    })
    return acceptance


def _verify(corpus: Path, rows) -> dict:
    expectations = _read_json(corpus / GRAPH_EXPECTATIONS_MANIFEST)
    top = _read_json(corpus / "manifest.json")
    actual_version = int(top.get("derived_schema_version", 0) or 0)
    if actual_version != TARGET_DERIVED_SCHEMA_VERSION:
        raise RuntimeError(
            f"Navigation graph verification requires derived schema {TARGET_DERIVED_SCHEMA_VERSION}; got {actual_version}"
        )
    expected = navigation_graph.expected_edge_keys(corpus, rows)
    domain = set(navigation_graph.RELATION_STREAMS)
    project_edges = list(rows(corpus / "project_edges.jsonl"))
    actual_rows = [row for row in project_edges if str(row.get("relation", "") or "") in domain]
    actual = {
        (str(row.get("source", "") or ""), str(row.get("relation", "") or ""), str(row.get("target", "") or ""))
        for row in actual_rows
    }
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append(f"missing={len(missing)} first={missing[0]}")
        if extra:
            detail.append(f"extra={len(extra)} first={extra[0]}")
        raise RuntimeError("Navigation exact graph edge set mismatch: " + "; ".join(detail))

    counts = collections.Counter()
    for row in actual_rows:
        relation = str(row.get("relation", "") or "")
        counts[relation] += 1
        if str(row.get("edge_quality", "") or "") != "exact_semantic":
            raise RuntimeError(f"Navigation relation is not exact_semantic: {relation}")
        stream = navigation_graph.RELATION_STREAMS[relation]
        evidence = row.get("evidence", []) if isinstance(row.get("evidence", []), list) else []
        if not any(isinstance(item, dict) and str(item.get("stream", "")) == stream for item in evidence):
            raise RuntimeError(f"Navigation relation lacks canonical {stream} evidence: {relation}")

    expected_counts = expectations.get("expected_relation_counts", {})
    for relation in navigation_graph.RELATION_STREAMS:
        if int(expected_counts.get(relation, 0) or 0) != int(counts.get(relation, 0)):
            raise RuntimeError(
                f"Navigation relation count mismatch for {relation}: "
                f"expected={expected_counts.get(relation,0)} actual={counts.get(relation,0)}"
            )
    result = {
        "schema_version": 1,
        "verified": True,
        "systems_schema_version": 11,
        "derived_schema_version": actual_version,
        "edge_quality": "exact_semantic",
        "expected_exact_semantic_edge_count": len(expected),
        "verified_exact_semantic_edge_count": len(actual),
        "relation_counts": {
            relation: int(counts.get(relation, 0))
            for relation in sorted(navigation_graph.RELATION_STREAMS)
        },
        "runtime_state_captured": False,
        "generated_navmesh_instances_captured": False,
        "generated_navmesh_promoted": False,
    }
    _write_json(corpus / GRAPH_VERIFICATION_MANIFEST, result)
    return result


def _accept_cli(systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool systems-schema11-accept")
    parser.add_argument("project", help="host .uproject")
    parser.add_argument("--systems-capture", help="defaults to <project>/.uatool/systems-schema11-capture")
    parser.add_argument("--corpus", help="defaults to <project>/.uatool-navigation-acceptance")
    args = parser.parse_args(argv)
    project = _resolve_project(args.project)
    capture = Path(args.systems_capture).expanduser().resolve() if args.systems_capture else project.parent / ".uatool" / "systems-schema11-capture"
    corpus = Path(args.corpus).expanduser().resolve() if args.corpus else project.parent / ".uatool-navigation-acceptance"
    result = accept_schema11(systems_module, project, capture, corpus)
    print(f"accepted canonical Navigation systems schema 11: {corpus}")
    print(f"acceptance manifest: {corpus / ACCEPTANCE_MANIFEST}")
    print(f"graph expectations: {corpus / GRAPH_EXPECTATIONS_MANIFEST}")
    print(f"  target_derived_schema_version: {TARGET_DERIVED_SCHEMA_VERSION}")
    print(f"  expected_exact_semantic_edges: {result['expected_exact_semantic_edge_count']}")
    for relation, count in sorted(result["expected_relation_counts"].items()):
        if count:
            print(f"    {relation}: {count}")
    print("  partial_corpus: True")
    print("  runtime_state_captured: False")
    print("  generated_navmesh_instances_captured: False")
    print("  world_placement_authority: world schema 12")
    print("Unreal was not run")
    print("derive was not run")
    return 0


def _verify_cli(systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool navigation-graph-verify")
    parser.add_argument("project", help="host .uproject")
    parser.add_argument("--corpus", help="defaults to <project>/.uatool-navigation-acceptance")
    args = parser.parse_args(argv)
    project = _resolve_project(args.project)
    corpus = Path(args.corpus).expanduser().resolve() if args.corpus else project.parent / ".uatool-navigation-acceptance"
    result = _verify(corpus, systems_module._rows)
    print(f"verified Navigation derived-schema-27 project graph: {corpus}")
    print(f"verification manifest: {corpus / GRAPH_VERIFICATION_MANIFEST}")
    print(f"  exact_semantic_edges: {result['verified_exact_semantic_edge_count']}")
    for relation, count in sorted(result["relation_counts"].items()):
        if count:
            print(f"  {relation}: {count}")
    print("  runtime_state_captured: False")
    print("  generated_navmesh_instances_captured: False")
    return 0


def install(runtime_module, systems_module) -> None:
    if getattr(runtime_module, "_systems_schema11_accept_installed", False):
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
    try:
        import uatool_systems_schema6_accept as schema6
        old_accept = schema6._accepted_systems_only_corpus

        def accepted(output):
            if old_accept(output):
                return True
            root = Path(output).expanduser().resolve()
            try:
                acceptance = _read_json(root / ACCEPTANCE_MANIFEST)
                systems_manifest = _read_json(root / "systems_manifest.json")
            except RuntimeError:
                return False
            return (
                int(acceptance.get("systems_schema_version", 0) or 0) == 11
                and int(acceptance.get("target_derived_schema_version", 0) or 0) == TARGET_DERIVED_SCHEMA_VERSION
                and int(systems_manifest.get("schema_version", 0) or 0) == 11
                and bool(systems_manifest.get("success", False))
            )

        schema6._accepted_systems_only_corpus = accepted
    except Exception:
        pass

    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "systems-schema11-accept":
            try:
                return _accept_cli(systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 57
        if len(sys.argv) > 1 and sys.argv[1] == "navigation-graph-verify":
            try:
                return _verify_cli(systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 58
        return original_main()

    runtime_module.main = main
    runtime_module._systems_schema11_accept_installed = True
