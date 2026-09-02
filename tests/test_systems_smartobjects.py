from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_smartobjects as smart
import uatool_smartobject_graph as graph


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def valid_rows() -> dict[str, list[dict]]:
    definition = "/Game/AI/SmartObject/SOD_Test.SOD_Test"
    behavior = definition + ":SmartObjectMassBehaviorDefinition_0"
    behavior_class = "/Script/MassSmartObjects.SmartObjectMassBehaviorDefinition"
    schema = "/Script/SmartObjectsModule.SmartObjectWorldConditionSchema"
    return {
        "smartobject_definitions.jsonl": [{
            "definition_path": definition,
            "package_name": "/Game/AI/SmartObject/SOD_Test",
            "class_path": "/Script/SmartObjectsModule.SmartObjectDefinition",
            "slot_count": 2,
            "default_behavior_count": 1,
            "activity_tags": "(GameplayTags=())",
            "user_tag_filter": "()",
            "object_tag_filter": "()",
            "preconditions": "()",
            "world_condition_schema_class": schema,
            "activity_tags_merging_policy": "Override",
            "user_tags_filtering_policy": "Override",
        }],
        "smartobject_slots.jsonl": [{
            "definition_path": definition, "slot_index": 0,
            "slot_id": "573FF06A43CF8E90E0C1A6A26469B851", "name": "None", "enabled": True,
            "offset_x": -85.0, "offset_y": 0.0, "offset_z": 0.0,
            "rotation_pitch": 0.0, "rotation_yaw": 90.0, "rotation_roll": 0.0,
            "user_tag_filter": "()", "activity_tags": "(GameplayTags=())", "runtime_tags": "(GameplayTags=())",
            "selection_preconditions": "()", "selection_schema_class": schema,
            "behavior_count": 0, "definition_data_count": 0,
        }, {
            "definition_path": definition, "slot_index": 1,
            "slot_id": "E321BAA54EA72F347C192C9A0530BCB5", "name": "None", "enabled": True,
            "offset_x": 85.0, "offset_y": 0.0, "offset_z": 0.0,
            "rotation_pitch": 0.0, "rotation_yaw": 90.0, "rotation_roll": 0.0,
            "user_tag_filter": "()", "activity_tags": "(GameplayTags=())", "runtime_tags": "(GameplayTags=())",
            "selection_preconditions": "()", "selection_schema_class": schema,
            "behavior_count": 0, "definition_data_count": 0,
        }],
        "smartobject_behaviors.jsonl": [{
            "definition_path": definition, "scope": "default", "slot_index": -1, "behavior_index": 0,
            "behavior_path": behavior, "behavior_class": behavior_class, "property_count": 1,
        }],
        "smartobject_behavior_properties.jsonl": [{
            "definition_path": definition, "behavior_path": behavior, "property_index": 0,
            "declaring_type": behavior_class, "property_name": "UseTime",
            "property_type": "FloatProperty", "cpp_type": "float", "value": "5.000000", "truncated": False,
        }],
    }


