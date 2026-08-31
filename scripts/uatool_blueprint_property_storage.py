#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

STORAGE_SCHEMA_VERSION = 1
ENCODING = "blueprint_node_property_blocks_v1"
PROPERTY_FILE = "blueprint_node_properties.jsonl"
NODE_FILE = "blueprint_nodes.jsonl"

AUTHORITATIVE_NODE_FIELDS = ("blueprint_path", "graph_name", "node_class")
COLUMN_FIELDS = (
    "property_name",
    "property_path",
    "owner_class",
    "declaring_type",
    "depth",
    "property_type",
    "cpp_type",
    "value",
    "object_path",
    "object_class",
    "property_flags",
    "truncated",
)
LEGACY_FIELDS = {"node_id", *AUTHORITATIVE_NODE_FIELDS, *COLUMN_FIELDS}
BLOCK_FIELDS = {"encoding", "node_id", "property_count", "columns"}


def _j(value: dict) -> str:
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
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield line_number, row


def _read_manifest(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"manifest root is not an object: {path}")
    return value


def _collapse(values: list):
    if not values:
        return []
    first = values[0]
    return first if all(value == first for value in values[1:]) else values


def _expand_column(value, count: int, field: str, context: str) -> list:
    if isinstance(value, list):
        if len(value) != count:
            raise RuntimeError(
                f"Blueprint property block column {field!r} length mismatch in {context}: "
                f"expected {count}, got {len(value)}"
            )
        return value
    return [value] * count


def _node_map(output: Path) -> dict[str, tuple[str, str, str]]:
    result: dict[str, tuple[str, str, str]] = {}
    path = output / NODE_FILE
    for line_number, row in _rows(path) or ():
        node_id = str(row.get("node_id", ""))
        if not node_id:
            raise RuntimeError(f"Blueprint node missing node_id in {path}:{line_number}")
        if node_id in result:
            raise RuntimeError(f"duplicate Blueprint node_id in {path}:{line_number}: {node_id}")
        result[node_id] = tuple(str(row.get(field, "")) for field in AUTHORITATIVE_NODE_FIELDS)
    return result


def _validate_block(row: dict, context: str) -> tuple[int, int]:
    extra = set(row) - BLOCK_FIELDS
    if extra:
        raise RuntimeError(f"Blueprint property block has unsupported fields {sorted(extra)} in {context}")
    if row.get("encoding") != ENCODING:
        raise RuntimeError(f"unexpected Blueprint property encoding in {context}: {row.get('encoding')!r}")
    node_id = row.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        raise RuntimeError(f"Blueprint property block has invalid node_id in {context}")
    count = row.get("property_count")
    if not isinstance(count, int) or count < 0:
        raise RuntimeError(f"Blueprint property block has invalid property_count in {context}")
    columns = row.get("columns")
    if not isinstance(columns, dict):
        raise RuntimeError(f"Blueprint property block columns is not an object in {context}")
    if set(columns) != set(COLUMN_FIELDS):
        missing = sorted(set(COLUMN_FIELDS) - set(columns))
        extra_columns = sorted(set(columns) - set(COLUMN_FIELDS))
        raise RuntimeError(
            f"Blueprint property block columns mismatch in {context}: "
            f"missing={missing} extra={extra_columns}"
        )
    for field in COLUMN_FIELDS:
        _expand_column(columns[field], count, field, context)
    return count, 1


def _flush(handle, node_id: str | None, columns: dict[str, list]) -> None:
    if node_id is None:
        return
    count = len(columns[COLUMN_FIELDS[0]])
    row = {
        "encoding": ENCODING,
        "node_id": node_id,
        "property_count": count,
        "columns": {field: _collapse(columns[field]) for field in COLUMN_FIELDS},
    }
    handle.write(_j(row) + "\n")


