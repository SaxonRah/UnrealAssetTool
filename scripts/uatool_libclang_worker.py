#!/usr/bin/env python3
"""Isolated libclang cursor worker for native compiler semantic capture."""
from __future__ import annotations

import ctypes
import hashlib
import json
import sys
from pathlib import Path


class CXString(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("private_flags", ctypes.c_uint),
    ]


class CXCursor(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_int),
        ("xdata", ctypes.c_int),
        ("data", ctypes.c_void_p * 3),
    ]


class CXType(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_int),
        ("data", ctypes.c_void_p * 2),
    ]


class CXSourceLocation(ctypes.Structure):
    _fields_ = [
        ("ptr_data", ctypes.c_void_p * 2),
        ("int_data", ctypes.c_uint),
    ]


CXChildVisit_Break = 0
CXChildVisit_Continue = 1
CXChildVisit_Recurse = 2
CXTranslationUnit_KeepGoing = 0x200
CXTranslationUnit_IgnoreNonErrorsFromIncludedFiles = 0x4000


def _stable_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]


def _slash(value: str) -> str:
    return str(value).replace("\\", "/")


EXCLUDED_SOURCE_PARTS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    "binaries",
    "deriveddatacache",
    "intermediate",
    "saved",
}


def _project_relative(value: str, root: Path) -> str | None:
    source = _slash(value)
    prefix = root.resolve().as_posix().rstrip("/") + "/"
    if not source.lower().startswith(prefix.lower()):
        return None
    relative = source[len(prefix):]
    parts = {part.lower() for part in relative.split("/") if part}
    if parts & EXCLUDED_SOURCE_PARTS:
        return None
    return relative


def _is_excluded_physical_path(value: str) -> bool:
    parts = {
        part.lower()
        for part in _slash(value).split("/")
        if part
    }
    return bool(parts & EXCLUDED_SOURCE_PARTS)


