# VFX schema 1

VFX schema 1 is the independently versioned canonical authored-effects layer for UnrealAssetTool.

```text
structural schema: 12
world schema:      12
animation schema:   1
vfx schema:         1   # under validation
derived schema:    11
```

The VFX pass runs alongside the world/animation commandlet work and writes `vfx_manifest.json`. `scripts/uatool.py` remains the only public launcher; VFX data is validated, packed into SQLite, queried, and included in ordinary upload bundles by that launcher.

## Design boundary

Niagara is deliberately inspected through Unreal reflection instead of adding a hard `Niagara` module dependency. A project that does not enable Niagara must still be able to build UnrealAssetTool. Concrete Niagara class names and reflected authored properties/references are retained without guessing semantics from display text.

Legacy Cascade uses the same reflection-backed mechanism. Its emitter/LOD/module hierarchy is normalized because those relationships are directly represented by serialized UObject properties.

## Canonical streams

```text
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
vfx_manifest.json
```

## Niagara coverage

### Systems and stateful emitters

- system identity/package and ordered emitter handles
- handle name, ID, enabled state, mode and selected version
- exact versioned-emitter and stateless-emitter targets
- system Effect Type and warmup/fixed-bounds state
- emitter versioning state and ordered version data
- simulation target, deterministic/local-space state and bounds mode
- renderer stacks with exact concrete renderer classes/settings/references
- simulation stages
- event-handler counts

### Stateless/lightweight emitters

UE 5.8 systems can select `UNiagaraStatelessEmitter` handles. These are normalized separately from stateful emitter version data:

- stateless emitter identity/class
- deterministic/random-seed/fixed-bounds state
- ordered `Modules[]`
- ordered `RendererProperties[]`
- exact child module/renderer classes
- child enabled state where reflected
- bounded authored properties/references for each child UObject

This topology was promoted after the first real Content Examples scan proved 12 stateless emitters with substantial child module state that a parent-only reflection pass would underspecify.

### Scripts

- script identity
- usage and usage ID
- exposed version and version count
- bounded reflected properties/references

### Data Channels

- DataChannelAsset -> definition object
- ordered channel variables
- variable version, name, type and bounded raw value
- definition properties/references

UE 5.8 serializes the payload array as `ChannelVariables`; `Variables` remains a reflection fallback for compatibility. The first Content Examples scan exposed this exact shape and proved 22 variables across six channel assets.

### Parameter Collections

`NiagaraParameterCollection` is a first-class VFX asset family:

- collection identity/package/namespace
- ordered parameter list
- parameter name/type/raw authored value
- source Material Parameter Collection when present
- default-instance identity/state when present

This family was promoted because StackOBot + the separately installable Fab Niagara Examples pack contains a project-authored Parameter Collection that Content Examples does not exercise.

### Effect Types

- asset identity
- update-frequency and cull-reaction authored settings
- bounded reflected properties/references

## Cascade coverage

```text
ParticleSystem
  -> ParticleEmitter
      -> ParticleLODLevel
          -> RequiredModule
          -> SpawnModule
          -> TypeDataModule
          -> Modules[]
```

The normalized rows retain emitter/LOD order, emitter name/significance, LOD enabled/level state, module role, exact module UObject/class, and bounded authored properties/references for systems, emitters, LODs, and modules.

## Loss-minimizing fallback

`vfx_properties.jsonl` and `vfx_references.jsonl` follow the same facts-first rule as animation schema 1:

- transient/deprecated/non-serialized fields are excluded;
- reflected authored values are capped rather than allowed to make a scan unbounded;
- hard/soft UObject references are recursively normalized through arrays, sets, maps and structs;
- uncommon renderer/module/plugin-specific state remains available even before receiving dedicated normalized fields.

The corpus validator additionally checks manifest row counts and normalized topology counts before derive/pack/bundle is allowed to proceed.

## Validation corpora

### Content Examples

Content Examples is the primary mixed Niagara + Cascade breadth corpus. Generic inventory before VFX normalization:

```text
NiagaraSystem             84
NiagaraEmitter            14
NiagaraDataChannelAsset    6
NiagaraScript              3
NiagaraEffectType          1
ParticleSystem            29
```

The first true UE 5.8.2 VFX-schema-1 scan produced a 162-file bundle with correct top-level VFX provenance and every JSON/JSONL file parseable:

```text
vfx_assets                       137
vfx_properties                 48999
vfx_references                  6313
niagara_systems                   84
niagara_system_emitters          141
niagara_emitters                 155
niagara_emitter_versions         155
niagara_renderers                225
niagara_simulation_stages        386
niagara_scripts                    3
niagara_data_channels              6
niagara_data_channel_variables     0   # first-pass bug; raw facts prove 22
niagara_effect_types               1
cascade_systems                    29
cascade_emitters                   76
cascade_lods                       76
cascade_modules                   694
```

Validated from that corpus:

- every system emitter count matched its emitted handle rows;
- all 141 handle targets were distinct embedded emitters;
- every emitter version count matched emitted version rows;
- every declared renderer/stage count matched the 225 renderer / 386 stage rows;
- renderer families included Sprite, Mesh, Ribbon, Volume and Component renderers;
- every Cascade system/emitter/LOD count matched its normalized topology;
- no reflected property value was truncated;
- no reference root reached the 4096-row bound.

Two evidence-driven fixes came directly from the scan:

1. Data Channels use UE 5.8 `ChannelVariables`, yielding an expected 22 normalized variables on the rerun.
2. Twelve stateless emitters expose exact `Modules[]` and `RendererProperties[]` child topology, so schema 1 now descends into those child UObjects instead of retaining only parent references.

### StackOBot + Niagara Examples

The separately installable Fab Niagara Examples content was added to StackOBot. The pack contributes 669 project assets and provides an independently authored gameplay-oriented Niagara corpus rather than duplicating Content Examples.

Whole-project Niagara-related inventory before VFX normalization:

```text
NiagaraSystem              73
NiagaraEmitter             21
NiagaraEffectType           7
NiagaraScript               3
NiagaraDataChannelAsset     2
NiagaraParameterCollection  1
```

The `/Game/NiagaraExamples/` pack itself contains 59 Systems, 21 Emitters, 5 Effect Types, 3 Scripts, 2 Data Channels and the one Parameter Collection. It also broadens future regression coverage with Enhanced Input, Level Sequence, Control Rig, Animation Blueprint, Animated Sparse Volume Texture, materials, meshes and gameplay Blueprints.

World-placement facts remain outside raw VFX asset identity. StackOBot currently provides 18 loaded NiagaraActor placements; those are reserved for the later exact world -> VFX derived bridge.

### City Sample

City Sample is intentionally not part of the immediate VFX-schema gate. Once available, it will be retained as a production-scale corpus for later World Partition, Mass/traffic/crowds, geometry/streaming density, audio, cinematics, dependency-graph scale, performance and final 1.0-beta regression.

## Current validation state

The first true Content Examples scan validates the stateful Niagara and Cascade architecture. The branch now contains the corpus-driven Data Channel fix, first-class stateless topology, Parameter Collection support, stronger count/topology validation, and scan/pack completeness gating.

The remaining raw-schema gate is:

1. rerun Content Examples and verify the expanded streams, especially 22 Data Channel variables and stateless emitter child counts;
2. run StackOBot + Niagara Examples and validate the second-corpus Parameter Collection and Niagara shapes;
3. fix only corpus-proven mismatches before declaring VFX schema 1 stable.
