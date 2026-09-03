#!/usr/bin/env python3
"""Exact authored StaticMesh graph model for mesh schema 1."""
from __future__ import annotations

RELATIONS = {
    "static_mesh_has_lod",
    "static_mesh_has_material_slot",
    "static_mesh_owns_socket",
    "static_mesh_has_body_setup",
    "static_mesh_uses_complex_collision_mesh",
    "material_slot_uses_material",
    "body_setup_has_collision_shape",
}

RELATION_STREAMS = {
    "static_mesh_has_lod": "static_mesh_lods.jsonl",
    "static_mesh_has_material_slot": "static_mesh_material_slots.jsonl",
    "static_mesh_owns_socket": "static_mesh_sockets.jsonl",
    "static_mesh_has_body_setup": "static_mesh_body_setups.jsonl",
    "static_mesh_uses_complex_collision_mesh": "static_meshes.jsonl",
    "material_slot_uses_material": "static_mesh_material_slots.jsonl",
    "body_setup_has_collision_shape": "static_mesh_collision_shapes.jsonl",
}


def lod_path(mesh: str, index: int) -> str:
    return f"{mesh}#lod:{index}"


def material_slot_path(mesh: str, index: int) -> str:
    return f"{mesh}#material-slot:{index}"


def shape_path(body_setup: str, shape_type: str, index: int) -> str:
    return f"{body_setup}#shape:{shape_type}:{index}"


def _node(path: str, kind: str, *, class_path: str = "", package_name: str = "", root: bool = False) -> dict:
    return {
        "path": str(path or ""),
        "kind": str(kind or "object"),
        "coverage": "first_class",
        "class_path": str(class_path or ""),
        "package_name": str(package_name or ""),
        "family": "static_mesh",
        "root": bool(root),
    }


def _edge(source: str, relation: str, target: str, source_kind: str, target_kind: str, stream: str, **detail) -> dict:
    evidence = {
        "kind": "canonical_static_mesh",
        "stream": stream,
        "quality": "exact_semantic",
    }
    evidence.update({key: value for key, value in detail.items() if value not in (None, "")})
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
        path = str(spec.get("path", "")); kind = str(spec.get("kind", ""))
        if path and kind:
            nodes[(kind, path)] = spec

    def add_edge(spec: dict) -> None:
        if not spec["source"] or not spec["target"] or not spec["relation"]:
            return
        key = (spec["source_kind"], spec["source"], spec["relation"], spec["target_kind"], spec["target"])
        edges[key] = spec

    meshes = list(rows(output / "static_meshes.jsonl"))
    for row in meshes:
        mesh = str(row.get("static_mesh_path", ""))
        add_node(_node(
            mesh, "static_mesh",
            class_path=str(row.get("class_path", "")),
            package_name=str(row.get("package_name", "")),
            root=True,
        ))
        complex_collision = str(row.get("complex_collision_mesh_path", ""))
        if complex_collision:
            add_node(_node(complex_collision, "static_mesh"))
            add_edge(_edge(
                mesh, "static_mesh_uses_complex_collision_mesh", complex_collision,
                "static_mesh", "static_mesh", "static_meshes.jsonl",
                field="complex_collision_mesh_path",
            ))

    for row in rows(output / "static_mesh_lods.jsonl"):
        mesh = str(row.get("static_mesh_path", "")); index = int(row.get("lod_index", 0) or 0)
        target = lod_path(mesh, index)
        add_node(_node(target, "static_mesh_lod"))
        add_edge(_edge(
            mesh, "static_mesh_has_lod", target,
            "static_mesh", "static_mesh_lod", "static_mesh_lods.jsonl",
            lod_index=index,
        ))

    for row in rows(output / "static_mesh_material_slots.jsonl"):
        mesh = str(row.get("static_mesh_path", "")); index = int(row.get("material_index", 0) or 0)
        slot = material_slot_path(mesh, index)
        add_node(_node(slot, "static_mesh_material_slot"))
        add_edge(_edge(
            mesh, "static_mesh_has_material_slot", slot,
            "static_mesh", "static_mesh_material_slot", "static_mesh_material_slots.jsonl",
            material_index=index,
            material_slot_name=str(row.get("material_slot_name", "")),
        ))
        material = str(row.get("material_path", ""))
        if material:
            add_node(_node(material, "material", class_path=str(row.get("material_class", ""))))
            add_edge(_edge(
                slot, "material_slot_uses_material", material,
                "static_mesh_material_slot", "material", "static_mesh_material_slots.jsonl",
                material_index=index,
                material_slot_name=str(row.get("material_slot_name", "")),
            ))

    for row in rows(output / "static_mesh_sockets.jsonl"):
        mesh = str(row.get("static_mesh_path", "")); socket = str(row.get("socket_path", "")); index = int(row.get("socket_index", 0) or 0)
        add_node(_node(socket, "static_mesh_socket", class_path=str(row.get("socket_class", ""))))
        add_edge(_edge(
            mesh, "static_mesh_owns_socket", socket,
            "static_mesh", "static_mesh_socket", "static_mesh_sockets.jsonl",
            socket_index=index,
            socket_name=str(row.get("socket_name", "")),
        ))

    for row in rows(output / "static_mesh_body_setups.jsonl"):
        mesh = str(row.get("static_mesh_path", "")); body = str(row.get("body_setup_path", ""))
        add_node(_node(body, "static_mesh_body_setup", class_path=str(row.get("body_setup_class", ""))))
        add_edge(_edge(
            mesh, "static_mesh_has_body_setup", body,
            "static_mesh", "static_mesh_body_setup", "static_mesh_body_setups.jsonl",
            collision_trace_flag=str(row.get("collision_trace_flag", "")),
        ))

    for row in rows(output / "static_mesh_collision_shapes.jsonl"):
        body = str(row.get("body_setup_path", "")); shape_type = str(row.get("shape_type", "")); index = int(row.get("shape_index", 0) or 0)
        target = shape_path(body, shape_type, index)
        add_node(_node(target, "static_mesh_collision_shape", class_path=str(row.get("shape_struct", ""))))
        add_edge(_edge(
            body, "body_setup_has_collision_shape", target,
            "static_mesh_body_setup", "static_mesh_collision_shape", "static_mesh_collision_shapes.jsonl",
            shape_type=shape_type,
            shape_index=index,
            shape_struct=str(row.get("shape_struct", "")),
        ))

    return {
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edge_specs": [edges[key] for key in sorted(edges)],
        "counts": {
            "static_meshes": len(meshes),
            "first_class_nodes": len(nodes),
            "exact_semantic_edges": len(edges),
        },
    }


def expected_edge_keys(output, rows) -> set[tuple[str, str, str]]:
    return {
        (spec["source"], spec["relation"], spec["target"])
        for spec in build_model(output, rows)["edge_specs"]
    }
