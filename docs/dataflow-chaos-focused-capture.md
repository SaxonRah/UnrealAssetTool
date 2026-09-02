# Dataflow / Geometry Collection / Chaos focused capture

This is an evidence pass, not systems schema 9.

The command is:

```text
uatool dataflow-chaos-capture <project> --editor <UnrealEditor-Cmd> [--asset-prefix <object-prefix>]
```

It launches a focused UE 5.8 commandlet over exact assets nominated by an existing UnrealAssetTool corpus. It does not run the normal project scan and does not run `derive`.

## Why this capture exists

The read-only ContentExamples evidence diagnostic proved a strong destruction corpus before this commandlet was designed:

```text
unique_dataflow_assets                       12
unique_geometry_collection_assets            29
unique_placed_geometry_collection_components 349
unique_blueprint_geometry_collection_components 288
rest_collection_link_owners                 636
damage_authoring_owners                     287
unique_chaos_cache_collection_assets          1
```

Nine of the twelve `UDataflow` assets are under `/Game/ExampleContent/Destruction/`. The remaining three are MetaHuman hair Dataflows and are intentionally treated as a separate Dataflow consumer for this acceptance slice.

The generic corpus already gives strong authored evidence for `GeometryCollectionComponent`, `RestCollection`, damage/clustering/removal settings and gameplay usage. The two meaningful gaps are:

1. the internal authored `UDataflow` node/pin/link graph;
2. direct Geometry Collection asset state, especially any authored `DataflowAsset` binding.

The focused capture is limited to those gaps rather than repeating hundreds of already-proven placed components.

## Recommended ContentExamples scope

```text
--asset-prefix /Game/ExampleContent/Destruction/
```

On the current corpus this should nominate exactly:

- 9 destruction `UDataflow` assets;
- 29 `UGeometryCollection` assets;
- 38 total focus assets.

It should exclude the three `/Game/MetaHumans/...` hair Dataflows.

## Dataflow graph truth

Unlike systems whose authored surface can be recovered entirely through `UObject` reflection, Dataflow's real evaluation topology is owned by `UE::Dataflow::FGraph`. The focused commandlet therefore has explicit `DataflowCore` and `DataflowEngine` dependencies and reads the public UE 5.8 graph model directly.

For every focused `UDataflow` it records:

- one graph row;
- every `FDataflowNode` returned by the graph, including concrete `TypedScriptStruct()` identity;
- every input and output connection with pin GUID, name, direction, original type and backing reflected property;
- every exact `FLink` with source/target node GUID and pin GUID endpoints;
- top-level reflected authored fields on the `UDataflow` asset;
- top-level reflected fields on each concrete Dataflow node struct, including `DataflowInput`, `DataflowOutput`, `DataflowPassthrough` and `DataflowIntrinsic` metadata;
- direct object/soft-object references on those fields.

Node parameter values remain Unreal's own `ExportTextItem_Direct` representation in this diagnostic. Nested normalization must be designed only after the real node structs/values are inspected.

## Geometry Collection truth

For every focused exact `/Script/GeometryCollectionEngine.GeometryCollection` asset the commandlet reflects all non-transient top-level properties against the native class default object and emits direct object/soft-object references.

This is deliberately reflection-based: the focused module does not add a GeometryCollectionEngine compile-time dependency or hard-code field layouts. Important current UE 5.8 fields such as `DataflowAsset`, `DataflowInstance`, `Overrides`, `DamageThreshold`, `DamagePropagationData`, clustering/removal fields and `SizeSpecificData` can therefore be observed as authored engine state without coupling the diagnostic to a sample convention.

## Output

```text
dataflow_chaos_capture_manifest.json
dataflow_chaos_focus_assets.txt
dataflow_chaos_assets.jsonl
dataflow_graphs.jsonl
dataflow_nodes.jsonl
dataflow_pins.jsonl
dataflow_edges.jsonl
dataflow_asset_properties.jsonl
dataflow_asset_references.jsonl
dataflow_node_properties.jsonl
dataflow_node_references.jsonl
geometry_collection_properties.jsonl
geometry_collection_references.jsonl
```

The launcher also writes a ZIP and a human-readable report. The ZIP is written before Python semantic validation so a real UE result is preserved even if a new invariant rejects it.

## Manifest boundary

The focused manifest is schema 1 and must state:

```text
diagnostic_only=true
semantic_promotion=false
schema_promotion=false
runtime_state_captured=false
```

No systems schema version changes in this pass.

## Runtime exclusions

This capture does **not** record:

- evaluated Dataflow values/results;
- Chaos solver particles, islands or collision state;
- live break/removal/collision event history;
- current dynamic Geometry Collection transforms;
- runtime cache playback state;
- runtime Field System results;
- Cloth, Flesh, Vehicles or Hair semantics merely because they can consume Dataflow.

Those would need separately designed evidence/coverage boundaries.

## Acceptance gate before schema design

A useful real ContentExamples result should prove:

- all 38 destruction-scoped focus assets load;
- 9 Dataflow graph rows and 29 Geometry Collection assets;
- nonzero Dataflow nodes, pins and links;
- every node has an exact concrete script-struct identity;
- every link resolves to an output pin and an input pin owned by its declared endpoint nodes;
- nonzero node property rows that expose actual authored node types/parameters;
- Geometry Collection authored property rows, with exact `DataflowAsset` references if any are actually authored;
- zero property truncation/row-limit loss, or explicit inspection before any normalization if a limit is hit.

Only after the raw ZIP passes that gate should systems schema 9 and any derived graph version be designed.
