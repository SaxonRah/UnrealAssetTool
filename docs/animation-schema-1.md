# Animation schema 1 — development scope

This document tracks the first raw animation-asset extraction layer while it is under validation.

## Versioning

Animation is versioned independently from the existing structural/world/derived layers:

```text
structural schema: 12
world schema:      12
animation schema:   1
derived schema:    10
```

`animation_schema_version` and `animation_counts` are copied into the main `manifest.json` after a successful scan. `animation_manifest.json` remains the canonical animation-pass manifest. A bounded companion pass writes `animation_deep_manifest.json`; the Python integration validates it and folds its counts/file list into animation schema 1 before database packing/bundling. The companion pass is an implementation split, not a second public schema.

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
animation_curves.jsonl
animation_curve_keys.jsonl
pose_search_interaction_assets.jsonl
pose_search_interaction_items.jsonl
pose_search_normalization_sets.jsonl
pose_search_normalization_databases.jsonl
mirror_data_tables.jsonl
mirror_data_table_rows.jsonl
animation_manifest.json
animation_deep_manifest.json
```

## First-class facts

### Animation sequences and sequence-base assets

- asset identity/class/package
- Skeleton
- play length/additive state
- authored notifies and notify states
- notify timing, duration, track, branching-point state and trigger settings
- authored sync markers
- root-motion flag for `UAnimSequence`
- bounded reflected authored properties and UObject references

### Animation curves

The companion pass reads the UE animation data model rather than only Skeleton curve metadata:

- float-curve identity/type flags
- transform-curve identity/type flags
- every `FRichCurveKey`
- key time/value
- interpolation mode
- tangent mode and tangent-weight mode
- arrive/leave tangent values and weights
- transform component identity (`translation_x/y/z`, `rotation_x/y/z`, `scale_x/y/z`)

This is required for systems such as Pose Search Curve channels where the actual authored curve values matter.

### Montages

In addition to the sequence-base facts:

- sections and next-section links
- section start times
- slots
- animation segments used by each slot
- segment source animation, time range, rate and loop count
- authored montage sync markers

### Blend Spaces / Aim Offsets

- authored axes and ranges/grid settings
- samples and sample coordinates
- source animations
- rate/mirror/single-frame settings
- authored sync markers

The post-pass normalization removes unused backing `BlendParameters` slots so a 1D/2D asset does not falsely appear to author three axes.

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

Pose Search remains an optional engine plugin, so the scanner deliberately does not add a hard `PoseSearch` module dependency. When the plugin is enabled and its assets can load, Unreal reflection preserves:

- Pose Search database identity
- database Schema/preview/search-mode/tags
- database animation entries and their source assets
- Pose Search schema settings
- schema channels and concrete channel classes
- reflected channel settings/references
- schema role/Skeleton/MirrorDataTable entries
- Pose Search Interaction Asset identity
- interaction items, roles, source animations, preview meshes, origins, and warping weights
- Pose Search Normalization Set identity
- normalization-set -> database membership

This lets projects without Pose Search continue to build UnrealAssetTool while giving Motion Matching projects first-class raw data.

### Mirror Data Tables

Schema 1 records the animation mirroring data that affects bones, curves, notifies and sync markers:

- table identity/package
- Skeleton
- mirror axis
- row identity
- source and mirrored names
- mirror entry type
- enabled state

### Chooser / Proxy / IK Rig

Chooser Tables, Proxy Tables, Proxy Assets, IK Rig definitions and IK Retargeters are recognized as animation-adjacent optional assets. Schema 1 preserves their identity plus bounded reflected properties/references without hard module dependencies. `ProxyAsset` and `ProxyTable` are kept as distinct asset kinds.

## GASP validation — first pass

The first UE 5.8.2 Game Animation Sample run compiled and completed successfully. Before the companion follow-up, it produced:

```text
animation_assets                 2518
animation_notifies              13373
animation_sync_markers             69
montage_sections                  137
animation_segments                137
blend_space_axes                   45   # pre-normalization backing slots
blend_space_samples                157
skeletons                           11
skeleton_bones                    2866
skeleton_sockets                    58
pose_search_databases              155
pose_search_database_assets       2138
pose_search_schemas                 33
pose_search_channels                74
pose_search_schema_skeletons        37
animation_optional_assets           31
animation_properties            106033
animation_references             46620
```

Important invariants from that corpus:

- all 155 Pose Search databases resolved to one of the 33 scanned schemas
- database declared-entry counts summed exactly to the 2,138 emitted rows
- schema channel counts summed exactly to the 74 emitted channel rows
- schema role/Skeleton counts summed exactly to the 37 emitted role rows
- all 37 referenced Skeletons resolved to indexed Skeleton rows
- channel coverage included Trajectory, Group, Position, Curve, Pose, Heading, and a Blueprint-defined custom feature channel
- structural schema 12, world schema 12, derived schema 10, and the existing 1,099 GASP world-system relations remained stable

That run also exposed the gaps now addressed by the companion pass: 24 `PoseSearchInteractionAsset` database entries, four normalization sets, actual animation curve keys, the project Mirror Data Table, unused BlendSpace backing axes, and `ProxyAsset`/`ProxyTable` disambiguation.

## Not yet claimed complete

Animation schema 1 still intentionally does **not** claim exhaustive coverage. Important remaining depth includes:

- richer Pose Asset pose internals
- richer Chooser/Proxy row/column semantics
- IK Rig/Retarget chain-specific normalization
- Motion Warping assets/settings where useful
- animation modifiers and metadata where they materially affect runtime behavior
- evidence-driven support for additional animation/plugin asset families found by broader corpora

## Validation order

1. **Passed:** UE 5.8.2 compile and first full GASP animation scan.
2. **Current:** compile and rerun GASP with curves, interactions, normalization sets, Mirror Data Table, and post-pass normalization enabled.
3. Verify Motion Matching traversal: database -> schema -> channel -> animation / interaction -> curve / mirror facts.
4. Run Content Examples for broad Sequence/Montage/BlendSpace/Skeleton/Chooser/IK coverage.
5. Only after the raw pass is stable, add derived animation relations/context and connect them to `world_system_relations` and project-neighborhood traversal.
