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

import uatool_native_source as native_source


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


class NativeSourceSchema1Test(unittest.TestCase):
    def test_project_inventory_excludes_staged_unreal_asset_tool(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = write(root / "Sample.uproject", "{}\n")

            write(
                root / "Source" / "Sample" / "Sample.Build.cs",
                "public class Sample {}\n",
            )
            write(
                root
                / "Plugins"
                / "HR_RAI"
                / "Source"
                / "HRRAI"
                / "HRRAI.Build.cs",
                "public class HRRAI {}\n",
            )
            write(
                root
                / "Plugins"
                / "UnrealAssetTool"
                / "Source"
                / "UnrealAssetTool"
                / "UnrealAssetTool.Build.cs",
                "public class UnrealAssetTool {}\n",
            )

            modules = native_source.discover_modules(project)
            names = [module.name for module in modules]

            self.assertEqual(names, ["HRRAI", "Sample"])
            self.assertNotIn("UnrealAssetTool", names)

    def test_lexical_fallback_captures_raw_c_functions_and_calls(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build_cs = write(
                root
                / "Plugins"
                / "HR_RAI"
                / "Source"
                / "HRRAI"
                / "HRRAI.Build.cs",
                "public class HRRAI {}\n",
            )
            source = write(
                build_cs.parent / "Private" / "hrsim.c",
                """#include "hrsim.h"
#define HRSIM_LIMIT 8

typedef struct hrsim_state {
    int value;
} hrsim_state;

static int hrsim_step(int value)
{
    return value + 1;
}

int hrsim_tick(int value)
{
    return hrsim_step(value);
}
""",
            )
            module = native_source.ModuleRoot(
                name="HRRAI",
                root=build_cs.parent,
                build_cs=build_cs,
                owner_kind="project_plugin",
                owner_name="HR_RAI",
            )

            includes, defines, symbols, parameters, calls = (
                native_source.scan_lexical_file(source, module, root)
            )

            self.assertEqual(
                [row["spelling"] for row in includes],
                ["hrsim.h"],
            )
            self.assertEqual(
                [row["name"] for row in defines],
                ["HRSIM_LIMIT"],
            )

            functions = [
                row for row in symbols if row["kind"] == "function"
            ]
            self.assertEqual(
                [row["name"] for row in functions],
                ["hrsim_step", "hrsim_tick"],
            )
            self.assertTrue(
                all(row["evidence"] == "lexical_source" for row in functions)
            )
            self.assertEqual(len(parameters), 2)
            self.assertEqual(
                [row["name"] for row in parameters],
                ["value", "value"],
            )
            self.assertEqual(
                [row["callee_spelling"] for row in calls],
                ["hrsim_step"],
            )
            self.assertEqual(calls[0]["resolution"], "lexical_unresolved")
            self.assertNotIn(
                "return",
                [row["name"] for row in functions],
            )

    def test_compile_database_filters_owned_tu_and_expands_rsp(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = write(root / "Sample.uproject", "{}\n")
            source = write(
                root
                / "Plugins"
                / "HR_RAI"
                / "Source"
                / "HRRAI"
                / "Private"
                / "hrsim.c",
                "int hrsim_tick(void) { return 0; }\n",
            )
            foreign = write(
                root / "EngineThing.cpp",
                "int engine_thing(void) { return 0; }\n",
            )
            include_dir = root / "include dir"
            include_dir.mkdir()
            forced = write(root / "defs.h", "#define FORCED 1\n")
            rsp = write(
                root / "hrsim.rsp",
                (
                    f'/I"{include_dir}" '
                    '/DHRSIM_TEST=1 '
                    f'/FI"{forced}" '
                    '/W4\n'
                ),
            )
            compile_db = root / "compile_commands.json"
            compile_db.write_text(
                json.dumps(
                    [
                        {
                            "directory": str(root),
                            "file": str(source),
                            "arguments": [
                                "clang-cl.exe",
                                f"@{rsp}",
                                "/c",
                                str(source),
                            ],
                        },
                        {
                            "directory": str(root),
                            "file": str(foreign),
                            "arguments": [
                                "clang-cl.exe",
                                "/c",
                                str(foreign),
                            ],
                        },
                    ]
                ),
                encoding="utf-8",
            )

            rows, diagnostics = native_source.load_compile_commands(
                compile_db,
                project,
                {source.resolve()},
            )

            self.assertEqual(diagnostics, [])
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(
                row["source_path"],
                source.relative_to(root).as_posix(),
            )
            self.assertEqual(row["compiler"], "clang-cl.exe")
            self.assertEqual(
                row["response_files"],
                [rsp.relative_to(root).as_posix()],
            )
            self.assertIn(
                include_dir.resolve().as_posix(),
                row["include_paths"],
            )
            self.assertIn("HRSIM_TEST=1", row["definitions"])
            self.assertIn(
                forced.resolve().as_posix(),
                row["forced_includes"],
            )
            self.assertEqual(
                row["evidence"],
                "ubt_generate_clang_database",
            )

    def test_manifest_count_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            counts: dict[str, int] = {}
            for filename in native_source.RAW_FILES:
                row = {"file": filename}
                (root / filename).write_text(
                    json.dumps(row) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
                counts[filename.removesuffix(".jsonl")] = 1

            manifest = {
                "schema_version": native_source.SCHEMA_VERSION,
                "pass": "UnrealAssetToolNativeSource",
                "success": True,
                "error": "",
                "files": list(native_source.RAW_FILES),
                "counts": counts,
            }
            (root / "source_manifest.json").write_text(
                json.dumps(manifest) + "\n",
                encoding="utf-8",
                newline="\n",
            )

            self.assertEqual(native_source.validation_error(root), "")

            manifest["counts"]["source_calls"] = 2
            (root / "source_manifest.json").write_text(
                json.dumps(manifest) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            self.assertEqual(
                native_source.validation_error(root),
                "count mismatch for source_calls: manifest=2 actual=1",
            )

    def test_canonical_launcher_exposes_source_capture(self) -> None:
        launcher = (SCRIPTS / "uatool.py").read_text(encoding="utf-8")
        self.assertIn(
            "import uatool_native_source as native_source",
            launcher,
        )
        self.assertIn('prog="uatool source-capture"', launcher)
        self.assertIn('sys.argv[1] == "source-capture"', launcher)
        self.assertIn(
            "generate_compile_database=not args.no_generate_compile_db",
            launcher,
        )

        source = (SCRIPTS / "uatool_native_source.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"-Mode=GenerateClangDatabase"', source)
        self.assertIn('"-NoExecCodeGenActions"', source)
        self.assertIn('"lexical_unresolved"', source)
        self.assertIn('"ubt_generate_clang_database"', source)


if __name__ == "__main__":
    unittest.main()
