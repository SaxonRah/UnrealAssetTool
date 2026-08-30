# VFX schema 1

VFX schema 1 is the independently versioned canonical authored-effects layer for UnrealAssetTool.

```text
structural schema: 12
world schema:      12
animation schema:   1
vfx schema:         1   # under validation
 derived schema:   11
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

## Initial validation corpus

Content Examples is the first breadth corpus because the existing Asset Registry scan already exposes substantial real VFX content:

```text
NiagaraSystem             84
NiagaraEmitter            14
NiagaraDataChannelAsset    6
NiagaraScript              3
NiagaraEffectType          1
ParticleSystem            29
```

The first UE 5.8.2 build/scan will validate the actual serialized container shapes and determine which reflected fields need post-pass normalization, following the same evidence-driven approach used for animation schema 1.
