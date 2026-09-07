# Native semantics schema 1

## Purpose

UnrealAssetTool's native semantic layer connects three independently proven sources of truth without weakening their evidence boundaries:

1. Unreal reflection truth for project/project-plugin native types and functions.
2. Compiler-resolved project-owned C/C++ symbols, parameters and direct calls.
3. Exact reflected-to-source joins proven by module scope, C++ identity and parameter projection.

The JSONL streams remain authoritative. SQLite is a disposable retrieval cache.

## Authoritative inputs

### Reflected native schema 1

Produced by `uatool native-capture`.

Relevant query/index streams:

```text
native_types.jsonl
native_functions.jsonl
native_function_parameters.jsonl
```

The complete reflected capture also contains modules, interfaces, properties, enums and enum values.

### Compiler-resolved native AST schema 1

Produced by `uatool ast-capture`.

```text
native_ast_manifest.json
native_ast_symbols.jsonl
native_ast_parameters.jsonl
native_ast_calls.jsonl
native_ast_diagnostics.jsonl
```

Project-owned semantic identity is compiler-derived. Clang USR is retained when available. Symbols are canonicalized while call rows remain translation-unit-specific. Engine/system headers may participate in compilation but are not emitted as project-owned symbols. Current compiler schema-1 outputs declare ruleset `libclang_semantic_callable_owner_v1`: parameter rows are accepted only when the libclang semantic parent exactly matches the current callable identity, and calls inside a lambda body are not attributed to an enclosing function when the lambda callable itself does not materialize as a canonical symbol. Rejected parameter-owner mismatches and conservatively suppressed nested-callable calls are counted in the manifest.

Any indexing-only compatibility replay is retained on each affected symbol/call as `compatibility_overrides`.

### Reflected/source join schema 1

Produced by `uatool native-join`.

```text
native_join_manifest.json
native_type_joins.jsonl
native_function_joins.jsonl
native_join_diagnostics.jsonl
```

Join schema 1 uses exact proof only. Ambiguity and legitimate missing authored counterparts remain diagnostics; they are never promoted by fuzzy name similarity. Current outputs also declare ruleset `reflection_parameter_projection_v1`; validation rejects earlier schema-1 join directories that predate the reflected-to-source passing-mode projection fix and tells the caller to regenerate only the cheap join layer from retained reflected/compiler inputs.

## SQLite cache schema 1

`uatool native-index` imports the three validated roots into the standard `uat.db`. If the database is missing, the command initializes the full canonical UnrealAssetTool SQLite schema first, then imports the native rows.

```text
native_index_meta
native_reflected_types
native_reflected_functions
native_reflected_function_parameters
native_compiler_symbols
native_compiler_parameters
native_compiler_calls
native_type_joins
native_function_joins
native_join_diagnostics
```

Important lookup indexes cover:

- reflected type/function paths;
- source symbol IDs and occurrence IDs;
- Clang USRs;
- qualified/source names;
- source path + line;
- translation unit;
- caller symbol;
- target symbol and target USR;
- unresolved/ambiguous join status.

The importer validates source manifests and JSONL counts before writing, requires every caller to resolve to a canonical project symbol, rejects excluded build/source leakage, and rechecks SQLite row counts after loading. Compiler parameter cache identity mirrors the authoritative AST canonical key exactly: `(function_occurrence_id, parameter_index, name, type_spelling)`. A repeated numeric parameter index is therefore preserved when the authoritative stream distinguishes the rows by name/type; the cache does not collapse or renumber them. A non-empty compiler `target_symbol_id` is preserved even when no canonical symbol row materializes for that referenced cursor. This can occur because call-target identity is assigned from a compiler-resolved project-relative cursor while canonical symbol emission uses stricter authored/traversal filters. Exact Clang USR is used as a navigation fallback when it resolves to a canonical symbol; otherwise the target remains explicitly `unmaterialized_project_cursor` rather than being synthesized.

## Validated native lifecycle

The explicit native query/index layer and the portable normal scan/bundle lifecycle have both been validated on the Hyperreality corpus. Reflection, compiler AST and reflected/source joins remain independently authoritative, while a staged copy under `.uatool/native_semantics` lets ordinary database rebuilds and bundles consume the validated evidence without retaining the original sidecar paths.

```powershell
python scripts\uatool.py native-index "E:\Path\Project\.uatool" `
    --reflected "E:\Path\Project\.uatool-native-reflected" `
    --compiler "E:\Path\Project\.uatool-native-ast" `
    --joins "E:\Path\Project\.uatool-native-join"
