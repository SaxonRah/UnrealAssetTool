#!/usr/bin/env python3
from __future__ import annotations

import itertools
import json
import os
from pathlib import Path

STORAGE_SCHEMA_VERSION = 1
ENCODING = "blueprint_pin_blocks_v1"
PIN_FILE = "blueprint_pins.jsonl"
NODE_FILE = "blueprint_nodes.jsonl"

AUTHORITATIVE_NODE_FIELDS = ("blueprint_path", "graph_id", "graph_name")
TYPE_FIELDS = (
    "category",
    "subcategory",
    "container_type",
    "is_reference",
    "is_const",
    "subcategory_object",
)
COLUMN_FIELDS = (
    "pin_id_suffix",
    "name",
    "direction",
    "type_category",
    "type_subcategory",
    "type_container_type",
    "type_is_reference",
    "type_is_const",
    "type_subcategory_object",
    "default_value",
    "default_object",
    "default_text",
    "hidden",
    "not_connectable",
    "linked_count",
)
LEGACY_FIELDS = {
    "pin_id",
    "node_id",
    *AUTHORITATIVE_NODE_FIELDS,
    "pin_index",
    "name",
    "direction",
    "type",
    "default_value",
    "default_object",
    "default_text",
    "hidden",
    "not_connectable",
    "linked_count",
}
BLOCK_REQUIRED_FIELDS = {"encoding", "node_id", "pin_count", "columns"}
BLOCK_OPTIONAL_FIELDS = {"pin_index_start", "pin_indices"}
BLOCK_FIELDS = BLOCK_REQUIRED_FIELDS | BLOCK_OPTIONAL_FIELDS


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
                f"Blueprint pin block column {field!r} length mismatch in {context}: "
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


def _encode_indices(indices: list[int]) -> dict:
    if not indices:
        return {}
    if indices == list(range(len(indices))):
        return {}
    start = indices[0]
    if indices == list(range(start, start + len(indices))):
        return {"pin_index_start": start}
    return {"pin_indices": indices}


def _decode_indices(row: dict, count: int, context: str) -> list[int]:
    has_start = "pin_index_start" in row
    has_indices = "pin_indices" in row
    if has_start and has_indices:
        raise RuntimeError(f"Blueprint pin block has both index encodings in {context}")
    if has_indices:
        value = row.get("pin_indices")
        if not isinstance(value, list) or len(value) != count:
            raise RuntimeError(
                f"Blueprint pin block pin_indices length mismatch in {context}: "
                f"expected {count}, got {len(value) if isinstance(value, list) else 'non-list'}"
            )
        if any(not isinstance(index, int) or index < 0 for index in value):
            raise RuntimeError(f"Blueprint pin block has invalid pin_indices in {context}")
        if len(set(value)) != len(value):
            raise RuntimeError(f"Blueprint pin block has duplicate pin_indices in {context}")
        return value
    start = row.get("pin_index_start", 0)
    if not isinstance(start, int) or start < 0:
        raise RuntimeError(f"Blueprint pin block has invalid pin_index_start in {context}")
    return list(range(start, start + count))


def _validate_block(row: dict, context: str) -> tuple[int, int]:
    missing = BLOCK_REQUIRED_FIELDS - set(row)
    extra = set(row) - BLOCK_FIELDS
    if missing or extra:
        raise RuntimeError(
            f"Blueprint pin block fields mismatch in {context}: "
            f"missing={sorted(missing)} extra={sorted(extra)}"
        )
    if row.get("encoding") != ENCODING:
        raise RuntimeError(f"unexpected Blueprint pin encoding in {context}: {row.get('encoding')!r}")
    node_id = row.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        raise RuntimeError(f"Blueprint pin block has invalid node_id in {context}")
    count = row.get("pin_count")
    if not isinstance(count, int) or count < 0:
        raise RuntimeError(f"Blueprint pin block has invalid pin_count in {context}")
    columns = row.get("columns")
    if not isinstance(columns, dict):
        raise RuntimeError(f"Blueprint pin block columns is not an object in {context}")
    if set(columns) != set(COLUMN_FIELDS):
        missing_columns = sorted(set(COLUMN_FIELDS) - set(columns))
        extra_columns = sorted(set(columns) - set(COLUMN_FIELDS))
        raise RuntimeError(
            f"Blueprint pin block columns mismatch in {context}: "
            f"missing={missing_columns} extra={extra_columns}"
        )
    _decode_indices(row, count, context)
    for field in COLUMN_FIELDS:
        _expand_column(columns[field], count, field, context)
    return count, 1


