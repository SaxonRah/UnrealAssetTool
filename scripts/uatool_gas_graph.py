#!/usr/bin/env python3
"""Promote systems-schema-6 GAS facts into the typed project graph.

Only relationships with exact normalized source fields are emitted. Broad exported
GameplayTagContainer strings, live specs, active effects, prediction state and
other runtime-only state are deliberately not reconstructed here.
"""
from __future__ import annotations

import json
from pathlib import Path

RELATION_STREAMS = {
    "defines_gameplay_ability_class": "gas_abilities.jsonl",
    "inherits_gameplay_ability_class": "gas_abilities.jsonl",
    "uses_cost_gameplay_effect_class": "gas_abilities.jsonl",
    "uses_cooldown_gameplay_effect_class": "gas_abilities.jsonl",
    "has_gameplay_ability_trigger": "gas_ability_triggers.jsonl",
    "triggered_by_gameplay_tag": "gas_ability_triggers.jsonl",
    "has_additional_gameplay_ability_cost": "gas_ability_costs.jsonl",
    "instance_of_gameplay_ability_cost_class": "gas_ability_costs.jsonl",
    "instance_of_gameplay_ability_set_class": "gas_ability_sets.jsonl",
    "grants_gameplay_ability_class": "gas_ability_set_abilities.jsonl",
    "grants_gameplay_effect_class": "gas_ability_set_effects.jsonl",
    "grants_attribute_set_class": "gas_ability_set_attributes.jsonl",
    "defines_gameplay_effect_class": "gas_gameplay_effects.jsonl",
    "inherits_gameplay_effect_class": "gas_gameplay_effects.jsonl",
    "has_gameplay_effect_component": "gas_gameplay_effect_components.jsonl",
    "instance_of_gameplay_effect_component_class": "gas_gameplay_effect_components.jsonl",
    "has_gameplay_effect_modifier": "gas_gameplay_effect_modifiers.jsonl",
    "modifies_gameplay_attribute": "gas_gameplay_effect_modifiers.jsonl",
    "has_gameplay_effect_execution": "gas_gameplay_effect_executions.jsonl",
    "uses_gameplay_effect_execution_calculation": "gas_gameplay_effect_executions.jsonl",
    "has_gameplay_effect_execution_modifier": "gas_gameplay_effect_execution_modifiers.jsonl",
    "captures_gameplay_attribute": "gas_gameplay_effect_execution_modifiers.jsonl",
    "has_gameplay_effect_cue": "gas_gameplay_effect_cues.jsonl",
    "uses_cue_magnitude_attribute": "gas_gameplay_effect_cues.jsonl",
    "defines_gameplay_cue_class": "gas_gameplay_cues.jsonl",
    "inherits_gameplay_cue_class": "gas_gameplay_cues.jsonl",
    "handles_gameplay_cue_tag": "gas_gameplay_cues.jsonl",
    "inherits_attribute_set_class": "gas_attribute_sets.jsonl",
    "has_gameplay_attribute": "gas_attributes.jsonl",
}


def _trigger_path(ability: str, index: int) -> str:
    return f"{ability}#gas_trigger:{index}"


def _modifier_path(effect: str, index: int) -> str:
    return f"{effect}#gas_modifier:{index}"


def _execution_path(effect: str, index: int) -> str:
    return f"{effect}#gas_execution:{index}"


def _execution_modifier_path(effect: str, execution_index: int, modifier_index: int) -> str:
    return f"{effect}#gas_execution:{execution_index}#modifier:{modifier_index}"


def _effect_cue_path(effect: str, index: int) -> str:
    return f"{effect}#gas_cue:{index}"


def _attribute_path(owner_class: str, name: str) -> str:
    owner_class = str(owner_class or "")
    name = str(name or "")
    return f"{owner_class}:{name}" if owner_class and name else ""


def _meaningful(value) -> str:
    text = str(value or "")
    return "" if text in {"None", "null", "NULL"} else text


