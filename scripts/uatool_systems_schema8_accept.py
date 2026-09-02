#!/usr/bin/env python3
"""Promote accepted systems schema 8 and verify exact AI Perception graph topology."""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import sys
from pathlib import Path

import uatool_ai_perception_graph as ai_graph

ACCEPTANCE_MANIFEST = "systems_schema8_acceptance.json"
GRAPH_EXPECTATIONS_MANIFEST = "ai_perception_graph_expectations.json"
GRAPH_VERIFICATION_MANIFEST = "ai_perception_graph_verification.json"
TARGET_DERIVED_SCHEMA_VERSION = 24


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} root is not an object")
    return value


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _count_rows(root: Path, filename: str, rows) -> int:
    return sum(1 for _ in rows(Path(root) / filename))


def _graph_expectations(root: Path, rows) -> dict:
    edges = ai_graph.expected_edge_keys(root, rows)
    relation_counts = collections.Counter(relation for _, relation, _ in edges)
    raw_files = tuple(dict.fromkeys(ai_graph.RELATION_STREAMS.values()))
    raw_counts = {
        name.removesuffix(".jsonl"): _count_rows(root, name, rows)
        for name in raw_files
    }
    return {
        "schema_version": 1,
        "systems_schema_version": 8,
        "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
        "edge_quality": "exact_semantic",
        "runtime_state_captured": False,
        "raw_counts": dict(sorted(raw_counts.items())),
        "expected_relation_counts": {
            relation: int(relation_counts.get(relation, 0))
            for relation in sorted(ai_graph.RELATION_STREAMS)
        },
        "expected_exact_semantic_edge_count": len(edges),
        "expected_edges": [
            {"source": source, "relation": relation, "target": target}
            for source, relation, target in sorted(edges)
        ],
    }


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def accept_schema8(systems_module, project: Path, *, corpus: Path, systems_capture: Path) -> dict:
    if int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0) != 8:
        raise RuntimeError("systems-schema8-accept requires composed systems schema 8")

    manifest = _read_json(systems_capture / "systems_manifest.json")
    if int(manifest.get("schema_version", 0) or 0) != 8 or not bool(manifest.get("success", False)):
        raise RuntimeError("isolated systems capture is not a successful schema-8 manifest")
    error = systems_module.validation_error(systems_capture)
    if error:
        raise RuntimeError(f"isolated systems capture is not valid schema 8: {error}")

    stage = corpus / ".systems-schema8-accept-staging"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    try:
        for filename in systems_module.RAW_FILES:
            source = systems_capture / filename
            if not source.is_file():
                raise RuntimeError(f"isolated systems capture missing canonical file: {filename}")
            shutil.copy2(source, stage / filename)

        error = systems_module.validation_error(stage)
        if error:
            raise RuntimeError(f"staged systems schema 8 failed validation: {error}")

        expectations = _graph_expectations(stage, systems_module._rows)
        counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
        acceptance = {
            "acceptance_schema_version": 1,
            "systems_schema_version": 8,
            "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
            "systems_capture": str(systems_capture),
            "project": str(project),
            "runtime_state_captured": False,
            "systems_manifest_counts": counts,
            "expected_exact_semantic_edge_count": expectations["expected_exact_semantic_edge_count"],
            "expected_relation_counts": expectations["expected_relation_counts"],
        }

        corpus.mkdir(parents=True, exist_ok=True)
        for filename in systems_module.RAW_FILES:
            if filename == "systems_manifest.json":
                continue
            temp = corpus / f".{filename}.schema8-accept.tmp"
            shutil.copy2(stage / filename, temp)
            os.replace(temp, corpus / filename)
        manifest_temp = corpus / ".systems_manifest.json.schema8-accept.tmp"
        shutil.copy2(stage / "systems_manifest.json", manifest_temp)
        os.replace(manifest_temp, corpus / "systems_manifest.json")
        _write_json_atomic(corpus / GRAPH_EXPECTATIONS_MANIFEST, expectations)
        _write_json_atomic(corpus / ACCEPTANCE_MANIFEST, acceptance)

        error = systems_module.validation_error(corpus)
        if error:
            raise RuntimeError(f"promoted canonical systems schema 8 failed validation: {error}")
        return acceptance
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _verify_graph(corpus: Path, rows) -> dict:
    expectations = _read_json(corpus / GRAPH_EXPECTATIONS_MANIFEST)
    if int(expectations.get("target_derived_schema_version", 0) or 0) != TARGET_DERIVED_SCHEMA_VERSION:
        raise RuntimeError("AI Perception graph expectations target an unexpected derived schema")

    top_manifest = _read_json(corpus / "manifest.json")
    actual_version = int(top_manifest.get("derived_schema_version", 0) or 0)
    if actual_version != TARGET_DERIVED_SCHEMA_VERSION:
        raise RuntimeError(
            f"AI Perception graph verification requires derived schema {TARGET_DERIVED_SCHEMA_VERSION}; got {actual_version}"
        )

    expected = ai_graph.expected_edge_keys(corpus, rows)
    domain_relations = set(ai_graph.RELATION_STREAMS)
    project_edges = list(rows(corpus / "project_edges.jsonl"))
    actual_rows = [row for row in project_edges if str(row.get("relation", "")) in domain_relations]
    actual = {
        (str(row.get("source", "") or ""), str(row.get("relation", "") or ""), str(row.get("target", "") or ""))
        for row in actual_rows
    }
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing={len(missing)} first={missing[0]}")
        if extra:
            details.append(f"extra={len(extra)} first={extra[0]}")
        raise RuntimeError("AI Perception exact graph edge set mismatch: " + "; ".join(details))

    relation_counts = collections.Counter()
    for row in actual_rows:
        relation = str(row.get("relation", ""))
        relation_counts[relation] += 1
        if str(row.get("edge_quality", "")) != "exact_semantic":
            raise RuntimeError(f"AI Perception relation is not exact_semantic: {relation}")
        expected_stream = ai_graph.RELATION_STREAMS[relation]
        evidence = row.get("evidence", []) if isinstance(row.get("evidence", []), list) else []
        if not any(isinstance(item, dict) and str(item.get("stream", "")) == expected_stream for item in evidence):
            raise RuntimeError(f"AI Perception relation lacks canonical {expected_stream} evidence: {relation}")

    expected_counts = expectations.get("expected_relation_counts", {})
    for relation in ai_graph.RELATION_STREAMS:
        if int(expected_counts.get(relation, 0) or 0) != int(relation_counts.get(relation, 0)):
            raise RuntimeError(
                f"AI Perception relation count mismatch for {relation}: expected={expected_counts.get(relation, 0)} "
                f"actual={relation_counts.get(relation, 0)}"
            )

    expected_nodes = {
        "ai_perception_component": {
            str(row.get("component_path", "") or "")
            for row in rows(corpus / "ai_perception_components.jsonl") if row.get("component_path")
        },
        "ai_perception_sense_config": {
            str(row.get("config_path", "") or "")
            for row in rows(corpus / "ai_perception_sense_configs.jsonl") if row.get("config_path")
        },
        "ai_perception_stimuli_source": {
            str(row.get("component_path", "") or "")
            for row in rows(corpus / "ai_perception_stimuli_sources.jsonl") if row.get("component_path")
        },
    }
    project_nodes = list(rows(corpus / "project_nodes.jsonl"))
    actual_nodes: dict[str, set[str]] = collections.defaultdict(set)
    for row in project_nodes:
        actual_nodes[str(row.get("node_kind", ""))].add(str(row.get("path", "") or ""))
    for kind, paths in expected_nodes.items():
        missing = paths - actual_nodes.get(kind, set())
        if missing:
            first = sorted(missing)[0]
            raise RuntimeError(f"AI Perception graph nodes missing for {kind}: {len(missing)} first={first}")

    verification = {
        "schema_version": 1,
        "verified": True,
        "systems_schema_version": 8,
        "derived_schema_version": actual_version,
        "edge_quality": "exact_semantic",
        "expected_exact_semantic_edge_count": len(expected),
        "verified_exact_semantic_edge_count": len(actual),
        "relation_counts": {
            relation: int(relation_counts.get(relation, 0))
            for relation in sorted(ai_graph.RELATION_STREAMS)
        },
        "node_counts": {kind: len(paths) for kind, paths in sorted(expected_nodes.items())},
        "runtime_state_captured": False,
    }
    _write_json_atomic(corpus / GRAPH_VERIFICATION_MANIFEST, verification)
    return verification


