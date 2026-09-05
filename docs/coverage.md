# Coverage matrix

This is the maintained answer to **“what does UnrealAssetTool actually understand?”**

Current release contract: **1.0.0-beta.1**. See [release-contract.md](release-contract.md).

The matrix distinguishes asset discovery from semantic depth. An asset appearing in `assets.jsonl` is not sufficient to call that family first-class. `capabilities.json` exposes the same contract in machine-readable form for each corpus.

## Coverage levels

| Level | Meaning |
| --- | --- |
| `first_class` | Dedicated normalized authored facts/topology, validation, SQLite/query exposure and project-graph integration where applicable. |
| `first_class_depth_pending` | Dedicated recognition and meaningful normalized structure exist, but important authored internals are still only reflection/raw-reference fallback. |
| `partial` | Useful project/world/Blueprint facts are captured, but there is no coherent subsystem model. |
| `generic_only` | Asset Registry/file/source fallback only; no subsystem-specific semantic extractor. |
| `external_or_excluded` | Target is outside the scanned scope or the relevant canonical pass is absent from this corpus. |

These names align with the project graph and capability-contract vocabulary. A separate edge-quality axis distinguishes exact semantics/references from package-level fallback.

## Current schema baseline

```text
structural=13
world=12
animation=4
mesh=1
world_geometry=1
vfx=1
systems=11
derived=40
capabilities=1
```

---

# Current first-class coverage

