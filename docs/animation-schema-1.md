# Animation schema 1

Animation schema 1 is UnrealAssetTool's canonical authored-animation layer.

Current project baseline:

```text
structural schema: 12
world schema:      12
animation schema:   1
vfx schema:         1
systems schema:     4
derived schema:    20
```

It is implemented by several internal passes so optional/plugin-heavy families remain build-safe, but they form one public schema:

```text
UnrealAssetToolAnimation
UnrealAssetToolAnimationDeep
UnrealAssetToolAnimationBreadth
UnrealAssetToolAnimationBreadthFinalize
```

The scanner avoids hard dependencies on Pose Search, Chooser, ProxyTable and IKRig where reflection can recover authored data safely.

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

Internal pass provenance is retained in:

```text
animation_manifest.json
animation_deep_manifest.json
animation_breadth_manifest.json
```

## First-class facts

### AnimSequence / sequence-base

- asset identity/class/package;
- Skeleton and play length;
- additive/root-motion state where applicable;
- authored notifies and notify states;
- notify timing/duration/track/branching settings;
- authored sync markers;
- bounded reflected authored properties/references.

### Curves

Float and transform curves are read through Unreal's animation data model. Every `FRichCurveKey` retains time/value, interpolation, tangent mode, tangent-weight mode and tangent values/weights. Transform curves retain translation/rotation/scale component identity.

Non-finite numeric state is serialized safely rather than emitting invalid JSON numeric tokens.

### Montages

- sections and next-section links;
- section start times;
- slot tracks;
- animation segments/source assets;
- segment timing/rate/loop settings;
- sync markers.

### BlendSpace / BlendSpace1D / AimOffset

- authored axes/ranges/grid settings;
- samples and coordinates;
- source animations;
- rate/mirror/single-frame settings;
- sync markers.

Unused backing `BlendParameters` slots are filtered so lower-dimensional assets do not falsely claim three authored axes.

### Skeleton

- reference-bone hierarchy/local transforms;
- sockets/socket transforms;
- virtual-bone count;
- curve/notify/sync-marker metadata;
- authored slot groups/slots;
- bounded reflected properties/references.

### PoseAsset

- Skeleton/source animation;
- additive/base-pose state;
- track and pose identities;
- complete full-pose transforms;
- raw/full per-curve pose values.

### Pose Search / Motion Matching

- database -> schema;
- ordered database source entries;
- schema settings;
- concrete feature channel classes/settings/references;
- role -> Skeleton/MirrorDataTable;
- multi-role interaction items/source animations/preview meshes/origins/warping weights;
- NormalizationSet -> database membership.

### Mirror Data Table

Skeleton, mirror axis and source/mirrored row mappings are normalized with entry type and enabled state.

### Chooser

- table identity/output type;
- exact column/result/context counts;
- disabled result rows;
- concrete InstancedStruct types;
- bounded authored raw struct values;
- object/class/asset references extracted from those structs.

Uncommon column semantics are preserved losslessly rather than guessed from display text.

Derived schema 20 additionally persists a conservative generic decision layer for supported enum columns:

```text
chooser_decisions.jsonl
chooser_decision_predicates.jsonl
```

That layer keeps raw structs and refuses ambiguous/cardinality-mismatched interpretations. Chooser decision schema 1 is independently versioned from animation schema 1.

### ProxyTable / ProxyAsset

- distinct identities;
- ordered entries;
- entry -> ProxyAsset;
- concrete value struct/raw value;
- inherited table relationships;
- references from entry values.

### IK Rig

- preview/skeleton mesh relationships;
- retarget root/pelvis;
- complete rig bone hierarchy and excluded bones;
- chains/start/end/goal names;
- goals and goal bones;
- ordered solver stack with concrete solver type/raw settings.

### IK Retargeter

- source/target IK Rig;
- ordered retarget operations;
- source/target named retarget poses;
- concrete operation types/raw values;
- object/IK references contained by operation structs.

## Derived animation layer

The current final derived schema is 20. The animation-specific derived streams introduced earlier remain:

```text
animation_relations.jsonl
animation_context.jsonl
animation_summaries.jsonl
```

Relationships are built only from canonical authored facts. Display names are not used to infer asset identity and generic package dependencies are not promoted into semantic animation edges.

Animation roots are also integrated into `project_nodes.jsonl`, `project_edges.jsonl` and bounded project neighborhoods with explicit coverage and edge quality.

## Validation

### GASP — UE 5.8.2

The current Motion Matching/deep-animation gate includes:

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
animation_curves                          7692
animation_curve_keys                    811357
pose_search_interaction_assets              24
pose_search_interaction_items               48
pose_search_normalization_sets               4
pose_search_normalization_databases         117
mirror_data_tables                            1
mirror_data_table_rows                       88
```

Validated invariants include exact database/schema/source/channel/role counts, interaction and normalization resolution, exact curve/key accounting, no duplicate curve-key identities and complete Mirror Data Table row accounting.

### Content Examples — UE 5.8.2

The breadth gate includes:

```text
animation_assets                           294
pose_assets                                  38
pose_asset_tracks                          5406
pose_asset_poses                            351
pose_asset_transforms                     41710
pose_asset_curve_values                   78039
chooser_tables                               23
chooser_columns                              32
chooser_results                              78
chooser_context                              27
proxy_tables                                  9
proxy_entries                                16
ik_rigs                                      19
ik_rig_bones                               1025
ik_rig_chains                                79
ik_rig_goals                                 75
ik_rig_solvers                               21
ik_retargeters                                9
ik_retarget_ops                              68
ik_retarget_poses                            23
animation_struct_references                 278
```

Validated invariants include exact declared/detail counts, complete IK chain/goal bone resolution, Retargeter source/target rig resolution, ProxyAsset target resolution and zero breadth-row truncation.

## Current depth gaps

Animation schema 1 is stable, but not every UE animation-adjacent family has dedicated semantics. Important remaining depth includes:

- Motion Warping configuration/assets beyond incidental Blueprint/world references;
- AnimNext assets/graphs;
- SkeletalMesh/PhysicsAsset internals that affect animation/retarget context;
- more typed interpretation of uncommon Chooser columns, IK solver settings and Retarget operations where corpus evidence justifies it.

The existing raw struct/property/reference fallback keeps unusual authored data available until it is promoted to dedicated normalized fields.
