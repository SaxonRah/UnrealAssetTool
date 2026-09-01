from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_gameplay_camera_behavior as behavior
import uatool_gameplay_camera_behavior_graph as behavior_graph
import uatool_project_graph as project_graph


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class GameplayCameraBehaviorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.director = "/Game/Cameras/CameraDirector.CameraDirector"
        self.interface = "/Game/BPI_CameraPawn.BPI_CameraPawn"
        self.interface_class = "/Game/BPI_CameraPawn.BPI_CameraPawn_C"
        self.provider = "/Game/BP_Mover.BP_Mover"
        self.chooser = "/Game/Cameras/CHT_Camera.CHT_Camera"
        self.eval_node = "node:eval"
        self.call_node = "node:get-properties"
        self.provider_graph = "graph:provider"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> None:
        write_jsonl(self.output / "blueprints.jsonl", [
            {
                "object_path": self.director,
                "parent_class": "/Script/GameplayCameras.BlueprintCameraDirectorEvaluator",
                "generated_class": self.director + "_C",
                "implemented_interfaces": [],
            },
            {
                "object_path": self.interface,
                "parent_class": "/Script/CoreUObject.Interface",
                "generated_class": self.interface_class,
                "implemented_interfaces": [],
            },
            {
                "object_path": self.provider,
                "parent_class": "/Script/Engine.Pawn",
                "generated_class": self.provider + "_C",
                "implemented_interfaces": [{"interface_class": self.interface_class}],
            },
        ])
        write_jsonl(self.output / "chooser_tables.jsonl", [{
            "chooser_path": self.chooser,
            "result_count": 1,
            "column_count": 2,
            "context_count": 1,
        }])
        write_jsonl(self.output / "blueprint_relations.jsonl", [{
            "blueprint_path": self.director,
            "relation": "uses_asset",
            "source_id": self.eval_node,
            "target": self.chooser,
        }])
        write_jsonl(self.output / "blueprint_semantic_nodes.jsonl", [
            {
                "node_id": self.eval_node,
                "blueprint_path": self.director,
                "graph_id": "graph:director",
                "graph_name": "EventGraph",
                "operation": "evaluate_chooser",
                "symbol": "CHT_Camera",
                "target": self.chooser + "::CHT_Camera",
                "owner": self.director,
            },
            {
                "node_id": "node:cvar",
                "blueprint_path": self.director,
                "graph_id": "graph:director",
                "graph_name": "EventGraph",
                "operation": "function_call",
                "symbol": "GetConsoleVariableIntValue",
                "owner": "/Script/Engine.KismetSystemLibrary",
                "target": "/Script/Engine.KismetSystemLibrary:GetConsoleVariableIntValue",
            },
            {
                "node_id": "node:mode",
                "blueprint_path": self.provider,
                "graph_id": self.provider_graph,
                "graph_name": "Get_PropertiesForCamera",
                "operation": "function_call",
                "symbol": "Get_CurrentMovementMode",
                "owner": self.provider + "_C",
                "target": self.provider + "_C:Get_CurrentMovementMode",
            },
        ])
        write_jsonl(self.output / "blueprint_semantic_statements.jsonl", [
            {
                "statement_id": "stmt:cvar",
                "node_id": "node:cvar",
                "blueprint_path": self.director,
                "graph_id": "graph:director",
                "graph_name": "EventGraph",
                "block_id": "block:director",
                "block_position": 0,
                "operation": "function_call",
                "text": "GetConsoleVariableIntValue(VariableName=DDCvar.CameraStyle)",
            },
            {
                "statement_id": "stmt:return",
                "node_id": "node:return",
                "blueprint_path": self.provider,
                "graph_id": self.provider_graph,
                "graph_name": "Get_PropertiesForCamera",
                "block_id": "block:provider",
                "block_position": 1,
                "operation": "function_result",
                "text": "return ReturnValue=Make S_CharacterPropertiesForCamera(CameraMode=Aim, MovementMode=Get_CurrentMovementMode.ReturnValue)",
            },
        ])
        write_jsonl(self.output / "blueprint_data_dependencies.jsonl", [
            {
                "dependency_id": "dep:director",
                "blueprint_path": self.director,
                "graph_id": "graph:director",
                "graph_name": "EventGraph",
                "sink_node_id": self.eval_node,
                "sink_operation": "evaluate_chooser",
                "sink_pin_id": "pin:context",
                "sink_pin_name": "S_CharacterPropertiesForCamera",
                "text": "Make S_CharacterPropertiesForCamera(CameraStyle=GetConsoleVariableIntValue.ReturnValue, CameraMode=CharacterPropertiesForCamera.CameraMode, MovementMode=CharacterPropertiesForCamera.MovementMode)",
                "expression": {
                    "kind": "expression",
                    "operation": "make_struct",
                    "label": "Make S_CharacterPropertiesForCamera",
                    "inputs": [
                        {
                            "pin": "CameraStyle_9_3AB8E4E240527073591DBC8A5CC26A59",
                            "sources": [{
                                "kind": "boundary",
                                "operation": "function_call",
                                "label": "GetConsoleVariableIntValue",
                                "node_id": "node:cvar",
                                "output_pin": "ReturnValue",
                            }],
                        },
                        {
                            "pin": "CameraMode_6_A59B5561435DC3553D7444B49C47015A",
                            "sources": [{
                                "kind": "expression",
                                "operation": "break_struct",
                                "label": "Break S_CharacterPropertiesForCamera",
                                "node_id": "node:break-mode",
                                "output_pin": "CameraMode_6_A59B5561435DC3553D7444B49C47015A",
                            }],
                        },
                        {
                            "pin": "MovementMode_29_9179014C47EBE85BE880F78CB6E2E69D",
                            "sources": [{
                                "kind": "expression",
                                "operation": "break_struct",
                                "label": "Break S_CharacterPropertiesForCamera",
                                "node_id": "node:break-movement",
                                "output_pin": "MovementMode_29_9179014C47EBE85BE880F78CB6E2E69D",
                            }],
                        },
                    ],
                },
                "function_calls": ["/Script/Engine.KismetSystemLibrary:GetConsoleVariableIntValue"],
                "object_refs": [],
            },
            {
                "dependency_id": "dep:return",
                "blueprint_path": self.provider,
                "graph_id": self.provider_graph,
                "graph_name": "Get_PropertiesForCamera",
                "sink_node_id": "node:return",
                "sink_operation": "function_result",
                "sink_pin_id": "pin:return",
                "sink_pin_name": "ReturnValue",
                "text": "Make S_CharacterPropertiesForCamera(CameraMode=Aim, MovementMode=Get_CurrentMovementMode.ReturnValue)",
                "expression": {
                    "kind": "expression",
                    "operation": "make_struct",
                    "label": "Make S_CharacterPropertiesForCamera",
                    "inputs": [
                        {
                            "pin": "CameraMode_6_A59B5561435DC3553D7444B49C47015A",
                            "sources": [{"literal": "Aim", "type": "byte"}],
                        },
                        {
                            "pin": "MovementMode_29_9179014C47EBE85BE880F78CB6E2E69D",
                            "sources": [{
                                "kind": "boundary",
                                "operation": "function_call",
                                "label": "Get_CurrentMovementMode",
                                "node_id": "node:mode",
                                "output_pin": "ReturnValue",
                            }],
                        },
                    ],
                },
                "function_calls": [self.provider + "_C:Get_CurrentMovementMode"],
                "object_refs": [],
            },
        ])
        write_jsonl(self.output / "blueprint_pins.jsonl", [])
        write_jsonl(self.output / "blueprint_semantic_blocks.jsonl", [])
        write_jsonl(self.output / "blueprint_functions.jsonl", [
            {
                "function_id": "graph:interface",
                "blueprint_path": self.interface,
                "graph_id": "graph:interface",
                "graph_name": "Get_PropertiesForCamera",
                "name": "Get_PropertiesForCamera",
                "resolved_function": self.interface_class + ":Get_PropertiesForCamera",
                "result_node_ids": ["node:interface-return"],
                "outputs": [{"name": "ReturnValue", "type": {"category": "struct"}}],
            },
            {
                "function_id": self.provider_graph,
                "blueprint_path": self.provider,
                "graph_id": self.provider_graph,
                "graph_name": "Get_PropertiesForCamera",
                "name": "Get_PropertiesForCamera",
                "resolved_function": self.interface_class + ":Get_PropertiesForCamera",
                "result_node_ids": ["node:return"],
                "outputs": [{
                    "name": "ReturnValue",
                    "type": {
                        "category": "struct",
                        "subcategory_object": "/Game/Data/S_CharacterPropertiesForCamera.S_CharacterPropertiesForCamera",
                    },
                }],
            },
        ])
        write_jsonl(self.output / "blueprint_call_edges.jsonl", [{
            "call_id": self.call_node,
            "call_node_id": self.call_node,
            "blueprint_path": self.director,
            "graph_id": "graph:director",
            "graph_name": "EventGraph",
            "target_function": self.interface_class + ":Get_PropertiesForCamera",
            "target_name": "Get_PropertiesForCamera",
            "target_owner": "/Game/BPI_CameraPawn.SKEL_BPI_CameraPawn_C",
            "target_blueprint_path": self.interface,
            "target_function_id": "graph:interface",
            "resolution": "internal",
            "candidate_count": 1,
            "candidate_function_ids": ["graph:interface"],
            "interface_call": True,
        }])

    def test_derives_queryable_provider_fields_inputs_and_sqlite(self) -> None:
        self._fixture()
        providers, fields, inputs = behavior.derive(self.output, rows)
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["provider_blueprint_path"], self.provider)
        self.assertEqual(providers[0]["field_count"], 2)
        self.assertTrue(providers[0]["fully_modeled"])

        fields_by_name = {row["field_name"]: row for row in fields}
        self.assertEqual(set(fields_by_name), {"CameraMode", "MovementMode"})
        self.assertEqual(fields_by_name["CameraMode"]["literal_values"], ["Aim"])
        self.assertEqual(
            fields_by_name["MovementMode"]["function_calls"],
            [self.provider + "_C:Get_CurrentMovementMode"],
        )

        inputs_by_name = {row["field_name"]: row for row in inputs}
        self.assertEqual(set(inputs_by_name), {"CameraStyle", "CameraMode", "MovementMode"})
        self.assertEqual(inputs_by_name["CameraStyle"]["source_kind"], "console_variable")
        self.assertEqual(inputs_by_name["CameraStyle"]["source_name"], "DDCvar.CameraStyle")
        self.assertEqual(inputs_by_name["CameraMode"]["source_kind"], "provider_passthrough")
        self.assertEqual(inputs_by_name["CameraMode"]["provider_field_candidate_count"], 1)
        self.assertEqual(inputs_by_name["MovementMode"]["provider_field_candidate_count"], 1)

        for name, values in zip(behavior.DERIVED_FILES, (providers, fields, inputs)):
            write_jsonl(self.output / name, values)
        self.assertIsNone(behavior.validation_error(self.output, rows))

        conn = sqlite3.connect(":memory:")
        try:
            behavior.create_schema(conn)
            behavior.load_database(conn, self.output, rows)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM gameplay_camera_property_providers").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM gameplay_camera_property_fields").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM gameplay_camera_director_inputs").fetchone()[0], 3)
            self.assertEqual(
                conn.execute("SELECT source_name FROM gameplay_camera_director_inputs WHERE field_name='CameraStyle'").fetchone()[0],
                "DDCvar.CameraStyle",
            )
        finally:
            conn.close()

    def test_graph_preserves_candidate_semantics_and_exact_quality(self) -> None:
        self._fixture()
        nodes, edges = behavior_graph._augment(self.output, rows, [], [], project_graph)
        relations = {row["relation"] for row in edges}
        self.assertIn("has_camera_property_provider_candidate", relations)
        self.assertIn("implements_camera_property_provider", relations)
        self.assertIn("provides_camera_property", relations)
        self.assertIn("builds_camera_context_field", relations)
        self.assertIn("passes_through_camera_property_candidate", relations)
        self.assertIn("reads_console_variable", relations)
        self.assertIn("evaluates_camera_chooser", relations)
        self.assertTrue(all(row.get("edge_quality") == "exact_semantic" for row in edges))
        self.assertEqual(sum(row["relation"] == "passes_through_camera_property_candidate" for row in edges), 2)
        self.assertEqual(sum(row["relation"] == "evaluates_camera_chooser" for row in edges), 1)
        self.assertTrue(any(row.get("node_kind") == "console_variable" for row in nodes))


if __name__ == "__main__":
    unittest.main()
