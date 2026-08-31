# Systems schema 1

Systems schema 1 is the canonical reflection-backed layer for Sequencer, audio/MetaSound, Enhanced Input and selected gameplay-data systems.

Current baseline:

```text
structural schema: 12
world schema:      12
animation schema:   1
vfx schema:         1
systems schema:     1
derived schema:    14
```

The pass runs inside the world Editor process and writes `systems_manifest.json`. It deliberately avoids hard dependencies on optional LevelSequence/MovieScene, MetaSound, EnhancedInput, CommonInput/CommonUI and GameplayTags modules where reflection can recover the authored data safely.

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

## Shared reflected state

Every recognized systems asset is represented in `systems_assets.jsonl`. Bounded reflected authored properties and hard/soft object references are preserved in:

```text
systems_properties.jsonl
systems_references.jsonl
```

Property traversal excludes transient, duplicate-transient, non-PIE duplicate transient, deprecated and skip-serialization fields. Object references traverse supported structs, arrays, sets and maps with explicit depth/row bounds.

Current safety bounds:

```text
property export                 65536 chars
reference depth                     8
references per root              4096
nested objects per asset         8192
structured rows per asset       65536
```

## Sequencer / LevelSequence

Normalized streams:

```text
level_sequences.jsonl
movie_scene_bindings.jsonl
movie_scene_tracks.jsonl
movie_scene_sections.jsonl
movie_scene_channels.jsonl
```

First-class facts include:

- LevelSequence/MovieScene identity;
- display rate, tick resolution and playback range;
- binding rows from reflected ObjectBindings/Possessables/Spawnables shapes;
- binding GUID/name/parent/template/possessed class;
- track identity/class/name/binding GUID;
- section identity/class/range/row/priority/pre/post-roll/active/locked state;
- channel identity/type/default/raw serialized value;
- exact declared binding/track/section/channel counts.

The validator reconciles sequence totals, track -> section counts and section -> channel counts.

### Current depth boundary

Channels are first-class containers, but individual channel keys are not yet emitted as dedicated normalized rows. Key counts and loss-minimizing raw channel state are retained. Subsequence, camera-cut, event, animation, audio and VFX references can appear through concrete track/section classes and `systems_references`, but family-specific Sequencer semantics are not yet normalized into separate typed streams.

For that reason Sequencer is best described as **first-class, depth pending** rather than exhaustive.

## Audio

Recognized first-class audio asset kinds currently include:

```text
MetaSoundSource
MetaSoundPatch
SoundCue
SoundWave
SoundClass
SoundMix
SoundAttenuation
SoundConcurrency
```

`audio_assets.jsonl` records identity/class/package plus common duration/volume/pitch/channel/sample-rate/attenuation facts where those fields exist.

### SoundCue

`sound_cue_nodes.jsonl` records ordered `AllNodes`, node class/path/name and child count. Each node's authored state/references is also preserved through the shared reflection layer.

Current depth boundary: there is no dedicated `sound_cue_edges.jsonl`; child topology is not yet normalized as explicit node-to-node edges. Exact UObject child references may still exist in `systems_references`.

### MetaSound

MetaSound scanning recursively finds serialized frontend node/edge structs and normalizes:

- node ID/class ID/name/interface/style;
- edge from-node/from-vertex/to-node/to-vertex IDs;
- exact per-asset node/edge counts;
- bounded raw struct state.

The validator requires every emitted edge endpoint to resolve inside the same MetaSound asset in corpus validation.

Current depth boundary: frontend vertex declarations, literals/defaults, interface members and node-class registry semantics are not yet normalized into dedicated rows. The topology itself is first-class.

## Enhanced Input

Normalized streams:

```text
input_actions.jsonl
input_mapping_contexts.jsonl
input_mappings.jsonl
input_processors.jsonl
```

### InputAction

Captured facts include:

- value type;
- consume/paused/reservation/legacy-key settings;
- action-level trigger/modifier counts;
- trigger/modifier child UObject identities/classes/state.

### InputMappingContext

Mappings normalize:

- context -> mapping index;
- exact InputAction target;
- key;
- trigger/modifier counts;
- player-mappable options/settings;
- bounded raw mapping struct state.

