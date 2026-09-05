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
            brace += 1
        elif t == "}":
            brace = max(0, brace - 1)
        elif t == "[":
            bracket += 1
        elif t == "]":
            bracket = max(0, bracket - 1)
        elif t == "(" and brace == 0 and bracket == 0:
            stack.append(i)
        elif t == ")" and brace == 0 and bracket == 0 and stack:
            left = stack.pop()
            if not stack:
                pairs.append((left, i))
    return pairs


def _name_before_paren(tokens: list[Token], open_index: int) -> tuple[str, int] | None:
    i = open_index - 1
    if i < 0:
        return None
    if tokens[i].kind != "identifier":
        return None
    parts = [tokens[i].text]
    name_start = i
    i -= 1
    while i >= 1 and tokens[i].text == "::" and tokens[i - 1].kind == "identifier":
        parts.insert(0, "::")
        parts.insert(0, tokens[i - 1].text)
        name_start = i - 1
        i -= 2
    if i >= 0 and tokens[i].text == "~":
        parts.insert(0, "~")
        name_start = i
    return "".join(parts), name_start


def _suffix_is_functionish(tokens: list[Token], close_index: int, end: int) -> bool:
    i = close_index + 1
    while i < end:
        text = tokens[i].text
        if text in QUALIFIER_WORDS:
            i += 1
            continue
        if text == "->":
            return True
        if text == "[":
            close = _matching(tokens, i, "[", "]")
            if close is None or close >= end:
                return False
            i = close + 1
            continue
        if tokens[i].kind == "identifier" and text.isupper():
            i += 1
            continue
        return False
    return True


def _function_signature(tokens: list[Token], start: int, end: int, allow_bare: bool = False):
    pairs = _top_level_paren_pairs(tokens, start, end)
    for open_index, close_index in reversed(pairs):
        named = _name_before_paren(tokens, open_index)
        if not named:
            continue
        name, name_start = named
        base_name = name.split("::")[-1].lstrip("~")
        if base_name in CONTROL_WORDS:
            continue
        if not _suffix_is_functionish(tokens, close_index, end):
            continue
        prefix = tokens[start:name_start]
        # A bare macro invocation such as UFUNCTION(...) before a declaration
        # does not become the function name because the real parameter list is
        # the later top-level parenthesis selected above.
        if not prefix and "::" not in name and not allow_bare:
            continue
        return name, name_start, open_index, close_index
    return None


def _split_parameters(tokens: list[Token]) -> list[list[Token]]:
    if not tokens:
        return []
    result: list[list[Token]] = []
    start = 0
    paren = bracket = brace = angle = 0
    for i, token in enumerate(tokens):
        t = token.text
        if t == "(":
            paren += 1
        elif t == ")":
            paren = max(0, paren - 1)
        elif t == "[":
            bracket += 1
        elif t == "]":
            bracket = max(0, bracket - 1)
        elif t == "{":
            brace += 1
        elif t == "}":
            brace = max(0, brace - 1)
        elif t == "<":
            angle += 1
        elif t == ">" and angle:
            angle -= 1
        elif t == "," and not (paren or bracket or brace or angle):
            result.append(tokens[start:i])
            start = i + 1
    result.append(tokens[start:])
    return [part for part in result if part]


def _parameter_row(
    declaration_id: str,
    index: int,
    tokens: list[Token],
) -> dict:
    default_at = next((i for i, t in enumerate(tokens) if t.text == "="), None)
    core = tokens if default_at is None else tokens[:default_at]
    default = [] if default_at is None else tokens[default_at + 1:]
    if len(core) == 1 and core[0].text == "void":
        name = ""
        type_text = "void"
    elif any(t.text == "..." for t in core):
        name = ""
        type_text = "..."
    else:
        name_index = None
        for i in range(len(core) - 1, -1, -1):
            if core[i].kind == "identifier":
                if i > 0 and core[i - 1].text == "::":
                    continue
                name_index = i
                break
        if name_index is None:
            name = ""
            type_text = _tokens_text(core)
        else:
            name = core[name_index].text
            type_tokens = core[:name_index] + core[name_index + 1:]
            type_text = _tokens_text(type_tokens)
            if not type_text:
                # An unnamed single-token parameter type is more likely than a
                # parameter whose type is absent.
                type_text = name
                name = ""
    first = tokens[0]
    last = tokens[-1]
    return {
        "parameter_id": _stable_id(declaration_id, index),
        "declaration_id": declaration_id,
        "parameter_index": index,
        "name": name,
        "type_text": type_text,
        "default_text": _tokens_text(default),
        "variadic": type_text == "...",
        "start_line": first.line,
        "start_column": first.column,
        "end_line": last.line,
        "end_column": last.column + max(0, len(last.text) - 1),
        "evidence_level": EVIDENCE_LEVEL,
    }


