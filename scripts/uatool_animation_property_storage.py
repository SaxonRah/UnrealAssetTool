#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

ENCODING = "animation_property_blocks_v1"
META_FIELDS = ("asset_path", "owner_path", "owner_kind", "owner_class")
PROPERTY_FIELDS = (
    "declaring_type", "property_name", "property_type", "cpp_type", "value", "truncated",
)
LEGACY_FIELDS = set(META_FIELDS) | set(PROPERTY_FIELDS)
BLOCK_FIELDS = set(META_FIELDS) | {"encoding", "property_count", "columns"}


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
        raise RuntimeError(f"invalid animation manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"animation manifest root is not an object: {path}")
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
                f"animation-property block column {field!r} length mismatch in {context}: "
                f"expected {count}, got {len(value)}"
            )
        return value
    return [value] * count


def _validate_block(row: dict, context: str) -> tuple[int, int]:
    extra = set(row) - BLOCK_FIELDS
    if extra:
        raise RuntimeError(f"animation-property block has unsupported fields {sorted(extra)} in {context}")
    if row.get("encoding") != ENCODING:
        raise RuntimeError(f"unexpected animation-property encoding in {context}: {row.get('encoding')!r}")
    for field in META_FIELDS:
        if field not in row:
            raise RuntimeError(f"animation-property block missing {field!r} in {context}")
    count = row.get("property_count")
    if not isinstance(count, int) or count < 0:
        raise RuntimeError(f"animation-property block has invalid property_count in {context}")
    columns = row.get("columns")
    if not isinstance(columns, dict) or set(columns) != set(PROPERTY_FIELDS):
        missing = sorted(set(PROPERTY_FIELDS) - set(columns or {})) if isinstance(columns, dict) else list(PROPERTY_FIELDS)
        extra_columns = sorted(set(columns or {}) - set(PROPERTY_FIELDS)) if isinstance(columns, dict) else []
        raise RuntimeError(
            f"animation-property block columns mismatch in {context}: missing={missing} extra={extra_columns}"
        )
    for field in PROPERTY_FIELDS:
        _expand_column(columns[field], count, field, context)
    return count, 1


def _flush(handle, meta, columns) -> None:
    if meta is None:
        return
    count = len(columns[PROPERTY_FIELDS[0]])
    row = {
        "encoding": ENCODING,
        "asset_path": meta[0],
        "owner_path": meta[1],
        "owner_kind": meta[2],
        "owner_class": meta[3],
        "property_count": count,
        "columns": {field: _collapse(columns[field]) for field in PROPERTY_FIELDS},
    }
    handle.write(_j(row) + "\n")


def compact(path: Path) -> dict[str, int | bool]:
    path = Path(path)
    if not path.is_file():
        return {"logical_properties": 0, "blocks": 0, "rewritten": False}
    iterator = _rows(path)
    first = next(iterator, None)
    if first is None:
        return {"logical_properties": 0, "blocks": 0, "rewritten": False}

    first_line, first_row = first
    if first_row.get("encoding") == ENCODING:
        logical = blocks = 0
        count, block_count = _validate_block(first_row, f"{path}:{first_line}")
        logical += count
        blocks += block_count
        for line_number, row in iterator:
            count, block_count = _validate_block(row, f"{path}:{line_number}")
            logical += count
            blocks += block_count
        return {"logical_properties": logical, "blocks": blocks, "rewritten": False}

    temp = path.with_name(path.name + ".uatool-animation-property-compact.tmp")
    current_meta = None
    columns = {field: [] for field in PROPERTY_FIELDS}
    seen_groups: set[tuple[str, str, str, str]] = set()
    logical = blocks = 0

    def consume(line_number: int, row: dict, handle) -> None:
        nonlocal current_meta, columns, logical, blocks
        if set(row) != LEGACY_FIELDS:
            raise RuntimeError(
                f"legacy animation-property row fields mismatch in {path}:{line_number}: "
                f"missing={sorted(LEGACY_FIELDS - set(row))} extra={sorted(set(row) - LEGACY_FIELDS)}"
            )
        meta = tuple(str(row[field]) for field in META_FIELDS)
        if current_meta != meta:
            if current_meta is not None:
                _flush(handle, current_meta, columns)
                blocks += 1
                seen_groups.add(current_meta)
            if meta in seen_groups:
                raise RuntimeError(
                    f"legacy animation-property owner group is non-contiguous in {path}:{line_number}: {meta}"
                )
            current_meta = meta
            columns = {field: [] for field in PROPERTY_FIELDS}
        for field in PROPERTY_FIELDS:
            columns[field].append(row[field])
        logical += 1

    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            consume(first_line, first_row, handle)
            for line_number, row in iterator:
                if row.get("encoding") == ENCODING:
                    raise RuntimeError(f"mixed legacy/compact animation-property rows in {path}:{line_number}")
                consume(line_number, row, handle)
            if current_meta is not None:
                _flush(handle, current_meta, columns)
                blocks += 1
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return {"logical_properties": logical, "blocks": blocks, "rewritten": True}


