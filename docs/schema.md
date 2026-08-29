# UnrealAssetTool schema

## Current versions

UnrealAssetTool 0.6.4 uses:

```text
scanner schema: 11
derived schema: 7
```

The two numbers intentionally version different layers.

- `schema_version` in `manifest.json` versions canonical Unreal-extracted output.
- `derived_schema_version` versions deterministic Python-generated views.

A scanner-schema change generally requires rescanning in Unreal. A derived-schema change generally does not.

## Storage model

The canonical scan format is JSON Lines: one JSON object per line.

This permits streaming writes, partial reads, diffing, independent index rebuilding, and bounded retrieval.

`uat.db` is not canonical. It is a regenerable SQLite index.

## `manifest.json`

One JSON object describing the scan.

Important fields include:

- `schema_version`
- `tool`
- `generated_utc`
- `engine_version`
- `project_file`
- `project_dir`
- scanner options such as engine/generated/self inclusion
- `tool_plugin_dir`
- `counts`
- after derivation: `derived_schema_version`
- after derivation: `derived_counts`

## Canonical scanner streams

The files below require Unreal/editor data and therefore belong to scanner schema 11.

### Project/files

#### `files.jsonl`

One record per indexed physical project file.

Typical fields:

```text
path
kind
extension
size
modified_utc
```

#### `source_chunks.jsonl`

Text/source/config/document files split into bounded source-line chunks.

Typical fields:

```text
path
start_line
end_line
text
```

### Asset Registry

#### `assets.jsonl`

One record per indexed Unreal asset.

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

#### `asset_dependencies.jsonl`

Normalized package dependency edges.

```text
source_package
target_package
category
```

## Blueprint canonical streams

### `blueprints.jsonl`

One record per Blueprint-family asset.

Includes Blueprint identity/inheritance plus declared variable and SCS-component arrays. Large graph bodies live in separate streams.

### `blueprint_graphs.jsonl`

One record per unique Blueprint-owned graph.

Important fields:

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

Typical systems include:

```text
k2
animation
control_rig
blend_stack
umg
graph
```

### `blueprint_nodes.jsonl`

One record per editor graph node.

Important fields:

```text
node_id
blueprint_path
graph_id
graph_name
graph_kind
graph_system
node_class
operation
symbol
owner
semantic
title
comment
x
y
pins[]
```

`operation`, `symbol`, and `owner` are factual normalized semantics. Specialized facts remain in `semantic`.

Unknown/specialized nodes stay factual rather than being guessed from display text.

### Core K2 operation examples

```text
function_entry
function_result
function_call
event
custom_event
variable_get
variable_set
variable_reference
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
comment
```

### Schema-11 struct operations

Schema 11 canonically distinguishes:

```text
make_struct
break_struct
set_fields_in_struct
struct_operation
```

For recognized `UK2Node_StructOperation` nodes, semantic fields include:

```text
struct_type
struct_name
pure
classification_source
concrete_node_class
```

This fixes schema-10's inherited-class misclassification of Make/Break/SetFields nodes as `variable_reference`.

### Animation operation examples

```text
anim_state_machine
anim_state_entry
anim_state
anim_transition
anim_conduit
anim_state_alias
anim_save_cached_pose
anim_use_cached_pose
anim_linked_layer
anim_linked_input_pose
anim_slot
anim_sequence_player
anim_graph_root
anim_state_result
anim_transition_result
anim_blend_space_player
anim_sequence_evaluator
anim_motion_matching
anim_control_rig
```

### `blueprint_pins.jsonl`

Normalized pin stream.

Important fields include:

```text
pin_id
node_id
graph_id
blueprint_path
name
direction
type
default_value
default_object
default_text
hidden/connectability flags
link_count
```

Pin types preserve category/subcategory/container/reference/const information and object types when Unreal exposes them.

### `blueprint_edges.jsonl`

Exact pin-to-pin Blueprint graph connections.

```text
edge_id
graph_id
source_node_id
source_pin_id
target_node_id
target_pin_id
source_pin_name
target_pin_name
edge_kind
```

`edge_kind` is `execution` or `data`.

### `blueprint_interfaces.jsonl`

Implemented Blueprint interfaces and associated function graph paths.

### `blueprint_node_properties.jsonl`

