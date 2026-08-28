# Architecture

## Principle

UnrealAssetTool separates **extraction**, **storage**, and **interpretation**.

```text
                         Unreal Editor 5.8+
                               |
                 UUnrealAssetToolCommandlet
                               |
       +-----------------------+-----------------------+
       |                       |                       |
 filesystem facts       Asset Registry facts    loaded editor objects
       |                       |                       |
 source/config          assets/dependencies      Blueprints/graphs/etc.
       +-----------------------+-----------------------+
                               |
                         canonical JSONL
                               |
                        scripts/uatool.py
                               |
                             SQLite
                               |
             retrieval / AI context / graph analysis
```

The commandlet is the authoritative extractor. SQLite and future AI summaries are derived indexes.

## Why JSONL is canonical

A single `project.json` becomes impractical on real projects. JSONL gives the tool:

- streaming writes while Unreal scans;
- partial reads;
- easy diffing;
- independent index rebuilding;
- records that can be embedded or sent to an AI individually;
- graceful handling of projects whose Blueprint node count is in the hundreds of thousands.

## Long-term normalized graph

The database should converge on two universal concepts in addition to specialist tables:

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

- file
- module
- plugin
- native class
- native function
- asset
- Blueprint
- Blueprint graph
- Blueprint node
- Blueprint pin
- map
- actor
- component
- AnimBP state
- Behavior Tree node
- DataTable row

### Edge

```text
source_id
edge_kind
target_id
properties
```

Examples:

- contains
- inherits
- depends_on
- references
- calls
- reads
- writes
- execution_flow
- data_flow
- owns_component
- attached_to
- placed_in
- transitions_to

Specialized tables remain useful for efficient queries, but the normalized entity graph lets an AI expand context across systems without knowing every Unreal asset type ahead of time.

## Blueprint extraction

Blueprint understanding should have three layers.

### Layer 1: exact serialized structure

Already started in schema v1:

- graph identity;
- node identity/class/title;
- pins/types/defaults;
- pin links;
- variables;
- SCS components.

This is the verification layer.

### Layer 2: normalized semantics

Special-case common K2 nodes into semantic operations:

```text
call_function
get_variable
set_variable
branch
event
cast
spawn_actor
interface_call
dispatcher_bind
dispatcher_broadcast
macro_call
function_entry
function_return
```

For a `UK2Node_CallFunction`, for example, store the referenced function/member and owner class explicitly instead of making a model recover that from the display title.

### Layer 3: derived readable control flow

Build basic blocks from exec pins and render a readable representation. This is generated data, never a replacement for Layer 1.

## C++ extraction

Raw source chunks are the safe MVP because no source parser is required inside Unreal. A later native-source pass should build symbols for:

- modules;
- headers/sources;
- namespaces;
- classes/structs/enums;
- inheritance;
- functions/methods;
- fields;
- Unreal reflection macros;
- includes;
- call/reference relationships where reliably obtainable.

Clang tooling is a better long-term parser than regex because Unreal C++ has macros, generated headers, conditional compilation, and platform-specific definitions.

## Asset-specific extractors

Generic UObject reflection can discover many properties, but semantic serializers should exist for asset classes where relationships matter more than a flat property dump.

Examples:

- `UAnimBlueprint`: graphs, state machines, transitions, linked layers;
- `UAnimMontage`: sections, slots, branches, referenced sequences;
- `UBehaviorTree`: composites/decorators/services/tasks;
- `UBlackboardData`: keys and parent;
- `UDataTable`: row struct + rows;
- `UInputAction` / `UInputMappingContext`: actions/triggers/modifiers/mappings;
- materials: expressions and links;
- Niagara: systems/emitters/modules;
- PCG: graph nodes/edges/settings;
- StateTree;
- Control Rig / RigVM.

## Maps and World Partition

World scanning should avoid blindly loading every world and every external actor. Prefer metadata/descriptor APIs first, then selectively load objects only when information is unavailable otherwise.

Store:

- world/map;
- level hierarchy;
- actors and actor class;
- actor labels/folders/tags;
- transforms;
- components;
- edited property overrides;
- Data Layers;
- World Partition actor descriptors;
- soft/hard references to assets and actors.

## Incremental indexing

Full scans are acceptable initially but should not be the final workflow. Future scans should calculate stable hashes for:

- physical text files;
- package files;
- Blueprint graph structure;
- selected object properties.

Unchanged records can be retained. Changed package dependency neighborhoods can be selectively re-derived.

## AI access

The preferred end state is not "upload the whole database to an AI." It is a local query service (MCP or HTTP) that exposes operations such as:

```text
project_overview()
find_entity(name_or_path)
search_source(query)
search_blueprints(query)
get_blueprint(path, include_graphs=true)
get_dependencies(id, depth=2)
get_referencers(id, depth=2)
get_class_hierarchy(class)
get_map_contents(map)
get_context(query, token_budget=20000)
```

That makes the Unreal project itself a browsable knowledge source for an AI agent.


## Derived visual-program views

The commandlet owns engine-truth extraction. Python may build deterministic retrieval views over those facts without changing their meaning. In schema v7 this includes semantic relations, bounded graph-context text, Blueprint summaries, and a scored Control Rig editor-node to RigVM-model join. Derived views must retain ambiguity/status instead of silently guessing and must be regenerable from JSONL without launching Unreal.
