#!/usr/bin/env python3
"""Exact authored SkeletalMesh / PhysicsAsset graph model for animation schema 3.

Only normalized schema-3 rows are used. Synthetic node identities are namespaced
by their canonical owner so bone-name, LOD, shape, profile and collision-pair
nodes never imply cross-asset identity.
"""
from __future__ import annotations

RELATIONS = {
    "skeletal_mesh_uses_skeleton",
    "skeletal_mesh_uses_physics_asset",
    "skeletal_mesh_uses_shadow_physics_asset",
    "skeletal_mesh_uses_lod_settings",
    "skeletal_mesh_has_lod",
    "skeletal_mesh_uses_material",
    "skeletal_mesh_owns_morph_target",
    "skeletal_mesh_owns_clothing_asset",
    "clothing_asset_uses_physics_asset",
    "clothing_asset_has_config",
    "physics_asset_uses_preview_mesh",
    "physics_asset_owns_body",
    "physics_body_bound_to_bone_name",
    "physics_body_has_shape",
    "physics_asset_owns_constraint",
    "physics_constraint_uses_bone1_name",
    "physics_constraint_uses_bone2_name",
    "physics_asset_has_constraint_profile",
    "physics_asset_has_physical_animation_profile",
    "physics_asset_has_collision_disable_pair",
}

RELATION_STREAMS = {
    "skeletal_mesh_uses_skeleton": "skeletal_meshes.jsonl",
    "skeletal_mesh_uses_physics_asset": "skeletal_meshes.jsonl",
    "skeletal_mesh_uses_shadow_physics_asset": "skeletal_meshes.jsonl",
    "skeletal_mesh_uses_lod_settings": "skeletal_meshes.jsonl",
    "skeletal_mesh_has_lod": "skeletal_mesh_lods.jsonl",
    "skeletal_mesh_uses_material": "skeletal_mesh_materials.jsonl",
    "skeletal_mesh_owns_morph_target": "skeletal_mesh_morph_targets.jsonl",
    "skeletal_mesh_owns_clothing_asset": "skeletal_mesh_clothing_assets.jsonl",
    "clothing_asset_uses_physics_asset": "skeletal_mesh_clothing_assets.jsonl",
    "clothing_asset_has_config": "skeletal_mesh_clothing_configs.jsonl",
    "physics_asset_uses_preview_mesh": "physics_assets.jsonl",
    "physics_asset_owns_body": "physics_bodies.jsonl",
    "physics_body_bound_to_bone_name": "physics_bodies.jsonl",
    "physics_body_has_shape": "physics_body_shapes.jsonl",
    "physics_asset_owns_constraint": "physics_constraints.jsonl",
    "physics_constraint_uses_bone1_name": "physics_constraints.jsonl",
    "physics_constraint_uses_bone2_name": "physics_constraints.jsonl",
    "physics_asset_has_constraint_profile": "physics_constraint_profiles.jsonl",
    "physics_asset_has_physical_animation_profile": "physics_physical_animation_profiles.jsonl",
    "physics_asset_has_collision_disable_pair": "physics_collision_disable_pairs.jsonl",
}


def lod_path(mesh: str, index: int) -> str:
    return f"{mesh}#lod:{index}"


def bone_name_path(physics_asset: str, bone_name: str) -> str:
    return f"{physics_asset}#bone-name:{bone_name}"


def shape_path(body: str, shape_type: str, index: int) -> str:
    return f"{body}#shape:{shape_type}:{index}"


def constraint_profile_path(physics_asset: str, index: int, name: str) -> str:
    return f"{physics_asset}#constraint-profile:{index}:{name}"


def physical_animation_profile_path(physics_asset: str, index: int, name: str) -> str:
    return f"{physics_asset}#physical-animation-profile:{index}:{name}"


def collision_pair_path(physics_asset: str, index: int) -> str:
    return f"{physics_asset}#collision-disable:{index}"


def _node(path: str, kind: str, *, class_path: str = "", package_name: str = "", root: bool = False) -> dict:
    return {
        "path": str(path or ""),
        "kind": str(kind or "object"),
        "coverage": "first_class",
        "class_path": str(class_path or ""),
        "package_name": str(package_name or ""),
        "family": "animation_mesh_physics",
        "root": bool(root),
    }


def _edge(source: str, relation: str, target: str, source_kind: str, target_kind: str, stream: str, **detail) -> dict:
    evidence = {
        "kind": "canonical_animation_mesh_physics",
        "stream": stream,
        "quality": "exact_semantic",
    }
    evidence.update({k: v for k, v in detail.items() if v not in (None, "")})
    return {
        "source": str(source or ""),
        "relation": str(relation or ""),
        "target": str(target or ""),
        "source_kind": str(source_kind or "object"),
        "target_kind": str(target_kind or "object"),
        "evidence": evidence,
    }


