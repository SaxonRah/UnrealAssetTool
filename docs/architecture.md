# UnrealAssetTool architecture

## Principle

UnrealAssetTool separates **extraction**, **storage**, **derivation**, and **retrieval**.

```text
                         Unreal Editor 5.8+
                               |
        +----------------------+----------------------+
        |                                             |
UUnrealAssetToolCommandlet                UUnrealAssetToolWorldCommandlet
        |                                             |
project/assets/program facts                   world/placement facts
        |                                             |
        +----------------------+----------------------+
                               |
                    canonical schema-12 JSONL
                               |
                        scripts/uatool.py
                               |
               deterministic derived schema 10
                               |
           +-------------------+-------------------+
           |                   |                   |
     specialist views      world graph      world-system bridge
           |                   |                   |
           +-------------------+-------------------+
                               |
                             SQLite
                               |
               retrieval / AI context / traversal
```

The main rule is simple:

> If Unreal can state a fact exactly, extract that fact first. Interpretation belongs in a derived layer unless Unreal itself is required to determine it.

## Current version layers

```text
UnrealAssetTool:          0.7.0
structural schema:       12
world schema:            12
derived schema:          10
validated engine:        UE 5.8.2
```

### Structural schema

The main Unreal commandlet owns facts about:

- physical files/source chunks;
- Asset Registry assets/dependencies;
- Blueprint/K2/UMG/AnimBP graphs;
- Control Rig/RigVM;
- Behavior Trees, Blackboards, EQS, StateTrees;
- PCG;
- materials.

### World schema

The world commandlet owns facts about:

- worlds/maps/levels;
- loaded actors and components;
- transforms/attachments/ownership;
- authored instance overrides;
- hard/soft UObject references;
- Data Layers;
- World Partition descriptors and descriptor relationships.

### Derived schema

Python reconstructs disposable deterministic views such as:

- Blueprint functions/events/calls;
- caller/callee parameter bindings;
- bounded data provenance;
- execution blocks;
- normalized AnimBP state machines;
- AI/PCG/material relations/context;
- world relations/context/summaries;
- LevelInstance/PackedLevelActor child-world joins;
- placement -> authored-system bridge relations.

A scanner-schema change normally requires Unreal. A derived-schema change normally requires only `derive`, `pack`, or `bundle`.

## Why extraction runs inside Unreal

`.uasset` and `.umap` are Unreal serialization formats whose editor/runtime structures vary by engine version and asset family.

Using Unreal itself gives the indexer authoritative access to:

- package loading and version handling;
- Asset Registry;
- editor-only Blueprint graphs;
- reflection;
- project/plugin mount points;
- World/Level/Actor objects;
- World Partition descriptor APIs;
- asset-family-specific authored structures.

The project intentionally avoids building an external `.uasset` reverse-engineering stack.

## Why canonical output is JSONL

A large Unreal project cannot sensibly be represented as one monolithic JSON document.

JSONL gives:

- streaming writes;
- bounded memory use;
- independent subsystem shards;
- partial retrieval;
- diffability;
- independent derived regeneration;
- easy SQLite/search ingestion;
- small context slices for AI tools.

`uat.db` is an index, not the source of truth.

## Facts-first examples

Canonical facts:

```text
Blueprint node concrete class
pin type/default/link
UFunction flags
struct type
AnimBP transition endpoints
Behavior Tree child order
StateTree binding path
PCG edge
material expression input
asset/object reference
actor/component transform
World Partition descriptor GUID
Data Layer membership
```

Derived facts:

```text
function-call resolution
caller/callee parameter bindings
basic blocks
data provenance
normalized state-machine topology
world contains/attachment relations
LevelInstance -> child world
placed actor -> referenced StateTree/PCG/material/AnimBP
readable context/summaries
```

A derived result never replaces the canonical facts that justify it.

## Blueprint understanding model

Blueprint understanding is layered.

### Layer 1 — exact graph truth

Canonical extraction stores:

- graph identity and nesting;
- node identity/class;
- pins and normalized types/defaults;
- exact execution/data links;
- variables/components/interfaces;
- node reflected state;
- UObject references;
- authored CDO/component-template state;
- Timelines;
- UMG structure and animation data.

This is the verification layer.

### Layer 2 — normalized semantics

Common graph-node classes are promoted to factual operations such as:

```text
function_call
variable_get
variable_set
branch
switch
dynamic_cast
spawn_actor
make_struct
break_struct
set_fields_in_struct
anim_state_machine
anim_transition
anim_sequence_player
anim_motion_matching
anim_control_rig
```

