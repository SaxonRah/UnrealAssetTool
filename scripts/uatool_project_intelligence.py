#!/usr/bin/env python3
"""Bounded project-intelligence graph views over the authoritative typed graph."""
from __future__ import annotations

import argparse
import collections
import heapq
import json
import sqlite3
import sys
from pathlib import Path

import uatool_inspect as inspect_report

DEFAULT_NEIGHBOR_LIMIT = 100
DEFAULT_EVIDENCE_LIMIT = 4
DEFAULT_CANDIDATE_LIMIT = 12
DEFAULT_WHY_DEPTH = 4
DEFAULT_PER_NODE_LIMIT = 96
DEFAULT_MAX_EXPANSIONS = 2000
DEFAULT_SUMMARY_LIMIT = 20

QUALITY_RANK = dict(inspect_report.QUALITY_RANK)
QUALITY_ORDER = tuple(
    name for name, _ in sorted(QUALITY_RANK.items(), key=lambda item: (-item[1], item[0]))
)


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _decode_json(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _row_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _corpus_db(output: Path) -> tuple[Path, Path]:
    root = Path(output).expanduser().resolve()
    db = root if root.suffix.lower() == ".db" else root / "uat.db"
    corpus = db.parent if root.suffix.lower() == ".db" else root
    if not db.is_file():
        raise FileNotFoundError(
            f"uat.db missing: {db}; run `python scripts\\uatool.py pack \"{corpus}\"`"
        )
    stamp = corpus / ".derived_freshness.json"
    if stamp.is_file() and db.stat().st_mtime_ns < stamp.stat().st_mtime_ns:
        raise RuntimeError(
            "uat.db predates the current derived output; rebuild it with "
            f"`python scripts\\uatool.py pack \"{corpus}\"`"
        )
    return corpus, db


def _open_graph(output: Path) -> tuple[Path, sqlite3.Connection]:
    corpus, db = _corpus_db(output)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    if not _table_exists(conn, "project_nodes") or not _table_exists(conn, "project_edges"):
        conn.close()
        raise RuntimeError("uat.db does not contain the typed project graph; repack the current corpus")
    return corpus, conn


def _allowed_qualities(min_quality: str) -> tuple[str, ...]:
    if min_quality not in QUALITY_RANK:
        raise ValueError(f"unknown edge quality: {min_quality}")
    minimum = QUALITY_RANK[min_quality]
    return tuple(name for name, rank in QUALITY_RANK.items() if rank >= minimum)


def _resolve(conn: sqlite3.Connection, term: str, candidate_limit: int) -> dict:
    resolved, variants, candidates, truncated = inspect_report._resolve_target(
        conn, str(term), candidate_limit
    )
    if resolved is None:
        return {
            "found": False,
            "query": str(term),
            "ambiguous": bool(candidates),
            "candidates": candidates,
            "candidates_truncated": truncated,
        }
    primary = max(variants, key=inspect_report._node_sort_key)
    return {
        "found": True,
        "query": str(term),
        "path": resolved,
        "primary": primary,
        "variants": sorted(variants, key=inspect_report._node_sort_key, reverse=True),
    }


def _edge_record(row: sqlite3.Row, focus: str, evidence_limit: int) -> dict:
    item = _row_dict(row)
    evidence = _decode_json(item.pop("evidence_json", ""))
    evidence = evidence if isinstance(evidence, list) else []
    direction = "out" if str(item.get("source", "")) == focus else "in"
    return {
        **item,
        "direction": direction,
        "neighbor_kind": item.get("target_kind", "") if direction == "out" else item.get("source_kind", ""),
        "neighbor_path": item.get("target", "") if direction == "out" else item.get("source", ""),
        "neighbor_coverage": item.get("target_coverage", "") if direction == "out" else item.get("source_coverage", ""),
        "evidence": evidence[:evidence_limit],
        "evidence_truncated": len(evidence) > evidence_limit,
    }


def _quality_case() -> str:
    return (
        "CASE edge_quality "
        "WHEN 'exact_semantic' THEN 3 WHEN 'exact_reference' THEN 2 "
        "WHEN 'unique_dependency_resolution' THEN 1 ELSE 0 END"
    )


def neighbors_report(
    output: Path,
    target: str,
    *,
    limit: int = DEFAULT_NEIGHBOR_LIMIT,
    evidence_limit: int = DEFAULT_EVIDENCE_LIMIT,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    min_quality: str = "generic_package_dependency",
) -> dict:
    if limit < 1 or evidence_limit < 0 or candidate_limit < 1:
        raise ValueError("invalid neighbors limits")
    allowed = _allowed_qualities(min_quality)
    corpus, conn = _open_graph(output)
    try:
        resolved = _resolve(conn, target, candidate_limit)
        if not resolved.get("found"):
            return {"command": "neighbors", **resolved}
        path = str(resolved["path"])
        placeholders = ",".join("?" for _ in allowed)
        where = f"(source=? OR target=?) AND edge_quality IN ({placeholders})"
        total = int(conn.execute(
            f"SELECT COUNT(*) FROM project_edges WHERE {where}",
            (path, path, *allowed),
        ).fetchone()[0])
        rows = list(conn.execute(
            "SELECT edge_id,source_kind,source,relation,target_kind,target,source_coverage,target_coverage,"
            "edge_quality,evidence_count,evidence_json FROM project_edges WHERE " + where +
            f" ORDER BY {_quality_case()} DESC,relation,source,target,edge_id LIMIT ?",
            (path, path, *allowed, limit + 1),
        ))
        truncated = len(rows) > limit
        edges = [_edge_record(row, path, evidence_limit) for row in rows[:limit]]

        relation_counts = []
        for direction, endpoint in (("out", "source"), ("in", "target")):
            for relation, quality, count in conn.execute(
                f"SELECT relation,edge_quality,COUNT(*) FROM project_edges WHERE {endpoint}=? "
                f"AND edge_quality IN ({placeholders}) GROUP BY relation,edge_quality "
                f"ORDER BY {_quality_case()} DESC,relation",
                (path, *allowed),
            ):
                relation_counts.append({
                    "direction": direction,
                    "relation": str(relation),
                    "edge_quality": str(quality),
                    "count": int(count),
                })

        return {
            "command": "neighbors",
            "found": True,
            "query": str(target),
            "resolved_path": path,
            "primary": resolved["primary"],
            "capabilities": inspect_report._read_capabilities(corpus, resolved["primary"]),
            "min_quality": min_quality,
            "total": total,
            "shown": len(edges),
            "truncated": truncated,
            "relation_counts": relation_counts,
            "edges": edges,
        }
    finally:
        conn.close()


def _adjacent_edges(
    conn: sqlite3.Connection,
    path: str,
    *,
    allowed: tuple[str, ...],
    per_node_limit: int,
    evidence_limit: int,
) -> tuple[list[dict], bool, int]:
    placeholders = ",".join("?" for _ in allowed)
    where = f"(source=? OR target=?) AND edge_quality IN ({placeholders})"
    total = int(conn.execute(
        f"SELECT COUNT(*) FROM project_edges WHERE {where}",
        (path, path, *allowed),
    ).fetchone()[0])
    rows = list(conn.execute(
        "SELECT edge_id,source_kind,source,relation,target_kind,target,source_coverage,target_coverage,"
        "edge_quality,evidence_count,evidence_json FROM project_edges WHERE " + where +
        f" ORDER BY {_quality_case()} DESC,relation,source,target,edge_id LIMIT ?",
        (path, path, *allowed, per_node_limit + 1),
    ))
    truncated = len(rows) > per_node_limit
    return [
        _edge_record(row, path, evidence_limit)
        for row in rows[:per_node_limit]
    ], truncated, total


def why_connected_report(
    output: Path,
    source: str,
    target: str,
    *,
    max_depth: int = DEFAULT_WHY_DEPTH,
    per_node_limit: int = DEFAULT_PER_NODE_LIMIT,
    max_expansions: int = DEFAULT_MAX_EXPANSIONS,
    evidence_limit: int = DEFAULT_EVIDENCE_LIMIT,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    min_quality: str = "generic_package_dependency",
) -> dict:
    if max_depth < 1 or per_node_limit < 1 or max_expansions < 1:
        raise ValueError("invalid why-connected search bounds")
    if evidence_limit < 0 or candidate_limit < 1:
        raise ValueError("invalid why-connected limits")
    allowed = _allowed_qualities(min_quality)
    corpus, conn = _open_graph(output)
    try:
        left = _resolve(conn, source, candidate_limit)
        right = _resolve(conn, target, candidate_limit)
        if not left.get("found") or not right.get("found"):
            return {
                "command": "why-connected",
                "found": False,
                "source": left,
                "target": right,
                "path_found": False,
            }
        source_path = str(left["path"])
        target_path = str(right["path"])
        if source_path == target_path:
            return {
                "command": "why-connected",
                "found": True,
                "path_found": True,
                "source": left,
                "target": right,
                "hops": [],
                "hop_count": 0,
                "bottleneck_quality": "same_node",
                "search": {
                    "max_depth": max_depth,
                    "per_node_limit": per_node_limit,
                    "max_expansions": max_expansions,
                    "expansions": 0,
                    "truncated": False,
                    "min_quality": min_quality,
                },
            }

        # Maximize bottleneck edge quality first, then minimize hop count, then
        # maximize summed quality. This favors a slightly longer exact path over
        # a short package-dependency shortcut, while still keeping explanations
        # compact among paths with the same trust floor.
        start_floor = max(QUALITY_RANK.values()) + 1
        queue = [( -start_floor, 0, 0, source_path, source_path, tuple(), frozenset({source_path}) )]
        best: dict[str, tuple[int, int, int]] = {source_path: (start_floor, 0, 0)}
        expansions = 0
        truncated = False
        adjacency_cache: dict[str, tuple[list[dict], bool, int]] = {}
        answer = None

        while queue and expansions < max_expansions:
            neg_floor, depth, neg_sum, signature, current, hops, seen = heapq.heappop(queue)
            floor = -neg_floor
            quality_sum = -neg_sum
            state_score = (floor, -depth, quality_sum)
            if best.get(current, state_score) > state_score:
                continue
            if current == target_path:
                answer = (floor, quality_sum, list(hops))
                break
            if depth >= max_depth:
                continue

            expansions += 1
            cached = adjacency_cache.get(current)
            if cached is None:
                cached = _adjacent_edges(
                    conn,
                    current,
                    allowed=allowed,
                    per_node_limit=per_node_limit,
                    evidence_limit=evidence_limit,
                )
                adjacency_cache[current] = cached
            adjacent, local_truncated, _ = cached
            truncated = truncated or local_truncated

            for edge in adjacent:
                nxt = str(edge.get("neighbor_path", "") or "")
                if not nxt or nxt in seen:
                    continue
                quality = QUALITY_RANK.get(str(edge.get("edge_quality", "")), -1)
                next_floor = min(floor, quality)
                next_depth = depth + 1
                next_sum = quality_sum + quality
                next_score = (next_floor, -next_depth, next_sum)
                if best.get(nxt, (-1, -10**9, -1)) >= next_score:
                    continue
                best[nxt] = next_score
                next_hops = (*hops, edge)
                next_seen = frozenset((*seen, nxt))
                next_signature = signature + "\x1f" + str(edge.get("edge_id", ""))
                heapq.heappush(
                    queue,
                    (-next_floor, next_depth, -next_sum, next_signature, nxt, next_hops, next_seen),
                )

        if queue and expansions >= max_expansions:
            truncated = True

        search = {
            "max_depth": max_depth,
            "per_node_limit": per_node_limit,
            "max_expansions": max_expansions,
            "expansions": expansions,
            "truncated": truncated,
            "min_quality": min_quality,
        }
        if answer is None:
            return {
                "command": "why-connected",
                "found": True,
                "path_found": False,
                "source": left,
                "target": right,
                "search": search,
                "note": "no connection was found within the bounded search; this is not proof that the project graph is disconnected",
            }

        floor, quality_sum, hops = answer
        floor_name = next((name for name, rank in QUALITY_RANK.items() if rank == floor), "")
        return {
            "command": "why-connected",
            "found": True,
            "path_found": True,
            "source": left,
            "target": right,
            "hop_count": len(hops),
            "bottleneck_quality": floor_name,
            "quality_sum": quality_sum,
            "hops": hops,
            "search": search,
            "source_capabilities": inspect_report._read_capabilities(corpus, left["primary"]),
            "target_capabilities": inspect_report._read_capabilities(corpus, right["primary"]),
        }
    finally:
        conn.close()


def _read_capabilities(corpus: Path) -> dict:
    path = corpus / "capabilities.json"
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def project_summary_report(
    output: Path,
    *,
    limit: int = DEFAULT_SUMMARY_LIMIT,
) -> dict:
    if limit < 1:
        raise ValueError("summary limit must be >= 1")
    corpus, conn = _open_graph(output)
    try:
        capabilities = _read_capabilities(corpus)
        node_count = int(conn.execute("SELECT COUNT(*) FROM project_nodes").fetchone()[0])
        edge_count = int(conn.execute("SELECT COUNT(*) FROM project_edges").fetchone()[0])
        root_count = int(conn.execute("SELECT COUNT(*) FROM project_nodes WHERE root=1").fetchone()[0])

        coverage_counts = {
            str(name): int(count)
            for name, count in conn.execute(
                "SELECT coverage,COUNT(*) FROM project_nodes GROUP BY coverage ORDER BY coverage"
            )
        }
        quality_counts = {
            str(name): int(count)
            for name, count in conn.execute(
                "SELECT edge_quality,COUNT(*) FROM project_edges GROUP BY edge_quality"
            )
        }
        root_families = [
            {"family": str(family), "count": int(count)}
            for family, count in conn.execute(
                "SELECT family,COUNT(*) c FROM project_nodes WHERE root=1 GROUP BY family "
                "ORDER BY c DESC,family LIMIT ?",
                (limit,),
            )
        ]
        root_kinds = [
            {"node_kind": str(kind), "count": int(count)}
            for kind, count in conn.execute(
                "SELECT node_kind,COUNT(*) c FROM project_nodes WHERE root=1 GROUP BY node_kind "
                "ORDER BY c DESC,node_kind LIMIT ?",
                (limit,),
            )
        ]
        relations = [
            {"relation": str(relation), "count": int(count)}
            for relation, count in conn.execute(
                "SELECT relation,COUNT(*) c FROM project_edges GROUP BY relation "
                "ORDER BY c DESC,relation LIMIT ?",
                (limit,),
            )
        ]

        neighborhood = {"count": 0, "truncated": 0, "largest": []}
        if _table_exists(conn, "project_neighborhoods"):
            neighborhood["count"] = int(
                conn.execute("SELECT COUNT(*) FROM project_neighborhoods").fetchone()[0]
            )
            neighborhood["truncated"] = int(
                conn.execute("SELECT COUNT(*) FROM project_neighborhoods WHERE truncated!=0").fetchone()[0]
            )
            neighborhood["largest"] = [
                {
                    "root_path": str(path),
                    "root_kind": str(kind),
                    "root_coverage": str(coverage),
                    "edge_count": int(edges),
                    "node_count": int(nodes),
                    "truncated": bool(truncated),
                }
                for path, kind, coverage, edges, nodes, truncated in conn.execute(
                    "SELECT root_path,root_kind,root_coverage,edge_count,node_count,truncated "
                    "FROM project_neighborhoods ORDER BY edge_count DESC,root_path LIMIT ?",
                    (limit,),
                )
            ]

        specialist_tables = {}
        for table in (
            "blueprints", "worlds", "animation_assets", "vfx_assets", "systems_assets",
            "mover_blueprints", "gameplay_camera_assets", "mass_entity_configs",
            "zonegraph_shapes", "gas_abilities", "gas_gameplay_effects", "gas_gameplay_cues",
        ):
            if _table_exists(conn, table):
                specialist_tables[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])

        return {
            "command": "project-summary",
            "corpus": str(corpus),
            "capability_schema_version": capabilities.get("capability_schema_version", 0),
            "schemas": capabilities.get("schemas", {}),
            "partial": bool(
                capabilities.get("corpus", {}).get("partial", False)
                if isinstance(capabilities.get("corpus", {}), dict) else False
            ),
            "canonical_passes": (
                capabilities.get("corpus", {}).get("canonical_passes", [])
                if isinstance(capabilities.get("corpus", {}), dict) else []
            ),
            "families": capabilities.get("families", []),
            "graph": {
                "nodes": node_count,
                "edges": edge_count,
                "roots": root_count,
                "coverage_counts": coverage_counts,
                "quality_counts": dict(sorted(
                    quality_counts.items(),
                    key=lambda item: (-QUALITY_RANK.get(item[0], -1), item[0]),
                )),
                "top_root_families": root_families,
                "top_root_kinds": root_kinds,
                "top_relations": relations,
            },
            "specialist_counts": specialist_tables,
            "neighborhoods": neighborhood,
        }
    finally:
        conn.close()


