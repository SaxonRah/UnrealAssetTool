#!/usr/bin/env python3
"""Promote exact authored Gameplay Framework joins into derived schema 28."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import uatool_gameplay_framework_model as model

TARGET_DERIVED_SCHEMA_VERSION = model.TARGET_DERIVED_SCHEMA_VERSION
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

    def register(path, kind, coverage="first_class", class_path="", family="gameplay_framework", root=False):
        path = str(path or "")
        if not path:
            return None
        key = (kind, path)
        node = node_by_key.get(key)
        if node is None:
            node = {
                "node_id": graph_module._node_id(kind, path),
                "node_kind": kind,
                "path": path,
                "coverage": coverage,
                "class_path": str(class_path or ""),
                "package_name": graph_module._package(path),
                "family": family,
                "root": bool(root),
            }
            nodes.append(node)
            node_by_key[key] = node
            path_nodes.setdefault(path, []).append(node)
        else:
            if graph_module.COVERAGE_RANK.get(coverage, -1) > graph_module.COVERAGE_RANK.get(str(node.get("coverage", "")), -1):
                node["coverage"] = coverage
            if class_path and not node.get("class_path"):
                node["class_path"] = class_path
            if root:
                node["root"] = True
        return node

    # Existing structural/world nodes stay authoritative for their own identity.
    # Register specialist class/settings nodes separately instead of replacing them.
    for record in data["framework_blueprints"]:
        bp = record["blueprint_path"]
        if bp and not any(node.get("node_kind") in {"blueprint", "animation_blueprint", "widget_blueprint", "control_rig_blueprint"} for node in path_nodes.get(bp, [])):
            register(bp, "blueprint", "first_class", family="blueprint", root=True)
        generated = record["generated_class"]
        if generated:
            register(
                generated,
                f"{record['framework_kind']}_class",
                "first_class",
                class_path=generated,
                root=False,
            )
    register(model.GAME_MAPS_SETTINGS_NODE, "game_maps_settings", "first_class", family="gameplay_framework", root=True)

    edge_by_key = {
        (
            str(edge.get("source_kind", "")),
            str(edge.get("source", "")),
            str(edge.get("relation", "")),
            str(edge.get("target_kind", "")),
            str(edge.get("target", "")),
        ): edge
        for edge in edges
    }

    def endpoint(path: str, kind: str, is_target: bool):
        existing = node_by_key.get((kind, path))
        if existing:
            return existing
        if kind == "world":
            world = next((node for node in path_nodes.get(path, []) if node.get("node_kind") == "world"), None)
            if world:
                return world
            return register(path, kind, "external_or_excluded", class_path="/Script/Engine.World", family="world")
        if kind == "blueprint":
            bp = next((node for node in path_nodes.get(path, []) if "blueprint" in str(node.get("node_kind", ""))), None)
            if bp:
                return bp
            return register(path, kind, "first_class", family="blueprint")
        if kind == "actor":
            actor = next((node for node in path_nodes.get(path, []) if node.get("node_kind") == "actor"), None)
            if actor:
                return actor
            return register(path, kind, "first_class", family="world")
        if kind.endswith("_class") or kind == "class":
            coverage = "first_class" if kind != "class" else "partial"
            family = "gameplay_framework" if kind != "class" else "class"
            return register(path, kind, coverage, class_path=path, family=family)
        return register(path, kind, "first_class")

    for spec in data["edge_specs"]:
        sk = str(spec["source_kind"])
        source = str(spec["source"])
        relation = str(spec["relation"])
        tk = str(spec["target_kind"])
        target = str(spec["target"])
        sm = endpoint(source, sk, False)
        tm = endpoint(target, tk, True)
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
                "source_coverage": sm.get("coverage", "first_class"),
                "target_coverage": tm.get("coverage", "first_class"),
                "edge_quality": "exact_semantic",
                "evidence_count": 1,
                "evidence": [evidence],
            }
            edges.append(edge)
            edge_by_key[key] = edge
        else:
            current = {
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in edge.get("evidence", [])
                if isinstance(item, dict)
            }
            if token not in current:
                edge.setdefault("evidence", []).append(evidence)
                edge["evidence_count"] = len(edge["evidence"])
            edge["edge_quality"] = "exact_semantic"

    edges.sort(key=lambda edge: (
        str(edge.get("source_kind", "")), str(edge.get("source", "")), str(edge.get("relation", "")),
        str(edge.get("target_kind", "")), str(edge.get("target", "")), str(edge.get("edge_id", "")),
    ))
    nodes.sort(key=lambda node: (str(node.get("node_kind", "")), str(node.get("path", ""))))
    return nodes, edges


def _promote_public_derived_version(project_graph_module) -> None:
    project_graph_module.DERIVED_SCHEMA_VERSION = max(
        int(getattr(project_graph_module, "DERIVED_SCHEMA_VERSION", 0) or 0),
        TARGET_DERIVED_SCHEMA_VERSION,
    )
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


def install(project_graph_module) -> None:
    if getattr(project_graph_module, "_gameplay_framework_graph_installed", False):
        _promote_public_derived_version(project_graph_module)
        return
    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._gameplay_framework_graph_installed = True
    _promote_public_derived_version(project_graph_module)
