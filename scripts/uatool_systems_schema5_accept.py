#!/usr/bin/env python3
"""Promote accepted systems-schema-5 captures and verify their graph contract.

The isolated systems capture owns asset/config/Blueprint-side systems facts. Placed
ZoneShape actors are world-owned, so their accepted focused world capture overlays
only the two ZoneGraph streams. Promotion is explicit and Python-only: it never
launches Unreal or derive, and the composed tree must pass the normal systems
schema validator before the canonical manifest is replaced.

Schema 5 also defines the raw contract for final derived schema 21. Acceptance
writes the exact Mass/ZoneGraph project-edge keys implied by canonical rows. After
the intentionally expensive derive, ``mass-zonegraph-graph-verify`` checks that
those and only those domain relations were promoted as exact semantic edges.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import uatool_zonegraph_world_capture as zonegraph_world_capture

ACCEPTANCE_MANIFEST = "systems_schema5_acceptance.json"
GRAPH_EXPECTATIONS_MANIFEST = "mass_zonegraph_graph_expectations.json"
GRAPH_VERIFICATION_MANIFEST = "mass_zonegraph_graph_verification.json"
ZONEGRAPH_FILES = ("zonegraph_shapes.jsonl", "zonegraph_shape_points.jsonl")
TARGET_DERIVED_SCHEMA_VERSION = 21
ZONEGRAPH_BASE_GENERATOR_CLASS = "/Script/MassSpawner.MassEntityZoneGraphSpawnPointsGenerator"

RELATION_STREAMS = {
    "inherits_mass_entity_config": "mass_entity_configs.jsonl",
    "has_mass_entity_trait": "mass_entity_traits.jsonl",
    "spawns_mass_entity_config": "mass_spawner_entity_types.jsonl",
    "uses_mass_spawn_generator_asset": "mass_spawner_generators.jsonl",
    "uses_mass_spawn_generator_instance": "mass_spawner_generators.jsonl",
    "inherits_mass_spawn_generator_class": "mass_spawn_generator_assets.jsonl",
    "inherits_zonegraph_spawn_generator_base": "mass_spawn_generator_assets.jsonl",
    "owns_mass_agent_component": "mass_agent_components.jsonl",
    "uses_mass_entity_config": "mass_agent_components.jsonl",
    "contains_zonegraph_shape": "zonegraph_shapes.jsonl",
    "owns_zonegraph_shape_component": "zonegraph_shapes.jsonl",
    "has_zonegraph_shape_point": "zonegraph_shape_points.jsonl",
}


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
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temp, path)


def _count_rows(path: Path) -> int:
    return sum(1 for _ in zonegraph_world_capture._rows(path))


def _rows_list(root: Path, filename: str) -> list[dict]:
    return list(zonegraph_world_capture._rows(Path(root) / filename))


def _default_paths(project: Path, corpus_value: str | None, systems_value: str | None, zone_value: str | None):
    corpus = Path(corpus_value).expanduser().resolve() if corpus_value else project.parent / ".uatool"
    systems_capture = (
        Path(systems_value).expanduser().resolve()
        if systems_value
        else corpus / "systems-schema5-capture"
    )
    zonegraph_capture = (
        Path(zone_value).expanduser().resolve()
        if zone_value
        else corpus / "zonegraph-world-capture"
    )
    return corpus, systems_capture, zonegraph_capture


def _point_path(shape_path: str, point_index: int) -> str:
    return f"{shape_path}#zonegraph_point:{point_index}"


def _expected_graph_edges(root: Path) -> set[tuple[str, str, str]]:
    root = Path(root)
    edges: set[tuple[str, str, str]] = set()

    for row in _rows_list(root, "mass_entity_configs.jsonl"):
        source = str(row.get("config_path", "") or "")
        target = str(row.get("parent_config_path", "") or "")
        if source and target and source != target:
            edges.add((source, "inherits_mass_entity_config", target))

    for row in _rows_list(root, "mass_entity_traits.jsonl"):
        source = str(row.get("config_path", "") or "")
        target = str(row.get("trait_path", "") or "")
        if source and target and source != target:
            edges.add((source, "has_mass_entity_trait", target))

    for row in _rows_list(root, "mass_spawner_entity_types.jsonl"):
        source = str(row.get("spawner_path", "") or "")
        target = str(row.get("entity_config_path", "") or "")
        if source and target and source != target:
            edges.add((source, "spawns_mass_entity_config", target))

    for row in _rows_list(root, "mass_spawner_generators.jsonl"):
        source = str(row.get("spawner_path", "") or "")
        asset = str(row.get("generator_asset_path", "") or "")
        instance = str(row.get("generator_path", "") or "")
        if source and asset and source != asset:
            edges.add((source, "uses_mass_spawn_generator_asset", asset))
        elif source and instance and source != instance:
            edges.add((source, "uses_mass_spawn_generator_instance", instance))

    for row in _rows_list(root, "mass_spawn_generator_assets.jsonl"):
        source = str(row.get("generator_asset_path", "") or "")
        parent = str(row.get("parent_class", "") or "")
        if source and parent and source != parent:
            edges.add((source, "inherits_mass_spawn_generator_class", parent))
        if source and bool(row.get("zonegraph_generator", False)):
            edges.add((source, "inherits_zonegraph_spawn_generator_base", ZONEGRAPH_BASE_GENERATOR_CLASS))

    for row in _rows_list(root, "mass_agent_components.jsonl"):
        blueprint = str(row.get("blueprint_path", "") or "")
        component = str(row.get("component_path", "") or "")
        config = str(row.get("entity_config_parent_path", "") or "")
        if blueprint and component and blueprint != component:
            edges.add((blueprint, "owns_mass_agent_component", component))
        if component and config and component != config:
            edges.add((component, "uses_mass_entity_config", config))

    for row in _rows_list(root, "zonegraph_shapes.jsonl"):
        world = str(row.get("world_path", "") or "")
        shape = str(row.get("shape_path", "") or "")
        component = str(row.get("component_path", "") or "")
        if world and shape and world != shape:
            edges.add((world, "contains_zonegraph_shape", shape))
        if shape and component and shape != component:
            edges.add((shape, "owns_zonegraph_shape_component", component))

    for row in _rows_list(root, "zonegraph_shape_points.jsonl"):
        shape = str(row.get("shape_path", "") or "")
        if not shape:
            continue
        index = int(row.get("point_index", 0) or 0)
        point = _point_path(shape, index)
        edges.add((shape, "has_zonegraph_shape_point", point))

    return edges


def _graph_expectations(root: Path) -> dict:
    root = Path(root)
    edges = _expected_graph_edges(root)
    relation_counts: dict[str, int] = {relation: 0 for relation in RELATION_STREAMS}
    for _, relation, _ in edges:
        relation_counts[relation] = relation_counts.get(relation, 0) + 1

    raw_files = (
        "mass_entity_configs.jsonl",
        "mass_entity_traits.jsonl",
        "mass_spawners.jsonl",
        "mass_spawner_entity_types.jsonl",
        "mass_spawner_generators.jsonl",
        "mass_spawn_generator_assets.jsonl",
        "mass_agent_components.jsonl",
        "zonegraph_shapes.jsonl",
        "zonegraph_shape_points.jsonl",
    )
    raw_counts = {name.removesuffix(".jsonl"): _count_rows(root / name) for name in raw_files}
    return {
        "schema_version": 1,
        "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
        "edge_quality": "exact_semantic",
        "generated_lane_topology": False,
        "unsupported_generator_to_placed_shape_edges": 0,
        "raw_counts": raw_counts,
        "expected_relation_counts": relation_counts,
        "expected_exact_semantic_edge_count": len(edges),
        "expected_edges": [
            {"source": source, "relation": relation, "target": target}
            for source, relation, target in sorted(edges)
        ],
    }


def _promote_composed_derived_schema_version() -> None:
    """Promote the already-loaded one-launcher composition from schema 20 to 21.

    ``uatool.py`` defines its final schema constant before ``build_perf.install``
    composes optional systems. Schema-5 is installed from that composition call,
    so this is the narrow point where a domain extension can advance the public
    final schema without creating another launcher or duplicating the composition
    root. Functions in ``uatool.py`` resolve the global at call time.
    """
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


def _compose(
    systems_module,
    corpus: Path,
    systems_capture: Path,
    zonegraph_capture: Path,
    stage: Path,
) -> dict:
    if int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0) != 5:
        raise RuntimeError("systems-schema5-accept requires composed systems schema 5")

    error = systems_module.validation_error(systems_capture)
    if error:
        raise RuntimeError(f"isolated systems capture is not valid schema 5: {error}")

    worlds, expected_shapes = zonegraph_world_capture.discover_zonegraph_worlds(corpus)
    zone_manifest = zonegraph_world_capture._validate_capture(zonegraph_capture, expected_shapes)

    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)

    for filename in systems_module.RAW_FILES:
        source = systems_capture / filename
        if not source.is_file():
            raise RuntimeError(f"isolated systems capture missing {filename}")
        shutil.copy2(source, stage / filename)

    for filename in ZONEGRAPH_FILES:
        source = zonegraph_capture / filename
        if not source.is_file():
            raise RuntimeError(f"focused ZoneGraph capture missing {filename}")
        shutil.copy2(source, stage / filename)

    manifest_path = stage / "systems_manifest.json"
    manifest = _read_json(manifest_path)
    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("systems_manifest.json counts missing or invalid")

    shapes = _rows_list(stage, "zonegraph_shapes.jsonl")
    points = _rows_list(stage, "zonegraph_shape_points.jsonl")
    counts["zonegraph_shapes"] = len(shapes)
    counts["zonegraph_shape_points"] = len(points)
    manifest["zonegraph_authored_source"] = "focused_world_placed_actor_reflection"
    manifest["zonegraph_world_manifest_schema"] = int(zone_manifest.get("schema_version", 0) or 0)
    manifest["zonegraph_worlds_requested"] = len(worlds)
    manifest["zonegraph_expected_shape_count"] = len(expected_shapes)
    manifest["generated_lane_topology"] = False
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    error = systems_module.validation_error(stage)
    if error:
        raise RuntimeError(f"composed schema-5 corpus failed validation: {error}")

    if len(shapes) != len(expected_shapes):
        raise RuntimeError(
            f"composed ZoneGraph shape count mismatch: expected={len(expected_shapes)} actual={len(shapes)}"
        )
    if any(bool(row.get("generated_lane_topology", True)) for row in shapes):
        raise RuntimeError("composed ZoneGraph shape row claims generated lane topology")
    truncated_points = sum(1 for row in points if bool(row.get("truncated", False)))
    if truncated_points:
        raise RuntimeError(f"composed ZoneGraph capture has truncated point rows: {truncated_points}")

    graph_expectations = _graph_expectations(stage)
    return {
        "acceptance_schema_version": 2,
        "systems_schema_version": 5,
        "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
        "systems_capture": str(systems_capture),
        "zonegraph_capture": str(zonegraph_capture),
        "zonegraph_world_manifest_schema": int(zone_manifest.get("schema_version", 0) or 0),
        "zonegraph_worlds": len(worlds),
        "zonegraph_shapes": len(shapes),
        "zonegraph_shape_points": len(points),
        "zonegraph_exact_shape_set_match": True,
        "generated_lane_topology": False,
        "systems_manifest_counts": counts,
        "expected_exact_semantic_edge_count": graph_expectations["expected_exact_semantic_edge_count"],
        "expected_relation_counts": graph_expectations["expected_relation_counts"],
        "graph_expectations": graph_expectations,
    }


def _promote(corpus: Path, stage: Path, raw_files: tuple[str, ...], acceptance: dict) -> None:
    corpus.mkdir(parents=True, exist_ok=True)
    promoted = [name for name in raw_files if name != "systems_manifest.json"]
    # JSONL streams land first. The schema-5 manifest is the commit marker and is
    # replaced last, so a successful manifest never advertises files that were
    # not already promoted.
    for filename in promoted:
        source = stage / filename
        temp = corpus / f".{filename}.schema5-accept.tmp"
        shutil.copy2(source, temp)
        os.replace(temp, corpus / filename)

    manifest_temp = corpus / ".systems_manifest.json.schema5-accept.tmp"
    shutil.copy2(stage / "systems_manifest.json", manifest_temp)
    os.replace(manifest_temp, corpus / "systems_manifest.json")

    zone_manifest_source = Path(acceptance["zonegraph_capture"]) / "zonegraph_world_manifest.json"
    zone_manifest_temp = corpus / ".zonegraph_world_manifest.json.schema5-accept.tmp"
    shutil.copy2(zone_manifest_source, zone_manifest_temp)
    os.replace(zone_manifest_temp, corpus / "zonegraph_world_manifest.json")

    expectations = dict(acceptance.get("graph_expectations", {}))
    _write_json_atomic(corpus / GRAPH_EXPECTATIONS_MANIFEST, expectations)

    acceptance_document = dict(acceptance)
    acceptance_document.pop("graph_expectations", None)
    _write_json_atomic(corpus / ACCEPTANCE_MANIFEST, acceptance_document)


def accept_schema5(
    systems_module,
    project: Path,
    *,
    corpus: Path,
    systems_capture: Path,
    zonegraph_capture: Path,
) -> dict:
    stage = corpus / ".systems-schema5-accept-staging"
    acceptance = _compose(systems_module, corpus, systems_capture, zonegraph_capture, stage)
    try:
        _promote(corpus, stage, tuple(systems_module.RAW_FILES), acceptance)
        error = systems_module.validation_error(corpus)
        if error:
            raise RuntimeError(f"promoted canonical systems schema 5 failed validation: {error}")
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return acceptance


def _verify_graph(corpus: Path) -> dict:
    corpus = Path(corpus)
    expectations_path = corpus / GRAPH_EXPECTATIONS_MANIFEST
    if not expectations_path.is_file():
        raise RuntimeError(
            f"{GRAPH_EXPECTATIONS_MANIFEST} missing; rerun systems-schema5-accept with the current scripts"
        )
    expectations = _read_json(expectations_path)
    target_version = int(expectations.get("target_derived_schema_version", 0) or 0)
    if target_version != TARGET_DERIVED_SCHEMA_VERSION:
        raise RuntimeError(
            f"graph expectation schema targets derived {target_version}, expected {TARGET_DERIVED_SCHEMA_VERSION}"
        )

    top_manifest = _read_json(corpus / "manifest.json")
    actual_version = int(top_manifest.get("derived_schema_version", 0) or 0)
    if actual_version != TARGET_DERIVED_SCHEMA_VERSION:
        raise RuntimeError(
            "Mass/ZoneGraph graph verification requires the new derive: "
            f"manifest derived_schema_version={actual_version}, expected={TARGET_DERIVED_SCHEMA_VERSION}"
        )

    expected = _expected_graph_edges(corpus)
    project_edges = _rows_list(corpus, "project_edges.jsonl")
    domain_relations = set(RELATION_STREAMS)
    actual_rows = [row for row in project_edges if str(row.get("relation", "")) in domain_relations]
    actual = {
        (
            str(row.get("source", "") or ""),
            str(row.get("relation", "") or ""),
            str(row.get("target", "") or ""),
        )
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
        raise RuntimeError("Mass/ZoneGraph exact graph edge set mismatch: " + "; ".join(detail))

    relation_counts: dict[str, int] = {relation: 0 for relation in RELATION_STREAMS}
    for row in actual_rows:
        relation = str(row.get("relation", ""))
        relation_counts[relation] += 1
        if str(row.get("edge_quality", "")) != "exact_semantic":
            raise RuntimeError(
                f"Mass/ZoneGraph relation is not exact_semantic: {relation} {row.get('source')} -> {row.get('target')}"
            )
        evidence = row.get("evidence", []) if isinstance(row.get("evidence", []), list) else []
        expected_stream = RELATION_STREAMS[relation]
        if not any(
            isinstance(item, dict) and str(item.get("stream", "")) == expected_stream
            for item in evidence
        ):
            raise RuntimeError(
                f"Mass/ZoneGraph relation lacks canonical {expected_stream} evidence: "
                f"{relation} {row.get('source')} -> {row.get('target')}"
            )

    expected_counts = expectations.get("expected_relation_counts", {})
    for relation in RELATION_STREAMS:
        if int(expected_counts.get(relation, 0) or 0) != relation_counts[relation]:
            raise RuntimeError(
                f"Mass/ZoneGraph relation count mismatch for {relation}: "
                f"expected={expected_counts.get(relation, 0)} actual={relation_counts[relation]}"
            )

    generator_paths = {
        str(row.get("generator_asset_path", "") or "")
        for row in _rows_list(corpus, "mass_spawn_generator_assets.jsonl")
        if row.get("generator_asset_path")
    }
    shape_paths = {
        str(row.get("shape_path", "") or "")
        for row in _rows_list(corpus, "zonegraph_shapes.jsonl")
        if row.get("shape_path")
    }
    unsupported = [
        row for row in project_edges
        if str(row.get("source", "")) in generator_paths and str(row.get("target", "")) in shape_paths
    ]
    if unsupported:
        row = unsupported[0]
        raise RuntimeError(
            "unsupported generator-to-placed-ZoneShape graph edge was invented: "
            f"{row.get('source')} {row.get('relation')} {row.get('target')}"
        )

    nodes = _rows_list(corpus, "project_nodes.jsonl")
    config_paths = {
        str(row.get("config_path", "") or "")
        for row in _rows_list(corpus, "mass_entity_configs.jsonl")
        if row.get("config_path")
    }
    config_roots = {
        str(row.get("path", "") or "")
        for row in nodes
        if row.get("root") and str(row.get("node_kind", "")) == "mass_entity_config"
    }
    if not config_paths.issubset(config_roots):
        missing = sorted(config_paths - config_roots)
        raise RuntimeError(f"Mass entity config graph roots missing: {len(missing)} first={missing[0]}")

    point_targets = {
        target for _, relation, target in expected if relation == "has_zonegraph_shape_point"
    }
    actual_point_targets = {
        str(row.get("target", ""))
        for row in actual_rows
        if str(row.get("relation", "")) == "has_zonegraph_shape_point"
    }
    if actual_point_targets != point_targets:
        raise RuntimeError("ZoneGraph synthetic point node targets do not exactly match authored point rows")

    verification = {
        "schema_version": 1,
        "verified": True,
        "derived_schema_version": actual_version,
        "edge_quality": "exact_semantic",
        "expected_exact_semantic_edge_count": len(expected),
        "verified_exact_semantic_edge_count": len(actual),
        "relation_counts": relation_counts,
        "mass_entity_config_roots": len(config_roots & config_paths),
        "zonegraph_shapes": len(shape_paths),
        "zonegraph_shape_points": len(point_targets),
        "unsupported_generator_to_placed_shape_edges": 0,
        "generated_lane_topology": False,
    }
    _write_json_atomic(corpus / GRAPH_VERIFICATION_MANIFEST, verification)
    return verification


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def _accept_cli(runtime_module, systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool systems-schema5-accept",
        description=(
            "compose the accepted isolated systems capture with the accepted authored ZoneGraph "
            "world capture and promote only canonical systems-schema-5 files; does not run Unreal or derive"
        ),
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--corpus", help="canonical corpus; defaults to <Project>/.uatool")
    parser.add_argument("--systems-capture", help="isolated systems capture directory")
    parser.add_argument("--zonegraph-capture", help="focused authored ZoneGraph capture directory")
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    corpus, systems_capture, zonegraph_capture = _default_paths(
        project, args.corpus, args.systems_capture, args.zonegraph_capture
    )

    result = accept_schema5(
        systems_module,
        project,
        corpus=corpus,
        systems_capture=systems_capture,
        zonegraph_capture=zonegraph_capture,
    )
    print(f"accepted canonical systems schema 5: {corpus}")
    print(f"acceptance manifest: {corpus / ACCEPTANCE_MANIFEST}")
    print(f"graph expectations: {corpus / GRAPH_EXPECTATIONS_MANIFEST}")
    print(f"  target_derived_schema_version: {TARGET_DERIVED_SCHEMA_VERSION}")
    print(f"  zonegraph_worlds: {result['zonegraph_worlds']}")
    print(f"  zonegraph_shapes: {result['zonegraph_shapes']}")
    print(f"  zonegraph_shape_points: {result['zonegraph_shape_points']}")
    print(f"  expected_exact_semantic_edges: {result['expected_exact_semantic_edge_count']}")
    for relation, count in sorted(result["expected_relation_counts"].items()):
        if count:
            print(f"    {relation}: {count}")
    print("  exact_shape_set_match: True")
    print("  generated_lane_topology: False")
    print("derive was not run")
    return 0


def _verify_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool mass-zonegraph-graph-verify",
        description="verify schema-21 Mass/ZoneGraph project graph edges against accepted canonical raw facts",
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--corpus", help="canonical corpus; defaults to <Project>/.uatool")
    args = parser.parse_args(argv)
    project = _resolve_project(args.project)
    corpus = Path(args.corpus).expanduser().resolve() if args.corpus else project.parent / ".uatool"
    result = _verify_graph(corpus)
    print(f"verified Mass/ZoneGraph schema-21 project graph: {corpus}")
    print(f"verification manifest: {corpus / GRAPH_VERIFICATION_MANIFEST}")
    print(f"  exact_semantic_edges: {result['verified_exact_semantic_edge_count']}")
    print(f"  mass_entity_config_roots: {result['mass_entity_config_roots']}")
    print(f"  zonegraph_shapes: {result['zonegraph_shapes']}")
    print(f"  zonegraph_shape_points: {result['zonegraph_shape_points']}")
    print("  unsupported_generator_to_placed_shape_edges: 0")
    print("  generated_lane_topology: False")
    return 0


def install(runtime_module, systems_module) -> None:
    if getattr(systems_module, "__name__", "") != "uatool_systems":
        return
    if getattr(runtime_module, "_systems_schema5_accept_installed", False):
        return

    _promote_composed_derived_schema_version()

    # Provenance/acceptance documents are small and optional on projects that have
    # not run schema-5 acceptance. Bundle creation already skips absent files.
    try:
        import uatool_core as core_module
        core_module.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((
            *core_module.DEFAULT_BUNDLE_FILES,
            ACCEPTANCE_MANIFEST,
            "zonegraph_world_manifest.json",
            GRAPH_EXPECTATIONS_MANIFEST,
            GRAPH_VERIFICATION_MANIFEST,
        )))
    except Exception:
        pass

    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "systems-schema5-accept":
            try:
                return _accept_cli(runtime_module, systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 39
        if len(sys.argv) > 1 and sys.argv[1] == "mass-zonegraph-graph-verify":
            try:
                return _verify_cli(sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 40
        return original_main()

    runtime_module.main = main
    runtime_module._systems_schema5_accept_installed = True
