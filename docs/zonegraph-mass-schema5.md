# ZoneGraph + Mass systems schema 5

This draft slice is evidence-driven from the UE 5.8 City Sample corpus. It does not infer Mass or ZoneGraph relationships from naming alone and does not claim generated ZoneGraph lane connectivity that the current scanner has not observed directly.

## Canonical scanner streams

Systems schema 5 adds:

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

The scanner remains reflection-first and introduces no hard MassSpawner, MassActors, or ZoneGraph module dependency. Concrete classes are detected through loaded inheritance. Full non-transient reflected state for discovered config assets, Trait objects, spawner/generator CDOs, MassAgent component templates, and ZoneShape components is also retained in the existing `systems_properties.jsonl` and `systems_references.jsonl` streams.

### Mass entity configuration

`mass_entity_configs.jsonl` records `UMassEntityConfigAsset` identity plus the reflected `FMassEntityConfig` property, config GUID, parent config reference, and ordered Trait count.

`mass_entity_traits.jsonl` preserves ordered Trait UObject identity/class. Trait object settings and UObject references remain loss-minimizing in the generic systems state streams rather than being reduced to a hand-picked set of Trait fields.

### Mass spawners and generators

`mass_spawners.jsonl` records Blueprint-derived `AMassSpawner` defaults, including the reflected Count/auto-spawn values and declared entity/generator counts.

`mass_spawner_entity_types.jsonl` preserves ordered `EntityTypes` entries, exact entity-config targets, proportions, and bounded raw reflected values.

`mass_spawner_generators.jsonl` preserves ordered `SpawnDataGenerators` entries, exact generator instance/class/Blueprint targets, proportions, and bounded raw reflected values.

`mass_spawn_generator_assets.jsonl` records Blueprint generator identity and parent class. `zonegraph_generator` is true only when the generated class actually inherits `MassEntityZoneGraphSpawnPointsGenerator`; it is not inferred from the asset name.

### Mass agent components

`mass_agent_components.jsonl` records Blueprint component templates whose loaded class inherits `MassAgentComponent`, including the reflected `FMassEntityConfig` parent and config GUID. The complete component state is also written to the generic systems property/reference streams.

### Authored ZoneGraph shapes

`zonegraph_shapes.jsonl` records authored `ZoneShape`/`ZoneShapeComponent` state observed through reflection: ordered point count, shape type, lane profile, tags, reverse-profile flag, polygon routing type, and component transform fields.

`zonegraph_shape_points.jsonl` preserves ordered reflected `FZoneShapePoint` values including position, rotation, tangent length, point type, lane profile and lane-connection restrictions, plus bounded raw text.

The slice intentionally does **not** normalize `FZoneGraphStorage`, generated lanes, lane points, or lane links yet. The City Sample evidence report found the types and source/API usage but did not demonstrate those generated arrays as accessible authored scanner state. Likewise transient ZoneShape connector caches are not promoted as authored facts.

## Validation boundary

Python validation requires:

- unique config/spawner/generator/component/shape identities;
- contiguous ordered Trait, entity-type, generator, and point indices;
- parent row counts matching their ordered child rows;
- referenced Blueprint generator assets resolving when a generator asset path is present;
- expected Mass/ZoneShape class families for normalized rows.

This schema remains draft until the UE 5.8 native module compiles and a real City Sample systems capture confirms the reflected field shapes and counts. Python schema smoke coverage alone is not considered native acceptance.
