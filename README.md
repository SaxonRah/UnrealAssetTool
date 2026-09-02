# UnrealAssetTool

**UnrealAssetTool** builds an AI-friendly structural and semantic index of an Unreal Engine project from Unreal's own serialized/editor data. It is intended to answer gameplay and content questions from authored facts rather than screenshots, guessed relationships, or hand-maintained project documentation.

> Unreal Engine already uses **UAT** for **Unreal AutomationTool**. This project is `UnrealAssetTool`; the command-line launcher is `uatool`.

## Current baseline

- release line: **0.8.0**
- Unreal target: **UE 5.8+**
- validated engine: **UE 5.8.2**
- structural scanner schema: **12**
- world scanner schema: **12**
- animation scanner schema: **1**
- VFX scanner schema: **1**
- systems scanner schema: **6**
- derived schema: **22**

The schemas are independently versioned because they represent different extraction lifecycles. A change to a Python-only derived view does not require renumbering canonical Unreal scanner output.

## Architecture in one sentence

**Unreal extracts exact authored facts; Python derives deterministic cross-system relationships; SQLite and bounded project neighborhoods make the result retrievable.**

Three rules drive the design:

1. If Unreal can state a fact exactly, store it canonically first.
2. Derived relationships must be regenerable from compatible canonical facts.
3. Generic Asset Registry package dependencies must never be presented as equivalent to first-class semantic references.

## First-class coverage

UnrealAssetTool currently has dedicated extraction for:

- project/source/config files and Asset Registry identity/dependencies;
- Blueprint/K2, Animation Blueprint graphs, UMG, Control Rig/RigVM;
- Behavior Trees, Blackboards, EQS and StateTree;
- PCG graphs;
- Materials, Material Instances and Material Functions;
- worlds, actors, components, Data Layers and World Partition descriptors;
- animation assets, Skeletons, curves, Montages, BlendSpaces, Pose Search, Pose Assets, Chooser/Proxy data, IK Rig and IK Retargeter;
- Niagara, Niagara Stateless and legacy Cascade VFX;
- LevelSequence/Sequencer structure;
- MetaSound, SoundCue and core audio assets;
- Enhanced Input and selected Common Input assets;
- general DataTable and CurveTable authored rows/values/references, PrimaryDataAsset identity and the project Gameplay Tags settings/source/dictionary/redirect model;
- Mover component/mode/settings/transition composition plus derived concrete transition behavior/routes;
- Gameplay Cameras CameraAsset/CameraRig/node/transition/director topology, generic Chooser decisions and Blueprint camera-provider/director behavior;
- Mass entity configs/ordered Traits, MassSpawner composition, spawn-generator inheritance, MassAgent components, and authored placed ZoneShape/ZoneShapePoint topology;
- Gameplay Ability System authored definitions and relationships: GameplayAbilities, triggers, additional costs, Ability Sets/grants, GameplayEffects/components/modifiers/executions/cues, Gameplay Cues, AttributeSets and attributes;
- typed project-level graph edges and bounded neighborhoods with per-hop provenance/coverage quality.

Unsupported asset families still appear through Asset Registry identity/tags/package dependencies. Their presence in `assets.jsonl` does **not** imply that UnrealAssetTool understands their internal authored structure.

See [docs/coverage.md](docs/coverage.md) for the maintained coverage matrix and remaining gaps.

## Machine-readable capability contract

Every current derive emits `capabilities.json`. It tells tools and AI what the current UnrealAssetTool build knows and, separately, which canonical passes are actually present in this corpus.

The contract includes:

- structural/world/animation/VFX/systems/derived schema versions;
- the maintained coverage vocabulary (`first_class`, `first_class_depth_pending`, `partial`, `generic_only`, `external_or_excluded`);
- per-family tool coverage and corpus coverage;
- canonical streams and high-value derived relations owned by each family;
- explicit runtime/generated-state boundaries;
- acceptance/verification provenance for evidence-driven Mass/ZoneGraph and GAS corpora when present;
- honest partial-corpus state for focused captures.

Inspect or regenerate it without rescanning Unreal:

```powershell
python scripts\uatool.py capabilities "E:\Path\Project\.uatool" --check
```

