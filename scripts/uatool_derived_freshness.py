#!/usr/bin/env python3
"""Cheap freshness guard for deterministic derived output.

Derived JSONL and SQLite are disposable caches over canonical scanner facts. The
expensive derived pass should run when canonical inputs or derived Python logic
change, not every time a user asks to inspect, pack, or report an already-current
output.

The stamp deliberately uses file metadata for large canonical/derived JSONL
rather than re-hashing gigabytes of data. Scanner and cleanup rewrites change
size and/or mtime in normal operation. Python that can affect derived output is
content-hashed so a derived-code edit invalidates the stamp even when the schema
number does not change. Pure read-only reporting/capture launchers are excluded
because they cannot alter derived JSONL.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

STAMP_FILE = ".derived_freshness.json"
STAMP_VERSION = 1

NON_DERIVED_SCRIPTS = frozenset({
    "uatool_blueprint_program_report.py",
    "uatool_gas_capture.py",
    "uatool_gas_evidence.py",
    "uatool_mover_report.py",
    "uatool_semantic_quality.py",
    "uatool_semantic_report.py",
    "uatool_staticmesh_evidence.py",
    "uatool_staticmesh_capture.py",
    "uatool_world_geometry_evidence.py",
    "uatool_world_geometry_capture.py",
    "uatool_world_geometry_foliage_native_integration.py",
    "uatool_verify_bundle.py",
    "uatool_zonegraph_mass_evidence.py",
})


def _script_fingerprint(script_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(script_dir.glob("uatool*.py"), key=lambda item: item.name.lower()):
        if path.name in NON_DERIVED_SCRIPTS:
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _declared_derived_files(output: Path) -> set[str]:
    manifest_path = output / "manifest.json"
    if not manifest_path.is_file():
        return set()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    counts = manifest.get("derived_counts", {})
    if not isinstance(counts, dict):
        return set()
    return {f"{name}.jsonl" for name in counts if isinstance(name, str) and name}


def _file_stat(path: Path) -> list[int | str]:
    stat = path.stat()
    return [path.name, int(stat.st_size), int(stat.st_mtime_ns)]


def _canonical_signature(output: Path) -> list[list[int | str]]:
    derived_files = _declared_derived_files(output)
    result: list[list[int | str]] = []
    for path in sorted(output.glob("*.jsonl"), key=lambda item: item.name.lower()):
        if path.name in derived_files:
            continue
        result.append(_file_stat(path))
    for path in sorted(output.glob("*_manifest.json"), key=lambda item: item.name.lower()):
        result.append(_file_stat(path))
    return result


def _derived_signature(output: Path) -> list[list[int | str]]:
    result: list[list[int | str]] = []
    for name in sorted(_declared_derived_files(output), key=str.lower):
        path = output / name
        if not path.is_file():
            return []
        result.append(_file_stat(path))
    return result


def _read_stamp(output: Path) -> dict | None:
    path = output / STAMP_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def is_fresh(output, *, schema_version: int, script_dir: Path) -> bool:
    output = Path(output).expanduser().resolve()
    stamp = _read_stamp(output)
    if not stamp:
        return False
    if int(stamp.get("stamp_version", 0) or 0) != STAMP_VERSION:
        return False
    if int(stamp.get("derived_schema_version", 0) or 0) != int(schema_version):
        return False
    if str(stamp.get("script_fingerprint", "")) != _script_fingerprint(script_dir):
        return False
    if stamp.get("canonical_signature") != _canonical_signature(output):
        return False
    derived_signature = _derived_signature(output)
    if not derived_signature or stamp.get("derived_signature") != derived_signature:
        return False

    manifest_path = output / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return int(manifest.get("derived_schema_version", 0) or 0) == int(schema_version)


def mark_fresh(output, *, schema_version: int, script_dir: Path) -> None:
    output = Path(output).expanduser().resolve()
    payload = {
        "stamp_version": STAMP_VERSION,
        "derived_schema_version": int(schema_version),
        "script_fingerprint": _script_fingerprint(script_dir),
        "canonical_signature": _canonical_signature(output),
        "derived_signature": _derived_signature(output),
    }
    path = output / STAMP_FILE
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temp, path)


def invalidate(output) -> None:
    Path(output).expanduser().resolve().joinpath(STAMP_FILE).unlink(missing_ok=True)
