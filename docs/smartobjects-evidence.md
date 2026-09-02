# Smart Objects evidence workflow

Smart Objects are the next evidence-driven subsystem after the 0.8 project-intelligence work. The first step is intentionally **diagnostic only**: prove what existing UE 5.8.2 corpora already expose and identify the exact authored internals that require a focused Unreal reflection capture before designing a first-class systems schema.

No Smart Object schema/version is claimed by this workflow.

## Known representative corpora

The existing City Sample UE 5.8.2 corpus is suitable for the first evidence gate. Prior evidence already proves project content including:

```text
/Game/AI/SmartObject/SmartObjectDefinition_WallSigns.SmartObjectDefinition_WallSigns
    class=/Script/SmartObjectsModule.SmartObjectDefinition

/Game/AI/SmartObject/SmartObject_WallSigns

placed Smart Object actors in /Game/AI/Map/MassCrowd

/Script/MassSmartObjects integration
```

GASP separately contains Smart Object-oriented StateTrees/tasks and is useful as a second usage-logic corpus, but City Sample is the better definition/placement corpus.

## Existing-corpus diagnostic

After updating the canonical checkout to a commit containing this command, run:

```powershell
python scripts\uatool.py smartobject-evidence `
    "N:\EpicVault\Projects\CitySample\.uatool" `
    --report "N:\EpicVault\Projects\CitySample\CitySample.smartobjects-evidence.txt"
```

This command:

- does **not** launch Unreal;
- does **not** change canonical or derived files;
- does **not** promote Smart Object coverage;
- streams the existing corpus once;
- writes a UTF-8 report suitable for review/upload.

Use `--no-source` if `source_chunks.jsonl` is not needed. Restrict the report with repeated `--focus` options:

```text
definition
slot
behavior
placement
usage
```

Example:

```powershell
python scripts\uatool.py smartobject-evidence `
    "N:\EpicVault\Projects\CitySample\.uatool" `
    --focus definition `
    --focus placement `
    --row-limit 50 `
    --report "N:\EpicVault\Projects\CitySample\CitySample.smartobjects-definition-placement.txt"
```

## What the diagnostic proves

The report separates broad matching rows from narrow corpus proof counters:

```text
unique_definition_assets
unique_placed_smartobject_components
unique_smartobject_named_actors
unique_exact_definition_references
definition_slot_internal_rows
definition_behavior_internal_rows
usage_rows
```

It also groups high-signal evidence into:

- `definition` — SmartObjectDefinition identity and authored state;
- `slot` — slot/slot-definition evidence;
- `behavior` — behavior definitions plus StateTree/Mass integration;
- `placement` — components, actors and definition references;
- `usage` — authored Blueprint/StateTree logic that finds/claims/uses/releases Smart Objects.

## Expected first City Sample outcome

The previous City Sample Mass/ZoneGraph evidence proves that at least one SmartObjectDefinition exists and that Smart Object actors are placed. It did **not** normalize the definition's slot or behavior internals.

Therefore the likely outcome is:

```text
definition asset proof: yes
placement proof: yes
usage/integration proof: yes
slot internals: insufficient in current canonical streams
behavior-definition internals: insufficient in current canonical streams
```

The command must report those missing internals rather than pretending Asset Registry recognition is first-class Smart Object understanding.

## Next gate: focused Unreal reflection capture

Only after reviewing the diagnostic output should a focused native capture be designed. The first capture should target observed UE 5.8.2 serialized/reflected shapes around the actual City Sample definition and placement objects.

Candidate authored facts to investigate—not yet schema promises—include:

```text
SmartObjectDefinition identity
ordered Slots[]
per-slot transform/offset/rotation
per-slot behavior definitions
per-slot/user/activity tag requirements
shared definition-level tag/query state
SmartObjectComponent -> definition reference
placed actor/component ownership
StateTree behavior-definition references where present
MassSmartObjects bridge objects where exact authored links exist
```

The focused capture should remain separate from runtime state. It must not attempt to model:

```text
live slot occupancy
runtime claims/reservations
runtime SmartObjectSubsystem state
current users
runtime execution/history
transient handles
```

## Acceptance rule

Smart Objects become first-class only after all of the following are true:

1. a representative real UE 5.8.2 definition/placement corpus is captured;
2. exact reflected/serialized authored identities and ordering are understood;
3. normalized rows have deterministic identity/order/count validation;
4. SQLite/query and project-graph relations are useful and evidence-backed;
5. unsupported runtime/generated state remains explicitly excluded;
6. the real corpus passes an acceptance/verification contract.

Until then, Smart Objects remain `generic_only` in the maintained capability contract.
