# UnrealAssetTool schema reference

## Current versions

UnrealAssetTool 0.7.0 uses independently versioned canonical layers plus one final derived layer:

```text
structural scanner schema: 12
world scanner schema:      12
animation scanner schema:   1
VFX scanner schema:         1
systems scanner schema:     5
derived schema:            21
```

Additional independently versioned semantic/canonical companions currently include:

```text
Blueprint user-defined enum schema: 1
Chooser decision schema:            1
Gameplay Camera behavior schema:    2
Mass/ZoneGraph graph expectation:   1
Mass/ZoneGraph graph verification:  1
```

The version numbers intentionally describe different facts and lifecycles.

- `manifest.json` -> structural `schema_version` and final `derived_schema_version`
- `world_manifest.json` -> world `schema_version`
- `animation_manifest.json` -> animation `schema_version`
- `vfx_manifest.json` -> VFX `schema_version`
- `systems_manifest.json` -> systems `schema_version`
- `blueprint_enum_manifest.json` -> Blueprint enum companion `schema_version`

A canonical scanner change normally requires Unreal to run again. A compatible derived-only change normally requires only `derive`, `pack` and `bundle`.

The current systems extension is documented in [zonegraph-mass-schema5.md](zonegraph-mass-schema5.md). Historical systems contracts remain in [systems-schema-1.md](systems-schema-1.md), [systems-schema-2.md](systems-schema-2.md) and [systems-schema-4.md](systems-schema-4.md).

## Storage rules

Canonical and derived streams use JSON Lines: one JSON object per physical line. This keeps writes streaming, supports partial reads/diffs and lets SQLite be rebuilt without treating the database as truth.

When parsing JSONL, split on physical `\n` records. Do not use Unicode `str.splitlines()` because serialized Unreal text can contain control characters that Python treats as additional line separators.

`uat.db` is a regenerable retrieval cache; canonical/derived JSON and their manifests are authoritative.

---

# Structural scanner schema 12

Structural extraction is emitted by the main Unreal commandlet.

## Project/files and Asset Registry

```text
files.jsonl
source_chunks.jsonl
assets.jsonl
asset_dependencies.jsonl
```

`assets.jsonl` is the universal fallback layer: asset identity, class, package, tags and disk/path facts. Asset Registry presence does not imply first-class understanding of an asset's internals. Generic package dependencies are never upgraded to semantic references without stronger evidence.

## Blueprint / K2 / UMG

```text
blueprints.jsonl
blueprint_graphs.jsonl
blueprint_nodes.jsonl
blueprint_pins.jsonl
blueprint_edges.jsonl
blueprint_interfaces.jsonl
blueprint_node_properties.jsonl
blueprint_node_references.jsonl
blueprint_bindings.jsonl
blueprint_defaults.jsonl
blueprint_component_properties.jsonl
blueprint_state_values.jsonl
blueprint_timelines.jsonl
blueprint_timeline_tracks.jsonl
blueprint_timeline_keys.jsonl
blueprint_widgets.jsonl
blueprint_widget_properties.jsonl
blueprint_widget_bindings.jsonl
blueprint_widget_animations.jsonl
blueprint_widget_animation_bindings.jsonl
```

These preserve Blueprint identity/inheritance/interfaces/state, every graph/node/pin, exact graph wiring, reflected node state/references, component/default state, Timelines and UMG authored structure.

## Blueprint user-defined enums

```text
blueprint_enum_manifest.json
blueprint_enums.jsonl
blueprint_enum_entries.jsonl
```

Enum identity plus raw/authored/display names are preserved. Readable enum decoration is derived conservatively from actual pin/enum typing; ambiguous values remain raw.

## Compact Control Rig / RigVM

```text
rigvm_objects.jsonl
rigvm_pins.jsonl
rigvm_links.jsonl
rigvm_references.jsonl
```

The much larger `rigvm_properties.jsonl` reflection stream is opt-in with `--include-raw-rigvm-properties`.

## AI / PCG / materials

AI canonical streams cover Behavior Trees, Blackboards, EQS and StateTree. PCG canonical streams preserve graph/node/pin/edge/property structure. Material streams preserve assets, expressions, root/expression edges, parameters, properties and references.

Generated `UMaterialExpression::MaterialExpressionGuid` values are removed by canonical cleanup because they are generated node identifiers rather than stable authored state.

---

# World scanner schema 12

