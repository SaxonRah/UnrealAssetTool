# Gameplay Ability System evidence and schema 6

Gameplay Ability System coverage began as an evidence-first investigation. UE 5.8.2 Lyra now **real-corpus accepts systems schema 6 and derived schema 22**. The raw/native, canonical-promotion, derive, and exact project-graph verification gates are all closed.

## Diagnostic evidence commands

The public launcher exposes read-only corpus diagnostics:

```powershell
python scripts\uatool.py gas-evidence <Project>\.uatool
python scripts\uatool.py gas-focus <Project>\.uatool
```

Both commands are diagnostic only: they do not launch Unreal, modify canonical JSONL, run derive, or promote GAS relationships into the project graph. Large derived semantic/project-graph streams are opt-in with `--include-derived`; source chunks are separately opt-in with `--include-source`.

`gas-focus` groups concrete evidence into abilities, GameplayEffects/components, AbilitySystemComponent, AttributeSets, Gameplay Cues/AbilityTasks, and Lyra/GameFeature granting structures. Matching requires concrete GAS/Lyra anchors rather than generic English words.

## Focused native diagnostic capture

```powershell
python scripts\uatool.py gas-capture <Project.uproject> --editor <UnrealEditor-Cmd.exe>
```

`gas-capture` is a diagnostic AssetRegistry+reflection pass. It does not invoke the normal scanner and does not run derive. Its manifest explicitly states `diagnostic_only=true`, `semantic_promotion=false`, and `runtime_state_captured=false`.

The GASP smoke proved the commandlet builds/runs on UE 5.8.2 and, after fixing a PCG `AttributeSet` false positive, produced 0 project GAS candidates while retaining 75 loaded GAS-derived classes as independent engine/plugin vocabulary. The accepted confirmation run took 25.30 seconds total and ran neither the normal scanner nor derive.

## Lyra evidence

The focused Lyra diagnostic considered 18,033 assets and emitted 315 GAS-derived classes, 16,090 reflected properties, 948 references, 31 nested GAS objects, and zero truncated properties.

Deep inspection established the real authored boundary:

- 43 genuine GameplayAbility assets;
- 42 genuine GameplayEffect assets;
- 24 GameplayCue assets;
- 12 Lyra Ability Set assets;
- 20 ability trigger entries;
- 5 Lyra additional-cost objects;
- 33 Ability Set ability grants;
- 3 Ability Set GameplayEffect grants;
- 1 Ability Set AttributeSet grant;
- 31 GameplayEffectComponent entries;
- 10 top-level GameplayEffect modifiers;
- 20 GameplayEffect executions;
- 20 execution calculation modifiers;
- 30 GameplayEffect cue entries.

Four diagnostic-only actor/world assets whose names contain `GameplayEffect` are not GAS content. Canonical schema 6 therefore does not infer semantic type from asset names or path-bearing `GeneratedClass` strings; actual loaded inheritance is authoritative.

## Systems schema 6

Schema 6 additively retains the prior systems families and introduces 16 GAS streams:

1. `gas_abilities.jsonl`
2. `gas_ability_triggers.jsonl`
3. `gas_ability_costs.jsonl`
4. `gas_ability_sets.jsonl`
5. `gas_ability_set_abilities.jsonl`
6. `gas_ability_set_effects.jsonl`
7. `gas_ability_set_attributes.jsonl`
8. `gas_gameplay_effects.jsonl`
9. `gas_gameplay_effect_components.jsonl`
10. `gas_gameplay_effect_modifiers.jsonl`
11. `gas_gameplay_effect_executions.jsonl`
12. `gas_gameplay_effect_execution_modifiers.jsonl`
13. `gas_gameplay_effect_cues.jsonl`
14. `gas_gameplay_cues.jsonl`
15. `gas_attribute_sets.jsonl`
16. `gas_attributes.jsonl`

Native extraction remains reflection-first and does not add hard GameplayAbilities headers/module dependencies. Python schema 6 adds SQLite/query support and validates unique roots, exact Blueprint object/package/generated-class/CDO identity, child-parent resolution, contiguous ordered child indices, declared child-count agreement, execution/modifier ownership, AttributeSet attribute counts, and absence of truncated structured rows.

## Real-corpus acceptance history

### First Lyra schema-6 pass

The first real schema-6 capture built and ran successfully but exposed two policy bugs:

1. Python incorrectly required literal `Ability` / `GameplayEffect` words in class names, rejecting valid chains such as `GA_Weapon_Reload_Pistol -> GA_Weapon_ReloadMagazine_C` and `GE_AdditionalHeart -> GET_ArenaPickup_Base_C`.
2. the loaded AttributeSet loop admitted engine vocabulary (`AttributeSet`, `AbilitySystemTestAttributeSet`) as project content.

