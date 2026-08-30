# UnrealAssetTool subsystem coverage

This document tracks what UnrealAssetTool understands as a first-class authored system versus what is only visible through generic Asset Registry identity/dependency data.

The distinction matters for AI retrieval. A generic asset record can tell us that an asset exists and what packages it depends on. A first-class extractor can tell us how the asset itself is structured, wired, configured, and related to gameplay.

## Coverage levels

| Level | Meaning |
| --- | --- |
| **First-class** | Dedicated canonical streams preserve authored structure/settings/topology, with derived relations/context where useful. |
| **Partial** | Important structure is captured indirectly or only from the surrounding Blueprint/world model, but the asset family itself is not yet fully extracted. |
| **Generic-only** | Asset Registry identity, tags, package dependencies, and incidental UObject/world references are available, but no dedicated internal extractor exists. |
| **Not targeted yet** | No dedicated model is planned in the immediate roadmap unless project evidence makes it useful. |

## Current 0.7.0 coverage

### Project, world, and gameplay-program systems

| System | Coverage | Notes |
| --- | --- | --- |
| Physical files/source/config | **First-class** | Bounded source chunks plus file metadata. |
| Asset Registry | **First-class baseline** | Asset identity, class, tags, package paths, direct package dependencies. This is the fallback for every unsupported asset family. |
| Worlds/maps/levels | **First-class** | World identity, persistent/streaming levels, actor placement, components, transforms, instance overrides, object references, Data Layers, World Partition descriptors. |
| World Partition | **First-class** | Descriptor-only enumeration where possible; parent/reference GUID relationships; LevelInstance/PackedLevelActor child-world relationships are derived without loading external actors. |
| Blueprint/K2 | **First-class** | Graphs, nodes, pins, exact edges, properties, references, functions/events, execution blocks, call bindings, bounded data provenance. |
| Animation Blueprints | **First-class graph/program model** | AnimGraph/state-machine topology and common animation-node semantics are strong. Referenced animation asset internals remain a separate gap below. |
| UMG Widget Blueprints | **First-class Blueprint/UMG model** | Widget tree, properties, bindings, animations, animation bindings, Blueprint graph structure. |
| Control Rig / RigVM | **First-class** | Editor graph plus compact RigVM graph/node/pin/link/reference model and editor-to-model joins. |
| Behavior Trees | **First-class** | Tree hierarchy, tasks/composites/decorators/services, settings, Blackboard relationships. |
| Blackboards | **First-class** | Keys, types, inheritance, selector resolution. |
| EQS | **First-class** | Queries, options, generators, tests, relationships. |
| StateTree | **First-class** | States, tasks/evaluators, conditions, transitions, bindings, linked assets. |
| PCG | **First-class** | Graphs, nodes, pins, exact edges, settings/properties, parameters, subgraph relationships. |
| Materials / Material Instances / Material Functions | **First-class** | Graph expressions, root/output wiring, expression edges, reflected settings, parameters, texture/function references, derived visual relations/context. |
| World-to-system placement links | **First-class derived** | Schema 10 bridges placed actors/components/worlds to Blueprint, AnimBP, Control Rig, UMG, AI, PCG, and material targets with explicit evidence. |

### Animation asset breadth

| Asset family | Coverage | What is still missing |
| --- | --- | --- |
| AnimSequence | **Generic-only / referenced from AnimBP** | Notifies, notify states, curves, sync markers, additive/root-motion/compression metadata, skeleton relationships, authored sequence internals. |
| AnimMontage | **Generic-only / referenced from AnimBP** | Sections, slot tracks, branching points, notifies, section links, blend settings. |
| BlendSpace / BlendSpace1D / AimOffset | **Generic-only / referenced from AnimBP** | Axis definitions, samples, interpolation/grid settings. |
| PoseAsset | **Generic-only** | Pose names/curves/skeleton relationships. |
| Skeleton | **Generic-only** | Bone tree, sockets, slot groups, virtual bones, retarget metadata. |
| SkeletalMesh | **Generic-only** | Skeleton/material-slot/LOD/morph/socket/physics relationships beyond generic dependencies and incidental references. |
| PhysicsAsset | **Generic-only** | Bodies, constraints, skeletal association. |
| Pose Search Schema / Database | **Partial** | Motion Matching AnimGraph nodes are recognized, but Pose Search schema/database/channel contents are not first-class yet. |
| Chooser Table | **Generic-only** | Columns/rows/evaluation structure and selected assets are not yet extracted. |
| ProxyTable / ProxyAsset | **Generic-only** | Proxy entries and lookup/fallback semantics are not yet extracted. |
| IK Rig / IK Retargeter | **Generic-only** | Chains, goals, solvers, retarget mappings/settings are not yet modeled. |
| Motion Warping authored assets/settings | **Partial** | Blueprint/world references can surface them, but no dedicated semantic model exists. |

