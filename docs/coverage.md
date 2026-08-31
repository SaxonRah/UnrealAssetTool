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
systems=1
derived=14
```

---

# Current first-class coverage

| Family | Coverage | What is understood | Important boundary |
| --- | --- | --- | --- |
| Files/source/config | `first_class` | Physical files, kinds, bounded text chunks | Not a C++ semantic compiler/indexer |
| Asset Registry | `first_class` fallback | Asset identity/class/package/tags/dependencies | Package dependency is not semantic object linkage |
| Blueprint/K2 | `first_class` | Graphs, nodes, pins, links, state, refs, functions/events/calls/data provenance/execution blocks | Uncommon node-specific meaning may remain generic class/pin/property state |
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
| Chooser / Proxy | `first_class_depth_pending` | Tables, rows/columns/context, concrete struct types, raw settings/refs | Many uncommon column/value types are lossless raw structs rather than dedicated semantics |
| IK Rig / IK Retargeter | `first_class_depth_pending` | Bones/chains/goals/solvers, rig refs, ops and poses | Solver/op-specific semantics are mostly concrete type + raw authored state |
| Niagara | `first_class_depth_pending` | Systems, handles, emitters/versions, renderers, stages, scripts, data channels, parameter collections, effect types | Stateful module/function execution-stack semantics are not normalized |
| Niagara Stateless | `first_class` | Stateless emitters, ordered modules/renderers and child state | Runtime simulation output not evaluated |
| Cascade | `first_class` | System -> emitter -> LOD -> module topology and state | Runtime particle simulation not evaluated |
| LevelSequence / Sequencer | `first_class_depth_pending` | Bindings, tracks, sections, channels, timing/rates and reflected refs | Individual channel keys and family-specific track semantics are not normalized |
| MetaSound | `first_class_depth_pending` | Frontend nodes and exact node/vertex edge endpoints | Vertex declarations/literals/interfaces/class registry semantics are not normalized |
| SoundCue | `first_class_depth_pending` | Nodes, child counts, node state/references | No dedicated normalized SoundCue edge stream yet |
| Enhanced Input: InputAction/MappingContext | `first_class` | Actions, contexts, exact action/key mappings, trigger/modifier objects | Runtime input stack/user remapping state is out of scope |
| Common Input | `first_class_depth_pending` | Action tables and action-domain assets recognized; authored state/refs preserved | Row/domain semantics are not deeply normalized |
| Gameplay Tag DataTables | `first_class_depth_pending` | DataTable rows with tag/comment | Full project tag dictionary/config/native tags/redirects are not normalized |
| Typed project graph | `first_class` | Typed nodes/edges, provenance, coverage and quality classes | It reflects extractor depth; it must not imply unsupported subsystem semantics |

---

# Partial coverage

These systems are visible through existing generic layers, Blueprint/component state, world placement or reflected references, but do **not** yet have a dedicated subsystem model.

| Family | Current useful facts | Missing semantic model |
| --- | --- | --- |
| Gameplay Framework native classes | Blueprint subclasses/defaults plus placed Actor/component state | Native GameMode/GameState/PlayerState/Controller/Pawn relationship summary across project settings/maps |
| AI Perception | Component templates/placed components can be seen through Blueprint/world state | Sense configs, dominant sense, stimuli sources and sense relationships |
| Navigation | Nav actors/volumes/components can appear as world objects | NavMesh tiles/areas/costs, NavLink topology, agent settings and navigation project settings |
| Gameplay Ability System | GameplayAbility Blueprints still receive normal Blueprint graph coverage | GameplayAbility/GameplayEffect/AbilitySystemComponent/AttributeSet/Cue/tag/cost/cooldown relationships |
| Mover | Mover components/classes can be visible as Blueprint/world component state | Movement modes, layered moves, transitions, input/output state and Mover-specific composition |
| Gameplay Cameras | Blueprint actors/components and referenced assets can be discovered generically | Camera Asset -> rig -> node -> transition -> director topology |
| Landscape/Foliage/HLOD | World actors/components/assets are discoverable | Landscape layer/material/component topology, foliage type/instance semantics, HLOD composition |
| SkeletalMesh / PhysicsAsset | Asset identity/references and use by animation assets can be seen | Skeleton/LOD/material/morph/cloth data and physics bodies/constraints |
| StaticMesh | Asset identity/references/material use can be seen generically | LOD/section/socket/collision/Nanite authored topology |
| PrimaryAssetLabel | Recognized systems asset plus reflected state | Broader Asset Manager rules/types/bundles/config are not modeled |

---

# Generic-only high-value gaps

Repository scanning found no dedicated extractor/model for these major UE 5.8 families. They still benefit from universal file/Asset Registry/source indexing where present.

| Family | Why it matters for gameplay understanding | Suggested priority |
| --- | --- | --- |
| Smart Objects | Designer-authored interaction slots/behaviors/tags used by AI and players | **High** |
| ZoneGraph | Lane/zone topology used by Smart Objects/Mass/crowds/traffic | **High** when Mass/crowd projects are targeted |
| Mass Entity / Mass Gameplay | Entity configs, traits, processors, representation/spawn/StateTree composition | **High** for City Sample / large-scale AI |
| General DataTable / CurveTable | Common project-owned gameplay data and asset references | **High**; broad, relatively tractable reflection target |
| Gameplay Tag project configuration | Config/native tag dictionary, sources, redirects, restricted tags | **High** because tags connect many systems |
| Gameplay Effects / GAS data | Core ability/effect/attribute relationships | **High** for Lyra/action/RPG projects |
| Dataflow | General-purpose node graph used by Geometry Collection/Chaos Cloth/Flesh and other authoring | Medium-high |
| Geometry Collection / Chaos destruction | Breakable geometry, clustering, materials and Dataflow links | Medium-high |
| AnimNext | New animation graph/data ecosystem not represented by animation schema 1 | Medium-high for forward-looking animation projects |
| Gameplay Camera assets | Camera rigs/transitions/directors are authored data assets | Medium |
| Groom / Hair | Groom assets/bindings/physics relationships | Medium for character-heavy projects |
| Texture/RenderTarget/VirtualTexture internals | Rendering resource relationships beyond material refs | Medium-low for gameplay-focused indexing |
| Iris/replication configuration | Important runtime networking system but mostly code/config rather than content graph | Medium-low unless networking analysis becomes a goal |

The priorities above are about **AI/project-understanding value**, not engine importance in the abstract.

---

# Specific depth gaps discovered by repository audit

## 1. Systems graph coverage currently overstates some roots

`systems_assets.jsonl` contains both deeply normalized assets and recognition/reflection-only assets. `scripts/uatool_project_graph.py` currently registers the whole `systems_assets` specialist stream as `first_class`, and the finalizer preserves that canonical root typing.

This can overstate coverage for assets such as:

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

These assets are useful and intentionally recognized, but several are primarily reflected state/references rather than fully normalized family internals.

**Recommended fix:** give systems asset kinds an explicit coverage policy (`first_class` vs `first_class_depth_pending`) and preserve it into project nodes/edges/neighborhoods instead of assigning blanket first-class coverage.

## 2. Sequencer has container depth but not key depth

`movie_scene_channels.jsonl` records channel type, key/value counts, default value and bounded raw serialized channel state. There is no dedicated MovieScene key stream.

**Recommended next depth:** normalize individual key times/values/interpolation for common channel types and add family semantics for high-value tracks such as subsequences, camera cuts, events, animation, audio and VFX.

## 3. SoundCue topology is incomplete

`sound_cue_nodes.jsonl` records nodes and child counts, while reflection preserves UObject references. There is no canonical `sound_cue_edges.jsonl`.

**Recommended fix:** emit exact parent/child node edges from the serialized SoundCue graph.

## 4. MetaSound topology is strong but semantic dataflow is shallow

Frontend nodes/edges are exact, but dedicated streams do not yet expose vertex declarations, literals/default values, interface members or class-registry metadata.

**Recommended next depth:** add typed vertex/literal rows before adding higher-level interpretations.

## 5. Gameplay Tags are only partially modeled

Gameplay Tag DataTables are normalized, but UE projects can define tags in config and C++ and can configure table sources, redirects, restricted tags and replication settings.

**Recommended fix:** add project-level Gameplay Tags config/native-source indexing and join tag references across supported systems.

## 6. AI coverage omits perception/navigation

Behavior Tree, Blackboard, EQS and StateTree are first-class, but AI Perception and Navigation have no dedicated extractor.

**Recommended priority:** AI Perception first (small, high semantic value), then authored navigation configuration/links/areas rather than serializing the generated NavMesh wholesale.

## 7. Modern gameplay framework gaps

Current UE 5.8 projects increasingly use Smart Objects, Mass, ZoneGraph, Mover, Gameplay Cameras and GAS. None has a dedicated model in this repository today.

**Recommended order for broad project understanding:**

```text
Gameplay Tags project model
General DataTables
GAS
Smart Objects
AI Perception
Mover
Gameplay Cameras
ZoneGraph + Mass
Dataflow / GeometryCollection
AnimNext
```

Corpus availability should still determine the actual implementation order.

---

# Pipeline completeness audit

| Layer | Raw manifest/count validation | SQLite | Query surface | Project graph | Corpus validation |
| --- | --- | --- | --- | --- | --- |
| Structural / Blueprint / AI / PCG / material | Yes | Yes | Yes | Yes | GASP/Cropout/ContentExamples/StackOBot |
| World | Yes | Yes | Yes | Yes | ContentExamples/StackOBot + others |
| Animation | Yes | Yes | Yes | Yes | GASP + ContentExamples |
| VFX | Yes | Yes | Yes | Yes | ContentExamples + StackOBot/Niagara Examples |
| Systems | Yes | Yes | Yes | Yes | StackOBot + ContentExamples + GASP |
| Project graph/neighborhoods | Yes | Yes | Yes | n/a | StackOBot + ContentExamples + GASP |

At the pipeline level, the planned indexed families are wired end-to-end. The remaining gaps are primarily **domain depth and unmodeled subsystems**, not forgotten pack/query plumbing.

---

# Automated regression coverage audit

The project has strong real-corpus validation but relatively little focused automated unit coverage for its Python surface.

Current `tests/` files:

```text
test_cleanup_compaction.py
test_derived_perf.py
test_neighborhood_priority.py
test_systems_graph.py
```

Strongly covered in unit/smoke tests:

- generated-value cleanup;
- schema-14 neighborhood compaction/reconstruction;
- derived freshness/performance helpers;
- neighborhood quality priority;
- systems/project-graph synthetic integration.

Underrepresented in focused tests:

- structural/base Blueprint derivation in `uatool_core.py`;
- world stitching;
- animation validators and animation stitching;
- VFX validators and VFX stitching;
- build freshness/fallback/cache policy;
- SQLite/query parity across specialist tables;
- manifest compatibility/error-path behavior.

The existing UE corpora catch many of these failures, but targeted Python tests would shorten feedback loops and make refactoring safer.

**Recommended testing priority:** animation/VFX/world derivation invariants first, then build-policy unit tests and query/SQLite parity.

---

# What “complete” means now

The original planned indexer roadmap is complete: Blueprint/world/AI/PCG/material/animation/VFX/Sequencer/audio/input and a typed provenance-aware project graph are all implemented and validated.

The repository is **not complete with respect to the entire Unreal Engine 5.8 content ecosystem**, and it should not claim to be. The next phase should be evidence-driven expansion into the high-value gaps above, while keeping unsupported families honestly marked as partial or generic-only.

See [architecture.md](architecture.md), [schema.md](schema.md), [animation-schema-1.md](animation-schema-1.md), [vfx-schema-1.md](vfx-schema-1.md) and [systems-schema-1.md](systems-schema-1.md) for the maintained technical references.