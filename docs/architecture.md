# UnrealAssetTool architecture

## Principle

UnrealAssetTool separates **extraction**, **storage**, and **interpretation**.

```text
                         Unreal Editor 5.8+
                               |
                 UUnrealAssetToolCommandlet
                               |
       +-----------------------+------------------------+
       |                       |                        |
 filesystem facts       Asset Registry facts     loaded editor objects
       |                       |                        |
 source/config          assets/dependencies       Blueprints/AI/PCG/etc.
       +-----------------------+------------------------+
                               |
                   canonical scanner JSONL
                      scanner schema 11
                               |
                        scripts/uatool.py
                               |
                 deterministic derived JSONL
                      derived schema 7
                               |
                             SQLite
                               |
             retrieval / AI context / graph analysis
```

The Unreal commandlet is authoritative for facts that require Unreal's serializer, reflection system, editor graph objects, or asset-specific runtime/editor structures.

Python-derived views are disposable interpretations of those facts.

## Facts first

If Unreal can state something exactly, UnrealAssetTool should record that fact rather than infer it from presentation.

Examples:

```text
Blueprint parent class
node concrete class
pin type
pin default
pin link
UFunction flags
struct type
state transition endpoints
Behavior Tree hierarchy
StateTree binding path
PCG edge
material expression input
asset reference
actor transform
```

Higher-level reconstruction can then derive:

```text
calls
basic blocks
parameter bindings
data provenance
cross-system relations
readable context
summaries
```

A derived result never replaces the canonical graph facts used to verify it.

## Why extraction runs inside Unreal

`.uasset` and `.umap` packages are Unreal serialization formats whose layout and editor/runtime objects vary by engine version and asset family.

Using Unreal itself provides:

- package loading;
- version handling;
- Asset Registry;
- Blueprint editor graphs;
- reflection;
- plugin/project mount points;
- editor-only authored data;
- UE-version-compatible object interpretation.

The project therefore avoids building an external `.uasset` reverse-engineering stack.

## Why canonical output is JSONL

A monolithic project JSON document becomes impractical on real projects.

JSONL provides:

- streaming writes from the commandlet;
- bounded memory use;
- partial reads;
- sharding by fact family;
- diffability;
- independent derived regeneration;
- easy ingestion into SQLite/search/vector systems;
- records that can be retrieved without sending a full project to an AI.

`uat.db` is an index, not the source of truth.

## Two schema layers

### Scanner schema

Scanner schema versions Unreal-extracted canonical facts.

Current: **11**

A scanner-schema change normally requires an Unreal rescan.

### Derived schema

Derived schema versions deterministic Python reconstruction.

Current: **7**

A derived-schema change normally requires only:

```powershell
python scripts\uatool.py derive <output>
```

or `pack`/`bundle`, which rerun derivation.

Keeping these versions separate lets interpretation evolve without needlessly rescanning large projects.

## Blueprint understanding model

Blueprint understanding is built in layers.

### Layer 1 — exact graph structure

Canonical facts:

- graph identity;
- node identity/class;
- pins and types;
- default values;
- exact links;
- variables;
- components;
- interfaces;
- reflected node state;
- object references;
- authored defaults/overrides.

This is the verification layer.

### Layer 2 — normalized semantics

Common Unreal graph-node classes are promoted to factual operations such as:

```text
function_call
variable_get
variable_set
branch
event
dynamic_cast
spawn_actor
make_struct
break_struct
set_fields_in_struct
anim_transition
anim_sequence_player
property_access
```

The classifier uses concrete Unreal classes/APIs and reflected fields. Display titles are not treated as authoritative behavior.

Schema 11's struct-operation fix is an example of this rule: Make/Break/SetFields are identified from their class hierarchy and exact `StructType`, not from text like "Make Linear Color".

### Layer 3 — executable reconstruction

Derived schema 7 builds:

- normalized functions/events;
- call graph;
- internal call parameter bindings;
- upstream data provenance;
- execution basic blocks;
- execution roots;
- normalized AnimBP state machines;
- graph context and summaries.

This is now implemented rather than future work.

## Control flow

Raw execution-pin edges remain canonical.

The derived layer groups linear execution chains into deterministic basic blocks. It starts blocks at semantic roots, joins/splits, and branch successors and preserves closed-cycle safety.

The result makes graph behavior easier to retrieve while retaining source node/pin IDs.

## Data flow and provenance

Raw data-pin edges remain canonical.

For execution-relevant sink pins, derived schema 7 recursively traces upstream producers through pure/data-only nodes.

The expression tree is bounded and records cycles/truncation explicitly.

This gives retrieval a compact answer to questions such as:

```text
What feeds this Branch condition?
Where does this setter value come from?
Which pure calls compute this impure call argument?
What feeds a function return value?
```

without deleting the raw wiring used to verify it.

## Interprocedural Blueprint flow

`blueprint_call_edges` resolves each function-call node as:

```text
internal
ambiguous_internal
external
unresolved
```

Only uniquely resolved internal calls are eligible for `blueprint_call_bindings`.

The binding layer maps:

```text
caller argument pin -> callee input parameter pin(s)
callee return parameter pin(s) -> caller output pin
```

Split struct pins are normalized to their parent function parameter.

Ambiguous interfaces/overrides remain ambiguous. The system should not manufacture a call target simply to make traversal easier.

The next provenance improvements should build on these bindings rather than inventing a separate interprocedural graph.

## Animation Blueprints

Animation extraction combines exact editor graph facts with normalized derived state-machine topology.

Canonical coverage includes AnimGraph/state-machine node semantics, state/transition settings, aliases/conduits, linked layers, cached poses, slots, sequence assets, property bindings, and reflected runtime-node state.

Derived state-machine views resolve entries and transition endpoint IDs.

Control Rig graphs are connected to the underlying compact RigVM model rather than treating editor nodes as the whole program.

## AI gameplay extraction

Behavior Trees, Blackboards, EQS, and StateTrees are treated as connected authored programs rather than generic flat UObject dumps.

The scanner preserves hierarchy/topology/settings. The derived layer creates factual cross-asset relations such as Blackboard usage, selector resolution, EQS execution, StateTree transitions, and linked assets.

Reflection-first extraction avoids hard dependencies on every editor module while still reading Unreal-owned serialized data.

## PCG and materials

PCG and material graphs follow the same architecture:

```text
exact nodes/pins/edges/properties
             +
normalized references/parameters
             +
derived relations/context
```

Reflection ownership pointers are not automatically interpreted as semantic graph relations. The PCG self-subgraph bug found during corpus testing is why this distinction matters.

## Long-term universal entity/edge graph

Specialist tables remain valuable for exact queries, but the database should continue converging toward two universal concepts.

### Entity

```text
id
kind
name
path
class/type
source
properties
```

Examples:

```text
file
asset
Blueprint
graph
node
pin
function
AnimBP state
Behavior Tree node
StateTree state
world
level
actor
component
Data Layer
```

### Edge

```text
source_id
edge_kind
target_id
properties
```

Examples:

```text
contains
inherits
depends_on
references
calls
binds_argument
binds_return
reads
writes
execution_flow
data_flow
owns_component
attached_to
placed_in
transitions_to
```

This gives an AI a common traversal model while specialist tables retain exact system semantics.

## Cross-project launcher architecture

The canonical workflow is one UnrealAssetTool checkout used against many `.uproject` files.

The launcher passes its own exact `.uplugin` descriptor to UBT and Unreal.

When a target project contains another `UnrealAssetTool.uplugin`, the launcher temporarily masks that duplicate descriptor for the build/run and restores it afterward.

This avoids requiring three manually synchronized plugin copies.

The target project's `.uatool` output and bundle still live with the target project.