| Family | Coverage | What is understood | Important boundary |
| --- | --- | --- | --- |
| Files/source/config | `first_class` | Physical files, kinds, bounded text chunks | Not a C++ semantic compiler/indexer |
| Asset Registry | `first_class` fallback | Asset identity/class/package/tags/dependencies | Package dependency is not semantic object linkage |
| Blueprint/K2 | `first_class` | Graphs, nodes, pins, links, state, refs, functions/events/calls/data provenance/execution blocks plus generic semantic statements/control flow; structural-schema-13 delegate member/scope provenance; exact project-authored macro graph/interface bindings, schema-33 cross-graph macro execution edges, schema-34 joined macro data-provenance routes, schema-35 direct-internal Blueprint function call/return topology, schema-36 function data provenance, and schema-38 exact authored delegate bindings | Static authored topology only: macro/function bodies are not inlined/simulated, cross-graph expressions are not executed/substituted, split call-site struct projections do not claim uncaptured callee member identity, interface dispatch implementations and latent scheduling are not guessed, engine StandardMacros remain external unless captured, and runtime Blueprint VM state is not executed |
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
| StaticMesh | `first_class` | Authored source-model LOD/build/reduction settings, material slots, sockets, collision primitives/settings and exact derived-schema-30 relationships | Render buffers, generated render LOD resources, Nanite runtime resources and runtime physics state are excluded |
| Landscape / Foliage / HLOD authored geometry | `first_class` | Landscape/component/layer allocation and material relationships, foliage type/info/instance authored state, HLOD layer/composition semantics and exact derived-schema-31 relationships | Generated/render geometry, runtime vegetation state, HISM render-instance internals and runtime HLOD state are excluded |
| Worlds/levels | `first_class` | World identity, persistent/classic streaming relationships | Runtime dynamically spawned state is out of scope |
| Actors/components | `first_class` | Placement, transforms, classes, ownership/attachments, tags, Blueprint identity | Runtime-only state is out of scope |
| Placed overrides/references | `first_class` | Archetype-diff authored state plus hard/soft UObject refs | Bounded reflection intentionally caps pathological data |
| Data Layers | `first_class` | Identity, hierarchy, runtime/editor authored state and DataLayerAsset association | Runtime activation is not simulated |
| World Partition descriptors | `first_class` | Descriptor identity/GUID/package/class/refs/Data Layers/transforms/bounds | External actors are not deliberately loaded only to inspect them |
| Core animation assets | `first_class` | Sequence/Montage/BlendSpace settings, notifies, markers, sections, segments, samples | See animation-specific depth rows below |
| Skeleton | `first_class` | Bones, sockets, slots and metadata | Runtime pose/deformation state is not modeled |
| SkeletalMesh / PhysicsAsset | `first_class` | Authored SkeletalMesh source-model LODs/build settings, material slots, morph targets, clothing membership/configs; PhysicsAsset bodies, collision primitives, constraints, profiles and exact derived-schema-29 relationships | Render buffers, runtime skinning/pose, cloth simulation, Chaos solver state and live collision/contact state are excluded |
| Motion Warping | `first_class` | Exact authored Motion Warping notify windows, notify-owned RootMotionModifier templates/classes, common warp policy, typed editable modifier properties, target-name symbols and active bone-provider relationships; exact derived-schema-32 graph | Live warp targets, active runtime modifiers, root-motion evaluation, trajectory/runtime transforms and playback state are excluded |
| Animation curves | `first_class` | Float/transform curves and individual keys/tangents | Compression/runtime evaluation is not modeled |
| Pose Search | `first_class` | Databases, schemas, channels, roles, interaction assets, normalization sets | Search index/runtime query results are not extracted |
| PoseAsset | `first_class` | Poses, tracks, transforms and curve values | Runtime pose blending not simulated |
| Chooser / Proxy | `first_class_depth_pending` | Tables, rows/columns/context, concrete struct types, raw settings/refs; supported enum columns are promoted into queryable decisions/predicates | Many uncommon column/value types remain lossless raw structs rather than guessed semantics |
| IK Rig / IK Retargeter | `first_class_depth_pending` | Bones/chains/goals/solvers, rig refs, ops and poses | Solver/op-specific semantics are mostly concrete type + raw authored state |
| Niagara | `first_class_depth_pending` | Systems, handles, emitters/versions, renderers, stages, scripts, data channels, parameter collections, effect types | Stateful module/function execution-stack semantics are not normalized |
| Niagara Stateless | `first_class` | Stateless emitters, ordered modules/renderers and child state | Runtime simulation output not evaluated |
| Cascade | `first_class` | System -> emitter -> LOD -> module topology and state | Runtime particle simulation output not evaluated |
| LevelSequence / Sequencer | `first_class_depth_pending` | Bindings, tracks, sections, channels, timing/rates and reflected refs | Individual channel keys and family-specific track semantics are not normalized |
| MetaSound | `first_class_depth_pending` | Frontend nodes and exact node/vertex edge endpoints | Vertex declarations/literals/interfaces/class registry semantics are not normalized |
| SoundCue | `first_class_depth_pending` | Nodes, child counts, node state/references | No dedicated normalized SoundCue edge stream yet |
| Enhanced Input: InputAction/MappingContext | `first_class` | Actions, contexts, exact action/key mappings, trigger/modifier objects | Runtime input stack/user remapping state is out of scope |
| Common Input | `first_class_depth_pending` | Action tables and action-domain assets recognized; authored state/refs preserved | Row/domain semantics are not deeply normalized |
| General DataTable / CurveTable | `first_class` | DataTable row struct/type, rows/fields, exact object references; CurveTable rows and keys | Family-specific interpretation of arbitrary project row structs is intentionally not guessed |
| PrimaryDataAsset | `first_class_depth_pending` | PrimaryDataAsset identity plus generic reflected state/references | Arbitrary project-specific payload semantics are not normalized by family |
| Gameplay Tags project model | `first_class` | Settings, configured sources, merged project dictionary and redirects plus tag-bearing gameplay data | Exhaustive native C++ registration provenance/restricted-tag special cases and all cross-system tag semantics are not yet normalized |
| Mover | `first_class` | Mover Blueprint/component composition, movement modes, starting mode, shared settings, transitions and exact backend-class references; derived transition behaviors/routes | Runtime simulation/layered-move execution is not simulated |
| Gameplay Cameras | `first_class` | CameraAsset -> director, CameraRig roots/nodes/edges/transitions/prefab refs, generic Chooser selection decisions and polymorphic Blueprint camera-property providers/director context | Runtime camera evaluation/blending is not executed; polymorphic providers remain candidates unless runtime actor type disambiguates them |
| Mass Entity / Mass Gameplay | `first_class` | EntityConfig assets, parent configs, ordered Traits, MassSpawner entity-type composition/generator inheritance, MassAgent components and exact semantic graph relationships | Runtime Mass processor/archetype execution and ECS state are not simulated |
| ZoneGraph authored shapes | `first_class` | Placed ZoneShape/ZoneShapeComponent identity, authored shape settings, ordered FZoneShapePoint geometry/settings and exact world/shape/component/point graph relationships | Generated `FZoneGraphStorage` lanes/lane points/lane links and transient connector caches are explicitly not claimed |
| Gameplay Ability System | `first_class` | GameplayAbility identity/defaults/triggers/cost/cooldown; Ability Sets/grants; GameplayEffects/components/modifiers/executions/cues; Gameplay Cues; AttributeSets/attributes; exact schema-22 graph promotion | Active specs, live grants/effects, prediction, replicated ASC state, runtime cue history and live attribute values are not captured |
| Smart Objects | `first_class` | Definition identity, ordered slots, default/slot behaviors, world-condition/selection schemas, reflected behavior properties and exact schema-23 graph semantics | Runtime occupancy, claims, reservations, subsystem handles and execution history are not captured |
| AI Perception | `first_class` | Authored perception-component templates, ordered sense configs, dominant sense, sense implementations/settings, stimuli-source templates, ordered registered senses and exact schema-24 graph semantics | Live listener state, perceived actors, stimulus history, runtime registration state and sense-query results are not captured |
| Dataflow | `first_class` | Project-wide `UDataflow` graphs, concrete node structs, ordered input/output pins, exact links, authored asset/node properties and direct object references with exact schema-25 graph semantics | Runtime graph evaluation/results are not captured; higher-level Hair/Cloth/Flesh/Vehicles semantics are not inferred merely from Dataflow use |
| Geometry Collection / Chaos destruction | `first_class` | Authored clustering, damage, connection, mass/sleep/removal, SizeSpecificData, physics material, DataflowInstance/Overrides and nullable DataflowAsset state with exact schema-25 graph semantics | `GeometrySource` construction provenance is excluded; solver state, dynamic transforms, live break/collision/removal history, cache playback and runtime Field results are not captured |
| AnimNext / UAF | `first_class` | Exact `UAFSystem`/`UAFAnimGraph` identity, entries, variables/defaults/bindings, authored components, runtime entry points, editor-side RigVM graphs/nodes/pins/links and exact variable-node resolution with schema-26 graph semantics | No RigVM execution, current pose/value state, ticking, runtime event execution, injection history or transient graph-instance state |
| Authored Navigation | `first_class` | NavArea costs/inheritance/agent masks and meta-area mappings; NavigationSystem/agent policy; simple-link/SmartLink defaults; modifier/invoker/bounds defaults; authored Recast defaults; exact schema-27 semantic relations | World schema 12 owns placed actors/components/transforms/instance overrides and world link endpoints; generated Recast instances/tiles/polys, path queries and runtime navigation state are excluded |
| Gameplay Framework | `first_class` | Exact/transitive Blueprint framework identity, explicit GameMode class selectors, per-world `DefaultGameMode`, project `GameMapsSettings`, Pawn/Character -> AIController class joins and exact schema-28 graph semantics | No runtime possession/spawn/GameMode simulation; inherited native selector values absent from authored rows are not invented; systems stays independently versioned |
| Typed project graph | `first_class` | Typed nodes/edges, provenance, coverage and quality classes | It reflects extractor depth; it must not imply unsupported subsystem semantics |
| Capability contract | `first_class` | Corpus schema versions, tool/corpus coverage, canonical streams, derived relations, runtime boundaries, partial-corpus state and acceptance provenance | It describes evidence available to the corpus; it does not manufacture new semantic facts |

