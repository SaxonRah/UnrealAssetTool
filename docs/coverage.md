# Coverage matrix

This is the maintained answer to **“what does UnrealAssetTool actually understand?”**

The matrix distinguishes asset discovery from semantic depth. An asset appearing in `assets.jsonl` is not sufficient to call that family first-class.

## Coverage levels

| Level | Meaning |
| --- | --- |
| `first_class` | Dedicated normalized authored facts/topology, validation, SQLite/query exposure and project-graph integration where applicable. |
| `first_class_depth_pending` | Dedicated recognition and meaningful normalized structure exist, but important authored internals are still only reflection/raw-reference fallback. |
| `partial` | Useful project/world/Blueprint facts are captured, but there is no coherent subsystem model. |
| `generic_only` | Asset Registry/file/source fallback only; no subsystem-specific semantic extractor. |
| `external_or_excluded` | Target is outside the scanned scope or cannot be resolved to indexed project content. |

These names also align with the project graph's coverage vocabulary. A separate edge-quality axis distinguishes exact semantics/references from package-level fallback.

## Current schema baseline

```text
structural=12
world=12
animation=1
vfx=1
systems=4
derived=20
```

---

# Current first-class coverage

| Family | Coverage | What is understood | Important boundary |
| --- | --- | --- | --- |
| Files/source/config | `first_class` | Physical files, kinds, bounded text chunks | Not a C++ semantic compiler/indexer |
| Asset Registry | `first_class` fallback | Asset identity/class/package/tags/dependencies | Package dependency is not semantic object linkage |
| Blueprint/K2 | `first_class` | Graphs, nodes, pins, links, state, refs, functions/events/calls/data provenance/execution blocks plus generic semantic statements/control flow | Uncommon node-specific meaning may remain generic class/pin/property state |
| Blueprint user-defined enums | `first_class` | Enum identity, entries, raw/authored/display names and conservative readable enum decoration | Ambiguous enum typing is left raw rather than guessed |
| Animation Blueprint state machines | `first_class` | Machines, states, aliases/conduits, transitions, transition rules, pose/cache/link nodes | Runtime generated/compiled VM behavior is not simulated |
| UMG Widget Blueprint | `first_class_depth_pending` | Widget tree, properties, bindings, animations, animation bindings plus Blueprint graphs | Slate/runtime rendering/style semantics are not modeled as a separate graph |
| Control Rig / RigVM | `first_class_depth_pending` | Compact objects/pins/links/references and editor-link reconstruction | Full raw property dump is opt-in; richer RigVM opcode/runtime semantics are not modeled |
| Behavior Tree | `first_class` | Tree nodes, topology and properties | Runtime execution/debug state is out of scope |
| Blackboard | `first_class` | Keys/types/default authored data | Runtime values are out of scope |
| EQS | `first_class` | Queries/options/generators/tests/properties | Runtime query results are out of scope |
| StateTree | `first_class` | States, nodes, transitions, bindings/properties | Compiler/runtime state is not executed |
| PCG | `first_class` | Graphs, nodes, pins, edges, properties, parameters, context | Generated runtime/spatial output is not evaluated |
| Materials | `first_class` | Assets, expressions, root/expression edges, parameters, properties/references | Shader compilation/runtime resource graph is out of scope |
| Worlds/levels | `first_class` | World identity, persistent/classic streaming relationships | Runtime dynamically spawned state is out of scope |
| Actors/components | `first_class` | Placement, transforms, classes, ownership/attachments, tags, Blueprint identity | Runtime-only state is out of scope |
| Placed overrides/references | `first_class` | Archetype-diff authored state plus hard/soft UObject refs | Bounded reflection intentionally caps pathological data |
| Data Layers | `first_class` | Identity, hierarchy, runtime/editor state and DataLayerAsset association | Runtime activation state is not simulated |
| World Partition descriptors | `first_class` | Descriptor identity/GUID/package/class/refs/Data Layers/transforms/bounds | External actors are not deliberately loaded just to inspect them |
| Core animation assets | `first_class` | Sequence/Montage/BlendSpace settings, notifies, markers, sections, segments, samples | See animation-specific depth rows below |
| Skeleton | `first_class` | Bones, sockets, slots and metadata | SkeletalMesh/PhysicsAsset internals are separate gaps |
| Animation curves | `first_class` | Float/transform curves and individual keys/tangents | Compression/runtime evaluation is not modeled |
| Pose Search | `first_class` | Databases, schemas, channels, roles, interaction assets, normalization sets | Search index/runtime query results are not extracted |
| PoseAsset | `first_class` | Poses, tracks, transforms and curve values | Runtime pose blending not simulated |
| Chooser / Proxy | `first_class_depth_pending` | Tables, rows/columns/context, concrete struct types, raw settings/refs; supported enum columns are promoted into queryable decisions/predicates | Many uncommon column/value types remain lossless raw structs rather than guessed semantics |
| IK Rig / IK Retargeter | `first_class_depth_pending` | Bones/chains/goals/solvers, rig refs, ops and poses | Solver/op-specific semantics are mostly concrete type + raw authored state |
| Niagara | `first_class_depth_pending` | Systems, handles, emitters/versions, renderers, stages, scripts, data channels, parameter collections, effect types | Stateful module/function execution-stack semantics are not normalized |
| Niagara Stateless | `first_class` | Stateless emitters, ordered modules/renderers and child state | Runtime simulation output not evaluated |
| Cascade | `first_class` | System -> emitter -> LOD -> module topology and state | Runtime particle simulation not evaluated |
| LevelSequence / Sequencer | `first_class_depth_pending` | Bindings, tracks, sections, channels, timing/rates and reflected refs | Individual channel keys and family-specific track semantics are not normalized |
| MetaSound | `first_class_depth_pending` | Frontend nodes and exact node/vertex edge endpoints | Vertex declarations/literals/interfaces/class registry semantics are not normalized |
| SoundCue | `first_class_depth_pending` | Nodes, child counts, node state/references | No dedicated normalized SoundCue edge stream yet |
| Enhanced Input: InputAction/MappingContext | `first_class` | Actions, contexts, exact action/key mappings, trigger/modifier objects | Runtime input stack/user remapping state is out of scope |
| Common Input | `first_class_depth_pending` | Action tables and action-domain assets recognized; authored state/refs preserved | Row/domain semantics are not deeply normalized |
| General DataTable / CurveTable | `first_class` | DataTable row struct/type, rows/fields, exact object references; CurveTable rows and keys | Family-specific interpretation of arbitrary project row structs is intentionally not guessed |
| PrimaryDataAsset | `first_class_depth_pending` | PrimaryDataAsset identity plus generic reflected state/references | Arbitrary project-specific PrimaryDataAsset semantics are not normalized by family |
| Gameplay Tags project model | `first_class` | Settings, configured sources, merged project dictionary and redirects plus tag-bearing gameplay data | Exhaustive native C++ registration provenance/restricted-tag special cases and all cross-system tag semantics are not yet normalized |
| Mover | `first_class` | Mover Blueprint/component composition, movement modes, starting mode, shared settings, transitions and exact backend-class references; derived transition behaviors/routes | Runtime simulation/layered-move execution is not simulated |
| Gameplay Cameras | `first_class` | CameraAsset -> director, CameraRig roots/nodes/edges/transitions/prefab refs, generic Chooser selection decisions and polymorphic Blueprint camera-property providers/director context | Runtime camera evaluation/blending is not executed; polymorphic providers remain candidates unless runtime actor type disambiguates them |
| Typed project graph | `first_class` | Typed nodes/edges, provenance, coverage and quality classes | It reflects extractor depth; it must not imply unsupported subsystem semantics |

