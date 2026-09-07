#!/usr/bin/env python3
"""Compiler-resolved native C/C++ index capture using clangd-indexer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import uatool_native_source as native_source
import uatool_native_libclang as native_libclang

SCHEMA_VERSION = 1
RAW_INDEX = "native_ast_index.yaml"
FILTERED_DB = "native_ast_compile_commands.json"
MANIFEST = "native_ast_manifest.json"
DIAGNOSTICS = "native_ast_diagnostics.jsonl"
SYMBOLS = "native_ast_symbols.jsonl"
PARAMETERS = "native_ast_parameters.jsonl"
CALLS = "native_ast_calls.jsonl"


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



def _stable_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _slash_path(value: str) -> str:
    return str(value).replace("\\", "/")


def _project_relative_string(value: str, project_root: Path) -> str | None:
    source = _slash_path(value)
    root = _slash_path(project_root.as_posix()).rstrip("/")
    prefix = root + "/"
    if source.lower().startswith(prefix.lower()):
        return source[len(prefix):]
    return None


def _location_file(location: dict | None) -> str | None:
    if not isinstance(location, dict):
        return None
    if location.get("file"):
        return _slash_path(location["file"])
    expansion = location.get("expansionLoc")
    if isinstance(expansion, dict) and expansion.get("file"):
        return _slash_path(expansion["file"])
    spelling = location.get("spellingLoc")
    if isinstance(spelling, dict) and spelling.get("file"):
        return _slash_path(spelling["file"])
    return None


def _flatten_clang_location(location: dict | None) -> dict:
    if not isinstance(location, dict):
        return {}
    expansion = location.get("expansionLoc")
    if isinstance(expansion, dict):
        return expansion
    if any(
        key in location
        for key in ("file", "offset", "line", "col", "tokLen")
    ):
        return location
    spelling = location.get("spellingLoc")
    if isinstance(spelling, dict):
        return spelling
    return location


def _node_location(node: dict) -> dict:
    location = node.get("loc")
    if isinstance(location, dict):
        flattened = _flatten_clang_location(location)
        if flattened:
            return flattened
    source_range = node.get("range")
    if isinstance(source_range, dict):
        begin = source_range.get("begin")
        if isinstance(begin, dict):
            return _flatten_clang_location(begin)
    return {}


def _walk_ast(
    children: list,
    inherited_file: str | None = None,
    enclosing_function: str | None = None,
):
    active_file = inherited_file
    function_kinds = {
        "FunctionDecl",
        "CXXMethodDecl",
        "CXXConstructorDecl",
        "CXXDestructorDecl",
        "CXXConversionDecl",
    }
    for node in children or []:
        if not isinstance(node, dict):
            continue
        explicit_file = _location_file(_node_location(node))
        if explicit_file:
            active_file = explicit_file
        node_file = explicit_file or active_file or inherited_file
        node_enclosing = enclosing_function
        if node.get("kind") in function_kinds:
            node_enclosing = str(node.get("id", "") or "")
        yield node, node_file, enclosing_function
        yield from _walk_ast(
            node.get("inner") or [],
            node_file,
            node_enclosing,
        )


def _symbol_identity(node: dict, source_path: str) -> str:
    kind = str(node.get("kind", ""))
    name = str(node.get("name", ""))
    mangled = str(node.get("mangledName", "") or "")
    qual_type = str((node.get("type") or {}).get("qualType", ""))
    storage = str(node.get("storageClass", "") or "")
    location = _node_location(node)
    line = int(location.get("line", 0) or 0)
    column = int(location.get("col", 0) or 0)
    offset = int(location.get("offset", 0) or 0)

    if mangled and storage != "static":
        key = f"{kind}|mangled|{mangled}|{qual_type}"
    elif mangled:
        key = f"{kind}|static|{source_path}|{mangled}|{qual_type}"
    else:
        key = (
            f"{kind}|source|{source_path}|{name}|"
            f"{line}|{column}|{offset}|{qual_type}"
        )
    return _stable_id(key)


def _find_referenced_decl(node: dict) -> dict | None:
    stack = list(reversed(node.get("inner") or []))
    while stack:
        current = stack.pop()
        if not isinstance(current, dict):
            continue
        referenced = current.get("referencedDecl")
        if isinstance(referenced, dict):
            return referenced
        stack.extend(reversed(current.get("inner") or []))
    return None


def _normalize_ast_probe(
    ast_path: Path,
    project_root: Path,
    translation_unit: str,
    language: str,
    compatibility_overrides: list[str] | None = None,
) -> tuple[list[dict], list[dict], list[dict]]:
    root = json.loads(ast_path.read_text(encoding="utf-8", errors="replace"))
    walked = list(_walk_ast(root.get("inner") or []))
    compatibility_overrides = list(compatibility_overrides or [])
    evidence = (
        "clang_frontend_ast_json_compatibility_replay"
        if compatibility_overrides
        else "clang_frontend_ast_json"
    )

    symbol_kinds = {
        "FunctionDecl": "function",
        "CXXMethodDecl": "method",
        "CXXConstructorDecl": "constructor",
        "CXXDestructorDecl": "destructor",
        "CXXRecordDecl": "record",
        "RecordDecl": "record",
        "EnumDecl": "enum",
        "TypedefDecl": "typedef",
        "TypeAliasDecl": "type_alias",
        "FieldDecl": "field",
        "VarDecl": "variable",
    }
    function_kinds = {
        "FunctionDecl",
        "CXXMethodDecl",
        "CXXConstructorDecl",
        "CXXDestructorDecl",
        "CXXConversionDecl",
    }

    symbols: list[dict] = []
    parameters: list[dict] = []
    calls: list[dict] = []
    clang_to_stable: dict[str, str] = {}

    for node, source_file, _ in walked:
        kind = str(node.get("kind", ""))
        if kind not in symbol_kinds or not source_file:
            continue
        source_path = _project_relative_string(source_file, project_root)
        if source_path is None:
            continue
        location = _node_location(node)
        stable = _symbol_identity(node, source_path)
        clang_id = str(node.get("id", "") or "")
        if clang_id:
            clang_to_stable[clang_id] = stable
        inner = node.get("inner") or []
        is_definition = (
            kind in function_kinds
            and any(
                isinstance(child, dict)
                and child.get("kind") in {"CompoundStmt", "CXXTryStmt"}
                for child in inner
            )
        ) or (
            kind in {"RecordDecl", "CXXRecordDecl", "EnumDecl"}
            and bool(node.get("completeDefinition"))
        )
        occurrence_id = _stable_id(
            f"occurrence|{source_path}|{kind}|"
            f"{location.get('offset', 0)}|{location.get('line', 0)}|"
            f"{location.get('col', 0)}|{node.get('name', '')}|"
            f"{(node.get('type') or {}).get('qualType', '')}"
        )
        symbols.append({
            "symbol_id": stable,
            "occurrence_id": occurrence_id,
            "clang_node_id": clang_id,
            "source_path": source_path,
            "translation_unit": translation_unit,
            "language": language,
            "clang_kind": kind,
            "kind": symbol_kinds[kind],
            "name": str(node.get("name", "") or ""),
            "mangled_name": str(node.get("mangledName", "") or ""),
            "type_spelling": str((node.get("type") or {}).get("qualType", "")),
            "storage_class": str(node.get("storageClass", "") or ""),
            "line": int(location.get("line", 0) or 0),
            "column": int(location.get("col", 0) or 0),
            "offset": int(location.get("offset", 0) or 0),
            "is_definition": bool(is_definition),
            "compatibility_overrides": compatibility_overrides,
            "evidence": evidence,
        })

        if kind in function_kinds:
            parameter_index = 0
            for child in inner:
                if not isinstance(child, dict) or child.get("kind") != "ParmVarDecl":
                    continue
                ploc = _node_location(child)
                parameters.append({
                    "function_symbol_id": stable,
                    "function_occurrence_id": occurrence_id,
                    "parameter_index": parameter_index,
                    "name": str(child.get("name", "") or ""),
                    "type_spelling": str(
                        (child.get("type") or {}).get("qualType", "")
                    ),
                    "source_path": source_path,
                    "translation_unit": translation_unit,
                    "language": language,
                    "line": int(ploc.get("line", 0) or 0),
                    "column": int(ploc.get("col", 0) or 0),
                    "compatibility_overrides": compatibility_overrides,
                    "evidence": evidence,
                })
                parameter_index += 1

    call_kinds = {"CallExpr", "CXXMemberCallExpr", "CXXOperatorCallExpr"}
    for node, source_file, enclosing_clang in walked:
        if node.get("kind") not in call_kinds or not source_file:
            continue
        source_path = _project_relative_string(source_file, project_root)
        if source_path is None:
            continue
        referenced = _find_referenced_decl(node)
        if referenced is None:
            continue
        location = _node_location(node)
        target_clang = str(referenced.get("id", "") or "")
        caller_stable = clang_to_stable.get(str(enclosing_clang or ""), "")
        calls.append({
            "call_id": _stable_id(
                f"{translation_unit}|{source_path}|"
                f"{location.get('offset', 0)}|{target_clang}"
            ),
            "caller_symbol_id": caller_stable,
            "source_path": source_path,
            "translation_unit": translation_unit,
            "language": language,
            "line": int(location.get("line", 0) or 0),
            "column": int(location.get("col", 0) or 0),
            "offset": int(location.get("offset", 0) or 0),
            "target_symbol_id": clang_to_stable.get(target_clang, ""),
            "target_clang_node_id": target_clang,
            "target_kind": str(referenced.get("kind", "") or ""),
            "target_name": str(referenced.get("name", "") or ""),
            "target_type_spelling": str(
                (referenced.get("type") or {}).get("qualType", "")
            ),
            "resolution": "compiler_resolved",
            "compatibility_overrides": compatibility_overrides,
            "evidence": evidence,
        })

    symbols.sort(key=lambda row: (
        row["source_path"].lower(),
        row["line"],
        row["column"],
        row["kind"],
        row["name"],
    ))
    parameters.sort(key=lambda row: (
        row["function_symbol_id"],
        row["parameter_index"],
    ))
    calls.sort(key=lambda row: (
        row["source_path"].lower(),
        row["line"],
        row["column"],
        row["call_id"],
    ))
    return symbols, parameters, calls


def _normalize_successful_probes(
    output: Path,
    diagnostics: list[dict],
    project: Path,
) -> dict[str, int]:
    symbols: list[dict] = []
    parameters: list[dict] = []
    calls: list[dict] = []
    for row in diagnostics:
        if not row.get("success"):
            continue

        if row.get("kind") == "libclang_cursor_probe":
            s, p, c = native_libclang.read_probe_rows(row)
            symbols.extend(s)
            parameters.extend(p)
            calls.extend(c)
            continue

        if row.get("kind") != "clang_ast_probe":
            continue
        ast_path = Path(str(row.get("output", "")))
        if not ast_path.is_file():
            continue
        s, p, c = _normalize_ast_probe(
            ast_path,
            project.parent,
            str(row.get("source_path", "")),
            str(row.get("language", "")),
            list(row.get("compatibility_overrides") or []),
        )
        symbols.extend(s)
        parameters.extend(p)
        calls.extend(c)

    _write_jsonl(output / SYMBOLS, symbols)
    _write_jsonl(output / PARAMETERS, parameters)
    _write_jsonl(output / CALLS, calls)
    return {
        "symbols": len(symbols),
        "parameters": len(parameters),
        "calls": len(calls),
    }


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


def _clang_version_major(frontend: Path) -> int:
    try:
        run = subprocess.run(
            [str(frontend), "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            errors="replace",
            check=False,
        )
    except OSError:
        return 0
    match = re.search(r"clang version\s+(\d+)", run.stdout or "")
    return int(match.group(1)) if match else 0


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

    candidates: list[Path] = []
    for name in ("clang-cl.exe", "clang-cl", "clang.exe", "clang"):
        found = shutil.which(name)
        if found:
            candidates.append(_norm(Path(found)))

    for compiler in compiler_paths:
        for bindir in _vs_llvm_bin_candidates(compiler):
            for exe in ("clang-cl.exe", "clang.exe"):
                candidates.append(_norm(bindir / exe))

    engine_root = native_source._engine_root_from_editor(editor)
    ue_root = engine_root.parent
    for bindir in (
        ue_root / "Engine" / "Extras" / "ThirdPartyNotUE" / "SDKs" /
        "HostWin64" / "Win64" / "LLVM" / "bin",
        ue_root / "Engine" / "Binaries" / "ThirdParty" / "LLVM" /
        "Win64" / "bin",
    ):
        for exe in ("clang-cl.exe", "clang.exe"):
            candidates.append(_norm(bindir / exe))

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = candidate.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        checked.append(candidate.as_posix())
        if candidate.is_file():
            unique.append(candidate)

    if not unique:
        return None, checked

    # Prefer the newest installed Clang frontend. For equal versions, prefer
    # clang-cl because the UBT database was generated for MSVC/CL semantics.
    unique.sort(
        key=lambda path: (
            _clang_version_major(path),
            1 if "clang-cl" in path.name.lower() else 0,
            path.as_posix().lower(),
        ),
        reverse=True,
    )
    return unique[0], checked


def _semantic_mode_arguments(entry: dict) -> list[str]:
    """Extract language/ABI mode flags from the exact expanded UBT command."""
    directory = _norm(Path(str(entry.get("directory", "."))))
    tokens = native_source._command_tokens(entry)
    expanded, _ = native_source._expand_response_tokens(tokens, directory)
    if expanded:
        expanded = expanded[1:]

    prefixes = (
        "/std:", "/permissive", "/Zc:", "/EH", "/GR", "/MD", "/MT",
        "/arch:", "/fp:", "/volatile:", "/utf-8", "/await",
        "/constexpr:", "/experimental:", "/favor:",
        "-std=", "-fms-", "-fdelayed-template-parsing",
        "-fchar8_t", "-fno-char8_t",
    )
    result: list[str] = []
    for token in expanded:
        stripped = native_source._strip_quotes(str(token))
        if stripped.startswith(prefixes) and stripped not in result:
            result.append(stripped)
    return result


def _precompiled_header_from_entry(entry: dict) -> str:
    """Return the UBT /Yu header spelling from the exact expanded command."""
    directory = _norm(Path(str(entry.get("directory", "."))))
    tokens = native_source._command_tokens(entry)
    expanded, _ = native_source._expand_response_tokens(tokens, directory)
    if expanded:
        expanded = expanded[1:]

    i = 0
    while i < len(expanded):
        token = native_source._strip_quotes(str(expanded[i]))
        if token.startswith("/Yu"):
            value = native_source._strip_quotes(token[3:])
            if not value and i + 1 < len(expanded):
                i += 1
                value = native_source._strip_quotes(str(expanded[i]))
            return value
        i += 1
    return ""


def _attach_semantic_mode_arguments(
    entries: list[dict],
    compile_rows: list[dict],
    project_root: Path,
) -> None:
    by_source: dict[Path, dict] = {}
    for entry in entries:
        source = native_source._resolve_compile_file(entry)
        if source is not None:
            by_source[source] = entry

    for row in compile_rows:
        source = _norm(project_root / row["source_path"])
        entry = by_source.get(source)
        row["_semantic_mode_arguments"] = (
            _semantic_mode_arguments(entry) if entry is not None else []
        )
        row["_precompiled_header"] = (
            _precompiled_header_from_entry(entry)
            if entry is not None
            else ""
        )


def _clang_probe_arguments(
    frontend: Path,
    compile_row: dict,
    source: Path,
    language: str,
    *,
    dump_ast: bool,
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
        pch_header = str(compile_row.get("_precompiled_header", "") or "")
        if pch_header:
            args.append(f"/FI{pch_header}")
    else:
        args.extend(["-x", "c" if language == "c" else "c++"])
        for include in compile_row.get("include_paths", []):
            args.extend(["-I", include])
        for definition in compile_row.get("definitions", []):
            args.append(f"-D{definition}")
        for forced in compile_row.get("forced_includes", []):
            args.extend(["-include", forced])
        pch_header = str(compile_row.get("_precompiled_header", "") or "")
        if pch_header:
            args.extend(["-include", pch_header])

    args.extend(compile_row.get("_semantic_mode_arguments", []))
    args.append("-fsyntax-only")
    if dump_ast:
        args.extend([
            "-Xclang",
            "-ast-dump=json",
        ])
    args.append(str(source))
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
        if not matches:
            continue
        if wanted == "c":
            preferred = {
                "radiant.c": 0,
                "hrsim_world.c": 1,
                "hrsim_action.c": 2,
            }
            _, row, source, language = min(
                matches,
                key=lambda x: (
                    preferred.get(x[2].name.lower(), 10),
                    x[0],
                ),
            )
        else:
            preferred_cpp = {
                "hrraientitycomponent.cpp": 0,
                "hrraiinteractablecomponent.cpp": 1,
                "hrraiplayerinteractorcomponent.cpp": 2,
                "hrraiworldsubsystem.cpp": 3,
                "hrraibootstrapactor.cpp": 4,
            }
            _, row, source, language = min(
                matches,
                key=lambda x: (
                    preferred_cpp.get(x[2].name.lower(), 10),
                    x[0],
                ),
            )
        result.append((row, source, language))
    return result


def _diagnostic_error_lines(stderr: str) -> list[str]:
    return [
        line
        for line in stderr.splitlines()
        if " error:" in line.lower() or "fatal error:" in line.lower()
    ][:80]


def _with_extra_probe_arguments(
    arguments: list[str],
    extra: list[str],
) -> list[str]:
    if not arguments or not extra:
        return list(arguments)
    return list(arguments[:-1]) + list(extra) + [arguments[-1]]


def _run_clang_ast_probes(
    frontend: Path,
    libclang: Path | None,
    compile_rows: list[dict],
    project: Path,
    output: Path,
) -> tuple[list[dict], dict[str, str]]:
    diagnostics: list[dict] = []
    outputs: dict[str, str] = {}
    frontend_major = _clang_version_major(frontend)

    for row, source, language in _select_probe_rows(
        compile_rows, project.parent
    ):
        base_syntax_arguments = _clang_probe_arguments(
            frontend, row, source, language, dump_ast=False
        )
        syntax_arguments = list(base_syntax_arguments)
        syntax_rsp = output / f"native_ast_probe_{language}_syntax.rsp"
        _write_response_file(syntax_rsp, syntax_arguments)
        syntax_command = [str(frontend), f"@{syntax_rsp}"]

        syntax_launch_error = ""
        syntax_returncode = None
        syntax_stderr = ""
        try:
            syntax_run = subprocess.run(
                syntax_command,
                cwd=str(Path(row["directory"])),
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                errors="replace",
                check=False,
            )
            syntax_returncode = syntax_run.returncode
            syntax_stderr = syntax_run.stderr or ""
        except OSError as exc:
            syntax_launch_error = str(exc)

        initial_syntax_returncode = syntax_returncode
        initial_syntax_stderr = syntax_stderr
        initial_syntax_error_lines = _diagnostic_error_lines(
            initial_syntax_stderr
        )
        initial_syntax_stderr_path = (
            output
            / f"native_ast_probe_{language}_syntax_initial.stderr.txt"
        )
        initial_syntax_stderr_path.write_text(
            initial_syntax_stderr,
            encoding="utf-8",
            newline="\n",
        )

        compatibility_overrides: list[str] = []
        if language == "cpp" and syntax_returncode not in {0, None}:
            if (
                frontend_major < 19
                and "STL1000: Unexpected compiler version" in syntax_stderr
            ):
                compatibility_overrides.append(
                    "/D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH=1"
                )
            if "[-Winvalid-constexpr]" in syntax_stderr:
                compatibility_overrides.append(
                    "-Wno-invalid-constexpr"
                )

        if compatibility_overrides:
            syntax_arguments = _with_extra_probe_arguments(
                base_syntax_arguments,
                compatibility_overrides,
            )
            syntax_rsp = (
                output
                / f"native_ast_probe_{language}_syntax_compat.rsp"
            )
            _write_response_file(syntax_rsp, syntax_arguments)
            syntax_command = [str(frontend), f"@{syntax_rsp}"]
            syntax_launch_error = ""
            syntax_returncode = None
            syntax_stderr = ""
            try:
                syntax_run = subprocess.run(
                    syntax_command,
                    cwd=str(Path(row["directory"])),
                    text=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    errors="replace",
                    check=False,
                )
                syntax_returncode = syntax_run.returncode
                syntax_stderr = syntax_run.stderr or ""
            except OSError as exc:
                syntax_launch_error = str(exc)

        syntax_stderr_path = (
            output / f"native_ast_probe_{language}_syntax.stderr.txt"
        )
        syntax_stderr_path.write_text(
            syntax_stderr,
            encoding="utf-8",
            newline="\n",
        )
        syntax_error_lines = _diagnostic_error_lines(syntax_stderr)

        # UE C++ TUs can exceed a gigabyte when dumped through
        # -ast-dump=json. Once syntax is proven, use libclang cursors instead
        # so only project-owned semantics are materialized.
        if language == "cpp":
            base_diag = {
                "kind": "clang_ast_probe",
                "language": language,
                "source_path": row["source_path"],
                "success": False,
                "frontend_major": frontend_major,
                "semantic_mode_arguments": row.get(
                    "_semantic_mode_arguments", []
                ),
                "compatibility_overrides": compatibility_overrides,
                "initial_syntax_exit_code": initial_syntax_returncode,
                "initial_syntax_stderr_file": (
                    initial_syntax_stderr_path.as_posix()
                ),
                "initial_syntax_error_lines": initial_syntax_error_lines,
                "syntax_exit_code": syntax_returncode,
                "syntax_launch_error": syntax_launch_error,
                "syntax_command": subprocess.list2cmdline(syntax_command),
                "syntax_response_file": syntax_rsp.as_posix(),
                "syntax_response_argument_count": len(syntax_arguments),
                "syntax_response_file_bytes": syntax_rsp.stat().st_size,
                "syntax_stderr_file": syntax_stderr_path.as_posix(),
                "syntax_error_lines": syntax_error_lines,
                "syntax_stderr_tail": "\n".join(
                    syntax_stderr.splitlines()[-120:]
                ),
                "extraction_backend": "libclang_cursor",
                "output": "",
                "output_bytes": 0,
                "valid_json": False,
                "root_kind": "",
            }
            diagnostics.append(base_diag)

            if syntax_returncode == 0 and libclang is not None:
                libclang_diag = native_libclang.run_cursor_probe(
                    frontend=frontend,
                    libclang=libclang,
                    row=row,
                    source=source,
                    language=language,
                    compatibility_overrides=compatibility_overrides,
                    syntax_arguments=syntax_arguments,
                    project_root=project.parent,
                    output=output,
                )
                diagnostics.append(libclang_diag)
                outputs[language] = str(
                    libclang_diag.get("result_file", "")
                )
            else:
                outputs[language] = ""
            continue

        target = output / f"native_ast_probe_{language}.json"
        target.write_text("", encoding="utf-8")
        ast_rsp = output / f"native_ast_probe_{language}.rsp"
        ast_returncode = None
        ast_stderr = ""
        ast_launch_error = ""
        ast_argument_count = 0

        if syntax_returncode == 0:
            ast_arguments = _clang_probe_arguments(
                frontend, row, source, language, dump_ast=True
            )
            ast_arguments = _with_extra_probe_arguments(
                ast_arguments,
                compatibility_overrides,
            )
            ast_argument_count = len(ast_arguments)
            _write_response_file(ast_rsp, ast_arguments)
            ast_command = [str(frontend), f"@{ast_rsp}"]
            with target.open("w", encoding="utf-8", newline="\n") as stdout_fh:
                try:
                    ast_run = subprocess.run(
                        ast_command,
                        cwd=str(Path(row["directory"])),
                        text=True,
                        stdout=stdout_fh,
                        stderr=subprocess.PIPE,
                        errors="replace",
                        check=False,
                    )
                    ast_returncode = ast_run.returncode
                    ast_stderr = ast_run.stderr or ""
                except OSError as exc:
                    ast_launch_error = str(exc)
        else:
            ast_rsp.write_text("", encoding="utf-8")

        ast_stderr_path = output / f"native_ast_probe_{language}.stderr.txt"
        ast_stderr_path.write_text(
            ast_stderr,
            encoding="utf-8",
            newline="\n",
        )
        ast_error_lines = _diagnostic_error_lines(ast_stderr)

        valid_json = False
        node_kind = ""
        if ast_returncode == 0 and target.stat().st_size:
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
            "success": ast_returncode == 0 and valid_json,
            "frontend_major": frontend_major,
            "semantic_mode_arguments": row.get(
                "_semantic_mode_arguments", []
            ),
            "precompiled_header": row.get("_precompiled_header", ""),
            "precompiled_header_replay": (
                "forced_include_source_header"
                if row.get("_precompiled_header")
                else ""
            ),
            "compatibility_overrides": compatibility_overrides,
            "initial_syntax_exit_code": initial_syntax_returncode,
            "initial_syntax_stderr_file": (
                initial_syntax_stderr_path.as_posix()
            ),
            "initial_syntax_error_lines": initial_syntax_error_lines,
            "syntax_exit_code": syntax_returncode,
            "syntax_launch_error": syntax_launch_error,
            "syntax_command": subprocess.list2cmdline(syntax_command),
            "syntax_response_file": syntax_rsp.as_posix(),
            "syntax_response_argument_count": len(syntax_arguments),
            "syntax_response_file_bytes": syntax_rsp.stat().st_size,
            "syntax_stderr_file": syntax_stderr_path.as_posix(),
            "syntax_error_lines": syntax_error_lines,
            "syntax_stderr_tail": "\n".join(
                syntax_stderr.splitlines()[-120:]
            ),
            "exit_code": ast_returncode,
            "launch_error": ast_launch_error,
            "response_file": ast_rsp.as_posix(),
            "response_argument_count": ast_argument_count,
            "response_file_bytes": ast_rsp.stat().st_size,
            "stderr_file": ast_stderr_path.as_posix(),
            "error_lines": ast_error_lines,
            "stderr_tail": "\n".join(ast_stderr.splitlines()[-120:]),
            "output": target.as_posix(),
            "output_bytes": target.stat().st_size,
            "valid_json": valid_json,
            "root_kind": node_kind,
            "extraction_backend": "clang_ast_json",
        })
        outputs[language] = target.as_posix()
    return diagnostics, outputs



def _probe_languages_successful(diagnostics: list[dict]) -> bool:
    by_language: dict[str, bool] = {}
    for row in diagnostics:
        language = str(row.get("language", "") or "")
        if not language:
            continue
        if row.get("kind") not in {"clang_ast_probe", "libclang_cursor_probe"}:
            continue
        by_language.setdefault(language, False)
        if row.get("success"):
            by_language[language] = True
    return bool(by_language) and all(by_language.values())


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
    _attach_semantic_mode_arguments(
        entries, compile_rows, project.parent
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
        libclang, libclang_checked = native_libclang.discover_libclang(
            frontend
        )
        diagnostics.append({
            "kind": "libclang_discovery",
            "success": libclang is not None,
            "checked": libclang_checked,
            "selected": libclang.as_posix() if libclang else "",
        })
        probe_diagnostics, probe_outputs = _run_clang_ast_probes(
            frontend, libclang, compile_rows, project, output
        )
        diagnostics.extend(probe_diagnostics)
        normalized_counts = _normalize_successful_probes(
            output, probe_diagnostics, project
        )
        probe_success = _probe_languages_successful(
            probe_diagnostics
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
            "libclang": libclang.as_posix() if libclang else "",
            "checked_libclang_paths": libclang_checked,
            "checked_indexer_paths": checked,
            "checked_frontend_paths": frontend_checked,
            "raw_document_counts": {"symbols": 0, "refs": 0, "relations": 0},
            "ast_probe_outputs": probe_outputs,
            "normalized_files": {
                "symbols": (output / SYMBOLS).as_posix(),
                "parameters": (output / PARAMETERS).as_posix(),
                "calls": (output / CALLS).as_posix(),
            },
            "normalized_counts": normalized_counts,
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
