# Cross-project workflow

UnrealAssetTool 0.7.0 supports one **canonical checkout** scanning multiple Unreal projects without manually maintaining a plugin copy in every project.

Validated engine: **UE 5.8.2**.

Primary regression projects:

- Game Animation Sample
- Cropout Sample Project
- Content Examples

Occasional targeted probe:

- StackOBot

Current schema baseline:

```text
structural scanner schema: 12
world scanner schema:      12
derived schema:            10
```

## Why one checkout

Maintaining one plugin copy per project creates avoidable drift:

```text
Project A plugin != Project B plugin != Project C plugin
```

The canonical workflow gives:

```text
one source tree
one scripts/uatool.py
one UnrealAssetTool.uplugin
one version to update
many target .uproject files
```

Each target project still owns its own `.uatool` output and compact bundle.

## Canonical checkout

Validated canonical checkout:

```text
E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

Run commands from there:

```powershell
cd E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

## How external-project scanning works

UnrealBuildTool reliably discovers plugin module rules when the plugin is beneath:

```text
<TargetProject>\Plugins
```

The launcher therefore does not depend on `-Plugin` or `-ForeignPlugin` for unrelated target builds.

For an external target it performs this transaction:

```text
canonical checkout
      |
      | copy descriptor + Source only
      v
<TargetProject>\Plugins\UnrealAssetTool   (temporary)
      |
      v
normal target Editor build
      |
      v
normal -Module=UnrealAssetTool build
      |
      v
resolve actual UBT-produced plugin DLL
      |
      v
repair plugin runtime .modules manifest
using target project's BuildId
      |
      v
run structural commandlet
      |
      v
run world commandlet
      |
      v
derive / pack / bundle
      |
      v
remove temporary staged plugin
```

The temporary staging copy contains only:

```text
UnrealAssetTool.uplugin
Source\
```

UBT may create `Binaries/` and `Intermediate/` under the temporary stage. The whole stage is removed after the transaction.

## Existing target-project plugin copies

If a target already contains one or more `UnrealAssetTool.uplugin` files below its `Plugins` tree, the launcher temporarily moves each containing plugin directory completely outside `Plugins` before staging the canonical copy.

Temporary backup location:

```text
<TargetProject>\Saved\UnrealAssetToolCrossProjectBackup\<pid>\...
```

After success or failure:

1. the staged canonical plugin is removed;
2. the target's original plugin directories are restored.

Once the one-checkout workflow is adopted, deleting obsolete maintained copies is still simpler.

## Same-project behavior

If the canonical checkout already lives under the target project's `Plugins` directory, as with Game Animation Sample, the launcher uses it directly and does not stage a second copy.

## Regression commands

### Game Animation Sample

```powershell
python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\GameAnimationSample\GameAnimationSample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

### Cropout

```powershell
python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\CropoutSampleProject\Cropout.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

### Content Examples

```powershell
python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\ContentExamples\ContentExamples.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

StackOBot is not part of every iteration. Use it when a feature needs the coverage it uniquely provided, especially World Partition descriptor references or LevelInstance/PackedLevelActor behavior.

## Output location

Output remains target-project-local:

```text
<TargetProject>\.uatool\
<TargetProject>\<ProjectName>.uatool.zip
```

For example:

```text
E:\TheDigitalGame\ue\CropoutSampleProject\.uatool\
E:\TheDigitalGame\ue\CropoutSampleProject\Cropout.uatool.zip
```

No maintained plugin source remains in an external target after the scan transaction.

## Build behavior

For a normal scan the launcher:

1. resolves the requested target configuration from the exact `--editor` executable;
2. stages the canonical plugin if the target is external;
3. builds the target Editor;
4. explicitly builds `-Module=UnrealAssetTool`;
5. resolves the DLL UBT actually produced;
6. repairs/validates the staged/local plugin runtime manifest using the target project's BuildId;
7. runs the structural UnrealAssetTool commandlet;
8. runs the UnrealAssetToolWorld commandlet;
9. derives, packs, and bundles output;
10. removes the staged plugin and restores temporarily moved target plugin copies.

For C++ scanner changes, do not use `--no-build` unless the correct module is already rebuilt.

Because an external stage is temporary, ordinary external scans should normally allow the launcher to build it.

## UE 5.8 DebugGame module naming

Do not assume one plugin DLL filename.

Validated UE 5.8 builds have produced forms including:

```text
UnrealEditor-UnrealAssetTool.dll
UnrealEditor-UnrealAssetTool-Win64-DebugGame.dll
```

The running DebugGame Editor consumes:

```text
UnrealEditor-Win64-DebugGame.modules
```

The launcher resolves the `UnrealAssetTool` DLL from generated `.modules` metadata first. If metadata cannot identify it, it accepts only one unambiguous `UnrealEditor-UnrealAssetTool*.dll` candidate.

It then writes/repairs the plugin runtime manifest using:

```text
BuildId = target project's runtime BuildId
Modules.UnrealAssetTool = exact DLL filename UBT produced
```

Correctness does not depend on a hard-coded DebugGame naming rule.

## Manifest provenance

`manifest.json` records `tool_plugin_dir` from the Unreal commandlet's point of view.

For an external scan this is the temporary staged location, for example:

```text
E:/TheDigitalGame/ue/CropoutSampleProject/Plugins/UnrealAssetTool
```

That does not mean the target contains a maintained plugin copy.

## Updating UnrealAssetTool

Update only the canonical checkout:

```text
E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

Then scan or regenerate whichever corpus is required.

Do not manually copy plugin versions into Cropout or Content Examples.

## When rescanning is necessary

### Structural/world scanner schema changed

Example:

```text
structural: 12 -> 13
```

or:

```text
world: 12 -> 13
```

Canonical Unreal facts changed. Rebuild and run the requested Unreal regression scans.

### Only derived schema changed

Example:

```text
derived: 10 -> 11
```

Compatible canonical facts can normally be reused.

Regenerate with:

```powershell
python scripts\uatool.py bundle `
    "<Target>\.uatool" `
    --destination "<Target>\<Name>.uatool.zip"
```

because `bundle` reruns derivation. `pack` also reruns derivation before rebuilding SQLite.

### Docs/plugin descriptor only

No Unreal rescan is required unless the change itself affects build/launcher behavior that needs verification.

## Current validated semantic state

The cross-project infrastructure has been validated through the 0.7.0 world/system-stitching milestone.

The workflow does not change project semantics; it changes where the plugin is built from and ensures the correct module is loaded by the target Editor.

Current expected schemas:

```text
structural=12
world=12
derived=10
```

## Recommended validation order

### Scanner C++ changes

```text
1. Game Animation Sample when animation/Blueprint coverage is relevant
2. inspect result
3. Cropout for compact gameplay regression
4. Content Examples for broad engine-feature regression
5. StackOBot only when its unique coverage is useful
6. freeze the new baseline
```

### Derived-only changes

```text
1. regenerate from frozen corpora
2. validate offline first
3. request Unreal rescans only when canonical facts changed
```

### New subsystem extractors

Choose the corpus that actually exercises the subsystem rather than rerunning every project blindly. For example, Content Examples is currently the strongest broad probe for Niagara, Sequencer, MetaSounds, materials, and PCG, while Game Animation Sample is the strongest animation/Motion Matching corpus.