---

# Partial coverage

These systems are visible through existing generic layers, Blueprint/component state, world placement or reflected references, but do **not** yet have a dedicated subsystem model.

| Family | Current useful facts | Missing semantic model |
| --- | --- | --- |
| PrimaryAssetLabel | Recognized systems asset plus reflected state | Broader Asset Manager rules/types/bundles/config are not modeled |

---

# Generic-only high-value gaps

Repository scanning has no dedicated semantic model yet for these major UE 5.8 families. They still benefit from universal file/Asset Registry/source indexing where present.

| Family | Why it matters for gameplay understanding | Suggested priority |
| --- | --- | --- |
| Groom / Hair | Groom assets/bindings/physics relationships beyond the reusable Dataflow substrate | Medium for character-heavy projects |
| Texture/RenderTarget/VirtualTexture internals | Rendering resource relationships beyond material refs | Medium-low for gameplay-focused indexing |
| Iris/replication configuration | Important runtime networking system but mostly code/config rather than content graph | Medium-low unless networking analysis becomes a goal |

The priorities above are about **AI/project-understanding value**, not engine importance in the abstract.

---

# Specific depth gaps discovered by repository audit

## 1. Systems graph coverage must remain conservative

`systems_assets.jsonl` contains both deeply normalized assets and recognition/reflection-only assets. Coverage policy must continue distinguishing assets whose family internals are normalized from assets that are primarily reflected state/references.

Examples that require conservative treatment include:

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

The project graph and `capabilities.json` must not promote generic recognition into unsupported family semantics.

## 2. Sequencer has container depth but not key depth

`movie_scene_channels.jsonl` records channel type, key/value counts, default value and bounded raw serialized channel state. There is no dedicated MovieScene key stream.

**Recommended next depth:** normalize individual key times/values/interpolation for common channel types and add family semantics for high-value tracks such as subsequences, camera cuts, events, animation, audio and VFX.

