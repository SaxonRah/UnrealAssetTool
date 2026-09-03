#!/usr/bin/env python3
"""Canonical composition for independent StaticMesh mesh schema 1."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import uatool_staticmesh_schema as mesh_schema
import uatool_staticmesh_graph as mesh_graph
import uatool_staticmesh_accept as mesh_accept
import uatool_staticmesh_capabilities as mesh_capabilities
import uatool_project_graph as project_graph
import uatool_capabilities as capabilities
import uatool_build_perf as build_perf


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

    def create_schema(conn) -> None:
        original_create_schema(conn)
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='static_meshes'"
        ).fetchone()
        if not exists:
            mesh_schema.create_schema(conn)

    def derive_output(output):
        output = Path(output).expanduser().resolve()
        error = mesh_schema.validation_error(output, require_present=False)
        if error:
            raise RuntimeError(f"StaticMesh mesh schema 1 incomplete: {error}")
        mesh_graph.promote_public_derived_version(project_graph, core_module, runtime_module)
        return original_derive_output(output)

    def build_database(output):
        output = Path(output).expanduser().resolve()
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

    runtime_module.create_schema = create_schema
    runtime_module.derive_output = derive_output
    runtime_module.build_database = build_database
    runtime_module.query = query
    core_module.create_schema = create_schema
    core_module.derive_output = derive_output
    core_module.build_database = build_database
    core_module.query = query
    core_module.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((*core_module.DEFAULT_BUNDLE_FILES, *mesh_schema.RAW_FILES)))
    runtime_module._staticmesh_schema1_integration_installed = True
