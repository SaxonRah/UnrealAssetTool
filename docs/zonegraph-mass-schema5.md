# Systems schema 5: Mass + ZoneGraph

Systems schema 5 is the first canonical Mass + ZoneGraph slice. It is intentionally evidence-first and reflection-backed.

## Evidence boundary

The City Sample focused evidence establishes that authored Mass configuration/spawner/agent state and authored ZoneShape state are recoverable. It does **not** establish a trustworthy reflected representation of generated `FZoneGraphStorage` lane/lane-point/lane-link topology.

Therefore schema 5 normalizes only proven serialized/authored facts and deliberately does not claim generated lane connectivity.

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

The existing loss-minimizing streams remain authoritative for reflected object detail:

```text
systems_properties.jsonl
systems_references.jsonl
```

Trait instances, generator instances and component state are written there rather than reducing every optional Mass type to a hand-maintained property list.

## Mass model

`mass_entity_configs.jsonl` records `UMassEntityConfigAsset` identity, reflected `FMassEntityConfig` metadata, config GUID, optional parent config and ordered Trait count.

`mass_entity_traits.jsonl` records exact ordered Trait object identity/class. Trait object properties and references remain in `systems_properties.jsonl` / `systems_references.jsonl`.

`mass_spawners.jsonl`, `mass_spawner_entity_types.jsonl` and `mass_spawner_generators.jsonl` preserve reflected spawner composition, including ordered entity types, exact config references, proportions, count/autospawn state and ordered generator instances.

`mass_spawn_generator_assets.jsonl` records generator Blueprint identity/inheritance and whether the generated class actually inherits `MassEntityZoneGraphSpawnPointsGenerator`; this is inheritance evidence, not an asset-name heuristic.

`mass_agent_components.jsonl` records actor-side `MassAgentComponent` identity and its reflected `FMassEntityConfig` parent/config GUID state.

### City Sample Mass acceptance

The final isolated City Sample systems capture is valid and count-complete:

```text
mass_entity_configs             28
mass_entity_traits             125
mass_spawners                    5
mass_spawner_entity_types       23
mass_spawner_generators          0
mass_spawn_generator_assets      7
mass_agent_components            36
```

All physical JSONL row counts match the schema-5 manifest and all JSONL files validate. The earlier exact-4-KiB truncation pattern was traced to specialized static `FArchive` writer buffers and fixed by closing every systems writer group synchronously inside `RunSystemsScan()` before a success manifest is written.

The Mass portion of schema 5 is therefore real-corpus accepted.

## ZoneGraph model

`zonegraph_shapes.jsonl` records authored placed `ZoneShape` / `ZoneShapeComponent` state including containing world, shape type, lane profile, tags, reverse-profile state, polygon routing type, relative transform and `PerPointLaneProfiles`.

`zonegraph_shape_points.jsonl` records ordered reflected `FZoneShapePoint` values including position, rotation, tangent length, point type, point lane-profile selector, per-point reverse-profile state, lane-connection restrictions and inner-turn radius.

A point `lane_profile` value is preserved exactly as reflected. City Sample commonly emits numeric selectors such as `255`; schema 5 does not reinterpret those values as asset paths or invent a lane-profile resolution table.

Transient connector caches are not promoted as authored topology.

Generated `FZoneGraphStorage` lanes, lane points and lane links are explicitly out of scope for schema 5 until a real scanner capture proves the exact serializable/reflected representation.

### City Sample placed-actor acceptance

The isolated systems Asset Registry pass returns zero ZoneShape rows, but the canonical world layer proves that City Sample contains placed ZoneShape actors/components. The accepted focused world capture found exactly the same actor set:

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

Field coverage in that real corpus is complete for all core normalized point values:

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

Shape-level `PerPointLaneProfiles` is present on 3/61 shapes; this is sparse authored state, not information loss. Shape types are 36 `Spline` and 25 `Polygon`; point types are 72 `Sharp` and 72 `LaneProfile`.

The ownership boundary is therefore explicit: placed ZoneShapes are world-owned canonical facts. Zero Asset Registry ZoneShape rows must not be interpreted as zero ZoneShapes.

## Optional-system implementation

The extractor introduces no hard link dependency on MassSpawner, MassActors or ZoneGraph modules. Optional-system recognition is based on loaded class inheritance and reflected `FProperty` structure, consistent with the existing Mover and Gameplay Cameras approach.

