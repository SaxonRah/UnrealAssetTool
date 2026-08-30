# UnrealAssetTool schema

## Current versions

The 0.7.0 development line uses independently versioned layers:

```text
structural scanner schema: 12
world scanner schema:      12
animation scanner schema:   1   # PR #5, under validation
derived schema:            10
```

The numbers intentionally version different facts and lifecycles.

- `schema_version` in `manifest.json` versions structural Unreal-extracted output.
- `schema_version` in `world_manifest.json` versions world/placement output.
- `schema_version` in `animation_manifest.json` versions canonical animation output.
- `derived_schema_version` in `manifest.json` versions deterministic Python-generated views.

A structural/world/animation scanner-schema change normally requires Unreal to run again. A derived-schema change normally requires only derive/pack/bundle.

## Storage model

Canonical scan data is JSON Lines: one JSON object per line. This supports streaming writes, bounded memory, partial reads, diffing, independent index rebuilding and subsystem sharding.

`uat.db` is a regenerable SQLite index, not canonical truth.

## Manifests

### `manifest.json`

Important fields include:

```text
schema_version
counts
derived_schema_version
derived_counts
world_schema_version
world_counts
world_files
world_pass
animation_schema_version
animation_counts
animation_files
animation_pass
```

### `world_manifest.json`

Records world-pass provenance, engine/project information, scan policy and world counts/files.

### `animation_manifest.json`

Records animation schema version, engine provenance, success/error state, canonical animation counts and file list.

Animation schema 1 currently has an internal bounded companion pass that writes `animation_deep_manifest.json`. This is an implementation split, not a second public schema. Python validates both passes and folds the companion counts/files into animation schema 1 before SQLite packing/bundling.

---

# Structural scanner schema 12

## Project/files

### `files.jsonl`

Physical indexed project files with path, kind, extension, size and modification time.

### `source_chunks.jsonl`

Bounded text/source/config/document chunks with source path and line range.

## Asset Registry

### `assets.jsonl`

One row per indexed Unreal asset. Typical fields:

```text
object_path
asset_name
package_name
package_path
class_path
disk_path
tags
dependencies
```

Every supported or unsupported asset family appears here, making Asset Registry data the universal fallback layer.

### `asset_dependencies.jsonl`

Normalized package dependencies:

```text
source_package
target_package
category
```

A package dependency does not imply first-class understanding of the target asset's internals.

## Blueprint canonical streams

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

Blueprint rows preserve identity/inheritance/interfaces/state, graph/node/pin identity, exact execution/data edges, reflected properties/references, authored defaults/components, Timelines and UMG state.

Common normalized node operations include function/event entry/results, calls, variables, branches/switches/selects, casts, spawn, macros/tunnels, struct operations and common AnimGraph/state-machine/cached-pose/linked-layer/Motion-Matching nodes. Unknown/plugin nodes remain factual/generic instead of being guessed.

## Compact Control Rig / RigVM streams

```text
rigvm_objects.jsonl
rigvm_pins.jsonl
rigvm_links.jsonl
rigvm_references.jsonl
```

`rigvm_properties.jsonl` is the optional large raw reflection stream enabled by `--include-raw-rigvm-properties`.

## AI canonical streams

```text
behavior_trees.jsonl
behavior_tree_nodes.jsonl
behavior_tree_edges.jsonl
blackboards.jsonl
blackboard_keys.jsonl
eqs_queries.jsonl
eqs_options.jsonl
eqs_generators.jsonl
eqs_tests.jsonl
statetrees.jsonl
statetree_states.jsonl
statetree_nodes.jsonl
statetree_transitions.jsonl
statetree_bindings.jsonl
ai_properties.jsonl
```

## PCG canonical streams

```text
pcg_graphs.jsonl
pcg_nodes.jsonl
pcg_pins.jsonl
pcg_edges.jsonl
pcg_properties.jsonl
```

These preserve graph/node/pin identity, exact topology, settings/properties, parameters and subgraph facts.

## Material canonical streams

```text
materials.jsonl
material_expressions.jsonl
material_edges.jsonl
material_properties.jsonl
```

These preserve Material/MaterialInstance/MaterialFunction identity, expression objects, root/output wiring, recursive expression-input topology, references and reflected settings.

Materials are first-class. Niagara/particles are not part of the material model.

---

# World scanner schema 12

The world pass emits:

```text
worlds.jsonl
world_levels.jsonl
world_actors.jsonl
world_components.jsonl
world_instance_properties.jsonl
world_references.jsonl
world_data_layers.jsonl
world_partition_actor_descs.jsonl
world_manifest.json
```

### `worlds.jsonl`

World identity/package/persistent-level fields plus World Partition presence and initialization/descriptor-walk facts.

### `world_levels.jsonl`

Persistent-level rows and classic streaming-level relationships, including target world package and streaming class/owner.

