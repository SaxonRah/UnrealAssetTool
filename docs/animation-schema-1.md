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
animation_curves.jsonl
animation_curve_keys.jsonl
pose_search_interaction_assets.jsonl
pose_search_interaction_items.jsonl
pose_search_normalization_sets.jsonl
pose_search_normalization_databases.jsonl
mirror_data_tables.jsonl
mirror_data_table_rows.jsonl
animation_deep_manifest.json
animation_manifest.json
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

- float and transform curve identity through UE's animation data model
- every `FRichCurveKey`
- key time/value
- interpolation mode
- tangent mode and tangent-weight mode
- arrive/leave tangent values and tangent weights
- transform-component identity when transform curves exist

Non-finite numeric state is never written as an invalid JSON token. A non-finite field is stored as JSON `null` plus `<field>_non_finite` with `nan`, `+inf`, or `-inf`. The deep manifest counts these exceptional fields.

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

Unused backing `BlendParameters` slots are removed from the normalized schema output. This matters because UE stores three backing parameter structures even for lower-dimensional BlendSpaces.

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
- database animation entries and source assets
- Pose Search schema settings
- schema channels and concrete channel classes
- reflected channel settings/references
- schema role/Skeleton/MirrorDataTable entries
- PoseSearchInteractionAsset identity
- interaction roles, source animation, origin, preview mesh and warping weights
- PoseSearchNormalizationSet identity and database membership

### Mirror Data Tables

- table identity
- Skeleton
- mirror axis
- row names
- source/mirrored names
- entry type
- enabled state

### Chooser / Proxy / IK Rig

Chooser Tables, Proxy Tables, Proxy Assets, IK Rig definitions and IK Retargeters are recognized as animation-adjacent optional assets. Schema 1 preserves identity plus bounded reflected authored properties/references without hard module dependencies. ProxyAsset and ProxyTable are distinct normalized kinds.

Deep family-specific Chooser/IK normalization remains evidence-driven follow-up work rather than being guessed from display text.

## GASP validation — UE 5.8.2

The Game Animation Sample regression corpus has now completed the base and deep animation passes successfully.

Validated counts:

```text
animation_assets                         2518
animation_notifies                      13373
animation_sync_markers                     69
montage_sections                          137
animation_segments                        137
blend_space_axes                           26
blend_space_samples                        157
skeletons                                   11
skeleton_bones                            2866
skeleton_sockets                            58
pose_search_databases                      155
pose_search_database_assets               2138
pose_search_schemas                         33
pose_search_channels                        74
pose_search_schema_skeletons                37
animation_optional_assets                   31
animation_properties                    106033
animation_references                     46620
animation_curves                          7692
animation_curve_keys                    811357
animation_curve_non_finite_values           54
pose_search_interaction_assets              24
pose_search_interaction_items               48
pose_search_normalization_sets               4
pose_search_normalization_databases         117
mirror_data_tables                            1
mirror_data_table_rows                       88
```

Verified invariants:

- every one of the 155 Pose Search databases resolves to one of the 33 indexed schemas;
- database declared source counts exactly equal all 2,138 emitted database-source rows;
- all database source targets resolve: 2,080 AnimSequences, 34 AnimMontages, and 24 PoseSearchInteractionAssets;
- all 24 interaction assets are the exact interaction targets referenced by databases;
- all 48 interaction items resolve to indexed AnimMontages, with 24 Attacker and 24 Victim roles;
- all four normalization sets have exact emitted membership counts, and all 117 memberships resolve to indexed Pose Search databases;
- schema declared channel/role counts exactly equal the 74 channel rows and 37 role/Skeleton rows;
- all 37 role Skeleton references resolve;
- channel classes include Trajectory, Group, Position, Curve, Pose, Heading, and a Blueprint-defined custom channel;
- all 7,692 curve rows account exactly for all 811,357 curve-key rows;
- there are no duplicate curve-key primary identities;
- the 54 non-finite numeric fields occur in only 27 curve keys across five assets;
- none of those 54 values is a key time or authored curve value: 25 are arrive tangents, 25 leave tangents, two arrive tangent weights, and two leave tangent weights; all are NaNs;
- the single MirrorDataTable declares 88 rows, exactly 88 rows are emitted, all are enabled, and its Skeleton resolves;
- BlendSpace normalization produces 26 authored axes: three BlendSpace1D assets contribute one axis each, and one nominal `BlendSpace` is authored effectively one-dimensional with only `Horizontal` and all sample Y values equal to zero;
- structural schema 12, world schema 12, and derived schema 10 regression counts remain unchanged, including exactly 1,099 GASP world-system relations.

A provenance-ordering bug discovered during this validation caused the top-level `manifest.json` to copy the base animation counts before deep-output normalization. The canonical `animation_manifest.json` and JSONL were correct. The Python integration now normalizes/merges animation output when `read_manifest()` is called, so top-level animation provenance receives the final deep counts and normalized axis count before derivation/packing/bundling.

## Still not claimed complete

Animation schema 1 now has strong modern locomotion/Motion Matching coverage, but some adjacent systems remain intentionally partial:

- richer PoseAsset pose data
- dedicated Chooser row/column/result normalization
- dedicated Proxy Table entry/fallback normalization
- IK Rig chains/goals/solvers
- IK Retargeter chain mappings/settings
- Motion Warping authored settings where they materially affect project understanding
- SkeletalMesh / PhysicsAsset internals, which remain separate coverage families

## Validation order

1. **GASP:** complete for the current raw schema-1 feature set.
2. **Content Examples:** breadth validation for Sequence/Montage/BlendSpace/Skeleton/Chooser/IK and unusual asset combinations.
3. Fix any corpus-proven animation gaps before stabilizing schema 1.
4. Only after raw animation coverage is stable, add derived animation relations/context and connect them to later project-neighborhood traversal.
