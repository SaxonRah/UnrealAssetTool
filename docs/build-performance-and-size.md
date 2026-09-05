# Build performance and bundle size

This document records the current performance behavior and the measured UE 5.8.2 baseline. It is a reference for future regressions, not a development diary.

## Current behavior

UnrealAssetTool optimizes four separate costs:

1. cross-project C++ rebuilds;
2. derived graph regeneration;
3. SQLite packing;
4. upload ZIP size/compression time.

None of the size optimizations remove authoritative project-graph facts. `project_edges.jsonl` remains the source of typed graph provenance.

---

# Cross-project C++ builds

## Persistent staged-plugin cache

External targets temporarily stage the canonical plugin under:

```text
<Target>/Plugins/UnrealAssetTool
```

Generated:

```text
Binaries/
Intermediate/
```

are moved to:

```text
<Target>/Saved/UnrealAssetToolBuildCache/
```

before the temporary stage is removed and are restored for the next invocation.

The cache keeps all UBT-declared outputs, including PDBs. Removing a declared product can turn a warm no-op into a relink.

Disable it with:

```powershell
$env:UATOOL_BUILD_CACHE = "0"
```

Measured StackOBot cache:

```text
Binaries      66.66 MB
Intermediate  12.33 MB
total         78.99 MB
```

The cache is moved, not duplicated.

After an abnormal Unreal exit, Windows can briefly keep the just-loaded staged
module DLL locked. Staging cleanup retries transient `PermissionError` locks
before giving up. A persistent lock is reported as a cleanup warning rather
than replacing the scanner's original failure result; if a pre-existing target
plugin had been moved aside, its backup location is retained and reported until
the staging path can be cleared safely.

## Freshness-safe module-only build

If the target runtime manifest has a valid BuildId and no target-owned native/build input is newer than it, the launcher skips the full Editor target and builds only:

```text
-Module=UnrealAssetTool
-ForceUnity
-DisableAdaptiveUnity
```

Adaptive unity is disabled only for the isolated scanner-module build. A temporary/untracked staged plugin otherwise tends to be classified entirely as UBT's adaptive non-unity working set.

If target-owned inputs changed, or the module-only build fails, the launcher falls back to the normal full Editor target.

## Measured build result

StackOBot / UE 5.8.2:

| Build | UBT total | Wrapper elapsed | UBA actions |
| --- | ---: | ---: | ---: |
| prior baseline | ~32.68 s | — | 14 |
| optimized cold | **18.47 s** | **18.77 s** | **4** |
| warm cached | **1.25 s** | **1.49 s** | **0** |

The cold build is about **43.5% faster** than the prior baseline. The warm repeat is about **96.2% faster** by UBT total time.

The cold action shape is now effectively the architectural minimum for the current single module:

```text
compile resource
compile Module.UnrealAssetTool.cpp
link import library
link DLL
```

Further cold-build reductions would require larger source/module restructuring rather than another launcher flag.

---

# Derived schema 14 storage

## Why neighborhoods were large

Schema 13 duplicated every selected graph edge inside every root neighborhood, including full paths, provenance/evidence and rendered text. `project_edges.jsonl` already stored those facts authoritatively.

Schema 14 stores only compact hop references:

```text
depth
direction
edge_id
edge_quality
source_coverage
target_coverage
evidence_count
```

`project_edges.jsonl` keeps the full source/target/relation/evidence. Query-time rendering joins compact hops back to authoritative edges.

## Neighborhood reduction

Validated corpus replay:

| Corpus | Old neighborhood | Schema 14 | Reduction |
| --- | ---: | ---: | ---: |
| Content Examples | 560.9 MB | 109.3 MB | 80.5% |
| GASP | 751.2 MB | 140.6 MB | 81.3% |
| StackOBot | 167.0 MB | 34.46 MB | 79.4% |

## Actual StackOBot output reduction

