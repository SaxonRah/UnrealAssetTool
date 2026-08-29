# UnrealAssetTool

**UnrealAssetTool** builds an AI-friendly structural index of an Unreal Engine project from Unreal's own serialized/editor data instead of relying on hand-written project documentation.

> Unreal Engine already uses **UAT** for **Unreal AutomationTool**. The project is `UnrealAssetTool`; the command-line launcher is `uatool`.

## Current stable baseline

**UnrealAssetTool 0.6.4**

- Unreal target: **UE 5.8+**
- validated engine: **UE 5.8.2**
- scanner schema: **11**
- derived schema: **7**
- canonical storage: line-oriented JSONL emitted from Unreal
- derived storage/retrieval: regenerable JSONL views plus SQLite
- validated regression corpora:
  - Game Animation Sample
  - Cropout Sample Project
  - Content Examples

Schema 11 and derived schema 7 are intentionally separate version numbers:

- **scanner schema 11** describes facts that require Unreal/editor objects and therefore require an Unreal rescan when the schema changes;
- **derived schema 7** describes deterministic Python reconstruction that can be regenerated from compatible canonical JSONL without reopening Unreal.

## Goal

Given a `.uproject`, UnrealAssetTool should help answer questions such as:

- What modules, plugins, source files, configs, maps, assets, and Blueprints exist?
- What depends on what?
- Which Blueprint inherits from which class?
- What variables, components, interfaces, defaults, and authored overrides exist?
- What graphs, nodes, pins, defaults, and exact links implement Blueprint logic?
- What execution paths exist?
- Where did a value feeding a Branch, setter, return, or impure call come from?
- Which internal Blueprint function does a call target?
- How do a caller's argument/return pins correspond to a callee's parameters?
- How are Animation Blueprint state machines, states, aliases, conduits, and transitions connected?
- How do Control Rig editor graphs map to the underlying RigVM model?
- How do Behavior Trees, Blackboards, EQS, StateTrees, PCG, and materials connect to surrounding project content?
- What project content is relevant to a question without loading the entire project into an AI context window?

The output is deliberately **facts-first, loss-minimizing, sharded, and regenerable**. Unreal-extracted structural truth remains available even when later interpretation algorithms change.

## Architecture in one sentence

**Unreal extracts authoritative facts; Python reconstructs deterministic program/context views; SQLite makes those facts and views easy to retrieve.**

See [docs/architecture.md](docs/architecture.md) for the full architecture.

## Current scope

### Files and source

The scanner records project files with path, kind, size, timestamp, and source/config/document text in bounded line chunks.

Generated/cache directories are excluded by default. The active UnrealAssetTool checkout and output directory are also excluded by default so the tool does not pollute its own project model.

### Unreal assets and dependencies

The scanner records project and project-plugin Asset Registry assets, tags, package identity, class, physical package path, and direct package dependency edges.

### Blueprints and visual program structure

Schema 11 records the real Blueprint/editor graph structure:

- Blueprint identity, parent/generated classes, type, and status;
- declared variables;
- SCS components and attachment hierarchy;
- graph identity, kind, system, schema, and nesting;
- node identity/class/title/comment/editor position;
- normalized node semantics;
- normalized pins, types, defaults, visibility/connectability metadata, and links;
- execution-vs-data edge classification;
- Blueprint interfaces;
- reflected non-transient node properties;
- normalized node-to-UObject references;
- AnimGraph property bindings;
- class-default-object overrides;
- component-template overrides;
- bounded nested changed-state paths;
- Timelines, tracks, and curve keys;
- UMG widget trees, instance/slot overrides, bindings, animations, and animation bindings.

#### Struct operations fixed in schema 11

`UK2Node_MakeStruct`, `UK2Node_BreakStruct`, and `UK2Node_SetFieldsInStruct` inherit through Unreal's struct-operation/variable hierarchy. Schema 11 classifies them canonically as:

- `make_struct`
- `break_struct`
- `set_fields_in_struct`

and records the exact `struct_type` instead of misclassifying them as generic variable references.

### Blueprint reconstruction

Derived schema 7 reconstructs higher-level program facts without replacing raw graph truth:

- normalized function definitions and authoritative UFunction flags;
- normalized event definitions;
- call-site resolution to internal/external/ambiguous/unresolved targets;
- call-site ↔ callee parameter bindings, including split-struct pins;
- bounded upstream data provenance for execution-relevant inputs;
- deterministic execution basic blocks and block edges;
- semantic roots for functions/events;
- Blueprint relations;
- graph-context text;
- per-Blueprint summaries.

#### Data provenance

`blueprint_data_dependencies.jsonl` follows upstream data edges from connected non-exec inputs on execution-bearing/result nodes through pure/data-only nodes.

It preserves:

- sink node/pin;
- expression tree and compact expression text;
- variable reads;
- function calls;
- object references;
- side-effect/execution boundaries;
- cycle detection;
- truncation status.

Current safety bounds are 24 recursive levels and 64 expression nodes per dependency.

#### Cross-function bindings

`blueprint_call_bindings.jsonl` maps uniquely resolved internal Blueprint call pins to the actual callee parameter pins.

It supports:

- caller argument → callee input parameter;
- callee return parameter → caller output;
- split struct pin matching;
- links to provenance dependency IDs and downstream consumer pins.

Ambiguous interface/override targets are deliberately **not** forced into a unique binding.

### Animation Blueprints

The scanner plus derived layer covers:

- AnimGraphs;
- state machines;
- states;
- transitions;
- conduits;
- aliases;
- state-entry targets;
- cached poses;
- linked layers/input poses;
- slots;
- sequence players/evaluators;
- common AnimGraph node semantics;
- exact transition endpoints and key transition settings;
- normalized `anim_state_machines`, `anim_states`, and `anim_transitions`.

### Control Rig / RigVM

Normal scans store a compact RigVM model:

- graph/node objects;
- pins;
- links;
- object relationships;
- editor-ControlRig-node ↔ model-node joins.

The very large raw reflection stream is opt-in via `--include-raw-rigvm-properties`.

### AI gameplay systems

Current canonical coverage includes:

- Behavior Trees;
- Blackboard assets and keys;
- EQS options/generators/tests;
- StateTree hierarchy, tasks/evaluators, conditions, transitions, bindings, and linked assets.

Python derives normalized AI relations and compact summaries.

### PCG and materials

Current coverage includes:

- PCG graphs, nodes, pins, exact edges, settings/properties, and parameters;
- material/material-function graphs, expressions, parameter/function/texture relationships, root outputs, and exact expression wiring;
- visual-system relations, context, and summaries.

A schema-5 derivation bug that treated reflected PCG ownership back-references as subgraph uses has been removed; only real non-self graph references or explicitly named subgraph fields become `uses_subgraph`.

## What is not the current priority

UnrealAssetTool is not trying to collect every possible Unreal asset family as quickly as possible.

The present priority is **gameplay understanding**:

1. keep canonical Blueprint/visual-program semantics accurate;
2. deepen cross-function/cross-system provenance and call-chain reconstruction;
3. add map/world/actor placement so extracted gameplay systems can be located in the actual game world;
4. then expand breadth into systems such as Sequencer, Niagara, and MetaSounds when they materially improve project understanding.

Native C++ semantic parsing is secondary for now because source text is already directly retrievable. A future Clang-based pass is preferable to regex inference.

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
    architecture.md
    schema.md
    cross-project-workflow.md
```

## Recommended workflow: one canonical checkout

Keep one canonical UnrealAssetTool checkout and use its launcher against any target `.uproject`.

This avoids manually synchronizing multiple copies.

See [docs/cross-project-workflow.md](docs/cross-project-workflow.md).

### Example canonical checkout

```text
E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

From that directory:

```powershell
python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\GameAnimationSample\GameAnimationSample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

The same launcher can target another project:

```powershell
python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\CropoutSampleProject\Cropout.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

and:

```powershell
python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\ContentExamples\ContentExamples.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

For an external target, the launcher temporarily stages the canonical checkout's `UnrealAssetTool.uplugin` and `Source/` tree under `<TargetProject>/Plugins/UnrealAssetTool`, builds and scans through Unreal's normal project-plugin path, then removes the staged copy automatically.

If the target already contains its own UnrealAssetTool plugin directory, the launcher moves that whole directory temporarily outside `Plugins`, restores it afterward, and never modifies it. Removing duplicate target-project copies is still cleaner once the canonical workflow is adopted.

## Build behavior

Engine selection is explicit. UnrealAssetTool does not guess an engine installation from the registry, Epic Launcher metadata, `EngineAssociation`, or environment variables.

Pass the exact editor executable:

```powershell
python scripts\uatool.py build `
    "E:\TheDigitalGame\ue\GameAnimationSample\GameAnimationSample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

For standard engine layouts, the launcher derives `Engine\Build\BatchFiles\Build.bat` from that editor path. Use `--build-script` only for a nonstandard custom layout.

### UE 5.8 DebugGame detail

For a DebugGame Editor target:

- the running executable can be `UnrealEditor-Win64-DebugGame-Cmd.exe`;
- the target project's game module is DebugGame;
- the running DebugGame process consumes `UnrealEditor-Win64-DebugGame.modules`;
- Unreal may emit the UnrealAssetTool Editor-module DLL as either an unsuffixed Editor binary or a `-Win64-DebugGame` binary depending on how the plugin participates in the target;
- the launcher therefore does **not** hard-code the plugin DLL name;
- it resolves the actual module from generated `.modules` metadata (falling back only to a unique UBT-produced DLL), then writes the plugin runtime manifest with the **target project's BuildId** and that exact DLL filename.

This behavior was validated through the canonical cross-project staging workflow on Game Animation Sample, Cropout, and Content Examples.

## Scan

A normal scan:

```powershell
python scripts\uatool.py scan `
    "E:\Path\MyProject.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

By default it:

1. checks/builds the target Editor and UnrealAssetTool module as required;
2. runs the Unreal commandlet;
3. writes canonical JSONL to `<Project>\.uatool`;
4. runs the deterministic derived pass;
5. builds `<Project>\.uatool\uat.db`;
6. creates `<ProjectName>.uatool.zip` beside the `.uproject`.

Useful scan options:

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

Do not use `--no-build` after scanner C++ changes unless you already know the correct module was rebuilt.

## Derived-only regeneration

If scanner schema is compatible and only Python-derived logic changed:

```powershell
python scripts\uatool.py derive "E:\Path\Project\.uatool"
```

Rebuild SQLite:

```powershell
python scripts\uatool.py pack "E:\Path\Project\.uatool"
```

`pack` reruns derivation first.

Regenerate the compact upload ZIP:

```powershell
python scripts\uatool.py bundle `
    "E:\Path\Project\.uatool" `
    --destination "E:\Path\Project\Project.uatool.zip"
```

`bundle` also reruns derivation first.

## Compact upload bundle

The normal upload ZIP deliberately excludes:

- `uat.db`;
- `rigvm_properties.jsonl` unless explicitly requested.

This keeps the upload artifact compact while preserving canonical and useful derived JSONL.

`uat.db` is only a regenerable local index.

## Query

Quick text/index search:

```powershell
python scripts\uatool.py query `
    "E:\Path\Project\.uatool" `
    "Desired Aim Rotation"
```

The query command searches source/assets plus normalized Blueprint, call-graph, call-binding, provenance, execution, AnimBP, AI, PCG, and material views.

## Canonical vs derived rule

If Unreal can state a fact exactly, store that fact first.

Examples:

```text
node class
pin type
pin default
pin link
UFunction flags
struct type
transition endpoint
asset reference
world transform
```

Interpretation can then produce:

```text
execution blocks
call graph
parameter bindings
data provenance
summaries
readable graph context
```

Derived data must remain disposable and reproducible from canonical data whenever possible.

## Versioning rule

A scanner-schema change means canonical Unreal output changed and normally requires an Unreal rescan.

A derived-schema change means deterministic reconstruction changed and can normally be regenerated with `derive`, `pack`, or `bundle`.

The plugin's semantic version does not replace either schema number.

## Next development milestone

With 0.6.4 stabilized, the next major extractor priority is **map/world/actor placement and authored world state**, while continuing targeted cross-system provenance improvements where the current corpora expose real gaps.

The world pass should prefer metadata/descriptor APIs where possible and avoid blindly loading every World Partition actor.

See [docs/architecture.md](docs/architecture.md#next-development-priority-world-and-placement).
