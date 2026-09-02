# AI Perception evidence diagnostic

This diagnostic is the evidence-first entry point for the next Issue #14 subsystem after accepted Smart Objects.

It does **not** define systems schema 8, add graph semantics, or claim runtime perception state. It inventories what an existing UnrealAssetTool corpus can already prove so any focused UE 5.8.2 reflection capture is driven by real authored serialization.

## Command

```powershell
python scripts\uatool.py ai-perception-evidence `
    "N:\EpicVault\Projects\CitySample\.uatool" `
    --report "N:\EpicVault\Projects\CitySample\.uatool\CitySample.ai-perception-evidence.txt"
```

The command is read-only. Unreal is not run and the corpus is not modified.

## Evidence families

The diagnostic separates four authored evidence families:

```text
component
sense_config
stimuli_source
usage
```

### Component

Anchors on concrete AI Perception component class evidence such as:

```text
/Script/AIModule.AIPerceptionComponent
```

It looks for listener-level authored state including `SensesConfig`, `DominantSense`, age/forget settings, and perception delegates without treating generic words like `sight` as proof.

### Sense config

Anchors on concrete `AISenseConfig` classes and `SensesConfig` property paths. High-signal fields include sight/hearing radii, peripheral angle, affiliation filters, max age, enabled state and implementation class.

This phase is diagnostic only. A later schema must preserve the actual UE serialization shape observed in a focused capture rather than assuming all senses share one normalized layout.

### Stimuli source

Anchors on:

```text
/Script/AIModule.AIPerceptionStimuliSourceComponent
```

and attempts to recover authored `RegisterAsSourceForSenses` / auto-register state and concrete `AISense_*` classes.

### Usage

Inventories Blueprint/reflected authored usage such as perception update callbacks, perceived-actor queries, sense enablement, listener refresh and stimuli registration. These rows prove integration/usage only; they do not prove listener configuration by themselves.

## Narrow proof counters

The report publishes bounded diagnostic counters:

```text
unique_perception_components
unique_stimuli_source_components
dominant_sense_rows
sense_config_rows
stimuli_registered_sense_rows
usage_rows
unique_sense_classes
```

These counters are not schema fields and are not promoted into the project graph.

## Explicit boundary

Every report states:

```text
diagnostic_only=True
semantic_promotion=False
runtime_state_captured=False
```

The diagnostic does not capture perceived actors, stimuli history, timestamps, strengths, live listener state, runtime registrations, perception-system state, or results of sight/hearing tests.

## Next decision

Run this first on City Sample because its current corpus is already large and accepted for Mass/ZoneGraph and Smart Objects. If City Sample proves representative AI Perception component/config/stimuli-source state, use those exact rows to design the focused native capture. If it does not, choose another UE 5.8 sample/project with authored AI Perception before designing schema 8.
