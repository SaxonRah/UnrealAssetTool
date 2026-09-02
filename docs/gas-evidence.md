# Gameplay Ability System evidence and schema 6

Gameplay Ability System coverage began as an evidence-first investigation. UE 5.8.2 Lyra evidence is now strong enough to define the first-class **systems schema 6** raw boundary, while derived project-graph promotion remains deliberately pending until the schema-6 real-corpus capture is accepted.

## Diagnostic evidence commands

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
- `attribute` — AttributeSet classes/data plus `FGameplayAttribute` / `FGameplayAttributeData` evidence;
- `cue-task` — Gameplay Cue handlers/tags and AbilityTask helpers;
- `granting` — Lyra/GameFeature ability grants, ability sets and tag-relationship evidence.

Matching requires a concrete GAS/Lyra anchor. Generic words such as `ability`, `Modifiers`, `Tags`, or `Effects` are ranking details only and cannot create a match by themselves.

## Focused native diagnostic capture

When no suitable pre-existing corpus exists, use the focused native pass instead of running a broad scan merely to discover GAS serialization shapes:

```powershell
python scripts\uatool.py gas-capture <Project.uproject> --editor <UnrealEditor-Cmd.exe>
```

`gas-capture` does **not** invoke the normal scanner and does **not** run derive. It performs one AssetRegistry enumeration, filters likely candidates, loads only candidates, and reflects authored/default state. It also enumerates loaded GAS-derived classes so native AttributeSets and other subclasses can be observed even when they do not have standalone assets.

The focused output is written under `<Project>/.uatool`:

- `gas-capture/gas_capture_manifest.json`
- `gas-capture/gas_assets.jsonl`
- `gas-capture/gas_classes.jsonl`
- `gas-capture/gas_properties.jsonl`
- `gas-capture/gas_references.jsonl`
- `<Project>.gas-capture.zip`
- `<Project>.gas-capture.txt`

The manifest is schema 1 and explicitly states:

- `diagnostic_only=true`
- `semantic_promotion=false`
- `runtime_state_captured=false`

Transient/deprecated/skip-serialization properties are excluded. Relevant nested subobjects are reflected and hard/soft object references are recorded recursively. JSONL writers are synchronously closed before a success manifest is published.

### Game Animation Sample smoke

The accepted GASP smoke on UE 5.8.2 produced:

- 13,005 assets considered;
- 0 project GAS candidate assets after the PCG `AttributeSet` false-positive fix;
- 75 loaded GAS-derived classes as an independent native/plugin vocabulary inventory;
- 944 reflected class-CDO properties;
- 2 hard references;
- 0 truncated properties;
- commandlet execution 0.51 s;
- focused editor run 11.67 s;
- total focused workflow 25.30 s;
- no normal scan and no derive.

This proves the commandlet builds/runs and that project-authored candidates are distinct from the loaded native GAS vocabulary. It is not semantic acceptance evidence.

## Lyra UE 5.8.2 evidence

The focused Lyra capture considered 18,033 assets and initially emitted 125 candidates, 315 GAS-derived classes, 16,090 reflected properties, 948 references, 31 nested objects, and **zero truncated properties**.

Deeper inspection of the raw ZIP identified four remaining diagnostic-selector false positives whose asset names contain `GameplayEffect` but whose actual classes are actors/world objects. The source was the diagnostic selector's use of AssetRegistry `GeneratedClass`, whose value embeds the asset path. Those four rows are not treated as GAS evidence. The schema-6 scanner therefore nominates Blueprint candidates from `ParentClass` / `NativeParentClass` metadata and then verifies the loaded generated class by inheritance; it does **not** use `GeneratedClass` text as nomination evidence.

After removing those four false positives, the authored Lyra evidence is:

- 43 GameplayAbility assets;
- 42 GameplayEffect assets;
- 24 GameplayCue assets;
- 12 Lyra Ability Set assets.

The real corpus proves these normalized structures:

### GameplayAbility

All 43 authored abilities expose authored/default policy and tag state including activation policy/group, replication, instancing, net execution/security, ability tag containers, `CostGameplayEffectClass`, `CooldownGameplayEffectClass`, `AbilityTriggers`, and Lyra `AdditionalCosts`.

Observed policy distributions include:

