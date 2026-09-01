#!/usr/bin/env python3
"""Readable enum decoration for derived Gameplay Camera behavior.

The behavior layer keeps the canonical dependency expression tree untouched, but
its compact expression_text/literal_values should be useful to an AI without
re-decoding Blueprint user-defined enum storage.  This module reuses the same
canonical Blueprint enum model and pin typing used by the general Blueprint
semantic renderer.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

import uatool_blueprint_enums as blueprint_enums
import uatool_core as core

GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION = 2
_OPAQUE_ENUM_RE = re.compile(r"^(?:[^:]+::)?NewEnumerator\d+$")


def _pin_maps(output: Path) -> dict[str, dict[str, dict]]:
    by_node_name: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    for pin in core.iter_blueprint_pin_rows(Path(output)):
        node_id = str(pin.get("node_id", "") or "")
        name = str(pin.get("name", "") or "")
        if node_id and name and name not in by_node_name[node_id]:
            by_node_name[node_id][name] = pin
    return by_node_name


def _pin_enum_path(pin: dict | None) -> str:
    if not isinstance(pin, dict):
        return ""
    pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
    return str(pin_type.get("subcategory_object", "") or "")


def _display(lookup: dict[tuple[str, str], dict], enum_path: str, raw: str) -> str:
    return blueprint_enums._display_value(lookup, str(enum_path or ""), str(raw or ""))


def _selector_enum_path(node_pins: dict[str, dict], operation: str) -> str:
    if str(operation or "") != "select":
        return ""
    for name in ("Index", "Selection"):
        enum_path = _pin_enum_path(node_pins.get(name))
        if enum_path:
            return enum_path
    return ""


def _logical_field_name(raw_name: str) -> str:
    # Kept local so this decorator can install before/after the behavior module
    # without creating an import-time circular dependency.
    value = str(raw_name or "")
    match = re.match(r"^(?P<name>.+)_\d+_[0-9A-Fa-f]{32}$", value)
    return match.group("name") if match else value


def _render(
    value,
    lookup: dict[tuple[str, str], dict],
    pins_by_node: dict[str, dict[str, dict]],
    expected_enum_path: str = "",
    depth: int = 0,
    max_depth: int = 12,
) -> str:
    if depth >= max_depth:
        return "..."
    if isinstance(value, list):
        return ", ".join(
            _render(item, lookup, pins_by_node, expected_enum_path, depth + 1, max_depth)
            for item in value
        )
    if not isinstance(value, dict):
        return str(value)
    if "literal" in value:
        raw = str(value.get("literal", "") or "")
        return _display(lookup, expected_enum_path, raw)

    kind = str(value.get("kind", "") or "")
    operation = str(value.get("operation", "") or "")
    node_id = str(value.get("node_id", "") or "")
    node_pins = pins_by_node.get(node_id, {})
    selector_enum = _selector_enum_path(node_pins, operation)
    label = str(value.get("label", "") or operation or kind or "expression")
    output_pin = str(value.get("output_pin", "") or "")
    inputs = [
        item for item in value.get("inputs", [])
        if isinstance(item, dict) and item.get("pin")
    ] if isinstance(value.get("inputs"), list) else []

    if inputs:
        args: list[str] = []
        for item in inputs:
            raw_pin = str(item.get("pin", "") or "")
            rendered_pin = _display(lookup, selector_enum, raw_pin)
            value_enum = _pin_enum_path(node_pins.get(raw_pin)) or expected_enum_path
            if "literal" in item:
                rendered = _display(lookup, value_enum, str(item.get("literal", "") or ""))
            else:
                sources = item.get("sources", []) if isinstance(item.get("sources"), list) else []
                rendered_values = [
                    _render(child, lookup, pins_by_node, value_enum, depth + 1, max_depth)
                    for child in sources
                    if isinstance(child, dict)
                ]
                rendered_values = [part for part in rendered_values if part]
                rendered = rendered_values[0] if len(rendered_values) == 1 else "[" + ", ".join(rendered_values) + "]"
            args.append(f"{_logical_field_name(rendered_pin)}={rendered}")
        text = f"{label}({', '.join(args)})"
    elif kind == "boundary":
        text = "boundary:" + label
    else:
        text = label

    if output_pin and output_pin not in {"ReturnValue", label}:
        text += "." + _logical_field_name(output_pin)
    return text


def _literal_records(
    value,
    lookup: dict[tuple[str, str], dict],
    pins_by_node: dict[str, dict[str, dict]],
    expected_enum_path: str = "",
) -> list[dict]:
    records: list[dict] = []

    def visit(node, expected: str) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child, expected)
            return
        if not isinstance(node, dict):
            return
        if "literal" in node:
            raw = str(node.get("literal", "") or "")
            display = _display(lookup, expected, raw)
            records.append({
                "raw": raw,
                "display": display,
                "enum_path": expected,
                "opaque": bool(_OPAQUE_ENUM_RE.match(raw)),
                "decoded": bool(not _OPAQUE_ENUM_RE.match(raw) or display != raw),
            })
            return

        node_id = str(node.get("node_id", "") or "")
        operation = str(node.get("operation", "") or "")
        node_pins = pins_by_node.get(node_id, {})
        for item in node.get("inputs", []) if isinstance(node.get("inputs"), list) else []:
            if not isinstance(item, dict):
                continue
            raw_pin = str(item.get("pin", "") or "")
            value_enum = _pin_enum_path(node_pins.get(raw_pin)) or expected
            if "literal" in item:
                visit({"literal": item.get("literal", "")}, value_enum)
            for child in item.get("sources", []) if isinstance(item.get("sources"), list) else []:
                visit(child, value_enum)

    visit(value, expected_enum_path)

    unique: dict[tuple[str, str, str], dict] = {}
    for row in records:
        key = (str(row.get("raw", "")), str(row.get("display", "")), str(row.get("enum_path", "")))
        unique[key] = row
    return [unique[key] for key in sorted(unique)]


def _expected_enum_path(row: dict, dependency_by_id: dict[str, dict], pins_by_node: dict[str, dict[str, dict]]) -> str:
    dep = dependency_by_id.get(str(row.get("dependency_id", "") or ""), {})
    expression = dep.get("expression", {}) if isinstance(dep.get("expression"), dict) else {}
    node_id = str(expression.get("node_id", "") or "")
    raw_field = str(row.get("raw_field_name", "") or "")
    return _pin_enum_path(pins_by_node.get(node_id, {}).get(raw_field))


def _decorate_row(
    row: dict,
    dependency_by_id: dict[str, dict],
    lookup: dict[tuple[str, str], dict],
    pins_by_node: dict[str, dict[str, dict]],
) -> None:
    expression = row.get("expression", {})
    expected_enum = _expected_enum_path(row, dependency_by_id, pins_by_node)
    row["schema_version"] = GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION
    row["expression_text"] = _render(expression, lookup, pins_by_node, expected_enum)
    records = _literal_records(expression, lookup, pins_by_node, expected_enum)
    row["enum_literal_decodings"] = records
    row["raw_literal_values"] = sorted({str(item.get("raw", "")) for item in records if item.get("raw")})
    row["literal_values"] = sorted({str(item.get("display", "")) for item in records if item.get("display")})
    row["enum_paths"] = sorted({str(item.get("enum_path", "")) for item in records if item.get("enum_path")})
    opaque = [item for item in records if bool(item.get("opaque", False))]
    decoded = [item for item in opaque if bool(item.get("decoded", False))]
    row["opaque_enum_literal_count"] = len(opaque)
    row["decoded_opaque_enum_literal_count"] = len(decoded)
    row["enum_literals_fully_decoded"] = len(decoded) == len(opaque)


def decorate(output: Path, providers: list[dict], fields: list[dict], inputs: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    output = Path(output).expanduser().resolve()
    lookup = blueprint_enums._entry_lookup(output)
    pins_by_node = _pin_maps(output)
    dependency_by_id = {
        str(row.get("dependency_id", "") or ""): row
        for row in core.iter_jsonl(output / "blueprint_data_dependencies.jsonl")
        if str(row.get("dependency_id", "") or "")
    }

    fields_by_provider: dict[str, list[dict]] = collections.defaultdict(list)
    for row in fields:
        _decorate_row(row, dependency_by_id, lookup, pins_by_node)
        fields_by_provider[str(row.get("provider_id", "") or "")].append(row)
    for row in inputs:
        _decorate_row(row, dependency_by_id, lookup, pins_by_node)

    for provider in providers:
        provider["schema_version"] = GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION
        provider_fields = fields_by_provider.get(str(provider.get("provider_id", "") or ""), [])
        provider["opaque_enum_literal_count"] = sum(int(row.get("opaque_enum_literal_count", 0) or 0) for row in provider_fields)
        provider["decoded_opaque_enum_literal_count"] = sum(int(row.get("decoded_opaque_enum_literal_count", 0) or 0) for row in provider_fields)
        provider["fully_decoded"] = all(bool(row.get("enum_literals_fully_decoded", False)) for row in provider_fields)
    return providers, fields, inputs


def install(camera_behavior_module) -> None:
    if getattr(camera_behavior_module, "_gameplay_camera_behavior_enums_installed", False):
        return
    original_derive = camera_behavior_module.derive
    original_validation_error = camera_behavior_module.validation_error

    camera_behavior_module.GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION = GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION

    def derive(output, rows=None):
        providers, fields, inputs = original_derive(output, rows)
        return decorate(Path(output), providers, fields, inputs)

    def validation_error(output, rows=None):
        error = original_validation_error(output, rows)
        if error:
            return error
        row_reader = rows or camera_behavior_module._rows
        for filename in camera_behavior_module.DERIVED_FILES:
            for row in row_reader(Path(output) / filename):
                if int(row.get("schema_version", 0) or 0) != GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION:
                    return f"Gameplay Camera behavior row has stale schema in {filename}: {row.get('schema_version')}"
        for filename in camera_behavior_module.DERIVED_FILES[1:]:
            for row in row_reader(Path(output) / filename):
                records = row.get("enum_literal_decodings", []) if isinstance(row.get("enum_literal_decodings"), list) else []
                opaque = sum(1 for item in records if isinstance(item, dict) and bool(item.get("opaque", False)))
                decoded = sum(1 for item in records if isinstance(item, dict) and bool(item.get("opaque", False)) and bool(item.get("decoded", False)))
                if int(row.get("opaque_enum_literal_count", 0) or 0) != opaque:
                    return f"Gameplay Camera opaque enum literal count mismatch: {row.get('field_id', row.get('input_id', ''))}"
                if int(row.get("decoded_opaque_enum_literal_count", 0) or 0) != decoded:
                    return f"Gameplay Camera decoded enum literal count mismatch: {row.get('field_id', row.get('input_id', ''))}"
                if bool(row.get("enum_literals_fully_decoded", False)) != (decoded == opaque):
                    return f"Gameplay Camera enum decode completeness mismatch: {row.get('field_id', row.get('input_id', ''))}"
        return None

    camera_behavior_module.derive = derive
    camera_behavior_module.validation_error = validation_error
    camera_behavior_module._gameplay_camera_behavior_enums_installed = True
