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
DECL_ANNOTATION_MACROS = {
    "UCLASS", "USTRUCT", "UENUM", "UFUNCTION", "UPROPERTY", "GENERATED_BODY",
}
ACCESS_WORDS = {"public", "private", "protected"}
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
            # Preprocessor directives are logical lines. A multiline #define
            # must be skipped through every backslash-continuation line or its
            # body will be misinterpreted as ordinary C/C++ declarations.
            cursor = i
            j = i
            while cursor < n:
                newline = text.find("\n", cursor)
                if newline < 0:
                    j = n
                    break
                physical = text[cursor:newline]
                j = newline + 1
                if not physical.rstrip().endswith("\\"):
                    break
                cursor = newline + 1
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


def _top_level_token_index(tokens: list[Token], target: str) -> int | None:
    paren = bracket = brace = 0
    for i, token in enumerate(tokens):
        text = token.text
        if text == target and not (paren or bracket or brace):
            return i
        if text == "(":
            paren += 1
        elif text == ")":
            paren = max(0, paren - 1)
        elif text == "[":
            bracket += 1
        elif text == "]":
            bracket = max(0, bracket - 1)
        elif text == "{":
            brace += 1
        elif text == "}":
            brace = max(0, brace - 1)
    return None


def _strip_leading_decl_annotations(tokens: list[Token]) -> list[Token]:
    i = 0
    while i < len(tokens):
        if (
            tokens[i].text in DECL_ANNOTATION_MACROS
            and i + 1 < len(tokens)
            and tokens[i + 1].text == "("
        ):
            close = _matching(tokens, i + 1, "(", ")")
            if close is None:
                break
            i = close + 1
            continue
        if (
            tokens[i].text in ACCESS_WORDS
            and i + 1 < len(tokens)
            and tokens[i + 1].text == ":"
        ):
            i += 2
            continue
        break
    return tokens[i:]


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

    # Destructors place '~' between the qualification and the final identifier:
    # MyClass::~MyClass(). Consume it before walking the preceding :: chain so
    # the spelling remains fully qualified and no fake return type is created.
    if i >= 0 and tokens[i].text == "~":
        parts.insert(0, "~")
        name_start = i
        i -= 1

    while i >= 1 and tokens[i].text == "::" and tokens[i - 1].kind == "identifier":
        parts.insert(0, "::")
        parts.insert(0, tokens[i - 1].text)
        name_start = i - 1
        i -= 2
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
        if _top_level_token_index(tokens[start:name_start], "=") is not None:
            # A field/global initializer such as "FName Name = TEXT(...)" is
            # not a declaration of TEXT. Metadata macro arguments may contain
            # '=' too, but those are nested inside parentheses and therefore
            # do not trip this top-level test.
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