def _short(value, limit: int = 600) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        text = str(value)
    if len(text) > limit:
        return text[: limit - 15] + "...[truncated]"
    return text


def _print_resolution(value: dict, label: str = "Result") -> None:
    if value.get("found"):
        primary = value.get("primary", {})
        print(
            f"{label}: {value.get('path','')} kind={primary.get('node_kind','')} "
            f"coverage={primary.get('coverage','')} family={primary.get('family','')}"
        )
        return
    candidates = value.get("candidates", [])
    if candidates:
        suffix = "+" if value.get("candidates_truncated") else ""
        print(f"{label}: ambiguous ({len(candidates)}{suffix} candidates shown)")
        for row in candidates:
            print(f"  {row.get('node_kind','')} {row.get('path','')} coverage={row.get('coverage','')}")
    else:
        print(f"{label}: no project-graph node matched {value.get('query','')}")


def print_neighbors(report: dict) -> None:
    print("=== PROJECT NEIGHBORS ===")
    if not report.get("found"):
        _print_resolution(report)
        return
    primary = report.get("primary", {})
    print(
        f"Target: {report.get('resolved_path','')} kind={primary.get('node_kind','')} "
        f"coverage={primary.get('coverage','')} family={primary.get('family','')}"
    )
    print(
        f"Edges: total={report.get('total',0)} shown={report.get('shown',0)} "
        f"truncated={bool(report.get('truncated',False))} min_quality={report.get('min_quality','')}"
    )
    if report.get("relation_counts"):
        print("Relations:")
        for row in report["relation_counts"]:
            print(
                f"  {row.get('direction','')} {row.get('relation','')} "
                f"quality={row.get('edge_quality','')} count={row.get('count',0)}"
            )
    for edge in report.get("edges", []):
        arrow = "->" if edge.get("direction") == "out" else "<-"
        print(
            f"  {arrow} {edge.get('relation','')} {edge.get('neighbor_kind','')} "
            f"{edge.get('neighbor_path','')} quality={edge.get('edge_quality','')} "
            f"coverage={edge.get('neighbor_coverage','')} evidence={edge.get('evidence_count',0)}"
        )
        for evidence in edge.get("evidence", []):
            print(f"      evidence: {_short(evidence)}")
        if edge.get("evidence_truncated"):
            print("      ...[evidence truncated]")


