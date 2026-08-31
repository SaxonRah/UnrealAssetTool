#!/usr/bin/env python3
"""Compact project-neighborhood storage backed by authoritative project edges.

Logical derived schema 15 keeps the same neighborhood model: each selected hop
has `{depth,direction,edge_id}`. Physical storage version 2 removes repeated
hashed edge IDs by referring to the zero-based order of `project_edges.jsonl`.

Each physical hop is a signed 1-based edge ordinal:
- positive => traversal direction `out`
- negative => traversal direction `in`
- absolute value minus one => row index in `project_edges.jsonl`

`depth_ends` stores cumulative hop counts for depths 1..max_depth. This is
lossless because the neighborhood builder emits hops in nondecreasing depth
order. Query/database consumers reconstruct the logical hop model on demand.
"""
from __future__ import annotations

import json
from pathlib import Path

import uatool_project_graph as project_graph
import uatool_project_neighborhoods as neighborhood_policy
import uatool_runtime as runtime

STORAGE_SCHEMA_VERSION = 2
ENCODING = "project_neighborhood_ordinals_v1"

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


def _edge_ids(project_edges: list[dict]) -> list[str]:
    ids = [str(row.get("edge_id", "")) for row in project_edges]
    if any(not edge_id for edge_id in ids):
        raise RuntimeError("project edge missing edge_id while compacting neighborhoods")
    if len(set(ids)) != len(ids):
        raise RuntimeError("duplicate project edge_id while compacting neighborhoods")
    return ids


def compact(neighborhoods: list[dict], project_edges: list[dict]) -> list[dict]:
    """Convert logical schema-15 hop objects to ordinal-backed physical rows."""
    edge_ids = _edge_ids(project_edges)
    edge_index = {edge_id: index for index, edge_id in enumerate(edge_ids)}
    result: list[dict] = []

    for row in neighborhoods:
        hops = row.get("hops", [])
        if not isinstance(hops, list):
            raise RuntimeError(
                f"project neighborhood hops is not a list: {row.get('root_path','')}"
            )
        max_depth = int(row.get("max_depth", 0) or 0)
        depths: list[int] = []
        signed_edges: list[int] = []
        previous_depth = 0
        seen_ordinals: set[int] = set()

        for hop in hops:
            if not isinstance(hop, dict):
                raise RuntimeError(
                    f"project neighborhood hop is not an object: {row.get('root_path','')}"
                )
            extra = set(hop) - {"depth", "direction", "edge_id"}
            if extra:
                raise RuntimeError(
                    f"project neighborhood logical hop has unexpected fields {sorted(extra)}"
                )
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
    logical = {key: row.get(key) for key in ROOT_FIELDS}
    logical["hops"] = logical_hops(row, edge_ids)
    return logical


def _logical_rows(output: Path, rows):
    edge_rows = list(rows(output / "project_edges.jsonl"))
    edge_ids = _edge_ids(edge_rows)
    for row in rows(output / "project_neighborhoods.jsonl"):
        if row.get("encoding") == ENCODING:
            yield expand(row, edge_ids)
        else:
            yield row


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
        neighborhoods = list(rows(output / "project_neighborhoods.jsonl"))
        seen_roots: set[str] = set()
        for index, neighborhood in enumerate(neighborhoods, 1):
            context = f"{output / 'project_neighborhoods.jsonl'}:{index}"
            if "text" in neighborhood:
                return "project neighborhood storage unexpectedly embeds duplicated text"
            root = str(neighborhood.get("root_path", ""))
            if not root:
                return f"project neighborhood missing root_path in {context}"
            if root in seen_roots:
                return f"duplicate project neighborhood root: {root}"
            seen_roots.add(root)
            _validate_physical_row(
                neighborhood,
                edge_count=len(edge_ids),
                context=context,
            )
            if len(logical_hops(neighborhood, edge_ids)) != int(
                neighborhood.get("edge_count", 0)
            ):
                return f"project neighborhood expansion count mismatch: {root}"
    except RuntimeError as exc:
        return str(exc)

    _update_storage_manifest(output)
    return None


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


