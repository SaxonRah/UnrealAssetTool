# UnrealAssetTool subsystem coverage

This document tracks what UnrealAssetTool understands as a first-class authored system versus what is only visible through generic Asset Registry identity/dependency data.

A generic asset record can tell us that an asset exists and what packages it depends on. A first-class extractor can tell us how the asset itself is structured, wired, configured, and related to gameplay.

## Coverage levels

| Level | Meaning |
| --- | --- |
| **First-class** | Dedicated canonical streams preserve authored structure/settings/topology. |
| **First-class, depth pending** | A dedicated model exists and captures the high-value authored structure, but important family-specific internals remain to be normalized. |
| **Partial** | Important structure is captured indirectly or only from surrounding systems. |
| **Generic-only** | Asset Registry identity/tags/dependencies and incidental references exist, but no dedicated internal extractor exists. |

## Current development baseline

```text
UnrealAssetTool:    0.7.0 development line
UE target:          5.8+
validated engine:   5.8.2
structural schema:  12
world schema:       12
animation schema:    1   (PR #5, under validation)
derived schema:     10
```

The animation schema is intentionally independent from structural/world/derived numbering.

## Project, world, and gameplay-program systems

| System | Coverage | Notes |
| --- | --- | --- |
| Physical files/source/config | **First-class** | Bounded source chunks plus file metadata. |
| Asset Registry | **First-class baseline** | Identity, class, tags, packages and direct package dependencies; universal fallback for unsupported families. |
| Worlds/maps/levels | **First-class** | World identity, persistent/streaming levels, actors, components, transforms, instance overrides, object references and Data Layers. |
| World Partition | **First-class** | Descriptor enumeration, parent/reference GUIDs, LevelInstance/PackedLevelActor child-world relationships. |
| Blueprint/K2 | **First-class** | Graphs, nodes, pins, exact edges, properties/references, functions/events, execution blocks, call bindings and bounded data provenance. |
| Animation Blueprints | **First-class** | AnimGraph/state-machine topology, transitions, cached poses, linked layers and common animation-node semantics. |
| UMG Widget Blueprints | **First-class** | Widget tree, properties, bindings, animations and Blueprint graph structure. |
| Control Rig / RigVM | **First-class** | Editor graph plus compact RigVM model and editor-to-model joins. |
| Behavior Trees | **First-class** | Tree hierarchy, nodes/services/decorators and Blackboard relationships. |
| Blackboards | **First-class** | Keys, types, inheritance and selector resolution. |
| EQS | **First-class** | Queries, options, generators, tests and relationships. |
| StateTree | **First-class** | States, tasks/evaluators, conditions, transitions, bindings and linked assets. |
| PCG | **First-class** | Graphs, nodes, pins, exact edges, settings, parameters and subgraphs. |
| Materials / Material Instances / Material Functions | **First-class** | Expression graph, root wiring, properties, parameters, texture/function references and derived visual relations/context. |
| World-to-system placement links | **First-class derived** | Derived schema 10 joins placed actors/components/worlds to Blueprint, AnimBP, Control Rig, UMG, AI, PCG and material targets with explicit evidence. |

## Animation schema 1

Animation schema 1 is currently the active validation work on PR #5. The first GASP run compiled and scanned successfully; the current branch adds the gaps revealed by that run.

| Asset family | Coverage | Current facts / remaining depth |
| --- | --- | --- |
| AnimSequence / sequence-base | **First-class** | Skeleton, play length, additive/root-motion state, notifies/states, timing, sync markers, reflected settings/references, float/transform curves and rich-curve keys. Compression-specific internals are not normalized. |
| AnimMontage | **First-class** | Sequence-base facts plus sections, next-section links, slots, segments/source animations and marker data. More blend/branching metadata can be promoted if needed. |
| BlendSpace / BlendSpace1D / AimOffset | **First-class** | Authored axes, samples, coordinates, source animations and marker data. Unused backing axis slots are filtered. |
| Skeleton | **First-class** | Bone hierarchy/reference transforms, sockets, virtual-bone count, curve metadata, notify/marker names and reflected references. Slot-group/retarget depth can grow later. |
| Pose Search Database | **First-class** | Database -> schema, source entries, settings and references. |
| Pose Search Schema | **First-class** | Feature channels, concrete channel classes/settings/references and role/Skeleton/MirrorDataTable entries. |
| Pose Search Interaction Asset | **First-class** | Multi-role interaction items, roles, source animations, preview meshes, origins and warping weights. |
| Pose Search Normalization Set | **First-class** | Set identity and database membership. |
| Mirror Data Table | **First-class** | Skeleton, mirror axis and source/mirrored row mappings with type/enabled state. |
| PoseAsset | **First-class, depth pending** | Asset identity, Skeleton and reflected authored state/references are preserved; pose-level normalization remains. |
| Chooser Table | **First-class, depth pending** | Identity plus bounded reflected authored properties/references; row/column evaluation semantics remain. |
| ProxyTable / ProxyAsset | **First-class, depth pending** | Distinct identities plus reflected properties/references; entry/fallback semantics remain. |
| IK Rig / IK Retargeter | **First-class, depth pending** | Identity plus reflected properties/references; chains/goals/solvers/retarget mappings remain. |
| Motion Warping | **Partial** | Can surface through Blueprint/world/asset references; no dedicated normalized model yet. |
| SkeletalMesh | **Generic-only** | Skeleton/material/LOD/morph/physics internals are not yet normalized. |
| PhysicsAsset | **Generic-only** | Bodies/constraints and skeletal association are not yet normalized. |

### GASP animation evidence

The first UE 5.8.2 schema-1 GASP scan produced:

```text
animation_assets                 2518
animation_notifies              13373
animation_sync_markers             69
montage_sections                  137
animation_segments                137
blend_space_axes                   45   # raw backing slots before normalization
blend_space_samples                157
skeletons                           11
skeleton_bones                    2866
skeleton_sockets                    58
pose_search_databases              155
pose_search_database_assets       2138
pose_search_schemas                 33
pose_search_channels                74
pose_search_schema_skeletons        37
animation_optional_assets           31
animation_properties            106033
animation_references             46620
```

Validated invariants:

- all 155 Pose Search databases resolve to one of 33 schemas;
- all 2,138 declared database entries have emitted rows;
- schema totals exactly match 74 channel rows and 37 role/Skeleton rows;
- all 37 schema Skeleton references resolve;
- observed channel families include Trajectory, Group, Position, Curve, Pose, Heading and a project Blueprint-defined custom feature channel;
- structural schema 12, world schema 12, derived schema 10 and the 1,099 GASP world-system relations remained stable.

The run exposed 24 `PoseSearchInteractionAsset` database targets, four normalization sets, actual curve-key needs, the project Mirror Data Table, phantom BlendSpace backing axes and a ProxyAsset/ProxyTable classification ambiguity. Those are addressed on the current PR branch and await the next GASP validation scan.

## VFX / particles

This is the next major first-class coverage gap after animation schema 1 stabilizes.

| Asset family | Coverage | Missing authored internals |
| --- | --- | --- |
| Niagara System | **Generic-only** | System/emitter composition, stacks, modules, renderers, parameters, bindings, events and data interfaces. |
| Niagara Emitter | **Generic-only** | Emitter stack/module/renderer structure and settings. |
| Niagara Script | **Generic-only** | Script usage, rapid-iteration parameters and module/function relationships. |
| Niagara Data Channel | **Generic-only** | Variables/settings/readers/writers. |
| Niagara Effect Type | **Generic-only** | Scalability/culling/significance settings. |
| Legacy Cascade ParticleSystem | **Generic-only** | Emitters/modules/LOD/material relationships. |

Content Examples contains substantial Niagara and Cascade content, so this is a real blind spot rather than a theoretical future feature.

## Cinematics

| Asset family | Coverage | Missing authored internals |
| --- | --- | --- |
| LevelSequence / Sequencer | **Generic-only** | Object bindings, tracks, sections, channels/keyframes, subsequences, events, camera cuts and animation/audio/VFX references. |
| Template/Camera Animation Sequence | **Generic-only** | Sequence tracks/channels/bindings. |

World scans can identify placed LevelSequenceActors and references, but the sequence assets themselves are not decomposed yet.

## Audio

| Asset family | Coverage | Missing authored internals |
| --- | --- | --- |
| MetaSound Source / Patch | **Generic-only** | Graph nodes/pins/edges, interfaces, inputs/outputs, literals and referenced patches/waves. |
| SoundCue | **Generic-only** | Cue graph topology and wave relationships. |
| SoundWave | **Generic-only** | Audio metadata beyond Asset Registry facts. |
| SoundClass / SoundMix / SoundAttenuation | **Generic-only** | Routing, hierarchy, modifiers and spatialization/attenuation settings. |

## Input and gameplay data

| Asset family | Coverage | Missing authored internals |
| --- | --- | --- |
| Enhanced Input InputAction | **Generic-only** | Value type, triggers, modifiers and consumption/reservation settings. |
| InputMappingContext | **Generic-only** | Key/action mappings, triggers/modifiers and priority relationships. |
| DataTable / CompositeDataTable / CurveTable | **Generic-only** | Row schemas and normalized row values. |
| UserDefinedStruct / UserDefinedEnum | **Partial** | Blueprint type usage is preserved; standalone definitions are not yet dedicated entities. |
| Gameplay Tags | **Partial** | Referenced tags are visible through reflection; project-wide dictionary/redirect/category semantics are not modeled. |

## Rendering, geometry, physics, and environment

The following remain primarily Asset Registry/world-reference entities and should be promoted when their internals materially affect project understanding:

- StaticMesh
- SkeletalMesh
- Texture families
- GeometryCollection/Dataflow
- Groom/GroomBinding
- Optimus deformers
- PhysicalMaterial
- Landscape layer/grass assets
- Foliage types
- HLOD layers
- render targets and atlases

## What “covered” means for traversal

Future project-neighborhood traversal must never flatten all evidence into one confidence level. Every hop should retain provenance such as:

```text
canonical-structural
canonical-reference
derived-exact-join
generic-package-dependency
```

and every target should expose its subsystem coverage level. An AI must be able to distinguish:

```text
this placed actor uses this material and we know the material graph
```

from:

```text
this map depends on this Niagara System, but Niagara internals are not indexed yet
```

## Coverage gate and roadmap

Current order:

1. **Finish animation schema 1 validation**
   - current GASP deep pass
   - Content Examples breadth validation
   - then derived animation relations/context
2. **Niagara + legacy Cascade**
3. **Sequencer**
4. **MetaSounds + SoundCue/audio routing**
5. **Enhanced Input and common gameplay-data assets**
6. **Typed bounded project-level traversal/neighborhoods** with provenance/coverage quality on every hop
7. Promote additional geometry/physics/rendering/plugin families when real corpora demonstrate the need

Traversal can be developed in parallel, but it should expose unsupported families honestly rather than hiding them behind generic dependency edges.

## Regression corpora

Primary:

- Game Animation Sample — animation-heavy, Motion Matching/Pose Search emphasis
- Cropout Sample Project — compact gameplay/Blueprint/AI regression
- Content Examples — broad engine-feature/material/PCG/AI/VFX/audio/cinematic coverage

Targeted:

- StackOBot — World Partition descriptor references, LevelInstance/PackedLevelActor relationships, PCG and additional Blueprint-node coverage
