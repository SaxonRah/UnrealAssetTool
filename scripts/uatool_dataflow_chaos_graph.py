#!/usr/bin/env python3
"""Promote systems-schema-9 Dataflow / Geometry Collection facts into the typed project graph."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TARGET_DERIVED_SCHEMA_VERSION = 25
RELATION_STREAMS = {
    "has_dataflow_node": "dataflow_nodes.jsonl",
    "instance_of_dataflow_node_struct": "dataflow_nodes.jsonl",
    "has_dataflow_input": "dataflow_pins.jsonl",
    "has_dataflow_output": "dataflow_pins.jsonl",
    "dataflow_connects": "dataflow_edges.jsonl",
    "dataflow_node_references_object": "dataflow_node_references.jsonl",
    "geometry_collection_uses_dataflow_asset": "geometry_collections.jsonl",
    "geometry_collection_uses_physics_material": "geometry_collection_references.jsonl",
}


def _meaningful(value) -> str:
    text = str(value or "")
    return "" if text in {"None", "null", "NULL"} else text


def node_path(asset_path: str, node_guid: str) -> str:
    return f"{asset_path}#DataflowNode:{node_guid}"


def pin_path(asset_path: str, pin_guid: str) -> str:
    return f"{asset_path}#DataflowPin:{pin_guid}"


def expected_edge_keys(output: Path, rows) -> set[tuple[str, str, str]]:
    output = Path(output)
    edges: set[tuple[str, str, str]] = set()

    def add(source, relation, target):
        source = _meaningful(source)
        target = _meaningful(target)
        if source and target and source != target:
            edges.add((source, relation, target))

    for row in rows(output / "dataflow_nodes.jsonl"):
        asset = str(row.get("asset_path", "") or "")
        node = node_path(asset, str(row.get("node_guid", "") or ""))
        add(asset, "has_dataflow_node", node)
        add(node, "instance_of_dataflow_node_struct", row.get("node_struct", ""))
    for row in rows(output / "dataflow_pins.jsonl"):
        asset = str(row.get("asset_path", "") or "")
        node = node_path(asset, str(row.get("node_guid", "") or ""))
        pin = pin_path(asset, str(row.get("pin_guid", "") or ""))
        relation = "has_dataflow_input" if row.get("direction") == "input" else "has_dataflow_output"
        add(node, relation, pin)
    for row in rows(output / "dataflow_edges.jsonl"):
        asset = str(row.get("asset_path", "") or "")
        add(pin_path(asset, str(row.get("source_pin_guid", "") or "")),
            "dataflow_connects",
            pin_path(asset, str(row.get("target_pin_guid", "") or "")))
    for row in rows(output / "dataflow_node_references.jsonl"):
        asset = str(row.get("source_path", "") or "")
        add(node_path(asset, str(row.get("owner_id", "") or "")),
            "dataflow_node_references_object",
            row.get("target_path", ""))
    for row in rows(output / "geometry_collections.jsonl"):
        add(row.get("asset_path", ""), "geometry_collection_uses_dataflow_asset", row.get("dataflow_asset", ""))
    for row in rows(output / "geometry_collection_references.jsonl"):
        if str(row.get("root_property", "") or "") == "PhysicsMaterial":
            add(row.get("source_path", ""), "geometry_collection_uses_physics_material", row.get("target_path", ""))
    return edges


def _augment(output: Path, rows, nodes: list[dict], edges: list[dict], graph_module):
    node_by_key = {(str(n.get("node_kind", "")), str(n.get("path", ""))): n for n in nodes}

    def register(path: str, kind: str, coverage: str, class_path: str = "", *, root=False, family="dataflow"):
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
            *, source_coverage="first_class", target_coverage="first_class",
            source_family="dataflow", target_family="dataflow"):
        source = _meaningful(source)
        target = _meaningful(target)
        if not source or not target or source == target:
            return
        source_node = node_by_key.get((source_kind, source)) or register(
            source, source_kind, source_coverage, family=source_family)
        target_node = node_by_key.get((target_kind, target)) or register(
            target, target_kind, target_coverage, family=target_family)
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

    dataflow_assets = {str(row.get("asset_path", "") or "") for row in rows(output / "dataflow_graphs.jsonl")}
    for asset in dataflow_assets:
        register(asset, "dataflow", "first_class", "/Script/DataflowEngine.Dataflow", root=True, family="dataflow")

    for row in rows(output / "dataflow_nodes.jsonl"):
        asset = str(row.get("asset_path", "") or "")
        guid = str(row.get("node_guid", "") or "")
        node = node_path(asset, guid)
        struct = _meaningful(row.get("node_struct", ""))
        register(node, "dataflow_node", "first_class", struct, family="dataflow")
        add(asset, "has_dataflow_node", node, "dataflow", "dataflow_node", {
            "stream": "dataflow_nodes.jsonl", "kind": "canonical_dataflow_node", "node_guid": guid,
        })
        if struct:
            register(struct, "struct", "partial", struct, family="struct")
            add(node, "instance_of_dataflow_node_struct", struct, "dataflow_node", "struct", {
                "stream": "dataflow_nodes.jsonl", "kind": "canonical_dataflow_node_struct", "node_guid": guid,
            }, target_coverage="partial", target_family="struct")

    for row in rows(output / "dataflow_pins.jsonl"):
        asset = str(row.get("asset_path", "") or "")
        node = node_path(asset, str(row.get("node_guid", "") or ""))
        pin_guid = str(row.get("pin_guid", "") or "")
        pin = pin_path(asset, pin_guid)
        direction = str(row.get("direction", "") or "")
        relation = "has_dataflow_input" if direction == "input" else "has_dataflow_output"
        register(pin, "dataflow_pin", "first_class", family="dataflow")
        add(node, relation, pin, "dataflow_node", "dataflow_pin", {
            "stream": "dataflow_pins.jsonl",
            "kind": "canonical_dataflow_pin",
            "pin_guid": pin_guid,
            "pin_index": int(row.get("pin_index", 0) or 0),
            "pin_name": str(row.get("pin_name", "") or ""),
            "direction": direction,
            "original_type": str(row.get("original_type", "") or ""),
        })

    for row in rows(output / "dataflow_edges.jsonl"):
        asset = str(row.get("asset_path", "") or "")
        source = pin_path(asset, str(row.get("source_pin_guid", "") or ""))
        target = pin_path(asset, str(row.get("target_pin_guid", "") or ""))
        add(source, "dataflow_connects", target, "dataflow_pin", "dataflow_pin", {
            "stream": "dataflow_edges.jsonl",
            "kind": "canonical_dataflow_link",
            "source_node_guid": str(row.get("source_node_guid", "") or ""),
            "target_node_guid": str(row.get("target_node_guid", "") or ""),
        })

    for row in rows(output / "dataflow_node_references.jsonl"):
        asset = str(row.get("source_path", "") or "")
        node = node_path(asset, str(row.get("owner_id", "") or ""))
        target = _meaningful(row.get("target_path", ""))
        if not target:
            continue
        register(target, "object_reference_target", "partial", str(row.get("target_class", "") or ""), family="reference")
        add(node, "dataflow_node_references_object", target,
            "dataflow_node", "object_reference_target", {
                "stream": "dataflow_node_references.jsonl",
                "kind": "canonical_dataflow_node_object_reference",
                "property_path": str(row.get("property_path", "") or ""),
                "reference_kind": str(row.get("reference_kind", "") or ""),
            }, target_coverage="partial", target_family="reference")

    for row in rows(output / "geometry_collections.jsonl"):
        collection = str(row.get("asset_path", "") or "")
        dataflow = _meaningful(row.get("dataflow_asset", ""))
        register(collection, "geometry_collection", "first_class", "/Script/GeometryCollectionEngine.GeometryCollection", root=True, family="geometry_collection")
        if dataflow:
            target_coverage = "first_class" if dataflow in dataflow_assets else "partial"
            register(dataflow, "dataflow", target_coverage, "/Script/DataflowEngine.Dataflow", root=dataflow in dataflow_assets, family="dataflow")
            add(collection, "geometry_collection_uses_dataflow_asset", dataflow,
                "geometry_collection", "dataflow", {
                    "stream": "geometry_collections.jsonl",
                    "kind": "canonical_non_null_geometry_collection_dataflow_asset",
                }, target_coverage=target_coverage)

    for row in rows(output / "geometry_collection_references.jsonl"):
        if str(row.get("root_property", "") or "") != "PhysicsMaterial":
            continue
        collection = str(row.get("source_path", "") or "")
        target = _meaningful(row.get("target_path", ""))
        if not target:
            continue
        register(target, "physics_material", "partial", str(row.get("target_class", "") or ""), family="physics")
        add(collection, "geometry_collection_uses_physics_material", target,
            "geometry_collection", "physics_material", {
                "stream": "geometry_collection_references.jsonl",
                "kind": "canonical_geometry_collection_physics_material",
                "property_path": str(row.get("property_path", "") or ""),
            }, target_coverage="partial", target_family="physics")

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
    if getattr(project_graph_module, "_dataflow_chaos_graph_installed", False):
        _promote_public_derived_version(project_graph_module)
        return
    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._dataflow_chaos_graph_installed = True
    _promote_public_derived_version(project_graph_module)
