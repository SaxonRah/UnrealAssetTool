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

import uatool_native_compiler as native_compiler


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


class NativeCompilerSchema1Test(unittest.TestCase):
    def seed_project(self, project: Path, output: Path) -> tuple[Path, Path]:
        module = project / "Plugins" / "HR_RAI" / "Source" / "HRRAI"
        private = module / "Private"
        runtime = private / "Runtime"
        private.mkdir(parents=True)
        runtime.mkdir()
        (module / "HRRAI.Build.cs").write_text("// synthetic\n", encoding="utf-8")

        ue_cpp = private / "Bridge.cpp"
        raw_c = runtime / "raw.c"
        header = module / "Public" / "Api.h"
        header.parent.mkdir()
        ue_cpp.write_text('#include "../Public/Api.h"\nint Bridge() { return 1; }\n', encoding="utf-8")
        raw_c.write_text("int raw_fn(void) { return 2; }\n", encoding="utf-8")
        header.write_text("#pragma once\nint Bridge();\n", encoding="utf-8")

        write_jsonl(
            output / "native_modules.jsonl",
            [{
                "module_name": "HRRAI",
                "build_cs": "Plugins/HR_RAI/Source/HRRAI/HRRAI.Build.cs",
                "loaded": True,
            }],
        )
        write_jsonl(
            output / "native_source_files.jsonl",
            [
                {
                    "module_name": "HRRAI",
                    "path": "Plugins/HR_RAI/Source/HRRAI/Private/Bridge.cpp",
                    "module_relative_path": "Private/Bridge.cpp",
                    "language": "cpp",
                    "size": ue_cpp.stat().st_size,
                    "line_count": 2,
                    "sha256": "x",
                    "evidence_level": "source_syntax",
                },
                {
                    "module_name": "HRRAI",
                    "path": "Plugins/HR_RAI/Source/HRRAI/Private/Runtime/raw.c",
                    "module_relative_path": "Private/Runtime/raw.c",
                    "language": "c",
                    "size": raw_c.stat().st_size,
                    "line_count": 1,
                    "sha256": "y",
                    "evidence_level": "source_syntax",
                },
                {
                    "module_name": "HRRAI",
                    "path": "Plugins/HR_RAI/Source/HRRAI/Public/Api.h",
                    "module_relative_path": "Public/Api.h",
                    "language": "c_or_cpp_header",
                    "size": header.stat().st_size,
                    "line_count": 2,
                    "sha256": "z",
                    "evidence_level": "source_syntax",
                },
            ],
        )
        return ue_cpp, raw_c

    def test_ingest_real_compile_commands_without_ast_claims(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            output = project / ".uatool-native-compiler"
            output.mkdir()
            ue_cpp, raw_c = self.seed_project(project, output)

            database = output / "compile_commands.json"
            database.write_text(
                json.dumps(
                    [
                        {
                            "directory": str(project),
                            "file": str(ue_cpp),
                            "command": f'"C:/VS/cl.exe" /c "{ue_cpp}" @"C:/tmp/Bridge.rsp"',
                        },
                        {
                            "directory": str(project),
                            "file": str(raw_c),
                            "arguments": ["C:/VS/cl.exe", "/TC", "/c", str(raw_c)],
                        },
                        {
                            "directory": str(project),
                            "file": str(project / "EngineOwned.cpp"),
                            "command": '"C:/VS/cl.exe" /c EngineOwned.cpp',
                        },
                    ]
                ),
                encoding="utf-8",
            )

            manifest = native_compiler.ingest_database(project, output, database)
            self.assertIsNone(native_compiler.validation_error(output))
            self.assertEqual(manifest["schema_version"], 1)
            self.assertFalse(manifest["ast_resolved"])
            self.assertEqual(manifest["counts"]["compile_units"], 2)
            self.assertEqual(manifest["counts"]["expected_translation_units"], 2)
            self.assertEqual(manifest["missing_translation_units"], [])

            units = list(native_compiler._rows(output / "native_compile_units.jsonl"))
            self.assertEqual(
                {row["source_path"] for row in units},
                {
                    "Plugins/HR_RAI/Source/HRRAI/Private/Bridge.cpp",
                    "Plugins/HR_RAI/Source/HRRAI/Private/Runtime/raw.c",
                },
            )
            bridge = next(row for row in units if row["source_path"].endswith("Bridge.cpp"))
            raw = next(row for row in units if row["source_path"].endswith("raw.c"))
            self.assertEqual(bridge["compiler_family"], "msvc")
            self.assertEqual(bridge["response_files"], ["C:/tmp/Bridge.rsp"])
            self.assertFalse(bridge["arguments_exact"])
            self.assertTrue(bridge["command_exact"])
            self.assertTrue(raw["arguments_exact"])
            self.assertEqual(raw["arguments"][1], "/TC")

            for filename in native_compiler.EMPTY_SCHEMA_STREAMS:
                self.assertEqual(list(native_compiler._rows(output / filename)), [])

    def test_validator_rejects_missing_translation_unit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            output = project / ".uatool-native-compiler"
            output.mkdir()
            ue_cpp, raw_c = self.seed_project(project, output)

            database = output / "compile_commands.json"
            database.write_text(
                json.dumps([
                    {
                        "directory": str(project),
                        "file": str(ue_cpp),
                        "command": f'"C:/VS/cl.exe" /c "{ue_cpp}"',
                    }
                ]),
                encoding="utf-8",
            )
            native_compiler.ingest_database(project, output, database)
            error = native_compiler.validation_error(output)
            self.assertIsNotNone(error)
            self.assertIn("missing project translation units", error)
            self.assertIn("raw.c", error)

    def test_launcher_engine_resolves_ubt_dll_with_bundled_dotnet(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            engine = Path(temp) / "UE_5.8" / "Engine"
            ubt = engine / "Binaries" / "DotNET" / "UnrealBuildTool" / "UnrealBuildTool.dll"
            dotnet = (
                engine
                / "Binaries"
                / "ThirdParty"
                / "DotNet"
                / "10.0.0"
                / "win-x64"
                / "dotnet.exe"
            )
            ubt.parent.mkdir(parents=True)
            dotnet.parent.mkdir(parents=True)
            ubt.write_bytes(b"synthetic")
            dotnet.write_bytes(b"synthetic")

            command = native_compiler._resolve_ubt_command(engine)
            self.assertEqual(command, [str(dotnet), str(ubt)])

    def test_core_exposes_focused_compiler_capture(self) -> None:
        core = (SCRIPTS / "uatool_core.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_native_compiler as native_compiler", core)
        self.assertIn('"native-compiler-capture"', core)
        self.assertIn("native_compiler.generate_database(", core)
        self.assertIn("native_compiler.ingest_database(", core)
        self.assertIn("native_compiler.validation_error(output)", core)
        self.assertIn('"VisualStudio2022"', core)


if __name__ == "__main__":
    unittest.main()
