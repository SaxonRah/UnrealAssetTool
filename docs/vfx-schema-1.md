# VFX schema 1

VFX schema 1 is the independently versioned canonical authored-effects layer for UnrealAssetTool.

```text
structural schema: 12
world schema:      12
animation schema:   1
vfx schema:         1
derived schema:    11
```

The VFX pass runs alongside the world/animation commandlet work and writes `vfx_manifest.json`. `scripts/uatool.py` remains the only public launcher; VFX data is validated, packed into SQLite, queried, and included in ordinary upload bundles by that launcher.

## Design boundary

Niagara is deliberately inspected through Unreal reflection instead of adding a hard `Niagara` module dependency. A project that does not enable Niagara must still be able to build UnrealAssetTool. Concrete Niagara class names and reflected authored properties/references are retained without guessing semantics from display text.

Legacy Cascade uses the same reflection-backed mechanism. Its emitter/LOD/module hierarchy is normalized because those relationships are directly represented by serialized UObject properties.

Raw VFX schema 1 intentionally stops at authored VFX facts. Exact world/component/Blueprint -> VFX stitching belongs to the separately versioned derived layer.

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

The first real Content Examples scan proved 12 stateless emitters with substantial child state. StackOBot + Niagara Examples expanded this to 51 stateless emitters and exercised Sprite, Mesh, Decal and Light stateless renderer families.

### Scripts

- script identity
- usage and usage ID
- exposed version and version count
- bounded reflected properties/references

### Data Channels

- DataChannelAsset -> definition object
- ordered channel variables
- variable name and exact live serialized type handle
- explicitly labelled legacy/deprecated type-definition evidence
- stable canonical raw value
- definition properties/references

UE 5.8 serializes the payload array as `ChannelVariables`; `Variables` remains a reflection fallback for compatibility. Content Examples proves 22 variables across six channel assets; StackOBot + Niagara Examples proves 16 variables across two channel assets.

The canonical `type` value is the exact reflected `TypeDefHandle` when present. `legacy_type_definition` preserves `TypeDef_DEPRECATED`/historical `TypeDef` only as labelled evidence; it is never allowed to override the live handle. UnrealAssetTool deliberately does not hard-link Niagara merely to resolve the registry index into a semantic runtime type.

Per-variable `Version` GUIDs were proven by repeated unchanged StackOBot scans to be load-generated bookkeeping, so schema 1 does not treat them as authored state. The dedicated variable stream keeps the stable semantic facts instead.

### Parameter Collections

`NiagaraParameterCollection` is a first-class VFX asset family:

- collection identity/package/namespace
- ordered parameter list
- parameter name and exact live serialized type handle
- explicitly labelled legacy/deprecated type-definition evidence
- raw authored parameter value
- source Material Parameter Collection when present
- default-instance identity/state when present

StackOBot + Niagara Examples proves one Parameter Collection with six parameters, an exact source Material Parameter Collection, and an exact Niagara default-instance object.

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

Repeated unchanged StackOBot scans also proved three Niagara bookkeeping cases are not stable authored facts and must not enter the canonical property fallback:

```text
niagara_stateless_module.MergeId
niagara_emitter.ChangeId
niagara_data_channel_definition.ChannelVariables
```

`ChannelVariables` is excluded only from the aggregate fallback because its per-variable semantic content is already represented by `niagara_data_channel_variables.jsonl`. Other `MergeId` fields remain available where repeated scans proved them stable; GUID-like fields are not suppressed globally.

The validator checks manifest row counts, normalized topology, live-type-handle canonicalization, and these generated-ID exclusions before derive/pack/bundle is allowed to proceed.

## Validation corpora

### Content Examples — primary mixed Niagara + Cascade corpus

Final validated UE 5.8.2 VFX schema-1 counts:

```text
vfx_assets                             137
vfx_properties                       51834
vfx_references                        6325
niagara_systems                         84
niagara_system_emitters                141
niagara_emitters                       155
niagara_emitter_versions               155
niagara_renderers                      225
niagara_simulation_stages              386
niagara_stateless_emitters              12
niagara_stateless_modules              300
niagara_stateless_renderers             12
niagara_scripts                          3
niagara_data_channels                    6
niagara_data_channel_variables          22
niagara_parameter_collections            0
niagara_parameter_collection_parameters  0
niagara_effect_types                     1
cascade_systems                         29
cascade_emitters                        76
cascade_lods                            76
cascade_modules                        694
```

Validated invariants:

- all 167 bundle files parse cleanly;
- top-level and VFX manifests agree exactly;
- every VFX manifest count equals its JSONL row count;
- all system/emitter/version/renderer/stage hierarchy counts reconcile;
- all 12 stateless emitter module/renderer counts reconcile;
- stateless topology contains 300 module rows (25 slots per emitter), 52 enabled and 248 disabled;
- all 12 stateless renderers are enabled: 10 Sprite, 1 Mesh, 1 Ribbon;
- all six Data Channel counts reconcile with 22 variables;
- all Cascade system/emitter/LOD counts reconcile;
- no VFX property row is truncated;
- the largest reference root is 41 rows, far below the 4096 safety bound.

Renderer coverage includes Sprite, Mesh, Ribbon, Volume and Component renderers.

### StackOBot + Fab Niagara Examples — independent Niagara corpus

The separately installable Fab Niagara Examples content supplies independently authored Niagara shapes and the Parameter Collection family that Content Examples does not exercise.

Final validated UE 5.8.2 VFX schema-1 counts:

```text
vfx_assets                             107
vfx_properties                       35196
vfx_references                        5962
niagara_systems                         73
niagara_system_emitters                216
niagara_emitters                       237
niagara_emitter_versions               237
niagara_renderers                      259
niagara_simulation_stages               36
niagara_stateless_emitters              51
niagara_stateless_modules             1275
niagara_stateless_renderers             78
niagara_scripts                          3
niagara_data_channels                    2
niagara_data_channel_variables          16
niagara_parameter_collections            1
niagara_parameter_collection_parameters  6
niagara_effect_types                     7
cascade_systems                          0
cascade_emitters                         0
cascade_lods                             0
cascade_modules                          0
```

Validated invariants:

- all 167 bundle files parse cleanly;
- top-level and VFX manifests agree exactly;
- every manifest count equals its JSONL row count;
- 216 system handles resolve with zero missing targets: 165 Standard and 51 Stateless;
- all 51 stateless handles resolve exactly to first-class stateless-emitter rows;
- every system/emitter/version/renderer/stage/stateless/Data Channel/Parameter Collection topology count reconciles;
- the one Parameter Collection has six parameters, exact source Material Parameter Collection and exact default-instance identity;
- the 16 Data Channel variables contain six distinct live `TypeDefHandle` registry values;
- all six Parameter Collection parameters carry live handles (two distinct registry values);
- `type == type_handle` on every row that has a live handle;
- no Data Channel canonical raw value contains the load-generated Version GUID;
- no VFX property/variable/parameter row is truncated;
- the largest reference root is 32 rows.

Stateful renderer coverage includes Sprite, Mesh, Component, Decal, Ribbon, Light and Volume. Stateless renderer coverage includes Sprite, Mesh, Decal and Light.

#### Determinism regression

Two consecutive unchanged StackOBot scans exposed generated Niagara bookkeeping. The final scanner removed exactly:

```text
1275 niagara_stateless_module.MergeId rows
 237 niagara_emitter.ChangeId rows
   2 niagara_data_channel_definition.ChannelVariables aggregate rows
----
1514 rows total
```

The final `vfx_properties` count therefore changed from 36710 to 35196. This is the exact intended delta.

Between the pre-filter and final runs:

- 20 of 22 VFX JSONL streams are byte-for-byte identical;
- every surviving common `vfx_properties` row is byte-for-byte identical;
- no property rows were added;
- `niagara_data_channel_variables.jsonl` changed only in `version` and stable canonical `raw_value`;
- `vfx_manifest.json` differs only in generation timestamp and the `vfx_properties` count.

This closes the raw VFX determinism gate.

World-placement facts remain outside raw VFX identity. StackOBot provides loaded NiagaraActor placements that are reserved for the later exact world/component -> VFX derived bridge.

### City Sample

City Sample is intentionally not part of the raw VFX-schema gate. It remains a production-scale corpus for later World Partition, Mass/traffic/crowds, geometry/streaming density, audio, cinematics, dependency-graph scale, performance and final 1.0-beta regression.

## Validation state

**Raw VFX schema 1 is stable on the current UE 5.8.2 validation corpora.**

The validated surface covers mixed Niagara/Cascade assets, stateful and stateless Niagara emitter topology, renderer families, simulation stages, Data Channels, Parameter Collections, Effect Types, reflection fallback, exact object references, live Niagara type-handle provenance, and repeated-scan determinism.

The next separate feature collection is derived VFX relations/context. That layer can stitch exact authored evidence such as:

- Niagara System -> stateful/stateless emitter
- emitter -> renderer/resource
- system -> Effect Type
- Niagara Parameter Collection -> Material Parameter Collection
- world actor/component -> Niagara/Cascade system
- Blueprint -> exact VFX references

Generic package dependencies remain fallback graph evidence and must not be promoted to strong semantic VFX relations without exact authored reference evidence.
