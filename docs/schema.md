# UnrealAssetTool schema reference

## Current versions

UnrealAssetTool 0.7.0 uses independently versioned canonical layers plus one final derived layer:

```text
structural scanner schema: 12
world scanner schema:      12
animation scanner schema:   1
VFX scanner schema:         1
systems scanner schema:     4
derived schema:            20
```

Additional independently versioned semantic/canonical companions currently include:

```text
Blueprint user-defined enum schema: 1
Chooser decision schema:            1
Gameplay Camera behavior schema:    2
```

The version numbers intentionally describe different facts and lifecycles.

- `manifest.json` -> structural `schema_version` and final `derived_schema_version`
- `world_manifest.json` -> world `schema_version`
- `animation_manifest.json` -> animation `schema_version`
- `vfx_manifest.json` -> VFX `schema_version`
- `systems_manifest.json` -> systems `schema_version`
- `blueprint_enum_manifest.json` -> Blueprint enum companion `schema_version`

A canonical scanner change normally requires Unreal to run again. A compatible derived-only change normally requires only `derive`, `pack` and `bundle`.

Historical schema-specific documents record the contracts they introduced. The current systems contract is [systems-schema-4.md](systems-schema-4.md); [systems-schema-1.md](systems-schema-1.md) and [systems-schema-2.md](systems-schema-2.md) are retained as historical contracts.

## Storage rules

Canonical and derived streams use JSON Lines: one JSON object per physical line. This keeps writes streaming, supports partial reads/diffs and lets SQLite be rebuilt without treating the database as truth.

When parsing JSONL, split on physical `\n` records. Do not use Unicode `str.splitlines()` because serialized Unreal text can contain control characters that Python treats as additional line separators.

`uat.db` is a regenerable retrieval cache.

---

# Structural scanner schema 12

Structural extraction is emitted by the main Unreal commandlet.

## Project/files

```text
files.jsonl
source_chunks.jsonl
```

`files.jsonl` records indexed physical files and metadata. `source_chunks.jsonl` stores bounded text chunks for supported source/config/document files.

## Asset Registry

```text
assets.jsonl
asset_dependencies.jsonl
```

`assets.jsonl` is the universal fallback layer: asset identity, class, package, tags and disk/path facts. `asset_dependencies.jsonl` stores normalized package dependencies.

Asset Registry presence does not imply first-class understanding of an asset's internals.

## Blueprint / K2 / UMG canonical streams

```text
blueprints.jsonl
blueprint_graphs.jsonl
blueprint_nodes.jsonl
blueprint_pins.jsonl
blueprint_edges.jsonl
blueprint_interfaces.jsonl
blueprint_node_properties.jsonl
blueprint_node_references.jsonl
blueprint_bindings.jsonl
blueprint_defaults.jsonl
blueprint_component_properties.jsonl
blueprint_state_values.jsonl
blueprint_timelines.jsonl
blueprint_timeline_tracks.jsonl
blueprint_timeline_keys.jsonl
blueprint_widgets.jsonl
blueprint_widget_properties.jsonl
blueprint_widget_bindings.jsonl
blueprint_widget_animations.jsonl
blueprint_widget_animation_bindings.jsonl
```

These preserve Blueprint identity/inheritance/interfaces/state, every graph/node/pin, exact graph wiring, reflected node state/references, component/default state, Timelines and UMG authored structure.

## Blueprint user-defined enums

The world process also runs a small canonical companion scanner for project-owned user-defined enums:

```text
blueprint_enum_manifest.json
blueprint_enums.jsonl
blueprint_enum_entries.jsonl
```

It preserves enum identity plus raw, authored and display names. Readable enum decoration is derived conservatively from actual pin/enum typing; ambiguous values stay raw.

## Compact Control Rig / RigVM

```text
rigvm_objects.jsonl
rigvm_pins.jsonl
rigvm_links.jsonl
rigvm_references.jsonl
```

The much larger reflection stream:

```text
rigvm_properties.jsonl
```

is opt-in with `--include-raw-rigvm-properties`.

## AI

```text
behavior_trees.jsonl
behavior_tree_nodes.jsonl
behavior_tree_edges.jsonl
blackboards.jsonl
blackboard_keys.jsonl
eqs_queries.jsonl
eqs_options.jsonl
eqs_generators.jsonl
eqs_tests.jsonl
statetrees.jsonl
statetree_states.jsonl
statetree_nodes.jsonl
statetree_transitions.jsonl
statetree_bindings.jsonl
ai_properties.jsonl
```

