# Build performance and bundle size

This note records the performance cleanup introduced after the combined systems/project-graph milestone.

## Findings

### Cross-project C++ builds were effectively cold

Cross-project scans stage the canonical plugin under:

```text
<TargetProject>/Plugins/UnrealAssetTool
```

so UBT can discover the module normally. The old staging context deleted that directory at the end of every invocation, including the plugin's generated `Binaries` and `Intermediate` trees. The next scan therefore had to rebuild the plugin from a cold staged state.

The observed UE 5.8 build log also showed every UnrealAssetTool translation unit excluded from the adaptive unity file. UE 5.8's documented adaptive-unity heuristic uses source-control working-set state; a temporary/untracked staged plugin is a poor fit for that heuristic.

### The full Editor target was rebuilt before every module build

The launcher always invoked:

```text
<Target>Editor Win64 <Config>
```

and then invoked the same target again with:

```text
-Module=UnrealAssetTool
```

This is robust for a never-built project, but redundant after the target already has a valid, current runtime module manifest/BuildId.

### Project neighborhoods dominated derived output size

The schema-13 neighborhood stream repeated the complete selected project edge inside every root neighborhood, including full source/target paths, evidence arrays, and an additional rendered text copy. `project_edges.jsonl` already stores those facts authoritatively.

Measured from validated UE 5.8.2 corpora:

| Corpus | Bundle ZIP | Uncompressed bundle | `project_neighborhoods.jsonl` | ZIP-compressed neighborhood |
|---|---:|---:|---:|---:|
| ContentExamples | 120.7 MB | 2383.4 MB | 560.9 MB | 44.2 MB |
| GASP | 108.8 MB | 2237.9 MB | 751.2 MB | 39.6 MB |
| StackOBot | 33.7 MB | 649.7 MB | 167.0 MB | 12.8 MB |

In ContentExamples alone, the duplicate rendered neighborhood `text` fields account for about 153 MB of that JSONL before compression. Persisting the same expanded text in SQLite would duplicate it again locally.

## Changes

### Persistent staged-plugin build cache

For a cross-project target only, the staged plugin's generated:

```text
Binaries/
Intermediate/
```

are moved to:

```text
<TargetProject>/Saved/UnrealAssetToolBuildCache/
```

before the temporary plugin stage is removed. They are moved back into the same stable plugin path before the next build. Project-local canonical builds are unchanged because their build products already persist normally.

All UBT-declared build products are retained in this local cache. In particular, PDBs are kept because deleting a declared output can turn a would-be warm no-op into a relink. The cache deliberately trades some target-local `Saved` disk space for faster repeated builds; upload/output size is addressed independently below.

Set:

```text
UATOOL_BUILD_CACHE=0
```

to disable this cache for a run.

### Prefer a freshness-safe module-only UBT build

The launcher first checks the target project's runtime module manifest. The module-only fast path is used only when:

1. the runtime manifest exists and contains a valid BuildId; and
2. the `.uproject`, project `Source`, and non-UnrealAssetTool project-plugin native/build inputs are not newer than that manifest.

The temporary UnrealAssetTool stage is deliberately excluded from this freshness check because it is the module about to be rebuilt.

When those conditions hold, the launcher skips the full Editor-target build and invokes only:

```text
-Module=UnrealAssetTool -ForceUnity
```

This avoids rebuilding unrelated project code and forces the scanner module into unity compilation instead of allowing a temporary/untracked stage to be classified entirely as the adaptive non-unity working set.

If target-owned native/build inputs changed, the normal full Editor target is rebuilt. If module-only compilation fails for any other reason, the launcher also automatically falls back to the original full-target build. If that full target already produced the plugin DLL, the redundant second module UBT invocation is skipped.

The launcher prints elapsed wall time for each UBT step so corpus runs provide directly comparable before/after measurements.

### Schema 14 compact project neighborhoods

Schema 14 does **not** remove graph facts. `project_edges.jsonl` remains the authoritative typed graph and retains:

- source/target type and path;
- relation;
- source/target coverage;
- edge quality;
- full evidence/provenance.

A neighborhood hop now stores only:

```text
depth
direction
edge_id
edge_quality
source_coverage
target_coverage
evidence_count
```

This keeps the required quality/coverage classification directly on every hop while using `edge_id` as the provenance reference into `project_edges.jsonl`.

The JSONL neighborhood no longer embeds a second rendered text copy. SQLite also stores the compact neighborhood instead of expanding the text again. `uatool query` joins each selected hop's `edge_id` to `project_edges` and renders the human-readable neighborhood on demand. This keeps the query surface while avoiding the duplicated text in both the upload bundle and local `uat.db`.

Replaying the compact representation over the validated corpora produces:

| Corpus | Old neighborhood | Compact neighborhood | Reduction | Approx. compressed old -> compact |
|---|---:|---:|---:|---:|
| ContentExamples | 560.9 MB | 109.3 MB | 80.5% | 44.2 MB -> 10.2 MB |
| GASP | 751.2 MB | 140.6 MB | 81.3% | 39.6 MB -> 12.9 MB |
| StackOBot | 167.0 MB | 34.6 MB | 79.3% | 12.8 MB -> 3.2 MB |

This also reduces JSON serialization, disk writes, SQLite writes, ZIP compression work, local database size, and upload size.

## Material expression GUID cleanup

`UMaterialExpression::MaterialExpressionGuid` is a generated node identifier, not authored material state. It is removed from canonical `material_properties.jsonl` during canonical post-scan cleanup, and the manifest row count is corrected.

The cleanup is byte-preserving for every retained JSONL row and idempotent. Therefore compatible existing output can be repaired with:

```powershell
python scripts\uatool.py derive <output-directory>
```

without running Unreal again.