def _simple_globals(tokens: list[Token], start: int, end: int) -> list[tuple[str, str, str]]:
    body = _strip_leading_decl_annotations(tokens[start:end])
    if not body:
        return []
    if body[0].text in {"typedef", "using", "static_assert"}:
        return []

    parts = _split_parameters(body)
    if not parts:
        return []

    def declarator_name_index(left: list[Token]) -> int | None:
        # Direct function-pointer declarators are outside this simple-variable
        # path. Reject them rather than guessing.
        if any(t.text in {"(", ")"} for t in left):
            return None

        # Only identifiers at the declarator's outer level can be the variable
        # name. This avoids choosing an array bound such as
        # HRSIM_REGISTRY_KIND_COUNT from "registries[HRSIM_...]".
        bracket = brace = 0
        candidates: list[int] = []
        for index, token in enumerate(left):
            text = token.text
            if text == "[":
                bracket += 1
                continue
            if text == "]":
                bracket = max(0, bracket - 1)
                continue
            if text == "{":
                brace += 1
                continue
            if text == "}":
                brace = max(0, brace - 1)
                continue
            if text == ":" and not (bracket or brace):
                # Bitfield widths can contain identifiers; the declarator name
                # must be before the top-level ':'.
                break
            if token.kind == "identifier" and not (bracket or brace):
                candidates.append(index)
        return candidates[-1] if candidates else None

    def split_decl(part: list[Token]):
        eq_index = _top_level_token_index(part, "=")
        eq = len(part) if eq_index is None else eq_index
        left = part[:eq]
        name_index = declarator_name_index(left)
        if name_index is None:
            return None
        return (
            left,
            name_index,
            part[eq + 1:] if eq < len(part) else [],
        )

    first = split_decl(parts[0])
    if first is None:
        return []
    first_left, first_name_index, first_initializer = first
    if first_name_index == 0:
        return []

    first_prefix = first_left[:first_name_index]
    first_suffix = first_left[first_name_index + 1:]
    # In "char *a, *b", "char" is shared while "*" belongs to each
    # declarator. Keep trailing pointer/reference/cv tokens declarator-local.
    base_end = len(first_prefix)
    while (
        base_end > 0
        and first_prefix[base_end - 1].text in {"*", "&", "&&", "const", "volatile"}
    ):
        base_end -= 1
    shared_type = first_prefix[:base_end]
    first_decl_prefix = first_prefix[base_end:]
    if not shared_type:
        return []

    result = [
        (
            first_left[first_name_index].text,
            _tokens_text(shared_type + first_decl_prefix + first_suffix),
            _tokens_text(first_initializer),
        )
    ]

    for part in parts[1:]:
        parsed = split_decl(part)
        if parsed is None:
            continue
        left, name_index, initializer = parsed
        declarator_prefix = left[:name_index]
        declarator_suffix = left[name_index + 1:]
        result.append(
            (
                left[name_index].text,
                _tokens_text(shared_type + declarator_prefix + declarator_suffix),
                _tokens_text(initializer),
            )
        )
    return result


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

    # Function-pointer typedefs must take the identifier from the declarator,
    # not from the final parameter name:
    #   typedef void (*HRSimEventCallback)(..., void *userdata);
    for i in range(1, len(body) - 3):
        if body[i].text != "(":
            continue
        close = _matching(body, i, "(", ")")
        if close is None:
            continue
        star = next(
            (j for j in range(i + 1, close) if body[j].text == "*"),
            None,
        )
        if star is None:
            continue
        alias_index = next(
            (
                j
                for j in range(star + 1, close)
                if body[j].kind == "identifier"
            ),
            None,
        )
        if alias_index is None:
            continue
        name = body[alias_index].text
        type_tokens = body[1:alias_index] + body[alias_index + 1:]
        return name, _tokens_text(type_tokens)

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
    scope_kind: str = "global",
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

        if (
            tokens[i].kind == "identifier"
            and re.search(r"(?:^|_)EXTERN_C_(?:BEGIN|END)$", tokens[i].text)
        ):
            # Portable C headers commonly wrap declarations in macro sentinels
            # such as HRSIM_EXTERN_C_BEGIN / HRSIM_EXTERN_C_END. Without macro
            # expansion the BEGIN token otherwise becomes a fake type prefix
            # on the following typedef. Treat these source-level linkage
            # sentinels as transparent boundaries.
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

        if (
            tokens[i].text == "extern"
            and delimiter == "{"
            and i + 1 < j
            and tokens[i + 1].kind == "literal"
        ):
            body_close = _matching(tokens, j, "{", "}")
            if body_close is None:
                i = j + 1
                continue
            linkage = tokens[i + 1].text.strip("\"'")
            linkage_name = f"extern_{linkage}" if linkage else "extern"
            add_decl(
                "linkage_block",
                linkage_name,
                i,
                j,
                definition=True,
                language_linkage=linkage,
            )
            nested_declarations, nested_parameters, nested_calls = (
                _parse_declarations_and_calls(
                    tokens[j + 1:body_close],
                    path,
                    module_name,
                    scope_name,
                    scope_kind,
                )
            )
            declarations.extend(nested_declarations)
            parameters.extend(nested_parameters)
            calls.extend(nested_calls)
            i = body_close + 1
            continue

        if tokens[i].text == "namespace" and delimiter == "{":
            body_close = _matching(tokens, j, "{", "}")
            if body_close is None:
                i = j + 1
                continue
            namespace_text = _tokens_text(tokens[i + 1:j]).strip()
            namespace_name = namespace_text or f"<anonymous@{tokens[i].line}>"
            qualified_namespace = (
                f"{scope_name}::{namespace_name}" if scope_name else namespace_name
            )
            add_decl(
                "namespace",
                namespace_name,
                i,
                j,
                qualified_name=qualified_namespace,
                definition=True,
            )
            nested_declarations, nested_parameters, nested_calls = (
                _parse_declarations_and_calls(
                    tokens[j + 1:body_close],
                    path,
                    module_name,
                    qualified_namespace,
                    "namespace",
                )
            )
            declarations.extend(nested_declarations)
            parameters.extend(nested_parameters)
            calls.extend(nested_calls)
            i = body_close + 1
            continue

        if tokens[i].text == "typedef":
            if delimiter == "{":
                body_close = _matching(tokens, j, "{", "}")
                prefix = tokens[i:j]
                type_local_index = next(
                    (
                        index
                        for index, token in enumerate(prefix)
                        if token.text in TYPE_WORDS
                    ),
                    None,
                )
                if body_close is not None and type_local_index is not None:
                    kind = prefix[type_local_index].text
                    type_start = i + type_local_index
                    after_type = type_local_index + 1
                    if (
                        kind == "enum"
                        and after_type < len(prefix)
                        and prefix[after_type].text == "class"
                    ):
                        kind = "enum_class"
                        after_type += 1

                    tag_name = ""
                    for token in prefix[after_type:]:
                        if token.kind == "identifier":
                            if token.text.endswith("_API"):
                                continue
                            tag_name = token.text
                            break

                    semi = body_close + 1
                    while semi < len(tokens) and tokens[semi].text != ";":
                        semi += 1

                    alias_parts = _split_parameters(tokens[body_close + 1:semi])
                    alias_names: list[str] = []
                    for part in alias_parts:
                        alias_name = next(
                            (
                                token.text
                                for token in reversed(part)
                                if token.kind == "identifier"
                            ),
                            "",
                        )
                        if alias_name:
                            alias_names.append(alias_name)

                    anonymous = not bool(tag_name)
                    type_name = (
                        tag_name
                        if tag_name
                        else f"<anonymous@{tokens[type_start].line}>"
                    )
                    type_row = add_decl(
                        kind,
                        type_name,
                        type_start,
                        body_close + 1,
                        definition=True,
                        type_text=_tokens_text(tokens[type_start:j]),
                        anonymous=anonymous,
                        typedef_aliases=alias_names,
                    )

                    if kind in {"struct", "class", "union"}:
                        record_scope = (
                            alias_names[0]
                            if alias_names
                            else tag_name
                            if tag_name
                            else type_name
                        )
                        if scope_name:
                            record_scope = f"{scope_name}::{record_scope}"
                        nested_declarations, nested_parameters, nested_calls = (
                            _parse_declarations_and_calls(
                                tokens[j + 1:body_close],
                                path,
                                module_name,
                                record_scope,
                                "record",
                            )
                        )
                        declarations.extend(nested_declarations)
                        parameters.extend(nested_parameters)
                        calls.extend(nested_calls)

                    for alias_name in alias_names:
                        alias_row = add_decl(
                            "typedef",
                            alias_name,
                            i,
                            semi,
                            type_text=(
                                f"{kind} {tag_name}".strip()
                                if tag_name
                                else kind
                            ),
                            target_declaration_id=type_row["declaration_id"],
                            anonymous_target=anonymous,
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
                        "record",
                    )
                )
                declarations.extend(nested_declarations)
                parameters.extend(nested_parameters)
                calls.extend(nested_calls)
                i = body_close + 1
                if i < len(tokens) and tokens[i].text == ";":
                    i += 1
                continue

            # A forward declaration such as "class UFoo;" or "struct Bar;"
            # is complete here. Do not let it fall through into ordinary
            # variable parsing, which would fabricate a global named UFoo/Bar.
            i = j + 1
            continue

        signature = _function_signature(tokens, i, j, allow_bare=bool(scope_name))
        if signature:
            qualified_name, name_start, open_index, close_index = signature
            name = qualified_name.split("::")[-1]
            definition = delimiter == "{"
            end_for_decl = j
            if scope_name and "::" not in qualified_name:
                qualified_name = f"{scope_name}::{qualified_name}"
            clean_prefix = _strip_leading_decl_annotations(tokens[i:name_start])
            row = add_decl(
                "method" if scope_kind == "record" else "function",
                name,
                i,
                end_for_decl,
                qualified_name=qualified_name,
                definition=definition,
                return_type_text=_tokens_text(clean_prefix),
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
            for name, type_text, initializer in _simple_globals(tokens, i, j):
                add_decl(
                    "field" if scope_kind == "record" else "global",
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
        resolution = "unresolved_source_syntax"
        candidates = [path.parent / target] + [root / target for root in public_roots]
        for candidate in candidates:
            candidate = candidate.resolve()
            if candidate in indexed_paths:
                resolved = _relative(project_dir, candidate)
                resolution = "project_filesystem"
                break

        if not resolved:
            normalized_target = target.replace("\\", "/").lstrip("./")
            suffix = "/" + normalized_target
            suffix_matches = sorted(
                (
                    candidate
                    for candidate in indexed_paths
                    if candidate.as_posix().endswith(suffix)
                ),
                key=lambda candidate: candidate.as_posix().lower(),
            )
            if len(suffix_matches) == 1:
                resolved = _relative(project_dir, suffix_matches[0])
                resolution = "project_unique_suffix"

        result.append({
            "include_id": _stable_id(rel, line_number, target, form),
            "module_name": module_name,
            "path": rel,
            "line": line_number,
            "column": max(1, column),
            "target_spelling": target,
            "form": form,
            "resolved_project_path": resolved,
            "resolution": resolution,
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
    function_kinds = {"function", "method"}
    reflected_type_kinds = {"class", "struct", "union"}
    enum_kinds = {"enum", "enum_class"}

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
        candidates = [
            row
            for row in by_key.get((module_name, project_path, name), [])
            if row.get("kind") in function_kinds
        ]
        if len(candidates) != 1:
            continue
        source = candidates[0]
        join_id = _stable_id("function", reflected.get("function_path", ""), source["declaration_id"])
        joins.append({
            "join_id": join_id,
            "join_kind": "reflected_function_source_declaration",
            "module_name": module_name,
            "reflected_path": reflected.get("function_path", ""),
            "source_declaration_id": source["declaration_id"],
            "source_path": source["path"],
            "source_line": source["start_line"],
            "proof": "module_relative_path+symbol_name+unique_source_candidate",
            "evidence_level": "exact_join",
        })

    for reflected in _reflection_rows(output, "native_types.jsonl"):
        module_name = str(reflected.get("module_name", "") or "")
        metadata = reflected.get("metadata") or {}
        rel = str(metadata.get("ModuleRelativePath", "") or "")
        project_path = expected_path(module_name, rel)
        name = str(
            reflected.get("cpp_name", "")
            or reflected.get("name", "")
            or ""
        )
        candidates = [
            row
            for row in by_key.get((module_name, project_path, name), [])
            if row.get("kind") in reflected_type_kinds
        ]
        if len(candidates) != 1:
            continue
        source = candidates[0]
        join_id = _stable_id("type", reflected.get("type_path", ""), source["declaration_id"])
        joins.append({
            "join_id": join_id,
            "join_kind": "reflected_type_source_declaration",
            "module_name": module_name,
            "reflected_path": reflected.get("type_path", ""),
            "source_declaration_id": source["declaration_id"],
            "source_path": source["path"],
            "source_line": source["start_line"],
            "proof": "module_relative_path+symbol_name+unique_source_candidate",
            "evidence_level": "exact_join",
        })

    for reflected in _reflection_rows(output, "native_enums.jsonl"):
        module_name = str(reflected.get("module_name", "") or "")
        metadata = reflected.get("metadata") or {}
        rel = str(metadata.get("ModuleRelativePath", "") or "")
        project_path = expected_path(module_name, rel)
        name = str(
            reflected.get("cpp_type", "")
            or reflected.get("name", "")
            or ""
        )
        candidates = [
            row
            for row in by_key.get((module_name, project_path, name), [])
            if row.get("kind") in enum_kinds
        ]
        if len(candidates) != 1:
            continue
        source = candidates[0]
        join_id = _stable_id(
            "enum", reflected.get("enum_path", ""), source["declaration_id"]
        )
        joins.append({
            "join_id": join_id,
            "join_kind": "reflected_enum_source_declaration",
            "module_name": module_name,
            "reflected_path": reflected.get("enum_path", ""),
            "source_declaration_id": source["declaration_id"],
            "source_path": source["path"],
            "source_line": source["start_line"],
            "proof": "module_relative_path+cpp_symbol_name+unique_source_candidate",
            "evidence_level": "exact_join",
        })

    joins.sort(key=lambda row: (row["join_kind"], row["reflected_path"], row["source_path"]))
    return joins


def capture(project_dir: Path, output: Path) -> dict:
    project_dir = Path(project_dir).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    native_manifest = output / "native_manifest.json"
    if not native_manifest.is_file():
        raise RuntimeError("native_manifest.json is required before native source capture")

    file_specs = _source_paths(project_dir, output)
    indexed_paths = {path for _, _, path in file_specs}

    file_rows: list[dict] = []
    include_rows: list[dict] = []
    declaration_rows: list[dict] = []
    parameter_rows: list[dict] = []
    call_rows: list[dict] = []

    for module_name, module_root, path in file_specs:
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        rel = _relative(project_dir, path)
        file_rows.append({
            "module_name": module_name,
            "path": rel,
            "module_relative_path": path.relative_to(module_root).as_posix(),
            "language": _language(path),
            "size": len(raw),
            "line_count": len(text.splitlines()),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "evidence_level": EVIDENCE_LEVEL,
        })
        include_rows.extend(_include_rows(
            project_dir, module_name, module_root, path, indexed_paths
        ))
        declarations, parameters, calls = _parse_declarations_and_calls(
            tokenize(text), rel, module_name
        )
        declaration_rows.extend(declarations)
        parameter_rows.extend(parameters)
        call_rows.extend(calls)

    file_rows.sort(key=lambda row: (row["path"], row["module_name"]))
    include_rows.sort(key=lambda row: (row["path"], row["line"], row["column"], row["target_spelling"]))
    declaration_rows.sort(key=lambda row: (row["path"], row["start_line"], row["start_column"], row["kind"], row["name"]))
    parameter_rows.sort(key=lambda row: (row["declaration_id"], row["parameter_index"]))
    call_rows.sort(key=lambda row: (row["path"], row["start_line"], row["start_column"], row["callee_spelling"]))
    join_rows = _reflection_joins(project_dir, output, declaration_rows)

    streams = {
        "native_source_files.jsonl": file_rows,
        "native_source_includes.jsonl": include_rows,
        "native_source_declarations.jsonl": declaration_rows,
        "native_source_parameters.jsonl": parameter_rows,
        "native_source_calls.jsonl": call_rows,
        "native_source_reflection_joins.jsonl": join_rows,
    }
    counts = {
        "files": len(file_rows),
        "includes": len(include_rows),
        "declarations": len(declaration_rows),
        "parameters": len(parameter_rows),
        "calls": len(call_rows),
        "reflection_joins": len(join_rows),
    }
    for filename, rows in streams.items():
        _write_jsonl(output / filename, rows)

    modules = [str(row.get("module_name", "") or "") for row in _module_rows(output)]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "pass": PASS_NAME,
        "success": True,
        "error": "",
        "evidence_level": EVIDENCE_LEVEL,
        "compiler_resolved": False,
        "capture_scope": (
            "project and project-plugin C/C++ source syntax under native module roots; "
            "compiler overload/callee resolution is not claimed"
        ),
        "files": list(JSONL_FILES),
        "modules": sorted(name for name in modules if name),
        "counts": counts,
    }
    (output / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


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
        return f"expected native source schema {SCHEMA_VERSION}, got {manifest.get('schema_version')}"
    if manifest.get("pass") != PASS_NAME:
        return f"unexpected native source pass {manifest.get('pass')!r}"
    if not bool(manifest.get("success", False)):
        return f"native source scanner failed: {manifest.get('error', '')}"
    if manifest.get("evidence_level") != EVIDENCE_LEVEL:
        return "native source manifest evidence level is not source_syntax"
    if bool(manifest.get("compiler_resolved", True)):
        return "native source schema 1 must not claim compiler resolution"
    if tuple(manifest.get("files", [])) != JSONL_FILES:
        return f"native source manifest file list does not match schema {SCHEMA_VERSION}"

    count_keys = {
        "native_source_files.jsonl": "files",
        "native_source_includes.jsonl": "includes",
        "native_source_declarations.jsonl": "declarations",
        "native_source_parameters.jsonl": "parameters",
        "native_source_calls.jsonl": "calls",
        "native_source_reflection_joins.jsonl": "reflection_joins",
    }
    counts = manifest.get("counts", {})
    if not isinstance(counts, dict):
        return "native source manifest counts missing or invalid"

    for filename in JSONL_FILES:
        path = output / filename
        if not path.is_file():
            return f"native source stream missing: {filename}"
        rows = list(_rows(path))
        key = count_keys[filename]
        if int(counts.get(key, -1)) != len(rows):
            return (
                f"native source count mismatch for {key}: "
                f"manifest={counts.get(key)} actual={len(rows)}"
            )

    files = list(_rows(output / "native_source_files.jsonl"))
    if len({row.get("path") for row in files}) != len(files):
        return "duplicate native source file path"
    file_paths = {str(row.get("path", "") or "") for row in files}

    includes = list(_rows(output / "native_source_includes.jsonl"))
    if len({row.get("include_id") for row in includes}) != len(includes):
        return "duplicate native source include id"
    for row in includes:
        if row.get("evidence_level") != EVIDENCE_LEVEL:
            return "native source include mislabeled evidence level"
        if bool(row.get("compiler_resolved", True)):
            return "native source include incorrectly claims compiler resolution"
        if row.get("path") not in file_paths:
            return "native source include references unknown source file"
        resolved = str(row.get("resolved_project_path", "") or "")
        if resolved and resolved not in file_paths:
            return "native source include resolves outside indexed source files"

    declarations = list(_rows(output / "native_source_declarations.jsonl"))
    if len({row.get("declaration_id") for row in declarations}) != len(declarations):
        return "duplicate native source declaration id"
    if any(row.get("evidence_level") != EVIDENCE_LEVEL for row in declarations):
        return "native source declaration mislabeled evidence level"
    declaration_ids = {
        str(row.get("declaration_id", "") or "")
        for row in declarations
    }

    parameters = list(_rows(output / "native_source_parameters.jsonl"))
    if len({row.get("parameter_id") for row in parameters}) != len(parameters):
        return "duplicate native source parameter id"
    for row in parameters:
        if row.get("evidence_level") != EVIDENCE_LEVEL:
            return "native source parameter mislabeled evidence level"
        if row.get("declaration_id") not in declaration_ids:
            return "native source parameter references unknown declaration"

    calls = list(_rows(output / "native_source_calls.jsonl"))
    if len({row.get("call_id") for row in calls}) != len(calls):
        return "duplicate native source call id"
    for row in calls:
        if row.get("evidence_level") != EVIDENCE_LEVEL:
            return "native source call mislabeled evidence level"
        if bool(row.get("compiler_resolved", True)):
            return "native source call incorrectly claims compiler resolution"
        if row.get("resolution") != "unresolved_source_syntax":
            return "native source schema 1 call must remain unresolved_source_syntax"
        if row.get("caller_declaration_id") not in declaration_ids:
            return "native source call references unknown caller declaration"

    joins = list(_rows(output / "native_source_reflection_joins.jsonl"))
    if len({row.get("join_id") for row in joins}) != len(joins):
        return "duplicate native source reflection join id"
    for row in joins:
        if row.get("evidence_level") != "exact_join":
            return "native source reflection join mislabeled evidence level"
        if row.get("source_declaration_id") not in declaration_ids:
            return "native source reflection join references unknown declaration"
        if row.get("source_path") not in file_paths:
            return "native source reflection join references unknown source file"

    native_modules = {
        str(row.get("module_name", "") or "")
        for row in _module_rows(output)
        if row.get("module_name")
    }
    manifest_modules = {str(value) for value in manifest.get("modules", [])}
    if native_modules != manifest_modules:
        return "native source module list does not match native_modules.jsonl"

    return None