## PCG

```text
pcg_graphs.jsonl
pcg_nodes.jsonl
pcg_pins.jsonl
pcg_edges.jsonl
pcg_properties.jsonl
```

## Materials

```text
materials.jsonl
material_expressions.jsonl
material_edges.jsonl
material_properties.jsonl
```

Material/MaterialInstance/MaterialFunction identity, expression objects, exact root/expression input topology, properties, parameters and object references are preserved. Generated `UMaterialExpression::MaterialExpressionGuid` values are removed by canonical cleanup because they are generated node identifiers rather than stable authored state.

---

# World scanner schema 12

```text
world_manifest.json
worlds.jsonl
world_levels.jsonl
world_actors.jsonl
world_components.jsonl
world_instance_properties.jsonl
world_references.jsonl
world_data_layers.jsonl
world_partition_actor_descs.jsonl
```

### `worlds.jsonl`

World identity/package/persistent-level facts plus World Partition presence.

### `world_levels.jsonl`

Persistent-level rows and classic streaming relationships.

### `world_actors.jsonl`

Loaded actors with identity/class/GUID/label, tags/folders, transforms, ownership/attachments, Blueprint identity and Data Layer membership.

### `world_components.jsonl`

Actor component identity/class/archetype, creation method, attachment/socket state and transforms.

### `world_instance_properties.jsonl`

Authored placed-instance differences from the exact archetype, excluding transient/deprecated/non-instance state.

### `world_references.jsonl`

Bounded hard/soft object references discovered from actor/component properties, including the exact property path and whether the value is an authored override.

### `world_data_layers.jsonl`

Data Layer identity/hierarchy/runtime/editor state and DataLayerAsset association.

### `world_partition_actor_descs.jsonl`

World Partition descriptor facts without loading every external actor: GUID/package/soft path/native class, parent/reference GUIDs, transform/bounds and Data Layer membership.

---

# Animation scanner schema 1

Animation schema 1 is one public schema implemented by base, deep and breadth passes. Internal companion manifests are implementation provenance, not separate public schemas.

## Base/deep streams

```text
animation_manifest.json
animation_deep_manifest.json
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
```

These cover shared animation asset identity/settings, notifies/states, sync markers, Montage sections/segments, BlendSpace axes/samples, Skeleton hierarchy/sockets, curves and keys, Pose Search databases/schemas/channels/roles/interactions/normalization and mirror mappings.

## Breadth streams

