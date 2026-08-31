#!/usr/bin/env python3
"""Promote normalized Mover topology into the typed project graph."""
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
        return max(
            values,
            key=lambda n: (
                graph_module.COVERAGE_RANK.get(str(n.get("coverage", "")), -1),
                int(bool(n.get("root", False))),
                str(n.get("node_kind", "")),
            ),
        )

    def register(path: str, kind: str, coverage: str, class_path: str = "", family: str = "mover", root: bool = False):
        path = str(path or "")
        if not path:
            return None
        key = (str(kind), path)
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

    edge_by_key = {
        (
            str(e.get("source_kind", "")), str(e.get("source", "")), str(e.get("relation", "")),
            str(e.get("target_kind", "")), str(e.get("target", "")),
        ): e
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

    for row in rows(output / "mover_blueprints.jsonl"):
        bp = str(row.get("blueprint_path", ""))
        bp_node = existing(bp) or register(bp, "blueprint", "first_class", family="blueprint", root=True)
        cdo = str(row.get("cdo_path", ""))
        kind = str(row.get("mover_kind", ""))
        cdo_kind = "mover_transition_cdo" if kind == "movement_transition" else "mover_mode_cdo"
        if cdo:
            register(cdo, cdo_kind, "first_class", row.get("cdo_class", ""))
            add(
                bp, "defines_mover_cdo", cdo,
                str(bp_node.get("node_kind", "blueprint")), cdo_kind,
                {"stream": "mover_blueprints.jsonl", "kind": "canonical_mover_topology", "mover_kind": kind},
            )

    for row in rows(output / "mover_components.jsonl"):
        bp = str(row.get("blueprint_path", ""))
        component = str(row.get("component_path", ""))
        bp_node = existing(bp) or register(bp, "blueprint", "first_class", family="blueprint", root=True)
        register(component, "mover_component", "first_class", row.get("component_class", ""))
        add(
            bp, "owns_mover_component", component,
            str(bp_node.get("node_kind", "blueprint")), "mover_component",
            {"stream": "mover_components.jsonl", "kind": "canonical_mover_topology", "component_name": row.get("component_name", ""), "component_kind": row.get("component_kind", "")},
        )
        backend = str(row.get("backend_class", ""))
        if backend:
            register(backend, "class", "partial", backend, family="class")
            add(
                component, "uses_mover_backend_class", backend,
                "mover_component", "class",
                {"stream": "mover_components.jsonl", "kind": "canonical_mover_topology"},
            )

    for row in rows(output / "mover_modes.jsonl"):
        component = str(row.get("component_path", ""))
        mode = str(row.get("mode_path", ""))
        register(component, "mover_component", "first_class")
        register(mode, "mover_mode", "first_class", row.get("mode_class", ""))
        evidence = {
            "stream": "mover_modes.jsonl",
            "kind": "canonical_mover_topology",
            "mode_name": row.get("mode_name", ""),
            "mode_index": int(row.get("mode_index", 0) or 0),
        }
        add(component, "has_movement_mode", mode, "mover_component", "mover_mode", evidence)
        if row.get("is_starting"):
            add(component, "starts_in_movement_mode", mode, "mover_component", "mover_mode", evidence)
        asset = str(row.get("mode_asset_path", ""))
        if asset:
            asset_node = existing(asset) or register(asset, "blueprint", "first_class", family="blueprint", root=True)
            add(
                mode, "instance_of_movement_mode_blueprint", asset,
                "mover_mode", str(asset_node.get("node_kind", "blueprint")),
                {"stream": "mover_modes.jsonl", "kind": "canonical_mover_topology", "mode_name": row.get("mode_name", "")},
            )

    owner_kinds = {
        "mover_component": "mover_component",
        "mover_mode": "mover_mode",
        "movement_mode": "mover_mode_cdo",
        "movement_transition": "mover_transition_cdo",
    }
    for row in rows(output / "mover_settings.jsonl"):
        owner = str(row.get("owner_path", ""))
        owner_kind = owner_kinds.get(str(row.get("owner_kind", "")), "mover_object")
        target = str(row.get("setting_path", ""))
        target_kind = "class" if row.get("target_kind") == "class" else "mover_setting"
        register(owner, owner_kind, "first_class")
        register(target, target_kind, "partial" if target_kind == "class" else "first_class", row.get("setting_class", ""), family="class" if target_kind == "class" else "mover")
        relation = "requires_shared_setting_class" if row.get("relation") == "shared_setting_class" else "uses_shared_setting"
        add(
            owner, relation, target, owner_kind, target_kind,
            {"stream": "mover_settings.jsonl", "kind": "canonical_mover_topology", "setting_index": int(row.get("setting_index", 0) or 0)},
        )

    for row in rows(output / "mover_transitions.jsonl"):
        owner = str(row.get("owner_path", ""))
        owner_kind = owner_kinds.get(str(row.get("owner_kind", "")), "mover_object")
        target = str(row.get("transition_path", ""))
        target_kind = "class" if row.get("target_kind") == "class" else "mover_transition"
        register(owner, owner_kind, "first_class")
        register(target, target_kind, "partial" if target_kind == "class" else "first_class", row.get("transition_class", ""), family="class" if target_kind == "class" else "mover")
        evidence = {
            "stream": "mover_transitions.jsonl",
            "kind": "canonical_mover_topology",
            "transition_index": int(row.get("transition_index", 0) or 0),
        }
        add(owner, "has_movement_transition", target, owner_kind, target_kind, evidence)

        asset = str(row.get("transition_asset_path", ""))
        if asset:
            asset_node = existing(asset) or register(asset, "blueprint", "first_class", family="blueprint", root=True)
            relation = (
                "generated_by_movement_transition_blueprint"
                if target_kind == "class"
                else "instance_of_movement_transition_blueprint"
            )
            add(
                target, relation, asset,
                target_kind, str(asset_node.get("node_kind", "blueprint")),
                evidence,
            )

    nodes.sort(key=lambda n: (str(n.get("path", "")), str(n.get("node_kind", "")), str(n.get("node_id", ""))))
    edges.sort(key=lambda e: (str(e.get("source", "")), str(e.get("relation", "")), str(e.get("target", "")), str(e.get("edge_id", ""))))
    return nodes, edges


def install(project_graph_module) -> None:
    if getattr(project_graph_module, "_mover_graph_installed", False):
        return
    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._mover_graph_installed = True