class SystemsSmartObjectsTest(unittest.TestCase):
    def populate(self, root: Path, rows_by_file=None) -> None:
        rows_by_file = rows_by_file or valid_rows()
        for filename in smart.SMARTOBJECT_FILES:
            write_jsonl(root / filename, rows_by_file.get(filename, []))

    def test_citysample_shaped_rows_validate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.populate(root)
            self.assertIsNone(smart.validation_error(root))

    def test_default_behavior_is_not_flattened_onto_slots(self) -> None:
        rows = valid_rows()
        self.assertEqual([row["behavior_count"] for row in rows["smartobject_slots.jsonl"]], [0, 0])
        self.assertEqual(rows["smartobject_behaviors.jsonl"][0]["scope"], "default")
        self.assertEqual(rows["smartobject_behaviors.jsonl"][0]["slot_index"], -1)

    def test_slot_identity_and_counts_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = valid_rows()
            rows["smartobject_slots.jsonl"][1]["slot_id"] = rows["smartobject_slots.jsonl"][0]["slot_id"]
            self.populate(root, rows)
            self.assertIn("slot_id is duplicated", smart.validation_error(root) or "")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = valid_rows()
            rows["smartobject_definitions.jsonl"][0]["slot_count"] = 3
            self.populate(root, rows)
            self.assertIn("slot count mismatch", smart.validation_error(root) or "")

    def test_behavior_scope_and_property_count_are_strict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = valid_rows()
            rows["smartobject_behaviors.jsonl"][0]["scope"] = "slot"
            self.populate(root, rows)
            self.assertIn("invalid slot_index", smart.validation_error(root) or "")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = valid_rows()
            rows["smartobject_behavior_properties.jsonl"][0]["truncated"] = True
            self.populate(root, rows)
            self.assertIn("truncated", smart.validation_error(root) or "")

    def test_sqlite_round_trip_and_query(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.populate(root)
            conn = sqlite3.connect(":memory:")
            smart.create_schema(conn)
            smart.load_database(conn, root)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM smartobject_definitions").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM smartobject_slots").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT scope,slot_index FROM smartobject_behaviors").fetchone(), ("default", -1))
            self.assertEqual(conn.execute("SELECT property_name,value FROM smartobject_behavior_properties").fetchone(), ("UseTime", "5.000000"))

            def print_rows(cursor, headers):
                list(cursor)

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                smart.query(conn, print_rows, "%SOD_Test%", 20)
            self.assertIn("Smart Object definitions", buffer.getvalue())

    def test_exact_graph_uses_slot_guid_identity_and_default_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.populate(root)
            rows = smart._read_rows
            definition = valid_rows()["smartobject_definitions.jsonl"][0]["definition_path"]
            first_slot_id = valid_rows()["smartobject_slots.jsonl"][0]["slot_id"]
            first_slot = graph.slot_path(definition, first_slot_id)
            behavior = valid_rows()["smartobject_behaviors.jsonl"][0]["behavior_path"]
            keys = graph.expected_edge_keys(root, rows)
            self.assertIn((definition, "has_smart_object_slot", first_slot), keys)
            self.assertIn((definition, "has_default_smart_object_behavior", behavior), keys)
            self.assertFalse(any(relation == "has_smart_object_behavior" for _, relation, _ in keys))
            self.assertEqual(len(keys), 7)

    def test_native_scanner_contract_is_reflection_first(self) -> None:
        scanner = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp").read_text(encoding="utf-8")
        native = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsSmartObjects.inl").read_text(encoding="utf-8")
        policy = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsSmartObjectsPolicy.inl").read_text(encoding="utf-8")
        build_cs = (ROOT / "Source/UnrealAssetTool/UnrealAssetTool.Build.cs").read_text(encoding="utf-8")
        self.assertIn('UnrealAssetToolSystemsSmartObjects.inl', scanner)
        self.assertIn('UnrealAssetToolSystemsSmartObjectsPolicy.inl', scanner)
        self.assertIn('ClassInheritsName(Definition->GetClass(), TEXT("SmartObjectDefinition"))', native)
        self.assertIn('FName(TEXT("DefaultBehaviorDefinitions"))', native)
        self.assertIn('FName(TEXT("BehaviorDefinitions"))', native)
        self.assertIn('Root->SetNumberField(TEXT("schema_version"), 7)', policy)
        self.assertNotIn('#include "SmartObject', scanner)
        self.assertNotIn('"SmartObjectsModule"', build_cs)

    def test_canonical_composition_promotes_schema7_and_capture_membership(self) -> None:
        import uatool
        import uatool_project_graph
        import uatool_systems
        import uatool_systems_capture

        self.assertEqual(uatool_systems.SYSTEMS_SCHEMA_VERSION, 7)
        self.assertEqual(uatool.FINAL_DERIVED_SCHEMA_VERSION, 23)
        self.assertEqual(uatool_project_graph.DERIVED_SCHEMA_VERSION, 23)
        self.assertTrue(getattr(uatool_project_graph, "_smartobject_graph_installed", False))
        self.assertTrue(set(smart.SMARTOBJECT_FILES).issubset(uatool_systems.JSONL_FILES))
        self.assertTrue(set(smart.SMARTOBJECT_FILES).issubset(uatool_systems_capture.CAPTURE_FILES))


if __name__ == "__main__":
    unittest.main()
