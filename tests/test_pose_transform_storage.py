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

import uatool_animation_breadth as breadth
import uatool_pose_transform_storage as storage


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


class PoseTransformStorageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.asset = "/Game/Pose/Test.Test"
        self.tracks = [
            {"pose_asset_path": self.asset, "track_index": 0, "track_name": "root"},
            {"pose_asset_path": self.asset, "track_index": 1, "track_name": "pelvis"},
        ]
        self.poses = [
            {"pose_asset_path": self.asset, "pose_index": 0, "pose_name": "A", "full_transform_count": 2, "full_curve_count": 0},
            {"pose_asset_path": self.asset, "pose_index": 1, "pose_name": "B", "full_transform_count": 2, "full_curve_count": 0},
        ]
        self.transforms = []
        for pose_index, pose_name in ((0, "A"), (1, "B")):
            for track_index, track_name in ((0, "root"), (1, "pelvis")):
                self.transforms.append({
                    "pose_asset_path": self.asset,
                    "pose_index": pose_index,
                    "pose_name": pose_name,
                    "track_index": track_index,
                    "track_name": track_name,
                    "translation_x": float(pose_index + track_index),
                    "translation_y": 0,
                    "translation_z": 0,
                    "rotation_x": 0,
                    "rotation_y": 0,
                    "rotation_z": 0,
                    "rotation_w": 1,
                    "scale_x": 1,
                    "scale_y": 1,
                    "scale_z": 1,
                })
        write_jsonl(self.output / "pose_asset_tracks.jsonl", self.tracks)
        write_jsonl(self.output / "pose_asset_poses.jsonl", self.poses)
        write_jsonl(self.output / "pose_asset_transforms.jsonl", self.transforms)
        (self.output / "animation_manifest.json").write_text(json.dumps({
            "schema_version": 2,
            "success": True,
            "counts": {"pose_asset_transforms": len(self.transforms)},
            "files": ["pose_asset_tracks.jsonl", "pose_asset_poses.jsonl", "pose_asset_transforms.jsonl"],
        }, indent=2) + "\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_round_trip_manifest_and_idempotency(self) -> None:
        stats = storage.normalize_output(self.output)
        self.assertEqual(stats["logical_transforms"], 4)
        self.assertEqual(stats["blocks"], 2)
        self.assertTrue(stats["rewritten"])

        blocks = list(rows(self.output / "pose_asset_transforms.jsonl"))
        self.assertEqual(len(blocks), 2)
        self.assertTrue(all(block["encoding"] == storage.ENCODING for block in blocks))
        self.assertTrue(all("pose_name" not in block for block in blocks))
        self.assertTrue(all("track_name" not in block for block in blocks))
        self.assertEqual(list(storage.iter_logical_transforms(self.output)), self.transforms)
        self.assertIsNone(storage.manifest_validation_error(self.output))

        manifest = json.loads((self.output / "animation_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["counts"]["pose_asset_transforms"], 4)
        self.assertEqual(manifest["counts"]["pose_asset_transform_blocks"], 2)
        self.assertEqual(manifest["pose_transform_encoding"], storage.ENCODING)

        second = storage.normalize_output(self.output)
        self.assertFalse(second["rewritten"])
        self.assertEqual(second["logical_transforms"], 4)
        self.assertEqual(second["blocks"], 2)

    def test_refuses_non_authoritative_names(self) -> None:
        broken = list(self.transforms)
        broken[1] = dict(broken[1])
        broken[1]["track_name"] = "wrong"
        write_jsonl(self.output / "pose_asset_transforms.jsonl", broken)
        with self.assertRaisesRegex(RuntimeError, "track_name is not authoritative"):
            storage.normalize_output(self.output)

    def test_sqlite_loader_sees_logical_rows(self) -> None:
        storage.normalize_output(self.output)
        storage.install(breadth)
        conn = sqlite3.connect(":memory:")
        try:
            breadth.create_schema(conn)
            breadth.load_database(conn, self.output, rows)
            values = conn.execute(
                "SELECT pose_index,track_index,track_name,json FROM pose_asset_transforms ORDER BY pose_index,track_index"
            ).fetchall()
            self.assertEqual(len(values), 4)
            self.assertEqual([row[:3] for row in values], [
                (0, 0, "root"), (0, 1, "pelvis"), (1, 0, "root"), (1, 1, "pelvis")
            ])
            logical_json = [json.loads(row[3]) for row in values]
            self.assertEqual(logical_json, self.transforms)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
