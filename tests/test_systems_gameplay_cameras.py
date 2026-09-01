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

import uatool_gameplay_camera_graph as camera_graph
import uatool_project_graph as project_graph
import uatool_systems_gameplay_cameras as cameras


def write_jsonl(path: Path, values: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class SystemsGameplayCamerasTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.asset = "/Game/Cameras/CA_Test.CA_Test"
        self.director = self.asset + ":BlueprintCameraDirector_0"
        self.rig = "/Game/Cameras/Rig_Test.Rig_Test"
        self.root = self.rig + ":RootNode_0"
        self.child = self.rig + ":BoomArm_0"
        self.transition = self.rig + ":CameraRigTransition_0"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        write_jsonl(self.output / "gameplay_camera_assets.jsonl", [{
            "camera_asset_path": self.asset,
            "package_name": "/Game/Cameras/CA_Test",
            "class_path": "/Script/GameplayCameras.CameraAsset",
            "director_path": self.director,
            "director_class": "/Script/GameplayCameras.BlueprintCameraDirector",
            "enter_transition_count": 0,
            "exit_transition_count": 0,
            "loose_transition_count": 0,
            "asset_rig_reference_count": 0,
            "director_rig_reference_count": 1,
        }])
        write_jsonl(self.output / "gameplay_camera_rigs.jsonl", [{
            "rig_path": self.rig,
            "package_name": "/Game/Cameras/Rig_Test",
            "class_path": "/Script/GameplayCameras.CameraRigAsset",
            "root_node_path": self.root,
            "root_node_class": "/Script/GameplayCameras.RootCameraNode",
            "initial_orientation": "PreviousYawPitch",
            "gameplay_tags": "(GameplayTags=())",
            "node_count": 2,
            "node_edge_count": 1,
            "enter_transition_count": 1,
            "exit_transition_count": 0,
            "loose_transition_count": 0,
            "rig_reference_count": 0,
        }])
        write_jsonl(self.output / "gameplay_camera_nodes.jsonl", [
            {
                "rig_path": self.rig,
                "node_index": 0,
                "node_path": self.child,
                "node_name": "BoomArm_0",
                "node_class": "/Script/GameplayCameras.BoomArmCameraNode",
                "is_root": False,
            },
            {
                "rig_path": self.rig,
                "node_index": 1,
                "node_path": self.root,
                "node_name": "RootNode_0",
                "node_class": "/Script/GameplayCameras.RootCameraNode",
                "is_root": True,
            },
        ])
        write_jsonl(self.output / "gameplay_camera_node_edges.jsonl", [{
            "rig_path": self.rig,
            "source_node_path": self.root,
            "property_path": "Children[0]",
            "target_node_path": self.child,
            "target_node_class": "/Script/GameplayCameras.BoomArmCameraNode",
        }])
        write_jsonl(self.output / "gameplay_camera_transitions.jsonl", [{
            "asset_path": self.rig,
            "owner_path": self.rig,
            "owner_kind": "gameplay_camera_rig",
            "transition_role": "enter",
            "transition_index": 0,
            "transition_path": self.transition,
            "transition_class": "/Script/GameplayCameras.CameraRigTransition",
        }])
        write_jsonl(self.output / "gameplay_camera_directors.jsonl", [{
            "asset_path": self.asset,
            "director_path": self.director,
            "director_class": "/Script/GameplayCameras.BlueprintCameraDirector",
            "run_in_editor": "False",
            "nested_object_count": 1,
            "rig_reference_count": 1,
        }])
        write_jsonl(self.output / "gameplay_camera_rig_references.jsonl", [{
            "asset_path": self.asset,
            "source_owner_path": self.director,
            "source_owner_kind": "gameplay_camera_director",
            "property_path": "CameraRigProxyRedirectTable.Entries[0].CameraRig",
            "target_rig_path": self.rig,
            "target_rig_class": "/Script/GameplayCameras.CameraRigAsset",
        }])

    def test_validation_and_sqlite(self) -> None:
        self._write_fixture()
        self.assertIsNone(cameras.validation_error(self.output, rows))
        conn = sqlite3.connect(":memory:")
        try:
            cameras.create_schema(conn)
            cameras.load_database(conn, self.output, rows)
            self.assertEqual(conn.execute("SELECT count(*) FROM gameplay_camera_assets").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM gameplay_camera_nodes").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT target_node_path FROM gameplay_camera_node_edges").fetchone()[0], self.child)
            self.assertEqual(conn.execute("SELECT rig_reference_count FROM gameplay_camera_directors").fetchone()[0], 1)
        finally:
            conn.close()

    def test_graph_edges_are_exact_semantic(self) -> None:
        self._write_fixture()
        nodes, edges = camera_graph._augment(self.output, rows, [], [], project_graph)
        relations = {edge["relation"] for edge in edges}
        self.assertIn("uses_camera_director", relations)
        self.assertIn("contains_camera_node", relations)
        self.assertIn("has_camera_root_node", relations)
        self.assertIn("camera_node_links_to", relations)
        self.assertIn("has_camera_enter_transition", relations)
        self.assertIn("references_camera_rig", relations)
        self.assertIn("uses_camera_rig", relations)
        self.assertTrue(all(edge["edge_quality"] == "exact_semantic" for edge in edges))
        self.assertTrue(any(node["node_kind"] == "gameplay_camera_asset" for node in nodes))
        self.assertTrue(any(node["node_kind"] == "gameplay_camera_rig" for node in nodes))
        self.assertTrue(any(node["node_kind"] == "gameplay_camera_node" for node in nodes))
        self.assertTrue(any(node["node_kind"] == "gameplay_camera_transition" for node in nodes))

    def test_validation_rejects_cross_rig_node_edge(self) -> None:
        self._write_fixture()
        edge = next(rows(self.output / "gameplay_camera_node_edges.jsonl"))
        edge["target_node_path"] = "/Game/Cameras/Other.Other:Node"
        write_jsonl(self.output / "gameplay_camera_node_edges.jsonl", [edge])
        error = cameras.validation_error(self.output, rows)
        self.assertIn("endpoint", str(error))


if __name__ == "__main__":
    unittest.main()
