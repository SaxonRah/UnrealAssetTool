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

import uatool_dataflow_chaos_evidence as evidence


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class DataflowChaosEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_positive_corpus_inventory_is_diagnostic_only(self) -> None:
        dataflow = "/Game/Chaos/DF_Fracture.DF_Fracture"
        collection = "/Game/Chaos/GC_Wall.GC_Wall"
        component = "/Game/Chaos/L_Chaos.L_Chaos:PersistentLevel.GC_Wall.GeometryCollectionComponent0"
        write_jsonl(self.output / "assets.jsonl", [
            {"object_path": dataflow, "class_path": "/Script/DataflowEngine.Dataflow"},
            {"object_path": collection, "class_path": "/Script/GeometryCollectionEngine.GeometryCollection"},
            {"object_path": "/Game/Chaos/GC_Cache.GC_Cache", "class_path": "/Script/GeometryCollectionEngine.GeometryCollectionCache"},
        ])
        write_jsonl(self.output / "world_components.jsonl", [{
            "component_path": component,
            "component_class": "/Script/GeometryCollectionEngine.GeometryCollectionComponent",
        }])
        write_jsonl(self.output / "world_instance_properties.jsonl", [
            {
                "owner_path": component,
                "owner_class": "/Script/GeometryCollectionEngine.GeometryCollectionComponent",
                "property_path": "RestCollection",
                "value": collection,
            },
            {
                "owner_path": component,
                "owner_class": "/Script/GeometryCollectionEngine.GeometryCollectionComponent",
                "property_path": "DamageThreshold",
                "value": "(500.0,250.0)",
            },
            {
                "owner_path": collection,
                "owner_class": "/Script/GeometryCollectionEngine.GeometryCollection",
                "property_path": "DataflowAsset",
                "value": dataflow,
            },
            {
                "owner_path": collection,
                "owner_class": "/Script/GeometryCollectionEngine.GeometryCollection",
                "property_path": "DataflowTerminal",
                "value": "GeometryCollectionTerminal",
            },
        ])
        write_jsonl(self.output / "world_references.jsonl", [{
            "owner_path": component,
            "property_path": "RestCollection",
            "target_path": collection,
            "target_class": "/Script/GeometryCollectionEngine.GeometryCollection",
        }])
        write_jsonl(self.output / "blueprint_semantic_nodes.jsonl", [{
            "blueprint_path": "/Game/Chaos/BP_Field.BP_Field",
            "semantic_kind": "call",
            "symbol": "ApplyExternalStrain",
            "owner": "/Script/GeometryCollectionEngine.GeometryCollectionComponent",
        }])

        report = evidence.build_report(self.output, rows, include_source=False)
        self.assertTrue(report["diagnostic_only"])
        self.assertFalse(report["semantic_promotion"])
        self.assertFalse(report["schema_promotion"])
        self.assertFalse(report["runtime_state_captured"])
        proof = report["proof"]
        self.assertEqual(proof["unique_dataflow_assets"], 1)
        self.assertEqual(proof["unique_geometry_collection_assets"], 1)
        self.assertEqual(proof["unique_geometry_collection_cache_assets"], 1)
        self.assertEqual(proof["unique_placed_geometry_collection_components"], 1)
        self.assertEqual(proof["dataflow_asset_link_owners"], 1)
        self.assertEqual(proof["dataflow_terminal_owners"], 1)
        self.assertEqual(proof["rest_collection_link_owners"], 1)
        self.assertEqual(proof["damage_authoring_owners"], 1)
        self.assertGreaterEqual(proof["exact_reference_rows"], 1)
        self.assertGreaterEqual(proof["usage_rows"], 1)
        self.assertIn(dataflow, report["assets"]["dataflow"])
        self.assertIn(collection, report["assets"]["geometry_collection"])
        self.assertTrue(any("dedicated Dataflow node/pin/edge extractor" in gap for gap in report["gaps"]))

    def test_negative_corpus_refuses_schema_implication(self) -> None:
        write_jsonl(self.output / "assets.jsonl", [
            {"object_path": "/Game/Other/SM_Box.SM_Box", "class_path": "/Script/Engine.StaticMesh"},
        ])
        report = evidence.build_report(self.output, rows, include_source=False)
        self.assertEqual(report["proof"]["unique_dataflow_assets"], 0)
        self.assertEqual(report["proof"]["unique_geometry_collection_assets"], 0)
        self.assertTrue(any("do not design" in gap for gap in report["gaps"]))

    def test_focus_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown Dataflow/Chaos focus"):
            evidence.build_report(self.output, rows, focuses=("not_real",))

    def test_facade_wires_public_command(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_dataflow_chaos_evidence as _dataflow_chaos_evidence", facade)
        self.assertIn("_dataflow_chaos_evidence.install(_runtime)", facade)
        source = (SCRIPTS / "uatool_dataflow_chaos_evidence.py").read_text(encoding="utf-8")
        self.assertIn('sys.argv[1] == "dataflow-chaos-evidence"', source)
        self.assertIn("schema_promotion", source)


if __name__ == "__main__":
    unittest.main()
