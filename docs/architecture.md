# UnrealAssetTool architecture

## Purpose

UnrealAssetTool is an AI-facing indexer for Unreal Engine projects. It prioritizes authoritative authored facts from Unreal objects and serialized/editor data, then builds deterministic cross-system relationships and retrieval views outside Unreal.

The architecture has three layers:

1. **canonical Unreal extraction** — facts Unreal can state exactly;
2. **deterministic derivation** — joins, normalization and bounded traversal that can be regenerated;
3. **retrieval** — SQLite queries and compact upload bundles.

A generic package dependency is useful fallback evidence, but it is never promoted to the same confidence as an exact authored object reference.

## Current schemas

```text
structural schema: 12
world schema:      12
animation schema:   1
VFX schema:         1
systems schema:     4
derived schema:    20
```

Each layer is independently versioned. Canonical scanner changes normally require Unreal to run again. Compatible Python-derived changes can normally be applied with `derive`, `pack` and `bundle` only.

## One public CLI

The user-facing entry point is always:

```text
scripts/uatool.py
```

Supporting Python modules isolate real concerns, but are implementation details rather than alternate launchers.

## Scan lifecycle

A normal scan follows this shape:

```text
explicit Unreal Editor executable
        |
        v
stage canonical plugin when target is external
        |
        v
freshness-safe build
        |
        +--> full Editor target if target-owned native inputs changed
        |
        +--> otherwise UnrealAssetTool module-only unity build
        |
        v
structural Unreal commandlet
        |
        v
world Unreal commandlet process
        |
        +--> world schema 12
        +--> animation schema 1 passes
        +--> VFX schema 1 callback
        +--> systems schema 4 callback
        |
        v
raw manifest validation
        |
        v
canonical cleanup + deterministic derivation
        |
        +--> Blueprint/AI/PCG/material/world/animation/VFX views
        +--> Gameplay Tags/gameplay-data joins
        +--> Blueprint enum/control-flow/Chooser semantics
        +--> Mover behavior and Gameplay Camera behavior
        +--> typed project graph
        +--> bounded quality-prioritized neighborhoods
        |
        v
SQLite pack
        |
        v
compact upload ZIP
```

VFX and systems piggyback the world Editor process rather than launching separate Editors. This keeps a normal scan to two Unreal processes: one structural process and one world/animation/VFX/systems process.

## Canonical extraction layers

### Structural schema 12

The structural commandlet owns project-wide content that does not require loading every world:

- physical files/source/config/document chunks;
- Asset Registry identity, tags and package dependencies;
- Blueprint/K2/UMG/Animation Blueprint graphs;
- compact Control Rig/RigVM;
- Behavior Tree, Blackboard, EQS and StateTree;
- PCG graphs;
- Materials, Material Instances and Material Functions.

Unknown or plugin-specific graph nodes remain preserved by concrete class, pins, properties, references and wiring instead of guessed from display labels.

### World schema 12

The world commandlet owns placement and map state:

- world/level identity;
- classic streaming relationships;
- loaded actors and components;
- transforms, attachments and ownership;
- placed-instance property overrides;
- hard/soft UObject references;
- Data Layers;
- World Partition metadata and actor descriptors.

World Partition descriptors are enumerated without deliberately loading every external actor. LevelInstance/PackedLevelActor source worlds are derived only when canonical facts identify a unique target.

### Animation schema 1

Animation schema 1 records authored animation content behind Animation Blueprint graphs. It is implemented as several internal passes but exposed as one public schema.

Coverage includes:

- AnimSequence, AnimMontage and BlendSpace families;
- notifies, notify states, sync markers, Montage sections/segments and BlendSpace samples;
- Skeleton hierarchy, sockets and slot groups;
- float/transform curves and individual rich-curve keys;
- Pose Search databases, schemas, channels, roles and source assets;
- Pose Search Interaction Assets and Normalization Sets;
- Mirror Data Tables;
- Pose Assets including tracks/poses/transforms/curve values;
- Chooser tables, columns, results and contexts;
- Proxy tables/entries/inheritance;
- IK Rig bones/chains/goals/solvers;
- IK Retargeter operations/poses;
- bounded reflected properties/references for adjacent optional assets.

