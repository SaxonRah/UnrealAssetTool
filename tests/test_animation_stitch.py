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

import uatool_animation_stitch as animation_stitch


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class AnimationStitchRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_exact_topology_absorbs_reference_evidence_and_ignores_package_dependencies(self) -> None:
        montage = "/Game/Anim/M_Test.M_Test"
        sequence = "/Game/Anim/A_Run.A_Run"
        write_jsonl(self.output / "assets.jsonl", [
            {"object_path": montage, "class_path": "/Script/Engine.AnimMontage", "package_name": "/Game/Anim/M_Test"},
            {"object_path": sequence, "class_path": "/Script/Engine.AnimSequence", "package_name": "/Game/Anim/A_Run"},
        ])
        write_jsonl(self.output / "animation_assets.jsonl", [
            {"animation_path": montage, "animation_kind": "anim_montage", "class_path": "/Script/Engine.AnimMontage", "package_name": "/Game/Anim/M_Test"},
            {"animation_path": sequence, "animation_kind": "anim_sequence", "class_path": "/Script/Engine.AnimSequence", "package_name": "/Game/Anim/A_Run"},
        ])
        write_jsonl(self.output / "animation_segments.jsonl", [{
            "asset_path": montage,
            "slot_index": 0,
            "slot_name": "DefaultSlot",
            "segment_index": 0,
            "animation_path": sequence,
            "start_pos": 0.0,
            "anim_start_time": 0.0,
            "anim_end_time": 1.0,
            "anim_play_rate": 1.0,
            "looping_count": 1,
        }])
        write_jsonl(self.output / "animation_references.jsonl", [{
            "asset_path": montage,
            "owner_path": montage,
            "owner_kind": "anim_montage",
            "root_property": "SlotAnimTracks",
            "property_path": "SlotAnimTracks[0].AnimTrack.AnimSegments[0].AnimReference",
            "reference_kind": "hard",
            "target_path": sequence,
            "target_class": "/Script/Engine.AnimSequence",
        }])
        # Animation stitching must never invent semantic animation edges from this.
        write_jsonl(self.output / "asset_dependencies.jsonl", [{
            "source_package": "/Game/Anim/M_Test",
            "target_package": "/Game/Anim/A_Run",
            "category": "hard",
        }])

        relations, contexts, summaries = animation_stitch.derive(self.output, read_rows)
        edge = [
            row for row in relations
            if row["source"] == montage
            and row["relation"] == "plays_animation_segment"
            and row["target"] == sequence
        ]
        self.assertEqual(len(edge), 1)
        self.assertEqual(edge[0]["target_coverage"], "first_class")
        self.assertEqual(edge[0]["evidence_count"], 2)
        self.assertEqual(
            {item["stream"] for item in edge[0]["evidence"]},
            {"animation_segments.jsonl", "animation_references.jsonl"},
        )
        self.assertFalse(any(
            item.get("stream") == "asset_dependencies.jsonl"
            for row in relations for item in row["evidence"]
        ))
        self.assertFalse(any(
            row["source"] == montage and row["relation"] == "references_asset" and row["target"] == sequence
            for row in relations
        ))
        self.assertEqual({row["asset_path"] for row in contexts}, {montage, sequence})
        self.assertEqual({row["asset_path"] for row in summaries}, {montage, sequence})

    def test_context_link_bound_is_explicit(self) -> None:
        montage = "/Game/Anim/M_Dense.M_Dense"
        targets = [f"/Game/Anim/A_{index:03d}.A_{index:03d}" for index in range(205)]
        animation_assets = [{
            "animation_path": montage,
            "animation_kind": "anim_montage",
            "class_path": "/Script/Engine.AnimMontage",
            "package_name": "/Game/Anim/M_Dense",
        }]
        animation_assets.extend({
            "animation_path": path,
            "animation_kind": "anim_sequence",
            "class_path": "/Script/Engine.AnimSequence",
            "package_name": path.split(".", 1)[0],
        } for path in targets)
        write_jsonl(self.output / "animation_assets.jsonl", animation_assets)
        write_jsonl(self.output / "animation_segments.jsonl", [{
            "asset_path": montage,
            "slot_index": 0,
            "slot_name": "DefaultSlot",
            "segment_index": index,
            "animation_path": path,
            "start_pos": float(index),
            "anim_start_time": 0.0,
            "anim_end_time": 1.0,
            "anim_play_rate": 1.0,
            "looping_count": 1,
        } for index, path in enumerate(targets)])

        relations, contexts, summaries = animation_stitch.derive(self.output, read_rows)
        self.assertEqual(len([row for row in relations if row["source"] == montage]), 205)
        context = next(row for row in contexts if row["asset_path"] == montage)
        summary = next(row for row in summaries if row["asset_path"] == montage)
        self.assertEqual(context["outgoing_count"], 205)
        self.assertEqual(summary["outgoing_count"], 205)
        self.assertTrue(context["truncated"])
        self.assertIn("more relations omitted by context link bound", context["text"])


if __name__ == "__main__":
    unittest.main()
