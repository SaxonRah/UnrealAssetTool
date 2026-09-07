from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_native_ast as native_ast
import uatool_native_source as native_source


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


class NativeASTSchema1Test(unittest.TestCase):
    def test_compiler_environment_does_not_treat_lowercase_d_switches_as_defines(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            ext = root / "external include"
            ext.mkdir()
            includes, defines, forced = native_source._compiler_environment(
                [
                    "/diagnostics:caret",
                    "/d2ExtendedWarningInfo",
                    "/d1trimfile:C:/src",
                    "/DREAL_DEFINE=1",
                    f'/external:I"{ext}"',
                ],
                root,
            )
            self.assertEqual(defines, ["REAL_DEFINE=1"])
            self.assertIn(ext.resolve().as_posix(), includes)
            self.assertEqual(forced, [])

    def test_owned_compile_entries_exclude_foreign_translation_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = write(root / "Sample.uproject", "{}\n")
            build_cs = write(
                root / "Source" / "Sample" / "Sample.Build.cs",
                "public class Sample {}\n",
            )
            owned = write(build_cs.parent / "Sample.cpp", "int sample(void) { return 0; }\n")
            foreign = write(root / "Foreign.cpp", "int foreign(void) { return 0; }\n")
            db = root / "compile_commands.json"
            db.write_text(
                json.dumps([
                    {"directory": str(root), "file": str(owned), "arguments": ["cl.exe", "/c", str(owned)]},
                    {"directory": str(root), "file": str(foreign), "arguments": ["cl.exe", "/c", str(foreign)]},
                ]),
                encoding="utf-8",
            )
            entries, owned_set = native_ast._owned_compile_entries(db, project)
            self.assertEqual(len(entries), 1)
            self.assertIn(owned.resolve(), owned_set)
            self.assertEqual(Path(entries[0]["file"]).resolve(), owned.resolve())

    def test_clang_probe_arguments_use_compiler_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frontend = root / "clang-cl.exe"
            source = root / "sample.cpp"
            row = {
                "include_paths": ["C:/inc one", "C:/inc2"],
                "definitions": ["FOO=1", "BAR"],
                "forced_includes": ["C:/defs.h"],
            }
            arguments = native_ast._clang_probe_arguments(
                frontend,
                row,
                source,
                "cpp",
                dump_ast=True,
            )
            self.assertIn("/TP", arguments)
            self.assertIn("/IC:/inc one", arguments)
            self.assertIn("/DFOO=1", arguments)
            self.assertIn("/FIC:/defs.h", arguments)
            self.assertIn("-ast-dump=json", arguments)
            self.assertEqual(arguments[-1], str(source))

    def test_plain_clang_probe_uses_gnu_style_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frontend = root / "clang.exe"
            source = root / "sample.c"
            row = {
                "include_paths": ["C:/inc one"],
                "definitions": ["FOO=1"],
                "forced_includes": ["C:/defs.h"],
            }
            arguments = native_ast._clang_probe_arguments(
                frontend,
                row,
                source,
                "c",
                dump_ast=False,
            )
            self.assertEqual(arguments[:2], ["-x", "c"])
            self.assertIn("-I", arguments)
            self.assertIn("C:/inc one", arguments)
            self.assertIn("-DFOO=1", arguments)
            self.assertIn("-include", arguments)
            self.assertIn("C:/defs.h", arguments)

    def test_semantic_mode_arguments_replay_ubt_language_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rsp = write(
                root / "sample.rsp",
                (
                    "/std:c++20 /permissive- /Zc:__cplusplus "
                    "/EHsc /MDd /arch:AVX2 /fp:fast "
                    "/O2 /W4 /DIGNORED_DEFINE=1\n"
                ),
            )
            source = write(root / "sample.cpp", "int sample() { return 0; }\n")
            entry = {
                "directory": str(root),
                "file": str(source),
                "arguments": ["cl.exe", f"@{rsp}", "/c", str(source)],
            }
            self.assertEqual(
                native_ast._semantic_mode_arguments(entry),
                [
                    "/std:c++20",
                    "/permissive-",
                    "/Zc:__cplusplus",
                    "/EHsc",
                    "/MDd",
                    "/arch:AVX2",
                    "/fp:fast",
                ],
            )

    def test_probe_response_file_preserves_spaced_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            rsp = Path(temp) / "probe.rsp"
            native_ast._write_response_file(
                rsp,
                [
                    "/IC:/Program Files/UE/include",
                    "/DVALUE=hello world",
                    "-Xclang",
                    "-ast-dump=json",
                    "C:/Source Dir/sample.cpp",
                ],
            )
            text = rsp.read_text(encoding="utf-8")
            self.assertEqual(len(text.splitlines()), 1)
            self.assertIn('"/IC:/Program Files/UE/include"', text)
            self.assertIn('"/DVALUE=hello world"', text)
            self.assertIn("-Xclang -ast-dump=json", text)
            self.assertIn('"C:/Source Dir/sample.cpp"', text)

    def test_vs_llvm_candidates_come_from_vc_root(self) -> None:
        compiler = (
            "C:/Program Files/Microsoft Visual Studio/2022/Community/"
            "VC/Tools/MSVC/14.44.35207/bin/Hostx64/x64/cl.exe"
        )
        candidates = native_ast._vs_llvm_bin_candidates(compiler)
        rendered = [path.as_posix() for path in candidates]
        self.assertTrue(
            any("/VC/Tools/Llvm/x64/bin" in path for path in rendered)
        )
        self.assertTrue(
            any(path.endswith("/VC/Tools/Llvm/bin") for path in rendered)
        )

    def test_ast_normalizer_emits_stable_symbols_parameters_and_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Source" / "Sample" / "sample.c"
            source.parent.mkdir(parents=True)
            ast = {
                "kind": "TranslationUnitDecl",
                "inner": [
                    {
                        "id": "0x100",
                        "kind": "FunctionDecl",
                        "loc": {
                            "file": source.as_posix(),
                            "line": 3,
                            "col": 5,
                            "offset": 20,
                        },
                        "name": "helper",
                        "mangledName": "helper",
                        "type": {"qualType": "int (int)"},
                        "inner": [
                            {
                                "id": "0x101",
                                "kind": "ParmVarDecl",
                                "loc": {"line": 3, "col": 16, "offset": 31},
                                "name": "value",
                                "type": {"qualType": "int"},
                            }
                        ],
                    },
                    {
                        "id": "0x200",
                        "kind": "FunctionDecl",
                        "loc": {"line": 5, "col": 5, "offset": 40},
                        "name": "caller",
                        "mangledName": "caller",
                        "type": {"qualType": "int (void)"},
                        "inner": [
                            {
                                "id": "0x201",
                                "kind": "CompoundStmt",
                                "range": {
                                    "begin": {"line": 6, "col": 1, "offset": 55},
                                    "end": {"line": 8, "col": 1, "offset": 80},
                                },
                                "inner": [
                                    {
                                        "id": "0x202",
                                        "kind": "CallExpr",
                                        "range": {
                                            "begin": {
                                                "line": 7,
                                                "col": 12,
                                                "offset": 68,
                                            },
                                            "end": {
                                                "line": 7,
                                                "col": 20,
                                                "offset": 76,
                                            },
                                        },
                                        "inner": [
                                            {
                                                "id": "0x203",
                                                "kind": "DeclRefExpr",
                                                "referencedDecl": {
                                                    "id": "0x100",
                                                    "kind": "FunctionDecl",
                                                    "name": "helper",
                                                    "type": {
                                                        "qualType": "int (int)"
                                                    },
                                                },
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                ],
            }
            ast_path = root / "probe.json"
            ast_path.write_text(json.dumps(ast), encoding="utf-8")

            symbols, parameters, calls = native_ast._normalize_ast_probe(
                ast_path,
                root,
                "Source/Sample/sample.c",
                "c",
            )

            functions = [row for row in symbols if row["kind"] == "function"]
            self.assertEqual(
                [row["name"] for row in functions],
                ["helper", "caller"],
            )
            self.assertEqual(len(parameters), 1)
            self.assertEqual(parameters[0]["name"], "value")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0]["target_name"], "helper")
            self.assertEqual(calls[0]["resolution"], "compiler_resolved")
            self.assertTrue(calls[0]["target_symbol_id"])
            self.assertTrue(calls[0]["caller_symbol_id"])
            self.assertNotEqual(
                calls[0]["target_symbol_id"],
                calls[0]["caller_symbol_id"],
            )

    def test_source_offset_prevents_local_symbol_id_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Source" / "Sample" / "sample.c"
            source.parent.mkdir(parents=True)
            ast = {
                "kind": "TranslationUnitDecl",
                "inner": [
                    {
                        "id": "0x100",
                        "kind": "VarDecl",
                        "loc": {
                            "file": source.as_posix(),
                            "col": 12,
                            "offset": 100,
                        },
                        "name": "i",
                        "type": {"qualType": "size_t"},
                    },
                    {
                        "id": "0x101",
                        "kind": "VarDecl",
                        "loc": {
                            "col": 12,
                            "offset": 200,
                        },
                        "name": "i",
                        "type": {"qualType": "size_t"},
                    },
                ],
            }
            ast_path = root / "locals.json"
            ast_path.write_text(json.dumps(ast), encoding="utf-8")

            symbols, _, _ = native_ast._normalize_ast_probe(
                ast_path,
                root,
                "Source/Sample/sample.c",
                "c",
            )

            self.assertEqual(len(symbols), 2)
            self.assertEqual(
                len({row["symbol_id"] for row in symbols}),
                2,
            )
            self.assertEqual(
                len({row["occurrence_id"] for row in symbols}),
                2,
            )

    def test_compatibility_overrides_are_inserted_before_source(self) -> None:
        arguments = [
            "/nologo",
            "/TP",
            "-fsyntax-only",
            "C:/Source/sample.cpp",
        ]
        result = native_ast._with_extra_probe_arguments(
            arguments,
            [
                "/D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH=1",
                "-Wno-invalid-constexpr",
            ],
        )
        self.assertEqual(result[-1], "C:/Source/sample.cpp")
        self.assertEqual(
            result[-3:-1],
            [
                "/D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH=1",
                "-Wno-invalid-constexpr",
            ],
        )

    def test_document_counts_cover_symbols_refs_and_relations(self) -> None:
        text = """--- !Symbol
ID: AAA
...
--- !Refs
ID: AAA
References: []
...
--- !Relation
Subject: AAA
Predicate: 0
Object: BBB
...
"""
        self.assertEqual(
            native_ast._document_counts(text),
            {"symbols": 1, "refs": 1, "relations": 1},
        )

    def test_canonical_launcher_exposes_ast_capture(self) -> None:
        launcher = (SCRIPTS / "uatool.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_native_ast as native_ast", launcher)
        self.assertIn('prog="uatool ast-capture"', launcher)
        self.assertIn('sys.argv[1] == "ast-capture"', launcher)

        source = (SCRIPTS / "uatool_native_ast.py").read_text(encoding="utf-8")
        self.assertIn('"--format=yaml"', source)
        self.assertIn('"--executor=all-TUs"', source)
        self.assertIn('"clangd_indexer_compiler_resolved"', source)
        self.assertIn('"clang_frontend_ast_json_probe"', source)
        self.assertIn("discover_clang_frontend", source)
        self.assertIn("_run_clang_ast_probes", source)
        self.assertIn("_write_response_file", source)
        self.assertIn("_semantic_mode_arguments", source)
        self.assertIn("syntax_exit_code", source)
        self.assertIn("syntax_error_lines", source)
        self.assertIn("compatibility_overrides", source)
        self.assertIn("STL1000: Unexpected compiler version", source)
        self.assertIn("_clang_version_major", source)
        self.assertIn("_normalize_successful_probes", source)
        self.assertIn('"compiler_resolved"', source)
        self.assertIn('f"@{syntax_rsp}"', source)
        self.assertIn('f"@{ast_rsp}"', source)


if __name__ == "__main__":
    unittest.main()
