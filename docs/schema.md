# UnrealAssetTool schema reference

## Current versions

UnrealAssetTool 0.8.0 uses independently versioned canonical layers plus one final derived layer and a machine-readable capability contract:

```text
structural scanner schema: 12
world scanner schema:      12
animation scanner schema:   1
VFX scanner schema:         1
systems scanner schema:     6
derived schema:            22
capability schema:          1
```

Additional independently versioned semantic/canonical companions include:

```text
Blueprint user-defined enum schema: 1
Chooser decision schema:            1
Gameplay Camera behavior schema:    2
Mass/ZoneGraph graph expectation:   1
Mass/ZoneGraph graph verification:  1
GAS graph expectation:              1
GAS graph verification:             1
```

The version numbers intentionally describe different facts and lifecycles.

- `manifest.json` -> structural `schema_version` and final `derived_schema_version`
- `world_manifest.json` -> world `schema_version`
- `animation_manifest.json` -> animation `schema_version`
- `vfx_manifest.json` -> VFX `schema_version`
- `systems_manifest.json` -> systems `schema_version`
- `blueprint_enum_manifest.json` -> Blueprint enum companion `schema_version`
- `capabilities.json` -> capability-contract `capability_schema_version` plus the schema versions observed in this corpus

A canonical scanner change normally requires Unreal to run again. A compatible derived-only or capability/report change normally requires only `derive`, `pack` and `bundle`.

The current systems extension is documented in [systems-schema-6.md](systems-schema-6.md). The retained Mass/ZoneGraph foundation is documented in [zonegraph-mass-schema5.md](zonegraph-mass-schema5.md). Historical systems contracts remain in [systems-schema-1.md](systems-schema-1.md), [systems-schema-2.md](systems-schema-2.md) and [systems-schema-4.md](systems-schema-4.md).

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

# Systems scanner schema 6

Systems schema 6 is the current canonical gameplay-systems contract. It retains schemas 1–5 and adds the accepted Gameplay Ability System slice.

## Retained systems families

Schema 6 retains normalized support for:

- LevelSequence / MovieScene bindings, tracks, sections and channels;
- core audio assets, SoundCue nodes and MetaSound frontend nodes/edges;
- Enhanced Input actions, mapping contexts, mappings and trigger/modifier objects;
- DataTable / CurveTable rows/fields/keys;
- PrimaryDataAsset identity;
- Gameplay Tags settings, sources, merged dictionary and redirects;
- Mover Blueprint/component/mode/settings/transition composition;
- Gameplay Cameras CameraAsset/CameraRig/node/transition/director/rig-reference topology;
- Mass EntityConfig/Trait/spawner/generator/agent composition;
- authored placed ZoneShape/ZoneShapePoint topology.

The generic loss-minimizing streams remain:

```text
systems_assets.jsonl
systems_properties.jsonl
systems_references.jsonl
```

## Retained Mass / authored ZoneGraph streams

```text
mass_entity_configs.jsonl
mass_entity_traits.jsonl
mass_spawners.jsonl
mass_spawner_entity_types.jsonl
mass_spawner_generators.jsonl
mass_spawn_generator_assets.jsonl
mass_agent_components.jsonl
zonegraph_shapes.jsonl
zonegraph_shape_points.jsonl
```

Generated `FZoneGraphStorage` lanes/lane points/lane links and transient connector caches remain explicitly outside the canonical contract.

See [zonegraph-mass-schema5.md](zonegraph-mass-schema5.md) for the accepted City Sample evidence and schema-5 boundary.

## GAS streams added by schema 6

```text
gas_abilities.jsonl
gas_ability_triggers.jsonl
gas_ability_costs.jsonl
gas_ability_sets.jsonl
gas_ability_set_abilities.jsonl
gas_ability_set_effects.jsonl
gas_ability_set_attributes.jsonl
gas_gameplay_effects.jsonl
gas_gameplay_effect_components.jsonl
gas_gameplay_effect_modifiers.jsonl
gas_gameplay_effect_executions.jsonl
gas_gameplay_effect_execution_modifiers.jsonl
gas_gameplay_effect_cues.jsonl
gas_gameplay_cues.jsonl
gas_attribute_sets.jsonl
gas_attributes.jsonl
```

These preserve authored/default GameplayAbility, Ability Set, GameplayEffect, Gameplay Cue, AttributeSet and attribute facts required for exact deterministic graph promotion.

The accepted UE 5.8.2 Lyra raw contract contains 43 GameplayAbilities, 12 Ability Sets, 42 GameplayEffects, 24 Gameplay Cues, 4 project-owned AttributeSets and their normalized child rows. See [systems-schema-6.md](systems-schema-6.md) for complete counts and boundaries.

Schema-6 acceptance/provenance files may include:

```text
systems_schema6_acceptance.json
gas_graph_expectations.json
gas_graph_verification.json
```

Focused systems-only accepted corpora are marked `partial_corpus=true` with `canonical_passes=["systems"]`. They must not imply unrelated structural/world/animation/VFX coverage.

---

# Derived schema 22

Everything in this section is deterministic Python output and may be regenerated from compatible canonical data:

```powershell
python scripts\uatool.py derive <Project>\.uatool
```