```

This command does not recapture Unreal, rerun Clang, or rewrite the authoritative JSONL streams. Creating a missing `uat.db` is only cache initialization; it does not imply that unrelated canonical JSONL tables contain scanned project data. Each explicit import drops and recreates only the disposable `native_*` cache tables before loading, so native cache-schema migrations do not require deleting `uat.db` and do not touch standard project tables.

For portable normal-scan integration, `uatool native-stage` copies a validated reflected/compiler/join triple into `.uatool/native_semantics` with per-file SHA-256 and size records, then swaps the complete stage atomically. Normal database rebuilds and bundles automatically consume that stage. When a normal reflected-native manifest exists at the `.uatool` root, its reflected JSONL streams must be semantically identical to the staged reflected snapshot. Comparison canonicalizes each JSON row and compares the complete row multiset, so harmless row ordering or JSON whitespace differences are accepted while any added, removed, or changed reflected declaration is rejected as stale. The one current projection exception is `EClassFlags::CLASS_ReplicationDataIsSetUp` (`0x00000800`) inside `class_flags_hex`: Unreal mutates that bit as runtime replication setup state, so the raw flag remains preserved in evidence but that bit alone is masked for cross-capture semantic identity. All other class-flag bits remain strict. This prevents a later normal scan from silently pairing changed reflected C++ declarations with an older compiler graph without requiring byte-for-byte or runtime-state serialization stability.


### Live compiler/join freshness

Current `ast-capture` manifests include a project-owned compiler-input snapshot. The snapshot uses project-relative paths, byte counts and SHA-256 for the target `.uproject`, project `Source/**` native source/header/build files, source-owning project-plugin `.uplugin` descriptors and their `Plugins/**/Source/**` inputs. Generated/build trees and UnrealAssetTool itself are excluded. The same snapshot is re-read after the all-TU capture; if any tracked input changes while Clang is running, the AST capture fails instead of blessing a mixed-time graph.

`native-stage` carries that compiler snapshot into its own manifest and validation proves it exactly matches the snapshot inside the hashed staged AST manifest. Live development can then check freshness without invoking UnrealBuildTool or Clang:

```powershell
python scripts\uatool.py native-stage-freshness `
    "E:\Path\Project\.uatool" `
    --project "E:\Path\Project\Project.uproject"
```

The result is deliberately split:

- `fresh`: project-owned compiler inputs and reflected semantics both match; reuse compiler evidence and joins.
- `join_stale`: compiler inputs still match but current reflection differs; retain the compiler graph, rerun only `native-join` against current reflection, then restage.
- `compiler_stale`: tracked source/header/build/descriptors changed; recapture AST, rerun `native-join`, then restage.
- `unknown_legacy_stage`: the staged AST predates compiler-input fingerprints. It remains valid portable/query evidence, but live freshness is not guessed; one current AST capture is required to establish the baseline.
- `reflection_unknown` / `reflection_invalid`: current normal reflected evidence is missing or invalid and must be refreshed before join freshness can be decided.

A normal `scan` with a staged native corpus performs the same cheap source preflight and postflight. It never launches the all-TU AST capture automatically. Stale compiler evidence returns before expensive scan work; join-only staleness is reported separately so the retained compiler graph can be reused.

Portable `pack`, bundle verification and query/report operations remain self-contained: they validate staged bytes and current bundled reflection, but they do **not** consult the original absolute project source path. This keeps a ZIP round trip portable even when the source tree is unavailable.

## Corpus audit

After importing native streams, use the audit command to inspect semantic coverage and the exact edge cases that remain in the cache:

```powershell
python scripts\uatool.py native-index-audit "E:\Path\Project\.uatool" --limit 100
```

The audit reports:

- compiler capture ruleset plus parameter-owner rejection and nested-callable suppression counts;
- joined reflected functions with exact source identities;
- unresolved reflected-function diagnostics;
- repeated numeric compiler parameter-index slots, preserving every authoritative row;
- compiler-resolved project call targets that carry a stable project target identity but do not materialize as canonical symbols.

This is a diagnostic/read-only view. It does not rewrite native JSONL, synthesize symbols, renumber parameters, or change join decisions.

## Query surfaces

The normal query command searches the imported native cache alongside the existing UnrealAssetTool tables:

```powershell
python scripts\uatool.py query "E:\Path\Project\.uatool" "UHRThing::DoThing"
```

Native query sections include:

- reflected types and functions;
- exact type joins and function joins;
- compiler symbols;
- compiler-resolved direct calls;
- exact join diagnostics.

For semantic traversal, use:

```powershell
python scripts\uatool.py native-program-report `
    "E:\Path\Project\.uatool" `
    "/Script/Module.Type.Function"
```

The report resolves exact identity only. Supported exact starting identities are:

- reflected function path;
- unique exact reflected function name;
- compiler symbol ID;
- Clang USR;
- qualified C/C++ name;
- unique exact compiler symbol name.

By default the report shows both one-hop callers and callees. Use `--callers` or `--callees` to select a direction, `--limit` to bound rows and `--json` for machine-readable output. A compiler symbol that has no reflected UFunction counterpart is reported as `source` and explicitly labeled source-only; that status is distinct from an unresolved reflected function.

A joined reflected function reports:

```text
reflected UFunction
 -> exact native_function_join proof
 -> compiler source symbol/definition
 -> compiler parameters
 -> direct compiler call edges
 -> project-owned caller/callee source identity where available
```

An unjoined reflected function reports the exact join diagnostic. It is not silently dropped.

## Evidence boundary

The cache must not:

- manufacture reflected/source identity;
- convert substring query matches into semantic joins;
- promote unresolved calls to project-owned targets;
- emit Engine/generated/build declarations as project-owned compiler symbols;
- treat SQLite as authoritative;
- hide compatibility replay or join proof;
- assume every reflected UFunction has an authored C++ method.

The current validation contract keeps capture provenance, live freshness and disposable cache integration distinct: portable evidence stays usable without a source tree, while live development must prove source/build freshness before reusing a staged compiler graph.
