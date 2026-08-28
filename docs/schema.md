# UnrealAssetTool schema v5

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
- `counts` (including Blueprint semantic/property/reference/binding counts and RigVM object/property/reference counts for schema v5)

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

- `node_id`: stable-ish composite ID using Blueprint object path, graph name, and node GUID;
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

## `rigvm_objects.jsonl`

One record per Blueprint-owned UObject whose class derives from `RigVMGraph`, `RigVMNode`, `RigVMPin`, or `RigVMLink`.

Important fields:

- `object_id`: full UObject path;
- `blueprint_path`
- `kind`: `graph`, `node`, `pin`, or `link`;
- `class_path`
- `name`
- `outer_object_id`
- `outer_class`
- `operation`: factual class-based operation for RigVM nodes.

Recognized node operations include `rigvm_function_entry`, `rigvm_function_return`, `rigvm_function_reference`, `rigvm_variable`, `rigvm_unit`, `rigvm_dispatch`, `rigvm_invoke_entry`, `rigvm_reroute`, `rigvm_enum`, `rigvm_comment`, `rigvm_parameter`, `rigvm_library`, and `rigvm_template`. Unknown RigVM node subclasses remain `rigvm_node` rather than having behavior inferred from names.

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