def _legacy_columns(row: dict, node_id: str, context: str) -> dict:
    pin_id = row.get("pin_id")
    if not isinstance(pin_id, str) or not pin_id:
        raise RuntimeError(f"legacy Blueprint pin has invalid pin_id in {context}")
    prefix = node_id + "::"
    if not pin_id.startswith(prefix) or len(pin_id) <= len(prefix):
        raise RuntimeError(
            f"legacy Blueprint pin_id is not reconstructible from node_id in {context}: {pin_id!r}"
        )
    pin_type = row.get("type")
    if not isinstance(pin_type, dict) or tuple(pin_type.keys()) != TYPE_FIELDS:
        raise RuntimeError(f"legacy Blueprint pin type shape mismatch in {context}")
    return {
        "pin_id_suffix": pin_id[len(prefix):],
        "name": row["name"],
        "direction": row["direction"],
        "type_category": pin_type["category"],
        "type_subcategory": pin_type["subcategory"],
        "type_container_type": pin_type["container_type"],
        "type_is_reference": pin_type["is_reference"],
        "type_is_const": pin_type["is_const"],
        "type_subcategory_object": pin_type["subcategory_object"],
        "default_value": row["default_value"],
        "default_object": row["default_object"],
        "default_text": row["default_text"],
        "hidden": row["hidden"],
        "not_connectable": row["not_connectable"],
        "linked_count": row["linked_count"],
    }


def _flush(handle, node_id: str | None, indices: list[int], columns: dict[str, list]) -> None:
    if node_id is None:
        return
    count = len(indices)
    row = {
        "encoding": ENCODING,
        "node_id": node_id,
        "pin_count": count,
        "columns": {field: _collapse(columns[field]) for field in COLUMN_FIELDS},
    }
    row.update(_encode_indices(indices))
    handle.write(_j(row) + "\n")


def compact(output: Path, *, expected_logical: int | None = None) -> dict[str, int | bool]:
    output = Path(output)
    path = output / PIN_FILE
    if not path.is_file():
        return {"logical_pins": 0, "blocks": 0, "rewritten": False}

    iterator = _rows(path)
    first = next(iterator, None)
    if first is None:
        if expected_logical not in (None, 0):
            raise RuntimeError(
                f"Blueprint pin count mismatch before compaction: manifest={expected_logical} actual=0"
            )
        return {"logical_pins": 0, "blocks": 0, "rewritten": False}

    nodes = _node_map(output)
    first_line, first_row = first
    if first_row.get("encoding") == ENCODING:
        logical = blocks = 0
        seen: set[str] = set()
        for line_number, row in itertools.chain((first,), iterator):
            count, block_count = _validate_block(row, f"{path}:{line_number}")
            node_id = row["node_id"]
            if node_id not in nodes:
                raise RuntimeError(
                    f"Blueprint pin block references missing node in {path}:{line_number}: {node_id}"
                )
            if node_id in seen:
                raise RuntimeError(
                    f"duplicate Blueprint pin block for node in {path}:{line_number}: {node_id}"
                )
            seen.add(node_id)
            logical += count
            blocks += block_count
        if expected_logical is not None and logical != int(expected_logical):
            raise RuntimeError(
                f"Blueprint pin logical count mismatch: manifest={expected_logical} actual={logical}"
            )
        return {"logical_pins": logical, "blocks": blocks, "rewritten": False}

    temp = path.with_name(path.name + ".uatool-blueprint-pin-compact.tmp")
    current_node: str | None = None
    indices: list[int] = []
    columns = {field: [] for field in COLUMN_FIELDS}
    seen_nodes: set[str] = set()
    logical = blocks = 0

    def consume(line_number: int, row: dict, handle) -> None:
        nonlocal current_node, indices, columns, logical, blocks
        context = f"{path}:{line_number}"
        if set(row) != LEGACY_FIELDS:
            raise RuntimeError(
                f"legacy Blueprint pin fields mismatch in {context}: "
                f"missing={sorted(LEGACY_FIELDS - set(row))} extra={sorted(set(row) - LEGACY_FIELDS)}"
            )
        node_id = row.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise RuntimeError(f"legacy Blueprint pin has invalid node_id in {context}")
        authoritative = nodes.get(node_id)
        if authoritative is None:
            raise RuntimeError(f"legacy Blueprint pin references missing node in {context}: {node_id}")
        actual_meta = tuple(str(row.get(field, "")) for field in AUTHORITATIVE_NODE_FIELDS)
        if actual_meta != authoritative:
            raise RuntimeError(
                f"legacy Blueprint pin node metadata differs from authoritative node in {context}"
            )
        pin_index = row.get("pin_index")
        if not isinstance(pin_index, int) or pin_index < 0:
            raise RuntimeError(f"legacy Blueprint pin has invalid pin_index in {context}")

        if current_node != node_id:
            if current_node is not None:
                _flush(handle, current_node, indices, columns)
                blocks += 1
                seen_nodes.add(current_node)
            if node_id in seen_nodes:
                raise RuntimeError(
                    f"legacy Blueprint pin node group is non-contiguous in {context}: {node_id}"
                )
            current_node = node_id
            indices = []
            columns = {field: [] for field in COLUMN_FIELDS}

        if pin_index in indices:
            raise RuntimeError(f"duplicate Blueprint pin_index for node in {context}: {pin_index}")
        values = _legacy_columns(row, node_id, context)
        indices.append(pin_index)
        for field in COLUMN_FIELDS:
            columns[field].append(values[field])
        logical += 1

    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            consume(first_line, first_row, handle)
            for line_number, row in iterator:
                if row.get("encoding") == ENCODING:
                    raise RuntimeError(f"mixed legacy/compact Blueprint pin rows in {path}:{line_number}")
                consume(line_number, row, handle)
            if current_node is not None:
                _flush(handle, current_node, indices, columns)
                blocks += 1

        if expected_logical is not None and logical != int(expected_logical):
            raise RuntimeError(
                "Blueprint pin count differs from structural scanner manifest before compaction: "
                f"manifest={expected_logical} actual={logical}"
            )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

    return {"logical_pins": logical, "blocks": blocks, "rewritten": True}


