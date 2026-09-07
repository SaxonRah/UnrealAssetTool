#!/usr/bin/env python3
"""Project-owned native C/C++ source/compiler capture for UnrealAssetTool."""
from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 1
RAW_FILES = (
    "source_files.jsonl",
    "source_compile_commands.jsonl",
    "source_includes.jsonl",
    "source_defines.jsonl",
    "source_symbols.jsonl",
    "source_function_parameters.jsonl",
    "source_calls.jsonl",
    "source_diagnostics.jsonl",
)

SOURCE_EXTENSIONS = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".m": "objective_c",
    ".mm": "objective_cpp",
    ".h": "header",
    ".hh": "header",
    ".hpp": "header",
    ".hxx": "header",
    ".inl": "header",
    ".inc": "header",
}

_EXCLUDED_DIRS = {
    ".git", ".svn", ".hg", "Binaries", "DerivedDataCache", "Intermediate",
    "Saved", "__pycache__",
}

_CONTROL_NAMES = {
    "if", "for", "while", "switch", "catch", "return", "sizeof", "alignof",
    "decltype", "static_cast", "dynamic_cast", "reinterpret_cast", "const_cast",
    "new", "delete", "throw", "co_await", "co_yield", "co_return",
}

_TYPE_WORDS = {
    "const", "volatile", "static", "extern", "inline", "constexpr", "consteval",
    "constinit", "mutable", "register", "signed", "unsigned", "short", "long",
    "struct", "class", "union", "enum", "typename", "auto", "void", "bool",
    "char", "wchar_t", "char8_t", "char16_t", "char32_t", "float", "double",
    "int", "size_t",
}


@dataclass(frozen=True)
class ModuleRoot:
    name: str
    root: Path
    build_cs: Path
    owner_kind: str
    owner_name: str


def _norm(path: Path) -> Path:
    return path.expanduser().resolve()


def _display_path(path: Path, project_root: Path) -> str:
    path = _norm(path)
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _jsonl_write(path: Path, rows: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            fh.write("\n")
            count += 1
    return count


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def discover_modules(project: Path) -> list[ModuleRoot]:
    project_root = _norm(project).parent
    build_files = (
        list((project_root / "Source").rglob("*.Build.cs"))
        if (project_root / "Source").is_dir()
        else []
    )
    plugins_root = project_root / "Plugins"
    if plugins_root.is_dir():
        build_files.extend(plugins_root.rglob("*.Build.cs"))

    result: list[ModuleRoot] = []
    for build_cs in sorted(
        {_norm(p) for p in build_files},
        key=lambda p: p.as_posix().lower(),
    ):
        rel = _display_path(build_cs, project_root)
        parts = Path(rel).parts
        if "UnrealAssetTool" in parts and "Plugins" in parts:
            continue
        filename = build_cs.name
        if not filename.endswith(".Build.cs"):
            continue
        name = filename[:-9]
        if not name:
            continue

        owner_kind = "project"
        owner_name = project.stem
        if len(parts) >= 3 and parts[0].lower() == "plugins":
            owner_kind = "project_plugin"
            owner_name = parts[1]

        result.append(
            ModuleRoot(
                name=name,
                root=build_cs.parent,
                build_cs=build_cs,
                owner_kind=owner_kind,
                owner_name=owner_name,
            )
        )
    return result


def discover_source_files(
    project: Path,
    modules: list[ModuleRoot],
) -> list[tuple[Path, ModuleRoot, str]]:
    seen: dict[Path, tuple[ModuleRoot, str]] = {}
    for module in modules:
        if not module.root.is_dir():
            continue
        for path in module.root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _EXCLUDED_DIRS for part in path.parts):
                continue
            language = SOURCE_EXTENSIONS.get(path.suffix.lower())
            if not language:
                continue
            resolved = _norm(path)
            seen.setdefault(resolved, (module, language))
    return [
        (p, seen[p][0], seen[p][1])
        for p in sorted(seen, key=lambda x: x.as_posix().lower())
    ]


def _target_name(project: Path) -> str:
    source_root = project.parent / "Source"
    candidates = (
        sorted(source_root.glob("*Editor.Target.cs"))
        if source_root.is_dir()
        else []
    )
    if candidates:
        return candidates[0].name[:-10]
    return f"{project.stem}Editor"


