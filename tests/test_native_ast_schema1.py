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


if __name__ == "__main__":
    unittest.main()
