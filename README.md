# UnrealAssetTool

**UnrealAssetTool** builds an AI-friendly structural index of an Unreal Engine project from Unreal's own serialized/editor data instead of relying on screenshots or hand-written project documentation.

> Unreal Engine already uses **UAT** for **Unreal AutomationTool**. The project is `UnrealAssetTool`; the command-line launcher is `uatool`.

## Current baseline

**UnrealAssetTool 0.7.0 development line**

- Unreal target: **UE 5.8+**
- validated engine: **UE 5.8.2**
- structural scanner schema: **12**
- world scanner schema: **12**
- animation scanner schema: **1** — currently under PR #5 validation
- derived schema: **10**
- canonical storage: sharded JSONL emitted from Unreal-authored data
- derived storage/retrieval: regenerable JSONL views plus SQLite

The schema numbers intentionally describe independent layers:

- **structural schema 12** — project/assets/Blueprint/AI/PCG/material facts;
- **world schema 12** — maps, actors, components, authored instance state, references, Data Layers and World Partition descriptors;
- **animation schema 1** — animation assets, Skeletons, Motion Matching/Pose Search, curves and animation-adjacent assets;
- **derived schema 10** — deterministic Python reconstruction and cross-system joins.

Primary regression corpora are Game Animation Sample, Cropout Sample Project and Content Examples, with StackOBot used as a targeted World Partition/LevelInstance/PCG probe.

## Goal

Given a `.uproject`, UnrealAssetTool should let an AI move from a gameplay question to authoritative authored facts without loading the entire project into context.

Examples:

- Which maps, actors, components, Blueprints, materials, AI graphs and PCG graphs exist?
- Where is a Blueprint instantiated in the playable world?
- What function/event/graph implements an actor's behavior?
- What feeds a Branch, setter, function argument or return value?
- Which internal function does a call target, and how do caller pins map to callee parameters?
- How do Animation Blueprint state machines and transitions connect?
- Which Motion Matching database/schema/channels and source animations drive a character?
- Which animation curves, notifies, sync markers, Montage sections or BlendSpace samples are authored?
- Which StateTree, EQS query, PCG graph, material, AnimBP or referenced Blueprint is associated with a placed actor/component?
- Which LevelInstance/PackedLevelActor instantiates which child world?
- What is known exactly, and what is only known through a generic package dependency?

The output is deliberately **facts-first, loss-minimizing, sharded, deterministic and regenerable**.

## Architecture in one sentence

**Unreal extracts authoritative facts; Python derives deterministic program/world/system relationships; SQLite makes them easy to retrieve.**

See:

- [Architecture](docs/architecture.md)
- [Schema reference](docs/schema.md)
- [Subsystem coverage matrix](docs/coverage.md)
- [Animation schema 1](docs/animation-schema-1.md)
- [Cross-project workflow](docs/cross-project-workflow.md)

## Current first-class coverage

### Project / Asset Registry

- physical project/source/config/document files with bounded text chunks;
- Asset Registry asset identity, class, tags, package paths and direct package dependencies.

Asset Registry data is the universal fallback: unsupported asset families still exist in the index, but that does not mean their internal authored structure is understood.

### Blueprint / K2 / UMG / Animation Blueprint

Canonical extraction includes:

- Blueprint identity, inheritance, interfaces, variables, SCS components and defaults;
- every graph, node, pin and exact execution/data edge;
- reflected node properties and normalized UObject references;
- common K2 and AnimGraph semantic operations;
- Timelines/tracks/keys;
- UMG widget trees, bindings and animations;
- AnimGraph property bindings and state-machine topology;
- Control Rig editor graphs.

Derived reconstruction includes normalized functions/events, call edges, internal parameter bindings, bounded upstream data provenance, execution blocks, Blueprint relations/context/summaries and Control Rig editor-node -> RigVM joins.

Unknown/plugin-specific graph nodes remain preserved generically rather than guessed from display text.

### Control Rig / RigVM

Normal scans preserve a compact RigVM model:

- graph/node objects;
- pins;
- links;
- UObject relationships/references;
- editor Control Rig node -> model-node joins.

The extremely large raw RigVM reflection stream remains opt-in with `--include-raw-rigvm-properties`.

