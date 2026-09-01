#!/usr/bin/env python3
"""Promote schema-5 Mass and authored ZoneGraph facts into the typed project graph."""
from __future__ import annotations

import json
from pathlib import Path

ZONEGRAPH_BASE_GENERATOR_CLASS = "/Script/MassSpawner.MassEntityZoneGraphSpawnPointsGenerator"


def _point_path(shape_path: str, point_index: int) -> str:
    return f"{shape_path}#zonegraph_point:{point_index}"


def _augment(output: Path, rows, nodes: list[dict], edges: list[dict], graph_module):
    node_by_key = {(str(n.get("node_kind", "")), str(n.get("path", ""))): n for n in nodes}
    path_nodes: dict[str, list[dict]] = {}
    for node in nodes:
        path_nodes.setdefault(str(node.get("path", "")), []).append(node)

    def existing(path: str):
        values = path_nodes.get(str(path or ""), [])
        if not values:
            return None
        return max(
            values,
            key=lambda n: (
                graph_module.COVERAGE_RANK.get(str(n.get("coverage", "")), -1),
                int(bool(n.get("root", False))),
                str(n.get("family", "")) != "asset_registry",
                str(n.get("node_kind", "")),
            ),
        )

    def register(
        path: str,
        kind: str,
        coverage: str,
        class_path: str = "",
        family: str = "mass_zonegraph",
        root: bool = False,
    ):
        path = str(path or "")
        if not path:
            return None
        key = (str(kind), path)
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
            path_nodes.setdefault(path, []).append(node)
        else:
            if graph_module.COVERAGE_RANK.get(coverage, -1) > graph_module.COVERAGE_RANK.get(
                str(node.get("coverage", "")), -1
            ):
                node["coverage"] = coverage
            if class_path and not node.get("class_path"):
                node["class_path"] = class_path
            if root:
                node["root"] = True
        return node

    edge_by_key = {
        (
            str(e.get("source_kind", "")),
            str(e.get("source", "")),
            str(e.get("relation", "")),
            str(e.get("target_kind", "")),
            str(e.get("target", "")),
        ): e
        for e in edges
    }

    def add(
        source: str,
        relation: str,
        target: str,
        source_kind: str,
        target_kind: str,
        evidence: dict,
        *,
        source_coverage: str = "first_class",
        target_coverage: str = "first_class",
    ) -> None:
        source = str(source or "")
        target = str(target or "")
        if not source or not target or source == target:
            return
        source_node = node_by_key.get((source_kind, source)) or register(
            source, source_kind, source_coverage
        )
        target_node = node_by_key.get((target_kind, target)) or register(
            target, target_kind, target_coverage
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
                "source_coverage": source_node.get("coverage", source_coverage),
                "target_coverage": target_node.get("coverage", target_coverage),
                "edge_quality": "exact_semantic",
                "evidence_count": 1,
                "evidence": [value],
            }
            edges.append(edge)
            edge_by_key[key] = edge
            return
        current = {
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for item in edge.get("evidence", [])
            if isinstance(item, dict)
        }
        if token not in current:
            edge.setdefault("evidence", []).append(value)
            edge["evidence"].sort(
                key=lambda item: json.dumps(
                    item, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            )
            edge["evidence_count"] = len(edge["evidence"])

    configs = list(rows(output / "mass_entity_configs.jsonl"))
    config_paths = {str(row.get("config_path", "")) for row in configs if row.get("config_path")}
    for row in configs:
        config = str(row.get("config_path", ""))
        register(
            config,
            "mass_entity_config",
            "first_class",
            row.get("class_path", ""),
            root=True,
        )
        parent = str(row.get("parent_config_path", "") or "")
        if parent:
            register(
                parent,
                "mass_entity_config",
                "first_class" if parent in config_paths else "partial",
                row.get("parent_config_class", ""),
            )
            add(
                config,
                "inherits_mass_entity_config",
                parent,
                "mass_entity_config",
                "mass_entity_config",
                {
                    "stream": "mass_entity_configs.jsonl",
                    "kind": "canonical_mass_config_parent",
                    "config_guid": row.get("config_guid", ""),
                },
                target_coverage="first_class" if parent in config_paths else "partial",
            )

    for row in rows(output / "mass_entity_traits.jsonl"):
        config = str(row.get("config_path", ""))
        trait = str(row.get("trait_path", "") or "")
        if not trait:
            continue
        register(config, "mass_entity_config", "first_class", root=True)
        register(trait, "mass_entity_trait", "first_class", row.get("trait_class", ""))
        add(
            config,
            "has_mass_entity_trait",
            trait,
            "mass_entity_config",
            "mass_entity_trait",
            {
                "stream": "mass_entity_traits.jsonl",
                "kind": "canonical_ordered_mass_trait",
                "trait_index": int(row.get("trait_index", 0) or 0),
                "trait_class": row.get("trait_class", ""),
            },
        )

    spawner_kinds: dict[str, str] = {}
    for row in rows(output / "mass_spawners.jsonl"):
        spawner = str(row.get("spawner_path", ""))
        node = existing(spawner) or register(
            spawner, "blueprint", "first_class", row.get("generated_class", ""), family="blueprint", root=True
        )
        if node:
            spawner_kinds[spawner] = str(node.get("node_kind", "blueprint"))

    for row in rows(output / "mass_spawner_entity_types.jsonl"):
        spawner = str(row.get("spawner_path", ""))
        config = str(row.get("entity_config_path", "") or "")
        if not config:
            continue
        source_kind = spawner_kinds.get(spawner) or str((existing(spawner) or {}).get("node_kind", "blueprint"))
        register(config, "mass_entity_config", "first_class" if config in config_paths else "partial", row.get("entity_config_class", ""))
        add(
            spawner,
            "spawns_mass_entity_config",
            config,
            source_kind,
            "mass_entity_config",
            {
                "stream": "mass_spawner_entity_types.jsonl",
                "kind": "canonical_mass_spawner_entity_type",
                "entity_type_index": int(row.get("entity_type_index", 0) or 0),
                "proportion": row.get("proportion", ""),
            },
            target_coverage="first_class" if config in config_paths else "partial",
        )

    generator_assets: dict[str, dict] = {}
    for row in rows(output / "mass_spawn_generator_assets.jsonl"):
        asset = str(row.get("generator_asset_path", ""))
        generator_assets[asset] = row
        node = existing(asset) or register(
            asset,
            "blueprint",
            "first_class",
            row.get("generated_class", ""),
            family="blueprint",
            root=True,
        )
        source_kind = str(node.get("node_kind", "blueprint")) if node else "blueprint"
        parent = str(row.get("parent_class", "") or "")
        if parent:
            register(parent, "class", "partial", parent, family="class")
            add(
                asset,
                "inherits_mass_spawn_generator_class",
                parent,
                source_kind,
                "class",
                {
                    "stream": "mass_spawn_generator_assets.jsonl",
                    "kind": "canonical_generated_class_parent",
                },
                target_coverage="partial",
            )
        if bool(row.get("zonegraph_generator", False)):
            register(
                ZONEGRAPH_BASE_GENERATOR_CLASS,
                "class",
                "partial",
                ZONEGRAPH_BASE_GENERATOR_CLASS,
                family="class",
            )
            add(
                asset,
                "inherits_zonegraph_spawn_generator_base",
                ZONEGRAPH_BASE_GENERATOR_CLASS,
                source_kind,
                "class",
                {
                    "stream": "mass_spawn_generator_assets.jsonl",
                    "kind": "canonical_inheritance_check",
                    "zonegraph_generator": True,
                },
                target_coverage="partial",
            )

    for row in rows(output / "mass_spawner_generators.jsonl"):
        spawner = str(row.get("spawner_path", ""))
        source_kind = spawner_kinds.get(spawner) or str((existing(spawner) or {}).get("node_kind", "blueprint"))
        asset = str(row.get("generator_asset_path", "") or "")
        instance = str(row.get("generator_path", "") or "")
        if asset:
            target_node = existing(asset) or register(asset, "blueprint", "first_class", family="blueprint", root=True)
            target_kind = str(target_node.get("node_kind", "blueprint")) if target_node else "blueprint"
            add(
                spawner,
                "uses_mass_spawn_generator_asset",
                asset,
                source_kind,
                target_kind,
                {
                    "stream": "mass_spawner_generators.jsonl",
                    "kind": "canonical_mass_spawner_generator",
                    "generator_index": int(row.get("generator_index", 0) or 0),
                    "proportion": row.get("proportion", ""),
                },
            )
        elif instance:
            register(instance, "mass_spawn_generator_instance", "first_class", row.get("generator_class", ""))
            add(
                spawner,
                "uses_mass_spawn_generator_instance",
                instance,
                source_kind,
                "mass_spawn_generator_instance",
                {
                    "stream": "mass_spawner_generators.jsonl",
                    "kind": "canonical_mass_spawner_generator",
                    "generator_index": int(row.get("generator_index", 0) or 0),
                    "proportion": row.get("proportion", ""),
                },
            )

    for row in rows(output / "mass_agent_components.jsonl"):
        blueprint = str(row.get("blueprint_path", ""))
        component = str(row.get("component_path", ""))
        bp_node = existing(blueprint) or register(blueprint, "blueprint", "first_class", family="blueprint", root=True)
        bp_kind = str(bp_node.get("node_kind", "blueprint")) if bp_node else "blueprint"
        register(component, "mass_agent_component", "first_class", row.get("component_class", ""))
        add(
            blueprint,
            "owns_mass_agent_component",
            component,
            bp_kind,
            "mass_agent_component",
            {
                "stream": "mass_agent_components.jsonl",
                "kind": "canonical_mass_agent_component",
                "component_name": row.get("component_name", ""),
            },
        )
        config = str(row.get("entity_config_parent_path", "") or "")
        if config:
            register(config, "mass_entity_config", "first_class" if config in config_paths else "partial", row.get("entity_config_parent_class", ""))
            add(
                component,
                "uses_mass_entity_config",
                config,
                "mass_agent_component",
                "mass_entity_config",
                {
                    "stream": "mass_agent_components.jsonl",
                    "kind": "canonical_embedded_mass_config_parent",
                    "config_guid": row.get("config_guid", ""),
                },
                target_coverage="first_class" if config in config_paths else "partial",
            )

    shape_paths: set[str] = set()
    for row in rows(output / "zonegraph_shapes.jsonl"):
        shape = str(row.get("shape_path", ""))
        shape_paths.add(shape)
        world = str(row.get("world_path", "") or "")
        component = str(row.get("component_path", "") or "")
        register(shape, "zonegraph_shape", "first_class", row.get("class_path", ""), family="zonegraph")
        if world:
            register(world, "world", "first_class", "/Script/Engine.World", family="world", root=True)
            add(
                world,
                "contains_zonegraph_shape",
                shape,
                "world",
                "zonegraph_shape",
                {
                    "stream": "zonegraph_shapes.jsonl",
                    "kind": "canonical_loaded_world_zone_shape",
                    "provenance": row.get("provenance", ""),
                },
            )
        if component:
            register(
                component,
                "zonegraph_shape_component",
                "first_class",
                row.get("component_class", ""),
                family="zonegraph",
            )
            add(
                shape,
                "owns_zonegraph_shape_component",
                component,
                "zonegraph_shape",
                "zonegraph_shape_component",
                {
                    "stream": "zonegraph_shapes.jsonl",
                    "kind": "canonical_zone_shape_component",
                },
            )

    for row in rows(output / "zonegraph_shape_points.jsonl"):
        shape = str(row.get("shape_path", ""))
        index = int(row.get("point_index", 0) or 0)
        point = _point_path(shape, index)
        register(shape, "zonegraph_shape", "first_class" if shape in shape_paths else "partial", family="zonegraph")
        register(point, "zonegraph_shape_point", "first_class", "/Script/ZoneGraph.ZoneShapePoint", family="zonegraph")
        add(
            shape,
            "has_zonegraph_shape_point",
            point,
            "zonegraph_shape",
            "zonegraph_shape_point",
            {
                "stream": "zonegraph_shape_points.jsonl",
                "kind": "canonical_ordered_zone_shape_point",
                "point_index": index,
                "point_type": row.get("point_type", ""),
                "lane_profile": row.get("lane_profile", ""),
                "reverse_lane_profile": row.get("reverse_lane_profile", ""),
            },
            source_coverage="first_class" if shape in shape_paths else "partial",
        )

    nodes.sort(key=lambda n: (str(n.get("path", "")), str(n.get("node_kind", "")), str(n.get("node_id", ""))))
    edges.sort(key=lambda e: (str(e.get("source", "")), str(e.get("relation", "")), str(e.get("target", "")), str(e.get("edge_id", ""))))
    return nodes, edges


def install(project_graph_module) -> None:
    if getattr(project_graph_module, "_mass_zonegraph_graph_installed", False):
        return

    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._mass_zonegraph_graph_installed = True

    # MassEntityConfigAssets are first-class specialist roots even though the
    # generic systems_assets stream does not own their normalization. Extend the
    # final root authority so finalize() does not demote them to non-root nodes.
    import uatool_project_graph_finalize as finalize_module

    if not getattr(finalize_module, "_mass_zonegraph_roots_installed", False):
        original_roots = finalize_module._canonical_roots

        def canonical_roots(output, rows):
            roots = original_roots(output, rows)
            for row in rows(output / "mass_entity_configs.jsonl"):
                path = str(row.get("config_path", "") or "")
                if path:
                    roots.setdefault(path, "mass_entity_config")
            return roots

        finalize_module._canonical_roots = canonical_roots
        finalize_module._mass_zonegraph_roots_installed = True
