#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

ENCODING = "pose_transform_blocks_v1"
META_FIELDS = ("pose_asset_path", "pose_index")
VALUE_FIELDS = (
    "translation_x", "translation_y", "translation_z",
    "rotation_x", "rotation_y", "rotation_z", "rotation_w",
    "scale_x", "scale_y", "scale_z",
)
LEGACY_FIELDS = {
    "pose_asset_path", "pose_index", "pose_name", "track_index", "track_name", *VALUE_FIELDS
}
BLOCK_FIELDS = {
    "encoding", "pose_asset_path", "pose_index", "transform_count",
    "track_index_start", "track_indices", "columns",
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
                f"pose-transform block column {field!r} length mismatch in {context}: "
                f"expected {count}, got {len(value)}"
            )
        return value
    return [value] * count


def _pose_map(output: Path) -> dict[tuple[str, int], dict]:
    result = {}
    path = output / "pose_asset_poses.jsonl"
    for line_number, row in _rows(path) or ():
        key = (str(row.get("pose_asset_path", "")), int(row.get("pose_index", -1)))
        if not key[0] or key[1] < 0:
            raise RuntimeError(f"invalid pose identity in {path}:{line_number}")
        if key in result:
            raise RuntimeError(f"duplicate pose identity in {path}:{line_number}: {key}")
        result[key] = row
    return result


def _track_map(output: Path) -> dict[tuple[str, int], str]:
    result = {}
    path = output / "pose_asset_tracks.jsonl"
    for line_number, row in _rows(path) or ():
        key = (str(row.get("pose_asset_path", "")), int(row.get("track_index", -1)))
        name = str(row.get("track_name", ""))
        if not key[0] or key[1] < 0 or not name:
            raise RuntimeError(f"invalid pose track identity in {path}:{line_number}")
        if key in result:
            raise RuntimeError(f"duplicate pose track identity in {path}:{line_number}: {key}")
        result[key] = name
    return result


def _indices(row: dict, count: int, context: str) -> list[int]:
    explicit = row.get("track_indices")
    if explicit is not None:
        if not isinstance(explicit, list) or len(explicit) != count:
            raise RuntimeError(f"pose-transform block track_indices length mismatch in {context}")
        if any(not isinstance(value, int) or value < 0 for value in explicit):
            raise RuntimeError(f"pose-transform block track_indices are invalid in {context}")
        if len(set(explicit)) != len(explicit):
            raise RuntimeError(f"pose-transform block has duplicate track indices in {context}")
        return explicit
    start = row.get("track_index_start", 0)
    if not isinstance(start, int) or start < 0:
        raise RuntimeError(f"pose-transform block track_index_start is invalid in {context}")
    return list(range(start, start + count))


def _validate_block(row: dict, context: str) -> tuple[int, int]:
    extra = set(row) - BLOCK_FIELDS
    if extra:
        raise RuntimeError(f"pose-transform block has unsupported fields {sorted(extra)} in {context}")
    if row.get("encoding") != ENCODING:
        raise RuntimeError(f"unexpected pose-transform encoding in {context}: {row.get('encoding')!r}")
    asset = row.get("pose_asset_path")
    index = row.get("pose_index")
    if not isinstance(asset, str) or not asset or not isinstance(index, int) or index < 0:
        raise RuntimeError(f"pose-transform block has invalid pose identity in {context}")
    count = row.get("transform_count")
    if not isinstance(count, int) or count < 0:
        raise RuntimeError(f"pose-transform block has invalid transform_count in {context}")
    columns = row.get("columns")
    if not isinstance(columns, dict) or set(columns) != set(VALUE_FIELDS):
        missing = sorted(set(VALUE_FIELDS) - set(columns or {})) if isinstance(columns, dict) else list(VALUE_FIELDS)
        extra_columns = sorted(set(columns or {}) - set(VALUE_FIELDS)) if isinstance(columns, dict) else []
        raise RuntimeError(
            f"pose-transform block columns mismatch in {context}: missing={missing} extra={extra_columns}"
        )
    for field in VALUE_FIELDS:
        _expand_column(columns[field], count, field, context)
    _indices(row, count, context)
    return count, 1


def _flush(handle, meta, indices, columns) -> None:
    if meta is None:
        return
    count = len(indices)
    row = {
        "encoding": ENCODING,
        "pose_asset_path": meta[0],
        "pose_index": meta[1],
        "transform_count": count,
        "columns": {field: _collapse(columns[field]) for field in VALUE_FIELDS},
    }
    if indices != list(range(count)):
        if indices == list(range(indices[0], indices[0] + count)):
            row["track_index_start"] = indices[0]
        else:
            row["track_indices"] = indices
    handle.write(_j(row) + "\n")


