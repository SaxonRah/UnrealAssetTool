#!/usr/bin/env python3
"""Accept systems schema 10 UAF evidence and verify derived schema 26."""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import sys
from pathlib import Path

import uatool_uaf_graph as uaf_graph

ACCEPTANCE_MANIFEST = "systems_schema10_acceptance.json"
GRAPH_EXPECTATIONS_MANIFEST = "uaf_graph_expectations.json"
GRAPH_VERIFICATION_MANIFEST = "uaf_graph_verification.json"
TARGET_DERIVED_SCHEMA_VERSION = 26


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
    edges = uaf_graph.expected_edge_keys(root, rows)
    relation_counts = collections.Counter(relation for _, relation, _ in edges)
    return {
        "schema_version": 1,
        "systems_schema_version": 10,
        "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
        "edge_quality": "exact_semantic",
        "runtime_state_captured": False,
        "expected_relation_counts": {r: int(relation_counts.get(r, 0)) for r in sorted(uaf_graph.RELATION_STREAMS)},
        "expected_exact_semantic_edge_count": len(edges),
        "expected_edges": [
            {"source": s, "relation": r, "target": t} for s, r, t in sorted(edges)
        ],
    }


def accept_schema10(systems_module, project: Path, capture: Path, corpus: Path) -> dict:
    if int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0) != 10:
        raise RuntimeError("systems-schema10-accept requires composed systems schema 10")
    manifest = _read_json(capture / "systems_manifest.json")
    if int(manifest.get("schema_version", 0) or 0) != 10 or not bool(manifest.get("success", False)):
        raise RuntimeError("isolated UAF systems capture is not a successful schema-10 manifest")
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    if int(counts.get("uaf_truncated_values", -1)) != 0:
        raise RuntimeError(f"UAF schema-10 acceptance requires zero truncation; got {counts.get('uaf_truncated_values')}")
    required = ("uaf_assets","uaf_entries","uaf_variables","uaf_components","uaf_entry_points","uaf_rigvm_graphs","uaf_rigvm_nodes","uaf_rigvm_pins","uaf_rigvm_links","uaf_variable_usages")
    missing = [key for key in required if int(counts.get(key, 0) or 0) <= 0]
    if missing:
        raise RuntimeError("UAF schema-10 representative capture is incomplete: " + ", ".join(missing))
    error = systems_module.validation_error(capture)
    if error:
        raise RuntimeError(f"isolated UAF systems capture failed schema-10 validation: {error}")

    if corpus.exists(): shutil.rmtree(corpus)
    corpus.mkdir(parents=True, exist_ok=True)
    for filename in systems_module.RAW_FILES:
        source = capture / filename
        if not source.is_file():
            raise RuntimeError(f"UAF schema-10 capture missing canonical file: {filename}")
        shutil.copy2(source, corpus / filename)
    error = systems_module.validation_error(corpus)
    if error:
        raise RuntimeError(f"promoted UAF systems corpus failed validation: {error}")

    expectations = _expectations(corpus, systems_module._rows)
    acceptance = {
        "acceptance_schema_version": 1,
        "systems_schema_version": 10,
        "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
        "project": str(project),
        "systems_capture": str(capture),
        "partial_corpus": True,
        "canonical_passes": ["systems"],
        "representative_content": "installed UE 5.8 UAF/UAFAnimGraph plugin assets",
        "runtime_state_captured": False,
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
        "systems_schema_version": 10,
        "systems_counts": counts,
        "systems_files": manifest.get("files", []),
        "systems_pass": manifest.get("pass", "UnrealAssetToolSystems"),
    })
    return acceptance


def _verify(corpus: Path, rows) -> dict:
    expectations = _read_json(corpus / GRAPH_EXPECTATIONS_MANIFEST)
    top = _read_json(corpus / "manifest.json")
    actual_version = int(top.get("derived_schema_version", 0) or 0)
    if actual_version != TARGET_DERIVED_SCHEMA_VERSION:
        raise RuntimeError(f"UAF graph verification requires derived schema {TARGET_DERIVED_SCHEMA_VERSION}; got {actual_version}")
    expected = uaf_graph.expected_edge_keys(corpus, rows)
    domain = set(uaf_graph.RELATION_STREAMS)
    project_edges = list(rows(corpus / "project_edges.jsonl"))
    actual_rows = [r for r in project_edges if str(r.get("relation", "") or "") in domain]
    actual = {(str(r.get("source", "") or ""), str(r.get("relation", "") or ""), str(r.get("target", "") or "")) for r in actual_rows}
    if actual != expected:
        missing = sorted(expected - actual); extra = sorted(actual - expected)
        detail = []
        if missing: detail.append(f"missing={len(missing)} first={missing[0]}")
        if extra: detail.append(f"extra={len(extra)} first={extra[0]}")
        raise RuntimeError("UAF exact graph edge set mismatch: " + "; ".join(detail))
    counts = collections.Counter()
    for row in actual_rows:
        relation = str(row.get("relation", "") or "")
        counts[relation] += 1
        if str(row.get("edge_quality", "") or "") != "exact_semantic":
            raise RuntimeError(f"UAF relation is not exact_semantic: {relation}")
        stream = uaf_graph.RELATION_STREAMS[relation]
        evidence = row.get("evidence", []) if isinstance(row.get("evidence", []), list) else []
        if not any(isinstance(x, dict) and str(x.get("stream", "")) == stream for x in evidence):
            raise RuntimeError(f"UAF relation lacks canonical {stream} evidence: {relation}")
    expected_counts = expectations.get("expected_relation_counts", {})
    for relation in uaf_graph.RELATION_STREAMS:
        if int(expected_counts.get(relation, 0) or 0) != int(counts.get(relation, 0)):
            raise RuntimeError(f"UAF relation count mismatch for {relation}: expected={expected_counts.get(relation,0)} actual={counts.get(relation,0)}")
    result = {
        "schema_version": 1, "verified": True, "systems_schema_version": 10,
        "derived_schema_version": actual_version, "edge_quality": "exact_semantic",
        "expected_exact_semantic_edge_count": len(expected), "verified_exact_semantic_edge_count": len(actual),
        "relation_counts": {r: int(counts.get(r, 0)) for r in sorted(uaf_graph.RELATION_STREAMS)},
        "runtime_state_captured": False,
    }
    _write_json(corpus / GRAPH_VERIFICATION_MANIFEST, result)
    return result


