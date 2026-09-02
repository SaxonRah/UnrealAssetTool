#!/usr/bin/env python3
"""Promote accepted systems schema 6 and verify exact GAS graph topology."""
from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import sys
from pathlib import Path

import uatool_gas_graph as gas_graph

ACCEPTANCE_MANIFEST = "systems_schema6_acceptance.json"
GRAPH_EXPECTATIONS_MANIFEST = "gas_graph_expectations.json"
GRAPH_VERIFICATION_MANIFEST = "gas_graph_verification.json"
TARGET_DERIVED_SCHEMA_VERSION = 22


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


def _rows_list(root: Path, filename: str, rows) -> list[dict]:
    return list(rows(Path(root) / filename))


def _count_rows(root: Path, filename: str, rows) -> int:
    return sum(1 for _ in rows(Path(root) / filename))


def _graph_expectations(root: Path, rows) -> dict:
    edges = gas_graph.expected_edge_keys(root, rows)
    relation_counts = collections.Counter(relation for _, relation, _ in edges)
    raw_counts = {
        name.removesuffix(".jsonl"): _count_rows(root, name, rows)
        for name in gas_graph.RELATION_STREAMS.values()
    }
    return {
        "schema_version": 1,
        "systems_schema_version": 6,
        "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
        "edge_quality": "exact_semantic",
        "runtime_state_captured": False,
        "raw_counts": dict(sorted(raw_counts.items())),
        "expected_relation_counts": {
            relation: int(relation_counts.get(relation, 0))
            for relation in sorted(gas_graph.RELATION_STREAMS)
        },
        "expected_exact_semantic_edge_count": len(edges),
        "expected_edges": [
            {"source": source, "relation": relation, "target": target}
            for source, relation, target in sorted(edges)
        ],
    }