def _simple_global(tokens: list[Token], start: int, end: int):
    body = tokens[start:end]
    if not body:
        return None
    if body[0].text in {"typedef", "using", "static_assert"}:
        return None
    if any(t.text in {"(", ")"} for t in body):
        return None
    eq = next((i for i, t in enumerate(body) if t.text == "="), len(body))
    left = body[:eq]
    name_index = None
    for i in range(len(left) - 1, -1, -1):
        if left[i].kind == "identifier":
            name_index = i
            break
    if name_index is None or name_index == 0:
        return None
    name = left[name_index].text
    type_text = _tokens_text(left[:name_index])
    if not type_text:
        return None
    initializer = _tokens_text(body[eq + 1:]) if eq < len(body) else ""
    return name, type_text, initializer


def _type_declaration(tokens: list[Token], start: int, end: int):
    body = tokens[start:end]
    if not body:
        return None
    type_index = next(
        (i for i, token in enumerate(body) if token.text in TYPE_WORDS),
        None,
    )
    if type_index is None:
        return None
    kind = body[type_index].text
    i = type_index + 1
    if kind == "enum" and i < len(body) and body[i].text == "class":
        kind = "enum_class"
        i += 1
    name = ""
    while i < len(body):
        token = body[i]
        if token.kind == "identifier":
            if token.text.endswith("_API"):
                i += 1
                continue
            name = token.text
            break
        i += 1
    return (kind, name, start + type_index) if name else None


def _typedef_declaration(tokens: list[Token], start: int, end: int):
    body = tokens[start:end]
    if not body or body[0].text != "typedef":
        return None
    for i in range(len(body) - 1, 0, -1):
        if body[i].kind == "identifier":
            return body[i].text, _tokens_text(body[1:i])
    return None


def _using_alias(tokens: list[Token], start: int, end: int):
    body = tokens[start:end]
    if len(body) < 3 or body[0].text != "using" or body[1].kind != "identifier":
        return None
    if not any(t.text == "=" for t in body[2:]):
        return None
    eq = next(i for i, t in enumerate(body) if t.text == "=")
    return body[1].text, _tokens_text(body[eq + 1:])


def _call_spelling(tokens: list[Token], name_index: int) -> tuple[str, str]:
    parts = [tokens[name_index].text]
    i = name_index - 1
    kind = "direct_or_macro"
    while i >= 1 and tokens[i].text in {"::", ".", "->"} and tokens[i - 1].kind == "identifier":
        op = tokens[i].text
        parts.insert(0, op)
        parts.insert(0, tokens[i - 1].text)
        if op in {".", "->"}:
            kind = "member_call_syntax"
        elif kind == "direct_or_macro":
            kind = "qualified_call_syntax"
        i -= 2
    return "".join(parts), kind


def _calls_for_function(
    tokens: list[Token],
    body_open: int,
    body_close: int,
    declaration: dict,
    path: str,
    module_name: str,
) -> list[dict]:
    result: list[dict] = []
    i = body_open + 1
    while i < body_close - 1:
        token = tokens[i]
        if token.kind == "identifier" and tokens[i + 1].text == "(":
            if token.text not in CONTROL_WORDS:
                spelling, syntax_kind = _call_spelling(tokens, i)
                call_id = _stable_id(
                    path,
                    declaration["declaration_id"],
                    token.line,
                    token.column,
                    spelling,
                )
                result.append({
                    "call_id": call_id,
                    "module_name": module_name,
                    "path": path,
                    "caller_declaration_id": declaration["declaration_id"],
                    "caller_name": declaration["name"],
                    "callee_spelling": spelling,
                    "syntax_kind": syntax_kind,
                    "start_line": token.line,
                    "start_column": token.column,
                    "resolution": "unresolved_source_syntax",
                    "compiler_resolved": False,
                    "evidence_level": EVIDENCE_LEVEL,
                })
        i += 1
    return result


