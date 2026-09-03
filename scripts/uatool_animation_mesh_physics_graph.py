#!/usr/bin/env python3
"""Promote exact animation-schema-3 mesh/physics joins into derived schema 29."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import uatool_animation_mesh_physics_model as model

TARGET_DERIVED_SCHEMA_VERSION = 29
RELATIONS = set(model.RELATIONS)


def _augment(output: Path, rows, nodes: list[dict], edges: list[dict], graph_module):
    data = model.build_model(Path(output), rows)
    node_by_key = {
        (str(node.get("node_kind", "")), str(node.get("path", ""))): node
        for node in nodes
    }
    path_nodes: dict[str, list[dict]] = {}
    for node in nodes:
        path_nodes.setdefault(str(node.get("path", "")), []).append(node)

    def register(spec: dict):
        path = str(spec.get("path", "")); kind = str(spec.get("kind", ""))
        if not path or not kind:
            return None
        key = (kind, path)
        node = node_by_key.get(key)
        if node is None:
            node = {
                "node_id": graph_module._node_id(kind, path),
                "node_kind": kind,
                "path": path,
                "coverage": str(spec.get("coverage", "first_class")),
                "class_path": str(spec.get("class_path", "")),
                "package_name": str(spec.get("package_name", "") or graph_module._package(path)),
                "family": str(spec.get("family", "animation_mesh_physics")),
                "root": bool(spec.get("root", False)),
            }
            nodes.append(node)
            node_by_key[key] = node
            path_nodes.setdefault(path, []).append(node)
        else:
            coverage = str(spec.get("coverage", "first_class"))
            if graph_module.COVERAGE_RANK.get(coverage, -1) > graph_module.COVERAGE_RANK.get(str(node.get("coverage", "")), -1):
                node["coverage"] = coverage
            if spec.get("class_path") and not node.get("class_path"):
                node["class_path"] = str(spec["class_path"])
            if spec.get("package_name") and not node.get("package_name"):
                node["package_name"] = str(spec["package_name"])
            if spec.get("root"):
                node["root"] = True
            if str(node.get("family", "")) in ("", "asset_registry", "external"):
                node["family"] = "animation_mesh_physics"
        return node

    # Seed authoritative roots directly from their canonical identity streams.
    # Referencing the same mesh later as a preview mesh, or the same PhysicsAsset
    # from clothing, must never downgrade root/class/package metadata.
    for row in rows(Path(output) / "skeletal_meshes.jsonl"):
        register({
            "path": str(row.get("skeletal_mesh_path", "")),
            "kind": "skeletal_mesh",
            "coverage": "first_class",
            "class_path": str(row.get("class_path", "")),
            "package_name": str(row.get("package_name", "")),
            "family": "animation_mesh_physics",
            "root": True,
        })
    for row in rows(Path(output) / "physics_assets.jsonl"):
        register({
            "path": str(row.get("physics_asset_path", "")),
            "kind": "physics_asset",
            "coverage": "first_class",
            "class_path": str(row.get("class_path", "")),
            "package_name": str(row.get("package_name", "")),
            "family": "animation_mesh_physics",
            "root": True,
        })

    for spec in data["nodes"]:
        register(spec)

    edge_by_key = {
        (
            str(edge.get("source_kind", "")), str(edge.get("source", "")),
            str(edge.get("relation", "")), str(edge.get("target_kind", "")),
            str(edge.get("target", "")),
        ): edge
        for edge in edges
    }

    for spec in data["edge_specs"]:
        sk = str(spec["source_kind"]); source = str(spec["source"])
        relation = str(spec["relation"]); tk = str(spec["target_kind"]); target = str(spec["target"])
        sm = node_by_key.get((sk, source))
        tm = node_by_key.get((tk, target))
        if sm is None:
            sm = register({"path": source, "kind": sk, "coverage": "first_class", "family": "animation_mesh_physics"})
        if tm is None:
            tm = register({"path": target, "kind": tk, "coverage": "first_class", "family": "animation_mesh_physics"})
        if not sm or not tm:
            continue
        key = (sk, source, relation, tk, target)
        evidence = dict(spec.get("evidence", {}))
        evidence.setdefault("quality", "exact_semantic")
        token = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        edge = edge_by_key.get(key)
        if edge is None:
            edge = {
                "edge_id": graph_module._edge_id(sk, source, relation, tk, target),
                "source_kind": sk,
                "source": source,
                "relation": relation,
                "target_kind": tk,
                "target": target,
                "source_coverage": str(sm.get("coverage", "first_class")),
                "target_coverage": str(tm.get("coverage", "first_class")),
                "edge_quality": "exact_semantic",
                "evidence_count": 1,
                "evidence": [evidence],
            }
            edges.append(edge)
            edge_by_key[key] = edge
        else:
            current = {
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in edge.get("evidence", []) if isinstance(item, dict)
            }
            if token not in current:
                edge.setdefault("evidence", []).append(evidence)
            edge["evidence_count"] = len(edge.get("evidence", []))
            edge["edge_quality"] = "exact_semantic"
            edge["source_coverage"] = str(sm.get("coverage", "first_class"))
            edge["target_coverage"] = str(tm.get("coverage", "first_class"))

    edges.sort(key=lambda edge: (
        str(edge.get("source_kind", "")), str(edge.get("source", "")),
        str(edge.get("relation", "")), str(edge.get("target_kind", "")),
        str(edge.get("target", "")), str(edge.get("edge_id", "")),
    ))
    nodes.sort(key=lambda node: (str(node.get("node_kind", "")), str(node.get("path", ""))))
    return nodes, edges


def promote_public_derived_version(project_graph_module, core_module=None, runtime_module=None) -> None:
    project_graph_module.DERIVED_SCHEMA_VERSION = max(
        int(getattr(project_graph_module, "DERIVED_SCHEMA_VERSION", 0) or 0),
        TARGET_DERIVED_SCHEMA_VERSION,
    )
    for module in (core_module, runtime_module):
        if module is not None and hasattr(module, "DERIVED_SCHEMA_VERSION"):
            setattr(module, "DERIVED_SCHEMA_VERSION", max(
                int(getattr(module, "DERIVED_SCHEMA_VERSION", 0) or 0),
                TARGET_DERIVED_SCHEMA_VERSION,
            ))
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
        if int(getattr(module, "FINAL_DERIVED_SCHEMA_VERSION", 0) or 0) < TARGET_DERIVED_SCHEMA_VERSION:
            setattr(module, "FINAL_DERIVED_SCHEMA_VERSION", TARGET_DERIVED_SCHEMA_VERSION)


def install(project_graph_module, core_module=None, runtime_module=None) -> None:
    if getattr(project_graph_module, "_animation_mesh_physics_graph_installed", False):
        promote_public_derived_version(project_graph_module, core_module, runtime_module)
        return
    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._animation_mesh_physics_graph_installed = True
    promote_public_derived_version(project_graph_module, core_module, runtime_module)
