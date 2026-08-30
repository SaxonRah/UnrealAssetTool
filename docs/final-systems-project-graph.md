# Final systems indexing and project graph

This feature collection finishes the remaining planned UnrealAssetTool specialist indexing layers in one combined UE 5.8.2 validation cycle.

```text
structural scanner schema: 12
world scanner schema:      12
animation scanner schema:   1
VFX scanner schema:         1
systems scanner schema:     1   # this feature collection
derived schema:            13   # this feature collection
```

The new work deliberately keeps raw authored facts separate from derived traversal:

- **systems schema 1** is canonical UE-extracted data;
- **project graph schema 13** is deterministic Python output and can be regenerated from compatible raw data.

## Why these systems are combined

Sequencer, audio, Enhanced Input and project traversal were the last broad planned feature groups. Developing them in four serial scanner/validation loops would add more editor startup and corpus-roundtrip overhead than useful isolation.

They are therefore shipped in one feature collection while remaining separate streams and typed graph families.

The combined systems scanner runs during the existing `UnrealAssetToolWorld` editor process through `OnPostEngineInit`, the same pattern already used by VFX. A normal scan still uses the existing structural and world editor launches rather than adding one editor process per new subsystem.

Optional plugin systems are reflection-backed. UnrealAssetTool does not add hard dependencies on LevelSequence, MetaSound, Enhanced Input, Common Input or Gameplay Tags solely to inspect their authored assets.

---

# Systems scanner schema 1

## Canonical streams

```text
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
systems_manifest.json
```

`systems_assets.jsonl` is the first-class root inventory for this pass. `systems_properties.jsonl` and `systems_references.jsonl` provide the same bounded loss-minimizing fallback used by the animation and VFX scanners for uncommon/plugin-specific authored state.

Transient, duplicate-transient, deprecated and skip-serialization fields are excluded. Property exports are bounded to 65,536 characters. Reference traversal is bounded by depth and rows per root and recursively follows arrays, sets, maps and structs.

## Sequencer / LevelSequence

LevelSequence assets normalize:

```text
LevelSequence
  -> MovieScene
      -> binding / possessable / spawnable
      -> MovieSceneTrack
          -> MovieSceneSection
              -> MovieScene channel structs
```

### `level_sequences.jsonl`

Stores:

- LevelSequence identity/package/class;
- exact MovieScene UObject path;
- binding, track, section and channel counts;
- reflected display rate, tick resolution and playback range.

### `movie_scene_bindings.jsonl`

Stores ordered reflected binding records including:

- binding kind and source array;
- GUID/name/parent GUID where reflected;
- spawnable object-template identity/class;
- possessed-object class where reflected;
- track count;
- bounded raw reflected value for loss minimization.

### `movie_scene_tracks.jsonl`

Stores exact track UObject identity/class, outer, binding GUID where reflected, section count and display-name state.

### `movie_scene_sections.jsonl`

Stores exact section UObject identity/class, owning track, range/row/overlap/pre-roll/post-roll/active/locked state and channel count.

### `movie_scene_channels.jsonl`

MovieScene channel structs are found recursively through reflected section properties. Rows retain:

- section and property path;
- exact channel struct type;
- key/value counts where `Times` / `Values` are reflected;
- default value where reflected;
- bounded raw channel value.

This intentionally preserves uncommon channel implementations without hard-coding every MovieScene channel class.

## MetaSounds and audio

### `audio_assets.jsonl`

First-class families include MetaSound Source/Patch and core authored audio resources such as SoundCue, SoundWave, SoundClass, SoundMix, SoundAttenuation and SoundConcurrency.

Common reflected facts include duration, volume/pitch multiplier, channel/sample-rate information, attenuation reference and normalized graph-node counts where applicable.

### `sound_cue_nodes.jsonl`

Normalizes the exact `SoundCue -> AllNodes[]` UObject topology with node identity/class/name/child count. Node properties/references are retained through the common reflection fallback.

### `metasound_nodes.jsonl` / `metasound_edges.jsonl`

MetaSound frontend document structs are discovered recursively through reflected authored state. Exact frontend node/edge structs retain IDs, vertex IDs, class IDs, names/interfaces/style where present plus bounded raw values.

The scanner does not infer connections from display names. A MetaSound edge is only emitted from a reflected frontend edge structure.

## Enhanced Input

### `input_actions.jsonl`

Stores InputAction identity plus value type, consume/pause/reservation state and authored trigger/modifier counts.

### `input_mapping_contexts.jsonl`

Stores context identity and mapping count.

### `input_mappings.jsonl`

Normalizes ordered Enhanced Action Key Mapping structures:

```text
InputMappingContext
  -> mapping
      -> InputAction
      -> Key
      -> Triggers[]
      -> Modifiers[]
```

Rows retain action identity/class, key, trigger/modifier counts and reflected player-mappable configuration.

### `input_processors.jsonl`

