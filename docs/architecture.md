# UnrealAssetTool architecture

## Purpose

UnrealAssetTool is an AI-facing indexer for Unreal Engine projects. It prioritizes authoritative authored facts from Unreal objects and serialized/editor data, then builds deterministic relationships and retrieval views outside Unreal.

The design deliberately separates:

1. **canonical Unreal extraction** — facts Unreal can state exactly;
2. **deterministic derivation** — joins/reconstruction that can be regenerated;
3. **retrieval** — SQLite/text query and compact upload bundles.

The project should not hide uncertainty by converting generic package dependencies into semantic claims.

## Current versioned layers

```text
structural schema: 12
world schema:      12
animation schema:   1   # PR #5, under validation
derived schema:    10
```

These versions are independent. A new animation extractor does not force the Blueprint/world schemas to change.

## Canonical CLI

The user-facing entry point is always:

```text
scripts/uatool.py
```

Supporting modules may exist when they isolate a real concern (`uatool_core.py`, `uatool_world_stitch.py`, `uatool_animation.py`), but launcher proliferation is intentionally avoided.

## Scan lifecycle

A normal `uatool scan` performs the following high-level lifecycle:

```text
resolve explicit Editor executable
        |
        v
stage canonical plugin into target project when necessary
        |
        v
build target Editor + UnrealAssetTool module
        |
        v
run structural Unreal commandlet
        |
        v
run world Unreal commandlet
        |
        +--> world canonical extraction
        |
        +--> animation schema-1 extraction callbacks
        |
        v
validate raw manifests
        |
        v
run deterministic Python derivation/post-pass normalization
        |
        v
build SQLite
        |
        v
create compact upload bundle
```

The animation implementation currently has a base extractor and a bounded companion/deep extractor. Both execute during the world-commandlet process and write separate internal manifests, but together form public **animation schema 1**. Python validates both and folds the companion file/count provenance into the animation schema manifest before packing.

## Why separate canonical schemas?

Different Unreal domains have different loading/lifecycle constraints.

### Structural schema

The structural commandlet owns project/source files, Asset Registry facts, Blueprint/K2/UMG/AnimBP, Control Rig/RigVM, AI, PCG and material extraction.

### World schema

World extraction loads map assets and handles actor/component instance state, references, streaming relationships, Data Layers and World Partition descriptor enumeration. World Partition is intentionally scanned without loading every external actor.

### Animation schema

Animation extraction loads only relevant animation/animation-adjacent assets and records assets that Blueprint graph topology alone cannot explain: Sequences, Montages, BlendSpaces, Skeletons, Pose Search data, authored curves, interactions, normalization and mirroring.

Pose Search/Chooser/Proxy/IK support avoids hard optional-plugin module dependencies where possible by using Unreal reflection against loaded asset classes.

This separation keeps a project that does not enable an optional animation plugin buildable while still extracting the plugin's authored facts when it is present.

## Facts-first rule

If Unreal can state a fact exactly, preserve that fact before deriving meaning.

Examples:

```text
Blueprint pin link
UFunction flag
actor transform
component attachment
World Partition GUID/reference
PCG edge
material expression input
Pose Search schema/channel
Montage section
animation curve key
Mirror Data Table row
```

Derived logic may later join or summarize these facts, but should not replace them.

## Structural extraction

Structural schema 12 owns the largest project-wide pass.

Major families:

- physical files/source/config chunks;
- Asset Registry identity/tags/package dependencies;
- Blueprint graphs/nodes/pins/edges/properties/references/state;
- UMG;
- Animation Blueprint graph/state-machine semantics;
- compact Control Rig/RigVM;
- Behavior Tree / Blackboard / EQS / StateTree;
- PCG;
- Materials / Material Instances / Material Functions.

Unknown/plugin graph nodes are preserved by concrete class, title, pins, properties and wiring instead of guessed from UI names.

## World extraction

World schema 12 owns:

- world/level identity;
- classic streaming relationships;
- loaded actors and components;
- transforms/attachments/ownership;
- placed-instance overrides;
- hard/soft object references;
- Data Layers;
- World Partition metadata/descriptors and descriptor reference GUIDs.

### World Partition policy

Descriptor enumeration should not load every external actor. The scanner may temporarily initialize a deserialized World Partition only when required/supported, walks descriptor instances, and restores initialization ownership afterward.

