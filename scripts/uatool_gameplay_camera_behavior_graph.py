#!/usr/bin/env python3
"""Promote Gameplay Camera behavior/provider semantics into the project graph."""
from __future__ import annotations

import json
from pathlib import Path

import uatool_gameplay_camera_behavior as camera_behavior
import uatool_gameplay_camera_behavior_enums as camera_behavior_enums

# Install the readable enum decorator as soon as this graph layer is imported.
# uatool_build_perf already imports this module before derive composition, and
# the decorator mutates camera_behavior.derive in place so both persisted rows
# and graph evidence use the same schema-2 representation.
camera_behavior_enums.install(camera_behavior)


def _augment(output: Path, rows, nodes: list[dict], edges: list[dict], graph_module):
    providers, fields, inputs = camera_behavior.derive(Path(output), rows)

    node_by_key = {(str(n.get("node_kind", "")), str(n.get("path", ""))): n for n in nodes}
    path_nodes: dict[str, list[dict]] = {}
    for node in nodes:
        path_nodes.setdefault(str(node.get("path", "")), []).append(node)

    def existing(path: str):
        values = path_nodes.get(str(path or ""), [])
        if not values:
            return None
        return max(values, key=lambda n: (
            graph_module.COVERAGE_RANK.get(str(n.get("coverage", "")), -1),
            int(bool(n.get("root", False))),
            str(n.get("node_kind", "")),
        ))

    def register(path: str, kind: str, coverage: str, class_path: str = "", family: str = "gameplay_camera", root: bool = False):
        path = str(path or "")
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
            path_nodes.setdefault(path, []).append(node)
        else:
            if graph_module.COVERAGE_RANK.get(coverage, -1) > graph_module.COVERAGE_RANK.get(str(node.get("coverage", "")), -1):
                node["coverage"] = coverage
            if class_path and not node.get("class_path"):
                node["class_path"] = class_path
            if root:
                node["root"] = True
        return node

    edge_by_key = {
        (str(e.get("source_kind", "")), str(e.get("source", "")), str(e.get("relation", "")),
         str(e.get("target_kind", "")), str(e.get("target", ""))): e
        for e in edges
    }

    def add(source: str, relation: str, target: str, source_kind: str, target_kind: str, evidence: dict):
        source = str(source or "")
        target = str(target or "")
        if not source or not relation or not target or source == target:
            return
        source_node = node_by_key.get((source_kind, source)) or existing(source) or register(source, source_kind, "partial")
        target_node = node_by_key.get((target_kind, target)) or existing(target) or register(target, target_kind, "partial")
        if not source_node or not target_node:
            return
        source_kind = str(source_node.get("node_kind", source_kind))
        target_kind = str(target_node.get("node_kind", target_kind))
        key = (source_kind, source, relation, target_kind, target)
        token = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        edge = edge_by_key.get(key)
        if edge is None:
            edge = {
                "edge_id": graph_module._edge_id(source_kind, source, relation, target_kind, target),
                "source_kind": source_kind,
                "source": source,
                "relation": relation,
                "target_kind": target_kind,
                "target": target,
                "source_coverage": source_node.get("coverage", "partial"),
                "target_coverage": target_node.get("coverage", "partial"),
                "edge_quality": "exact_semantic",
                "evidence_count": 1,
                "evidence": [evidence],
            }
            edges.append(edge)
            edge_by_key[key] = edge
            return
        current = {
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for item in edge.get("evidence", []) if isinstance(item, dict)
        }
        if token not in current:
            edge.setdefault("evidence", []).append(evidence)
            edge["evidence"].sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            edge["evidence_count"] = len(edge["evidence"])

    provider_by_id = {str(row.get("provider_id", "") or ""): row for row in providers}
    field_by_id = {str(row.get("field_id", "") or ""): row for row in fields}

    for provider in providers:
        director = str(provider.get("director_blueprint_path", "") or "")
        provider_bp = str(provider.get("provider_blueprint_path", "") or "")
        virtual = camera_behavior.provider_path(provider)
        director_node = existing(director) or register(director, "blueprint", "first_class", family="blueprint", root=True)
        provider_bp_node = existing(provider_bp) or register(provider_bp, "blueprint", "first_class", family="blueprint", root=True)
        register(virtual, "gameplay_camera_property_provider", "first_class" if provider.get("fully_modeled") else "partial")
        evidence = {
            "stream": "gameplay_camera_property_providers.jsonl",
            "kind": "derived_camera_property_provider",
            "provider_id": str(provider.get("provider_id", "") or ""),
            "interface_blueprint_path": str(provider.get("interface_blueprint_path", "") or ""),
            "implementation_kind": str(provider.get("implementation_kind", "") or ""),
            "fully_modeled": bool(provider.get("fully_modeled", False)),
            "fully_decoded": bool(provider.get("fully_decoded", False)),
        }
        if director_node:
            add(director, "has_camera_property_provider_candidate", virtual, str(director_node.get("node_kind", "blueprint")), "gameplay_camera_property_provider", evidence)
        if provider_bp_node:
            add(provider_bp, "implements_camera_property_provider", virtual, str(provider_bp_node.get("node_kind", "blueprint")), "gameplay_camera_property_provider", evidence)

    for field in fields:
        provider = provider_by_id.get(str(field.get("provider_id", "") or ""), {})
        provider_virtual = camera_behavior.provider_path(provider)
        field_virtual = camera_behavior.provider_field_path(field)
        register(field_virtual, "gameplay_camera_property_field", "first_class")
        add(
            provider_virtual,
            "provides_camera_property",
            field_virtual,
            "gameplay_camera_property_provider",
            "gameplay_camera_property_field",
            {
                "stream": "gameplay_camera_property_fields.jsonl",
                "kind": "derived_camera_property_field",
                "field_id": str(field.get("field_id", "") or ""),
                "field_name": str(field.get("field_name", "") or ""),
                "expression_text": str(field.get("expression_text", "") or ""),
                "function_calls": field.get("function_calls", []),
                "enum_paths": field.get("enum_paths", []),
                "enum_literals_fully_decoded": bool(field.get("enum_literals_fully_decoded", False)),
            },
        )

    seen_director_chooser: set[tuple[str, str, str]] = set()
    for row in inputs:
        director = str(row.get("director_blueprint_path", "") or "")
        chooser = str(row.get("chooser_path", "") or "")
        input_virtual = camera_behavior.director_input_path(row)
        director_node = existing(director) or register(director, "blueprint", "first_class", family="blueprint", root=True)
        register(input_virtual, "gameplay_camera_director_input", "first_class")
        evidence = {
            "stream": "gameplay_camera_director_inputs.jsonl",
            "kind": "derived_camera_director_input",
            "input_id": str(row.get("input_id", "") or ""),
            "field_name": str(row.get("field_name", "") or ""),
            "source_kind": str(row.get("source_kind", "") or ""),
            "source_name": str(row.get("source_name", "") or ""),
            "passthrough_field": str(row.get("passthrough_field", "") or ""),
            "enum_paths": row.get("enum_paths", []),
            "enum_literals_fully_decoded": bool(row.get("enum_literals_fully_decoded", False)),
        }
        if director_node:
            add(director, "builds_camera_context_field", input_virtual, str(director_node.get("node_kind", "blueprint")), "gameplay_camera_director_input", evidence)
        if chooser:
            key = (director, str(row.get("evaluation_node_id", "") or ""), chooser)
            if key not in seen_director_chooser:
                seen_director_chooser.add(key)
                chooser_node = existing(chooser) or register(chooser, "chooser_table", "first_class", family="chooser", root=True)
                if director_node and chooser_node:
                    add(
                        director,
                        "evaluates_camera_chooser",
                        chooser,
                        str(director_node.get("node_kind", "blueprint")),
                        str(chooser_node.get("node_kind", "chooser_table")),
                        {
                            "stream": "gameplay_camera_director_inputs.jsonl",
                            "kind": "derived_camera_chooser_evaluation",
                            "evaluation_node_id": str(row.get("evaluation_node_id", "") or ""),
                        },
                    )
        for field_id in row.get("provider_field_candidate_ids", []) if isinstance(row.get("provider_field_candidate_ids", []), list) else []:
            field = field_by_id.get(str(field_id), {})
            if not field:
                continue
            field_virtual = camera_behavior.provider_field_path(field)
            add(
                input_virtual,
                "passes_through_camera_property_candidate",
                field_virtual,
                "gameplay_camera_director_input",
                "gameplay_camera_property_field",
                {
                    **evidence,
                    "provider_field_id": str(field_id),
                    "provider_blueprint_path": str(field.get("provider_blueprint_path", "") or ""),
                },
            )
        if row.get("source_kind") == "console_variable" and row.get("source_name"):
            cvar = str(row.get("source_name", "") or "")
            cvar_path = "console_variable:" + cvar
            register(cvar_path, "console_variable", "first_class", family="runtime_config")
            add(
                input_virtual,
                "reads_console_variable",
                cvar_path,
                "gameplay_camera_director_input",
                "console_variable",
                evidence,
            )

    nodes.sort(key=lambda n: (str(n.get("path", "")), str(n.get("node_kind", "")), str(n.get("node_id", ""))))
    edges.sort(key=lambda e: (str(e.get("source", "")), str(e.get("relation", "")), str(e.get("target", "")), str(e.get("edge_id", ""))))
    return nodes, edges


def install(project_graph_module) -> None:
    if getattr(project_graph_module, "_gameplay_camera_behavior_graph_installed", False):
        return
    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._gameplay_camera_behavior_graph_installed = True
