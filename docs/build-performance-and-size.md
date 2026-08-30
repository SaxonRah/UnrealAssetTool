# Build performance and bundle size

This note records the performance cleanup introduced after the combined systems/project-graph milestone.

## Findings

### Cross-project C++ builds were effectively cold

Cross-project scans stage the canonical plugin under:

```text
<TargetProject>/Plugins/UnrealAssetTool
```

so UBT can discover the module normally. The old staging context deleted that directory at the end of every invocation, including the plugin's generated `Binaries` and `Intermediate` trees. The next scan therefore had to rebuild the plugin from a cold staged state.

The observed UE 5.8 build log also showed every UnrealAssetTool translation unit excluded from the adaptive unity file. UE 5.8's adaptive-unity working-set behavior is a poor fit for a temporary/untracked staged plugin: effectively the entire scanner module was treated as non-unity source.

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

### Pack and bundle redundantly rederived current output

The public commands intentionally kept themselves safe by running derivation first, but this meant a common maintenance sequence such as:

```text
derive -> pack -> bundle
```

ran the same deterministic derived reconstruction three times. On the validated StackOBot corpus, the first schema-14 measurement was:

```text
derive  41.18 s
pack    76.10 s
bundle  46.04 s
```

Because `pack` and `bundle` each called `derive_output()` internally, roughly 41 seconds of each later command was duplicated work. The actual SQLite and ZIP portions were therefore approximately 34.9 s and 4.9 s respectively before the later SQLite optimizations.

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

The measured StackOBot cache is 78.99 MB total:

```text
Binaries      66.66 MB
Intermediate  12.33 MB
```

The cache is moved between `Saved` and the temporary stage rather than copied, so this does not create a second simultaneous build tree.

### Prefer a freshness-safe module-only UBT build

The launcher first checks the target project's runtime module manifest. The module-only fast path is used only when:

1. the runtime manifest exists and contains a valid BuildId; and
2. the `.uproject`, project `Source`, and non-UnrealAssetTool project-plugin native/build inputs are not newer than that manifest.

The temporary UnrealAssetTool stage is deliberately excluded from this freshness check because it is the module about to be rebuilt.

When those conditions hold, the launcher skips the full Editor-target build and invokes only:

```text
-Module=UnrealAssetTool -ForceUnity -DisableAdaptiveUnity
```

The module rules also explicitly prefer unity. Disabling adaptive unity only on this isolated scanner-module build prevents the temporary/untracked stage from being split back into independent translation units.

If target-owned native/build inputs changed, the normal full Editor target is rebuilt. If module-only compilation fails for any other reason, the launcher also automatically falls back to the original full-target build. If that full target already produced the plugin DLL, the redundant second module UBT invocation is skipped.

The launcher prints elapsed wall time for each UBT step so corpus runs provide directly comparable before/after measurements.

StackOBot / UE 5.8.2 measured results:

| Build | UBT total | Wrapper elapsed | UBA actions |
|---|---:|---:|---:|
| prior baseline | ~32.68 s | — | 14 |
| module-only before adaptive-unity fix | 28.27 s | 28.58 s | 13 |
| final cold unity build | **18.47 s** | **18.77 s** | **4** |
| final warm cached build | **1.25 s** | **1.49 s** | **0** |

The final cold path is about 43.5% faster than the prior baseline. The warm path is about 96.2% faster by UBT total time. The cold action list is reduced to one unity compile plus resource and link actions.

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

The actual StackOBot repack measured:

| Output | Before | After | Reduction |
|---|---:|---:|---:|
| `.uatool` total | 1749.80 MB | 1435.14 MB | 18.0% |
| `uat.db` | 1100.12 MB | 920.29 MB | 16.3% |
| `project_neighborhoods.jsonl` | 167.00 MB | 34.46 MB | 79.4% |
| upload ZIP | 33.69 MB | 24.00 MB | 28.8% |

This removes duplicated serialization, disk writes, SQLite writes, ZIP compression work, local database size, and upload size.

### Build compact neighborhoods directly

The first schema-14 implementation generated the old expanded neighborhood object in memory and then immediately stripped it down with a second compaction pass. The final implementation emits compact hop references during traversal itself. It preserves the same edge selection, depth/direction, quality/coverage and truncation result while avoiding transient copies of source/target/evidence payloads and rendered neighborhood text.

### Reuse validated derived output

A `.derived_freshness.json` stamp is written only after a full derived pass and all validators succeed. It records:

- derived schema version;
- SHA-256 of the `uatool*.py` implementation;
- size/mtime metadata for canonical JSONL and specialist raw manifests;
- size/mtime metadata for declared derived JSONL.

`derive`, `pack`, and `bundle` can therefore reuse already-validated schema-14 output when both canonical facts and derived code are unchanged. Scanner rewrites, canonical cleanup changes, missing/changed derived files, schema changes, or Python implementation changes automatically invalidate the stamp and force normal derivation.

The stamp intentionally avoids re-hashing gigabytes of JSONL on every command; normal scanner/cleanup rewrites change file size and/or nanosecond mtime. Python source is content-hashed because source edits can change derived meaning without changing the schema number.

### Fast disposable SQLite rebuild

`uat.db` is regenerated from canonical/derived JSONL and is not authoritative storage. During the from-scratch pack, SQLite therefore uses bulk-build settings:

```text
journal_mode=OFF
synchronous=OFF
temp_store=MEMORY
cache_size≈256 MB
```

After all data has been loaded and committed, the connection runs `PRAGMA optimize` and restores normal `journal_mode=DELETE` / `synchronous=NORMAL` behavior for the completed database.

The validated freshness stamp also avoids reparsing the entire raw/derived graph a second time immediately before a pack, and the normal `scan` closeout no longer repeats full graph validation after the already-validated derive/pack path.

## Material expression GUID cleanup

`UMaterialExpression::MaterialExpressionGuid` is a generated node identifier, not authored material state. It is removed from canonical `material_properties.jsonl` during canonical post-scan cleanup, and the manifest row count is corrected.

The cleanup is byte-preserving for every retained JSONL row and idempotent. Therefore compatible existing output can be repaired with:

```powershell
python scripts\uatool.py derive <output-directory>
```

without running Unreal again.

On the validated StackOBot corpus this removed all 3,975 generated `MaterialExpressionGuid` rows.