Flattened non-transient reflected node properties.

Important fields:

```text
node_id
property_name
property_path
declaring_type
depth
property_type
cpp_type
value
object_path
object_class
property_flags
truncated
```

Nested structs are traversed to a bounded depth. Simple arrays are expanded in bounded form.

### `blueprint_node_references.jsonl`

Normalized UObject references discovered during node reflection.

### `blueprint_bindings.jsonl`

Normalized AnimGraph node property-binding entries.

Includes target property, access path, path segments, compiled context, pin types, and raw reflected value.

### Authored Blueprint state/default streams

```text
blueprint_defaults.jsonl
blueprint_component_properties.jsonl
blueprint_state_values.jsonl
```

These capture Blueprint CDO/component-template changed state that requires loaded Unreal objects.

### Timeline streams

```text
blueprint_timelines.jsonl
blueprint_timeline_tracks.jsonl
blueprint_timeline_keys.jsonl
```

Keys preserve time/value/interpolation/tangent facts where applicable.

### UMG streams

```text
blueprint_widgets.jsonl
blueprint_widget_properties.jsonl
blueprint_widget_bindings.jsonl
blueprint_widget_animations.jsonl
blueprint_widget_animation_bindings.jsonl
```

## Compact RigVM canonical streams

Normal scans write:

```text
rigvm_objects.jsonl
rigvm_pins.jsonl
rigvm_links.jsonl
rigvm_references.jsonl
```

`rigvm_objects` records compact graph/node model identity and factual node kind/operation.

`rigvm_pins` records model pins, types, directions, defaults, and flags.

`rigvm_links` records exact source-pin-path → target-pin-path connections.

`rigvm_references` records structural and external UObject relationships.

### `rigvm_properties.jsonl`

Optional raw reflection stream, populated only with:

```text
--include-raw-rigvm-properties
```

It is intentionally excluded from ordinary scans/uploads because large Control Rig corpora showed extremely high volume with little routine retrieval value.

## AI canonical streams

### Behavior Trees

```text
behavior_trees.jsonl
behavior_tree_nodes.jsonl
behavior_tree_edges.jsonl
```

Includes hierarchy, child ordering, task/composite/decorator/service identity, attachments, Blackboard association, and reflected settings.

### Blackboards

```text
blackboards.jsonl
blackboard_keys.jsonl
```

Includes parent inheritance, key order/name/type, sync settings, and key-type configuration.

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

Includes hierarchy, tasks/evaluators, conditions/considerations, transitions, property bindings, linked StateTrees, and reflected settings.

### `ai_properties.jsonl`

Loss-minimizing reflected settings for AI nodes/objects.

## PCG canonical streams

```text
pcg_graphs.jsonl
pcg_nodes.jsonl
pcg_pins.jsonl
pcg_edges.jsonl
pcg_properties.jsonl
```

These preserve graph identity, exact topology, settings objects, graph/user state, and reflected node/settings properties.

## Material canonical streams

```text
materials.jsonl
material_expressions.jsonl
material_edges.jsonl
material_properties.jsonl
```

They preserve material/function/instance identity, expression objects, root/output wiring, recursive expression-input topology, references, parameters/settings, and reflected properties.

---

# Derived schema 7

Everything below is deterministic Python output and may be deleted/regenerated.

Run:

```powershell
python scripts\uatool.py derive <Project>\.uatool
```

`pack` and `bundle` also rerun derivation.

## `blueprint_functions.jsonl`

Normalized function definitions.

Includes:

```text
function_id
blueprint_path
graph_id
name
owner
resolved_function
function_flags
has_exec
pure_shape
blueprint_pure
const_function
blueprint_callable
static_function
event_function
entry_node_id
result_node_ids
inputs
outputs
locals
```

`blueprint_pure` comes from authoritative `FUNC_BlueprintPure`; it is intentionally separate from structural `has_exec` because UE can retain entry/result exec pins even on BlueprintPure functions.

## `blueprint_events.jsonl`

Normalized event definitions including custom, override, component-bound, input, and related event kinds.

## `blueprint_call_edges.jsonl`

One row per Blueprint `function_call`.

Important fields:

