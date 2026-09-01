#!/usr/bin/env python3
"""Conservative interpretation of UE Chooser enum columns.

The animation breadth scanner intentionally preserves Chooser columns/results as
raw exported InstancedStruct values. This module reads only the well-proven
/Script/Chooser.EnumColumn shape and aligns each RowValues entry with the same
Chooser result index. Unsupported columns/comparisons stay raw and are never
invented.
"""
from __future__ import annotations

import re
from pathlib import Path

KNOWN_COMPARISONS = {"MatchAny", "MatchEqual", "MatchNotEqual"}
_OBJECT_PATH_RE = re.compile(r"'([^']+)'$")


def _strip_outer(value: str) -> str:
    value = str(value or "").strip()
    if value.startswith("(") and value.endswith(")"):
        return value[1:-1]
    return value


def _split_top_level(value: str) -> list[str]:
    result: list[str] = []
    start = 0
    depth = 0
    quoted = False
    escaped = False
    for index, char in enumerate(value):
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            result.append(value[start:index].strip())
            start = index + 1
    tail = value[start:].strip()
    if tail:
        result.append(tail)
    return result


def _fields(value: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in _split_top_level(_strip_outer(value)):
        if "=" not in item:
            continue
        name, raw = item.split("=", 1)
        name = name.strip()
        if name and name not in result:
            result[name] = raw.strip()
    return result


def _unquote(value: str) -> str:
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return value


def _object_path(value: str) -> str:
    value = _unquote(value)
    match = _OBJECT_PATH_RE.search(value)
    return match.group(1) if match else value


def _integer(value: str, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def _binding_chain(value: str) -> list[str]:
    value = _strip_outer(value)
    result = []
    for item in _split_top_level(value):
        item = _unquote(item)
        if item:
            result.append(item)
    return result


def _enum_lookup(entries: list[dict]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for row in entries:
        path = str(row.get("enum_path", "") or "")
        if path:
            result.setdefault(path, []).append(row)
    return result


def _decode_enum_value(by_enum: dict[str, list[dict]], enum_path: str, raw_name: str) -> tuple[str, bool]:
    raw_name = str(raw_name or "")
    if not enum_path or not raw_name:
        return raw_name, False
    candidates = by_enum.get(enum_path, [])
    exact = [row for row in candidates if str(row.get("raw_name", "") or "") == raw_name]
    if len(exact) != 1:
        short = raw_name.rsplit("::", 1)[-1]
        exact = [
            row for row in candidates
            if str(row.get("raw_name", "") or "").rsplit("::", 1)[-1] == short
        ]
    if len(exact) != 1:
        return raw_name, False
    row = exact[0]
    return str(row.get("display_name", "") or row.get("authored_name", "") or raw_name), True


def parse_enum_column(raw_value: str, *, column_index: int, result_count: int, enum_entries: list[dict]) -> dict | None:
    raw_value = str(raw_value or "").strip()
    if not raw_value.startswith("/Script/Chooser.EnumColumn("):
        return None
    open_index = raw_value.find("(")
    if open_index < 0 or not raw_value.endswith(")"):
        return None
    top = _fields(raw_value[open_index:])
    input_value = top.get("InputValue", "")
    if "EnumContextProperty" not in input_value:
        return None
    input_open = input_value.find("(")
    input_fields = _fields(input_value[input_open:]) if input_open >= 0 else {}
    binding_raw = input_fields.get("Binding", "")
    binding = _fields(binding_raw)

    enum_path = _object_path(binding.get("Enum", ""))
    context_index = _integer(binding.get("ContextIndex", "0"), 0)
    display_name = _unquote(binding.get("DisplayName", ""))
    chain = _binding_chain(binding.get("PropertyBindingChain", ""))
    property_name = display_name or (chain[-1].split("_", 1)[0] if chain else "")

    default_fields = _fields(top.get("DefaultRowValue", ""))
    default_comparison = str(default_fields.get("Comparison", "MatchEqual") or "MatchEqual")

    row_values_raw = top.get("RowValues", "")
    row_values_body = _strip_outer(row_values_raw)
    row_items = _split_top_level(row_values_body)
    if len(row_items) != result_count:
        return None

    by_enum = _enum_lookup(enum_entries)
    values: list[dict] = []
    for row_index, item in enumerate(row_items):
        fields = _fields(item)
        comparison = str(fields.get("Comparison", default_comparison) or default_comparison)
        raw_name = _unquote(fields.get("ValueName", ""))
        display_value, decoded = _decode_enum_value(by_enum, enum_path, raw_name)
        match_any = comparison == "MatchAny"
        known_comparison = comparison in KNOWN_COMPARISONS
        if match_any:
            text = "any"
        elif comparison == "MatchEqual":
            text = f"{property_name or 'value'} == {display_value or raw_name}"
        elif comparison == "MatchNotEqual":
            text = f"{property_name or 'value'} != {display_value or raw_name}"
        else:
            text = f"{property_name or 'value'} {comparison} {display_value or raw_name}".strip()
        values.append({
            "row_index": row_index,
            "column_index": int(column_index),
            "context_index": context_index,
            "property_name": property_name,
            "binding_chain": chain,
            "enum_path": enum_path,
            "comparison": comparison,
            "raw_value_name": raw_name,
            "display_value": display_value,
            "numeric_value": fields.get("Value", ""),
            "match_any": match_any,
            "known_comparison": known_comparison,
            "decoded": bool(match_any or decoded),
            "text": text,
            "raw_value": item,
        })

    return {
        "column_index": int(column_index),
        "context_index": context_index,
        "property_name": property_name,
        "binding_chain": chain,
        "enum_path": enum_path,
        "default_comparison": default_comparison,
        "rows": values,
    }


def build_decisions(
    chooser_path: str,
    *,
    result_count: int,
    columns: list[dict],
    results: list[dict],
    references: list[dict],
    enum_entries: list[dict],
) -> list[dict]:
    parsed_columns: list[dict] = []
    for column in sorted(columns, key=lambda row: int(row.get("index", 0) or 0)):
        if str(column.get("asset_path", "") or "") != chooser_path:
            continue
        parsed = parse_enum_column(
            str(column.get("raw_value", "") or ""),
            column_index=int(column.get("index", 0) or 0),
            result_count=result_count,
            enum_entries=enum_entries,
        )
        if parsed is not None:
            parsed_columns.append(parsed)

    result_by_index = {
        int(row.get("index", 0) or 0): row
        for row in results
        if str(row.get("asset_path", "") or "") == chooser_path
    }
    refs_by_index: dict[int, list[dict]] = {}
    for ref in references:
        if str(ref.get("owner_path", "") or "") != chooser_path:
            continue
        if str(ref.get("source_kind", "") or "") != "chooser_result":
            continue
        refs_by_index.setdefault(int(ref.get("source_index", 0) or 0), []).append(ref)

    decisions: list[dict] = []
    for row_index in range(result_count):
        predicates = [column["rows"][row_index] for column in parsed_columns]
        effective = [predicate for predicate in predicates if not predicate.get("match_any", False)]
        condition_text = " and ".join(str(predicate.get("text", "")) for predicate in effective if predicate.get("text")) or "always"
        refs = sorted(
            refs_by_index.get(row_index, []),
            key=lambda row: (str(row.get("target_path", "") or ""), str(row.get("target_class", "") or "")),
        )
        result = result_by_index.get(row_index, {})
        decisions.append({
            "chooser_path": chooser_path,
            "row_index": row_index,
            "disabled": bool(result.get("disabled", False)),
            "condition_text": condition_text,
            "predicate_count": len(predicates),
            "effective_predicate_count": len(effective),
            "modeled_column_count": len(parsed_columns),
            "fully_modeled": len(parsed_columns) == len(columns),
            "fully_decoded": all(bool(predicate.get("decoded", False)) and bool(predicate.get("known_comparison", False)) for predicate in predicates),
            "predicates": predicates,
            "result_struct_type": str(result.get("struct_type", "") or ""),
            "result_raw_value": str(result.get("raw_value", "") or ""),
            "result_references": [
                {
                    "target_path": str(ref.get("target_path", "") or ""),
                    "target_class": str(ref.get("target_class", "") or ""),
                    "reference_kind": str(ref.get("reference_kind", "") or ""),
                }
                for ref in refs
            ],
        })
    return decisions


def decisions_for_output(output: Path, rows, chooser_paths: set[str] | None = None) -> list[dict]:
    output = Path(output)
    tables = list(rows(output / "chooser_tables.jsonl"))
    columns = list(rows(output / "chooser_columns.jsonl"))
    results = list(rows(output / "chooser_results.jsonl"))
    references = list(rows(output / "animation_struct_references.jsonl"))
    enum_entries = list(rows(output / "blueprint_enum_entries.jsonl"))
    decisions: list[dict] = []
    for table in tables:
        chooser_path = str(table.get("chooser_path", "") or "")
        if not chooser_path or (chooser_paths is not None and chooser_path not in chooser_paths):
            continue
        decisions.extend(build_decisions(
            chooser_path,
            result_count=int(table.get("result_count", 0) or 0),
            columns=columns,
            results=results,
            references=references,
            enum_entries=enum_entries,
        ))
    decisions.sort(key=lambda row: (str(row.get("chooser_path", "")), int(row.get("row_index", 0) or 0)))
    return decisions