Trigger/modifier UObjects receive exact identity/class plus bounded authored properties/references.

## Bounded common gameplay data

This is intentionally narrow instead of promoting every `UDataAsset` into a pseudo-specialist family.

Current first-class additions are:

- Gameplay Tag DataTables, including ordered tag/comment rows;
- Common Input action DataTables when present;
- PrimaryAssetLabel-like project packaging data;
- Enhanced Input configuration assets that are useful as retrieval roots.

All other project assets remain available through the universal Asset Registry and existing Blueprint/reflection layers.

## Raw validation

The systems validator requires:

- schema/pass/success provenance;
- exact manifest file list;
- manifest counts matching every JSONL stream;
- LevelSequence binding/track/section/channel topology counts;
- track -> section and section -> channel count consistency;
- SoundCue and MetaSound graph counts;
- InputAction and InputMappingContext trigger/modifier/mapping counts;
- Gameplay Tag table row counts.

A failed systems pass gates derive/pack so stale output cannot look current.

---

# Project graph derived schema 13

The project graph is a typed retrieval graph over all canonical/derived families rather than a replacement for their specialist schemas.

## Streams

```text
project_nodes.jsonl
project_edges.jsonl
project_neighborhoods.jsonl
```

## Nodes

Nodes retain:

```text
node_id
node_kind
path
coverage
class_path
package_name
family
root
```

Coverage is explicit and ordered conceptually as:

```text
external_or_excluded
generic_only
partial
first_class_depth_pending
first_class
```

The Asset Registry supplies universal `generic_only` fallback nodes. Specialist scanner assets replace or coexist with those paths as first-class typed nodes.

## Edges

Every edge retains:

```text
edge_id
source_kind
source
relation
target_kind
target
source_coverage
target_coverage
edge_quality
evidence_count
evidence[]
```

Quality classes are:

```text
exact_semantic
exact_reference
unique_dependency_resolution
generic_package_dependency
```

Evidence rows preserve source stream, relation/evidence kind and relevant source identifiers/properties.

### Package dependency rule

`asset_dependencies.jsonl` is useful for broad project navigation but is not exact semantic evidence.

It is represented only as:

```text
package --depends_on_package--> package
```

with:

```text
edge_quality = generic_package_dependency
```

Asset/package membership is represented separately through exact membership edges. A generic package dependency therefore cannot silently become `Blueprint -> NiagaraSystem`, `Sequence -> SoundWave`, or any other invented specialist relationship.

Existing uniquely resolved dependency bridges retain the separate `unique_dependency_resolution` quality class.

## Imported specialist relations

Schema 13 composes existing exact domain facts from:

- Blueprint relations;
- world and world-system relations;
- AI relations;
- PCG/material visual relations;
- animation relations;
- VFX relations;
- new systems topology and references.

It also adds exact topology for the remaining systems:

```text
LevelSequence -> track -> section -> channel
LevelSequence -> binding -> object template
SoundCue -> sound node
MetaSound asset -> node -> connected node
InputMappingContext -> mapping -> InputAction
InputAction/mapping -> trigger/modifier
Gameplay Tag table -> gameplay tag
```

## Bounded neighborhoods

`project_neighborhoods.jsonl` precomputes bidirectional retrieval neighborhoods only for connected first-class roots.

Bounds:

```text
maximum depth:       3
maximum edges:     256
maximum text:   131072 characters
```

Every hop preserves:

- depth and direction;
- edge ID;
- source/target type and path;
- source/target coverage;
- edge quality;
- evidence count;
- full evidence/provenance.

The purpose is not to claim all nodes within three hops are equally meaningful. The purpose is to make every hop inspectable so an AI/tooling consumer can distinguish exact authored structure from lower-confidence package traversal.

## Determinism and validation

The validator checks:

- unique deterministic node/edge IDs;
- every edge endpoint exists;
- edge coverage matches endpoint coverage;
- valid quality class and non-empty evidence;
- package-dependency evidence remains generic quality;
- neighborhood roots are actual graph roots;
- every neighborhood hop references a real edge;
- depth/edge bounds;
- quality and coverage on every hop;
- exact neighborhood coverage for connected roots.

SQLite mirrors all three streams and is regenerable.

---

# Validation plan

The remaining features are validated together rather than one subsystem at a time:

1. **StackOBot + Fab Niagara Examples** — first compile/runtime gate; independently authored LevelSequence/Enhanced Input/Blueprint content plus known VFX/world graph facts.
2. **Content Examples** — broader cinematic/audio/content-family coverage.
3. **GASP** — animation/Blueprint-heavy graph-scale and cross-system regression.

A new GitHub Python smoke workflow runs before the UE corpus gate. It performs Python compilation plus synthetic systems-manifest, SQLite and project-graph quality/neighborhood tests.

City Sample remains a later production-scale beta/regression corpus rather than a blocker for these schema definitions.
