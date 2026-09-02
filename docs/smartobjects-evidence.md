# Smart Objects evidence workflow

Smart Objects are the next evidence-driven subsystem after the 0.8 project-intelligence work. Coverage is being built in explicit gates: existing-corpus diagnosis, focused native reflection, normalized authored schema, graph acceptance, then first-class promotion.

Until the final acceptance gate passes, Smart Objects remain `generic_only` in the maintained capability contract.

## Representative corpora

City Sample UE 5.8.2 is the primary definition/placement corpus. It contains:

```text
/Game/AI/SmartObject/SmartObjectDefinition_WallSigns.SmartObjectDefinition_WallSigns
    class=/Script/SmartObjectsModule.SmartObjectDefinition

/Game/AI/SmartObject/SmartObject_WallSigns

placed Smart Object actors/components in /Game/AI/Map/MassCrowd

/Script/MassSmartObjects integration
```

GASP separately contains Smart Object-oriented StateTrees/tasks and remains useful as a second usage-logic corpus.

## Gate 1 — existing-corpus diagnostic

The read-only diagnostic is:

```powershell
python scripts\uatool.py smartobject-evidence `
    "N:\EpicVault\Projects\CitySample\.uatool" `
    --report "N:\EpicVault\Projects\CitySample\CitySample.smartobjects-evidence.txt"
```

It does not launch Unreal, change the corpus, or promote coverage.

### Accepted City Sample diagnostic result

The UE 5.8.2 City Sample report produced:

```text
unique_definition_assets                 1
unique_placed_smartobject_components    15
unique_smartobject_named_actors        311
unique_exact_definition_references      16
usage_rows                              10
definition_slot_internal_rows            0
definition_behavior_internal_rows        0
```

The exact definition is:

```text
/Game/AI/SmartObject/SmartObjectDefinition_WallSigns.SmartObjectDefinition_WallSigns
```

The 15 placed `SmartObjectComponent` instances all reference that definition, and `SmartObjectPersistentCollection_0` supplies the sixteenth exact definition reference.

The usage evidence includes authored StateTree `FindSmartObject`, `ClaimSmartObject` and `UseSmartObject` task data. MassSmartObjects integration is also visible.

The diagnostic therefore passed the corpus-entry gate but failed the definition-depth gate: current canonical streams know that the definition exists and where it is used, but they do not expose the definition's authored slot/behavior internals.

### Important false-positive lesson

The broad `slot` text focus matched hundreds of unrelated `Slots[...]` paths from PCG and character data. Those rows are not Smart Object slots.

For that reason, first-class Smart Object slot semantics must never be inferred from a property name containing `Slots`. The next capture is anchored on loaded objects whose reflected class actually inherits `SmartObjectDefinition`.

## Gate 2 — focused native definition capture

The focused capture is intentionally separate from the normal scanner and from systems schema promotion:

```powershell
cd "E:\TheDigitalGame\ue\GameAnimationSample\Plugins\UnrealAssetTool"

git switch issue-14-smartobjects-focused-capture
git pull --ff-only origin issue-14-smartobjects-focused-capture

python scripts\uatool.py smartobject-capture `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

Default outputs are:

```text
N:\EpicVault\Projects\CitySample\.uatool\smartobject-capture\
N:\EpicVault\Projects\CitySample\.uatool\CitySample.smartobject-capture.zip
N:\EpicVault\Projects\CitySample\.uatool\CitySample.smartobject-capture.txt
```

The ZIP is written before Python-side semantic validation so raw UE evidence survives even if a new invariant fails.

### Focused capture contract

The diagnostic manifest is `smartobject_capture_manifest.json`, schema 1. It must state:

```text
diagnostic_only=true
semantic_promotion=false
runtime_state_captured=false
```

The raw streams are:

```text
smartobject_assets.jsonl
smartobject_objects.jsonl
smartobject_properties.jsonl
smartobject_references.jsonl
```

The commandlet has no hard `SmartObjectsModule` build dependency. Candidate selection uses Asset Registry class metadata; semantic confirmation uses the loaded class hierarchy.

Unlike the broad scanner, this pass recursively walks reflected arrays/sets/maps/structs on the actual definition. A reflected definition array therefore produces addressable paths such as:

```text
Slots
Slots[0]
Slots[0].<field>
Slots[0].BehaviorDefinitions
Slots[0].BehaviorDefinitions[0]
```

The exact field names above `Slots` are evidence targets, not schema promises. The implementation does not depend on a `SmartObjectDefinition.h` include or compile-time knowledge of the slot struct.

Owned non-transient nested UObjects are captured separately. This is intended to expose instanced behavior-definition objects without assuming their concrete class names in advance.

### Capture bounds

The diagnostic is bounded to prevent corrupted/pathological assets from exploding output:

```text
max reflected property depth       16
max elements per container       4096
max property rows per object    65536
max nested objects per definition 4096
max exported property text      65536 characters
```

Limit-hit counters are written to the manifest and report. A real acceptance cannot silently ignore a limit hit.

## Authored boundary

The focused pass captures loaded editor/default authored state only. It explicitly does not model:

```text
live slot occupancy
runtime claims/reservations
runtime SmartObjectSubsystem state
current users
runtime execution/history
transient runtime handles
```

The existing world scanner remains authoritative for placed actor/component ownership and exact component -> definition references. The focused definition capture does not duplicate world placement as a new truth source.

## Gate 3 — normalization after evidence review

Do not design systems schema 7 until the focused City Sample archive has been inspected.

The next normalization should be driven by the actual reflected paths/classes and should target only stable authored concepts that the real capture proves. Likely candidates include, subject to evidence:

```text
SmartObjectDefinition identity
ordered slot identity/order
slot transform/offset/rotation fields actually serialized in UE 5.8.2
slot behavior-definition references
slot/user/activity tags or queries actually serialized
shared definition-level tag/query state
behavior-definition object identity and authored asset references
exact joins to existing SmartObjectComponent definition references
exact joins to StateTree behavior assets where present
```

A field is not first-class merely because an Unreal header/API contains it. It must appear as stable authored evidence in the representative capture.

## Final acceptance rule

Smart Objects become first-class only after all of the following are true:

1. the real UE 5.8.2 focused capture exposes the intended definition internals without unhandled traversal limits;
2. normalized rows have deterministic identity/order/count validation;
3. the systems schema is additive and preserves prior systems families;
4. SQLite/query support exposes the normalized facts;
5. typed project-graph relations preserve exact evidence/provenance;
6. runtime/generated state remains explicitly excluded;
7. City Sample passes a durable acceptance manifest and exact graph verification where feasible;
8. a second corpus such as GASP confirms usage-side interoperability without weakening the definition contract.
