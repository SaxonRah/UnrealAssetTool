# Systems schema 5: Mass + ZoneGraph

Systems schema 5 is the first canonical Mass + ZoneGraph slice. It is intentionally evidence-first and reflection-backed.

## Evidence boundary

The City Sample focused evidence establishes that authored Mass configuration/spawner/agent state and authored ZoneShape state are recoverable. It does **not** yet establish a trustworthy reflected representation of generated `FZoneGraphStorage` lane/lane-point/lane-link topology.

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

## ZoneGraph model

`zonegraph_shapes.jsonl` records authored `ZoneShape` / `ZoneShapeComponent` state including shape type, lane profile, tags, reverse-profile state, polygon routing type and relative transform.

`zonegraph_shape_points.jsonl` records ordered reflected `FZoneShapePoint` values including position, rotation, tangent length, point type, point lane profile and lane-connection restrictions.

Transient connector caches are not promoted as authored topology.

Generated `FZoneGraphStorage` lanes, lane points and lane links are explicitly out of scope for schema 5 until a real scanner capture proves the exact serializable/reflected representation.

## Optional-system implementation

The extractor introduces no hard link dependency on MassSpawner, MassActors or ZoneGraph modules. Optional-system recognition is based on loaded class inheritance and reflected `FProperty` structure, consistent with the existing Mover and Gameplay Cameras approach.

## Isolated systems capture

For real-corpus validation, the canonical launcher provides an isolated systems-only mode:

```powershell
python scripts\uatool.py systems-capture `
    "N:\EpicVault\Projects\CitySample\CitySample.uproject" `
    --editor "E:\UE_5.8\Engine\Binaries\Win64\UnrealEditor-Win64-DebugGame-Cmd.exe"
```

The command stages/reuses the normal cross-project plugin cache, builds UnrealAssetTool when needed, launches the editor with `-UnrealAssetToolSystemsOnly`, runs only the systems scanner, requests editor exit immediately after the systems pass, validates systems schema 5, and writes a focused archive at:

```text
N:\EpicVault\Projects\CitySample\.uatool\CitySample.systems-schema5-capture.zip
```

The archive contains the systems manifest, generic systems asset/property/reference evidence, and the nine Mass/ZoneGraph schema-5 streams. It intentionally excludes world, animation, VFX, database and derived outputs.

After the isolated native gate has already been built, `--no-build` can be used for subsequent systems-only captures.

## Acceptance boundary

Schema 5 is not complete merely because synthetic Python validation passes. Acceptance requires:

1. UE 5.8 native compilation.
2. A real City Sample isolated systems capture.
3. Real-corpus invariant validation of the nine new streams.
4. Inspection of reflected Trait/config/generator/ZoneShape state for information loss.
5. Only then, project-graph promotion of exact relationships that the capture proves.

City Sample derive is intentionally not rerun until the raw systems facts are accepted.
