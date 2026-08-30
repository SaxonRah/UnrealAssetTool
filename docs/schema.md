# UnrealAssetTool schema

## Current versions

UnrealAssetTool 0.7.0 uses:

```text
structural scanner schema: 12
world scanner schema:      12
derived schema:            10
```

The numbers intentionally version different layers.

- `schema_version` in `manifest.json` versions the structural Unreal-extracted output.
- `schema_version` in `world_manifest.json` versions the world/placement Unreal-extracted output.
- `derived_schema_version` in `manifest.json` versions deterministic Python-generated views.

A structural/world scanner-schema change generally requires rescanning in Unreal. A derived-schema change generally does not.

## Storage model

Canonical scan data is JSON Lines: one JSON object per line. This supports streaming writes, bounded memory, partial reads, diffing, independent index rebuilding, and sharding by subsystem.

`uat.db` is a regenerable SQLite index, not canonical truth.

## Manifests

### `manifest.json`

Important fields include:

```text
schema_version
tool
generated_utc
engine_version
project_file
project_dir
tool_plugin_dir
counts
derived_schema_version
derived_counts
world_schema_version
world_counts
world_files
world_pass
```

### `world_manifest.json`

Records world-pass provenance, structural-schema baseline, engine/project information, scan policies, and world-specific counts.

The world pass is a separate Unreal commandlet so world loading/World Partition behavior can evolve independently from the main structural pass while still sharing the same structural schema baseline.

---

# Structural scanner schema 12

## Project/files

### `files.jsonl`

Physical indexed project files with path, kind, extension, size, and modification time.

### `source_chunks.jsonl`

Bounded text/source/config/document chunks with source path and line range.

## Asset Registry

### `assets.jsonl`

One row per indexed Unreal asset.

Typical fields:

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

Every supported or unsupported asset family appears here, making Asset Registry data the universal fallback coverage layer.

### `asset_dependencies.jsonl`

Normalized package dependencies:

```text
source_package
target_package
category
```

Package dependency does not imply first-class understanding of the target asset's internals.

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

### `blueprints.jsonl`

Blueprint-family asset identity, parent/generated classes, Blueprint type/status, declared variables, implemented interfaces, and SCS component data.

### `blueprint_graphs.jsonl`

One row per unique Blueprint-owned graph.

Important fields include:

```text
graph_id
blueprint_path
graph_path
graph_name
graph_kind
graph_system
graph_class
schema_class
outer_path
parent_graph_id
node_count
```

Typical graph kinds include:

```text
ubergraph
function
macro
delegate_signature
anim_graph
anim_state_machine
anim_state
anim_transition
anim_conduit
graph
```

Typical systems include K2, animation, Control Rig, blend-stack, UMG, and generic graphs.

### `blueprint_nodes.jsonl`

Node identity/class/title/comment/editor position plus normalized factual semantics.

Core operation examples:

```text
function_entry
function_result
function_call
event
custom_event
variable_get
variable_set
branch
switch
select
execution_sequence
reroute
dynamic_cast
spawn_actor
macro_instance
self
tunnel
make_struct
break_struct
set_fields_in_struct
```

Animation operation examples include state machines/states/transitions/conduits/aliases, cached poses, linked layers/input poses, slots, sequence players/evaluators, BlendSpace players, Motion Matching nodes, Control Rig nodes, and graph/state/transition result nodes.

Unknown/plugin-defined nodes remain preserved with concrete class/title/pins/properties/wiring instead of being guessed.

### `blueprint_pins.jsonl`

Normalized pin identity, direction, type, defaults, object defaults, flags, and link counts.

### `blueprint_edges.jsonl`

Exact pin-to-pin graph links classified as `execution` or `data`.

### `blueprint_node_properties.jsonl`

Bounded flattened non-transient reflected node properties, including object references when available.

### `blueprint_node_references.jsonl`

Normalized UObject references found during node reflection.

### `blueprint_bindings.jsonl`

AnimGraph property-access/property-binding facts including target property and access path.

### Authored Blueprint state streams

```text
blueprint_defaults.jsonl
blueprint_component_properties.jsonl
blueprint_state_values.jsonl
```

These capture CDO/component-template changed state that requires Unreal objects.

### Timeline streams

