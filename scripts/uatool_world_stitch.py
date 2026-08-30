#!/usr/bin/env python3
"""Derived world-to-system bridge relations for UnrealAssetTool.

This module never invents a target from names. It joins already-extracted facts:
placed actors/components, Blueprint relations, Asset Registry dependencies, and
specialist AI/PCG/material/Blueprint/animation streams.
"""

from __future__ import annotations

import collections
import hashlib
import json


SYSTEM_DERIVED_FILE = "world_system_relations.jsonl"
MAX_CONTEXT_LINKS_PER_WORLD = 200
MAX_CONTEXT_CHARS = 524288

SYSTEM_SQL = """
CREATE TABLE world_system_relations(
    relation_id TEXT PRIMARY KEY,
    world_path TEXT NOT NULL,
    actor_path TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target TEXT NOT NULL,
    evidence_count INTEGER NOT NULL,
    evidence_json TEXT NOT NULL
);
CREATE INDEX world_system_relations_world_idx
    ON world_system_relations(world_path, relation);
CREATE INDEX world_system_relations_source_idx
    ON world_system_relations(source_id, relation);
CREATE INDEX world_system_relations_target_idx
    ON world_system_relations(target, relation);
"""


def _package_from_object_path(path: str) -> str:
    return str(path or "").split(".", 1)[0]


def _blueprint_kind(row: dict) -> tuple[str, str]:
    class_path = str(row.get("class", ""))
    if class_path == "/Script/Engine.AnimBlueprint":
        return "animation_blueprint", "references_animation_blueprint"
    if "ControlRigBlueprint" in class_path:
        return "control_rig_blueprint", "references_control_rig_blueprint"
    if "WidgetBlueprint" in class_path:
        return "widget_blueprint", "references_widget_blueprint"
    return "blueprint", "references_blueprint"


def _material_kind(row: dict) -> tuple[str, str]:
    target_kind = {
        "material": "material",
        "instance": "material_instance",
        "function": "material_function",
    }.get(str(row.get("material_kind", "")), "material")
    return target_kind, "references_material"


def _animation_relation(kind: str) -> str:
    kind = str(kind or "")
    if kind == "skeleton":
        return "references_skeleton"
    if kind in {"anim_sequence", "anim_montage", "blend_space", "pose_asset"}:
        return "references_animation_asset"
    if kind == "pose_search_database":
        return "references_pose_search_database"
    if kind == "pose_search_schema":
        return "references_pose_search_schema"
    if kind == "pose_search_interaction_asset":
        return "references_pose_search_interaction_asset"
    if kind == "pose_search_normalization_set":
        return "references_pose_search_normalization_set"
    if kind == "mirror_data_table":
        return "references_mirror_data_table"
    if kind == "chooser_table":
        return "references_chooser_table"
    if kind == "proxy_table":
        return "references_proxy_table"
    if kind == "proxy_asset":
        return "references_proxy_asset"
    if kind == "ik_rig":
        return "references_ik_rig"
    if kind == "ik_retargeter":
        return "references_ik_retargeter"
    return "references_animation_asset"


