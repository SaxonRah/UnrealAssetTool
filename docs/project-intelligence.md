# Project intelligence commands

UnrealAssetTool's project-intelligence layer is deliberately a **retrieval and explanation layer over existing canonical and derived truth**. It does not create a second semantic model and it must not turn weak package dependencies into strong authored relationships.

The first command in this layer is `inspect`.

## `inspect` — provenance-aware asset/object dossier

```powershell
python scripts\uatool.py inspect `
    "E:\Path\Project\.uatool" `
    "/Game/Path/Asset.Asset"
```

An unambiguous path fragment may also be used:

```powershell
python scripts\uatool.py inspect `
    "E:\Path\Project\.uatool" `
    "SandboxCharacter_Mover"
```

If a fragment matches multiple distinct graph paths, `inspect` refuses to guess and prints bounded candidates. Exact paths always win.

Machine-readable output is available for tools and agents:

```powershell
python scripts\uatool.py inspect `
    "E:\Path\Project\.uatool" `
    "/Game/Path/Asset.Asset" `
    --json
```

Useful bounds:

```text
--edge-limit <n>       maximum graph edges printed; default 80
--evidence-limit <n>   maximum evidence records printed per edge; default 6
--child-limit <n>      maximum child rows shown per specialist table; default 8
--candidate-limit <n>  maximum ambiguous path candidates shown; default 12
```

## Dossier contents

When available in the current corpus, the dossier includes:

1. the best typed project-graph identity plus all same-path node variants;
2. the matching `capabilities.json` family contract, corpus coverage and runtime boundary;
3. canonical specialist root facts already stored in `uat.db`;
4. bounded child facts such as Blueprint semantic statements, Sequencer structure, input mappings, table rows/fields, Mover modes/transitions, Gameplay Camera nodes, Mass traits, ZoneShape points and GAS children;
5. complete incoming/outgoing relation counts;
6. bounded graph edges ordered by evidence quality;
7. canonical evidence records for each displayed edge.

The graph quality order is:

```text
exact_semantic
exact_reference
unique_dependency_resolution
generic_package_dependency
```

This is presentation priority only. `inspect` does not alter the stored edge quality.

## Freshness and storage contract

`inspect` reads the regenerable SQLite cache because an interactive dossier needs indexed lookups across many canonical/derived tables. The authoritative semantic data remains the JSON/JSONL corpus and manifests.

The public command first requires the current derived output. It also rejects a `uat.db` older than the current derived freshness stamp and tells the user to rebuild with:

```powershell
python scripts\uatool.py pack "E:\Path\Project\.uatool"
```

No Unreal rescan is required merely to use `inspect`.

## Truthfulness rules

`inspect` follows the same project-wide evidence policy:

- Asset Registry presence is not first-class semantic understanding;
- package dependency is not an exact object reference;
- reflected/default authored state is not runtime state;
- a focused/partial corpus must remain visibly partial;
- unsupported relationships are not inferred from names;
- capability boundaries from `capabilities.json` are shown when available;
- displayed graph evidence is the evidence already attached to the authoritative project edge.

For example, a GAS dossier may show authored activation policy, triggers, costs and exact relationships while also showing `runtime_state_captured=false`. It must not imply that active ability specs, cooldown timers, prediction state or live AbilitySystemComponent state were observed.

## Planned next commands

The roadmap intentionally builds the remaining project-intelligence surface as thin views over the same typed graph:

```text
neighbors <asset>       bounded nearby typed relationships
why-connected <A> <B>  explain the strongest supported connection/path
project-summary         subsystem counts, coverage and major roots
```

Those commands are **not implemented by this document**. They should reuse the same coverage, provenance, edge-quality and capability contracts rather than introducing parallel truth models.
