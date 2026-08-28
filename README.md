# UnrealAssetTool

**UnrealAssetTool** builds an AI-friendly structural database of an Unreal Engine project from the project itself, rather than relying on hand-written documentation.

> **Naming note:** Unreal Engine already uses **UAT** to mean **Unreal AutomationTool**. The project remains `UnrealAssetTool`, but the command-line launcher is intentionally named `uatool` to avoid collisions with Epic's UAT.

## Goal

Given a `.uproject`, UnrealAssetTool should answer questions such as:

- What modules, plugins, source files, configs, maps, assets, and Blueprints exist?
- What depends on what?
- Which Blueprint inherits from which class?
- What variables and components are declared by a Blueprint?
- What graphs exist in a Blueprint?
- Which nodes, pins, default values, and links make up the actual Blueprint logic?
- Where is a C++ symbol or config setting defined?
- What project content is relevant to a question without loading the entire project into an AI context window?

The output is deliberately **loss-minimizing and sharded**. Raw structural facts are stored first; higher-level summaries can be derived later and regenerated without rescanning Unreal assets.

## Why it runs inside Unreal

`.uasset` and `.umap` files are serialized Unreal packages whose internal representation changes with engine versions and asset types. Reverse-engineering them outside the engine would duplicate a large amount of Unreal's loader, reflection, versioning, and editor-only logic.

The primary scanner is therefore an **Editor Commandlet**. Unreal itself supplies:

- package loading;
- the Asset Registry;
- Blueprint graph objects;
- reflection;
- project/plugin mount points;
- engine-version compatibility.

A small Python launcher invokes the commandlet and converts the JSONL records into `uat.db` for fast retrieval.

## Current MVP (0.1.9)

The first vertical slice indexes:

### Files and source

- every project file by relative path, type, size, and timestamp;
- C/C++, headers, Build.cs, Target.cs, INI, JSON, `.uproject`, `.uplugin`, Python, shader source, Markdown, and text;
- source text in 200-line chunks suitable for retrieval;
- generated/cache directories are excluded by default.
- the active UnrealAssetTool plugin installation is excluded by default so the scanner does not pollute its own project model;
- the active output directory is always excluded, including when `--output` uses a custom directory name.

### Unreal assets

- project and project-plugin assets from the Asset Registry;
- object path, package path, class, physical package path;
- all Asset Registry tags;
- direct package dependency edges.

### Blueprints

For Blueprint-family assets the scanner loads the real asset and records:

- Blueprint class, parent class, generated class, type, and status;
- member variables and pin types;
- Simple Construction Script components and attachment hierarchy;
- every graph;
- every graph node, node class, title, comment, and editor position;
- normalized semantic operation/symbol/owner fields for core K2 node types;
- structured semantic metadata for variable accesses, calls, events, casts, macros, branches, function boundaries, switches, selects, sequences, reroutes, self references, and actor spawning;
- Animation Blueprint graph kinds, state machines, states, transitions, conduits, aliases, cached poses, linked layers/input poses, slots, sequence players, and graph/state/transition result nodes;
- reflected non-transient node properties, including nested runtime-node structs flattened into addressable paths such as `Node.Sequence` and `Node.BlendSpace`;
- node-owned AnimGraph binding subobjects plus normalized `PropertyBindings` records, so runtime/thread-safe binding paths are directly queryable;
- normalized node-level UObject reference edges from reflected properties to assets/classes;
- RigVM/Control Rig model objects discovered from the Blueprint's owned UObject hierarchy, including graphs, nodes, pins, links, reflected properties, and object-reference topology;
- every pin, direction, type, defaults, and flags;
- every pin-to-pin graph edge.

This is enough to reconstruct a large portion of Blueprint control/data flow without screenshots or documentation.

## Repository layout

```text
UnrealAssetTool/
  UnrealAssetTool.uplugin
  Source/
    UnrealAssetTool/
      UnrealAssetTool.Build.cs
      Public/
        UnrealAssetToolCommandlet.h
      Private/
        UnrealAssetToolModule.cpp
        UnrealAssetToolCommandlet.cpp
  scripts/
    uatool.py
  docs/
    schema.md
```

