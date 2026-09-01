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

import uatool_chooser_derived as chooser_derived
import uatool_chooser_graph as chooser_graph
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


class ChooserDerivedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.chooser = "/Game/Cameras/CHT.CHT"
        self.other = "/Game/Cameras/Other.Other"
        self.enum = "/Game/Cameras/E_Mode.E_Mode"
        self.rig_a = "/Game/Cameras/RigA.RigA"
        self.rig_b = "/Game/Cameras/RigB.RigB"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> None:
        write_jsonl(self.output / "chooser_tables.jsonl", [
            {"chooser_path": self.chooser, "result_count": 2, "column_count": 1, "context_count": 1,
             "output_object_type": "/Script/GameplayCameras.CameraRigAsset"},
            {"chooser_path": self.other, "result_count": 1, "column_count": 1, "context_count": 1,
             "output_object_type": "/Script/CoreUObject.Object"},
        ])
        column = (
            "/Script/Chooser.EnumColumn("
            "InputValue=/Script/Chooser.EnumContextProperty(Binding=("
            f"Enum=\"/Script/Engine.UserDefinedEnum'{self.enum}'\","
            "PropertyBindingChain=(\"Mode_1_GUID\"),ContextIndex=0,DisplayName=\"Mode\")),"
            "DefaultRowValue=(ValueName=\"\",Comparison=MatchEqual,Value=0),"
            "RowValues=((ValueName=\"E_Mode::NewEnumerator0\"),"
            "(ValueName=\"E_Mode::NewEnumerator1\",Comparison=MatchAny,Value=1)))"
        )
        other_column = (
            "/Script/Chooser.EnumColumn("
            "InputValue=/Script/Chooser.EnumContextProperty(Binding=("
            f"Enum=\"/Script/Engine.UserDefinedEnum'{self.enum}'\",DisplayName=\"Mode\")),"
            "DefaultRowValue=(Comparison=MatchEqual),"
            "RowValues=((ValueName=\"E_Mode::NewEnumerator1\")))"
        )
        write_jsonl(self.output / "chooser_columns.jsonl", [
            {"asset_path": self.chooser, "index": 0, "struct_type": "/Script/Chooser.EnumColumn", "raw_value": column},
            {"asset_path": self.other, "index": 0, "struct_type": "/Script/Chooser.EnumColumn", "raw_value": other_column},
        ])
        write_jsonl(self.output / "chooser_results.jsonl", [
            {"asset_path": self.chooser, "index": 0, "struct_type": "/Script/Chooser.AssetChooser", "disabled": False, "raw_value": "A"},
            {"asset_path": self.chooser, "index": 1, "struct_type": "/Script/Chooser.AssetChooser", "disabled": True, "raw_value": "B"},
            {"asset_path": self.other, "index": 0, "struct_type": "/Script/Chooser.AssetChooser", "disabled": False, "raw_value": "Other"},
        ])
        write_jsonl(self.output / "animation_struct_references.jsonl", [
            {"owner_path": self.chooser, "source_kind": "chooser_result", "source_index": 0,
             "target_path": self.rig_a, "target_class": "/Script/GameplayCameras.CameraRigAsset", "reference_kind": "export_text_object"},
            {"owner_path": self.chooser, "source_kind": "chooser_result", "source_index": 1,
             "target_path": self.rig_b, "target_class": "/Script/GameplayCameras.CameraRigAsset", "reference_kind": "export_text_object"},
        ])
        write_jsonl(self.output / "blueprint_enum_entries.jsonl", [
            {"enum_path": self.enum, "raw_name": "E_Mode::NewEnumerator0", "display_name": "FreeCam", "authored_name": "FreeCam"},
            {"enum_path": self.enum, "raw_name": "E_Mode::NewEnumerator1", "display_name": "TwinStick", "authored_name": "TwinStick"},
        ])

    def test_persists_decisions_predicates_sqlite_and_per_table_completeness(self) -> None:
        self._fixture()
        decisions, predicates = chooser_derived.derive(self.output, rows)
        self.assertEqual(len(decisions), 3)
        self.assertEqual(len(predicates), 3)
        first = next(row for row in decisions if row["chooser_path"] == self.chooser and row["row_index"] == 0)
        second = next(row for row in decisions if row["chooser_path"] == self.chooser and row["row_index"] == 1)
        self.assertTrue(first["fully_modeled"])
        self.assertTrue(first["fully_decoded"])
        self.assertEqual(first["condition_text"], "Mode == FreeCam")
        self.assertEqual(second["condition_text"], "always")
        self.assertTrue(second["disabled"])

        write_jsonl(self.output / "chooser_decisions.jsonl", decisions)
        write_jsonl(self.output / "chooser_decision_predicates.jsonl", predicates)
        self.assertIsNone(chooser_derived.validation_error(self.output, rows))

        conn = sqlite3.connect(":memory:")
        chooser_derived.create_schema(conn)
        chooser_derived.load_database(conn, self.output, rows)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM chooser_decisions").fetchone()[0], 3)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM chooser_decision_predicates").fetchone()[0], 3)
        self.assertEqual(
            conn.execute("SELECT display_value FROM chooser_decision_predicates WHERE chooser_path=? AND row_index=0", (self.chooser,)).fetchone()[0],
            "FreeCam",
        )
        conn.close()

    def test_graph_promotes_exact_decision_result_edges_and_disabled_rows(self) -> None:
        self._fixture()
        decisions, predicates = chooser_derived.derive(self.output, rows)
        write_jsonl(self.output / "chooser_decisions.jsonl", decisions)
        write_jsonl(self.output / "chooser_decision_predicates.jsonl", predicates)

        def node(path: str, kind: str, coverage: str = "first_class", family: str = "test") -> dict:
            return {
                "node_id": project_graph._node_id(kind, path), "node_kind": kind, "path": path,
                "coverage": coverage, "class_path": "", "package_name": project_graph._package(path),
                "family": family, "root": True,
            }

        base_nodes = [
            node(self.chooser, "chooser_table", family="animation"),
            node(self.other, "chooser_table", family="animation"),
            node(self.enum, "user_defined_enum", family="blueprint"),
            node(self.rig_a, "gameplay_camera_rig", family="gameplay_camera"),
            node(self.rig_b, "gameplay_camera_rig", family="gameplay_camera"),
        ]
        nodes_out, edges_out = chooser_graph._augment(self.output, rows, base_nodes, [], project_graph)
        relations = {(edge["relation"], edge["target"]) for edge in edges_out}
        self.assertIn(("selects_chooser_result", self.rig_a), relations)
        self.assertIn(("disabled_chooser_result", self.rig_b), relations)
        self.assertTrue(any(edge["relation"] == "has_chooser_decision" for edge in edges_out))
        self.assertTrue(any(edge["relation"] == "tests_chooser_enum" and edge["target"] == self.enum for edge in edges_out))
        self.assertTrue(all(edge["edge_quality"] == "exact_semantic" for edge in edges_out))
        decision_nodes = [row for row in nodes_out if row["node_kind"] == "chooser_decision"]
        self.assertEqual(len(decision_nodes), 3)


if __name__ == "__main__":
    unittest.main()
