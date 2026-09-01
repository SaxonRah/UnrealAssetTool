#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

ENCODING = "columnar_blocks_v1"
META_FIELDS = ("asset_path", "curve_name", "curve_type", "component")
KEY_FIELDS = (
    "time", "value", "interp_mode", "tangent_mode", "tangent_weight_mode",
    "arrive_tangent", "leave_tangent", "arrive_tangent_weight", "leave_tangent_weight",
)
NON_FINITE_BASE_FIELDS = {
    "time", "value", "arrive_tangent", "leave_tangent",
    "arrive_tangent_weight", "leave_tangent_weight",
}
LEGACY_ALLOWED_FIELDS = set(META_FIELDS) | {"key_index"} | set(KEY_FIELDS) | {
    field + "_non_finite" for field in NON_FINITE_BASE_FIELDS
}
BLOCK_ALLOWED_FIELDS = set(META_FIELDS) | {
    "encoding", "key_count", "key_index_start", "key_indices", "columns", "non_finite"
}


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


def _collapse(values: list):
    if not values:
        return []
    first = values[0]
    return first if all(value == first for value in values[1:]) else values


def _expand_column(value, key_count: int, field: str, context: str) -> list:
    if isinstance(value, list):
        if len(value) != key_count:
            raise RuntimeError(
                f"curve-key block column {field!r} length mismatch in {context}: "
                f"expected {key_count}, got {len(value)}"
            )
        return value
    return [value] * key_count


def _validate_block(row: dict, context: str) -> tuple[int, int]:
    extra = set(row) - BLOCK_ALLOWED_FIELDS
    if extra:
        raise RuntimeError(f"curve-key block has unsupported fields {sorted(extra)} in {context}")
    if row.get("encoding") != ENCODING:
        raise RuntimeError(f"unexpected curve-key encoding in {context}: {row.get('encoding')!r}")
    for field in META_FIELDS:
        if field not in row:
            raise RuntimeError(f"curve-key block missing {field!r} in {context}")
    key_count = int(row.get("key_count", -1))
    if key_count < 0:
        raise RuntimeError(f"curve-key block has invalid key_count in {context}")
    columns = row.get("columns")
    if not isinstance(columns, dict):
        raise RuntimeError(f"curve-key block columns is not an object in {context}")
    if set(columns) != set(KEY_FIELDS):
        missing = sorted(set(KEY_FIELDS) - set(columns))
        extra_columns = sorted(set(columns) - set(KEY_FIELDS))
        raise RuntimeError(
            f"curve-key block columns mismatch in {context}: missing={missing} extra={extra_columns}"
        )
    for field in KEY_FIELDS:
        _expand_column(columns[field], key_count, field, context)

    key_indices = row.get("key_indices")
    if key_indices is not None:
        if not isinstance(key_indices, list) or len(key_indices) != key_count:
            raise RuntimeError(f"curve-key block key_indices length mismatch in {context}")
        if any(not isinstance(value, int) for value in key_indices):
            raise RuntimeError(f"curve-key block key_indices must be integers in {context}")
    else:
        start = row.get("key_index_start", 0)
        if not isinstance(start, int):
            raise RuntimeError(f"curve-key block key_index_start must be an integer in {context}")

    non_finite = row.get("non_finite", [])
    if not isinstance(non_finite, list):
        raise RuntimeError(f"curve-key block non_finite is not an array in {context}")
    for marker in non_finite:
        if not isinstance(marker, dict):
            raise RuntimeError(f"curve-key block non_finite entry is not an object in {context}")
        if set(marker) != {"offset", "field", "value"}:
            raise RuntimeError(f"curve-key block non_finite entry has invalid fields in {context}")
        offset = marker.get("offset")
        field = marker.get("field")
        if not isinstance(offset, int) or offset < 0 or offset >= key_count:
            raise RuntimeError(f"curve-key block non_finite offset is invalid in {context}")
        if field not in NON_FINITE_BASE_FIELDS:
            raise RuntimeError(f"curve-key block non_finite field is invalid in {context}: {field!r}")
        if not isinstance(marker.get("value"), str):
            raise RuntimeError(f"curve-key block non_finite value is not a string in {context}")
    return key_count, 1


def _flush_block(handle, meta, indices, columns, non_finite) -> None:
    if meta is None:
        return
    key_count = len(indices)
    row = {
        "encoding": ENCODING,
        "asset_path": meta[0],
        "curve_name": meta[1],
        "curve_type": meta[2],
        "component": meta[3],
        "key_count": key_count,
        "columns": {field: _collapse(columns[field]) for field in KEY_FIELDS},
    }
    if indices != list(range(key_count)):
        if indices == list(range(indices[0], indices[0] + key_count)):
            row["key_index_start"] = indices[0]
        else:
            row["key_indices"] = indices
    if non_finite:
        row["non_finite"] = non_finite
    handle.write(_j(row) + "\n")


