#!/usr/bin/env python3
"""Compact schema-15 project neighborhoods.

`project_edges.jsonl` is the authoritative typed/provenance graph. A bounded
neighborhood therefore only needs to record which edge was selected and at what
traversal depth/direction. Edge quality, source/target coverage, evidence count,
paths, relation and provenance are all reconstructed from the authoritative edge
row instead of being repeated in every root neighborhood.

SQLite keeps the same compact representation. Human-readable neighborhood text
is reconstructed on demand at query time by joining compact hop `edge_id`s to
`project_edges`, avoiding another large duplicated text column in uat.db.
"""
from __future__ import annotations

import json
import sqlite3

HOP_FIELDS = (
    "depth",
    "direction",
    "edge_id",
)
ROOT_FIELDS = (
    "root_path",
    "root_kind",
    "root_coverage",
    "max_depth",
    "edge_count",
    "node_count",
    "truncated",
)


def compact(neighborhoods: list[dict]) -> list[dict]:
    result = []
    for row in neighborhoods:
        compact_row = {key: row.get(key) for key in ROOT_FIELDS}
        compact_row["hops"] = [
            {key: hop.get(key) for key in HOP_FIELDS}
            for hop in row.get("hops", [])
            if isinstance(hop, dict)
        ]
        result.append(compact_row)
    return result


