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



def _vs_llvm_bin_candidates(compiler: str) -> list[Path]:
    if not compiler:
        return []
    path = _norm(Path(compiler))
    parts = list(path.parts)
    lowered = [part.lower() for part in parts]
    try:
        vc = lowered.index("vc")
    except ValueError:
        return []
    vc_root = Path(*parts[: vc + 1])
    return [
        vc_root / "Tools" / "Llvm" / "x64" / "bin",
        vc_root / "Tools" / "Llvm" / "bin",
    ]


def discover_clang_frontend(
    editor: Path,
    compiler_paths: list[str],
    override: Path | None = None,
) -> tuple[Path | None, list[str]]:
    checked: list[str] = []
    if override is not None:
        candidate = _norm(override)
        checked.append(candidate.as_posix())
        return (candidate if candidate.is_file() else None), checked

    for name in ("clang-cl.exe", "clang-cl", "clang.exe", "clang"):
        found = shutil.which(name)
        if found:
            candidate = _norm(Path(found))
            checked.append(candidate.as_posix())
            return candidate, checked

    for compiler in compiler_paths:
        for bindir in _vs_llvm_bin_candidates(compiler):
            for exe in ("clang-cl.exe", "clang.exe"):
                candidate = bindir / exe
                checked.append(candidate.as_posix())
                if candidate.is_file():
                    return _norm(candidate), checked

    engine_root = native_source._engine_root_from_editor(editor)
    ue_root = engine_root.parent
    for bindir in (
        ue_root / "Engine" / "Extras" / "ThirdPartyNotUE" / "SDKs" /
        "HostWin64" / "Win64" / "LLVM" / "bin",
        ue_root / "Engine" / "Binaries" / "ThirdParty" / "LLVM" /
        "Win64" / "bin",
    ):
        for exe in ("clang-cl.exe", "clang.exe"):
            candidate = bindir / exe
            checked.append(candidate.as_posix())
            if candidate.is_file():
                return _norm(candidate), checked
    return None, checked


def _clang_probe_arguments(
    frontend: Path,
    compile_row: dict,
    source: Path,
    language: str,
) -> list[str]:
    is_clang_cl = "clang-cl" in frontend.name.lower()
    args: list[str] = []

    if is_clang_cl:
        args.extend(["/nologo", "/TC" if language == "c" else "/TP"])
        for include in compile_row.get("include_paths", []):
            args.append(f"/I{include}")
        for definition in compile_row.get("definitions", []):
            args.append(f"/D{definition}")
        for forced in compile_row.get("forced_includes", []):
            args.append(f"/FI{forced}")
    else:
        args.extend(["-x", "c" if language == "c" else "c++"])
        for include in compile_row.get("include_paths", []):
            args.extend(["-I", include])
        for definition in compile_row.get("definitions", []):
            args.append(f"-D{definition}")
        for forced in compile_row.get("forced_includes", []):
            args.extend(["-include", forced])

    args.extend([
        "-fsyntax-only",
        "-Xclang",
        "-ast-dump=json",
        str(source),
    ])
    return args


def _write_response_file(path: Path, arguments: list[str]) -> None:
    # clang-cl expands response files with Windows command-line tokenization
    # and preserves physical end-of-line markers. Keep the full argument
    # vector on one logical line so options such as "-Xclang <value>" are
    # never split by an EOL marker.
    text = subprocess.list2cmdline(arguments)
    path.write_text(
        text + ("\n" if text else ""),
        encoding="utf-8",
        newline="\n",
    )


def _select_probe_rows(
    compile_rows: list[dict],
    project_root: Path,
) -> list[tuple[dict, Path, str]]:
    candidates: list[tuple[int, dict, Path, str]] = []
    for row in compile_rows:
        source = project_root / row["source_path"]
        if not source.is_file():
            continue
        suffix = source.suffix.lower()
        language = "c" if suffix == ".c" else "cpp"
        if suffix not in {".c", ".cc", ".cpp", ".cxx"}:
            continue
        candidates.append((source.stat().st_size, row, source, language))

    result: list[tuple[dict, Path, str]] = []
    for wanted in ("c", "cpp"):
        matches = [item for item in candidates if item[3] == wanted]
        if matches:
            _, row, source, language = min(matches, key=lambda x: x[0])
            result.append((row, source, language))
    return result