### AI gameplay systems

Dedicated canonical extraction exists for Behavior Trees, Blackboards, EQS and StateTree, including their hierarchy, settings, transitions/bindings and linked assets.

### PCG

Dedicated extraction includes PCG graphs, nodes, pins, exact graph edges, settings/properties, graph parameters, real subgraph relationships and derived relations/context/summaries.

### Materials

Materials are already **first-class**, not a coverage gap.

Dedicated extraction includes Materials, Material Instances and Material Functions; expression objects; exact expression/input wiring and root outputs; reflected settings; parameters; texture/function references; and derived visual relations/context.

### Worlds, actors and placement

World schema 12 includes:

- world/map identity;
- persistent and classic streaming levels;
- loaded actors, GUIDs, labels, classes, folders, tags, transforms, ownership and attachments;
- components and component attachments/transforms;
- authored instance property overrides;
- hard/soft object references;
- Data Layers;
- World Partition metadata and actor descriptors;
- descriptor parent/reference GUID relationships.

Derived world relations/context/summaries add world -> actor/component relationships, actor -> Blueprint placement, attachments/ownership, Data Layer membership and LevelInstance/PackedLevelActor -> source-world relationships.

### World-to-system stitching

Derived schema 10 adds `world_system_relations.jsonl`, bridging authored placement to specialist models such as Blueprint, AnimBP, Control Rig, UMG, Behavior Tree, Blackboard, EQS, StateTree, PCG and materials.

Every bridge keeps explicit evidence; multiple proofs are aggregated rather than duplicated.

### Animation schema 1

Animation schema 1 is currently under validation on Game Animation Sample and adds dedicated canonical streams for:

- AnimSequence and sequence-base assets;
- notifies / notify states and timing;
- authored sync markers;
- Montage sections, slots and animation segments;
- BlendSpace/BlendSpace1D/AimOffset authored axes and samples;
- Skeleton bone hierarchy/reference transforms and sockets;
- float/transform animation curves and individual `FRichCurveKey` data;
- Pose Search databases, schemas, feature channels and role/Skeleton mappings;
- Pose Search Interaction Assets and multi-role items;
- Pose Search Normalization Sets and database membership;
- Mirror Data Tables and row mappings;
- reflection-backed Chooser, ProxyAsset/ProxyTable, IK Rig and IK Retargeter facts.

Pose Search/Chooser/IK support deliberately avoids hard optional-plugin dependencies where possible.

The first UE 5.8.2 GASP schema-1 run passed and established 155 Pose Search databases, 33 schemas, 74 channels and 2,138 database source rows with exact count/link invariants. The current branch is validating the deeper curve/interaction/normalization/mirror pass before the schema is called stable.

See [docs/animation-schema-1.md](docs/animation-schema-1.md).

## Important remaining coverage gaps

The largest current gaps after animation schema 1 are:

1. **Niagara and legacy Cascade VFX** — systems, emitters, stacks/modules, renderers, parameters, events and data interfaces;
2. **Sequencer** — bindings, tracks, sections, channels/keyframes, subsequences and event/camera/animation/VFX/audio references;
3. **MetaSounds and audio graphs** — MetaSound graph topology plus SoundCue/routing assets;
4. **Enhanced Input/common gameplay data** — InputAction, InputMappingContext, DataTables and project-wide Gameplay Tag semantics;
5. selected mesh/physics/rendering/plugin assets where their internals materially affect gameplay understanding.

Animation also still has depth work such as richer PoseAsset, Chooser/Proxy and IK Rig/Retarget semantics. See [docs/coverage.md](docs/coverage.md) for the maintained matrix.

## Repository layout

```text
UnrealAssetTool/
  UnrealAssetTool.uplugin
  Source/
    UnrealAssetTool/
      UnrealAssetTool.Build.cs
      Public/
        UnrealAssetToolCommandlet.h
        UnrealAssetToolWorldCommandlet.h
      Private/
        UnrealAssetToolModule.cpp
        UnrealAssetToolCommandlet.cpp
        UnrealAssetToolWorldCommandlet.cpp
        UnrealAssetToolAnimationScanner.cpp
        UnrealAssetToolAnimationDeepScanner.cpp
  scripts/
    uatool.py
    uatool_core.py
    uatool_world_stitch.py
    uatool_animation.py
  docs/
    architecture.md
    schema.md
    coverage.md
    animation-schema-1.md
    cross-project-workflow.md
```

