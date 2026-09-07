#!/usr/bin/env python3
"""Compiler-resolved native C/C++ index capture using clangd-indexer."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import uatool_native_source as native_source

SCHEMA_VERSION = 1
RAW_INDEX = "native_ast_index.yaml"
FILTERED_DB = "native_ast_compile_commands.json"
MANIFEST = "native_ast_manifest.json"
DIAGNOSTICS = "native_ast_diagnostics.jsonl"


def _norm(path: Path) -> Path:
    return path.expanduser().resolve()


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def _owned_compile_entries(compile_db: Path, project: Path) -> tuple[list[dict], set[Path]]:
    modules = native_source.discover_modules(project)
    source_files = native_source.discover_source_files(project, modules)
    owned = {row[0] for row in source_files}
    data = json.loads(compile_db.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        raise RuntimeError(f"compile database root is not an array: {compile_db}")
    result: list[dict] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        source = native_source._resolve_compile_file(entry)
        if source is not None and source in owned:
            result.append(entry)
    return result, owned


def _vs_indexer_from_compiler(compiler: str) -> Path | None:
    if not compiler:
        return None
    path = _norm(Path(compiler))
    parts = list(path.parts)
    lowered = [part.lower() for part in parts]
    try:
        vc = lowered.index("vc")
        tools = lowered.index("tools", vc + 1)
        msvc = lowered.index("msvc", tools + 1)
    except ValueError:
        return None
    root = Path(*parts[:tools + 1])
    candidates = (
        root / "Llvm" / "x64" / "bin" / "clangd-indexer.exe",
        root / "LLVM" / "x64" / "bin" / "clangd-indexer.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return _norm(candidate)
    return None


def discover_clangd_indexer(
    editor: Path,
    compiler_paths: list[str],
    override: Path | None = None,
) -> tuple[Path | None, list[str]]:
    checked: list[str] = []
    if override is not None:
        candidate = _norm(override)
        checked.append(candidate.as_posix())
        return (candidate if candidate.is_file() else None), checked

    found = shutil.which("clangd-indexer.exe") or shutil.which("clangd-indexer")
    if found:
        candidate = _norm(Path(found))
        checked.append(candidate.as_posix())
        return candidate, checked

    for compiler in compiler_paths:
        candidate = _vs_indexer_from_compiler(compiler)
        if candidate is not None:
            checked.append(candidate.as_posix())
            return candidate, checked

    engine_root = native_source._engine_root_from_editor(editor)
    ue_root = engine_root.parent
    candidates = (
        ue_root / "Engine" / "Extras" / "ThirdPartyNotUE" / "SDKs" /
        "HostWin64" / "Win64" / "LLVM" / "bin" / "clangd-indexer.exe",
        ue_root / "Engine" / "Binaries" / "ThirdParty" / "LLVM" /
        "Win64" / "bin" / "clangd-indexer.exe",
    )
    for candidate in candidates:
        checked.append(candidate.as_posix())
        if candidate.is_file():
            return _norm(candidate), checked
    return None, checked


def _document_counts(text: str) -> dict[str, int]:
    return {
        "symbols": len(re.findall(r"(?m)^---\s*!Symbol\s*$", text)),
        "refs": len(re.findall(r"(?m)^---\s*!Refs\s*$", text)),
        "relations": len(re.findall(r"(?m)^---\s*!Relation\s*$", text)),
    }


def capture(
    project: Path,
    editor: Path,
    output: Path,
    *,
    configuration: str = "DebugGame",
    clangd_indexer: Path | None = None,
    generate_compile_database: bool = True,
) -> dict:
    project = _norm(project)
    editor = _norm(editor)
    output = _norm(output)
    output.mkdir(parents=True, exist_ok=True)

    diagnostics: list[dict] = []
    compile_db = native_source._find_existing_compile_database(project, editor)
    if generate_compile_database:
        compile_db, generation = native_source._run_generate_clang_database(
            project, editor, configuration
        )
        diagnostics.append(generation)
    if compile_db is None:
        raise RuntimeError("no compile_commands.json available")

    entries, owned = _owned_compile_entries(compile_db, project)
    if not entries:
        raise RuntimeError("compile database contained no project-owned translation units")

    filtered_db = output / FILTERED_DB
    filtered_db.write_text(
        json.dumps(entries, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    compile_rows, _ = native_source.load_compile_commands(
        compile_db, project, owned
    )
    compiler_paths = sorted({
        str(row.get("compiler", ""))
        for row in compile_rows
        if row.get("compiler")
    })
    indexer, checked = discover_clangd_indexer(
        editor, compiler_paths, clangd_indexer
    )
    if indexer is None:
        diagnostics.append({
            "kind": "clangd_indexer_discovery",
            "success": False,
            "checked": checked,
            "message": "clangd-indexer executable not found",
        })
        _write_jsonl(output / DIAGNOSTICS, diagnostics)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "pass": "UnrealAssetToolNativeAST",
            "success": False,
            "error": "clangd-indexer executable not found",
            "project": project.as_posix(),
            "compile_database": compile_db.as_posix(),
            "filtered_compile_database": filtered_db.as_posix(),
            "project_owned_translation_units": len(entries),
            "compiler_paths": compiler_paths,
            "clangd_indexer": "",
            "checked_indexer_paths": checked,
            "raw_document_counts": {"symbols": 0, "refs": 0, "relations": 0},
        }
        (output / MANIFEST).write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        return manifest

    version = subprocess.run(
        [str(indexer), "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        errors="replace",
        check=False,
    )
    raw_index = output / RAW_INDEX
    command = [
        str(indexer),
        "--format=yaml",
        "--executor=all-TUs",
        str(filtered_db),
    ]
    with raw_index.open("w", encoding="utf-8", newline="\n") as stdout_fh:
        run = subprocess.run(
            command,
            cwd=str(project.parent),
            text=True,
            stdout=stdout_fh,
            stderr=subprocess.PIPE,
            errors="replace",
            check=False,
        )
    raw_text = raw_index.read_text(encoding="utf-8", errors="replace")
    counts = _document_counts(raw_text)
    diagnostics.append({
        "kind": "clangd_indexer",
        "success": run.returncode == 0,
        "exit_code": run.returncode,
        "command": subprocess.list2cmdline(command),
        "stderr_tail": "\n".join((run.stderr or "").splitlines()[-120:]),
        "output_bytes": raw_index.stat().st_size,
        "document_counts": counts,
    })
    _write_jsonl(output / DIAGNOSTICS, diagnostics)

    success = run.returncode == 0 and sum(counts.values()) > 0
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pass": "UnrealAssetToolNativeAST",
        "success": success,
        "error": "" if success else "clangd-indexer failed or emitted no index documents",
        "project": project.as_posix(),
        "configuration": configuration,
        "compile_database": compile_db.as_posix(),
        "filtered_compile_database": filtered_db.as_posix(),
        "project_owned_translation_units": len(entries),
        "compiler_paths": compiler_paths,
        "clangd_indexer": indexer.as_posix(),
        "clangd_indexer_version": version.stdout.strip(),
        "raw_index": raw_index.as_posix(),
        "raw_index_bytes": raw_index.stat().st_size,
        "raw_document_counts": counts,
        "evidence": "clangd_indexer_compiler_resolved",
    }
    (output / MANIFEST).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def print_summary(manifest: dict) -> None:
    counts = manifest.get("raw_document_counts", {})
    print(
        "native AST capture: "
        f"success={bool(manifest.get('success'))} "
        f"tus={manifest.get('project_owned_translation_units', 0)} "
        f"symbols={counts.get('symbols', 0)} "
        f"refs={counts.get('refs', 0)} "
        f"relations={counts.get('relations', 0)}"
    )
    print(f"clangd-indexer: {manifest.get('clangd_indexer') or '<not found>'}")
