#!/usr/bin/env python3
"""Promote normalized Gameplay Cameras topology into the typed project graph."""
from __future__ import annotations

import json
from pathlib import Path


def _augment(output: Path, rows, nodes: list[dict], edges: list[dict], graph_module):
    node_by_key = {(str(n.get("node_kind", "")), str(n.get("path", ""))): n for n in nodes}
    path_nodes: dict[str, list[dict]] = {}
    for node in nodes:
        path_nodes.setdefault(str(node.get("path", "")), []).append(node)

    def existing(path: str):
        values = path_nodes.get(str(path or ""), [])
        if not values:
            return None
        return max(values, key=lambda n: (
            graph_module.COVERAGE_RANK.get(str(n.get("coverage", "")), -1),
            int(bool(n.get("root", False))),
            str(n.get("node_kind", "")),
        ))

    def register(path: str, kind: str, coverage: str, class_path: str = "", root: bool = False):
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
                "family": "gameplay_camera",
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

    edge_by_key = {
        (str(e.get("source_kind", "")), str(e.get("source", "")), str(e.get("relation", "")),
         str(e.get("target_kind", "")), str(e.get("target", ""))): e
        for e in edges
    }

    def add(source: str, relation: str, target: str, source_kind: str, target_kind: str, evidence: dict):
        source = str(source or "")
        target = str(target or "")
        if not source or not target or source == target:
            return
        source_node = node_by_key.get((source_kind, source)) or existing(source) or register(source, source_kind, "partial")
        target_node = node_by_key.get((target_kind, target)) or existing(target) or register(target, target_kind, "partial")
        if not source_node or not target_node:
            return
        source_kind = str(source_node.get("node_kind", source_kind))
        target_kind = str(target_node.get("node_kind", target_kind))
        key = (source_kind, source, relation, target_kind, target)
        token = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        edge = edge_by_key.get(key)
        if edge is None:
            edge = {
                "edge_id": graph_module._edge_id(source_kind, source, relation, target_kind, target),
                "source_kind": source_kind,
                "source": source,
                "relation": relation,
                "target_kind": target_kind,
                "target": target,
                "source_coverage": source_node.get("coverage", "partial"),
                "target_coverage": target_node.get("coverage", "partial"),
                "edge_quality": "exact_semantic",
                "evidence_count": 1,
                "evidence": [evidence],
            }
            edges.append(edge)
            edge_by_key[key] = edge
            return
        current = {
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for item in edge.get("evidence", []) if isinstance(item, dict)
        }
        if token not in current:
            edge.setdefault("evidence", []).append(evidence)
            edge["evidence"].sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            edge["evidence_count"] = len(edge["evidence"])

    asset_paths: set[str] = set()
    rig_paths: set[str] = set()
    for row in rows(output / "gameplay_camera_assets.jsonl"):
        asset = str(row.get("camera_asset_path", ""))
        asset_paths.add(asset)
        register(asset, "gameplay_camera_asset", "first_class", row.get("class_path", ""), root=True)
        director = str(row.get("director_path", ""))
        if director:
            register(director, "gameplay_camera_director", "first_class", row.get("director_class", ""))
            add(asset, "uses_camera_director", director, "gameplay_camera_asset", "gameplay_camera_director", {
                "stream": "gameplay_camera_assets.jsonl", "kind": "canonical_gameplay_camera_topology",
            })

    for row in rows(output / "gameplay_camera_rigs.jsonl"):
        rig = str(row.get("rig_path", ""))
        rig_paths.add(rig)
        register(rig, "gameplay_camera_rig", "first_class", row.get("class_path", ""), root=True)

    for row in rows(output / "gameplay_camera_directors.jsonl"):
        director = str(row.get("director_path", ""))
        register(director, "gameplay_camera_director", "first_class", row.get("director_class", ""))

    for row in rows(output / "gameplay_camera_nodes.jsonl"):
        rig = str(row.get("rig_path", ""))
        node = str(row.get("node_path", ""))
        register(rig, "gameplay_camera_rig", "first_class")
        register(node, "gameplay_camera_node", "first_class", row.get("node_class", ""))
        evidence = {
            "stream": "gameplay_camera_nodes.jsonl", "kind": "canonical_gameplay_camera_topology",
            "node_index": int(row.get("node_index", 0) or 0), "node_name": row.get("node_name", ""),
        }
        add(rig, "contains_camera_node", node, "gameplay_camera_rig", "gameplay_camera_node", evidence)
        if row.get("is_root"):
            add(rig, "has_camera_root_node", node, "gameplay_camera_rig", "gameplay_camera_node", evidence)

    for row in rows(output / "gameplay_camera_node_edges.jsonl"):
        source = str(row.get("source_node_path", ""))
        target = str(row.get("target_node_path", ""))
        register(source, "gameplay_camera_node", "first_class")
        register(target, "gameplay_camera_node", "first_class", row.get("target_node_class", ""))
        add(source, "camera_node_links_to", target, "gameplay_camera_node", "gameplay_camera_node", {
            "stream": "gameplay_camera_node_edges.jsonl", "kind": "canonical_gameplay_camera_topology",
            "rig_path": row.get("rig_path", ""), "property_path": row.get("property_path", ""),
        })

    owner_kind_map = {
        "gameplay_camera_asset": "gameplay_camera_asset",
        "gameplay_camera_rig": "gameplay_camera_rig",
    }
    role_relation = {
        "enter": "has_camera_enter_transition",
        "exit": "has_camera_exit_transition",
        "graph_object": "has_camera_transition_graph_object",
    }
    for row in rows(output / "gameplay_camera_transitions.jsonl"):
        owner = str(row.get("owner_path", ""))
        transition = str(row.get("transition_path", ""))
        owner_kind = owner_kind_map.get(str(row.get("owner_kind", "")), "gameplay_camera_object")
        register(owner, owner_kind, "first_class")
        register(transition, "gameplay_camera_transition", "first_class", row.get("transition_class", ""))
        add(owner, role_relation.get(str(row.get("transition_role", "")), "has_camera_transition"), transition,
            owner_kind, "gameplay_camera_transition", {
                "stream": "gameplay_camera_transitions.jsonl", "kind": "canonical_gameplay_camera_topology",
                "transition_role": row.get("transition_role", ""),
                "transition_index": int(row.get("transition_index", 0) or 0),
            })

    source_kind_map = {
        "gameplay_camera_asset": "gameplay_camera_asset",
        "gameplay_camera_rig": "gameplay_camera_rig",
        "gameplay_camera_node": "gameplay_camera_node",
        "gameplay_camera_transition": "gameplay_camera_transition",
        "gameplay_camera_director": "gameplay_camera_director",
        "gameplay_camera_director_object": "gameplay_camera_object",
    }
    for row in rows(output / "gameplay_camera_rig_references.jsonl"):
        asset = str(row.get("asset_path", ""))
        source = str(row.get("source_owner_path", ""))
        target = str(row.get("target_rig_path", ""))
        source_kind = source_kind_map.get(str(row.get("source_owner_kind", "")), "gameplay_camera_object")
        register(source, source_kind, "first_class" if source_kind != "gameplay_camera_object" else "partial")
        register(target, "gameplay_camera_rig", "first_class", row.get("target_rig_class", ""), root=True)
        evidence = {
            "stream": "gameplay_camera_rig_references.jsonl", "kind": "canonical_gameplay_camera_topology",
            "asset_path": asset, "property_path": row.get("property_path", ""),
            "source_owner_kind": row.get("source_owner_kind", ""),
        }
        add(source, "references_camera_rig", target, source_kind, "gameplay_camera_rig", evidence)
        if asset in asset_paths:
            add(asset, "uses_camera_rig", target, "gameplay_camera_asset", "gameplay_camera_rig", evidence)
        elif asset in rig_paths and asset != target:
            add(asset, "uses_camera_rig", target, "gameplay_camera_rig", "gameplay_camera_rig", evidence)

    nodes.sort(key=lambda n: (str(n.get("path", "")), str(n.get("node_kind", "")), str(n.get("node_id", ""))))
    edges.sort(key=lambda e: (str(e.get("source", "")), str(e.get("relation", "")), str(e.get("target", "")), str(e.get("edge_id", ""))))
    return nodes, edges


def install(project_graph_module) -> None:
    if getattr(project_graph_module, "_gameplay_camera_graph_installed", False):
        return
    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._gameplay_camera_graph_installed = True