## Isolated systems capture

For real-corpus validation, the canonical launcher provides an isolated systems-only mode:

```powershell
python scripts\uatool.py systems-capture `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

The command stages/reuses the normal cross-project plugin cache, builds UnrealAssetTool when needed, launches the editor with `-UnrealAssetToolSystemsOnly`, runs only the systems scanner, validates systems schema 5, and writes a focused archive at:

```text
N:\EpicVault\Projects\CitySample\.uatool\CitySample.systems-schema5-capture.zip
```

The archive contains the systems manifest, generic systems asset/property/reference evidence, and the nine Mass/ZoneGraph schema-5 streams. It intentionally excludes world, animation, VFX, database and derived outputs.

## Focused authored ZoneGraph world capture

ZoneShape validation uses a second narrow command on the same canonical launcher:

```powershell
python scripts\uatool.py zonegraph-world-capture `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

The Python launcher reads the already-canonical `world_actors.jsonl` and `world_components.jsonl`, discovers only worlds containing exact `/Script/ZoneGraph.ZoneShape` / `/Script/ZoneGraph.ZoneShapeComponent` evidence, and writes that world list to the focused capture directory. `UnrealAssetToolZoneGraphWorld` then loads only those worlds and reflects the live placed actors/components.

The focused archive contains only:

```text
zonegraph_world_manifest.json
zonegraph_shapes.jsonl
zonegraph_shape_points.jsonl
```

The capture cross-checks the emitted shape set against the pre-existing canonical world evidence. Its manifest explicitly records:

```text
canonical_authored_zonegraph_capture = true
generated_lane_topology = false
provenance = loaded_world_placed_actor_reflection
```

## Canonical schema-5 acceptance / promotion

The accepted Mass and authored-ZoneGraph captures are intentionally separate during evidence gathering. Once both validate, a Python-only acceptance command composes them into the canonical corpus without rerunning Unreal and without running derive:

```powershell
python scripts\uatool.py systems-schema5-accept `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject"
```

The command:

1. validates the isolated systems schema-5 capture;
2. validates the focused ZoneGraph capture against the existing world actor/component set;
3. copies the complete isolated systems raw tree into a staging directory;
4. overlays only `zonegraph_shapes.jsonl` and `zonegraph_shape_points.jsonl` from the accepted world capture;
5. updates the systems manifest ZoneGraph counts/provenance while keeping `generated_lane_topology=false`;
6. runs the ordinary composed systems-schema-5 validator over the staging tree;
7. promotes JSONL files first and `systems_manifest.json` last as the commit marker;
8. writes `systems_schema5_acceptance.json` and preserves `zonegraph_world_manifest.json` beside the canonical systems manifest.

No structural/world/animation/VFX streams are replaced and no derived output is touched.

## Exact-semantic project graph boundary

Schema-5 graph promotion is limited to relationships directly established by canonical rows:

- Mass config -> parent Mass config;
- Mass config -> ordered Trait object;
- MassSpawner Blueprint -> referenced entity config;
- MassSpawner Blueprint -> referenced generator asset/instance when present;
- MassAgent component -> embedded config parent;
- generator Blueprint -> reflected parent class and proven ZoneGraph generator base inheritance;
- world -> placed ZoneShape;
- ZoneShape -> ZoneShapeComponent;
- ZoneShape -> ordered synthetic point node.

Every promoted relationship is `exact_semantic` with the originating stream/index/value retained as evidence. A ZoneGraph-based Mass spawn generator is **not** linked to a particular placed ZoneShape because the accepted corpus contains no canonical evidence for that specific binding.

## Acceptance boundary

Current status:

1. UE 5.8 native systems compilation: accepted.
2. Real City Sample isolated systems capture: accepted.
3. Mass real-corpus invariants and row-count integrity: accepted.
4. Authored ZoneShape Asset Registry path: rejected as incomplete for placed world actors.
5. Focused authored ZoneGraph world capture: accepted (61 shapes / 144 points, exact actor-set match, zero truncation).
6. Generated `FZoneGraphStorage` lane topology: explicitly not promoted.
7. Canonical systems-schema-5 promotion: implemented; pending execution against the accepted local captures.
8. Exact-semantic project-graph promotion: implemented with synthetic invariants; pending the next real derive.

City Sample derive is intentionally deferred until canonical schema-5 promotion succeeds. That promotion is Python-only and reuses the already accepted captures.
