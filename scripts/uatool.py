#!/usr/bin/env python3
"""Canonical UnrealAssetTool CLI composition root."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import uatool_core as core
import uatool_runtime as runtime
import uatool_vfx as vfx

# uatool_runtime installs the structural/world/animation/derived-schema-11
# pipeline into uatool_core. Keep this file as the single public launcher and
# compose independently-versioned scanners here rather than growing another
# monolithic implementation.
_base_create_schema = core.create_schema
_base_derive_output = core.derive_output
_base_build_database = core.build_database
_base_query = core.query
_base_scan = core.scan


def create_schema(conn) -> None:
    _base_create_schema(conn)
    vfx.create_schema(conn)


def derive_output(output):
    output = Path(output).expanduser().resolve()
    counts = dict(_base_derive_output(output))
    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        vfx_manifest = vfx.read_manifest(output)
        if vfx_manifest:
            manifest["vfx_schema_version"] = int(vfx_manifest.get("schema_version", 0) or 0)
            manifest["vfx_counts"] = vfx_manifest.get("counts", {})
            manifest["vfx_files"] = vfx_manifest.get("files", [])
            manifest["vfx_pass"] = vfx_manifest.get("pass", "UnrealAssetToolVFX")
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    return counts


def build_database(output):
    output = Path(output).expanduser().resolve()
    db = _base_build_database(output)
    conn = sqlite3.connect(db)
    try:
        vfx.load_database(conn, output, runtime._rows)
        conn.commit()
    finally:
        conn.close()
    return db


def query(args):
    result = int(_base_query(args))
    root = Path(args.output).expanduser().resolve()
    db = root if root.suffix.lower() == ".db" else root / core.DB_NAME
    if db.is_file():
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            vfx.query(conn, core._print_rows, f"%{args.term}%", args.limit)
        finally:
            conn.close()
    return result


def _vfx_summary(args) -> None:
    output = runtime._output(args)
    manifest = vfx.read_manifest(output) or {}
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts", {}), dict) else {}
    names = (
        "vfx_assets",
        "niagara_systems",
        "niagara_system_emitters",
        "niagara_emitters",
        "niagara_renderers",
        "niagara_simulation_stages",
        "niagara_data_channels",
        "cascade_systems",
        "cascade_emitters",
        "cascade_lods",
        "cascade_modules",
    )
    print("vfx scan complete: " + " ".join(f"{name}={counts.get(name, 0)}" for name in names))
    print(f"vfx schema: {manifest.get('schema_version', 0)}")


def scan(args):
    result = int(_base_scan(args))
    if result != 0:
        return result
    error = vfx.validation_error(runtime._output(args))
    if error:
        print(f"ERROR: VFX scan incomplete: {error}", file=sys.stderr)
        return 25
    _vfx_summary(args)
    return 0


core.create_schema = create_schema
core.derive_output = derive_output
core.build_database = build_database
core.query = query
core.scan = scan
core.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((*core.DEFAULT_BUNDLE_FILES, *vfx.RAW_FILES)))


def main():
    return int(runtime.main())


if __name__ == "__main__":
    raise SystemExit(main())