def _parse_declarations_and_calls(
    tokens: list[Token],
    path: str,
    module_name: str,
    scope_name: str = "",
) -> tuple[list[dict], list[dict], list[dict]]:
    declarations: list[dict] = []
    parameters: list[dict] = []
    calls: list[dict] = []
    i = 0

    def add_decl(kind: str, name: str, start: int, end: int, **extra):
        first = tokens[start]
        last = tokens[max(start, end - 1)]
        qualified_name = extra.pop(
            "qualified_name",
            f"{scope_name}::{name}" if scope_name else name,
        )
        declaration_id = _stable_id(
            path, kind, qualified_name, first.line, first.column
        )
        row = {
            "declaration_id": declaration_id,
            "module_name": module_name,
            "path": path,
            "kind": kind,
            "name": name,
            "qualified_name": qualified_name,
            "start_line": first.line,
            "start_column": first.column,
            "end_line": last.line,
            "end_column": last.column + max(0, len(last.text) - 1),
            "definition": bool(extra.pop("definition", False)),
            "evidence_level": EVIDENCE_LEVEL,
        }
        row.update(extra)
        declarations.append(row)
        return row

    while i < len(tokens):
        if tokens[i].text == ";":
            i += 1
            continue

        # Find the next top-level statement delimiter.
        paren = bracket = 0
        j = i
        delimiter = None
        while j < len(tokens):
            t = tokens[j].text
            if t == "(":
                paren += 1
            elif t == ")":
                paren = max(0, paren - 1)
            elif t == "[":
                bracket += 1
            elif t == "]":
                bracket = max(0, bracket - 1)
            elif paren == 0 and bracket == 0 and t in {";", "{"}:
                delimiter = t
                break
            j += 1
        if delimiter is None:
            break

        if tokens[i].text == "typedef":
            if delimiter == "{":
                type_info = _type_declaration(tokens, i, j)
                body_close = _matching(tokens, j, "{", "}")
                if type_info and body_close is not None:
                    kind, tag_name, type_start = type_info
                    add_decl(
                        kind,
                        tag_name,
                        type_start,
                        body_close + 1,
                        definition=True,
                        type_text=_tokens_text(tokens[type_start:j]),
                    )
                    nested_declarations, nested_parameters, nested_calls = (
                        _parse_declarations_and_calls(
                            tokens[j + 1:body_close],
                            path,
                            module_name,
                            f"{scope_name}::{tag_name}" if scope_name else tag_name,
                        )
                    )
                    declarations.extend(nested_declarations)
                    parameters.extend(nested_parameters)
                    calls.extend(nested_calls)

                    semi = body_close + 1
                    while semi < len(tokens) and tokens[semi].text != ";":
                        semi += 1
                    alias_tokens = tokens[body_close + 1:semi]
                    alias_name = next(
                        (
                            token.text
                            for token in reversed(alias_tokens)
                            if token.kind == "identifier"
                        ),
                        "",
                    )
                    if alias_name:
                        add_decl(
                            "typedef",
                            alias_name,
                            i,
                            semi,
                            type_text=f"{kind} {tag_name}",
                        )
                    i = min(len(tokens), semi + 1)
                    continue
            info = _typedef_declaration(tokens, i, j)
            if info:
                name, type_text = info
                add_decl("typedef", name, i, j, type_text=type_text)
            i = j + 1
            continue

        if tokens[i].text == "using":
            info = _using_alias(tokens, i, j)
            if info:
                name, type_text = info
                add_decl("type_alias", name, i, j, type_text=type_text)
            i = j + 1
            continue

        type_info = _type_declaration(tokens, i, j)
        if type_info:
            kind, name, type_start = type_info
            body_close = _matching(tokens, j, "{", "}") if delimiter == "{" else None
            end = (body_close + 1) if body_close is not None else j
            add_decl(
                kind,
                name,
                type_start,
                max(type_start + 1, end),
                definition=body_close is not None,
                type_text=_tokens_text(tokens[type_start:j]),
            )
            if body_close is not None:
                nested_declarations, nested_parameters, nested_calls = (
                    _parse_declarations_and_calls(
                        tokens[j + 1:body_close],
                        path,
                        module_name,
                        f"{scope_name}::{name}" if scope_name else name,
                    )
                )
                declarations.extend(nested_declarations)
                parameters.extend(nested_parameters)
                calls.extend(nested_calls)
                i = body_close + 1
                if i < len(tokens) and tokens[i].text == ";":
                    i += 1
                continue

        signature = _function_signature(tokens, i, j, allow_bare=bool(scope_name))
        if signature:
            qualified_name, name_start, open_index, close_index = signature
            name = qualified_name.split("::")[-1]
            definition = delimiter == "{"
            end_for_decl = j
            if scope_name and "::" not in qualified_name:
                qualified_name = f"{scope_name}::{qualified_name}"
            row = add_decl(
                "method" if scope_name else "function",
                name,
                i,
                end_for_decl,
                qualified_name=qualified_name,
                definition=definition,
                return_type_text=_tokens_text(tokens[i:name_start]),
                signature_text=_tokens_text(tokens[i:j]),
                parameter_count=0,
            )
            param_parts = _split_parameters(tokens[open_index + 1:close_index])
            if len(param_parts) == 1 and len(param_parts[0]) == 1 and param_parts[0][0].text == "void":
                param_parts = []
            param_rows = [
                _parameter_row(row["declaration_id"], index, part)
                for index, part in enumerate(param_parts)
            ]
            row["parameter_count"] = len(param_rows)
            parameters.extend(param_rows)

            if definition:
                body_close = _matching(tokens, j, "{", "}")
                if body_close is None:
                    i = j + 1
                    continue
                row["body_start_line"] = tokens[j].line
                row["body_end_line"] = tokens[body_close].line
                calls.extend(_calls_for_function(
                    tokens, j, body_close, row, path, module_name
                ))
                i = body_close + 1
                continue
            i = j + 1
            continue

        if delimiter == ";":
            global_info = _simple_global(tokens, i, j)
            if global_info:
                name, type_text, initializer = global_info
                add_decl(
                    "field" if scope_name else "global",
                    name,
                    i,
                    j,
                    type_text=type_text,
                    initializer_text=initializer,
                )
            i = j + 1
            continue

        # Unknown top-level brace construct: skip its balanced body rather than
        # interpreting nested syntax as global declarations.
        body_close = _matching(tokens, j, "{", "}")
        i = (body_close + 1) if body_close is not None else (j + 1)

    declarations.sort(key=lambda r: (r["path"], r["start_line"], r["start_column"], r["kind"], r["name"]))
    parameters.sort(key=lambda r: (r["declaration_id"], r["parameter_index"]))
    calls.sort(key=lambda r: (r["path"], r["start_line"], r["start_column"], r["callee_spelling"]))
    return declarations, parameters, calls


