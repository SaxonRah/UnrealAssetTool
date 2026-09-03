#!/usr/bin/env python3
"""Promote systems-schema-11 authored Navigation facts into derived schema 27."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TARGET_DERIVED_SCHEMA_VERSION = 27
NAV_SYSTEM_CLASS = "/Script/NavigationSystem.NavigationSystemV1"

RELATION_STREAMS = {
    "navigation_area_inherits_area": "navigation_areas.jsonl",
    "navigation_area_maps_agent_to_area": "navigation_area_agent_mappings.jsonl",
    "navigation_area_supports_agent": "navigation_areas.jsonl",
    "navigation_system_supports_agent": "navigation_agents.jsonl",
    "navigation_system_uses_crowd_manager": "navigation_systems.jsonl",
    "navigation_agent_uses_nav_data": "navigation_agents.jsonl",
    "navigation_agent_prefers_nav_data": "navigation_agents.jsonl",
    "navigation_link_uses_area": "navigation_link_defaults.jsonl",
    "navigation_link_supports_agent": "navigation_link_defaults.jsonl",
    "navigation_modifier_uses_area": "navigation_modifier_defaults.jsonl",
    "navigation_modifier_replaces_area": "navigation_modifier_defaults.jsonl",
    "navigation_invoker_supports_agent": "navigation_invoker_defaults.jsonl",
    "navigation_bounds_supports_agent": "navigation_bounds_defaults.jsonl",
    "navigation_recast_uses_area": "navigation_recast_defaults.jsonl",
}


def _meaningful(value) -> str:
    text = str(value or "")
    return "" if text in {"None", "null", "NULL"} else text


def agent_path(system: str, index: int, name: str) -> str:
    return f"{system}#NavigationAgent:{index}:{name}"


def _configured_agents(output: Path, rows):
    result = {}
    for row in rows(output / "navigation_agents.jsonl"):
        system = str(row.get("system_class", "") or "")
        index = int(row.get("agent_index", 0) or 0)
        name = str(row.get("name", "") or "")
        result[(system, index)] = agent_path(system, index, name)
    return result


def expected_edge_keys(output: Path, rows) -> set[tuple[str, str, str]]:
    output = Path(output)
    edges: set[tuple[str, str, str]] = set()

    def add(source, relation, target):
        source = _meaningful(source)
        target = _meaningful(target)
        if source and target and source != target:
            edges.add((source, relation, target))

    areas = {str(row.get("class_path", "") or "") for row in rows(output / "navigation_areas.jsonl")}
    configured = _configured_agents(output, rows)

    for row in rows(output / "navigation_areas.jsonl"):
        area = str(row.get("class_path", "") or "")
        parent = str(row.get("parent_class", "") or "")
        if parent in areas:
            add(area, "navigation_area_inherits_area", parent)
        supported = row.get("supported_agents", []) if isinstance(row.get("supported_agents"), list) else []
        for index in supported:
            target = configured.get((NAV_SYSTEM_CLASS, int(index)))
            if target:
                add(area, "navigation_area_supports_agent", target)

    for row in rows(output / "navigation_area_agent_mappings.jsonl"):
        add(row.get("source_area"), "navigation_area_maps_agent_to_area", row.get("target_area"))

    for row in rows(output / "navigation_systems.jsonl"):
        add(row.get("class_path"), "navigation_system_uses_crowd_manager", row.get("crowd_manager_class"))

    for row in rows(output / "navigation_agents.jsonl"):
        system = str(row.get("system_class", "") or "")
        index = int(row.get("agent_index", 0) or 0)
        name = str(row.get("name", "") or "")
        agent = agent_path(system, index, name)
        add(system, "navigation_system_supports_agent", agent)
        add(agent, "navigation_agent_uses_nav_data", row.get("nav_data_class"))
        add(agent, "navigation_agent_prefers_nav_data", row.get("preferred_nav_data"))

    for row in rows(output / "navigation_link_defaults.jsonl"):
        link = str(row.get("link_id", "") or "")
        for field in ("area_class", "enabled_area_class", "disabled_area_class", "obstacle_area_class"):
            add(link, "navigation_link_uses_area", row.get(field))
        supported = row.get("supported_agents", []) if isinstance(row.get("supported_agents"), list) else []
        for index in supported:
            target = configured.get((NAV_SYSTEM_CLASS, int(index)))
            if target:
                add(link, "navigation_link_supports_agent", target)

    for row in rows(output / "navigation_modifier_defaults.jsonl"):
        modifier = str(row.get("modifier_id", "") or "")
        add(modifier, "navigation_modifier_uses_area", row.get("area_class"))
        add(modifier, "navigation_modifier_replaces_area", row.get("area_class_to_replace"))

    for row in rows(output / "navigation_invoker_defaults.jsonl"):
        invoker = str(row.get("invoker_id", "") or "")
        supported = row.get("supported_agents", []) if isinstance(row.get("supported_agents"), list) else []
        for index in supported:
            target = configured.get((NAV_SYSTEM_CLASS, int(index)))
            if target:
                add(invoker, "navigation_invoker_supports_agent", target)

    for row in rows(output / "navigation_bounds_defaults.jsonl"):
        bounds = str(row.get("bounds_id", "") or "")
        supported = row.get("supported_agents", []) if isinstance(row.get("supported_agents"), list) else []
        for index in supported:
            target = configured.get((NAV_SYSTEM_CLASS, int(index)))
            if target:
                add(bounds, "navigation_bounds_supports_agent", target)

    for row in rows(output / "navigation_recast_defaults.jsonl"):
        recast = str(row.get("recast_id", "") or "")
        add(recast, "navigation_recast_uses_area", row.get("jump_down_area_class"))
        add(recast, "navigation_recast_uses_area", row.get("jump_up_area_class"))
    return edges


def _augment(output: Path, rows, nodes: list[dict], edges: list[dict], graph_module):
    node_by_key = {(str(node.get("node_kind", "")), str(node.get("path", ""))): node for node in nodes}

    def register(path, kind, coverage="first_class", class_path="", *, family="navigation", root=False):
        path = _meaningful(path)
        if not path:
            return None
        key = (kind, path)
        node = node_by_key.get(key)
        if node is None:
            node = {
                "node_id": graph_module._node_id(kind, path),
                "node_kind": kind,
                "path": path,
                "coverage": coverage,
                "class_path": str(class_path or ""),
                "package_name": graph_module._package(path),
                "family": family,
                "root": bool(root),
            }
            nodes.append(node)
            node_by_key[key] = node
        else:
            if graph_module.COVERAGE_RANK.get(coverage, -1) > graph_module.COVERAGE_RANK.get(str(node.get("coverage", "")), -1):
                node["coverage"] = coverage
            if class_path and not node.get("class_path"):
                node["class_path"] = class_path
            if root:
                node["root"] = True
        return node

    edge_by_key = {
        (
            str(edge.get("source_kind", "")), str(edge.get("source", "")), str(edge.get("relation", "")),
            str(edge.get("target_kind", "")), str(edge.get("target", "")),
        ): edge for edge in edges
    }

    def add(source, relation, target, source_kind, target_kind, evidence, *, target_coverage="first_class", target_family="navigation"):
        source = _meaningful(source)
        target = _meaningful(target)
        if not source or not target or source == target:
            return
        source_node = node_by_key.get((source_kind, source)) or register(source, source_kind)
        target_node = node_by_key.get((target_kind, target)) or register(
            target, target_kind, coverage=target_coverage,
            class_path=target if target_kind == "class" else "", family=target_family,
        )
        if not source_node or not target_node:
            return
        key = (source_kind, source, relation, target_kind, target)
        value = dict(evidence)
        value.setdefault("quality", "exact_semantic")
        token = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        edge = edge_by_key.get(key)
        if edge is None:
            edge = {
                "edge_id": graph_module._edge_id(source_kind, source, relation, target_kind, target),
                "source_kind": source_kind,
                "source": source,
                "relation": relation,
                "target_kind": target_kind,
                "target": target,
                "source_coverage": source_node.get("coverage", "first_class"),
                "target_coverage": target_node.get("coverage", target_coverage),
                "edge_quality": "exact_semantic",
                "evidence_count": 1,
                "evidence": [value],
            }
            edges.append(edge)
            edge_by_key[key] = edge
        else:
            current = {
                json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                for item in edge.get("evidence", []) if isinstance(item, dict)
            }
            if token not in current:
                edge.setdefault("evidence", []).append(value)
                edge["evidence_count"] = len(edge["evidence"])
            edge["edge_quality"] = "exact_semantic"

    area_paths = set()
    for row in rows(output / "navigation_areas.jsonl"):
        area = str(row.get("class_path", "") or "")
        area_paths.add(area)
        register(area, "navigation_area", class_path=area, root=True)

    system_kind = {}
    for row in rows(output / "navigation_systems.jsonl"):
        system = str(row.get("class_path", "") or "")
        kind = "navigation_system" if row.get("system_kind") == "navigation_system" else "navigation_system_config"
        system_kind[system] = kind
        register(system, kind, class_path=system, root=True)
        crowd = _meaningful(row.get("crowd_manager_class"))
        if crowd:
            register(crowd, "class", coverage="partial", class_path=crowd, family="class")
            add(
                system, "navigation_system_uses_crowd_manager", crowd, kind, "class",
                {"stream": "navigation_systems.jsonl", "kind": "authored_navigation_system_crowd_manager"},
                target_coverage="partial", target_family="class",
            )

    configured = {}
    for row in rows(output / "navigation_agents.jsonl"):
        system = str(row.get("system_class", "") or "")
        index = int(row.get("agent_index", 0) or 0)
        name = str(row.get("name", "") or "")
        agent = agent_path(system, index, name)
        configured[(system, index)] = agent
        register(agent, "navigation_agent")
        add(
            system, "navigation_system_supports_agent", agent,
            system_kind.get(system, "navigation_system"), "navigation_agent",
            {"stream": "navigation_agents.jsonl", "kind": "authored_navigation_agent", "agent_index": index, "name": name},
        )
        for relation, field, role in (
            ("navigation_agent_uses_nav_data", "nav_data_class", "nav_data_class"),
            ("navigation_agent_prefers_nav_data", "preferred_nav_data", "preferred_nav_data"),
        ):
            target = _meaningful(row.get(field))
            if target:
                target_kind = "navigation_recast_config" if target == "/Script/NavigationSystem.RecastNavMesh" else "class"
                coverage = "first_class" if target_kind == "navigation_recast_config" else "partial"
                family = "navigation" if target_kind == "navigation_recast_config" else "class"
                register(target, target_kind, coverage=coverage, class_path=target, family=family)
                add(
                    agent, relation, target, "navigation_agent", target_kind,
                    {"stream": "navigation_agents.jsonl", "kind": f"authored_navigation_agent_{role}"},
                    target_coverage=coverage, target_family=family,
                )

    for row in rows(output / "navigation_areas.jsonl"):
        area = str(row.get("class_path", "") or "")
        parent = _meaningful(row.get("parent_class"))
        if parent in area_paths:
            add(
                area, "navigation_area_inherits_area", parent, "navigation_area", "navigation_area",
                {"stream": "navigation_areas.jsonl", "kind": "native_navigation_area_inheritance"},
            )
        supported = row.get("supported_agents", []) if isinstance(row.get("supported_agents"), list) else []
        for index in supported:
            target = configured.get((NAV_SYSTEM_CLASS, int(index)))
            if target:
                add(
                    area, "navigation_area_supports_agent", target, "navigation_area", "navigation_agent",
                    {"stream": "navigation_areas.jsonl", "kind": "authored_navigation_area_agent_mask", "agent_index": int(index)},
                )

    for row in rows(output / "navigation_area_agent_mappings.jsonl"):
        source = str(row.get("source_area", "") or "")
        target = str(row.get("target_area", "") or "")
        add(
            source, "navigation_area_maps_agent_to_area", target, "navigation_area", "navigation_area",
            {"stream": "navigation_area_agent_mappings.jsonl", "kind": "authored_navigation_meta_area_mapping", "agent_index": int(row.get("agent_index", 0) or 0)},
        )

    for row in rows(output / "navigation_link_defaults.jsonl"):
        link = str(row.get("link_id", "") or "")
        register(link, "navigation_link_default", class_path=str(row.get("class_path", "") or ""))
        for field, role in (
            ("area_class", "area"), ("enabled_area_class", "enabled"),
            ("disabled_area_class", "disabled"), ("obstacle_area_class", "obstacle"),
        ):
            target = _meaningful(row.get(field))
            if target:
                add(
                    link, "navigation_link_uses_area", target, "navigation_link_default", "navigation_area",
                    {"stream": "navigation_link_defaults.jsonl", "kind": "authored_navigation_link_area", "role": role},
                )
        supported = row.get("supported_agents", []) if isinstance(row.get("supported_agents"), list) else []
        for index in supported:
            target = configured.get((NAV_SYSTEM_CLASS, int(index)))
            if target:
                add(
                    link, "navigation_link_supports_agent", target, "navigation_link_default", "navigation_agent",
                    {"stream": "navigation_link_defaults.jsonl", "kind": "authored_navigation_link_agent_mask", "agent_index": int(index)},
                )

    for row in rows(output / "navigation_modifier_defaults.jsonl"):
        modifier = str(row.get("modifier_id", "") or "")
        register(modifier, "navigation_modifier_default", class_path=str(row.get("class_path", "") or ""))
        for relation, field, role in (
            ("navigation_modifier_uses_area", "area_class", "apply"),
            ("navigation_modifier_replaces_area", "area_class_to_replace", "replace"),
        ):
            target = _meaningful(row.get(field))
            if target:
                add(
                    modifier, relation, target, "navigation_modifier_default", "navigation_area",
                    {"stream": "navigation_modifier_defaults.jsonl", "kind": "authored_navigation_modifier_area", "role": role},
                )

    for row in rows(output / "navigation_invoker_defaults.jsonl"):
        invoker = str(row.get("invoker_id", "") or "")
        register(invoker, "navigation_invoker_default", class_path=str(row.get("class_path", "") or ""))
        supported = row.get("supported_agents", []) if isinstance(row.get("supported_agents"), list) else []
        for index in supported:
            target = configured.get((NAV_SYSTEM_CLASS, int(index)))
            if target:
                add(
                    invoker, "navigation_invoker_supports_agent", target, "navigation_invoker_default", "navigation_agent",
                    {"stream": "navigation_invoker_defaults.jsonl", "kind": "authored_navigation_invoker_agent_mask", "agent_index": int(index)},
                )

    for row in rows(output / "navigation_bounds_defaults.jsonl"):
        bounds = str(row.get("bounds_id", "") or "")
        register(bounds, "navigation_bounds_default", class_path=str(row.get("class_path", "") or ""))
        supported = row.get("supported_agents", []) if isinstance(row.get("supported_agents"), list) else []
        for index in supported:
            target = configured.get((NAV_SYSTEM_CLASS, int(index)))
            if target:
                add(
                    bounds, "navigation_bounds_supports_agent", target, "navigation_bounds_default", "navigation_agent",
                    {"stream": "navigation_bounds_defaults.jsonl", "kind": "authored_navigation_bounds_agent_mask", "agent_index": int(index)},
                )

    for row in rows(output / "navigation_recast_defaults.jsonl"):
        recast_id = str(row.get("recast_id", "") or "")
        class_path = str(row.get("class_path", "") or "")
        register(class_path, "navigation_recast_config", class_path=class_path, root=True)
        register(recast_id, "navigation_recast_defaults", class_path=class_path)
        for field, role in (("jump_down_area_class", "down"), ("jump_up_area_class", "up")):
            target = _meaningful(row.get(field))
            if target:
                add(
                    recast_id, "navigation_recast_uses_area", target, "navigation_recast_defaults", "navigation_area",
                    {"stream": "navigation_recast_defaults.jsonl", "kind": "authored_navigation_recast_jump_area", "role": role},
                )
    return nodes, edges


def _promote_public_derived_version(project_graph_module) -> None:
    project_graph_module.DERIVED_SCHEMA_VERSION = max(
        int(getattr(project_graph_module, "DERIVED_SCHEMA_VERSION", 0) or 0),
        TARGET_DERIVED_SCHEMA_VERSION,
    )
    target = Path(__file__).with_name("uatool.py").resolve()
    for module in tuple(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if not module_file or not hasattr(module, "FINAL_DERIVED_SCHEMA_VERSION"):
            continue
        try:
            if Path(module_file).resolve() != target:
                continue
        except (OSError, RuntimeError, TypeError):
            continue
        if int(getattr(module, "FINAL_DERIVED_SCHEMA_VERSION", 0) or 0) < TARGET_DERIVED_SCHEMA_VERSION:
            setattr(module, "FINAL_DERIVED_SCHEMA_VERSION", TARGET_DERIVED_SCHEMA_VERSION)


def install(project_graph_module) -> None:
    if getattr(project_graph_module, "_navigation_graph_installed", False):
        _promote_public_derived_version(project_graph_module)
        return
    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._navigation_graph_installed = True
    _promote_public_derived_version(project_graph_module)
