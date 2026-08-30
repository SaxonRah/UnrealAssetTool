#!/usr/bin/env python3
"""Canonicalize schema-13 typed graph roots and rebuild bounded neighborhoods.

The universal Asset Registry layer may initially type an asset differently from a
later first-class specialist stream. This finalizer uses those specialist streams
as the authority for root typing, folds duplicate edge identities after that
canonicalization, and rebuilds neighborhoods without changing evidence.
"""
from __future__ import annotations

import collections
import hashlib
import json

import uatool_project_graph as graph


def _edge_id(source_kind: str, source: str, relation: str, target_kind: str, target: str) -> str:
    basis = "\x1f".join((source_kind, source, relation, target_kind, target))
    return "pedge:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


def _node_id(kind: str, path: str) -> str:
    return "pnode:" + hashlib.sha1(f"{kind}\x1f{path}".encode("utf-8")).hexdigest()[:24]


def _bp_kind(row: dict) -> str:
    cls = str(row.get("class", ""))
    if cls == "/Script/Engine.AnimBlueprint":
        return "animation_blueprint"
    if "ControlRigBlueprint" in cls:
        return "control_rig_blueprint"
    if "WidgetBlueprint" in cls:
        return "widget_blueprint"
    return "blueprint"


def _canonical_roots(output, rows) -> dict[str, str]:
    roots: dict[str, str] = {}

    def add(path, kind) -> None:
        path = str(path or "")
        kind = str(kind or "")
        if path and path.strip() and kind:
            roots[path] = kind

    for row in rows(output / "blueprints.jsonl"):
        add(row.get("object_path"), _bp_kind(row))

    for filename, path_key, kind_key, fixed_kind in (
        ("animation_assets.jsonl", "animation_path", "animation_kind", ""),
        ("vfx_assets.jsonl", "vfx_path", "vfx_kind", ""),
        ("systems_assets.jsonl", "systems_path", "systems_kind", ""),
        ("behavior_trees.jsonl", "behavior_tree_path", "", "behavior_tree"),
        ("blackboards.jsonl", "blackboard_path", "", "blackboard"),
        ("eqs_queries.jsonl", "eqs_path", "", "eqs_query"),
        ("statetrees.jsonl", "statetree_path", "", "statetree"),
        ("pcg_graphs.jsonl", "pcg_path", "", "pcg_graph"),
        ("materials.jsonl", "material_path", "material_kind", ""),
    ):
        for row in rows(output / filename):
            add(row.get(path_key), fixed_kind or row.get(kind_key, "asset"))

    for row in rows(output / "worlds.jsonl"):
        add(row.get("world_path"), "world")
    return roots


def _node_copy(node: dict, kind: str, path: str, *, root: bool) -> dict:
    out = dict(node)
    out["node_id"] = _node_id(kind, path)
    out["node_kind"] = kind
    out["path"] = path
    out["root"] = bool(root)
    return out


def _best_path_node(nodes_by_path: dict[str, list[dict]], path: str) -> dict:
    candidates = nodes_by_path.get(path, [])
    if not candidates:
        return {
            "node_id": "", "node_kind": "object", "path": path,
            "coverage": "external_or_excluded", "class_path": "",
            "package_name": "", "family": "external", "root": False,
        }
    return max(
        candidates,
        key=lambda n: (
            graph.COVERAGE_RANK.get(str(n.get("coverage", "")), -1),
            int(bool(n.get("root", False))),
            str(n.get("family", "")) != "asset_registry",
            str(n.get("node_kind", "")),
        ),
    )


