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

import uatool_zonegraph_world_capture as zonegraph


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(value, separators=(",", ":")) + "\n" for value in values),
        encoding="utf-8",
    )


def row_count(path: Path) -> int:
    if not path.is_file():
        return -1
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)


class FakeCurrentSystems:
    SYSTEMS_SCHEMA_VERSION = 11
    RAW_FILES = (
        "systems_manifest.json",
        "unrelated_systems.jsonl",
        "zonegraph_shapes.jsonl",
        "zonegraph_shape_points.jsonl",
    )

    @staticmethod
    def validation_error(root: Path) -> str | None:
        root = Path(root)
        manifest_path = root / "systems_manifest.json"
        if not manifest_path.is_file():
            return "systems_manifest missing"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if int(manifest.get("schema_version", 0) or 0) != 11:
            return "wrong systems schema"
        counts = manifest.get("counts", {})
        if not isinstance(counts, dict):
            return "counts missing"
        for filename in FakeCurrentSystems.RAW_FILES[1:]:
            path = root / filename
            if not path.is_file():
                return f"missing {filename}"
            key = filename.removesuffix(".jsonl")
            if int(counts.get(key, -1)) != row_count(path):
                return f"count mismatch {key}"
        return None


class ZoneGraphCurrentSchemaPromotionTest(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path]:
        corpus = root / "corpus"
        capture = root / "capture"
        corpus.mkdir()
        capture.mkdir()

        shape = "/Game/City/Map.Map:PersistentLevel.ZoneShape_1"
        component = shape + ".ZoneShape"
        world = "/Game/City/Map.Map"

        write_jsonl(corpus / "world_actors.jsonl", [{
            "world_path": world,
            "actor_path": shape,
            "actor_class": zonegraph.ZONE_SHAPE_CLASS,
        }])
        write_jsonl(corpus / "world_components.jsonl", [{
            "world_path": world,
            "actor_path": shape,
            "component_path": component,
            "component_class": zonegraph.ZONE_SHAPE_COMPONENT_CLASS,
        }])

        write_jsonl(corpus / "unrelated_systems.jsonl", [
            {"id": "keep-me-1"},
            {"id": "keep-me-2"},
        ])
        write_jsonl(corpus / "zonegraph_shapes.jsonl", [])
        write_jsonl(corpus / "zonegraph_shape_points.jsonl", [])
        write_json(corpus / "systems_manifest.json", {
            "schema_version": 11,
            "pass": "UnrealAssetToolSystems",
            "success": True,
            "files": [
                "unrelated_systems.jsonl",
                "zonegraph_shapes.jsonl",
                "zonegraph_shape_points.jsonl",
            ],
            "counts": {
                "unrelated_systems": 2,
                "zonegraph_shapes": 0,
                "zonegraph_shape_points": 0,
            },
            "newer_schema_field": {"must": "survive"},
        })

        write_jsonl(capture / "zonegraph_shapes.jsonl", [{
            "world_path": world,
            "shape_path": shape,
            "class_path": zonegraph.ZONE_SHAPE_CLASS,
            "component_path": component,
            "component_class": zonegraph.ZONE_SHAPE_COMPONENT_CLASS,
            "point_count": 2,
            "generated_lane_topology": False,
        }])
        write_jsonl(capture / "zonegraph_shape_points.jsonl", [
            {"shape_path": shape, "point_index": 0},
            {"shape_path": shape, "point_index": 1},
        ])
        write_json(capture / "zonegraph_world_manifest.json", {
            "schema_version": 1,
            "success": True,
            "generated_lane_topology": False,
            "counts": {
                "worlds_requested": 1,
                "worlds_loaded": 1,
                "zonegraph_shapes": 1,
                "zonegraph_shape_points": 2,
            },
        })
        return corpus, capture

    def test_promotes_only_zonegraph_streams_into_current_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            corpus, capture = self._fixture(Path(temp))

            result = zonegraph.promote_capture(FakeCurrentSystems, corpus, capture)

            self.assertEqual(result["systems_schema_version"], 11)
            self.assertEqual(result["zonegraph_shapes"], 1)
            self.assertEqual(result["zonegraph_shape_points"], 2)
            self.assertEqual(row_count(corpus / "unrelated_systems.jsonl"), 2)
            self.assertEqual(row_count(corpus / "zonegraph_shapes.jsonl"), 1)
            self.assertEqual(row_count(corpus / "zonegraph_shape_points.jsonl"), 2)

            manifest = json.loads((corpus / "systems_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 11)
            self.assertEqual(manifest["newer_schema_field"], {"must": "survive"})
            self.assertEqual(manifest["counts"]["unrelated_systems"], 2)
            self.assertEqual(manifest["counts"]["zonegraph_shapes"], 1)
            self.assertEqual(manifest["counts"]["zonegraph_shape_points"], 2)
            self.assertEqual(
                manifest["zonegraph_authored_source"],
                "focused_world_placed_actor_reflection",
            )
            self.assertEqual(manifest["zonegraph_worlds_requested"], 1)
            self.assertEqual(manifest["zonegraph_expected_shape_count"], 1)
            self.assertFalse(manifest["generated_lane_topology"])
            self.assertIsNone(FakeCurrentSystems.validation_error(corpus))

    def test_rejects_capture_that_does_not_match_current_world_shape_set(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            corpus, capture = self._fixture(Path(temp))
            shapes = list(zonegraph._rows(capture / "zonegraph_shapes.jsonl"))
            shapes[0]["shape_path"] = "/Game/City/Map.Map:PersistentLevel.Wrong"
            write_jsonl(capture / "zonegraph_shapes.jsonl", shapes)

            with self.assertRaisesRegex(RuntimeError, "shape set does not match"):
                zonegraph.promote_capture(FakeCurrentSystems, corpus, capture)

            self.assertEqual(row_count(corpus / "zonegraph_shapes.jsonl"), 0)
            manifest = json.loads((corpus / "systems_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"]["zonegraph_shapes"], 0)


if __name__ == "__main__":
    unittest.main()