def _promote_composed_derived_schema_version() -> None:
    try:
        import uatool_project_graph as project_graph_module
        project_graph_module.DERIVED_SCHEMA_VERSION = max(
            int(getattr(project_graph_module, "DERIVED_SCHEMA_VERSION", 0) or 0),
            TARGET_DERIVED_SCHEMA_VERSION,
        )
    except Exception:
        pass

    target = Path(__file__).with_name("uatool.py").resolve()
    for module in tuple(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if not module_file or not hasattr(module, "FINAL_DERIVED_SCHEMA_VERSION"):
            continue
        try:
            if Path(module_file).resolve() != target:
                continue
        except (OSError, RuntimeError, TypeError):
            continue
        current = int(getattr(module, "FINAL_DERIVED_SCHEMA_VERSION", 0) or 0)
        if current < TARGET_DERIVED_SCHEMA_VERSION:
            setattr(module, "FINAL_DERIVED_SCHEMA_VERSION", TARGET_DERIVED_SCHEMA_VERSION)


def _accepted_systems_only_corpus(output: Path) -> bool:
    output = Path(output).expanduser().resolve()
    acceptance_path = output / ACCEPTANCE_MANIFEST
    systems_path = output / "systems_manifest.json"
    if not acceptance_path.is_file() or not systems_path.is_file():
        return False
    try:
        acceptance = _read_json(acceptance_path)
        systems_manifest = _read_json(systems_path)
    except RuntimeError:
        return False
    return (
        int(acceptance.get("systems_schema_version", 0) or 0) == 6
        and int(acceptance.get("target_derived_schema_version", 0) or 0) == TARGET_DERIVED_SCHEMA_VERSION
        and int(systems_manifest.get("schema_version", 0) or 0) == 6
        and bool(systems_manifest.get("success", False))
    )


def _vfx_raw_present(output: Path, vfx_module) -> bool:
    output = Path(output).expanduser().resolve()
    for filename in tuple(getattr(vfx_module, "RAW_FILES", ())):
        if filename == "vfx_manifest.json":
            continue
        if (output / filename).is_file():
            return True
    return False


def _ensure_partial_top_manifest(output: Path) -> bool:
    """Create an honest top manifest for an accepted focused systems corpus.

    The focused schema-6 promotion intentionally does not run the structural,
    world, animation, or VFX scanners. Derived graph code still needs a top
    manifest as its commit marker. Do not claim a structural scanner schema;
    record the corpus as partial and name the only canonical pass explicitly.
    """
    output = Path(output).expanduser().resolve()
    manifest_path = output / "manifest.json"
    if manifest_path.is_file() or not _accepted_systems_only_corpus(output):
        return False

    systems_manifest = _read_json(output / "systems_manifest.json")
    manifest = {
        "schema_version": 0,
        "schema_name": "partial_canonical_corpus",
        "success": True,
        "partial_corpus": True,
        "canonical_passes": ["systems"],
        "systems_schema_version": 6,
        "systems_counts": systems_manifest.get("counts", {}),
        "systems_files": systems_manifest.get("files", []),
        "systems_pass": systems_manifest.get("pass", "UnrealAssetToolSystems"),
    }
    _write_json_atomic(manifest_path, manifest)
    print("created partial canonical manifest from accepted systems schema 6")
    return True


def _install_systems_only_derive_policy(runtime_module) -> None:
    """Permit derive on an explicitly accepted systems-only corpus.

    Missing VFX is optional only when the whole VFX pass is absent. A partial
    VFX stream set without a valid manifest remains an error and is delegated to
    the original strict validator. Normal/full corpora therefore keep the old
    prerequisite behavior unchanged.
    """
    if getattr(runtime_module, "_systems_only_derive_policy_installed", False):
        return

    vfx_module = getattr(runtime_module, "vfx", None)
    original_require_vfx = getattr(runtime_module, "_require_vfx", None)
    original_require_vfx_derived = getattr(runtime_module, "_require_vfx_derived", None)
    original_derive_output = getattr(runtime_module, "derive_output", None)
    if vfx_module is None or not callable(original_require_vfx) or not callable(original_derive_output):
        return

    def vfx_is_fully_absent(output: Path) -> bool:
        output = Path(output).expanduser().resolve()
        return (
            _accepted_systems_only_corpus(output)
            and not bool(vfx_module.read_manifest(output))
            and not _vfx_raw_present(output, vfx_module)
        )

    def require_vfx(output: Path) -> None:
        output = Path(output).expanduser().resolve()
        if vfx_is_fully_absent(output):
            print("VFX specialist pass absent: continuing accepted systems-only derive")
            return
        return original_require_vfx(output)

    def require_vfx_derived(output: Path) -> None:
        output = Path(output).expanduser().resolve()
        if vfx_is_fully_absent(output):
            return
        if callable(original_require_vfx_derived):
            return original_require_vfx_derived(output)

    def derive_output(output):
        output = Path(output).expanduser().resolve()
        _ensure_partial_top_manifest(output)
        return original_derive_output(output)

    runtime_module._require_vfx = require_vfx
    if callable(original_require_vfx_derived):
        runtime_module._require_vfx_derived = require_vfx_derived
    runtime_module.derive_output = derive_output
    runtime_module._systems_only_derive_policy_installed = True


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def accept_schema6(systems_module, project: Path, *, corpus: Path, systems_capture: Path) -> dict:
    if int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0) != 6:
        raise RuntimeError("systems-schema6-accept requires composed systems schema 6")

    manifest = _read_json(systems_capture / "systems_manifest.json")
    if int(manifest.get("schema_version", 0) or 0) != 6 or not bool(manifest.get("success", False)):
        raise RuntimeError("isolated systems capture is not a successful schema-6 manifest")
    error = systems_module.validation_error(systems_capture)
    if error:
        raise RuntimeError(f"isolated systems capture is not valid schema 6: {error}")

    stage = corpus / ".systems-schema6-accept-staging"
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
            raise RuntimeError(f"staged systems schema 6 failed validation: {error}")

        expectations = _graph_expectations(stage, systems_module._rows)
        counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
        acceptance = {
            "acceptance_schema_version": 1,
            "systems_schema_version": 6,
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
            temp = corpus / f".{filename}.schema6-accept.tmp"
            shutil.copy2(stage / filename, temp)
            os.replace(temp, corpus / filename)
        manifest_temp = corpus / ".systems_manifest.json.schema6-accept.tmp"
        shutil.copy2(stage / "systems_manifest.json", manifest_temp)
        os.replace(manifest_temp, corpus / "systems_manifest.json")
        _write_json_atomic(corpus / GRAPH_EXPECTATIONS_MANIFEST, expectations)
        _write_json_atomic(corpus / ACCEPTANCE_MANIFEST, acceptance)

        error = systems_module.validation_error(corpus)
        if error:
            raise RuntimeError(f"promoted canonical systems schema 6 failed validation: {error}")
        return acceptance
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def _verify_graph(corpus: Path, rows) -> dict:
    expectations = _read_json(corpus / GRAPH_EXPECTATIONS_MANIFEST)
    if int(expectations.get("target_derived_schema_version", 0) or 0) != TARGET_DERIVED_SCHEMA_VERSION:
        raise RuntimeError("GAS graph expectations target an unexpected derived schema")

    top_manifest = _read_json(corpus / "manifest.json")
    actual_version = int(top_manifest.get("derived_schema_version", 0) or 0)
    if actual_version != TARGET_DERIVED_SCHEMA_VERSION:
        raise RuntimeError(
            f"GAS graph verification requires derived schema {TARGET_DERIVED_SCHEMA_VERSION}; got {actual_version}"
        )

    expected = gas_graph.expected_edge_keys(corpus, rows)
    project_edges = list(rows(corpus / "project_edges.jsonl"))
    domain_relations = set(gas_graph.RELATION_STREAMS)
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
        raise RuntimeError("GAS exact graph edge set mismatch: " + "; ".join(details))

    relation_counts = collections.Counter()
    for row in actual_rows:
        relation = str(row.get("relation", ""))
        relation_counts[relation] += 1
        if str(row.get("edge_quality", "")) != "exact_semantic":
            raise RuntimeError(f"GAS relation is not exact_semantic: {relation}")
        expected_stream = gas_graph.RELATION_STREAMS[relation]
        evidence = row.get("evidence", []) if isinstance(row.get("evidence", []), list) else []
        if not any(isinstance(item, dict) and str(item.get("stream", "")) == expected_stream for item in evidence):
            raise RuntimeError(f"GAS relation lacks canonical {expected_stream} evidence: {relation}")

    expected_counts = expectations.get("expected_relation_counts", {})
    for relation in gas_graph.RELATION_STREAMS:
        if int(expected_counts.get(relation, 0) or 0) != int(relation_counts.get(relation, 0)):
            raise RuntimeError(
                f"GAS relation count mismatch for {relation}: expected={expected_counts.get(relation, 0)} "
                f"actual={relation_counts.get(relation, 0)}"
            )

    project_nodes = list(rows(corpus / "project_nodes.jsonl"))
    root_specs = (
        ("gas_abilities.jsonl", "ability_path", "gameplay_ability"),
        ("gas_ability_sets.jsonl", "ability_set_path", "gameplay_ability_set"),
        ("gas_gameplay_effects.jsonl", "gameplay_effect_path", "gameplay_effect"),
        ("gas_gameplay_cues.jsonl", "gameplay_cue_path", "gameplay_cue"),
        ("gas_attribute_sets.jsonl", "attribute_set_class", "gameplay_attribute_set"),
    )
    root_counts = {}
    for filename, path_field, kind in root_specs:
        expected_roots = {
            str(row.get(path_field, "") or "") for row in rows(corpus / filename) if row.get(path_field)
        }
        actual_roots = {
            str(row.get("path", "") or "") for row in project_nodes
            if bool(row.get("root")) and str(row.get("node_kind", "")) == kind
        }
        if not expected_roots.issubset(actual_roots):
            missing = sorted(expected_roots - actual_roots)
            raise RuntimeError(f"GAS {kind} graph roots missing: {len(missing)} first={missing[0]}")
        root_counts[kind] = len(expected_roots)

    verification = {
        "schema_version": 1,
        "verified": True,
        "systems_schema_version": 6,
        "derived_schema_version": actual_version,
        "edge_quality": "exact_semantic",
        "expected_exact_semantic_edge_count": len(expected),
        "verified_exact_semantic_edge_count": len(actual),
        "relation_counts": {relation: int(relation_counts.get(relation, 0)) for relation in sorted(gas_graph.RELATION_STREAMS)},
        "root_counts": root_counts,
        "runtime_state_captured": False,
    }
    _write_json_atomic(corpus / GRAPH_VERIFICATION_MANIFEST, verification)
    return verification


def _accept_cli(systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool systems-schema6-accept",
        description="promote an accepted focused systems-schema-6 capture into the canonical corpus; no Unreal or derive",
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--corpus", help="canonical corpus; defaults to <Project>/.uatool")
    parser.add_argument("--systems-capture", help="capture directory; defaults to <corpus>/systems-schema6-capture")
    args = parser.parse_args(argv)
    project = _resolve_project(args.project)
    corpus = Path(args.corpus).expanduser().resolve() if args.corpus else project.parent / ".uatool"
    capture = Path(args.systems_capture).expanduser().resolve() if args.systems_capture else corpus / "systems-schema6-capture"
    result = accept_schema6(systems_module, project, corpus=corpus, systems_capture=capture)
    print(f"accepted canonical systems schema 6: {corpus}")
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
        prog="uatool gas-graph-verify",
        description="verify derived-schema-22 GAS graph topology against accepted systems-schema-6 facts",
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--corpus", help="canonical corpus; defaults to <Project>/.uatool")
    args = parser.parse_args(argv)
    project = _resolve_project(args.project)
    corpus = Path(args.corpus).expanduser().resolve() if args.corpus else project.parent / ".uatool"
    result = _verify_graph(corpus, systems_module._rows)
    print(f"verified GAS derived-schema-22 project graph: {corpus}")
    print(f"verification manifest: {corpus / GRAPH_VERIFICATION_MANIFEST}")
    print(f"  exact_semantic_edges: {result['verified_exact_semantic_edge_count']}")
    for kind, count in sorted(result["root_counts"].items()):
        print(f"  {kind}_roots: {count}")
    print("  runtime_state_captured: False")
    return 0


def install(runtime_module, systems_module) -> None:
    if getattr(systems_module, "__name__", "") != "uatool_systems":
        return
    if getattr(runtime_module, "_systems_schema6_accept_installed", False):
        return

    _promote_composed_derived_schema_version()
    _install_systems_only_derive_policy(runtime_module)
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
        if len(sys.argv) > 1 and sys.argv[1] == "systems-schema6-accept":
            try:
                return _accept_cli(systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 43
        if len(sys.argv) > 1 and sys.argv[1] == "gas-graph-verify":
            try:
                return _verify_cli(systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 44
        return original_main()

    runtime_module.main = main
    runtime_module._systems_schema6_accept_installed = True