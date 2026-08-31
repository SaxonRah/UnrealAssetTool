#!/usr/bin/env python3
"""Compact project-neighborhood storage backed by authoritative project edges.

Logical derived schema 15 keeps the same neighborhood model: each selected hop
has `{depth,direction,edge_id}`. Physical storage version 2 removes repeated
hashed edge IDs by referring to the row order of `project_edges.jsonl`.

Each physical hop is a signed 1-based edge ordinal:
- positive => traversal direction `out`
- negative => traversal direction `in`
- absolute value minus one => row index in `project_edges.jsonl`

`depth_ends` stores cumulative hop counts for depths 1..max_depth. The public
`compact()` helper remains schema-15 compatible; the canonical writer converts
that logical form to ordinal storage only when `project_neighborhoods.jsonl` is
written. Query/validation consumers reconstruct the logical hop model on demand.
"""
from __future__ import annotations

import json
from pathlib import Path

import uatool_project_graph as project_graph
import uatool_runtime as runtime

STORAGE_SCHEMA_VERSION = 2
ENCODING = "project_neighborhood_ordinals_v1"

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
PHYSICAL_FIELDS = set(ROOT_FIELDS) | {
    "encoding",
    "depth_ends",
    "hop_edges",
}


def compact(neighborhoods: list[dict]) -> list[dict]:
    """Legacy/public schema-15 compaction: keep only traversal hop metadata."""
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


def _edge_ids(project_edges: list[dict]) -> list[str]:
    ids = [str(row.get("edge_id", "")) for row in project_edges]
    if any(not edge_id for edge_id in ids):
        raise RuntimeError("project edge missing edge_id while compacting neighborhoods")
    if len(set(ids)) != len(ids):
        raise RuntimeError("duplicate project edge_id while compacting neighborhoods")
    return ids


def compact_ordinals(
    neighborhoods: list[dict],
    project_edges: list[dict],
) -> list[dict]:
    """Convert schema-15 logical hop rows to ordinal-backed physical rows."""
    edge_ids = _edge_ids(project_edges)
    edge_index = {edge_id: index for index, edge_id in enumerate(edge_ids)}
    result: list[dict] = []

    for row in compact(neighborhoods):
        hops = row.get("hops", [])
        max_depth = int(row.get("max_depth", 0) or 0)
        depths: list[int] = []
        signed_edges: list[int] = []
        previous_depth = 0
        seen_ordinals: set[int] = set()

        for hop in hops:
            edge_id = str(hop.get("edge_id", ""))
            if edge_id not in edge_index:
                raise RuntimeError(f"project neighborhood references unknown edge: {edge_id}")
            depth = int(hop.get("depth", 0) or 0)
            if depth < 1 or (max_depth > 0 and depth > max_depth):
                raise RuntimeError(f"project neighborhood depth out of range: {edge_id}")
            if depth < previous_depth:
                raise RuntimeError(
                    f"project neighborhood hop depths are not monotonic: {row.get('root_path','')}"
                )
            previous_depth = depth
            direction = hop.get("direction")
            if direction not in {"in", "out"}:
                raise RuntimeError(f"invalid project neighborhood direction: {edge_id}")

            ordinal = edge_index[edge_id] + 1
            if ordinal in seen_ordinals:
                raise RuntimeError(
                    f"duplicate project neighborhood edge: {row.get('root_path','')} {edge_id}"
                )
            seen_ordinals.add(ordinal)
            depths.append(depth)
            signed_edges.append(ordinal if direction == "out" else -ordinal)

        if int(row.get("edge_count", 0) or 0) != len(hops):
            raise RuntimeError(
                f"project neighborhood edge count mismatch: {row.get('root_path','')}"
            )

        depth_ends: list[int] = []
        cursor = 0
        for depth in range(1, max_depth + 1):
            while cursor < len(depths) and depths[cursor] == depth:
                cursor += 1
            depth_ends.append(cursor)
        if cursor != len(depths):
            raise RuntimeError(
                f"project neighborhood contains depth above max_depth: {row.get('root_path','')}"
            )

        compact_row = {key: row.get(key) for key in ROOT_FIELDS}
        compact_row["encoding"] = ENCODING
        compact_row["depth_ends"] = depth_ends
        compact_row["hop_edges"] = signed_edges
        result.append(compact_row)

    return result