def build_model(output, rows) -> dict:
    nodes: dict[tuple[str, str], dict] = {}
    edges: dict[tuple[str, str, str, str, str], dict] = {}

    def add_node(spec: dict) -> None:
        path = spec.get("path", "")
        kind = spec.get("kind", "")
        if not path or not kind:
            return
        nodes[(kind, path)] = spec

    def add_edge(spec: dict) -> None:
        if not spec["source"] or not spec["target"] or not spec["relation"]:
            return
        key = (
            spec["source_kind"], spec["source"], spec["relation"],
            spec["target_kind"], spec["target"],
        )
        edges[key] = spec

    meshes = list(rows(output / "skeletal_meshes.jsonl"))
    physics_assets = list(rows(output / "physics_assets.jsonl"))
    for row in meshes:
        mesh = str(row.get("skeletal_mesh_path", ""))
        add_node(_node(mesh, "skeletal_mesh", class_path=row.get("class_path", ""), package_name=row.get("package_name", ""), root=True))
        for relation, field_name, target_kind in (
            ("skeletal_mesh_uses_skeleton", "skeleton_path", "skeleton"),
            ("skeletal_mesh_uses_physics_asset", "physics_asset_path", "physics_asset"),
            ("skeletal_mesh_uses_shadow_physics_asset", "shadow_physics_asset_path", "physics_asset"),
            ("skeletal_mesh_uses_lod_settings", "lod_settings_path", "skeletal_mesh_lod_settings"),
        ):
            target = str(row.get(field_name, ""))
            if target:
                add_node(_node(target, target_kind))
                add_edge(_edge(mesh, relation, target, "skeletal_mesh", target_kind, "skeletal_meshes.jsonl", field=field_name))

    for row in rows(output / "skeletal_mesh_lods.jsonl"):
        mesh = str(row.get("skeletal_mesh_path", "")); index = int(row.get("lod_index", 0) or 0)
        target = lod_path(mesh, index)
        add_node(_node(target, "skeletal_mesh_lod"))
        add_edge(_edge(mesh, "skeletal_mesh_has_lod", target, "skeletal_mesh", "skeletal_mesh_lod", "skeletal_mesh_lods.jsonl", lod_index=index))

    for row in rows(output / "skeletal_mesh_materials.jsonl"):
        mesh = str(row.get("skeletal_mesh_path", "")); target = str(row.get("material_path", ""))
        if target:
            add_node(_node(target, "material", class_path=row.get("material_class", "")))
            add_edge(_edge(mesh, "skeletal_mesh_uses_material", target, "skeletal_mesh", "material", "skeletal_mesh_materials.jsonl", material_index=int(row.get("material_index", 0) or 0), material_slot_name=str(row.get("material_slot_name", ""))))

    clothing_nodes = set()
    for row in rows(output / "skeletal_mesh_morph_targets.jsonl"):
        mesh = str(row.get("skeletal_mesh_path", "")); target = str(row.get("morph_target_path", ""))
        add_node(_node(target, "morph_target", class_path=row.get("class_path", "")))
        add_edge(_edge(mesh, "skeletal_mesh_owns_morph_target", target, "skeletal_mesh", "morph_target", "skeletal_mesh_morph_targets.jsonl", morph_index=int(row.get("morph_index", 0) or 0)))

    for row in rows(output / "skeletal_mesh_clothing_assets.jsonl"):
        mesh = str(row.get("skeletal_mesh_path", "")); target = str(row.get("clothing_asset_path", ""))
        add_node(_node(target, "clothing_asset", class_path=row.get("class_path", "")))
        clothing_nodes.add(target)
        add_edge(_edge(mesh, "skeletal_mesh_owns_clothing_asset", target, "skeletal_mesh", "clothing_asset", "skeletal_mesh_clothing_assets.jsonl", clothing_index=int(row.get("clothing_index", 0) or 0)))
        physics = str(row.get("physics_asset_path", ""))
        if physics:
            add_node(_node(physics, "physics_asset"))
            add_edge(_edge(target, "clothing_asset_uses_physics_asset", physics, "clothing_asset", "physics_asset", "skeletal_mesh_clothing_assets.jsonl", clothing_index=int(row.get("clothing_index", 0) or 0)))

    for row in rows(output / "skeletal_mesh_clothing_configs.jsonl"):
        clothing = str(row.get("clothing_asset_path", "")); target = str(row.get("config_path", ""))
        add_node(_node(target, "clothing_config", class_path=row.get("config_class", "")))
        add_edge(_edge(clothing, "clothing_asset_has_config", target, "clothing_asset", "clothing_config", "skeletal_mesh_clothing_configs.jsonl", config_index=int(row.get("config_index", 0) or 0)))

    for row in physics_assets:
        physics = str(row.get("physics_asset_path", ""))
        add_node(_node(physics, "physics_asset", class_path=row.get("class_path", ""), package_name=row.get("package_name", ""), root=True))
        preview = str(row.get("preview_skeletal_mesh_path", ""))
        if preview:
            add_node(_node(preview, "skeletal_mesh"))
            add_edge(_edge(physics, "physics_asset_uses_preview_mesh", preview, "physics_asset", "skeletal_mesh", "physics_assets.jsonl", field="preview_skeletal_mesh_path"))

    for row in rows(output / "physics_bodies.jsonl"):
        physics = str(row.get("physics_asset_path", "")); body = str(row.get("body_path", "")); index = int(row.get("body_index", 0) or 0)
        add_node(_node(body, "physics_body", class_path=row.get("body_class", "")))
        add_edge(_edge(physics, "physics_asset_owns_body", body, "physics_asset", "physics_body", "physics_bodies.jsonl", body_index=index))
        bone = str(row.get("bone_name", ""))
        if bone:
            target = bone_name_path(physics, bone)
            add_node(_node(target, "physics_bone_name"))
            add_edge(_edge(body, "physics_body_bound_to_bone_name", target, "physics_body", "physics_bone_name", "physics_bodies.jsonl", body_index=index, bone_name=bone))

    for row in rows(output / "physics_body_shapes.jsonl"):
        body = str(row.get("body_path", "")); physics = str(row.get("physics_asset_path", "")); shape_type = str(row.get("shape_type", "")); index = int(row.get("shape_index", 0) or 0)
        target = shape_path(body, shape_type, index)
        add_node(_node(target, "physics_shape"))
        add_edge(_edge(body, "physics_body_has_shape", target, "physics_body", "physics_shape", "physics_body_shapes.jsonl", body_index=int(row.get("body_index", 0) or 0), shape_type=shape_type, shape_index=index, shape_struct=str(row.get("shape_struct", ""))))

    for row in rows(output / "physics_constraints.jsonl"):
        physics = str(row.get("physics_asset_path", "")); constraint = str(row.get("constraint_path", "")); index = int(row.get("constraint_index", 0) or 0)
        add_node(_node(constraint, "physics_constraint", class_path=row.get("constraint_class", "")))
        add_edge(_edge(physics, "physics_asset_owns_constraint", constraint, "physics_asset", "physics_constraint", "physics_constraints.jsonl", constraint_index=index, joint_name=str(row.get("joint_name", ""))))
        for relation, field_name in (("physics_constraint_uses_bone1_name", "constraint_bone1"), ("physics_constraint_uses_bone2_name", "constraint_bone2")):
            bone = str(row.get(field_name, ""))
            if bone:
                target = bone_name_path(physics, bone)
                add_node(_node(target, "physics_bone_name"))
                add_edge(_edge(constraint, relation, target, "physics_constraint", "physics_bone_name", "physics_constraints.jsonl", constraint_index=index, bone_name=bone))

    for row in rows(output / "physics_constraint_profiles.jsonl"):
        physics = str(row.get("physics_asset_path", "")); index = int(row.get("profile_index", 0) or 0); name = str(row.get("profile_name", ""))
        target = constraint_profile_path(physics, index, name)
        add_node(_node(target, "physics_constraint_profile"))
        add_edge(_edge(physics, "physics_asset_has_constraint_profile", target, "physics_asset", "physics_constraint_profile", "physics_constraint_profiles.jsonl", profile_index=index, profile_name=name))

    for row in rows(output / "physics_physical_animation_profiles.jsonl"):
        physics = str(row.get("physics_asset_path", "")); index = int(row.get("profile_index", 0) or 0); name = str(row.get("profile_name", ""))
        target = physical_animation_profile_path(physics, index, name)
        add_node(_node(target, "physics_physical_animation_profile"))
        add_edge(_edge(physics, "physics_asset_has_physical_animation_profile", target, "physics_asset", "physics_physical_animation_profile", "physics_physical_animation_profiles.jsonl", profile_index=index, profile_name=name))

    for row in rows(output / "physics_collision_disable_pairs.jsonl"):
        physics = str(row.get("physics_asset_path", "")); index = int(row.get("pair_index", 0) or 0)
        target = collision_pair_path(physics, index)
        add_node(_node(target, "physics_collision_disable_pair"))
        add_edge(_edge(physics, "physics_asset_has_collision_disable_pair", target, "physics_asset", "physics_collision_disable_pair", "physics_collision_disable_pairs.jsonl", pair_index=index))

    return {
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edge_specs": [edges[key] for key in sorted(edges)],
        "counts": {
            "skeletal_meshes": len(meshes),
            "physics_assets": len(physics_assets),
            "first_class_nodes": len(nodes),
            "exact_semantic_edges": len(edges),
        },
    }


def expected_edge_keys(output, rows) -> set[tuple[str, str, str]]:
    return {
        (spec["source"], spec["relation"], spec["target"])
        for spec in build_model(output, rows)["edge_specs"]
    }
