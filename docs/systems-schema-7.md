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

### First canonical systems-schema-7 City Sample capture

The first run of the canonical `systems-capture` scanner on UE 5.8.2 successfully built and emitted the new normalized streams:

```text
smartobject_definitions:          1
smartobject_slots:                2
smartobject_behaviors:            1
smartobject_behavior_properties:  1
```

The exact normalized authored values matched the focused capture:

```text
slot 0 id: 573FF06A43CF8E90E0C1A6A26469B851
slot 0 offset: -85, 0, 0
slot 0 yaw: 90
slot 0 slot-local behaviors: 0

slot 1 id: E321BAA54EA72F347C192C9A0530BCB5
slot 1 offset: 85, 0, 0
slot 1 yaw: 90
slot 1 slot-local behaviors: 0

default behavior count: 1
default behavior class: /Script/MassSmartObjects.SmartObjectMassBehaviorDefinition
UseTime: 5.000000
```

This run exposed one integration defect rather than an extraction defect: the native systems manifest remained at schema 6 and therefore omitted the four Smart Object count/file declarations. `systems-capture` correctly refused `6 != 7` before creating its ZIP, so the capture directory was archived manually for inspection.

The schema-7 finalizer has since been changed to register its shutdown callbacks from the active Smart Object scan path, after engine initialization, rather than from translation-unit static initialization. The canonical extraction values above are accepted evidence; automatic schema-7 manifest/ZIP publication still requires one rerun of the fixed branch before merge.

The captured normalized rows imply exactly **7** Smart Object `exact_semantic` graph edges:

```text
has_smart_object_slot:                       2
has_default_smart_object_behavior:           1
has_smart_object_behavior:                   0
instance_of_smart_object_behavior_class:     1
uses_smart_object_world_condition_schema:    1
uses_smart_object_selection_schema:          2
```

These counts are now the schema-7/derived-schema-23 acceptance contract.

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

The acceptance tooling writes deterministic `smartobject_graph_expectations.json` directly from the canonical schema-7 rows and verifies that derived schema 23 contains exactly the expected Smart Object domain edge set with canonical stream evidence.

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

## Final real-corpus acceptance gate

Run the fixed isolated canonical systems scanner on UE 5.8.2 City Sample:

```powershell
python scripts\uatool.py systems-capture `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe" `
    --archive "N:\EpicVault\Projects\CitySample\.uatool\CitySample.systems-schema7-capture.zip"
```

The final rerun must:

1. build the current schema-7 branch successfully;
2. publish `systems_manifest.json` with `schema_version=7` and `success=true`;
3. create the requested ZIP automatically;
4. reproduce `1 / 2 / 1 / 1` Smart Object definition/slot/behavior/property counts and the exact normalized values above;
5. pass schema-7 Python validation;
6. preserve runtime-state exclusion boundaries;
7. pass `systems-schema7-accept`, derive schema 23, and `smartobject-graph-verify` before merge.

Until that final publication gate passes, maintained capability coverage should not claim Smart Objects as accepted first-class coverage.
