#!/usr/bin/env python3
"""Derived animation relations, summaries, and bounded context for UnrealAssetTool.

The module only joins canonical scanner facts. It never infers an asset from a
display name and never treats a package dependency as equivalent to an exact
object reference.
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
    relation_id TEXT PRIMARY KEY,
    source_kind TEXT NOT NULL,
    source TEXT NOT NULL,
    relation TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target TEXT NOT NULL,
    target_coverage TEXT NOT NULL,
    evidence_count INTEGER NOT NULL,
    evidence_json TEXT NOT NULL
);
CREATE INDEX animation_relations_source_idx
    ON animation_relations(source, relation);
CREATE INDEX animation_relations_target_idx
    ON animation_relations(target, relation);
CREATE INDEX animation_relations_kind_idx
    ON animation_relations(source_kind, target_kind, relation);

CREATE TABLE animation_context(
    asset_path TEXT PRIMARY KEY,
    asset_kind TEXT NOT NULL,
    class_path TEXT NOT NULL,
    coverage TEXT NOT NULL,
    outgoing_count INTEGER NOT NULL,
    incoming_count INTEGER NOT NULL,
    truncated INTEGER NOT NULL,
    text TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX animation_context_kind_idx ON animation_context(asset_kind);

CREATE TABLE animation_summaries(
    asset_path TEXT PRIMARY KEY,
    asset_kind TEXT NOT NULL,
    class_path TEXT NOT NULL,
    coverage TEXT NOT NULL,
    package_name TEXT NOT NULL,
    outgoing_count INTEGER NOT NULL,
    incoming_count INTEGER NOT NULL,
    relation_counts_json TEXT NOT NULL,
    text TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX animation_summaries_kind_idx ON animation_summaries(asset_kind);
"""


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def _class_leaf(class_path: str) -> str:
    value = str(class_path or "").rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    if not value:
        return "asset"
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower()
    return value or "asset"


def _blueprint_kind(row: dict) -> str:
    class_path = str(row.get("class", ""))
    if class_path == "/Script/Engine.AnimBlueprint":
        return "animation_blueprint"
    if "ControlRigBlueprint" in class_path:
        return "control_rig_blueprint"
    if "WidgetBlueprint" in class_path:
        return "widget_blueprint"
    return "blueprint"


def _coverage_for_generic(class_path: str) -> str:
    if class_path in {"/Script/Engine.UserDefinedStruct", "/Script/Engine.UserDefinedEnum"}:
        return "partial"
    return "generic_only"


def _meta_text(meta: dict) -> list[str]:
    lines = [
        f"Asset: {meta.get('path', '')}",
        f"Kind: {meta.get('kind', '')}",
        f"Class: {meta.get('class_path', '')}",
        f"Coverage: {meta.get('coverage', '')}",
    ]
    package = str(meta.get("package_name", ""))
    if package:
        lines.append(f"Package: {package}")
    facts = meta.get("facts", {})
    if isinstance(facts, dict):
        compact = []
        for key in (
            "skeleton_path",
            "source_animation_path",
            "play_length",
            "additive",
            "notify_count",
            "sync_marker_count",
            "pose_count",
            "track_count",
            "curve_count",
            "item_count",
            "database_count",
            "row_count",
            "column_count",
            "result_count",
            "context_count",
            "entry_count",
            "inherit_table_count",
            "bone_count",
            "chain_count",
            "goal_count",
            "solver_count",
            "op_count",
            "source_pose_count",
            "target_pose_count",
        ):
            if key in facts and facts.get(key) not in ("", None):
                compact.append(f"{key}={facts.get(key)}")
        if compact:
            lines.append("Facts: " + " ".join(compact))
    return lines


