# UnrealAssetTool schema v9

The scan format is line-oriented so individual records can be streamed, indexed, diffed, embedded, or retrieved without parsing a monolithic project document.

## `manifest.json`

One JSON document describing the scan.

Important fields:

- `schema_version`
- `tool`
- `generated_utc`
- `engine_version`
- `project_file`
- `project_dir`
- `include_generated`
- `include_engine`
- `counts` (including normalized Blueprint graph/pin/interface counts, flattened state/Timeline/UMG counts, and compact RigVM object/pin/link/reference counts; raw RigVM property count is normally zero)
- `derived_schema_version` and `derived_counts` after the Python derivation pass

## `files.jsonl`

One record per physical project file.

```json
{
  "path": "Source/MyGame/MyActor.cpp",
  "kind": "source",
  "extension": ".cpp",
  "size": 12345,
  "modified_utc": "2026-08-28T12:00:00Z"
}
```

## `source_chunks.jsonl`

Text files are split by source line rather than arbitrary token count so results can be mapped back to files and diagnostics.

```json
{
  "path": "Source/MyGame/MyActor.cpp",
  "start_line": 1,
  "end_line": 200,
  "text": "..."
}
```

## `assets.jsonl`

One record per project-owned Asset Registry asset.

```json
{
  "object_path": "/Game/Characters/BP_Player.BP_Player",
  "asset_name": "BP_Player",
  "package_name": "/Game/Characters/BP_Player",
  "package_path": "/Game/Characters",
  "class_path": "/Script/Engine.Blueprint",
  "disk_path": "E:/Project/Content/Characters/BP_Player.uasset",
  "tags": {},
  "dependencies": ["/Game/Input/IMC_Player"]
}
```

## `asset_dependencies.jsonl`

Normalized dependency edges.

```json
{
  "source_package": "/Game/Characters/BP_Player",
  "target_package": "/Game/Input/IMC_Player",
  "category": "package"
}
```

## `blueprints.jsonl`

One record per Blueprint-family asset.

The record includes identity/inheritance plus arrays for declared variables and SCS components. Graph node bodies are kept in their own stream to avoid giant Blueprint rows.

## `blueprint_nodes.jsonl`

One record per Blueprint graph node.

Important fields:

- `node_id`: stable-ish composite ID using Blueprint object path, full graph identity, and node GUID;
- `blueprint_path`
- `graph_name`
- `graph_kind`
- `graph_class`
- `schema_class`
- `node_class`
- `operation`: normalized factual operation. Core K2 examples include `variable_get`, `variable_set`, `function_call`, `function_entry`, `function_result`, `event`, `custom_event`, `dynamic_cast`, `spawn_actor`, `macro_instance`, `switch`, `select`, `execution_sequence`, `reroute`, `branch`, `tunnel`, and `self`. AnimBP examples include `anim_state_machine`, `anim_state`, `anim_transition`, `anim_conduit`, `anim_state_alias`, `anim_state_entry`, `anim_save_cached_pose`, `anim_use_cached_pose`, `anim_linked_layer`, `anim_linked_input_pose`, `anim_slot`, `anim_sequence_player`, `anim_graph_root`, `anim_state_result`, and `anim_transition_result`;
- `symbol`: the referenced variable/function/event/macro/type name when Unreal exposes one;
- `owner`: the owning/source class or Blueprint when Unreal exposes one;
- `semantic`: node-type-specific structured facts used to derive `operation`, `symbol`, and `owner`;
- `title`
- `comment`
- `x`, `y`
- `pins[]`

Each pin includes:

- `pin_id`
- `name`
- `direction`
- `type`
- default literal/object/text values
- relevant connection/display flags

For example, a function-call node may contain:

```json
{
  "operation": "function_call",
  "symbol": "GetMover",
  "owner": "/Script/Mover.MoverComponent",
  "semantic": {
    "operation": "function_call",
    "symbol": "GetMover",
    "owner": "/Script/Mover.MoverComponent",
    "member_name": "GetMover",
    "resolved_function": "/Script/Mover.MoverComponent:GetMover",
    "function_owner": "/Script/Mover.MoverComponent",
    "pure": true,
    "const": true,
    "interface_call": false,
    "latent": false
  }
}
```

Unknown or specialized graph-node classes remain `operation: "node"` rather than having behavior inferred from their display title.


### Animation Blueprint graph kinds

For Animation Blueprints, `graph_kind` distinguishes the editor graph class rather than treating every nested graph as generic Blueprint logic:

- `anim_graph`
- `anim_state_machine`
- `anim_state`
- `anim_transition`
- `anim_conduit`

Animation state/transition node semantics include exact state names, rule graph paths, previous/next states, transition priority, crossfade duration, automatic-rule settings, shared-rule/crossfade metadata, and state reset/type settings when Unreal exposes them.



## `blueprint_graphs.jsonl`

One record per unique Blueprint-owned graph. Schema v6 deduplicates `UBlueprint::GetAllGraphs()` by full graph path before scanning, preventing repeated nested Control Rig graphs from producing duplicate node IDs. Records include `graph_id`, full `graph_path`, `graph_kind`, `graph_system`, graph/schema classes, outer/parent context, and node count.

## `blueprint_pins.jsonl`

One normalized record per Blueprint pin, including its node/graph IDs, index, direction, type object, default value/object/text, visibility/connectability flags, and link count. Pins remain inline in `blueprint_nodes.jsonl` for self-contained node records.

## `blueprint_interfaces.jsonl`

One record per implemented Blueprint interface, including the interface class and associated function graph paths.

The SQLite packer also normalizes the `variables` and `components` arrays already stored in each `blueprints.jsonl` record into `blueprint_variables` and `blueprint_components` tables. These are derived indexes rather than additional canonical JSONL streams.

## `blueprint_node_properties.jsonl`

One record per node-specific reflected Unreal property. This stream captures serialized/editor configuration that is not represented by pins or by a dedicated semantic decoder. UATool walks each node's concrete class hierarchy down to (but not including) the generic `UK2Node`/`UEdGraphNode` storage and exports non-transient `FProperty` values through Unreal's reflection system.

Important fields:

- `node_id`
- `blueprint_path`
- `graph_name`
- `node_class`
- `property_name`
- `property_path`: flattened address from the graph node, for example `Node.Sequence` or `Binding.PropertyBindings`;
- `owner_class`: retained compatibility field for the declaring Unreal type;
- `declaring_type`: class or script-struct that declared the property;
- `depth`: zero for a direct node property, greater than zero for nested struct/binding fields;
- `property_type`: Unreal reflection property class;
- `cpp_type`
- `value`: Unreal's text export of the property value;
- `object_path`: direct UObject reference when the property value resolves to an object;
- `object_class`: concrete class of `object_path`;
- `property_flags`
- `truncated`: true only when an individual exported value exceeded the safety cap.

Nested structs are recursively flattened to a bounded depth. Arrays of simple scalar/name/object values are expanded with paths such as `Path[0]`; arrays of structs remain represented by their exported parent value to avoid unbounded growth. Node-owned binding objects are selectively traversed so AnimGraph property bindings become visible without recursively walking arbitrary graphs or assets.

This remains a raw-facts layer. Dedicated semantic fields are promoted only when the reflected fact is unambiguous.

## `blueprint_node_references.jsonl`

Normalized object-reference edges discovered while reflecting graph-node properties.

```json
{
  "node_id": "...",
  "blueprint_path": "/Game/Characters/ABP_Player.ABP_Player",
  "graph_name": "AnimGraph",
  "node_class": "/Script/AnimGraph.AnimGraphNode_BlendSpacePlayer",
  "property_path": "Node.BlendSpace",
  "target_object_path": "/Game/Animation/BS_Locomotion.BS_Locomotion",
  "target_class": "/Script/Engine.BlendSpace",
  "node_owned": false
}
```

`node_owned` distinguishes editor subobjects such as an AnimGraph binding object from external assets/classes referenced by the node.

## `blueprint_bindings.jsonl`

One record per normalized entry in a node-owned AnimGraph binding object's `PropertyBindings` map.

Important fields:

- `node_id`
- `blueprint_path`
- `graph_name`
- `node_class`
- `binding_object`
- `binding_key`
- `target_property`
- `access_path`
- `property_path[]`
- `compiled_context`
- `pin_type`
- `promoted_pin_type`
- `raw_value`

This stream preserves both normalized fields and the raw reflected map-value text. It is intended for facts such as an AnimGraph runtime property being driven by a Property Access/function path.

## Compact RigVM model (schema v6)

Normal scans write compact RigVM graph/node records to `rigvm_objects.jsonl`, normalized model pins to `rigvm_pins.jsonl`, links to `rigvm_links.jsonl`, and structural/external UObject relationships to `rigvm_references.jsonl`. `rigvm_properties.jsonl` is only populated when `-IncludeRawRigVMProperties` / `--include-raw-rigvm-properties` is requested.

