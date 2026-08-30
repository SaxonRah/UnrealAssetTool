# Derived VFX schema 12

Derived schema 12 adds deterministic VFX relations, summaries, and bounded retrieval context on top of the stable raw VFX schema 1.

```text
structural schema: 12
world schema:      12
animation schema:   1
vfx schema:         1
derived schema:    12
```

This is a Python-only derived-schema change. It does not change the UE commandlets or any canonical scanner stream and therefore does not require Unreal to rescan a project when compatible raw `.uatool` output already exists.

## Derived streams

```text
vfx_relations.jsonl
vfx_context.jsonl
vfx_summaries.jsonl
```

The same data is loaded into regenerable SQLite tables:

```text
vfx_relations
vfx_context
vfx_summaries
```

## Evidence boundary

Only exact canonical facts are promoted into semantic VFX relations:

- normalized raw VFX topology;
- exact reflected `vfx_references.jsonl` object references;
- exact `world_references.jsonl` actor/component references;
- exact evidence-bearing `blueprint_relations.jsonl` targets;
- exact generated-Blueprint-class -> authored-Blueprint aliases.

`asset_dependencies.jsonl` is deliberately **not** used to create semantic VFX edges. Generic package dependency evidence remains generic package dependency evidence.

When an exact reflected VFX reference joins the same source/target pair as a stronger normalized topology relation, it is retained as additional evidence on that stronger relation rather than emitted as a competing weaker semantic interpretation.

## Normalized relations

### Niagara

```text
NiagaraSystem
  -> uses_emitter -> NiagaraEmitter
  -> uses_stateless_emitter -> NiagaraStatelessEmitter
  -> uses_effect_type -> NiagaraEffectType

NiagaraEmitter
  -> uses_renderer -> NiagaraRenderer
  -> uses_simulation_stage -> NiagaraSimulationStage

NiagaraStatelessEmitter
  -> uses_module -> NiagaraStatelessModule
  -> uses_renderer -> NiagaraRenderer

NiagaraParameterCollection
  -> uses_material_parameter_collection -> MaterialParameterCollection
```

For stateless System handles, the active semantic edge targets the exact `StatelessEmitter`. The versioned wrapper-emitter path remains in the relation evidence rather than being misrepresented as the active emitter.

### Cascade

```text
ParticleSystem
  -> uses_cascade_emitter -> ParticleEmitter
      -> uses_cascade_lod -> ParticleLODLevel
          -> uses_cascade_module -> ParticleModule
```

### Exact cross-system references

```text
VFX UObject -> references_object -> exact UObject
world actor/component -> references_vfx_asset -> first-class VFX asset
Blueprint -> references_vfx_asset -> first-class VFX asset
```

World and Blueprint joins are emitted only when their exact target path is a first-class `vfx_assets.jsonl` root.

## Relation evidence

Each relation has a deterministic ID plus aggregated evidence. Current evidence kinds are:

```text
canonical_vfx_structure
canonical_vfx_field
canonical_vfx_reference
canonical_world_reference
exact_blueprint_relation
```

Evidence records retain relevant source stream, property/topology location, classes, indices, enabled/mode/version facts, and upstream relation IDs where applicable.

Coverage metadata is attached to relation targets but is not part of semantic edge identity.

## Context and summaries

`vfx_summaries.jsonl` contains one row for every first-class raw VFX asset. It records:

- asset identity/kind/class/package;
- first-class coverage;
- high-value raw family counts/fields;
- outgoing/incoming relation counts;
- relation-type counts;
- compact retrieval text.

`vfx_context.jsonl` also has exactly one row per first-class VFX asset and adds bounded incoming/outgoing relation detail. Context is bounded to 250 links and 262,144 characters per asset.

Nested emitters/renderers/modules/stages participate in the relation graph but do not each receive a top-level VFX retrieval context row unless they are themselves first-class VFX assets.

## Validation

Derived schema 12 validation checks:

- unique deterministic relation IDs;
- exact summary/context coverage of every `vfx_assets.jsonl` root;
- summary/context incoming/outgoing counts against the emitted relation graph;
- every normalized Niagara System/emitter relation;
- every stateful/stateless renderer relation;
- every simulation-stage and stateless-module relation;
- every System -> Effect Type relation;
- every Parameter Collection -> Material Parameter Collection relation;
- every Cascade System/emitter/LOD/module relation;
- preservation of every exact reflected VFX object reference;
- preservation of every exact world -> VFX reference;
- preservation of every exact Blueprint -> VFX relation;
- rejection of semantic evidence sourced from `asset_dependencies.jsonl`.

`pack` also requires `manifest.json` to report derived schema 12 and exact row counts for all three VFX-derived files.

## Saved-corpus replay before end-to-end validation

The implementation was replayed directly against the already-validated final raw VFX bundles from both UE 5.8.2 corpora. This exercises the new Python layer without changing the proven scanner inputs.

### Content Examples

```text
vfx_relations  6611
vfx_context     137
vfx_summaries   137
```

Relation distribution:

```text
references_object        4334
uses_cascade_module       694
uses_simulation_stage     386
references_vfx_asset      345
uses_module               300
uses_renderer             237
uses_emitter              129
uses_cascade_lod           76
uses_cascade_emitter       76
uses_effect_type           22
uses_stateless_emitter     12
```

The 345 exact cross-system VFX references comprise 304 world-reference source/target pairs plus 41 unique Blueprint/VFX pairs after evidence aggregation.

### StackOBot + Fab Niagara Examples

```text
vfx_relations  6104
vfx_context     107
vfx_summaries   107
```

Relation distribution:

```text
references_object                      4021
uses_module                             1275
uses_renderer                            337
uses_emitter                             165
references_vfx_asset                     159
uses_effect_type                          59
uses_stateless_emitter                    51
uses_simulation_stage                     36
uses_material_parameter_collection         1
```

The 159 exact cross-system relations comprise 102 world-reference pairs plus 57 unique Blueprint/VFX pairs. The world set includes the previously corpus-proven 18 loaded `NiagaraActor` placements, each resolving to an exact Niagara System.

Both replay corpora pass the derived validator and SQLite create/load/count checks.

## End-to-end validation workflow

Because this PR changes only derived Python code, existing compatible raw `.uatool` output is sufficient.

For StackOBot:

```powershell
python scripts\uatool.py derive "E:\TheDigitalGame\ue\StackOBot\.uatool"
python scripts\uatool.py pack "E:\TheDigitalGame\ue\StackOBot\.uatool"
python scripts\uatool.py bundle "E:\TheDigitalGame\ue\StackOBot\.uatool" `
    --destination "E:\TheDigitalGame\ue\StackOBot\StackOBot.uatool.zip"
```

The expected derived VFX counts are:

```text
vfx_relations=6104
vfx_context=107
vfx_summaries=107
```

A full Unreal `scan` remains useful as a later regression, but it is not required to validate a Python-only derived-schema change against already-valid raw schema-1 output.