### `world_actors.jsonl`

Loaded actors with path/name/label/class/GUID, folder/tags, transform, ownership/attachments, Blueprint asset/generated class and Data Layer memberships.

### `world_components.jsonl`

Actor components with identity/class/archetype/creation method, tags, attachment/socket facts and relative/world transforms.

### `world_instance_properties.jsonl`

Authored placed-instance differences from the exact archetype, excluding transient/deprecated/non-instance state.

### `world_references.jsonl`

Bounded hard/soft UObject references discovered from actor/component properties:

```text
world_path
actor_path
owner_kind
owner_path
root_property
property_path
reference_kind
target_path
target_class
target_kind
authored_override
```

### `world_data_layers.jsonl`

Data Layer identity, hierarchy, runtime/editor state and DataLayerAsset association.

### `world_partition_actor_descs.jsonl`

World Partition descriptor facts without loading every external actor: GUID/package/soft path/native class, parent/reference GUIDs, transform/bounds and Data Layer membership.

---

# Animation scanner schema 1

Animation schema 1 is currently under validation on PR #5. It is canonical Unreal-authored data, not a derived view.

## Base animation streams

```text
animation_assets.jsonl
animation_notifies.jsonl
animation_sync_markers.jsonl
montage_sections.jsonl
animation_segments.jsonl
blend_space_axes.jsonl
blend_space_samples.jsonl
skeletons.jsonl
skeleton_bones.jsonl
skeleton_sockets.jsonl
pose_search_databases.jsonl
pose_search_database_assets.jsonl
pose_search_schemas.jsonl
pose_search_channels.jsonl
pose_search_schema_skeletons.jsonl
animation_optional_assets.jsonl
animation_properties.jsonl
animation_references.jsonl
```

### `animation_assets.jsonl`

Animation-family identity and shared high-value facts such as kind/class/package, Skeleton, play length, additive state, notify/marker counts and type-specific summary fields.

### `animation_notifies.jsonl`

Authored sequence/montage notify and notify-state facts including name, GUID, trigger/end/duration, track, branching-point state, trigger settings and concrete notify classes.

### `animation_sync_markers.jsonl`

Authored marker name/GUID/time/track with source family (`sequence`, `montage`, `blend_space`).

### `montage_sections.jsonl`

Montage section index/name/next-section/start-time facts.

### `animation_segments.jsonl`

Montage slot/segment source animations and timing/rate/loop settings.

### `blend_space_axes.jsonl`

Authored BlendSpace axis metadata. Schema-1 normalization filters unused backing `BlendParameters` slots so 1D/2D assets do not falsely claim three authored axes.

### `blend_space_samples.jsonl`

Blend sample coordinates/source animations/rate/mirror/single-frame facts.

### Skeleton streams

```text
skeletons.jsonl
skeleton_bones.jsonl
skeleton_sockets.jsonl
```

These preserve reference-bone hierarchy/local transforms, sockets, virtual-bone count and Skeleton curve/notify/marker metadata.

## Pose Search / Motion Matching streams

```text
pose_search_databases.jsonl
pose_search_database_assets.jsonl
pose_search_schemas.jsonl
pose_search_channels.jsonl
pose_search_schema_skeletons.jsonl
```

These preserve:

```text
database -> schema
database -> source entry
schema -> concrete feature channel
schema role -> Skeleton
schema role -> MirrorDataTable
```

Optional Pose Search classes are inspected through Unreal reflection to avoid making PoseSearch a hard module dependency for projects that do not enable it.

## Animation companion streams

```text
animation_curves.jsonl
animation_curve_keys.jsonl
pose_search_interaction_assets.jsonl
pose_search_interaction_items.jsonl
pose_search_normalization_sets.jsonl
pose_search_normalization_databases.jsonl
mirror_data_tables.jsonl
mirror_data_table_rows.jsonl
animation_deep_manifest.json
```

### `animation_curves.jsonl`

Float/transform curve identity, type flags and key counts from the UE animation data model.

### `animation_curve_keys.jsonl`

Every canonical `FRichCurveKey` with:

```text
asset_path
curve_name
curve_type
component
key_index
time
value
interp_mode
tangent_mode
tangent_weight_mode
```

The JSON row additionally retains arrive/leave tangent values and weights. Transform curves identify translation/rotation/scale X/Y/Z components.

### Pose Search Interaction streams

`pose_search_interaction_assets.jsonl` and `pose_search_interaction_items.jsonl` preserve multi-role interaction identity, roles, source animations/classes, preview meshes, origins and warping weights.

### Pose Search Normalization streams

`pose_search_normalization_sets.jsonl` and `pose_search_normalization_databases.jsonl` preserve normalization-set identity and ordered database membership.

### Mirror Data Table streams