UnrealAssetTool excludes itself from filesystem, source-text, and asset indexing by default. To deliberately index the scanner while developing/debugging it, use:

```powershell
python scripts\uatool.py scan MyProject.uproject `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" `
    --include-self
```

## Install in a project

Clone or copy this repository to:

```text
<MyProject>/Plugins/UnrealAssetTool/
```

UnrealAssetTool contains an Editor C++ module, so it must be built at least once before Unreal can load the commandlet. The launcher can do this automatically when the module DLL is missing.

## Build and scan a UE 5.8 project

Engine selection is intentionally explicit. UnrealAssetTool does **not** inspect the registry, Epic Launcher metadata, `EngineAssociation`, environment variables, or guessed installation directories. Pass the exact editor executable you want used for the scan:

```powershell
python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\GameAnimationSample\GameAnimationSample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
```

This works the same way for Launcher engines and source/custom engine builds: point `--editor` at that build's `UnrealEditor-Cmd.exe`.

If the UnrealAssetTool editor module has not been compiled yet, `scan` first invokes the project Editor build. For the standard engine layout, the build script is taken deterministically from the supplied editor path:

```text
E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe
                    ↓
E:\UE_5.8\Engine\Build\BatchFiles\Build.bat
```

For a custom engine with a nonstandard layout, provide the build script explicitly as well:

```powershell
python scripts\uatool.py scan MyProject.uproject `
    --editor "X:\MyUE\bin\UnrealEditor-Cmd.exe" `
    --build-script "X:\MyUE\Build\Build.bat"
```

You can also build separately:

```powershell
python scripts\uatool.py build `
    "E:\TheDigitalGame\ue\GameAnimationSample\GameAnimationSample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
```

Or suppress the automatic first build if you know the module is already compiled:

```powershell
python scripts\uatool.py scan MyProject.uproject `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe" `
    --no-build
```

The underlying commandlet can still be run directly once the plugin module is built:

```powershell
E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe MyProject.uproject -run=UnrealAssetTool -Output=.uatool -unattended -nop4 -nosplash -NoShaderCompile
```

## Output

```text
.uatool/
  manifest.json
  files.jsonl
  source_chunks.jsonl
  assets.jsonl
  asset_dependencies.jsonl
  blueprints.jsonl
  blueprint_nodes.jsonl
  blueprint_node_properties.jsonl
  blueprint_node_references.jsonl
  blueprint_bindings.jsonl
  rigvm_objects.jsonl
  rigvm_properties.jsonl
  rigvm_references.jsonl
  blueprint_edges.jsonl
  uat.db
```

The JSONL files are the canonical scan output. `uat.db` is a derived query/index layer and can be rebuilt at any time:

```powershell
python scripts\uatool.py pack .uatool
```

Quick search:

```powershell
python scripts\uatool.py query .uatool "Desired Aim Rotation"
```

## Nested Blueprint property/reference indexing

For visual graph nodes, important facts are often stored inside runtime structs rather than exposed as pins. UnrealAssetTool therefore flattens reflected structs into stable property paths. Examples include:

```text
Node.Sequence
Node.BlendSpace
Node.BlendProfile
Node.ControlRigAssetReference.BlueprintRigClass
Binding.*
```

Object-valued reflected fields are also emitted to `blueprint_node_references.jsonl`, giving retrieval a direct node-to-object relationship instead of forcing it to parse an exported struct string. Arrays of simple values are expanded with bounded indexed paths; arrays of structs remain available through their loss-minimizing exported value to avoid unbounded output growth.

Property Access, Chooser/Proxy evaluation, BlendSpace players, sequence evaluators, Pose Drivers, Motion Matching blend profiles, and Control Rig graph model-node paths are promoted into node semantic fields when the reflected facts are available.

## AnimGraph bindings and RigVM model extraction

`blueprint_bindings.jsonl` normalizes the entries stored in AnimGraph node binding objects instead of leaving the entire `PropertyBindings` map as one reflection string. Records retain the target property, access path, path segments, compiled context, pin types, and the raw reflected value. This makes bindings such as `BlendTime -> Get_MMBlendTime` directly searchable.

Control Rig editor nodes are only one presentation of a deeper RigVM model. UATool therefore also walks Blueprint-owned objects and records objects whose class hierarchy derives from `RigVMGraph`, `RigVMNode`, `RigVMPin`, or `RigVMLink`. The result is split into:

- `rigvm_objects.jsonl`: object identity, kind, class, outer, and factual node operation classification;
- `rigvm_properties.jsonl`: reflected RigVM graph/node/pin/link properties;
- `rigvm_references.jsonl`: normalized object and object-array references such as graph-to-node, node-to-pin, pin-to-subpin/link, and references to external assets/classes when Unreal stores them as UObject properties.

RigVM node operations distinguish function entry/return/reference, variables, units, dispatch, reroutes, enums, comments, parameters, library/template nodes, and related model-node classes by the actual Unreal class hierarchy. UATool does not infer a unit's behavior from its display name; deeper unit/function semantics can be promoted later from these model properties. This reflection-first path deliberately avoids depending on non-exported convenience methods of Unreal `MinimalAPI` editor classes.

## Design rule: facts first, interpretation second

The scanner should avoid asking an LLM to infer facts that Unreal can state exactly. For example, Blueprint graph edges are stored as graph edges, not only as generated prose. Later passes may produce natural-language summaries such as:

```text
Event Blueprint Update Animation
  -> read Velocity
  -> compute Speed
  -> if Speed > 5
       set IsMoving = true
