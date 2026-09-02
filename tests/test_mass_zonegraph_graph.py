from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_mass_zonegraph_graph as mz_graph
import uatool_project_graph as project_graph
import uatool_project_graph_finalize as project_graph_finalize

mz_graph.install(project_graph)


CONFIG = "/Game/AI/Crowd.Crowd"
PARENT = "/Game/AI/Base.Base"
SPAWNER = "/Game/AI/BP_Spawner.BP_Spawner"
GENERATOR = "/Game/AI/BP_ZoneGenerator.BP_ZoneGenerator"
AGENT_BP = "/Game/AI/BP_Agent.BP_Agent"
AGENT_COMPONENT = "/Game/AI/BP_Agent.Default__BP_Agent_C:MassAgent"
WORLD = "/Game/Map/City.City"
SHAPE = "/Game/Map/City.City:PersistentLevel.ZoneShape_0"
COMPONENT = SHAPE + ".ShapeComp"


def _fixture_rows(path: Path):
    name = path.name
    fixture = {
        "blueprints.jsonl": [
            {"object_path": SPAWNER, "class": "/Script/Engine.Blueprint", "generated_class": SPAWNER + "_C"},
            {"object_path": GENERATOR, "class": "/Script/Engine.Blueprint", "generated_class": GENERATOR + "_C"},
            {"object_path": AGENT_BP, "class": "/Script/Engine.Blueprint", "generated_class": AGENT_BP + "_C"},
        ],
        "worlds.jsonl": [{"world_path": WORLD, "package_name": "/Game/Map/City"}],
        "world_actors.jsonl": [{"actor_path": SHAPE, "actor_class": "/Script/ZoneGraph.ZoneShape"}],
        "world_components.jsonl": [{"component_path": COMPONENT, "component_class": "/Script/ZoneGraph.ZoneShapeComponent"}],
        "mass_entity_configs.jsonl": [
            {
                "config_path": PARENT,
                "class_path": "/Script/MassSpawner.MassEntityConfigAsset",
                "parent_config_path": "",
                "parent_config_class": "",
                "config_guid": "BASE",
            },
            {
                "config_path": CONFIG,
                "class_path": "/Script/MassSpawner.MassEntityConfigAsset",
                "parent_config_path": PARENT,
                "parent_config_class": "/Script/MassSpawner.MassEntityConfigAsset",
                "config_guid": "CHILD",
            },
        ],
        "mass_entity_traits.jsonl": [
            {
                "config_path": CONFIG,
                "trait_index": 0,
                "trait_path": CONFIG + ":Trait_0",
                "trait_class": "/Script/MassSpawner.MassAssortedFragmentsTrait",
            },
            {
                "config_path": CONFIG,
                "trait_index": 1,
                "trait_path": CONFIG + ":Trait_1",
                "trait_class": "/Script/MassZoneGraphNavigation.MassZoneGraphNavigationTrait",
            },
        ],
        "mass_spawners.jsonl": [
            {"spawner_path": SPAWNER, "generated_class": SPAWNER + "_C"}
        ],
        "mass_spawner_entity_types.jsonl": [
            {
                "spawner_path": SPAWNER,
                "entity_type_index": 0,
                "entity_config_path": CONFIG,
                "entity_config_class": "/Script/MassSpawner.MassEntityConfigAsset",
                "proportion": "1.000000",
            }
        ],
        "mass_spawn_generator_assets.jsonl": [
            {
                "generator_asset_path": GENERATOR,
                "generated_class": GENERATOR + "_C",
                "parent_class": "/Script/MassSpawner.MassEntityZoneGraphSpawnPointsGenerator",
                "zonegraph_generator": True,
            }
        ],
        "mass_spawner_generators.jsonl": [
            {
                "spawner_path": SPAWNER,
                "generator_index": 0,
                "generator_asset_path": GENERATOR,
                "generator_path": GENERATOR + "_C:Generator",
                "generator_class": GENERATOR + "_C",
                "proportion": "0.5",
            }
        ],
        "mass_agent_components.jsonl": [
            {
                "blueprint_path": AGENT_BP,
                "component_path": AGENT_COMPONENT,
                "component_name": "MassAgent",
                "component_class": "/Script/MassActors.MassAgentComponent",
                "entity_config_parent_path": CONFIG,
                "entity_config_parent_class": "/Script/MassSpawner.MassEntityConfigAsset",
                "config_guid": "AGENT",
            }
        ],
        "zonegraph_shapes.jsonl": [
            {
                "world_path": WORLD,
                "shape_path": SHAPE,
                "class_path": "/Script/ZoneGraph.ZoneShape",
                "component_path": COMPONENT,
                "component_class": "/Script/ZoneGraph.ZoneShapeComponent",
                "provenance": "loaded_world_placed_actor_reflection",
            }
        ],
        "zonegraph_shape_points.jsonl": [
            {
                "shape_path": SHAPE,
                "point_index": 0,
                "point_type": "Sharp",
                "lane_profile": "255",
                "reverse_lane_profile": "False",
            },
            {
                "shape_path": SHAPE,
                "point_index": 1,
                "point_type": "LaneProfile",
                "lane_profile": "0",
                "reverse_lane_profile": "False",
            },
        ],
    }
    yield from fixture.get(name, [])


def test_mass_zonegraph_exact_semantic_graph_topology():
    output = Path("/synthetic")
    nodes, edges, _ = project_graph.derive(output, _fixture_rows)
    nodes, edges, neighborhoods = project_graph_finalize.finalize(
        output, _fixture_rows, nodes, edges
    )

    relations = {(e["source"], e["relation"], e["target"]): e for e in edges}
    expected = {
        (CONFIG, "inherits_mass_entity_config", PARENT),
        (CONFIG, "has_mass_entity_trait", CONFIG + ":Trait_0"),
        (CONFIG, "has_mass_entity_trait", CONFIG + ":Trait_1"),
        (SPAWNER, "spawns_mass_entity_config", CONFIG),
        (SPAWNER, "uses_mass_spawn_generator_asset", GENERATOR),
        (GENERATOR, "inherits_zonegraph_spawn_generator_base", mz_graph.ZONEGRAPH_BASE_GENERATOR_CLASS),
        (AGENT_BP, "owns_mass_agent_component", AGENT_COMPONENT),
        (AGENT_COMPONENT, "uses_mass_entity_config", CONFIG),
        (WORLD, "contains_zonegraph_shape", SHAPE),
        (SHAPE, "owns_zonegraph_shape_component", COMPONENT),
        (SHAPE, "has_zonegraph_shape_point", mz_graph._point_path(SHAPE, 0)),
        (SHAPE, "has_zonegraph_shape_point", mz_graph._point_path(SHAPE, 1)),
    }
    assert expected.issubset(relations)
    assert all(relations[key]["edge_quality"] == "exact_semantic" for key in expected)

    config_roots = [
        n for n in nodes
        if n.get("path") == CONFIG and n.get("node_kind") == "mass_entity_config" and n.get("root")
    ]
    assert len(config_roots) == 1

    point_edge = relations[(SHAPE, "has_zonegraph_shape_point", mz_graph._point_path(SHAPE, 0))]
    assert point_edge["evidence"][0]["point_index"] == 0
    assert point_edge["evidence"][0]["lane_profile"] == "255"

    # Inheritance proves that the generator is ZoneGraph-based, but there is no
    # canonical evidence binding that generator to any particular placed shape.
    assert not any(
        e.get("source") == GENERATOR and e.get("target") == SHAPE for e in edges
    )
    assert any(n.get("root_path") == CONFIG for n in neighborhoods)