Classification is driven by Unreal classes/APIs/reflected fields, not display-title guessing.

Plugin-defined or uncommon nodes remain generically preserved when no safe specialization exists.

### Layer 3 — program reconstruction

Derived reconstruction builds:

- functions/events;
- call edges;
- unique internal call bindings;
- bounded upstream expression/provenance trees;
- execution basic blocks and roots;
- AnimBP state-machine topology;
- semantic relations/context/summaries.

Ambiguous interface/override calls stay ambiguous rather than being forced to one target.

## Interprocedural flow

`blueprint_call_edges` preserves whether a call target is:

```text
internal
ambiguous_internal
external
unresolved
```

Only unique internal calls receive argument/return parameter bindings.

Future recursive/interprocedural provenance should build on those bindings. It should not infer cross-function flow independently from weaker naming heuristics.

## Animation architecture

Animation currently has two very different coverage levels.

### Strong: Animation Blueprint program structure

The Blueprint/derived layers understand:

- AnimGraphs;
- state machines/states/transitions/conduits/aliases;
- cached poses;
- linked layers/input poses;
- slots;
- common sequence/BlendSpace/Motion Matching/Control Rig graph nodes;
- property bindings;
- exact graph and transition topology.

### Gap: animation asset internals

Referenced assets such as AnimSequence, AnimMontage, BlendSpace, Skeleton, Pose Search Schema/Database, Chooser, ProxyTable, IK Rig, and IK Retargeter are currently mostly generic Asset Registry entities.

That gap is especially important for UE 5.8 Motion Matching. Recognizing a Motion Matching AnimGraph node is not enough; the project graph also needs the Pose Search database/schema/channel and source-animation structure behind it.

See `docs/coverage.md`.

## Control Rig / RigVM

Control Rig keeps both editor presentation and compact RigVM model truth.

The editor graph is useful for authored layout/context. RigVM objects/pins/links/references are useful for actual model structure. Derived joins connect the two instead of treating either representation as complete by itself.

## AI gameplay systems

Behavior Trees, Blackboards, EQS, and StateTrees are specialist authored programs rather than flat UObject dumps.

The scanner preserves topology/settings/bindings; derived relations connect them to one another and to Blueprint content.

## PCG and materials

PCG and material graphs follow the same facts-first pattern:

```text
exact nodes/expressions/pins/edges/settings
                +
       normalized references/parameters
                +
        derived relations/context
```

Materials are already a first-class subsystem. Niagara is not part of the material model and remains a separate VFX gap.

## World and placement architecture

World extraction is intentionally separate from the structural commandlet because maps and World Partition need different loading and lifecycle rules.

### Loaded world objects

The world pass records loaded persistent-level actors/components and their authored state.

Scene component world transforms are refreshed from serialized relative transform + attachment state before extraction because passive map loading can leave stale identity `ComponentToWorld` caches.

### World Partition

World Partition scanning prefers descriptor APIs.

Rules:

- initialize a deserialized `UWorldPartition` only when needed and allowed;
- iterate descriptor instances;
- do not call `GetActor()` merely to inspect descriptors;
- do not use actor-loading enumeration as the normal scan path;
- uninitialize only when the scanner initialized it.

Descriptor GUIDs, parent GUIDs, reference GUIDs, packages, soft paths, class, transform/bounds, and Data Layer information remain canonical.

### LevelInstance / PackedLevelActor

Derived schema 9 connects World Partition LevelInstance/PackedLevelActor descriptors to child/source world packages from existing canonical descriptor + Asset Registry facts.

The relation is asserted only when one non-owning scanned world package resolves uniquely.

## World-to-system stitching

Derived schema 10 is the first explicit bridge between placement and specialist authored systems.

Example:

```text
placed actor
    -> instantiates_blueprint
    -> BP_NPC

placed actor/component
    -> references_animation_blueprint
    -> ABP_NPC

placed actor/component
    -> references_statetree
    -> ST_NPC

placed actor/component
    -> references_pcg_graph
    -> PCG_Forest

placed actor/component
    -> references_material
    -> MI_NPC
```

Bridge rows keep evidence rather than only the conclusion.

Current evidence sources include:

- placed actor Blueprint identity;
- direct world actor/component UObject references;
- Blueprint semantic relations;
- Blueprint package dependencies;
- world package dependencies.