## 3. SoundCue topology is incomplete

`sound_cue_nodes.jsonl` records nodes and child counts, while reflection preserves UObject references. There is no canonical `sound_cue_edges.jsonl`.

**Recommended fix:** emit exact parent/child node edges from the serialized SoundCue graph.

## 4. MetaSound topology is strong but semantic dataflow is shallow

Frontend nodes/edges are exact, but dedicated streams do not yet expose vertex declarations, literals/default values, interface members or class-registry metadata.

**Recommended next depth:** add typed vertex/literal rows before adding higher-level interpretations.

## 5. Gameplay Tags remaining depth is provenance and joins

The project tag model is first-class. Remaining tag work is narrower: native C++ registration provenance where recoverable, restricted-tag special cases, replication/config depth and richer cross-system tag joins.

## 6. Authored Navigation boundary is authored/default plus world-instance split ownership

Systems schema 11 and derived schema 27 are accepted on ContentExamples UE 5.8.2. The normalized systems model covers NavArea definitions/masks/inheritance/meta mappings, NavigationSystem and configured agent policy, link/modifier/invoker/bounds class defaults and authored Recast defaults.

World schema 12 remains authoritative for placed Navigation actors/components, transforms, per-instance overrides and world-authored link endpoints. Generated RecastNavMesh instances/tiles/polys, path-query results, rebuild history and live path-following state are deliberate non-claims.

The accepted systems corpus contains 7 NavArea definitions, 16 explicit meta-area agent mappings, 2 system rows, 1 configured agent, 2 link defaults, 2 modifier defaults, 1 invoker default, 1 bounds default and 1 Recast-default row, and verifies exactly 27 specialist schema-27 edges.

See [authored-navigation-schema11.md](authored-navigation-schema11.md).

## 7. Mass/ZoneGraph boundary is authored, not generated

Systems schema 5 accepts City Sample Mass configuration/spawner/agent structure and authored placed ZoneShapes as first-class. Generated ZoneGraph storage remains a deliberate non-claim until representative evidence proves a stable authored/serializable representation.

This also prevents a ZoneGraph-capable Mass spawn generator from being linked to a particular placed ZoneShape without canonical evidence for that binding.

## 8. GAS boundary is authored/default state, not runtime ASC state

Systems schema 6 and derived schema 22 are accepted on Lyra. The remaining GAS boundary is intentional rather than an open coverage defect: no active GameplayEffect specs, live granted ability specs, prediction state, replicated runtime AbilitySystemComponent state, live attribute mutation history or runtime cue execution is claimed.

See [systems-schema-6.md](systems-schema-6.md) and [gas-evidence.md](gas-evidence.md).

## 9. AI Perception boundary is authored, not runtime perception state

Systems schema 8 and derived schema 24 are accepted on ContentExamples. The normalized model covers authored listener templates, sense configs/settings, dominant sense and stimuli-source registrations while deliberately excluding live listeners, perceived actors, stimulus history and runtime registration/query state.

See [ai-perception-schema8.md](ai-perception-schema8.md).

## 10. Dataflow / Geometry Collection boundary is authored, not evaluated Chaos state

Systems schema 9 and derived schema 25 are accepted on ContentExamples. Dataflow is modeled as a reusable project-wide graph substrate; Geometry Collection is modeled as authored destruction behavior. The accepted corpus contains 12 Dataflows and 29 Geometry Collections with an exact 4,595-edge schema-25 specialist graph.

All 29 representative collections have `DataflowAsset=None`, so no Geometry Collection -> Dataflow relationship is manufactured. `GeometrySource` remains excluded from the specialist behavioral surface.

See [dataflow-chaos-schema9.md](dataflow-chaos-schema9.md).

## 11. AnimNext / UAF boundary is authored/default, not runtime execution

Systems schema 10 and derived schema 26 are accepted on the GameAnimationSample-hosted UE 5.8.2 representative UAF corpus. The normalized model covers exact `UAFSystem`/`UAFAnimGraph` identity, entries, variables, components, runtime entry points, editor-side RigVM topology and exact RigVM variable-node -> UAF declaration resolution.

The real acceptance inspected 11 assets from the explicitly enabled UAF plugin roots, promoted exactly 3 loaded first-class UAF assets, emitted 6 graphs / 22 nodes / 90 pins / 19 links with zero truncated values, and verified exactly 213 specialist schema-26 edges.

No VM execution, live pose/value state, ticking, runtime event execution, injection history or transient graph instances are claimed.

See [animnext-uaf-schema10.md](animnext-uaf-schema10.md).

## 12. Gameplay Framework is a derived join, not another systems pass

