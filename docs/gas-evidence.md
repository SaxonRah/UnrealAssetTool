# Gameplay Ability System evidence pass

Gameplay Ability System coverage is currently an **evidence-first investigation**, not a first-class schema claim.

The public launcher exposes two read-only commands over an existing `.uatool` corpus:

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

## Acceptance corpus

Lyra Starter Game is the preferred UE 5.8 acceptance corpus because it exercises GAS across abilities, effects, attributes, Gameplay Cues, Game Feature grants, Experiences and Equipment.

The first pass should reuse an existing Lyra `.uatool` corpus if one already exists. If no suitable corpus exists, prefer a focused native GAS capture over requiring a full derive merely to discover serialization shapes.

## Current semantic boundary

No first-class GAS schema is claimed yet. In particular, runtime-only state such as active GameplayEffect specs, current granted ability specs, live attribute values, prediction state and replicated ASC runtime state is outside the authored canonical claim unless a later evidence pass establishes a deliberate runtime-capture model.