def _include_rows(
    project_dir: Path,
    module_name: str,
    module_root: Path,
    path: Path,
    indexed_paths: set[Path],
) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    result: list[dict] = []
    rel = _relative(project_dir, path)
    public_roots = [module_root / "Public", module_root / "Private", module_root]
    for line_number, line in enumerate(text.splitlines(), 1):
        match = INCLUDE_RE.match(line)
        if not match:
            continue
        opener, target = match.groups()
        form = "angle" if opener == "<" else "quote"
        column = line.find(target) + 1
        resolved = ""
        candidates = [path.parent / target] + [root / target for root in public_roots]
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate in indexed_paths:
                resolved = _relative(project_dir, candidate)
                break
        result.append({
            "include_id": _stable_id(rel, line_number, target, form),
            "module_name": module_name,
            "path": rel,
            "line": line_number,
            "column": max(1, column),
            "target_spelling": target,
            "form": form,
            "resolved_project_path": resolved,
            "resolution": "project_filesystem" if resolved else "unresolved_source_syntax",
            "compiler_resolved": False,
            "evidence_level": EVIDENCE_LEVEL,
        })
    return result


def _reflection_rows(output: Path, filename: str) -> list[dict]:
    return list(_rows(output / filename))


def _reflection_joins(
    project_dir: Path,
    output: Path,
    declarations: list[dict],
) -> list[dict]:
    modules = {str(row.get("module_name", "") or ""): row for row in _module_rows(output)}
    by_key: dict[tuple[str, str, str], list[dict]] = {}
    for row in declarations:
        by_key.setdefault(
            (row.get("module_name", ""), row.get("path", ""), row.get("name", "")),
            [],
        ).append(row)

    joins: list[dict] = []

    def expected_path(module_name: str, module_relative: str) -> str:
        module = modules.get(module_name)
        if not module:
            return ""
        build_cs = str(module.get("build_cs", "") or "")
        if not build_cs or not module_relative:
            return ""
        return (Path(build_cs).parent / Path(module_relative)).as_posix()

    for reflected in _reflection_rows(output, "native_functions.jsonl"):
        module_name = str(reflected.get("module_name", "") or "")
        metadata = reflected.get("metadata") or {}
        rel = str(metadata.get("ModuleRelativePath", "") or "")
        project_path = expected_path(module_name, rel)
        name = str(reflected.get("name", "") or "")
        candidates = by_key.get((module_name, project_path, name), [])
        if len(candidates) != 1:
            continue
        source = candidates[0]
        join_id = _stable_id("function", reflected.get("function_path", ""), source["declaration_id"])