```text
blueprint_timelines.jsonl
blueprint_timeline_tracks.jsonl
blueprint_timeline_keys.jsonl
```

### UMG streams

```text
blueprint_widgets.jsonl
blueprint_widget_properties.jsonl
blueprint_widget_bindings.jsonl
blueprint_widget_animations.jsonl
blueprint_widget_animation_bindings.jsonl
```

## Compact Control Rig / RigVM streams

```text
rigvm_objects.jsonl
rigvm_pins.jsonl
rigvm_links.jsonl
rigvm_references.jsonl
```

These preserve compact model graph/node objects, pins/types/defaults/directions, exact source-pin-path -> target-pin-path links, and structural/external UObject references.

### `rigvm_properties.jsonl`

Optional large raw reflection stream enabled with:

```text
--include-raw-rigvm-properties
```

It is excluded from ordinary compact bundles unless explicitly requested.

## AI canonical streams

### Behavior Trees

```text
behavior_trees.jsonl
behavior_tree_nodes.jsonl
behavior_tree_edges.jsonl
```

### Blackboards

```text
blackboards.jsonl
blackboard_keys.jsonl
```

### EQS

```text
eqs_queries.jsonl
eqs_options.jsonl
eqs_generators.jsonl
eqs_tests.jsonl
```

### StateTree

```text
statetrees.jsonl
statetree_states.jsonl
statetree_nodes.jsonl
statetree_transitions.jsonl
statetree_bindings.jsonl
```

### `ai_properties.jsonl`

Loss-minimizing reflected settings for supported AI objects/nodes.

## PCG canonical streams

```text
pcg_graphs.jsonl
pcg_nodes.jsonl
pcg_pins.jsonl
pcg_edges.jsonl
pcg_properties.jsonl
```

The scanner preserves graph identity, nodes, pins, exact topology, settings objects, and reflected node/settings state.

## Material canonical streams

```text
materials.jsonl
material_expressions.jsonl
material_edges.jsonl
material_properties.jsonl
```

These preserve Material/MaterialInstance/MaterialFunction identity, expression objects, root/output wiring, recursive expression-input topology, references, and reflected settings.

