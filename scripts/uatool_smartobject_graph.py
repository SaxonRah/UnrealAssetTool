#!/usr/bin/env python3
"""Promote systems-schema-7 Smart Object facts into the typed project graph."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TARGET_DERIVED_SCHEMA_VERSION = 23
RELATION_STREAMS = {
    "has_smart_object_slot": "smartobject_slots.jsonl",
    "has_default_smart_object_behavior": "smartobject_behaviors.jsonl",
    "has_smart_object_behavior": "smartobject_behaviors.jsonl",
    "instance_of_smart_object_behavior_class": "smartobject_behaviors.jsonl",
    "uses_smart_object_world_condition_schema": "smartobject_definitions.jsonl",
    "uses_smart_object_selection_schema": "smartobject_slots.jsonl",
}


def slot_path(definition: str, slot_id: str) -> str:
    definition = str(definition or "")
    slot_id = str(slot_id or "")
    return f"{definition}#smartobject_slot:{slot_id}" if definition and slot_id else ""


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

    for row in rows(output / "smartobject_definitions.jsonl"):
        definition = str(row.get("definition_path", "") or "")
        add(definition, "uses_smart_object_world_condition_schema", row.get("world_condition_schema_class", ""))

    for row in rows(output / "smartobject_slots.jsonl"):
        definition = str(row.get("definition_path", "") or "")
        slot = slot_path(definition, row.get("slot_id", ""))
        add(definition, "has_smart_object_slot", slot)
        add(slot, "uses_smart_object_selection_schema", row.get("selection_schema_class", ""))

    slots = {
        (str(row.get("definition_path", "") or ""), int(row.get("slot_index", -1))):
        slot_path(row.get("definition_path", ""), row.get("slot_id", ""))
        for row in rows(output / "smartobject_slots.jsonl")
    }
    for row in rows(output / "smartobject_behaviors.jsonl"):
        definition = str(row.get("definition_path", "") or "")
        behavior = str(row.get("behavior_path", "") or "")
        scope = str(row.get("scope", "") or "")
        if scope == "default":
            add(definition, "has_default_smart_object_behavior", behavior)
        elif scope == "slot":
            add(slots.get((definition, int(row.get("slot_index", -1))), ""), "has_smart_object_behavior", behavior)
        add(behavior, "instance_of_smart_object_behavior_class", row.get("behavior_class", ""))
    return edges


def _augment(output: Path, rows, nodes: list[dict], edges: list[dict], graph_module):
    node_by_key = {(str(n.get("node_kind", "")), str(n.get("path", ""))): n for n in nodes}
    path_nodes: dict[str, list[dict]] = {}
    for node in nodes:
        path_nodes.setdefault(str(node.get("path", "")), []).append(node)

    def register(path: str, kind: str, coverage: str, class_path: str = "", *, root=False, family="smart_objects"):
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
            path_nodes.setdefault(path, []).append(node)
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

    definitions = list(rows(output / "smartobject_definitions.jsonl"))
    slots_rows = list(rows(output / "smartobject_slots.jsonl"))
    behaviors = list(rows(output / "smartobject_behaviors.jsonl"))

    for row in definitions:
        definition = str(row.get("definition_path", "") or "")
        register(definition, "smart_object_definition", "first_class", row.get("class_path", ""), root=True)
        schema = _meaningful(row.get("world_condition_schema_class", ""))
        if schema:
            register(schema, "class", "partial", schema, family="class")
            add(definition, "uses_smart_object_world_condition_schema", schema,
                "smart_object_definition", "class", {
                    "stream": "smartobject_definitions.jsonl",
                    "kind": "canonical_definition_world_condition_schema",
                }, target_coverage="partial")

    slot_by_index: dict[tuple[str, int], str] = {}
    for row in slots_rows:
        definition = str(row.get("definition_path", "") or "")
        index = int(row.get("slot_index", 0) or 0)
        slot_id = str(row.get("slot_id", "") or "")
        slot = slot_path(definition, slot_id)
        slot_by_index[(definition, index)] = slot
        register(slot, "smart_object_slot", "first_class")
        add(definition, "has_smart_object_slot", slot,
            "smart_object_definition", "smart_object_slot", {
                "stream": "smartobject_slots.jsonl",
                "kind": "canonical_ordered_smart_object_slot",
                "slot_index": index,
                "slot_id": slot_id,
            })
        schema = _meaningful(row.get("selection_schema_class", ""))
        if schema:
            register(schema, "class", "partial", schema, family="class")
            add(slot, "uses_smart_object_selection_schema", schema,
                "smart_object_slot", "class", {
                    "stream": "smartobject_slots.jsonl",
                    "kind": "canonical_slot_selection_schema",
                    "slot_index": index,
                    "slot_id": slot_id,
                }, target_coverage="partial")

    for row in behaviors:
        definition = str(row.get("definition_path", "") or "")
        scope = str(row.get("scope", "") or "")
        slot_index = int(row.get("slot_index", -1))
        behavior_index = int(row.get("behavior_index", 0) or 0)
        behavior = str(row.get("behavior_path", "") or "")
        behavior_class = str(row.get("behavior_class", "") or "")
        register(behavior, "smart_object_behavior", "first_class", behavior_class)
        if scope == "default":
            add(definition, "has_default_smart_object_behavior", behavior,
                "smart_object_definition", "smart_object_behavior", {
                    "stream": "smartobject_behaviors.jsonl",
                    "kind": "canonical_default_behavior",
                    "behavior_index": behavior_index,
                })
        elif scope == "slot":
            slot = slot_by_index.get((definition, slot_index), "")
            add(slot, "has_smart_object_behavior", behavior,
                "smart_object_slot", "smart_object_behavior", {
                    "stream": "smartobject_behaviors.jsonl",
                    "kind": "canonical_slot_behavior",
                    "slot_index": slot_index,
                    "behavior_index": behavior_index,
                })
        if behavior_class:
            register(behavior_class, "class", "partial", behavior_class, family="class")
            add(behavior, "instance_of_smart_object_behavior_class", behavior_class,
                "smart_object_behavior", "class", {
                    "stream": "smartobject_behaviors.jsonl",
                    "kind": "canonical_behavior_class",
                    "scope": scope,
                    "slot_index": slot_index,
                    "behavior_index": behavior_index,
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
    if getattr(project_graph_module, "_smartobject_graph_installed", False):
        _promote_public_derived_version(project_graph_module)
        return
    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._smartobject_graph_installed = True
    _promote_public_derived_version(project_graph_module)

    import uatool_project_graph_finalize as finalize_module
    if not getattr(finalize_module, "_smartobject_roots_installed", False):
        original_roots = finalize_module._canonical_roots

        def canonical_roots(output, rows):
            roots = original_roots(output, rows)
            for row in rows(Path(output) / "smartobject_definitions.jsonl"):
                path = str(row.get("definition_path", "") or "")
                if path:
                    roots[path] = "smart_object_definition"
            return roots

        finalize_module._canonical_roots = canonical_roots
        finalize_module._smartobject_roots_installed = True
