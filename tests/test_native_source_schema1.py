from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_native_source as native_source


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


class NativeSourceSchema1Test(unittest.TestCase):
    def make_project(self, root: Path) -> tuple[Path, Path]:
        module = root / "Plugins" / "HR_RAI" / "Source" / "HRRAI"
        public = module / "Public"
        private = module / "Private"
        public.mkdir(parents=True)
        private.mkdir()
        (module / "HRRAI.Build.cs").write_text("// synthetic module\n", encoding="utf-8")

        (public / "Api.h").write_text(
            textwrap.dedent(
                """
                #pragma once

                USTRUCT(BlueprintType)
                struct HRRAI_API FThing
                {
                    GENERATED_BODY()

                    UFUNCTION(BlueprintCallable)
                    int32 DoThing(int32 Input) const;
                };
                """
            ),
            encoding="utf-8",
        )

        (private / "raw.c").write_text(
            textwrap.dedent(
                """
                #include "../Public/Api.h"

                typedef struct HRPoint { int x; int y; } HRPoint;
                static int g_counter = 0;

                static int helper(int x)
                {
                    return x + 1;
                }

                int DoRaw(int value)
                {
                    g_counter++;
                    return helper(value);
                }
                """
            ),
            encoding="utf-8",
        )
        return module, public / "Api.h"

    def seed_reflection(self, output: Path) -> None:
        write_jsonl(
            output / "native_modules.jsonl",
            [
                {
                    "module_name": "HRRAI",
                    "build_cs": "Plugins/HR_RAI/Source/HRRAI/HRRAI.Build.cs",
                    "owner_kind": "project_plugin",
                    "owner_name": "HR_RAI",
                    "loaded": True,
                }
            ],
        )
        (output / "native_manifest.json").write_text(
            json.dumps({"schema_version": 1, "success": True}) + "\n",
            encoding="utf-8",
        )
        write_jsonl(
            output / "native_functions.jsonl",
            [
                {
                    "function_path": "/Script/HRRAI.Thing:DoThing",
                    "module_name": "HRRAI",
                    "name": "DoThing",
                    "metadata": {"ModuleRelativePath": "Public/Api.h"},
                }
            ],
        )
        write_jsonl(
            output / "native_types.jsonl",
            [
                {
                    "type_path": "/Script/HRRAI.Thing",
                    "module_name": "HRRAI",
                    "kind": "script_struct",
                    "name": "FThing",
                    "metadata": {"ModuleRelativePath": "Public/Api.h"},
                }
            ],
        )

    def test_capture_records_source_syntax_without_claiming_compiler_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.make_project(project)
            output = project / ".uatool-native"
            output.mkdir()
            self.seed_reflection(output)

            manifest = native_source.capture(project, output)
            self.assertIsNone(native_source.validation_error(output))
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["evidence_level"], "source_syntax")
            self.assertFalse(manifest["compiler_resolved"])

            files = list(native_source._rows(output / "native_source_files.jsonl"))
            self.assertEqual(len(files), 2)
            self.assertTrue(any(row["path"].endswith("/Private/raw.c") for row in files))
            self.assertTrue(any(row["path"].endswith("/Public/Api.h") for row in files))

            includes = list(native_source._rows(output / "native_source_includes.jsonl"))
            self.assertEqual(len(includes), 1)
            self.assertTrue(includes[0]["resolved_project_path"].endswith("/Public/Api.h"))
            self.assertFalse(includes[0]["compiler_resolved"])

            declarations = list(native_source._rows(output / "native_source_declarations.jsonl"))
            by_kind_name = {(row["kind"], row["name"]) for row in declarations}
            self.assertIn(("struct", "FThing"), by_kind_name)
            self.assertIn(("method", "DoThing"), by_kind_name)
            self.assertIn(("struct", "HRPoint"), by_kind_name)
            self.assertIn(("typedef", "HRPoint"), by_kind_name)
            self.assertIn(("global", "g_counter"), by_kind_name)
            self.assertIn(("function", "helper"), by_kind_name)
            self.assertIn(("function", "DoRaw"), by_kind_name)

            calls = list(native_source._rows(output / "native_source_calls.jsonl"))
            self.assertEqual([row["callee_spelling"] for row in calls], ["helper"])
            self.assertTrue(all(row["resolution"] == "unresolved_source_syntax" for row in calls))
            self.assertTrue(all(not row["compiler_resolved"] for row in calls))

            joins = list(native_source._rows(output / "native_source_reflection_joins.jsonl"))
            self.assertEqual(len(joins), 2)
            self.assertEqual(
                {row["join_kind"] for row in joins},
                {
                    "reflected_function_source_declaration",
                    "reflected_type_source_declaration",
                },
            )

    def test_validation_rejects_compiler_claim_on_lexical_call(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            self.make_project(project)
            output = project / ".uatool-native"
            output.mkdir()
            self.seed_reflection(output)
            native_source.capture(project, output)

            path = output / "native_source_calls.jsonl"
            rows = list(native_source._rows(path))
            rows[0]["compiler_resolved"] = True
            write_jsonl(path, rows)

            self.assertEqual(
                native_source.validation_error(output),
                "native source call incorrectly claims compiler resolution",
            )

    def test_core_integration_keeps_native_source_bundle_portable(self) -> None:
        core_path = SCRIPTS / "uatool_core.py"
        core = core_path.read_text(encoding="utf-8")
        self.assertIn("import uatool_native_source as native_source", core)
        self.assertIn("native_source.capture(project.parent, output)", core)
        self.assertIn("native source pass incomplete", core)
        self.assertIn(native_source.MANIFEST_FILE, core)
        for filename in native_source.JSONL_FILES:
            self.assertIn(filename, core)


if __name__ == "__main__":
    unittest.main()