See `docs/cross-project-workflow.md`.

## UE 5.8 DebugGame module loading

UE 5.8 DebugGame Editor has an important split:

```text
running target: DebugGame
project game module: DebugGame
Editor/plugin module binary form: Development-style
```

Therefore UnrealAssetTool's module binary is normally:

```text
UnrealEditor-UnrealAssetTool.dll
```

while the running DebugGame process looks for:

```text
UnrealEditor-Win64-DebugGame.modules
```

The plugin-local runtime manifest must use the target project's BuildId.

The launcher performs:

1. a full target Editor build for target/runtime readiness;
2. an explicit UnrealAssetTool module build;
3. plugin-local runtime-manifest repair using the target project's manifest/BuildId.

This behavior is launcher infrastructure, not scanner schema.

## Build/read lifecycle

A normal scan is:

```text
target .uproject
    |
validate explicit editor path
    |
temporarily mask duplicate project-local plugin descriptor if needed
    |
build target Editor if required
    |
build invoking UnrealAssetTool module
    |
repair runtime module manifest
    |
run UnrealAssetTool commandlet
    |
canonical schema-11 JSONL
    |
derive schema-7 views
    |
pack SQLite
    |
create compact upload ZIP
```

A failed commandlet run deletes/does not trust stale `manifest.json`; old output must not be mistaken for a new successful scan.

## Incremental indexing

Full scans are acceptable for current development but should not be the final workflow.

Future incremental indexing should hash:

- physical text files;
- package files;
- Blueprint graph structure;
- selected authored object state.

Unchanged facts can then be retained and only affected dependency neighborhoods re-derived.

Incremental work should come after the world/placement model is established; optimizing incomplete semantics would be premature.

## Native C++ understanding

Raw source chunks are currently the safe and useful baseline.

A later semantic source pass should use Clang tooling rather than regex because Unreal C++ includes generated headers, macros, platform conditionals, reflection annotations, and build-specific compile environments.

Potential native entities:

```text
module
namespace
class/struct/enum
inheritance
function/method
field
UCLASS/USTRUCT/UENUM/UFUNCTION/UPROPERTY
include
call/reference
```

This remains secondary to visual-program/world understanding.

## Next development priority: world and placement

The next broad extractor after 0.6.4 should connect existing gameplay semantics to where they are instantiated.

The goal is not merely "list maps." It is to answer:

```text
Which worlds/maps exist?
Which levels/sublevels belong to them?
Which actor classes are placed?
Where are actors placed?
What components and authored overrides exist on placed actors?
Which assets/Blueprints/AI/PCG/materials are referenced from those instances?
Which Data Layers contain them?
What can be learned from World Partition descriptors without loading every actor?
```

### World-scanner design rules

Prefer metadata/descriptor APIs first.

Avoid blindly loading every World Partition external actor.

Canonical facts should include, as available:

```text
world/map identity
level hierarchy
actor GUID/path/name/label
actor class
folder
tags
transform
component identity/class
component attachment
instance property overrides
Data Layers
World Partition descriptor facts
soft/hard asset references
actor references
```

Placement must remain canonical Unreal-extracted fact, not inferred from filenames or Blueprint names.

### Derived world context

Once canonical placement exists, Python can derive:

```text
world -> actor -> Blueprint/class
actor -> component -> asset
actor -> AI graph
actor -> material
actor -> PCG graph
placed gameplay clusters
per-map summaries
cross-system retrieval neighborhoods
```

That will let an AI connect the program model built in 0.6.4 to the actual playable space.

## Priority after world placement

After the world model is established:

1. deepen cross-system provenance where real gaps remain;
2. Sequencer where gameplay/cinematics require it;
3. Niagara where VFX structure materially affects understanding;
4. MetaSounds where authored audio graphs materially affect understanding;
5. native source semantics;
6. incremental indexing/query-service work.

Priority should continue to be evidence-driven by real project corpora rather than coverage-count driven.