## Output model

A normal scan writes target-project-local output:

```text
<Project>/.uatool/
<Project>/<ProjectName>.uatool.zip
```

The `.uatool` directory contains canonical JSONL, deterministic derived JSONL, manifests and a regenerable `uat.db` SQLite database. The upload ZIP contains the portable JSON/manifests but omits the SQLite cache.

Important schema layers:

```text
manifest.json             structural schema 12 + derived schema 22
world_manifest.json       world schema 12
animation_manifest.json   animation schema 1
vfx_manifest.json         VFX schema 1
systems_manifest.json     systems schema 6
capabilities.json         capability contract schema 1
```

Derived schema 22 includes the typed project graph and Blueprint/Chooser/Mover/Gameplay Camera/Mass/ZoneGraph/GAS semantics while preserving the earlier derived streams:

```text
project_nodes.jsonl
project_edges.jsonl
project_neighborhoods.jsonl
blueprint_control_edges.jsonl
chooser_decisions.jsonl
chooser_decision_predicates.jsonl
mover_transition_behaviors.jsonl
mover_transition_routes.jsonl
gameplay_camera_property_providers.jsonl
gameplay_camera_property_fields.jsonl
gameplay_camera_director_inputs.jsonl
```

`project_edges.jsonl` is authoritative for typed project-graph relationships and provenance. Neighborhoods store compact references to those edges instead of duplicating full evidence payloads.

Evidence-driven acceptance/provenance manifests are included when the corresponding focused validation workflows have been run. Current accepted contracts include:

```text
systems_schema5_acceptance.json
zonegraph_world_manifest.json
mass_zonegraph_graph_expectations.json
mass_zonegraph_graph_verification.json
systems_schema6_acceptance.json
gas_graph_expectations.json
gas_graph_verification.json
```

## Quick start

Keep one canonical checkout and run its launcher against any target `.uproject`.

```powershell
cd "E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool"

python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\GameAnimationSample\GameAnimationSample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

For an external target, the launcher temporarily stages the canonical descriptor and `Source/` below that project's `Plugins/UnrealAssetTool`, builds/runs it as a normal project plugin, then removes the temporary stage. Generated staged `Binaries/` and `Intermediate/` are preserved under the target's `Saved/UnrealAssetToolBuildCache` so repeated builds remain incremental.

See [docs/cross-project-workflow.md](docs/cross-project-workflow.md).

## Commands

### Build only

```powershell
python scripts\uatool.py build `
    "E:\Path\Project.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

When the target Editor runtime manifest is current, the launcher builds only the `UnrealAssetTool` module with unity enabled. If target-owned native/build inputs changed, it falls back to the full Editor target.

### Scan

```powershell
python scripts\uatool.py scan `
    "E:\Path\Project.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

A normal scan:

1. validates/builds the target and plugin module;
2. runs structural extraction;
3. runs the world process, which also executes animation, VFX and systems passes;
4. validates raw manifests;
5. performs deterministic derivation and canonical cleanup;
6. emits the machine-readable capability contract;
7. builds `uat.db`;
8. creates the upload ZIP.

Useful scan options include:

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

Do not use `--no-build` after C++ scanner changes unless the correct module is already built for that target.

### Derived-only regeneration

If canonical scanner schemas are still compatible and only Python-derived behavior changed:

```powershell
python scripts\uatool.py derive "E:\Path\Project\.uatool"
python scripts\uatool.py pack   "E:\Path\Project\.uatool"
python scripts\uatool.py bundle "E:\Path\Project\.uatool" `
    --destination "E:\Path\Project\Project.uatool.zip"
```

A validated freshness stamp lets `pack` and `bundle` reuse current derived output instead of rebuilding it unnecessarily.

Upload ZIPs default to **Deflate level 3**, chosen from measured UE corpus results as the best speed/size tradeoff. Override it when needed:

```powershell
$env:UATOOL_BUNDLE_LEVEL = "6"
```

Set `UATOOL_BUILD_CACHE=0` to disable the cross-project build cache for a run.

### Query

```powershell
python scripts\uatool.py query `
    "E:\Path\Project\.uatool" `
    "PoseSearch"
```

