#!/usr/bin/env python3
"""Cheap in-process memoization for deterministic derived validators.

Several composition layers intentionally validate a freshly written derived
stream before proceeding and then validate the same unchanged stream again at a
higher gate. The second parse adds no safety when the exact validated files have
not changed. Cache validator results only against exact file size + mtime_ns
signatures; any rewrite automatically misses the cache.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Iterable

PROFILE_ENV = "UATOOL_PROFILE_DERIVE"


def _profiling() -> bool:
    return os.environ.get(PROFILE_ENV, "0").strip().lower() not in {"", "0", "false", "no", "off"}


def _signature(output: Path, names: Iterable[str]) -> tuple[tuple[str, int, int], ...]:
    result = []
    for name in names:
        path = output / name
        try:
            stat = path.stat()
        except OSError:
            result.append((name, -1, -1))
            continue
        result.append((name, int(stat.st_size), int(stat.st_mtime_ns)))
    return tuple(result)


def _wrap(module, names: tuple[str, ...], label: str) -> None:
    original = module.validation_error
    cached_signature = None
    cached_result = None
    has_cache = False

    def wrapped(output, *args, **kwargs):
        nonlocal cached_signature, cached_result, has_cache
        root = Path(output).expanduser().resolve()
        signature = _signature(root, names)
        if has_cache and signature == cached_signature:
            if _profiling():
                print(f"derive profile: {label} validation cache hit")
            return cached_result
        started = time.perf_counter()
        result = original(output, *args, **kwargs)
        elapsed = time.perf_counter() - started
        cached_signature = signature
        cached_result = result
        has_cache = True
        if _profiling():
            print(f"derive profile: {label} validation {elapsed:.3f}s")
        return result

    module.validation_error = wrapped


def _time_function(module, name: str, label: str) -> None:
    original = getattr(module, name)

    def wrapped(*args, **kwargs):
        if not _profiling():
            return original(*args, **kwargs)
        started = time.perf_counter()
        result = original(*args, **kwargs)
        elapsed = time.perf_counter() - started
        print(f"derive profile: {label} {elapsed:.3f}s")
        return result

    setattr(module, name, wrapped)


def install() -> None:
    import uatool_vfx_stitch as vfx_stitch
    import uatool_project_graph as project_graph
    import uatool_project_graph_finalize as project_graph_finalize
    import uatool_project_neighborhood_compact as neighborhood_compact
    import uatool_project_neighborhoods as neighborhoods

    _wrap(
        vfx_stitch,
        tuple(vfx_stitch.DERIVED_FILES),
        "vfx-derived",
    )
    project_files = tuple(project_graph.DERIVED_FILES)
    _wrap(project_graph, project_files, "project-graph")
    _wrap(project_graph_finalize, project_files, "project-finalize")
    _wrap(neighborhood_compact, project_files, "project-neighborhood")

    _time_function(project_graph, "derive", "project_graph.derive")
    _time_function(project_graph_finalize, "finalize", "project_graph.finalize")
    _time_function(neighborhoods, "rebuild", "project_neighborhoods.rebuild")
    _time_function(vfx_stitch, "derive", "vfx_stitch.derive")
