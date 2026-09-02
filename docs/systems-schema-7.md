# Systems schema 7 — Smart Objects

Systems schema 7 additively retains systems schema 6 and introduces first-class **authored Smart Object definition structure** derived from real UE 5.8.2 City Sample evidence.

This document describes the accepted schema contract. It does **not** claim runtime Smart Object state.

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

These are part of the normal systems manifest and SQLite corpus.

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

For the accepted City Sample rows the exact specialist graph contract is:

```text
has_smart_object_slot:                       2
has_default_smart_object_behavior:           1
has_smart_object_behavior:                   0
instance_of_smart_object_behavior_class:     1
uses_smart_object_world_condition_schema:    1
uses_smart_object_selection_schema:          2
```

Total: **7 `exact_semantic` edges**.

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

## Real-corpus acceptance status

Three canonical City Sample systems runs reproduced the normalized Smart Object payload exactly. The first two isolated the manifest-publication defect; the third, using the synchronous manifest-write proxy, completed the raw schema-7 acceptance gate successfully:

```text
systems_manifest.schema_version:       7
systems_manifest.success:              true
smartobject_definitions:                 1
smartobject_slots:                       2
smartobject_behaviors:                   1
smartobject_behavior_properties:         1
```

The final capture reproduced the same two serialized slot GUIDs:

```text
573FF06A43CF8E90E0C1A6A26469B851
E321BAA54EA72F347C192C9A0530BCB5
```

and the same `-85/+85` X offsets, yaw `90`, zero slot-local behaviors, one definition-default `SmartObjectMassBehaviorDefinition`, and `UseTime=5.000000`.

Schema-7 publication is synchronous. While the shared systems driver include is compiled, its `FFileHelper::SaveStringToFile` manifest write is routed through a narrow proxy. The proxy performs the real base-manifest write and immediately upgrades that exact completed file to schema 7 before `SaveSystemsManifest()` returns. No multicast delegate ordering or shutdown callback participates in correctness. The raw archive guard remains as evidence preservation if a later Python validation gate fails.

The accepted schema-7 capture was promoted into the canonical City Sample corpus, the full corpus was regenerated at derived schema 23, and `smartobject-graph-verify` passed exactly:

```text
expected_exact_semantic_edges: 7
verified_exact_semantic_edges: 7
smart_object_definition_roots: 1
runtime_state_captured: False
```

The verified relation counts are exactly the seven-edge contract above; there are no invented slot-local behavior edges. Smart Objects therefore have maintained `first_class` capability coverage beginning with systems schema 7 / derived schema 23.
