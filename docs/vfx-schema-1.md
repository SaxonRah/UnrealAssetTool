# VFX schema 1

VFX schema 1 is UnrealAssetTool's canonical authored-effects layer for Niagara, Niagara Stateless and legacy Cascade.

```text
structural=12
world=12
animation=1
vfx=1
systems=1
derived=14
```

The VFX pass runs inside the world Editor process. It uses reflection for Niagara/plugin-specific state rather than requiring Niagara as a hard build dependency.

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

## Niagara

First-class normalized facts include:

- Niagara System identity and ordered emitter handles;
- stateful/stateless handle mode and exact emitter target;
- emitter versions and selected/exposed version state;
- simulation target, local-space/determinism/bounds settings;
- renderer stacks and concrete renderer classes;
- simulation stages and event-handler counts;
- stateless emitters, ordered modules and renderers;
- Niagara script usage/version identity;
- Data Channel definition/variables and live serialized type handles;
- Parameter Collections, parameters, source Material Parameter Collection and default instance;
- Effect Type settings.

`vfx_properties.jsonl` and `vfx_references.jsonl` preserve bounded authored reflection state around those normalized rows.

Known generated/duplicated bookkeeping excluded from canonical properties includes:

```text
niagara_stateless_module.MergeId
niagara_emitter.ChangeId
niagara_data_channel_definition.ChannelVariables
```

The aggregate `ChannelVariables` field is excluded because variables are normalized separately. GUID-like fields are not suppressed globally; exclusions are evidence-driven.

## Cascade

Normalized topology follows:

```text
ParticleSystem
  -> ParticleEmitter
      -> ParticleLODLevel
          -> RequiredModule
          -> SpawnModule
          -> TypeDataModule
          -> Modules[]
```

Rows retain emitter/LOD order, emitter name/significance, LOD state, module role and exact module object/class. Reflection preserves additional authored state/references.

## Derived VFX

Derived schema 14 adds:

```text
vfx_relations.jsonl
vfx_context.jsonl
vfx_summaries.jsonl
```

Relations are built from canonical VFX topology/references and exact Blueprint/world evidence. Generic Asset Registry package dependencies are not promoted into semantic VFX relations.

VFX assets also become typed project-graph nodes with provenance-bearing edges and bounded neighborhoods.

## Validation

### Content Examples

Validated UE 5.8.2 mixed Niagara/Cascade corpus:

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
niagara_effect_types                     1
cascade_systems                         29
cascade_emitters                        76
cascade_lods                            76
cascade_modules                        694
```

All normalized hierarchy/count invariants reconcile.

### StackOBot + Niagara Examples

Validated independent Niagara corpus:

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
```

All 216 System handles resolve with zero missing targets: 165 stateful and 51 stateless. This corpus also validates Parameter Collection source/default-instance references and repeated-scan determinism.

## Current depth gaps

VFX schema 1 is stable, but stateful Niagara is not exhaustively normalized at stack-graph depth. Remaining useful promotion areas include:

- stateful Niagara module/function execution stacks;
- rapid-iteration parameter semantics and bindings;
- event-handler internals beyond current count/reference coverage;
- renderer/data-interface binding semantics;
- more explicit parameter-flow relationships.

These are **depth gaps**, not asset-discovery gaps: the reflection/reference fallback keeps authored data available until dedicated normalization is justified by corpus evidence.