## `rigvm_objects.jsonl`

One compact record per Blueprint-owned RigVM graph or node. Pins and links are normalized into their own streams so normal scans do not duplicate them in the object stream.

Important fields:

- `object_id`: full UObject path;
- `blueprint_path`
- `kind`: `graph` or `node`;
- `class_path`
- `name`
- `outer_object_id`
- `outer_class`
- `operation`: factual class-based operation for RigVM nodes.

Recognized node operations include `rigvm_function_entry`, `rigvm_function_return`, `rigvm_function_reference`, `rigvm_variable`, `rigvm_unit`, `rigvm_dispatch`, `rigvm_invoke_entry`, `rigvm_reroute`, `rigvm_enum`, `rigvm_comment`, `rigvm_parameter`, `rigvm_library`, and `rigvm_template`. Unknown RigVM node subclasses remain `rigvm_node` rather than having behavior inferred from names.

## `rigvm_pins.jsonl`

One compact record per RigVM model pin, including its full pin ID/path, owning model object, direction, C++ type/type object, default value/object/type, custom widget, and key constant/input/dynamic/lazy flags.

## `rigvm_links.jsonl`

One compact record per RigVM link, including its full link ID/path and exact `source_pin_path` / `target_pin_path`.

## `rigvm_properties.jsonl`

Reflected non-transient properties for each object in `rigvm_objects.jsonl`.

Important fields:

- `object_id`
- `blueprint_path`
- `kind`
- `class_path`
- `declaring_type`
- `property_name`
- `property_path`
- `property_type`
- `cpp_type`
- `value`
- `object_path`
- `object_class`
- `property_flags`
- `truncated`

This is a loss-minimizing raw layer intended to expose actual RigVM model data such as node pins, pin types/defaults/directions, function headers, variable metadata, and unit/dispatch configuration when those fields are reflected by Unreal.

## `rigvm_references.jsonl`

Normalized UObject relationships found in reflected RigVM properties. Direct object properties and arrays of object properties are emitted independently from the text representation.

```json
{
  "source_object_id": "/Game/Rigs/CR_Example.CR_Example:Model",
  "blueprint_path": "/Game/Rigs/CR_Example.CR_Example",
  "source_kind": "graph",
  "source_class": "/Script/RigVMDeveloper.RigVMGraph",
  "property_path": "Nodes[0]",
  "target_object_id": "/Game/Rigs/CR_Example.CR_Example:Model.RigUnit_BeginExecution",
  "target_kind": "node",
  "target_class": "/Script/RigVMDeveloper.RigVMUnitNode"
}
```

Targets may also be non-RigVM assets/classes; in that case `target_kind` is empty while the exact target class/path remain recorded.

## `blueprint_edges.jsonl`

One directed record per output-pin to linked-pin connection.

```json
{
  "blueprint_path": "/Game/Characters/BP_Player.BP_Player",
  "graph_name": "EventGraph",
  "source_pin_id": "...",
  "target_pin_id": "...",
  "pin_category": "exec"
}
```

`pin_category` lets downstream tools distinguish execution-flow edges from typed data-flow edges.

## `uat.db`

The Python `pack` step creates a derived SQLite database with normalized tables and an FTS5 source index when the local SQLite build supports FTS5.

Canonical truth remains the JSONL output. The database may be deleted and rebuilt without rescanning Unreal.


## Schema v7 Blueprint state and derived reconstruction

Schema v7 adds non-graph Blueprint state that materially changes runtime/design behavior:

- `blueprint_defaults.jsonl`: CDO values that differ from the parent CDO (plus Blueprint-declared fields), with property type/flags and direct UObject references.
- `blueprint_component_properties.jsonl`: SCS component-template values that differ from the component class default object.
- `blueprint_timelines.jsonl` and `blueprint_timeline_tracks.jsonl`: Timeline configuration and typed tracks/curves/functions.
- `blueprint_widgets.jsonl`, `blueprint_widget_bindings.jsonl`, and `blueprint_widget_animations.jsonl`: UMG designer hierarchy, slot layout state, editor bindings, and animations.

Graph scanning also de-duplicates emitted node, pin, and edge identities within each graph, not only graph objects themselves. This prevents repeated nested Control Rig editor nodes from appearing twice in canonical JSONL.

