# Gameplay Framework derived schema 28

Gameplay Framework project intelligence is accepted as a **derived-only join** over canonical structural, world, and source/config evidence. It does not add a native scanner and it does not advance the systems schema beyond 11.

Validated representative corpus: **ContentExamples on UE 5.8.2**.

## Canonical ownership

The accepted ownership boundary is:

- structural schema 12 owns Blueprint asset identity, generated classes, immediate parent classes, and authored Blueprint/CDO state;
- world schema 12 owns worlds, WorldSettings instance state, placement, and exact object references;
- source/config owns exact `[/Script/EngineSettings.GameMapsSettings]` assignments from `Config/DefaultEngine.ini`;
- derived schema 28 joins those facts into Gameplay Framework semantics.

No Blueprint, WorldSettings, or config fact is copied into a parallel subsystem stream.

## Accepted representative evidence

The ContentExamples corpus proves:

```text
framework_blueprints:               36
transitive_framework_blueprints:     4
game_mode_blueprints:                8
character_blueprints:               17
player_controller_blueprints:         4
ai_controller_blueprints:             1
game_mode_selector_overrides:        15
world_game_mode_overrides:           70
project_game_maps_settings:           5
```

The original diagnostic displayed 140 WorldSettings `DefaultGameMode` rows because both the property row and its exact reference row were visible. Schema 28 uses the 70 unique authored WorldSettings property owners as the semantic edge authority.

Representative transitive inheritance includes:

```text
/Game/ExampleContent/StateTree/Blueprints/Gameplay/CE_Game_Gameplay.CE_Game_Gameplay_C
  -> /Game/Global/Blueprints/CE_Game.CE_Game_C
  -> /Script/Engine.GameMode

/Game/ExampleContent/Blueprint_Communication/Blueprints/MyCharacter_BP_Comms.MyCharacter_BP_Comms_C
  -> /Game/Global/Blueprints/PlayerCharacter.PlayerCharacter_C
  -> /Script/Engine.Character
```

The project config proves:

```text
GlobalDefaultGameMode=/Script/Engine.GameModeBase
GameInstanceClass=/Script/Engine.GameInstance
GameDefaultMap=/Game/Maps/ExampleProjectWelcome.ExampleProjectWelcome
ServerDefaultMap=/Game/Maps/ExampleProjectWelcome.ExampleProjectWelcome
EditorStartupMap=/Game/Maps/ExampleProjectWelcome.ExampleProjectWelcome
```

`GlobalDefaultServerGameMode=None` and `TransitionMap=None` remain non-edges rather than fabricated relationships.

## Exact derived relation domain

Schema 28 can emit the following exact-semantic relations when canonical evidence exists:

```text
defines_gameplay_framework_class
inherits_gameplay_framework_class

game_mode_overrides_default_pawn_class
game_mode_overrides_hud_class
game_mode_overrides_player_controller_class
game_mode_overrides_game_state_class
game_mode_overrides_player_state_class
game_mode_overrides_spectator_class
game_mode_overrides_replay_spectator_player_controller_class

world_overrides_default_game_mode_class
pawn_uses_ai_controller_class

project_sets_global_default_game_mode_class
project_sets_global_default_server_game_mode_class
project_sets_game_instance_class
project_sets_game_default_map
project_sets_server_default_map
project_sets_editor_startup_map
project_sets_transition_map
```

Only relations actually evidenced by the corpus are emitted.

## Real acceptance result

The real ContentExamples acceptance produced exactly **187** Gameplay Framework edges:

```text
defines_gameplay_framework_class:             36
inherits_gameplay_framework_class:            36
game_mode_overrides_default_pawn_class:        7
game_mode_overrides_hud_class:                 3
game_mode_overrides_player_controller_class:   5
pawn_uses_ai_controller_class:                25
project_sets_editor_startup_map:               1
project_sets_game_default_map:                 1
project_sets_game_instance_class:              1
project_sets_global_default_game_mode_class:   1
project_sets_server_default_map:               1
world_overrides_default_game_mode_class:      70
TOTAL:                                        187
```

`gameplay-framework-graph-verify` proved exact source/relation/target set equality at derived schema 28.

The acceptance also records:

```text
runtime_state_captured: False
runtime_possession_state_captured: False
runtime_spawn_state_captured: False
native_default_state_inferred: False
```

## Mixed-version corpus compatibility

The representative ContentExamples full corpus predates the later UAF and Navigation systems passes and truthfully contains **systems schema 9**. Gameplay Framework does not depend on systems schema 10 or 11, so forcing a new systems scan would couple an unrelated derived-only feature to later specialist extraction.

The accepted derive policy therefore permits an already-accepted Gameplay Framework corpus to reuse a successful older systems schema 9 or 10 pass only when:

- the Gameplay Framework acceptance/expectation manifests target derived schema 28;
- the older systems manifest is successful;
- every stream declared by that manifest still exists;
- every declared row count exactly matches the stream contents.

The manifest remains truthful about the older systems version. Missing UAF/Navigation streams are not promoted and no later systems coverage is implied.

Normal scans and unaccepted/damaged corpora remain subject to the current systems-schema-11 validator.

## Deliberate non-claims

Derived schema 28 does **not** claim:

- runtime spawned Pawn, Controller, GameState, or PlayerState instances;
- current or historical possession;
- runtime GameMode selection or simulation;
- seamless-travel/session state;
- effective inherited native selector values that are absent from authored rows;
- framework identity from asset names;
- semantic ownership from package dependencies.

Blueprint calls/events such as `Possess`, `ReceivePossessed`, `RestartPlayer`, or `K2_PostLogin` can remain authored usage evidence, but are not promoted into runtime state facts.

## Commands

Acceptance is offline:

```powershell
python scripts\uatool.py gameplay-framework-accept "E:\TheDigitalGame\ue\ContentExamples\.uatool"
python scripts\uatool.py derive "E:\TheDigitalGame\ue\ContentExamples\.uatool"
python scripts\uatool.py gameplay-framework-graph-verify "E:\TheDigitalGame\ue\ContentExamples\.uatool"
```

No Unreal Editor launch or native rebuild is required for this slice.