Materials are a first-class system in schema 12. Niagara/particles are not part of this material model.

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
```

## `worlds.jsonl`

World identity/package/persistent-level fields plus World Partition presence and initialization/descriptor-walk facts.

## `world_levels.jsonl`

Persistent-level rows and classic streaming-level relationships, including target world package and streaming class/owner.

## `world_actors.jsonl`

Loaded persistent-level actors with:

- path/name/label/class;
- actor GUID;
- folder/tags;
- transform;
- attachment/ownership/child-actor facts;
- Blueprint asset/generated-class identity where available;
- Data Layer memberships/references.

## `world_components.jsonl`

Actor components with identity/class/archetype/creation method, tags, scene-component attachment/socket information, relative/world transforms, and ownership.

Serialized scene-component world transforms are refreshed from relative/attachment state before extraction because loaded map assets may otherwise retain identity `ComponentToWorld` caches.

## `world_instance_properties.jsonl`

Authored placed-instance property differences from the exact archetype.

The extractor excludes transient/deprecated/skip-serialization state plus fields that cannot represent normal user-authored instance overrides.

## `world_references.jsonl`

Hard and soft UObject references discovered from actor/component properties, with:

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

Reference recursion and per-owner output are bounded. Truncation/cap policy belongs to the scanner implementation and should remain explicit when expanded in future schemas.

## `world_data_layers.jsonl`

Data Layer instance identity, hierarchy, runtime/editor state, and associated DataLayerAsset information.

## `world_partition_actor_descs.jsonl`

World Partition actor descriptor facts without calling `GetActor()` or loading every external actor.

Includes descriptor GUID, package/soft path, native class, parent GUID, actor-reference GUIDs, transform/bounds, Data Layer membership, and related descriptor metadata.

If a deserialized World Partition must be temporarily initialized for descriptor enumeration, the scanner initializes only when supported and uninitializes afterward.

---

# Derived schema 10

Everything below is deterministic Python output and may be deleted/regenerated from compatible canonical data.

Run:

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

### Functions/events and calls

Functions retain UFunction flags, inputs/outputs/locals, structural purity/exec facts, and graph identity.

Call edges preserve resolution status:

```text
internal
ambiguous_internal
external
unresolved
```

Only uniquely resolved internal calls receive caller/callee parameter bindings.

### Data provenance

`blueprint_data_dependencies.jsonl` traces bounded upstream data producers for execution-relevant sink inputs.

Current safety bounds:

```text
maximum recursive depth: 24
maximum expression nodes: 64
```

Cycles and truncation remain explicit.

### Execution blocks

Raw execution-pin links are collapsed into deterministic basic blocks/edges/roots while retaining underlying node IDs.

### AnimBP state machines

Derived state-machine tables resolve editor state/transition topology, entry states, aliases/conduits, transition endpoints, rule/custom-transition graphs, and key transition settings.

## AI derived views

```text
ai_relations.jsonl
ai_summaries.jsonl
```

Examples include:

```text
uses_blackboard
selects_blackboard_key
runs_eqs_query
transitions_to
links_statetree
references_blueprint
```

## PCG/material derived views

```text
pcg_parameters.jsonl
material_parameters.jsonl
visual_relations.jsonl
pcg_graph_context.jsonl
material_graph_context.jsonl
visual_summaries.jsonl
```

PCG `uses_subgraph` is emitted only for real non-self graph references or explicitly identified subgraph fields; reflected ownership back-references are not promoted to semantic graph use.

## Derived world graph — schema 8+

```text
world_relations.jsonl
world_context.jsonl
world_summaries.jsonl
```

`world_relations` includes factual derived relationships such as:

```text
has_persistent_level
streams_world_package
has_world_partition
contains_loaded_actor
owns_component
attached_to_actor
attached_to_component
instantiates_blueprint
contains_data_layer
member_of_data_layer
uses_data_layer_asset
contains_partition_actor_desc
describes_loaded_actor
parent_partition_actor
references_partition_actor
hard_object_reference
soft_object_reference
```

### LevelInstance / PackedLevelActor child worlds — schema 9

For World Partition LevelInstance/PackedLevelActor descriptors, schema 9 may emit:

```text
partition_actor -> instantiates_world -> world_package
```

The join is emitted only when existing canonical package-dependency/world facts resolve exactly one non-owning scanned world package. Ambiguous cases remain unasserted.

## World-to-system bridge — schema 10

### `world_system_relations.jsonl`

Connects a world/placed actor/component to an authored specialist asset.

Current target kinds include:

```text
blueprint
animation_blueprint
control_rig_blueprint
widget_blueprint
behavior_tree
blackboard
eqs_query
statetree
pcg_graph
material
material_instance
material_function
```

Typical relations include:

```text
instantiates_blueprint
references_blueprint
references_animation_blueprint
references_control_rig_blueprint
references_widget_blueprint
references_behavior_tree
references_blackboard
references_eqs_query
references_statetree
references_pcg_graph
references_material
```

Each row contains stable source/target semantics plus an `evidence` array and `evidence_count`.

Evidence kinds currently include:

```text
placed_actor_class
world_reference
blueprint_relation
blueprint_asset_dependency
world_asset_dependency
```

Multiple proofs for the same semantic relation are aggregated under one stable relation ID.

Generated Blueprint class paths normalize back to the authored Blueprint asset. Package dependency joins are emitted only when the package maps unambiguously to one indexed specialist entity.

World context is augmented with bounded system-link counts/examples while preserving the underlying world summary facts.

---

# SQLite

`uat.db` mirrors canonical and derived streams into indexed relational tables, including schema-10 `world_system_relations`.

It is regenerable:

```powershell
python scripts\uatool.py pack <Project>\.uatool
```

## Upload bundle

The ordinary compact bundle includes canonical JSONL and useful derived JSONL, including world and world-system relations.

It excludes:

```text
uat.db
rigvm_properties.jsonl
```

unless raw RigVM properties are explicitly requested.

## Schema compatibility rule

Never silently rewrite old canonical JSONL into new canonical truth.

Backward-compatible derived fixes may interpret compatible old facts differently, but manifests must continue to identify the scanner schemas that actually produced the raw data.

## Coverage is not equal to Asset Registry presence

An asset appearing in `assets.jsonl` means UnrealAssetTool knows that it exists and knows its generic Asset Registry facts. It does not mean its internal authored structure is first-class.

For the current first-class/partial/generic-only subsystem matrix, see [coverage.md](coverage.md).