| Output | Before | Final | Reduction |
| --- | ---: | ---: | ---: |
| `.uatool` directory | 1749.80 MB | 1435.14 MB | **18.0%** |
| `uat.db` | 1100.12 MB | **901.48 MB** | **18.1%** |
| `project_neighborhoods.jsonl` | 167.00 MB | **34.46 MB** | **79.4%** |
| upload ZIP, old behavior | 33.69 MB | — | — |
| upload ZIP, current default | — | **30.80 MB** | **8.6%** |
| upload ZIP, level 6 | — | **24.00 MB** | **28.8%** |

---

# Derived freshness

A full successful derive writes:

```text
.derived_freshness.json
```

The stamp records:

- derived schema version;
- content hash of `uatool*.py` implementation files;
- size/mtime metadata for canonical JSONL and specialist manifests;
- size/mtime metadata for declared derived JSONL.

If the stamp still matches, `derive`, `pack` and `bundle` reuse validated derived output instead of rebuilding it.

A scanner rewrite, canonical cleanup change, missing/changed derived file, schema change or Python implementation change invalidates the stamp automatically.

Repeated in-process read-back validators are also memoized by exact file metadata. A rewritten file invalidates that validator cache.

---

# SQLite packing

`uat.db` is a disposable cache rebuilt from authoritative JSONL, so from-scratch packing uses bulk-build settings:

```text
journal_mode=OFF
synchronous=OFF
temp_store=MEMORY
cache_size≈256 MB
```

Primary-key and unique constraints remain active while loading. Ordinary non-unique secondary indexes are deferred until after bulk insertion, then recreated. This both reduces pack time and produced a denser final database in the StackOBot measurement.

After packing, the connection runs `PRAGMA optimize` and restores:

```text
journal_mode=DELETE
synchronous=NORMAL
```

---

# Bundle compression

The upload bundle uses ordinary ZIP/Deflate and defaults to **compression level 3**.

Override it with:

```powershell
$env:UATOOL_BUNDLE_LEVEL = "6"
```

Accepted values are 0 through 9.

Measured on identical StackOBot schema-14 content:

| Level | Time | ZIP size |
| --- | ---: | ---: |
| 1 | 38.69 s* | 33.36 MB |
| **3** | **4.52 s** | **30.80 MB** |
| 6 | 6.84 s | 24.00 MB |

`*` Level 1 ran first and was strongly affected by cold filesystem/cache state. The reliable warm comparison is level 3 versus level 6. Level 3 is faster while still producing an upload smaller than the old 33.69 MB baseline. Level 6 remains available when minimum upload size matters more than CPU time.

---

# Post-processing benchmark

Original StackOBot maintenance sequence:

```text
derive   41.18 s
pack     76.10 s
bundle   46.04 s
total   163.32 s
```

Final measured sequence:

```text
derive   32.03 s
pack     22.11 s
bundle    4.52 s
total    58.66 s
```

That is about **64.1% faster end-to-end** for `derive -> pack -> bundle`.

The profiled final project/VFX stages were:

```text
vfx_stitch.derive                 0.582 s
vfx-derived validation            0.182 s
project_graph.derive              2.716 s
project_graph.finalize            1.959 s
project_neighborhoods.rebuild     0.524 s
project-graph validation          7.272 s
project-finalize validation       0.840 s
project-neighborhood validation   1.391 s
```

The remaining first-derive time is largely in the older Blueprint/world/animation derived pipeline plus JSON parsing/serialization. Subsequent operations normally reuse the freshness stamp.

---

# Canonical generated-value cleanup

Generated `UMaterialExpression::MaterialExpressionGuid` rows are removed from `material_properties.jsonl` during canonical cleanup and the structural manifest count is corrected.

The cleanup is byte-preserving for retained rows and idempotent. Existing compatible outputs can be repaired with:

```powershell
python scripts\uatool.py derive <output-directory>
```

without rerunning Unreal.

Validated StackOBot cleanup:

```text
MaterialExpressionGuid rows: 3975 -> 0
```

See [architecture.md](architecture.md) for the canonical/derived boundary and [cross-project-workflow.md](cross-project-workflow.md) for staging/build behavior.