```text
world_manifest.json
worlds.jsonl
world_levels.jsonl
world_actors.jsonl
world_components.jsonl
world_instance_properties.jsonl
world_references.jsonl
world_data_layers.jsonl
world_partition_actor_descs.jsonl
```

The world layer preserves world/level identity, loaded actor/component placement and ownership, authored archetype-diff overrides, exact hard/soft references, Data Layers and World Partition descriptors.

Placed `ZoneShape` actors are an important schema-5 ownership case: their authored normalized ZoneGraph state is captured while the containing world is loaded, not inferred from Asset Registry rows.

---

# Animation scanner schema 1

Animation schema 1 is one public schema implemented by base/deep/breadth passes. It covers:

- animation asset identity/settings, notifies/states, sync markers;
- Montage sections/segments and BlendSpace axes/samples;
- Skeleton hierarchy/sockets/slots;
- float/transform curves and keys;
- Pose Search databases/schemas/channels/roles/interactions/normalization;
- PoseAssets and pose transforms/curve values;
- Chooser and Proxy tables;
- IK Rig and IK Retargeter authored structure;
- mirror mappings and reflection-backed optional asset state/references.

See [animation-schema-1.md](animation-schema-1.md) for the domain-specific stream list and contracts.

---

# VFX scanner schema 1

VFX schema 1 covers Niagara Systems, versioned emitters, renderers, simulation stages, Niagara Stateless emitters/modules/renderers, scripts, Data Channels, Parameter Collections, Effect Types and legacy Cascade emitter/LOD/module topology.

`vfx_properties.jsonl` / `vfx_references.jsonl` preserve bounded reflection-backed authored state around the normalized VFX rows.

See [vfx-schema-1.md](vfx-schema-1.md).

---

# Systems scanner schema 5

Systems schema 5 is the current canonical gameplay-systems contract. It retains schemas 1-4 and adds the accepted Mass + authored ZoneGraph slice.

## Base systems families

Schema 5 retains normalized support for:

- LevelSequence / MovieScene bindings, tracks, sections and channels;
- core audio assets, SoundCue nodes and MetaSound frontend nodes/edges;
- Enhanced Input actions, mapping contexts, mappings and trigger/modifier objects;
- DataTable / CurveTable rows/fields/keys;
- PrimaryDataAsset identity;
- Gameplay Tags settings, sources, merged dictionary and redirects;
- Mover Blueprint/component/mode/settings/transition composition;
- Gameplay Cameras CameraAsset/CameraRig/node/transition/director/rig-reference topology.

The generic loss-minimizing streams remain:

```text
systems_assets.jsonl
systems_properties.jsonl
systems_references.jsonl
```

## Mass streams

```text
mass_entity_configs.jsonl
mass_entity_traits.jsonl
mass_spawners.jsonl
mass_spawner_entity_types.jsonl
mass_spawner_generators.jsonl
mass_spawn_generator_assets.jsonl
mass_agent_components.jsonl
```

These preserve MassEntityConfigAsset identity/parentage/config GUIDs, ordered Trait objects, MassSpawner entity-type/generator composition, generator Blueprint inheritance and MassAgent component config state.

Optional Trait/generator/component internals remain available through `systems_properties.jsonl` and `systems_references.jsonl` rather than forcing every Mass subclass into a hand-maintained schema.

## Authored ZoneGraph streams

```text
zonegraph_shapes.jsonl
zonegraph_shape_points.jsonl
```

`zonegraph_shapes.jsonl` preserves the containing world, placed ZoneShape identity, ZoneShapeComponent, point count, ShapeType, LaneProfile, Tags, reverse profile flag, PolygonRoutingType, relative transform and `PerPointLaneProfiles`.

`zonegraph_shape_points.jsonl` preserves ordered `FZoneShapePoint` Position, Rotation, TangentLength, PointType, LaneProfile selector, reverse-profile flag, LaneConnectionRestrictions and InnerTurnRadius.

Generated `FZoneGraphStorage` lanes/lane points/lane links and transient connector caches are **not** part of schema 5.

## City Sample schema-5 acceptance

Accepted raw counts:

```text
mass_entity_configs             28
mass_entity_traits             125
mass_spawners                    5
mass_spawner_entity_types       23
mass_spawner_generators          0
mass_spawn_generator_assets      7
mass_agent_components            36
zonegraph_shapes                61
zonegraph_shape_points         144
```

The focused ZoneGraph capture exactly matched the 61 placed ZoneShape actors already proven by the canonical world corpus, with zero truncated point rows.