Derived schema 28 is accepted on the full ContentExamples UE 5.8.2 corpus. It joins structural schema 12 Blueprint/CDO facts, world schema 12 WorldSettings facts, and exact `GameMapsSettings` config assignments into a deterministic Gameplay Framework relationship layer.

The accepted corpus contains 36 framework Blueprints with 4 transitive framework inheritance cases, 15 explicit GameMode selector overrides, 70 unique world `DefaultGameMode` overrides, 5 non-null project `GameMapsSettings` assignments, and verifies exactly 187 schema-28 edges.

The representative full corpus truthfully remains systems schema 9 because it predates later UAF and Navigation systems captures. The derived-28 compatibility policy may reuse that older successful systems pass only after Gameplay Framework acceptance and only when every manifest-declared stream/count self-validates. It does not claim missing systems-10/11 content.

Runtime spawn/possession/GameMode state and inherited native selector values absent from authored rows remain explicit non-claims.

See [gameplay-framework-derived28.md](gameplay-framework-derived28.md).

## 13. SkeletalMesh / PhysicsAsset is authored topology, not runtime simulation

Animation schema 3 and derived schema 29 promote exact authored SkeletalMesh and PhysicsAsset structure: source-model LODs/build settings, materials, morph/clothing membership, PhysicsAsset bodies/shapes/constraints/profiles and exact owner-scoped bone relationships.

Render resources, runtime skinning/current pose, cloth simulation, Chaos solver state, generated runtime bodies/constraints, contacts and break history remain explicit non-claims.

See [animation-schema-3.md](animation-schema-3.md).

## 14. StaticMesh is authored source topology, not render-resource topology

Mesh schema 1 and derived schema 30 model authored StaticMesh source LOD/build/reduction settings, material slots, sockets and authored collision/settings. The accepted real corpus verifies exactly 1,789 specialist edges.

Render buffers, generated render sections/vertex/index resources, Nanite runtime resources and runtime physics state are excluded.

See [staticmesh-schema-1.md](staticmesh-schema-1.md).

## 15. Landscape / Foliage / HLOD is authored geometry, not generated/render state

World-geometry schema 1 and derived schema 31 normalize authored Landscape/component/layer-allocation/material state, Foliage type/info/instance state and HLOD authored composition while preserving world schema 12 as the authority for placement and transforms.

Generated terrain/render resources, HISM render-instance internals, runtime vegetation simulation and runtime HLOD state are not claimed.

## 16. Motion Warping is authored configuration, not live warp state

Animation schema 4 and derived schema 32 are accepted on UE 5.8.2 GASP. The representative corpus contains 145 exact Motion Warping notify windows, 145 notify-owned modifier templates, 2,565 editable modifier-property rows and exactly 540 specialist semantic edges.

Target names and provider-gated bone names are authored symbols/relationships only. Live `FMotionWarpingTarget` arrays, active runtime modifiers, root-motion evaluation, current target transforms, trajectory state and playback remain explicit non-claims.

See [animation-schema-4-motion-warping.md](animation-schema-4-motion-warping.md).

## 17. Blueprint macro interprocedural flow is static cross-graph topology, not VM execution

Blueprint semantic schema 4 proves exact project-authored macro graph identity and call-site/interface pin bindings. Derived schema 33 builds on those proof edges plus canonical execution edges and existing graph-local basic blocks to expose cross-graph macro control flow without flattening the authored graphs.

The accepted GASP evidence behind the promotion contains 12 exact executable project macro instances, 14 exact caller-block -> macro-entry-block bridges, 9 exact macro-exit -> caller-continuation bridges and 8 authored terminal/unconnected macro exits, with zero bridge mismatches or duplicate block assignments.

An exact macro interface may expose exec-shaped input/output pins even when the authored
call-site node is completely disconnected. Execution participation is therefore proven
from canonical caller-graph execution edges, not from interface shape alone. An
exec-shaped macro with zero incoming and zero outgoing caller execution edges has no
caller execution block and emits no interprocedural execution edge or terminal; its
ordinary macro/data evidence remains available. Conversely, any macro with canonical
caller execution wiring but no caller block remains a hard derivation error.

Derived schema 33 adds:

- `blueprint_interprocedural_execution_edges.jsonl` for real cross-graph `macro_enter` and `macro_return` block edges;
- `blueprint_interprocedural_execution_terminals.jsonl` for exact macro exit endpoints with no canonical call-site continuation.

Graph-local `blueprint_execution_block_edges.jsonl` remains unchanged and authoritative within each graph. The interprocedural layer does not inline macro bodies, execute Blueprint VM code, infer engine StandardMacros behavior, or invent a continuation for an unconnected output.

