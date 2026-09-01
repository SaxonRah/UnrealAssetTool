#!/usr/bin/env python3
"""Promote derived Chooser decision rows into the typed project graph."""
from __future__ import annotations

import json
from pathlib import Path


def decision_path(chooser_path: str, row_index: int) -> str:
    return f"{str(chooser_path or '')}#chooser-row={int(row_index)}"


def _augment(output: Path, rows, nodes: list[dict], edges: list[dict], graph_module):
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

    def register(path: str, kind: str, coverage: str, class_path: str = "", family: str = "chooser", root: bool = False):
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

    predicates_by_decision: dict[str, list[dict]] = {}
    for predicate in rows(output / "chooser_decision_predicates.jsonl"):
        predicates_by_decision.setdefault(str(predicate.get("decision_id", "") or ""), []).append(predicate)

    for row in rows(output / "chooser_decisions.jsonl"):
        chooser = str(row.get("chooser_path", "") or "")
        row_index = int(row.get("row_index", 0) or 0)
        decision_id = str(row.get("decision_id", "") or "")
        if not chooser or not decision_id:
            continue
        chooser_node = existing(chooser) or register(chooser, "chooser_table", "first_class", family="animation", root=True)
        if not chooser_node:
            continue
        virtual_path = decision_path(chooser, row_index)
        coverage = "first_class" if bool(row.get("fully_modeled", False)) else "partial"
        register(virtual_path, "chooser_decision", coverage, family="chooser", root=False)
        evidence = {
            "stream": "chooser_decisions.jsonl",
            "kind": "derived_chooser_decision",
            "decision_id": decision_id,
            "row_index": row_index,
            "condition_text": str(row.get("condition_text", "") or ""),
            "fully_modeled": bool(row.get("fully_modeled", False)),
            "fully_decoded": bool(row.get("fully_decoded", False)),
            "disabled": bool(row.get("disabled", False)),
        }
        add(
            chooser,
            "has_chooser_decision",
            virtual_path,
            str(chooser_node.get("node_kind", "chooser_table")),
            "chooser_decision",
            evidence,
        )
        for predicate in predicates_by_decision.get(decision_id, []):
            enum_path = str(predicate.get("enum_path", "") or "")
            if not enum_path:
                continue
            enum_node = existing(enum_path) or register(enum_path, "user_defined_enum", "first_class", family="blueprint", root=True)
            if not enum_node:
                continue
            add(
                virtual_path,
                "tests_chooser_enum",
                enum_path,
                "chooser_decision",
                str(enum_node.get("node_kind", "user_defined_enum")),
                {
                    "stream": "chooser_decision_predicates.jsonl",
                    "kind": "derived_chooser_predicate",
                    "decision_id": decision_id,
                    "column_index": int(predicate.get("column_index", 0) or 0),
                    "property_name": str(predicate.get("property_name", "") or ""),
                    "comparison": str(predicate.get("comparison", "") or ""),
                    "display_value": str(predicate.get("display_value", "") or ""),
                    "match_any": bool(predicate.get("match_any", False)),
                },
            )
        for ref in row.get("result_references", []) if isinstance(row.get("result_references", []), list) else []:
            if not isinstance(ref, dict):
                continue
            target = str(ref.get("target_path", "") or "")
            if not target:
                continue
            target_class = str(ref.get("target_class", "") or "")
            target_node = existing(target)
            if target_node is None:
                target_kind = graph_module._class_leaf(target_class) if target_class else "object"
                target_node = register(target, target_kind, "partial", target_class, family="chooser_result")
            if not target_node:
                continue
            add(
                virtual_path,
                "disabled_chooser_result" if bool(row.get("disabled", False)) else "selects_chooser_result",
                target,
                "chooser_decision",
                str(target_node.get("node_kind", "object")),
                {
                    **evidence,
                    "reference_kind": str(ref.get("reference_kind", "") or ""),
                    "target_class": target_class,
                },
            )

    nodes.sort(key=lambda n: (str(n.get("path", "")), str(n.get("node_kind", "")), str(n.get("node_id", ""))))
    edges.sort(key=lambda e: (str(e.get("source", "")), str(e.get("relation", "")), str(e.get("target", "")), str(e.get("edge_id", ""))))
    return nodes, edges


def install(project_graph_module) -> None:
    if getattr(project_graph_module, "_chooser_graph_installed", False):
        return
    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._chooser_graph_installed = True