Optional-plugin families are reflection-backed where practical so UnrealAssetTool does not require those modules to be enabled in every scanned project.

### VFX schema 1

VFX schema 1 covers Niagara, Niagara Stateless and legacy Cascade. Canonical streams preserve:

- VFX asset identity/properties/references;
- Niagara System emitter composition;
- emitter versions;
- renderers and simulation stages;
- stateless emitters/modules/renderers;
- Niagara scripts;
- Data Channels and variables;
- Parameter Collections and parameters;
- Effect Types;
- Cascade systems, emitters, LODs and modules.

Derived VFX views join exact canonical VFX topology/references and world/Blueprint evidence. Generic Asset Registry dependencies are excluded from semantic VFX evidence.

### Systems schema 4

Systems schema 4 extends the original reflection-first systems pass with accepted gameplay-data, Mover and Gameplay Cameras normalization while keeping optional plugin dependencies reflection-backed where practical.

Coverage includes:

- LevelSequence/MovieScene bindings, tracks, sections and channels;
- SoundCue nodes;
- MetaSound frontend nodes and edges;
- core audio asset summaries/references;
- Enhanced Input actions, mapping contexts, mappings, triggers and modifiers;
- selected Common Input assets;
- general DataTable rows/fields and exact row references;
- CurveTable rows/keys;
- PrimaryDataAsset identity;
- project Gameplay Tags settings, sources, dictionary and redirects;
- Mover Blueprint/component/movement-mode/shared-setting/transition composition;
- Gameplay Camera assets, rigs, nodes, node edges, transitions, directors and reflected rig references.

The canonical scanner does not invent direct ownership where the project uses indirect behavior. In GASP, for example, the camera director selects rigs through a Chooser table rather than through direct director-to-rig pointers.

See [systems-schema-4.md](systems-schema-4.md) for the current systems contract. [systems-schema-1.md](systems-schema-1.md) and [systems-schema-2.md](systems-schema-2.md) are historical contracts.

## Facts-first rule

If Unreal can state a fact exactly, preserve that fact before deriving meaning.

Examples:

```text
Blueprint pin link
UFunction flags
actor/component transform
World Partition descriptor GUID/reference
PCG edge
material expression input
animation curve key
Pose Search schema/channel
Niagara renderer/module relationship
MovieScene track/section/channel containment
MetaSound node/edge endpoint
InputAction mapping/processor
Mover movement-mode/transition ownership
Gameplay Camera rig/node/transition topology
```

Derived logic may later join or summarize these facts, but should not replace them.

## Deterministic derivation

Derived schema 20 is disposable and reproducible from compatible canonical input. Major views include:

- Blueprint functions/events/calls/bindings/data provenance/execution blocks;
- generic Blueprint semantic nodes/statements/control-flow edges;
- Blueprint user-defined enum display semantics;
- Animation Blueprint state-machine topology;
- AI relations and summaries;
- PCG/material parameters and visual relations;
- world relations/context/summaries;
- world-to-system placement links;
- animation relations/context/summaries;
- VFX relations/context/summaries;
- generic Chooser decisions and predicates;
- Mover transition behaviors and concrete routes;
- Gameplay Camera provider/director context behavior;
- typed project nodes/edges/neighborhoods.

Later independently versioned derived submodels can add readable semantics without forcing a canonical Unreal rescan. For example, Gameplay Camera behavior schema 2 decorates enum display names while preserving the raw `NewEnumeratorN` values and raw expression trees.

### World-to-system stitching

`world_system_relations.jsonl` joins placement to first-class systems when evidence supports the relationship. Evidence can include exact world references, Blueprint relations, placed Blueprint classes and uniquely resolved package-level dependencies.

### Typed project graph