The validator now trusts native inheritance and validates structural Blueprint identity instead. AttributeSet classes are scoped by actual module/package ownership.

### Second Lyra schema-6 pass

The second preserved ZIP was internally healthy and proved the AttributeSet scope exactly:

- 37 GameplayAbility roots;
- 20 triggers;
- 5 additional costs;
- 12 Ability Sets;
- 33 / 3 / 1 ability/effect/AttributeSet grants;
- 42 GameplayEffects;
- 31 GE components;
- 10 modifiers;
- 20 executions;
- 20 execution modifiers;
- 30 effect cue entries;
- 24 Gameplay Cues;
- 4 project-owned AttributeSets;
- 10 project-owned attributes.

The four accepted project-owned AttributeSets are:

- `/Script/LyraGame.LyraAttributeSet`
- `/Script/LyraGame.LyraCombatSet`
- `/Script/LyraGame.LyraHealthSet`
- `/Script/TopDownArenaRuntime.TopDownArenaAttributeSet`

The remaining six abilities were identified as ShooterCore and TopDownArena `Phase_Playing`, `Phase_PostGame`, and `Phase_Warmup`. AssetRegistry registers them as `/Script/GameplayAbilities.GameplayAbilityBlueprint`, not `/Script/Engine.Blueprint`. They inherit `LyraGamePhaseAbility` and are genuine GameplayAbilities.

Schema 6 therefore admits both exact Blueprint asset-class identities into the same loaded generated-class inheritance check.

### Final Lyra schema-6 acceptance pass

The final focused capture on the specialized-Blueprint fix is accepted as the real-corpus schema-6 gate.

Native/build/runtime result:

- `LyraEditor` DebugGame module build succeeded;
- isolated systems editor pass completed in 34.33 s;
- total focused workflow completed in 49.16 s;
- normal project scan was not run;
- derive was not run;
- editor returned 3 only after writing a valid manifest/archive; the validated schema output is authoritative.

Final GAS counts:

- `gas_abilities`: **43**
- `gas_ability_triggers`: **20**
- `gas_ability_costs`: **5**
- `gas_ability_sets`: **12**
- `gas_ability_set_abilities`: **33**
- `gas_ability_set_effects`: **3**
- `gas_ability_set_attributes`: **1**
- `gas_gameplay_effects`: **42**
- `gas_gameplay_effect_components`: **31**
- `gas_gameplay_effect_modifiers`: **10**
- `gas_gameplay_effect_executions`: **20**
- `gas_gameplay_effect_execution_modifiers`: **20**
- `gas_gameplay_effect_cues`: **30**
- `gas_gameplay_cues`: **24**
- `gas_attribute_sets`: **4**
- `gas_attributes`: **10**

Independent archive inspection confirms:

- ZIP CRC OK;
- 29 members, including 28 JSONL streams;
- systems manifest schema 6 / `success=true`;
- every manifest count equals the physical JSONL row count;
- every JSONL parses cleanly;
- all ordered GAS child indices are contiguous;
- all child-parent joins resolve;
- declared child counts agree with physical child streams;
- zero truncated structured GAS rows;
- all six phase abilities are present as `LyraGamePhaseAbility` children with zero trigger/additional-cost/cost/cooldown children.

**Systems schema 6 is therefore real-corpus accepted on UE 5.8.2 Lyra.**

### Canonical schema-6 promotion

`systems-schema6-accept` promoted the accepted focused capture into `LyraStarterGame/.uatool` without launching Unreal and without running derive. It wrote:

- `systems_schema6_acceptance.json`
- `gas_graph_expectations.json`

The graph expectation contract recomputed **560 exact semantic GAS edges** from the promoted raw rows. Non-zero relation counts are:

- `captures_gameplay_attribute`: 20
- `defines_gameplay_ability_class`: 43
- `defines_gameplay_cue_class`: 24
- `defines_gameplay_effect_class`: 42
- `grants_attribute_set_class`: 1
- `grants_gameplay_ability_class`: 33
- `grants_gameplay_effect_class`: 3
- `handles_gameplay_cue_tag`: 23
- `has_additional_gameplay_ability_cost`: 5
- `has_gameplay_ability_trigger`: 20
- `has_gameplay_attribute`: 10
- `has_gameplay_effect_component`: 31
- `has_gameplay_effect_cue`: 30
- `has_gameplay_effect_execution`: 20
- `has_gameplay_effect_execution_modifier`: 20
- `has_gameplay_effect_modifier`: 10
- `inherits_attribute_set_class`: 4
- `inherits_gameplay_ability_class`: 43
- `inherits_gameplay_cue_class`: 24
- `inherits_gameplay_effect_class`: 42
- `instance_of_gameplay_ability_cost_class`: 5
- `instance_of_gameplay_ability_set_class`: 12
- `instance_of_gameplay_effect_component_class`: 31
- `modifies_gameplay_attribute`: 10
- `triggered_by_gameplay_tag`: 20
- `uses_cooldown_gameplay_effect_class`: 2
- `uses_cost_gameplay_effect_class`: 1
- `uses_cue_magnitude_attribute`: 11
- `uses_gameplay_effect_execution_calculation`: 20

`runtime_state_captured` remains false. The promotion result exactly matches the precomputed 560-edge expectation, so the canonical raw promotion gate is accepted.

### Focused-corpus derive policy

The first schema-22 derive attempt exposed a pipeline assumption rather than a GAS data problem: the canonical derive preflight required `vfx_manifest.json` even though this Lyra corpus was deliberately built from the accepted systems-only capture and had never run the VFX scanner.

Focused derived acceptance now has an explicit conservative policy:

- a completely absent VFX pass is allowed only when `systems_schema6_acceptance.json` and a successful schema-6 `systems_manifest.json` prove this is an accepted systems-only corpus;
- any VFX raw stream present without a valid VFX manifest still uses the original strict failure path;
- normal/full corpora keep the original VFX prerequisite unchanged;
- when an accepted focused corpus has no top `manifest.json`, derive creates a minimal commit marker with `partial_corpus=true`, `canonical_passes=["systems"]`, and `schema_version=0` rather than claiming structural/world/VFX scanner coverage that did not occur.

The first implementation correctly modeled that policy but installed it too early on `uatool_runtime`, before canonical `uatool.py` had defined the final VFX gates. The public command therefore still failed. The final implementation uses a deferred public-root hook: it waits until command dispatch, finds the fully constructed canonical `uatool.py` module, patches its actual VFX prerequisites/derive wrapper, and synchronizes `uatool_core.derive_output`. Regression coverage now exercises that real composition ordering rather than only a helper module.

This policy remains strict for partial VFX data and does not run or synthesize any missing scanner pass.

## Derived schema 22 GAS graph

The GAS graph layer is implemented from normalized exact fields only. It promotes relationships such as ability/class inheritance, cost/cooldown classes, ordered trigger/tag links, additional-cost objects/classes, Ability Set grants, GameplayEffect components/modifiers/executions/cues, exact attributes, GameplayCue scalar tags, and AttributeSet declarations.

Broad exported tag-container strings are not parsed into guessed graph relations. Runtime specs, active effects, live granted ability specs, prediction state, replicated ASC runtime state, and live attributes remain outside the claim.

### Final Lyra derived-schema-22 acceptance

The accepted systems-only Lyra corpus derived successfully through the canonical public launcher after the deferred focused-corpus policy fix. The derive explicitly reported:

- `created partial canonical manifest from accepted systems schema 6`;
- `VFX specialist pass absent: continuing accepted systems-only derive`;
- zero Blueprint/world/animation/VFX derived rows, as expected for a systems-only corpus;
- `project_nodes`: **8,366**;
- `project_edges`: **12,522**;
- `project_neighborhoods`: **1,089**.

`gas-graph-verify` then verified the schema-22 GAS topology exactly:

- `exact_semantic_edges`: **560**;
- `gameplay_ability_roots`: **43**;
- `gameplay_ability_set_roots`: **12**;
- `gameplay_attribute_set_roots`: **4**;
- `gameplay_cue_roots`: **24**;
- `gameplay_effect_roots`: **42**;
- `runtime_state_captured`: **False**.

The verifier requires exact source/relation/target equality, `exact_semantic` edge quality, canonical stream evidence, and specialist GAS roots. The expected and actual GAS edge sets are identical.

**Derived schema 22 GAS coverage is therefore real-corpus accepted on UE 5.8.2 Lyra. No additional Unreal GAS capture is required.**

## Semantic boundary

Systems schema 6 and derived schema 22 are authored/default-state coverage only. They do not claim active GameplayEffect specs, current granted ability specs, prediction keys/state, replicated AbilitySystemComponent runtime state, live attribute values, or runtime activation/cooldown state. The focused corpus also did not establish exact authored GameFeatureAction_AddAbilities or tag-relationship-mapping instances strongly enough for first-class promotion.
