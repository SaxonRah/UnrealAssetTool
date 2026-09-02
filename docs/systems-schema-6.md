# Systems schema 6 — Gameplay Ability System

Systems schema 6 is the current UnrealAssetTool gameplay-systems canonical contract. It retains all systems schema 1–5 streams and adds an evidence-driven Gameplay Ability System slice accepted on **UE 5.8.2 Lyra Starter Game**.

The design boundary is the same as the rest of UnrealAssetTool: preserve exact authored/default facts, derive only reproducible relationships from those facts, and do not claim live runtime state.

## Baseline

```text
structural=12
world=12
animation=1
vfx=1
systems=6
derived=22
```

Systems schema 5 remains the Mass + authored ZoneGraph foundation. Schema 6 is additive.

## Canonical GAS streams

```text
gas_abilities.jsonl
gas_ability_triggers.jsonl
gas_ability_costs.jsonl
gas_ability_sets.jsonl
gas_ability_set_abilities.jsonl
gas_ability_set_effects.jsonl
gas_ability_set_attributes.jsonl
gas_gameplay_effects.jsonl
gas_gameplay_effect_components.jsonl
gas_gameplay_effect_modifiers.jsonl
gas_gameplay_effect_executions.jsonl
gas_gameplay_effect_execution_modifiers.jsonl
gas_gameplay_effect_cues.jsonl
gas_gameplay_cues.jsonl
gas_attribute_sets.jsonl
gas_attributes.jsonl
```

These streams are normalized and validated by `scripts/uatool_systems_gas.py` and are included in the systems manifest/count contract.

## Authored facts covered

### Gameplay Abilities

The normalized root records preserve exact Blueprint/object/class/CDO identity plus authored defaults including activation policy/group where available, replication/instancing/net policies, tag requirement containers, cost GameplayEffect class, cooldown GameplayEffect class, trigger count and additional-cost count.

Triggers and additional ability costs are normalized into indexed child rows rather than left only in broad reflected text.

### Ability Sets

Ability Set assets preserve exact authored grants for:

- Gameplay Ability classes and input tags;
- Gameplay Effect classes;
- Attribute Set classes.

These rows intentionally describe authored grants. They are not a snapshot of a live AbilitySystemComponent.

### Gameplay Effects

Gameplay Effects preserve exact Blueprint/class/CDO identity plus authored duration/period/stacking/tag defaults and normalized children for:

- Gameplay Effect components;
- top-level attribute modifiers;
- executions and their calculation classes;
- execution modifiers / captured attributes;
- Gameplay Cue entries and cue magnitude attributes.

### Gameplay Cues

Gameplay Cue roots preserve Blueprint/class/CDO identity and the authored handled cue tag/name/override state needed for exact graph promotion.

### Attribute Sets and attributes

Project-owned Attribute Set classes preserve native/Blueprint identity, superclass/module/CDO metadata and normalized authored attributes with name, C++ type, base value and current default value.

These are class/default-object facts. They are not live replicated attribute values.

## Derived schema 22 graph promotion

Schema 22 promotes only relationships backed by exact normalized GAS fields. The current relation vocabulary is:

```text
defines_gameplay_ability_class
inherits_gameplay_ability_class
uses_cost_gameplay_effect_class
uses_cooldown_gameplay_effect_class
has_gameplay_ability_trigger
triggered_by_gameplay_tag
has_additional_gameplay_ability_cost
instance_of_gameplay_ability_cost_class
instance_of_gameplay_ability_set_class
grants_gameplay_ability_class
grants_gameplay_effect_class
grants_attribute_set_class
defines_gameplay_effect_class
inherits_gameplay_effect_class
has_gameplay_effect_component
instance_of_gameplay_effect_component_class
has_gameplay_effect_modifier
modifies_gameplay_attribute
has_gameplay_effect_execution
uses_gameplay_effect_execution_calculation
has_gameplay_effect_execution_modifier
captures_gameplay_attribute
has_gameplay_effect_cue
uses_cue_magnitude_attribute
defines_gameplay_cue_class
inherits_gameplay_cue_class
handles_gameplay_cue_tag
inherits_attribute_set_class
has_gameplay_attribute
```