def compact(path: Path) -> dict[str, int | bool]:
    path = Path(path)
    if not path.is_file():
        return {"logical_keys": 0, "blocks": 0, "rewritten": False}

    iterator = _rows(path)
    first = next(iterator, None)
    if first is None:
        return {"logical_keys": 0, "blocks": 0, "rewritten": False}
    first_line, first_row = first
    if first_row.get("encoding") == ENCODING:
        logical = blocks = 0
        key_count, block_count = _validate_block(first_row, f"{path}:{first_line}")
        logical += key_count
        blocks += block_count
        for line_number, row in iterator:
            key_count, block_count = _validate_block(row, f"{path}:{line_number}")
            logical += key_count
            blocks += block_count
        return {"logical_keys": logical, "blocks": blocks, "rewritten": False}

    temp = path.with_name(path.name + ".uatool-curve-compact.tmp")
    logical = blocks = 0
    current_meta = None
    indices: list[int] = []
    columns = {field: [] for field in KEY_FIELDS}
    non_finite: list[dict] = []
    seen_groups: set[tuple[str, str, str, str]] = set()

    def consume(line_number: int, row: dict, handle) -> None:
        nonlocal current_meta, indices, columns, non_finite, logical, blocks
        extra = set(row) - LEGACY_ALLOWED_FIELDS
        if extra:
            raise RuntimeError(
                f"legacy curve-key row has unsupported fields {sorted(extra)} in {path}:{line_number}"
            )
        missing = [field for field in (*META_FIELDS, "key_index", *KEY_FIELDS) if field not in row]
        if missing:
            raise RuntimeError(f"legacy curve-key row missing fields {missing} in {path}:{line_number}")
        meta = tuple(str(row[field]) for field in META_FIELDS)
        if current_meta != meta:
            if current_meta is not None:
                _flush_block(handle, current_meta, indices, columns, non_finite)
                blocks += 1
                seen_groups.add(current_meta)
            if meta in seen_groups:
                raise RuntimeError(f"legacy curve-key group is non-contiguous in {path}:{line_number}: {meta}")
            current_meta = meta
            indices = []
            columns = {field: [] for field in KEY_FIELDS}
            non_finite = []
        offset = len(indices)
        index = row.get("key_index")
        if not isinstance(index, int):
            raise RuntimeError(f"legacy curve-key key_index is not an integer in {path}:{line_number}")
        indices.append(index)
        for field in KEY_FIELDS:
            columns[field].append(row[field])
        for field in NON_FINITE_BASE_FIELDS:
            marker_name = field + "_non_finite"
            if marker_name in row:
                marker = row[marker_name]
                if not isinstance(marker, str):
                    raise RuntimeError(f"legacy curve-key non-finite marker is not a string in {path}:{line_number}")
                non_finite.append({"offset": offset, "field": field, "value": marker})
        logical += 1

    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            consume(first_line, first_row, handle)
            for line_number, row in iterator:
                if row.get("encoding") == ENCODING:
                    raise RuntimeError(f"mixed legacy/compact curve-key rows in {path}:{line_number}")
                consume(line_number, row, handle)
            if current_meta is not None:
                _flush_block(handle, current_meta, indices, columns, non_finite)
                blocks += 1
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return {"logical_keys": logical, "blocks": blocks, "rewritten": True}


def iter_logical_keys(path: Path):
    path = Path(path)
    iterator = _rows(path)
    first = next(iterator, None)
    if first is None:
        return

    def emit_block(line_number: int, row: dict):
        key_count, _ = _validate_block(row, f"{path}:{line_number}")
        columns = {
            field: _expand_column(
                row["columns"][field], key_count, field, f"{path}:{line_number}"
            )
            for field in KEY_FIELDS
        }
        if row.get("key_indices") is not None:
            indices = row["key_indices"]
        else:
            start = int(row.get("key_index_start", 0))
            indices = list(range(start, start + key_count))
        markers = {}
        for marker in row.get("non_finite", []):
            markers[(int(marker["offset"]), str(marker["field"]))] = str(marker["value"])
        for offset in range(key_count):
            result = {
                "asset_path": row["asset_path"],
                "curve_name": row["curve_name"],
                "curve_type": row["curve_type"],
                "component": row["component"],
                "key_index": indices[offset],
            }
            for field in KEY_FIELDS:
                result[field] = columns[field][offset]
            for field in NON_FINITE_BASE_FIELDS:
                marker = markers.get((offset, field))
                if marker is not None:
                    result[field + "_non_finite"] = marker
            yield result

    first_line, first_row = first
    compact_mode = first_row.get("encoding") == ENCODING
    if compact_mode:
        yield from emit_block(first_line, first_row)
        for line_number, row in iterator:
            if row.get("encoding") != ENCODING:
                raise RuntimeError(f"mixed compact/legacy curve-key rows in {path}:{line_number}")
            yield from emit_block(line_number, row)
    else:
        yield first_row
        for line_number, row in iterator:
            if row.get("encoding") == ENCODING:
                raise RuntimeError(f"mixed legacy/compact curve-key rows in {path}:{line_number}")
            yield row


