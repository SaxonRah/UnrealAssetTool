# UnrealAssetTool

**UnrealAssetTool** builds an AI-friendly structural index of an Unreal Engine project from Unreal's own serialized/editor data instead of relying on hand-written project documentation.

> Unreal Engine already uses **UAT** for **Unreal AutomationTool**. The project is `UnrealAssetTool`; the command-line launcher is `uatool`.

## Current baseline

**UnrealAssetTool 0.7.0**

- Unreal target: **UE 5.8+**
- validated engine: **UE 5.8.2**
- structural scanner schema: **12**
- world scanner schema: **12**
- derived schema: **10**
- canonical storage: sharded JSONL emitted by Unreal
- derived storage/retrieval: regenerable JSONL views plus SQLite
- primary regression corpora:
  - Game Animation Sample
  - Cropout Sample Project
  - Content Examples
- targeted extra coverage corpus:
  - StackOBot

The version numbers intentionally describe different layers:

- **structural schema 12**: Unreal-extracted project/assets/Blueprint/AI/PCG/material facts;
- **world schema 12**: Unreal-extracted maps, actors, components, authored instance state, references, Data Layers, and World Partition descriptors;
- **derived schema 10**: deterministic Python reconstruction and cross-system joins that can normally be regenerated without reopening Unreal.

## Goal

Given a `.uproject`, UnrealAssetTool should let an AI move from a gameplay question to the relevant authored facts without loading the entire project into context.

Examples:

- Which maps, actors, components, Blueprints, materials, AI graphs, and PCG graphs exist?
- Where is a Blueprint instantiated in the playable world?
- What function/event/graph implements an actor's behavior?
- What feeds a Branch, setter, function argument, or return value?
- Which internal function does a call target, and how do caller pins map to callee parameters?
- How do Animation Blueprint state machines and transitions connect?
- How does a Control Rig editor node map to the underlying RigVM model?
- Which StateTree, EQS query, PCG graph, material, AnimBP, or referenced Blueprint is associated with a placed actor/component?
- Which LevelInstance/PackedLevelActor instantiates which child world?
- What is known exactly, and what is only known through a generic package dependency?

The output is deliberately **facts-first, loss-minimizing, sharded, deterministic, and regenerable**.

## Architecture in one sentence

**Unreal extracts authoritative facts; Python derives deterministic program/world/system relationships; SQLite makes them easy to retrieve.**

See:

- [Architecture](docs/architecture.md)
- [Schema reference](docs/schema.md)
- [Subsystem coverage matrix](docs/coverage.md)
- [Cross-project workflow](docs/cross-project-workflow.md)

## Current first-class coverage

### Project and Asset Registry

- project/source/config/document files with bounded source chunks;
- Asset Registry asset identity, class, tags, package paths, physical package paths, and direct package dependencies.

Asset Registry data is the universal fallback: unsupported asset families still exist in the index, but their internal authored structure may not yet be decomposed.

### Blueprint / K2 / UMG / Animation Blueprint

Canonical extraction includes:

- Blueprint identity, inheritance, interfaces, variables, SCS components, defaults and component-template overrides;
- every graph, node, pin, exact execution/data edge, reflected node property, and normalized UObject reference;
- common K2 and AnimGraph semantic operations;
- Timelines/tracks/keys;
- UMG widget tree, widget properties, bindings, animations, and animation bindings;
- AnimGraph property bindings;
- Control Rig editor graphs.

Derived reconstruction includes:

- normalized functions/events;
- call edges and unique internal call parameter bindings;
- bounded upstream data provenance;
- execution blocks, block edges, and roots;
- normalized AnimBP state machines, states, aliases, conduits, and transitions;
- Blueprint relations, graph context, and summaries;
- Control Rig editor-node -> compact RigVM model joins.

Unknown/plugin-specific graph nodes remain preserved generically rather than being guessed from display text.

### Control Rig / RigVM

Normal scans keep a compact RigVM representation:

- graph/node objects;
- pins;
- links;
- UObject relationships/references;
- editor Control Rig node -> model-node joins.

The extremely large raw RigVM reflection stream remains opt-in with `--include-raw-rigvm-properties`.

### AI gameplay systems

Dedicated canonical extraction exists for:

- Behavior Trees;
- Blackboards and keys;
- EQS queries/options/generators/tests;
- StateTree hierarchy, tasks/evaluators, conditions, transitions, property bindings, and linked assets.

Derived AI relations preserve relationships such as Blackboard use, key selection, EQS execution, StateTree transitions, and linked assets.

### PCG

Dedicated extraction includes:

- PCG graphs;
- nodes and pins;
- exact graph edges;
- settings/properties;
- graph parameters;
- real subgraph relationships;
- derived relations/context/summaries.

### Materials

Materials are already **first-class**, not a coverage gap.

Dedicated extraction includes:

- Materials, Material Instances, and Material Functions;
- expression objects;
- exact expression/input wiring and root outputs;
- reflected properties/settings;
- parameters;
- texture/function/object references;
- derived visual relations, graph context, and summaries.

### Worlds, actors, and placement

The schema-12 world pass adds:

- world/map identity;
- persistent and classic streaming level relationships;
- loaded actors, GUIDs, labels, classes, folders, tags, transforms, ownership and attachments;
- components and component attachments/transforms;
- authored instance property overrides;
- hard/soft object references;
- Data Layers;
- World Partition metadata and actor descriptors;
- descriptor parent/reference GUID relationships.

World Partition descriptor enumeration avoids loading every external actor.