def iter_logical_properties(path: Path):
    path = Path(path)
    iterator = _rows(path)
    first = next(iterator, None)
    if first is None:
        return

    def emit(line_number: int, row: dict):
        count, _ = _validate_block(row, f"{path}:{line_number}")
        columns = {
            field: _expand_column(row["columns"][field], count, field, f"{path}:{line_number}")
            for field in PROPERTY_FIELDS
        }
        for offset in range(count):
            result = {field: row[field] for field in META_FIELDS}
            for field in PROPERTY_FIELDS:
                result[field] = columns[field][offset]
            yield result

    first_line, first_row = first
    compact_mode = first_row.get("encoding") == ENCODING
    if compact_mode:
        yield from emit(first_line, first_row)
        for line_number, row in iterator:
            if row.get("encoding") != ENCODING:
                raise RuntimeError(f"mixed compact/legacy animation-property rows in {path}:{line_number}")
            yield from emit(line_number, row)
    else:
        yield first_row
        for line_number, row in iterator:
            if row.get("encoding") == ENCODING:
                raise RuntimeError(f"mixed legacy/compact animation-property rows in {path}:{line_number}")
            yield row


def normalize_output(output: Path) -> dict[str, int | bool]:
    output = Path(output)
    path = output / "animation_properties.jsonl"
    manifest_path = output / "animation_manifest.json"
    manifest = _read_manifest(manifest_path)
    expected = None
    if manifest is not None:
        counts = manifest.get("counts", {})
        if isinstance(counts, dict) and "animation_properties" in counts:
            expected = int(counts.get("animation_properties", 0) or 0)

    stats = compact(path)
    if expected is not None and expected != int(stats["logical_properties"]):
        raise RuntimeError(
            "animation property count changed during storage normalization: "
            f"manifest={expected} logical={stats['logical_properties']}"
        )
    if manifest is None:
        return stats
    if int(manifest.get("schema_version", 0) or 0) != 2:
        raise RuntimeError(
            f"animation-property storage requires normalized animation schema 2, got {manifest.get('schema_version')!r}"
        )
    counts = manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    counts["animation_properties"] = int(stats["logical_properties"])
    counts["animation_property_blocks"] = int(stats["blocks"])
    manifest["counts"] = counts
    manifest["animation_property_encoding"] = ENCODING
    manifest["animation_property_logical_count"] = int(stats["logical_properties"])
    manifest["animation_property_block_count"] = int(stats["blocks"])
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return stats


def manifest_validation_error(output: Path) -> str | None:
    output = Path(output)
    try:
        manifest = _read_manifest(output / "animation_manifest.json")
        if manifest is None:
            return None
        if int(manifest.get("schema_version", 0) or 0) != 2:
            return f"unexpected normalized animation schema {manifest.get('schema_version')!r}"
        if manifest.get("animation_property_encoding") != ENCODING:
            return f"unexpected animation-property encoding {manifest.get('animation_property_encoding')!r}"
        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        expected_logical = int(
            counts.get("animation_properties", manifest.get("animation_property_logical_count", 0)) or 0
        )
        expected_blocks = int(
            counts.get("animation_property_blocks", manifest.get("animation_property_block_count", 0)) or 0
        )
        actual_logical = actual_blocks = 0
        for line_number, row in _rows(output / "animation_properties.jsonl") or ():
            if row.get("encoding") != ENCODING:
                return "legacy row-per-property animation storage remains"
            count, block_count = _validate_block(row, f"{output / 'animation_properties.jsonl'}:{line_number}")
            actual_logical += count
            actual_blocks += block_count
        if actual_logical != expected_logical:
            return f"animation-property logical count mismatch: manifest={expected_logical} actual={actual_logical}"
        if actual_blocks != expected_blocks:
            return f"animation-property block count mismatch: manifest={expected_blocks} actual={actual_blocks}"
        expanded = sum(1 for _ in iter_logical_properties(output / "animation_properties.jsonl"))
        if expanded != actual_logical:
            return f"animation-property expansion count mismatch: blocks={actual_logical} expanded={expanded}"
    except RuntimeError as exc:
        return str(exc)
    return None


def install(animation_module) -> None:
    if getattr(animation_module, "_animation_property_storage_installed", False):
        return
    original_prepare = animation_module.prepare_output
    original_load_database = animation_module.load_database
    original_validation_error = animation_module.validation_error

    def prepare_output(output, rows) -> None:
        original_prepare(output, rows)
        normalize_output(Path(output))

    def load_database(conn, output, rows) -> None:
        output = Path(output)

        def logical_rows(path):
            path = Path(path)
            if path.name == "animation_properties.jsonl":
                return iter_logical_properties(path)
            return rows(path)

        original_load_database(conn, output, logical_rows)

    def animation_validation_error(output) -> str | None:
        error = original_validation_error(Path(output))
        if error:
            return error
        return manifest_validation_error(Path(output))

    animation_module.prepare_output = prepare_output
    animation_module.load_database = load_database
    animation_module.validation_error = animation_validation_error
    animation_module._animation_property_storage_installed = True