def iter_logical_pins(output: Path):
    output = Path(output)
    path = output / PIN_FILE
    iterator = _rows(path)
    first = next(iterator, None)
    if first is None:
        return

    nodes = _node_map(output)

    def emit(line_number: int, row: dict):
        context = f"{path}:{line_number}"
        count, _ = _validate_block(row, context)
        node_id = row["node_id"]
        authoritative = nodes.get(node_id)
        if authoritative is None:
            raise RuntimeError(
                f"Blueprint pin block references missing node in {path}:{line_number}: {node_id}"
            )
        indices = _decode_indices(row, count, context)
        columns = {
            field: _expand_column(row["columns"][field], count, field, context)
            for field in COLUMN_FIELDS
        }
        for offset in range(count):
            pin_type = {
                "category": columns["type_category"][offset],
                "subcategory": columns["type_subcategory"][offset],
                "container_type": columns["type_container_type"][offset],
                "is_reference": columns["type_is_reference"][offset],
                "is_const": columns["type_is_const"][offset],
                "subcategory_object": columns["type_subcategory_object"][offset],
            }
            blueprint_path, graph_id, graph_name = authoritative
            yield {
                "pin_id": node_id + "::" + str(columns["pin_id_suffix"][offset]),
                "node_id": node_id,
                "blueprint_path": blueprint_path,
                "graph_id": graph_id,
                "graph_name": graph_name,
                "pin_index": indices[offset],
                "name": columns["name"][offset],
                "direction": columns["direction"][offset],
                "type": pin_type,
                "default_value": columns["default_value"][offset],
                "default_object": columns["default_object"][offset],
                "default_text": columns["default_text"][offset],
                "hidden": columns["hidden"][offset],
                "not_connectable": columns["not_connectable"][offset],
                "linked_count": columns["linked_count"][offset],
            }

    first_line, first_row = first
    compact_mode = first_row.get("encoding") == ENCODING
    if compact_mode:
        seen: set[str] = set()
        for line_number, row in itertools.chain((first,), iterator):
            if row.get("encoding") != ENCODING:
                raise RuntimeError(f"mixed compact/legacy Blueprint pin rows in {path}:{line_number}")
            node_id = str(row.get("node_id", ""))
            if node_id in seen:
                raise RuntimeError(
                    f"duplicate Blueprint pin block for node in {path}:{line_number}: {node_id}"
                )
            seen.add(node_id)
            yield from emit(line_number, row)
    else:
        yield first_row
        for line_number, row in iterator:
            if row.get("encoding") == ENCODING:
                raise RuntimeError(f"mixed legacy/compact Blueprint pin rows in {path}:{line_number}")
            yield row