def derive(output, rows) -> tuple[list[dict], list[dict], list[dict]]:
    """Build deterministic asset-level animation relations and retrieval views."""

    registry: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    roots: dict[str, dict] = {}

    def register(
        path: str,
        kind: str,
        coverage: str,
        *,
        class_path: str = "",
        package_name: str = "",
        root: bool = False,
        facts: dict | None = None,
    ) -> None:
        path = str(path or "")
        if not path:
            return
        current = registry.get(path)
        rank = {
            "external_or_excluded": 0,
            "generic_only": 1,
            "partial": 2,
            "first_class_depth_pending": 3,
            "first_class": 4,
        }
        candidate = {
            "path": path,
            "kind": str(kind or "asset"),
            "coverage": str(coverage or "generic_only"),
            "class_path": str(class_path or ""),
            "package_name": str(package_name or ""),
        }
        if current is None or rank.get(candidate["coverage"], 0) >= rank.get(current.get("coverage", ""), 0):
            registry[path] = candidate
        if root:
            root_meta = dict(registry[path])
            root_meta["facts"] = dict(facts or {})
            roots[path] = root_meta

    def register_alias(alias: str, target: str) -> None:
        alias = str(alias or "")
        target = str(target or "")
        if alias and target:
            aliases[alias] = target

    # Universal Asset Registry fallback. Specialist registrations below override it.
    for row in rows(output / "assets.jsonl"):
        register(
            row.get("object_path", ""),
            _class_leaf(row.get("class_path", "")),
            _coverage_for_generic(str(row.get("class_path", ""))),
            class_path=row.get("class_path", ""),
            package_name=row.get("package_name", ""),
        )

    # Structural specialist assets are useful exact targets for references embedded in
    # Chooser/Proxy/IK structures.
    for row in rows(output / "blueprints.jsonl"):
        path = str(row.get("object_path", ""))
        kind = _blueprint_kind(row)
        register(
            path,
            kind,
            "first_class",
            class_path=row.get("class", ""),
            package_name=path.split(".", 1)[0],
        )
        register_alias(row.get("generated_class", ""), path)

    # Root animation schema entities.
    animation_rows = list(rows(output / "animation_assets.jsonl"))
    for row in animation_rows:
        path = str(row.get("animation_path", ""))
        register(
            path,
            row.get("animation_kind", "animation_asset"),
            "first_class",
            class_path=row.get("class_path", ""),
            package_name=row.get("package_name", ""),
            root=True,
            facts=row,
        )

    # Deep-only root entities are not necessarily present in animation_assets.
    for filename, path_key, kind in (
        ("pose_search_interaction_assets.jsonl", "interaction_path", "pose_search_interaction_asset"),
        ("pose_search_normalization_sets.jsonl", "normalization_set_path", "pose_search_normalization_set"),
        ("mirror_data_tables.jsonl", "mirror_table_path", "mirror_data_table"),
    ):
        for row in rows(output / filename):
            path = str(row.get(path_key, ""))
            register(
                path,
                kind,
                "first_class",
                class_path=row.get("class_path", ""),
                package_name=row.get("package_name", ""),
                root=True,
                facts=row,
            )

    # First-class subobjects that reflection rows may reference exactly.
    for row in rows(output / "pose_search_channels.jsonl"):
        register(
            row.get("channel_path", ""),
            "pose_search_channel",
            "first_class",
            class_path=row.get("channel_class", ""),
        )
    for row in rows(output / "ik_rig_goals.jsonl"):
        register(row.get("goal_path", ""), "ik_goal", "first_class")

    def resolve(path: str, desired_kind: str = "object") -> dict:
        path = str(path or "")
        canonical = aliases.get(path, path)
        meta = registry.get(canonical)
        if meta:
            return meta
        return {
            "path": canonical,
            "kind": desired_kind or "object",
            "coverage": "external_or_excluded",
            "class_path": "",
            "package_name": canonical.split(".", 1)[0] if canonical else "",
        }

    evidence_by_key: dict[tuple[str, ...], dict[str, dict]] = collections.defaultdict(dict)
    edge_keys_by_pair: dict[tuple[str, str], set[tuple[str, ...]]] = collections.defaultdict(set)

    def add(
        source: str,
        relation: str,
        target: str,
        *,
        source_kind: str | None = None,
        desired_target_kind: str = "object",
        evidence: dict | None = None,
        generic_reference: bool = False,
    ) -> None:
        source = aliases.get(str(source or ""), str(source or ""))
        target = str(target or "")
        if not source or not relation or not target:
            return
        source_meta = registry.get(source)
        if source_meta is None and source not in roots:
            return
        target_meta = resolve(target, desired_target_kind)
        target_path = str(target_meta.get("path", ""))
        if not target_path:
            return

        pair = (source, target_path)
        evidence = dict(evidence or {})

        if generic_reference and pair in edge_keys_by_pair:
            # An exact reflected reference is supporting evidence for a stronger
            # canonical topology edge; do not create a second noisy relation.
            for key in edge_keys_by_pair[pair]:
                encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                evidence_by_key[key][encoded] = evidence
            return

        sk = str(source_kind or (registry.get(source) or roots.get(source) or {}).get("kind", "animation_asset"))
        key = (
            sk,
            source,
            str(relation),
            str(target_meta.get("kind", desired_target_kind or "object")),
            target_path,
            str(target_meta.get("coverage", "external_or_excluded")),
        )
        encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        evidence_by_key[key][encoded] = evidence
        edge_keys_by_pair[pair].add(key)

    # Shared animation -> Skeleton relation.
    for row in animation_rows:
        skeleton = str(row.get("skeleton_path", ""))
        if skeleton:
            add(
                row.get("animation_path", ""),
                "uses_skeleton",
                skeleton,
                desired_target_kind="skeleton",
                evidence={
                    "kind": "canonical_animation_field",
                    "stream": "animation_assets.jsonl",
                    "field": "skeleton_path",
                },
            )

    # Montage and BlendSpace authored topology.
    for row in rows(output / "animation_segments.jsonl"):
        add(
            row.get("asset_path", ""),
            "plays_animation_segment",
            row.get("animation_path", ""),
            desired_target_kind="animation_asset",
            evidence={
                "kind": "canonical_animation_structure",
                "stream": "animation_segments.jsonl",
                "slot_index": int(row.get("slot_index", 0)),
                "slot_name": str(row.get("slot_name", "")),
                "segment_index": int(row.get("segment_index", 0)),
                "start_pos": row.get("start_pos"),
                "anim_start_time": row.get("anim_start_time"),
                "anim_end_time": row.get("anim_end_time"),
                "anim_play_rate": row.get("anim_play_rate"),
                "looping_count": row.get("looping_count"),
            },
        )
    for row in rows(output / "blend_space_samples.jsonl"):
        add(
            row.get("blend_space_path", ""),
            "samples_animation",
            row.get("animation_path", ""),
            desired_target_kind="animation_asset",
            evidence={
                "kind": "canonical_animation_structure",
                "stream": "blend_space_samples.jsonl",
                "sample_index": int(row.get("sample_index", 0)),
                "x": row.get("x"),
                "y": row.get("y"),
                "z": row.get("z"),
                "rate_scale": row.get("rate_scale"),
                "mirror": bool(row.get("mirror", False)),
                "single_frame": bool(row.get("single_frame", False)),
            },
        )

    # PoseAsset canonical source/skeleton relations.
    for row in rows(output / "pose_assets.jsonl"):
        source = row.get("pose_asset_path", "")
        if row.get("skeleton_path"):
            add(
                source,
                "uses_skeleton",
                row.get("skeleton_path", ""),
                desired_target_kind="skeleton",
                evidence={
                    "kind": "canonical_animation_field",
                    "stream": "pose_assets.jsonl",
                    "field": "skeleton_path",
                },
            )
        if row.get("source_animation_path"):
            add(
                source,
                "derived_from_animation",
                row.get("source_animation_path", ""),
                desired_target_kind="animation_asset",
                evidence={
                    "kind": "canonical_animation_field",
                    "stream": "pose_assets.jsonl",
                    "field": "source_animation_path",
                },
            )

    # Pose Search database/schema graph.
    for row in rows(output / "pose_search_databases.jsonl"):
        if row.get("schema_path"):
            add(
                row.get("database_path", ""),
                "uses_pose_search_schema",
                row.get("schema_path", ""),
                desired_target_kind="pose_search_schema",
                evidence={
                    "kind": "canonical_animation_field",
                    "stream": "pose_search_databases.jsonl",
                    "field": "schema_path",
                },
            )
        if row.get("preview_mesh_path"):
            add(
                row.get("database_path", ""),
                "uses_preview_mesh",
                row.get("preview_mesh_path", ""),
                desired_target_kind="skeletal_mesh",
                evidence={
                    "kind": "canonical_animation_field",
                    "stream": "pose_search_databases.jsonl",
                    "field": "preview_mesh_path",
                },
            )
    for row in rows(output / "pose_search_database_assets.jsonl"):
        add(
            row.get("database_path", ""),
            "contains_pose_search_source",
            row.get("animation_path", ""),
            desired_target_kind="animation_asset",
            evidence={
                "kind": "canonical_animation_structure",
                "stream": "pose_search_database_assets.jsonl",
                "asset_index": int(row.get("asset_index", 0)),
                "animation_class": str(row.get("animation_class", "")),
            },
        )
    for row in rows(output / "pose_search_schema_skeletons.jsonl"):
        source = row.get("schema_path", "")
        if row.get("skeleton_path"):
            add(
                source,
                "uses_skeleton",
                row.get("skeleton_path", ""),
                desired_target_kind="skeleton",
                evidence={
                    "kind": "canonical_animation_structure",
                    "stream": "pose_search_schema_skeletons.jsonl",
                    "role_index": int(row.get("role_index", 0)),
                    "role": str(row.get("role", "")),
                },
            )
        if row.get("mirror_data_table_path"):
            add(
                source,
                "uses_mirror_data_table",
                row.get("mirror_data_table_path", ""),
                desired_target_kind="mirror_data_table",
                evidence={
                    "kind": "canonical_animation_structure",
                    "stream": "pose_search_schema_skeletons.jsonl",
                    "role_index": int(row.get("role_index", 0)),
                    "role": str(row.get("role", "")),
                },
            )

    # Deep Pose Search and mirroring.
    for row in rows(output / "pose_search_interaction_items.jsonl"):
        source = row.get("interaction_path", "")
        if row.get("animation_path"):
            add(
                source,
                "uses_interaction_animation",
                row.get("animation_path", ""),
                desired_target_kind="animation_asset",
                evidence={
                    "kind": "canonical_animation_structure",
                    "stream": "pose_search_interaction_items.jsonl",
                    "item_index": int(row.get("item_index", 0)),
                    "role": str(row.get("role", "")),
                    "animation_class": str(row.get("animation_class", "")),
                },
            )
        if row.get("preview_mesh_path"):
            add(
                source,
                "uses_preview_mesh",
                row.get("preview_mesh_path", ""),
                desired_target_kind="skeletal_mesh",
                evidence={
                    "kind": "canonical_animation_structure",
                    "stream": "pose_search_interaction_items.jsonl",
                    "item_index": int(row.get("item_index", 0)),
                    "role": str(row.get("role", "")),
                },
            )
    for row in rows(output / "pose_search_normalization_databases.jsonl"):
        add(
            row.get("normalization_set_path", ""),
            "normalizes_pose_search_database",
            row.get("database_path", ""),
            desired_target_kind="pose_search_database",
            evidence={
                "kind": "canonical_animation_structure",
                "stream": "pose_search_normalization_databases.jsonl",
                "database_index": int(row.get("database_index", 0)),
            },
        )
    for row in rows(output / "mirror_data_tables.jsonl"):
        if row.get("skeleton_path"):
            add(
                row.get("mirror_table_path", ""),
                "uses_skeleton",
                row.get("skeleton_path", ""),
                desired_target_kind="skeleton",
                evidence={
                    "kind": "canonical_animation_field",
                    "stream": "mirror_data_tables.jsonl",
                    "field": "skeleton_path",
                },
            )

    # Chooser / Proxy and IK topology.
    for row in rows(output / "proxy_entries.jsonl"):
        add(
            row.get("proxy_table_path", ""),
            "maps_proxy",
            row.get("proxy_path", ""),
            desired_target_kind="proxy_asset",
            evidence={
                "kind": "canonical_animation_structure",
                "stream": "proxy_entries.jsonl",
                "entry_index": int(row.get("entry_index", 0)),
                "value_struct_type": str(row.get("value_struct_type", "")),
            },
        )
    for row in rows(output / "proxy_table_inheritance.jsonl"):
        add(
            row.get("proxy_table_path", ""),
            "inherits_proxy_table",
            row.get("parent_table_path", ""),
            desired_target_kind="proxy_table",
            evidence={
                "kind": "canonical_animation_structure",
                "stream": "proxy_table_inheritance.jsonl",
                "inherit_index": int(row.get("inherit_index", 0)),
            },
        )
    for row in rows(output / "ik_rigs.jsonl"):
        if row.get("preview_mesh_path"):
            add(
                row.get("ik_rig_path", ""),
                "uses_preview_mesh",
                row.get("preview_mesh_path", ""),
                desired_target_kind="skeletal_mesh",
                evidence={
                    "kind": "canonical_animation_field",
                    "stream": "ik_rigs.jsonl",
                    "field": "preview_mesh_path",
                },
            )
    for row in rows(output / "ik_retargeters.jsonl"):
        source = row.get("retargeter_path", "")
        if row.get("source_ik_rig_path"):
            add(
                source,
                "uses_source_ik_rig",
                row.get("source_ik_rig_path", ""),
                desired_target_kind="ik_rig",
                evidence={
                    "kind": "canonical_animation_field",
                    "stream": "ik_retargeters.jsonl",
                    "field": "source_ik_rig_path",
                },
            )
        if row.get("target_ik_rig_path"):
            add(
                source,
                "uses_target_ik_rig",
                row.get("target_ik_rig_path", ""),
                desired_target_kind="ik_rig",
                evidence={
                    "kind": "canonical_animation_field",
                    "stream": "ik_retargeters.jsonl",
                    "field": "target_ik_rig_path",
                },
            )

    # Loss-minimizing reflection references become exact edges when the target is
    # indexed. If a stronger topology edge already joins the same pair, keep the
    # reference as supporting evidence instead of duplicating the relation.
    for row in rows(output / "animation_references.jsonl"):
        target = str(row.get("target_path", ""))
        canonical_target = aliases.get(target, target)
        source = aliases.get(str(row.get("asset_path", "")), str(row.get("asset_path", "")))
        if canonical_target not in registry or canonical_target == source:
            continue
        add(
            source,
            "references_asset",
            target,
            evidence={
                "kind": "canonical_reference",
                "stream": "animation_references.jsonl",
                "owner_path": str(row.get("owner_path", "")),
                "owner_kind": str(row.get("owner_kind", "")),
                "root_property": str(row.get("root_property", "")),
                "property_path": str(row.get("property_path", "")),
                "reference_kind": str(row.get("reference_kind", "")),
                "target_class": str(row.get("target_class", "")),
            },
            generic_reference=True,
        )
    for row in rows(output / "animation_struct_references.jsonl"):
        source = str(row.get("owner_path", ""))
        if source not in registry and source not in roots:
            continue
        target = str(row.get("target_path", ""))
        canonical_target = aliases.get(target, target)
        if canonical_target not in registry:
            continue
        add(
            source,
            "references_object",
            target,
            evidence={
                "kind": "canonical_struct_reference",
                "stream": "animation_struct_references.jsonl",
                "source_kind": str(row.get("source_kind", "")),
                "source_index": int(row.get("source_index", 0)),
                "reference_kind": str(row.get("reference_kind", "")),
                "target_class": str(row.get("target_class", "")),
            },
            generic_reference=True,
        )

    relations = []
    for key in sorted(evidence_by_key):
        source_kind, source, relation, target_kind, target, target_coverage = key
        evidence = [evidence_by_key[key][encoded] for encoded in sorted(evidence_by_key[key])]
        relation_id = "arel:" + hashlib.sha1("\x1f".join(key).encode("utf-8")).hexdigest()[:24]
        relations.append(
            {
                "relation_id": relation_id,
                "source_kind": source_kind,
                "source": source,
                "relation": relation,
                "target_kind": target_kind,
                "target": target,
                "target_coverage": target_coverage,
                "evidence_count": len(evidence),
                "evidence": evidence,
            }
        )

    outgoing: dict[str, list[dict]] = collections.defaultdict(list)
    incoming: dict[str, list[dict]] = collections.defaultdict(list)
    for relation in relations:
        outgoing[relation["source"]].append(relation)
        incoming[relation["target"]].append(relation)

    summaries = []
    contexts = []
    for path in sorted(roots):
        meta = roots[path]
        out = sorted(
            outgoing.get(path, []),
            key=lambda r: (r["relation"], r["target_kind"], r["target"], r["relation_id"]),
        )
        inc = sorted(
            incoming.get(path, []),
            key=lambda r: (r["relation"], r["source_kind"], r["source"], r["relation_id"]),
        )
        relation_counts = dict(sorted(collections.Counter(r["relation"] for r in out).items()))
        summary_lines = _meta_text(meta)
        summary_lines.append(f"Relations: outgoing={len(out)} incoming={len(inc)} {relation_counts}")
        summary_text = "\n".join(summary_lines)
        summary = {
            "asset_path": path,
            "asset_kind": meta.get("kind", ""),
            "class_path": meta.get("class_path", ""),
            "coverage": meta.get("coverage", ""),
            "package_name": meta.get("package_name", ""),
            "outgoing_count": len(out),
            "incoming_count": len(inc),
            "relation_counts": relation_counts,
            "text": summary_text,
        }
        summaries.append(summary)

        lines = list(summary_lines)
        if out:
            lines.append("Outgoing:")
            for relation in out[:MAX_CONTEXT_LINKS_PER_ASSET]:
                lines.append(
                    f"  {relation['relation']} -> {relation['target_kind']} "
                    f"{relation['target']} coverage={relation['target_coverage']} "
                    f"evidence={relation['evidence_count']}"
                )
        if inc:
            lines.append("Incoming:")
            remaining = max(0, MAX_CONTEXT_LINKS_PER_ASSET - min(len(out), MAX_CONTEXT_LINKS_PER_ASSET))
            for relation in inc[:remaining]:
                lines.append(
                    f"  {relation['source_kind']} {relation['source']} -> "
                    f"{relation['relation']} evidence={relation['evidence_count']}"
                )
        text = "\n".join(lines)
        truncated = len(text) > MAX_CONTEXT_CHARS
        if truncated:
            text = text[:MAX_CONTEXT_CHARS] + "\n...[truncated]"
        contexts.append(
            {
                "asset_path": path,
                "asset_kind": meta.get("kind", ""),
                "class_path": meta.get("class_path", ""),
                "coverage": meta.get("coverage", ""),
                "outgoing_count": len(out),
                "incoming_count": len(inc),
                "truncated": truncated,
                "text": text,
            }
        )

    return relations, contexts, summaries