---

# Partial coverage

These systems are visible through existing generic layers, Blueprint/component state, world placement or reflected references, but do **not** yet have a dedicated subsystem model.

| Family | Current useful facts | Missing semantic model |
| --- | --- | --- |
| Gameplay Framework native classes | Blueprint subclasses/defaults plus placed Actor/component state | Native GameMode/GameState/PlayerState/Controller/Pawn relationship summary across project settings/maps |
| AI Perception | Component templates/placed components can be seen through Blueprint/world state | Sense configs, dominant sense, stimuli sources and sense relationships |
| Navigation | Nav actors/volumes/components can appear as world objects | NavMesh areas/costs, NavLink topology, agent settings and authored navigation project settings; generated NavMesh tile serialization is not a goal |
| Gameplay Ability System | GameplayAbility Blueprints still receive normal Blueprint graph coverage | GameplayAbility/GameplayEffect/AbilitySystemComponent/AttributeSet/Cue/tag/cost/cooldown relationships |
| Landscape/Foliage/HLOD | World actors/components/assets are discoverable | Landscape layer/material/component topology, foliage type/instance semantics, HLOD composition |
| SkeletalMesh / PhysicsAsset | Asset identity/references and use by animation assets can be seen | Skeleton/LOD/material/morph/cloth data and physics bodies/constraints |
| StaticMesh | Asset identity/references/material use can be seen generically | LOD/section/socket/collision/Nanite authored topology |
| PrimaryAssetLabel | Recognized systems asset plus reflected state | Broader Asset Manager rules/types/bundles/config are not modeled |

