#!/usr/bin/env python3
"""Persist conservative Gameplay Camera director/provider semantics as derived data.

The canonical Blueprint scan already contains the facts needed to reconstruct the
GASP Gameplay Camera path.  This module keeps the polymorphic interface boundary
explicit while splitting camera context structs into queryable fields.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path

import uatool_gameplay_camera_director_report as director_report

GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION = 1
DERIVED_FILES = (
    "gameplay_camera_property_providers.jsonl",
    "gameplay_camera_property_fields.jsonl",
    "gameplay_camera_director_inputs.jsonl",
)

_FIELD_SUFFIX_RE = re.compile(r"^(?P<name>.+)_\d+_[0-9A-Fa-f]{32}$")
_CVAR_RE = re.compile(r"VariableName=([^,\)]+)")

_SQL = """
CREATE TABLE gameplay_camera_property_providers(
 provider_id TEXT PRIMARY KEY,director_blueprint_path TEXT NOT NULL,interface_blueprint_path TEXT NOT NULL,
 call_id TEXT NOT NULL,provider_blueprint_path TEXT NOT NULL,function_id TEXT NOT NULL,function_name TEXT NOT NULL,
 implementation_kind TEXT NOT NULL,return_struct_type TEXT NOT NULL,return_dependency_count INTEGER NOT NULL,
 field_count INTEGER NOT NULL,fully_modeled INTEGER NOT NULL,json TEXT NOT NULL
);
CREATE INDEX gameplay_camera_provider_bp_idx ON gameplay_camera_property_providers(provider_blueprint_path,function_name);
CREATE INDEX gameplay_camera_provider_director_idx ON gameplay_camera_property_providers(director_blueprint_path);
CREATE TABLE gameplay_camera_property_fields(
 field_id TEXT PRIMARY KEY,provider_id TEXT NOT NULL,provider_blueprint_path TEXT NOT NULL,function_id TEXT NOT NULL,
 dependency_id TEXT NOT NULL,field_index INTEGER NOT NULL,field_name TEXT NOT NULL,raw_field_name TEXT NOT NULL,
 expression_text TEXT NOT NULL,source_kind TEXT NOT NULL,source_operations_json TEXT NOT NULL,source_labels_json TEXT NOT NULL,
 source_node_ids_json TEXT NOT NULL,function_calls_json TEXT NOT NULL,literal_values_json TEXT NOT NULL,
 expression_json TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX gameplay_camera_property_field_name_idx ON gameplay_camera_property_fields(field_name,provider_blueprint_path);
CREATE INDEX gameplay_camera_property_field_provider_idx ON gameplay_camera_property_fields(provider_id,field_index);
CREATE TABLE gameplay_camera_director_inputs(
 input_id TEXT PRIMARY KEY,director_blueprint_path TEXT NOT NULL,evaluation_node_id TEXT NOT NULL,chooser_path TEXT NOT NULL,
 dependency_id TEXT NOT NULL,field_index INTEGER NOT NULL,field_name TEXT NOT NULL,raw_field_name TEXT NOT NULL,
 source_kind TEXT NOT NULL,source_name TEXT NOT NULL,passthrough_field TEXT NOT NULL,
 provider_field_candidate_count INTEGER NOT NULL,provider_field_candidate_ids_json TEXT NOT NULL,
 expression_text TEXT NOT NULL,source_operations_json TEXT NOT NULL,source_labels_json TEXT NOT NULL,
 source_node_ids_json TEXT NOT NULL,function_calls_json TEXT NOT NULL,literal_values_json TEXT NOT NULL,
 source_statements_json TEXT NOT NULL,expression_json TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX gameplay_camera_director_input_field_idx ON gameplay_camera_director_inputs(field_name,director_blueprint_path);
CREATE INDEX gameplay_camera_director_input_chooser_idx ON gameplay_camera_director_inputs(chooser_path,evaluation_node_id);
"""


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield value


def _write(path: Path, values: list[dict]) -> int:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(_j(value) + "\n")
    return len(values)


def logical_field_name(raw_name: str) -> str:
    value = str(raw_name or "")
    match = _FIELD_SUFFIX_RE.match(value)
    return match.group("name") if match else value


def _stable_id(prefix: str, *parts) -> str:
    basis = "\x1f".join(str(part or "") for part in parts)
    return prefix + ":" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


def provider_path(provider: dict) -> str:
    return f"{provider.get('provider_blueprint_path', '')}#camera-properties={provider.get('function_name', '')}"


def provider_field_path(field: dict) -> str:
    return f"{field.get('provider_blueprint_path', '')}#camera-properties={field.get('function_id', '')}#field={field.get('field_name', '')}"


def director_input_path(row: dict) -> str:
    return f"{row.get('director_blueprint_path', '')}#camera-context={row.get('field_name', '')}@{row.get('evaluation_node_id', '')}"


def _root_expression(dep: dict) -> dict:
    value = dep.get("expression", {})
    return value if isinstance(value, dict) else {}


def _is_make_struct(expr: dict) -> bool:
    operation = str(expr.get("operation", "") or "").lower()
    label = str(expr.get("label", "") or "").lower()
    return operation == "make_struct" or label.startswith("make s_") or label.startswith("make ")


def _expression_inputs(expr: dict) -> list[dict]:
    values = expr.get("inputs", []) if isinstance(expr.get("inputs"), list) else []
    return [value for value in values if isinstance(value, dict) and value.get("pin")]


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _unique(values) -> list[str]:
    return sorted({str(value) for value in values if str(value)})


def _source_metadata(expression) -> dict:
    nodes = list(_walk(expression))
    operations = _unique(node.get("operation", "") for node in nodes if isinstance(node, dict))
    labels = _unique(node.get("label", "") for node in nodes if isinstance(node, dict))
    node_ids = _unique(node.get("node_id", "") for node in nodes if isinstance(node, dict))
    literals = _unique(node.get("literal", "") for node in nodes if isinstance(node, dict) and "literal" in node)
    return {
        "source_operations": operations,
        "source_labels": labels,
        "source_node_ids": node_ids,
        "literal_values": literals,
    }


def _render(value) -> str:
    if isinstance(value, list):
        return ", ".join(_render(item) for item in value)
    if not isinstance(value, dict):
        return str(value)
    if "literal" in value:
        return str(value.get("literal", ""))
    kind = str(value.get("kind", "") or "")
    label = str(value.get("label", "") or value.get("operation", "") or kind or "expression")
    output_pin = str(value.get("output_pin", "") or "")
    inputs = _expression_inputs(value)
    if inputs:
        args = []
        for item in inputs:
            sources = item.get("sources", []) if isinstance(item.get("sources"), list) else []
            if sources:
                rendered = _render(sources[0]) if len(sources) == 1 else "[" + _render(sources) + "]"
            elif "literal" in item:
                rendered = str(item.get("literal", ""))
            else:
                rendered = ""
            args.append(f"{logical_field_name(str(item.get('pin', '') or ''))}={rendered}")
        text = f"{label}({', '.join(args)})"
    elif kind == "boundary":
        text = "boundary:" + label
    else:
        text = label
    if output_pin and output_pin not in {"ReturnValue", label}:
        text += "." + logical_field_name(output_pin)
    return text


def _field_source(input_row: dict):
    sources = input_row.get("sources", []) if isinstance(input_row.get("sources"), list) else []
    if len(sources) == 1:
        return sources[0]
    if sources:
        return sources
    if "literal" in input_row:
        return {"literal": input_row.get("literal", ""), "type": input_row.get("type", "")}
    return {}


def _passthrough_field(expression) -> str:
    candidates: list[str] = []
    saw_camera_struct_break = False
    for node in _walk(expression):
        if not isinstance(node, dict):
            continue
        operation = str(node.get("operation", "") or "")
        label = str(node.get("label", "") or "")
        if operation == "break_struct" and "CharacterPropertiesForCamera" in label:
            saw_camera_struct_break = True
            output = logical_field_name(str(node.get("output_pin", "") or ""))
            if output:
                candidates.append(output)
    if saw_camera_struct_break and len(set(candidates)) == 1:
        return candidates[0]
    return ""


def _source_statements(node_ids: list[str], statement_by_node: dict[str, dict]) -> list[str]:
    result = []
    for node_id in node_ids:
        row = statement_by_node.get(node_id)
        if not row:
            continue
        text = str(row.get("text", "") or "")
        if text:
            result.append(text)
    return _unique(result)


def _console_variable(statements: list[str]) -> str:
    for text in statements:
        match = _CVAR_RE.search(text)
        if match:
            return match.group(1).strip()
    return ""


def _return_struct_type(candidate: dict) -> str:
    for output in candidate.get("outputs", []) if isinstance(candidate.get("outputs"), list) else []:
        if not isinstance(output, dict) or str(output.get("name", "") or "") != "ReturnValue":
            continue
        value = output.get("type", {}) if isinstance(output.get("type"), dict) else {}
        return str(value.get("subcategory_object", "") or "")
    return ""


def derive(output: Path, rows=None) -> tuple[list[dict], list[dict], list[dict]]:
    output = Path(output).expanduser().resolve()
    rows = rows or _rows
    report = director_report.build_report(output, rows)

    providers: list[dict] = []
    fields: list[dict] = []
    provider_fields_by_name: dict[str, list[str]] = {}

    for candidate in report.get("implementation_candidates", []):
        if not isinstance(candidate, dict):
            continue
        bp = str(candidate.get("blueprint_path", "") or "")
        function_id = str(candidate.get("function_id", "") or "")
        function_name = str(candidate.get("function_name", "") or "")
        call_id = str(candidate.get("call_id", "") or "")
        interface = str(candidate.get("interface_blueprint_path", "") or "")
        if not bp or not function_id:
            continue
        provider_id = _stable_id("camera_provider", call_id, bp, function_id)
        return_deps = [
            dep for dep in candidate.get("dependencies", [])
            if isinstance(dep, dict) and str(dep.get("sink_pin_name", "") or "") == "ReturnValue"
        ]
        parsed_field_count = 0
        fully_modeled = bool(return_deps)
        for dep_index, dep in enumerate(return_deps):
            root = _root_expression(dep)
            if not _is_make_struct(root):
                fully_modeled = False
                continue
            for field_index, input_row in enumerate(_expression_inputs(root)):
                raw_name = str(input_row.get("pin", "") or "")
                name = logical_field_name(raw_name)
                source = _field_source(input_row)
                metadata = _source_metadata(source)
                field_id = _stable_id("camera_property_field", provider_id, dep.get("dependency_id", ""), field_index, raw_name)
                row = {
                    "field_id": field_id,
                    "schema_version": GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION,
                    "provider_id": provider_id,
                    "provider_blueprint_path": bp,
                    "function_id": function_id,
                    "dependency_id": str(dep.get("dependency_id", "") or ""),
                    "dependency_index": dep_index,
                    "field_index": field_index,
                    "field_name": name,
                    "raw_field_name": raw_name,
                    "expression_text": _render(source),
                    "source_kind": "literal" if isinstance(source, dict) and "literal" in source else "expression",
                    "source_operations": metadata["source_operations"],
                    "source_labels": metadata["source_labels"],
                    "source_node_ids": metadata["source_node_ids"],
                    "function_calls": list(dep.get("function_calls", [])) if isinstance(dep.get("function_calls"), list) else [],
                    "literal_values": metadata["literal_values"],
                    "expression": source,
                }
                fields.append(row)
                provider_fields_by_name.setdefault(name, []).append(field_id)
                parsed_field_count += 1
        providers.append({
            "provider_id": provider_id,
            "schema_version": GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION,
            "director_blueprint_path": next(iter(report.get("director_paths", set())), ""),
            "interface_blueprint_path": interface,
            "call_id": call_id,
            "provider_blueprint_path": bp,
            "function_id": function_id,
            "function_name": function_name,
            "implementation_kind": str(candidate.get("implementation_kind", "") or ""),
            "return_struct_type": _return_struct_type(candidate),
            "return_dependency_count": len(return_deps),
            "field_count": parsed_field_count,
            "fully_modeled": fully_modeled and len(return_deps) == 1,
        })

    statement_by_node = report.get("statement_by_node", {}) if isinstance(report.get("statement_by_node"), dict) else {}
    chooser_by_source: dict[str, str] = {}
    for link in report.get("director_chooser_links", []):
        if not isinstance(link, dict):
            continue
        source_id = str(link.get("source_id", "") or "")
        target = str(link.get("target", "") or "")
        if source_id and target:
            chooser_by_source[source_id] = target

    inputs: list[dict] = []
    for eval_node in report.get("evaluation_nodes", []):
        if not isinstance(eval_node, dict):
            continue
        eval_id = str(eval_node.get("node_id", "") or "")
        director_bp = str(eval_node.get("blueprint_path", "") or "")
        chooser = chooser_by_source.get(eval_id, "")
        for dep in report.get("dependencies_by_sink", {}).get(eval_id, []):
            if not isinstance(dep, dict):
                continue
            root = _root_expression(dep)
            if not _is_make_struct(root):
                continue
            for field_index, input_row in enumerate(_expression_inputs(root)):
                raw_name = str(input_row.get("pin", "") or "")
                name = logical_field_name(raw_name)
                source = _field_source(input_row)
                metadata = _source_metadata(source)
                statements = _source_statements(metadata["source_node_ids"], statement_by_node)
                passthrough = _passthrough_field(source)
                cvar = _console_variable(statements)
                if passthrough:
                    source_kind = "provider_passthrough"
                    source_name = passthrough
                elif cvar:
                    source_kind = "console_variable"
                    source_name = cvar
                elif isinstance(source, dict) and "literal" in source:
                    source_kind = "literal"
                    source_name = str(source.get("literal", "") or "")
                else:
                    source_kind = "expression"
                    source_name = ""
                provider_candidate_ids = list(provider_fields_by_name.get(passthrough, [])) if passthrough else []
                input_id = _stable_id("camera_director_input", director_bp, eval_id, dep.get("dependency_id", ""), field_index, raw_name)
                inputs.append({
                    "input_id": input_id,
                    "schema_version": GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION,
                    "director_blueprint_path": director_bp,
                    "evaluation_node_id": eval_id,
                    "chooser_path": chooser,
                    "dependency_id": str(dep.get("dependency_id", "") or ""),
                    "field_index": field_index,
                    "field_name": name,
                    "raw_field_name": raw_name,
                    "source_kind": source_kind,
                    "source_name": source_name,
                    "passthrough_field": passthrough,
                    "provider_field_candidate_count": len(provider_candidate_ids),
                    "provider_field_candidate_ids": sorted(provider_candidate_ids),
                    "expression_text": _render(source),
                    "source_operations": metadata["source_operations"],
                    "source_labels": metadata["source_labels"],
                    "source_node_ids": metadata["source_node_ids"],
                    "function_calls": list(dep.get("function_calls", [])) if isinstance(dep.get("function_calls"), list) else [],
                    "literal_values": metadata["literal_values"],
                    "source_statements": statements,
                    "expression": source,
                })

    providers.sort(key=lambda row: (row["provider_blueprint_path"], row["function_id"], row["provider_id"]))
    fields.sort(key=lambda row: (row["provider_blueprint_path"], row["function_id"], row["field_index"], row["field_id"]))
    inputs.sort(key=lambda row: (row["director_blueprint_path"], row["evaluation_node_id"], row["field_index"], row["input_id"]))
    return providers, fields, inputs


def validation_error(output: Path, rows=None) -> str | None:
    output = Path(output)
    rows = rows or _rows
    providers = list(rows(output / DERIVED_FILES[0]))
    fields = list(rows(output / DERIVED_FILES[1]))
    inputs = list(rows(output / DERIVED_FILES[2]))
    provider_ids = [str(row.get("provider_id", "") or "") for row in providers]
    if any(not value for value in provider_ids) or len(provider_ids) != len(set(provider_ids)):
        return "Gameplay Camera provider ids are blank or duplicated"
    provider_by_id = {str(row.get("provider_id", "")): row for row in providers}
    field_ids = [str(row.get("field_id", "") or "") for row in fields]
    if any(not value for value in field_ids) or len(field_ids) != len(set(field_ids)):
        return "Gameplay Camera property field ids are blank or duplicated"
    field_by_id = {str(row.get("field_id", "")): row for row in fields}
    counts: dict[str, int] = {}
    seen_fields: set[tuple[str, str, int]] = set()
    for row in fields:
        provider_id = str(row.get("provider_id", "") or "")
        if provider_id not in provider_by_id:
            return f"Gameplay Camera property field references unknown provider: {provider_id}"
        key = (provider_id, str(row.get("dependency_id", "") or ""), int(row.get("field_index", 0) or 0))
        if key in seen_fields:
            return f"duplicate Gameplay Camera property field slot: {key}"
        seen_fields.add(key)
        counts[provider_id] = counts.get(provider_id, 0) + 1
    for provider_id, row in provider_by_id.items():
        if not row.get("provider_blueprint_path") or not row.get("function_id"):
            return f"Gameplay Camera provider missing Blueprint/function identity: {provider_id}"
        if int(row.get("field_count", 0) or 0) != counts.get(provider_id, 0):
            return f"Gameplay Camera provider field count mismatch: {provider_id}"
    input_ids = [str(row.get("input_id", "") or "") for row in inputs]
    if any(not value for value in input_ids) or len(input_ids) != len(set(input_ids)):
        return "Gameplay Camera director input ids are blank or duplicated"
    for row in inputs:
        if not row.get("director_blueprint_path") or not row.get("evaluation_node_id") or not row.get("field_name"):
            return f"Gameplay Camera director input missing identity: {row.get('input_id', '')}"
        candidate_ids = row.get("provider_field_candidate_ids", []) if isinstance(row.get("provider_field_candidate_ids"), list) else []
        if int(row.get("provider_field_candidate_count", 0) or 0) != len(candidate_ids):
            return f"Gameplay Camera director input candidate count mismatch: {row.get('input_id', '')}"
        for field_id in candidate_ids:
            if str(field_id) not in field_by_id:
                return f"Gameplay Camera director input references unknown provider field: {field_id}"
        if row.get("source_kind") == "provider_passthrough" and not row.get("passthrough_field"):
            return f"Gameplay Camera passthrough input lacks field identity: {row.get('input_id', '')}"
    return None


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def load_database(conn, output: Path, rows=None) -> None:
    rows = rows or _rows
    for row in rows(Path(output) / DERIVED_FILES[0]):
        conn.execute(
            "INSERT OR REPLACE INTO gameplay_camera_property_providers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("provider_id", ""), row.get("director_blueprint_path", ""), row.get("interface_blueprint_path", ""),
                row.get("call_id", ""), row.get("provider_blueprint_path", ""), row.get("function_id", ""),
                row.get("function_name", ""), row.get("implementation_kind", ""), row.get("return_struct_type", ""),
                int(row.get("return_dependency_count", 0) or 0), int(row.get("field_count", 0) or 0),
                int(bool(row.get("fully_modeled", False))), _j(row),
            ),
        )
    for row in rows(Path(output) / DERIVED_FILES[1]):
        conn.execute(
            "INSERT OR REPLACE INTO gameplay_camera_property_fields VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("field_id", ""), row.get("provider_id", ""), row.get("provider_blueprint_path", ""), row.get("function_id", ""),
                row.get("dependency_id", ""), int(row.get("field_index", 0) or 0), row.get("field_name", ""), row.get("raw_field_name", ""),
                row.get("expression_text", ""), row.get("source_kind", ""), _j(row.get("source_operations", [])), _j(row.get("source_labels", [])),
                _j(row.get("source_node_ids", [])), _j(row.get("function_calls", [])), _j(row.get("literal_values", [])),
                _j(row.get("expression", {})), _j(row),
            ),
        )
    for row in rows(Path(output) / DERIVED_FILES[2]):
        conn.execute(
            "INSERT OR REPLACE INTO gameplay_camera_director_inputs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("input_id", ""), row.get("director_blueprint_path", ""), row.get("evaluation_node_id", ""), row.get("chooser_path", ""),
                row.get("dependency_id", ""), int(row.get("field_index", 0) or 0), row.get("field_name", ""), row.get("raw_field_name", ""),
                row.get("source_kind", ""), row.get("source_name", ""), row.get("passthrough_field", ""),
                int(row.get("provider_field_candidate_count", 0) or 0), _j(row.get("provider_field_candidate_ids", [])),
                row.get("expression_text", ""), _j(row.get("source_operations", [])), _j(row.get("source_labels", [])),
                _j(row.get("source_node_ids", [])), _j(row.get("function_calls", [])), _j(row.get("literal_values", [])),
                _j(row.get("source_statements", [])), _j(row.get("expression", {})), _j(row),
            ),
        )


def query_table(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gameplay_camera_property_providers'").fetchone():
        return
    print("\n[Gameplay Camera property providers]")
    print_rows(
        conn.execute(
            """SELECT provider_blueprint_path,function_name,implementation_kind,field_count,fully_modeled
               FROM gameplay_camera_property_providers
               WHERE provider_blueprint_path LIKE ? OR function_name LIKE ? LIMIT ?""",
            (pattern, pattern, limit),
        ),
        ("provider_blueprint_path", "function_name", "implementation_kind", "field_count", "fully_modeled"),
    )
    print("\n[Gameplay Camera property fields]")
    print_rows(
        conn.execute(
            """SELECT provider_blueprint_path,field_name,expression_text
               FROM gameplay_camera_property_fields
               WHERE provider_blueprint_path LIKE ? OR field_name LIKE ? OR expression_text LIKE ? LIMIT ?""",
            (pattern, pattern, pattern, limit),
        ),
        ("provider_blueprint_path", "field_name", "expression_text"),
    )
    print("\n[Gameplay Camera director inputs]")
    print_rows(
        conn.execute(
            """SELECT director_blueprint_path,field_name,source_kind,source_name,passthrough_field,provider_field_candidate_count,chooser_path
               FROM gameplay_camera_director_inputs
               WHERE director_blueprint_path LIKE ? OR field_name LIKE ? OR source_name LIKE ? OR chooser_path LIKE ? LIMIT ?""",
            (pattern, pattern, pattern, pattern, limit),
        ),
        ("director_blueprint_path", "field_name", "source_kind", "source_name", "passthrough_field", "provider_field_candidate_count", "chooser_path"),
    )


def _update_manifest(output: Path, provider_count: int, field_count: int, input_count: int) -> None:
    path = output / "manifest.json"
    if not path.is_file():
        return
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid manifest.json while recording Gameplay Camera behavior: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("invalid manifest.json root while recording Gameplay Camera behavior")
    manifest["gameplay_camera_behavior_schema_version"] = GAMEPLAY_CAMERA_BEHAVIOR_SCHEMA_VERSION
    declared = manifest.get("derived_counts", {})
    declared = declared if isinstance(declared, dict) else {}
    declared["gameplay_camera_property_providers"] = int(provider_count)
    declared["gameplay_camera_property_fields"] = int(field_count)
    declared["gameplay_camera_director_inputs"] = int(input_count)
    manifest["derived_counts"] = declared
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def install(core_module, runtime_module) -> None:
    if getattr(core_module, "_gameplay_camera_behavior_installed", False):
        return
    original_create_schema = core_module.create_schema
    original_derive_output = core_module.derive_output
    original_build_database = core_module.build_database
    original_query = core_module.query

    def create_schema_wrapper(conn):
        original_create_schema(conn)
        create_schema(conn)

    def derive_output_wrapper(output):
        output = Path(output).expanduser().resolve()
        counts = dict(original_derive_output(output))
        providers, fields, inputs = derive(output, runtime_module._rows)
        provider_count = _write(output / DERIVED_FILES[0], providers)
        field_count = _write(output / DERIVED_FILES[1], fields)
        input_count = _write(output / DERIVED_FILES[2], inputs)
        error = validation_error(output, runtime_module._rows)
        if error:
            raise RuntimeError(f"Gameplay Camera behavior derived incomplete: {error}")
        _update_manifest(output, provider_count, field_count, input_count)
        counts["gameplay_camera_property_providers"] = provider_count
        counts["gameplay_camera_property_fields"] = field_count
        counts["gameplay_camera_director_inputs"] = input_count
        return counts

    def build_database_wrapper(output):
        db = original_build_database(output)
        conn = sqlite3.connect(db)
        try:
            load_database(conn, Path(output), runtime_module._rows)
            conn.commit()
        finally:
            conn.close()
        return db

    def query_wrapper(args):
        result = int(original_query(args))
        root = Path(args.output).expanduser().resolve()
        db = root if root.suffix.lower() == ".db" else root / core_module.DB_NAME
        if db.is_file():
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                query_table(conn, core_module._print_rows, f"%{args.term}%", args.limit)
            finally:
                conn.close()
        return result

    core_module.create_schema = create_schema_wrapper
    core_module.derive_output = derive_output_wrapper
    core_module.build_database = build_database_wrapper
    core_module.query = query_wrapper
    core_module.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((*core_module.DEFAULT_BUNDLE_FILES, *DERIVED_FILES)))
    core_module._gameplay_camera_behavior_installed = True