```text
animation_breadth_manifest.json
pose_assets.jsonl
pose_asset_tracks.jsonl
pose_asset_poses.jsonl
pose_asset_transforms.jsonl
pose_asset_curve_values.jsonl
skeleton_slot_groups.jsonl
skeleton_slots.jsonl
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

These promote PoseAsset pose-level data, Skeleton slots, Chooser tables, Proxy tables, IK Rig and IK Retargeter internals beyond generic reflection.

See [animation-schema-1.md](animation-schema-1.md) for domain-specific details.

---

# VFX scanner schema 1

```text
vfx_manifest.json
vfx_assets.jsonl
vfx_properties.jsonl
vfx_references.jsonl
niagara_systems.jsonl
niagara_system_emitters.jsonl
niagara_emitters.jsonl
niagara_emitter_versions.jsonl
niagara_renderers.jsonl
niagara_simulation_stages.jsonl
niagara_stateless_emitters.jsonl
niagara_stateless_modules.jsonl
niagara_stateless_renderers.jsonl
niagara_scripts.jsonl
niagara_data_channels.jsonl
niagara_data_channel_variables.jsonl
niagara_parameter_collections.jsonl
niagara_parameter_collection_parameters.jsonl
niagara_effect_types.jsonl
cascade_systems.jsonl
cascade_emitters.jsonl
cascade_lods.jsonl
cascade_modules.jsonl
```

VFX schema 1 preserves Niagara System/emitter composition, versioned emitter state, renderer/simulation-stage objects, stateless modules/renderers, scripts, Data Channels, Parameter Collections, Effect Types and legacy Cascade topology. `vfx_properties.jsonl` / `vfx_references.jsonl` provide bounded reflection-backed authored state around those normalized rows.

See [vfx-schema-1.md](vfx-schema-1.md).

---

# Systems scanner schema 4

Systems schema 4 is the current canonical gameplay-systems contract. It retains the original reflection-first systems streams, adds schema-2 gameplay-data/Gameplay Tags normalization, then adds reflection-backed Mover and Gameplay Cameras topology.

## Base systems streams

```text
systems_manifest.json
systems_assets.jsonl
systems_properties.jsonl
systems_references.jsonl
level_sequences.jsonl
movie_scene_bindings.jsonl
movie_scene_tracks.jsonl
movie_scene_sections.jsonl
movie_scene_channels.jsonl
audio_assets.jsonl
sound_cue_nodes.jsonl
metasound_nodes.jsonl
metasound_edges.jsonl
input_actions.jsonl
input_mapping_contexts.jsonl
input_mappings.jsonl
input_processors.jsonl
gameplay_data_assets.jsonl
gameplay_tags.jsonl
```

### Sequencer

`level_sequences.jsonl` summarizes sequence/MovieScene state. Binding, track, section and channel streams preserve normalized containment and channel/key counts while `systems_properties`/`systems_references` preserve reflected authored state and exact references.

### Audio / MetaSound

`audio_assets.jsonl` normalizes core audio identities/settings. SoundCue nodes are normalized separately. MetaSound frontend document nodes and edges are captured with stable frontend IDs and exact endpoints.

### Enhanced Input

`input_actions.jsonl` preserves action type/settings and declared processor counts. Mapping contexts/mappings normalize key/action relationships. `input_processors.jsonl` records action- and mapping-level trigger/modifier objects.

## Schema-2 gameplay data / Gameplay Tags streams

```text
data_table_rows.jsonl
data_table_fields.jsonl
curve_tables.jsonl
curve_table_rows.jsonl
curve_table_keys.jsonl
primary_data_assets.jsonl
gameplay_tag_settings.jsonl
gameplay_tag_sources.jsonl
gameplay_tag_dictionary.jsonl
gameplay_tag_redirects.jsonl
```

General DataTables preserve row struct/type, physical rows/fields and exact normalized object references without guessing project-specific field semantics. CurveTables preserve rows/keys. PrimaryDataAsset has first-class identity while arbitrary project-specific payload meaning remains reflected/raw.

Gameplay Tags preserve project settings, configured sources, the merged dictionary and redirects. Native C++ registration provenance/restricted-tag special cases are not claimed to be exhaustive.

## Mover streams

```text
mover_blueprints.jsonl
mover_components.jsonl
mover_modes.jsonl
mover_settings.jsonl
mover_transitions.jsonl
```

These preserve Mover Blueprint/component identity, authored defaults, movement modes and starting mode, shared settings/required setting classes, transitions and exact referenced backend classes. Extraction is reflection-backed and does not require a hard Mover module dependency.

## Gameplay Cameras streams

```text
gameplay_camera_assets.jsonl
gameplay_camera_rigs.jsonl
gameplay_camera_nodes.jsonl
gameplay_camera_node_edges.jsonl
gameplay_camera_transitions.jsonl
gameplay_camera_directors.jsonl
gameplay_camera_rig_references.jsonl
```

These preserve CameraAsset/director identity, CameraRig root/node topology, exact reflected node-to-node edges, transitions and rig-to-rig/prefab references. A direct director-to-rig reference is not invented when authored behavior selects rigs through a Chooser table.

See [systems-schema-4.md](systems-schema-4.md) for accepted GASP corpus counts and behavior boundaries.

---

# Derived schema 20

Everything in this section is deterministic Python output and may be regenerated from compatible canonical data.

```powershell
python scripts\uatool.py derive <Project>\.uatool
```

A validated `.derived_freshness.json` allows subsequent `derive`, `pack` and `bundle` calls to reuse current output when canonical facts and derived implementation have not changed.

## Blueprint program reconstruction

```text
blueprint_functions.jsonl
blueprint_events.jsonl
blueprint_call_edges.jsonl
blueprint_call_bindings.jsonl
blueprint_data_dependencies.jsonl
blueprint_execution_blocks.jsonl
blueprint_execution_block_edges.jsonl
blueprint_execution_roots.jsonl
anim_state_machines.jsonl
anim_states.jsonl
anim_transitions.jsonl
blueprint_relations.jsonl
blueprint_graph_context.jsonl
blueprint_summaries.jsonl
rigvm_editor_links.jsonl
```

## Generic Blueprint semantic layer

```text
blueprint_semantic_nodes.jsonl
blueprint_semantic_edges.jsonl
blueprint_semantic_graphs.jsonl
blueprint_semantic_statements.jsonl
blueprint_semantic_blocks.jsonl
blueprint_control_edges.jsonl
```

The semantic layer normalizes generic operations/control flow while preserving raw node/pin facts. User-defined enum names are decorated only when actual typing resolves them conservatively.

## AI

```text
ai_relations.jsonl
ai_summaries.jsonl
```

## PCG/material

```text
pcg_parameters.jsonl
material_parameters.jsonl
visual_relations.jsonl
pcg_graph_context.jsonl
material_graph_context.jsonl
visual_summaries.jsonl
```

## World

```text
world_relations.jsonl
world_system_relations.jsonl
world_context.jsonl
world_summaries.jsonl
```

`world_system_relations.jsonl` connects placement to specialist assets only when evidence supports the relationship.

## Animation

```text
animation_relations.jsonl
animation_context.jsonl
animation_summaries.jsonl
```

Animation relations are built only from canonical references/topology and explicitly do not promote generic package dependencies into semantic animation edges.

## VFX

```text
vfx_relations.jsonl
vfx_context.jsonl
vfx_summaries.jsonl
```

Generic Asset Registry dependencies are not treated as semantic VFX evidence.

## Chooser decisions

```text
chooser_decisions.jsonl
chooser_decision_predicates.jsonl
```

Supported Chooser enum-column predicates are normalized into row decisions while preserving raw exported structs and refusing ambiguous/cardinality-mismatched cases. Disabled result rows remain explicit.

## Mover behavior

```text
mover_transition_behaviors.jsonl
mover_transition_routes.jsonl
```

These reconstruct readable Evaluate() branch behavior and resolved concrete movement-mode routes from canonical Blueprint dependencies plus canonical Mover transition facts.

## Gameplay Camera behavior

```text
gameplay_camera_property_providers.jsonl
gameplay_camera_property_fields.jsonl
gameplay_camera_director_inputs.jsonl
```

The model preserves dynamic Blueprint-interface polymorphism: provider implementations are candidates until runtime actor type disambiguates them. Provider return structs and final director Chooser context are split into queryable fields. Gameplay Camera behavior schema 2 decorates readable enum names while keeping raw enum literals/expression trees.

## Typed project graph

```text
project_nodes.jsonl
project_edges.jsonl
project_neighborhoods.jsonl
```

### Node coverage

```text
first_class
first_class_depth_pending
partial
generic_only
external_or_excluded
```

### Edge quality

```text
exact_semantic
exact_reference
unique_dependency_resolution
generic_package_dependency
```

`project_edges.jsonl` is authoritative for source/target kinds, paths, relation, coverage, quality and evidence. Asset Registry dependency evidence remains `generic_package_dependency` and is represented as package-to-package traversal.

Neighborhoods are compact references to selected authoritative edges. Each hop stores:

```text
depth
direction
edge_id
edge_quality
source_coverage
target_coverage
evidence_count
```

Neighborhood generation is bounded to depth 3 / 256 edges and prioritizes stronger semantic/reference evidence before package plumbing.

---

# SQLite and bundle

`uat.db` mirrors the canonical and derived streams into indexed tables and is fully regenerable:

```powershell
python scripts\uatool.py pack <Project>\.uatool
```

The normal upload bundle contains JSON/manifests but excludes `uat.db` and excludes the optional raw RigVM properties unless explicitly requested.

Default ZIP compression is Deflate level 3. Override with:

```powershell
$env:UATOOL_BUNDLE_LEVEL = "6"
```

## Compatibility rule

Never silently invent or rewrite old canonical truth. Backward-compatible canonical cleanup may remove known generated/representation-only values when the transformation is exact, deterministic and manifest-aware; semantic schema changes still require an Unreal rescan.

See [coverage.md](coverage.md) for the maintained first-class/partial/generic-only matrix.