---

# Generic-only high-value gaps

Repository scanning has no dedicated semantic model yet for these major UE 5.8 families. They still benefit from universal file/Asset Registry/source indexing where present.

| Family | Why it matters for gameplay understanding | Suggested priority |
| --- | --- | --- |
| Smart Objects | Designer-authored interaction slots/behaviors/tags used by AI and players | **High** |
| ZoneGraph | Lane/zone topology used by Smart Objects/Mass/crowds/traffic | **High** when Mass/crowd projects are targeted |
| Mass Entity / Mass Gameplay | Entity configs, traits, processors, representation/spawn/StateTree composition | **High** for City Sample / large-scale AI |
| Gameplay Effects / GAS data | Core ability/effect/attribute relationships | **High** for Lyra/action/RPG projects |
| Dataflow | General-purpose node graph used by Geometry Collection/Chaos Cloth/Flesh and other authoring | Medium-high |
| Geometry Collection / Chaos destruction | Breakable geometry, clustering, materials and Dataflow links | Medium-high |
| AnimNext | New animation graph/data ecosystem not represented by animation schema 1 | Medium-high for forward-looking animation projects |
| Groom / Hair | Groom assets/bindings/physics relationships | Medium for character-heavy projects |
| Texture/RenderTarget/VirtualTexture internals | Rendering resource relationships beyond material refs | Medium-low for gameplay-focused indexing |
| Iris/replication configuration | Important runtime networking system but mostly code/config rather than content graph | Medium-low unless networking analysis becomes a goal |

The priorities above are about **AI/project-understanding value**, not engine importance in the abstract.

---

# Specific depth gaps discovered by repository audit

## 1. Systems graph coverage can still overstate recognition-only roots

`systems_assets.jsonl` contains both deeply normalized assets and recognition/reflection-only assets. Coverage policy must continue distinguishing assets whose family internals are normalized from assets that are primarily reflected state/references.

Examples that need conservative treatment include:

```text
PlayerMappableInputConfig
EnhancedInputPlatformData
SoundClass
SoundMix
SoundAttenuation
SoundConcurrency
PrimaryAssetLabel
Common Input action-domain assets
```

The project graph should not promote generic systems recognition into unsupported family semantics.

## 2. Sequencer has container depth but not key depth

`movie_scene_channels.jsonl` records channel type, key/value counts, default value and bounded raw serialized channel state. There is no dedicated MovieScene key stream.

**Recommended next depth:** normalize individual key times/values/interpolation for common channel types and add family semantics for high-value tracks such as subsequences, camera cuts, events, animation, audio and VFX.

## 3. SoundCue topology is incomplete

`sound_cue_nodes.jsonl` records nodes and child counts, while reflection preserves UObject references. There is no canonical `sound_cue_edges.jsonl`.

**Recommended fix:** emit exact parent/child node edges from the serialized SoundCue graph.

## 4. MetaSound topology is strong but semantic dataflow is shallow

Frontend nodes/edges are exact, but dedicated streams do not yet expose vertex declarations, literals/default values, interface members or class-registry metadata.

**Recommended next depth:** add typed vertex/literal rows before adding higher-level interpretations.

## 5. Gameplay Tags have a project model; remaining depth is provenance and joins