## 18. Blueprint macro data provenance is joined evidence, not cross-graph evaluation

Derived schema 34 advances Blueprint interprocedural schema to version 2 and materializes one `blueprint_interprocedural_data_routes.jsonl` row per exact non-exec project-macro binding. The route joins existing canonical evidence without replacing it: schema-4 call/interface pin identity, caller-side data edges or authored call-site defaults, macro-body consumer edges, output dependency provenance and caller-side output consumers.

The accepted GASP evidence behind the promotion contains 46 exact macro data inputs and 1 exact macro data output. All 46 inputs are bridge-ready: 40 have connected caller sources and 6 use authored call-site values, all 46 are consumed by macro bodies, and those interface pins fan out through 94 canonical body-consumer edges. The single output has one internal source edge, one exact dependency-provenance row and one caller consumer. No data-provenance mismatches were observed.

The route stream deliberately does not substitute expressions across graph boundaries, inline macro bodies, manufacture values for unconnected pins, or claim Blueprint VM evaluation. Graph-local `blueprint_edges.jsonl` and `blueprint_data_dependencies.jsonl` remain the authoritative topology/provenance inputs.

## 19. Blueprint function execution requires an executable callsite and a reachable callee frontier

Derived schema 35 advances Blueprint interprocedural schema to version 3 and materializes exact static call/return topology for direct internal Blueprint function calls.

The accepted GASP target audit distinguishes 466 uniquely captured internal function targets into 25 interface dispatch/declaration targets, 162 pure calls, 0 latent calls and 279 impure call nodes. Three impure call nodes are disconnected/dead authored callsites and therefore have no caller basic block. The remaining 276 executable callsites have exact caller blocks, exact callee entry blocks, entry-reachable return frontiers and exact connected caller continuations where present.

Schema 35 adds:

- `blueprint_interprocedural_function_execution_edges.jsonl` with `function_enter` and `function_return` block edges;
- `blueprint_interprocedural_function_execution_terminals.jsonl` for executable direct calls whose caller side has no continuation.

Return edges originate from every entry-reachable terminal block in the callee graph rather than assuming every function owns a `FunctionResult` node. This preserves valid void functions. Declared result nodes that are off the reachable exec path remain authored structure but are not used as fabricated return edges.

Eligibility follows the actual call node: an impure call node remains executable even when its target function is default-pure, because UE supports a node-level purity override. Interface dispatch/declarations, pure calls, latent calls and unreachable/dead callsites are excluded from the direct execution stream. The tool does not guess interface implementations, latent scheduler continuations or runtime Blueprint VM behavior.

## 20. Blueprint function data provenance separates exact members from split parent projections

Derived schema 36 advances Blueprint interprocedural schema to version 4 and adds `blueprint_interprocedural_function_data_routes.jsonl`.

The prerequisite call-binding schema-2 audit is accepted on GASP with 908 bindings: all 908 have exact parent-parameter identity and structural value-type compatibility; 886 have exact member identity; 22 are split call-site projections to exact unsplit parent parameters. The 138 differences observed between call/signature/parameter pin surfaces are limited to `is_reference`/`is_const` presentation and are retained as provenance rather than treated as transported value-type mismatches.

Schema 36 materializes one static function-data row per non-interface, non-latent exact-internal binding. Each row preserves call/function identity, argument-vs-return direction, target kind, exact-member-vs-split-parent identity, structural value-type proof, qualifier surfaces, caller source/default evidence, callee parameter/body provenance, caller result consumers and readiness state.

Two readiness levels are deliberate:

- `boundary_ready` means the function boundary mapping and required value/provenance evidence are exact enough for the captured parameter identity;
- `member_route_ready` additionally requires exact member identity and a canonical consumer across the boundary.

Split bindings remain queryable as `split_parent_projection` rows with `member_identity_exact=false`. They can never become member-route-ready merely from a lexical suffix. The representative GASP callee boundaries expose only the unsplit parent parameter for all 22 split cases, so no callee child-pin/member identity is manufactured.

Pure functions remain valid data-provenance targets. Unreachable/dead impure callsites remain authored data topology and can retain data routes. Blueprint Interface declarations/dispatches and latent calls are excluded from schema-36 implementation provenance. No expression substitution, function-body inlining, scheduler simulation or runtime Blueprint VM execution is claimed.

## 21. Blueprint delegate bindings preserve authored subscriptions without simulating multicast runtime state