def compact(output: Path) -> dict[str, int | bool]:
    output = Path(output)
    path = output / "pose_asset_transforms.jsonl"
    if not path.is_file():
        return {"logical_transforms": 0, "blocks": 0, "rewritten": False}
    iterator = _rows(path)
    first = next(iterator, None)
    if first is None:
        return {"logical_transforms": 0, "blocks": 0, "rewritten": False}

    first_line, first_row = first
    poses = _pose_map(output)
    tracks = _track_map(output)
    if first_row.get("encoding") == ENCODING:
        logical = blocks = 0
        for line_number, row in (first, *iterator):
            count, block_count = _validate_block(row, f"{path}:{line_number}")
            pose_key = (row["pose_asset_path"], row["pose_index"])
            pose = poses.get(pose_key)
            if pose is None:
                raise RuntimeError(f"pose-transform block references missing pose in {path}:{line_number}: {pose_key}")
            if int(pose.get("full_transform_count", -1)) != count:
                raise RuntimeError(
                    f"pose-transform block count differs from pose full_transform_count in {path}:{line_number}"
                )
            for track_index in _indices(row, count, f"{path}:{line_number}"):
                if (row["pose_asset_path"], track_index) not in tracks:
                    raise RuntimeError(
                        f"pose-transform block references missing track in {path}:{line_number}: {track_index}"
                    )
            logical += count
            blocks += block_count
        return {"logical_transforms": logical, "blocks": blocks, "rewritten": False}

    temp = path.with_name(path.name + ".uatool-pose-compact.tmp")
    current_meta = None
    indices: list[int] = []
    columns = {field: [] for field in VALUE_FIELDS}
    seen_groups: set[tuple[str, int]] = set()
    logical = blocks = 0

    def consume(line_number: int, row: dict, handle) -> None:
        nonlocal current_meta, indices, columns, logical, blocks
        if set(row) != LEGACY_FIELDS:
            raise RuntimeError(
                f"legacy pose-transform row fields mismatch in {path}:{line_number}: "
                f"missing={sorted(LEGACY_FIELDS - set(row))} extra={sorted(set(row) - LEGACY_FIELDS)}"
            )
        asset = str(row["pose_asset_path"])
        pose_index = row["pose_index"]
        track_index = row["track_index"]
        if not isinstance(pose_index, int) or pose_index < 0 or not isinstance(track_index, int) or track_index < 0:
            raise RuntimeError(f"legacy pose-transform indices are invalid in {path}:{line_number}")
        meta = (asset, pose_index)
        if current_meta != meta:
            if current_meta is not None:
                pose = poses.get(current_meta)
                if pose is None or int(pose.get("full_transform_count", -1)) != len(indices):
                    raise RuntimeError(f"pose-transform group count does not match authoritative pose: {current_meta}")
                _flush(handle, current_meta, indices, columns)
                blocks += 1
                seen_groups.add(current_meta)
            if meta in seen_groups:
                raise RuntimeError(f"legacy pose-transform group is non-contiguous in {path}:{line_number}: {meta}")
            current_meta = meta
            indices = []
            columns = {field: [] for field in VALUE_FIELDS}

        pose = poses.get(meta)
        if pose is None or str(pose.get("pose_name", "")) != str(row["pose_name"]):
            raise RuntimeError(f"legacy pose-transform pose_name is not authoritative in {path}:{line_number}")
        expected_track_name = tracks.get((asset, track_index))
        if expected_track_name is None or expected_track_name != str(row["track_name"]):
            raise RuntimeError(f"legacy pose-transform track_name is not authoritative in {path}:{line_number}")
        if track_index in indices:
            raise RuntimeError(f"duplicate legacy pose-transform track index in {path}:{line_number}")
        indices.append(track_index)
        for field in VALUE_FIELDS:
            columns[field].append(row[field])
        logical += 1

    try:
        with temp.open("w", encoding="utf-8", newline="\n") as handle:
            consume(first_line, first_row, handle)
            for line_number, row in iterator:
                if row.get("encoding") == ENCODING:
                    raise RuntimeError(f"mixed legacy/compact pose-transform rows in {path}:{line_number}")
                consume(line_number, row, handle)
            if current_meta is not None:
                pose = poses.get(current_meta)
                if pose is None or int(pose.get("full_transform_count", -1)) != len(indices):
                    raise RuntimeError(f"pose-transform group count does not match authoritative pose: {current_meta}")
                _flush(handle, current_meta, indices, columns)
                blocks += 1
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return {"logical_transforms": logical, "blocks": blocks, "rewritten": True}