def derive(output, rows) -> list[dict]:
    """Return deterministic world-to-system bridge relations."""

    targets: dict[str, tuple[str, str, str]] = {}
    package_targets: dict[str, set[tuple[str, str, str]]] = collections.defaultdict(set)

    def register(path: str, target_kind: str, relation: str, *, package_join: bool = True) -> None:
        path = str(path or "")
        if not path:
            return
        targets[path] = (path, target_kind, relation)
        if package_join:
            package_targets[_package_from_object_path(path)].add((path, target_kind, relation))

    blueprints = list(rows(output / "blueprints.jsonl"))
    for blueprint in blueprints:
        target_kind, relation = _blueprint_kind(blueprint)
        object_path = str(blueprint.get("object_path", ""))
        generated_class = str(blueprint.get("generated_class", ""))
        if object_path:
            register(object_path, target_kind, relation)
        if generated_class and object_path:
            # Generated classes normalize back to the authored Blueprint asset.
            targets[generated_class] = (object_path, target_kind, relation)

    specialist_streams = (
        ("behavior_trees.jsonl", "behavior_tree_path", "behavior_tree", "references_behavior_tree"),
        ("blackboards.jsonl", "blackboard_path", "blackboard", "references_blackboard"),
        ("eqs_queries.jsonl", "eqs_path", "eqs_query", "references_eqs_query"),
        ("statetrees.jsonl", "statetree_path", "statetree", "references_statetree"),
        ("pcg_graphs.jsonl", "pcg_path", "pcg_graph", "references_pcg_graph"),
    )
    for filename, path_key, target_kind, relation in specialist_streams:
        for row in rows(output / filename):
            register(str(row.get(path_key, "")), target_kind, relation)

    for material in rows(output / "materials.jsonl"):
        target_kind, relation = _material_kind(material)
        register(str(material.get("material_path", "")), target_kind, relation)

    # Animation schema targets participate in exact world/property and Blueprint
    # relation joins, but deliberately do NOT participate in package dependency
    # resolution. Animation packages are numerous and package-level fan-out would
    # obscure stronger authored object references.
    for row in rows(output / "animation_assets.jsonl"):
        path = str(row.get("animation_path", ""))
        kind = str(row.get("animation_kind", "animation_asset"))
        register(path, kind, _animation_relation(kind), package_join=False)

    deep_animation_streams = (
        ("pose_search_interaction_assets.jsonl", "interaction_path", "pose_search_interaction_asset"),
        ("pose_search_normalization_sets.jsonl", "normalization_set_path", "pose_search_normalization_set"),
        ("mirror_data_tables.jsonl", "mirror_table_path", "mirror_data_table"),
    )
    for filename, path_key, kind in deep_animation_streams:
        for row in rows(output / filename):
            register(str(row.get(path_key, "")), kind, _animation_relation(kind), package_join=False)

    # A package dependency resolves to an exact specialist asset only when that
    # package maps to one authored specialist entity. Ambiguous packages remain
    # unasserted rather than guessed.
    unique_package_target = {
        package: next(iter(values))
        for package, values in package_targets.items()
        if len(values) == 1
    }

    evidence_by_relation: dict[tuple[str, ...], dict[str, dict]] = collections.defaultdict(dict)

    def add(
        world_path: str,
        actor_path: str,
        source_kind: str,
        source_id: str,
        relation: str,
        target_kind: str,
        target: str,
        evidence: dict,
    ) -> None:
        if not (world_path and source_id and relation and target):
            return
        key = (
            str(world_path),
            str(actor_path or ""),
            str(source_kind),
            str(source_id),
            str(relation),
            str(target_kind),
            str(target),
        )
        evidence_json = json.dumps(
            evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        evidence_by_relation[key][evidence_json] = evidence

    world_references = list(rows(output / "world_references.jsonl"))
    for reference in world_references:
        original_target = str(reference.get("target_path", ""))
        resolved = targets.get(original_target)
        if not resolved:
            continue
        target, target_kind, relation = resolved
        add(
            str(reference.get("world_path", "")),
            str(reference.get("actor_path", "")),
            str(reference.get("owner_kind", "object")),
            str(reference.get("owner_path", "")),
            relation,
            target_kind,
            target,
            {
                "kind": "world_reference",
                "property_path": str(reference.get("property_path", "")),
                "reference_kind": str(reference.get("reference_kind", "")),
                "authored_override": bool(reference.get("authored_override", False)),
                "original_target": original_target,
            },
        )

    blueprint_relations_by_blueprint: dict[str, list[dict]] = collections.defaultdict(list)
    for relation in rows(output / "blueprint_relations.jsonl"):
        blueprint_relations_by_blueprint[str(relation.get("blueprint_path", ""))].append(relation)

    dependencies = list(rows(output / "asset_dependencies.jsonl"))
    dependencies_by_source: dict[str, list[dict]] = collections.defaultdict(list)
    for dependency in dependencies:
        dependencies_by_source[str(dependency.get("source_package", ""))].append(dependency)

    actors = list(rows(output / "world_actors.jsonl"))
    for actor in actors:
        world_path = str(actor.get("world_path", ""))
        actor_path = str(actor.get("actor_path", ""))
        blueprint_path = str(actor.get("blueprint_asset", ""))
        if not blueprint_path:
            continue

        blueprint_target = targets.get(blueprint_path)
        if blueprint_target:
            target, target_kind, _ = blueprint_target
            add(
                world_path,
                actor_path,
                "actor",
                actor_path,
                "instantiates_blueprint",
                target_kind,
                target,
                {
                    "kind": "placed_actor_class",
                    "blueprint_path": blueprint_path,
                    "generated_class": str(actor.get("generated_class", "")),
                },
            )

        for blueprint_relation in blueprint_relations_by_blueprint.get(blueprint_path, []):
            original_target = str(blueprint_relation.get("target", ""))
            resolved = targets.get(original_target)
            if not resolved:
                continue
            target, target_kind, relation = resolved
            add(
                world_path,
                actor_path,
                "actor",
                actor_path,
                relation,
                target_kind,
                target,
                {
                    "kind": "blueprint_relation",
                    "blueprint_path": blueprint_path,
                    "relation_id": str(blueprint_relation.get("relation_id", "")),
                    "blueprint_relation": str(blueprint_relation.get("relation", "")),
                    "graph_id": str(blueprint_relation.get("graph_id", "")),
                    "original_target": original_target,
                },
            )

        blueprint_package = _package_from_object_path(blueprint_path)
        for dependency in dependencies_by_source.get(blueprint_package, []):
            resolved = unique_package_target.get(str(dependency.get("target_package", "")))
            if not resolved:
                continue
            target, target_kind, relation = resolved
            add(
                world_path,
                actor_path,
                "actor",
                actor_path,
                relation,
                target_kind,
                target,
                {
                    "kind": "blueprint_asset_dependency",
                    "blueprint_path": blueprint_path,
                    "source_package": blueprint_package,
                    "target_package": str(dependency.get("target_package", "")),
                    "category": str(dependency.get("category", "")),
                },
            )

    # World-package dependencies provide a factual map-level bridge for authored
    # programs (especially standalone PCG volumes) when no actor-specific raw
    # property exposes the graph asset. Materials and animation assets are
    # deliberately excluded here because package-level fan-out is too broad for
    # a useful semantic bridge; actor/component/property references remain exact.
    program_target_kinds = {
        "blueprint",
        "animation_blueprint",
        "control_rig_blueprint",
        "widget_blueprint",
        "behavior_tree",
        "blackboard",
        "eqs_query",
        "statetree",
        "pcg_graph",
    }
    world_by_package = {
        str(world.get("package_name", "")): str(world.get("world_path", ""))
        for world in rows(output / "worlds.jsonl")
        if world.get("package_name") and world.get("world_path")
    }
    for dependency in dependencies:
        world_path = world_by_package.get(str(dependency.get("source_package", "")))
        if not world_path:
            continue
        resolved = unique_package_target.get(str(dependency.get("target_package", "")))
        if not resolved:
            continue
        target, target_kind, relation = resolved
        if target_kind not in program_target_kinds:
            continue
        add(
            world_path,
            "",
            "world",
            world_path,
            relation,
            target_kind,
            target,
            {
                "kind": "world_asset_dependency",
                "source_package": str(dependency.get("source_package", "")),
                "target_package": str(dependency.get("target_package", "")),
                "category": str(dependency.get("category", "")),
            },
        )

    result = []
    for key, evidence_map in evidence_by_relation.items():
        world_path, actor_path, source_kind, source_id, relation, target_kind, target = key
        evidence = [evidence_map[token] for token in sorted(evidence_map)]
        relation_id = "wsrel:" + hashlib.sha1("\x1f".join(key).encode()).hexdigest()[:24]
        result.append(
            {
                "relation_id": relation_id,
                "world_path": world_path,
                "actor_path": actor_path,
                "source_kind": source_kind,
                "source_id": source_id,
                "relation": relation,
                "target_kind": target_kind,
                "target": target,
                "evidence_count": len(evidence),
                "evidence": evidence,
            }
        )

    result.sort(
        key=lambda row: (
            row["world_path"],
            row["source_kind"],
            row["source_id"],
            row["relation"],
            row["target_kind"],
            row["target"],
            row["relation_id"],
        )
    )
    return result


def augment_context(context_rows: list[dict], system_relations: list[dict]) -> list[dict]:
    by_world: dict[str, list[dict]] = collections.defaultdict(list)
    for relation in system_relations:
        by_world[str(relation.get("world_path", ""))].append(relation)

    for context in context_rows:
        world_path = str(context.get("world_path", ""))
        relations = by_world.get(world_path, [])
        counts = collections.Counter(row["relation"] for row in relations)
        context["system_relation_count"] = len(relations)
        context["system_relation_counts"] = dict(sorted(counts.items()))
        if not relations:
            continue

        lines = [
            f"System links: {len(relations)} {dict(sorted(counts.items()))}",
            "System relation examples:",
        ]
        for row in relations[:MAX_CONTEXT_LINKS_PER_WORLD]:
            lines.append(
                f"  {row['source_kind']} {row['source_id']} -> {row['relation']} -> "
                f"{row['target_kind']} {row['target']}"
            )
        if len(relations) > MAX_CONTEXT_LINKS_PER_WORLD:
            lines.append(
                f"  ... {len(relations) - MAX_CONTEXT_LINKS_PER_WORLD} more system links"
            )
        text = "\n".join(lines) + "\n" + str(context.get("text", ""))
        truncated = len(text) > MAX_CONTEXT_CHARS
        if truncated:
            text = text[:MAX_CONTEXT_CHARS] + "\n...[truncated]"
        context["text"] = text
        context["truncated"] = bool(context.get("truncated", False) or truncated)

    return context_rows


def create_schema(conn) -> None:
    conn.executescript(SYSTEM_SQL)


def load_database(conn, output, rows) -> None:
    for row in rows(output / SYSTEM_DERIVED_FILE):
        conn.execute(
            "INSERT OR REPLACE INTO world_system_relations VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("relation_id", ""),
                row.get("world_path", ""),
                row.get("actor_path", ""),
                row.get("source_kind", ""),
                row.get("source_id", ""),
                row.get("relation", ""),
                row.get("target_kind", ""),
                row.get("target", ""),
                row.get("evidence_count", 0),
                json.dumps(row.get("evidence", []), ensure_ascii=False, separators=(",", ":")),
            ),
        )


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_system_relations'"
    ).fetchone():
        return
    print("\n[world system relations]")
    print_rows(
        conn.execute(
            "SELECT world_path,actor_path,source_kind,source_id,relation,target_kind,target,evidence_count "
            "FROM world_system_relations WHERE world_path LIKE ? OR actor_path LIKE ? "
            "OR source_id LIKE ? OR relation LIKE ? OR target LIKE ? OR evidence_json LIKE ? LIMIT ?",
            (pattern, pattern, pattern, pattern, pattern, pattern, limit),
        ),
        (
            "world_path",
            "actor_path",
            "source_kind",
            "source_id",
            "relation",
            "target_kind",
            "target",
            "evidence_count",
        ),
    )
