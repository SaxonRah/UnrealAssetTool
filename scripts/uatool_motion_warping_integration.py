#!/usr/bin/env python3
"""Canonical composition for Motion Warping animation schema 4."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import uatool_animation as animation
import uatool_animation_mesh_physics as mesh_physics
import uatool_motion_warping_schema as motion_schema
import uatool_motion_warping_graph as motion_graph
import uatool_motion_warping_accept as motion_accept
import uatool_motion_warping_capabilities as motion_capabilities
import uatool_project_graph as project_graph
import uatool_capabilities as capabilities
import uatool_build_perf as build_perf

AUTO_CAPTURE_DIR = "motion-warping-native-capture"


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _base_animation_schema(output: Path) -> int:
    manifest = _read_json(Path(output) / "animation_manifest.json")
    return int(manifest.get("schema_version", 0) or 0) if manifest is not None else 0


def _promote_base_animation_schema(output: Path) -> int:
    """Compose an authored mesh/physics sidecar before Motion Warping promotion.

    The normal World pass writes animation schema 2 plus the schema-3
    SkeletalMesh/PhysicsAsset sidecar in the same editor process. Motion Warping
    is an outer derive wrapper, so it must promote that sidecar before attempting
    to compose public animation schema 4.
    """
    output = Path(output).expanduser().resolve()
    if (output / "animation_mesh_physics_manifest.json").is_file():
        mesh_physics.normalize_output(output)
    return _base_animation_schema(output)


def _promote_pending_capture(output: Path) -> bool:
    output = Path(output).expanduser().resolve()
    capture_dir = output / AUTO_CAPTURE_DIR
    manifest_path = capture_dir / "motion_warping_capture_manifest.json"
    if not manifest_path.is_file():
        return (output / motion_schema.MANIFEST_FILE).is_file()

    capture_manifest = _read_json(manifest_path)
    if capture_manifest is None:
        raise RuntimeError("normal Motion Warping pass wrote an invalid capture manifest")
    if not bool(capture_manifest.get("success", False)):
        raise RuntimeError(f"normal Motion Warping pass failed: {capture_manifest.get('error', '')}")

    counts = capture_manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    if int(counts.get("load_failures", -1)) != 0:
        raise RuntimeError("normal Motion Warping pass reports animation load failures")

    base_animation_schema = _promote_base_animation_schema(output)

    windows = int(counts.get("motion_warping_windows", 0) or 0)
    if windows == 0:
        motion_schema.clear_schema(output, base_animation_schema=base_animation_schema)
        shutil.rmtree(capture_dir)
        print("Motion Warping pass: project contains no authored Motion Warping windows; stale schema cleared")
        return False

    manifest = motion_schema.promote_capture(output, capture_dir)
    shutil.rmtree(capture_dir)
    c = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    print(
        "Motion Warping animation schema 4 promoted: "
        f"windows={c.get('motion_warping_windows',0)} "
        f"modifiers={c.get('motion_warping_modifiers',0)} "
        f"properties={c.get('motion_warping_modifier_properties',0)}"
    )
    return True


def install(runtime_module, core_module) -> None:
    if getattr(runtime_module, "_motion_warping_schema4_integration_installed", False):
        motion_graph.promote_public_derived_version(project_graph, core_module, runtime_module)
        return

    motion_schema.install(animation)
    motion_graph.install(project_graph, core_module, runtime_module)
    motion_accept.install(runtime_module)
    motion_capabilities.install(capabilities)

    if not getattr(build_perf, "_motion_warping_schema32_composition_installed", False):
        original_build_perf_install = build_perf.install

        def build_perf_install_with_schema32(core) -> None:
            original_build_perf_install(core)
            motion_graph.install(project_graph, core, runtime_module)
            motion_graph.promote_public_derived_version(project_graph, core, runtime_module)

        build_perf.install = build_perf_install_with_schema32
        build_perf._motion_warping_schema32_composition_installed = True

    original_create_schema = core_module.create_schema
    original_derive_output = core_module.derive_output
    original_build_database = core_module.build_database
    original_query = core_module.query
    original_scan = core_module.scan

    def ensure_animation_api() -> None:
        motion_schema.install(animation)
        motion_graph.promote_public_derived_version(project_graph, core_module, runtime_module)

    def create_schema(conn) -> None:
        ensure_animation_api()
        original_create_schema(conn)
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='motion_warping_windows'"
        ).fetchone()
        if not exists:
            motion_schema.create_schema(conn)

    def derive_output(output):
        ensure_animation_api()
        output = Path(output).expanduser().resolve()
        _promote_pending_capture(output)
        if (output / motion_schema.MANIFEST_FILE).is_file():
            motion_schema.normalize_output(output)
            error = motion_schema.validation_error(output, require_present=True)
            if error:
                raise RuntimeError(f"Motion Warping animation schema 4 incomplete: {error}")
        motion_graph.promote_public_derived_version(project_graph, core_module, runtime_module)
        return original_derive_output(output)

    def build_database(output):
        ensure_animation_api()
        output = Path(output).expanduser().resolve()
        _promote_pending_capture(output)
        if (output / motion_schema.MANIFEST_FILE).is_file():
            motion_schema.normalize_output(output)
            error = motion_schema.validation_error(output, require_present=True)
            if error:
                raise RuntimeError(f"Motion Warping animation schema 4 incomplete: {error}")
        db = original_build_database(output)
        if (output / motion_schema.MANIFEST_FILE).is_file():
            conn = sqlite3.connect(db)
            try:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='motion_warping_windows'"
                ).fetchone()
                if not exists:
                    motion_schema.create_schema(conn)
                motion_schema.load_database(conn, output, runtime_module._rows)
                conn.commit()
            finally:
                conn.close()
        return db

    def query(args):
        ensure_animation_api()
        result = int(original_query(args))
        root = Path(args.output).expanduser().resolve()
        db = root if root.suffix.lower() == ".db" else root / core_module.DB_NAME
        if not db.is_file():
            return result
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='motion_warping_windows'"
            ).fetchone()
            if exists:
                motion_schema.query(conn, core_module._print_rows, f"%{args.term}%", args.limit)
        finally:
            conn.close()
        return result

    def scan(args):
        ensure_animation_api()
        result = int(original_scan(args))
        if result != 0:
            return result
        output = (
            Path(args.output).expanduser()
            if getattr(args, "output", None)
            else Path(args.project).expanduser().resolve().parent / ".uatool"
        ).resolve()
        if (output / AUTO_CAPTURE_DIR).exists():
            print(
                "ERROR: Motion Warping normal-scan capture survived derive; canonical promotion did not run",
                file=__import__("sys").stderr,
            )
            return 28
        error = motion_schema.validation_error(output, require_present=False)
        if error:
            print(f"ERROR: Motion Warping animation schema 4 incomplete: {error}", file=__import__("sys").stderr)
            return 28
        manifest = _read_json(output / motion_schema.MANIFEST_FILE)
        if manifest is not None:
            c = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
            print(
                "Motion Warping scan complete: "
                f"windows={c.get('motion_warping_windows',0)} "
                f"modifiers={c.get('motion_warping_modifiers',0)} "
                f"properties={c.get('motion_warping_modifier_properties',0)}"
            )
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
    core_module.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((
        *core_module.DEFAULT_BUNDLE_FILES,
        *motion_schema.RAW_FILES,
    )))
    runtime_module._motion_warping_schema4_integration_installed = True