def print_why_connected(report: dict) -> None:
    print("=== WHY CONNECTED ===")
    if not report.get("found"):
        _print_resolution(report.get("source", {}), "Source")
        _print_resolution(report.get("target", {}), "Target")
        return
    _print_resolution(report.get("source", {}), "Source")
    _print_resolution(report.get("target", {}), "Target")
    search = report.get("search", {})
    if not report.get("path_found"):
        print(
            "Path: not found within bounds "
            f"depth={search.get('max_depth',0)} per_node={search.get('per_node_limit',0)} "
            f"expansions={search.get('expansions',0)}/{search.get('max_expansions',0)} "
            f"truncated={bool(search.get('truncated',False))} min_quality={search.get('min_quality','')}"
        )
        if report.get("note"):
            print(f"Note: {report.get('note')}")
        return
    print(
        f"Path: hops={report.get('hop_count',0)} bottleneck={report.get('bottleneck_quality','')} "
        f"truncated_search={bool(search.get('truncated',False))} expansions={search.get('expansions',0)}"
    )
    for index, edge in enumerate(report.get("hops", []), 1):
        arrow = "->" if edge.get("direction") == "out" else "<-"
        print(
            f"  {index}. {edge.get('source_kind','')} {edge.get('source','')} {arrow} "
            f"{edge.get('relation','')} {arrow} {edge.get('target_kind','')} {edge.get('target','')} "
            f"quality={edge.get('edge_quality','')} evidence={edge.get('evidence_count',0)}"
        )
        for evidence in edge.get("evidence", []):
            print(f"       evidence: {_short(evidence)}")
        if edge.get("evidence_truncated"):
            print("       ...[evidence truncated]")