def _engine_root_from_editor(editor: Path) -> Path:
    editor = _norm(editor)
    parts_lower = [p.lower() for p in editor.parts]
    try:
        engine_index = max(i for i, p in enumerate(parts_lower) if p == "engine")
    except ValueError as exc:
        raise RuntimeError(
            f"cannot derive Engine root from editor path: {editor}"
        ) from exc
    return Path(*editor.parts[: engine_index + 1])


def _run_generate_clang_database(
    project: Path,
    editor: Path,
    configuration: str,
) -> tuple[Path | None, dict]:
    engine_root = _engine_root_from_editor(editor)
    build_bat = engine_root / "Build" / "BatchFiles" / "Build.bat"
    target = _target_name(project)
    diagnostics = {
        "kind": "compile_database_generation",
        "attempted": True,
        "target": target,
        "configuration": configuration,
        "build_bat": build_bat.as_posix(),
        "success": False,
        "exit_code": None,
        "message": "",
    }
    if not build_bat.is_file():
        diagnostics["message"] = f"Build.bat not found: {build_bat}"
        return None, diagnostics

    candidates = [
        engine_root / "compile_commands.json",
        project.parent / "compile_commands.json",
    ]
    previous = {
        p: p.stat().st_mtime_ns if p.is_file() else -1
        for p in candidates
    }

    args = [
        str(build_bat),
        f"-Target={target} Win64 {configuration}",
        f"-Project={project}",
        "-Mode=GenerateClangDatabase",
        "-WaitMutex",
        "-NoExecCodeGenActions",
    ]
    command_text = subprocess.list2cmdline(args)
    try:
        completed = subprocess.run(
            ["cmd.exe", "/d", "/s", "/c", command_text],
            cwd=str(project.parent),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            errors="replace",
            check=False,
        )
    except OSError as exc:
        diagnostics["message"] = str(exc)
        return None, diagnostics

    diagnostics["exit_code"] = completed.returncode
    diagnostics["output_tail"] = "\n".join(completed.stdout.splitlines()[-80:])
    if completed.returncode != 0:
        diagnostics["message"] = "UnrealBuildTool GenerateClangDatabase failed"
        return None, diagnostics

    existing = [p for p in candidates if p.is_file()]
    if not existing:
        for root in (engine_root, project.parent):
            for candidate in root.glob("**/compile_commands.json"):
                if candidate.is_file():
                    existing.append(candidate)

    if not existing:
        diagnostics["message"] = (
            "GenerateClangDatabase succeeded but compile_commands.json was not found"
        )
        return None, diagnostics

    existing.sort(
        key=lambda p: (
            p.stat().st_mtime_ns > previous.get(p, -1),
            p.stat().st_mtime_ns,
            -len(p.as_posix()),
        ),
        reverse=True,
    )
    chosen = _norm(existing[0])
    diagnostics["success"] = True
    diagnostics["compile_commands"] = chosen.as_posix()
    diagnostics["message"] = "compile database generated"
    return chosen, diagnostics


def _find_existing_compile_database(
    project: Path,
    editor: Path,
) -> Path | None:
    engine_root = _engine_root_from_editor(editor)
    candidates = (
        project.parent / "compile_commands.json",
        engine_root / "compile_commands.json",
    )
    for path in candidates:
        if path.is_file():
            return _norm(path)
    return None


def _resolve_compile_file(entry: dict) -> Path | None:
    raw = entry.get("file")
    if not raw:
        return None
    path = Path(str(raw).strip('"'))
    if not path.is_absolute():
        directory = Path(str(entry.get("directory", ".")).strip('"'))
        path = directory / path
    try:
        return _norm(path)
    except OSError:
        return None


def _command_tokens(entry: dict) -> list[str]:
    arguments = entry.get("arguments")
    if isinstance(arguments, list):
        return [str(x) for x in arguments]
    command = str(entry.get("command", "") or "")
    if not command:
        return []
    try:
        return shlex.split(command, posix=False)
    except ValueError:
        return command.split()


def _strip_quotes(value: str) -> str:
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in "\"'"
    ):
        return value[1:-1]
    return value


def _response_path(token: str, cwd: Path) -> Path | None:
    if not token.startswith("@"):
        return None
    raw = _strip_quotes(token[1:])
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = cwd / path
    return _norm(path)


