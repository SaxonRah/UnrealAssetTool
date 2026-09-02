# Gameplay Ability System evidence pass

Gameplay Ability System coverage is currently an **evidence-first investigation**, not a first-class schema claim.

The public launcher exposes read-only corpus diagnostics:

```powershell
python scripts\uatool.py gas-evidence <Project>\.uatool
python scripts\uatool.py gas-focus <Project>\.uatool
```

Both commands are diagnostic only:

- they do not launch Unreal;
- they do not modify canonical JSONL;
- they do not run derive;
- they do not promote GAS relationships into the project graph;
- by default they inspect canonical authored streams only.

The large derived Blueprint semantic/project-graph streams are opt-in with `--include-derived`. Source chunks are separately opt-in with `--include-source`.

`gas-focus` groups concrete evidence into six families:

- `ability` — GameplayAbility classes/assets, authored policies, tags, triggers, cost and cooldown references;
- `effect` — GameplayEffect definitions/components, modifiers, executions, duration/period, cues and stacking evidence;
- `ability-system` — AbilitySystemComponent templates/instances and authored component policy;
- `attribute` — AttributeSet classes/data and `FGameplayAttribute` / `FGameplayAttributeData` evidence;
- `cue-task` — Gameplay Cue handlers/tags and AbilityTask helpers;
- `granting` — Lyra/GameFeature ability grants, ability sets and tag-relationship assets.

Matching requires a concrete GAS/Lyra anchor. Generic words such as `ability`, `Modifiers`, `Tags`, or `Effects` are ranking details only and cannot create a match by themselves.

## Focused native capture

When no suitable pre-existing corpus exists, use the focused native pass instead of running a broad scan just to discover GAS serialization shapes:

```powershell
python scripts\uatool.py gas-capture <Project.uproject> --editor <UnrealEditor-Cmd.exe>
```

`gas-capture` does **not** invoke the normal scanner and does **not** run derive. It performs one AssetRegistry enumeration, filters candidates using concrete GameplayAbilities/Lyra class metadata, loads only candidate assets, and reflects authored/default state. It also enumerates already-loaded GAS-derived classes so native AttributeSets and other native subclasses can be observed even when they do not have standalone assets.

The focused output is written under `<Project>/.uatool`:

- `gas-capture/gas_capture_manifest.json`
- `gas-capture/gas_assets.jsonl`
- `gas-capture/gas_classes.jsonl`
- `gas-capture/gas_properties.jsonl`
- `gas-capture/gas_references.jsonl`
- `<Project>.gas-capture.zip`
- `<Project>.gas-capture.txt`

The manifest is schema 1 and is deliberately explicit:

- `diagnostic_only=true`
- `semantic_promotion=false`
- `runtime_state_captured=false`
- provenance is `asset_registry_candidate_plus_loaded_object_reflection`.

Transient/deprecated/skip-serialization properties are excluded. GameplayEffectComponent and other GAS-relevant nested subobjects are reflected, and hard/soft object references are recorded recursively. JSONL writers are synchronously closed before a success manifest is published.

## Acceptance corpus

Lyra Starter Game is the preferred UE 5.8 acceptance corpus because it exercises GAS across abilities, effects, attributes, Gameplay Cues, Game Feature grants, Experiences and Equipment.

The initial compile/runtime smoke can use another existing UE 5.8 project such as Game Animation Sample; that smoke proves only that the focused commandlet builds and runs. **It is not GAS acceptance evidence.** Real semantic promotion will wait for the focused Lyra evidence.

## Current semantic boundary

No first-class GAS schema is claimed yet. In particular, runtime-only state such as active GameplayEffect specs, current granted ability specs, live attribute values, prediction state and replicated ASC runtime state is outside the authored canonical claim unless a later evidence pass establishes a deliberate runtime-capture model.
