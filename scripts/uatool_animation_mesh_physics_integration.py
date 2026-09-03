#!/usr/bin/env python3
"""Deferred composition for authored mesh/physics animation schema 3."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import uatool_animation as animation
import uatool_animation_curve_storage as curve_storage
import uatool_animation_property_storage as property_storage
import uatool_animation_mesh_physics as mesh_physics


def _patch_curve_storage_for_schema3() -> None:
    if getattr(curve_storage, "_schema3_compatible", False):
        return
    original_normalize = curve_storage.normalize_output
    original_manifest_validation = curve_storage.manifest_validation_error

    def normalize_output(output: Path):
        output = Path(output)
        manifest = curve_storage._read_manifest(output / "animation_manifest.json")
        if manifest is None or int(manifest.get("schema_version", 0) or 0) != mesh_physics.PUBLIC_ANIMATION_SCHEMA_VERSION:
            return original_normalize(output)
        stats = curve_storage.compact(output / "animation_curve_keys.jsonl")
        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        counts["animation_curve_keys"] = int(stats["logical_keys"])
        counts["animation_curve_key_blocks"] = int(stats["blocks"])
        manifest["counts"] = counts
        manifest["curve_key_encoding"] = curve_storage.ENCODING
        manifest["curve_key_logical_count"] = int(stats["logical_keys"])
        manifest["curve_key_block_count"] = int(stats["blocks"])
        (output / "animation_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        return stats

    def manifest_validation_error(output: Path) -> str | None:
        output = Path(output)
        manifest = curve_storage._read_manifest(output / "animation_manifest.json")
        if manifest is None or int(manifest.get("schema_version", 0) or 0) != mesh_physics.PUBLIC_ANIMATION_SCHEMA_VERSION:
            return original_manifest_validation(output)
        if manifest.get("curve_key_encoding") != curve_storage.ENCODING:
            return f"unexpected animation curve-key encoding {manifest.get('curve_key_encoding')!r}"
        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        expected_logical = int(counts.get("animation_curve_keys", manifest.get("curve_key_logical_count", 0)) or 0)
        expected_blocks = int(counts.get("animation_curve_key_blocks", manifest.get("curve_key_block_count", 0)) or 0)
        return curve_storage.validation_error(
            output / "animation_curve_keys.jsonl",
            expected_logical_keys=expected_logical,
            expected_blocks=expected_blocks)

    curve_storage.normalize_output = normalize_output
    curve_storage.manifest_validation_error = manifest_validation_error
    curve_storage._schema3_compatible = True


def _patch_property_storage_for_schema3() -> None:
    """Keep schema-2 property blocks valid when the public manifest is schema 3."""
    if getattr(property_storage, "_schema3_compatible", False):
        return
    original_normalize = property_storage.normalize_output
    original_manifest_validation = property_storage.manifest_validation_error

    def normalize_output(output: Path):
        output = Path(output)
        manifest_path = output / "animation_manifest.json"
        manifest = property_storage._read_manifest(manifest_path)
        if manifest is None or int(manifest.get("schema_version", 0) or 0) != mesh_physics.PUBLIC_ANIMATION_SCHEMA_VERSION:
            return original_normalize(output)

        path = output / "animation_properties.jsonl"
        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        expected = None
        if "animation_properties" in counts:
            expected = int(counts.get("animation_properties", 0) or 0)

        stats = property_storage.compact(path)
        if expected is not None and expected != int(stats["logical_properties"]):
            raise RuntimeError(
                "animation property count changed during storage normalization: "
                f"manifest={expected} logical={stats['logical_properties']}"
            )

        counts["animation_properties"] = int(stats["logical_properties"])
        counts["animation_property_blocks"] = int(stats["blocks"])
        manifest["counts"] = counts
        manifest["animation_property_encoding"] = property_storage.ENCODING
        manifest["animation_property_logical_count"] = int(stats["logical_properties"])
        manifest["animation_property_block_count"] = int(stats["blocks"])
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        return stats

    def manifest_validation_error(output: Path) -> str | None:
        output = Path(output)
        try:
            manifest = property_storage._read_manifest(output / "animation_manifest.json")
            if manifest is None or int(manifest.get("schema_version", 0) or 0) != mesh_physics.PUBLIC_ANIMATION_SCHEMA_VERSION:
                return original_manifest_validation(output)
            if manifest.get("animation_property_encoding") != property_storage.ENCODING:
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
            path = output / "animation_properties.jsonl"
            for line_number, row in property_storage._rows(path) or ():
                if row.get("encoding") != property_storage.ENCODING:
                    return "legacy row-per-property animation storage remains"
                count, block_count = property_storage._validate_block(row, f"{path}:{line_number}")
                actual_logical += count
                actual_blocks += block_count
            if actual_logical != expected_logical:
                return f"animation-property logical count mismatch: manifest={expected_logical} actual={actual_logical}"
            if actual_blocks != expected_blocks:
                return f"animation-property block count mismatch: manifest={expected_blocks} actual={actual_blocks}"
            expanded = sum(1 for _ in property_storage.iter_logical_properties(path))
            if expanded != actual_logical:
                return f"animation-property expansion count mismatch: blocks={actual_logical} expanded={expanded}"
        except RuntimeError as exc:
            return str(exc)
        return None

    property_storage.normalize_output = normalize_output
    property_storage.manifest_validation_error = manifest_validation_error
    property_storage._schema3_compatible = True


def install(runtime_module, core_module) -> None:
    if getattr(runtime_module, "_mesh_physics_schema3_integration_installed", False):
        return

    original_create_schema = core_module.create_schema
    original_derive_output = core_module.derive_output
    original_build_database = core_module.build_database
    original_query = core_module.query
    original_scan = core_module.scan

    def ensure_animation_api() -> None:
        _patch_curve_storage_for_schema3()
        _patch_property_storage_for_schema3()
        mesh_physics.install(animation)

    def create_schema(conn) -> None:
        ensure_animation_api()
        original_create_schema(conn)
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='skeletal_meshes'"
        ).fetchone()
        if not exists:
            mesh_physics.create_schema(conn)

    def derive_output(output):
        ensure_animation_api()
        output = Path(output).expanduser().resolve()
        # uatool.py applies canonical storage cleanup before delegating here.
        # At that point curve/property storage is schema 2 and the authored
        # sidecar can be composed deterministically into public animation schema 3.
        mesh_physics.normalize_output(output)
        return original_derive_output(output)

    def build_database(output):
        ensure_animation_api()
        output = Path(output).expanduser().resolve()
        mesh_physics.normalize_output(output)
        db = original_build_database(output)
        if (output / "animation_mesh_physics_manifest.json").is_file():
            conn = sqlite3.connect(db)
            try:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='skeletal_meshes'"
                ).fetchone()
                if not exists:
                    mesh_physics.create_schema(conn)
                mesh_physics.load_database(conn, output, runtime_module._rows)
                conn.commit()
            finally:
                conn.close()
        return db

    def query(args):
        result = int(original_query(args))
        root = Path(args.output).expanduser().resolve()
        db = root if root.suffix.lower() == ".db" else root / core_module.DB_NAME
        if not db.is_file():
            return result
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='skeletal_meshes'"
            ).fetchone()
            if exists:
                mesh_physics.query(conn, core_module._print_rows, f"%{args.term}%", args.limit)
        finally:
            conn.close()
        return result

    def scan(args):
        ensure_animation_api()
        result = int(original_scan(args))
        if result != 0:
            return result
        output = (Path(args.output).expanduser() if args.output else Path(args.project).expanduser().resolve().parent / ".uatool").resolve()
        error = mesh_physics.validation_error(output, require_present=True)
        if error:
            print(f"ERROR: SkeletalMesh/PhysicsAsset animation scan incomplete: {error}")
            return 25
        # The normal scan path must advertise the composed public schema rather
        # than merely leaving a valid sidecar beside a schema-2 manifest.
        mesh_physics.normalize_output(output)
        return 0

    runtime_module.create_schema = create_schema
    runtime_module.derive_output = derive_output
    runtime_module.build_database = build_database
    runtime_module.query = query
    runtime_module.scan = scan
    core_module.create_schema = create_schema
    core_module.derive_output = derive_output
    core_module.build_database = build_database
    core_module.query = query
    core_module.scan = scan
    core_module.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((*core_module.DEFAULT_BUNDLE_FILES, *mesh_physics.RAW_FILES)))
    runtime_module._mesh_physics_schema3_integration_installed = True
