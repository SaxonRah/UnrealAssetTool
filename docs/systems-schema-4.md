# Systems schema 4

Systems schema 4 is the current gameplay-systems canonical extraction contract on `main`.

It retains the schema-2 gameplay-data / Gameplay Tags model and adds reflection-backed Mover and Gameplay Cameras extraction while preserving the project rule that Unreal emits authored facts and deterministic Python derives higher-level semantics.

Historical contracts remain documented in [systems-schema-1.md](systems-schema-1.md) and [systems-schema-2.md](systems-schema-2.md).

## Versioning

```text
systems schema = 4
derived schema = 20
Chooser decision schema = 1
Gameplay Camera behavior schema = 2
```

The schemas are independently versioned. A Python-only semantic/readability change does not require an Unreal rescan unless canonical C++ extraction changes.

## Retained schema-2 gameplay data / Gameplay Tags

Schema 4 preserves the accepted schema-2 canonical model for:

- general DataTable rows/fields and exact object references;
- CurveTable rows/keys;
- PrimaryDataAsset identity;
- Gameplay Tags settings, configured sources, merged dictionary and redirects.

Project-specific table/PrimaryDataAsset meaning remains loss-minimizing rather than guessed. See [systems-schema-2.md](systems-schema-2.md) for the historical schema-2 contract and [schema.md](schema.md) for the current combined stream list.

## Mover

Canonical streams:

```text
mover_blueprints.jsonl
mover_components.jsonl
mover_modes.jsonl
mover_settings.jsonl
mover_transitions.jsonl
```

The scanner is reflection-backed and does not require a hard compile-time dependency on the Mover plugin.

Normalized facts include:

- Blueprint and component identity;
- authored Mover component defaults;
- movement modes and starting mode;
- shared settings and required setting classes;
- movement transitions;
- exact referenced Mover backend classes.

Derived Mover behavior adds:

```text
mover_transition_behaviors.jsonl
mover_transition_routes.jsonl
```

and exact project-graph relations including movement-mode ownership, starting modes, transitions and concrete transition routes.

GASP corpus validation includes the modern Mover character rather than treating CharacterMovementComponent as the current architecture.

## Gameplay Cameras canonical topology

Canonical streams:

```text
gameplay_camera_assets.jsonl
gameplay_camera_rigs.jsonl
gameplay_camera_nodes.jsonl
gameplay_camera_node_edges.jsonl
gameplay_camera_transitions.jsonl
gameplay_camera_directors.jsonl
gameplay_camera_rig_references.jsonl
```

The scanner uses reflected class identity / inheritance and therefore does not require a hard GameplayCameras module dependency.

### Camera Assets

Normalized facts include:

- Camera Asset identity;
- instantiated camera director identity/class;
- director `bRunInEditor` state;
- enter/exit/shared transition topology;
- reflected rig references where they are actually authored.

A director rig-reference count of zero is valid when a Blueprint director selects rigs indirectly through a Chooser table. The scanner does not invent direct director-to-rig ownership.

### Camera Rigs

Normalized facts include:

- Camera Rig identity;
- root node;
- initial orientation;
- Gameplay Tags;
- complete owned camera-node set;
- exact reflected node-to-node edges;
- enter/exit/transition-object topology;
- reflected rig-to-rig references such as prefab/reference nodes.

### GASP schema-4 corpus gate

The accepted Game Animation Sample scan contains:

```text
gameplay_camera_assets = 1
gameplay_camera_rigs = 16
gameplay_camera_nodes = 30
gameplay_camera_node_edges = 10
gameplay_camera_transitions = 5
gameplay_camera_directors = 1
gameplay_camera_rig_references = 11
```

All manifest counts reconcile to physical JSONL rows, rig roots resolve, node-edge endpoints resolve inside their owning rigs, and promoted camera-topology graph edges are `exact_semantic`.

The corpus proves non-trivial authored graphs, including the TwinStick rig and the reusable ThirdPerson prefab rig.

## Chooser decision semantics

Gameplay Camera rig selection in GASP is not represented as direct reflected director-to-rig pointers. The exact path is:

```text
CameraAsset_SandboxCharacter
  -> BlueprintCameraDirector
     -> CameraDirector_SandboxCharacter Blueprint
        -> CHT_CameraRig
           -> Chooser decision row
              -> CameraRig
```

