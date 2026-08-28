# UnrealAssetTool schema v1

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
