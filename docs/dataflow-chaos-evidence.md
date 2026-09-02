# Dataflow / Geometry Collection / Chaos evidence diagnostic

Issue #14 requires this slice to begin from representative UE 5.8 authored content rather than from API/header names. `dataflow-chaos-evidence` is the read-only entry gate.

It does **not** define systems schema 9, does not change the corpus, does not launch Unreal, and does not promote any semantic graph relations.

## Why ContentExamples is the first target

Epic's UE 5.8 Content Examples project includes a Chaos Destruction example map, and Epic's current destruction/Dataflow quickstarts use Chaos assets from Content Examples. That makes the existing ContentExamples corpus a strong first candidate for authored destruction evidence without introducing a new sample project.

This is only corpus selection evidence. The public schema must still be based on actual serialized/reflected rows recovered from the local project.

## UE 5.8 concepts used only as search anchors

Current UE 5.8 API/documentation establishes several useful identities for finding authored evidence:

- `UDataflow` is the UObject/UEdGraph wrapper for the Dataflow graph substrate.
- `UGeometryCollection` is the authored Geometry Collection asset wrapper and implements Dataflow content/instance interfaces.
- Geometry Collections expose authored fields including Dataflow ownership/terminal state and destruction defaults.
- `UGeometryCollectionComponent` exposes `RestCollection` plus authored damage/destruction settings.
- Chaos destruction uses Geometry Collections as its authored base content; generated/live solver state is a different boundary.

These names are diagnostic anchors, not schema commitments.

## Command

```powershell
python scripts\uatool.py dataflow-chaos-evidence `
    "E:\TheDigitalGame\ue\ContentExamples\.uatool" `
    --report "E:\TheDigitalGame\ue\ContentExamples\.uatool\ContentExamples.dataflow-chaos-evidence.txt"
```

The command only reads existing JSON/JSONL.

Optional focused runs:

```text
--focus dataflow_graph
--focus geometry_collection
--focus destruction_component
--focus chaos_support
--focus usage
```

`--no-source` skips `source_chunks.jsonl` when only authored asset/state evidence is wanted.

## Proof counters

The diagnostic reports exact/generic evidence separately, including:

```text
unique_dataflow_assets
unique_geometry_collection_assets
unique_geometry_collection_cache_assets
unique_chaos_cache_collection_assets
unique_field_system_assets
unique_placed_geometry_collection_components
unique_blueprint_geometry_collection_components
dataflow_asset_link_owners
dataflow_terminal_owners
rest_collection_link_owners
damage_authoring_owners
exact_reference_rows
usage_rows
```

Asset identity is counted only from `assets.jsonl`. Placed component identity is counted only from `world_components.jsonl`. Other rows provide anchored authored state or usage evidence but are not silently upgraded into asset/component existence.

## Streams inspected

The diagnostic searches existing authoritative/derived layers only:

- Asset Registry assets/dependencies;
- Blueprint component/state/node/reference/semantic rows;
- world actors/components/instance properties/references;
- current systems generic state/references;
- project graph rows;
- project source chunks unless disabled.

There is intentionally no new native extractor in this PR.

## Expected decision after the corpus sweep

A useful representative result should prove at least a nontrivial Geometry Collection population and preferably authored `UDataflow` assets plus collection-to-Dataflow and component-to-RestCollection relationships.

If Dataflow assets are present, their asset identity alone is **not** enough to design a graph schema. The current tool has no dedicated UDataflow node/pin/edge extractor, so a focused UE reflection/native graph capture is still required.

Likewise, Geometry Collection asset identity alone is insufficient to normalize fracture/destruction semantics. The focused capture must establish which authored/default fields, nested objects/collections, Dataflow links, hierarchy/group counts, and component references are stable and query-worthy in UE 5.8.2.

## Boundary

Potential future first-class scope is authored content only:

- Dataflow graph topology and stable authored node/pin/connection state;
- Geometry Collection identity and stable destruction/default settings;
- exact Geometry Collection -> Dataflow ownership/reference relationships;
- exact GeometryCollectionComponent -> RestCollection relationships;
- selected authored Chaos destruction support objects where representative evidence proves them.

Explicit nonclaims:

- live Chaos solver particles/islands;
- runtime break/collision/removal event history;
- current dynamic collection transforms;
- generated physics proxies/caches that are not authored assets;
- runtime Dataflow evaluation results;
- simulation playback state;
- all Chaos subsystems merely because they share the Chaos name.

The initial slice is destruction authoring plus the reusable Dataflow graph substrate. Cloth, Flesh, Vehicles, Hair and other Dataflow/Chaos consumers should be added only when their own authored corpus evidence justifies reusable extensions.
