#!/usr/bin/env python3
"""Derived animation relations, summaries, and bounded context.

Only canonical scanner facts are joined. Display names are never used to infer
asset identity, and generic package dependencies are not promoted to animation
semantic edges.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re

DERIVED_FILES = (
    "animation_relations.jsonl",
    "animation_context.jsonl",
    "animation_summaries.jsonl",
)
MAX_CONTEXT_LINKS_PER_ASSET = 200
MAX_CONTEXT_CHARS = 262144

_SQL = """
CREATE TABLE animation_relations(
 relation_id TEXT PRIMARY KEY,source_kind TEXT NOT NULL,source TEXT NOT NULL,
 relation TEXT NOT NULL,target_kind TEXT NOT NULL,target TEXT NOT NULL,
 target_coverage TEXT NOT NULL,evidence_count INTEGER NOT NULL,evidence_json TEXT NOT NULL);
CREATE INDEX animation_relations_source_idx ON animation_relations(source,relation);
CREATE INDEX animation_relations_target_idx ON animation_relations(target,relation);
CREATE INDEX animation_relations_kind_idx ON animation_relations(source_kind,target_kind,relation);
CREATE TABLE animation_context(
 asset_path TEXT PRIMARY KEY,asset_kind TEXT NOT NULL,class_path TEXT NOT NULL,
 coverage TEXT NOT NULL,outgoing_count INTEGER NOT NULL,incoming_count INTEGER NOT NULL,
 truncated INTEGER NOT NULL,text TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX animation_context_kind_idx ON animation_context(asset_kind);
CREATE TABLE animation_summaries(
 asset_path TEXT PRIMARY KEY,asset_kind TEXT NOT NULL,class_path TEXT NOT NULL,
 coverage TEXT NOT NULL,package_name TEXT NOT NULL,outgoing_count INTEGER NOT NULL,
 incoming_count INTEGER NOT NULL,relation_counts_json TEXT NOT NULL,text TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX animation_summaries_kind_idx ON animation_summaries(asset_kind);
"""


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def _class_leaf(class_path: str) -> str:
    value = str(class_path or "").rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower() or "asset"


def _blueprint_kind(row: dict) -> str:
    cls = str(row.get("class", ""))
    if cls == "/Script/Engine.AnimBlueprint":
        return "animation_blueprint"
    if "ControlRigBlueprint" in cls:
        return "control_rig_blueprint"
    if "WidgetBlueprint" in cls:
        return "widget_blueprint"
    return "blueprint"


def _generic_coverage(class_path: str) -> str:
    if class_path in {"/Script/Engine.UserDefinedStruct", "/Script/Engine.UserDefinedEnum"}:
        return "partial"
    return "generic_only"


def _summary_lines(meta: dict) -> list[str]:
    lines = [
        f"Asset: {meta.get('path', '')}",
        f"Kind: {meta.get('kind', '')}",
        f"Class: {meta.get('class_path', '')}",
        f"Coverage: {meta.get('coverage', '')}",
    ]
    if meta.get("package_name"):
        lines.append(f"Package: {meta['package_name']}")
    facts = meta.get("facts", {})
    keys = (
        "skeleton_path","source_animation_path","play_length","additive",
        "notify_count","sync_marker_count","pose_count","track_count","curve_count",
        "item_count","database_count","row_count","column_count","result_count",
        "context_count","entry_count","inherit_table_count","bone_count","chain_count",
        "goal_count","solver_count","op_count","source_pose_count","target_pose_count",
    )
    values = [f"{k}={facts[k]}" for k in keys if k in facts and facts[k] not in ("", None)]
    if values:
        lines.append("Facts: " + " ".join(values))
    return lines


def derive(output, rows) -> tuple[list[dict], list[dict], list[dict]]:
    registry: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    roots: dict[str, dict] = {}
    rank = {"external_or_excluded":0,"generic_only":1,"partial":2,"first_class_depth_pending":3,"first_class":4}

    def register(path, kind, coverage, class_path="", package_name="", root=False, facts=None):
        path = str(path or "")
        if not path:
            return
        candidate = {
            "path": path,
            "kind": str(kind or "asset"),
            "coverage": str(coverage or "generic_only"),
            "class_path": str(class_path or ""),
            "package_name": str(package_name or ""),
        }
        current = registry.get(path)
        if current is None or rank.get(candidate["coverage"], 0) >= rank.get(current.get("coverage", ""), 0):
            registry[path] = candidate
        if root:
            roots[path] = {**registry[path], "facts": dict(facts or {})}

    for row in rows(output / "assets.jsonl"):
        register(
            row.get("object_path"), _class_leaf(row.get("class_path")),
            _generic_coverage(str(row.get("class_path", ""))),
            row.get("class_path"), row.get("package_name"),
        )
    for row in rows(output / "blueprints.jsonl"):
        path = str(row.get("object_path", ""))
        register(path, _blueprint_kind(row), "first_class", row.get("class"), path.split(".", 1)[0])
        if row.get("generated_class") and path:
            aliases[str(row["generated_class"])] = path

    animation_rows = list(rows(output / "animation_assets.jsonl"))
    for row in animation_rows:
        register(
            row.get("animation_path"), row.get("animation_kind", "animation_asset"), "first_class",
            row.get("class_path"), row.get("package_name"), True, row,
        )

    # Enrich root retrieval facts from dedicated family summaries.
    for filename, path_key in (
        ("skeletons.jsonl","skeleton_path"),
        ("pose_search_databases.jsonl","database_path"),
        ("pose_search_schemas.jsonl","schema_path"),
        ("pose_assets.jsonl","pose_asset_path"),
        ("chooser_tables.jsonl","chooser_path"),
        ("proxy_tables.jsonl","proxy_table_path"),
        ("ik_rigs.jsonl","ik_rig_path"),
        ("ik_retargeters.jsonl","retargeter_path"),
    ):
        for row in rows(output / filename):
            path = str(row.get(path_key, ""))
            if path in roots:
                roots[path].setdefault("facts", {}).update(row)

    for filename, path_key, kind in (
        ("pose_search_interaction_assets.jsonl","interaction_path","pose_search_interaction_asset"),
        ("pose_search_normalization_sets.jsonl","normalization_set_path","pose_search_normalization_set"),
        ("mirror_data_tables.jsonl","mirror_table_path","mirror_data_table"),
    ):
        for row in rows(output / filename):
            register(path=row.get(path_key), kind=kind, coverage="first_class",
                     class_path=row.get("class_path"), package_name=row.get("package_name"),
                     root=True, facts=row)

    for row in rows(output / "pose_search_channels.jsonl"):
        register(row.get("channel_path"), "pose_search_channel", "first_class", row.get("channel_class"))
    for row in rows(output / "ik_rig_goals.jsonl"):
        register(row.get("goal_path"), "ik_goal", "first_class")

    def resolve(path, desired_kind="object"):
        canonical = aliases.get(str(path or ""), str(path or ""))
        if canonical in registry:
            return registry[canonical]
        return {
            "path": canonical, "kind": desired_kind or "object",
            "coverage": "external_or_excluded", "class_path": "",
            "package_name": canonical.split(".", 1)[0] if canonical else "",
        }

    evidence_by_key = collections.defaultdict(dict)
    keys_by_pair = collections.defaultdict(set)

    def add(source, relation, target, desired_target_kind="object", evidence=None, generic_reference=False):
        source = aliases.get(str(source or ""), str(source or ""))
        target = str(target or "")
        if not source or not relation or not target or (source not in registry and source not in roots):
            return
        tm = resolve(target, desired_target_kind)
        target_path = str(tm.get("path", ""))
        if not target_path:
            return
        pair = (source, target_path)
        evidence = dict(evidence or {})
        encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if generic_reference and pair in keys_by_pair:
            for key in keys_by_pair[pair]:
                evidence_by_key[key][encoded] = evidence
            return
        sm = registry.get(source) or roots.get(source) or {}
        key = (
            str(sm.get("kind", "animation_asset")), source, str(relation),
            str(tm.get("kind", desired_target_kind)), target_path,
            str(tm.get("coverage", "external_or_excluded")),
        )
        evidence_by_key[key][encoded] = evidence
        keys_by_pair[pair].add(key)

    def field(source, relation, target, target_kind, stream, field_name):
        if target:
            add(source, relation, target, target_kind, {
                "kind":"canonical_animation_field","stream":stream,"field":field_name,
            })

    # Shared root fields.
    for row in animation_rows:
        field(row.get("animation_path"), "uses_skeleton", row.get("skeleton_path"),
              "skeleton", "animation_assets.jsonl", "skeleton_path")

    # Montage and BlendSpace topology.
    for row in rows(output / "animation_segments.jsonl"):
        add(row.get("asset_path"), "plays_animation_segment", row.get("animation_path"), "animation_asset", {
            "kind":"canonical_animation_structure","stream":"animation_segments.jsonl",
            "slot_index":int(row.get("slot_index",0)),"slot_name":str(row.get("slot_name","")),
            "segment_index":int(row.get("segment_index",0)),"start_pos":row.get("start_pos"),
            "anim_start_time":row.get("anim_start_time"),"anim_end_time":row.get("anim_end_time"),
            "anim_play_rate":row.get("anim_play_rate"),"looping_count":row.get("looping_count"),
        })
    for row in rows(output / "blend_space_samples.jsonl"):
        add(row.get("blend_space_path"), "samples_animation", row.get("animation_path"), "animation_asset", {
            "kind":"canonical_animation_structure","stream":"blend_space_samples.jsonl",
            "sample_index":int(row.get("sample_index",0)),"x":row.get("x"),"y":row.get("y"),"z":row.get("z"),
            "rate_scale":row.get("rate_scale"),"mirror":bool(row.get("mirror",False)),
            "single_frame":bool(row.get("single_frame",False)),
        })

    for row in rows(output / "pose_assets.jsonl"):
        field(row.get("pose_asset_path"), "uses_skeleton", row.get("skeleton_path"),
              "skeleton", "pose_assets.jsonl", "skeleton_path")
        field(row.get("pose_asset_path"), "derived_from_animation", row.get("source_animation_path"),
              "animation_asset", "pose_assets.jsonl", "source_animation_path")

    # Pose Search.
    for row in rows(output / "pose_search_databases.jsonl"):
        field(row.get("database_path"), "uses_pose_search_schema", row.get("schema_path"),
              "pose_search_schema", "pose_search_databases.jsonl", "schema_path")
        field(row.get("database_path"), "uses_preview_mesh", row.get("preview_mesh_path"),
              "skeletal_mesh", "pose_search_databases.jsonl", "preview_mesh_path")
    for row in rows(output / "pose_search_database_assets.jsonl"):
        add(row.get("database_path"), "contains_pose_search_source", row.get("animation_path"), "animation_asset", {
            "kind":"canonical_animation_structure","stream":"pose_search_database_assets.jsonl",
            "asset_index":int(row.get("asset_index",0)),"animation_class":str(row.get("animation_class","")),
        })
    for row in rows(output / "pose_search_schema_skeletons.jsonl"):
        detail = {
            "kind":"canonical_animation_structure","stream":"pose_search_schema_skeletons.jsonl",
            "role_index":int(row.get("role_index",0)),"role":str(row.get("role","")),
        }
        if row.get("skeleton_path"):
            add(row.get("schema_path"), "uses_skeleton", row.get("skeleton_path"), "skeleton", detail)
        if row.get("mirror_data_table_path"):
            add(row.get("schema_path"), "uses_mirror_data_table", row.get("mirror_data_table_path"),
                "mirror_data_table", detail)
    for row in rows(output / "pose_search_interaction_items.jsonl"):
        detail = {
            "kind":"canonical_animation_structure","stream":"pose_search_interaction_items.jsonl",
            "item_index":int(row.get("item_index",0)),"role":str(row.get("role","")),
            "animation_class":str(row.get("animation_class","")),
        }
        if row.get("animation_path"):
            add(row.get("interaction_path"), "uses_interaction_animation", row.get("animation_path"),
                "animation_asset", detail)
        if row.get("preview_mesh_path"):
            add(row.get("interaction_path"), "uses_preview_mesh", row.get("preview_mesh_path"),
                "skeletal_mesh", detail)
    for row in rows(output / "pose_search_normalization_databases.jsonl"):
        add(row.get("normalization_set_path"), "normalizes_pose_search_database", row.get("database_path"),
            "pose_search_database", {
                "kind":"canonical_animation_structure","stream":"pose_search_normalization_databases.jsonl",
                "database_index":int(row.get("database_index",0)),
            })
    for row in rows(output / "mirror_data_tables.jsonl"):
        field(row.get("mirror_table_path"), "uses_skeleton", row.get("skeleton_path"),
              "skeleton", "mirror_data_tables.jsonl", "skeleton_path")

    # Chooser / Proxy / IK.
    for row in rows(output / "proxy_entries.jsonl"):
        add(row.get("proxy_table_path"), "maps_proxy", row.get("proxy_path"), "proxy_asset", {
            "kind":"canonical_animation_structure","stream":"proxy_entries.jsonl",
            "entry_index":int(row.get("entry_index",0)),
            "value_struct_type":str(row.get("value_struct_type","")),
        })
    for row in rows(output / "proxy_table_inheritance.jsonl"):
        add(row.get("proxy_table_path"), "inherits_proxy_table", row.get("parent_table_path"), "proxy_table", {
            "kind":"canonical_animation_structure","stream":"proxy_table_inheritance.jsonl",
            "inherit_index":int(row.get("inherit_index",0)),
        })
    for row in rows(output / "ik_rigs.jsonl"):
        field(row.get("ik_rig_path"), "uses_preview_mesh", row.get("preview_mesh_path"),
              "skeletal_mesh", "ik_rigs.jsonl", "preview_mesh_path")
    for row in rows(output / "ik_retargeters.jsonl"):
        field(row.get("retargeter_path"), "uses_source_ik_rig", row.get("source_ik_rig_path"),
              "ik_rig", "ik_retargeters.jsonl", "source_ik_rig_path")
        field(row.get("retargeter_path"), "uses_target_ik_rig", row.get("target_ik_rig_path"),
              "ik_rig", "ik_retargeters.jsonl", "target_ik_rig_path")

    # Exact reflected references. When a stronger topology edge already joins the
    # same source/target pair, retain the reference as supporting evidence.
    for row in rows(output / "animation_references.jsonl"):
        source = aliases.get(str(row.get("asset_path","")), str(row.get("asset_path","")))
        target = str(row.get("target_path",""))
        canonical_target = aliases.get(target, target)
        if canonical_target not in registry or canonical_target == source:
            continue
        add(source, "references_asset", target, evidence={
            "kind":"canonical_reference","stream":"animation_references.jsonl",
            "owner_path":str(row.get("owner_path","")),"owner_kind":str(row.get("owner_kind","")),
            "root_property":str(row.get("root_property","")),"property_path":str(row.get("property_path","")),
            "reference_kind":str(row.get("reference_kind","")),"target_class":str(row.get("target_class","")),
        }, generic_reference=True)
    for row in rows(output / "animation_struct_references.jsonl"):
        source = str(row.get("owner_path",""))
        target = str(row.get("target_path",""))
        if (source not in registry and source not in roots) or aliases.get(target,target) not in registry:
            continue
        add(source, "references_object", target, evidence={
            "kind":"canonical_struct_reference","stream":"animation_struct_references.jsonl",
            "source_kind":str(row.get("source_kind","")),"source_index":int(row.get("source_index",0)),
            "reference_kind":str(row.get("reference_kind","")),"target_class":str(row.get("target_class","")),
        }, generic_reference=True)

    relations = []
    for key in sorted(evidence_by_key):
        source_kind, source, relation, target_kind, target, target_coverage = key
        evidence = [evidence_by_key[key][token] for token in sorted(evidence_by_key[key])]
        identity = key[:-1]  # coverage is metadata, not semantic edge identity
        relation_id = "arel:" + hashlib.sha1("\x1f".join(identity).encode("utf-8")).hexdigest()[:24]
        relations.append({
            "relation_id":relation_id,"source_kind":source_kind,"source":source,
            "relation":relation,"target_kind":target_kind,"target":target,
            "target_coverage":target_coverage,"evidence_count":len(evidence),"evidence":evidence,
        })

    outgoing = collections.defaultdict(list)
    incoming = collections.defaultdict(list)
    for relation in relations:
        outgoing[relation["source"]].append(relation)
        incoming[relation["target"]].append(relation)

    summaries, contexts = [], []
    for path in sorted(roots):
        meta = roots[path]
        out = sorted(outgoing.get(path, []), key=lambda r:(r["relation"],r["target_kind"],r["target"],r["relation_id"]))
        inc = sorted(incoming.get(path, []), key=lambda r:(r["relation"],r["source_kind"],r["source"],r["relation_id"]))
        relation_counts = dict(sorted(collections.Counter(r["relation"] for r in out).items()))
        lines = _summary_lines(meta)
        lines.append(f"Relations: outgoing={len(out)} incoming={len(inc)} {relation_counts}")
        summary = {
            "asset_path":path,"asset_kind":meta.get("kind",""),"class_path":meta.get("class_path",""),
            "coverage":meta.get("coverage",""),"package_name":meta.get("package_name",""),
            "outgoing_count":len(out),"incoming_count":len(inc),
            "relation_counts":relation_counts,"text":"\n".join(lines),
        }
        summaries.append(summary)

        context_lines = list(lines)
        shown_out = min(len(out), MAX_CONTEXT_LINKS_PER_ASSET)
        if shown_out:
            context_lines.append("Outgoing:")
            for r in out[:shown_out]:
                context_lines.append(
                    f"  {r['relation']} -> {r['target_kind']} {r['target']} "
                    f"coverage={r['target_coverage']} evidence={r['evidence_count']}"
                )
        remaining = max(0, MAX_CONTEXT_LINKS_PER_ASSET - shown_out)
        shown_inc = min(len(inc), remaining)
        if shown_inc:
            context_lines.append("Incoming:")
            for r in inc[:shown_inc]:
                context_lines.append(
                    f"  {r['source_kind']} {r['source']} -> {r['relation']} evidence={r['evidence_count']}"
                )
        omitted = (len(out)-shown_out) + (len(inc)-shown_inc)
        if omitted:
            context_lines.append(f"... {omitted} more relations omitted by context link bound")
        text = "\n".join(context_lines)
        char_truncated = len(text) > MAX_CONTEXT_CHARS
        if char_truncated:
            text = text[:MAX_CONTEXT_CHARS] + "\n...[truncated]"
        contexts.append({
            "asset_path":path,"asset_kind":meta.get("kind",""),"class_path":meta.get("class_path",""),
            "coverage":meta.get("coverage",""),"outgoing_count":len(out),"incoming_count":len(inc),
            "truncated":bool(omitted or char_truncated),"text":text,
        })

    return relations, contexts, summaries


def load_database(conn, output, rows) -> None:
    for r in rows(output / "animation_relations.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_relations VALUES(?,?,?,?,?,?,?,?,?)",(
            r.get("relation_id",""),r.get("source_kind",""),r.get("source",""),r.get("relation",""),
            r.get("target_kind",""),r.get("target",""),r.get("target_coverage",""),
            int(r.get("evidence_count",0)),json.dumps(r.get("evidence",[]),ensure_ascii=False,separators=(",",":")),
        ))
    for r in rows(output / "animation_context.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_context VALUES(?,?,?,?,?,?,?,?,?)",(
            r.get("asset_path",""),r.get("asset_kind",""),r.get("class_path",""),r.get("coverage",""),
            int(r.get("outgoing_count",0)),int(r.get("incoming_count",0)),int(bool(r.get("truncated",False))),
            r.get("text",""),json.dumps(r,ensure_ascii=False,separators=(",",":")),
        ))
    for r in rows(output / "animation_summaries.jsonl"):
        conn.execute("INSERT OR REPLACE INTO animation_summaries VALUES(?,?,?,?,?,?,?,?,?,?)",(
            r.get("asset_path",""),r.get("asset_kind",""),r.get("class_path",""),r.get("coverage",""),
            r.get("package_name",""),int(r.get("outgoing_count",0)),int(r.get("incoming_count",0)),
            json.dumps(r.get("relation_counts",{}),ensure_ascii=False,separators=(",",":")),
            r.get("text",""),json.dumps(r,ensure_ascii=False,separators=(",",":")),
        ))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='animation_summaries'").fetchone():
        return
    print("\n[animation summaries]")
    print_rows(conn.execute(
        "SELECT asset_path,asset_kind,outgoing_count,incoming_count,substr(text,1,1400) text "
        "FROM animation_summaries WHERE asset_path LIKE ? OR asset_kind LIKE ? OR text LIKE ? LIMIT ?",
        (pattern,pattern,pattern,limit)),
        ("asset_path","asset_kind","outgoing_count","incoming_count","text"))
    print("\n[animation relations]")
    print_rows(conn.execute(
        "SELECT source_kind,source,relation,target_kind,target,target_coverage,evidence_count "
        "FROM animation_relations WHERE source LIKE ? OR relation LIKE ? OR target LIKE ? "
        "OR target_kind LIKE ? OR evidence_json LIKE ? LIMIT ?",
        (pattern,pattern,pattern,pattern,pattern,limit)),
        ("source_kind","source","relation","target_kind","target","target_coverage","evidence_count"))
    print("\n[animation context]")
    print_rows(conn.execute(
        "SELECT asset_path,asset_kind,substr(text,1,1800) text FROM animation_context "
        "WHERE asset_path LIKE ? OR asset_kind LIKE ? OR text LIKE ? LIMIT ?",
        (pattern,pattern,pattern,limit)),
        ("asset_path","asset_kind","text"))