Derived schema 37 introduced `blueprint_delegate_bindings.jsonl`; derived schema 38 tightened endpoint identity precedence; derived schema 39 additionally resolves exact delegate data paths through transparent Blueprint Reroute nodes while preserving every reroute hop as provenance. Derived schema 40 distinguishes authored Bind/Assign sites from resolved subscriptions: zero-input sites remain visible in structural facts and semantic-report diagnostics but emit no binding row.

Structural schema 13 is the prerequisite evidence layer. It preserves exact multicast-delegate `FMemberReference` provenance (resolved owner/name, member GUID, self/local scope) plus both `CreateDelegate` selected-function GUID and resolved UFunction path evidence.

Schema 40 materializes one row per resolved canonical delegate-typed data path into `Bind Event` / `Assign` only when the dispatcher, endpoint and any intervening Reroute chain are exact. A Bind/Assign node with no delegate input route is an authored site, not proof of a subscription, and is therefore reported but not materialized. When UE exposes both an exact selected event-node GUID and a compiled/skeleton UFunction path for the same CreateDelegate, the authored event node is the primary endpoint and the UFunction path is retained as supporting provenance. Exact UFunction path remains the fallback endpoint when no exact authored event-node GUID target is captured. A row preserves:

- exact dispatcher owner/name/member GUID and scope provenance;
- bind-vs-assign operation and caller graph/node identity;
- exact endpoint identity;
- endpoint resolution basis: selected event GUID, selected function path, or direct captured event node;
- source/target delegate pin identity and static evidence kind.

The relation is intentionally an authored subscription declaration, not a runtime subscriber set. `Unbind Event`, `Clear`, and dispatcher `Call` remain separately captured authored operations; schema 40 does not simulate their temporal effects, multicast ordering, duplicate-subscription behavior, object lifetime, or broadcast execution.

Name-only endpoint matching is never promoted. Missing delegate owner information is never reinterpreted as self-context. Runtime delegate object state remains outside the contract.

---






# Issue #14 status

Accepted slices:

```text
Gameplay Tags project model
General DataTable / CurveTable / PrimaryDataAsset coverage
Mover
Gameplay Cameras
ZoneGraph + Mass (authored schema-5 boundary)
Gameplay Ability System (systems schema 6 / derived schema 22)
Smart Objects (systems schema 7 / derived schema 23)
AI Perception (systems schema 8 / derived schema 24)
Dataflow / Geometry Collection (systems schema 9 / derived schema 25)
AnimNext / UAF (systems schema 10 / derived schema 26)
```

The original evidence-driven gameplay-family expansion tracked by issue #14 is complete. Authored Navigation was subsequently completed as issue #45 with systems schema 11 / derived schema 27, and Gameplay Framework was subsequently completed as issue #49 with derived schema 28 while leaving systems independently versioned.

---

# Pipeline completeness audit

| Layer | Raw manifest/count validation | SQLite | Query surface | Project graph | Corpus validation |
| --- | --- | --- | --- | --- | --- |
| Structural / Blueprint / AI / PCG / material | Yes | Yes | Yes | Yes | GASP/Cropout/ContentExamples/StackOBot |
| World | Yes | Yes | Yes | Yes | ContentExamples/StackOBot/City Sample + others |
| Animation through schema 4 | Yes | Yes | Yes | Yes, through exact derived schema 32 | GASP + ContentExamples; Motion Warping exact gate on GASP UE 5.8.2 |
| SkeletalMesh / PhysicsAsset schema-3 slice | Yes | Yes | Yes | Yes, exact derived-schema-29 contract | ContentExamples UE 5.8.2 |
| StaticMesh mesh-schema-1 slice | Yes | Yes | Yes | Yes, exact 1,789-edge derived-schema-30 contract | ContentExamples UE 5.8.2 |
| World-geometry schema-1 slice | Yes | Yes | Yes | Yes, exact derived-schema-31 contract | ContentExamples UE 5.8.2 |
| Motion Warping animation-schema-4 slice | Yes | Yes | Yes | Yes, exact 540-edge derived-schema-32 contract | GASP UE 5.8.2 |
| VFX | Yes | Yes | Yes | Yes | ContentExamples + StackOBot/Niagara Examples |
| Systems schema 11 | Yes | Yes | Yes | Yes | StackOBot + ContentExamples + GASP + City Sample + Lyra, with specialist corpus gates by family |
| GAS schema-6 slice | Yes | Yes | Yes | Yes, exact schema-22 contract | Lyra UE 5.8.2 |
| Smart Objects schema-7 slice | Yes | Yes | Yes | Yes, exact schema-23 contract | City Sample UE 5.8.2 |
| AI Perception schema-8 slice | Yes | Yes | Yes | Yes, exact schema-24 contract | ContentExamples UE 5.8.2 |
| Dataflow / Geometry Collection schema-9 slice | Yes | Yes | Yes | Yes, exact schema-25 contract | ContentExamples UE 5.8.2 |
| AnimNext / UAF schema-10 slice | Yes | Yes | Yes | Yes, exact 213-edge schema-26 contract | GameAnimationSample-hosted UE 5.8.2 representative UAF content |
| Authored Navigation schema-11 slice | Yes | Yes | Yes | Yes, exact 27-edge schema-27 contract | ContentExamples UE 5.8.2 |
| Gameplay Framework derived-28 slice | Existing canonical structural/world/config validation | n/a new tables | Project graph/capability surface | Yes, exact 187-edge schema-28 contract | ContentExamples UE 5.8.2 |
| Project graph/neighborhoods | Yes | Yes | Yes | n/a | StackOBot + ContentExamples + GASP + City Sample + Lyra |
| Capability contract | Yes | n/a | `uatool capabilities` | Describes graph/canonical coverage | Synthetic regression + emitted per corpus |

