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

## Current MVP (0.1)

The first vertical slice indexes:

### Files and source

- every project file by relative path, type, size, and timestamp;
- C/C++, headers, Build.cs, Target.cs, INI, JSON, `.uproject`, `.uplugin`, Python, shader source, Markdown, and text;
- source text in 200-line chunks suitable for retrieval;
- generated/cache directories are excluded by default.

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

## Install in a project

Clone or copy this repository to:

```text
<MyProject>/Plugins/UnrealAssetTool/
```

Regenerate project files/build the editor target if Unreal requests it. The plugin is Editor-only and contains no runtime content.

## Scan a UE 5.8 project

From the plugin repository or any directory:

```powershell
python scripts\uatool.py scan E:\TheDigitalGame\ue\hyperreality\hyperreality.uproject --engine G:\UE_5.8
```

If Unreal is installed in Epic's normal `C:\Program Files\Epic Games\UE_<version>` location and the `.uproject` has a normal `EngineAssociation`, `--engine` may be omitted.

You can also point directly at the command executable:

```powershell
python scripts\uatool.py scan MyProject.uproject --editor G:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Cmd.exe
```

The commandlet can also be run directly:

```powershell
UnrealEditor-Cmd.exe MyProject.uproject -run=UnrealAssetTool -Output=.uatool -unattended -nop4 -nosplash -NoShaderCompile
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
