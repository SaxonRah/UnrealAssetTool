#!/usr/bin/env python3
"""Cheap project-owned compiler-input freshness for staged native semantics."""
from __future__ import annotations

import hashlib
from pathlib import Path

SCHEMA_VERSION = 1

_NATIVE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx",
    ".h", ".hh", ".hpp", ".hxx",
    ".inl", ".inc",
}
_EXCLUDED_DIRS = {
    ".git", ".svn", ".hg",
    "Binaries", "DerivedDataCache", "Intermediate", "Saved",
    "__pycache__",
}


def _norm(path: Path) -> Path:
    return Path(path).expanduser().resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_excluded(path: Path, project_root: Path) -> bool:
    try:
        relative = path.relative_to(project_root)
    except ValueError:
        return True
    parts = relative.parts
    if any(part in _EXCLUDED_DIRS for part in parts):
        return True
    # The scanner plugin itself is tooling, not target-project native evidence.
    return "UnrealAssetTool" in parts and "Plugins" in parts


def _is_native_or_build_input(path: Path) -> bool:
    name = path.name
    return (
        path.suffix.lower() in _NATIVE_SUFFIXES
        or name.endswith(".Build.cs")
        or name.endswith(".Target.cs")
    )


def discover_inputs(project: Path) -> list[Path]:
    project = _norm(project)
    project_root = project.parent
    if not project.is_file():
        raise RuntimeError(f"project file not found: {project}")

    paths: set[Path] = {project}

    source_root = project_root / "Source"
    if source_root.is_dir():
        for path in source_root.rglob("*"):
            if (
                path.is_file()
                and not _is_excluded(path, project_root)
                and _is_native_or_build_input(path)
            ):
                paths.add(_norm(path))

    plugins_root = project_root / "Plugins"
    plugin_descriptors: list[Path] = []
    if plugins_root.is_dir():
        for path in plugins_root.rglob("*"):
            if not path.is_file() or _is_excluded(path, project_root):
                continue
            relative = path.relative_to(project_root)
            if path.suffix.lower() == ".uplugin":
                plugin_descriptors.append(_norm(path))
                continue
            if "Source" in relative.parts and _is_native_or_build_input(path):
                paths.add(_norm(path))

    # Only plugin descriptors that actually own project source can affect this
    # project-owned native compiler graph.
    for descriptor in plugin_descriptors:
        if (descriptor.parent / "Source").is_dir():
            paths.add(descriptor)

    return sorted(
        paths,
        key=lambda path: path.relative_to(project_root).as_posix().lower(),
    )


def capture_snapshot(project: Path) -> dict:
    project = _norm(project)
    project_root = project.parent
    files = []
    digest = hashlib.sha256()
    for path in discover_inputs(project):
        relative = path.relative_to(project_root).as_posix()
        record = {
            "path": relative,
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
        }
        files.append(record)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(record["sha256"].encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["bytes"]).encode("ascii"))
        digest.update(b"\n")

    return {
        "schema_version": SCHEMA_VERSION,
        "project_file": project.relative_to(project_root).as_posix(),
        "file_count": len(files),
        "aggregate_sha256": digest.hexdigest(),
        "files": files,
    }


def validation_error(snapshot: object) -> str | None:
    if not isinstance(snapshot, dict):
        return "compiler input snapshot missing or invalid"
    if int(snapshot.get("schema_version", 0) or 0) != SCHEMA_VERSION:
        return (
            f"expected compiler input snapshot schema {SCHEMA_VERSION}, got "
            f"{snapshot.get('schema_version')}"
        )
    project_file = snapshot.get("project_file")
    if not isinstance(project_file, str) or not project_file:
        return "compiler input snapshot project_file missing or invalid"
    files = snapshot.get("files")
    if not isinstance(files, list):
        return "compiler input snapshot files missing or invalid"

    seen: set[str] = set()
    for record in files:
        if not isinstance(record, dict):
            return "compiler input snapshot file record invalid"
        path = record.get("path")
        sha256 = record.get("sha256")
        try:
            byte_count = int(record.get("bytes", -1))
        except (TypeError, ValueError):
            return "compiler input snapshot byte count invalid"
        if not isinstance(path, str) or not path or path in seen:
            return "compiler input snapshot path missing, invalid, or duplicated"
        seen.add(path)
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(ch not in "0123456789abcdef" for ch in sha256.lower())
        ):
            return f"compiler input snapshot SHA-256 invalid: {path}"
        if byte_count < 0:
            return f"compiler input snapshot byte count invalid: {path}"

    if int(snapshot.get("file_count", -1) or 0) != len(files):
        return "compiler input snapshot file_count mismatch"
    aggregate = snapshot.get("aggregate_sha256")
    if (
        not isinstance(aggregate, str)
        or len(aggregate) != 64
        or any(ch not in "0123456789abcdef" for ch in aggregate.lower())
    ):
        return "compiler input snapshot aggregate SHA-256 invalid"

    digest = hashlib.sha256()
    for record in files:
        digest.update(str(record["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(int(record["bytes"])).encode("ascii"))
        digest.update(b"\n")
    if digest.hexdigest() != aggregate:
        return "compiler input snapshot aggregate SHA-256 mismatch"
    return None


def compare_snapshot(
    expected: dict,
    project: Path,
    *,
    limit: int = 100,
) -> dict:
    error = validation_error(expected)
    if error:
        return {
            "status": "invalid_snapshot",
            "error": error,
            "difference_count": 0,
            "shown_difference_count": 0,
            "differences": [],
        }

    current = capture_snapshot(project)
    expected_by_path = {
        str(row["path"]): row
        for row in expected["files"]
    }
    current_by_path = {
        str(row["path"]): row
        for row in current["files"]
    }

    differences: list[dict] = []
    total = 0
    for path in sorted(
        set(expected_by_path) | set(current_by_path),
        key=str.lower,
    ):
        before = expected_by_path.get(path)
        after = current_by_path.get(path)
        if before == after:
            continue
        total += 1
        if before is None:
            diff = {"kind": "added", "path": path, "current": after}
        elif after is None:
            diff = {"kind": "removed", "path": path, "expected": before}
        else:
            diff = {
                "kind": "changed",
                "path": path,
                "expected_sha256": before.get("sha256", ""),
                "current_sha256": after.get("sha256", ""),
                "expected_bytes": int(before.get("bytes", 0) or 0),
                "current_bytes": int(after.get("bytes", 0) or 0),
            }
        if len(differences) < limit:
            differences.append(diff)

    return {
        "status": "same" if total == 0 else "different",
        "error": "",
        "expected_file_count": int(expected.get("file_count", 0) or 0),
        "current_file_count": int(current.get("file_count", 0) or 0),
        "expected_aggregate_sha256": str(
            expected.get("aggregate_sha256", "") or ""
        ),
        "current_aggregate_sha256": str(
            current.get("aggregate_sha256", "") or ""
        ),
        "difference_count": total,
        "shown_difference_count": len(differences),
        "differences": differences,
        "current_snapshot": current,
    }
