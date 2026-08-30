# Animation schema 1 — development scope

This document tracks the first raw animation-asset extraction pass while it is under validation.

## Versioning

Animation is versioned independently from the existing structural/world/derived layers:

```text
structural schema: 12
world schema:      12
animation schema:   1
derived schema:    10
```

`animation_schema_version` and `animation_counts` are copied into the main `manifest.json` after a successful scan, while `animation_manifest.json` remains the raw pass manifest.

## Canonical streams

Animation schema 1 writes:

```text
animation_assets.jsonl
animation_notifies.jsonl
animation_sync_markers.jsonl
montage_sections.jsonl
animation_segments.jsonl
blend_space_axes.jsonl
blend_space_samples.jsonl
skeletons.jsonl
skeleton_bones.jsonl
skeleton_sockets.jsonl
pose_search_databases.jsonl
pose_search_database_assets.jsonl
pose_search_schemas.jsonl
pose_search_channels.jsonl
pose_search_schema_skeletons.jsonl
animation_optional_assets.jsonl
animation_properties.jsonl
animation_references.jsonl
animation_manifest.json
```

## First-class facts in the first pass

### Animation sequences and sequence-base assets

- asset identity/class/package
- Skeleton
- play length/additive state
- authored notifies and notify states
- notify timing, duration, track, branching-point state and trigger settings
- authored sync markers
- root-motion flag for `UAnimSequence`
- bounded reflected authored properties and UObject references

### Montages

In addition to the sequence-base facts:

- sections and next-section links
- section start times
- slots
- animation segments used by each slot
- segment source animation, time range, rate and loop count
- authored montage sync markers

### Blend Spaces / Aim Offsets

- axes and ranges/grid settings
- samples and sample coordinates
- source animations
- rate/mirror/single-frame settings
- authored sync markers

### Skeletons

- reference-bone hierarchy
- local reference transforms
- sockets and socket transforms
- virtual-bone count
- curve metadata names
- registered animation-notify names
- registered sync-marker names
- reflected authored properties/references

### Pose Search / Motion Matching

Pose Search remains an optional engine plugin, so the scanner deliberately does not add a hard `PoseSearch` module dependency. When the plugin is enabled and its assets can load, Unreal reflection is used to preserve:

- Pose Search database identity
- database Schema/preview/search-mode/tags
- database animation entries and their source animation assets
- Pose Search schema settings
- schema channels and concrete channel classes
- reflected channel settings/references
- schema role/Skeleton/MirrorDataTable entries

This lets projects without Pose Search continue to build UnrealAssetTool while still giving Motion Matching projects first-class raw data.

### Chooser / Proxy Table / IK Rig

Chooser Tables, Proxy Tables, IK Rig definitions and IK Retargeters are recognized as animation-adjacent optional assets. Schema 1 preserves their identity plus bounded reflected properties/references without hard module dependencies. Deep family-specific normalization is intentionally deferred until corpus evidence shows what is needed.

## Not yet claimed complete

The first pass intentionally does **not** claim complete animation coverage. Important follow-up areas include:

- animation float/transform curve keys
- richer Pose Asset pose data
- richer Chooser/Proxy table row/column semantics
- IK Rig/Retarget chain-specific normalization
- Motion Warping assets/settings where useful
- animation modifiers and metadata where they materially affect gameplay

The GASP and Content Examples validation runs determine which of these become part of animation schema 1 before it is considered stable versus a later schema revision.

## Validation order

1. UE 5.8.2 compile in Game Animation Sample.
2. Full GASP scan; verify Pose Search database/schema/channel data and animation references.
3. Inspect Motion Matching database -> schema -> channel -> animation traversal.
4. Content Examples scan for broad Sequence/Montage/BlendSpace/Skeleton/Chooser/IK coverage.
5. Only after the raw pass is stable, add derived animation relations/context and connect them to `world_system_relations` / later project-neighborhood traversal.
