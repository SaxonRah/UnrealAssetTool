from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

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


def _fixture(root: Path) -> tuple[str, str, str, str]:
    config = "/Game/AI/Crowd.Crowd"
    parent = "/Game/AI/Base.Base"
    spawner = "/Game/AI/BP_Spawner.BP_Spawner"
    generator = "/Game/AI/BP_ZoneGenerator.BP_ZoneGenerator"
    agent_bp = "/Game/AI/BP_Agent.BP_Agent"
    agent_component = agent_bp + ":MassAgent"
    world = "/Game/Map/City.City"
    shape = world + ":PersistentLevel.ZoneShape_0"
    component = shape + ".ShapeComp"

    rows = {
        "mass_entity_configs.jsonl": [
            {"config_path": parent, "parent_config_path": ""},
            {"config_path": config, "parent_config_path": parent},
        ],
        "mass_entity_traits.jsonl": [
            {"config_path": config, "trait_index": 0, "trait_path": config + ":Trait_0"}
        ],
        "mass_spawners.jsonl": [{"spawner_path": spawner}],
        "mass_spawner_entity_types.jsonl": [
            {"spawner_path": spawner, "entity_type_index": 0, "entity_config_path": config}
        ],
        "mass_spawner_generators.jsonl": [
            {"spawner_path": spawner, "generator_index": 0, "generator_asset_path": generator}
        ],
        "mass_spawn_generator_assets.jsonl": [
            {
                "generator_asset_path": generator,
                "parent_class": accept.ZONEGRAPH_BASE_GENERATOR_CLASS,
                "zonegraph_generator": True,
            }
        ],
        "mass_agent_components.jsonl": [
            {
                "blueprint_path": agent_bp,
                "component_path": agent_component,
                "entity_config_parent_path": config,
            }
        ],
        "zonegraph_shapes.jsonl": [
            {"world_path": world, "shape_path": shape, "component_path": component}
        ],
        "zonegraph_shape_points.jsonl": [
            {"shape_path": shape, "point_index": 0},
            {"shape_path": shape, "point_index": 1},
        ],
    }
    for filename, values in rows.items():
        _write_jsonl(root / filename, values)
    return config, generator, world, shape


def test_public_composition_promotes_final_schema21() -> None:
    import uatool
    import uatool_core
    import uatool_project_graph

    assert uatool.FINAL_DERIVED_SCHEMA_VERSION == accept.TARGET_DERIVED_SCHEMA_VERSION
    assert uatool_core.DERIVED_SCHEMA_VERSION == accept.TARGET_DERIVED_SCHEMA_VERSION
    assert uatool_project_graph.DERIVED_SCHEMA_VERSION == accept.TARGET_DERIVED_SCHEMA_VERSION
    for filename in (
        accept.ACCEPTANCE_MANIFEST,
        "zonegraph_world_manifest.json",
        accept.GRAPH_EXPECTATIONS_MANIFEST,
        accept.GRAPH_VERIFICATION_MANIFEST,
    ):
        assert filename in uatool_core.DEFAULT_BUNDLE_FILES


def test_graph_expectations_are_exact_raw_contract() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        _fixture(root)
        expectations = accept._graph_expectations(root)
        edges = accept._expected_graph_edges(root)

        assert expectations["target_derived_schema_version"] == 21
        assert expectations["generated_lane_topology"] is False
        assert expectations["unsupported_generator_to_placed_shape_edges"] == 0
        assert expectations["expected_exact_semantic_edge_count"] == len(edges)
        assert expectations["expected_relation_counts"]["has_zonegraph_shape_point"] == 2
        assert expectations["expected_relation_counts"]["inherits_zonegraph_spawn_generator_base"] == 1


def _write_valid_derived_contract(root: Path) -> tuple[str, str]:
    config, generator, _world, shape = _fixture(root)
    expectations = accept._graph_expectations(root)
    (root / accept.GRAPH_EXPECTATIONS_MANIFEST).write_text(
        json.dumps(expectations), encoding="utf-8"
    )
    (root / "manifest.json").write_text(
        json.dumps({"derived_schema_version": accept.TARGET_DERIVED_SCHEMA_VERSION}),
        encoding="utf-8",
    )

    edges = []
    for source, relation, target in sorted(accept._expected_graph_edges(root)):
        edges.append({
            "source": source,
            "relation": relation,
            "target": target,
            "edge_quality": "exact_semantic",
            "evidence": [{"stream": accept.RELATION_STREAMS[relation]}],
        })
    _write_jsonl(root / "project_edges.jsonl", edges)
    _write_jsonl(root / "project_nodes.jsonl", [
        {"path": row["config_path"], "node_kind": "mass_entity_config", "root": True}
        for row in accept._rows_list(root, "mass_entity_configs.jsonl")
    ])
    return generator, shape


def test_postderive_graph_verifier_accepts_exact_contract() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        _write_valid_derived_contract(root)
        result = accept._verify_graph(root)
        assert result["verified"] is True
        assert result["derived_schema_version"] == 21
        assert result["unsupported_generator_to_placed_shape_edges"] == 0
        assert (root / accept.GRAPH_VERIFICATION_MANIFEST).is_file()


def test_postderive_graph_verifier_rejects_invented_generator_shape_binding() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        generator, shape = _write_valid_derived_contract(root)
        rows = accept._rows_list(root, "project_edges.jsonl")
        rows.append({
            "source": generator,
            "relation": "invented_generator_shape_binding",
            "target": shape,
            "edge_quality": "exact_semantic",
            "evidence": [{"stream": "guessed"}],
        })
        _write_jsonl(root / "project_edges.jsonl", rows)
        with pytest.raises(RuntimeError, match="unsupported generator-to-placed-ZoneShape"):
            accept._verify_graph(root)