```text
call_id
caller_function_id
target_function
target_name
target_owner
target_blueprint_path
target_function_id
resolution
candidate_count
candidate_function_ids
pure
const_function
latent
interface_call
function_flags
```

Resolution values:

```text
internal
ambiguous_internal
external
unresolved
```

Ambiguous interface/override definitions are preserved rather than guessed.

## `blueprint_call_bindings.jsonl`

Derived schema 7 cross-function parameter map for uniquely resolved internal calls.

Important fields:

```text
binding_id
call_id
call_node_id
caller_blueprint_path
caller_graph_id
caller_function_id
target_blueprint_path
target_function_id
direction
call_pin_id
call_pin_name
parameter_name
parameter_pin_ids
match_kind
split_suffix
call_pin_type
parameter_type
dependency_ids
consumer_pin_ids
```

`direction`:

```text
argument
return
```

`match_kind` includes exact and split-struct matching.

Context pins such as `self`/`Target` are not falsely treated as function parameters.

## `blueprint_data_dependencies.jsonl`

Bounded upstream data provenance for connected non-exec inputs on execution-bearing/result nodes.

Important fields include:

```text
dependency_id
blueprint_path
graph_id
sink_node_id
sink_pin_id
sink_pin_name
sink_operation
sink_label
expression
expression_text
variable_reads
function_calls
object_references
boundary_nodes
cycle
truncated
```

Current bounds:

```text
maximum recursive depth: 24
maximum expression nodes: 64
```

Cycles/truncation are explicit rather than silently discarded.

For legacy schema-10 input, derived schema 7 corrects the known Make/Break/SetFields struct-operation classification in-memory for reconstruction without mutating canonical data.

## Blueprint execution program

```text
blueprint_execution_blocks.jsonl
blueprint_execution_block_edges.jsonl
blueprint_execution_roots.jsonl
```

Execution edges are collapsed into deterministic basic blocks.

Blocks preserve ordered node IDs, semantic operations, labels, and compact text.

Block edges preserve source/target node and exec-pin names.

Roots map normalized functions/events to starting blocks. BlueprintPure functions remain explicitly identifiable even if UE keeps structural exec pins.

## Normalized AnimBP state machines

```text
anim_state_machines.jsonl
anim_states.jsonl
anim_transitions.jsonl
```

The derived layer resolves:

- machine editor graph;
- entry node and entry state;
- state/conduit/alias records;
- exact previous/next transition state IDs;
- rule/custom transition graph paths;
- transition settings.

## Blueprint relations/context/summaries

```text
blueprint_relations.jsonl
blueprint_graph_context.jsonl
blueprint_summaries.jsonl
```

Relations include factual calls, reads/writes, casts, macros, asset references, animation links, bindings, timeline/widget links, and Control Rig/RigVM joins.

Graph context is bounded deterministic text reconstructed from nodes/pins/edges/semantics.

Summaries are factual inventories rather than generated interpretation.

## `rigvm_editor_links.jsonl`

Deterministic joins from Control Rig editor nodes to compact RigVM model nodes.

Join status remains explicit:

```text
matched
ambiguous
unmatched
```

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

Blackboard selector resolution respects parent Blackboard inheritance.

## PCG/material derived views

```text
pcg_parameters.jsonl
material_parameters.jsonl
visual_relations.jsonl
pcg_graph_context.jsonl
material_graph_context.jsonl
visual_summaries.jsonl
```

PCG `uses_subgraph` is emitted only for a non-self PCGGraph target or a property whose name explicitly identifies a subgraph relationship, avoiding reflected ownership back-reference false positives.

## SQLite

`uat.db` mirrors canonical and derived streams into indexed relational tables.

It is always regenerable:

```powershell
python scripts\uatool.py pack <Project>\.uatool
```

## Upload bundle

The normal bundle includes canonical JSONL and useful derived JSONL.

It excludes:

```text
uat.db
rigvm_properties.jsonl
```

unless raw RigVM properties are explicitly requested.

Create it with:

```powershell
python scripts\uatool.py bundle <Project>\.uatool
```

## Schema compatibility rule

Never silently rewrite canonical old-schema JSONL into new canonical truth.

Backward-compatible derived fixes may interpret known old-schema facts differently, but the manifest continues to identify the scanner schema that actually produced the raw data.
