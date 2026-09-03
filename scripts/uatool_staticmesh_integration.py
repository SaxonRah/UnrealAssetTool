#!/usr/bin/env python3
"""Canonical composition for independent StaticMesh mesh schema 1."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import uatool_staticmesh_schema as mesh_schema
import uatool_staticmesh_graph as mesh_graph
import uatool_staticmesh_accept as mesh_accept
import uatool_staticmesh_capabilities as mesh_capabilities
import uatool_project_graph as project_graph
import uatool_capabilities as capabilities
import uatool_build_perf as build_perf


AUTO_CAPTURE_DIR = "staticmesh-native-capture"


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _clear_canonical_mesh(output: Path) -> None:
    """Remove stale mesh facts when a new normal scan proves there are no meshes."""
    output = Path(output)
    for filename in mesh_schema.RAW_FILES:
        (output / filename).unlink(missing_ok=True)

    top_path = output / "manifest.json"
    top = _read_json(top_path)
    if top is not None:
        for key in ("mesh_schema_version", "mesh_counts", "mesh_files", "mesh_pass"):
            top.pop(key, None)
        passes = top.get("canonical_passes", [])
        if isinstance(passes, list):
            top["canonical_passes"] = [value for value in passes if value != "mesh"]
        temp = top_path.with_name(f".{top_path.name}.tmp")
        temp.write_text(json.dumps(top, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        temp.replace(top_path)

    try:
        import uatool_derived_freshness as freshness
        freshness.invalidate(output)
    except Exception:
        pass


def _promote_pending_capture(output: Path) -> bool:
    """Promote the compact pass emitted inside the normal World commandlet.

    Return True when canonical mesh schema 1 is present after this call. A
    genuine zero-StaticMesh project leaves the optional corpus mesh pass absent
    and clears any stale mesh facts from an earlier scan.
    """
    output = Path(output).expanduser().resolve()
    capture_dir = output / AUTO_CAPTURE_DIR
    capture_manifest_path = capture_dir / "staticmesh_capture_manifest.json"
    if not capture_manifest_path.is_file():
        return (output / mesh_schema.MANIFEST_FILE).is_file()

    capture_manifest = _read_json(capture_manifest_path)
    if capture_manifest is None:
        raise RuntimeError("normal StaticMesh pass wrote an invalid capture manifest")
    if not bool(capture_manifest.get("success", False)):
        raise RuntimeError(f"normal StaticMesh pass failed: {capture_manifest.get('error', '')}")
    counts = capture_manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    if int(counts.get("load_failures", -1)) != 0:
        raise RuntimeError("normal StaticMesh pass reports asset load failures")

    static_mesh_count = int(counts.get("static_meshes", 0) or 0)
    if static_mesh_count == 0:
        _clear_canonical_mesh(output)
        shutil.rmtree(capture_dir)
        print("StaticMesh mesh pass: project contains no StaticMesh assets; stale mesh facts cleared")
        return False

    manifest = mesh_schema.promote_capture(output, capture_dir)
    shutil.rmtree(capture_dir)
    promoted_counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    print(
        "StaticMesh mesh schema 1 promoted: "
        f"meshes={promoted_counts.get('static_meshes', 0)} "
        f"lods={promoted_counts.get('static_mesh_lods', 0)} "
        f"slots={promoted_counts.get('static_mesh_material_slots', 0)} "
        f"shapes={promoted_counts.get('static_mesh_collision_shapes', 0)}"
    )
    return True


def install(runtime_module, core_module) -> None:
    if getattr(runtime_module, "_staticmesh_schema1_integration_installed", False):
        mesh_graph.promote_public_derived_version(project_graph, core_module, runtime_module)
        return

    mesh_graph.install(project_graph, core_module, runtime_module)
    mesh_accept.install(runtime_module)
    mesh_capabilities.install(capabilities)

    # This wrapper is installed after the animation-schema-29 wrapper. Therefore
    # the canonical build-composition call promotes monotonically through 29 and
    # then 30 before uatool.py performs its first derived-freshness check.
    if not getattr(build_perf, "_staticmesh_schema30_composition_installed", False):
        original_build_perf_install = build_perf.install

        def build_perf_install_with_schema30(core) -> None:
            original_build_perf_install(core)
            mesh_graph.install(project_graph, core, runtime_module)
            mesh_graph.promote_public_derived_version(project_graph, core, runtime_module)

        build_perf.install = build_perf_install_with_schema30
        build_perf._staticmesh_schema30_composition_installed = True

    original_create_schema = core_module.create_schema
    original_derive_output = core_module.derive_output
    original_build_database = core_module.build_database
    original_query = core_module.query
    original_scan = core_module.scan

    def create_schema(conn) -> None:
        original_create_schema(conn)
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='static_meshes'"
        ).fetchone()
        if not exists:
            mesh_schema.create_schema(conn)

    def derive_output(output):
        output = Path(output).expanduser().resolve()
        # Normal scans emit a bounded raw StaticMesh capture during the existing
        # World commandlet process. Promote it before derived30 is computed so
        # project graph and freshness signatures see the canonical mesh facts.
        _promote_pending_capture(output)
        error = mesh_schema.validation_error(output, require_present=False)
        if error:
            raise RuntimeError(f"StaticMesh mesh schema 1 incomplete: {error}")
        mesh_graph.promote_public_derived_version(project_graph, core_module, runtime_module)
        return original_derive_output(output)

    def build_database(output):
        output = Path(output).expanduser().resolve()
        # This also makes pack robust if a scan was interrupted after native
        # capture but before derive completed.
        _promote_pending_capture(output)
        error = mesh_schema.validation_error(output, require_present=False)
        if error:
            raise RuntimeError(f"StaticMesh mesh schema 1 incomplete: {error}")
        db = original_build_database(output)
        if (output / mesh_schema.MANIFEST_FILE).is_file():
            conn = sqlite3.connect(db)
            try:
                exists = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='static_meshes'"
                ).fetchone()
                if not exists:
                    mesh_schema.create_schema(conn)
                mesh_schema.load_database(conn, output, runtime_module._rows)
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
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='static_meshes'"
            ).fetchone()
            if exists:
                mesh_schema.query(conn, core_module._print_rows, f"%{args.term}%", args.limit)
        finally:
            conn.close()
        return result

    def scan(args):
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
                "ERROR: StaticMesh normal-scan capture survived derive; canonical mesh promotion did not run",
                file=__import__("sys").stderr,
            )
            return 26
        error = mesh_schema.validation_error(output, require_present=False)
        if error:
            print(f"ERROR: StaticMesh mesh schema 1 incomplete: {error}", file=__import__("sys").stderr)
            return 26
        manifest = _read_json(output / mesh_schema.MANIFEST_FILE)
        if manifest is not None:
            counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
            print(
                "mesh scan complete: "
                f"static_meshes={counts.get('static_meshes', 0)} "
                f"lods={counts.get('static_mesh_lods', 0)} "
                f"material_slots={counts.get('static_mesh_material_slots', 0)} "
                f"sockets={counts.get('static_mesh_sockets', 0)} "
                f"body_setups={counts.get('static_mesh_body_setups', 0)} "
                f"collision_shapes={counts.get('static_mesh_collision_shapes', 0)}"
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
    core_module.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((*core_module.DEFAULT_BUNDLE_FILES, *mesh_schema.RAW_FILES)))
    runtime_module._staticmesh_schema1_integration_installed = True