def normalize_output(output: Path) -> dict[str, int | bool]:
    output = Path(output)
    manifest_path = output / "manifest.json"
    manifest = _read_manifest(manifest_path)
    expected = None
    if manifest is not None:
        counts = manifest.get("counts", {})
        if isinstance(counts, dict) and "blueprint_pins" in counts:
            expected = int(counts.get("blueprint_pins", 0) or 0)

    stats = compact(output, expected_logical=expected)
    if manifest is None:
        return stats

    counts = manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    counts["blueprint_pins"] = int(stats["logical_pins"])
    counts["blueprint_pin_blocks"] = int(stats["blocks"])
    manifest["counts"] = counts
    manifest["blueprint_pin_storage_schema_version"] = STORAGE_SCHEMA_VERSION
    manifest["blueprint_pin_encoding"] = ENCODING
    manifest["blueprint_pin_logical_count"] = int(stats["logical_pins"])
    manifest["blueprint_pin_block_count"] = int(stats["blocks"])
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
        if int(manifest.get("blueprint_pin_storage_schema_version", 0) or 0) != STORAGE_SCHEMA_VERSION:
            return (
                "unexpected Blueprint pin storage schema "
                f"{manifest.get('blueprint_pin_storage_schema_version')!r}"
            )
        if manifest.get("blueprint_pin_encoding") != ENCODING:
            return f"unexpected Blueprint pin encoding {manifest.get('blueprint_pin_encoding')!r}"
        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        expected_logical = int(
            counts.get("blueprint_pins", manifest.get("blueprint_pin_logical_count", 0)) or 0
        )
        expected_blocks = int(
            counts.get("blueprint_pin_blocks", manifest.get("blueprint_pin_block_count", 0)) or 0
        )

        logical = blocks = 0
        seen_nodes: set[str] = set()
        nodes = _node_map(output)
        for line_number, row in _rows(output / PIN_FILE) or ():
            if row.get("encoding") != ENCODING:
                return "legacy row-per-pin Blueprint storage remains"
            count, block_count = _validate_block(row, f"{output / PIN_FILE}:{line_number}")
            node_id = row["node_id"]
            if node_id not in nodes:
                return f"Blueprint pin block references missing node: {node_id}"
            if node_id in seen_nodes:
                return f"duplicate Blueprint pin block for node: {node_id}"
            seen_nodes.add(node_id)
            logical += count
            blocks += block_count

        if logical != expected_logical:
            return f"Blueprint pin logical count mismatch: manifest={expected_logical} actual={logical}"
        if blocks != expected_blocks:
            return f"Blueprint pin block count mismatch: manifest={expected_blocks} actual={blocks}"

        expanded = 0
        seen_pin_ids: set[str] = set()
        for row in iter_logical_pins(output):
            pin_id = str(row.get("pin_id", ""))
            if not pin_id:
                return "expanded Blueprint pin missing pin_id"
            if pin_id in seen_pin_ids:
                return f"duplicate expanded Blueprint pin_id: {pin_id}"
            seen_pin_ids.add(pin_id)
            expanded += 1
        if expanded != logical:
            return f"Blueprint pin expansion count mismatch: blocks={logical} expanded={expanded}"
    except RuntimeError as exc:
        return str(exc)
    return None


def install(core_module, runtime_module=None) -> None:
    if not getattr(core_module, "_blueprint_pin_storage_installed", False):
        original_core_rows = core_module.iter_jsonl

        def core_rows(path):
            path = Path(path)
            if path.name == PIN_FILE:
                yield from iter_logical_pins(path.parent)
                return
            yield from original_core_rows(path)

        core_module.iter_jsonl = core_rows
        core_module._blueprint_pin_storage_installed = True

    if runtime_module is not None and not getattr(
        runtime_module, "_blueprint_pin_storage_installed", False
    ):
        original_runtime_rows = runtime_module._rows

        def runtime_rows(path):
            path = Path(path)
            if path.name == PIN_FILE:
                yield from iter_logical_pins(path.parent)
                return
            yield from original_runtime_rows(path)

        runtime_module._rows = runtime_rows
        runtime_module._blueprint_pin_storage_installed = True