def _validate_physical_row(row: dict, *, edge_count: int, context: str) -> int:
    extra = set(row) - PHYSICAL_FIELDS
    missing = PHYSICAL_FIELDS - set(row)
    if missing or extra:
        raise RuntimeError(
            f"project neighborhood storage fields mismatch in {context}: "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
    if row.get("encoding") != ENCODING:
        raise RuntimeError(
            f"unexpected project neighborhood encoding in {context}: {row.get('encoding')!r}"
        )

    max_depth = row.get("max_depth")
    declared_edges = row.get("edge_count")
    depth_ends = row.get("depth_ends")
    hop_edges = row.get("hop_edges")
    if not isinstance(max_depth, int) or max_depth < 0:
        raise RuntimeError(f"invalid project neighborhood max_depth in {context}")
    if not isinstance(declared_edges, int) or declared_edges < 0:
        raise RuntimeError(f"invalid project neighborhood edge_count in {context}")
    if not isinstance(depth_ends, list) or len(depth_ends) != max_depth:
        raise RuntimeError(f"invalid project neighborhood depth_ends in {context}")
    if not isinstance(hop_edges, list) or len(hop_edges) != declared_edges:
        raise RuntimeError(f"invalid project neighborhood hop_edges in {context}")

    previous = 0
    for value in depth_ends:
        if not isinstance(value, int) or value < previous or value > declared_edges:
            raise RuntimeError(f"invalid project neighborhood depth boundary in {context}")
        previous = value
    if (depth_ends[-1] if depth_ends else 0) != declared_edges:
        raise RuntimeError(f"project neighborhood final depth boundary mismatch in {context}")

    seen: set[int] = set()
    for signed in hop_edges:
        if not isinstance(signed, int) or isinstance(signed, bool) or signed == 0:
            raise RuntimeError(f"invalid project neighborhood signed edge ordinal in {context}")
        ordinal = abs(signed)
        if ordinal < 1 or ordinal > edge_count:
            raise RuntimeError(
                f"project neighborhood edge ordinal out of range in {context}: {ordinal}"
            )
        if ordinal in seen:
            raise RuntimeError(
                f"duplicate project neighborhood edge ordinal in {context}: {ordinal}"
            )
        seen.add(ordinal)

    return declared_edges


def _validate_legacy_row(row: dict, edge_by_id: dict[str, dict], context: str) -> None:
    hops = row.get("hops", []) if isinstance(row.get("hops", []), list) else []
    if "text" in row:
        raise RuntimeError("schema-15 project neighborhood unexpectedly embeds duplicated text")
    if int(row.get("edge_count", 0) or 0) != len(hops):
        raise RuntimeError(f"compact neighborhood edge count mismatch: {row.get('root_path','')}")
    max_depth = int(row.get("max_depth", 0) or 0)
    seen: set[str] = set()
    for hop in hops:
        if not isinstance(hop, dict):
            raise RuntimeError(f"invalid compact neighborhood hop in {context}")
        extra = set(hop) - set(HOP_FIELDS)
        if extra:
            raise RuntimeError(f"compact neighborhood duplicates edge fields {sorted(extra)}")
        edge_id = str(hop.get("edge_id", ""))
        if edge_id not in edge_by_id:
            raise RuntimeError(f"compact neighborhood references unknown edge: {edge_id}")
        if edge_id in seen:
            raise RuntimeError(f"duplicate compact neighborhood edge: {edge_id}")
        seen.add(edge_id)
        depth = int(hop.get("depth", 0) or 0)
        if depth < 1 or (max_depth > 0 and depth > max_depth):
            raise RuntimeError(f"compact neighborhood depth out of range: {edge_id}")
        if hop.get("direction") not in {"in", "out"}:
            raise RuntimeError(f"invalid compact neighborhood direction: {edge_id}")


def logical_hops(row: dict, edge_ids: list[str]) -> list[dict]:
    """Expand one physical row to logical `{depth,direction,edge_id}` hops."""
    _validate_physical_row(
        row,
        edge_count=len(edge_ids),
        context=str(row.get("root_path", "")),
    )
    result: list[dict] = []
    start = 0
    for depth, end in enumerate(row["depth_ends"], 1):
        for signed in row["hop_edges"][start:end]:
            ordinal = abs(signed)
            result.append(
                {
                    "depth": depth,
                    "direction": "out" if signed > 0 else "in",
                    "edge_id": edge_ids[ordinal - 1],
                }
            )
        start = end
    return result


def expand(row: dict, edge_ids: list[str]) -> dict:
    if row.get("encoding") != ENCODING:
        return compact([row])[0]
    logical = {key: row.get(key) for key in ROOT_FIELDS}
    logical["hops"] = logical_hops(row, edge_ids)
    return logical


def _logical_rows(output: Path, rows):
    edge_rows = list(rows(output / "project_edges.jsonl"))
    edge_ids = _edge_ids(edge_rows)
    for row in rows(output / "project_neighborhoods.jsonl"):
        yield expand(row, edge_ids)


def _update_storage_manifest(output: Path) -> None:
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"invalid manifest.json while recording project neighborhood storage: {exc}"
        ) from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("manifest.json root is not an object")
    manifest["project_neighborhood_storage_schema_version"] = STORAGE_SCHEMA_VERSION
    manifest["project_neighborhood_encoding"] = ENCODING
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def validation_error(output, rows) -> str | None:
    output = Path(output)
    try:
        edges = list(rows(output / "project_edges.jsonl"))
        edge_ids = _edge_ids(edges)
        edge_by_id = {edge_id: row for edge_id, row in zip(edge_ids, edges)}
        neighborhoods = list(rows(output / "project_neighborhoods.jsonl"))
        seen_roots: set[str] = set()
        physical_seen = False
        for index, neighborhood in enumerate(neighborhoods, 1):
            context = f"{output / 'project_neighborhoods.jsonl'}:{index}"
            root = str(neighborhood.get("root_path", ""))
            if not root:
                return f"project neighborhood missing root_path in {context}"
            if root in seen_roots:
                return f"duplicate project neighborhood root: {root}"
            seen_roots.add(root)
            if neighborhood.get("encoding") == ENCODING:
                physical_seen = True
                _validate_physical_row(
                    neighborhood,
                    edge_count=len(edge_ids),
                    context=context,
                )
                if len(logical_hops(neighborhood, edge_ids)) != int(
                    neighborhood.get("edge_count", 0)
                ):
                    return f"project neighborhood expansion count mismatch: {root}"
            else:
                _validate_legacy_row(neighborhood, edge_by_id, context)
    except RuntimeError as exc:
        return str(exc)

    if physical_seen:
        _update_storage_manifest(output)
    return None


