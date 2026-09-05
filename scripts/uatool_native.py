#!/usr/bin/env python3
"""Validation contract for reflected native C++ schema 1."""
from __future__ import annotations

import json
from pathlib import Path

NATIVE_SCHEMA_VERSION = 1
MANIFEST_FILE = "native_manifest.json"
PASS_NAME = "UnrealAssetToolNative"

JSONL_FILES = (
    "native_modules.jsonl",
    "native_types.jsonl",
    "native_interfaces.jsonl",
    "native_functions.jsonl",
    "native_function_parameters.jsonl",
    "native_properties.jsonl",
    "native_enums.jsonl",
    "native_enum_values.jsonl",
)


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"expected object row in {path}:{line_number}")
            yield value


def read_manifest(output: Path) -> dict | None:
    path = Path(output) / MANIFEST_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def validation_error(output: Path) -> str | None:
    output = Path(output)
    manifest = read_manifest(output)
    if not manifest:
        return f"{MANIFEST_FILE} missing or invalid"

    observed = int(manifest.get("schema_version", 0) or 0)
    if observed != NATIVE_SCHEMA_VERSION:
        return f"expected native schema {NATIVE_SCHEMA_VERSION}, got {observed}"

    if manifest.get("pass") != PASS_NAME:
        return f"unexpected native pass {manifest.get('pass')!r}"

    if not bool(manifest.get("success", False)):
        return f"native scanner failed: {manifest.get('error', '')}"

    files = manifest.get("files", [])
    if not isinstance(files, list) or tuple(files) != JSONL_FILES:
        return f"native manifest file list does not match schema {NATIVE_SCHEMA_VERSION}"

    counts = manifest.get("counts", {})
    if not isinstance(counts, dict):
        return "native manifest counts missing or invalid"

    count_keys = {
        "native_modules.jsonl": "modules",
        "native_types.jsonl": "types",
        "native_interfaces.jsonl": "interfaces",
        "native_functions.jsonl": "functions",
        "native_function_parameters.jsonl": "function_parameters",
        "native_properties.jsonl": "properties",
        "native_enums.jsonl": "enums",
        "native_enum_values.jsonl": "enum_values",
    }

    for filename in JSONL_FILES:
        path = output / filename
        if not path.is_file():
            return f"native stream missing: {filename}"
        actual = sum(1 for _ in _rows(path))
        key = count_keys[filename]
        if int(counts.get(key, -1)) != actual:
            return (
                f"native count mismatch for {key}: "
                f"manifest={counts.get(key)} actual={actual}"
            )

    types = list(_rows(output / "native_types.jsonl"))
    classes = sum(1 for row in types if row.get("kind") == "class")
    structs = sum(1 for row in types if row.get("kind") == "script_struct")
    if int(counts.get("classes", -1)) != classes:
        return (
            f"native count mismatch for classes: "
            f"manifest={counts.get('classes')} actual={classes}"
        )
    if int(counts.get("structs", -1)) != structs:
        return (
            f"native count mismatch for structs: "
            f"manifest={counts.get('structs')} actual={structs}"
        )

    module_names = {
        str(row.get("module_name", "") or "")
        for row in _rows(output / "native_modules.jsonl")
        if row.get("module_name")
    }
    manifest_modules = manifest.get("modules", [])
    if not isinstance(manifest_modules, list):
        return "native manifest modules missing or invalid"
    if sorted(module_names) != sorted(str(value) for value in manifest_modules):
        return "native manifest module list does not match native_modules.jsonl"

    return None