def _edge_map_for_ids(conn, edge_ids: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    unique = sorted({str(edge_id) for edge_id in edge_ids if edge_id})
    # Stay comfortably below SQLite's traditional bind-variable limit.
    for start in range(0, len(unique), 800):
        chunk = unique[start:start + 800]
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(
            "SELECT edge_id,source_kind,source,relation,target_kind,target,source_coverage,target_coverage,edge_quality,evidence_count "
            f"FROM project_edges WHERE edge_id IN ({placeholders})",
            chunk,
        ):
            result[str(row[0])] = {
                "edge_id": str(row[0]),
                "source_kind": str(row[1]),
                "source": str(row[2]),
                "relation": str(row[3]),
                "target_kind": str(row[4]),
                "target": str(row[5]),
                "source_coverage": str(row[6]),
                "target_coverage": str(row[7]),
                "edge_quality": str(row[8]),
                "evidence_count": int(row[9]),
            }
    return result


def render_text(row: dict, edge_by_id: dict[str, dict], max_chars: int) -> str:
    lines = [
        f"Root: {row.get('root_path','')}",
        f"Kind: {row.get('root_kind','')} coverage={row.get('root_coverage','')}",
        f"Neighborhood: depth<={int(row.get('max_depth',0))} edges={int(row.get('edge_count',0))} "
        f"nodes={int(row.get('node_count',0))} truncated={bool(row.get('truncated',False))}",
    ]
    for hop in row.get("hops", []):
        edge = edge_by_id.get(str(hop.get("edge_id", "")))
        if not edge:
            continue
        arrow = "->" if hop.get("direction") == "out" else "<-"
        lines.append(
            f"d{int(hop.get('depth',0))} {edge['source_kind']} {edge['source']} {arrow} "
            f"{edge['relation']} {arrow} {edge['target_kind']} {edge['target']} "
            f"quality={edge['edge_quality']} coverage={edge['source_coverage']}->{edge['target_coverage']} "
            f"evidence={edge['evidence_count']}"
        )
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text


def _matching_neighborhood_rows(conn, pattern: str, limit: int):
    """Find roots by root metadata or by any authoritative edge in their hops."""
    try:
        return list(conn.execute(
            """
            SELECT DISTINCT n.root_path,n.root_kind,n.root_coverage,n.edge_count,n.node_count,n.truncated,n.json
            FROM project_neighborhoods n
            WHERE n.root_path LIKE ? OR n.root_kind LIKE ?
               OR EXISTS (
                    SELECT 1
                    FROM json_each(n.json, '$.hops') h
                    JOIN project_edges e ON e.edge_id=json_extract(h.value, '$.edge_id')
                    WHERE e.source LIKE ? OR e.relation LIKE ? OR e.target LIKE ?
                       OR e.edge_quality LIKE ? OR e.evidence_json LIKE ?
               )
            LIMIT ?
            """,
            (pattern, pattern, pattern, pattern, pattern, pattern, pattern, limit),
        ))
    except sqlite3.OperationalError:
        # Very old SQLite builds may lack JSON1. Root search still works and the
        # separate project-edge query remains fully available.
        return list(conn.execute(
            """
            SELECT root_path,root_kind,root_coverage,edge_count,node_count,truncated,json
            FROM project_neighborhoods
            WHERE root_path LIKE ? OR root_kind LIKE ?
            LIMIT ?
            """,
            (pattern, pattern, limit),
        ))


def query(conn, print_rows, pattern: str, limit: int, *, max_chars: int) -> None:
    """Schema-15 project query with neighborhood text rendered on demand."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_nodes'").fetchone():
        return

    print("\n[project nodes]")
    print_rows(conn.execute(
        "SELECT node_kind,path,coverage,family,class_path FROM project_nodes "
        "WHERE path LIKE ? OR node_kind LIKE ? OR family LIKE ? OR class_path LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, limit),
    ), ("node_kind", "path", "coverage", "family", "class_path"))

    print("\n[project edges]")
    print_rows(conn.execute(
        "SELECT source_kind,source,relation,target_kind,target,edge_quality,source_coverage,target_coverage "
        "FROM project_edges WHERE source LIKE ? OR relation LIKE ? OR target LIKE ? "
        "OR edge_quality LIKE ? OR evidence_json LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, pattern, limit),
    ), ("source_kind", "source", "relation", "target_kind", "target", "edge_quality", "source_coverage", "target_coverage"))

    print("\n[project neighborhoods]")
    rendered = []
    for db_row in _matching_neighborhood_rows(conn, pattern, limit):
        try:
            row = json.loads(str(db_row[6]))
        except (TypeError, json.JSONDecodeError):
            continue
        edge_ids = [
            str(hop.get("edge_id", ""))
            for hop in row.get("hops", [])
            if isinstance(hop, dict) and hop.get("edge_id")
        ]
        edge_by_id = _edge_map_for_ids(conn, edge_ids)
        rendered.append({
            "root_path": str(db_row[0]),
            "root_kind": str(db_row[1]),
            "root_coverage": str(db_row[2]),
            "edge_count": int(db_row[3]),
            "node_count": int(db_row[4]),
            "truncated": int(db_row[5]),
            "text": render_text(row, edge_by_id, max_chars),
        })
    print_rows(
        rendered,
        ("root_path", "root_kind", "root_coverage", "edge_count", "node_count", "truncated", "text"),
    )


def validation_error(output, rows) -> str | None:
    edges = {str(row.get("edge_id", "")): row for row in rows(output / "project_edges.jsonl")}
    for neighborhood in rows(output / "project_neighborhoods.jsonl"):
        hops = neighborhood.get("hops", []) if isinstance(neighborhood.get("hops", []), list) else []
        if "text" in neighborhood:
            return "schema-15 project neighborhood unexpectedly embeds duplicated text"
        if int(neighborhood.get("edge_count", 0)) != len(hops):
            return f"compact neighborhood edge count mismatch: {neighborhood.get('root_path','')}"
        max_depth = int(neighborhood.get("max_depth", 0))
        for hop in hops:
            if not isinstance(hop, dict):
                return f"invalid compact neighborhood hop: {neighborhood.get('root_path','')}"
            extra = set(hop) - set(HOP_FIELDS)
            if extra:
                return f"compact neighborhood duplicates edge fields {sorted(extra)}"
            edge_id = str(hop.get("edge_id", ""))
            if edge_id not in edges:
                return f"compact neighborhood references unknown edge: {edge_id}"
            try:
                depth = int(hop.get("depth", 0))
            except (TypeError, ValueError):
                return f"invalid compact neighborhood depth: {edge_id}"
            if depth < 1 or (max_depth > 0 and depth > max_depth):
                return f"compact neighborhood depth out of range: {edge_id}"
            if hop.get("direction") not in {"in", "out"}:
                return f"invalid compact neighborhood direction: {edge_id}"
    return None
