# UnrealAssetTool schema v3

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
- `counts`

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
- `owner_class`: the class that declared the property;
- `property_type`: Unreal reflection property class;
- `cpp_type`
- `value`: Unreal's text export of the property value;
- `object_path`: direct UObject reference when the property is an object property;
- `property_flags`
- `truncated`: true only when an individual exported value exceeded the safety cap.

This is intentionally a raw-facts layer. For example, plugin-specific nodes such as Property Access, Motion Matching, Chooser, or Control Rig can expose their serialized settings here before UATool has a hand-written semantic decoder for that node type.

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