def compact(output: Path, *, expected_logical: int | None = None) -> dict[str, int | bool]:
    output = Path(output)
    path = output / PROPERTY_FILE
    if not path.is_file():
        return {"logical_properties": 0, "blocks": 0, "rewritten": False}

    iterator = _rows(path)
    first = next(iterator, None)
    if first is None:
        if expected_logical not in (None, 0):
            raise RuntimeError(
                f"Blueprint property count mismatch before compaction: manifest={expected_logical} actual=0"
            )
        return {"logical_properties": 0, "blocks": 0, "rewritten": False}

    nodes = _node_map(output)
    first_line, first_row = first
    if first_row.get("encoding") == ENCODING:
        logical = blocks = 0
        seen: set[str] = set()
        for line_number, row in (first, *iterator):
            count, block_count = _validate_block(row, f"{path}:{line_number}")
            node_id = row["node_id"]
            if node_id not in nodes:
                raise RuntimeError(
                    f"Blueprint property block references missing node in {path}:{line_number}: {node_id}"
                )
            if node_id in seen:
                raise RuntimeError(
                    f"duplicate Blueprint property block for node in {path}:{line_number}: {node_id}"
                )
            seen.add(node_id)
            logical += count
            blocks += block_count
        if expected_logical is not None and logical != int(expected_logical):
            raise RuntimeError(
                "Blueprint property logical count mismatch: "
                f"manifest={expected_logical} actual={logical}"
            )
        return {"logical_properties": logical, "blocks": blocks, "rewritten": False}

    temp = path.with_name(path.name + ".uatool-blueprint-property-compact.tmp")
    current_node: str | None = None
    columns = {field: [] for field in COLUMN_FIELDS}
    seen_nodes: set[str] = set()
    logical = blocks = 0

    def consume(line_number: int, row: dict, handle) -> None:
        nonlocal current_node, columns, logical, blocks
        if set(row) != LEGACY_FIELDS:
            raise RuntimeError(
                f"legacy Blueprint property fields mismatch in {path}:{line_number}: "
                f"missing={sorted(LEGACY_FIELDS - set(row))} extra={sorted(set(row) - LEGACY_FIELDS)}"
            )
        node_id = row.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise RuntimeError(f"legacy Blueprint property has invalid node_id in {path}:{line_number}")
        authoritative = nodes.get(node_id)
        if authoritative is None:
            raise RuntimeError(
                f"legacy Blueprint property references missing node in {path}:{line_number}: {node_id}"
            )
        actual_meta = tuple(str(row.get(field, "")) for field in AUTHORITATIVE_NODE_FIELDS)
        if actual_meta != authoritative:
            raise RuntimeError(
                f"legacy Blueprint property node metadata differs from authoritative node in {path}:{line_number}"
            )

        if current_node != node_id:
            if current_node is not None:
                _flush(handle, current_node, columns)
                blocks += 1
                seen_nodes.add(current_node)
            if node_id in seen_nodes:
                raise RuntimeError(
                    f"legacy Blueprint property node group is non-contiguous in {path}:{line_number}: {node_id}"
                )
            current_node = node_id
            columns = {field: [] for field in COLUMN_FIELDS}

        for field in COLUMN_FIELDS:
            columns[field].append(row[field])
        logical += 1

    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            consume(first_line, first_row, handle)
            for line_number, row in iterator:
                if row.get("encoding") == ENCODING:
                    raise RuntimeError(
                        f"mixed legacy/compact Blueprint property rows in {path}:{line_number}"
                    )
                consume(line_number, row, handle)
            if current_node is not None:
                _flush(handle, current_node, columns)
                blocks += 1

        if expected_logical is not None and logical != int(expected_logical):
            raise RuntimeError(
                "Blueprint property count differs from structural scanner manifest before compaction: "
                f"manifest={expected_logical} actual={logical}"
            )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

    return {"logical_properties": logical, "blocks": blocks, "rewritten": True}


def iter_logical_properties(output: Path):
    output = Path(output)
    path = output / PROPERTY_FILE
    iterator = _rows(path)
    first = next(iterator, None)
    if first is None:
        return

    nodes = _node_map(output)

    def emit(line_number: int, row: dict):
        count, _ = _validate_block(row, f"{path}:{line_number}")
        node_id = row["node_id"]
        authoritative = nodes.get(node_id)
        if authoritative is None:
            raise RuntimeError(
                f"Blueprint property block references missing node in {path}:{line_number}: {node_id}"
            )
        columns = {
            field: _expand_column(row["columns"][field], count, field, f"{path}:{line_number}")
            for field in COLUMN_FIELDS
        }
        for offset in range(count):
            result = {"node_id": node_id}
            for field, value in zip(AUTHORITATIVE_NODE_FIELDS, authoritative):
                result[field] = value
            for field in COLUMN_FIELDS:
                result[field] = columns[field][offset]
            yield result

    first_line, first_row = first
    compact_mode = first_row.get("encoding") == ENCODING
    if compact_mode:
        seen: set[str] = set()
        for line_number, row in (first, *iterator):
            if row.get("encoding") != ENCODING:
                raise RuntimeError(
                    f"mixed compact/legacy Blueprint property rows in {path}:{line_number}"
                )
            node_id = str(row.get("node_id", ""))
            if node_id in seen:
                raise RuntimeError(
                    f"duplicate Blueprint property block for node in {path}:{line_number}: {node_id}"
                )
            seen.add(node_id)
            yield from emit(line_number, row)
    else:
        yield first_row
        for line_number, row in iterator:
            if row.get("encoding") == ENCODING:
                raise RuntimeError(
                    f"mixed legacy/compact Blueprint property rows in {path}:{line_number}"
                )
            yield row


