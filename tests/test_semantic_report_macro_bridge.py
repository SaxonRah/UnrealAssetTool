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

    def test_exact_macro_interface_roles_and_pin_bindings_are_structural(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            macro_graph = "/Game/Test/BPL.BPL:ToggleValue"

            write_jsonl(root / "blueprint_semantic_nodes.jsonl", [{
                "node_id": "macro-instance",
                "operation": "macro_instance",
                "semantic_kind": "call",
                "opaque": False,
                "blueprint_path": "/Game/Test/BP_User.BP_User",
            }])
            write_jsonl(root / "blueprint_nodes.jsonl", [
                {
                    "node_id": "macro-instance",
                    "graph_id": "caller",
                    "operation": "macro_instance",
                    "semantic": {
                        "macro_graph": macro_graph,
                        "source_blueprint": "/Game/Test/BPL.BPL",
                    },
                },
                {
                    "node_id": "entry",
                    "graph_id": "macro-graph-id",
                    "operation": "tunnel",
                    "semantic": {},
                },
                {
                    "node_id": "exit",
                    "graph_id": "macro-graph-id",
                    "operation": "tunnel",
                    "semantic": {},
                },
            ])
            write_jsonl(root / "blueprint_graphs.jsonl", [{
                "graph_id": "macro-graph-id",
                "graph_path": macro_graph,
            }])

            bool_type = {
                "category": "boolean",
                "subcategory": "",
                "container_type": 0,
                "is_reference": False,
                "is_const": False,
                "subcategory_object": "",
            }
            exec_type = {
                "category": "exec",
                "subcategory": "",
                "container_type": 0,
                "is_reference": False,
                "is_const": False,
                "subcategory_object": "",
            }
            pins = [
                # Macro instance call surface.
                ("mi-exec-in", "macro-instance", "execute", "input", exec_type),
                ("mi-value-in", "macro-instance", "Value", "input", bool_type),
                ("mi-exec-out", "macro-instance", "then", "output", exec_type),
                ("mi-value-out", "macro-instance", "Result", "output", bool_type),
                # Macro input tunnel exposes values into the macro body.
                ("entry-exec", "entry", "execute", "output", exec_type),
                ("entry-value", "entry", "Value", "output", bool_type),
                # Macro output tunnel consumes values from the macro body.
                ("exit-exec", "exit", "then", "input", exec_type),
                ("exit-value", "exit", "Result", "input", bool_type),
            ]
            write_jsonl(root / "blueprint_pins.jsonl", [
                {
                    "pin_id": pin_id,
                    "node_id": node_id,
                    "blueprint_path": "/Game/Test/BP_User.BP_User",
                    "graph_id": "caller" if node_id == "macro-instance" else "macro-graph-id",
                    "graph_name": "EventGraph" if node_id == "macro-instance" else "ToggleValue",
                    "pin_index": index,
                    "name": name,
                    "direction": direction,
                    "type": pin_type,
                    "default_value": "",
                    "default_object": "",
                    "default_text": "",
                    "hidden": False,
                    "not_connectable": False,
                    "linked_count": 0,
                }
                for index, (pin_id, node_id, name, direction, pin_type) in enumerate(pins)
            ])

            result = report.build_report(root, rows)
            self.assertEqual(result["macro_interface_graph_count"], 1)
            self.assertEqual(result["macro_interface_exact_role_graph_count"], 1)
            self.assertEqual(result["macro_interface_unresolved_role_graph_count"], 0)
            self.assertEqual(result["macro_binding_instance_count"], 1)
            self.assertEqual(result["macro_binding_resolved_instance_count"], 1)
            self.assertEqual(result["macro_binding_pin_count"], 4)
            self.assertEqual(result["macro_binding_exact_pin_count"], 4)
            self.assertEqual(dict(result["macro_binding_status"]), {"exact_pin_binding": 4})
            self.assertEqual(result["macro_binding_mismatches"], [])

    def test_macro_pin_name_match_with_type_mismatch_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            macro_graph = "/Game/Test/BPL.BPL:Typed"

            write_jsonl(root / "blueprint_semantic_nodes.jsonl", [{
                "node_id": "macro-instance",
                "operation": "macro_instance",
                "semantic_kind": "call",
                "opaque": False,
            }])
            write_jsonl(root / "blueprint_nodes.jsonl", [
                {
                    "node_id": "macro-instance",
                    "graph_id": "caller",
                    "operation": "macro_instance",
                    "semantic": {"macro_graph": macro_graph},
                },
                {"node_id": "entry", "graph_id": "g", "operation": "tunnel", "semantic": {}},
                {"node_id": "exit", "graph_id": "g", "operation": "tunnel", "semantic": {}},
            ])
            write_jsonl(root / "blueprint_graphs.jsonl", [{
                "graph_id": "g",
                "graph_path": macro_graph,
            }])

            def pin(
                pin_id: str, node_id: str, name: str, direction: str, category: str,
                *, is_reference: bool = False, is_const: bool = False,
            ) -> dict:
                return {
                    "pin_id": pin_id,
                    "node_id": node_id,
                    "blueprint_path": "/Game/Test/BP.BP",
                    "graph_id": "caller" if node_id == "macro-instance" else "g",
                    "graph_name": "EventGraph" if node_id == "macro-instance" else "Typed",
                    "pin_index": 0,
                    "name": name,
                    "direction": direction,
                    "type": {
                        "category": category,
                        "subcategory": "",
                        "container_type": 0,
                        "is_reference": is_reference,
                        "is_const": is_const,
                        "subcategory_object": "",
                    },
                    "default_value": "",
                    "default_object": "",
                    "default_text": "",
                    "hidden": False,
                    "not_connectable": False,
                    "linked_count": 0,
                }

            write_jsonl(root / "blueprint_pins.jsonl", [
                pin("mi", "macro-instance", "Value", "input", "float"),
                pin("entry", "entry", "Value", "output", "int"),
                pin("exit", "exit", "Result", "input", "float"),
            ])

            result = report.build_report(root, rows)
            self.assertEqual(result["macro_binding_pin_count"], 1)
            self.assertEqual(result["macro_binding_exact_pin_count"], 0)
            self.assertIn(("name_match_type_mismatch", 1), result["macro_binding_status"])

    def test_macro_pin_reference_qualifier_mismatch_is_not_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            macro_graph = "/Game/Test/BPL.BPL:ByRef"

            write_jsonl(root / "blueprint_semantic_nodes.jsonl", [{
                "node_id": "macro-instance",
                "operation": "macro_instance",
                "semantic_kind": "call",
                "opaque": False,
            }])
            write_jsonl(root / "blueprint_nodes.jsonl", [
                {
                    "node_id": "macro-instance",
                    "graph_id": "caller",
                    "operation": "macro_instance",
                    "semantic": {"macro_graph": macro_graph},
                },
                {"node_id": "entry", "graph_id": "g", "operation": "tunnel", "semantic": {}},
                {"node_id": "exit", "graph_id": "g", "operation": "tunnel", "semantic": {}},
            ])
            write_jsonl(root / "blueprint_graphs.jsonl", [{"graph_id": "g", "graph_path": macro_graph}])

            def pin(pin_id: str, node_id: str, direction: str, is_reference: bool) -> dict:
                return {
                    "pin_id": pin_id,
                    "node_id": node_id,
                    "blueprint_path": "/Game/Test/BP.BP",
                    "graph_id": "caller" if node_id == "macro-instance" else "g",
                    "graph_name": "EventGraph" if node_id == "macro-instance" else "ByRef",
                    "pin_index": 0,
                    "name": "Value",
                    "direction": direction,
                    "type": {
                        "category": "struct",
                        "subcategory": "",
                        "container_type": 0,
                        "is_reference": is_reference,
                        "is_const": False,
                        "subcategory_object": "/Script/CoreUObject.Vector",
                    },
                    "default_value": "",
                    "default_object": "",
                    "default_text": "",
                    "hidden": False,
                    "not_connectable": False,
                    "linked_count": 0,
                }

            write_jsonl(root / "blueprint_pins.jsonl", [
                pin("mi", "macro-instance", "input", True),
                pin("entry", "entry", "output", False),
                {
                    **pin("exit", "exit", "input", False),
                    "name": "Result",
                },
            ])

            result = report.build_report(root, rows)
            self.assertEqual(result["macro_binding_pin_count"], 1)
            self.assertEqual(result["macro_binding_exact_pin_count"], 0)
            self.assertIn(("name_match_type_mismatch", 1), result["macro_binding_status"])

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