def iter_logical_transforms(output: Path):
    output = Path(output)
    path = output / "pose_asset_transforms.jsonl"
    iterator = _rows(path)
    first = next(iterator, None)
    if first is None:
        return
    poses = _pose_map(output)
    tracks = _track_map(output)

    def emit(line_number: int, row: dict):
        count, _ = _validate_block(row, f"{path}:{line_number}")
        pose_key = (row["pose_asset_path"], row["pose_index"])
        pose = poses.get(pose_key)
        if pose is None:
            raise RuntimeError(f"pose-transform block references missing pose in {path}:{line_number}")
        columns = {
            field: _expand_column(row["columns"][field], count, field, f"{path}:{line_number}")
            for field in VALUE_FIELDS
        }
        indices = _indices(row, count, f"{path}:{line_number}")
        for offset, track_index in enumerate(indices):
            track_name = tracks.get((row["pose_asset_path"], track_index))
            if track_name is None:
                raise RuntimeError(f"pose-transform block references missing track in {path}:{line_number}")
            result = {
                "pose_asset_path": row["pose_asset_path"],
                "pose_index": row["pose_index"],
                "pose_name": str(pose.get("pose_name", "")),
                "track_index": track_index,
                "track_name": track_name,
            }
            for field in VALUE_FIELDS:
                result[field] = columns[field][offset]
            yield result

    first_line, first_row = first
    compact_mode = first_row.get("encoding") == ENCODING
    if compact_mode:
        yield from emit(first_line, first_row)
        for line_number, row in iterator:
            if row.get("encoding") != ENCODING:
                raise RuntimeError(f"mixed compact/legacy pose-transform rows in {path}:{line_number}")
            yield from emit(line_number, row)
    else:
        yield first_row
        for line_number, row in iterator:
            if row.get("encoding") == ENCODING:
                raise RuntimeError(f"mixed legacy/compact pose-transform rows in {path}:{line_number}")
            yield row


def normalize_output(output: Path) -> dict[str, int | bool]:
    output = Path(output)
    stats = compact(output)
    manifest_path = output / "animation_manifest.json"
    manifest = _read_manifest(manifest_path)
    if manifest is None:
        return stats
    counts = manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    counts["pose_asset_transforms"] = int(stats["logical_transforms"])
    counts["pose_asset_transform_blocks"] = int(stats["blocks"])
    manifest["counts"] = counts
    manifest["pose_transform_encoding"] = ENCODING
    manifest["pose_transform_logical_count"] = int(stats["logical_transforms"])
    manifest["pose_transform_block_count"] = int(stats["blocks"])
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
        if manifest.get("pose_transform_encoding") != ENCODING:
            return f"unexpected pose-transform encoding {manifest.get('pose_transform_encoding')!r}"
        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        expected_logical = int(counts.get("pose_asset_transforms", manifest.get("pose_transform_logical_count", 0)) or 0)
        expected_blocks = int(counts.get("pose_asset_transform_blocks", manifest.get("pose_transform_block_count", 0)) or 0)
        actual_logical = actual_blocks = 0
        for line_number, row in _rows(output / "pose_asset_transforms.jsonl") or ():
            if row.get("encoding") != ENCODING:
                return "legacy row-per-transform pose storage remains"
            count, block_count = _validate_block(row, f"{output / 'pose_asset_transforms.jsonl'}:{line_number}")
            actual_logical += count
            actual_blocks += block_count
        if actual_logical != expected_logical:
            return f"pose-transform logical count mismatch: manifest={expected_logical} actual={actual_logical}"
        if actual_blocks != expected_blocks:
            return f"pose-transform block count mismatch: manifest={expected_blocks} actual={actual_blocks}"
        # Re-expansion performs authoritative pose/track reference validation.
        expanded = sum(1 for _ in iter_logical_transforms(output))
        if expanded != actual_logical:
            return f"pose-transform expansion count mismatch: blocks={actual_logical} expanded={expanded}"
    except RuntimeError as exc:
        return str(exc)
    return None


def install(breadth_module) -> None:
    if getattr(breadth_module, "_pose_transform_storage_installed", False):
        return
    original_prepare = breadth_module.prepare_output
    original_load_database = breadth_module.load_database
    original_validation_error = breadth_module.validation_error

    def prepare_output(output) -> None:
        original_prepare(output)
        normalize_output(Path(output))

    def load_database(conn, output, rows) -> None:
        output = Path(output)
        def logical_rows(path):
            path = Path(path)
            if path.name == "pose_asset_transforms.jsonl":
                return iter_logical_transforms(output)
            return rows(path)
        original_load_database(conn, output, logical_rows)

    def breadth_validation_error(output) -> str | None:
        error = original_validation_error(Path(output))
        if error:
            return error
        return manifest_validation_error(Path(output))

    breadth_module.prepare_output = prepare_output
    breadth_module.load_database = load_database
    breadth_module.validation_error = breadth_validation_error
    breadth_module._pose_transform_storage_installed = True
