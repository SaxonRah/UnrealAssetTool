#!/usr/bin/env python3
"""Promote systems-schema-10 UAF authored facts into the typed project graph."""
from __future__ import annotations

import json
import sys
from pathlib import Path

TARGET_DERIVED_SCHEMA_VERSION = 26
RELATION_STREAMS = {
    "has_uaf_entry": "uaf_entries.jsonl",
    "uaf_entry_uses_rigvm_graph": "uaf_entries.jsonl",
    "has_uaf_variable": "uaf_variables.jsonl",
    "uaf_variable_uses_type": "uaf_variables.jsonl",
    "has_uaf_component": "uaf_components.jsonl",
    "instance_of_uaf_component_struct": "uaf_components.jsonl",
    "has_uaf_entry_point": "uaf_entry_points.jsonl",
    "has_uaf_rigvm_graph": "uaf_rigvm_graphs.jsonl",
    "has_rigvm_node": "uaf_rigvm_nodes.jsonl",
    "instance_of_rigvm_node_class": "uaf_rigvm_nodes.jsonl",
    "instance_of_rigvm_unit_struct": "uaf_rigvm_nodes.jsonl",
    "has_rigvm_pin": "uaf_rigvm_pins.jsonl",
    "rigvm_connects": "uaf_rigvm_links.jsonl",
    "uaf_rigvm_node_uses_variable": "uaf_variable_usages.jsonl",
}


def _meaningful(value) -> str:
    text = str(value or "")
    return "" if text in {"None", "null", "NULL"} else text


def component_path(asset: str, index: int) -> str:
    return f"{asset}#UAFComponent:{index}"


def entry_point_path(asset: str, index: int, name: str) -> str:
    return f"{asset}#UAFEntryPoint:{index}:{name}"


def rigvm_node_path(asset: str, graph: str, node: str) -> str:
    return f"{asset}#RigVMNode:{graph}:{node}"


def rigvm_pin_path(asset: str, graph: str, pin: str) -> str:
    return f"{asset}#RigVMPin:{graph}:{pin}"


def expected_edge_keys(output: Path, rows) -> set[tuple[str, str, str]]:
    output = Path(output)
    edges: set[tuple[str, str, str]] = set()

    def add(source, relation, target):
        source = _meaningful(source); target = _meaningful(target)
        if source and target and source != target:
            edges.add((source, relation, target))

    for row in rows(output / "uaf_entries.jsonl"):
        add(row.get("asset_path"), "has_uaf_entry", row.get("entry_path"))
        add(row.get("entry_path"), "uaf_entry_uses_rigvm_graph", row.get("graph_path"))
    for row in rows(output / "uaf_variables.jsonl"):
        add(row.get("asset_path"), "has_uaf_variable", row.get("variable_path"))
        add(row.get("variable_path"), "uaf_variable_uses_type", row.get("type_object"))
    for row in rows(output / "uaf_components.jsonl"):
        asset = str(row.get("asset_path", "") or "")
        comp = component_path(asset, int(row.get("component_index", 0) or 0))
        add(asset, "has_uaf_component", comp)
        add(comp, "instance_of_uaf_component_struct", row.get("component_struct"))
    for row in rows(output / "uaf_entry_points.jsonl"):
        asset = str(row.get("asset_path", "") or "")
        ep = entry_point_path(asset, int(row.get("entry_point_index", 0) or 0), str(row.get("entry_point_name", "") or ""))
        add(asset, "has_uaf_entry_point", ep)
    for row in rows(output / "uaf_rigvm_graphs.jsonl"):
        add(row.get("asset_path"), "has_uaf_rigvm_graph", row.get("graph_path"))
    for row in rows(output / "uaf_rigvm_nodes.jsonl"):
        asset = str(row.get("asset_path", "") or ""); graph = str(row.get("graph_path", "") or "")
        node = rigvm_node_path(asset, graph, str(row.get("node_path", "") or ""))
        add(graph, "has_rigvm_node", node)
        add(node, "instance_of_rigvm_node_class", row.get("node_class"))
        add(node, "instance_of_rigvm_unit_struct", row.get("unit_script_struct"))
    for row in rows(output / "uaf_rigvm_pins.jsonl"):
        asset = str(row.get("asset_path", "") or ""); graph = str(row.get("graph_path", "") or "")
        node = rigvm_node_path(asset, graph, str(row.get("node_path", "") or ""))
        pin = rigvm_pin_path(asset, graph, str(row.get("pin_path", "") or ""))
        add(node, "has_rigvm_pin", pin)
    for row in rows(output / "uaf_rigvm_links.jsonl"):
        asset = str(row.get("asset_path", "") or ""); graph = str(row.get("graph_path", "") or "")
        add(rigvm_pin_path(asset, graph, str(row.get("source_pin_path", "") or "")), "rigvm_connects",
            rigvm_pin_path(asset, graph, str(row.get("target_pin_path", "") or "")))
    for row in rows(output / "uaf_variable_usages.jsonl"):
        asset = str(row.get("asset_path", "") or ""); graph = str(row.get("graph_path", "") or "")
        add(rigvm_node_path(asset, graph, str(row.get("node_path", "") or "")),
            "uaf_rigvm_node_uses_variable", row.get("variable_path"))
    return edges


