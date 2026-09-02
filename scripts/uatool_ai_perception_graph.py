#!/usr/bin/env python3
"""Promote systems-schema-8 AI Perception facts into the typed project graph."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TARGET_DERIVED_SCHEMA_VERSION = 24
RELATION_STREAMS = {
    "has_ai_perception_component": "ai_perception_components.jsonl",
    "has_ai_perception_sense_config": "ai_perception_sense_configs.jsonl",
    "uses_ai_perception_dominant_sense": "ai_perception_components.jsonl",
    "implements_ai_perception_sense": "ai_perception_sense_configs.jsonl",
    "has_ai_perception_stimuli_source": "ai_perception_stimuli_sources.jsonl",
    "registers_ai_perception_sense": "ai_perception_registered_senses.jsonl",
}


def _meaningful(value) -> str:
    text = str(value or "")
    return "" if text in {"None", "null", "NULL"} else text


def expected_edge_keys(output: Path, rows) -> set[tuple[str, str, str]]:
    output = Path(output)
    edges: set[tuple[str, str, str]] = set()

    def add(source, relation, target):
        source = _meaningful(source)
        target = _meaningful(target)
        if source and target and source != target:
            edges.add((source, relation, target))

    for row in rows(output / "ai_perception_components.jsonl"):
        add(row.get("blueprint_path", ""), "has_ai_perception_component", row.get("component_path", ""))
        add(row.get("component_path", ""), "uses_ai_perception_dominant_sense", row.get("dominant_sense_class", ""))
    for row in rows(output / "ai_perception_sense_configs.jsonl"):
        add(row.get("component_path", ""), "has_ai_perception_sense_config", row.get("config_path", ""))
        add(row.get("config_path", ""), "implements_ai_perception_sense", row.get("implementation_class", ""))
    for row in rows(output / "ai_perception_stimuli_sources.jsonl"):
        add(row.get("blueprint_path", ""), "has_ai_perception_stimuli_source", row.get("component_path", ""))
    for row in rows(output / "ai_perception_registered_senses.jsonl"):
        if not bool(row.get("is_null", False)):
            add(row.get("component_path", ""), "registers_ai_perception_sense", row.get("sense_class", ""))
    return edges


def _augment(output: Path, rows, nodes: list[dict], edges: list[dict], graph_module):
    node_by_key = {(str(n.get("node_kind", "")), str(n.get("path", ""))): n for n in nodes}

    def register(path: str, kind: str, coverage: str, class_path: str = "", *, root=False, family="ai_perception"):
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
                node["class_path"] = str(class_path)
            if root:
                node["root"] = True
        return node

    edge_by_key = {
        (str(e.get("source_kind", "")), str(e.get("source", "")), str(e.get("relation", "")),
         str(e.get("target_kind", "")), str(e.get("target", ""))): e
        for e in edges
    }

    def add(source, relation, target, source_kind, target_kind, evidence,
            *, source_coverage="first_class", target_coverage="first_class"):
        source = _meaningful(source)
        target = _meaningful(target)
        if not source or not target or source == target:
            return
        source_node = node_by_key.get((source_kind, source)) or register(source, source_kind, source_coverage)
        target_node = node_by_key.get((target_kind, target)) or register(target, target_kind, target_coverage)
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
            for item in edge.get("evidence", []) if isinstance(item, dict)
        }
        if token not in current:
            edge.setdefault("evidence", []).append(value)
            edge["evidence"].sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            edge["evidence_count"] = len(edge["evidence"])
        edge["edge_quality"] = "exact_semantic"

    for row in rows(output / "ai_perception_components.jsonl"):
        blueprint = str(row.get("blueprint_path", "") or "")
        component = str(row.get("component_path", "") or "")
        component_class = str(row.get("component_class", "") or "")
        register(blueprint, "blueprint", "first_class", root=True, family="blueprint")
        register(component, "ai_perception_component", "first_class", component_class)
        add(blueprint, "has_ai_perception_component", component,
            "blueprint", "ai_perception_component", {
                "stream": "ai_perception_components.jsonl",
                "kind": "canonical_ai_perception_component_template",
            })
        dominant = _meaningful(row.get("dominant_sense_class", ""))
        if dominant:
            register(dominant, "class", "partial", dominant, family="class")
            add(component, "uses_ai_perception_dominant_sense", dominant,
                "ai_perception_component", "class", {
                    "stream": "ai_perception_components.jsonl",
                    "kind": "canonical_ai_perception_dominant_sense",
                }, target_coverage="partial")

    for row in rows(output / "ai_perception_sense_configs.jsonl"):
        component = str(row.get("component_path", "") or "")
        config = str(row.get("config_path", "") or "")
        config_class = str(row.get("config_class", "") or "")
        implementation = _meaningful(row.get("implementation_class", ""))
        index = int(row.get("config_index", 0) or 0)
        register(config, "ai_perception_sense_config", "first_class", config_class)
        add(component, "has_ai_perception_sense_config", config,
            "ai_perception_component", "ai_perception_sense_config", {
                "stream": "ai_perception_sense_configs.jsonl",
                "kind": "canonical_ordered_ai_perception_sense_config",
                "config_index": index,
            })
        if implementation:
            register(implementation, "class", "partial", implementation, family="class")
            add(config, "implements_ai_perception_sense", implementation,
                "ai_perception_sense_config", "class", {
                    "stream": "ai_perception_sense_configs.jsonl",
                    "kind": "canonical_ai_perception_implementation_class",
                    "config_index": index,
                }, target_coverage="partial")

    for row in rows(output / "ai_perception_stimuli_sources.jsonl"):
        blueprint = str(row.get("blueprint_path", "") or "")
        source = str(row.get("component_path", "") or "")
        source_class = str(row.get("component_class", "") or "")
        register(blueprint, "blueprint", "first_class", root=True, family="blueprint")
        register(source, "ai_perception_stimuli_source", "first_class", source_class)
        add(blueprint, "has_ai_perception_stimuli_source", source,
            "blueprint", "ai_perception_stimuli_source", {
                "stream": "ai_perception_stimuli_sources.jsonl",
                "kind": "canonical_ai_perception_stimuli_source_template",
            })

    for row in rows(output / "ai_perception_registered_senses.jsonl"):
        if bool(row.get("is_null", False)):
            continue
        source = str(row.get("component_path", "") or "")
        sense = _meaningful(row.get("sense_class", ""))
        index = int(row.get("sense_index", 0) or 0)
        if sense:
            register(sense, "class", "partial", sense, family="class")
            add(source, "registers_ai_perception_sense", sense,
                "ai_perception_stimuli_source", "class", {
                    "stream": "ai_perception_registered_senses.jsonl",
                    "kind": "canonical_ordered_registered_ai_sense",
                    "sense_index": index,
                }, target_coverage="partial")

    nodes.sort(key=lambda n: (str(n.get("path", "")), str(n.get("node_kind", "")), str(n.get("node_id", ""))))
    edges.sort(key=lambda e: (str(e.get("source", "")), str(e.get("relation", "")), str(e.get("target", "")), str(e.get("edge_id", ""))))
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
        current = int(getattr(module, "FINAL_DERIVED_SCHEMA_VERSION", 0) or 0)
        if current < TARGET_DERIVED_SCHEMA_VERSION:
            setattr(module, "FINAL_DERIVED_SCHEMA_VERSION", TARGET_DERIVED_SCHEMA_VERSION)


def install(project_graph_module) -> None:
    if getattr(project_graph_module, "_ai_perception_graph_installed", False):
        _promote_public_derived_version(project_graph_module)
        return
    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._ai_perception_graph_installed = True
    _promote_public_derived_version(project_graph_module)