`project_nodes.jsonl` and `project_edges.jsonl` unify canonical and derived families into one traversal surface.

Node coverage classes:

```text
first_class
first_class_depth_pending
partial
generic_only
external_or_excluded
```

Edge quality classes:

```text
exact_semantic
exact_reference
unique_dependency_resolution
generic_package_dependency
```

Every graph edge retains evidence/provenance. Asset Registry package dependencies remain explicit low-quality `package -> package` hops.

### Bounded neighborhoods

Project neighborhoods are precomputed to depth 3 with a 256-edge budget. Traversal prioritizes exact semantic/reference evidence before package plumbing.

Neighborhoods store compact references to authoritative project edges. Each hop records:

```text
depth
direction
edge_id
edge_quality
source_coverage
target_coverage
evidence_count
```

The full source/target/relation/evidence remains authoritative in `project_edges.jsonl`. Readable neighborhood text is reconstructed on demand.

## Canonical cleanup

Post-scan cleanup may remove generated values that are not authored semantic state when that transformation is exact and deterministic.

Current examples include:

- generated `UMaterialExpression::MaterialExpressionGuid` rows;
- generated/representation-only values previously identified in subsystem validation.

Cleanup must preserve every retained row byte-for-byte where practical and update manifest counts.

## Retrieval architecture

### JSONL

Canonical and derived JSONL are the portable interchange/debug representation.

### SQLite

`uat.db` is a disposable indexed cache. It is rebuilt from JSONL using bulk-load settings, then returned to normal SQLite durability settings. Non-unique secondary indexes are created after bulk insertion for faster packing and denser B-trees.

### Upload bundle

The normal `.uatool.zip` contains portable JSON/manifests, not `uat.db`. Large optional raw RigVM properties are excluded unless explicitly requested.

Default ZIP compression is Deflate level 3; `UATOOL_BUNDLE_LEVEL=0..9` overrides it.

### Derived freshness

`.derived_freshness.json` is written only after raw and derived validation succeeds. It records schema/source/file metadata so `pack` and `bundle` can reuse current derived output instead of reparsing/rebuilding it unnecessarily.

## Cross-project staging and build cache

One canonical checkout can scan unrelated targets. External projects temporarily receive:

```text
<Target>/Plugins/UnrealAssetTool/
  UnrealAssetTool.uplugin
  Source/
```

Generated `Binaries/` and `Intermediate/` are moved to:

```text
<Target>/Saved/UnrealAssetToolBuildCache/
```

when the temporary stage is removed, then restored for the next build. This keeps repeated external builds incremental without leaving maintained plugin source copies in each project.

If the target Editor runtime manifest is current and target-owned native/build inputs have not changed, the launcher uses an isolated module-only build with unity enabled and adaptive unity disabled for the scanner module. Otherwise it falls back to the full target build.

## Regression strategy

Primary UE 5.8.2 corpora:

- **Game Animation Sample** — Blueprint/animation/Pose Search/Enhanced Input scale plus accepted Mover and Gameplay Cameras validation;
- **Content Examples** — broad VFX, Sequencer, audio, MetaSound, material and gameplay-data/Gameplay Tags breadth;
- **StackOBot + Niagara Examples** — World Partition/LevelInstance/PCG/VFX and cross-project build regression;
- **Cropout** — compact Blueprint/gameplay regression.

A scanner family is considered stable only after corpus-level validation of counts, topology, endpoint resolution, provenance quality, deterministic identities and prior-output regressions.

## Remaining architecture boundary

Asset Registry is intentionally universal; first-class semantic extraction is intentionally selective. The project should expand first-class coverage where an asset family's authored internals materially affect gameplay understanding, while preserving unsupported assets honestly as generic entities rather than fabricating semantics.

Issue #14's remaining high-value work includes GAS, Smart Objects, AI Perception, ZoneGraph/Mass, Dataflow/GeometryCollection and AnimNext. Corpus availability still determines implementation order.

See [coverage.md](coverage.md) for the current audit.