Animation-asset internals are the highest-priority breadth gap because they are directly required to understand modern UE 5.8 locomotion and Motion Matching workflows.

## VFX / particles

| Asset family | Coverage | What is still missing |
| --- | --- | --- |
| Niagara System | **Generic-only** | System/emitter composition, stack groups, modules, renderers, parameters, bindings, events, data interfaces, scripts. |
| Niagara Emitter | **Generic-only** | Emitter stack/module/renderer structure and settings. |
| Niagara Script | **Generic-only** | Script usage, rapid-iteration parameters, module/function relationships. |
| Niagara Data Channel | **Generic-only** | Channel variables/settings/readers/writers. |
| Niagara Effect Type | **Generic-only** | Scalability/culling/significance settings. |
| Legacy Cascade ParticleSystem | **Generic-only** | Emitters/modules/LOD/material relationships. |

UE 5.8 treats Niagara as a stack-based authored VFX system built from systems, emitters, modules, parameters, renderers, and data interfaces. That structure is currently a real blind spot rather than a hidden extension of material coverage.

## Cinematics

| Asset family | Coverage | What is still missing |
| --- | --- | --- |
| LevelSequence / Sequencer | **Generic-only** | Possessables/spawnables, object bindings, tracks, sections, channels, keyframes, subsequences, event tracks, camera cuts, animation/audio/VFX references. |
| Template/Camera Animation Sequence | **Generic-only** | Sequence tracks/channels/bindings. |

World scans can identify placed LevelSequenceActors and their references, but the LevelSequence asset itself is not yet decomposed.

## Audio

| Asset family | Coverage | What is still missing |
| --- | --- | --- |
| MetaSound Source | **Generic-only** | Graph nodes/pins/edges, interfaces, inputs/outputs, literals, referenced patches/waves. |
| MetaSound Patch | **Generic-only** | Same graph model as MetaSound Source. |
| SoundCue | **Generic-only** | Cue graph nodes/edges/wave relationships and node settings. |
| SoundWave | **Generic-only** | Sound metadata beyond generic Asset Registry tags/dependencies. |
| SoundClass / SoundMix / SoundAttenuation | **Generic-only** | Routing, hierarchy, modifiers, attenuation/spatialization settings. |

MetaSounds are authored flow/DSP graphs and should eventually receive the same facts-first graph treatment as Blueprint, PCG, and materials.

## Input and gameplay data

| Asset family | Coverage | What is still missing |
| --- | --- | --- |
| Enhanced Input InputAction | **Generic-only** | Value type, triggers, modifiers, consumption/reservation settings. |
| InputMappingContext | **Generic-only** | Key/action mappings, triggers/modifiers, priorities supplied elsewhere. |
| DataTable / CompositeDataTable / CurveTable | **Generic-only** | Row schemas and row values are not currently normalized. |
| UserDefinedStruct / UserDefinedEnum | **Partial** | Blueprint pin/type usage is preserved; standalone authored definitions are not a dedicated table. |
| Gameplay Tags | **Partial** | Tags appear through reflected properties/text where referenced; no project-wide tag dictionary/redirect/category model yet. |

## Rendering, geometry, physics, and environment

These assets are visible through Asset Registry and world/component references but generally do not have dedicated internal models yet:

- StaticMesh
- SkeletalMesh
- Texture families
- GeometryCollection/Dataflow
- Groom/GroomBinding
- Optimus deformer assets
- PhysicalMaterial
- Landscape layer/grass assets
- Foliage types
- HLOD layers
- mesh deformers
- render targets and atlases

They should be promoted selectively when their authored internals materially affect gameplay/animation/VFX understanding.

## Coverage evidence from Content Examples

The validated UE 5.8.2 Content Examples corpus is useful because it contains both systems we already understand and major uncovered families.

Representative Asset Registry counts from the validated schema-10 scan include:

| Asset family | Count | Current status |
| --- | ---: | --- |
| Material | 564 | First-class |
| MaterialInstanceConstant | 278 | First-class |
| MaterialFunction | 129 | First-class |
| Blueprint | 363 | First-class |
| AnimBlueprint | 98 | First-class graph/program model |
| WidgetBlueprint | 65 | First-class |
| ControlRigBlueprint | 27 | First-class |
| PCGGraph | 27 | First-class |
| StateTree | 25 | First-class |
| AnimSequence | 143 | Generic-only asset internals |
| MetaSoundSource | 98 | Generic-only |
| NiagaraSystem | 84 | Generic-only |
| LevelSequence | 60 | Generic-only |
| ParticleSystem (Cascade) | 29 | Generic-only |
| PoseAsset | 38 | Generic-only |
| Skeleton | 30 | Generic-only |
| ChooserTable | 23 | Generic-only |
| IKRigDefinition | 19 | Generic-only |
| NiagaraEmitter | 14 | Generic-only |
| IKRetargeter | 9 | Generic-only |
| BlendSpace / BlendSpace1D | 10 | Generic-only internals |
| AnimMontage | 5 | Generic-only internals |
| NiagaraDataChannelAsset | 6 | Generic-only |

This is why overall asset existence/dependency coverage is much broader than first-class semantic coverage.

## What “covered” should mean before universal traversal

The project-level traversal layer should not pretend every `assets.jsonl` record is equally understood.

Every traversal result should carry the semantic quality of the hop:

```text
canonical-structural
canonical-reference
derived-exact-join
generic-package-dependency
```

and each target entity should expose its subsystem coverage level.

That lets an AI distinguish:

```text
"this placed actor uses this material and we know its graph"
```

from:

```text
"this map depends on this NiagaraSystem, but Niagara internals are not indexed yet"
```

## Coverage gate and roadmap

Before treating universal graph traversal as a broadly complete project-understanding layer, fill these gaps in this order:

1. **Animation asset internals**
   - AnimSequence / AnimMontage / BlendSpace
   - Skeleton/socket/sync-marker/notify/curve relationships
   - Pose Search schemas/databases/channels
   - Chooser and Proxy Table assets
   - IK Rig / IK Retargeter relationships where needed
2. **Niagara + legacy Cascade**
   - systems, emitters, stack modules, renderers, parameters, events/data interfaces
   - enough legacy ParticleSystem structure to follow older projects
3. **Sequencer**
   - bindings, tracks, sections, channels/keyframes, subsequences, event/camera/animation/VFX/audio references
4. **MetaSounds + SoundCue/audio routing**
   - graph topology and authored inputs/outputs/references
5. **Enhanced Input and common gameplay-data assets**
   - InputAction, InputMappingContext, DataTables, Gameplay Tags where evidence shows they are important
6. **Project-level graph traversal/neighborhoods**
   - typed bounded traversal across all first-class and generic entities
   - provenance and coverage quality on every hop
7. **Additional specialist families**
   - promote geometry/physics/rendering/plugin-specific assets only when real corpora expose a project-understanding need

Traversal can be developed in parallel with these extractors, but it should expose uncovered asset families honestly rather than hiding them behind generic dependency edges.

## Regression corpora

Primary regression projects:

- Game Animation Sample — animation-heavy, Motion Matching/Pose Search emphasis
- Cropout Sample Project — compact gameplay/Blueprint/AI regression
- Content Examples — broad engine-feature and material/PCG/AI/VFX/audio/cinematic coverage

Occasional targeted probe:

- StackOBot — especially useful for World Partition descriptor references, LevelInstance/PackedLevelActor relationships, and additional Blueprint-node coverage