Generic Chooser interpretation is persisted independently as:

```text
chooser_decisions.jsonl
chooser_decision_predicates.jsonl
```

The interpreter preserves raw exported structs while normalizing supported enum-column predicates (`MatchEqual`, `MatchAny`, `MatchNotEqual`) and resolving user-defined enum display names without guessing ambiguous values.

GASP validation for `CHT_CameraRig`:

```text
camera decisions = 12
camera predicates = 36
fully modeled = 12
fully decoded = 12
unresolved CameraRig results = 0
```

The decoded rule matrix covers the Ragdoll override, Close/Medium/Far x FreeCam/Strafe/Aim selections, DebugView exception and TwinStick override.

Project-graph relations include:

```text
has_chooser_decision
tests_chooser_enum
selects_chooser_result
disabled_chooser_result
```

Promoted Chooser edges are exact semantic facts; unsupported column/value families remain raw rather than being guessed.

## Gameplay Camera provider/director behavior

The GASP camera director calls the `BPI_SandboxCharacter_Pawn` interface dynamically. The derived model preserves that polymorphism instead of forcing a single implementation.

Persisted behavior streams:

```text
gameplay_camera_property_providers.jsonl
gameplay_camera_property_fields.jsonl
gameplay_camera_director_inputs.jsonl
```

Accepted GASP counts:

```text
providers = 2
provider fields = 9
director inputs = 5
```

The two providers are:

```text
SandboxCharacter_CMC.Get_PropertiesForCamera
SandboxCharacter_Mover.Get_PropertiesForCamera
```

The Blueprint Interface declaration itself is a contract and is never treated as an executable provider implementation.

### Modern Mover provider

The accepted readable Mover semantics are:

```text
CameraMode =
    TwinStickMode
        ? TwinStick
        : RotationMode {
              OrientToMovement -> FreeCam
              Strafe           -> Strafe
              Aim              -> Aim
          }

Gait = MoverCustomInputs_PostSim.Gait

Stance = CharacterMover.IsCrouching()
    ? Crouch
    : Stand

MovementMode = Get_CurrentMovementMode()
```

### Director context

`CameraDirector_SandboxCharacter` supplies the final Chooser context as:

```text
CameraStyle = DDCvar.CameraStyle
CameraMode = provider.CameraMode
Gait = provider.Gait
Stance = provider.Stance
MovementMode = provider.MovementMode
```

The four provider-derived fields retain both valid provider candidates. `CameraStyle` is separately modeled as a console-variable source.

Gameplay Camera behavior schema 2 decorates readable enum projections while preserving raw serialized identity. For example, `OnGround` may be the readable value while `NewEnumerator4` remains available under raw literal data / the raw expression tree.

The schema exposes decode-completeness metadata and never guesses an unresolved enum.

### Behavior graph gate

The accepted GASP project graph contains exactly 28 promoted behavior edges:

```text
builds_camera_context_field = 5
evaluates_camera_chooser = 1
has_camera_property_provider_candidate = 2
implements_camera_property_provider = 2
passes_through_camera_property_candidate = 8
provides_camera_property = 9
reads_console_variable = 1
```

All 28 edges are `exact_semantic`.

## End-to-end GASP camera path

The resulting AI-readable path is:

```text
SandboxCharacter_Mover gameplay state
        -> MoverCustomInputs_PostSim / CharacterMover / Get_CurrentMovementMode
        -> Get_PropertiesForCamera
        -> normalized camera property fields
        -> CameraDirector_SandboxCharacter
        -> DDCvar.CameraStyle override + provider passthrough fields
        -> CHT_CameraRig
        -> 12 decoded Chooser decisions
        -> selected CameraRig
        -> CameraRig node / transition / prefab-reference topology
```

This is sufficient to consider the Gameplay Cameras slice of Issue #14 first-class for the validated GASP corpus.

## Boundaries

- Runtime camera evaluation is not simulated.
- Dynamic interface dispatch remains candidate-based when the evaluation-context actor type is not statically unique.
- Unsupported Chooser column/value families remain lossless raw structs.
- Reflection-derived topology is promoted only when object identity/property endpoints make the relationship exact.
- A Python-only derived/readability change does not justify rescanning Unreal.