```

But that summary is derived data. The underlying nodes, pins, defaults, classes, and links remain available so another model or newer summarizer can verify it.

## Next implementation phases

Blueprint and visual-graph understanding remains the near-term priority because it is the project truth least recoverable from ordinary source text. The next passes should deepen RigVM/Control Rig unit and pin semantics, normalize additional visual systems (Behavior Trees, StateTree, PCG, materials, Niagara, Sequencer), and validate the schema against Blueprint-heavy Epic sample projects before spending substantial effort on native C++ parsing.

### 0.2 — project semantics

- native C++ symbol index (classes, UCLASS/USTRUCT/UENUM, UPROPERTY, UFUNCTION, functions, includes);
- module/plugin dependency graph from `.uproject`, `.uplugin`, Build.cs, and Target.cs;
- class hierarchy joining native classes to Blueprint generated classes;
- config section/key model rather than source text alone.

### 0.3 — worlds and placement

- maps/worlds;
- actors, classes, labels, folders, transforms, tags;
- actor components and component attachment trees;
- property overrides;
- level/sublevel relationships;
- World Partition actor descriptors and Data Layers without forcing the entire world into memory where possible.

### 0.4 — asset-specific semantic extractors

- AnimBlueprint state machines, transitions, linked layers, slots, montages and sequences;
- Behavior Trees / Blackboards;
- Materials and material functions;
- Niagara;
- DataTables / CurveTables / DataAssets;
- Input Actions / Mapping Contexts;
- Gameplay Tags;
- PCG graphs;
- Control Rig / RigVM;
- StateTree;
- Sequencer.

### 0.5 — AI retrieval layer

- stable content hashes and incremental rescans;
- normalized entity/edge model;
- graph-aware retrieval;
- dependency expansion ("give me this Blueprint plus everything it calls/reads");
- generated project overview and per-system summaries;
- export bundles sized for model context windows;
- MCP/HTTP query service so an AI can ask the database directly instead of receiving a static dump.

## Important scope boundary

The tool should index **project truth**, not just source control text. That means its authoritative path is:

```text
filesystem + Unreal Asset Registry + loaded editor objects + reflection + graph APIs
```

not:

```text
README files + filenames + guessed asset behavior
```


### Build configuration matching

`scan` checks the build configuration encoded by the exact `--editor` executable and then verifies Unreal's matching `.modules` manifest, not merely whether some `UnrealAssetTool` DLL exists. For example, `UnrealEditor-Cmd.exe` requires the Development module while `UnrealEditor-Win64-DebugGame-Cmd.exe` requires the DebugGame module. If the matching module/manifest is absent, `scan` builds that exact configuration before launching the commandlet.
