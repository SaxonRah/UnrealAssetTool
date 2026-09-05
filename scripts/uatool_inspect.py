#!/usr/bin/env python3
"""Provenance-aware asset/object dossier over existing UnrealAssetTool truth."""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

DEFAULT_EDGE_LIMIT = 80
DEFAULT_EVIDENCE_LIMIT = 6
DEFAULT_CHILD_LIMIT = 8
DEFAULT_CANDIDATE_LIMIT = 12

COVERAGE_RANK = {
    "external_or_excluded": 0,
    "generic_only": 1,
    "partial": 2,
    "first_class_depth_pending": 3,
    "first_class": 4,
}
QUALITY_RANK = {
    "generic_package_dependency": 0,
    "unique_dependency_resolution": 1,
    "exact_reference": 2,
    "exact_semantic": 3,
}

# These are retrieval joins over already-normalized SQLite tables. They do not
# define new semantic truth. A table/column pair is simply ignored when absent,
# which keeps inspect useful on focused and older compatible corpora.
ROOT_FACT_SOURCES = (
    ("assets", "object_path"),
    ("blueprints", "object_path"),
    ("worlds", "world_path"),
    ("world_actors", "actor_path"),
    ("world_components", "component_path"),
    ("animation_assets", "animation_path"),
    ("vfx_assets", "vfx_path"),
    ("systems_assets", "systems_path"),
    ("behavior_trees", "behavior_tree_path"),
    ("blackboards", "blackboard_path"),
    ("eqs_queries", "eqs_path"),
    ("statetrees", "statetree_path"),
    ("pcg_graphs", "pcg_path"),
    ("materials", "material_path"),
    ("level_sequences", "sequence_path"),
    ("audio_assets", "audio_path"),
    ("input_actions", "action_path"),
    ("input_mapping_contexts", "context_path"),
    ("gameplay_data_assets", "asset_path"),
    ("curve_tables", "table_path"),
    ("primary_data_assets", "asset_path"),
    ("mover_blueprints", "blueprint_path"),
    ("mover_components", "component_path"),
    ("gameplay_camera_assets", "camera_asset_path"),
    ("gameplay_camera_rigs", "rig_path"),
    ("mass_entity_configs", "config_path"),
    ("mass_spawners", "spawner_path"),
    ("mass_spawn_generator_assets", "generator_asset_path"),
    ("mass_agent_components", "component_path"),
    ("zonegraph_shapes", "shape_path"),
    ("gas_abilities", "ability_path"),
    ("gas_ability_sets", "ability_set_path"),
    ("gas_gameplay_effects", "gameplay_effect_path"),
    ("gas_gameplay_cues", "gameplay_cue_path"),
    ("gas_attribute_sets", "attribute_set_class"),
)

CHILD_FACT_SOURCES = (
    # Generic Blueprint semantics.
    ("blueprint_semantic_statements", "blueprint_path"),
    ("blueprint_semantic_blocks", "blueprint_path"),
    # Sequencer / Enhanced Input / gameplay data.
    ("movie_scene_bindings", "sequence_path"),
    ("movie_scene_tracks", "sequence_path"),
    ("movie_scene_sections", "sequence_path"),
    ("movie_scene_channels", "sequence_path"),
    ("input_mappings", "context_path"),
    ("data_table_rows", "table_path"),
    ("data_table_fields", "table_path"),
    ("curve_table_rows", "table_path"),
    ("curve_table_keys", "table_path"),
    # Mover.
    ("mover_modes", "component_path"),
    ("mover_modes", "blueprint_path"),
    ("mover_settings", "owner_path"),
    ("mover_transitions", "owner_path"),
    ("mover_transition_behaviors", "owner_path"),
    ("mover_transition_routes", "owner_path"),
    # Gameplay Cameras.
    ("gameplay_camera_nodes", "rig_path"),
    ("gameplay_camera_node_edges", "rig_path"),
    ("gameplay_camera_transitions", "owner_path"),
    ("gameplay_camera_rig_references", "asset_path"),
    # Mass / authored ZoneGraph.
    ("mass_entity_traits", "config_path"),
    ("mass_spawner_entity_types", "spawner_path"),
    ("mass_spawner_generators", "spawner_path"),
    ("zonegraph_shape_points", "shape_path"),
    # GAS.
    ("gas_ability_triggers", "ability_path"),
    ("gas_ability_costs", "ability_path"),
    ("gas_ability_set_abilities", "ability_set_path"),
    ("gas_ability_set_effects", "ability_set_path"),
    ("gas_ability_set_attributes", "ability_set_path"),
    ("gas_gameplay_effect_components", "gameplay_effect_path"),
    ("gas_gameplay_effect_modifiers", "gameplay_effect_path"),
    ("gas_gameplay_effect_executions", "gameplay_effect_path"),
    ("gas_gameplay_effect_execution_modifiers", "gameplay_effect_path"),
    ("gas_gameplay_effect_cues", "gameplay_effect_path"),
    ("gas_attributes", "attribute_set_class"),
)