def load_database(conn, output, rows) -> None:
    for row in rows(output / "animation_relations.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO animation_relations VALUES(?,?,?,?,?,?,?,?,?)",
            (
                row.get("relation_id", ""),
                row.get("source_kind", ""),
                row.get("source", ""),
                row.get("relation", ""),
                row.get("target_kind", ""),
                row.get("target", ""),
                row.get("target_coverage", ""),
                int(row.get("evidence_count", 0)),
                json.dumps(row.get("evidence", []), ensure_ascii=False, separators=(",", ":")),
            ),
        )
    for row in rows(output / "animation_context.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO animation_context VALUES(?,?,?,?,?,?,?,?,?)",
            (
                row.get("asset_path", ""),
                row.get("asset_kind", ""),
                row.get("class_path", ""),
                row.get("coverage", ""),
                int(row.get("outgoing_count", 0)),
                int(row.get("incoming_count", 0)),
                int(bool(row.get("truncated", False))),
                row.get("text", ""),
                json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            ),
        )
    for row in rows(output / "animation_summaries.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO animation_summaries VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("asset_path", ""),
                row.get("asset_kind", ""),
                row.get("class_path", ""),
                row.get("coverage", ""),
                row.get("package_name", ""),
                int(row.get("outgoing_count", 0)),
                int(row.get("incoming_count", 0)),
                json.dumps(row.get("relation_counts", {}), ensure_ascii=False, separators=(",", ":")),
                row.get("text", ""),
                json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            ),
        )