def print_project_summary(report: dict) -> None:
    print("=== PROJECT SUMMARY ===")
    schemas = report.get("schemas", {}) if isinstance(report.get("schemas", {}), dict) else {}
    print(
        f"Corpus: partial={bool(report.get('partial',False))} passes={','.join(report.get('canonical_passes',[])) or '-'}"
    )
    if schemas:
        print(
            "Schemas: " + " ".join(
                f"{key}={schemas.get(key,0)}"
                for key in ("structural", "world", "animation", "vfx", "systems", "derived")
            )
        )
    graph = report.get("graph", {})
    print(
        f"Graph: nodes={graph.get('nodes',0)} edges={graph.get('edges',0)} roots={graph.get('roots',0)}"
    )
    if graph.get("coverage_counts"):
        print("Coverage: " + " ".join(f"{k}={v}" for k, v in graph["coverage_counts"].items()))
    if graph.get("quality_counts"):
        print("Edge quality: " + " ".join(f"{k}={v}" for k, v in graph["quality_counts"].items()))
    if report.get("specialist_counts"):
        print("Specialist rows:")
        for key, value in sorted(report["specialist_counts"].items()):
            print(f"  {key}: {value}")
    if graph.get("top_root_families"):
        print("Top root families:")
        for row in graph["top_root_families"]:
            print(f"  {row.get('family','') or '<none>'}: {row.get('count',0)}")
    if graph.get("top_relations"):
        print("Top relations:")
        for row in graph["top_relations"]:
            print(f"  {row.get('relation','')}: {row.get('count',0)}")
    neighborhoods = report.get("neighborhoods", {})
    if neighborhoods.get("count"):
        print(
            f"Neighborhoods: count={neighborhoods.get('count',0)} "
            f"truncated={neighborhoods.get('truncated',0)}"
        )


