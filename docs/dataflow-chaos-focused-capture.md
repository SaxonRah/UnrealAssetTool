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

On the current corpus this nominates exactly:

- 9 destruction `UDataflow` assets;
- 29 `UGeometryCollection` assets;
- 38 total focus assets.

It excludes the three `/Game/MetaHumans/...` hair Dataflows.

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

Node parameter values remain Unreal's own `ExportTextItem_Direct` representation in this diagnostic. Nested normalization is a systems-schema design decision, not something inferred from editor text.

## Geometry Collection truth

For every focused exact `/Script/GeometryCollectionEngine.GeometryCollection` asset the commandlet reflects all non-transient top-level properties against the native class default object and emits direct object/soft-object references.

This is deliberately reflection-based: the focused module does not add a GeometryCollectionEngine compile-time dependency or hard-code field layouts. Current UE 5.8 fields such as `DataflowAsset`, `DataflowInstance`, `Overrides`, `DamageThreshold`, `DamagePropagationData`, clustering/removal fields and `SizeSpecificData` are observed as authored engine state without coupling the diagnostic to a sample convention.

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

Those need separately designed evidence/coverage boundaries.

## Accepted ContentExamples result

The real UE 5.8.2 ContentExamples pass completed successfully and loaded all 38 nominated assets:

```text
focus_assets                         38
loaded_assets                        38
dataflow_assets                       9
geometry_collections                 29
graphs                                9
nodes                               602
pins                               2365
edges                               767
dataflow_asset_properties           135
dataflow_asset_references              9
node_properties                    5570
node_references                       14
geometry_collection_properties     1508
geometry_collection_references       75
property_row_limit_hits                0
```

All nine graph rows reconcile with their physical node and edge rows. Node and pin GUIDs are unique within each asset. Every one of the 767 links resolves to the declared output-pin -> input-pin endpoints and every node's declared input/output count equals its emitted pin rows.

The focused graph surface is nontrivial. It includes nine `GeometryCollectionTerminalDataflowNode_v2` nodes as well as fracture, clustering, convex-hull, source, material, GeometryScript, subgraph, selection and reroute families.

### Negative evidence is part of the contract

Every focused Geometry Collection has `DataflowAsset=None`. There are zero Geometry Collection `DataflowAsset` reference rows. The corpus therefore does **not** prove a GeometryCollection -> Dataflow asset relationship and downstream schema/graph code must not manufacture one. `DataflowInstance` does carry `DataflowTerminal="GeometryCollectionTerminal"`; that remains authored scalar/struct state unless a real asset reference is present.

### GeometrySource boundary

One property export hit the 65,536-character diagnostic cap:

```text
/Game/ExampleContent/Destruction/Modules/ChaosPrimitives/GC/KioskExamples/GC_Stack_SizeSpecificDataExample.GC_Stack_SizeSpecificDataExample
  GeometrySource
```

This was inspected rather than silently accepted. `GeometrySource` is editor/construction-source provenance, not destruction behavior or runtime state. No Dataflow topology, node parameter/reference, damage/clustering/removal field, `SizeSpecificData` behavior field or `DataflowInstance` state was truncated.

Systems schema 9 therefore excludes `GeometrySource` from its first-class behavioral surface. Generic asset/dependency data remains available for coarse source-asset provenance. This inspected construction-provenance truncation does not require another focused capture.

## Acceptance decision

The focused evidence gate is accepted. No additional focused UE run is required before systems schema 9 / derived schema 25 design.