def query(conn, print_rows, q: str, limit: int) -> None:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='animation_summaries'"
    ).fetchone():
        return
    print("\n[animation summaries]")
    print_rows(
        conn.execute(
            "SELECT asset_path,asset_kind,outgoing_count,incoming_count,substr(text,1,1400) text "
            "FROM animation_summaries WHERE asset_path LIKE ? OR asset_kind LIKE ? OR text LIKE ? LIMIT ?",
            (q, q, q, limit),
        ),
        ("asset_path", "asset_kind", "outgoing_count", "incoming_count", "text"),
    )
    print("\n[animation relations]")
    print_rows(
        conn.execute(
            "SELECT source_kind,source,relation,target_kind,target,target_coverage,evidence_count "
            "FROM animation_relations WHERE source LIKE ? OR relation LIKE ? OR target LIKE ? "
            "OR target_kind LIKE ? OR evidence_json LIKE ? LIMIT ?",
            (q, q, q, q, q, limit),
        ),
        (
            "source_kind",
            "source",
            "relation",
            "target_kind",
            "target",
            "target_coverage",
            "evidence_count",
        ),
    )
    print("\n[animation context]")
    print_rows(
        conn.execute(
            "SELECT asset_path,asset_kind,substr(text,1,1800) text FROM animation_context "
            "WHERE asset_path LIKE ? OR asset_kind LIKE ? OR text LIKE ? LIMIT ?",
            (q, q, q, limit),
        ),
        ("asset_path", "asset_kind", "text"),
    )
