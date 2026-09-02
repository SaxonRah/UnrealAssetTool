# Gameplay Ability System evidence and schema 6

Gameplay Ability System coverage began as an evidence-first investigation. UE 5.8.2 Lyra evidence now defines the first-class **systems schema 6** raw boundary. One final focused Lyra recount remains to prove the specialized `GameplayAbilityBlueprint` asset-class fix in native output. Derived GAS project-graph schema 22 is implemented and synthetic-contract tested, but is not yet claimed as real-corpus accepted.

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

### First Lyra schema-6 pass

The first real schema-6 capture built and ran successfully but exposed two policy bugs:

1. Python incorrectly required literal `Ability` / `GameplayEffect` words in class names, rejecting valid chains such as `GA_Weapon_Reload_Pistol -> GA_Weapon_ReloadMagazine_C` and `GE_AdditionalHeart -> GET_ArenaPickup_Base_C`.
2. the loaded AttributeSet loop admitted engine vocabulary (`AttributeSet`, `AbilitySystemTestAttributeSet`) as project content.

The validator now trusts native inheritance and validates structural Blueprint identity instead. AttributeSet classes are scoped by actual module/package ownership.

### Second Lyra schema-6 pass

The preserved second ZIP is internally healthy:

- ZIP CRC OK;
- schema 6 / success true;
- all 28 focused JSONL streams parse cleanly;
- all manifest counts equal physical row counts;
- all ordered GAS child indices are contiguous;
- all child-parent joins resolve;
- every declared child count agrees;
- zero truncated structured GAS rows.

Observed second-pass counts:

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

The AttributeSet scope is accepted exactly:

- `/Script/LyraGame.LyraAttributeSet`
- `/Script/LyraGame.LyraCombatSet`
- `/Script/LyraGame.LyraHealthSet`
- `/Script/TopDownArenaRuntime.TopDownArenaAttributeSet`

The remaining 37-vs-43 ability discrepancy is also fully explained. The six missing assets are the `Phase_Playing`, `Phase_PostGame`, and `Phase_Warmup` game-phase abilities in ShooterCore and TopDownArena. AssetRegistry registers them as `/Script/GameplayAbilities.GameplayAbilityBlueprint`, not `/Script/Engine.Blueprint`. They inherit `LyraGamePhaseAbility` and are genuine GameplayAbilities.

Schema 6 now admits both exact Blueprint asset-class identities into the same loaded generated-class inheritance check. Those six phase abilities have no captured triggers, additional costs, cost GameplayEffect, or cooldown GameplayEffect, so the final recount is expected to change only `gas_abilities` from 37 to 43 while preserving the established child counts.

## Derived schema 22 GAS graph

The GAS graph layer is implemented from normalized exact fields only. It promotes relationships such as:

- ability asset -> generated class -> direct parent;
- ability -> cost/cooldown GameplayEffect class;
- ability -> ordered trigger -> exact trigger Gameplay Tag;
- ability -> additional cost object -> cost class;
- Ability Set -> granted ability/effect/AttributeSet classes;
- GameplayEffect asset -> generated class -> direct parent;
- GameplayEffect -> GE component -> component class;
- GameplayEffect -> ordered modifier -> exact gameplay attribute;
- GameplayEffect -> ordered execution -> calculation class;
- execution -> ordered execution modifier -> captured attribute;
- GameplayEffect -> ordered cue entry -> magnitude attribute when present;
- GameplayCue asset -> generated class -> direct parent;
- GameplayCue asset -> exact scalar cue tag;
- AttributeSet -> direct parent and declared gameplay attributes.

Broad exported tag-container strings are not parsed into guessed graph relations. Runtime specs, active effects, live granted ability specs, prediction state, replicated ASC runtime state, and live attributes remain outside the claim.

The second 37-ability ZIP implies 548 exact GAS-domain graph edges. The six specialized phase abilities add exactly two class-topology edges each, so the corrected 43-ability raw corpus is expected to imply **560 exact semantic GAS edges**. Expectations are generated from accepted raw rows rather than hardcoded to Lyra counts.

`systems-schema6-accept` promotes an accepted focused schema-6 capture into the canonical corpus without running Unreal or derive and writes `gas_graph_expectations.json`. `gas-graph-verify` later requires exact source/relation/target equality, `exact_semantic` edge quality, canonical stream evidence, and specialist GAS roots against derived schema 22.

## Semantic boundary

Schema 6 is authored/default-state coverage only. It does not claim active GameplayEffect specs, current granted ability specs, prediction keys/state, replicated AbilitySystemComponent runtime state, live attribute values, or runtime activation/cooldown state. The focused corpus also did not establish exact authored GameFeatureAction_AddAbilities or tag-relationship-mapping instances strongly enough for first-class promotion.

The remaining raw acceptance gate is one focused Lyra `systems-capture` to prove the `GameplayAbilityBlueprint` membership fix and obtain the authoritative 43-root corpus. No normal Lyra scan or derive is required for that gate.