def _accept_cli(systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool systems-schema8-accept",
        description="promote an accepted systems-schema-8 capture into the canonical corpus; no Unreal or derive",
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--corpus", help="canonical corpus; defaults to <Project>/.uatool")
    parser.add_argument("--systems-capture", help="capture directory; defaults to <corpus>/systems-schema8-capture")
    args = parser.parse_args(argv)
    project = _resolve_project(args.project)
    corpus = Path(args.corpus).expanduser().resolve() if args.corpus else project.parent / ".uatool"
    capture = Path(args.systems_capture).expanduser().resolve() if args.systems_capture else corpus / "systems-schema8-capture"
    result = accept_schema8(systems_module, project, corpus=corpus, systems_capture=capture)
    print(f"accepted canonical systems schema 8: {corpus}")
    print(f"acceptance manifest: {corpus / ACCEPTANCE_MANIFEST}")
    print(f"graph expectations: {corpus / GRAPH_EXPECTATIONS_MANIFEST}")
    print(f"  target_derived_schema_version: {TARGET_DERIVED_SCHEMA_VERSION}")
    print(f"  expected_exact_semantic_edges: {result['expected_exact_semantic_edge_count']}")
    for relation, count in sorted(result["expected_relation_counts"].items()):
        if count:
            print(f"    {relation}: {count}")
    print("  runtime_state_captured: False")
    print("Unreal was not run")
    print("derive was not run")
    return 0


def _verify_cli(systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool ai-perception-graph-verify",
        description="verify derived-schema-24 AI Perception graph topology against accepted systems-schema-8 facts",
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--corpus", help="canonical corpus; defaults to <Project>/.uatool")
    args = parser.parse_args(argv)
    project = _resolve_project(args.project)
    corpus = Path(args.corpus).expanduser().resolve() if args.corpus else project.parent / ".uatool"
    result = _verify_graph(corpus, systems_module._rows)
    print(f"verified AI Perception derived-schema-24 project graph: {corpus}")
    print(f"verification manifest: {corpus / GRAPH_VERIFICATION_MANIFEST}")
    print(f"  exact_semantic_edges: {result['verified_exact_semantic_edge_count']}")
    for kind, count in sorted(result["node_counts"].items()):
        print(f"  {kind}: {count}")
    print("  runtime_state_captured: False")
    return 0


def install(runtime_module, systems_module) -> None:
    if getattr(systems_module, "__name__", "") != "uatool_systems":
        return
    if getattr(runtime_module, "_systems_schema8_accept_installed", False):
        return

    try:
        import uatool_core as core_module
        core_module.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((
            *core_module.DEFAULT_BUNDLE_FILES,
            ACCEPTANCE_MANIFEST,
            GRAPH_EXPECTATIONS_MANIFEST,
            GRAPH_VERIFICATION_MANIFEST,
        )))
    except Exception:
        pass

    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "systems-schema8-accept":
            try:
                return _accept_cli(systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 51
        if len(sys.argv) > 1 and sys.argv[1] == "ai-perception-graph-verify":
            try:
                return _verify_cli(systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 52
        return original_main()

    runtime_module.main = main
    runtime_module._systems_schema8_accept_installed = True