The Python derivation layer has `derived_schema_version = 1` and emits `rigvm_editor_links.jsonl`, `blueprint_relations.jsonl`, `blueprint_graph_context.jsonl`, and `blueprint_summaries.jsonl`. These are reproducible indexes over canonical scan data and can be regenerated with `uatool.py derive`. The raw Unreal schema version and derived schema version are recorded separately in `manifest.json`.


## Schema v9 Blueprint reconstruction streams

### `blueprint_state_values.jsonl`

A bounded, changed-only tree for CDO and component-template state.  Top-level
schema-v7 override records remain available; this stream makes nested changed
struct/array values addressable without dumping unchanged defaults.

Important fields include `owner_kind`, `owner_id`, `owner_name`, `root_property`,
`property_path`, `depth`, `container_kind`, current/baseline values, and direct
current/baseline UObject references.  Recursion is deliberately bounded.

### `blueprint_timeline_keys.jsonl`

One record per rich-curve key used by a Blueprint Timeline track/channel.  It
records Timeline/track/channel identity, key index, time/value, interpolation
mode, tangent mode/weight mode, and arrive/leave tangent values and weights.

### `blueprint_widget_properties.jsonl`

Changed designer-widget and panel-slot properties relative to each object's
class default object.  This supplements the compact hierarchy in
`blueprint_widgets.jsonl` with class-specific authored state such as TextBlock,
Image, Button/CommonUI, and slot-layout overrides when Unreal exposes them as
reflected properties.

### `blueprint_widget_animation_bindings.jsonl`

Normalized `FWidgetAnimationBinding` records: animation identity, widget name,
slot-widget name, animation GUID, root-widget flag, and dynamic binding data.

## Schema v9 derived reconstruction streams

These files are reproducible with `python scripts/uatool.py derive <output>` and
do not require reopening Unreal.

### `blueprint_functions.jsonl`

Canonical function definitions derived from function-entry/result nodes and
normalized pins.  Records contain function/graph identity, resolved function and
flags, execution/pure shape, inputs, outputs, local variables, and result nodes.

### `blueprint_events.jsonl`

Canonical event definitions.  Event kinds include ordinary/override/custom,
component-bound delegate events, Enhanced Input, legacy input actions, input
axis events, and key events.  Component events promote component/delegate owner
facts from serialized node properties and expose output parameters.

### `rigvm_editor_links.jsonl`

Schema v9 uses graph-first Control Rig matching: the entire editor graph is
matched to a RigVM graph scope using exact hierarchy segments, model node names,
positions, and graph shape before individual nodes are joined.  This avoids
ambiguities from repeated Entry/Return/Sequence nodes in nested Control Rig
functions.

### `blueprint_relations.jsonl`

Adds function/event relations (`defines_function`, `defines_event`,
`handles_delegate`, `handles_input`), flattened-state/widget object-reference
relations, normalized widget-animation targets, and the existing calls/reads/
writes/assets/animation/Control Rig relations.

### `blueprint_graph_context.jsonl`

Retrieval-oriented deterministic graph text now includes canonical function
signatures, specialized event identity, resolved RigVM operations/functions,
RigVM input defaults, Blueprint pin defaults, and execution/data-flow edges.
Canonical node/pin/edge tables remain authoritative.

### `blueprint_summaries.jsonl`

Per-Blueprint summaries additionally count functions, events, defaults,
component/state overrides, Timelines/tracks/keys, widgets/properties/bindings,
and widget animations/bindings.


## AI gameplay systems (schema v9)

### `behavior_trees.jsonl`

One record per `UBehaviorTree`, including the root node, associated Blackboard, root decorator count, and root decorator logic.

### `behavior_tree_nodes.jsonl`

One record per composite, task, decorator, service, or auxiliary node. Records retain concrete class identity, display name, tree ownership, child position, and attachment metadata. Blueprint-generated node classes are joined to their originating Blueprint in the derived AI relation layer.

### `behavior_tree_edges.jsonl`

Ordered Behavior Tree topology. Child edges preserve child index, decorator IDs, and the serialized `FBTDecoratorLogic` expression. Service edges preserve service attachment to composites.

### `blackboards.jsonl` / `blackboard_keys.jsonl`

Blackboard inheritance and ordered key definitions. Each key records its key-type object/class and instance-sync flag. Key-type UObject settings are stored in `ai_properties.jsonl`.

### `eqs_queries.jsonl`, `eqs_options.jsonl`, `eqs_generators.jsonl`, `eqs_tests.jsonl`

Canonical Environment Query structure: query -> ordered option -> generator + ordered tests. Generator/test concrete classes and key scoring/filter fields are promoted; the full non-transient reflected settings remain available in `ai_properties.jsonl`.

