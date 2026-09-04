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

import uatool_blueprint_semantics as semantics
import uatool_semantic_report as semantic_report


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


def pin(
    pin_id: str,
    node_id: str,
    blueprint_path: str,
    graph_id: str,
    graph_name: str,
    name: str,
    direction: str,
    category: str,
    *,
    subcategory: str = "",
    subcategory_object: str = "",
    container_type: int = 0,
    is_reference: bool = False,
    is_const: bool = False,
) -> dict:
    return {
        "pin_id": pin_id,
        "node_id": node_id,
        "blueprint_path": blueprint_path,
        "graph_id": graph_id,
        "graph_name": graph_name,
        "pin_index": 0,
        "name": name,
        "direction": direction,
        "type": {
            "category": category,
            "subcategory": subcategory,
            "container_type": container_type,
            "is_reference": is_reference,
            "is_const": is_const,
            "subcategory_object": subcategory_object,
        },
        "default_value": "",
        "default_object": "",
        "default_text": "",
        "hidden": False,
        "not_connectable": False,
        "linked_count": 0,
    }


class BlueprintMacroSemanticSchema4Test(unittest.TestCase):
    def _exact_fixture(self, root: Path) -> tuple[str, str, str]:
        caller_bp = "/Game/Test/BP_User.BP_User"
        macro_bp = "/Game/Test/BPL_Macros.BPL_Macros"
        caller_graph = "caller-graph"
        macro_graph_id = "macro-graph"
        macro_graph_path = macro_bp + ":ToggleValue"

        write_jsonl(root / "blueprint_nodes.jsonl", [
            {
                "node_id": "macro-instance",
                "blueprint_path": caller_bp,
                "graph_id": caller_graph,
                "graph_name": "EventGraph",
                "graph_kind": "ubergraph",
                "graph_system": "k2",
                "node_class": "/Script/BlueprintGraph.K2Node_MacroInstance",
                "operation": "macro_instance",
                "symbol": "ToggleValue",
                "owner": macro_bp,
                "semantic": {
                    "macro_graph": macro_graph_path,
                    "source_blueprint": macro_bp,
                },
            },
            {
                "node_id": "entry",
                "blueprint_path": macro_bp,
                "graph_id": macro_graph_id,
                "graph_name": "ToggleValue",
                "graph_kind": "macro",
                "graph_system": "k2",
                "node_class": "/Script/BlueprintGraph.K2Node_Tunnel",
                "operation": "tunnel",
                "symbol": "",
                "owner": "",
                "semantic": {},
            },
            {
                "node_id": "exit",
                "blueprint_path": macro_bp,
                "graph_id": macro_graph_id,
                "graph_name": "ToggleValue",
                "graph_kind": "macro",
                "graph_system": "k2",
                "node_class": "/Script/BlueprintGraph.K2Node_Tunnel",
                "operation": "tunnel",
                "symbol": "",
                "owner": "",
                "semantic": {},
            },
        ])
        write_jsonl(root / "blueprint_graphs.jsonl", [
            {
                "graph_id": caller_graph,
                "blueprint_path": caller_bp,
                "graph_name": "EventGraph",
                "graph_path": caller_bp + ":EventGraph",
                "graph_kind": "ubergraph",
                "graph_system": "k2",
            },
            {
                "graph_id": macro_graph_id,
                "blueprint_path": macro_bp,
                "graph_name": "ToggleValue",
                "graph_path": macro_graph_path,
                "graph_kind": "macro",
                "graph_system": "k2",
            },
        ])
        write_jsonl(root / "blueprint_pins.jsonl", [
            pin("mi-exec-in", "macro-instance", caller_bp, caller_graph, "EventGraph", "execute", "input", "exec"),
            pin(
                "mi-value-in", "macro-instance", caller_bp, caller_graph, "EventGraph",
                "Value", "input", "struct",
                subcategory_object="/Script/CoreUObject.Vector",
                is_reference=True,
            ),
            pin("mi-exec-out", "macro-instance", caller_bp, caller_graph, "EventGraph", "then", "output", "exec"),
            pin("mi-value-out", "macro-instance", caller_bp, caller_graph, "EventGraph", "Result", "output", "boolean"),
            pin("entry-exec", "entry", macro_bp, macro_graph_id, "ToggleValue", "execute", "output", "exec"),
            pin(
                "entry-value", "entry", macro_bp, macro_graph_id, "ToggleValue",
                "Value", "output", "struct",
                subcategory_object="/Script/CoreUObject.Vector",
                is_reference=True,
            ),
            pin("exit-exec", "exit", macro_bp, macro_graph_id, "ToggleValue", "then", "input", "exec"),
            pin("exit-value", "exit", macro_bp, macro_graph_id, "ToggleValue", "Result", "input", "boolean"),
        ])
        write_jsonl(root / "blueprint_edges.jsonl", [])
        return caller_bp, macro_graph_id, macro_graph_path

    def test_exact_project_macro_emits_graph_and_full_pin_proof_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            caller_bp, macro_graph_id, macro_graph_path = self._exact_fixture(root)

            nodes, edges, graphs = semantics.derive(root, rows)
            self.assertEqual(semantics.SEMANTIC_SCHEMA_VERSION, 4)

            by_id = {row["node_id"]: row for row in nodes}
            macro = by_id["macro-instance"]
            self.assertEqual(macro["macro_bridge_status"], "matched")
            self.assertEqual(macro["macro_graph_id"], macro_graph_id)
            self.assertEqual(macro["macro_interface_status"], "exact_bindings")
            self.assertEqual(macro["macro_interface_pin_count"], 4)
            self.assertEqual(macro["macro_interface_binding_count"], 4)

            endpoint = {
                (
                    edge["relation"],
                    edge["target_kind"],
                    edge["target"],
                    edge["source_pin_id"],
                    edge["target_pin_id"],
                    edge["evidence_kind"],
                )
                for edge in edges
                if edge["source_node_id"] == "macro-instance"
            }
            self.assertIn(
                ("invokes_macro", "graph", macro_graph_path, "", "", "node_semantic"),
                endpoint,
            )
            self.assertIn(
                ("maps_to_macro_graph", "blueprint_graph", macro_graph_id, "", "", "macro_graph_exact"),
                endpoint,
            )
            self.assertIn(
                (
                    "binds_macro_input", "blueprint_pin", "entry-value",
                    "mi-value-in", "entry-value", "macro_interface_exact",
                ),
                endpoint,
            )
            self.assertIn(
                (
                    "binds_macro_output", "blueprint_pin", "exit-value",
                    "mi-value-out", "exit-value", "macro_interface_exact",
                ),
                endpoint,
            )
            self.assertEqual(
                sum(1 for edge in edges if edge["relation"] in {"binds_macro_input", "binds_macro_output"}),
                4,
            )

            for filename, file_rows in zip(semantics.DERIVED_FILES, (nodes, edges, graphs)):
                write_jsonl(root / filename, file_rows)
            manifest = {
                "blueprint_semantic_schema_version": semantics.SEMANTIC_SCHEMA_VERSION,
                "derived_counts": {
                    filename.removesuffix(".jsonl"): len(file_rows)
                    for filename, file_rows in zip(semantics.DERIVED_FILES, (nodes, edges, graphs))
                },
            }
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertIsNone(semantics.validation_error(root, rows))

            report = semantic_report.build_report(root, rows)
            self.assertEqual(report["macro_semantic_proof_edge_count"], 5)
            self.assertEqual(dict(report["macro_semantic_proof_edges"]), {
                "binds_macro_input": 2,
                "binds_macro_output": 2,
                "maps_to_macro_graph": 1,
            })

    def test_reference_qualifier_mismatch_does_not_emit_false_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._exact_fixture(root)
            pins = list(rows(root / "blueprint_pins.jsonl"))
            for item in pins:
                if item["pin_id"] == "entry-value":
                    item["type"]["is_reference"] = False
            write_jsonl(root / "blueprint_pins.jsonl", pins)

            nodes, edges, _ = semantics.derive(root, rows)
            macro = {row["node_id"]: row for row in nodes}["macro-instance"]
            self.assertEqual(macro["macro_bridge_status"], "matched")
            self.assertEqual(macro["macro_interface_status"], "partial_bindings")
            self.assertEqual(macro["macro_interface_pin_count"], 4)
            self.assertEqual(macro["macro_interface_binding_count"], 3)
            self.assertFalse(any(
                edge["relation"] == "binds_macro_input"
                and edge["source_pin_id"] == "mi-value-in"
                for edge in edges
            ))

    def test_external_macro_keeps_authored_identity_without_exact_proof_edges(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bp = "/Game/Test/BP_User.BP_User"
            macro_graph = "/Engine/EditorBlueprintResources/StandardMacros.StandardMacros:IsValid"
            write_jsonl(root / "blueprint_nodes.jsonl", [{
                "node_id": "macro-instance",
                "blueprint_path": bp,
                "graph_id": "caller",
                "graph_name": "EventGraph",
                "graph_kind": "ubergraph",
                "graph_system": "k2",
                "node_class": "/Script/BlueprintGraph.K2Node_MacroInstance",
                "operation": "macro_instance",
                "symbol": "IsValid",
                "owner": "/Engine/EditorBlueprintResources/StandardMacros.StandardMacros",
                "semantic": {
                    "macro_graph": macro_graph,
                    "source_blueprint": "/Engine/EditorBlueprintResources/StandardMacros.StandardMacros",
                },
            }])
            write_jsonl(root / "blueprint_graphs.jsonl", [{
                "graph_id": "caller",
                "blueprint_path": bp,
                "graph_name": "EventGraph",
                "graph_path": bp + ":EventGraph",
                "graph_kind": "ubergraph",
                "graph_system": "k2",
            }])
            write_jsonl(root / "blueprint_pins.jsonl", [])
            write_jsonl(root / "blueprint_edges.jsonl", [])

            nodes, edges, _ = semantics.derive(root, rows)
            macro = nodes[0]
            self.assertEqual(macro["macro_bridge_status"], "external_or_unscanned")
            self.assertEqual(macro["macro_graph_id"], "")
            self.assertTrue(any(
                edge["relation"] == "invokes_macro" and edge["target"] == macro_graph
                for edge in edges
            ))
            self.assertFalse(any(
                edge["relation"] in {"maps_to_macro_graph", "binds_macro_input", "binds_macro_output"}
                for edge in edges
            ))


if __name__ == "__main__":
    unittest.main()
