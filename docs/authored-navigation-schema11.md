# Authored Navigation systems schema 11

Authored Navigation follows the same evidence-first promotion rule used for GAS, Smart Objects, AI Perception, Dataflow/Chaos and UAF: inspect real UE 5.8.2 authored data first, use a focused native/default/config pass to resolve missing engine-side shape, normalize only proven semantics, then require an exact derived-graph verification before first-class coverage is claimed.

## Ownership model

Navigation is intentionally split across existing canonical layers rather than duplicated into one monolithic subsystem dump.

**Systems schema 11 owns authored/default definitions and policy:**

- NavArea classes, costs, supported-agent masks and inheritance;
- per-agent NavAreaMeta mappings;
- NavigationSystem / NavigationSystemConfig defaults;
- configured navigation-agent records;
- simple-link and SmartLink class defaults;
- modifier defaults;
- navigation-invoker defaults;
- NavMeshBoundsVolume supported-agent defaults;
- authored RecastNavMesh class/config defaults and exact area references.

**World schema 12 remains authoritative for world instances:**

- placed `NavMeshBoundsVolume` actors;
- placed `NavLinkProxy` actors/components;
- actor/component transforms;
- per-instance authored overrides;
- world-authored link endpoints/topology on placed instances.

This prevents systems schema 11 from manufacturing world connectivity from class defaults or copying world placement simply because an object participates in Navigation.

## Explicit non-goals

The accepted model does not capture or promote:

- generated RecastNavMesh instances;
- generated tiles or polygons;
- runtime path-query results;
- open-list/path-following state;
- dirty-tile/rebuild history;
- dynamic navigation generation history;
- runtime invoker registration state;
- transient navigation caches.

Generated navigation can remain visible through generic engine/world discovery where applicable, but it is not first-class authored Navigation evidence.

## Evidence phase

The initial read-only `navigation-evidence` diagnostic over ContentExamples proved that existing world schema already recovers meaningful placed Navigation structure. The representative `AI_NavMesh` content included:

- five `NavMeshBoundsVolume` actors;
- one real `NavLinkProxy`;
- authored simple-link endpoints and direction;
- exact `NavArea_Default` use;
- SmartLink component identity and enabled/disabled/obstacle area-class references.

It also proved that generic reflection alone was not sufficient for the class/default/config side:

- no representative placed `NavModifierVolume` / `NavModifierComponent` instance;
- no representative placed `NavigationInvokerComponent` instance;
- supported-agent/system policy mainly surfaced as config/default data;
- generic `AreaClass` / `AreaClassOverride` matches were dominated by ordinary collision/shape defaults and could not safely be promoted wholesale.

That evidence forced the split-ownership design instead of a world-schema-only or name-matching approach.

## Accepted focused native/default/config capture

The focused UE 5.8.2 ContentExamples native/default/config pass inspected exact loaded classes and recursively exported class-default/config state without loading maps for generated navigation.

Accepted capture counts:

```text
classes: 16
area_classes: 7
cdo_properties: 1497
cdo_references: 38
config_properties: 271
truncated_values: 0
depth_limit_hits: 0
container_limit_hits: 0
```

The seven discovered NavArea classes were exactly:

```text
/Script/NavigationSystem.NavArea
/Script/NavigationSystem.NavAreaMeta
/Script/NavigationSystem.NavAreaMeta_SwitchByAgent
/Script/NavigationSystem.NavArea_Default
/Script/NavigationSystem.NavArea_LowHeight
/Script/NavigationSystem.NavArea_Null
/Script/NavigationSystem.NavArea_Obstacle
```

The focused pass also proved representative defaults/config for:

- `DefaultCost` and `FixedAreaEnteringCost`;
- supported-agent masks;
- `NavigationSystemV1.SupportedAgents`;
- agent name/query extent/radius/height/step height/movement capabilities;
- `NavDataClass` and `PreferredNavData`;
- `DefaultAgentName`;
- `bGenerateNavigationOnlyAroundNavigationInvokers`;
- `NavLinkProxy.PointLinks` and SmartLink defaults;
- modifier `AreaClass` / `AreaClassToReplace`;
- invoker generation/removal radii;
- bounds supported-agent mask;
- authored Recast defaults and exact NavArea references.

The very large `NavArea_LowHeight` / `NavArea_Null` default costs are preserved exactly as UE exports them. The schema does not reinterpret or clamp those engine sentinel-style values.

## Agent-mask normalization

UE exposes supported-agent selection through repeated `bSupportsAgentN` fields. Systems schema 11 does not expand those implementation details into dozens of independent semantic columns.

Instead, every supported-agent mask is normalized to an ordered array of supported agent indices. Named/configured navigation agents are represented separately in `navigation_agents.jsonl`.

This keeps the semantic model stable while retaining the exact authored selection represented by UE.

## Canonical schema 11 streams

Systems schema 11 adds nine authoritative streams:

```text
navigation_areas.jsonl
navigation_area_agent_mappings.jsonl
navigation_systems.jsonl
navigation_agents.jsonl
navigation_link_defaults.jsonl
navigation_modifier_defaults.jsonl
navigation_invoker_defaults.jsonl
navigation_bounds_defaults.jsonl
navigation_recast_defaults.jsonl
```

### `navigation_areas.jsonl`

One row per normalized NavArea class/default definition, including:

- exact class path;
- parent NavArea class where applicable;
- area kind;
- default traversal cost;
- fixed entering cost;
- normalized supported-agent indices.