def render_text(row: dict, edge_by_ordinal: dict[int, dict], max_chars: int) -> str:
    lines = [
        f"Root: {row.get('root_path','')}",
        f"Kind: {row.get('root_kind','')} coverage={row.get('root_coverage','')}",
        f"Neighborhood: depth<={int(row.get('max_depth',0))} "
        f"edges={int(row.get('edge_count',0))} "
        f"nodes={int(row.get('node_count',0))} truncated={bool(row.get('truncated',False))}",
    ]
    start = 0
    for depth, end in enumerate(row.get("depth_ends", []), 1):
        for signed in row.get("hop_edges", [])[start:end]:
            edge = edge_by_ordinal.get(abs(int(signed)))
            if not edge:
                continue
            arrow = "->" if int(signed) > 0 else "<-"
            lines.append(
                f"d{depth} {edge['source_kind']} {edge['source']} {arrow} "
                f"{edge['relation']} {arrow} {edge['target_kind']} {edge['target']} "
                f"quality={edge['edge_quality']} "
                f"coverage={edge['source_coverage']}->{edge['target_coverage']} "
                f"evidence={edge['evidence_count']}"
            )
        start = end
    text = "\n".join(lines)
    if len(text) > max_chars:
        return text[:max_chars] + "\n...[truncated]"
    return text


def _matching_edge_ordinals(conn, pattern: str) -> set[int]:
    return {
        int(row[0])
        for row in conn.execute(
            "SELECT rowid FROM project_edges "
            "WHERE source LIKE ? OR relation LIKE ? OR target LIKE ? "
            "OR edge_quality LIKE ? OR evidence_json LIKE ?",
            (pattern, pattern, pattern, pattern, pattern),
        )
    }


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

    matching_ordinals = _matching_edge_ordinals(conn, pattern)
    if not matching_ordinals:
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
        values = row.get("hop_edges", [])
        if not isinstance(values, list):
            continue
        if any(abs(int(value)) in matching_ordinals for value in values):
            selected.append(db_row)
            seen_roots.add(root)
            if len(selected) >= limit:
                break
    return selected


def query(conn, print_rows, pattern: str, limit: int, *, max_chars: int) -> None:
    """Project query with neighborhood text reconstructed from ordinal storage."""
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
        ordinals = [
            abs(int(value))
            for value in row.get("hop_edges", [])
            if isinstance(value, int) and not isinstance(value, bool) and value != 0
        ]
        edge_by_ordinal = _edge_map_for_ordinals(conn, ordinals)
        rendered.append(
            {
                "root_path": str(db_row[0]),
                "root_kind": str(db_row[1]),
                "root_coverage": str(db_row[2]),
                "edge_count": int(db_row[3]),
                "node_count": int(db_row[4]),
                "truncated": int(db_row[5]),
                "text": render_text(row, edge_by_ordinal, max_chars),
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
    if getattr(neighborhood_policy, "_ordinal_storage_installed", False):
        return

    original_rebuild = neighborhood_policy.rebuild
    original_project_validation = project_graph.validation_error
    original_write = runtime._write

    def rebuild(*args, **kwargs):
        logical = original_rebuild(*args, **kwargs)
        if not bool(kwargs.get("compact", False)):
            return logical
        if len(args) >= 2:
            project_edges = args[1]
        else:
            project_edges = kwargs.get("project_edges")
        if not isinstance(project_edges, list):
            project_edges = list(project_edges or [])
        return compact(logical, project_edges)

    def project_validation(output, rows):
        output = Path(output)

        def logical_rows(path):
            path = Path(path)
            if path.name == "project_neighborhoods.jsonl":
                return _logical_rows(output, rows)
            return rows(path)

        return original_project_validation(output, logical_rows)

    def write(path, values):
        count = original_write(path, values)
        path = Path(path)
        if path.name == "project_neighborhoods.jsonl":
            _update_storage_manifest(path.parent)
        return count

    neighborhood_policy.rebuild = rebuild
    project_graph.validation_error = project_validation
    runtime._write = write
    neighborhood_policy._ordinal_storage_installed = True


_install()
