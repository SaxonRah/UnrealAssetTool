# AI Perception focused capture

This is an evidence-only UE 5.8.2 capture stage for Issue #14. It does **not** define systems schema 8 and does not promote project-graph semantics.

## Corpus basis

The read-only AI Perception diagnostic was run over four existing corpora.

City Sample, GASP and Cropout returned no anchored AI Perception evidence.

ContentExamples returned representative authored Blueprint-template evidence:

```text
placed perception components:        0
placed stimuli-source components:    0
dominant sense rows:                 1
sense config rows:                   1
stimuli registered-sense rows:       1
usage rows:                           4
concrete sense/config classes:        4
```

The positive authored objects are:

```text
/Game/ExampleContent/StateTree/Blueprints/Enemies/BP_AIController.BP_AIController
  component template: /Script/AIModule.AIPerceptionComponent
  SensesConfig[0]: /Script/AIModule.AISenseConfig_Hearing
  SensesConfig[1]: /Script/AIModule.AISenseConfig_Sight
  DominantSense: /Script/AIModule.AISense_Sight

/Game/Global/Blueprints/PlayerCharacter.PlayerCharacter
  component template: /Script/AIModule.AIPerceptionStimuliSourceComponent
  bAutoRegisterAsSource: True
  RegisterAsSourceForSenses: Sight, Hearing, None
```

The corpus also proves authored `OnTargetPerceptionUpdated` delegate/event usage in `STTG_ListenForPerception`.

The zero component counters in the original diagnostic refer specifically to **placed world components**. They do not negate the Blueprint component-template evidence above.

## Focused capture contract

Canonical command:

```text
uatool ai-perception-capture <project> --editor <UnrealEditor-Cmd>
```

Python nominates exact Blueprint asset paths from the existing corpus. Native UE loads only those assets and recursively inspects objects owned by their generated classes.

The capture recognizes classes by loaded inheritance name rather than AIModule headers:

```text
AIPerceptionComponent
AIPerceptionStimuliSourceComponent
AISenseConfig
```

No `AIModule` dependency is added to `UnrealAssetTool.Build.cs`.

For each captured component template or nested sense-config UObject, reflected non-transient authored/default properties are emitted along with:

```text
value
class_default_value
class_default_present
differs_from_class_default
```

This allows the next normalization design to separate authored overrides from native class defaults without hard-coding Sight or Hearing field lists.

## Diagnostic streams

```text
ai_perception_capture_manifest.json
ai_perception_focus_assets.txt
ai_perception_assets.jsonl
ai_perception_objects.jsonl
ai_perception_properties.jsonl
ai_perception_references.jsonl
```

The manifest remains:

```text
diagnostic_only: true
semantic_promotion: false
runtime_state_captured: false
```

## Explicit runtime non-claims

The capture does not inspect or claim:

```text
currently perceived actors
stimulus age/strength/history
listener runtime state
live perception-system registrations
runtime sense enablement
sight/hearing query results
team/affiliation results produced at runtime
```

Only authored Blueprint template/default state is in scope.
