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

import uatool_dataflow_chaos_capture as capture


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


class DataflowChaosCaptureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_discovery_uses_exact_classes_and_destruction_prefix(self) -> None:
        destruction_df = "/Game/ExampleContent/Destruction/Dataflow/DF_A.DF_A"
        destruction_gc = "/Game/ExampleContent/Destruction/GC/GC_A.GC_A"
        hair_df = "/Game/MetaHumans/Aera/Grooms/DF_Hair.DF_Hair"
        write_jsonl(self.root / "assets.jsonl", [
            {"object_path": destruction_df, "class_path": capture.DATAFLOW_CLASS},
            {"object_path": destruction_gc, "class_path": capture.GEOMETRY_COLLECTION_CLASS},
            {"object_path": hair_df, "class_path": capture.DATAFLOW_CLASS},
            {"object_path": "/Game/ExampleContent/Destruction/Caches/C.C", "class_path": "/Script/ChaosCaching.ChaosCacheCollection"},
        ])
        focus, excluded = capture.discover_focus_assets(
            self.root,
            ("/Game/ExampleContent/Destruction/",),
        )
        self.assertEqual(focus, sorted([destruction_df, destruction_gc]))
        self.assertEqual(excluded, {"dataflow": 1})

    def _write_valid_capture(self) -> None:
        df = "/Game/ExampleContent/Destruction/Dataflow/DF_A.DF_A"
        gc = "/Game/ExampleContent/Destruction/GC/GC_A.GC_A"
        n1 = "11111111-1111-1111-1111-111111111111"
        n2 = "22222222-2222-2222-2222-222222222222"
        p1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        p2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        p3 = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        p4 = "dddddddd-dddd-dddd-dddd-dddddddddddd"

        (self.root / "dataflow_chaos_focus_assets.txt").write_text(df + "\n" + gc + "\n", encoding="utf-8")
        write_jsonl(self.root / "dataflow_chaos_assets.jsonl", [
            {"asset_path": df, "loaded": True, "loaded_class": capture.DATAFLOW_CLASS, "asset_kind": "dataflow"},
            {"asset_path": gc, "loaded": True, "loaded_class": capture.GEOMETRY_COLLECTION_CLASS, "asset_kind": "geometry_collection"},
        ])
        write_jsonl(self.root / "dataflow_graphs.jsonl", [
            {"asset_path": df, "node_count": 2, "edge_count": 1},
        ])
        write_jsonl(self.root / "dataflow_nodes.jsonl", [
            {"asset_path": df, "node_guid": n1, "node_name": "Input", "node_struct": "/Script/DataflowNodes.StaticMeshToCollectionDataflowNode", "input_count": 1, "output_count": 1},
            {"asset_path": df, "node_guid": n2, "node_name": "Terminal", "node_struct": "/Script/GeometryCollectionNodes.GeometryCollectionTerminalDataflowNode_v2", "input_count": 1, "output_count": 1},
        ])
        write_jsonl(self.root / "dataflow_pins.jsonl", [
            {"asset_path": df, "node_guid": n1, "pin_guid": p1, "direction": "input", "pin_name": "Mesh"},
            {"asset_path": df, "node_guid": n1, "pin_guid": p2, "direction": "output", "pin_name": "Collection"},
            {"asset_path": df, "node_guid": n2, "pin_guid": p3, "direction": "input", "pin_name": "Collection"},
            {"asset_path": df, "node_guid": n2, "pin_guid": p4, "direction": "output", "pin_name": "Out"},
        ])
        write_jsonl(self.root / "dataflow_edges.jsonl", [
            {"asset_path": df, "source_node_guid": n1, "source_pin_guid": p2, "target_node_guid": n2, "target_pin_guid": p3},
        ])
        write_jsonl(self.root / "dataflow_asset_properties.jsonl", [
            {"source_path": df, "owner_id": df, "owner_kind": "dataflow_asset", "owner_type": capture.DATAFLOW_CLASS, "root_property": "Type", "property_path": "Type", "value": "Construction"},
        ])
        write_jsonl(self.root / "dataflow_asset_references.jsonl", [])
        write_jsonl(self.root / "dataflow_node_properties.jsonl", [
            {"source_path": df, "owner_id": n1, "owner_kind": "dataflow_node", "owner_type": "/Script/DataflowNodes.StaticMeshToCollectionDataflowNode", "root_property": "Mesh", "property_path": "Mesh", "value": "/Game/Meshes/SM_A", "truncated": False},
            {"source_path": df, "owner_id": n2, "owner_kind": "dataflow_node", "owner_type": "/Script/GeometryCollectionNodes.GeometryCollectionTerminalDataflowNode_v2", "root_property": "Collection", "property_path": "Collection", "value": "", "truncated": False},
        ])
        write_jsonl(self.root / "dataflow_node_references.jsonl", [
            {"source_path": df, "owner_id": n1, "owner_kind": "dataflow_node", "owner_type": "/Script/DataflowNodes.StaticMeshToCollectionDataflowNode", "root_property": "Mesh", "property_path": "Mesh", "target_path": "/Game/Meshes/SM_A", "target_class": "/Script/Engine.StaticMesh"},
        ])
        write_jsonl(self.root / "geometry_collection_properties.jsonl", [
            {"source_path": gc, "owner_id": gc, "owner_kind": "geometry_collection", "owner_type": capture.GEOMETRY_COLLECTION_CLASS, "root_property": "DataflowAsset", "property_path": "DataflowAsset", "value": df, "differs_from_default": True, "truncated": False},
            {"source_path": gc, "owner_id": gc, "owner_kind": "geometry_collection", "owner_type": capture.GEOMETRY_COLLECTION_CLASS, "root_property": "DamageThreshold", "property_path": "DamageThreshold", "value": "(500.0)", "differs_from_default": True, "truncated": False},
        ])
        write_jsonl(self.root / "geometry_collection_references.jsonl", [
            {"source_path": gc, "owner_id": gc, "owner_kind": "geometry_collection", "owner_type": capture.GEOMETRY_COLLECTION_CLASS, "root_property": "DataflowAsset", "property_path": "DataflowAsset", "target_path": df, "target_class": capture.DATAFLOW_CLASS},
        ])
        manifest = {
            "schema_version": 1,
            "success": True,
            "diagnostic_only": True,
            "semantic_promotion": False,
            "schema_promotion": False,
            "runtime_state_captured": False,
            "counts": {
                "focus_assets": 2,
                "loaded_assets": 2,
                "dataflow_assets": 1,
                "geometry_collections": 1,
                "graphs": 1,
                "nodes": 2,
                "pins": 4,
                "edges": 1,
                "disabled_nodes": 0,
                "dataflow_asset_properties": 1,
                "dataflow_asset_references": 0,
                "node_properties": 2,
                "node_references": 1,
                "geometry_collection_properties": 2,
                "geometry_collection_references": 1,
                "truncated_properties": 0,
                "property_depth_limit_hits": 0,
                "property_row_limit_hits": 0,
                "container_element_limit_hits": 0,
            },
        }
        (self.root / "dataflow_chaos_capture_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_validation_accepts_exact_graph_and_geometry_collection_binding(self) -> None:
        self._write_valid_capture()
        manifest = capture.validate_capture(self.root)
        self.assertTrue(manifest["diagnostic_only"])
        report = capture.semantic_report(self.root, manifest)
        self.assertIn("PASS: real UDataflow/FGraph topology", report)
        self.assertIn("Geometry Collection -> DataflowAsset authored bindings", report)
        self.assertIn("GeometryCollectionTerminal", report)

    def test_validation_rejects_wrong_edge_direction(self) -> None:
        self._write_valid_capture()
        edges = list(capture._rows(self.root / "dataflow_edges.jsonl"))
        pins = list(capture._rows(self.root / "dataflow_pins.jsonl"))
        pins[1]["direction"] = "input"
        write_jsonl(self.root / "dataflow_pins.jsonl", pins)
        with self.assertRaisesRegex(RuntimeError, "edge direction mismatch"):
            capture.validate_capture(self.root)

    def test_native_contract_uses_real_dataflow_graph_api(self) -> None:
        source = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolDataflowChaosCommandlet.cpp").read_text(encoding="utf-8")
        build = (ROOT / "Source/UnrealAssetTool/UnrealAssetTool.Build.cs").read_text(encoding="utf-8")
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn('#include "Dataflow/DataflowGraph.h"', source)
        self.assertIn('#include "Dataflow/DataflowNode.h"', source)
        self.assertIn("DataflowAsset->Dataflow", source)
        self.assertIn("Graph->GetNodes()", source)
        self.assertIn("Graph->GetConnections()", source)
        self.assertIn("Node->TypedScriptStruct()", source)
        self.assertIn("Connection->GetOriginalType()", source)
        self.assertIn("/Script/GeometryCollectionEngine.GeometryCollection", source)
        self.assertNotIn('#include "GeometryCollection/', source)
        self.assertNotIn("EvaluateTerminalNode", source)
        self.assertNotIn("Evaluate(", source)
        self.assertIn('"DataflowCore"', build)
        self.assertIn('"DataflowEngine"', build)
        self.assertIn("import uatool_dataflow_chaos_capture as _dataflow_chaos_capture", facade)
        self.assertIn("_dataflow_chaos_capture.install(_runtime)", facade)

    def test_no_void_pointer_cast_default_regression(self) -> None:
        source = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolDataflowChaosCommandlet.cpp").read_text(encoding="utf-8")
        self.assertNotIn("Cast<UObject>(const_cast<void*>", source)
        self.assertIn("UObject* DefaultObject = DataflowAsset->GetClass()->GetDefaultObject(false);", source)


if __name__ == "__main__":
    unittest.main()