def _augment(output: Path, rows, nodes: list[dict], edges: list[dict], graph_module):
    node_by_key = {(str(n.get("node_kind", "")), str(n.get("path", ""))): n for n in nodes}

    def register(path, kind, coverage="first_class", class_path="", *, family="uaf", root=False):
        path = _meaningful(path)
        if not path: return None
        key = (kind, path); node = node_by_key.get(key)
        if node is None:
            node = {
                "node_id": graph_module._node_id(kind, path), "node_kind": kind, "path": path,
                "coverage": coverage, "class_path": str(class_path or ""),
                "package_name": graph_module._package(path), "family": family, "root": bool(root),
            }
            nodes.append(node); node_by_key[key] = node
        else:
            if graph_module.COVERAGE_RANK.get(coverage, -1) > graph_module.COVERAGE_RANK.get(str(node.get("coverage", "")), -1):
                node["coverage"] = coverage
            if class_path and not node.get("class_path"): node["class_path"] = class_path
            if root: node["root"] = True
        return node

    edge_by_key = {
        (str(e.get("source_kind", "")), str(e.get("source", "")), str(e.get("relation", "")), str(e.get("target_kind", "")), str(e.get("target", ""))): e
        for e in edges
    }

    def add(source, relation, target, sk, tk, evidence, *, sf="uaf", tf="uaf", tc="first_class"):
        source = _meaningful(source); target = _meaningful(target)
        if not source or not target or source == target: return
        sn = node_by_key.get((sk, source)) or register(source, sk, family=sf)
        tn = node_by_key.get((tk, target)) or register(target, tk, coverage=tc, family=tf)
        if not sn or not tn: return
        key = (sk, source, relation, tk, target)
        value = dict(evidence); value.setdefault("quality", "exact_semantic")
        token = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        edge = edge_by_key.get(key)
        if edge is None:
            edge = {
                "edge_id": graph_module._edge_id(sk, source, relation, tk, target),
                "source_kind": sk, "source": source, "relation": relation, "target_kind": tk, "target": target,
                "source_coverage": sn.get("coverage", "first_class"), "target_coverage": tn.get("coverage", tc),
                "edge_quality": "exact_semantic", "evidence_count": 1, "evidence": [value],
            }
            edges.append(edge); edge_by_key[key] = edge
        else:
            current = {json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for x in edge.get("evidence", []) if isinstance(x, dict)}
            if token not in current:
                edge.setdefault("evidence", []).append(value)
                edge["evidence_count"] = len(edge["evidence"])
            edge["edge_quality"] = "exact_semantic"

    asset_kind = {}
    for row in rows(output / "uaf_assets.jsonl"):
        asset = str(row.get("asset_path", "") or ""); kind = str(row.get("asset_kind", "") or "")
        nk = "uaf_system" if kind == "system" else "uaf_animation_graph"
        asset_kind[asset] = nk
        register(asset, nk, class_path=str(row.get("asset_class", "") or ""), root=True)

    for row in rows(output / "uaf_entries.jsonl"):
        asset = str(row.get("asset_path", "") or ""); entry = str(row.get("entry_path", "") or "")
        register(entry, "uaf_entry", class_path=str(row.get("entry_class", "") or ""))
        register(str(row.get("graph_path", "") or ""), "rigvm_graph", family="rigvm")
        add(asset, "has_uaf_entry", entry, asset_kind.get(asset, "uaf_asset"), "uaf_entry", {"stream":"uaf_entries.jsonl","kind":"authored_uaf_entry"})
        add(entry, "uaf_entry_uses_rigvm_graph", row.get("graph_path"), "uaf_entry", "rigvm_graph", {"stream":"uaf_entries.jsonl","kind":"authored_uaf_entry_graph"}, tf="rigvm")

    for row in rows(output / "uaf_variables.jsonl"):
        asset = str(row.get("asset_path", "") or ""); variable = str(row.get("variable_path", "") or "")
        register(variable, "uaf_variable")
        add(asset, "has_uaf_variable", variable, asset_kind.get(asset, "uaf_asset"), "uaf_variable", {"stream":"uaf_variables.jsonl","kind":"authored_uaf_variable","guid":str(row.get("variable_guid", "") or ""),"name":str(row.get("variable_name", "") or "")})
        target = _meaningful(row.get("type_object"))
        if target:
            register(target, "type", coverage="partial", class_path=target, family="type")
            add(variable, "uaf_variable_uses_type", target, "uaf_variable", "type", {"stream":"uaf_variables.jsonl","kind":"authored_uaf_variable_type"}, tf="type", tc="partial")

    for row in rows(output / "uaf_components.jsonl"):
        asset = str(row.get("asset_path", "") or ""); index = int(row.get("component_index", 0) or 0)
        comp = component_path(asset, index); struct = _meaningful(row.get("component_struct"))
        register(comp, "uaf_component")
        add(asset, "has_uaf_component", comp, asset_kind.get(asset, "uaf_asset"), "uaf_component", {"stream":"uaf_components.jsonl","kind":"authored_uaf_component","component_index":index})
        if struct:
            register(struct, "struct", coverage="partial", class_path=struct, family="struct")
            add(comp, "instance_of_uaf_component_struct", struct, "uaf_component", "struct", {"stream":"uaf_components.jsonl","kind":"authored_uaf_component_struct"}, tf="struct", tc="partial")

    for row in rows(output / "uaf_entry_points.jsonl"):
        asset = str(row.get("asset_path", "") or ""); index = int(row.get("entry_point_index", 0) or 0); name = str(row.get("entry_point_name", "") or "")
        ep = entry_point_path(asset, index, name); register(ep, "uaf_entry_point")
        add(asset, "has_uaf_entry_point", ep, asset_kind.get(asset, "uaf_asset"), "uaf_entry_point", {"stream":"uaf_entry_points.jsonl","kind":"authored_uaf_runtime_entry_point","packed_root_trait_handle":str(row.get("packed_root_trait_handle", "") or "")})

    for row in rows(output / "uaf_rigvm_graphs.jsonl"):
        asset = str(row.get("asset_path", "") or ""); graph = str(row.get("graph_path", "") or "")
        register(graph, "rigvm_graph", class_path=str(row.get("graph_class", "") or ""), family="rigvm")
        add(asset, "has_uaf_rigvm_graph", graph, asset_kind.get(asset, "uaf_asset"), "rigvm_graph", {"stream":"uaf_rigvm_graphs.jsonl","kind":"authored_uaf_rigvm_graph","schema_class":str(row.get("schema_class", "") or "")}, tf="rigvm")

    for row in rows(output / "uaf_rigvm_nodes.jsonl"):
        asset = str(row.get("asset_path", "") or ""); graph = str(row.get("graph_path", "") or ""); raw = str(row.get("node_path", "") or "")
        node = rigvm_node_path(asset, graph, raw); cls = _meaningful(row.get("node_class")); unit = _meaningful(row.get("unit_script_struct"))
        register(node, "rigvm_node", class_path=cls, family="rigvm")
        add(graph, "has_rigvm_node", node, "rigvm_graph", "rigvm_node", {"stream":"uaf_rigvm_nodes.jsonl","kind":"authored_uaf_rigvm_node","node_path":raw}, sf="rigvm", tf="rigvm")
        if cls:
            register(cls, "class", coverage="partial", class_path=cls, family="class")
            add(node, "instance_of_rigvm_node_class", cls, "rigvm_node", "class", {"stream":"uaf_rigvm_nodes.jsonl","kind":"rigvm_node_class"}, sf="rigvm", tf="class", tc="partial")
        if unit:
            register(unit, "struct", coverage="partial", class_path=unit, family="struct")
            add(node, "instance_of_rigvm_unit_struct", unit, "rigvm_node", "struct", {"stream":"uaf_rigvm_nodes.jsonl","kind":"rigvm_unit_struct"}, sf="rigvm", tf="struct", tc="partial")

    for row in rows(output / "uaf_rigvm_pins.jsonl"):
        asset = str(row.get("asset_path", "") or ""); graph = str(row.get("graph_path", "") or "")
        node = rigvm_node_path(asset, graph, str(row.get("node_path", "") or "")); pin = rigvm_pin_path(asset, graph, str(row.get("pin_path", "") or ""))
        register(pin, "rigvm_pin", family="rigvm")
        add(node, "has_rigvm_pin", pin, "rigvm_node", "rigvm_pin", {"stream":"uaf_rigvm_pins.jsonl","kind":"authored_uaf_rigvm_pin","direction":str(row.get("direction", "") or ""),"depth":int(row.get("depth",0) or 0)}, sf="rigvm", tf="rigvm")

    for row in rows(output / "uaf_rigvm_links.jsonl"):
        asset = str(row.get("asset_path", "") or ""); graph = str(row.get("graph_path", "") or "")
        source = rigvm_pin_path(asset, graph, str(row.get("source_pin_path", "") or "")); target = rigvm_pin_path(asset, graph, str(row.get("target_pin_path", "") or ""))
        add(source, "rigvm_connects", target, "rigvm_pin", "rigvm_pin", {"stream":"uaf_rigvm_links.jsonl","kind":"authored_uaf_rigvm_link"}, sf="rigvm", tf="rigvm")

    for row in rows(output / "uaf_variable_usages.jsonl"):
        asset = str(row.get("asset_path", "") or ""); graph = str(row.get("graph_path", "") or "")
        node = rigvm_node_path(asset, graph, str(row.get("node_path", "") or "")); variable = str(row.get("variable_path", "") or "")
        add(node, "uaf_rigvm_node_uses_variable", variable, "rigvm_node", "uaf_variable", {"stream":"uaf_variable_usages.jsonl","kind":"exact_hidden_variable_pin_resolution","variable_guid":str(row.get("variable_guid", "") or ""),"variable_name":str(row.get("variable_name", "") or "")}, sf="rigvm")

    nodes.sort(key=lambda n: (str(n.get("path", "")), str(n.get("node_kind", ""))))
    edges.sort(key=lambda e: (str(e.get("source", "")), str(e.get("relation", "")), str(e.get("target", ""))))
    return nodes, edges


def _promote_public_derived_version(project_graph_module) -> None:
    project_graph_module.DERIVED_SCHEMA_VERSION = max(int(getattr(project_graph_module, "DERIVED_SCHEMA_VERSION", 0) or 0), TARGET_DERIVED_SCHEMA_VERSION)
    target = Path(__file__).with_name("uatool.py").resolve()
    for module in tuple(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if not module_file or not hasattr(module, "FINAL_DERIVED_SCHEMA_VERSION"): continue
        try:
            if Path(module_file).resolve() != target: continue
        except (OSError, RuntimeError, TypeError):
            continue
        if int(getattr(module, "FINAL_DERIVED_SCHEMA_VERSION", 0) or 0) < TARGET_DERIVED_SCHEMA_VERSION:
            setattr(module, "FINAL_DERIVED_SCHEMA_VERSION", TARGET_DERIVED_SCHEMA_VERSION)


def install(project_graph_module) -> None:
    if getattr(project_graph_module, "_uaf_graph_installed", False):
        _promote_public_derived_version(project_graph_module); return
    original_derive = project_graph_module.derive
    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods
    project_graph_module.derive = derive
    project_graph_module._uaf_graph_installed = True
    _promote_public_derived_version(project_graph_module)
