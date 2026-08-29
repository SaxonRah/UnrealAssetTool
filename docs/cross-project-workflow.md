# Cross-project workflow

UnrealAssetTool 0.6.4 supports one **canonical checkout** scanning multiple Unreal projects without manually maintaining a plugin copy in every project.

This workflow is validated on UE 5.8.2 with:

- Game Animation Sample
- Cropout Sample Project
- Content Examples

## Why

Maintaining one plugin copy per project creates avoidable drift:

```text
Project A plugin != Project B plugin != Project C plugin
```

The canonical workflow gives you:

```text
one source tree
one scripts/uatool.py
one UnrealAssetTool.uplugin
one version to update
many target .uproject files
```

Each target project still owns its own `.uatool` output and compact bundle.

## Canonical checkout

Current validated checkout:

```text
E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

Run commands from there:

```powershell
cd E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

## How external-project scanning actually works

UnrealBuildTool reliably discovers plugin module rules when the plugin is beneath:

```text
<TargetProject>\Plugins
```

The launcher therefore does **not** depend on `-Plugin` or `-ForeignPlugin` to compile an unrelated target.

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
run UnrealAssetTool commandlet
      |
      v
remove temporary staged plugin
```

The temporary staging copy contains only:

```text
UnrealAssetTool.uplugin
Source\
```

UBT creates `Binaries/` and `Intermediate/` beneath the temporary stage as needed. The whole staged directory is deleted after the build/scan transaction.

The real canonical checkout is never duplicated as another maintained working copy.

## Existing target-project plugin copies

If a target already has one or more `UnrealAssetTool.uplugin` files beneath its `Plugins` tree, the launcher moves each containing plugin directory completely outside `Plugins` before staging the canonical copy.

Temporary backup location:

```text
<TargetProject>\Saved\UnrealAssetToolCrossProjectBackup\<pid>\...
```

After the scan (or after an error), the staged canonical copy is removed and the original target plugin directories are restored.

This is a safety mechanism. Once the one-checkout workflow is adopted, removing obsolete target-project copies is simpler.

## Same-project behavior

If the canonical checkout already lives beneath the target project's `Plugins` directory—as it does for Game Animation Sample—the launcher does not stage another copy.

It uses the existing project-local canonical plugin directly.

## Running the regression projects

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

## Output location

Output remains target-project-local:

```text
<TargetProject>\.uatool\
<TargetProject>\<ProjectName>.uatool.zip
```

Example:

```text
E:\TheDigitalGame\ue\CropoutSampleProject\.uatool\
E:\TheDigitalGame\ue\CropoutSampleProject\Cropout.uatool.zip
```

The plugin source itself does not remain in Cropout after the scan.

## Build behavior

For a normal scan the launcher:

1. determines the requested target configuration from the exact `--editor` executable;
2. stages the canonical plugin if the target is external;
3. builds the target Editor through normal project-plugin discovery;
4. explicitly builds `-Module=UnrealAssetTool`;
5. resolves the DLL UBT actually produced;
6. repairs/validates the staged/local plugin runtime manifest using the target project's BuildId;
7. launches the commandlet with `-EnablePlugins=UnrealAssetTool`;
8. derives, packs, and bundles output;
9. removes the staged plugin and restores any temporarily moved target plugin.

For scanner C++ changes, do not use `--no-build` unless you already know the staged/local plugin binary is current.

Because an external stage is temporary, ordinary cross-project scans should normally allow the launcher to build it.

## UE 5.8 DebugGame module naming

Do not assume a single UnrealAssetTool DLL filename.

In the validated setups UE 5.8 has produced both styles depending on build context, including:

```text
UnrealEditor-UnrealAssetTool.dll
```

and:

```text
UnrealEditor-UnrealAssetTool-Win64-DebugGame.dll
```

The running DebugGame Editor consumes:

```text
UnrealEditor-Win64-DebugGame.modules
```

The launcher resolves `UnrealAssetTool` from generated module metadata first. If that metadata cannot identify it, it accepts only a single unambiguous:

```text
UnrealEditor-UnrealAssetTool*.dll
```

candidate.

It then writes/repairs the plugin runtime manifest using:

```text
BuildId = target project's runtime BuildId
Modules.UnrealAssetTool = exact DLL filename UBT produced
```

Correctness does not depend on a hard-coded DebugGame naming rule.

## Manifest provenance

`manifest.json` currently records `tool_plugin_dir` from the Unreal commandlet's point of view.

For an external scan that is therefore the temporary staged path, for example:

```text
E:/TheDigitalGame/ue/CropoutSampleProject/Plugins/UnrealAssetTool
```

That does **not** mean Cropout contains a maintained plugin copy.

A future scanner/launcher schema may record the canonical source checkout separately.

## Updating UnrealAssetTool

With the canonical workflow, update only:

```text
E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

Then scan whichever corpus is required.

Do not manually copy new versions into Cropout or Content Examples.

## When rescanning is necessary

### Scanner schema changed

Example:

```text
11 -> 12
```

Canonical Unreal facts changed.

Run an Unreal scan for the requested regression projects.

### Only derived schema changed

Example:

```text
7 -> 8
```

Canonical scanner facts are compatible.

Usually regenerate with:

```powershell
python scripts\uatool.py bundle `
    "<Target>\.uatool" `
    --destination "<Target>\<Name>.uatool.zip"
```

because `bundle` reruns derivation.

### Launcher/docs only

No Unreal rescan is required unless the launcher behavior itself needs regression testing.

## Validated 0.6.4 cross-project result

The final staged Cropout and Content Examples scans match their frozen schema-11/derived-7 semantic baselines.

Expected scanner state remains:

```text
scanner schema: 11
derived schema: 7
```

The cross-project implementation changes **where the plugin is built from**, not the extracted project semantics.

## Recommended validation order

Scanner C++ changes:

```text
1. Game Animation Sample
2. inspect result
3. Cropout via canonical checkout
4. Content Examples via canonical checkout
5. freeze new regression baseline
```

Derived-only changes:

```text
1. regenerate from frozen corpora
2. validate all three offline
3. request Unreal rescans only if canonical facts changed
```
