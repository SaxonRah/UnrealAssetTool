# Animation schema 1

Animation schema 1 is the canonical authored-animation layer for UnrealAssetTool.

It is independently versioned from the structural, world, and derived layers:

```text
structural schema: 12
world schema:      12
animation schema:   1
derived schema:    10
```

`animation_schema_version`, `animation_counts`, and `animation_files` are copied into the top-level `manifest.json` after the animation passes have been normalized and merged.

## Pass model

Animation extraction is internally split so optional/plugin-heavy families remain build-safe:

```text
UnrealAssetToolAnimation
UnrealAssetToolAnimationDeep
UnrealAssetToolAnimationBreadth
UnrealAssetToolAnimationBreadthFinalize
```

The split is an implementation detail. All emitted rows below are public animation schema 1.

The scanner deliberately avoids hard dependencies on Pose Search, Chooser, ProxyTable, and IKRig where reflection can recover the authored data safely.

## Canonical streams

### Core animation

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
animation_optional_assets.jsonl
animation_properties.jsonl
animation_references.jsonl
```

### Curves / Pose Search / mirroring

```text
animation_curves.jsonl
animation_curve_keys.jsonl
pose_search_databases.jsonl
pose_search_database_assets.jsonl
pose_search_schemas.jsonl
pose_search_channels.jsonl
pose_search_schema_skeletons.jsonl
pose_search_interaction_assets.jsonl
pose_search_interaction_items.jsonl
pose_search_normalization_sets.jsonl
pose_search_normalization_databases.jsonl
mirror_data_tables.jsonl
mirror_data_table_rows.jsonl
```

### PoseAsset / Skeleton slots

```text
pose_assets.jsonl
pose_asset_tracks.jsonl
pose_asset_poses.jsonl
pose_asset_transforms.jsonl
pose_asset_curve_values.jsonl
skeleton_slot_groups.jsonl
skeleton_slots.jsonl
```

### Chooser / Proxy / IK

```text
chooser_tables.jsonl
chooser_columns.jsonl
chooser_results.jsonl
chooser_context.jsonl
proxy_tables.jsonl
proxy_entries.jsonl
proxy_table_inheritance.jsonl
ik_rigs.jsonl
ik_rig_bones.jsonl
ik_rig_chains.jsonl
ik_rig_goals.jsonl
ik_rig_solvers.jsonl
ik_retargeters.jsonl
ik_retarget_ops.jsonl
ik_retarget_poses.jsonl
animation_struct_references.jsonl
```

Companion provenance is retained in:

```text
animation_manifest.json
animation_deep_manifest.json
animation_breadth_manifest.json
```

## First-class facts

### AnimSequence / sequence-base

- asset identity/class/package
- Skeleton
- play length / rate / looping / additive state
- root-motion state for AnimSequence
- authored notifies and notify states
- notify timing, duration, track, branching-point and trigger settings
- authored sync markers
- bounded reflected authored properties and UObject references

### Animation curves

- float and transform curve identity through UE's animation data model
- every `FRichCurveKey`
- key time/value
- interpolation mode
- tangent mode and tangent-weight mode
- arrive/leave tangent values and tangent weights
- transform-component identity

Non-finite numeric state is serialized as JSON `null` with a companion non-finite marker; invalid JSON numeric tokens are never emitted.

### Montages

- sections and next-section links
- section start times
- slot tracks
- animation segments and source animations
- segment time/rate/loop settings
- authored montage sync markers

### Blend Spaces / Aim Offsets

- authored axes and ranges/grid settings
- samples and coordinates
- source animations
- rate/mirror/single-frame settings
- authored sync markers

Unused backing `BlendParameters` slots are filtered so lower-dimensional assets do not falsely claim three authored axes.

### Skeletons

- reference-bone hierarchy
- local reference transforms
- sockets and socket transforms
- virtual-bone count
- curve metadata names
- registered notify / sync-marker names
- authored slot groups and slots
- bounded reflected properties/references

### PoseAsset

- Skeleton and source animation
- additive/base-pose state
- track identities
- pose identities
- raw/full pose counts
- full per-track transforms for every pose
- raw and full per-curve values for every pose

### Pose Search / Motion Matching

- database identity/settings and database -> schema
- ordered database source entries
- schema identity/settings
- concrete feature channel classes/settings/references
- schema role -> Skeleton / MirrorDataTable entries
- multi-role PoseSearchInteractionAsset items, source animations, preview meshes, origins and warping weights
- PoseSearchNormalizationSet -> database membership

### Mirror Data Table

- table identity
- Skeleton
- mirror axis
- source/mirrored names
- entry type
- enabled state

### Chooser

- table identity and output type
- exact column/result/context counts
- disabled result-row state
- concrete InstancedStruct type for every column/result/context row
- bounded authored struct export
- object/class/asset references extracted from those structs

The current schema intentionally preserves uncommon per-column settings losslessly in `raw_value` rather than inventing family-specific semantics from display text.

### ProxyTable / ProxyAsset

- distinct ProxyTable and ProxyAsset identities
- ordered table entries
- entry -> ProxyAsset
- concrete value struct type and bounded authored value
- inherited table relationships when authored
- object/asset references from entry values

### IK Rig

- preview/skeleton mesh relationship
- root/pelvis retarget definition
- complete rig bone hierarchy and current global pose
- excluded bones
- retarget chains with start/end bone and optional IK goal
- IK goals and goal bones
- solver stack with concrete solver struct type and bounded authored settings

### IK Retargeter

- source and target IK Rig
- ordered retarget operation stack and concrete op types
- source and target named retarget poses
- bounded authored operation/pose values
- object/IK Rig references contained by operation structs

## UE 5.8 breadth-shape fixes

Content Examples exposed several cases where generic reflection had the correct data but the first breadth pass assumed the wrong container shape. Schema 1 now handles the actual UE 5.8 layout:

- PoseAsset curve rows preserve distinct raw/full values;
- Proxy inheritance is `InheritEntriesFrom`;
- IK chains are `RetargetDefinition.BoneChains`;
- IK goals are UObject rows;
- source/target retarget poses are TMaps.

The breadth-finalization pass corrects those shapes without introducing hard Chooser/Proxy/IKRig module dependencies.

## GASP validation — UE 5.8.2

Game Animation Sample passed the Motion Matching/deep-animation gate.

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

Validated invariants include exact database/schema/source/channel/role counts, complete interaction and normalization-set resolution, exact curve/key accounting, no duplicate curve-key identities, and complete MirrorDataTable row accounting.

## Content Examples validation — UE 5.8.2

Content Examples passed the animation breadth gate.

```text
animation_assets                           294
animation_notifies                          84
animation_sync_markers                     162
montage_sections                              9
animation_segments                           10
blend_space_axes                              8
blend_space_samples                          40
skeletons                                    30
skeleton_bones                             2609
skeleton_sockets                             51
pose_assets                                  38
pose_asset_tracks                          5406
pose_asset_poses                            351
pose_asset_transforms                     41710
pose_asset_curve_values                   78039
skeleton_slot_groups                         10
skeleton_slots                               33
chooser_tables                               23
chooser_columns                              32
chooser_results                              78
chooser_context                              27
proxy_tables                                  9
proxy_entries                                16
proxy_table_inheritance                       0
ik_rigs                                      19
ik_rig_bones                               1025
ik_rig_chains                                79
ik_rig_goals                                 75
ik_rig_solvers                               21
ik_retargeters                                9
ik_retarget_ops                              68
ik_retarget_poses                            23
animation_struct_references                 278
animation_curves                           1349
animation_curve_keys                      66212
mirror_data_tables                            1
mirror_data_table_rows                      159
```

Verified:

- every PoseAsset declared track/pose count matches emitted rows;
- every pose's full transform/curve count matches emitted detail rows and all full poses match track counts;
- every Chooser declared column/result/context/disabled count matches emitted rows;
- every Proxy declared entry/inheritance count matches emitted rows;
- every IK Rig declared bone/chain/goal/solver count matches emitted rows;
- all chain start/end bones, named chain goals and goal bones resolve inside their rig;
- all Retargeter source/target rigs resolve and op/source-pose/target-pose counts match;
- all Proxy entry ProxyAssets resolve;
- no breadth rows are truncated;
- all 136 JSONL files in the bundle parse successfully;
- top-level `manifest.json` animation counts exactly match the normalized `animation_manifest.json` counts.

## Schema-1 status

Raw animation schema 1 validation is complete for the current GASP + Content Examples corpus gate.

Further family-specific semantic promotion remains evidence-driven, but it is no longer a blocker for schema 1. In particular, unusual Chooser columns, IK solver settings, and Retarget op settings remain preserved losslessly as concrete struct type + authored raw value + extracted references.

The next feature collection is **derived animation relations/context**, followed by project-neighborhood traversal integration. Niagara + legacy Cascade remains the next major raw subsystem coverage pass.