def _require_current(output: Path) -> Path:
    public = inspect_report._canonical_module()
    resolved = Path(output).expanduser().resolve()
    if public is not None:
        public._require_current_derive(resolved)
    return resolved


def _neighbors_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool neighbors",
        description="show bounded typed one-hop relationships around an asset/object",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("target", help="exact graph path or unambiguous fragment")
    parser.add_argument("--limit", type=int, default=DEFAULT_NEIGHBOR_LIMIT)
    parser.add_argument("--evidence-limit", type=int, default=DEFAULT_EVIDENCE_LIMIT)
    parser.add_argument("--candidate-limit", type=int, default=DEFAULT_CANDIDATE_LIMIT)
    parser.add_argument("--min-quality", choices=QUALITY_ORDER, default="generic_package_dependency")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = neighbors_report(
        _require_current(Path(args.output)),
        args.target,
        limit=args.limit,
        evidence_limit=args.evidence_limit,
        candidate_limit=args.candidate_limit,
        min_quality=args.min_quality,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_neighbors(report)
    return 0 if report.get("found") else 2


def _why_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool why-connected",
        description="find and explain the strongest bounded typed-graph path between two objects",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("source", help="first exact graph path or unambiguous fragment")
    parser.add_argument("target", help="second exact graph path or unambiguous fragment")
    parser.add_argument("--max-depth", type=int, default=DEFAULT_WHY_DEPTH)
    parser.add_argument("--per-node-limit", type=int, default=DEFAULT_PER_NODE_LIMIT)
    parser.add_argument("--max-expansions", type=int, default=DEFAULT_MAX_EXPANSIONS)
    parser.add_argument("--evidence-limit", type=int, default=DEFAULT_EVIDENCE_LIMIT)
    parser.add_argument("--candidate-limit", type=int, default=DEFAULT_CANDIDATE_LIMIT)
    parser.add_argument("--min-quality", choices=QUALITY_ORDER, default="generic_package_dependency")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = why_connected_report(
        _require_current(Path(args.output)),
        args.source,
        args.target,
        max_depth=args.max_depth,
        per_node_limit=args.per_node_limit,
        max_expansions=args.max_expansions,
        evidence_limit=args.evidence_limit,
        candidate_limit=args.candidate_limit,
        min_quality=args.min_quality,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_why_connected(report)
    return 0 if report.get("found") else 2


def _summary_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool project-summary",
        description="summarize corpus capability, specialist counts and typed project-graph structure",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("--limit", type=int, default=DEFAULT_SUMMARY_LIMIT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = project_summary_report(_require_current(Path(args.output)), limit=args.limit)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_project_summary(report)
    return 0


def install(runtime_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if bool(getattr(runtime_module, "_project_intelligence_commands_installed", False)):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1:
            command = sys.argv[1]
            handlers = {
                "neighbors": (_neighbors_cli, 47),
                "why-connected": (_why_cli, 48),
                "project-summary": (_summary_cli, 49),
            }
            if command in handlers:
                handler, error_code = handlers[command]
                try:
                    return handler(sys.argv[2:])
                except Exception as exc:
                    print(f"ERROR: {exc}", file=sys.stderr)
                    return error_code
        return original_main()

    runtime_module.main = main
    runtime_module._project_intelligence_commands_installed = True
