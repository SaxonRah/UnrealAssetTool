# Dataflow / Geometry Collection systems schema 9

Systems schema 9 promotes the accepted UE 5.8.2 Dataflow / Geometry Collection evidence into canonical authored facts. Derived schema 25 promotes only exact relationships proven by those facts.

This slice intentionally separates **Dataflow as a reusable graph substrate** from **Geometry Collection destruction authoring**. A Dataflow asset used by Hair, Cloth, Flesh, Vehicles or another consumer does not acquire that consumer's higher-level semantics merely because the graph exists.

## Canonical systems streams

Dataflow:

```text
dataflow_graphs.jsonl
dataflow_nodes.jsonl
dataflow_pins.jsonl
dataflow_edges.jsonl
dataflow_asset_properties.jsonl
dataflow_asset_references.jsonl
dataflow_node_properties.jsonl
dataflow_node_references.jsonl
```

Geometry Collection:

```text
geometry_collections.jsonl
geometry_collection_properties.jsonl
geometry_collection_references.jsonl
```

The systems manifest is schema 9.

## Dataflow model

For each exact `/Script/DataflowEngine.Dataflow` asset, the native scanner records:

- graph identity;
- every concrete `FDataflowNode` and its `UScriptStruct` type;
- ordered input and output pins with GUIDs, types and backing property identity;
- every exact `FLink` output-pin -> input-pin connection;
- bounded authored asset properties and direct object/soft-object references;
- bounded authored node-struct properties and direct object/soft-object references;
- Dataflow property metadata such as input/output/passthrough/intrinsic flags.

The graph is read through UE 5.8's public `UDataflow::GetDataflow()` / `UE::Dataflow::FGraph` surface rather than inferred from editor text or package dependency names.

## Geometry Collection behavior boundary

The first-class Geometry Collection surface is deliberately behavioral. It includes authored roots for:

- clustering and cluster connection settings;
- damage model/threshold/propagation settings;
- mass, density and physics material;
- sleep and slow-moving behavior;
- removal/crumble behavior;
- convex optimization;
- `SizeSpecificData`;
- `DataflowAsset`;
- `DataflowInstance`;
- `Overrides`.

`GeometrySource` is explicitly excluded from the specialist behavior stream. The focused ContentExamples diagnostic proved that field can contain very large editor/construction provenance, and no destruction-behavior semantics require promoting it. Coarse source-asset provenance remains available through the generic project dependency/reference layers.

## Derived schema 25 relations

The exact semantic graph relations are:

```text
has_dataflow_node
instance_of_dataflow_node_struct
has_dataflow_input
has_dataflow_output
dataflow_connects
dataflow_node_references_object
geometry_collection_uses_dataflow_asset
geometry_collection_uses_physics_material
```

`geometry_collection_uses_dataflow_asset` is emitted **only** for a non-null authored `DataflowAsset`. A terminal name or an engine API that supports a binding is not enough to manufacture this edge.

All specialist relations are `exact_semantic` and retain the canonical source stream as evidence.

## Runtime boundary

Schema 9 does not capture or simulate:

- evaluated Dataflow values/results;
- runtime Dataflow execution state;
- Chaos solver particles, islands or collision state;
- live break/collision/removal event history;
- dynamic Geometry Collection transforms;
- Chaos cache playback state;
- runtime Field System results;
- higher-level Cloth/Flesh/Hair/Vehicles semantics merely because those systems consume Dataflow.

`runtime_state_captured` is false in acceptance and verification manifests.

## Accepted ContentExamples UE 5.8.2 result

The full systems-schema-9 ContentExamples capture passed with zero specialist loss:

```text
dataflow_chaos_candidates                  71
dataflow_chaos_scoped_candidates           41
dataflow_chaos_loaded_assets               41

dataflow_assets                            12
geometry_collections                       29

dataflow_graphs                            12
dataflow_nodes                            629
dataflow_pins                            2482
dataflow_edges                            808
dataflow_asset_properties                 180
dataflow_asset_references                  15
dataflow_node_properties                 5828
dataflow_node_references                   18
geometry_collection_properties            812
geometry_collection_references             29

dataflow_chaos_truncated_properties         0
dataflow_chaos_property_row_limit_hits       0
```

The 12 Dataflows contain the nine destruction graphs previously proven by the focused pass plus three MetaHuman Hair Dataflows. This is intentional: schema 9 indexes the reusable Dataflow substrate project-wide.

Every graph/node/pin cardinality reconciles. All 808 links resolve to declared output pins and input pins. Pin indices are contiguous per node/direction.

### Negative Geometry Collection binding evidence

All 29 representative Geometry Collections have:

```text
DataflowAsset = None
DataflowTerminal = GeometryCollectionTerminal
```

Therefore ContentExamples proves **zero** `geometry_collection_uses_dataflow_asset` edges. The terminal scalar is retained as authored state but is not treated as an asset relationship.

All 29 collections produce an exact `geometry_collection_uses_physics_material` relationship.

`GeometrySource` has zero rows in the canonical behavior stream.

## Accepted derived graph

`systems-schema9-accept` generated an expectation of exactly 4,595 specialist edges:

```text
has_dataflow_node                          629
instance_of_dataflow_node_struct           629
has_dataflow_input                       1569
has_dataflow_output                       913
dataflow_connects                          808
dataflow_node_references_object             18
geometry_collection_uses_physics_material  29
geometry_collection_uses_dataflow_asset      0
                                           ----
TOTAL                                     4595
```

After one canonical derive, `dataflow-chaos-graph-verify` confirmed the exact same 4,595-edge set under derived schema 25 with these first-class node counts:

```text
dataflow               12
dataflow_node          629
dataflow_pin          2482
geometry_collection    29
```

No extra or missing specialist edge was accepted.

## Acceptance commands

The real-corpus publication sequence is:

```text
uatool systems-schema9-accept <project>
uatool derive <corpus>
uatool dataflow-chaos-graph-verify <project>
```

The acceptance command does not launch Unreal or derive. The verifier requires derived schema 25 and exact set equality against expectations generated from canonical schema-9 facts.

## Maintained capability status

After the accepted ContentExamples gate:

```text
dataflow            first_class
geometry_collection first_class
```

The capability contract remains corpus-aware. A corpus must actually contain the required schema-9 canonical streams to report `first_class` availability for that family; the tool-level contract alone does not manufacture corpus coverage.