## Recommended workflow: one canonical checkout

Keep one canonical UnrealAssetTool checkout and use its launcher against any target `.uproject`.

Example checkout:

```text
E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

Run a scan:

```powershell
python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\GameAnimationSample\GameAnimationSample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

The same checkout can scan Cropout, Content Examples or another target project. For external targets the launcher temporarily stages only the plugin descriptor and `Source/` under the target project's `Plugins/UnrealAssetTool`, builds/scans through Unreal's normal project-plugin path, then restores/removes the temporary stage.

See [docs/cross-project-workflow.md](docs/cross-project-workflow.md).

## Build behavior

Engine selection is explicit. Pass the exact editor executable:

```powershell
python scripts\uatool.py build `
    "E:\Path\MyProject.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

For standard engine layouts, `uatool` derives `Engine\Build\BatchFiles\Build.bat` from that editor path.

For UE 5.8 DebugGame, the launcher resolves the actual plugin DLL through generated `.modules` metadata and repairs the plugin runtime manifest with the target project's BuildId rather than assuming one hard-coded filename.

## Scan

```powershell
python scripts\uatool.py scan `
    "E:\Path\MyProject.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

A normal scan:

1. validates/builds the target Editor and UnrealAssetTool module;
2. runs the structural commandlet;
3. runs the world commandlet and the animation schema passes;
4. writes canonical JSONL to `<Project>\.uatool`;
5. runs deterministic derived reconstruction;
6. builds `<Project>\.uatool\uat.db`;
7. creates `<ProjectName>.uatool.zip` beside the `.uproject`.

Useful options:

```text
--no-build
--output <dir>
--include-generated
--include-engine
--include-self
--include-raw-rigvm-properties
--no-bundle
--bundle-include-raw-rigvm
--build-script <path>
```

Do not use `--no-build` after C++ scanner changes unless the correct module has already been rebuilt.

## Derived-only regeneration

When canonical scanner schemas are compatible and only Python-derived logic changed:

```powershell
python scripts\uatool.py derive "E:\Path\Project\.uatool"
```

Rebuild SQLite:

```powershell
python scripts\uatool.py pack "E:\Path\Project\.uatool"
```

Regenerate the compact bundle:

```powershell
python scripts\uatool.py bundle `
    "E:\Path\Project\.uatool" `
    --destination "E:\Path\Project\Project.uatool.zip"
```

`pack` and `bundle` rerun deterministic derivation first. A canonical animation-schema change still requires Unreal to be run again.

## Query

```powershell
python scripts\uatool.py query `
    "E:\Path\Project\.uatool" `
    "PoseSearch"
```

Query output includes specialist Blueprint/AI/PCG/material views, world summaries/relations/context, schema-10 world-system links, and animation/Pose Search/curve/mirroring views when animation schema 1 data is present.

## Canonical vs derived rule

If Unreal can state a fact exactly, store that fact canonically first.

Examples:

```text
node class
pin type/default/link
UFunction flags
state transition endpoint
asset/object reference
actor/component transform
World Partition descriptor GUID/reference
material expression input
PCG edge
Pose Search schema/channel
animation curve key
Montage section
```

Derived interpretation can then build execution blocks, call graphs, parameter bindings, data provenance, world relationships, world-to-system joins, animation relationships/context and future bounded project neighborhoods.

Derived data must remain disposable and reproducible from compatible canonical facts whenever possible.

## Next development priorities

The current coverage gate is:

1. finish **animation schema 1** GASP + Content Examples validation and then add derived animation relations/context;
2. **Niagara + legacy Cascade**;
3. **Sequencer**;
4. **MetaSounds/audio**;
5. **Enhanced Input/common gameplay data** where useful;
6. **typed bounded project-level graph traversal/neighborhoods** with provenance and coverage quality on every hop.

Traversal can evolve in parallel, but it must distinguish a first-class semantic edge from a generic Asset Registry dependency.
