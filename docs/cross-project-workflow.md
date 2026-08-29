# Cross-project workflow

UnrealAssetTool is designed to be used from **one canonical checkout** against multiple Unreal projects.

This is the recommended workflow after 0.6.4.

## Why

Maintaining one plugin copy per project creates avoidable drift:

```text
Project A plugin != Project B plugin != Project C plugin
```

A canonical checkout gives you:

```text
one source tree
one scripts/uatool.py
one UnrealAssetTool.uplugin
one version to update
many target .uproject files
```

The scan output still belongs to each target project.

## Choose the canonical checkout

For the current test setup, use:

```text
E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

This is the copy that was first validated with scanner schema 11.

## Remove duplicate target-project copies

Once the canonical checkout is confirmed, remove or move the other project-local copies:

```text
E:\TheDigitalGame\ue\CropoutSampleProject\Plugins\UnrealAssetTool
E:\TheDigitalGame\ue\ContentExamples\Plugins\UnrealAssetTool
```

If you want backups, move them **outside** each project's `Plugins` directory.

Do not keep a second enabled `UnrealAssetTool.uplugin` under the target `Plugins` tree unless you deliberately want to exercise duplicate-plugin masking.

The launcher can temporarily mask duplicate descriptors, but one checkout is simpler.

## Run all scans from the canonical checkout

```powershell
cd E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

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

## Where output goes

Default output remains target-project-local:

```text
<TargetProject>\.uatool\
<TargetProject>\<ProjectName>.uatool.zip
```

For example:

```text
E:\TheDigitalGame\ue\CropoutSampleProject\.uatool\
E:\TheDigitalGame\ue\CropoutSampleProject\Cropout.uatool.zip
```

The plugin code does not need to live in that project.

## How the external plugin is selected

The launcher knows its own checkout from:

```text
scripts\uatool.py
        ↓
<checkout>\UnrealAssetTool.uplugin
```

It passes that descriptor explicitly to UnrealBuildTool and the Editor commandlet.

If the target project contains another descriptor with the same plugin name, the launcher temporarily renames that target descriptor for the duration of the build/run, then restores it.

That exists as a safety mechanism, not as a reason to keep duplicates.

## Builds

Do not assume a module built for one target is automatically sufficient for another target configuration.

The launcher:

1. determines the requested target configuration from the explicit editor filename;
2. ensures the target Editor build is ready;
3. explicitly builds the canonical UnrealAssetTool module;
4. repairs the plugin-local runtime module manifest using the **target project's BuildId**;
5. runs the target project with the canonical plugin.

For scanner C++ changes, run a normal scan or explicit build. Do not add `--no-build` unless the new module is already known to be built.

## DebugGame UE 5.8

For:

```text
UnrealEditor-Win64-DebugGame-Cmd.exe
```

expect:

```text
project runtime manifest:
<Target>\Binaries\Win64\UnrealEditor-Win64-DebugGame.modules

canonical plugin binary:
<CanonicalPlugin>\Binaries\Win64\UnrealEditor-UnrealAssetTool.dll

canonical plugin runtime manifest:
<CanonicalPlugin>\Binaries\Win64\UnrealEditor-Win64-DebugGame.modules
```

The plugin manifest BuildId is copied from the target project's runtime manifest.

## Updating UnrealAssetTool

With the canonical workflow, a new build normally means updating only:

```text
E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

Then scan whichever corpus is required for validation.

You no longer copy the plugin update into Cropout and ContentExamples.

## When a new build requires rescanning

Use this rule:

### Scanner schema changed

Example:

```text
10 -> 11
```

Unreal-extracted canonical facts changed.

**Perform an Unreal scan** for the requested regression projects.

### Only derived schema changed

Example:

```text
6 -> 7
```

Canonical facts are compatible.

Usually run:

```powershell
python scripts\uatool.py bundle "<Target>\.uatool" --destination "<Target>\<Name>.uatool.zip"
```

because `bundle` reruns derivation.

No Unreal scan is normally needed.

### Docs/version metadata only

No scan, derive, or rebuild is needed.

## Recommended development validation order

For scanner C++ changes:

```text
1. Game Animation Sample
2. inspect result
3. Cropout
4. Content Examples
5. freeze new regression baseline
```

For Python-derived changes:

```text
1. regenerate from existing frozen corpora
2. validate all three offline
3. request new Unreal scans only if canonical scanner facts changed
```

This keeps Unreal rescans purposeful rather than routine.
