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

`zonegraph_shapes.jsonl` records authored `ZoneShape` / `ZoneShapeComponent` state including shape type, lane profile, tags, reverse-profile state, polygon routing type and relative transform.

`zonegraph_shape_points.jsonl` records ordered reflected `FZoneShapePoint` values including position, rotation, tangent length, point type, point lane profile and lane-connection restrictions.

Transient connector caches are not promoted as authored topology.

Generated `FZoneGraphStorage` lanes, lane points and lane links are explicitly out of scope for schema 5 until a real scanner capture proves the exact serializable/reflected representation.

### City Sample placed-actor finding

The isolated systems Asset Registry pass returns zero ZoneShape rows, but the existing canonical world layer proves that City Sample contains placed ZoneShape actors/components. Focused evidence contains 61 `/Script/ZoneGraph.ZoneShape` actors and 61 `/Script/ZoneGraph.ZoneShapeComponent` components, with authored world-instance state for `Points`, `LaneProfile`, `Tags`, `ShapeType`, `bReverseLaneProfile`, `PolygonRoutingType` and transforms.

This means the ownership boundary is different from Mass assets: placed ZoneShapes must be normalized while their containing worlds are loaded. Zero Asset Registry rows must not be interpreted as zero ZoneShapes.

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

After the isolated native gate has already been built, `--no-build` can be used for subsequent systems-only captures.

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

The capture cross-checks the emitted shape set against the pre-existing canonical world evidence. Point rows additionally retain reflected `bReverseLaneProfile` and `InnerTurnRadius` alongside the existing point fields for real-corpus inspection. These fields are not evidence of generated lane connectivity.

The manifest explicitly records:

```text
canonical_authored_zonegraph_capture = true
generated_lane_topology = false
provenance = loaded_world_placed_actor_reflection
```

## Acceptance boundary

Current status:

1. UE 5.8 native systems compilation: accepted.
2. Real City Sample isolated systems capture: accepted.
3. Mass real-corpus invariants and row-count integrity: accepted.
4. Authored ZoneShape Asset Registry path: rejected as incomplete for placed world actors.
5. Focused authored ZoneGraph world capture: pending real City Sample execution/inspection.
6. Generated `FZoneGraphStorage` lane topology: explicitly not promoted.
7. Project-graph promotion: deferred until the authored ZoneShape capture is accepted.

City Sample derive remains intentionally deferred until the raw ZoneShape facts are accepted.