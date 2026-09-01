from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_gameplay_camera_selection_report as selection_report


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


class GameplayCameraSelectionReportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.bp = "/Game/Cameras/BP_Director.BP_Director"
        self.generated = "/Game/Cameras/BP_Director.BP_Director_C"
        self.chooser = "/Game/Cameras/CHT_CameraRig.CHT_CameraRig"
        self.rig = "/Game/Cameras/Rigs/CameraRig_Close.CameraRig_Close"
        self.asset = "/Game/Cameras/CameraAsset.CameraAsset"
        self.director = self.asset + ":BlueprintCameraDirector_0"
        self.enum = "/Game/Cameras/E_CameraStyle.E_CameraStyle"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        write_jsonl(self.output / "blueprints.jsonl", [{
            "object_path": self.bp,
            "parent_class": "/Script/GameplayCameras.BlueprintCameraDirectorEvaluator",
            "generated_class": self.generated,
        }])
        write_jsonl(self.output / "blueprint_relations.jsonl", [{
            "blueprint_path": self.bp,
            "relation": "uses_asset",
            "source_id": "node-1",
            "target_kind": "chooser_table",
            "target": self.chooser,
        }])
        write_jsonl(self.output / "project_edges.jsonl", [])
        write_jsonl(self.output / "chooser_tables.jsonl", [{
            "chooser_path": self.chooser,
            "package_name": "/Game/Cameras/CHT_CameraRig",
            "output_object_type": "/Script/GameplayCameras.CameraRigAsset",
            "result_count": 1,
            "column_count": 1,
            "context_count": 1,
        }])
        raw_column = (
            "/Script/Chooser.EnumColumn("
            "InputValue=/Script/Chooser.EnumContextProperty(Binding=("
            f"Enum=\"/Script/Engine.UserDefinedEnum'{self.enum}'\","
            "PropertyBindingChain=(\"CameraStyle_GUID\"),ContextIndex=0,"
            "IsBoundToRoot=False,DisplayName=\"CameraStyle\")),"
            "DefaultRowValue=(ValueName=\"\",Comparison=MatchEqual,Value=0),"
            "RowValues=((ValueName=\"E_CameraStyle::NewEnumerator2\",Value=2)),"
            "bDisabled=False)"
        )
        write_jsonl(self.output / "chooser_columns.jsonl", [{
            "asset_path": self.chooser,
            "index": 0,
            "struct_type": "/Script/Chooser.EnumColumn",
            "raw_value": raw_column,
            "truncated": False,
        }])
        write_jsonl(self.output / "chooser_results.jsonl", [{
            "asset_path": self.chooser,
            "index": 0,
            "struct_type": "/Script/Chooser.ObjectChooser",
            "raw_value": f"(Object=\"/Script/GameplayCameras.CameraRigAsset'{self.rig}'\")",
            "truncated": False,
            "disabled": False,
        }])
        write_jsonl(self.output / "chooser_context.jsonl", [{
            "asset_path": self.chooser,
            "index": 0,
            "struct_type": "/Script/Chooser.StructContextProperty",
            "raw_value": "(BindingName=CharacterPropertiesForCamera)",
            "truncated": False,
        }])
        write_jsonl(self.output / "animation_struct_references.jsonl", [{
            "owner_path": self.chooser,
            "source_kind": "chooser_result",
            "source_index": 0,
            "reference_kind": "export_text_object",
            "target_path": self.rig,
            "target_class": "/Script/GameplayCameras.CameraRigAsset",
        }])
        write_jsonl(self.output / "blueprint_enum_entries.jsonl", [{
            "enum_path": self.enum,
            "enum_index": 2,
            "numeric_value": 2,
            "raw_name": "E_CameraStyle::NewEnumerator2",
            "authored_name": "Close",
            "display_name": "Close",
            "tooltip": "",
            "hidden": False,
            "is_max": False,
        }])
        write_jsonl(self.output / "gameplay_camera_assets.jsonl", [{
            "camera_asset_path": self.asset,
            "director_path": self.director,
            "director_class": "/Script/GameplayCameras.BlueprintCameraDirector",
        }])
        write_jsonl(self.output / "gameplay_camera_directors.jsonl", [{
            "asset_path": self.asset,
            "director_path": self.director,
            "director_class": "/Script/GameplayCameras.BlueprintCameraDirector",
        }])
        write_jsonl(self.output / "gameplay_camera_rigs.jsonl", [{
            "rig_path": self.rig,
            "class_path": "/Script/GameplayCameras.CameraRigAsset",
        }])
        write_jsonl(self.output / "systems_references.jsonl", [{
            "asset_path": self.asset,
            "owner_path": self.director,
            "owner_kind": "gameplay_camera_director",
            "root_property": "CameraDirectorClass",
            "property_path": "CameraDirectorClass",
            "reference_kind": "hard_object",
            "target_path": self.generated,
            "target_class": "/Script/CoreUObject.Class",
        }])

    def test_joins_director_blueprint_chooser_and_normalized_rig(self) -> None:
        self._write_fixture()
        report = selection_report.build_report(self.output, rows)
        self.assertEqual(len(report["director_blueprints"]), 1)
        self.assertEqual(len(report["camera_asset_director_links"]), 1)
        self.assertEqual(len(report["director_chooser_links"]), 1)
        self.assertEqual(len(report["chooser_tables"]), 1)
        self.assertEqual(len(report["chooser_columns"]), 1)
        self.assertEqual(len(report["chooser_results"]), 1)
        self.assertEqual(report["rig_result_count"], 1)
        self.assertEqual(report["unresolved_rig_result_count"], 0)
        self.assertEqual(
            report["result_refs"][(self.chooser, 0)][0]["target_path"],
            self.rig,
        )
        self.assertEqual(len(report["chooser_decisions"]), 1)
        decision = report["chooser_decisions"][0]
        self.assertTrue(decision["fully_decoded"])
        self.assertEqual(decision["condition_text"], "CameraStyle == Close")

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            selection_report.print_report(report)
        text = buffer.getvalue()
        self.assertIn("BP_Director", text)
        self.assertIn("CHT_CameraRig", text)
        self.assertIn("CameraRig_Close", text)
        self.assertIn("CameraStyle == Close", text)
        self.assertIn("decoded=True", text)


if __name__ == "__main__":
    unittest.main()
