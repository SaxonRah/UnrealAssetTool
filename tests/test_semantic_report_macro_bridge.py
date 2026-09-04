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

import uatool_semantic_report as report


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(value, separators=(",", ":")) + "\n" for value in values),
        encoding="utf-8",
    )


def rows(path: Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            yield json.loads(line)


class SemanticReportMacroBridgeTest(unittest.TestCase):
    def test_exact_macro_graph_bridge_separates_external_missing_and_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bp = "/Game/Test/BP_User.BP_User"

            write_jsonl(root / "blueprint_semantic_nodes.jsonl", [
                {
                    "node_id": "matched",
                    "operation": "macro_instance",
                    "semantic_kind": "call",
                    "opaque": False,
                    "blueprint_path": bp,
                },
                {
                    "node_id": "external",
                    "operation": "macro_instance",
                    "semantic_kind": "call",
                    "opaque": False,
                    "blueprint_path": bp,
                },
                {
                    "node_id": "missing",
                    "operation": "macro_instance",
                    "semantic_kind": "call",
                    "opaque": False,
                    "blueprint_path": bp,
                },
                {
                    "node_id": "ambiguous",
                    "operation": "macro_instance",
                    "semantic_kind": "call",
                    "opaque": False,
                    "blueprint_path": bp,
                },
            ])
            write_jsonl(root / "blueprint_nodes.jsonl", [
                {
                    "node_id": "matched",
                    "operation": "macro_instance",
                    "semantic": {
                        "macro_graph": "/Game/Test/BPL_Macros.BPL_Macros:ForEach",
                        "source_blueprint": "/Game/Test/BPL_Macros.BPL_Macros",
                    },
                },
                {
                    "node_id": "external",
                    "operation": "macro_instance",
                    "semantic": {
                        "macro_graph": "/Engine/EditorBlueprintResources/StandardMacros.StandardMacros:ForLoop",
                        "source_blueprint": "/Engine/EditorBlueprintResources/StandardMacros.StandardMacros",
                    },
                },
                {
                    "node_id": "missing",
                    "operation": "macro_instance",
                    "semantic": {
                        "macro_graph": "",
                        "source_blueprint": "",
                    },
                },
                {
                    "node_id": "ambiguous",
                    "operation": "macro_instance",
                    "semantic": {
                        "macro_graph": "/Game/Test/BPL_Duplicate.BPL_Duplicate:Macro",
                        "source_blueprint": "/Game/Test/BPL_Duplicate.BPL_Duplicate",
                    },
                },
            ])
            write_jsonl(root / "blueprint_graphs.jsonl", [
                {
                    "graph_id": "g-matched",
                    "graph_path": "/Game/Test/BPL_Macros.BPL_Macros:ForEach",
                },
                {
                    "graph_id": "g-dup-a",
                    "graph_path": "/Game/Test/BPL_Duplicate.BPL_Duplicate:Macro",
                },
                {
                    "graph_id": "g-dup-b",
                    "graph_path": "/Game/Test/BPL_Duplicate.BPL_Duplicate:Macro",
                },
            ])

            result = report.build_report(root, rows)
            self.assertEqual(result["macro_instance_count"], 4)
            self.assertEqual(result["macro_semantic_node_count"], 4)
            self.assertEqual(result["macro_matched_count"], 1)
            self.assertEqual(result["macro_external_count"], 1)
            self.assertEqual(result["macro_missing_graph_identity_count"], 1)
            self.assertEqual(result["macro_ambiguous_graph_path_count"], 1)
            self.assertEqual(result["macro_missing_semantic_node_count"], 0)
            self.assertEqual(result["macro_duplicate_captured_graph_path_count"], 1)

            text = []
            import contextlib
            import io
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                report.print_report(result)
            rendered = buffer.getvalue()
            self.assertIn("[Macro Instance -> Macro Graph bridge]", rendered)
            self.assertIn("exact_graph_matches=1", rendered)
            self.assertIn("external_or_unscanned=1", rendered)
            self.assertIn("missing_graph_identity=1", rendered)
            self.assertIn("ambiguous_graph_paths=1", rendered)

    def test_missing_semantic_macro_node_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_jsonl(root / "blueprint_semantic_nodes.jsonl", [])
            write_jsonl(root / "blueprint_nodes.jsonl", [{
                "node_id": "macro",
                "operation": "macro_instance",
                "semantic": {
                    "macro_graph": "/Game/Test/BPL.BPL:Macro",
                    "source_blueprint": "/Game/Test/BPL.BPL",
                },
            }])
            write_jsonl(root / "blueprint_graphs.jsonl", [{
                "graph_id": "g",
                "graph_path": "/Game/Test/BPL.BPL:Macro",
            }])

            result = report.build_report(root, rows)
            self.assertEqual(result["macro_instance_count"], 1)
            self.assertEqual(result["macro_semantic_node_count"], 0)
            self.assertEqual(result["macro_missing_semantic_node_count"], 1)
            self.assertEqual(result["macro_matched_count"], 1)


if __name__ == "__main__":
    unittest.main()
