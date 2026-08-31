#!/usr/bin/env python3
"""Canonical post-scan cleanup for redundant/generated canonical payloads.

Cleanups are lossless with respect to authoritative canonical facts. Retained
JSONL rows stay byte-preserved whenever possible; rows are rewritten only when
removing a redundant compatibility payload. Old compatible scans can therefore
be repaired with `derive`/`pack` without rerunning Unreal, and a second cleanup
pass is a no-op.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import uatool_animation as animation
import uatool_animation_breadth as animation_breadth
import uatool_animation_curve_storage as animation_curve_storage
import uatool_animation_property_storage as animation_property_storage
import uatool_pose_transform_storage as pose_transform_storage

# The canonical launcher imports uatool_runtime (and therefore the animation
# modules) before this cleanup module. Install compact storage behind the
# existing APIs so callers keep one canonical launcher and one logical row model.
animation_curve_storage.install(animation)
animation_property_storage.install(animation)
pose_transform_storage.install(animation_breadth)

MATERIAL_PROPERTIES_FILE = "material_properties.jsonl"
BLUEPRINT_NODES_FILE = "blueprint_nodes.jsonl"
BLUEPRINT_PINS_FILE = "blueprint_pins.jsonl"


def _decode_json_row(path: Path, line_number: int, raw: bytes) -> dict:
    try:
        row = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
    if not isinstance(row, dict):
        raise RuntimeError(f"expected JSON object in {path}:{line_number}")
    return row


def _is_generated_material_expression_guid(row: dict) -> bool:
    return (
        str(row.get("owner_kind", "")) == "expression"
        and str(row.get("declaring_type", "")) == "/Script/Engine.MaterialExpression"
        and str(row.get("property_name", "")) == "MaterialExpressionGuid"
    )


def _filter_jsonl_bytes(path: Path, predicate) -> tuple[int, int]:
    if not path.is_file():
        return 0, 0

    temp = path.with_name(path.name + ".uatool-cleanup.tmp")
    kept = 0
    removed = 0
    try:
        with path.open("rb") as src, temp.open("wb") as dst:
            for line_number, raw in enumerate(src, 1):
                if not raw.strip():
                    dst.write(raw)
                    continue
                row = _decode_json_row(path, line_number, raw)
                if predicate(row):
                    removed += 1
                    continue
                dst.write(raw)
                kept += 1
        if removed:
            os.replace(temp, path)
        else:
            temp.unlink(missing_ok=True)
    finally:
        temp.unlink(missing_ok=True)
    return kept, removed


def _normalized_blueprint_pin_ids(path: Path) -> set[str] | None:
    if not path.is_file():
        return None
    result: set[str] = set()
    with path.open("rb") as src:
        for line_number, raw in enumerate(src, 1):
            if not raw.strip():
                continue
            row = _decode_json_row(path, line_number, raw)
            pin_id = str(row.get("pin_id", ""))
            if not pin_id:
                raise RuntimeError(f"blueprint pin missing pin_id in {path}:{line_number}")
            if pin_id in result:
                raise RuntimeError(f"duplicate blueprint pin_id in {path}:{line_number}: {pin_id}")
            result.add(pin_id)
    return result


def _strip_redundant_inline_blueprint_pins(output: Path) -> tuple[int, int]:
    nodes_path = output / BLUEPRINT_NODES_FILE
    pin_ids = _normalized_blueprint_pin_ids(output / BLUEPRINT_PINS_FILE)
    if not nodes_path.is_file() or pin_ids is None:
        return 0, 0

    temp = nodes_path.with_name(nodes_path.name + ".uatool-cleanup.tmp")
    rewritten_nodes = 0
    removed_pins = 0
    try:
        with nodes_path.open("rb") as src, temp.open("wb") as dst:
            for line_number, raw in enumerate(src, 1):
                if not raw.strip():
                    dst.write(raw)
                    continue
                row = _decode_json_row(nodes_path, line_number, raw)
                if "pins" not in row:
                    dst.write(raw)
                    continue

                inline = row.get("pins")
                if not isinstance(inline, list):
                    raise RuntimeError(
                        f"blueprint node pins is not an array in {nodes_path}:{line_number}"
                    )

                for pin_index, pin in enumerate(inline):
                    if not isinstance(pin, dict):
                        raise RuntimeError(
                            "blueprint node inline pin is not an object in "
                            f"{nodes_path}:{line_number} index={pin_index}"
                        )
                    pin_id = str(pin.get("pin_id", ""))
                    if not pin_id or pin_id not in pin_ids:
                        raise RuntimeError(
                            "cannot remove inline blueprint pins because normalized "
                            f"pin {pin_id!r} is missing for {nodes_path}:{line_number}"
                        )

                removed_pins += len(inline)
                rewritten_nodes += 1
                del row["pins"]
                dst.write(
                    (
                        json.dumps(row, ensure_ascii=False, separators=(",", ":"))
                        + "\n"
                    ).encode("utf-8")
                )

        if rewritten_nodes:
            os.replace(temp, nodes_path)
        else:
            temp.unlink(missing_ok=True)
    finally:
        temp.unlink(missing_ok=True)
    return rewritten_nodes, removed_pins


def _validate_legacy_pose_transform_count(output: Path) -> None:
    """Gate pose compaction against the untouched breadth-pass row count."""
    path = output / "pose_asset_transforms.jsonl"
    if not path.is_file():
        return
    first_row = None
    actual = 0
    with path.open("rb") as src:
        for line_number, raw in enumerate(src, 1):
            if not raw.strip():
                continue
            row = _decode_json_row(path, line_number, raw)
            if first_row is None:
                first_row = row
                if row.get("encoding") == pose_transform_storage.ENCODING:
                    return
            actual += 1
    breadth_path = output / "animation_breadth_manifest.json"
    if not breadth_path.is_file():
        return
    try:
        breadth = json.loads(breadth_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid animation_breadth_manifest.json before pose compaction: {exc}") from exc
    counts = breadth.get("counts", {}) if isinstance(breadth, dict) else {}
    if isinstance(counts, dict) and "pose_asset_transforms" in counts:
        expected = int(counts.get("pose_asset_transforms", 0) or 0)
        if expected != actual:
            raise RuntimeError(
                "pose transform count differs from breadth scanner manifest before compaction: "
                f"manifest={expected} actual={actual}"
            )


def _update_manifest_material_count(output: Path, count: int) -> None:
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid manifest.json while applying canonical cleanup: {exc}") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("manifest.json root is not an object")
    counts = manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    counts["material_properties"] = count
    manifest["counts"] = counts
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def apply(output) -> dict[str, int]:
    """Apply all canonical cleanups and return removal/rewrite counts."""
    output = Path(output).expanduser().resolve()

    curve_stats = animation_curve_storage.normalize_output(output)
    if curve_stats.get("rewritten", False):
        print(
            "canonical cleanup: compacted animation curve keys="
            f"{curve_stats.get('logical_keys', 0)} into blocks={curve_stats.get('blocks', 0)}"
        )

    property_stats = animation_property_storage.normalize_output(output)
    if property_stats.get("rewritten", False):
        print(
            "canonical cleanup: compacted animation properties="
            f"{property_stats.get('logical_properties', 0)} into blocks={property_stats.get('blocks', 0)}"
        )

    _validate_legacy_pose_transform_count(output)
    pose_stats = pose_transform_storage.normalize_output(output)
    if pose_stats.get("rewritten", False):
        print(
            "canonical cleanup: compacted pose transforms="
            f"{pose_stats.get('logical_transforms', 0)} into blocks={pose_stats.get('blocks', 0)}"
        )

    material_path = output / MATERIAL_PROPERTIES_FILE
    kept, removed_guids = _filter_jsonl_bytes(
        material_path, _is_generated_material_expression_guid
    )
    if material_path.is_file():
        _update_manifest_material_count(output, kept)

    rewritten_nodes, removed_inline_pins = _strip_redundant_inline_blueprint_pins(output)
    return {
        "material_expression_guids": removed_guids,
        "blueprint_nodes_rewritten": rewritten_nodes,
        "inline_blueprint_pins": removed_inline_pins,
        "animation_curve_keys": int(curve_stats.get("logical_keys", 0)),
        "animation_curve_key_blocks": int(curve_stats.get("blocks", 0)),
        "animation_curve_keys_compacted": int(bool(curve_stats.get("rewritten", False))),
        "animation_properties": int(property_stats.get("logical_properties", 0)),
        "animation_property_blocks": int(property_stats.get("blocks", 0)),
        "animation_properties_compacted": int(bool(property_stats.get("rewritten", False))),
        "pose_asset_transforms": int(pose_stats.get("logical_transforms", 0)),
        "pose_asset_transform_blocks": int(pose_stats.get("blocks", 0)),
        "pose_asset_transforms_compacted": int(bool(pose_stats.get("rewritten", False))),
    }


def validation_error(output) -> str | None:
    output = Path(output).expanduser().resolve()

    curve_error = animation_curve_storage.manifest_validation_error(output)
    if curve_error:
        return curve_error

    property_error = animation_property_storage.manifest_validation_error(output)
    if property_error:
        return property_error

    pose_error = pose_transform_storage.manifest_validation_error(output)
    if pose_error:
        return pose_error

    material_path = output / MATERIAL_PROPERTIES_FILE
    if material_path.is_file():
        with material_path.open("rb") as src:
            for line_number, raw in enumerate(src, 1):
                if not raw.strip():
                    continue
                try:
                    row = _decode_json_row(material_path, line_number, raw)
                except RuntimeError as exc:
                    return str(exc)
                if _is_generated_material_expression_guid(row):
                    return "generated MaterialExpressionGuid remains in canonical material properties"

    pins_path = output / BLUEPRINT_PINS_FILE
    nodes_path = output / BLUEPRINT_NODES_FILE
    if pins_path.is_file() and nodes_path.is_file():
        try:
            _normalized_blueprint_pin_ids(pins_path)
        except RuntimeError as exc:
            return str(exc)
        with nodes_path.open("rb") as src:
            for line_number, raw in enumerate(src, 1):
                if not raw.strip():
                    continue
                try:
                    row = _decode_json_row(nodes_path, line_number, raw)
                except RuntimeError as exc:
                    return str(exc)
                if "pins" in row:
                    return (
                        "redundant inline blueprint pins remain while "
                        f"{BLUEPRINT_PINS_FILE} is authoritative"
                    )
    return None
