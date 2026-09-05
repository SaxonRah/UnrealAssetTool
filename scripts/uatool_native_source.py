#!/usr/bin/env python3
"""Project-owned ordinary C/C++ source-syntax capture for native schema 1.

This pass is intentionally lexical/source-level. It records exact source facts
without pretending that overload resolution, macro expansion, or callee binding
has been proven by a compiler.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCHEMA_VERSION = 1
MANIFEST_FILE = "native_source_manifest.json"
PASS_NAME = "UnrealAssetToolNativeSource"
EVIDENCE_LEVEL = "source_syntax"

JSONL_FILES = (
    "native_source_files.jsonl",
    "native_source_includes.jsonl",
    "native_source_declarations.jsonl",
    "native_source_parameters.jsonl",
    "native_source_calls.jsonl",
    "native_source_reflection_joins.jsonl",
)

SOURCE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx",
    ".h", ".hh", ".hpp", ".hxx",
    ".inl", ".inc",
}
SKIP_PARTS = {
    ".git", ".svn", ".vs",
    "Binaries", "DerivedDataCache", "Intermediate", "Saved",
}
CONTROL_WORDS = {
    "if", "for", "while", "switch", "catch", "sizeof", "alignof",
    "decltype", "return", "co_return", "new", "delete", "throw",
    "static_cast", "dynamic_cast", "reinterpret_cast", "const_cast",
}
TYPE_WORDS = {"struct", "class", "union", "enum"}
QUALIFIER_WORDS = {
    "const", "volatile", "override", "final", "noexcept",
    "requires", "&", "&&",
}
MULTI_TOKENS = (
    "->*", ".*", "::", "->", "++", "--", "<<=", ">>=", "==", "!=",
    "<=", ">=", "&&", "||", "<<", ">>", "+=", "-=", "*=", "/=", "%=",
    "&=", "|=", "^=", "...",
)
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
INCLUDE_RE = re.compile(r'^\s*#\s*include\s*([<"])([^>"]+)[>"]')


@dataclass(frozen=True)
class Token:
    text: str
    line: int
    column: int
    start: int
    end: int
    kind: str


def _stable_id(*parts: object) -> str:
    text = "\x1f".join(str(part) for part in parts)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


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


def _relative(project_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(project_dir.resolve()).as_posix()


def _language(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".c":
        return "c"
    if suffix in {".cc", ".cpp", ".cxx"}:
        return "cpp"
    return "c_or_cpp_header"


def _module_rows(output: Path) -> list[dict]:
    return list(_rows(output / "native_modules.jsonl"))


def _module_roots(project_dir: Path, output: Path) -> list[tuple[str, Path, dict]]:
    result: list[tuple[str, Path, dict]] = []
    root = project_dir.resolve()
    for row in _module_rows(output):
        name = str(row.get("module_name", "") or "")
        build_cs = str(row.get("build_cs", "") or "")
        if not name or not build_cs:
            continue
        build_path = (root / Path(build_cs)).resolve()
        try:
            build_path.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"native module escapes project root: {build_cs}") from exc
        module_root = build_path.parent
        if not module_root.is_dir():
            raise RuntimeError(f"native module root missing: {module_root}")
        result.append((name, module_root, row))
    result.sort(key=lambda item: (item[0], item[1].as_posix().lower()))
    return result


def _source_paths(project_dir: Path, output: Path) -> list[tuple[str, Path, Path]]:
    seen: set[Path] = set()
    rows: list[tuple[str, Path, Path]] = []
    for module_name, module_root, _ in _module_roots(project_dir, output):
        for path in sorted(module_root.rglob("*"), key=lambda p: p.as_posix().lower()):
            if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
                continue
            rel_parts = path.relative_to(module_root).parts
            if any(part in SKIP_PARTS for part in rel_parts):
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            rows.append((module_name, module_root, resolved))
    rows.sort(key=lambda item: (_relative(project_dir, item[2]).lower(), item[0]))
    return rows


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    line = 1
    col = 1
    n = len(text)
    line_only_space = True

    def advance(fragment: str) -> tuple[int, int, bool]:
        nonlocal line, col, line_only_space
        for ch in fragment:
            if ch == "\n":
                line += 1
                col = 1
                line_only_space = True
            else:
                if not ch.isspace():
                    line_only_space = False
                col += 1
        return line, col, line_only_space

    while i < n:
        ch = text[i]
        if ch.isspace():
            advance(ch)
            i += 1
            continue

        if ch == "#" and line_only_space:
            j = text.find("\n", i)
            if j < 0:
                j = n
            advance(text[i:j])
            i = j
            continue

        if text.startswith("//", i):
            j = text.find("\n", i + 2)
            if j < 0:
                j = n
            advance(text[i:j])
            i = j
            continue

        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            advance(text[i:j])
            i = j
            continue

        start_line, start_col, start = line, col, i

        if ch in "\"'":
            quote = ch
            j = i + 1
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == quote:
                    j += 1
                    break
                j += 1
            frag = text[i:j]
            tokens.append(Token(frag, start_line, start_col, start, j, "literal"))
            advance(frag)
            i = j
            continue

        match = IDENT_RE.match(text, i)
        if match:
            frag = match.group(0)
            j = match.end()
            tokens.append(Token(frag, start_line, start_col, start, j, "identifier"))
            advance(frag)
            i = j
            continue

        if ch.isdigit():
            j = i + 1
            while j < n and (text[j].isalnum() or text[j] in "._'"):
                j += 1
            frag = text[i:j]
            tokens.append(Token(frag, start_line, start_col, start, j, "number"))
            advance(frag)
            i = j
            continue

        multi = next((op for op in MULTI_TOKENS if text.startswith(op, i)), None)
        if multi:
            j = i + len(multi)
            tokens.append(Token(multi, start_line, start_col, start, j, "punct"))
            advance(multi)
            i = j
            continue

        j = i + 1
        tokens.append(Token(ch, start_line, start_col, start, j, "punct"))
        advance(ch)
        i = j

    return tokens


def _tokens_text(tokens: list[Token]) -> str:
    if not tokens:
        return ""
    out: list[str] = []
    previous = ""
    no_space_before = {",", ";", ")", "]", "}", "::", ".", "->", ">", ":"}
    no_space_after = {"(", "[", "{", "::", ".", "->", "<", "~"}
    for token in tokens:
        text = token.text
        if out and text not in no_space_before and previous not in no_space_after:
            out.append(" ")
        out.append(text)
        previous = text
    return "".join(out).strip()


def _matching(tokens: list[Token], start: int, opener: str, closer: str) -> int | None:
    depth = 0
    for i in range(start, len(tokens)):
        if tokens[i].text == opener:
            depth += 1
        elif tokens[i].text == closer:
            depth -= 1
            if depth == 0:
                return i
    return None


def _top_level_paren_pairs(tokens: list[Token], start: int, end: int) -> list[tuple[int, int]]:
    pairs: list[tuple[int, int]] = []
    stack: list[int] = []
    brace = bracket = 0
    for i in range(start, end):
        t = tokens[i].text
        if t == "{":
