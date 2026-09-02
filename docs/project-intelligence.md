# Project intelligence commands

UnrealAssetTool's project-intelligence layer is deliberately a **retrieval and explanation layer over existing canonical and derived truth**. It does not create a second semantic model and it must not turn weak package dependencies into strong authored relationships.

Current commands:

```text
inspect <asset>          provenance-aware dossier for one asset/object
neighbors <asset>        bounded typed one-hop relationships
why-connected <A> <B>   strongest bounded supported connection/path
project-summary          corpus capability and project-graph summary
```

All four commands support the same truthfulness policy: exact authored facts and exact graph evidence are preferred, coverage/edge quality remain visible, and bounded failure is never presented as proof of absence.

---

## `inspect` — provenance-aware asset/object dossier

```powershell
python scripts\uatool.py inspect `
    "E:\Path\Project\.uatool" `
    "/Game/Path/Asset.Asset"
```

A genuinely unambiguous path fragment may also be used. Including the object-name dot is often useful because package nodes do not contain it:

```powershell
python scripts\uatool.py inspect `
    "E:\Path\Project\.uatool" `
    ".SandboxCharacter_Mover"
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

### Dossier contents

When available in the current corpus, the dossier includes:

1. the best typed project-graph identity plus all same-path node variants;
2. the matching `capabilities.json` family contract, corpus coverage and runtime boundary;
3. canonical specialist root facts already stored in `uat.db`;
4. bounded child facts such as Blueprint semantic statements, Sequencer structure, input mappings, table rows/fields, Mover modes/transitions, Gameplay Camera nodes, Mass traits, ZoneShape points and GAS children;
5. complete incoming/outgoing relation counts;
6. bounded graph edges ordered by evidence quality;
7. canonical evidence records for each displayed edge.

---

## `neighbors` — typed one-hop neighborhood

```powershell
python scripts\uatool.py neighbors `
    "E:\Path\Project\.uatool" `
    "/Game/Path/Asset.Asset"
```

The command shows incoming and outgoing typed project edges around the target, including relation, endpoint type/coverage, edge quality and attached canonical evidence.

Filter out weaker package-level plumbing when the question requires stronger evidence:

```powershell
python scripts\uatool.py neighbors `
    "E:\Path\Project\.uatool" `
    "/Game/Path/Asset.Asset" `
    --min-quality exact_reference
```

Supported minimum-quality values are:

```text
exact_semantic
exact_reference
unique_dependency_resolution
generic_package_dependency
```

The limit bounds displayed edges only. Relation counts are calculated from the complete one-hop set that meets the requested quality floor.

Machine-readable form:

```powershell
python scripts\uatool.py neighbors `
    "E:\Path\Project\.uatool" `
    "/Game/Path/Asset.Asset" `
    --json
```

---

## `why-connected` — bounded strongest-path explanation

```powershell
python scripts\uatool.py why-connected `
    "E:\Path\Project\.uatool" `
    "/Game/Path/A.A" `
    "/Game/Path/B.B"
```

The path search traverses typed edges in either direction and preserves each edge's canonical orientation, coverage, quality and evidence.

Path selection prioritizes:

1. the strongest **bottleneck edge quality** across the path;
2. the fewest hops among paths with the same bottleneck quality;
3. the strongest summed quality as a final tie-breaker.

This means a two-hop path made entirely from `exact_semantic` edges is preferred over a one-hop `generic_package_dependency` shortcut.

The search is deliberately bounded:

```text
--max-depth <n>       default 4
--per-node-limit <n>  default 96
--max-expansions <n>  default 2000
--evidence-limit <n>  default 4
--min-quality <class> default generic_package_dependency
```

If no path is found within those bounds, the command says exactly that. It does **not** claim that the two objects are disconnected in the complete project graph.

Use a stricter quality floor when low-confidence package plumbing should not participate:

```powershell
python scripts\uatool.py why-connected `
    "E:\Path\Project\.uatool" `
    "/Game/Path/A.A" `
    "/Game/Path/B.B" `
    --min-quality exact_reference
```

Machine-readable form is available with `--json`.

---

## `project-summary` — capability and graph overview

```powershell
python scripts\uatool.py project-summary "E:\Path\Project\.uatool"
```

The summary combines the corpus capability contract with indexed graph statistics. It reports:

- structural/world/animation/VFX/systems/derived schema versions when available;
- whether the corpus is focused/partial and which canonical passes are present;
- project node/edge/root counts;
- node coverage distribution;
- edge-quality distribution;
- specialist SQLite row counts for major families present in the corpus;
- largest root families/kinds and most common relations;
- project-neighborhood count/truncation summary.

`--limit` controls the bounded top-N sections. `--json` returns the complete summary object used by the text renderer.

A partial systems-only Lyra corpus therefore remains visibly partial even when its GAS coverage is first-class. `project-summary` does not reinterpret missing structural/world/animation/VFX passes as zero-content full-project facts.

---

## Evidence-quality contract

Project-intelligence presentation uses the established graph quality order:

```text
exact_semantic
exact_reference
unique_dependency_resolution
generic_package_dependency
```

This is a retrieval/presentation priority only. None of these commands changes the stored `edge_quality` or target `coverage`.

The coverage vocabulary remains:

```text
first_class
first_class_depth_pending
partial
generic_only
external_or_excluded
```

---

## Freshness and storage contract

The project-intelligence commands read the regenerable SQLite cache because interactive dossier/path/summary queries need indexed access across many canonical and derived tables. The authoritative semantic data remains the JSON/JSONL corpus and manifests.

Public commands first require the current derived output. They also reject a `uat.db` older than the current derived freshness stamp and tell the user to rebuild with:

```powershell
python scripts\uatool.py pack "E:\Path\Project\.uatool"
```

No Unreal rescan is required merely to use these commands.

---

## Truthfulness rules

All project-intelligence commands follow the same project-wide evidence policy:

- Asset Registry presence is not first-class semantic understanding;
- package dependency is not an exact object reference;
- reflected/default authored state is not runtime state;
- a focused/partial corpus must remain visibly partial;
- unsupported relationships are not inferred from names;
- capability boundaries from `capabilities.json` are shown or retained when available;
- displayed graph evidence is the evidence already attached to the authoritative project edge;
- bounded graph search failure is not proof of global disconnection.

For example, a GAS dossier or path may show authored activation policy, triggers, costs and exact relationships while also showing `runtime_state_captured=false`. It must not imply that active ability specs, cooldown timers, prediction state or live AbilitySystemComponent state were observed.