def _edge_map_for_ids(conn, edge_ids: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    unique = sorted({str(edge_id) for edge_id in edge_ids if edge_id})
    for start in range(0, len(unique), 800):
        chunk = unique[start:start + 800]
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        for row in conn.execute(
            "SELECT edge_id,source_kind,source,relation,target_kind,target,"
            "source_coverage,target_coverage,edge_quality,evidence_count "
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


def _edge_map_for_ordinals(conn, ordinals: list[int]) -> dict[int, dict]:
    result: dict[int, dict] = {}
    unique = sorted({int(value) for value in ordinals if int(value) > 0})
    for start in range(0, len(unique), 800):
        chunk = unique[start:start + 800]
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        for db_row in conn.execute(
            "SELECT rowid,edge_id,source_kind,source,relation,target_kind,target,"
            "source_coverage,target_coverage,edge_quality,evidence_count "
            f"FROM project_edges WHERE rowid IN ({placeholders})",
            chunk,
        ):
            result[int(db_row[0])] = {
                "edge_id": str(db_row[1]),
                "source_kind": str(db_row[2]),
                "source": str(db_row[3]),
                "relation": str(db_row[4]),
                "target_kind": str(db_row[5]),
                "target": str(db_row[6]),
                "source_coverage": str(db_row[7]),
                "target_coverage": str(db_row[8]),
                "edge_quality": str(db_row[9]),
                "evidence_count": int(db_row[10]),
            }
    return result


def render_text(row: dict, edge_map: dict, max_chars: int) -> str:
    lines = [
        f"Root: {row.get('root_path','')}",
        f"Kind: {row.get('root_kind','')} coverage={row.get('root_coverage','')}",
        f"Neighborhood: depth<={int(row.get('max_depth',0))} "
        f"edges={int(row.get('edge_count',0))} "
        f"nodes={int(row.get('node_count',0))} truncated={bool(row.get('truncated',False))}",
    ]

    def append_edge(depth: int, direction: str, edge: dict | None) -> None:
        if not edge:
            return
        arrow = "->" if direction == "out" else "<-"
        lines.append(
            f"d{depth} {edge['source_kind']} {edge['source']} {arrow} "
            f"{edge['relation']} {arrow} {edge['target_kind']} {edge['target']} "
            f"quality={edge['edge_quality']} "
            f"coverage={edge['source_coverage']}->{edge['target_coverage']} "
            f"evidence={edge['evidence_count']}"
        )

    if row.get("encoding") == ENCODING:
        start = 0
        for depth, end in enumerate(row.get("depth_ends", []), 1):
            for signed in row.get("hop_edges", [])[start:end]:
                append_edge(
                    depth,
                    "out" if int(signed) > 0 else "in",
                    edge_map.get(abs(int(signed))),
                )
            start = end
    else:
        for hop in row.get("hops", []):
            if not isinstance(hop, dict):
                continue
            append_edge(
                int(hop.get("depth", 0) or 0),
                str(hop.get("direction", "")),
                edge_map.get(str(hop.get("edge_id", ""))),
            )

    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text


def _matching_edges(conn, pattern: str) -> tuple[set[int], set[str]]:
    rows = list(
        conn.execute(
            "SELECT rowid,edge_id FROM project_edges "
            "WHERE source LIKE ? OR relation LIKE ? OR target LIKE ? "
            "OR edge_quality LIKE ? OR evidence_json LIKE ?",
            (pattern, pattern, pattern, pattern, pattern),
        )
    )
    return ({int(row[0]) for row in rows}, {str(row[1]) for row in rows})


def _matching_neighborhood_rows(conn, pattern: str, limit: int):
    selected: list = []
    seen_roots: set[str] = set()

    for db_row in conn.execute(
        "SELECT root_path,root_kind,root_coverage,edge_count,node_count,truncated,json "
        "FROM project_neighborhoods "
        "WHERE root_path LIKE ? OR root_kind LIKE ? LIMIT ?",
        (pattern, pattern, limit),
    ):
        selected.append(db_row)
        seen_roots.add(str(db_row[0]))
    if len(selected) >= limit:
        return selected

    matching_ordinals, matching_ids = _matching_edges(conn, pattern)
    if not matching_ordinals and not matching_ids:
        return selected

    for db_row in conn.execute(
        "SELECT root_path,root_kind,root_coverage,edge_count,node_count,truncated,json "
        "FROM project_neighborhoods"
    ):
        root = str(db_row[0])
        if root in seen_roots:
            continue
        try:
            row = json.loads(str(db_row[6]))
        except (TypeError, json.JSONDecodeError):
            continue
        matched = False
        if row.get("encoding") == ENCODING:
            values = row.get("hop_edges", [])
            matched = isinstance(values, list) and any(
                abs(int(value)) in matching_ordinals for value in values
            )
        else:
            matched = any(
                isinstance(hop, dict)
                and str(hop.get("edge_id", "")) in matching_ids
                for hop in row.get("hops", [])
            )
        if matched:
            selected.append(db_row)
            seen_roots.add(root)
            if len(selected) >= limit:
                break
    return selected


def query(conn, print_rows, pattern: str, limit: int, *, max_chars: int) -> None:
    """Project query with neighborhood text reconstructed from compact storage."""
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_nodes'"
    ).fetchone():
        return

    print("\n[project nodes]")
    print_rows(
        conn.execute(
            "SELECT node_kind,path,coverage,family,class_path FROM project_nodes "
            "WHERE path LIKE ? OR node_kind LIKE ? OR family LIKE ? OR class_path LIKE ? LIMIT ?",
            (pattern, pattern, pattern, pattern, limit),
        ),
        ("node_kind", "path", "coverage", "family", "class_path"),
    )

    print("\n[project edges]")
    print_rows(
        conn.execute(
            "SELECT source_kind,source,relation,target_kind,target,edge_quality,"
            "source_coverage,target_coverage FROM project_edges "
            "WHERE source LIKE ? OR relation LIKE ? OR target LIKE ? "
            "OR edge_quality LIKE ? OR evidence_json LIKE ? LIMIT ?",
            (pattern, pattern, pattern, pattern, pattern, limit),
        ),
        (
            "source_kind",
            "source",
            "relation",
            "target_kind",
            "target",
            "edge_quality",
            "source_coverage",
            "target_coverage",
        ),
    )

    print("\n[project neighborhoods]")
    rendered = []
    for db_row in _matching_neighborhood_rows(conn, pattern, limit):
        try:
            row = json.loads(str(db_row[6]))
        except (TypeError, json.JSONDecodeError):
            continue
        if row.get("encoding") == ENCODING:
            ordinals = [
                abs(int(value))
                for value in row.get("hop_edges", [])
                if isinstance(value, int) and not isinstance(value, bool) and value != 0
            ]
            edge_map = _edge_map_for_ordinals(conn, ordinals)
        else:
            edge_ids = [
                str(hop.get("edge_id", ""))
                for hop in row.get("hops", [])
                if isinstance(hop, dict) and hop.get("edge_id")
            ]
            edge_map = _edge_map_for_ids(conn, edge_ids)
        rendered.append(
            {
                "root_path": str(db_row[0]),
                "root_kind": str(db_row[1]),
                "root_coverage": str(db_row[2]),
                "edge_count": int(db_row[3]),
                "node_count": int(db_row[4]),
                "truncated": int(db_row[5]),
                "text": render_text(row, edge_map, max_chars),
            }
        )
    print_rows(
        rendered,
        (
            "root_path",
            "root_kind",
            "root_coverage",
            "edge_count",
            "node_count",
            "truncated",
            "text",
        ),
    )


def _install() -> None:
    if getattr(runtime, "_project_neighborhood_ordinal_storage_installed", False):
        return

    original_project_validation = project_graph.validation_error
    original_write = runtime._write

    def project_validation(output, rows):
        output = Path(output)

        def logical_rows(path):
            path = Path(path)
            if path.name == "project_neighborhoods.jsonl":
                return _logical_rows(output, rows)
            return rows(path)

        return original_project_validation(output, logical_rows)

    def write(path, values):
        path = Path(path)
        if path.name == "project_neighborhoods.jsonl":
            project_edges = list(runtime._rows(path.parent / "project_edges.jsonl"))
            values = compact_ordinals(list(values), project_edges)
            count = original_write(path, values)
            _update_storage_manifest(path.parent)
            return count
        return original_write(path, values)

    project_graph.validation_error = project_validation
    runtime._write = write
    runtime._project_neighborhood_ordinal_storage_installed = True


_install()