def expected_edge_keys(output: Path, rows) -> set[tuple[str, str, str]]:
    """Return exact source/relation/target keys implied by schema-6 canonical rows."""
    output = Path(output)
    edges: set[tuple[str, str, str]] = set()

    def add(source, relation, target):
        source = _meaningful(source)
        target = _meaningful(target)
        if source and target and source != target:
            edges.add((source, relation, target))

    for row in rows(output / "gas_abilities.jsonl"):
        ability = str(row.get("ability_path", "") or "")
        generated = str(row.get("generated_class", "") or "")
        add(ability, "defines_gameplay_ability_class", generated)
        add(generated, "inherits_gameplay_ability_class", row.get("parent_class", ""))
        add(ability, "uses_cost_gameplay_effect_class", row.get("cost_gameplay_effect_class", ""))
        add(ability, "uses_cooldown_gameplay_effect_class", row.get("cooldown_gameplay_effect_class", ""))

    for row in rows(output / "gas_ability_triggers.jsonl"):
        ability = str(row.get("ability_path", "") or "")
        index = int(row.get("trigger_index", 0) or 0)
        trigger = _trigger_path(ability, index)
        add(ability, "has_gameplay_ability_trigger", trigger)
        add(trigger, "triggered_by_gameplay_tag", row.get("trigger_tag", ""))

    for row in rows(output / "gas_ability_costs.jsonl"):
        ability = str(row.get("ability_path", "") or "")
        cost = str(row.get("cost_path", "") or "")
        add(ability, "has_additional_gameplay_ability_cost", cost)
        add(cost, "instance_of_gameplay_ability_cost_class", row.get("cost_class", ""))

    for row in rows(output / "gas_ability_sets.jsonl"):
        add(row.get("ability_set_path", ""), "instance_of_gameplay_ability_set_class", row.get("class_path", ""))
    for row in rows(output / "gas_ability_set_abilities.jsonl"):
        add(row.get("ability_set_path", ""), "grants_gameplay_ability_class", row.get("ability_class", ""))
    for row in rows(output / "gas_ability_set_effects.jsonl"):
        add(row.get("ability_set_path", ""), "grants_gameplay_effect_class", row.get("gameplay_effect_class", ""))
    for row in rows(output / "gas_ability_set_attributes.jsonl"):
        add(row.get("ability_set_path", ""), "grants_attribute_set_class", row.get("attribute_set_class", ""))

    for row in rows(output / "gas_gameplay_effects.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        generated = str(row.get("generated_class", "") or "")
        add(effect, "defines_gameplay_effect_class", generated)
        add(generated, "inherits_gameplay_effect_class", row.get("parent_class", ""))

    for row in rows(output / "gas_gameplay_effect_components.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        component = str(row.get("component_path", "") or "")
        add(effect, "has_gameplay_effect_component", component)
        add(component, "instance_of_gameplay_effect_component_class", row.get("component_class", ""))

    for row in rows(output / "gas_gameplay_effect_modifiers.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        index = int(row.get("modifier_index", 0) or 0)
        modifier = _modifier_path(effect, index)
        add(effect, "has_gameplay_effect_modifier", modifier)
        add(modifier, "modifies_gameplay_attribute", _attribute_path(
            row.get("attribute_owner_class", ""), row.get("attribute_name", "")
        ))

    for row in rows(output / "gas_gameplay_effect_executions.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        index = int(row.get("execution_index", 0) or 0)
        execution = _execution_path(effect, index)
        add(effect, "has_gameplay_effect_execution", execution)
        add(execution, "uses_gameplay_effect_execution_calculation", row.get("calculation_class", ""))

    for row in rows(output / "gas_gameplay_effect_execution_modifiers.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        execution_index = int(row.get("execution_index", 0) or 0)
        modifier_index = int(row.get("modifier_index", 0) or 0)
        execution = _execution_path(effect, execution_index)
        modifier = _execution_modifier_path(effect, execution_index, modifier_index)
        add(execution, "has_gameplay_effect_execution_modifier", modifier)
        add(modifier, "captures_gameplay_attribute", _attribute_path(
            row.get("attribute_owner_class", ""), row.get("attribute_name", "")
        ))

    for row in rows(output / "gas_gameplay_effect_cues.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        index = int(row.get("cue_index", 0) or 0)
        cue = _effect_cue_path(effect, index)
        add(effect, "has_gameplay_effect_cue", cue)
        add(cue, "uses_cue_magnitude_attribute", _attribute_path(
            row.get("magnitude_attribute_owner_class", ""), row.get("magnitude_attribute_name", "")
        ))

    for row in rows(output / "gas_gameplay_cues.jsonl"):
        cue = str(row.get("gameplay_cue_path", "") or "")
        generated = str(row.get("generated_class", "") or "")
        add(cue, "defines_gameplay_cue_class", generated)
        add(generated, "inherits_gameplay_cue_class", row.get("parent_class", ""))
        add(cue, "handles_gameplay_cue_tag", row.get("gameplay_cue_tag", ""))

    for row in rows(output / "gas_attribute_sets.jsonl"):
        add(row.get("attribute_set_class", ""), "inherits_attribute_set_class", row.get("super_class", ""))
    for row in rows(output / "gas_attributes.jsonl"):
        owner = str(row.get("attribute_set_class", "") or "")
        add(owner, "has_gameplay_attribute", _attribute_path(owner, row.get("attribute_name", "")))

    return edges


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
            str(n.get("family", "")) != "asset_registry",
            str(n.get("node_kind", "")),
        ))

    def register(path: str, kind: str, coverage: str, class_path: str = "", *, root=False, family="gas"):
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
            *, source_coverage="first_class", target_coverage="partial"):
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

    abilities = list(rows(output / "gas_abilities.jsonl"))
    effects = list(rows(output / "gas_gameplay_effects.jsonl"))
    cues = list(rows(output / "gas_gameplay_cues.jsonl"))
    attribute_sets = list(rows(output / "gas_attribute_sets.jsonl"))

    ability_classes = {str(r.get("generated_class", "")): r for r in abilities if r.get("generated_class")}
    effect_classes = {str(r.get("generated_class", "")): r for r in effects if r.get("generated_class")}
    cue_classes = {str(r.get("generated_class", "")): r for r in cues if r.get("generated_class")}
    attribute_set_classes = {str(r.get("attribute_set_class", "")): r for r in attribute_sets if r.get("attribute_set_class")}

    def class_kind(path: str) -> tuple[str, str]:
        path = _meaningful(path)
        if path in ability_classes:
            return "gameplay_ability_class", "first_class"
        if path in effect_classes:
            return "gameplay_effect_class", "first_class"
        if path in cue_classes:
            return "gameplay_cue_class", "first_class"
        if path in attribute_set_classes:
            return "gameplay_attribute_set", "first_class"
        return "class", "partial"

    def add_class_edge(source, relation, target, source_kind, evidence):
        target_kind, target_coverage = class_kind(str(target or ""))
        register(target, target_kind, target_coverage, str(target or ""), family="class" if target_kind == "class" else "gas")
        add(source, relation, target, source_kind, target_kind, evidence, target_coverage=target_coverage)

    for row in abilities:
        ability = str(row.get("ability_path", "") or "")
        generated = str(row.get("generated_class", "") or "")
        register(ability, "gameplay_ability", "first_class", generated, root=True)
        register(generated, "gameplay_ability_class", "first_class", generated)
        add(ability, "defines_gameplay_ability_class", generated, "gameplay_ability", "gameplay_ability_class", {
            "stream": "gas_abilities.jsonl", "kind": "canonical_generated_class",
        }, target_coverage="first_class")
        add_class_edge(generated, "inherits_gameplay_ability_class", row.get("parent_class", ""), "gameplay_ability_class", {
            "stream": "gas_abilities.jsonl", "kind": "canonical_direct_parent",
        })
        for field, relation in (
            ("cost_gameplay_effect_class", "uses_cost_gameplay_effect_class"),
            ("cooldown_gameplay_effect_class", "uses_cooldown_gameplay_effect_class"),
        ):
            target = _meaningful(row.get(field, ""))
            if target:
                add_class_edge(ability, relation, target, "gameplay_ability", {
                    "stream": "gas_abilities.jsonl", "kind": "canonical_cdo_class_reference", "field": field,
                })

    for row in rows(output / "gas_ability_triggers.jsonl"):
        ability = str(row.get("ability_path", "") or "")
        index = int(row.get("trigger_index", 0) or 0)
        trigger = _trigger_path(ability, index)
        register(trigger, "gameplay_ability_trigger", "first_class")
        add(ability, "has_gameplay_ability_trigger", trigger, "gameplay_ability", "gameplay_ability_trigger", {
            "stream": "gas_ability_triggers.jsonl", "kind": "canonical_ordered_trigger", "trigger_index": index,
            "trigger_source": row.get("trigger_source", ""),
        }, target_coverage="first_class")
        tag = _meaningful(row.get("trigger_tag", ""))
        if tag:
            register(tag, "gameplay_tag", "first_class")
            add(trigger, "triggered_by_gameplay_tag", tag, "gameplay_ability_trigger", "gameplay_tag", {
                "stream": "gas_ability_triggers.jsonl", "kind": "canonical_trigger_tag", "trigger_index": index,
                "trigger_source": row.get("trigger_source", ""),
            }, target_coverage="first_class")

    for row in rows(output / "gas_ability_costs.jsonl"):
        ability = str(row.get("ability_path", "") or "")
        index = int(row.get("cost_index", 0) or 0)
        cost = _meaningful(row.get("cost_path", ""))
        if not cost:
            continue
        register(cost, "gameplay_ability_cost", "first_class", row.get("cost_class", ""))
        add(ability, "has_additional_gameplay_ability_cost", cost, "gameplay_ability", "gameplay_ability_cost", {
            "stream": "gas_ability_costs.jsonl", "kind": "canonical_ordered_additional_cost", "cost_index": index,
        }, target_coverage="first_class")
        add_class_edge(cost, "instance_of_gameplay_ability_cost_class", row.get("cost_class", ""), "gameplay_ability_cost", {
            "stream": "gas_ability_costs.jsonl", "kind": "canonical_cost_class", "cost_index": index,
        })

    for row in rows(output / "gas_ability_sets.jsonl"):
        ability_set = str(row.get("ability_set_path", "") or "")
        register(ability_set, "gameplay_ability_set", "first_class", row.get("class_path", ""), root=True)
        add_class_edge(ability_set, "instance_of_gameplay_ability_set_class", row.get("class_path", ""), "gameplay_ability_set", {
            "stream": "gas_ability_sets.jsonl", "kind": "canonical_asset_class",
        })
    for filename, relation, field, target_default in (
        ("gas_ability_set_abilities.jsonl", "grants_gameplay_ability_class", "ability_class", "gameplay_ability_class"),
        ("gas_ability_set_effects.jsonl", "grants_gameplay_effect_class", "gameplay_effect_class", "gameplay_effect_class"),
        ("gas_ability_set_attributes.jsonl", "grants_attribute_set_class", "attribute_set_class", "gameplay_attribute_set"),
    ):
        for row in rows(output / filename):
            ability_set = str(row.get("ability_set_path", "") or "")
            target = _meaningful(row.get(field, ""))
            kind, coverage = class_kind(target)
            if kind == "class" and target_default == "gameplay_attribute_set":
                kind = target_default
            elif kind == "class" and target_default in {"gameplay_ability_class", "gameplay_effect_class"}:
                kind = target_default
            register(target, kind, coverage, target)
            add(ability_set, relation, target, "gameplay_ability_set", kind, {
                "stream": filename, "kind": "canonical_ordered_ability_set_grant",
                "grant_index": int(row.get("grant_index", 0) or 0),
                "input_tag": row.get("input_tag", ""),
            }, target_coverage=coverage)

    for row in effects:
        effect = str(row.get("gameplay_effect_path", "") or "")
        generated = str(row.get("generated_class", "") or "")
        register(effect, "gameplay_effect", "first_class", generated, root=True)
        register(generated, "gameplay_effect_class", "first_class", generated)
        add(effect, "defines_gameplay_effect_class", generated, "gameplay_effect", "gameplay_effect_class", {
            "stream": "gas_gameplay_effects.jsonl", "kind": "canonical_generated_class",
        }, target_coverage="first_class")
        add_class_edge(generated, "inherits_gameplay_effect_class", row.get("parent_class", ""), "gameplay_effect_class", {
            "stream": "gas_gameplay_effects.jsonl", "kind": "canonical_direct_parent",
        })

    for row in rows(output / "gas_gameplay_effect_components.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        index = int(row.get("component_index", 0) or 0)
        component = str(row.get("component_path", "") or "")
        register(component, "gameplay_effect_component", "first_class", row.get("component_class", ""))
        add(effect, "has_gameplay_effect_component", component, "gameplay_effect", "gameplay_effect_component", {
            "stream": "gas_gameplay_effect_components.jsonl", "kind": "canonical_ordered_ge_component", "component_index": index,
        }, target_coverage="first_class")
        add_class_edge(component, "instance_of_gameplay_effect_component_class", row.get("component_class", ""), "gameplay_effect_component", {
            "stream": "gas_gameplay_effect_components.jsonl", "kind": "canonical_component_class", "component_index": index,
        })

    for row in rows(output / "gas_gameplay_effect_modifiers.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        index = int(row.get("modifier_index", 0) or 0)
        modifier = _modifier_path(effect, index)
        register(modifier, "gameplay_effect_modifier", "first_class")
        add(effect, "has_gameplay_effect_modifier", modifier, "gameplay_effect", "gameplay_effect_modifier", {
            "stream": "gas_gameplay_effect_modifiers.jsonl", "kind": "canonical_ordered_modifier", "modifier_index": index,
            "modifier_op": row.get("modifier_op", ""),
        }, target_coverage="first_class")
        attr = _attribute_path(row.get("attribute_owner_class", ""), row.get("attribute_name", ""))
        if attr:
            register(attr, "gameplay_attribute", "first_class", row.get("attribute_owner_class", ""))
            add(modifier, "modifies_gameplay_attribute", attr, "gameplay_effect_modifier", "gameplay_attribute", {
                "stream": "gas_gameplay_effect_modifiers.jsonl", "kind": "canonical_modifier_attribute", "modifier_index": index,
                "modifier_op": row.get("modifier_op", ""),
            }, target_coverage="first_class")

    for row in rows(output / "gas_gameplay_effect_executions.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        index = int(row.get("execution_index", 0) or 0)
        execution = _execution_path(effect, index)
        register(execution, "gameplay_effect_execution", "first_class", row.get("calculation_class", ""))
        add(effect, "has_gameplay_effect_execution", execution, "gameplay_effect", "gameplay_effect_execution", {
            "stream": "gas_gameplay_effect_executions.jsonl", "kind": "canonical_ordered_execution", "execution_index": index,
        }, target_coverage="first_class")
        add_class_edge(execution, "uses_gameplay_effect_execution_calculation", row.get("calculation_class", ""), "gameplay_effect_execution", {
            "stream": "gas_gameplay_effect_executions.jsonl", "kind": "canonical_execution_calculation", "execution_index": index,
        })

    for row in rows(output / "gas_gameplay_effect_execution_modifiers.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        execution_index = int(row.get("execution_index", 0) or 0)
        modifier_index = int(row.get("modifier_index", 0) or 0)
        execution = _execution_path(effect, execution_index)
        modifier = _execution_modifier_path(effect, execution_index, modifier_index)
        register(modifier, "gameplay_effect_execution_modifier", "first_class")
        add(execution, "has_gameplay_effect_execution_modifier", modifier, "gameplay_effect_execution", "gameplay_effect_execution_modifier", {
            "stream": "gas_gameplay_effect_execution_modifiers.jsonl", "kind": "canonical_ordered_execution_modifier",
            "execution_index": execution_index, "modifier_index": modifier_index,
        }, target_coverage="first_class")
        attr = _attribute_path(row.get("attribute_owner_class", ""), row.get("attribute_name", ""))
        if attr:
            register(attr, "gameplay_attribute", "first_class", row.get("attribute_owner_class", ""))
            add(modifier, "captures_gameplay_attribute", attr, "gameplay_effect_execution_modifier", "gameplay_attribute", {
                "stream": "gas_gameplay_effect_execution_modifiers.jsonl", "kind": "canonical_capture_attribute",
                "execution_index": execution_index, "modifier_index": modifier_index, "snapshot": row.get("snapshot", ""),
            }, target_coverage="first_class")

    for row in rows(output / "gas_gameplay_effect_cues.jsonl"):
        effect = str(row.get("gameplay_effect_path", "") or "")
        index = int(row.get("cue_index", 0) or 0)
        cue = _effect_cue_path(effect, index)
        register(cue, "gameplay_effect_cue", "first_class")
        add(effect, "has_gameplay_effect_cue", cue, "gameplay_effect", "gameplay_effect_cue", {
            "stream": "gas_gameplay_effect_cues.jsonl", "kind": "canonical_ordered_effect_cue", "cue_index": index,
            "gameplay_cue_tags": row.get("gameplay_cue_tags", ""),
        }, target_coverage="first_class")
        attr = _attribute_path(row.get("magnitude_attribute_owner_class", ""), row.get("magnitude_attribute_name", ""))
        if attr:
            register(attr, "gameplay_attribute", "first_class", row.get("magnitude_attribute_owner_class", ""))
            add(cue, "uses_cue_magnitude_attribute", attr, "gameplay_effect_cue", "gameplay_attribute", {
                "stream": "gas_gameplay_effect_cues.jsonl", "kind": "canonical_cue_magnitude_attribute", "cue_index": index,
            }, target_coverage="first_class")

    for row in cues:
        cue = str(row.get("gameplay_cue_path", "") or "")
        generated = str(row.get("generated_class", "") or "")
        register(cue, "gameplay_cue", "first_class", generated, root=True)
        register(generated, "gameplay_cue_class", "first_class", generated)
        add(cue, "defines_gameplay_cue_class", generated, "gameplay_cue", "gameplay_cue_class", {
            "stream": "gas_gameplay_cues.jsonl", "kind": "canonical_generated_class",
        }, target_coverage="first_class")
        add_class_edge(generated, "inherits_gameplay_cue_class", row.get("parent_class", ""), "gameplay_cue_class", {
            "stream": "gas_gameplay_cues.jsonl", "kind": "canonical_direct_parent",
        })
        tag = _meaningful(row.get("gameplay_cue_tag", ""))
        if tag:
            register(tag, "gameplay_tag", "first_class")
            add(cue, "handles_gameplay_cue_tag", tag, "gameplay_cue", "gameplay_tag", {
                "stream": "gas_gameplay_cues.jsonl", "kind": "canonical_cue_tag",
            }, target_coverage="first_class")

    for row in attribute_sets:
        attribute_set = str(row.get("attribute_set_class", "") or "")
        register(attribute_set, "gameplay_attribute_set", "first_class", attribute_set, root=True)
        add_class_edge(attribute_set, "inherits_attribute_set_class", row.get("super_class", ""), "gameplay_attribute_set", {
            "stream": "gas_attribute_sets.jsonl", "kind": "canonical_direct_parent",
        })
    for row in rows(output / "gas_attributes.jsonl"):
        attribute_set = str(row.get("attribute_set_class", "") or "")
        index = int(row.get("attribute_index", 0) or 0)
        attribute = _attribute_path(attribute_set, row.get("attribute_name", ""))
        register(attribute, "gameplay_attribute", "first_class", attribute_set)
        add(attribute_set, "has_gameplay_attribute", attribute, "gameplay_attribute_set", "gameplay_attribute", {
            "stream": "gas_attributes.jsonl", "kind": "canonical_declared_attribute", "attribute_index": index,
            "cpp_type": row.get("cpp_type", ""),
        }, target_coverage="first_class")

    nodes.sort(key=lambda n: (str(n.get("path", "")), str(n.get("node_kind", "")), str(n.get("node_id", ""))))
    edges.sort(key=lambda e: (str(e.get("source", "")), str(e.get("relation", "")), str(e.get("target", "")), str(e.get("edge_id", ""))))
    return nodes, edges


def install(project_graph_module) -> None:
    if getattr(project_graph_module, "_gas_graph_installed", False):
        return

    original_derive = project_graph_module.derive

    def derive(output, rows):
        nodes, edges, neighborhoods = original_derive(output, rows)
        nodes, edges = _augment(Path(output), rows, nodes, edges, project_graph_module)
        return nodes, edges, neighborhoods

    project_graph_module.derive = derive
    project_graph_module._gas_graph_installed = True

    import uatool_project_graph_finalize as finalize_module
    if not getattr(finalize_module, "_gas_roots_installed", False):
        original_roots = finalize_module._canonical_roots

        def canonical_roots(output, rows):
            roots = original_roots(output, rows)
            for filename, path_field, kind in (
                ("gas_abilities.jsonl", "ability_path", "gameplay_ability"),
                ("gas_ability_sets.jsonl", "ability_set_path", "gameplay_ability_set"),
                ("gas_gameplay_effects.jsonl", "gameplay_effect_path", "gameplay_effect"),
                ("gas_gameplay_cues.jsonl", "gameplay_cue_path", "gameplay_cue"),
                ("gas_attribute_sets.jsonl", "attribute_set_class", "gameplay_attribute_set"),
            ):
                for row in rows(output / filename):
                    path = str(row.get(path_field, "") or "")
                    if path:
                        roots[path] = kind
            return roots

        finalize_module._canonical_roots = canonical_roots
        finalize_module._gas_roots_installed = True