`mirror_data_tables.jsonl` and `mirror_data_table_rows.jsonl` preserve table Skeleton/mirror-axis plus source/mirrored name mappings, mirror entry type and enabled state. These mappings can affect bones, curves, notifies and sync markers.

## Reflected animation state

`animation_properties.jsonl` and `animation_references.jsonl` are bounded loss-minimizing reflection streams for supported animation and optional adjacent assets/channels.

Chooser, ProxyAsset/ProxyTable, IK Rig and IK Retargeter currently use this reflection-backed model; richer family-specific row/chain/solver semantics are future depth work.

## GASP schema-1 validation baseline

The first UE 5.8.2 GASP run at commit `6276ce8` produced:

```text
animation_assets                 2518
animation_notifies              13373
animation_sync_markers             69
montage_sections                  137
animation_segments                137
blend_space_axes                   45   # raw backing slots before normalization
blend_space_samples                157
skeletons                           11
skeleton_bones                    2866
skeleton_sockets                    58
pose_search_databases              155
pose_search_database_assets       2138
pose_search_schemas                 33
pose_search_channels                74
pose_search_schema_skeletons        37
animation_optional_assets           31
animation_properties            106033
animation_references             46620
```

All database/schema/channel/role count invariants resolved exactly. The current companion pass is the next validation target.

---

# Derived schema 10

Everything in this section is deterministic Python output and may be regenerated from compatible canonical data.

```powershell
python scripts\uatool.py derive <Project>\.uatool
```

`pack` and `bundle` rerun derivation automatically.

## Blueprint program reconstruction

```text
blueprint_functions.jsonl
blueprint_events.jsonl
blueprint_call_edges.jsonl
blueprint_call_bindings.jsonl
blueprint_data_dependencies.jsonl
blueprint_execution_blocks.jsonl
blueprint_execution_block_edges.jsonl
blueprint_execution_roots.jsonl
anim_state_machines.jsonl
anim_states.jsonl
anim_transitions.jsonl
blueprint_relations.jsonl
blueprint_graph_context.jsonl
blueprint_summaries.jsonl
rigvm_editor_links.jsonl
```

Functions/events retain flags and signature facts. Call edges preserve internal/ambiguous/external/unresolved resolution. Unique internal calls receive caller/callee bindings. Data dependencies retain bounded upstream provenance with explicit cycle/truncation state. Execution-pin wiring is collapsed into deterministic basic blocks while retaining source node IDs.

## AI derived views

```text
ai_relations.jsonl
ai_summaries.jsonl
```

Relationships include Blackboard use/key selection, EQS execution, StateTree transitions/links and Blueprint references.

## PCG/material derived views

```text
pcg_parameters.jsonl
material_parameters.jsonl
visual_relations.jsonl
pcg_graph_context.jsonl
material_graph_context.jsonl
visual_summaries.jsonl
```

## Derived world graph

```text
world_relations.jsonl
world_context.jsonl
world_summaries.jsonl
```

Relations include world/level/actor/component containment, attachments/ownership, actor Blueprint identity, Data Layers, World Partition descriptor relationships, hard/soft references and LevelInstance/PackedLevelActor source-world joins.

## World-to-system bridge — schema 10

### `world_system_relations.jsonl`

Connects a world/placed actor/component to specialist assets.

Current target kinds include Blueprint, Animation Blueprint, Control Rig Blueprint, Widget Blueprint, Behavior Tree, Blackboard, EQS, StateTree, PCG and Material/MaterialInstance/MaterialFunction.

Each row has a stable semantic source/target and explicit aggregated evidence. Evidence kinds include:

```text
placed_actor_class
world_reference
blueprint_relation
blueprint_asset_dependency
world_asset_dependency
```

Generated Blueprint classes normalize back to authored Blueprint assets. Package dependency joins are emitted only when a package maps unambiguously to one indexed specialist target.

Derived animation relations/context are intentionally **not** part of derived schema 10 yet; they come after animation schema 1 is validated.

---

# SQLite and upload bundle

`uat.db` mirrors canonical and derived streams into indexed tables and is fully regenerable:

```powershell
python scripts\uatool.py pack <Project>\.uatool
```

Ordinary bundles include compact canonical/derived streams, including animation schema 1 when present. `uat.db` and the enormous optional `rigvm_properties.jsonl` are excluded unless specifically requested where supported.

## Compatibility rule

Never silently rewrite old canonical JSONL into new canonical truth.

Backward-compatible derived/post-pass normalization may clean representation defects when the underlying authored facts are unchanged, but manifests must identify which scanner schemas actually produced the raw data.

## Coverage is not equal to Asset Registry presence

An asset appearing in `assets.jsonl` means it exists and its generic Asset Registry facts are known. It does not mean its internal authored structure is first-class.

See [coverage.md](coverage.md) for the first-class/partial/generic-only matrix and [animation-schema-1.md](animation-schema-1.md) for the animation validation record.
