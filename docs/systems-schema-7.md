# Systems schema 7 — Smart Objects

Systems schema 7 additively retains systems schema 6 and introduces first-class **authored Smart Object definition structure** derived from real UE 5.8.2 City Sample evidence.

This document describes the schema contract under acceptance. It does **not** claim runtime Smart Object state.

## Evidence basis

The evidence-only City Sample diagnostic first proved one `USmartObjectDefinition`, fifteen placed `USmartObjectComponent` instances, sixteen exact definition references and authored usage/integration, but no definition-internal slot/behavior rows in the existing corpus.

A focused native UE 5.8.2 reflection capture then loaded:

```text
/Game/AI/SmartObject/SmartObjectDefinition_WallSigns.SmartObjectDefinition_WallSigns
```

and proved:

```text
definition assets:          1
objects:                    2
nested objects:             1
recursive properties:     174
references:                 8
slot property rows:        78
behavior property rows:     5
behavior objects:            1
truncated properties:        0
property depth limit hits:   0
property row limit hits:     0
container limit hits:        0
```

The definition contains two ordered enabled slots with stable serialized GUIDs. Their authored offsets are `-85` and `+85` on X, each has yaw `90`, and both slot-local `BehaviorDefinitions` arrays are empty.

The definition itself contains one `DefaultBehaviorDefinitions[0]` object:

```text
class: /Script/MassSmartObjects.SmartObjectMassBehaviorDefinition
UseTime: 5.0
```

That distinction is preserved exactly. Schema 7 does **not** rewrite the default behavior as though it were authored independently on each slot.

## Canonical streams

Schema 7 adds:

```text
smartobject_definitions.jsonl
smartobject_slots.jsonl
smartobject_behaviors.jsonl
smartobject_behavior_properties.jsonl
```

These are part of the normal systems manifest and SQLite corpus once schema-7 acceptance is complete.

### `smartobject_definitions.jsonl`

One row per loaded, verified Smart Object definition:

```text
definition_path
package_name
class_path
slot_count
default_behavior_count
activity_tags
user_tag_filter
object_tag_filter
preconditions
world_condition_schema_class
activity_tags_merging_policy
user_tags_filtering_policy
```

Candidate nomination is based on Asset Registry **class metadata**. The loaded UObject must actually inherit `SmartObjectDefinition` before it can emit a row.

### `smartobject_slots.jsonl`

One row per authored slot:

```text
definition_path
slot_index
slot_id
name
enabled
offset_x / offset_y / offset_z
rotation_pitch / rotation_yaw / rotation_roll
user_tag_filter
activity_tags
runtime_tags
selection_preconditions
selection_schema_class
behavior_count
definition_data_count
```

`slot_index` preserves authored ordering.

`slot_id` is the serialized Smart Object slot GUID and is the stable semantic identity used by the project graph. Reordering slots therefore does not manufacture a new logical slot identity.

`runtime_tags` here means the authored serialized slot field named `RuntimeTags`; it does **not** mean live subsystem/runtime state.

### `smartobject_behaviors.jsonl`

One row per authored behavior-definition UObject referenced by a definition or slot:

```text
definition_path
scope
slot_index
behavior_index
behavior_path
behavior_class
property_count
```

`scope` is explicit:

```text
default
slot
```

For `default`, `slot_index` is `-1`.

For `slot`, `slot_index` identifies the owning authored slot.

This prevents a definition-level default from being flattened into slot-local authorship.

### `smartobject_behavior_properties.jsonl`

Subclass-specific authored/default behavior fields are preserved without hard-coding optional Smart Object integrations:

```text
definition_path
behavior_path
property_index
declaring_type
property_name
property_type
cpp_type
value
truncated
```

For the accepted City Sample evidence, this exposes `SmartObjectMassBehaviorDefinition.UseTime=5.0` without adding a `MassSmartObjects` compile-time dependency.

## Validation

Schema 7 requires:

- exact definition/package identity;
- nonblank unique definition paths;
- contiguous slot indices;
- nonblank slot GUIDs unique within each definition;
- declared slot count equality;
- explicit `default` versus `slot` behavior scope;
- contiguous behavior indices per owner/scope;
- declared default and per-slot behavior counts;
- exact behavior UObject/class identity;
- contiguous behavior-property indices;
- declared behavior property count equality;
- no truncated canonical behavior-property rows.

## SQLite

The disposable `uat.db` cache adds:

```text
smartobject_definitions
smartobject_slots
smartobject_behaviors
smartobject_behavior_properties
```

The JSON/JSONL corpus and manifests remain authoritative.

## Derived schema 23 graph topology

Schema 7 promotes exact authored topology with these relations:

```text
has_smart_object_slot
has_default_smart_object_behavior
has_smart_object_behavior
instance_of_smart_object_behavior_class
uses_smart_object_world_condition_schema
uses_smart_object_selection_schema
```

The Smart Object definition is a `first_class` root. Slot and behavior nodes are `first_class`; external/native class nodes remain conservatively typed by the existing class coverage policy.

Placed-world `SmartObjectComponent -> SmartObjectDefinition` references already come from the world/reference layer as `exact_reference`; schema 23 does not invent duplicate placement semantics.

## Explicit non-claims

Schema 7 is authored/default-state coverage only. It does not capture or infer:

```text
live slot occupancy
claims
reservations
claim priority/current user
SmartObjectSubsystem runtime registry state
runtime handles
execution history
live Mass entities using a Smart Object
transient/generated runtime tags
```

## Real-corpus acceptance gate

Before schema 7 is declared accepted, run the isolated canonical systems scanner on UE 5.8.2 City Sample:

```powershell
python scripts\uatool.py systems-capture `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe" `
    --archive "N:\EpicVault\Projects\CitySample\.uatool\CitySample.systems-schema7-capture.zip"
```

The capture must:

1. build the schema-7 branch successfully;
2. publish `systems_manifest.json` with `schema_version=7` and `success=true`;
3. include all schema-5 Mass/ZoneGraph and schema-6 GAS focused streams plus all four Smart Object streams;
4. reproduce the observed Smart Object definition/slot/default-behavior structure;
5. pass schema-7 Python validation;
6. preserve `runtime_state_captured=false` boundaries through later capability/acceptance metadata;
7. pass exact derived-schema-23 graph verification before merge.

Until that gate passes, maintained capability coverage should not claim Smart Objects as accepted first-class coverage.