A validated `.derived_freshness.json` allows subsequent `derive`, `pack` and `bundle` calls to reuse current output when canonical facts and derived implementation have not changed.

## Existing derived domains

Schema 22 retains the established derived layers for:

- Blueprint functions/events/calls/data dependencies/execution blocks;
- generic Blueprint semantic nodes/edges/graphs/statements/blocks/control flow;
- AI relationships/summaries;
- PCG/material/visual relationships and contexts;
- world and world-system relationships/contexts;
- animation relationships/contexts;
- VFX relationships/contexts;
- Chooser decisions/predicates;
- Mover transition behaviors/routes;
- Gameplay Camera provider/property/director-input behavior;
- Mass / authored ZoneGraph exact semantic graph relationships;
- Gameplay Ability System exact semantic graph relationships.

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

## Retained schema-21 Mass / ZoneGraph extension

Derived schema 22 retains the schema-21 relationships proven by systems schema 5:

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

Every accepted Mass/ZoneGraph domain edge is `exact_semantic` and retains its canonical source stream as evidence. City Sample's accepted contract verifies exactly 484 such domain edges.

## Schema-22 GAS graph extension

Schema 22 adds exact GAS relationships including:

```text
defines_gameplay_ability_class
inherits_gameplay_ability_class
uses_cost_gameplay_effect_class
uses_cooldown_gameplay_effect_class
has_gameplay_ability_trigger
triggered_by_gameplay_tag
has_additional_gameplay_ability_cost
instance_of_gameplay_ability_cost_class
instance_of_gameplay_ability_set_class
grants_gameplay_ability_class
grants_gameplay_effect_class
grants_attribute_set_class
defines_gameplay_effect_class
inherits_gameplay_effect_class
has_gameplay_effect_component
instance_of_gameplay_effect_component_class
has_gameplay_effect_modifier
modifies_gameplay_attribute
has_gameplay_effect_execution
uses_gameplay_effect_execution_calculation
has_gameplay_effect_execution_modifier
captures_gameplay_attribute
has_gameplay_effect_cue
uses_cue_magnitude_attribute
defines_gameplay_cue_class
inherits_gameplay_cue_class
handles_gameplay_cue_tag
inherits_attribute_set_class
has_gameplay_attribute
```

Every promoted GAS edge is `exact_semantic` and retains its normalized canonical source stream as evidence.

The accepted Lyra focused derive produced:

```text
project_nodes            8366
project_edges           12522
project_neighborhoods    1089
```

`gas-graph-verify` confirmed exactly **560 expected GAS semantic edges** with 43 Gameplay Ability roots, 12 Ability Set roots, 42 Gameplay Effect roots, 24 Gameplay Cue roots and 4 Attribute Set roots.

Runtime/live AbilitySystemComponent state remains explicitly outside schema 22.

---

# Capability contract schema 1

`capabilities.json` is emitted after a successful current derive and is included in portable bundles. It is deterministic metadata over existing manifests and the maintained tool contract, not a second semantic truth model.

The top-level shape includes:

```text
capability_schema_version
tool
coverage_levels
corpus
schemas
families
```

`schemas` reports the structural/world/animation/VFX/systems/derived versions actually observed in this corpus.

Each `families` row includes:

```text
family
contract_coverage
corpus_coverage
available_in_corpus
canonical_pass
canonical_streams
derived_streams
derived_relations
runtime_state_captured
boundary
acceptance
```

`contract_coverage` describes the current tool's supported semantic depth. `corpus_coverage` describes what can safely be claimed from this corpus. For example, a focused accepted schema-6 systems corpus can report GAS as `first_class` while structural/world/animation/VFX families are `external_or_excluded` because those passes were deliberately not run.

The command:

```powershell
python scripts\uatool.py capabilities <Project>\.uatool --check
```

regenerates, validates and prints the capability contract without running Unreal.

The contract deliberately records `runtime_state_captured=false` for the current authored-project indexing model.

---

# Retrieval and bundle contract

`uat.db` is rebuilt by `pack` from authoritative JSONL and contains specialist systems tables plus the typed project graph.

The query surface searches canonical/derived specialist tables and project nodes/edges. Systems schema 6 exposes retained systems data plus the normalized GAS streams through SQLite/query plumbing.

Upload bundles include the canonical/derived JSON/manifests selected by the composed launcher plus `capabilities.json`, and omit the regenerable SQLite cache. Schema-5/schema-6 acceptance/verification manifests are included when present.

---

# Compatibility rule

Do not infer a stronger fact from a weaker layer. In particular:

- Asset Registry presence is not first-class semantic coverage;
- package dependencies are not exact object references;
- reflected presence of a runtime system is not proof of runtime behavior;
- a ZoneGraph-capable generator is not proof that it targets a particular placed ZoneShape;
- authored ZoneShape points are not generated ZoneGraph lane storage;
- GameplayAbility/GameEffect class existence is not a snapshot of live AbilitySystemComponent state;
- a focused systems-only acceptance corpus is not a full-project scan.

The schema is intentionally conservative: retain exact authored facts first, derive only relationships that are reproducible from those facts, expose corpus capabilities explicitly, and leave unsupported runtime/generated semantics unclaimed.
