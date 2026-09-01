# Systems schema 5: Mass + ZoneGraph

Systems schema 5 is the first canonical Mass + ZoneGraph slice. It is evidence-first and reflection-backed.

## Evidence boundary

City Sample proves authored Mass configuration/spawner/agent state and authored placed `ZoneShape` state. It does **not** prove generated `FZoneGraphStorage` lane/lane-point/lane-link topology.

Schema 5 therefore normalizes only proven serialized/authored facts. Generated lane connectivity and transient ZoneShape connector caches are deliberately not promoted.

## Canonical streams

```text
mass_entity_configs.jsonl
mass_entity_traits.jsonl
mass_spawners.jsonl
mass_spawner_entity_types.jsonl
mass_spawner_generators.jsonl
mass_spawn_generator_assets.jsonl
mass_agent_components.jsonl
zonegraph_shapes.jsonl
zonegraph_shape_points.jsonl
```

The loss-minimizing reflected-state streams remain authoritative for optional object detail:

```text
systems_properties.jsonl
systems_references.jsonl
```

Trait instances, generator instances and component state live there rather than reducing every optional Mass type to a hand-maintained property list.

## Mass model

`mass_entity_configs.jsonl` records `UMassEntityConfigAsset` identity, reflected `FMassEntityConfig` metadata, config GUID, optional parent config and ordered Trait count.

`mass_entity_traits.jsonl` records exact ordered Trait object identity/class. Trait object properties and references remain in `systems_properties.jsonl` / `systems_references.jsonl`.

`mass_spawners.jsonl`, `mass_spawner_entity_types.jsonl` and `mass_spawner_generators.jsonl` preserve reflected spawner composition, including ordered entity types, exact config references, proportions, count/autospawn state and ordered generator instances.

`mass_spawn_generator_assets.jsonl` records generator Blueprint identity/inheritance and whether the generated class actually inherits `MassEntityZoneGraphSpawnPointsGenerator`; this is inheritance evidence, not an asset-name heuristic.

`mass_agent_components.jsonl` records actor-side `MassAgentComponent` identity and its reflected `FMassEntityConfig` parent/config GUID state.

### City Sample Mass acceptance

The accepted isolated City Sample systems capture is valid and count-complete:

```text
mass_entity_configs             28
mass_entity_traits             125
mass_spawners                    5
mass_spawner_entity_types       23
mass_spawner_generators          0
mass_spawn_generator_assets      7
mass_agent_components            36
```

All physical JSONL row counts match the schema-5 manifest and all files validate.

The real-corpus capture exposed an exact-4-KiB truncation bug in specialized static `FArchive` writers. All systems writer groups are now closed synchronously inside `RunSystemsScan()` before a success manifest is written, so manifest success cannot precede JSONL finalization.

## ZoneGraph model

`zonegraph_shapes.jsonl` records authored placed `ZoneShape` / `ZoneShapeComponent` state including containing world, shape type, lane profile, tags, reverse-profile state, polygon routing type, relative transform and `PerPointLaneProfiles`.

`zonegraph_shape_points.jsonl` records ordered reflected `FZoneShapePoint` values including position, rotation, tangent length, point type, point lane-profile selector, per-point reverse-profile state, lane-connection restrictions and inner-turn radius.

A point `lane_profile` value is preserved exactly as reflected. City Sample commonly emits numeric selectors such as `255`; schema 5 does not reinterpret those values as asset paths or invent a lane-profile resolution table.

### City Sample placed-actor acceptance

The Asset Registry systems pass returns zero ZoneShape rows because City Sample's authored ZoneShapes are placed world actors. The existing canonical world layer proves 61 ZoneShape actors/components, and the focused loaded-world capture returned exactly that same set:

```text
worlds_requested                    1
worlds_loaded                       1
expected_shapes_from_world_corpus  61
zonegraph_shapes                   61
zonegraph_shape_points            144
exact_shape_set_match            true
truncated_point_rows                0
shape_point_count_range          2..4
generated_lane_topology          false
```

Core point-field coverage is complete:

```text
position                       144/144
rotation                       144/144
tangent_length                 144/144
point_type                     144/144
lane_profile                   144/144
reverse_lane_profile           144/144
lane_connection_restrictions   144/144
inner_turn_radius              144/144
```

Shape-level `PerPointLaneProfiles` is authored on 3/61 shapes. Shape types are 36 `Spline` / 25 `Polygon`; point types are 72 `Sharp` / 72 `LaneProfile`.

The ownership boundary is explicit: placed ZoneShapes are world-owned canonical facts. Zero Asset Registry ZoneShape rows must not be interpreted as zero ZoneShapes.

## Optional-system implementation

The extractor introduces no hard link dependency on MassSpawner, MassActors or ZoneGraph modules. Optional-system recognition uses loaded class inheritance and reflected `FProperty` structure, consistent with the Mover and Gameplay Cameras slices.

## Evidence capture and canonical promotion

Isolated Mass/systems capture:

```powershell
python scripts\uatool.py systems-capture `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

Focused authored ZoneGraph world capture:

```powershell
python scripts\uatool.py zonegraph-world-capture `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

The ZoneGraph command reads existing canonical world actor/component streams, discovers only worlds already proven to contain exact `/Script/ZoneGraph.ZoneShape` evidence, and loads only those worlds. Its manifest records:

```text
canonical_authored_zonegraph_capture = true
generated_lane_topology = false
provenance = loaded_world_placed_actor_reflection
```

The accepted Mass and ZoneGraph captures are composed with the Python-only command:

```powershell
python scripts\uatool.py systems-schema5-accept `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject"
```

It validates both captures, overlays only the two world-owned ZoneGraph streams onto the complete isolated systems tree, reruns the ordinary composed schema-5 validator, promotes JSONLs first, and replaces `systems_manifest.json` last as the commit marker. Promotion never launches Unreal and never runs derive.

The accepted corpus records provenance/contracts in:

```text
systems_schema5_acceptance.json
zonegraph_world_manifest.json
mass_zonegraph_graph_expectations.json
mass_zonegraph_graph_verification.json
```

## Final derived schema 21 graph contract

Mass/ZoneGraph exact-semantic graph integration advances the composed final derived schema from 20 to **21**. No alternate public launcher is introduced.

`mass_zonegraph_graph_expectations.json` is computed directly from canonical raw rows before derive and contains the exact path-level edge keys and relation counts expected from schema 5.

Only proven relationships are promoted:

- Mass config -> parent Mass config;
- Mass config -> ordered Trait object;
- MassSpawner Blueprint -> referenced entity config;
- MassSpawner Blueprint -> referenced generator asset/instance when present;
- generator Blueprint -> reflected parent class;
- generator Blueprint -> proven `MassEntityZoneGraphSpawnPointsGenerator` base inheritance when applicable;
- Blueprint -> owned MassAgent component;
- MassAgent component -> embedded config parent;
- world -> placed ZoneShape;
- ZoneShape -> ZoneShapeComponent;
- ZoneShape -> ordered synthetic point node.

Every domain edge must be `exact_semantic` and retain evidence from its canonical source stream.

A ZoneGraph-based spawn generator is **not** linked to any particular placed ZoneShape because the accepted corpus contains no canonical evidence for that binding. The post-derive verifier rejects such an invented edge even if it uses a new relation name.

### Real City Sample schema-21 expectation

The accepted raw corpus requires exactly **484** Mass/ZoneGraph domain edges:

```text
contains_zonegraph_shape                 61
has_mass_entity_trait                   125
has_zonegraph_shape_point               144
inherits_mass_entity_config              21
inherits_mass_spawn_generator_class       7
inherits_zonegraph_spawn_generator_base   4
owns_mass_agent_component                36
owns_zonegraph_shape_component            61
spawns_mass_entity_config                23
uses_mass_entity_config                   2
------------------------------------------------
total                                    484
```

No `uses_mass_spawn_generator_*` edges are expected in this City Sample capture because `mass_spawner_generators.jsonl` contains zero rows.

### Real City Sample schema-21 derive

The accepted derive completed with the existing Blueprint/world/animation/VFX semantic counts stable and the project graph at:

```text
project_nodes            834529
project_edges           3668565
project_neighborhoods     11861
```

The dedicated verifier then succeeded exactly:

```text
exact_semantic_edges:                       484
mass_entity_config_roots:                    28
zonegraph_shapes:                            61
zonegraph_shape_points:                     144
unsupported_generator_to_placed_shape_edges: 0
generated_lane_topology:                  false
```

Verification command:

```powershell
python scripts\uatool.py mass-zonegraph-graph-verify `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject"
```

The verifier requires derived schema 21, compares the actual domain edge set exactly against the raw expectation set, checks canonical evidence streams and `exact_semantic` quality, verifies Mass config roots and ZoneGraph point targets, and writes `mass_zonegraph_graph_verification.json`.

The acceptance, ZoneGraph-world, graph-expectation and graph-verification manifests are included in upload bundles when present.

## Acceptance status

1. UE 5.8 native systems compilation: **accepted**.
2. Real City Sample isolated systems capture: **accepted**.
3. Mass real-corpus integrity: **accepted**.
4. Asset Registry ZoneShape path: **rejected as incomplete for placed actors**.
5. Focused authored ZoneGraph world capture: **accepted** (61 shapes / 144 points).
6. Generated `FZoneGraphStorage` lane topology: **explicitly not promoted**.
7. Canonical systems-schema-5 promotion: **accepted and executed**.
8. Schema-21 exact-semantic graph implementation: **accepted and CI-covered**.
9. Real City Sample schema-21 derive: **accepted**.
10. Post-derive Mass/ZoneGraph graph verification: **accepted** (484/484 exact edges).
11. Query/SQLite/bundle plumbing: implemented; final corpus pack/query/bundle smoke remains the final release gate for this PR.