### `navigation_area_agent_mappings.jsonl`

One row per exact per-agent area mapping exposed by `NavAreaMeta_SwitchByAgent`.

The representative UE 5.8.2 capture proves all 16 explicit mappings `Agent0Area` through `Agent15Area`, and schema-11 acceptance requires all 16.

### `navigation_systems.jsonl`

Normalized `NavigationSystemV1` / `NavigationSystemConfig` authored/default policy, including exact class identity, default-agent state, supported-agent mask/policy and recoverable system references such as the crowd manager.

### `navigation_agents.jsonl`

One row per configured supported-agent record, preserving:

- stable agent index;
- authored name;
- query extent;
- radius / height / step height;
- navigation-data class;
- preferred navigation-data class;
- walk/crouch/jump/swim/fly capabilities where authored.

ContentExamples proves one configured `Default` agent.

### `navigation_link_defaults.jsonl`

Normalized class-default semantics for:

- `NavLinkProxy` simple point links;
- `NavLinkCustomComponent` SmartLink policy.

These rows preserve area-class references, direction and normalized supported-agent masks. They do **not** claim that class-default endpoints are world connections.

### `navigation_modifier_defaults.jsonl`

Normalized `NavModifierComponent` and `NavModifierVolume` defaults, including:

- area class;
- area class to replace;
- relevant authored flags such as agent-height inclusion where exposed.

### `navigation_invoker_defaults.jsonl`

Normalized `NavigationInvokerComponent` defaults:

- generation radius;
- removal radius;
- normalized supported-agent mask.

### `navigation_bounds_defaults.jsonl`

Normalized `NavMeshBoundsVolume` supported-agent defaults. Placement and transform remain world-schema facts.

### `navigation_recast_defaults.jsonl`

Authored/default RecastNavMesh configuration and exact NavArea references only. No generated Recast instance, tile or polygon state is captured.

## Accepted systems schema 11 capture

The final ContentExamples UE 5.8.2 systems capture passed the canonical schema-11 validator with:

```text
navigation_areas:                 7
navigation_area_agent_mappings:  16
navigation_systems:               2
navigation_agents:                1
navigation_link_defaults:         2
navigation_modifier_defaults:     2
navigation_invoker_defaults:      1
navigation_bounds_defaults:       1
navigation_recast_defaults:       1
```

The capture also satisfied:

```text
navigation_truncated_values:          0
navigation_missing_expected_classes: 0
```

The isolated editor process returned code 3 after writing the successful systems manifest, but the validated manifest/archive are authoritative; the systems-capture runner explicitly accepts that post-write editor exit condition.

## Derived schema 27

Derived schema 27 promotes only exact relationships proven by schema-11 rows:

```text
navigation_area_inherits_area
navigation_area_maps_agent_to_area
navigation_area_supports_agent
navigation_system_supports_agent
navigation_system_uses_crowd_manager
navigation_agent_uses_nav_data
navigation_agent_prefers_nav_data
navigation_link_uses_area
navigation_link_supports_agent
navigation_modifier_uses_area
navigation_modifier_replaces_area
navigation_invoker_supports_agent
navigation_bounds_supports_agent
navigation_recast_uses_area
```

Relations whose optional targets are absent are not manufactured. For example, the accepted ContentExamples corpus does not emit `navigation_agent_prefers_nav_data` separately when the normalized authored target does not produce a distinct supported relation, and no modifier-replacement edge is emitted when `AreaClassToReplace=None`.

## Accepted exact graph gate

The ContentExamples acceptance corpus produced exactly **27** specialist Navigation edges:

```text
navigation_agent_uses_nav_data:          1
navigation_area_inherits_area:           6
navigation_area_maps_agent_to_area:      1
navigation_area_supports_agent:          7
navigation_bounds_supports_agent:        1
navigation_invoker_supports_agent:       1
navigation_link_supports_agent:          2
navigation_link_uses_area:               3
navigation_modifier_uses_area:           2
navigation_recast_uses_area:             1
navigation_system_supports_agent:        1
navigation_system_uses_crowd_manager:    1
------------------------------------------
total:                                  27
```

`navigation-graph-verify` requires exact source/relation/target set equality, `edge_quality=exact_semantic`, and canonical-stream evidence for every specialist relation.

The accepted partial corpus derived successfully as schema 27 with:

```text
project_nodes:         8836
project_edges:        10283
project_neighborhoods:   30
```

## Acceptance commands

Canonical real-corpus gate:

```powershell
python scripts\uatool.py systems-capture `
    "E:\TheDigitalGame\ue\ContentExamples\ContentExamples.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"

python scripts\uatool.py systems-schema11-accept `
    "E:\TheDigitalGame\ue\ContentExamples\ContentExamples.uproject"

python scripts\uatool.py derive `
    "E:\TheDigitalGame\ue\ContentExamples\.uatool-navigation-acceptance"

python scripts\uatool.py navigation-graph-verify `
    "E:\TheDigitalGame\ue\ContentExamples\ContentExamples.uproject"
```

After `systems-capture`, the remaining acceptance / derive / graph-verification steps are offline and do not launch Unreal again.

## Maintained coverage claim

Authored Navigation is `first_class` when the corpus contains all nine canonical schema-11 streams. The capability contract records the split ownership boundary explicitly:

- systems = authored/default Navigation definitions and policy;
- world schema 12 = placed actors/components/transforms/instance overrides;
- generated/runtime navigation state = excluded.

This is the maintained semantic boundary for UE 5.8.2 Navigation coverage.