Generated Blueprint classes normalize to authored Blueprint assets. Ambiguous package-to-specialist mappings are not guessed.

## Semantic coverage quality

The eventual project graph must distinguish **existence** from **understanding**.

Every Unreal asset has at least generic Asset Registry identity/dependencies. Only some families have first-class internal semantics.

Useful traversal quality levels are:

```text
canonical-structural
canonical-reference
derived-exact-join
generic-package-dependency
```

A future neighborhood query should carry this quality/provenance on every hop.

For example:

```text
Actor -> Material
```

can lead to a first-class material graph today, while:

```text
Actor/World -> NiagaraSystem
```

may currently terminate at a generic asset record because Niagara internals are not yet extracted.

See `docs/coverage.md` for the maintained subsystem matrix.

## Coverage gate before broad universal traversal

A universal graph API is architecturally useful now, but filling major subsystem blind spots first will make it much more valuable.

Priority:

1. animation asset internals, especially Pose Search/Motion Matching/Chooser plus sequence/montage/blend/skeleton data;
2. Niagara + legacy Cascade particles;
3. Sequencer;
4. MetaSounds + SoundCue/audio routing;
5. Enhanced Input/common gameplay-data assets where useful;
6. project-level typed bounded neighborhoods/traversal with per-hop provenance/coverage quality;
7. additional geometry/physics/rendering/plugin asset families when real corpora justify them.

Traversal can evolve in parallel, but unsupported subsystem internals must remain visible as unsupported rather than being disguised as semantically complete generic dependency edges.

## Long-term universal entity/edge graph

Specialist tables should remain. A universal graph should sit over them rather than replace them.

### Entity

```text
id
kind
name
path
class/type
source
coverage_level
properties
```

Potential entities include:

```text
file
asset
world
level
actor
component
Blueprint
graph
node
pin
function/event
AnimBP state
Behavior Tree node
StateTree state
PCG node
material expression
Niagara emitter/module
Sequencer binding/track/section
MetaSound node
```

### Edge

```text
source_id
edge_kind
target_id
provenance
quality
properties
```

Potential edges include:

```text
contains
inherits
depends_on
references
calls
binds_argument
binds_return
execution_flow
data_flow
owns_component
attached_to
placed_in
transitions_to
instantiates_world
```

The graph layer should provide bounded neighborhoods without flattening away specialist details.

## Cross-project launcher architecture

One canonical checkout can scan many `.uproject` files.

For an external target, the launcher temporarily stages:

```text
UnrealAssetTool.uplugin
Source/
```

under:

```text
<TargetProject>/Plugins/UnrealAssetTool
```

It then performs normal target/module builds, resolves the actual generated module DLL, repairs the staged/local runtime `.modules` manifest using the target project's BuildId, runs both commandlets, and removes/restores temporary plugin directories afterward.

This uses UnrealBuildTool's normal project-plugin discovery path rather than depending on foreign-plugin target modes.

See `docs/cross-project-workflow.md`.

## UE 5.8 DebugGame module loading

Do not hard-code one UnrealAssetTool DLL name for DebugGame.

The launcher resolves the actual DLL through generated `.modules` metadata and accepts a filesystem fallback only when one candidate is unambiguous.

The running process consumes the target project's runtime BuildId, so the plugin runtime manifest is repaired to match that target.

This is launcher infrastructure, not scanner schema.

## Build/read lifecycle

A normal scan is:

```text
target .uproject
    |
validate explicit editor path
    |
stage canonical plugin source if target is external
    |
build target Editor + UnrealAssetTool module
    |
resolve/repair runtime module metadata
    |
run structural commandlet -> schema 12
    |
run world commandlet -> world schema 12
    |
derive schema 10
    |
pack SQLite
    |
create compact upload ZIP
    |
remove stage / restore target plugin copies
```

A failed scan must not leave stale manifests that can be mistaken for a fresh successful run.

## Incremental indexing

Full scans remain acceptable for current development, but long-term indexing should avoid reprocessing unchanged packages.

Potential invalidation keys include:

- physical source/config hashes;
- package file hashes/timestamps;
- Blueprint graph structure;
- selected authored object state;
- world package/external actor changes.

Incremental indexing should preserve the same canonical/derived separation.

## Native C++ understanding

Raw source chunks are the current safe baseline.

A later semantic source pass should use Clang tooling rather than regex because Unreal C++ depends on generated headers, macros, platform conditions, reflection annotations, and target-specific compile environments.

This remains secondary to visual-program/world/subsystem understanding.