Schema-5 acceptance/provenance files may include:

```text
systems_schema5_acceptance.json
zonegraph_world_manifest.json
mass_zonegraph_graph_expectations.json
mass_zonegraph_graph_verification.json
```

See [zonegraph-mass-schema5.md](zonegraph-mass-schema5.md) for the evidence workflow and exact boundary.

---

# Derived schema 21

Everything in this section is deterministic Python output and may be regenerated from compatible canonical data:

```powershell
python scripts\uatool.py derive <Project>\.uatool
```

A validated `.derived_freshness.json` allows subsequent `derive`, `pack` and `bundle` calls to reuse current output when canonical facts and derived implementation have not changed.

## Existing derived domains

Schema 21 retains the established derived layers for:

- Blueprint functions/events/calls/data dependencies/execution blocks;
- generic Blueprint semantic nodes/edges/graphs/statements/blocks/control flow;
- AI relationships/summaries;
- PCG/material/visual relationships and contexts;
- world and world-system relationships/contexts;
- animation relationships/contexts;
- VFX relationships/contexts;
- Chooser decisions/predicates;
- Mover transition behaviors/routes;
- Gameplay Camera provider/property/director-input behavior.

## Typed project graph

```text
project_nodes.jsonl
project_edges.jsonl
project_neighborhoods.jsonl
```

Node coverage classes:

```text
first_class
first_class_depth_pending
partial
generic_only
external_or_excluded
```

Edge quality classes:

```text
exact_semantic
exact_reference
unique_dependency_resolution
generic_package_dependency
```

`project_edges.jsonl` is authoritative for source/target kinds, paths, relation, coverage, quality and evidence. Asset Registry dependency evidence remains package-level fallback.

Neighborhoods are compact references to selected authoritative edges and are bounded/prioritized toward stronger semantic/reference evidence before package plumbing.

## Schema-21 Mass / ZoneGraph graph extension

Schema 21 promotes only relationships proven by schema-5 canonical rows:

```text
inherits_mass_entity_config
has_mass_entity_trait
spawns_mass_entity_config
uses_mass_spawn_generator_asset
uses_mass_spawn_generator_instance
inherits_mass_spawn_generator_class
inherits_zonegraph_spawn_generator_base
owns_mass_agent_component
uses_mass_entity_config
contains_zonegraph_shape
owns_zonegraph_shape_component
has_zonegraph_shape_point
```

Every such edge is `exact_semantic` and retains its canonical source stream as evidence.

A ZoneGraph-capable spawn generator is not linked to a particular placed ZoneShape without direct canonical evidence.

City Sample's accepted raw contract expects exactly 484 domain edges:

```text
contains_zonegraph_shape                 61
has_mass_entity_trait                   125
has_zonegraph_shape_point               144
inherits_mass_entity_config              21
inherits_mass_spawn_generator_class       7
inherits_zonegraph_spawn_generator_base   4
owns_mass_agent_component                36
owns_zonegraph_shape_component            61
spawns_mass_entity_config                23
uses_mass_entity_config                   2
```

The accepted real schema-21 derive produced:

```text
project_nodes            834529
project_edges           3668565
project_neighborhoods     11861
```

`mass-zonegraph-graph-verify` then confirmed all 484 expected edges, all 28 Mass config roots, all 61 ZoneShapes and all 144 synthetic point targets, with zero unsupported generator-to-placed-shape edges.

---

# Retrieval and bundle contract

`uat.db` is rebuilt by `pack` from authoritative JSONL and contains specialist systems tables plus the typed project graph.

The query surface searches canonical/derived specialist tables and project nodes/edges. Systems schema 5 exposes Mass configs/Traits/spawners/agents/generators and authored ZoneShape/point rows through SQLite/query plumbing.

Upload bundles include the canonical/derived JSON/manifests selected by the composed launcher and omit the regenerable SQLite cache. Schema-5 acceptance/verification manifests are included when present.

---

# Compatibility rule

Do not infer a stronger fact from a weaker layer. In particular:

- Asset Registry presence is not first-class semantic coverage;
- package dependencies are not exact object references;
- reflected presence of a runtime system is not proof of runtime behavior;
- a ZoneGraph-capable generator is not proof that it targets a particular placed ZoneShape;
- authored ZoneShape points are not generated ZoneGraph lane storage.

The schema is intentionally conservative: retain exact authored facts first, derive only relationships that are reproducible from those facts, and leave unsupported runtime/generated semantics unclaimed.
