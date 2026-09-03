from __future__ import annotations

import collections
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_dataflow_chaos as systems
import uatool_dataflow_chaos_graph as graph


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def rows(path: Path):
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line:
            yield json.loads(line)


def prop(source: str, owner: str, kind: str, owner_type: str, index: int, root: str, value: str, **extra):
    return {
        "source_path": source, "owner_id": owner, "owner_kind": kind, "owner_type": owner_type,
        "property_index": index, "declaring_type": owner_type, "root_property": root, "property_name": root,
        "property_path": root, "property_type": "StrProperty", "cpp_type": "FString", "container_kind": "scalar",
        "value": value, "default_value": "", "default_present": False, "differs_from_default": True,
        "truncated": False, "dataflow_input": False, "dataflow_output": False,
        "dataflow_passthrough": False, "dataflow_intrinsic": False, **extra,
    }


def ref(source: str, owner: str, kind: str, owner_type: str, root: str, target: str, target_class: str):
    return {
        "source_path": source, "owner_id": owner, "owner_kind": kind, "owner_type": owner_type,
        "root_property": root, "property_path": root, "reference_kind": "hard_object",
        "target_path": target, "target_class": target_class,
    }


class SystemsDataflowChaosTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.df = "/Game/Test/DF_A.DF_A"
        self.gc = "/Game/Test/GC_A.GC_A"
        self.n1 = "11111111-1111-1111-1111-111111111111"
        self.n2 = "22222222-2222-2222-2222-222222222222"
        self.p1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.p2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        self.p3 = "cccccccc-cccc-cccc-cccc-cccccccccccc"
        self.p4 = "dddddddd-dddd-dddd-dddd-dddddddddddd"
        self.pm = "/Game/Test/PM_Stone.PM_Stone"
        self.mesh = "/Game/Test/SM_Source.SM_Source"
        self._write_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        write_jsonl(self.output / "dataflow_graphs.jsonl", [{
            "asset_path": self.df, "asset_class": systems.DATAFLOW_CLASS,
            "node_count": 2, "edge_count": 1, "asset_property_count": 1, "asset_reference_count": 0,
        }])
        write_jsonl(self.output / "dataflow_nodes.jsonl", [
            {"asset_path": self.df, "node_guid": self.n1, "node_name": "Source",
             "node_struct": "/Script/DataflowNodes.StaticMeshToCollectionDataflowNode",
             "input_count": 1, "output_count": 1, "property_count": 1, "reference_count": 1},
            {"asset_path": self.df, "node_guid": self.n2, "node_name": "Terminal",
             "node_struct": "/Script/GeometryCollectionNodes.GeometryCollectionTerminalDataflowNode_v2",
             "input_count": 1, "output_count": 1, "property_count": 1, "reference_count": 0},
        ])
        write_jsonl(self.output / "dataflow_pins.jsonl", [
            {"asset_path": self.df, "node_guid": self.n1, "pin_guid": self.p1, "pin_name": "Mesh", "direction": "input", "pin_index": 0, "original_type": "UStaticMesh", "property_name": "Mesh", "property_type": "TObjectPtr<UStaticMesh>"},
            {"asset_path": self.df, "node_guid": self.n1, "pin_guid": self.p2, "pin_name": "Collection", "direction": "output", "pin_index": 0, "original_type": "FManagedArrayCollection", "property_name": "Collection", "property_type": "FManagedArrayCollection"},
            {"asset_path": self.df, "node_guid": self.n2, "pin_guid": self.p3, "pin_name": "Collection", "direction": "input", "pin_index": 0, "original_type": "FManagedArrayCollection", "property_name": "Collection", "property_type": "FManagedArrayCollection"},
            {"asset_path": self.df, "node_guid": self.n2, "pin_guid": self.p4, "pin_name": "Out", "direction": "output", "pin_index": 0, "original_type": "FManagedArrayCollection", "property_name": "Out", "property_type": "FManagedArrayCollection"},
        ])
        write_jsonl(self.output / "dataflow_edges.jsonl", [{
            "asset_path": self.df, "source_node_guid": self.n1, "source_pin_guid": self.p2,
            "target_node_guid": self.n2, "target_pin_guid": self.p3,
        }])
        write_jsonl(self.output / "dataflow_asset_properties.jsonl", [
            prop(self.df, self.df, "dataflow_asset", systems.DATAFLOW_CLASS, 0, "Type", "Construction")
        ])
        write_jsonl(self.output / "dataflow_asset_references.jsonl", [])
        write_jsonl(self.output / "dataflow_node_properties.jsonl", [
            prop(self.df, self.n1, "dataflow_node", "/Script/DataflowNodes.StaticMeshToCollectionDataflowNode", 0, "Mesh", self.mesh),
            prop(self.df, self.n2, "dataflow_node", "/Script/GeometryCollectionNodes.GeometryCollectionTerminalDataflowNode_v2", 0, "Collection", ""),
        ])
        write_jsonl(self.output / "dataflow_node_references.jsonl", [
            ref(self.df, self.n1, "dataflow_node", "/Script/DataflowNodes.StaticMeshToCollectionDataflowNode", "Mesh", self.mesh, "/Script/Engine.StaticMesh")
        ])
        write_jsonl(self.output / "geometry_collections.jsonl", [{
            "asset_path": self.gc, "asset_class": systems.GEOMETRY_COLLECTION_CLASS,
            "dataflow_asset": "", "dataflow_terminal": "GeometryCollectionTerminal",
            "property_count": 2, "reference_count": 1, "geometry_source_in_behavior_schema": False,
        }])
        write_jsonl(self.output / "geometry_collection_properties.jsonl", [
            prop(self.gc, self.gc, "geometry_collection", systems.GEOMETRY_COLLECTION_CLASS, 0, "DamageThreshold", "(500000,50000,5000)"),
            prop(self.gc, self.gc, "geometry_collection", systems.GEOMETRY_COLLECTION_CLASS, 1, "PhysicsMaterial", self.pm),
        ])
        write_jsonl(self.output / "geometry_collection_references.jsonl", [
            ref(self.gc, self.gc, "geometry_collection", systems.GEOMETRY_COLLECTION_CLASS, "PhysicsMaterial", self.pm, "/Script/PhysicsCore.PhysicalMaterial")
        ])
        counts = {
            "dataflow_assets": 1, "geometry_collections": 1, "dataflow_graphs": 1, "dataflow_nodes": 2,
            "dataflow_pins": 4, "dataflow_edges": 1, "dataflow_asset_properties": 1,
            "dataflow_asset_references": 0, "dataflow_node_properties": 2, "dataflow_node_references": 1,
            "geometry_collection_properties": 2, "geometry_collection_references": 1,
            "dataflow_chaos_truncated_properties": 0, "dataflow_chaos_property_row_limit_hits": 0,
        }
        (self.output / "systems_manifest.json").write_text(json.dumps({"schema_version": 9, "success": True, "counts": counts}), encoding="utf-8")

    def test_schema9_fixture_validates(self) -> None:
        self.assertIsNone(systems.validation_error(self.output, rows))

    def test_exact_graph_contract_and_null_dataflow_binding(self) -> None:
        edges = graph.expected_edge_keys(self.output, rows)
        counts = collections.Counter(relation for _, relation, _ in edges)
        self.assertEqual(counts["has_dataflow_node"], 2)
        self.assertEqual(counts["instance_of_dataflow_node_struct"], 2)
        self.assertEqual(counts["has_dataflow_input"], 2)
        self.assertEqual(counts["has_dataflow_output"], 2)
        self.assertEqual(counts["dataflow_connects"], 1)
        self.assertEqual(counts["dataflow_node_references_object"], 1)
        self.assertEqual(counts["geometry_collection_uses_physics_material"], 1)
        self.assertEqual(counts["geometry_collection_uses_dataflow_asset"], 0)
        self.assertEqual(len(edges), 11)

    def test_rejects_geometry_source_behavior_leak(self) -> None:
        gc = list(rows(self.output / "geometry_collection_properties.jsonl"))
        gc[0]["root_property"] = "GeometrySource"
        gc[0]["property_name"] = "GeometrySource"
        gc[0]["property_path"] = "GeometrySource"
        write_jsonl(self.output / "geometry_collection_properties.jsonl", gc)
        self.assertIn("GeometrySource", systems.validation_error(self.output, rows) or "")

    def test_rejects_truncated_behavior_property(self) -> None:
        gc = list(rows(self.output / "geometry_collection_properties.jsonl"))
        gc[0]["truncated"] = True
        write_jsonl(self.output / "geometry_collection_properties.jsonl", gc)
        self.assertIn("truncated", systems.validation_error(self.output, rows) or "")

    def test_rejects_edge_direction_mismatch(self) -> None:
        pins = list(rows(self.output / "dataflow_pins.jsonl"))
        # Swap the two source-node pin directions. This preserves the node's
        # declared 1-in/1-out cardinality and contiguous per-direction indices,
        # so validation reaches the semantic edge-direction invariant itself.
        pins[0]["direction"] = "output"
        pins[1]["direction"] = "input"
        write_jsonl(self.output / "dataflow_pins.jsonl", pins)
        self.assertIn("direction mismatch", systems.validation_error(self.output, rows) or "")

    def test_native_schema9_contract(self) -> None:
        scanner = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp").read_text(encoding="utf-8")
        native = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsDataflowChaos.inl").read_text(encoding="utf-8")
        policy = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsDataflowChaosPolicy.inl").read_text(encoding="utf-8")
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn('#include "Dataflow/DataflowGraph.h"', scanner)
        self.assertIn("DataflowAsset->GetDataflow()", native)
        self.assertIn("Graph->GetNodes()", native)
        self.assertIn("Graph->GetConnections()", native)
        self.assertIn("Node->TypedScriptStruct()", native)
        self.assertNotIn('TEXT("GeometrySource")', native)
        self.assertNotIn("GeometrySource", systems.GEOMETRY_COLLECTION_BEHAVIOR_ROOTS)
        self.assertIn("UpgradeSystemsManifestToSchema9", policy)
        self.assertIn("FAIPerceptionSystemsFileHelperProxy::SaveStringToFile", policy)
        self.assertIn("FDataflowChaosSystemsFileHelperProxy", scanner)
        self.assertIn("import uatool_systems_dataflow_chaos as _systems_dataflow_chaos", facade)
        self.assertIn("_systems_dataflow_chaos.install(_systems)", facade)
        self.assertIn("_dataflow_chaos_graph.install(_project_graph)", facade)
        self.assertIn("_systems_schema9_accept.install(_runtime, _systems)", facade)


if __name__ == "__main__":
    unittest.main()
