# UnrealAssetTool 1.0 beta release contract

## Release

```text
version:          1.0.0-beta.1
engine target:    UE 5.8+
validated engine: UE 5.8.2
```

The canonical CLI reports this contract directly:

```powershell
python scripts\uatool.py --version
python scripts\uatool.py version
python scripts\uatool.py version --json
```

`UnrealAssetTool.uplugin`, the CLI, `capabilities.json`, and current-facing documentation must agree on the release version.

## Current full-corpus schema baseline

```text
structural=13
world=12
animation=4
vfx=1
systems=11
mesh=1
world_geometry=1
derived=37
capabilities=1
```

These schemas are independently versioned. Historical subsystem documents describe the schema milestone that introduced or accepted that subsystem and are not rewritten when unrelated later schemas advance.

A full current corpus is identified by its manifests, not by a single monolithic version number.

## Compatibility policy

Canonical scanner schemas and derived schemas are independent contracts.

- Native scanner changes advance the relevant canonical schema and normally require Unreal to scan again.
- Compatible Python-only derived changes advance only the derived/companion contract and normally require `derive`, `pack`, or `bundle`, not an Unreal rescan.
- Commands refuse stale or incompatible derived output rather than silently interpreting it under a newer contract.
- Old corpora remain self-describing through their manifests. They are not automatically claimed to satisfy the current baseline.
- Focused subsystem captures remain explicitly partial and do not imply unrelated canonical passes were run.

During the `1.0.0-beta.*` line, an individual schema may still advance when real-corpus evidence requires it. Breaking or ambiguous semantic changes must be evidence-driven, versioned, and validated before release.

## Semantic guarantee

The beta guarantee is **truthful authored semantics**, not exhaustive Unreal runtime simulation.

First-class semantics are promoted only from exact native/canonical evidence or deterministic derivations that can be reproduced from that evidence.

The tool does not silently turn package dependencies, names, or visual similarity into first-class semantic facts.

Important global non-claims include:

- no Blueprint VM execution;
- no latent scheduler simulation;
- no runtime delegate subscriber set/order/lifetime or broadcast execution;
- no runtime Mover simulation;
- no live GAS specs/prediction/runtime AttributeSet values;
- no Niagara/particle simulation;
- no shader compilation/runtime material resource graph;
- no runtime animation pose/search evaluation;
- no runtime AI/StateTree/BehaviorTree execution state;
- no generated PCG spatial output;
- no dynamically spawned world state unless authored/captured by a canonical pass.

`capabilities.json` is the machine-readable source for family-by-family coverage and boundaries.

## 1.0 beta acceptance bar

`1.0.0-beta.1` is ready when all of these gates are satisfied:

1. release/version/schema contract synchronized;
2. representative multi-corpus release-candidate matrix accepted;
3. clean-user install/build/scan/derive/query/inspect/bundle workflow accepted;
4. full Python smoke green;
5. no known high-confidence semantic corruption;
6. release notes enumerate first-class coverage, depth-pending coverage, generic gaps, schema baseline, and non-claims.

Exhaustive depth for every Unreal subsystem is **not** a beta blocker when the capability contract accurately reports the boundary.

## Representative release-candidate corpora

The beta RC matrix uses:

- **Game Animation Sample (GASP)** — Blueprint/K2, Mover, animation/Pose Search, Control Rig/RigVM, delegates;
- **Content Examples** — broad systems, VFX, audio, materials, Sequencer and gameplay-data coverage;
- **City Sample** — Mass, ZoneGraph and Smart Objects;
- **Lyra** — Gameplay Ability System and Gameplay Framework;
- **Cropout** — compact Blueprint/gameplay regression;
- **StackOBot** — external-project staging/build, world/PCG and bundle workflow.

Each RC result records the exact Git commit and observed schema versions so later regressions can be compared against a named release candidate rather than informal historical runs.