def finalize(output, rows, nodes: list[dict], edges: list[dict]):
    canonical_roots = _canonical_roots(output, rows)
    nodes_by_key = {
        (str(n.get("node_kind", "")), str(n.get("path", ""))): dict(n)
        for n in nodes
        if str(n.get("path", "")).strip()
    }
    nodes_by_path: dict[str, list[dict]] = collections.defaultdict(list)
    for node in nodes_by_key.values():
        nodes_by_path[str(node.get("path", ""))].append(node)

    evidence_by_key: dict[tuple[str, str, str, str, str], dict[str, tuple[dict, str]]] = collections.defaultdict(dict)
    for edge in edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        relation = str(edge.get("relation", ""))
        if not source.strip() or not target.strip() or not relation or source == target:
            continue
        source_kind = canonical_roots.get(source, str(edge.get("source_kind", "object")))
        target_kind = canonical_roots.get(target, str(edge.get("target_kind", "object")))
        quality = str(edge.get("edge_quality", "exact_reference"))
        for evidence in edge.get("evidence", []) if isinstance(edge.get("evidence", []), list) else []:
            if not isinstance(evidence, dict):
                continue
            value = dict(evidence)
            value.setdefault("quality", quality)
            token = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            evidence_by_key[(source_kind, source, relation, target_kind, target)][token] = (value, quality)

    canonical_edges: list[dict] = []
    used_keys: set[tuple[str, str]] = set()
    for key in sorted(evidence_by_key):
        source_kind, source, relation, target_kind, target = key
        pairs = [evidence_by_key[key][token] for token in sorted(evidence_by_key[key])]
        evidence = [item[0] for item in pairs]
        quality = max((item[1] for item in pairs), key=lambda q: graph.QUALITY_RANK.get(q, -1))

        source_node = nodes_by_key.get((source_kind, source))
        if source_node is None:
            source_node = _node_copy(
                _best_path_node(nodes_by_path, source), source_kind, source,
                root=canonical_roots.get(source) == source_kind,
            )
            nodes_by_key[(source_kind, source)] = source_node
        target_node = nodes_by_key.get((target_kind, target))
        if target_node is None:
            target_node = _node_copy(
                _best_path_node(nodes_by_path, target), target_kind, target,
                root=canonical_roots.get(target) == target_kind,
            )
            nodes_by_key[(target_kind, target)] = target_node

        used_keys.add((source_kind, source))
        used_keys.add((target_kind, target))
        canonical_edges.append({
            "edge_id": _edge_id(source_kind, source, relation, target_kind, target),
            "source_kind": source_kind,
            "source": source,
            "relation": relation,
            "target_kind": target_kind,
            "target": target,
            "source_coverage": str(source_node.get("coverage", "external_or_excluded")),
            "target_coverage": str(target_node.get("coverage", "external_or_excluded")),
            "edge_quality": quality,
            "evidence_count": len(evidence),
            "evidence": evidence,
        })

    # Retain all canonical roots, including disconnected specialist assets. Only
    # the canonical specialist kind may carry root=True for a given path.
    for path, kind in canonical_roots.items():
        key = (kind, path)
        node = nodes_by_key.get(key)
        if node is None:
            node = _node_copy(_best_path_node(nodes_by_path, path), kind, path, root=True)
            nodes_by_key[key] = node
        node["root"] = True
        used_keys.add(key)

    canonical_nodes: list[dict] = []
    for key in sorted(used_keys, key=lambda item: (item[1], item[0])):
        node = dict(nodes_by_key[key])
        node["root"] = canonical_roots.get(node["path"]) == node["node_kind"]
        canonical_nodes.append(node)

    canonical_edges.sort(key=lambda e: (e["source"], e["relation"], e["target"], e["edge_id"]))
    neighborhoods = _build_neighborhoods(canonical_nodes, canonical_edges)
    return canonical_nodes, canonical_edges, neighborhoods


