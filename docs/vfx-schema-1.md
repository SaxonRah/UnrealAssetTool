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
niagara_scripts.jsonl
niagara_data_channels.jsonl
niagara_data_channel_variables.jsonl
niagara_effect_types.jsonl
cascade_systems.jsonl
cascade_emitters.jsonl
cascade_lods.jsonl
cascade_modules.jsonl
vfx_manifest.json
```

## Niagara coverage in the first pass

### Systems

- system identity/package
- ordered emitter handles
- handle name, ID, enabled state, mode and selected version
- referenced versioned emitter or stateless emitter
- Effect Type
- warmup/fixed-bounds authored state

### Emitters

- emitter identity/class
- versioning state and exposed version
- ordered version data
- simulation target
- deterministic/local-space state
- bounds calculation mode
- renderer count
- simulation-stage count
- event-handler count

### Renderers

- renderer object identity
- exact concrete renderer class
- enabled state and sort-order hint
- bounded reflected authored properties and object references

### Simulation stages

- stage object identity/class
- script usage ID
- iteration source
- bounded reflected authored properties and object references

### Scripts

- script identity
- usage and usage ID
- exposed version
- version count
- bounded reflected properties/references

### Data Channels

- DataChannelAsset -> definition object
- ordered variable definitions when the serialized variable array is available
- variable name/type plus bounded raw authored value
- definition properties/references

### Effect Types

- asset identity
- update-frequency and cull-reaction authored settings
- bounded reflected properties/references

### Parameter Collections

StackOBot + the separately installable Fab Niagara Examples content exposes a project-authored `NiagaraParameterCollection`, a family not exercised by the original Content Examples VFX inventory. UE 5.8 treats this as a first-class global Niagara parameter asset and permits a collection to reference a Material Parameter Collection.

This family is now explicitly part of the schema-1 corpus gate. It is not silently considered covered by the initial scanner; collection/parameter normalization will be promoted from the second-corpus evidence during the validation/fix pass.

## Cascade coverage in the first pass

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

`vfx_properties.jsonl` and `vfx_references.jsonl` use the same bounded facts-first rule as animation schema 1:

- transient/deprecated/non-serialized fields are excluded;
- reflected authored values are capped rather than allowed to make a scan unbounded;
- hard/soft UObject references are recursively normalized through arrays, sets, maps and structs;
- uncommon Niagara renderer/module/plugin-specific state remains available even before it receives a dedicated normalized field.

## Validation corpora

### Content Examples

Content Examples is the primary mixed Niagara + Cascade breadth corpus. Generic Asset Registry inventory before VFX schema 1 normalization:

```text
NiagaraSystem             84
NiagaraEmitter            14
NiagaraDataChannelAsset    6
NiagaraScript              3
NiagaraEffectType          1
ParticleSystem            29
```

### StackOBot + Niagara Examples

The separately installable Fab Niagara Examples content was added to StackOBot. The pack contributes 669 project assets and provides an independently authored gameplay-oriented Niagara corpus rather than duplicating Content Examples.

Whole-project Niagara-related inventory:

```text
NiagaraSystem              73
NiagaraEmitter             21
NiagaraEffectType           7
NiagaraScript               3
NiagaraDataChannelAsset     2
NiagaraParameterCollection  1
```

The `/Game/NiagaraExamples/` pack itself contains:

```text
NiagaraSystem              59
NiagaraEmitter             21
NiagaraEffectType           5
NiagaraScript               3
NiagaraDataChannelAsset     2
NiagaraParameterCollection  1
```

The same pack also broadens future regression coverage with Enhanced Input, Level Sequence, Control Rig, Animation Blueprint, Animated Sparse Volume Texture, materials, meshes and gameplay Blueprints.

### City Sample

City Sample is intentionally not part of the immediate VFX-schema gate. Once available, it will be retained as a large production-scale corpus for later scale/performance and subsystem integration work, especially World Partition, Mass/traffic/crowds, geometry/streaming density, audio, cinematics, dependency-graph scale, and final 1.0-beta regression. It should not block the smaller evidence-driven schema passes that come first.

## Current validation state

The first uploaded Content Examples and StackOBot+NiagaraExamples bundles after PR #8 was opened are valid structural/world/animation/derived-schema-11 regression artifacts: all 144 files in each bundle parse cleanly and their existing schema invariants remain intact.

They do **not**, however, contain `vfx_manifest.json` or any VFX schema-1 streams, so they do not validate PR #8. A valid PR #8 scan must contain `vfx_manifest.json` and these top-level `manifest.json` fields:

```text
vfx_schema_version
vfx_counts
vfx_files
vfx_pass
```

The safest validation procedure is to switch explicitly to `vfx1-niagara-cascade`, confirm `git branch --show-current`, and then run the canonical `scan` command. If the new launcher is actually active and the C++ VFX pass fails to emit a manifest, `scan` must return error 25 rather than silently bundling schema-11-only output.

The first true UE 5.8.2 VFX-schema scans from both corpora will validate serialized container shapes and drive evidence-based normalization fixes, following the same process used for animation schema 1.