def normalize_output(output: Path) -> dict[str, int | bool]:
    output = Path(output)
    manifest_path = output / "manifest.json"
    manifest = _read_manifest(manifest_path)
    expected = None
    if manifest is not None:
        counts = manifest.get("counts", {})
        if isinstance(counts, dict) and "blueprint_node_properties" in counts:
            expected = int(counts.get("blueprint_node_properties", 0) or 0)

    stats = compact(output, expected_logical=expected)
    if manifest is None:
        return stats

    counts = manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    counts["blueprint_node_properties"] = int(stats["logical_properties"])
    counts["blueprint_node_property_blocks"] = int(stats["blocks"])
    manifest["counts"] = counts
    manifest["structural_storage_schema_version"] = STORAGE_SCHEMA_VERSION
    manifest["blueprint_node_property_encoding"] = ENCODING
    manifest["blueprint_node_property_logical_count"] = int(stats["logical_properties"])
    manifest["blueprint_node_property_block_count"] = int(stats["blocks"])
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return stats


def manifest_validation_error(output: Path) -> str | None:
    output = Path(output)
    try:
        manifest = _read_manifest(output / "manifest.json")
        if manifest is None:
            return None
        if int(manifest.get("structural_storage_schema_version", 0) or 0) != STORAGE_SCHEMA_VERSION:
            return (
                "unexpected structural storage schema "
                f"{manifest.get('structural_storage_schema_version')!r}"
            )
        if manifest.get("blueprint_node_property_encoding") != ENCODING:
            return (
                "unexpected Blueprint node property encoding "
                f"{manifest.get('blueprint_node_property_encoding')!r}"
            )
        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        expected_logical = int(
            counts.get(
                "blueprint_node_properties",
                manifest.get("blueprint_node_property_logical_count", 0),
            ) or 0
        )
        expected_blocks = int(
            counts.get(
                "blueprint_node_property_blocks",
                manifest.get("blueprint_node_property_block_count", 0),
            ) or 0
        )

        logical = blocks = 0
        seen: set[str] = set()
        nodes = _node_map(output)
        for line_number, row in _rows(output / PROPERTY_FILE) or ():
            if row.get("encoding") != ENCODING:
                return "legacy row-per-property Blueprint node storage remains"
            count, block_count = _validate_block(
                row, f"{output / PROPERTY_FILE}:{line_number}"
            )
            node_id = row["node_id"]
            if node_id not in nodes:
                return f"Blueprint property block references missing node: {node_id}"
            if node_id in seen:
                return f"duplicate Blueprint property block for node: {node_id}"
            seen.add(node_id)
            logical += count
            blocks += block_count

        if logical != expected_logical:
            return (
                f"Blueprint property logical count mismatch: manifest={expected_logical} actual={logical}"
            )
        if blocks != expected_blocks:
            return (
                f"Blueprint property block count mismatch: manifest={expected_blocks} actual={blocks}"
            )
        expanded = sum(1 for _ in iter_logical_properties(output))
        if expanded != logical:
            return f"Blueprint property expansion count mismatch: blocks={logical} expanded={expanded}"
    except RuntimeError as exc:
        return str(exc)
    return None


def install(core_module, runtime_module=None) -> None:
    if getattr(core_module, "_blueprint_property_storage_installed", False):
        return

    original_core_rows = core_module.iter_jsonl

    def core_rows(path):
        path = Path(path)
        if path.name == PROPERTY_FILE:
            yield from iter_logical_properties(path.parent)
            return
        yield from original_core_rows(path)

    core_module.iter_jsonl = core_rows
    core_module._blueprint_property_storage_installed = True

    if runtime_module is not None and not getattr(
        runtime_module, "_blueprint_property_storage_installed", False
    ):
        original_runtime_rows = runtime_module._rows

        def runtime_rows(path):
            path = Path(path)
            if path.name == PROPERTY_FILE:
                yield from iter_logical_properties(path.parent)
                return
            yield from original_runtime_rows(path)

        runtime_module._rows = runtime_rows
        runtime_module._blueprint_property_storage_installed = True