def _read_rsp_tokens(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    try:
        return shlex.split(text, posix=False)
    except ValueError:
        return [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]


def _expand_response_tokens(
    tokens: list[str],
    cwd: Path,
    max_depth: int = 8,
) -> tuple[list[str], list[Path]]:
    result: list[str] = []
    response_files: list[Path] = []
    seen: set[Path] = set()

    def visit(items: list[str], base: Path, depth: int) -> None:
        for token in items:
            rsp = _response_path(token, base)
            if (
                rsp is None
                or depth >= max_depth
                or rsp in seen
                or not rsp.is_file()
            ):
                result.append(token)
                continue
            seen.add(rsp)
            response_files.append(rsp)
            visit(_read_rsp_tokens(rsp), rsp.parent, depth + 1)

    visit(tokens, cwd, 0)
    return result, response_files


def _compiler_environment(
    tokens: list[str],
    cwd: Path,
) -> tuple[list[str], list[str], list[str]]:
    includes: list[str] = []
    defines: list[str] = []
    forced: list[str] = []

    i = 0
    while i < len(tokens):
        token = _strip_quotes(tokens[i])
        upper = token.upper()
        value = None
        kind = None

        for prefix, label in (
            ("/I", "include"),
            ("-I", "include"),
            ("/D", "define"),
            ("-D", "define"),
            ("/FI", "forced"),
        ):
            if upper.startswith(prefix.upper()):
                kind = label
                value = _strip_quotes(token[len(prefix):])
                if not value and i + 1 < len(tokens):
                    i += 1
                    value = _strip_quotes(tokens[i])
                break

        if value is not None:
            if kind in {"include", "forced"}:
                p = Path(value)
                if not p.is_absolute():
                    p = cwd / p
                value = _norm(p).as_posix()
            if kind == "include":
                includes.append(value)
            elif kind == "define":
                defines.append(value)
            else:
                forced.append(value)
        i += 1

    return includes, defines, forced


def load_compile_commands(
    compile_db: Path,
    project: Path,
    owned_files: set[Path],
) -> tuple[list[dict], list[dict]]:
    project_root = project.parent
    try:
        data = json.loads(
            compile_db.read_text(encoding="utf-8-sig")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"invalid compile database {compile_db}: {exc}"
        ) from exc
    if not isinstance(data, list):
        raise RuntimeError(
            f"compile database root is not an array: {compile_db}"
        )

    rows: list[dict] = []
    diagnostics: list[dict] = []
    for index, entry in enumerate(data):
        if not isinstance(entry, dict):
            continue
        source = _resolve_compile_file(entry)
        if source is None or source not in owned_files:
            continue
        directory = _norm(
            Path(str(entry.get("directory", project_root)))
        )
        tokens = _command_tokens(entry)
        expanded, rsp_files = _expand_response_tokens(
            tokens,
            directory,
        )
        includes, defines, forced = _compiler_environment(
            expanded,
            directory,
        )
        command = str(entry.get("command", "") or "")
        if not command and isinstance(entry.get("arguments"), list):
            command = subprocess.list2cmdline(
                [str(x) for x in entry["arguments"]]
            )

        rows.append(
            {
                "source_path": _display_path(source, project_root),
                "compile_index": index,
                "directory": directory.as_posix(),
                "command": command,
                "compiler": _strip_quotes(tokens[0]) if tokens else "",
                "response_files": [
                    _display_path(p, project_root)
                    for p in rsp_files
                ],
                "include_paths": includes,
                "definitions": defines,
                "forced_includes": forced,
                "evidence": "ubt_generate_clang_database",
            }
        )

    if not rows:
        diagnostics.append(
            {
                "kind": "compile_database_filter",
                "severity": "warning",
                "message": (
                    "compile database contained no project-owned "
                    "source translation units"
                ),
                "compile_database": compile_db.as_posix(),
            }
        )
    return rows, diagnostics


def _mask_noncode(text: str) -> str:
    out = list(text)
    i = 0
    n = len(out)
    state = "code"
    quote = ""
    while i < n:
        c = out[i]
        nxt = out[i + 1] if i + 1 < n else ""
        if state == "code":
            if c == "/" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "line_comment"
                continue
            if c == "/" and nxt == "*":
                out[i] = out[i + 1] = " "
                i += 2
                state = "block_comment"
                continue
            if c in ('"', "'"):
                quote = c
                out[i] = " "
                i += 1
                state = "string"
                continue
            i += 1
            continue
        if state == "line_comment":
            if c == "\n":
                state = "code"
            else:
                out[i] = " "
            i += 1
            continue
        if state == "block_comment":
            if c == "*" and nxt == "/":
                out[i] = out[i + 1] = " "
                i += 2
                state = "code"
            else:
                if c != "\n":
                    out[i] = " "
                i += 1
            continue
        if state == "string":
            if c == "\\":
                out[i] = " "
                if i + 1 < n and out[i + 1] != "\n":
                    out[i + 1] = " "
                i += 2
                continue
            if c == quote:
                out[i] = " "
                i += 1
                state = "code"
                continue
            if c != "\n":
                out[i] = " "
            i += 1
    return "".join(out)


def _line_col(text: str, offset: int) -> tuple[int, int]:
    line = text.count("\n", 0, offset) + 1
    last = text.rfind("\n", 0, offset)
    return line, offset - last


def _matching_brace(
    masked: str,
    open_index: int,
) -> int | None:
    depth = 0
    for i in range(open_index, len(masked)):
        c = masked[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def _split_parameters(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    paren = bracket = brace = angle = 0
    for i, c in enumerate(text):
        if c == "(":
            paren += 1
        elif c == ")":
            paren = max(paren - 1, 0)
        elif c == "[":
            bracket += 1
        elif c == "]":
            bracket = max(bracket - 1, 0)
        elif c == "{":
            brace += 1
        elif c == "}":
            brace = max(brace - 1, 0)
        elif c == "<":
            angle += 1
        elif c == ">" and angle:
            angle -= 1
        elif (
            c == ","
            and not (paren or bracket or brace or angle)
        ):
            parts.append(text[start:i].strip())
            start = i + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _parameter_name(spelling: str) -> str:
    no_default = spelling.split("=", 1)[0].strip()
    ids = re.findall(r"[A-Za-z_]\w*", no_default)
    for token in reversed(ids):
        if token not in _TYPE_WORDS:
            return token
    return ""


_FUNCTION_RE = re.compile(
    r"""(?mx)
    ^[ \t]*
    (?P<prefix>
        (?:[A-Za-z_~][\w:\<\>\,\*&\s\[\]\(\)\.]*?)
    )
    (?P<name>[A-Za-z_~]\w*(?:::[A-Za-z_~]\w*)*)
    [ \t]*\(
    (?P<params>[^;{}]*)
    \)
    (?P<suffix>[ \t]*(?:const\b|noexcept\b(?:\s*\([^)]*\))?|override\b|final\b|requires\b[^{;]*)*)[ \t]*
    (?P<term>[{;])
    """
)

_TYPE_RE = re.compile(
    r"""(?mx)
    ^[ \t]*
    (?P<prefix>typedef[ \t]+)?
    (?P<kind>struct|class|union|enum(?:[ \t]+class)?)
    [ \t]+
    (?P<name>[A-Za-z_]\w*)
    """
)


def scan_lexical_file(
    source: Path,
    module: ModuleRoot,
    project_root: Path,
) -> tuple[
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
]:
    data = source.read_bytes()
    text = data.decode("utf-8-sig", errors="replace")
    masked = _mask_noncode(text)
    source_path = _display_path(source, project_root)

    includes: list[dict] = []
    defines: list[dict] = []
    symbols: list[dict] = []
    parameters: list[dict] = []
    calls: list[dict] = []

    for line_no, line in enumerate(text.splitlines(), 1):
        m = re.match(
            r'^\s*#\s*include\s*([<"])([^>"]+)[>"]',
            line,
        )
        if m:
            includes.append(
                {
                    "source_path": source_path,
                    "module_name": module.name,
                    "line": line_no,
                    "include_kind": (
                        "system" if m.group(1) == "<" else "local"
                    ),
                    "spelling": m.group(2).strip(),
                    "evidence": "lexical_preprocessor",
                }
            )
        m = re.match(
            r"^\s*#\s*define\s+([A-Za-z_]\w*)"
            r"(\s*\(([^)]*)\))?\s*(.*)$",
            line,
        )
        if m:
            defines.append(
                {
                    "source_path": source_path,
                    "module_name": module.name,
                    "line": line_no,
                    "name": m.group(1),
                    "function_like": bool(m.group(2)),
                    "parameters": [
                        x.strip()
                        for x in (m.group(3) or "").split(",")
                        if x.strip()
                    ],
                    "replacement": (m.group(4) or "").strip(),
                    "evidence": "lexical_preprocessor",
                }
            )

    occupied_function_offsets: set[int] = set()
    function_ranges: list[tuple[int, int, str]] = []

    for m in _TYPE_RE.finditer(masked):
        kind = m.group("kind").replace(" ", "_")
        name = m.group("name")
        line, column = _line_col(text, m.start("name"))
        symbol_id = _sha256_text(
            f"{module.name}|{source_path}|{kind}|{name}|"
            f"{line}|{column}"
        )[:24]
        symbols.append(
            {
                "symbol_id": symbol_id,
                "source_path": source_path,
                "module_name": module.name,
                "kind": kind,
                "name": name,
                "qualified_name": name,
                "declaration_kind": "declaration",
                "line": line,
                "column": column,
                "signature": text[m.start():m.end()].strip(),
                "evidence": "lexical_source",
            }
        )

    for m in _FUNCTION_RE.finditer(masked):
        name = m.group("name")
        short_name = name.rsplit("::", 1)[-1]
        if short_name in _CONTROL_NAMES:
            continue
        prefix = re.sub(
            r"\s+",
            " ",
            text[m.start("prefix"):m.end("prefix")],
        ).strip()
        prefix_words = re.findall(r"[A-Za-z_]\w*", prefix)
        if prefix_words and prefix_words[0] in _CONTROL_NAMES:
            continue
        if any(op in prefix for op in ("=", "->", ".")):
            continue
        if (
            not prefix
            and "::" not in name
            and not name.startswith("~")
        ):
            continue

        line, column = _line_col(text, m.start("name"))
        term = m.group("term")
        declaration_kind = (
            "definition" if term == "{" else "declaration"
        )
        signature_end = m.start("term")
        signature = re.sub(
            r"\s+",
            " ",
            text[m.start():signature_end],
        ).strip()
        symbol_id = _sha256_text(
            f"{module.name}|{source_path}|function|{name}|"
            f"{line}|{column}|{signature}"
        )[:24]
        if term == "{":
            body_end = _matching_brace(
                masked,
                m.start("term"),
            )
            if body_end is not None:
                function_ranges.append(
                    (m.start("term"), body_end, symbol_id)
                )
        occupied_function_offsets.add(m.start("name"))
        symbols.append(
            {
                "symbol_id": symbol_id,
                "source_path": source_path,
                "module_name": module.name,
                "kind": "function",
                "name": short_name,
                "qualified_name": name,
                "declaration_kind": declaration_kind,
                "line": line,
                "column": column,
                "signature": signature,
                "return_spelling": prefix,
                "suffix_spelling": re.sub(
                    r"\s+",
                    " ",
                    m.group("suffix") or "",
                ).strip(),
                "evidence": "lexical_source",
            }
        )

        raw_params = text[
            m.start("params"):m.end("params")
        ]
        param_parts = (
            []
            if raw_params.strip() in {"", "void"}
            else _split_parameters(raw_params)
        )
        search_offset = m.start("params")
        for index, spelling in enumerate(param_parts):
            pname = _parameter_name(spelling)
            type_spelling = spelling
            if pname:
                type_spelling = re.sub(
                    rf"\b{re.escape(pname)}\b"
                    r"(?=\s*(?:=|$|\[))",
                    "",
                    spelling,
                ).strip()
            param_pos = text.find(
                spelling,
                search_offset,
                m.end("params"),
            )
            if param_pos < 0:
                param_pos = search_offset
            pline, pcol = _line_col(text, param_pos)
            parameters.append(
                {
                    "function_symbol_id": symbol_id,
                    "source_path": source_path,
                    "module_name": module.name,
                    "parameter_index": index,
                    "name": pname,
                    "type_spelling": type_spelling,
                    "spelling": spelling,
                    "line": pline,
                    "column": pcol,
                    "evidence": "lexical_source",
                }
            )
            search_offset = max(
                param_pos + len(spelling),
                search_offset,
            )

    call_re = re.compile(
        r"\b([A-Za-z_]\w*(?:::[A-Za-z_]\w*)*)\s*\("
    )
    for start, end, caller_id in function_ranges:
        body = masked[start + 1:end]
        base = start + 1
        for cm in call_re.finditer(body):
            absolute = base + cm.start(1)
            callee = cm.group(1)
            short = callee.rsplit("::", 1)[-1]
            if (
                short in _CONTROL_NAMES
                or absolute in occupied_function_offsets
            ):
                continue
            line, column = _line_col(text, absolute)
            calls.append(
                {
                    "caller_symbol_id": caller_id,
                    "source_path": source_path,
                    "module_name": module.name,
                    "callee_spelling": callee,
                    "line": line,
                    "column": column,
                    "resolution": "lexical_unresolved",
                    "evidence": "lexical_source",
                }
            )

    return includes, defines, symbols, parameters, calls


def validation_error(output: Path) -> str:
    output = _norm(output)
    manifest_path = output / "source_manifest.json"
    if not manifest_path.is_file():
        return "source_manifest.json missing"
    try:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return f"invalid source_manifest.json: {exc}"
    if int(manifest.get("schema_version", 0) or 0) != SCHEMA_VERSION:
        return f"expected source schema {SCHEMA_VERSION}"
    if not bool(manifest.get("success", False)):
        return f"source capture failed: {manifest.get('error', '')}"
    counts = manifest.get("counts", {})
    if not isinstance(counts, dict):
        return "counts missing"
    for filename in RAW_FILES:
        path = output / filename
        if not path.is_file():
            return f"{filename} missing"
        actual = sum(
            1
            for line in path.read_text(
                encoding="utf-8"
            ).splitlines()
            if line.strip()
        )
        key = filename.removesuffix(".jsonl")
        if int(counts.get(key, -1)) != actual:
            return (
                f"count mismatch for {key}: "
                f"manifest={counts.get(key)} actual={actual}"
            )
    return ""


def capture(
    project: Path,
    editor: Path,
    output: Path,
    *,
    configuration: str = "DebugGame",
    generate_compile_database: bool = True,
) -> dict:
    project = _norm(project)
    editor = _norm(editor)
    output = _norm(output)
    if (
        not project.is_file()
        or project.suffix.lower() != ".uproject"
    ):
        raise RuntimeError(f"uproject not found: {project}")
    if not editor.is_file():
        raise RuntimeError(f"editor not found: {editor}")

    output.mkdir(parents=True, exist_ok=True)
    project_root = project.parent
    modules = discover_modules(project)
    source_files = discover_source_files(project, modules)
    owned_set = {row[0] for row in source_files}

    diagnostics: list[dict] = []
    compile_db = _find_existing_compile_database(
        project,
        editor,
    )
    if generate_compile_database:
        compile_db, generation_record = (
            _run_generate_clang_database(
                project,
                editor,
                configuration,
            )
        )
        diagnostics.append(generation_record)
    elif compile_db is None:
        diagnostics.append(
            {
                "kind": "compile_database_generation",
                "attempted": False,
                "success": False,
                "message": (
                    "compile database generation disabled and no "
                    "existing compile_commands.json found"
                ),
            }
        )

    compile_rows: list[dict] = []
    if compile_db is not None:
        try:
            compile_rows, compile_diags = load_compile_commands(
                compile_db,
                project,
                owned_set,
            )
            diagnostics.extend(compile_diags)
        except RuntimeError as exc:
            diagnostics.append(
                {
                    "kind": "compile_database_load",
                    "severity": "warning",
                    "message": str(exc),
                }
            )

    file_rows: list[dict] = []
    include_rows: list[dict] = []
    define_rows: list[dict] = []
    symbol_rows: list[dict] = []
    parameter_rows: list[dict] = []
    call_rows: list[dict] = []

    for source, module, language in source_files:
        data = source.read_bytes()
        text = data.decode("utf-8-sig", errors="replace")
        file_rows.append(
            {
                "source_path": _display_path(
                    source,
                    project_root,
                ),
                "module_name": module.name,
                "owner_kind": module.owner_kind,
                "owner_name": module.owner_name,
                "build_cs": _display_path(
                    module.build_cs,
                    project_root,
                ),
                "language": language,
                "is_translation_unit": language in {
                    "c",
                    "cpp",
                    "objective_c",
                    "objective_cpp",
                },
                "size_bytes": len(data),
                "line_count": (
                    text.count("\n") + (1 if text else 0)
                ),
                "sha256": _sha256_bytes(data),
            }
        )
        try:
            inc, defs, syms, params, calls = (
                scan_lexical_file(
                    source,
                    module,
                    project_root,
                )
            )
            include_rows.extend(inc)
            define_rows.extend(defs)
            symbol_rows.extend(syms)
            parameter_rows.extend(params)
            call_rows.extend(calls)
        except OSError as exc:
            diagnostics.append(
                {
                    "kind": "source_read",
                    "severity": "warning",
                    "source_path": _display_path(
                        source,
                        project_root,
                    ),
                    "message": str(exc),
                }
            )

    file_rows.sort(
        key=lambda r: (
            r["module_name"],
            r["source_path"],
        )
    )
    compile_rows.sort(
        key=lambda r: (
            r["source_path"],
            r["compile_index"],
        )
    )
    include_rows.sort(
        key=lambda r: (
            r["source_path"],
            r["line"],
            r["spelling"],
        )
    )
    define_rows.sort(
        key=lambda r: (
            r["source_path"],
            r["line"],
            r["name"],
        )
    )
    symbol_rows.sort(
        key=lambda r: (
            r["source_path"],
            r["line"],
            r["column"],
            r["kind"],
            r["name"],
        )
    )
    parameter_rows.sort(
        key=lambda r: (
            r["source_path"],
            r["line"],
            r["parameter_index"],
        )
    )
    call_rows.sort(
        key=lambda r: (
            r["source_path"],
            r["line"],
            r["column"],
            r["callee_spelling"],
        )
    )

    counts = {
        "source_files": _jsonl_write(
            output / "source_files.jsonl",
            file_rows,
        ),
        "source_compile_commands": _jsonl_write(
            output / "source_compile_commands.jsonl",
            compile_rows,
        ),
        "source_includes": _jsonl_write(
            output / "source_includes.jsonl",
            include_rows,
        ),
        "source_defines": _jsonl_write(
            output / "source_defines.jsonl",
            define_rows,
        ),
        "source_symbols": _jsonl_write(
            output / "source_symbols.jsonl",
            symbol_rows,
        ),
        "source_function_parameters": _jsonl_write(
            output / "source_function_parameters.jsonl",
            parameter_rows,
        ),
        "source_calls": _jsonl_write(
            output / "source_calls.jsonl",
            call_rows,
        ),
        "source_diagnostics": _jsonl_write(
            output / "source_diagnostics.jsonl",
            diagnostics,
        ),
    }

    module_rows = [
        {
            "module_name": m.name,
            "module_root": _display_path(
                m.root,
                project_root,
            ),
            "build_cs": _display_path(
                m.build_cs,
                project_root,
            ),
            "owner_kind": m.owner_kind,
            "owner_name": m.owner_name,
        }
        for m in modules
    ]

    compiler_evidence = bool(compile_rows)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pass": "UnrealAssetToolNativeSource",
        "success": True,
        "error": "",
        "capture_scope": (
            "project and project-plugin C/C++ source only; "
            "lexical rows are explicitly non-compiler-resolved, "
            "while compile command rows come from UBT "
            "GenerateClangDatabase"
        ),
        "project": project.as_posix(),
        "configuration": configuration,
        "modules": module_rows,
        "compiler_database": {
            "available": compile_db is not None,
            "path": (
                compile_db.as_posix()
                if compile_db is not None
                else ""
            ),
            "project_owned_translation_units": len(
                compile_rows
            ),
            "compiler_evidence": compiler_evidence,
        },
        "lexical_evidence": {
            "available": True,
            "resolved_symbol_identity": False,
            "call_resolution": "lexical_unresolved",
        },
        "files": list(RAW_FILES),
        "counts": counts,
    }
    (output / "source_manifest.json").write_text(
        json.dumps(
            manifest,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )

    error = validation_error(output)
    if error:
        raise RuntimeError(error)
    return manifest


def print_summary(manifest: dict) -> None:
    counts = manifest.get("counts", {})
    compiler = manifest.get("compiler_database", {})
    print(
        "native source capture complete: "
        f"files={counts.get('source_files', 0)} "
        f"compile_commands={counts.get('source_compile_commands', 0)} "
        f"includes={counts.get('source_includes', 0)} "
        f"defines={counts.get('source_defines', 0)} "
        f"symbols={counts.get('source_symbols', 0)} "
        f"function_parameters="
        f"{counts.get('source_function_parameters', 0)} "
        f"calls={counts.get('source_calls', 0)} "
        f"diagnostics={counts.get('source_diagnostics', 0)}"
    )
    print(
        "compiler evidence: "
        f"available={bool(compiler.get('compiler_evidence', False))} "
        f"project_owned_translation_units="
        f"{compiler.get('project_owned_translation_units', 0)} "
        f"compile_database="
        f"{compiler.get('path', '') or '<none>'}"
    )
    print(
        "lexical function/call rows are fallback evidence "
        "and are not compiler-resolved"
    )