def _run_clang_ast_probes(
    frontend: Path,
    compile_rows: list[dict],
    project: Path,
    output: Path,
) -> tuple[list[dict], dict[str, str]]:
    diagnostics: list[dict] = []
    outputs: dict[str, str] = {}
    for row, source, language in _select_probe_rows(
        compile_rows, project.parent
    ):
        arguments = _clang_probe_arguments(
            frontend, row, source, language
        )
        rsp = output / f"native_ast_probe_{language}.rsp"
        _write_response_file(rsp, arguments)
        command = [str(frontend), f"@{rsp}"]
        target = output / f"native_ast_probe_{language}.json"

        launch_error = ""
        returncode = None
        stderr = ""
        with target.open("w", encoding="utf-8", newline="\n") as stdout_fh:
            try:
                run = subprocess.run(
                    command,
                    cwd=str(Path(row["directory"])),
                    text=True,
                    stdout=stdout_fh,
                    stderr=subprocess.PIPE,
                    errors="replace",
                    check=False,
                )
                returncode = run.returncode
                stderr = run.stderr or ""
            except OSError as exc:
                launch_error = str(exc)

        valid_json = False
        node_kind = ""
        if returncode == 0 and target.stat().st_size:
            try:
                root = json.loads(target.read_text(
                    encoding="utf-8", errors="replace"
                ))
                valid_json = isinstance(root, dict)
                node_kind = str(root.get("kind", "")) if valid_json else ""
            except json.JSONDecodeError:
                valid_json = False
        diagnostics.append({
            "kind": "clang_ast_probe",
            "language": language,
            "source_path": row["source_path"],
            "success": returncode == 0 and valid_json,
            "exit_code": returncode,
            "launch_error": launch_error,
            "command": subprocess.list2cmdline(command),
            "response_file": rsp.as_posix(),
            "response_argument_count": len(arguments),
            "response_file_bytes": rsp.stat().st_size,
            "stderr_tail": "\n".join(stderr.splitlines()[-120:]),
            "output": target.as_posix(),
            "output_bytes": target.stat().st_size,
            "valid_json": valid_json,
            "root_kind": node_kind,
        })
        outputs[language] = target.as_posix()
    return diagnostics, outputs


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
        for bindir in _vs_llvm_bin_candidates(compiler):
            candidate = bindir / "clangd-indexer.exe"
            checked.append(candidate.as_posix())
            if candidate.is_file():
                return _norm(candidate), checked

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
            "message": "clangd-indexer executable not found; trying clang frontend",
        })
        frontend, frontend_checked = discover_clang_frontend(
            editor, compiler_paths
        )
        if frontend is None:
            diagnostics.append({
                "kind": "clang_frontend_discovery",
                "success": False,
                "checked": frontend_checked,
                "message": "clang-cl/clang executable not found",
            })
            _write_jsonl(output / DIAGNOSTICS, diagnostics)
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "pass": "UnrealAssetToolNativeAST",
                "success": False,
                "error": "no clangd-indexer or clang frontend found",
                "project": project.as_posix(),
                "compile_database": compile_db.as_posix(),
                "filtered_compile_database": filtered_db.as_posix(),
                "project_owned_translation_units": len(entries),
                "compiler_paths": compiler_paths,
                "clangd_indexer": "",
                "clang_frontend": "",
                "checked_indexer_paths": checked,
                "checked_frontend_paths": frontend_checked,
                "raw_document_counts": {"symbols": 0, "refs": 0, "relations": 0},
                "ast_probe_outputs": {},
            }
            (output / MANIFEST).write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            return manifest

        version = subprocess.run(
            [str(frontend), "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            errors="replace",
            check=False,
        )
        probe_diagnostics, probe_outputs = _run_clang_ast_probes(
            frontend, compile_rows, project, output
        )
        diagnostics.extend(probe_diagnostics)
        probe_success = bool(probe_diagnostics) and all(
            row.get("success") for row in probe_diagnostics
        )
        diagnostics.append({
            "kind": "clang_frontend_discovery",
            "success": True,
            "checked": frontend_checked,
            "selected": frontend.as_posix(),
            "version": version.stdout.strip(),
        })
        _write_jsonl(output / DIAGNOSTICS, diagnostics)
        manifest = {
            "schema_version": SCHEMA_VERSION,
            "pass": "UnrealAssetToolNativeAST",
            "success": probe_success,
            "error": "" if probe_success else "clang frontend AST probe failed",
            "project": project.as_posix(),
            "compile_database": compile_db.as_posix(),
            "filtered_compile_database": filtered_db.as_posix(),
            "project_owned_translation_units": len(entries),
            "compiler_paths": compiler_paths,
            "clangd_indexer": "",
            "clang_frontend": frontend.as_posix(),
            "clang_frontend_version": version.stdout.strip(),
            "checked_indexer_paths": checked,
            "checked_frontend_paths": frontend_checked,
            "raw_document_counts": {"symbols": 0, "refs": 0, "relations": 0},
            "ast_probe_outputs": probe_outputs,
            "evidence": "clang_frontend_ast_json_probe",
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
