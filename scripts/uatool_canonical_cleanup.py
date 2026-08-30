#!/usr/bin/env python3
"""Canonical post-scan cleanup for generated/non-authored identifiers.

Cleanup is deliberately byte-preserving for retained JSONL rows. This means old
compatible scans can be repaired with `derive`/`pack` without rerunning Unreal,
and a second cleanup pass is a no-op.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

MATERIAL_PROPERTIES_FILE = "material_properties.jsonl"


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
                try:
                    row = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
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
    """Apply all canonical cleanups and return removal counts."""
    output = Path(output).expanduser().resolve()
    path = output / MATERIAL_PROPERTIES_FILE
    kept, removed = _filter_jsonl_bytes(path, _is_generated_material_expression_guid)
    if path.is_file():
        _update_manifest_material_count(output, kept)
    return {"material_expression_guids": removed}


def validation_error(output) -> str | None:
    output = Path(output).expanduser().resolve()
    path = output / MATERIAL_PROPERTIES_FILE
    if not path.is_file():
        return None
    with path.open("rb") as src:
        for line_number, raw in enumerate(src, 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return f"invalid JSON in {path}:{line_number}: {exc}"
            if _is_generated_material_expression_guid(row):
                return "generated MaterialExpressionGuid remains in canonical material properties"
    return None
