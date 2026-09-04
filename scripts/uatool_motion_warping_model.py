#!/usr/bin/env python3
"""Exact authored graph model for Motion Warping animation schema 4."""
from __future__ import annotations

RELATIONS = {
    "animation_asset_has_motion_warping_window",
    "motion_warping_window_owns_modifier",
    "motion_warping_modifier_targets_name",
    "motion_warping_modifier_uses_warp_point_bone_name",
    "motion_warping_modifier_uses_easing_curve",
}

RELATION_STREAMS = {
    "animation_asset_has_motion_warping_window": "motion_warping_windows.jsonl",
    "motion_warping_window_owns_modifier": "motion_warping_modifiers.jsonl",
    "motion_warping_modifier_targets_name": "motion_warping_modifiers.jsonl",
    "motion_warping_modifier_uses_warp_point_bone_name": "motion_warping_modifiers.jsonl",
    "motion_warping_modifier_uses_easing_curve": "motion_warping_modifiers.jsonl",
}


def window_path(asset: str, notify_index: int) -> str:
    return f"{asset}#motion-warping-window:{notify_index}"


def target_name_path(name: str) -> str:
    return f"motion-warp-target-name:{name}"


def bone_name_path(name: str) -> str:
    return f"bone-name:{name}"


def _node(path: str, kind: str, *, class_path: str = "", package_name: str = "", family: str = "motion_warping", root: bool = False) -> dict:
    return {
        "path": str(path or ""),
        "kind": str(kind or "object"),
        "coverage": "first_class",
        "class_path": str(class_path or ""),
        "package_name": str(package_name or ""),
        "family": family,
        "root": bool(root),
    }


def _edge(source: str, relation: str, target: str, source_kind: str, target_kind: str, stream: str, **detail) -> dict:
    evidence = {
        "kind": "canonical_motion_warping",
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

    for row in rows(output / "motion_warping_windows.jsonl"):
        asset = str(row.get("asset_path", ""))
        index = int(row.get("notify_index", -1))
        window = window_path(asset, index)
        add_node(_node(asset, "animation_asset", class_path=str(row.get("asset_class", "")), family="animation", root=True))
        add_node(_node(window, "motion_warping_window", class_path=str(row.get("notify_state_class", ""))))
        add_edge(_edge(
            asset,
            "animation_asset_has_motion_warping_window",
            window,
            "animation_asset",
            "motion_warping_window",
            "motion_warping_windows.jsonl",
            notify_index=index,
            notify_guid=str(row.get("notify_guid", "")),
            notify_state_path=str(row.get("notify_state_path", "")),
            trigger_time=float(row.get("trigger_time", 0.0) or 0.0),
            duration=float(row.get("duration", 0.0) or 0.0),
        ))

    for row in rows(output / "motion_warping_modifiers.jsonl"):
        asset = str(row.get("asset_path", ""))
        index = int(row.get("notify_index", -1))
        window = window_path(asset, index)
        modifier = str(row.get("modifier_path", ""))
        modifier_class = str(row.get("modifier_class", ""))
        add_node(_node(window, "motion_warping_window"))
        add_node(_node(modifier, "motion_warping_modifier", class_path=modifier_class))
        add_edge(_edge(
            window,
            "motion_warping_window_owns_modifier",
            modifier,
            "motion_warping_window",
            "motion_warping_modifier",
            "motion_warping_modifiers.jsonl",
            modifier_class=modifier_class,
        ))

        target_name = str(row.get("warp_target_name", ""))
        if target_name not in ("", "None"):
            target = target_name_path(target_name)
            add_node(_node(target, "motion_warp_target_name"))
            add_edge(_edge(
                modifier,
                "motion_warping_modifier_targets_name",
                target,
                "motion_warping_modifier",
                "motion_warp_target_name",
                "motion_warping_modifiers.jsonl",
                warp_target_name=target_name,
            ))

        provider = str(row.get("warp_point_anim_provider", ""))
        bone_name = str(row.get("warp_point_anim_bone_name", ""))
        if provider == "Bone" and bone_name not in ("", "None"):
            target = bone_name_path(bone_name)
            add_node(_node(target, "bone_name", family="animation"))
            add_edge(_edge(
                modifier,
                "motion_warping_modifier_uses_warp_point_bone_name",
                target,
                "motion_warping_modifier",
                "bone_name",
                "motion_warping_modifiers.jsonl",
                provider=provider,
                bone_name=bone_name,
            ))

        easing_curve = str(row.get("add_translation_easing_curve", ""))
        if easing_curve:
            easing_class = str(row.get("add_translation_easing_curve_class", ""))
            add_node(_node(easing_curve, "curve_asset", class_path=easing_class, family="asset_registry"))
            add_edge(_edge(
                modifier,
                "motion_warping_modifier_uses_easing_curve",
                easing_curve,
                "motion_warping_modifier",
                "curve_asset",
                "motion_warping_modifiers.jsonl",
                field="add_translation_easing_curve",
            ))

    return {
        "nodes": [nodes[key] for key in sorted(nodes)],
        "edge_specs": [edges[key] for key in sorted(edges)],
        "counts": {
            "first_class_nodes": len(nodes),
            "exact_semantic_edges": len(edges),
        },
    }


def expected_edge_keys(output, rows) -> set[tuple[str, str, str]]:
    return {
        (spec["source"], spec["relation"], spec["target"])
        for spec in build_model(output, rows)["edge_specs"]
    }