The query surface searches canonical/derived specialist tables plus typed project nodes/edges. Human-readable project-neighborhood text is reconstructed on demand from compact edge references.

### Focused systems / GAS acceptance

Expensive subsystem investigations do not require a full project rescan. Systems schema 6 retains the focused capture/promote/derive/verify lifecycle used for Lyra GAS acceptance. Focused corpora are explicitly marked partial so they never imply unrelated structural/world/animation/VFX coverage.

The exact GAS graph verifier is available through the canonical launcher:

```powershell
python scripts\uatool.py gas-graph-verify "E:\Path\Lyra\.uatool"
```

See [docs/gas-evidence.md](docs/gas-evidence.md) and [docs/systems-schema-6.md](docs/systems-schema-6.md).

## Repository layout

```text
UnrealAssetTool/
  UnrealAssetTool.uplugin
  Source/UnrealAssetTool/
    UnrealAssetTool.Build.cs
    Private/
      UnrealAssetToolCommandlet.cpp
      UnrealAssetToolWorldCommandlet.cpp
      UnrealAssetToolAnimation*.cpp
      UnrealAssetToolVFX*.cpp/.inl
      UnrealAssetToolSystems*.cpp/.inl
  scripts/
    uatool.py                  # only public launcher
    uatool_core.py
    uatool_animation*.py
    uatool_vfx*.py
    uatool_systems*.py
    uatool_project_*.py
    uatool_capabilities.py
  docs/
  tests/
```

Supporting modules isolate real concerns, but there is intentionally one canonical `scripts/uatool.py` entry point.

## Regression corpora

The main UE 5.8.2 validation corpora are:

- **Game Animation Sample (GASP)** — large Blueprint/animation/Pose Search/Enhanced Input graph plus accepted Mover and Gameplay Cameras coverage;
- **City Sample** — large Mass/traffic/crowd and authored ZoneGraph regression, including accepted systems-schema-5 and schema-21 graph contracts;
- **Lyra Starter Game** — accepted systems-schema-6 / derived-schema-22 Gameplay Ability System corpus with **560 exact semantic GAS graph edges**;
- **Content Examples** — broad Sequencer, audio, MetaSound, VFX, materials and gameplay-data/Gameplay Tags coverage;
- **StackOBot + Niagara Examples** — World Partition/LevelInstance/PCG/VFX and cross-project build regression;
- **Cropout Sample Project** — compact Blueprint/gameplay regression.

A scanner family is not considered stable merely because it compiles. Corpus validation checks count invariants, endpoint resolution, deterministic identities, provenance quality, unchanged prior output where applicable and representative authored examples.

## Documentation

- [Architecture](docs/architecture.md)
- [Schema reference](docs/schema.md)
- [Coverage matrix](docs/coverage.md)
- [Cross-project workflow](docs/cross-project-workflow.md)
- [Build performance and bundle size](docs/build-performance-and-size.md)
- [Animation schema 1](docs/animation-schema-1.md)
- [VFX schema 1](docs/vfx-schema-1.md)
- [Systems schema 1](docs/systems-schema-1.md) — historical initial contract
- [Systems schema 2](docs/systems-schema-2.md) — historical gameplay-data/tag extension
- [Systems schema 4](docs/systems-schema-4.md) — historical Mover and Gameplay Cameras contract
- [Systems schema 5](docs/zonegraph-mass-schema5.md) — historical/retained Mass + authored ZoneGraph contract
- [Systems schema 6](docs/systems-schema-6.md) — current GAS extension and Lyra acceptance contract
- [GAS evidence workflow](docs/gas-evidence.md)

## Coverage policy

The project-level graph deliberately carries both **edge quality** and **target coverage**.

Current edge-quality classes are:

```text
exact_semantic
exact_reference
unique_dependency_resolution
generic_package_dependency
```

Current coverage classes are:

```text
first_class
first_class_depth_pending
partial
generic_only
external_or_excluded
```

That distinction is essential: an exact authored Blueprint-to-Niagara reference and a generic package dependency are both useful, but they are not the same fact. `capabilities.json` exposes the same vocabulary before an AI or downstream tool decides what claims it can safely make.
