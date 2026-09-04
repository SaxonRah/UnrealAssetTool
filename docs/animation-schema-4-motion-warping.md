# Animation schema 4: authored Motion Warping

Animation schema 4 extends the existing schema-3 animation contract with first-class authored Motion Warping semantics.

The representative acceptance corpus is **Game Animation Sample / GASP on UE 5.8.2**.

## Public schema composition

```text
animation_schema_version=4
motion_warping_schema_version=1
derived_schema_version=32
```

Schema 4 retains all schema-2 compact animation curve/property storage and all schema-3 SkeletalMesh/PhysicsAsset streams unchanged. Motion Warping adds:

```text
animation_motion_warping_manifest.json
motion_warping_windows.jsonl
motion_warping_modifiers.jsonl
motion_warping_modifier_properties.jsonl
```

The focused/native source capture is promoted into those canonical streams. Normal `uatool scan` now runs the same dependency-free authored Motion Warping pass inside the existing headless `UnrealAssetToolWorld` process and promotes the raw capture during derive.

## Real GASP UE 5.8.2 acceptance evidence

The accepted native capture contains:

```text
animation_candidates:                 2145
animation_assets_loaded:              2145
load_failures:                           0
motion_warping_windows:                145
motion_warping_modifiers:              145
motion_warping_modifier_properties:   2565
windows_without_modifier:                0
animation_assets_with_windows:          72
```

All 145 native windows exactly match the pre-existing canonical `animation_notifies.jsonl` Motion Warping window set by `(asset_path, notify_index, notify_state_object)`.

All 145 windows are authored on `AnimMontage` assets.

### Modifier classes

```text
135  /Script/MotionWarping.RootMotionModifier_SkewWarp
 10  /Script/MotionWarping.RootMotionModifier_PrecomputedWarp
```

### Warp target names

```text
95  FrontLedge
26  BackFloor
14  BackLedge
10  SmartObject
```

The target-name value is stored as authored configuration. It is not resolved to a runtime warp target transform.

### Common authored modifier surface

All 145 modifier templates expose the common warp policy fields:

```text
WarpTargetName
WarpPointAnimProvider
WarpPointAnimTransform
WarpPointAnimBoneName
bWarpTranslation
bIgnoreZAxis
bWarpToFeetLocation
AddTranslationEasingFunc
AddTranslationEasingCurve
bWarpRotation
RotationType
RotationMethod
bSubtractRemainingRootMotion
AdditionalRotationOffset
WarpRotationTimeMultiplier
WarpMaxRotationRate
```

`RootMotionModifier_SkewWarp` additionally contributes `MaxSpeedClampRatio`.

The ten `RootMotionModifier_PrecomputedWarp` templates additionally expose authored precomputed behavior including:

```text
TranslationWarpingCurve
bSeparateTranslationCurves
TranslationWarpingCurve_InMovementDirection
TranslationWarpingCurve_OutOfMovementDirection
RotationWarpingCurve
AlignOffset
bForceTargetTransformUpright
UpdateMode
Disable
bEnableSteering
SteeringSettings
```

These fields are preserved as exact typed property rows instead of being collapsed into guessed common columns. The real GASP values vary across the ten precomputed templates, especially the translation/rotation warping curves.

## Exact graph contract

Derived schema 32 adds only exact authored relationships:

```text
animation_asset_has_motion_warping_window                  145
motion_warping_window_owns_modifier                        145
motion_warping_modifier_targets_name                       145
motion_warping_modifier_uses_warp_point_bone_name          105
motion_warping_modifier_uses_easing_curve                    0
---------------------------------------------------------------
expected exact semantic edges                              540
```

The warp-point bone relation is emitted only when `WarpPointAnimProvider == Bone`.

This distinction is evidence-driven: four GASP modifier templates retain `WarpPointAnimBoneName="interaction"` while `WarpPointAnimProvider=None`. The field is preserved in canonical data, but the graph does not manufacture an active bone relationship from it.

No easing-curve relation is present in the representative corpus because all `AddTranslationEasingCurve` object references are empty. The exact relation remains part of the schema for projects that author one.

## Runtime and generated-state boundary

Schema 4 explicitly does **not** capture or claim:

```text
runtime_state_captured=false
live_warp_targets_captured=false
active_root_motion_modifiers_captured=false
root_motion_evaluated=false
maps_loaded=false
motion_warping_module_linked=false
```

The scanner does not call runtime `GetWarpTargets`, `GetModifiers`, or root-motion processing APIs. It does not load maps and does not depend on or link the optional `MotionWarping` module.

Instead, the scanner identifies the exact serialized notify-state class path and follows the notify-owned `RootMotionModifier` UObject property by reflection. This keeps UnrealAssetTool buildable in projects that do not enable Motion Warping.

## Representative acceptance commands

After a current GASP scan/capture has produced the raw specialist capture:

```powershell
python scripts\uatool.py motion-warping-schema4-promote `
    "E:\TheDigitalGame\ue\GameAnimationSample\.uatool"

python scripts\uatool.py animation-schema4-accept `
    "E:\TheDigitalGame\ue\GameAnimationSample\.uatool"

python scripts\uatool.py derive `
    "E:\TheDigitalGame\ue\GameAnimationSample\.uatool"

python scripts\uatool.py animation-schema4-graph-verify `
    "E:\TheDigitalGame\ue\GameAnimationSample\.uatool"
```

A normal future `uatool scan` performs the raw Motion Warping pass automatically. A project with zero authored Motion Warping windows explicitly clears stale schema-4 Motion Warping facts and preserves its valid underlying animation schema instead.