### `statetrees.jsonl`

One record per `UStateTree`, including the reflected editor-data object and compile hash.

### `statetree_states.jsonl`

Hierarchical editor states with stable state ID, parent/child ordering, display name, state type, selection behavior, enabled/tag/task-completion information, required-event data, and linked StateTree/subtree information.

### `statetree_nodes.jsonl`

Editor nodes for evaluators, global tasks, state tasks, enter conditions, considerations, and transition conditions. `FStateTreeEditorNode` identity/expression fields are normalized; native instanced-struct payloads are retained as bounded raw text and Blueprint/object-backed node instances include their concrete class.

### `statetree_transitions.jsonl`

One record per editor transition with source state, order, trigger, target state-link text, event/priority/fallback/delay settings, and bounded raw transition text.

### `statetree_bindings.jsonl`

One record per editor property binding, preserving UE 5.8 `SourcePropertyPath`/`TargetPropertyPath` values and output-binding direction. The 0.5.1 packer can recover these paths from the bounded raw record when packing a 0.5.0 capture.

### `ai_properties.jsonl`

Shared reflected-property stream for Behavior Tree nodes, Blackboard key-type objects, EQS options/generators/tests, and StateTree editor/state/instance objects. It records owner/system identity, property type/text, direct UObject targets, flags, and truncation state.

### Derived `ai_relations.jsonl` and `ai_summaries.jsonl`

`uatool derive`, `pack`, and `bundle` generate reproducible AI-oriented joins including Behavior Tree -> Blackboard, inherited Blackboard-key selectors, BT -> EQS query execution, ordered BT child/service edges, Blackboard inheritance/keys, EQS option/generator/test edges, StateTree hierarchy/node/transition/binding relationships, concrete StateTree `transitions_to` edges, linked StateTrees, top-level AI asset references, and Blueprint implementations of Blueprint-backed AI nodes. Empty StateTree editor-node placeholders are ignored. `ai_summaries.jsonl` renders those facts into bounded per-asset retrieval context.


## PCG and material visual systems (schema v10)

### `pcg_graphs.jsonl`

One record per top-level or embedded PCG graph. Records include graph class, parent/embedded relationship, embedded-subgraph paths, node/pin/edge counts, and bounded user-parameter/default-grid state.

### `pcg_nodes.jsonl` / `pcg_pins.jsonl` / `pcg_edges.jsonl`

Canonical PCG topology. Nodes retain concrete settings object/class and editor position/title where reflected. Pins retain input/output direction, order, label, allowed data types, status, multiplicity, visibility, and raw pin properties. Edges use exact pin and node object paths.

### `pcg_properties.jsonl`

Bounded reflected properties for PCG graphs, nodes, and settings objects, including direct UObject/class targets. This is the factual substrate for subgraph, Blueprint element, material, and parameter derivation without a hard PCG module dependency.

### Derived `pcg_parameters.jsonl` and `pcg_graph_context.jsonl`

`pcg_parameters` promotes parameter-bearing graph/settings properties into addressable records. `pcg_graph_context` renders bounded node/settings and pin-to-pin data flow for retrieval while canonical PCG tables remain authoritative.

### `materials.jsonl`

One record per Material, Material Function, Material Instance Constant, or Material Function Instance scanned by schema v10. Records include kind, concrete class, expression count, parent relationship, and material-domain/blend/shading fields where present.

### `material_expressions.jsonl`

One record per owned `UMaterialExpression`, including concrete class, editor position, description, parameter name, called Material Function, referenced Texture, and common default/value fields.

### `material_edges.jsonl`

Canonical material wiring reconstructed from reflected `FExpressionInput`-family structs. The scanner recurses through nested structs and arrays so function-call inputs, layer-blend records, and similar compound expression inputs remain connected. Root `UMaterialEditorOnlyData` inputs are represented as `$output:<Property>` targets.

### `material_properties.jsonl`

Bounded reflected properties for material/function assets, expressions, and editor-only data objects with direct UObject targets.

### Derived `material_parameters.jsonl`, `material_graph_context.jsonl`, `visual_relations.jsonl`, and `visual_summaries.jsonl`

Material parameters promote parameter expressions and instance parameter override groups. Visual relations connect PCG data flow/subgraphs/Blueprint elements and material expression flow/function/texture/parent relationships, plus Blueprint references to PCG/material assets. Graph contexts and summaries are bounded deterministic retrieval views and can be regenerated with `uatool derive` without reopening Unreal.