UE 5.8 stores authored default mappings under `DefaultKeyMappings.Mappings` on validated projects; the scanner uses populated direct `Mappings` when present and otherwise handles the UE 5.8 default-key container.

`input_processors.jsonl` distinguishes action-level versus mapping-level trigger/modifier objects.

Recognized but reflection-only Enhanced Input assets also include:

```text
PlayerMappableInputConfig
EnhancedInputPlatformData
```

Those should be considered **first-class, depth pending** until their family-specific structures are normalized.

## Gameplay data / Common Input

Current recognized gameplay-data kinds include:

```text
PrimaryAssetLabel
Gameplay Tag DataTable
Common Input action table
Common Input action domain
Common Input action domain table
```

Gameplay Tag DataTables are recognized by row struct and emit normalized `gameplay_tags.jsonl` rows with row name, tag and comment.

Common Input action DataTables/CompositeDataTables are recognized through row struct `/Script/CommonUI.CommonInputActionDataBase`; Common Input action-domain assets/tables are also first-class roots. Their detailed authored state/references remain primarily reflection-backed.

General DataTables, CurveTables and arbitrary PrimaryDataAssets are not normalized by systems schema 1.

## Validation corpora

### StackOBot + Niagara Examples

Final validated UE 5.8.2 systems counts:

```text
systems_assets             92
systems_properties       6644
systems_references        435
level_sequences             5
movie_scene_bindings       48
movie_scene_tracks         49
movie_scene_sections       46
movie_scene_channels      345
audio_assets               53
sound_cue_nodes              0
metasound_nodes            248
metasound_edges            279
input_actions               30
input_mapping_contexts       4
input_mappings              55
input_processors            50
gameplay_data_assets         0
gameplay_tags                0
```

Enhanced Input validation proved:

- all 55 mappings have non-empty action/key;
- all 55 resolve to normalized InputActions;
- context counts reconcile exactly as 30 / 1 / 5 / 19;
- 27 mapping-level modifiers plus 23 action-level processors;
- action/mapping declared processor counts match emitted processor rows.

The eight MetaSound assets contain 248 nodes and 279 raw edges, all resolving endpoint IDs inside the same asset.

### Content Examples

Final validated UE 5.8.2 systems counts:

```text
systems_assets              235
systems_properties        27428
gameplay_data_assets          4
level_sequences              60
movie_scene_bindings         312
movie_scene_tracks           260
movie_scene_sections         279
movie_scene_channels       19178
audio_assets                147
sound_cue_nodes               13
metasound_nodes             1020
metasound_edges              958
input_actions                 14
input_mapping_contexts        10
input_mappings                23
input_processors              23
```

The four Common Input first-class assets are:

```text
NavigationInputDataTable
InputActionDataComposite
AD_MultiHandleLayer
SampleActionDomainTable
```

The two Common Input action tables use row struct `CommonInputActionDataBase` and contain 30 normalized rows total (27 + 3 at the validated gate).

Generated `UMovieSceneSignedObject::Signature` values are excluded from canonical systems properties because Epic's signature is generation/change-tracking state rather than a stable authored identifier.

## Derived project graph integration

Systems schema 1 contributes typed project-graph topology including:

```text
LevelSequence -> contains_movie_scene_binding -> binding
LevelSequence -> contains_movie_scene_track -> track
track -> contains_movie_scene_section -> section
section -> contains_movie_scene_channel -> channel
MetaSound asset -> contains_metasound_node -> node
MetaSound node -> metasound_connects_to -> node
InputMappingContext -> contains_input_mapping -> mapping
mapping -> maps_input_action -> InputAction
InputAction/mapping -> uses_input_trigger / uses_input_modifier -> processor
gameplay-tag table -> declares_gameplay_tag -> gameplay tag
```

Exact generic `systems_references` also feed `references_object` graph edges. Package dependencies remain lower-quality package-to-package traversal.

## Status

**Systems schema 1 is stable on the current UE 5.8.2 StackOBot, Content Examples and GASP corpus gate.**

The remaining work is family depth, not basic subsystem discovery: individual Sequencer keys, richer SoundCue edges/audio routing, MetaSound vertices/literals/interfaces, deeper Enhanced Input auxiliary assets and broader gameplay-data/tag semantics.