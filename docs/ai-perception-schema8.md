# AI Perception systems schema 8

AI Perception follows the same evidence-first promotion rule used for GAS, Mass/ZoneGraph and Smart Objects: existing corpus evidence first, focused UE reflection second, canonical systems normalization third, and first-class capability promotion only after a real full-corpus graph verification.

## Evidence selection

The read-only `ai-perception-evidence` diagnostic was run over four existing UE 5.8.2 corpora.

City Sample, GASP and Cropout produced no anchored AI Perception component, sense-config, stimuli-source or authored-usage evidence. They are intentionally not used to define schema 8.

ContentExamples produced representative authored Blueprint-template evidence:

- `/Game/ExampleContent/StateTree/Blueprints/Enemies/BP_AIController.BP_AIController`
  - `AIPerceptionComponent` template
  - `SensesConfig[0]` = `AISenseConfig_Hearing`
  - `SensesConfig[1]` = `AISenseConfig_Sight`
  - `DominantSense` = `/Script/AIModule.AISense_Sight`
- `/Game/Global/Blueprints/PlayerCharacter.PlayerCharacter`
  - `AIPerceptionStimuliSourceComponent` template
  - `bAutoRegisterAsSource = True`
  - `RegisterAsSourceForSenses = (Sight, Hearing, None)`
- `STTG_ListenForPerception`
  - authored `OnTargetPerceptionUpdated` usage

The evidence diagnostic remained read-only and made no semantic promotion.

## Accepted focused reflection capture

The focused UE 5.8.2 ContentExamples reflection pass loaded the two corpus-nominated Blueprint assets and proved:

```text
focus_assets: 2
loaded_assets: 2
blueprint_assets: 2
perception_component_templates: 1
stimuli_source_component_templates: 1
sense_configs: 2
objects: 4
properties: 94
properties_different_from_class_default: 21
references: 7
truncated_properties: 0
property_depth_limit_hits: 0
property_row_limit_hits: 0
container_element_limit_hits: 0
```

Captured object classes were exactly:

```text
/Script/AIModule.AIPerceptionComponent
/Script/AIModule.AISenseConfig_Hearing
/Script/AIModule.AISenseConfig_Sight
/Script/AIModule.AIPerceptionStimuliSourceComponent
```

The focused pass proved authored/default differences for:

- `SensesConfig`
- `DominantSense`
- `MaxAge`
- `DetectionByAffiliation`
- `HearingRange`
- `SightRadius`
- `LoseSightRadius`
- `PeripheralVisionAngleDegrees`
- `bAutoRegisterAsSource`
- `RegisterAsSourceForSenses`

It also proved exact object/class references from the listener component to both sense configs and the dominant sense, from each config to its `Implementation`, and from the stimuli source to Sight and Hearing.

## Canonical schema 8 streams

Systems schema 8 adds five authoritative JSONL streams:

```text
ai_perception_components.jsonl
ai_perception_sense_configs.jsonl
ai_perception_stimuli_sources.jsonl
ai_perception_registered_senses.jsonl
ai_perception_properties.jsonl
```

### `ai_perception_components.jsonl`

One row per authored Blueprint `AIPerceptionComponent` template:

- Blueprint/generated-class identity
- component path/name/class
- dominant sense class
- ordered sense-config count
- reflected property count

### `ai_perception_sense_configs.jsonl`

One row per ordered `SensesConfig` entry. Non-null config rows preserve:

- owning Blueprint and perception component
- source array index
- config object path/class
- `Implementation` sense class
- `MaxAge`
- exported `DetectionByAffiliation`
- enemy/neutral/friendly affiliation booleans when present
- Hearing range when present
- Sight radius / lose-sight radius / peripheral angle when present
- reflected property count

The schema can represent a null array entry explicitly. Null entries do not create semantic graph nodes or edges.

### `ai_perception_stimuli_sources.jsonl`

One row per authored Blueprint `AIPerceptionStimuliSourceComponent` template:

- Blueprint/generated-class identity
- component path/name/class
- `bAutoRegisterAsSource`
- ordered registered-sense count
- reflected property count

### `ai_perception_registered_senses.jsonl`

One row per source-array entry in `RegisterAsSourceForSenses`:

- source component path
- source array index
- sense class
- explicit `is_null`

ContentExamples proves that preserving null entries matters: the authored array is `Sight, Hearing, None`. The null third element remains canonical but produces no graph edge.

### `ai_perception_properties.jsonl`

A bounded reflection layer for the component/config/source objects records:

- owner identity and kind
- stable per-owner property index
- declaring type and property identity
- value
- native-class CDO value when available
- whether the CDO value is present
- `differs_from_class_default`
- truncation status

This keeps sense-specific and future subclass-specific authored settings recoverable without hard-coding every possible `AISenseConfig` subtype into the schema.

## Native boundary

The systems scanner remains reflection-first and does not add an `AIModule` build dependency or AI Perception header includes. Loaded class inheritance names determine whether an object is an AI Perception component, stimuli-source component or sense config.

Only authored Blueprint template/default state is captured.

Explicitly excluded:

- live `UAIPerceptionSystem` state
- listener runtime registrations
- perceived actors
- current/remembered stimuli
- stimulus age, strength or timestamps
- live source registration state
- sight/hearing query/test results
- transient runtime caches

Schema-8 acceptance also requires all AI-specific traversal-loss counters to be present and zero.

## Derived schema 24

Derived schema 24 adds these exact-semantic relations:

```text
has_ai_perception_component
has_ai_perception_sense_config
uses_ai_perception_dominant_sense
implements_ai_perception_sense
has_ai_perception_stimuli_source
registers_ai_perception_sense
```

For the proven ContentExamples topology, the expected specialist edge set is exactly nine:

```text
has_ai_perception_component:          1
has_ai_perception_sense_config:       2
uses_ai_perception_dominant_sense:    1
implements_ai_perception_sense:       2
has_ai_perception_stimuli_source:     1
registers_ai_perception_sense:        2
---------------------------------------
total:                                9
```

Every derived relation must use `edge_quality=exact_semantic` and include evidence from its canonical schema-8 stream. Exact source/relation/target equality is verified, not merely aggregate counts.

## Remaining real-corpus gate

Implementation alone does not make AI Perception first-class.

The remaining acceptance sequence is:

1. run a full systems-only schema-8 capture on ContentExamples;
2. require a successful schema-8 manifest and zero AI traversal-loss counters;
3. promote that capture with `systems-schema8-accept`;
4. run derive once to produce derived schema 24;
5. run `ai-perception-graph-verify` and require the exact canonical edge set;
6. only then promote the capability contract to `first_class`.

Until step 5 passes on the real ContentExamples corpus, AI Perception remains a pending first-class capability rather than a maintained guarantee.
