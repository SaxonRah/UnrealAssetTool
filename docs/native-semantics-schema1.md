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

Project-owned semantic identity is compiler-derived. Clang USR is retained when available. Symbols are canonicalized while call rows remain translation-unit-specific. Engine/system headers may participate in compilation but are not emitted as project-owned symbols.

Any indexing-only compatibility replay is retained on each affected symbol/call as `compatibility_overrides`.

### Reflected/source join schema 1

Produced by `uatool native-join`.

```text
native_join_manifest.json
native_type_joins.jsonl
native_function_joins.jsonl
native_join_diagnostics.jsonl
```

Join schema 1 uses exact proof only. Ambiguity and legitimate missing authored counterparts remain diagnostics; they are never promoted by fuzzy name similarity.

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

The importer validates source manifests and JSONL counts before writing, checks project-owned symbol/call cross-references, rejects excluded build/source leakage, and rechecks SQLite row counts after loading.

## Validation-phase workflow

Automatic scan/bundle integration is intentionally deferred until the native query layer is validated on a real corpus.

```powershell
python scripts\uatool.py native-index "E:\Path\Project\.uatool" `
    --reflected "E:\Path\Project\.uatool-native-reflected" `
    --compiler "E:\Path\Project\.uatool-native-ast" `
    --joins "E:\Path\Project\.uatool-native-join"
```

This command does not recapture Unreal, rerun Clang, or rewrite the authoritative JSONL streams. Creating a missing `uat.db` is only cache initialization; it does not imply that unrelated canonical JSONL tables contain scanned project data.

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

By default the report shows both one-hop callers and callees. Use `--callers` or `--callees` to select a direction, `--limit` to bound rows and `--json` for machine-readable output.

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

The current validation contract intentionally keeps capture and cache integration separate until real-project query evidence is accepted.
