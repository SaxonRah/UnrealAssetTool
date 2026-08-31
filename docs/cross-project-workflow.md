# Cross-project workflow

UnrealAssetTool supports one **canonical checkout** scanning multiple Unreal projects without maintaining a plugin source copy in every target.

Validated engine: **UE 5.8.2**.

Current schemas:

```text
structural=12
world=12
animation=1
vfx=1
systems=1
derived=14
```

## Why one checkout

One canonical source tree avoids plugin drift between projects:

```text
one source tree
one scripts/uatool.py
one UnrealAssetTool.uplugin
many target .uproject files
```

Each target owns only its `.uatool` output, upload ZIP and optional generated build cache.

## Canonical checkout

Example canonical checkout:

```text
E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool
```

Run commands from that checkout:

```powershell
cd "E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool"
```

## External target transaction

For a target where the canonical checkout is not already project-local, `uatool` performs this transaction:

```text
canonical checkout
      |
      | copy descriptor + Source only
      v
<Target>/Plugins/UnrealAssetTool       temporary stage
      |
      | restore prior build cache if present
      v
freshness-safe UBT build
      |
      +--> module-only unity build when target runtime is current
      |
      +--> otherwise full target build
      v
resolve actual UBT plugin DLL
      v
repair plugin runtime .modules manifest
using target project's BuildId
      v
run structural commandlet
      v
run world process
      +--> world
      +--> animation
      +--> VFX
      +--> systems
      v
derive / pack / bundle
      v
move generated Binaries/Intermediate to Saved cache
      v
remove temporary stage
```

The staged source contains only:

```text
UnrealAssetTool.uplugin
Source/
```

Generated build products are not maintained as plugin source copies.

## Persistent external build cache

Deleting the temporary stage used to make every external build effectively cold. The launcher now preserves generated:

```text
Binaries/
Intermediate/
```

under:

```text
<Target>/Saved/UnrealAssetToolBuildCache/
```

They are moved back into the same staged plugin path before the next build and moved out again when staging ends.

The cache is a speed optimization, not canonical output. Disable it for a run with:

```powershell
$env:UATOOL_BUILD_CACHE = "0"
```

Validated StackOBot measurements:

```text
cold UBT baseline          ~32.68 s
optimized cold UBT          18.47 s
warm cached UBT              1.25 s
cache size                  78.99 MB
```

All UBT-declared outputs, including PDBs, are retained because deleting a declared output can turn a warm no-op into a relink.

## Existing target plugin copies

If the target already contains one or more `UnrealAssetTool.uplugin` files below `Plugins`, the launcher temporarily moves each containing plugin directory completely outside `Plugins` before staging the canonical copy.

Temporary backup location:

```text
<Target>/Saved/UnrealAssetToolCrossProjectBackup/<pid>/...
```

On success or failure:

1. the generated build cache is saved if enabled;
2. the staged canonical plugin is removed;
3. original target plugin directories are restored.

## Project-local canonical checkout

If the canonical checkout already lives below the target project's `Plugins` directory, it is used directly. No temporary stage or external build-cache move is required because normal project-local build products already persist.

## Build policy

### Explicit engine selection

The exact Editor executable is always supplied by the user:

```powershell
python scripts\uatool.py build `
    "E:\Path\Project.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

For a standard engine layout, the launcher derives `Engine\Build\BatchFiles\Build.bat` from that Editor path. A custom location can be supplied with `--build-script`.

### Module-only fast path

The launcher uses the module-only path only when:

1. the target runtime module manifest exists with a valid BuildId; and
2. the `.uproject`, target `Source/`, and non-UnrealAssetTool plugin native/build inputs are not newer than that manifest.

When safe, it invokes only the scanner module:

```text
-Module=UnrealAssetTool
-ForceUnity
-DisableAdaptiveUnity
```

Adaptive unity is disabled only for this isolated scanner-module build because a temporary/untracked plugin otherwise tends to be treated entirely as the adaptive non-unity working set.

If the target changed, or if the module-only build fails, the launcher falls back to the normal full Editor target. If that target build already emitted the plugin DLL, a redundant second module build is skipped.

## UE DebugGame module resolution

Do not assume one plugin DLL filename. The launcher resolves `UnrealAssetTool` from generated `.modules` metadata and uses the target runtime BuildId.

Validated UE 5.8 layouts have produced forms such as:

```text
UnrealEditor-UnrealAssetTool.dll
UnrealEditor-UnrealAssetTool-Win64-DebugGame.dll
```

The generated manifest is authoritative; filename guessing is a fallback only when exactly one candidate exists.

## Scan examples

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

### StackOBot

```powershell
python scripts\uatool.py scan `
    "E:\TheDigitalGame\ue\StackOBot\StackOBot.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

Choose regression corpora based on the changed subsystem rather than rerunning everything blindly.

## Output locations

```text
<Target>/.uatool/
<Target>/<ProjectName>.uatool.zip
<Target>/Saved/UnrealAssetToolBuildCache/   external targets, when enabled
```

No maintained UnrealAssetTool source copy is left in an external target.

## Derived-only changes

When scanner schemas remain compatible and only Python-derived logic changes:

```powershell
python scripts\uatool.py derive "<Target>\.uatool"
python scripts\uatool.py pack   "<Target>\.uatool"
python scripts\uatool.py bundle "<Target>\.uatool" `
    --destination "<Target>\<Name>.uatool.zip"
```

A validated freshness stamp lets `pack` and `bundle` reuse current derived output. A real canonical scanner change still requires Unreal to run again.

## Bundle compression

The default upload ZIP uses Deflate level 3, selected from measured StackOBot results as the best normal speed/size tradeoff.

Override it when needed:

```powershell
$env:UATOOL_BUNDLE_LEVEL = "6"
```

Measured StackOBot bundle results:

```text
level 3   4.52 s   30.80 MB
level 6   6.84 s   24.00 MB
```

## Recommended validation strategy

### Scanner C++ change

Use the corpus that actually exercises the changed subsystem, then one broader regression corpus if the change touches shared reflection/build behavior.

### Python-derived change

Regenerate from frozen canonical corpora first. Request a new Unreal scan only when canonical facts changed.

### Build/staging change

Use an external target and test both a cold cache and immediate warm repeat. The warm repeat should be a UBT no-op when no inputs changed.

See [build-performance-and-size.md](build-performance-and-size.md) for measured build and storage results.