_FAMILY_MAP = {
    "blueprint": "blueprint",
    "world": "world",
    "animation": "animation",
    "vfx": "vfx",
    "ai": "ai_authored",
    "pcg": "pcg",
    "material": "materials",
}


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}
    except sqlite3.DatabaseError:
        return set()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _row_dict(row: sqlite3.Row) -> dict:
    return {key: row[key] for key in row.keys()}


def _decode_json(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _canonical_row(row: sqlite3.Row) -> dict:
    values = _row_dict(row)
    raw = values.pop("json", None)
    decoded = _decode_json(raw)
    return decoded if isinstance(decoded, dict) else values


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _node_sort_key(row: dict):
    return (
        COVERAGE_RANK.get(str(row.get("coverage", "")), -1),
        int(bool(row.get("root", False))),
        int(str(row.get("family", "")) != "asset_registry"),
        int(str(row.get("node_kind", "")) != "package"),
        str(row.get("node_kind", "")),
    )


def _node_variants(conn: sqlite3.Connection, path: str) -> list[dict]:
    return [
        _row_dict(row)
        for row in conn.execute(
            "SELECT node_id,node_kind,path,coverage,class_path,package_name,family,root "
            "FROM project_nodes WHERE path=? ORDER BY node_kind",
            (path,),
        )
    ]


def _candidate_row(conn: sqlite3.Connection, path: str) -> dict:
    variants = _node_variants(conn, path)
    primary = max(variants, key=_node_sort_key)
    return {
        "path": path,
        "node_kind": primary.get("node_kind", ""),
        "coverage": primary.get("coverage", ""),
        "family": primary.get("family", ""),
        "class_path": primary.get("class_path", ""),
    }


def _resolve_target(
    conn: sqlite3.Connection,
    term: str,
    candidate_limit: int,
) -> tuple[str | None, list[dict], list[dict], bool]:
    exact = _node_variants(conn, term)
    if exact:
        return term, exact, [], False

    pattern = f"%{_escape_like(term)}%"
    # Query distinct paths first. LIMIT candidate_limit+1 is enough to prove
    # ambiguity without sampling a bounded number of node variants. This avoids
    # falsely treating one path as unique when that path has many node kinds and
    # another matching path falls beyond the old row sample.
    paths = [
        str(row[0])
        for row in conn.execute(
            "SELECT DISTINCT path FROM project_nodes WHERE path LIKE ? ESCAPE '\\' "
            "ORDER BY path LIMIT ?",
            (pattern, candidate_limit + 1),
        )
        if str(row[0])
    ]
    if not paths:
        return None, [], [], False
    if len(paths) == 1:
        variants = _node_variants(conn, paths[0])
        return paths[0], variants, [_candidate_row(conn, paths[0])], False

    truncated = len(paths) > candidate_limit
    shown = paths[:candidate_limit]
    return None, [], [_candidate_row(conn, path) for path in shown], truncated


def _capability_family(node: dict) -> str:
    family = str(node.get("family", "") or "")
    kind = str(node.get("node_kind", "") or "")
    if family in _FAMILY_MAP:
        return _FAMILY_MAP[family]
    lowered = kind.lower()
    if (
        lowered.startswith("gameplay_ability")
        or lowered.startswith("gameplay_effect")
        or lowered.startswith("gameplay_cue")
        or lowered.startswith("gameplay_attribute")
    ):
        return "gas"
    if lowered.startswith("mover"):
        return "mover"
    if lowered.startswith("gameplay_camera") or lowered.startswith("camera_rig"):
        return "gameplay_cameras"
    if lowered.startswith("mass_") or lowered.startswith("zonegraph"):
        return "mass_zonegraph"
    if lowered in {"input_action", "input_mapping_context"}:
        return "enhanced_input"
    if "gameplay_tag" in lowered:
        return "gameplay_tags"
    if lowered in {"data_table", "curve_table", "gameplay_data_asset"}:
        return "gameplay_data"
    if lowered == "primary_data_asset":
        return "primary_data_assets"
    if lowered == "level_sequence":
        return "sequencer"
    if "sound" in lowered or "metasound" in lowered or lowered.startswith("audio"):
        return "audio"
    return ""


def _read_capabilities(corpus: Path, primary: dict) -> dict:
    path = corpus / "capabilities.json"
    if not path.is_file():
        return {}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(manifest, dict):
        return {}

    family_name = _capability_family(primary)
    family = {}
    families = manifest.get("families", [])
    if family_name and isinstance(families, list):
        for row in families:
            if isinstance(row, dict) and str(row.get("family", "")) == family_name:
                family = row
                break
    return {
        "capability_schema_version": manifest.get("capability_schema_version", 0),
        "schemas": manifest.get("schemas", {}),
        "corpus": manifest.get("corpus", {}),
        "family": family,
    }


def _fact_rows(
    conn: sqlite3.Connection,
    target: str,
    sources,
    limit: int | None = None,
) -> list[dict]:
    facts = []
    seen = set()
    for table, column in sources:
        key = (table, column)
        if key in seen:
            continue
        seen.add(key)
        if not _table_exists(conn, table):
            continue
        if column not in _table_columns(conn, table):
            continue

        if limit is None:
            row = conn.execute(
                f'SELECT * FROM "{table}" WHERE "{column}"=? LIMIT 1',
                (target,),
            ).fetchone()
            if row is not None:
                facts.append({
                    "table": table,
                    "identity_column": column,
                    "record": _canonical_row(row),
                })
            continue

        count = int(
            conn.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{column}"=?',
                (target,),
            ).fetchone()[0]
        )
        if count <= 0:
            continue
        rows = [
            _canonical_row(row)
            for row in conn.execute(
                f'SELECT * FROM "{table}" WHERE "{column}"=? LIMIT ?',
                (target, limit),
            )
        ]
        facts.append({
            "table": table,
            "identity_column": column,
            "count": count,
            "shown": len(rows),
            "truncated": count > len(rows),
            "records": rows,
        })
    return facts


