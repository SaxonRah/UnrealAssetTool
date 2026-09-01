#!/usr/bin/env python3
"""Conservative enum-type inference for readable Blueprint literal expressions."""
from __future__ import annotations

from typing import Callable

import uatool_blueprint_enums as blueprint_enums


def _source_enum_paths(expr: dict, pins_by_node, *, depth: int = 0, max_depth: int = 8) -> set[str]:
    """Return enum types established by an expression's output provenance."""
    if not isinstance(expr, dict) or depth >= max_depth:
        return set()

    result: set[str] = set()
    node_id = str(expr.get("node_id", "") or "")
    output_pin = str(expr.get("output_pin", "") or "")
    if node_id and output_pin:
        enum_path = blueprint_enums._pin_enum_path(
            pins_by_node.get(node_id, {}).get(output_pin)
        )
        if enum_path:
            result.add(enum_path)

    # Reroutes/wildcards can occasionally lose their concrete subtype on the
    # immediate output pin. Preserve provenance by walking upstream, but only
    # as a set; callers still require a unique matching enum before decoding.
    if not result:
        for item in expr.get("inputs", []) or []:
            if not isinstance(item, dict):
                continue
            for source in item.get("sources", []) or []:
                if isinstance(source, dict):
                    result.update(
                        _source_enum_paths(
                            source,
                            pins_by_node,
                            depth=depth + 1,
                            max_depth=max_depth,
                        )
                    )
    return result


def _literal_enum_path(expr: dict, item: dict, lookup, pins_by_node) -> str:
    """Resolve one literal's enum only when the evidence is unambiguous."""
    node_id = str(expr.get("node_id", "") or "")
    pin_name = str(item.get("pin", "") or "")
    raw_value = str(item.get("literal", "") or "")
    if not node_id or not raw_value:
        return ""

    node_pins = pins_by_node.get(node_id, {})
    direct = blueprint_enums._pin_enum_path(node_pins.get(pin_name))
    if direct and lookup.get((direct, raw_value)) is not None:
        return direct

    candidates: set[str] = set()

    # Some generic enum operators expose one typed operand and one wildcard-ish
    # literal operand. A sibling pin's subtype is valid evidence only when that
    # enum actually contains the raw serialized token.
    for pin in node_pins.values():
        enum_path = blueprint_enums._pin_enum_path(pin)
        if enum_path and lookup.get((enum_path, raw_value)) is not None:
            candidates.add(enum_path)

    # If the operator pins themselves do not retain the subtype, the connected
    # sibling expression often does (for example BreakStruct.RotationMode ->
    # Equal(Enum).A while B is the raw NewEnumerator literal).
    for sibling in expr.get("inputs", []) or []:
        if not isinstance(sibling, dict) or sibling is item:
            continue
        for source in sibling.get("sources", []) or []:
            if not isinstance(source, dict):
                continue
            for enum_path in _source_enum_paths(source, pins_by_node):
                if lookup.get((enum_path, raw_value)) is not None:
                    candidates.add(enum_path)

    return next(iter(candidates)) if len(candidates) == 1 else ""


def render_expression(
    expr: dict,
    lookup,
    pins_by_node,
    original_render: Callable,
    depth: int = 0,
    max_depth: int = 8,
) -> str:
    """Render inferred enum literals without mutating raw expression provenance."""
    if not isinstance(expr, dict):
        return original_render(expr, lookup, pins_by_node, depth, max_depth)

    clone = dict(expr)
    inputs = []
    for item in expr.get("inputs", []) or []:
        if not isinstance(item, dict):
            inputs.append(item)
            continue
        rendered = dict(item)
        if "literal" in item:
            raw_value = str(item.get("literal", "") or "")
            enum_path = _literal_enum_path(expr, item, lookup, pins_by_node)
            if enum_path:
                rendered["literal"] = blueprint_enums._display_value(
                    lookup,
                    enum_path,
                    raw_value,
                )
        inputs.append(rendered)
    if "inputs" in expr:
        clone["inputs"] = inputs

    return original_render(clone, lookup, pins_by_node, depth, max_depth)


def install() -> None:
    if getattr(blueprint_enums, "_enum_literal_inference_installed", False):
        return

    original_render = blueprint_enums._render_expression

    def inferred_render(expr, lookup, pins_by_node, depth=0, max_depth=8):
        return render_expression(
            expr,
            lookup,
            pins_by_node,
            original_render,
            depth,
            max_depth,
        )

    blueprint_enums._render_expression = inferred_render
    blueprint_enums._enum_literal_inference_installed = True