LevelInstance/PackedLevelActor source worlds are reconstructed deterministically from canonical descriptor/package dependency facts only when a unique target exists.

## Animation extraction

Animation schema 1 adds a dedicated authored-asset layer behind Animation Blueprint graphs.

### Base pass

Captures:

- AnimSequence/sequence-base identity and shared settings;
- notifies / notify states;
- sync markers;
- Montage sections/slots/segments;
- BlendSpace axes/samples;
- Skeleton hierarchy/sockets/metadata;
- Pose Search database/schema/channel/role facts;
- reflection-backed optional adjacent asset state/references.

### Companion/deep pass

Captures the gaps exposed by the first real GASP corpus:

- float and transform curves through `IAnimationDataModel`;
- every `FRichCurveKey` and tangent/interpolation state;
- PoseSearchInteractionAsset and role/items;
- PoseSearchNormalizationSet database membership;
- MirrorDataTable row semantics.

Python performs two representation cleanups before database packing:

- unused backing BlendSpace axis slots are removed from the canonical schema-1 representation;
- ProxyAsset is distinguished from ProxyTable rather than classified from the module-name substring.

## Deterministic derivation

Derived schema 10 currently reconstructs:

- Blueprint functions/events/calls;
- unique internal call bindings;
- bounded data provenance;
- execution blocks/roots;
- Animation Blueprint state-machine topology;
- Blueprint relations/context/summaries;
- AI relations/summaries;
- PCG/material parameters and visual relationships;
- world relations/context/summaries;
- world-to-system placement links.

### World-to-system stitching

`world_system_relations.jsonl` joins placement to specialist systems with explicit evidence.

Evidence may come from:

```text
placed_actor_class
world_reference
blueprint_relation
blueprint_asset_dependency
world_asset_dependency
```

A semantic edge is emitted only when the underlying facts justify it. Package joins require an unambiguous specialist target.

Derived animation relationships/context are intentionally postponed until animation schema 1 is stable; otherwise the project would bake unstable raw assumptions into a second layer.

## Retrieval architecture

### JSONL

Canonical and derived JSONL are the portable interchange/debug format.

### SQLite

`uat.db` is generated from the JSONL and is disposable. Specialist tables/indexes support targeted queries without placing the entire project into model context.

### Compact bundle

The normal `.uatool.zip` carries compact canonical + useful derived streams. The SQLite DB is excluded; the very large optional raw RigVM property stream is excluded unless explicitly requested.

## Cross-project staging

One canonical plugin checkout can scan other projects.

When the target is external, the launcher temporarily stages only:

```text
UnrealAssetTool.uplugin
Source/
```

under the target project's normal plugin location, moving any same-name target plugin fully outside `Plugins` during the operation. UBT therefore sees a conventional project plugin. The stage is removed and any prior target plugin restored afterward.

The launcher resolves the module binary from Unreal-generated `.modules` metadata and repairs the plugin runtime manifest using the target project's BuildId; it does not guess DebugGame DLL names.

## Coverage quality is part of the graph

Future project-level traversal must preserve two separate ideas:

1. **what relation is known?**
2. **how well is the target subsystem understood?**

A traversal hop should retain provenance such as:

```text
canonical-structural
canonical-reference
derived-exact-join
generic-package-dependency
```

and the entity should carry a coverage level. This prevents a generic Niagara package dependency from appearing as semantically equivalent to a material expression graph or Pose Search channel.

## Coverage gate before universal traversal

Current priority order:

1. finish animation schema 1 GASP + Content Examples validation;
2. add derived animation relations/context;
3. Niagara + legacy Cascade;
4. Sequencer;
5. MetaSounds/audio;
6. Enhanced Input/common gameplay data where useful;
7. typed bounded project neighborhoods across the resulting graph.

Traversal may be prototyped earlier, but must expose blind spots honestly.

## Regression strategy

Primary corpora:

- **Game Animation Sample** — Motion Matching/Pose Search/modern animation;
- **Cropout** — compact Blueprint/gameplay/AI regression;
- **Content Examples** — broad engine feature coverage, especially VFX/audio/cinematics/materials;
- **StackOBot** — targeted World Partition/LevelInstance/PackedLevelActor/PCG probe.

A new extractor is not considered stable merely because it compiles. Validation checks row-count invariants, source/target resolution, duplicate identities, unchanged prior-schema outputs where applicable, and representative authored examples.