def validation_error(
    path: Path,
    *,
    expected_logical_keys: int | None = None,
    expected_blocks: int | None = None,
) -> str | None:
    path = Path(path)
    try:
        iterator = _rows(path)
        first = next(iterator, None)
        if first is None:
            logical = blocks = 0
        else:
            line_number, row = first
            if row.get("encoding") != ENCODING:
                return "legacy row-per-key animation curve storage remains"
            logical, blocks = _validate_block(row, f"{path}:{line_number}")
            for line_number, row in iterator:
                key_count, block_count = _validate_block(row, f"{path}:{line_number}")
                logical += key_count
                blocks += block_count
    except RuntimeError as exc:
        return str(exc)
    if expected_logical_keys is not None and logical != int(expected_logical_keys):
        return f"curve-key logical count mismatch: manifest={expected_logical_keys} actual={logical}"
    if expected_blocks is not None and blocks != int(expected_blocks):
        return f"curve-key block count mismatch: manifest={expected_blocks} actual={blocks}"
    return None


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


def normalize_output(output: Path) -> dict[str, int | bool]:
    """Upgrade row-per-key scanner output to public animation schema 2."""
    output = Path(output)
    curve_path = output / "animation_curve_keys.jsonl"
    stats = compact(curve_path)

    manifest_path = output / "animation_manifest.json"
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        return stats
    schema = int(manifest.get("schema_version", 0) or 0)
    if schema not in (1, 2):
        raise RuntimeError(f"cannot normalize unexpected animation schema {schema}")

    deep = _read_manifest(output / "animation_deep_manifest.json")
    if deep is not None:
        deep_counts = deep.get("counts", {})
        if isinstance(deep_counts, dict) and "animation_curve_keys" in deep_counts:
            expected = int(deep_counts.get("animation_curve_keys", 0) or 0)
            if expected != int(stats["logical_keys"]):
                raise RuntimeError(
                    "animation curve-key count changed during storage normalization: "
                    f"deep_manifest={expected} logical={stats['logical_keys']}"
                )

    counts = manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    counts["animation_curve_keys"] = int(stats["logical_keys"])
    counts["animation_curve_key_blocks"] = int(stats["blocks"])
    manifest["counts"] = counts
    manifest["schema_version"] = 2
    manifest["curve_key_encoding"] = ENCODING
    manifest["curve_key_logical_count"] = int(stats["logical_keys"])
    manifest["curve_key_block_count"] = int(stats["blocks"])
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
    except RuntimeError as exc:
        return str(exc)
    if manifest is None:
        return None
    if int(manifest.get("schema_version", 0) or 0) != 2:
        return f"unexpected normalized animation schema {manifest.get('schema_version')!r}"
    if manifest.get("curve_key_encoding") != ENCODING:
        return f"unexpected animation curve-key encoding {manifest.get('curve_key_encoding')!r}"
    counts = manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    expected_logical = int(
        counts.get("animation_curve_keys", manifest.get("curve_key_logical_count", 0)) or 0
    )
    expected_blocks = int(
        counts.get("animation_curve_key_blocks", manifest.get("curve_key_block_count", 0)) or 0
    )
    return validation_error(
        output / "animation_curve_keys.jsonl",
        expected_logical_keys=expected_logical,
        expected_blocks=expected_blocks,
    )


def install(animation_module) -> None:
    """Install schema-2 curve storage behind the existing animation API."""
    if getattr(animation_module, "_curve_storage_schema2_installed", False):
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
            if path.name == "animation_curve_keys.jsonl":
                return iter_logical_keys(path)
            return rows(path)

        original_load_database(conn, output, logical_rows)

    def animation_validation_error(output) -> str | None:
        error = original_validation_error(Path(output))
        if error:
            return error
        return manifest_validation_error(Path(output))

    animation_module.ANIMATION_SCHEMA_VERSION = 2
    animation_module.prepare_output = prepare_output
    animation_module.load_database = load_database
    animation_module.validation_error = animation_validation_error
    animation_module._curve_storage_schema2_installed = True
