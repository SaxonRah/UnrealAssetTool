from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_schema5_accept as accept


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def _fake_validator(output: Path) -> str | None:
    output = Path(output)
    try:
        manifest = json.loads((output / "systems_manifest.json").read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - error text is enough for fixture use
        return str(exc)
    counts = manifest.get("counts", {})
    for name in ("mass_entity_configs.jsonl", "zonegraph_shapes.jsonl", "zonegraph_shape_points.jsonl"):
        path = output / name
        if not path.is_file():
            return f"missing {name}"
        actual = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)
        if int(counts.get(name.removesuffix(".jsonl"), -1)) != actual:
            return f"count mismatch {name}"
    return None


def test_accept_promotes_zonegraph_overlay_without_derive():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        project = root / "CitySample.uproject"
        project.write_text("{}", encoding="utf-8")
        corpus = root / ".uatool"
        systems_capture = corpus / "systems-schema5-capture"
        zone_capture = corpus / "zonegraph-world-capture"
        corpus.mkdir()
        systems_capture.mkdir()
        zone_capture.mkdir()

        world = "/Game/Map/City.City"
        shape = "/Game/Map/City.City:PersistentLevel.ZoneShape_0"
        component = shape + ".ShapeComp"
        _write_jsonl(corpus / "world_actors.jsonl", [
            {"world_path": world, "actor_path": shape, "actor_class": "/Script/ZoneGraph.ZoneShape"}
        ])
        _write_jsonl(corpus / "world_components.jsonl", [
            {
                "world_path": world,
                "actor_path": shape,
                "component_path": component,
                "component_class": "/Script/ZoneGraph.ZoneShapeComponent",
            }
        ])

        _write_jsonl(systems_capture / "mass_entity_configs.jsonl", [{"config_path": "/Game/AI/C.C"}])
        _write_jsonl(systems_capture / "zonegraph_shapes.jsonl", [])
        _write_jsonl(systems_capture / "zonegraph_shape_points.jsonl", [])
        (systems_capture / "systems_manifest.json").write_text(
            json.dumps({
                "schema_version": 5,
                "pass": "UnrealAssetToolSystems",
                "success": True,
                "counts": {
                    "mass_entity_configs": 1,
                    "zonegraph_shapes": 0,
                    "zonegraph_shape_points": 0,
                },
            }),
            encoding="utf-8",
        )

        shape_row = {
            "world_path": world,
            "shape_path": shape,
            "package_name": "/Game/Map/City",
            "class_path": "/Script/ZoneGraph.ZoneShape",
            "component_path": component,
            "component_class": "/Script/ZoneGraph.ZoneShapeComponent",
            "point_count": 2,
            "shape_type": "Spline",
            "lane_profile": "(Name=Test)",
            "tags": "()",
            "reverse_lane_profile": "False",
            "polygon_routing_type": "Bezier",
            "relative_location": "(X=0,Y=0,Z=0)",
            "relative_rotation": "(Pitch=0,Yaw=0,Roll=0)",
            "per_point_lane_profiles": "()",
            "provenance": "loaded_world_placed_actor_reflection",
            "generated_lane_topology": False,
        }
        point_rows = [
            {
                "world_path": world,
                "shape_path": shape,
                "point_index": i,
                "position": f"(X={i},Y=0,Z=0)",
                "rotation": "(Pitch=0,Yaw=0,Roll=0)",
                "tangent_length": "0",
                "point_type": "Sharp",
                "lane_profile": "255",
                "reverse_lane_profile": "False",
                "lane_connection_restrictions": "0",
                "inner_turn_radius": "100",
                "raw_value": "()",
                "truncated": False,
            }
            for i in range(2)
        ]
        _write_jsonl(zone_capture / "zonegraph_shapes.jsonl", [shape_row])
        _write_jsonl(zone_capture / "zonegraph_shape_points.jsonl", point_rows)
        (zone_capture / "zonegraph_world_manifest.json").write_text(
            json.dumps({
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
            }),
            encoding="utf-8",
        )

        fake_systems = types.SimpleNamespace(
            SYSTEMS_SCHEMA_VERSION=5,
            RAW_FILES=(
                "systems_manifest.json",
                "mass_entity_configs.jsonl",
                "zonegraph_shapes.jsonl",
                "zonegraph_shape_points.jsonl",
            ),
            validation_error=_fake_validator,
        )

        result = accept.accept_schema5(
            fake_systems,
            project,
            corpus=corpus,
            systems_capture=systems_capture,
            zonegraph_capture=zone_capture,
        )

        assert result["zonegraph_shapes"] == 1
        assert result["zonegraph_shape_points"] == 2
        assert result["generated_lane_topology"] is False
        assert len(list(accept.zonegraph_world_capture._rows(corpus / "zonegraph_shapes.jsonl"))) == 1
        assert len(list(accept.zonegraph_world_capture._rows(corpus / "zonegraph_shape_points.jsonl"))) == 2
        manifest = json.loads((corpus / "systems_manifest.json").read_text(encoding="utf-8"))
        assert manifest["counts"]["zonegraph_shapes"] == 1
        assert manifest["counts"]["zonegraph_shape_points"] == 2
        assert manifest["generated_lane_topology"] is False
        assert (corpus / accept.ACCEPTANCE_MANIFEST).is_file()