Systems schema 2 added settings, sources, merged dictionary and redirects, and schema 4 retains that model. The remaining tag work is narrower than the old gap: native C++ registration provenance where recoverable, restricted-tag special cases, replication/config depth and richer cross-system tag joins.

## 6. AI coverage omits perception/navigation semantics

Behavior Tree, Blackboard, EQS and StateTree are first-class, but AI Perception and authored Navigation settings/links/areas have no dedicated extractor.

**Recommended priority:** AI Perception first when a representative corpus is available, then authored navigation configuration/links/areas rather than serializing generated NavMesh data wholesale.

## 7. Remaining modern gameplay-framework gaps

Mover and Gameplay Cameras now have dedicated first-class models. The remaining Issue #14 modern-framework work is:

```text
Gameplay Ability System
Smart Objects
AI Perception
ZoneGraph + Mass
Dataflow / GeometryCollection
AnimNext
```

Corpus availability determines implementation order. City Sample is the intended evidence corpus for the next ZoneGraph/Mass slice; schema design should follow the observed UE 5.8 serialized/reflected shapes rather than API-name guesses.

---

# Issue #14 status

Accepted slices:

```text
Gameplay Tags project model
General DataTable / CurveTable / PrimaryDataAsset coverage
Mover
Gameplay Cameras
```

Still open:

```text
Gameplay Ability System
Smart Objects
AI Perception
ZoneGraph + Mass
Dataflow / GeometryCollection
AnimNext
```

Some accepted slices intentionally stop at a conservative boundary. For example, PrimaryDataAsset has first-class identity but project-specific payload semantics remain reflected/raw unless a broadly reusable family can be proven.

---

# Pipeline completeness audit

| Layer | Raw manifest/count validation | SQLite | Query surface | Project graph | Corpus validation |
| --- | --- | --- | --- | --- | --- |
| Structural / Blueprint / AI / PCG / material | Yes | Yes | Yes | Yes | GASP/Cropout/ContentExamples/StackOBot |
| World | Yes | Yes | Yes | Yes | ContentExamples/StackOBot + others |
| Animation | Yes | Yes | Yes | Yes | GASP + ContentExamples |
| VFX | Yes | Yes | Yes | Yes | ContentExamples + StackOBot/Niagara Examples |
| Systems schema 4 | Yes | Yes | Yes | Yes | StackOBot + ContentExamples + GASP |
| Project graph/neighborhoods | Yes | Yes | Yes | n/a | StackOBot + ContentExamples + GASP |

At the pipeline level, implemented families are wired end-to-end. The remaining gaps are primarily **domain depth and unmodeled subsystems**, not forgotten pack/query plumbing.

---

# Automated regression coverage audit

Focused Python regression coverage now includes:

- canonical/compact Blueprint pin and property storage;
- Blueprint semantic nodes/statements/control flow;
- user-defined enum extraction/rendering/inference;
- RigVM semantic bridging;
- world/animation/VFX stitching regressions;
- build freshness/fallback/cache policy;
- Chooser decision interpretation/storage/graph promotion;
- Mover extraction/behavior/graph semantics;
- Gameplay Camera canonical topology, director/provider behavior, enum readability and graph promotion;
- systems validation/SQLite/project-graph integration;
- derived freshness, neighborhood compaction and storage invariants.

Real UE corpora remain required because unit tests cannot substitute for actual serialized UE 5.8 shapes. New subsystem work should add synthetic invariants only after a representative corpus has established what the authored data actually looks like.

---

# What “complete” means now

The original planned indexer roadmap plus the accepted Issue #14 gameplay-data, Gameplay Tags, Mover and Gameplay Cameras slices are implemented and corpus-validated.

The repository is **not complete with respect to the entire Unreal Engine 5.8 content ecosystem**, and it should not claim to be. Expansion remains evidence-driven: acquire a representative corpus, inspect exact reflected/serialized facts, then normalize only semantics the evidence supports.

See [architecture.md](architecture.md), [schema.md](schema.md), [animation-schema-1.md](animation-schema-1.md), [vfx-schema-1.md](vfx-schema-1.md) and [systems-schema-4.md](systems-schema-4.md) for the maintained technical references. Historical systems contracts remain in [systems-schema-1.md](systems-schema-1.md) and [systems-schema-2.md](systems-schema-2.md).
