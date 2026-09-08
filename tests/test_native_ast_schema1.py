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
import uatool_native_libclang as native_libclang
import uatool_libclang_worker as libclang_worker


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

    def test_capture_manifest_paths_all_persist_freshness_provenance(self) -> None:
        source = (
            SCRIPTS / "uatool_native_ast.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            source.count(
                '"compiler_input_snapshot": compiler_input_snapshot'
            ),
            3,
        )
        self.assertEqual(
            source.count(
                '"compiler_inputs_unchanged": compiler_inputs_unchanged'
            ),
            2,
        )
        self.assertIn(
            "final_compiler_input_snapshot =",
            source,
        )
        self.assertIn(
            "project-owned compiler inputs changed during AST capture",
            source,
        )

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

    def test_shared_pch_is_replayed_as_source_forced_include(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rsp = write(
                root / "sample.rsp",
                (
                    '/std:c++20 '
                    '/Yu"SharedPCH.Engine.Project.ValApi.Cpp20.h" '
                    '/Fp"SharedPCH.Engine.Project.ValApi.Cpp20.h.pch" '
                    '/DVALUE=1\n'
                ),
            )
            source = write(
                root / "sample.cpp",
                "int sample() { return 0; }\n",
            )
            entry = {
                "directory": str(root),
                "file": str(source),
                "arguments": [
                    "cl.exe",
                    f"@{rsp}",
                    "/c",
                    str(source),
                ],
            }
            self.assertEqual(
                native_ast._precompiled_header_from_entry(entry),
                "SharedPCH.Engine.Project.ValApi.Cpp20.h",
            )

            row = {
                "include_paths": [str(root)],
                "definitions": ["VALUE=1"],
                "forced_includes": [],
                "_precompiled_header": (
                    "SharedPCH.Engine.Project.ValApi.Cpp20.h"
                ),
                "_semantic_mode_arguments": ["/std:c++20"],
            }
            arguments = native_ast._clang_probe_arguments(
                root / "clang-cl.exe",
                row,
                source,
                "cpp",
                dump_ast=False,
            )
            self.assertIn(
                "/FISharedPCH.Engine.Project.ValApi.Cpp20.h",
                arguments,
            )
            self.assertFalse(any(arg.startswith("/Fp") for arg in arguments))
            self.assertFalse(any(arg.startswith("/Yu") for arg in arguments))

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

    def test_macro_expansion_location_is_used_for_occurrence_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Source" / "Sample" / "sample.c"
            source.parent.mkdir(parents=True)
            ast = {
                "kind": "TranslationUnitDecl",
                "inner": [
                    {
                        "id": "0x100",
                        "kind": "FieldDecl",
                        "loc": {
                            "spellingLoc": {
                                "offset": 10,
                                "line": 1,
                                "col": 2,
                            },
                            "expansionLoc": {
                                "offset": 100,
                                "line": 10,
                                "col": 5,
                                "file": source.as_posix(),
                            },
                        },
                        "name": "len",
                        "type": {"qualType": "size_t"},
                    },
                    {
                        "id": "0x101",
                        "kind": "FieldDecl",
                        "loc": {
                            "spellingLoc": {
                                "offset": 10,
                                "line": 1,
                                "col": 2,
                            },
                            "expansionLoc": {
                                "offset": 200,
                                "line": 20,
                                "col": 5,
                                "file": source.as_posix(),
                            },
                        },
                        "name": "len",
                        "type": {"qualType": "size_t"},
                    },
                ],
            }
            ast_path = root / "macro.json"
            ast_path.write_text(json.dumps(ast), encoding="utf-8")

            symbols, _, _ = native_ast._normalize_ast_probe(
                ast_path,
                root,
                "Source/Sample/sample.c",
                "c",
            )

            self.assertEqual([row["offset"] for row in symbols], [100, 200])
            self.assertEqual(
                len({row["occurrence_id"] for row in symbols}),
                2,
            )
            self.assertEqual(
                len({row["symbol_id"] for row in symbols}),
                2,
            )

    def test_compatibility_replay_is_explicit_in_normalized_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Source" / "Sample" / "sample.cpp"
            source.parent.mkdir(parents=True)
            ast = {
                "kind": "TranslationUnitDecl",
                "inner": [
                    {
                        "id": "0x100",
                        "kind": "FunctionDecl",
                        "loc": {
                            "file": source.as_posix(),
                            "line": 1,
                            "col": 5,
                            "offset": 4,
                        },
                        "name": "sample",
                        "mangledName": "?sample@@YAHXZ",
                        "type": {"qualType": "int ()"},
                    }
                ],
            }
            ast_path = root / "compat.json"
            ast_path.write_text(json.dumps(ast), encoding="utf-8")

            symbols, _, _ = native_ast._normalize_ast_probe(
                ast_path,
                root,
                "Source/Sample/sample.cpp",
                "cpp",
                ["-Wno-invalid-constexpr"],
            )

            self.assertEqual(
                symbols[0]["evidence"],
                "clang_frontend_ast_json_compatibility_replay",
            )
            self.assertEqual(
                symbols[0]["compatibility_overrides"],
                ["-Wno-invalid-constexpr"],
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

    def test_exact_uworld_incomplete_error_adds_labeled_forced_include(self) -> None:
        stderr = (
            "HRRAIEntityComponent.cpp(563,44): error: "
            "member access into incomplete type 'UWorld'\n"
            "NameTypes.h(377,25): error: constexpr function never "
            "produces a constant expression [-Winvalid-constexpr]\n"
        )
        self.assertEqual(
            native_ast._compatibility_overrides_from_stderr(
                stderr,
                language="cpp",
                frontend_major=19,
            ),
            [
                "-Wno-invalid-constexpr",
                "/FIEngine/World.h",
            ],
        )

    def test_uworld_override_is_not_added_without_exact_error(self) -> None:
        self.assertEqual(
            native_ast._compatibility_overrides_from_stderr(
                "warning: forward declaration of 'UWorld'\n",
                language="cpp",
                frontend_major=19,
            ),
            [],
        )

    def test_exact_ustaticmesh_incomplete_error_adds_labeled_forced_include(self) -> None:
        stderr = (
            "ConstructorHelpers.h(33,19): error: "
            "incomplete type 'UStaticMesh' named in nested name specifier\n"
            "ConstructorHelpers.h(38,13): error: "
            "member access into incomplete type 'UStaticMesh'\n"
            "NameTypes.h(377,25): error: constexpr function never "
            "produces a constant expression [-Winvalid-constexpr]\n"
        )
        self.assertEqual(
            native_ast._compatibility_overrides_from_stderr(
                stderr,
                language="cpp",
                frontend_major=19,
            ),
            [
                "-Wno-invalid-constexpr",
                "/FIEngine/StaticMesh.h",
            ],
        )

    def test_ustaticmesh_override_is_not_added_for_forward_declaration_note(self) -> None:
        self.assertEqual(
            native_ast._compatibility_overrides_from_stderr(
                "note: forward declaration of 'UStaticMesh'\n",
                language="cpp",
                frontend_major=19,
            ),
            [],
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

    def test_probe_success_accepts_mixed_json_and_libclang_backends(self) -> None:
        diagnostics = [
            {
                "kind": "clang_ast_probe",
                "language": "c",
                "success": True,
            },
            {
                "kind": "clang_ast_probe",
                "language": "cpp",
                "success": False,
            },
            {
                "kind": "libclang_cursor_probe",
                "language": "cpp",
                "success": True,
            },
        ]
        self.assertTrue(
            native_ast._probe_languages_successful(diagnostics)
        )

    def test_libclang_discovery_checks_frontend_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindir = root / "bin"
            bindir.mkdir()
            frontend = write(bindir / "clang-cl.exe", "")
            dll = write(bindir / "libclang.dll", "")
            selected, checked = native_libclang.discover_libclang(frontend)
            self.assertEqual(selected, dll.resolve())
            self.assertIn(dll.resolve().as_posix(), checked)

    def test_libclang_worker_uses_fullargv_cursor_traversal(self) -> None:
        worker = (
            SCRIPTS / "uatool_libclang_worker.py"
        ).read_text(encoding="utf-8")
        self.assertIn("clang_parseTranslationUnit2FullArgv", worker)
        self.assertIn("clang_visitChildren", worker)
        self.assertIn("clang_getCursorReferenced", worker)
        self.assertIn("clang_getCursorUSR", worker)
        self.assertIn("libclang_cursor_compatibility_replay", worker)

    def test_libclang_worker_excludes_intermediate_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Source" / "Sample" / "Sample.h"
            generated = (
                root / "Plugins" / "Sample" / "Intermediate" /
                "Build" / "Generated.h"
            )
            source.parent.mkdir(parents=True)
            generated.parent.mkdir(parents=True)
            self.assertEqual(
                libclang_worker._project_relative(
                    source.as_posix(), root
                ),
                "Source/Sample/Sample.h",
            )
            self.assertIsNone(
                libclang_worker._project_relative(
                    generated.as_posix(), root
                )
            )
            self.assertTrue(
                libclang_worker._is_excluded_physical_path(
                    generated.as_posix()
                )
            )

    def test_libclang_parameter_owner_uses_semantic_callable_parent(self) -> None:
        class FakeDLL:
            def __init__(self, parents):
                self.parents = parents

            def clang_getCursorSemanticParent(self, cursor):
                return self.parents.get(cursor)

        class FakeClang:
            def __init__(self, root: Path):
                self.root = root
                self.outer = object()
                self.lambda_call = object()
                self.outer_param = object()
                self.lambda_param = object()
                self.dll = FakeDLL({
                    self.outer_param: self.outer,
                    self.lambda_param: self.lambda_call,
                })

            def is_null(self, cursor):
                return cursor is None

            def kind(self, cursor):
                if cursor in {self.outer, self.lambda_call}:
                    return "CXXMethod"
                return "ParmDecl"

            def location(self, cursor):
                if cursor is self.outer:
                    return (
                        (self.root / "Source" / "Outer.cpp").as_posix(),
                        10,
                        1,
                        100,
                    )
                if cursor is self.lambda_call:
                    return (
                        (self.root / "Source" / "Outer.cpp").as_posix(),
                        20,
                        5,
                        200,
                    )
                return (
                    (self.root / "Source" / "Outer.cpp").as_posix(),
                    11,
                    5,
                    110,
                )

            def usr(self, cursor):
                if cursor is self.outer:
                    return "c:@S@Outer@F@Run#"
                if cursor is self.lambda_call:
                    return "c:Outer.cpp@lambda@F@operator()#I#"
                return ""

            def spelling(self, cursor):
                if cursor is self.outer:
                    return "Run"
                if cursor is self.lambda_call:
                    return "operator()"
                return "Value"

            def type_spelling(self, cursor):
                return "void ()"

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "Source").mkdir()
            clang = FakeClang(root)
            capture = libclang_worker.Capture(
                clang,
                {
                    "project_root": root.as_posix(),
                    "translation_unit": "Source/Outer.cpp",
                    "language": "cpp",
                    "compatibility_overrides": [],
                },
            )
            outer_context = capture.callable_context_for_cursor(
                clang.outer
            )
            self.assertIsNotNone(outer_context)
            self.assertTrue(
                capture.parameter_belongs_to_context(
                    clang.outer_param,
                    outer_context,
                )
            )
            self.assertFalse(
                capture.parameter_belongs_to_context(
                    clang.lambda_param,
                    outer_context,
                )
            )

    def test_native_ast_manifest_declares_parameter_owner_ruleset(self) -> None:
        source = (SCRIPTS / "uatool_native_ast.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'RULESET = "libclang_semantic_callable_owner_target_v2"',
            source,
        )
        self.assertIn(
            "CALL_TARGET_MATERIALIZATION_POLICY",
            source,
        )
        self.assertIn(
            '"parameter_owner_mismatches_rejected"',
            source,
        )
        self.assertIn(
            '"nested_callable_calls_suppressed"',
            source,
        )
        self.assertIn(
            "inside_unmaterialized_local_callable",
            (
                SCRIPTS / "uatool_libclang_worker.py"
            ).read_text(encoding="utf-8"),
        )
        self.assertIn(
            "parameter_belongs_to_context",
            (
                SCRIPTS / "uatool_libclang_worker.py"
            ).read_text(encoding="utf-8"),
        )

    def test_callable_ownership_metrics_sum_probe_counts(self) -> None:
        diagnostics = [
            {
                "kind": "libclang_cursor_probe",
                "counts": {
                    "parameter_owner_mismatches": 2,
                    "nested_callable_calls_suppressed": 5,
                },
            },
            {
                "kind": "other",
                "counts": {
                    "parameter_owner_mismatches": 99,
                    "nested_callable_calls_suppressed": 99,
                },
            },
            {
                "kind": "libclang_cursor_probe",
                "counts": {
                    "parameter_owner_mismatches": 3,
                    "nested_callable_calls_suppressed": 7,
                },
            },
        ]
        self.assertEqual(
            native_ast._parameter_owner_mismatch_count(diagnostics),
            5,
        )
        self.assertEqual(
            native_ast._nested_callable_call_suppression_count(
                diagnostics
            ),
            12,
        )

    def test_libclang_worker_call_identity_uses_caller_occurrence(self) -> None:
        worker = (
            SCRIPTS / "uatool_libclang_worker.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"caller_occurrence_id": function_context[1]', worker)
        self.assertIn('f"{function_context[1]}|{target_usr}|"', worker)
        self.assertIn("unique_calls.setdefault", worker)

    def test_cpp_probe_prefers_gameplay_component(self) -> None:
        source = (SCRIPTS / "uatool_native_ast.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"hrraientitycomponent.cpp": 0', source)
        self.assertIn('"hrraiinteractablecomponent.cpp": 1', source)

    def test_all_translation_unit_success_requires_every_expected_tu(self) -> None:
        rows = [
            ({"source_path": "Source/A.c"}, Path("A.c"), "c"),
            ({"source_path": "Source/B.cpp"}, Path("B.cpp"), "cpp"),
        ]
        diagnostics = [
            {
                "kind": "libclang_cursor_probe",
                "source_path": "Source/A.c",
                "success": True,
            },
            {
                "kind": "libclang_cursor_probe",
                "source_path": "Source/B.cpp",
                "success": True,
            },
        ]
        self.assertTrue(
            native_ast._translation_units_successful(
                diagnostics,
                rows,
            )
        )
        diagnostics[-1]["success"] = False
        self.assertFalse(
            native_ast._translation_units_successful(
                diagnostics,
                rows,
            )
        )

    def test_libclang_occurrence_identity_is_language_aware(self) -> None:
        worker = (
            SCRIPTS / "uatool_libclang_worker.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'f"occurrence|{self.language}|{source_path}|{kind}|{offset}|"',
            worker,
        )
        self.assertIn("unique_symbols.setdefault", worker)

    def test_libclang_outputs_are_unique_per_translation_unit(self) -> None:
        source = (
            SCRIPTS / "uatool_native_libclang.py"
        ).read_text(encoding="utf-8")
        self.assertIn("hashlib.sha256(source_key.encode", source)
        self.assertIn(
            'stem = f"native_ast_libclang_{language}_{base}_{digest}"',
            source,
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
        self.assertIn('"libclang_cursor_all_translation_units"', source)
        self.assertIn("discover_clang_frontend", source)
        self.assertIn("_run_clang_ast_probes", source)
        self.assertIn("_write_response_file", source)
        self.assertIn("_semantic_mode_arguments", source)
        self.assertIn("_precompiled_header_from_entry", source)
        self.assertIn("precompiled_header_replay", source)
        self.assertIn("syntax_exit_code", source)
        self.assertIn("syntax_error_lines", source)
        self.assertIn("compatibility_overrides", source)
        self.assertIn("_compatibility_overrides_from_stderr", source)
        self.assertIn("/FIEngine/World.h", source)
        self.assertIn("clang_frontend_ast_json_compatibility_replay", source)
        self.assertIn("[-Winvalid-constexpr]", source)
        self.assertIn("STL1000: Unexpected compiler version", source)
        self.assertIn("_clang_version_major", source)
        self.assertIn("_normalize_successful_probes", source)
        self.assertIn("native_libclang.run_cursor_probe", source)
        self.assertIn("native_libclang.discover_libclang", source)
        self.assertIn("_translation_unit_rows", source)
        self.assertIn("_translation_units_successful", source)
        self.assertIn('"libclang_cursor_all_translation_units"', source)
        self.assertIn('"compiler_resolved"', source)
        self.assertIn('f"@{syntax_rsp}"', source)


if __name__ == "__main__":
    unittest.main()
