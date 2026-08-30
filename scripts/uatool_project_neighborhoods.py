#!/usr/bin/env python3
"""Deterministic quality-prioritized project neighborhoods.

This module does not create or remove graph facts. It selects which already-derived
project edges fit inside the bounded retrieval neighborhood. Strong semantic and
reference evidence is preferred; package plumbing is traversed last.
"""
from __future__ import annotations

import collections

PACKAGE_PLUMBING_RELATIONS = {
    "member_of_package",
    "contains_asset",
    "depends_on_package",
}

COMPACT_HOP_FIELDS = (
    "depth",
    "direction",
    "edge_id",
    "edge_quality",
    "source_coverage",
    "target_coverage",
    "evidence_count",
)


def rebuild(
    nodes,
    edges,
    *,
    quality_rank,
    coverage_rank,
    max_depth,
    max_edges,
    max_chars,
    compact=False,
):
    """Return deterministic bounded neighborhoods over an existing project graph.

    With ``compact=True`` the traversal emits schema-14 hop references directly.
    This avoids materializing the old expanded source/target/evidence payload and
    rendered text only to discard it immediately afterward.
    """

    adjacency = collections.defaultdict(list)
    for edge in edges:
        adjacency[edge["source"]].append(("out", edge, edge["target"]))
        adjacency[edge["target"]].append(("in", edge, edge["source"]))

    def priority(item):
        direction, edge, _ = item
        relation = str(edge.get("relation", ""))
        quality = str(edge.get("edge_quality", ""))
        return (
            relation in PACKAGE_PLUMBING_RELATIONS,
            -int(quality_rank.get(quality, -1)),
            0 if direction == "out" else 1,
            relation,
            str(edge.get("source_kind", "")),
            str(edge.get("source", "")),
            str(edge.get("target_kind", "")),
            str(edge.get("target", "")),
            str(edge.get("edge_id", "")),
        )

    for path in adjacency:
        adjacency[path].sort(key=priority)

    root_nodes = {}
    for node in nodes:
        if not node.get("root") or node["path"] not in adjacency:
            continue
        previous = root_nodes.get(node["path"])
        if previous is None or coverage_rank.get(node["coverage"], 0) > coverage_rank.get(previous["coverage"], 0):
            root_nodes[node["path"]] = node

    neighborhoods = []
    for root_path in sorted(root_nodes):
        root = root_nodes[root_path]
        queue = collections.deque([(root_path, 0)])
        expanded_depth = {root_path: 0}
        seen_edges = set()
        touched_nodes = {root_path}
        hops = []
        hop_text_chars = 0
        truncated = False

        while queue and len(hops) < max_edges:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for direction, edge, other in adjacency.get(current, []):
                edge_id = str(edge.get("edge_id", ""))
                if edge_id in seen_edges:
                    continue
                seen_edges.add(edge_id)

                expanded_hop = {
                    "depth": depth + 1,
                    "direction": direction,
                    "edge_id": edge_id,
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
                }
                if compact:
                    hops.append({key: expanded_hop[key] for key in COMPACT_HOP_FIELDS})
                else:
                    hops.append(expanded_hop)

                arrow = "->" if direction == "out" else "<-"
                hop_text_chars += len(
                    f"d{depth + 1} {edge['source_kind']} {edge['source']} {arrow} {edge['relation']} {arrow} "
                    f"{edge['target_kind']} {edge['target']} quality={edge['edge_quality']} "
                    f"coverage={edge['source_coverage']}->{edge['target_coverage']} evidence={edge['evidence_count']}"
                )
                touched_nodes.add(other)

                if len(hops) >= max_edges:
                    truncated = True
                    break

                next_depth = depth + 1
                if next_depth < max_depth and (
                    other not in expanded_depth or next_depth < expanded_depth[other]
                ):
                    expanded_depth[other] = next_depth
                    queue.append((other, next_depth))

            if truncated:
                break

        if queue:
            truncated = True

        header_lines = [
            f"Root: {root_path}",
            f"Kind: {root['node_kind']} coverage={root['coverage']}",
            f"Neighborhood: depth<={max_depth} edges={len(hops)} nodes={len(touched_nodes)} truncated={truncated}",
        ]
        line_count = len(header_lines) + len(hops)
        text_chars = sum(len(line) for line in header_lines) + hop_text_chars + max(0, line_count - 1)
        if text_chars > max_chars:
            truncated = True

        row = {
            "root_path": root_path,
            "root_kind": root["node_kind"],
            "root_coverage": root["coverage"],
            "max_depth": max_depth,
            "edge_count": len(hops),
            "node_count": len(touched_nodes),
            "truncated": truncated,
            "hops": hops,
        }

        if not compact:
            lines = list(header_lines)
            for hop in hops:
                arrow = "->" if hop["direction"] == "out" else "<-"
                lines.append(
                    f"d{hop['depth']} {hop['source_kind']} {hop['source']} {arrow} {hop['relation']} {arrow} "
                    f"{hop['target_kind']} {hop['target']} quality={hop['edge_quality']} "
                    f"coverage={hop['source_coverage']}->{hop['target_coverage']} evidence={hop['evidence_count']}"
                )
            text = "\n".join(lines)
            if len(text) > max_chars:
                text = text[:max_chars] + "\n...[truncated]"
            row["text"] = text

        neighborhoods.append(row)

    return neighborhoods