def _build_neighborhoods(nodes: list[dict], edges: list[dict]) -> list[dict]:
    adjacency: dict[str, list[tuple[str, dict, str]]] = collections.defaultdict(list)
    for edge in edges:
        adjacency[edge["source"]].append(("out", edge, edge["target"]))
        adjacency[edge["target"]].append(("in", edge, edge["source"]))
    for path in adjacency:
        adjacency[path].sort(key=lambda item: (
            item[0], item[1]["relation"], item[1]["source_kind"], item[1]["source"],
            item[1]["target_kind"], item[1]["target"], item[1]["edge_id"],
        ))

    root_nodes = {
        str(node["path"]): node
        for node in nodes
        if node.get("root") and str(node.get("path", "")) in adjacency
    }
    neighborhoods: list[dict] = []
    for root_path in sorted(root_nodes):
        root = root_nodes[root_path]
        queue = collections.deque([(root_path, 0)])
        expanded_depth = {root_path: 0}
        seen_edges: set[str] = set()
        touched_nodes = {root_path}
        hops: list[dict] = []
        truncated = False

        while queue and len(hops) < graph.MAX_NEIGHBOR_EDGES:
            current, depth = queue.popleft()
            if depth >= graph.MAX_NEIGHBOR_DEPTH:
                continue
            for direction, edge, other in adjacency.get(current, []):
                if edge["edge_id"] in seen_edges:
                    continue
                seen_edges.add(edge["edge_id"])
                hops.append({
                    "depth": depth + 1,
                    "direction": direction,
                    "edge_id": edge["edge_id"],
                    "source_kind": edge["source_kind"],
                    "source": edge["source"],
                    "relation": edge["relation"],
                    "target_kind": edge["target_kind"],
                    "target": edge["target"],
                    "source_coverage": edge["source_coverage"],
                    "target_coverage": edge["target_coverage"],
                    "edge_quality": edge["edge_quality"],
                    "evidence_count": edge["evidence_count"],
                    "evidence": edge["evidence"],
                })
                touched_nodes.add(other)
                if len(hops) >= graph.MAX_NEIGHBOR_EDGES:
                    truncated = True
                    break
                next_depth = depth + 1
                if next_depth < graph.MAX_NEIGHBOR_DEPTH and (
                    other not in expanded_depth or next_depth < expanded_depth[other]
                ):
                    expanded_depth[other] = next_depth
                    queue.append((other, next_depth))
            if truncated:
                break
        if queue:
            truncated = True

        lines = [
            f"Root: {root_path}",
            f"Kind: {root['node_kind']} coverage={root['coverage']}",
            f"Neighborhood: depth<={graph.MAX_NEIGHBOR_DEPTH} edges={len(hops)} nodes={len(touched_nodes)} truncated={truncated}",
        ]
        for hop in hops:
            arrow = "->" if hop["direction"] == "out" else "<-"
            lines.append(
                f"d{hop['depth']} {hop['source_kind']} {hop['source']} {arrow} {hop['relation']} {arrow} "
                f"{hop['target_kind']} {hop['target']} quality={hop['edge_quality']} "
                f"coverage={hop['source_coverage']}->{hop['target_coverage']} evidence={hop['evidence_count']}"
            )
        text = "\n".join(lines)
        if len(text) > graph.MAX_NEIGHBOR_CHARS:
            text = text[:graph.MAX_NEIGHBOR_CHARS] + "\n...[truncated]"
            truncated = True
        neighborhoods.append({
            "root_path": root_path,
            "root_kind": root["node_kind"],
            "root_coverage": root["coverage"],
            "max_depth": graph.MAX_NEIGHBOR_DEPTH,
            "edge_count": len(hops),
            "node_count": len(touched_nodes),
            "truncated": truncated,
            "text": text,
            "hops": hops,
        })
    return neighborhoods


def validation_error(output, rows) -> str | None:
    nodes = list(rows(output / "project_nodes.jsonl"))
    edges = list(rows(output / "project_edges.jsonl"))
    root_paths = [str(node.get("path", "")) for node in nodes if node.get("root")]
    if len(root_paths) != len(set(root_paths)):
        return "multiple canonical project roots share the same path"
    if any(not str(node.get("path", "")).strip() for node in nodes):
        return "project graph contains blank/whitespace node path"
    if any(not str(edge.get("source", "")).strip() or not str(edge.get("target", "")).strip() for edge in edges):
        return "project graph contains blank/whitespace edge endpoint"
    return None