Every accepted GAS domain edge is `exact_semantic` and keeps the canonical source stream as evidence. Broad package dependency or exported tag-container text is not promoted into a GAS semantic edge merely because it looks related.

## Lyra UE 5.8.2 accepted raw contract

The accepted focused Lyra corpus contains:

```text
gas_abilities                                  43
gas_ability_triggers                           20
gas_ability_costs                               5
gas_ability_sets                               12
gas_ability_set_abilities                      33
gas_ability_set_effects                         3
gas_ability_set_attributes                      1
gas_gameplay_effects                           42
gas_gameplay_effect_components                 31
gas_gameplay_effect_modifiers                  10
gas_gameplay_effect_executions                 20
gas_gameplay_effect_execution_modifiers        20
gas_gameplay_effect_cues                       30
gas_gameplay_cues                              24
gas_attribute_sets                              4
gas_attributes                                 10
```

The accepted derive produced:

```text
project_nodes            8366
project_edges           12522
project_neighborhoods    1089
```

`gas-graph-verify` then confirmed **560 exact semantic GAS edges** with the expected root coverage:

```text
Gameplay Ability roots       43
Ability Set roots            12
Attribute Set roots           4
Gameplay Cue roots           24
Gameplay Effect roots        42
```

## Acceptance artifacts

Focused schema-6 acceptance may emit:

```text
systems_schema6_acceptance.json
gas_graph_expectations.json
gas_graph_verification.json
```

`gas_graph_expectations.json` records the exact edge contract implied by accepted canonical rows. `gas_graph_verification.json` records the post-derive exact verification result.

The focused corpus is deliberately marked as a partial canonical corpus. Its top manifest identifies `canonical_passes=["systems"]`; it must not imply that structural, world, animation or VFX passes were executed for that focused archive.

## Focused lifecycle

The evidence workflow is deliberately separated from a normal expensive project scan:

1. capture systems/GAS evidence from a representative UE project;
2. preserve the raw focused archive before promotion/validation;
3. promote it to the systems schema-6 canonical contract;
4. derive the typed graph from the accepted partial corpus;
5. verify the exact expected GAS edge set.

Use the one canonical launcher; do not introduce alternate public wrappers.

The final exact verifier takes the project as its positional argument and the accepted corpus explicitly:

```powershell
python scripts\uatool.py gas-graph-verify `
    "E:\Path\Lyra\Lyra.uproject" `
    --corpus "E:\Path\Lyra\.uatool"
```

See [gas-evidence.md](gas-evidence.md) for the investigation/capture workflow.

## Explicit non-claims

Systems schema 6 does **not** claim to capture or reconstruct:

- active Gameplay Effect specs;
- live granted ability specs;
- prediction keys or prediction windows;
- replicated runtime AbilitySystemComponent state;
- active tags/stacks/cooldown timers on a live actor;
- live AttributeSet values after gameplay mutation;
- runtime cue execution/history;
- runtime targeting/task state;
- equivalence between a package dependency and a semantic GAS relationship.

`runtime_state_captured` is therefore false in both acceptance/capability metadata and the conceptual contract.

## Compatibility

Schema 6 is additive over schema 5. Compatible canonical GAS rows can be re-derived into schema 22 without rerunning Unreal when only Python graph/report behavior changes.

The universal compatibility rule remains:

> Do not infer a stronger fact from a weaker layer.

An Asset Registry row can prove an asset exists. A normalized GAS row can prove authored GAS state. A schema-22 exact-semantic edge can prove a specific relationship. Those are distinct evidence levels and must remain distinct in queries, reports and AI-facing context.