class LibClang:
    def __init__(self, dll_path: Path):
        self.dll = ctypes.CDLL(str(dll_path))
        d = self.dll

        d.clang_createIndex.argtypes = [ctypes.c_int, ctypes.c_int]
        d.clang_createIndex.restype = ctypes.c_void_p
        d.clang_disposeIndex.argtypes = [ctypes.c_void_p]

        d.clang_parseTranslationUnit2FullArgv.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_char_p),
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        d.clang_parseTranslationUnit2FullArgv.restype = ctypes.c_int
        d.clang_disposeTranslationUnit.argtypes = [ctypes.c_void_p]

        d.clang_getTranslationUnitCursor.argtypes = [ctypes.c_void_p]
        d.clang_getTranslationUnitCursor.restype = CXCursor

        self.visitor_type = ctypes.CFUNCTYPE(
            ctypes.c_uint, CXCursor, CXCursor, ctypes.c_void_p
        )
        d.clang_visitChildren.argtypes = [
            CXCursor, self.visitor_type, ctypes.c_void_p
        ]
        d.clang_visitChildren.restype = ctypes.c_uint

        d.clang_getCursorKindSpelling.argtypes = [ctypes.c_int]
        d.clang_getCursorKindSpelling.restype = CXString
        d.clang_getCursorSpelling.argtypes = [CXCursor]
        d.clang_getCursorSpelling.restype = CXString
        d.clang_getCursorDisplayName.argtypes = [CXCursor]
        d.clang_getCursorDisplayName.restype = CXString
        d.clang_getCursorUSR.argtypes = [CXCursor]
        d.clang_getCursorUSR.restype = CXString
        d.clang_getCString.argtypes = [CXString]
        d.clang_getCString.restype = ctypes.c_char_p
        d.clang_disposeString.argtypes = [CXString]

        d.clang_getCursorType.argtypes = [CXCursor]
        d.clang_getCursorType.restype = CXType
        d.clang_getTypeSpelling.argtypes = [CXType]
        d.clang_getTypeSpelling.restype = CXString

        d.clang_getCursorLocation.argtypes = [CXCursor]
        d.clang_getCursorLocation.restype = CXSourceLocation
        d.clang_getExpansionLocation.argtypes = [
            CXSourceLocation,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        d.clang_getSpellingLocation.argtypes = [
            CXSourceLocation,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
            ctypes.POINTER(ctypes.c_uint),
        ]
        d.clang_getFileName.argtypes = [ctypes.c_void_p]
        d.clang_getFileName.restype = CXString

        d.clang_getCursorReferenced.argtypes = [CXCursor]
        d.clang_getCursorReferenced.restype = CXCursor
        d.clang_Cursor_isNull.argtypes = [CXCursor]
        d.clang_Cursor_isNull.restype = ctypes.c_int
        d.clang_isCursorDefinition.argtypes = [CXCursor]
        d.clang_isCursorDefinition.restype = ctypes.c_uint
        d.clang_getCursorDefinition.argtypes = [CXCursor]
        d.clang_getCursorDefinition.restype = CXCursor
        d.clang_getCursorSemanticParent.argtypes = [CXCursor]
        d.clang_getCursorSemanticParent.restype = CXCursor

        d.clang_getNumDiagnostics.argtypes = [ctypes.c_void_p]
        d.clang_getNumDiagnostics.restype = ctypes.c_uint
        d.clang_getDiagnostic.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        d.clang_getDiagnostic.restype = ctypes.c_void_p
        d.clang_defaultDiagnosticDisplayOptions.restype = ctypes.c_uint
        d.clang_formatDiagnostic.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        d.clang_formatDiagnostic.restype = CXString
        d.clang_disposeDiagnostic.argtypes = [ctypes.c_void_p]

        if hasattr(d, "clang_Cursor_getMangling"):
            d.clang_Cursor_getMangling.argtypes = [CXCursor]
            d.clang_Cursor_getMangling.restype = CXString

    def string(self, value: CXString) -> str:
        raw = self.dll.clang_getCString(value)
        result = raw.decode("utf-8", errors="replace") if raw else ""
        self.dll.clang_disposeString(value)
        return result

    def kind(self, cursor: CXCursor) -> str:
        return self.string(self.dll.clang_getCursorKindSpelling(cursor.kind))

    def spelling(self, cursor: CXCursor) -> str:
        return self.string(self.dll.clang_getCursorSpelling(cursor))

    def display_name(self, cursor: CXCursor) -> str:
        return self.string(self.dll.clang_getCursorDisplayName(cursor))

    def usr(self, cursor: CXCursor) -> str:
        return self.string(self.dll.clang_getCursorUSR(cursor))

    def type_spelling(self, cursor: CXCursor) -> str:
        return self.string(
            self.dll.clang_getTypeSpelling(self.dll.clang_getCursorType(cursor))
        )

    def mangling(self, cursor: CXCursor) -> str:
        if not hasattr(self.dll, "clang_Cursor_getMangling"):
            return ""
        return self.string(self.dll.clang_Cursor_getMangling(cursor))

    def _physical_location(
        self,
        cursor: CXCursor,
        *,
        spelling: bool,
    ) -> tuple[str, int, int, int]:
        loc = self.dll.clang_getCursorLocation(cursor)
        file_handle = ctypes.c_void_p()
        line = ctypes.c_uint()
        column = ctypes.c_uint()
        offset = ctypes.c_uint()
        getter = (
            self.dll.clang_getSpellingLocation
            if spelling
            else self.dll.clang_getExpansionLocation
        )
        getter(
            loc,
            ctypes.byref(file_handle),
            ctypes.byref(line),
            ctypes.byref(column),
            ctypes.byref(offset),
        )
        file_name = ""
        if file_handle.value:
            file_name = self.string(self.dll.clang_getFileName(file_handle))
        return _slash(file_name), line.value, column.value, offset.value

    def location(self, cursor: CXCursor) -> tuple[str, int, int, int]:
        return self._physical_location(cursor, spelling=False)

    def spelling_location(
        self, cursor: CXCursor
    ) -> tuple[str, int, int, int]:
        return self._physical_location(cursor, spelling=True)

    def is_null(self, cursor: CXCursor) -> bool:
        return bool(self.dll.clang_Cursor_isNull(cursor))


SYMBOL_KIND = {
    "Namespace": "namespace",
    "StructDecl": "record",
    "UnionDecl": "record",
    "ClassDecl": "record",
    "ClassTemplate": "record",
    "ClassTemplatePartialSpecialization": "record",
    "EnumDecl": "enum",
    "EnumConstantDecl": "enum_constant",
    "TypedefDecl": "typedef",
    "TypeAliasDecl": "type_alias",
    "FieldDecl": "field",
    "VarDecl": "variable",
    "FunctionDecl": "function",
    "FunctionTemplate": "function_template",
    "CXXMethod": "method",
    "Constructor": "constructor",
    "Destructor": "destructor",
    "ConversionFunction": "conversion_function",
}

FUNCTION_KINDS = {
    "FunctionDecl",
    "FunctionTemplate",
    "CXXMethod",
    "Constructor",
    "Destructor",
    "ConversionFunction",
}

CALL_KINDS = {
    "CallExpr",
    "CXXMemberCallExpr",
    "CXXOperatorCallExpr",
}


class Capture:
    def __init__(self, clang: LibClang, config: dict):
        self.clang = clang
        self.project_root = Path(config["project_root"]).resolve()
        self.translation_unit = config["translation_unit"]
        self.language = config["language"]
        self.compatibility_overrides = list(
            config.get("compatibility_overrides") or []
        )
        self.evidence = (
            "libclang_cursor_compatibility_replay"
            if self.compatibility_overrides
            else "libclang_cursor"
        )
        self.symbols: list[dict] = []
        self.parameters: list[dict] = []
        self.calls: list[dict] = []
        self.parameter_owner_mismatches = 0

    def location(self, cursor: CXCursor) -> tuple[str | None, int, int, int]:
        file_name, line, column, offset = self.clang.location(cursor)
        relative = (
            _project_relative(file_name, self.project_root)
            if file_name else None
        )
        return relative, line, column, offset

    def qualified_name(self, cursor: CXCursor) -> str:
        parts: list[str] = []
        current = cursor
        for _ in range(64):
            name = self.clang.spelling(current)
            if name:
                parts.append(name)
            parent = self.clang.dll.clang_getCursorSemanticParent(current)
            if self.clang.is_null(parent):
                break
            if self.clang.kind(parent) == "TranslationUnit":
                break
            current = parent
        return "::".join(reversed(parts))

    def identity(
        self,
        cursor: CXCursor,
        kind: str,
        source_path: str,
        line: int,
        column: int,
        offset: int,
    ) -> tuple[str, str]:
        usr = self.clang.usr(cursor)
        name = self.clang.spelling(cursor)
        type_spelling = self.clang.type_spelling(cursor)
        if usr:
            semantic = _stable_id(f"{kind}|usr|{usr}")
        else:
            semantic = _stable_id(
                f"{kind}|source|{source_path}|{name}|"
                f"{line}|{column}|{offset}|{type_spelling}"
            )
        occurrence = _stable_id(
            f"occurrence|{self.language}|{source_path}|{kind}|{offset}|"
            f"{line}|{column}|{name}|{type_spelling}"
        )
        return semantic, occurrence

    def referenced_for_call(self, cursor: CXCursor) -> CXCursor:
        direct = self.clang.dll.clang_getCursorReferenced(cursor)
        if not self.clang.is_null(direct):
            return direct

        found: list[CXCursor] = []

        @self.clang.visitor_type
        def visitor(child: CXCursor, parent: CXCursor, data) -> int:
            referenced = self.clang.dll.clang_getCursorReferenced(child)
            if not self.clang.is_null(referenced):
                found.append(referenced)
                return CXChildVisit_Break
            return CXChildVisit_Recurse

        self.clang.dll.clang_visitChildren(cursor, visitor, None)
        return found[0] if found else CXCursor()

    def callable_context_for_cursor(
        self,
        cursor: CXCursor,
    ) -> tuple[str, str] | None:
        if self.clang.is_null(cursor):
            return None
        kind = self.clang.kind(cursor)
        if kind not in FUNCTION_KINDS:
            return None
        source_path, line, column, offset = self.location(cursor)
        if not source_path:
            return None
        return self.identity(
            cursor,
            kind,
            source_path,
            line,
            column,
            offset,
        )

    def parameter_belongs_to_context(
        self,
        cursor: CXCursor,
        function_context: tuple[str, str] | None,
    ) -> bool:
        if not function_context:
            return False
        parent = self.clang.dll.clang_getCursorSemanticParent(cursor)
        parent_context = self.callable_context_for_cursor(parent)
        return parent_context == function_context

    def target_identity(self, cursor: CXCursor) -> tuple[str, str, str, str]:
        if self.clang.is_null(cursor):
            return "", "", "", ""
        kind = self.clang.kind(cursor)
        name = self.clang.spelling(cursor)
        type_spelling = self.clang.type_spelling(cursor)
        usr = self.clang.usr(cursor)
        source_path, line, column, offset = self.location(cursor)
        stable = ""
        if source_path:
            stable, _ = self.identity(
                cursor, kind, source_path, line, column, offset
            )
        return stable, usr, kind, name or self.clang.display_name(cursor)

    def visit(
        self,
        cursor: CXCursor,
        inherited_project_path: str | None,
        function_context: tuple[str, str] | None,
    ) -> None:
        kind = self.clang.kind(cursor)
        source_path, line, column, offset = self.location(cursor)

        spelling_file, _, _, _ = self.clang.spelling_location(cursor)
        if spelling_file and _is_excluded_physical_path(spelling_file):
            return

        effective_path = source_path or inherited_project_path

        # At the TU root, external declarations are siblings of project
        # declarations, so there is no need to descend into the Engine AST.
        if source_path is None and inherited_project_path is None:
            return
        if source_path is None:
            source_path = inherited_project_path
        if not source_path:
            return

        next_function_context = function_context
        if kind in SYMBOL_KIND:
            semantic, occurrence = self.identity(
                cursor, kind, source_path, line, column, offset
            )
            symbol = {
                "symbol_id": semantic,
                "occurrence_id": occurrence,
                "clang_usr": self.clang.usr(cursor),
                "clang_node_id": "",
                "source_path": source_path,
                "translation_unit": self.translation_unit,
                "language": self.language,
                "clang_kind": kind,
                "kind": SYMBOL_KIND[kind],
                "name": self.clang.spelling(cursor),
                "qualified_name": self.qualified_name(cursor),
                "mangled_name": self.clang.mangling(cursor),
                "type_spelling": self.clang.type_spelling(cursor),
                "storage_class": "",
                "line": line,
                "column": column,
                "offset": offset,
                "is_definition": bool(
                    self.clang.dll.clang_isCursorDefinition(cursor)
                ),
                "compatibility_overrides": self.compatibility_overrides,
                "evidence": self.evidence,
            }
            self.symbols.append(symbol)
            if kind in FUNCTION_KINDS:
                next_function_context = (semantic, occurrence)

        if kind == "ParmDecl" and function_context:
            if self.parameter_belongs_to_context(
                cursor,
                function_context,
            ):
                self.parameters.append({
                    "function_symbol_id": function_context[0],
                    "function_occurrence_id": function_context[1],
                    "parameter_index": -1,
                    "name": self.clang.spelling(cursor),
                    "type_spelling": self.clang.type_spelling(cursor),
                    "source_path": source_path,
                    "translation_unit": self.translation_unit,
                    "language": self.language,
                    "line": line,
                    "column": column,
                    "compatibility_overrides": self.compatibility_overrides,
                    "evidence": self.evidence,
                })
            else:
                self.parameter_owner_mismatches += 1

        if kind in CALL_KINDS and function_context:
            referenced = self.referenced_for_call(cursor)
            target_id, target_usr, target_kind, target_name = (
                self.target_identity(referenced)
            )
            self.calls.append({
                "call_id": _stable_id(
                    f"{self.translation_unit}|{source_path}|{offset}|"
                    f"{function_context[1]}|{target_usr}|"
                    f"{target_kind}|{target_name}"
                ),
                "caller_symbol_id": function_context[0],
                "caller_occurrence_id": function_context[1],
                "source_path": source_path,
                "translation_unit": self.translation_unit,
                "language": self.language,
                "line": line,
                "column": column,
                "offset": offset,
                "target_symbol_id": target_id,
                "target_clang_node_id": "",
                "target_usr": target_usr,
                "target_kind": target_kind,
                "target_name": target_name,
                "target_type_spelling": (
                    self.clang.type_spelling(referenced)
                    if not self.clang.is_null(referenced) else ""
                ),
                "resolution": (
                    "compiler_resolved"
                    if not self.clang.is_null(referenced)
                    else "compiler_unresolved"
                ),
                "compatibility_overrides": self.compatibility_overrides,
                "evidence": self.evidence,
            })

        children: list[CXCursor] = []

        @self.clang.visitor_type
        def collect(child: CXCursor, parent: CXCursor, data) -> int:
            children.append(child)
            return CXChildVisit_Continue

        self.clang.dll.clang_visitChildren(cursor, collect, None)

        parameter_index = 0
        for child in children:
            child_kind = self.clang.kind(child)
            before = len(self.parameters)
            self.visit(child, source_path, next_function_context)
            if (
                child_kind == "ParmDecl"
                and len(self.parameters) > before
                and next_function_context
            ):
                self.parameters[-1]["parameter_index"] = parameter_index
                parameter_index += 1


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def run(config_path: Path) -> int:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output_dir = Path(config["output_dir"]).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    result_path = Path(config["result_path"]).resolve()
    result = {
        "success": False,
        "backend": "libclang_cursor",
        "libclang": config["libclang"],
        "translation_unit": config["translation_unit"],
        "language": config["language"],
        "compatibility_overrides": list(
            config.get("compatibility_overrides") or []
        ),
        "parse_error_code": None,
        "diagnostics": [],
        "counts": {
            "symbols": 0,
            "parameters": 0,
            "calls": 0,
            "parameter_owner_mismatches": 0,
        },
        "files": {},
    }

    clang = None
    index = None
    tu = ctypes.c_void_p()
    try:
        clang = LibClang(Path(config["libclang"]))
        index = clang.dll.clang_createIndex(1, 0)

        args = [str(arg) for arg in config["arguments"]]
        encoded = [arg.encode("utf-8") for arg in args]
        argv = (ctypes.c_char_p * len(encoded))(*encoded)
        options = (
            CXTranslationUnit_KeepGoing
            | CXTranslationUnit_IgnoreNonErrorsFromIncludedFiles
        )
        error = clang.dll.clang_parseTranslationUnit2FullArgv(
            index,
            None,
            argv,
            len(encoded),
            None,
            0,
            options,
            ctypes.byref(tu),
        )
        result["parse_error_code"] = int(error)
        if error != 0 or not tu.value:
            result_path.write_text(
                json.dumps(result, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return 2

        diagnostic_options = clang.dll.clang_defaultDiagnosticDisplayOptions()
        for i in range(clang.dll.clang_getNumDiagnostics(tu)):
            diag = clang.dll.clang_getDiagnostic(tu, i)
            result["diagnostics"].append(
                clang.string(
                    clang.dll.clang_formatDiagnostic(
                        diag, diagnostic_options
                    )
                )
            )
            clang.dll.clang_disposeDiagnostic(diag)

        capture = Capture(clang, config)
        root = clang.dll.clang_getTranslationUnitCursor(tu)

        children: list[CXCursor] = []

        @clang.visitor_type
        def collect_root(child: CXCursor, parent: CXCursor, data) -> int:
            children.append(child)
            return CXChildVisit_Continue

        clang.dll.clang_visitChildren(root, collect_root, None)
        for child in children:
            source_path, _, _, _ = capture.location(child)
            if source_path:
                capture.visit(child, source_path, None)

        unique_symbols: dict[str, dict] = {}
        for row in capture.symbols:
            unique_symbols.setdefault(row["occurrence_id"], row)
        capture.symbols = list(unique_symbols.values())
        capture.symbols.sort(
            key=lambda row: (
                row["source_path"].lower(),
                row["offset"],
                row["kind"],
                row["name"],
            )
        )
        capture.parameters.sort(
            key=lambda row: (
                row["function_occurrence_id"],
                row["parameter_index"],
            )
        )
        unique_calls: dict[str, dict] = {}
        for row in capture.calls:
            unique_calls.setdefault(row["call_id"], row)
        capture.calls = list(unique_calls.values())
        capture.calls.sort(
            key=lambda row: (
                row["source_path"].lower(),
                row["offset"],
                row["call_id"],
            )
        )

        stem = config["output_stem"]
        symbol_path = output_dir / f"{stem}_symbols.jsonl"
        parameter_path = output_dir / f"{stem}_parameters.jsonl"
        call_path = output_dir / f"{stem}_calls.jsonl"
        write_jsonl(symbol_path, capture.symbols)
        write_jsonl(parameter_path, capture.parameters)
        write_jsonl(call_path, capture.calls)

        result["files"] = {
            "symbols": symbol_path.as_posix(),
            "parameters": parameter_path.as_posix(),
            "calls": call_path.as_posix(),
        }
        result["counts"] = {
            "symbols": len(capture.symbols),
            "parameters": len(capture.parameters),
            "calls": len(capture.calls),
            "parameter_owner_mismatches": (
                capture.parameter_owner_mismatches
            ),
        }
        result["success"] = True
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0
    except Exception as exc:
        result["exception"] = f"{type(exc).__name__}: {exc}"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 3
    finally:
        if clang is not None and tu.value:
            try:
                clang.dll.clang_disposeTranslationUnit(tu)
            except Exception:
                pass
        if clang is not None and index:
            try:
                clang.dll.clang_disposeIndex(index)
            except Exception:
                pass


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: uatool_libclang_worker.py <config.json>", file=sys.stderr)
        return 64
    return run(Path(sys.argv[1]).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
