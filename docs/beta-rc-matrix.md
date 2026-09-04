# 1.0 beta release-candidate matrix

This is the executable gate for issue #97. It turns the representative sample projects into one named `1.0.0-beta.1` release-candidate regression matrix.

## Command

From the canonical checkout:

```powershell
python scripts\uatool.py beta-rc-check `
    "E:\Path\Project\.uatool" `
    --profile gasp
```

Use `--json` for machine-readable output or `--record <file.json>` to write the complete record.

The command requires a **current, fresh derive**. If the corpus was produced by compatible current canonical scanners but the Python-derived contract changed, run:

```powershell
python scripts\uatool.py derive "E:\Path\Project\.uatool"
```

If the RC check reports an old canonical schema (for example structural < 13, animation < 4, or systems < 11), perform a normal Unreal `scan` for that project instead of trying to repair the corpus with Python.

## Current beta baseline

```text
structural=13
world=12
animation=4
vfx=1
systems=11
mesh=1
world_geometry=1
derived=39
capabilities=1
```

Every RC record also requires tool version `1.0.0-beta.1` and validated engine `UE 5.8.2` in `capabilities.json`.

The table above is the **tool-current schema contract**, not a claim that every
representative project contains authored data for every content-dependent
companion pass. `mesh` and `world_geometry` are optional per corpus: if the
corresponding capability family is available, the observed schema must equal
the current version above; if the capability family is explicitly
`external_or_excluded` because the project has no authored candidates, the
corpus may report schema `0`. Any other nonzero version is rejected. Core
scanner, derived and capability schemas remain exact requirements for every RC
record.

## Profiles

### `gasp`

Purpose: Blueprint/K2, cross-graph semantics, Mover, animation/Pose Search, Motion Warping, delegates and Control Rig/RigVM.

GASP is a strict accepted-count regression gate:

```text
blueprint_nodes                                      18329
blueprint_semantic_nodes                             18329
blueprint_interprocedural_data_routes                   47
blueprint_interprocedural_function_execution_edges     668
blueprint_interprocedural_function_data_routes          872
blueprint_delegate_bindings                              24
blueprint_call_bindings                                 908
rigvm_editor_links                                     6646
mover_transition_behaviors                                2
mover_transition_routes                                   2
motion_warping_windows                                  145
pose_search_databases                                  >= 1
```

### `contentexamples`

Purpose: broad systems, VFX, audio, materials, Sequencer, gameplay data and Gameplay Tags.

Requires representative first-class/depth-pending families plus non-empty LevelSequence, audio, material-expression, VFX, DataTable, Gameplay Tag and project-edge streams.

### `citysample`

Purpose: Mass, authored ZoneGraph, Smart Objects, world and project-graph regression.

Requires non-empty MassEntityConfig, ZoneShape, SmartObjectDefinition, world-actor and project-edge streams.

### `lyra`

Purpose: Gameplay Ability System and Gameplay Framework.

Requires GAS and Gameplay Framework capability coverage plus non-empty ability, GameplayEffect, Blueprint, world and project-edge streams.

### `cropout`

Purpose: compact Blueprint/gameplay/world regression.

Requires Blueprint, world and project-graph coverage plus non-empty raw/semantic Blueprint nodes, world actors and project edges.

### `stackobot`

Purpose: PCG, world and project-graph corpus regression. External staging/build/bundle behavior is validated separately by the clean-user workflow gate (#98).

Requires non-empty PCG graph/node, world-actor and project-edge streams.

## Record format

Each successful check records:

- record schema version;
- UnrealAssetTool release version;
- exact Git commit;
- profile and representative project name;
- observed current schemas;
- required family availability/coverage;
- measured profile stream counts;
- every individual check and its result;
- final `accepted` boolean and failure list.

Local absolute corpus paths are deliberately not part of the portable record.

## Acceptance

The release-candidate matrix is accepted when all six profiles pass on the same beta candidate commit, with no unexplained semantic-count or topology regression.