def _edge_rows(
    conn: sqlite3.Connection,
    target: str,
    edge_limit: int,
    evidence_limit: int,
) -> tuple[list[dict], dict]:
    outgoing = int(
        conn.execute("SELECT COUNT(*) FROM project_edges WHERE source=?", (target,)).fetchone()[0]
    )
    incoming = int(
        conn.execute("SELECT COUNT(*) FROM project_edges WHERE target=?", (target,)).fetchone()[0]
    )
    rows = list(conn.execute(
        "SELECT edge_id,source_kind,source,relation,target_kind,target,source_coverage,target_coverage,"
        "edge_quality,evidence_count,evidence_json FROM project_edges WHERE source=? OR target=? "
        "ORDER BY CASE edge_quality "
        "WHEN 'exact_semantic' THEN 3 WHEN 'exact_reference' THEN 2 "
        "WHEN 'unique_dependency_resolution' THEN 1 ELSE 0 END DESC, relation, source, target, edge_id LIMIT ?",
        (target, target, edge_limit + 1),
    ))
    truncated = len(rows) > edge_limit
    rows = rows[:edge_limit]

    result = []
    for row in rows:
        item = _row_dict(row)
        evidence = _decode_json(item.pop("evidence_json", ""))
        evidence = evidence if isinstance(evidence, list) else []
        direction = "out" if str(item.get("source", "")) == target else "in"
        item.update({
            "direction": direction,
            "other_kind": item.get("target_kind", "") if direction == "out" else item.get("source_kind", ""),
            "other_path": item.get("target", "") if direction == "out" else item.get("source", ""),
            "other_coverage": item.get("target_coverage", "") if direction == "out" else item.get("source_coverage", ""),
            "evidence": evidence[:evidence_limit],
            "evidence_truncated": len(evidence) > evidence_limit,
        })
        result.append(item)

    relation_counts = []
    for direction, endpoint in (("out", "source"), ("in", "target")):
        for relation, count in conn.execute(
            f"SELECT relation,COUNT(*) FROM project_edges WHERE {endpoint}=? GROUP BY relation ORDER BY relation",
            (target,),
        ):
            relation_counts.append({
                "direction": direction,
                "relation": str(relation),
                "count": int(count),
            })

    quality_counts = collections.Counter()
    for quality, count in conn.execute(
        "SELECT edge_quality,COUNT(*) FROM project_edges WHERE source=? OR target=? GROUP BY edge_quality",
        (target, target),
    ):
        quality_counts[str(quality)] = int(count)

    return result, {
        "outgoing": outgoing,
        "incoming": incoming,
        "total": outgoing + incoming,
        "shown": len(result),
        "truncated": truncated,
        "relation_counts": relation_counts,
        "quality_counts": dict(sorted(
            quality_counts.items(),
            key=lambda item: (-QUALITY_RANK.get(item[0], -1), item[0]),
        )),
    }