Derived world relations/context/summaries add:

- world -> actor/component relationships;
- actor -> Blueprint placement;
- attachment/ownership relationships;
- Data Layer membership;
- World Partition descriptor relationships;
- LevelInstance/PackedLevelActor -> child/source world package relationships.

### World-to-system stitching

Derived schema 10 adds `world_system_relations.jsonl`, bridging placement to the specialist models already extracted.

Current target families include:

- Blueprint;
- Animation Blueprint;
- Control Rig Blueprint;
- Widget Blueprint;
- Behavior Tree;
- Blackboard;
- EQS;
- StateTree;
- PCG Graph;
- Material / Material Instance / Material Function.

Each bridge relation keeps explicit evidence. Evidence can come from direct world references, placed Blueprint identity, Blueprint semantic relations, Blueprint package dependencies, or world package dependencies. Multiple proofs are aggregated rather than duplicated.

## Important remaining coverage gaps

UnrealAssetTool does **not** yet have first-class internals for every Unreal asset family.

The largest current gaps are:

1. **animation asset internals** — AnimSequence, AnimMontage, BlendSpace, Skeleton, Pose Search databases/schemas/channels, Chooser, Proxy Tables, IK Rig/Retargeter;
2. **Niagara and legacy Cascade particles** — systems, emitters, modules, renderers, parameters, data interfaces/events;
3. **Sequencer** — bindings, tracks, sections, channels/keyframes, subsequences, event/camera/animation/VFX/audio references;
4. **MetaSounds and audio graphs** — MetaSound nodes/pins/edges/interfaces plus SoundCue/routing assets;
5. **Enhanced Input and common gameplay-data assets** — InputAction, InputMappingContext, DataTables, project-wide Gameplay Tag structure;
6. selected mesh/skeleton/physics/rendering assets where their internals materially affect gameplay or animation understanding.

These assets are still visible generically through Asset Registry identity/dependencies and may appear through Blueprint/world references, but that is not the same as understanding their authored internals.

See [docs/coverage.md](docs/coverage.md) for the maintained coverage matrix and regression evidence.

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
  scripts/
    uatool.py
    uatool_core.py
    uatool_world_stitch.py
  docs/
    architecture.md
    schema.md
    coverage.md
    cross-project-workflow.md
```

## Recommended workflow: one canonical checkout

Keep one canonical UnrealAssetTool checkout and use its launcher against any target `.uproject`.

Example:

```text
E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

From that directory:

```powershell
python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\GameAnimationSample\GameAnimationSample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

The same checkout can scan Cropout, Content Examples, or another target project. For external targets the launcher temporarily stages only the plugin descriptor and `Source/` under the target project's `Plugins/UnrealAssetTool`, builds/scans through Unreal's normal project-plugin path, and restores/removes the temporary stage afterward.

See [docs/cross-project-workflow.md](docs/cross-project-workflow.md).

## Build behavior

Engine selection is explicit. Pass the exact editor executable:

```powershell
python scripts\uatool.py build `
    "E:\Path\MyProject.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

For standard engine layouts, `uatool` derives `Engine\Build\BatchFiles\Build.bat` from that editor path.

For UE 5.8 DebugGame, the launcher does not assume one hard-coded plugin DLL filename. It resolves the actual module through generated `.modules` metadata and repairs the plugin runtime manifest with the target project's BuildId.

## Scan

```powershell
python scripts\uatool.py scan `
    "E:\Path\MyProject.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

A normal scan:

1. validates/builds the target Editor and UnrealAssetTool module;
2. runs the structural commandlet;
3. runs the world commandlet;
4. writes canonical JSONL to `<Project>\.uatool`;
5. runs deterministic derived reconstruction;
6. builds `<Project>\.uatool\uat.db`;
7. creates `<ProjectName>.uatool.zip` beside the `.uproject`.

Useful options include:

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

`pack` reruns derivation first.

Regenerate the compact bundle:

```powershell
python scripts\uatool.py bundle `
    "E:\Path\Project\.uatool" `
    --destination "E:\Path\Project\Project.uatool.zip"
```

`bundle` also reruns derivation first.

## Query

```powershell
python scripts\uatool.py query `
    "E:\Path\Project\.uatool" `
    "Desired Aim Rotation"
```

Query output includes the specialist Blueprint/AI/PCG/material views plus world summaries/relations/context and schema-10 world-system bridge relations.

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
```

Derived interpretation can then build:

```text
execution blocks
call graph
parameter bindings
data provenance
world relationships
world-to-system joins
summaries/context
future bounded project neighborhoods
```

Derived data must remain disposable and reproducible from compatible canonical facts whenever possible.

## Versioning rule

- structural/world schema changes normally require an Unreal rescan;
- derived schema changes normally require only `derive`, `pack`, or `bundle`;
- the plugin semantic version does not replace any schema number.

## Next development priorities

The architecture is ready for **project-level graph traversal/neighborhoods**, but traversal should not hide major subsystem blind spots.

The current coverage gate is:

1. animation asset internals, especially Motion Matching/Pose Search/Chooser plus sequence/montage/blend/skeleton semantics;
2. Niagara and legacy Cascade VFX;
3. Sequencer;
4. MetaSounds/audio graph structure;
5. Enhanced Input/common gameplay-data assets where useful;
6. typed, bounded project-level traversal with provenance and coverage quality on every hop.

Traversal can evolve in parallel, but a result must distinguish a first-class semantic edge from a generic Asset Registry dependency.

See [docs/coverage.md](docs/coverage.md) for the detailed roadmap.
