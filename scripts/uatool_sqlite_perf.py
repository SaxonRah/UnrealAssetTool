#!/usr/bin/env python3
"""Bulk SQLite rebuild acceleration for UnrealAssetTool.

`uat.db` is a disposable cache rebuilt from authoritative JSONL. Maintaining
ordinary secondary indexes row-by-row during bulk insert is unnecessary work.
This module defers only non-unique explicit indexes until all base/specialist rows
are loaded. PRIMARY KEY and UNIQUE indexes remain active throughout, preserving
all correctness constraints used by INSERT/REPLACE/IGNORE semantics.
"""
from __future__ import annotations

from typing import Callable

_ACTIVE = False
_DEFERRED: dict[str, str] = {}


def _quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _defer_nonunique_indexes(conn) -> None:
    for name, sql in list(conn.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name"
    )):
        sql_text = str(sql or "")
        normalized = " ".join(sql_text.split()).upper()
        if not normalized.startswith("CREATE INDEX "):
            # Keep CREATE UNIQUE INDEX constraints live while loading.
            continue
        name = str(name)
        _DEFERRED.setdefault(name, sql_text)
        conn.execute(f"DROP INDEX {_quote_identifier(name)}")


def _wrap_schema(module) -> None:
    original = module.create_schema

    def wrapped(conn) -> None:
        original(conn)
        if _ACTIVE:
            _defer_nonunique_indexes(conn)

    module.create_schema = wrapped


def _restore_indexes(conn) -> None:
    if not _DEFERRED:
        return
    print(f"sqlite bulk pack: creating deferred secondary indexes={len(_DEFERRED)}")
    for name in sorted(_DEFERRED):
        conn.execute(_DEFERRED[name])
    _DEFERRED.clear()


def install(core) -> None:
    """Install around the base packer before the composition root captures it."""
    global _ACTIVE

    import uatool_vfx as vfx
    import uatool_vfx_stitch as vfx_stitch
    import uatool_systems as systems
    import uatool_project_graph as project_graph

    _wrap_schema(core)
    _wrap_schema(vfx)
    _wrap_schema(vfx_stitch)
    _wrap_schema(systems)
    _wrap_schema(project_graph)

    base_build_database = core.build_database

    def bulk_base_build_database(output):
        global _ACTIVE, _DEFERRED
        _DEFERRED = {}
        _ACTIVE = True
        try:
            return base_build_database(output)
        finally:
            _ACTIVE = False

    core.build_database = bulk_base_build_database

    # The composition root loads project_graph last after VFX/systems. Recreate
    # every deferred ordinary index at that point, after all bulk inserts.
    base_project_load = project_graph.load_database

    def project_load_and_index(conn, output, rows) -> None:
        base_project_load(conn, output, rows)
        _restore_indexes(conn)

    project_graph.load_database = project_load_and_index