def build_report(
    output: Path,
    term: str,
    *,
    edge_limit: int = DEFAULT_EDGE_LIMIT,
    evidence_limit: int = DEFAULT_EVIDENCE_LIMIT,
    child_limit: int = DEFAULT_CHILD_LIMIT,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> dict:
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
    if edge_limit < 1 or evidence_limit < 0 or child_limit < 0 or candidate_limit < 1:
        raise ValueError("invalid inspect limits")

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        if not _table_exists(conn, "project_nodes") or not _table_exists(conn, "project_edges"):
            raise RuntimeError("uat.db does not contain the typed project graph; repack the current corpus")

        resolved, variants, candidates, candidate_truncated = _resolve_target(
            conn, str(term), candidate_limit
        )
        if resolved is None:
            return {
                "found": False,
                "query": str(term),
                "ambiguous": bool(candidates),
                "candidates": candidates,
                "candidates_truncated": candidate_truncated,
            }

        primary = max(variants, key=_node_sort_key)
        variants = sorted(variants, key=_node_sort_key, reverse=True)
        edges, edge_summary = _edge_rows(conn, resolved, edge_limit, evidence_limit)
        return {
            "found": True,
            "query": str(term),
            "resolved_path": resolved,
            "primary": primary,
            "node_variants": variants,
            "capabilities": _read_capabilities(corpus, primary),
            "canonical_facts": _fact_rows(conn, resolved, ROOT_FACT_SOURCES),
            "child_facts": _fact_rows(conn, resolved, CHILD_FACT_SOURCES, child_limit),
            "graph": edge_summary,
            "edges": edges,
        }
    finally:
        conn.close()


def _short(value, max_chars: int = 360) -> str:
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    else:
        text = str(value)
    if len(text) > max_chars:
        return text[: max_chars - 15] + "...[truncated]"
    return text


def _record_lines(record: dict, *, field_limit: int = 24) -> list[str]:
    lines = []
    omitted = {"raw_value", "text", "hops", "evidence", "properties"}
    for key in sorted(record):
        if key in omitted:
            continue
        value = record[key]
        if value in ("", None, [], {}):
            continue
        lines.append(f"    {key}: {_short(value)}")
        if len(lines) >= field_limit:
            lines.append("    ...[fields truncated]")
            break
    return lines


def _child_headline(record: dict):
    for key in (
        "text", "operation", "mode_name", "transition_class", "node_name",
        "row_name", "field_name", "key", "attribute_name", "trigger_tag",
        "component_class", "trait_class", "point_type",
    ):
        if record.get(key) not in ("", None):
            return record.get(key)
    return record


def print_report(report: dict) -> None:
    if not report.get("found"):
        print("=== UNREAL ASSET DOSSIER ===")
        print(f"Query: {report.get('query', '')}")
        candidates = report.get("candidates", [])
        if candidates:
            suffix = "+" if report.get("candidates_truncated") else ""
            print(f"Result: ambiguous ({len(candidates)}{suffix} candidates shown)")
            for row in candidates:
                print(
                    f"  {row.get('node_kind','')} {row.get('path','')} "
                    f"coverage={row.get('coverage','')} family={row.get('family','')}"
                )
        else:
            print("Result: no project-graph node matched")
        return

    primary = report.get("primary", {})
    print("=== UNREAL ASSET DOSSIER ===")
    print(f"Target: {report.get('resolved_path', '')}")
    print(
        "Primary: "
        f"kind={primary.get('node_kind','')} coverage={primary.get('coverage','')} "
        f"family={primary.get('family','')} class={primary.get('class_path','')}"
    )
    if primary.get("package_name"):
        print(f"Package: {primary.get('package_name')}")

    capabilities = report.get("capabilities", {})
    schemas = capabilities.get("schemas", {}) if isinstance(capabilities.get("schemas", {}), dict) else {}
    corpus = capabilities.get("corpus", {}) if isinstance(capabilities.get("corpus", {}), dict) else {}
    if schemas:
        print(
            "Corpus: "
            f"partial={bool(corpus.get('partial', False))} "
            + " ".join(
                f"{key}={schemas.get(key, 0)}"
                for key in ("structural", "world", "animation", "vfx", "systems", "derived")
            )
        )
    family = capabilities.get("family", {}) if isinstance(capabilities.get("family", {}), dict) else {}
    if family:
        print(
            "Capability: "
            f"{family.get('family','')} contract={family.get('contract_coverage','')} "
            f"corpus={family.get('corpus_coverage','')} "
            f"runtime_state={family.get('runtime_state_captured', False)}"
        )
        if family.get("boundary"):
            print(f"Boundary: {family.get('boundary')}")

    variants = report.get("node_variants", [])
    if len(variants) > 1:
        print(f"\n[node variants] {len(variants)}")
        for row in variants:
            print(
                f"  {row.get('node_kind','')} coverage={row.get('coverage','')} "
                f"family={row.get('family','')} root={bool(row.get('root', False))}"
            )

    facts = report.get("canonical_facts", [])
    if facts:
        print("\n[canonical root facts]")
        for fact in facts:
            print(f"  [{fact.get('table','')}] via {fact.get('identity_column','')}")
            for line in _record_lines(fact.get("record", {})):
                print(line)

    children = report.get("child_facts", [])
    if children:
        print("\n[canonical/derived child facts]")
        for fact in children:
            print(
                f"  [{fact.get('table','')}] via {fact.get('identity_column','')} "
                f"count={fact.get('count',0)} shown={fact.get('shown',0)} "
                f"truncated={bool(fact.get('truncated', False))}"
            )
            for index, record in enumerate(fact.get("records", [])):
                print(f"    #{index}: {_short(_child_headline(record), 520)}")

    graph = report.get("graph", {})
    print(
        "\n[graph] "
        f"outgoing={graph.get('outgoing',0)} incoming={graph.get('incoming',0)} "
        f"shown={graph.get('shown',0)} truncated={bool(graph.get('truncated', False))}"
    )
    quality_counts = graph.get("quality_counts", {})
    if quality_counts:
        print("  quality: " + " ".join(f"{key}={value}" for key, value in quality_counts.items()))
    relations = graph.get("relation_counts", [])
    if relations:
        print("  relations:")
        for row in relations:
            print(f"    {row.get('direction','')} {row.get('relation','')}: {row.get('count',0)}")

    for edge in report.get("edges", []):
        arrow = "->" if edge.get("direction") == "out" else "<-"
        print(
            f"  {arrow} {edge.get('relation','')} {edge.get('other_kind','')} "
            f"{edge.get('other_path','')} quality={edge.get('edge_quality','')} "
            f"coverage={edge.get('other_coverage','')} evidence={edge.get('evidence_count',0)}"
        )
        for evidence in edge.get("evidence", []):
            print(f"      evidence: {_short(evidence, 700)}")
        if edge.get("evidence_truncated"):
            print("      ...[evidence truncated]")


def _canonical_module(modules=None):
    target = Path(__file__).with_name("uatool.py").resolve()
    values = tuple(modules if modules is not None else sys.modules.values())
    for module in values:
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            if Path(module_file).resolve() != target:
                continue
        except (OSError, RuntimeError, TypeError):
            continue
        if hasattr(module, "_require_current_derive"):
            return module
    return None


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool inspect",
        description="print a provenance-aware asset/object dossier from the existing typed project graph",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("target", help="exact object/asset path or an unambiguous path fragment")
    parser.add_argument("--edge-limit", type=int, default=DEFAULT_EDGE_LIMIT, help="maximum graph edges to print")
    parser.add_argument("--evidence-limit", type=int, default=DEFAULT_EVIDENCE_LIMIT, help="maximum evidence records per edge")
    parser.add_argument("--child-limit", type=int, default=DEFAULT_CHILD_LIMIT, help="maximum child rows shown per specialist table")
    parser.add_argument("--candidate-limit", type=int, default=DEFAULT_CANDIDATE_LIMIT, help="maximum ambiguous path candidates to show")
    parser.add_argument("--json", action="store_true", help="emit the dossier as machine-readable JSON")
    args = parser.parse_args(argv)
    if args.edge_limit < 1:
        parser.error("--edge-limit must be >= 1")
    if args.evidence_limit < 0:
        parser.error("--evidence-limit must be >= 0")
    if args.child_limit < 0:
        parser.error("--child-limit must be >= 0")
    if args.candidate_limit < 1:
        parser.error("--candidate-limit must be >= 1")

    public = _canonical_module()
    output = Path(args.output).expanduser().resolve()
    if public is not None:
        public._require_current_derive(output)
    report = build_report(
        output,
        args.target,
        edge_limit=args.edge_limit,
        evidence_limit=args.evidence_limit,
        child_limit=args.child_limit,
        candidate_limit=args.candidate_limit,
    )
    if args.json:
        # Keep machine-readable output safe under Windows redirection/pipes.
        # JSON Unicode escapes round-trip exactly while avoiding dependence on
        # the active stdout text encoding when output is not attached to a
        # Unicode-aware console.
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print_report(report)
    return 0 if report.get("found") else 2


def install(runtime_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if bool(getattr(runtime_module, "_inspect_command_installed", False)):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "inspect":
            try:
                return _cli(sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 46
        return original_main()

    runtime_module.main = main
    runtime_module._inspect_command_installed = True