- activation: 34 `OnInputTriggered`, 5 `OnSpawn`, 4 `WhileInputActive`;
- activation group: 41 `Independent`, 2 `Exclusive_Blocking`;
- instancing: 43 `InstancedPerActor`;
- net execution: 27 `LocalPredicted`, 9 `ServerInitiated`, 7 `LocalOnly`.

Exact authored relationships present in the focused rows include:

- 20 ability trigger entries;
- 5 Lyra additional-cost object references;
- 1 cost GameplayEffect class reference;
- 2 cooldown GameplayEffect class references.

### Lyra Ability Sets

The 12 ability sets prove ordered grant arrays with exact class references:

- 33 `GrantedGameplayAbilities` entries, including their `InputTag`;
- 3 `GrantedGameplayEffects` entries;
- 1 `GrantedAttributes` entry.

These relationships are safe to normalize as authored semantic structure because the source object, array index, and target class are all explicit in the serialized object state.

### GameplayEffect

The 42 true GameplayEffects prove:

- duration policy/magnitude and period;
- periodic execution/inhibition policy;
- inherited tag containers and tag requirements;
- stacking state;
- 31 `GEComponents` entries;
- 10 top-level modifier entries;
- 20 execution entries;
- 20 execution calculation-modifier entries;
- 30 GameplayCue entries.

Modifier rows expose exact `FGameplayAttribute` name/owner, modifier operation and magnitude. Execution rows expose exact calculation classes; nested execution modifiers expose captured attribute name/owner, snapshot state, operation and magnitude. GameplayEffect cue entries expose cue tags and optional magnitude attribute name/owner.

### Gameplay Cues

The 24 authored cue Blueprints expose their generated/parent class plus authored/default `GameplayCueTag`, `GameplayCueName` and override state.

### Attribute Sets

The loaded Lyra project/plugin class inventory proves native AttributeSet subclasses and declared `FGameplayAttributeData` properties. Project-relevant examples include:

- `LyraCombatSet`: `BaseDamage`, `BaseHeal`;
- `LyraHealthSet`: `Health`, `MaxHealth`, `Healing`, `Damage`;
- `TopDownArenaAttributeSet`: `BombsRemaining`, `BombCapacity`, `BombRange`, `MovementSpeed`.

Schema 6 records CDO/default `BaseValue` and `CurrentValue`; these are **not live runtime attribute values**.

## Systems schema 6 raw streams

Schema 6 extends schema 5 with these first-class streams:

1. `gas_abilities.jsonl`
2. `gas_ability_triggers.jsonl`
3. `gas_ability_costs.jsonl`
4. `gas_ability_sets.jsonl`
5. `gas_ability_set_abilities.jsonl`
6. `gas_ability_set_effects.jsonl`
7. `gas_ability_set_attributes.jsonl`
8. `gas_gameplay_effects.jsonl`
9. `gas_gameplay_effect_components.jsonl`
10. `gas_gameplay_effect_modifiers.jsonl`
11. `gas_gameplay_effect_executions.jsonl`
12. `gas_gameplay_effect_execution_modifiers.jsonl`
13. `gas_gameplay_effect_cues.jsonl`
14. `gas_gameplay_cues.jsonl`
15. `gas_attribute_sets.jsonl`
16. `gas_attributes.jsonl`

The Python schema-6 validator enforces unique roots, parent resolution, contiguous ordered child indices, declared child counts, execution/modifier ownership, and no truncated structured rows. The SQLite/query surface exposes the same normalized structures.

## Current semantic boundary

Schema 6 is authored/default-state coverage only. It does **not** claim:

- active GameplayEffect specs;
- current granted ability specs;
- prediction keys/state;
- replicated AbilitySystemComponent runtime state;
- live attribute values;
- runtime activation or cooldown state.

The focused corpus shows the native `GameFeatureAction_AddAbilities` class, but it did not establish authored standalone Game Feature grant instances strongly enough for first-class promotion. Likewise, no exact authored tag-relationship-mapping corpus was established. Those remain outside schema 6 rather than being inferred.

Derived GAS project-graph edges are also not claimed yet. The next acceptance gate is one **systems-only Lyra schema-6 capture**; graph promotion follows only after those normalized raw rows pass the real-corpus validator.
