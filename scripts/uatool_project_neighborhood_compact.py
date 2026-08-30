#!/usr/bin/env python3
"""Compact schema-14 project neighborhoods.

`project_edges.jsonl` is the authoritative typed/provenance graph. A bounded
neighborhood therefore only needs to record which edge was selected, at what
traversal depth/direction, plus the quality/coverage classification required on
every hop. Duplicating complete source/target paths and evidence inside every
root neighborhood can expand a large project by hundreds of megabytes.

SQLite packing reconstructs readable neighborhood text from authoritative edges
so query behavior remains useful without storing that duplicated text in JSONL.
"""
from __future__ import annotations

import json

HOP_FIELDS = (
    "depth",
    "direction",
    "edge_id",
    "edge_quality",
    "source_coverage",
    "target_coverage",
    "evidence_count",
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


def _edge_map(conn) -> dict[str, dict]:
    result = {}
    for row in conn.execute(
        "SELECT edge_id,source_kind,source,relation,target_kind,target,source_coverage,target_coverage,edge_quality,evidence_count "
        "FROM project_edges"
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


def enrich_database(conn, output, rows, *, max_chars: int) -> None:
    """Populate SQLite neighborhood text from compact JSONL + project_edges."""
    edge_by_id = _edge_map(conn)
    for row in rows(output / "project_neighborhoods.jsonl"):
        text = render_text(row, edge_by_id, max_chars)
        conn.execute(
            "UPDATE project_neighborhoods SET text=?, json=? WHERE root_path=?",
            (
                text,
                json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                str(row.get("root_path", "")),
            ),
        )


def validation_error(output, rows) -> str | None:
    edges = {str(row.get("edge_id", "")): row for row in rows(output / "project_edges.jsonl")}
    for neighborhood in rows(output / "project_neighborhoods.jsonl"):
        hops = neighborhood.get("hops", []) if isinstance(neighborhood.get("hops", []), list) else []
        if "text" in neighborhood:
            return "schema-14 project neighborhood unexpectedly embeds duplicated text"
        if int(neighborhood.get("edge_count", 0)) != len(hops):
            return f"compact neighborhood edge count mismatch: {neighborhood.get('root_path','')}"
        for hop in hops:
            if not isinstance(hop, dict):
                return f"invalid compact neighborhood hop: {neighborhood.get('root_path','')}"
            extra = set(hop) - set(HOP_FIELDS)
            if extra:
                return f"compact neighborhood duplicates edge fields {sorted(extra)}"
            edge = edges.get(str(hop.get("edge_id", "")))
            if edge is None:
                return f"compact neighborhood references unknown edge: {hop.get('edge_id','')}"
            for field in ("edge_quality", "source_coverage", "target_coverage", "evidence_count"):
                if hop.get(field) != edge.get(field):
                    return f"compact neighborhood {field} mismatch: {hop.get('edge_id','')}"
    return None
