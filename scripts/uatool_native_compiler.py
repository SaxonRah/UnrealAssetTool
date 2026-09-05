#!/usr/bin/env python3
"""Compiler-command evidence for project-owned native C/C++.

Schema 1 starts by capturing and validating the real UnrealBuildTool
translation-unit database. AST-resolved symbols/references/calls are reserved
streams until an AST-capable frontend is added; this module does not invent
compiler facts from source syntax.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

import uatool_native_source as native_source

SCHEMA_VERSION = 1
MANIFEST_FILE = "native_compiler_manifest.json"
PASS_NAME = "UnrealAssetToolNativeCompiler"

JSONL_FILES = (
    "native_compile_units.jsonl",
    "native_compiler_symbols.jsonl",
    "native_compiler_references.jsonl",
    "native_compiler_calls.jsonl",
    "native_compiler_includes.jsonl",
    "native_compiler_source_joins.jsonl",
    "native_compiler_reflection_joins.jsonl",
)

EMPTY_SCHEMA_STREAMS = JSONL_FILES[1:]
TRANSLATION_SUFFIXES = {".c", ".cc", ".cpp", ".cxx"}


def _stable_id(*parts: object) -> str:
    text = "\x1f".join(str(part) for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise RuntimeError(f"expected object row in {path}:{line_number}")
            yield row


def _write_jsonl(path: Path, rows: Iterable[dict]) -> int:
    ordered = list(rows)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in ordered
        ),
        encoding="utf-8",
        newline="\n",
    )
    return len(ordered)


def _relative(project_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(project_dir.resolve()).as_posix()


def _module_roots(project_dir: Path, output: Path) -> list[tuple[str, Path]]:
    result: list[tuple[str, Path]] = []
    project_dir = project_dir.resolve()
    for row in _rows(output / "native_modules.jsonl"):
        name = str(row.get("module_name", "") or "")
        build_cs = str(row.get("build_cs", "") or "")
        if not name or not build_cs:
            continue
        build_path = (project_dir / build_cs).resolve()
        try:
            build_path.relative_to(project_dir)
        except ValueError as exc:
            raise RuntimeError(f"native module escapes project root: {build_cs}") from exc
        root = build_path.parent
        if not root.is_dir():
            raise RuntimeError(f"native module root missing: {root}")
        result.append((name, root))
    result.sort(key=lambda item: (-len(item[1].parts), item[0]))
    return result


def _module_for_source(source: Path, roots: list[tuple[str, Path]]) -> tuple[str, Path] | None:
    resolved = source.resolve()
    for module_name, root in roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return module_name, root
    return None


def _first_command_token(command: str) -> str:
    text = command.lstrip()
    if not text:
        return ""
    if text[0] == '"':
        escaped = False
        chars: list[str] = []
        for ch in text[1:]:
            if ch == '"' and not escaped:
                break
            chars.append(ch)
            escaped = (ch == "\\" and not escaped)
            if ch != "\\":
                escaped = False
        return "".join(chars)
    return text.split(None, 1)[0]


def _compiler_family(executable: str) -> str:
    name = Path(executable.strip('"')).name.lower()
    if "clang-cl" in name:
        return "clang-cl"
    if name in {"cl", "cl.exe"}:
        return "msvc"
    if "clang" in name:
        return "clang"
    if name.startswith(("gcc", "g++")):
        return "gcc"
    return "unknown"


def _resolve_entry_source(entry: dict) -> Path | None:
    file_text = str(entry.get("file", "") or "")
    if not file_text:
        return None
    directory = Path(str(entry.get("directory", "") or "."))
    source = Path(file_text)
    if not source.is_absolute():
        source = directory / source
    return source.resolve()


def _entry_command(entry: dict) -> tuple[list[str], str, bool]:
    arguments = entry.get("arguments")
    if isinstance(arguments, list) and all(isinstance(value, str) for value in arguments):
        args = list(arguments)
        command = subprocess.list2cmdline(args)
        return args, command, True

    command = str(entry.get("command", "") or "")
    return [], command, False


def ingest_database(project_dir: Path, output: Path, database: Path) -> dict:
    project_dir = Path(project_dir).resolve()
    output = Path(output).resolve()
    database = Path(database).resolve()

    if not database.is_file():
        raise FileNotFoundError(f"compilation database does not exist: {database}")

    try:
        payload = json.loads(database.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read compilation database: {database}") from exc
    if not isinstance(payload, list):
        raise RuntimeError("compile_commands.json root must be an array")

    roots = _module_roots(project_dir, output)
    source_rows = list(_rows(output / "native_source_files.jsonl"))
    source_by_path = {
        str(row.get("path", "") or ""): row
        for row in source_rows
        if row.get("path")
    }
    expected_units = {
        path
        for path in source_by_path
        if Path(path).suffix.lower() in TRANSLATION_SUFFIXES
    }

    units: list[dict] = []
    seen_source_paths: set[str] = set()

    for entry_index, entry in enumerate(payload):
        if not isinstance(entry, dict):
            continue
        source = _resolve_entry_source(entry)
        if source is None:
            continue
        owned = _module_for_source(source, roots)
        if owned is None:
            continue

        module_name, module_root = owned
        try:
            source_path = _relative(project_dir, source)
        except ValueError:
            continue
        if source_path not in source_by_path:
            continue

        arguments, command, arguments_exact = _entry_command(entry)
        compiler_executable = (
            arguments[0] if arguments else _first_command_token(command)
        )
        working_directory = str(entry.get("directory", "") or "")
        output_file = str(entry.get("output", "") or "")
        unit_id = _stable_id(
            module_name,
            source_path,
            working_directory,
            command,
            json.dumps(arguments, ensure_ascii=False, separators=(",", ":")),
        )
        response_files = [
            value[1:]
            for value in arguments
            if value.startswith("@") and len(value) > 1
        ]
        if not response_files and command:
            response_files = re.findall(
                r'@(?:"([^"]+)"|([^\s]+))',
                command,
            )
            response_files = [first or second for first, second in response_files]

        units.append({
            "compile_unit_id": unit_id,
            "module_name": module_name,
            "source_path": source_path,
            "module_relative_path": source.relative_to(module_root).as_posix(),
            "working_directory": working_directory,
            "compiler_executable": compiler_executable,
            "compiler_family": _compiler_family(compiler_executable),
            "arguments": arguments,
            "arguments_exact": arguments_exact,
            "command": command,
            "command_exact": bool(command),
            "command_sha256": hashlib.sha256(command.encode("utf-8")).hexdigest(),
            "response_files": response_files,
            "output": output_file,
            "database_entry_index": entry_index,
            "evidence_level": "compiler_command",
        })
        seen_source_paths.add(source_path)

    units.sort(key=lambda row: (row["module_name"], row["source_path"], row["compile_unit_id"]))
    _write_jsonl(output / "native_compile_units.jsonl", units)
    for filename in EMPTY_SCHEMA_STREAMS:
        _write_jsonl(output / filename, [])

    missing = sorted(expected_units - seen_source_paths)
    extra = sorted(seen_source_paths - expected_units)
    compiler_families = sorted({
        str(row.get("compiler_family", "") or "")
        for row in units
        if row.get("compiler_family")
    })

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pass": PASS_NAME,
        "success": True,
        "error": "",
        "evidence_level": "compiler_command",
        "ast_resolved": False,
        "capture_scope": (
            "real UBT translation-unit commands for project/project-plugin native "
            "module source; AST symbols/references/calls are not yet claimed"
        ),
        "database_path": str(database),
        "files": list(JSONL_FILES),
        "compiler_families": compiler_families,
        "counts": {
            "compile_units": len(units),
            "expected_translation_units": len(expected_units),
            "missing_translation_units": len(missing),
            "extra_translation_units": len(extra),
            "symbols": 0,
            "references": 0,
            "calls": 0,
            "includes": 0,
            "source_joins": 0,
            "reflection_joins": 0,
        },
        "missing_translation_units": missing,
        "extra_translation_units": extra,
    }
    (output / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def _resolve_dotnet(engine_dir: Path) -> Path | str:
    """Resolve the engine-bundled dotnet host, falling back to PATH.

    Epic Launcher installs may omit RunUBT.bat while still shipping
    UnrealBuildTool.dll and a private .NET runtime. Prefer that private host so
    the compiler capture uses the same runtime family as the normal UE build.
    """
    third_party = engine_dir / "Binaries" / "ThirdParty" / "DotNet"
    if third_party.is_dir():
        candidates = sorted(
            (
                path
                for path in third_party.rglob("dotnet.exe")
                if path.is_file()
            ),
            key=lambda path: (
                "win-x64" not in path.as_posix().lower(),
                path.as_posix().lower(),
            ),
        )
        if candidates:
            return candidates[0]

    on_path = shutil.which("dotnet")
    if on_path:
        return on_path

    raise FileNotFoundError(
        "UnrealBuildTool.dll exists, but no dotnet host was found under "
        f"{third_party} and 'dotnet' is not on PATH"
    )


def _resolve_ubt_command(engine_dir: Path) -> list[str]:
    """Return the executable prefix for UBT on source or Launcher engines."""
    ubt_dir = engine_dir / "Binaries" / "DotNET" / "UnrealBuildTool"
    ubt_exe = ubt_dir / "UnrealBuildTool.exe"
    if ubt_exe.is_file():
        return [str(ubt_exe)]

    ubt_dll = ubt_dir / "UnrealBuildTool.dll"
    if ubt_dll.is_file():
        dotnet = _resolve_dotnet(engine_dir)
        return [str(dotnet), str(ubt_dll)]

    # Source checkouts commonly expose RunUBT.bat. Keep it as a final
    # compatibility path, but do not require it for installed Launcher builds.
    run_ubt = engine_dir / "Build" / "BatchFiles" / "RunUBT.bat"
    if run_ubt.is_file():
        return [str(run_ubt)]

    raise FileNotFoundError(
        "Could not locate UnrealBuildTool. Checked:\n"
        f"  {ubt_exe}\n"
        f"  {ubt_dll}\n"
        f"  {run_ubt}"
    )


def generate_database(
    project: Path,
    editor: Path,
    output: Path,
    configuration: str,
    compiler: str,
) -> tuple[Path, list[str], int]:
    project = Path(project).resolve()
    editor = Path(editor).resolve()
    output = Path(output).resolve()

    try:
        engine_dir = editor.parents[2]
    except IndexError as exc:
        raise FileNotFoundError("could not derive Engine directory from --editor") from exc

    ubt_prefix = _resolve_ubt_command(engine_dir)

    database_dir = output / "compiler-db"
    database_dir.mkdir(parents=True, exist_ok=True)
    database = database_dir / "compile_commands.json"
    database.unlink(missing_ok=True)

    target = f"{project.stem}Editor"
    command = ubt_prefix + [
        "-Mode=GenerateClangDatabase",
        f"-Project={project}",
        target,
        "Win64",
        configuration,
        f"-Compiler={compiler}",
        "-NoPCH",
        "-DisableUnity",
        "-NoExecCodeGenActions",
        f"-OutputDir={database_dir}",
        "-WaitMutex",
    ]
    result = subprocess.run(command, check=False)
    return database, command, result.returncode


def read_manifest(output: Path) -> dict | None:
    path = Path(output) / MANIFEST_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def validation_error(output: Path) -> str | None:
    output = Path(output)
    manifest = read_manifest(output)
    if not manifest:
        return f"{MANIFEST_FILE} missing or invalid"
    if int(manifest.get("schema_version", 0) or 0) != SCHEMA_VERSION:
        return f"expected native compiler schema {SCHEMA_VERSION}, got {manifest.get('schema_version')}"
    if manifest.get("pass") != PASS_NAME:
        return f"unexpected native compiler pass {manifest.get('pass')!r}"
    if not bool(manifest.get("success", False)):
        return f"native compiler capture failed: {manifest.get('error', '')}"
    if manifest.get("evidence_level") != "compiler_command":
        return "native compiler manifest evidence level is not compiler_command"
    if bool(manifest.get("ast_resolved", True)):
        return "compile-unit schema must not claim AST resolution yet"
    if tuple(manifest.get("files", [])) != JSONL_FILES:
        return "native compiler manifest file list does not match schema 1"

    counts = manifest.get("counts")
    if not isinstance(counts, dict):
        return "native compiler manifest counts missing or invalid"

    count_keys = {
        "native_compile_units.jsonl": "compile_units",
        "native_compiler_symbols.jsonl": "symbols",
        "native_compiler_references.jsonl": "references",
        "native_compiler_calls.jsonl": "calls",
        "native_compiler_includes.jsonl": "includes",
        "native_compiler_source_joins.jsonl": "source_joins",
        "native_compiler_reflection_joins.jsonl": "reflection_joins",
    }
    streams: dict[str, list[dict]] = {}
    for filename in JSONL_FILES:
        path = output / filename
        if not path.is_file():
            return f"native compiler stream missing: {filename}"
        rows = list(_rows(path))
        streams[filename] = rows
        key = count_keys[filename]
        if int(counts.get(key, -1)) != len(rows):
            return (
                f"native compiler count mismatch for {key}: "
                f"manifest={counts.get(key)} actual={len(rows)}"
            )

    units = streams["native_compile_units.jsonl"]
    unit_ids = [row.get("compile_unit_id") for row in units]
    if len(unit_ids) != len(set(unit_ids)):
        return "duplicate native compile unit id"

    source_rows = list(_rows(output / "native_source_files.jsonl"))
    source_paths = {
        str(row.get("path", "") or "")
        for row in source_rows
        if row.get("path")
    }
    expected = {
        path
        for path in source_paths
        if Path(path).suffix.lower() in TRANSLATION_SUFFIXES
    }
    seen = {
        str(row.get("source_path", "") or "")
        for row in units
        if row.get("source_path")
    }

    for row in units:
        if row.get("evidence_level") != "compiler_command":
            return "native compile unit mislabeled evidence level"
        if row.get("source_path") not in source_paths:
            return "native compile unit references unknown source file"
        if not row.get("command_exact"):
            return "native compile unit is missing exact command text"
        if not row.get("compiler_executable"):
            return "native compile unit is missing compiler executable"

    missing = sorted(expected - seen)
    extra = sorted(seen - expected)
    if missing != list(manifest.get("missing_translation_units", [])):
        return "native compiler missing-translation list does not reconcile"
    if extra != list(manifest.get("extra_translation_units", [])):
        return "native compiler extra-translation list does not reconcile"
    if int(counts.get("expected_translation_units", -1)) != len(expected):
        return "native compiler expected translation-unit count does not reconcile"
    if int(counts.get("missing_translation_units", -1)) != len(missing):
        return "native compiler missing translation-unit count does not reconcile"
    if int(counts.get("extra_translation_units", -1)) != len(extra):
        return "native compiler extra translation-unit count does not reconcile"
    if missing:
        return (
            "UBT compilation database is missing project translation units: "
            + ", ".join(missing[:8])
            + (" ..." if len(missing) > 8 else "")
        )

    return None