At the pipeline level, implemented families are wired end-to-end. Remaining gaps are primarily **discoverability, domain depth and selected unmodeled subsystems**, not forgotten pack/query plumbing.

---

# Automated regression coverage audit

Focused Python regression coverage includes:

- canonical/compact Blueprint pin and property storage;
- Blueprint semantic nodes/statements/control flow;
- user-defined enum extraction/rendering/inference;
- RigVM semantic bridging;
- world/animation/VFX stitching regressions;
- build freshness/fallback/cache policy;
- Chooser decision interpretation/storage/graph promotion;
- Mover extraction/behavior/graph semantics;
- Gameplay Camera canonical topology, director/provider behavior, enum readability and graph promotion;
- Mass/ZoneGraph systems validation, focused capture/promotion, exact schema-21 graph contract and rejection of unsupported generator-to-shape bindings;
- GAS systems schema-6 validation, focused capture/promotion, candidate selection, exact schema-22 graph construction and real-corpus acceptance verification;
- Smart Objects systems schema-7 validation, focused capture/promotion and exact schema-23 graph verification;
- AI Perception systems schema-8 normalization, discovery/capture regression gates, null-array preservation, capability promotion and exact schema-24 graph verification;
- Dataflow / Geometry Collection systems schema-9 graph/cardinality validation, behavior-boundary enforcement, capability promotion and exact schema-25 graph verification;
- AnimNext / UAF systems schema-10 identity/discovery/cardinality validation, accepted representative capture, exact variable-use resolution and exact schema-26 graph verification;
- Authored Navigation systems schema-11 normalization, exact class/default/config contract, split world/system ownership, agent-mask normalization, representative 16-mapping cardinality and exact schema-27 graph verification;
- Gameplay Framework exact/transitive class identity, GameMode selector/config/world joins, rejection of name-only inference, mixed-version systems self-validation and exact schema-28 graph verification;
- SkeletalMesh/PhysicsAsset authored topology, schema-3 composition/storage compatibility and exact derived-schema-29 graph verification;
- StaticMesh authored source LOD/material/socket/collision normalization and exact derived-schema-30 graph verification;
- Landscape/Foliage/HLOD authored world-geometry normalization, native foliage refinement and exact derived-schema-31 graph verification;
- Motion Warping authored notify/modifier/property normalization, schema-3-before-schema-4 lifecycle regression coverage and exact 540-edge derived-schema-32 graph verification;
- systems validation/SQLite/project-graph integration;
- derived freshness, neighborhood compaction and storage invariants;
- capability-contract full-corpus/partial-corpus/determinism/deferred-composition behavior.

Real UE corpora remain required because unit tests cannot substitute for actual serialized UE 5.8 shapes. New subsystem work should add synthetic invariants only after a representative corpus establishes what the authored data actually looks like.

---

# What “complete” means now

The original planned indexer roadmap plus the accepted Gameplay Tags, gameplay-data, Mover, Gameplay Cameras, Mass/authored-ZoneGraph, GAS, Smart Objects, AI Perception, Dataflow/Geometry Collection, AnimNext/UAF, authored Navigation, Gameplay Framework, SkeletalMesh/PhysicsAsset, StaticMesh, Landscape/Foliage/HLOD authored geometry and Motion Warping slices are implemented and corpus-validated.

The repository is **not complete with respect to the entire Unreal Engine 5.8 content ecosystem**, and it should not claim to be. The 1.0 target is trustworthy semantic infrastructure with explicit coverage, deterministic/provenance-aware graph output, stable lifecycle commands and bounded performance—not “100% of Unreal classes.”