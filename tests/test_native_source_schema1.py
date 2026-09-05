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
        nested = public / "Runtime" / "include"
        nested.mkdir(parents=True)
        (nested / "Nested.h").write_text("#pragma once\n", encoding="utf-8")
        (module / "HRRAI.Build.cs").write_text("// synthetic module\n", encoding="utf-8")

        (public / "Api.h").write_text(
            textwrap.dedent(
                """
                #pragma once

                #define SYNTH_CHECK(v) \
                    do { if (!(v)) abort(); } while (0)

                namespace TestHelpers
                {
                    inline int HeaderHelper(int Value)
                    {
                        return Value + 1;
                    }
                }

                extern "C"
                {
                    int CApi(int Value);
                }

                class UForward;

                UENUM(BlueprintType)
                enum class EThingState : uint8
                {
                    Idle,
                    Active,
                };

                USTRUCT(BlueprintType)
                struct HRRAI_API FThing
                {
                    GENERATED_BODY()

                    FThing();

                    UPROPERTY(EditAnywhere)
                    FName Label = TEXT("Thing");

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
                #include "Nested.h"

                typedef struct {
                    int x, y;
                    char name[16];
                    int slots[HR_COUNT];
                    unsigned flags : HR_BITS;
                } HRPoint;
                typedef enum { RawIdle, RawActive } HRRawState;
                typedef void (*HRCallback)(int value, void *userdata);
                static int g_counter = 0, g_other = 1;

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
                    "name": "Thing",
                    "cpp_name": "FThing",
                    "metadata": {"ModuleRelativePath": "Public/Api.h"},
                }
            ],
        )
        write_jsonl(
            output / "native_enums.jsonl",
            [
                {
                    "enum_path": "/Script/HRRAI.EThingState",
                    "module_name": "HRRAI",
                    "name": "EThingState",
                    "cpp_type": "EThingState",
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
            self.assertEqual(len(files), 3)
            self.assertTrue(any(row["path"].endswith("/Private/raw.c") for row in files))
            self.assertTrue(any(row["path"].endswith("/Public/Api.h") for row in files))

            includes = list(native_source._rows(output / "native_source_includes.jsonl"))
            self.assertEqual(len(includes), 2)
            include_by_target = {row["target_spelling"]: row for row in includes}
            self.assertTrue(
                include_by_target["../Public/Api.h"]["resolved_project_path"].endswith("/Public/Api.h")
            )
            self.assertEqual(
                include_by_target["Nested.h"]["resolution"],
                "project_unique_suffix",
            )
            self.assertTrue(
                include_by_target["Nested.h"]["resolved_project_path"].endswith(
                    "/Public/Runtime/include/Nested.h"
                )
            )
            self.assertTrue(all(not row["compiler_resolved"] for row in includes))

            declarations = list(native_source._rows(output / "native_source_declarations.jsonl"))
            by_kind_name = {(row["kind"], row["name"]) for row in declarations}
            self.assertIn(("struct", "FThing"), by_kind_name)
            self.assertIn(("method", "FThing"), by_kind_name)
            self.assertIn(("method", "DoThing"), by_kind_name)
            self.assertIn(("class", "UForward"), by_kind_name)
            forward_globals = [
                row
                for row in declarations
                if row["kind"] == "global" and row["name"] == "UForward"
            ]
            self.assertEqual(forward_globals, [])
            self.assertIn(("field", "Label"), by_kind_name)
            self.assertIn(("namespace", "TestHelpers"), by_kind_name)
            self.assertIn(("function", "HeaderHelper"), by_kind_name)
            self.assertIn(("linkage_block", "extern_C"), by_kind_name)
            self.assertIn(("function", "CApi"), by_kind_name)
            self.assertIn(("enum_class", "EThingState"), by_kind_name)
            self.assertNotIn(("method", "TEXT"), by_kind_name)
            self.assertNotIn(("function", "abort"), by_kind_name)
            self.assertIn(("typedef", "HRPoint"), by_kind_name)
            self.assertIn(("typedef", "HRRawState"), by_kind_name)
            self.assertIn(("typedef", "HRCallback"), by_kind_name)
            self.assertNotIn(("typedef", "userdata"), by_kind_name)
            self.assertNotIn(("typedef", "struct"), by_kind_name)
            self.assertNotIn(("typedef", "enum"), by_kind_name)
            self.assertIn(("field", "x"), by_kind_name)
            self.assertIn(("field", "y"), by_kind_name)
            self.assertIn(("field", "name"), by_kind_name)
            self.assertIn(("field", "slots"), by_kind_name)
            self.assertIn(("field", "flags"), by_kind_name)
            self.assertNotIn(("field", "HR_COUNT"), by_kind_name)
            self.assertNotIn(("field", "HR_BITS"), by_kind_name)
            array_fields = {
                row["name"]: row["type_text"]
                for row in declarations
                if row["kind"] == "field" and row["name"] in {"name", "slots"}
            }
            self.assertIn("[16]", array_fields["name"].replace(" ", ""))
            self.assertIn("[HR_COUNT]", array_fields["slots"].replace(" ", ""))
            self.assertNotIn(("global", "x"), by_kind_name)
            self.assertNotIn(("global", "y"), by_kind_name)
            self.assertIn(("global", "g_counter"), by_kind_name)
            self.assertIn(("global", "g_other"), by_kind_name)
            self.assertIn(("function", "helper"), by_kind_name)
            self.assertIn(("function", "DoRaw"), by_kind_name)

            calls = list(native_source._rows(output / "native_source_calls.jsonl"))
            self.assertEqual([row["callee_spelling"] for row in calls], ["helper"])
            self.assertTrue(all(row["resolution"] == "unresolved_source_syntax" for row in calls))
            self.assertTrue(all(not row["compiler_resolved"] for row in calls))

            joins = list(native_source._rows(output / "native_source_reflection_joins.jsonl"))
            self.assertEqual(len(joins), 3)
            self.assertEqual(
                {row["join_kind"] for row in joins},
                {
                    "reflected_function_source_declaration",
                    "reflected_type_source_declaration",
                    "reflected_enum_source_declaration",
                },
            )

    def test_out_of_class_destructor_keeps_qualification(self) -> None:
        declarations, parameters, calls = native_source._parse_declarations_and_calls(
            native_source.tokenize("MyClass::~MyClass() {}\n"),
            "Source/Test.cpp",
            "Test",
        )
        self.assertEqual(len(declarations), 1)
        row = declarations[0]
        self.assertEqual(row["name"], "~MyClass")
        self.assertEqual(row["qualified_name"], "MyClass::~MyClass")
        self.assertEqual(row["return_type_text"], "")
        self.assertEqual(parameters, [])
        self.assertEqual(calls, [])

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
