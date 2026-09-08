# UnrealAssetTool 1.0.0-beta.2

Validated engine: **UE 5.8.2**  
Engine target: **UE 5.8+**

Beta.2 keeps the beta.1 authored-semantic coverage baseline and adds a substantial native C/C++ semantic layer, plus the correctness and lifecycle work needed to make that layer portable and queryable.

## Highlights

### Native reflected + compiler semantics

UnrealAssetTool can now build an optional project-owned native semantic index composed from independently authoritative evidence:

- reflected UE/UHT-visible classes, structs, functions, parameters, properties and enums;
- project-owned compile-database and response-file provenance;
- compiler-resolved libclang AST symbols, parameters and call sites;
- exact reflected-to-compiler joins only where owner/type/function/parameter identity is proven;
- SQLite/query/report integration for reflected and source-only native functions;
- portable staged native evidence under `.uatool/native_semantics`;
- compiler-vs-join freshness classification;
- exact compiler-referenced project call-target materialization;
- bounded exact multi-hop native caller/callee traversal.

The expensive compiler AST capture remains explicit. Normal Unreal scans do not silently parse every translation unit.

### Accepted Hyperreality native corpus

The beta.2 native acceptance corpus records:

```text
translation units                         48/48
compiler symbols                          5322
compiler parameters                       2569
compiler calls                            6997
target-only symbol occurrences              41
parameter-owner mismatches rejected           7
nested callable calls suppressed             95

reflected types                           18/18
reflected functions joined                43/49
expected delegate diagnostics                 6

project-target calls                       2932
materialized exact target symbols          2926
unmaterialized project-target calls           6
```

The six remaining unmaterialized calls are deliberate fail-closed boundaries:

- four `OverloadedDeclRef` overload-set references;
- two `TemplateTypeParameter` references.

Beta.2 does not guess identities for those constructs.

### Native program traversal

`native-program-report` retains its depth-1 compatibility surface and can now expose bounded multi-hop caller/callee graphs with:

- exact `symbol_id` continuation first;
- exact Clang USR fallback second;
- shortest discovered node depth;
- one discovery-tree edge per non-root node;
- cycle/revisit labeling;
- unresolved/external terminal boundaries;
- anti-starvation budgeting so high-fanout terminal traffic cannot consume the graph budget before deeper exact project paths are represented.

### Native evidence lifecycle

Validated native evidence can be staged atomically into the normal corpus lifecycle. Freshness reports distinguish:

- `fresh`;
- `join_stale` for reflection-only changes that can reuse compiler evidence;
- `compiler_stale` for source/build/descriptors changes;
- `unknown_legacy_stage` when historical evidence lacks the fingerprints needed to make a live freshness claim.

Portable pack/bundle rebuilds do not need access to the original absolute source tree.

## Existing first-class authored coverage

Beta.2 retains the beta.1 first-class authored-semantic coverage, including:

- Blueprint/K2 interprocedural execution/data provenance and exact authored delegate bindings;
- worlds, actors/components, Data Layers and World Partition descriptors;
- animation assets, Skeletons, Pose Search, PoseAsset and Motion Warping;
- PCG, Materials, StaticMesh, Landscape/Foliage/HLOD authored geometry;
- Behavior Tree, Blackboard, EQS and StateTree;
- Enhanced Input, DataTable/CurveTable and Gameplay Tags;
- Mover and Gameplay Cameras;
- Mass Entity, authored ZoneGraph and Smart Objects;
- Gameplay Ability System;
- AI Perception;
- Dataflow and Geometry Collection/Chaos;
- AnimNext/UAF;
- authored Navigation;
- Gameplay Framework;
- typed project graph and machine-readable capability contract.

See [coverage.md](coverage.md) for the maintained family-by-family matrix.

## Depth-pending coverage

Dedicated normalized structure exists but deeper authored/runtime semantics remain intentionally incomplete for:

- UMG/Slate;
- Control Rig/RigVM runtime behavior;
- uncommon Chooser/Proxy columns;
- IK solver/op-specific behavior;
- Niagara stateful execution;
- Sequencer key/track-family depth;
- MetaSound declarations/literals/interfaces;
- SoundCue edge topology;
- Common Input;
- arbitrary project-specific PrimaryDataAsset payloads.

## Generic/high-value gaps

Major remaining families without dedicated semantic models include:

- Groom/Hair beyond reusable Dataflow substrate;
- Texture/RenderTarget/VirtualTexture internals;
- Iris/replication configuration.

Unsupported families remain discoverable through files, Asset Registry and generic references, but are not promoted to first-class semantics.

## Important non-claims

Beta.2 does **not** simulate or claim:

- Blueprint VM or latent scheduler execution;
- runtime delegate subscriber order/lifetime;
- live Mover/GAS/AI/StateTree/BehaviorTree execution state;
- Niagara/particle simulation;
- shader compilation/runtime material resources;
- runtime animation pose/search evaluation;
- generated PCG/ZoneGraph/Recast runtime data;
- dynamically spawned runtime state unless canonically captured;
- guessed native call resolution through unresolved overload sets, template parameters or unsupported compiler cursor kinds.

## Compatibility

Canonical scanner schemas, derived schemas and native semantic companions are independently versioned. Older corpora remain self-describing through manifests and may require derive/repack, a normal Unreal rescan, or a new native AST capture depending on the exact stale contract reported by the current command.

Historical tag `1.0.0-beta.1` remains unchanged at its accepted release-candidate commit.
