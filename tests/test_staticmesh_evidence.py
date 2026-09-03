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

import uatool_staticmesh_evidence as evidence
import uatool_derived_freshness as freshness


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


class StaticMeshEvidenceTest(unittest.TestCase):
    def test_identity_tags_and_consumers_do_not_imply_owned_topology(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mesh = "/Game/Props/SM_Test.SM_Test"
            write_jsonl(root / "assets.jsonl", [
                {
                    "object_path": mesh,
                    "class_path": evidence.STATIC_MESH_CLASS,
                    "tags": {
                        "LODs": "3",
                        "NaniteEnabled": "True",
                        "MaterialCount": "2",
                    },
                },
                {
                    "object_path": "/Game/Props/StaticMeshNamedButWrong.StaticMeshNamedButWrong",
                    "class_path": "/Script/Engine.DataAsset",
                    "tags": {"NaniteEnabled": "True"},
                },
            ])
            write_jsonl(root / "world_references.jsonl", [{
                "owner_path": "/Game/Maps/Test.Test:PersistentLevel.SMActor.StaticMeshComponent0",
                "property_path": "StaticMesh",
                "target_path": mesh,
                "target_class": evidence.STATIC_MESH_CLASS,
            }])
            write_jsonl(root / "world_components.jsonl", [{
                "component_path": "/Game/Maps/Test.Test:PersistentLevel.SMActor.StaticMeshComponent0",
                "component_class": evidence.STATIC_MESH_COMPONENT_CLASS,
            }])

            report = evidence.build_report(root, rows, include_source=False)
            proof = report["proof"]
            self.assertEqual(proof["unique_static_mesh_assets"], 1)
            self.assertEqual(proof["static_mesh_assets_with_relevant_registry_tags"], 1)
            self.assertEqual(proof["relevant_registry_tag_rows"], 3)
            self.assertEqual(proof["static_mesh_consumer_reference_rows"], 1)
            self.assertEqual(proof["mesh_owned_detail_rows_in_existing_streams"], 0)
            self.assertEqual(report["static_mesh_assets"], [mesh])
            self.assertTrue(any("focused native authored capture" in gap for gap in report["gaps"]))
            self.assertTrue(any("do not prove ordered source LODs" in gap for gap in report["gaps"]))

    def test_mesh_owned_detail_rows_require_exact_staticmesh_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mesh = "/Game/Props/SM_Test.SM_Test"
            write_jsonl(root / "assets.jsonl", [
                {"object_path": mesh, "class_path": evidence.STATIC_MESH_CLASS},
            ])
            write_jsonl(root / "pcg_node_properties.jsonl", [
                {"asset_path": mesh, "property_path": "SourceModels[0].BuildSettings", "value": "(...)"},
                {"asset_path": "/Game/Other/Other.Other", "property_path": "StaticMesh", "value": mesh},
            ])

            report = evidence.build_report(root, rows, include_source=False)
            self.assertEqual(report["proof"]["mesh_owned_detail_rows_in_existing_streams"], 1)
            self.assertEqual(report["owned_detail_rows_by_stream"]["pcg_node_properties.jsonl"], 1)

    def test_canonical_facade_and_freshness_treat_command_as_read_only(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_staticmesh_evidence as _staticmesh_evidence", facade)
        self.assertIn("_staticmesh_evidence.install(_runtime)", facade)
        source = (SCRIPTS / "uatool_staticmesh_evidence.py").read_text(encoding="utf-8")
        self.assertIn('STATIC_MESH_CLASS = "/Script/Engine.StaticMesh"', source)
        self.assertIn('"diagnostic_only": True', source)
        self.assertIn('"schema_promotion": False', source)
        self.assertIn('"runtime_state_captured": False', source)
        self.assertIn('"render_buffers_captured": False', source)
        self.assertIn("uatool_staticmesh_evidence.py", freshness.NON_DERIVED_SCRIPTS)


if __name__ == "__main__":
    unittest.main()
