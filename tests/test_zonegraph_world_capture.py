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

import uatool_zonegraph_world_capture as capture


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


class ZoneGraphWorldCaptureTests(unittest.TestCase):
    def test_discovers_worlds_and_expected_shapes_from_existing_world_corpus(self):
        with tempfile.TemporaryDirectory() as temp:
            corpus = Path(temp)
            _write_jsonl(corpus / "world_actors.jsonl", [
                {
                    "world_path": "/Game/Map/City.City",
                    "actor_path": "/Game/Map/City.City:PersistentLevel.ZoneShape_0",
                    "actor_class": "/Script/ZoneGraph.ZoneShape",
                },
                {
                    "world_path": "/Game/Map/Other.Other",
                    "actor_path": "/Game/Map/Other.Other:PersistentLevel.Actor_0",
                    "actor_class": "/Script/Engine.Actor",
                },
            ])
            _write_jsonl(corpus / "world_components.jsonl", [
                {
                    "world_path": "/Game/Map/City.City",
                    "actor_path": "/Game/Map/City.City:PersistentLevel.ZoneShape_0",
                    "component_path": "/Game/Map/City.City:PersistentLevel.ZoneShape_0.ShapeComp",
                    "component_class": "/Script/ZoneGraph.ZoneShapeComponent",
                },
                {
                    "world_path": "/Game/Map/Subway.Subway",
                    "actor_path": "/Game/Map/Subway.Subway:PersistentLevel.ZoneShape_4",
                    "component_path": "/Game/Map/Subway.Subway:PersistentLevel.ZoneShape_4.ShapeComp",
                    "component_class": "/Script/ZoneGraph.ZoneShapeComponent",
                },
            ])

            worlds, shapes = capture.discover_zonegraph_worlds(corpus)
            self.assertEqual(worlds, ["/Game/Map/City.City", "/Game/Map/Subway.Subway"])
            self.assertEqual(shapes, {
                "/Game/Map/City.City:PersistentLevel.ZoneShape_0",
                "/Game/Map/Subway.Subway:PersistentLevel.ZoneShape_4",
            })

    def test_validates_exact_shape_set_and_ordered_points(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            shape = "/Game/Map/City.City:PersistentLevel.ZoneShape_0"
            manifest = {
                "schema_version": 1,
                "success": True,
                "error": "",
                "generated_lane_topology": False,
                "counts": {
                    "worlds_requested": 1,
                    "worlds_loaded": 1,
                    "zonegraph_shapes": 1,
                    "zonegraph_shape_points": 2,
                },
            }
            (output / "zonegraph_world_manifest.json").write_text(
                json.dumps(manifest) + "\n", encoding="utf-8"
            )
            _write_jsonl(output / "zonegraph_shapes.jsonl", [{
                "world_path": "/Game/Map/City.City",
                "shape_path": shape,
                "class_path": "/Script/ZoneGraph.ZoneShape",
                "component_class": "/Script/ZoneGraph.ZoneShapeComponent",
                "point_count": 2,
                "generated_lane_topology": False,
            }])
            _write_jsonl(output / "zonegraph_shape_points.jsonl", [
                {
                    "shape_path": shape,
                    "point_index": 0,
                    "reverse_lane_profile": "False",
                    "inner_turn_radius": "0.000000",
                },
                {
                    "shape_path": shape,
                    "point_index": 1,
                    "reverse_lane_profile": "True",
                    "inner_turn_radius": "500.000000",
                },
            ])

            parsed = capture._validate_capture(output, {shape})
            self.assertEqual(parsed["counts"]["zonegraph_shape_points"], 2)

    def test_native_commandlet_is_reflection_first_and_does_not_claim_generated_lanes(self):
        header = (
            ROOT / "Source/UnrealAssetTool/Public/UnrealAssetToolZoneGraphWorldCommandlet.h"
        ).read_text(encoding="utf-8")
        native = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolZoneGraphWorldCommandlet.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn("UUnrealAssetToolZoneGraphWorldCommandlet", header)
        self.assertIn('TEXT("ZoneShape")', native)
        self.assertIn('TEXT("ZoneShapeComponent")', native)
        self.assertIn('TEXT("Points")', native)
        self.assertIn('TEXT("bReverseLaneProfile")', native)
        self.assertIn('TEXT("InnerTurnRadius")', native)
        self.assertIn('TEXT("LaneConnectionRestrictions")', native)
        self.assertIn('TEXT("generated_lane_topology"), false', native)
        self.assertNotIn('#include "ZoneShapeComponent.h"', native)
        self.assertNotIn('#include "ZoneGraph', native)

    def test_canonical_composition_installs_zonegraph_world_capture_command(self):
        import uatool  # noqa: F401
        import uatool_runtime

        self.assertTrue(getattr(uatool_runtime, "_zonegraph_world_capture_installed", False))


if __name__ == "__main__":
    unittest.main()