def _accept_cli(systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool systems-schema10-accept")
    parser.add_argument("project", help="host .uproject")
    parser.add_argument("--systems-capture", help="defaults to <project>/.uatool/uaf-systems-schema10-capture")
    parser.add_argument("--corpus", help="defaults to <project>/.uatool-uaf-acceptance")
    args = parser.parse_args(argv)
    project = _resolve_project(args.project)
    capture = Path(args.systems_capture).expanduser().resolve() if args.systems_capture else project.parent / ".uatool" / "uaf-systems-schema10-capture"
    corpus = Path(args.corpus).expanduser().resolve() if args.corpus else project.parent / ".uatool-uaf-acceptance"
    result = accept_schema10(systems_module, project, capture, corpus)
    print(f"accepted canonical UAF systems schema 10: {corpus}")
    print(f"acceptance manifest: {corpus / ACCEPTANCE_MANIFEST}")
    print(f"graph expectations: {corpus / GRAPH_EXPECTATIONS_MANIFEST}")
    print(f"  target_derived_schema_version: {TARGET_DERIVED_SCHEMA_VERSION}")
    print(f"  expected_exact_semantic_edges: {result['expected_exact_semantic_edge_count']}")
    for relation, count in sorted(result["expected_relation_counts"].items()):
        if count: print(f"    {relation}: {count}")
    print("  partial_corpus: True")
    print("  runtime_state_captured: False")
    print("Unreal was not run")
    print("derive was not run")
    return 0


def _verify_cli(systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool uaf-graph-verify")
    parser.add_argument("project", help="host .uproject")
    parser.add_argument("--corpus", help="defaults to <project>/.uatool-uaf-acceptance")
    args = parser.parse_args(argv)
    project = _resolve_project(args.project)
    corpus = Path(args.corpus).expanduser().resolve() if args.corpus else project.parent / ".uatool-uaf-acceptance"
    result = _verify(corpus, systems_module._rows)
    print(f"verified UAF derived-schema-26 project graph: {corpus}")
    print(f"verification manifest: {corpus / GRAPH_VERIFICATION_MANIFEST}")
    print(f"  exact_semantic_edges: {result['verified_exact_semantic_edge_count']}")
    for relation, count in sorted(result["relation_counts"].items()):
        if count: print(f"  {relation}: {count}")
    print("  runtime_state_captured: False")
    return 0


def install(runtime_module, systems_module) -> None:
    if getattr(runtime_module, "_systems_schema10_accept_installed", False): return
    try:
        import uatool_core as core
        core.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((*core.DEFAULT_BUNDLE_FILES, ACCEPTANCE_MANIFEST, GRAPH_EXPECTATIONS_MANIFEST, GRAPH_VERIFICATION_MANIFEST)))
    except Exception:
        pass
    # Extend the established systems-only derive gate to recognize the newer
    # accepted partial systems corpus without weakening schema-6 behavior.
    try:
        import uatool_systems_schema6_accept as schema6
        old_accept = schema6._accepted_systems_only_corpus
        def accepted(output):
            if old_accept(output): return True
            root = Path(output).expanduser().resolve()
            try:
                a = _read_json(root / ACCEPTANCE_MANIFEST); s = _read_json(root / "systems_manifest.json")
            except RuntimeError:
                return False
            return int(a.get("systems_schema_version",0) or 0) == 10 and int(a.get("target_derived_schema_version",0) or 0) == TARGET_DERIVED_SCHEMA_VERSION and int(s.get("schema_version",0) or 0) == 10 and bool(s.get("success",False))
        schema6._accepted_systems_only_corpus = accepted
    except Exception:
        pass
    original_main = runtime_module.main
    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "systems-schema10-accept":
            try: return _accept_cli(systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr); return 55
        if len(sys.argv) > 1 and sys.argv[1] == "uaf-graph-verify":
            try: return _verify_cli(systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr); return 56
        return original_main()
    runtime_module.main = main
    runtime_module._systems_schema10_accept_installed = True
