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

import uatool_zonegraph_mass_evidence as evidence


def _write(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _rows(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


class ZoneGraphMassEvidenceTests(unittest.TestCase):
    def test_streams_broad_mass_and_zonegraph_evidence_without_promotion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(
                root / "assets.jsonl",
                [
                    {
                        "object_path": "/Game/AI/DA_MassCrowd.DA_MassCrowd",
                        "class_path": "/Script/MassEntity.MassEntityConfigAsset",
                    },
                    {
                        "object_path": "/Game/Props/Chair.Chair",
                        "class_path": "/Script/Engine.StaticMesh",
                    },
                ],
            )
            _write(
                root / "world_components.jsonl",
                [
                    {
                        "component_path": "/Game/Maps/City.City:PersistentLevel.ZoneShape.ZoneShapeComponent",
                        "component_class": "/Script/ZoneGraph.ZoneShapeComponent",
                    }
                ],
            )
            _write(
                root / "systems_properties.jsonl",
                [
                    {
                        "asset_path": "/Game/AI/DA_MassCrowd.DA_MassCrowd",
                        "property_name": "Traits",
                        "property_path": "Traits[0]",
                        "cpp_type": "TObjectPtr<UMassEntityTraitBase>",
                        "value": "/Script/MassRepresentation.MassRepresentationTrait",
                    }
                ],
            )
            _write(
                root / "project_edges.jsonl",
                [
                    {
                        "source_path": "/Game/AI/DA_MassCrowd.DA_MassCrowd",
                        "target_path": "/Script/MassRepresentation.MassRepresentationTrait",
                        "relation": "references_object",
                    }
                ],
            )

            report = evidence.build_report(root, _rows, example_limit=5)

            self.assertEqual(report["stream_stats"]["assets.jsonl"]["matched_rows"], 1)
            self.assertEqual(report["stream_stats"]["world_components.jsonl"]["matched_rows"], 1)
            self.assertEqual(report["stream_stats"]["systems_properties.jsonl"]["matched_rows"], 1)
            self.assertEqual(report["stream_stats"]["project_edges.jsonl"]["matched_rows"], 1)
            self.assertEqual(report["relation_counts"]["references_object"], 1)
            self.assertGreater(report["class_values"]["/Script/MassEntity.MassEntityConfigAsset"], 0)
            self.assertGreater(report["class_values"]["/Script/ZoneGraph.ZoneShapeComponent"], 0)
            self.assertGreater(report["class_values"]["TObjectPtr<UMassEntityTraitBase>"], 0)

    def test_source_chunks_are_opt_in(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write(
                root / "source_chunks.jsonl",
                [{"path": "Source/Traffic.cpp", "text": "UMassTrafficVehicleSimulationTrait"}],
            )

            without_source = evidence.build_report(root, _rows, include_source=False)
            with_source = evidence.build_report(root, _rows, include_source=True)

            self.assertNotIn("source_chunks.jsonl", without_source["stream_stats"])
            self.assertEqual(with_source["stream_stats"]["source_chunks.jsonl"]["matched_rows"], 1)

    def test_bare_english_mass_is_not_a_marker(self):
        row = {"text": "This object has a large physical mass."}
        self.assertEqual(evidence._markers_in_text(evidence._row_text(row)), ())


if __name__ == "__main__":
    unittest.main()
