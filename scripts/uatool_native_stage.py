#!/usr/bin/env python3
"""Portable staging of validated native semantic evidence inside .uatool."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path

import uatool_native as reflected_native
import uatool_native_ast as native_ast
import uatool_native_index as native_index
import uatool_native_join as native_join

SCHEMA_VERSION = 1
PASS_NAME = "UnrealAssetToolNativeStage"
ROOT_DIR = "native_semantics"
REFLECTED_DIR = "reflected"
COMPILER_DIR = "compiler"
JOINS_DIR = "joins"
MANIFEST = "native_semantics_manifest.json"

REFLECTED_FILES = (
    reflected_native.MANIFEST_FILE,
    *reflected_native.JSONL_FILES,
)
COMPILER_FILES = (
    native_ast.MANIFEST,
    native_ast.DIAGNOSTICS,
    native_ast.SYMBOLS,
    native_ast.PARAMETERS,
    native_ast.CALLS,
)
JOIN_FILES = (
    native_join.MANIFEST,
    *native_join.OUTPUT_FILES,
)

BUNDLE_FILES = (
    f"{ROOT_DIR}/{MANIFEST}",
    *(
        f"{ROOT_DIR}/{REFLECTED_DIR}/{name}"
        for name in REFLECTED_FILES
    ),
    *(
        f"{ROOT_DIR}/{COMPILER_DIR}/{name}"
        for name in COMPILER_FILES
    ),
    *(
        f"{ROOT_DIR}/{JOINS_DIR}/{name}"
        for name in JOIN_FILES
    ),
)


def root(output: Path) -> Path:
    return Path(output).expanduser().resolve() / ROOT_DIR


def roots(output: Path) -> tuple[Path, Path, Path]:
    base = root(output)
    return (
        base / REFLECTED_DIR,
        base / COMPILER_DIR,
        base / JOINS_DIR,
    )


def has_stage(output: Path) -> bool:
    base = root(output)
    return base.is_dir() or (base / MANIFEST).is_file()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_jsonl_rows(path: Path) -> list[str]:
    rows: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"invalid JSON in {path}:{line_number}: {exc}"
                ) from exc
            rows.append(
                json.dumps(
                    value,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            )
    rows.sort()
    return rows


def _semantic_jsonl_digest(path: Path) -> str:
    digest = hashlib.sha256()
    for row in _canonical_jsonl_rows(path):
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _reflected_semantic_records(
    directory: Path,
) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for name in reflected_native.JSONL_FILES:
        path = directory / name
        if not path.is_file():
            raise RuntimeError(
                f"reflected semantic file missing: {path}"
            )
        rows = _canonical_jsonl_rows(path)
        digest = hashlib.sha256()
        for row in rows:
            digest.update(row.encode("utf-8"))
            digest.update(b"\n")
        result[name] = {
            "rows": len(rows),
            "semantic_sha256": digest.hexdigest(),
        }
    return result


def _file_record(path: Path) -> dict:
    return {
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
    }


def _records(directory: Path, names: tuple[str, ...]) -> dict[str, dict]:
    return {
        name: _file_record(directory / name)
        for name in names
    }


def _copy_group(
    source: Path,
    destination: Path,
    names: tuple[str, ...],
) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        source_path = source / name
        if not source_path.is_file():
            raise RuntimeError(f"native stage source file missing: {source_path}")
        shutil.copyfile(source_path, destination / name)


def _counts(data: dict) -> dict[str, int]:
    return {
        "reflected_types": len(data["reflected_types"]),
        "reflected_functions": len(data["reflected_functions"]),
        "reflected_function_parameters": len(
            data["reflected_function_parameters"]
        ),
        "compiler_symbols": len(data["compiler_symbols"]),
        "compiler_parameters": len(data["compiler_parameters"]),
        "compiler_calls": len(data["compiler_calls"]),
        "type_joins": len(data["type_joins"]),
        "function_joins": len(data["function_joins"]),
        "join_diagnostics": len(data["join_diagnostics"]),
    }


def read_manifest(output: Path) -> dict | None:
    path = root(output) / MANIFEST
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _verify_file_records(
    base: Path,
    records: dict,
    *,
    label: str,
) -> str | None:
    if not isinstance(records, dict):
        return f"{label} file records missing or invalid"
    for relative, expected in sorted(records.items()):
        if not isinstance(expected, dict):
            return f"{label} file record invalid: {relative}"
        path = base / relative
        if not path.is_file():
            return f"{label} staged file missing: {relative}"
        observed = _file_record(path)
        if observed != expected:
            return (
                f"{label} staged file hash/size mismatch: {relative}"
            )
    return None


def _current_reflected_error(
    output: Path,
    staged_manifest: dict,
) -> str | None:
    current_manifest = output / reflected_native.MANIFEST_FILE
    if not current_manifest.is_file():
        return (
            "current normal reflected native manifest is missing; "
            "run a normal scan before building/bundling staged native semantics"
        )
    reflected_error = reflected_native.validation_error(output)
    if reflected_error:
        return (
            "current normal reflected native evidence is invalid: "
            f"{reflected_error}"
        )

    staged_reflected = root(output) / REFLECTED_DIR
    try:
        current_semantics = _reflected_semantic_records(output)
        staged_semantics = _reflected_semantic_records(staged_reflected)
    except RuntimeError as exc:
        return str(exc)

    if current_semantics != staged_semantics:
        for name in reflected_native.JSONL_FILES:
            if current_semantics.get(name) != staged_semantics.get(name):
                return (
                    "current reflected native semantics differ from the "
                    f"staged snapshot: {name}; restage native semantics "
                    "from compiler/join evidence captured against the "
                    "current reflection"
                )
        return (
            "current reflected native semantics differ from the staged "
            "snapshot"
        )
    return None


def validation_error(
    output: Path,
    *,
    require_current_reflected: bool = False,
) -> str | None:
    output = Path(output).expanduser().resolve()
    base = root(output)
    manifest = read_manifest(output)
    if not manifest:
        return f"{ROOT_DIR}/{MANIFEST} missing or invalid"
    if int(manifest.get("schema_version", 0) or 0) != SCHEMA_VERSION:
        return (
            f"expected native stage schema {SCHEMA_VERSION}, got "
            f"{manifest.get('schema_version')}"
        )
    if manifest.get("pass") != PASS_NAME:
        return f"unexpected native stage pass {manifest.get('pass')!r}"
    if not bool(manifest.get("success", False)):
        return f"native stage reports failure: {manifest.get('error', '')}"

    groups = manifest.get("files")
    if not isinstance(groups, dict):
        return "native stage files object missing or invalid"
    for label, dirname in (
        ("reflected", REFLECTED_DIR),
        ("compiler", COMPILER_DIR),
        ("joins", JOINS_DIR),
    ):
        error = _verify_file_records(
            base,
            groups.get(label),
            label=label,
        )
        if error:
            return error

    reflected, compiler, joins = roots(output)
    try:
        data = native_index.load_authoritative_inputs(
            reflected,
            compiler,
            joins,
        )
    except Exception as exc:
        return f"staged native evidence invalid: {exc}"

    semantic_records = manifest.get("reflected_semantics")
    if semantic_records is not None:
        if not isinstance(semantic_records, dict):
            return "native stage reflected_semantics invalid"
        try:
            observed_semantics = _reflected_semantic_records(
                base / REFLECTED_DIR
            )
        except RuntimeError as exc:
            return str(exc)
        if observed_semantics != semantic_records:
            return "native stage reflected semantic digest mismatch"

    expected_counts = manifest.get("counts")
    if not isinstance(expected_counts, dict):
        return "native stage counts missing or invalid"
    observed_counts = _counts(data)
    if {
        str(key): int(value)
        for key, value in expected_counts.items()
    } != observed_counts:
        return (
            "native stage row counts mismatch: "
            f"manifest={expected_counts} observed={observed_counts}"
        )
    if require_current_reflected:
        error = _current_reflected_error(output, manifest)
        if error:
            return error
    return None


def _atomic_replace_directory(temp_root: Path, final_root: Path) -> None:
    output = final_root.parent
    backup = output / f".{ROOT_DIR}.backup"
    if backup.exists():
        shutil.rmtree(backup)
    had_previous = final_root.exists()
    if had_previous:
        os.replace(final_root, backup)
    try:
        os.replace(temp_root, final_root)
    except Exception:
        if final_root.exists():
            shutil.rmtree(final_root)
        if had_previous and backup.exists():
            os.replace(backup, final_root)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def stage(
    output: Path,
    reflected: Path,
    compiler: Path,
    joins: Path,
) -> dict:
    output = Path(output).expanduser().resolve()
    reflected = Path(reflected).expanduser().resolve()
    compiler = Path(compiler).expanduser().resolve()
    joins = Path(joins).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    # Validate the exact source triple before copying anything.
    data = native_index.load_authoritative_inputs(
        reflected,
        compiler,
        joins,
    )

    temp_root: Path | None = Path(
        tempfile.mkdtemp(
            prefix=f".{ROOT_DIR}.stage-",
            dir=output,
        )
    )
    try:
        reflected_dest = temp_root / REFLECTED_DIR
        compiler_dest = temp_root / COMPILER_DIR
        joins_dest = temp_root / JOINS_DIR
        _copy_group(reflected, reflected_dest, REFLECTED_FILES)
        _copy_group(compiler, compiler_dest, COMPILER_FILES)
        _copy_group(joins, joins_dest, JOIN_FILES)

        # Revalidate the staged bytes themselves, not just their sources.
        staged_data = native_index.load_authoritative_inputs(
            reflected_dest,
            compiler_dest,
            joins_dest,
        )
        observed_counts = _counts(staged_data)
        source_counts = _counts(data)
        if observed_counts != source_counts:
            raise RuntimeError(
                "staged native row counts differ from validated sources"
            )

        manifest = {
            "schema_version": SCHEMA_VERSION,
            "pass": PASS_NAME,
            "success": True,
            "error": "",
            "sources": {
                "reflected": reflected.as_posix(),
                "compiler": compiler.as_posix(),
                "joins": joins.as_posix(),
            },
            "rulesets": {
                "compiler": str(
                    data["manifests"]["compiler"].get("ruleset", "") or ""
                ),
                "joins": str(
                    data["manifests"]["join"].get("ruleset", "") or ""
                ),
            },
            "counts": observed_counts,
            "reflected_semantics": _reflected_semantic_records(
                reflected_dest
            ),
            "files": {
                "reflected": {
                    f"{REFLECTED_DIR}/{name}": _file_record(
                        reflected_dest / name
                    )
                    for name in REFLECTED_FILES
                },
                "compiler": {
                    f"{COMPILER_DIR}/{name}": _file_record(
                        compiler_dest / name
                    )
                    for name in COMPILER_FILES
                },
                "joins": {
                    f"{JOINS_DIR}/{name}": _file_record(
                        joins_dest / name
                    )
                    for name in JOIN_FILES
                },
            },
        }
        (temp_root / MANIFEST).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

        # Validate the complete staged root, including its own hash manifest.
        # validation_error expects the canonical final path, so perform the
        # equivalent file/hash checks here before the atomic swap.
        for label in ("reflected", "compiler", "joins"):
            error = _verify_file_records(
                temp_root,
                manifest["files"][label],
                label=label,
            )
            if error:
                raise RuntimeError(error)

        _atomic_replace_directory(temp_root, root(output))
        temp_root = None
    finally:
        if temp_root is not None and temp_root.exists():
            shutil.rmtree(temp_root)

    error = validation_error(output)
    if error:
        raise RuntimeError(
            f"native stage failed post-swap validation: {error}"
        )
    return manifest


def load_database(
    conn,
    output: Path,
) -> dict[str, int]:
    if not has_stage(output):
        return {}
    error = validation_error(
        output,
        require_current_reflected=True,
    )
    if error:
        raise RuntimeError(f"native semantic stage incomplete: {error}")
    reflected, compiler, joins = roots(output)
    return native_index.load_database(
        conn,
        reflected,
        compiler,
        joins,
    )
