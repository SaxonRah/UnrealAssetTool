# Animation schema 3: authored SkeletalMesh / PhysicsAsset topology

Animation schema 3 promotes authored SkeletalMesh and PhysicsAsset structure from generic/reflection-only visibility to a compact first-class model.

It composes a focused native UE 5.8.2 pass over the existing animation schema-2 compact-storage layer. The pass loads exact SkeletalMesh and PhysicsAsset assets only; it does not load maps or execute runtime animation/physics systems.

## Canonical streams

The schema-3 sidecar is `animation_mesh_physics_manifest.json` with mesh/physics schema version 1. It contributes:

```text
skeletal_meshes.jsonl
skeletal_mesh_lods.jsonl
skeletal_mesh_materials.jsonl
skeletal_mesh_morph_targets.jsonl
skeletal_mesh_clothing_assets.jsonl
skeletal_mesh_clothing_configs.jsonl
physics_assets.jsonl
physics_bodies.jsonl
physics_body_shapes.jsonl
physics_constraints.jsonl
physics_constraint_profiles.jsonl
physics_physical_animation_profiles.jsonl
physics_collision_disable_pairs.jsonl
```

The public `animation_manifest.json` remains authoritative and is promoted to:

```text
schema_version=3
mesh_physics_schema_version=1
```

Schema 3 retains schema-2 compact animation curve/property/pose storage. Public schema evolution does not invalidate those storage encodings.

## SkeletalMesh semantics

Normalized authored facts include:

- exact SkeletalMesh identity/class/package;
- Skeleton, PhysicsAsset, ShadowPhysicsAsset and SkeletalMeshLODSettings references;
- Asset Registry summary counts where useful;
- exact reflected source-model LOD array entries and authored build/reduction settings;
- ordered material slots with exact MaterialInterface references and authored/imported slot names;
- exact morph-target membership;
- exact clothing-asset membership;
- clothing PhysicsAsset references and owned Chaos cloth config objects/properties.

LOD rows describe authored source models. They do not claim render-resource sections, vertex/index buffers, skin-weight buffers, generated render LODs or runtime deformation state.

## PhysicsAsset semantics

Normalized authored facts include:

- exact PhysicsAsset identity/class/package and preview SkeletalMesh;
- ordered SkeletalBodySetup membership with exact `BoneName`;
- authored body physics/collision state;
- collision primitives from authored `AggGeom` arrays;
- ordered PhysicsConstraintTemplate membership;
- exact `DefaultInstance.ConstraintBone1` / `ConstraintBone2` endpoint names;
- default/profile constraint state;
- constraint profile names;
- physical-animation profile names;
- collision-disable table pairs.

Body, constraint, shape and profile identities remain explicitly owned/namespaced. A repeated bone name in two PhysicsAssets is not promoted into a global bone-object identity.

## Authored/runtime boundary

The scanner explicitly records these non-claims in its manifest:

```text
runtime_state_captured=False
render_buffers_captured=False
cloth_simulation_state_captured=False
chaos_runtime_state_captured=False
maps_loaded=False
```

It does not capture runtime skinning, current pose, cloth simulation output, Chaos solver state, generated physics bodies/constraints, collision contacts, break history, map placement or live component overrides.

## Why the broad reflection diagnostic was not promoted

The evidence phase intentionally used a broad recursive owned-object capture first. On ContentExamples it recovered the needed ownership classes but produced:

```text
45 SkeletalMeshes
28 PhysicsAssets
263 owned SkeletalBodySetup objects
221 owned PhysicsConstraintTemplate objects
186 owned MorphTarget objects
12 owned ClothingAssetCommon objects
621,484 owned-object property rows
5,914 property row-limit hits
```

That proved a generic recursive dump was useful for discovery but inappropriate as canonical storage. Schema 3 therefore normalizes only stable authored structures.

## Accepted ContentExamples normalized corpus

The successful UE 5.8.2 production pass plus offline derive/pack produced:

```text
mesh_physics_registry_candidates:    73
skeletal_meshes:                     45
skeletal_mesh_lods:                  77
skeletal_mesh_materials:             134
skeletal_mesh_morph_targets:         186
skeletal_mesh_clothing_assets:       11
skeletal_mesh_clothing_configs:      11
physics_assets:                      28
physics_bodies:                      263
physics_body_shapes:                 289
physics_constraints:                 221
physics_constraint_profiles:         10
physics_physical_animation_profiles: 0
physics_collision_disable_pairs:     0
```

The difference between 12 owned clothing objects in the broad diagnostic and 11 canonical clothing memberships is intentional: canonical counts follow the exact authored membership arrays, not a global owned-object inventory.

Zero physical-animation-profile and collision-disable-pair rows are also valid corpus facts. Those streams are supported and validated without manufacturing representative content.

## Derived schema 29

Schema 3 promotes exact cross-family relationships into the typed project graph as derived schema 29. Relations include:

- SkeletalMesh -> Skeleton / PhysicsAsset / ShadowPhysicsAsset / LODSettings;
- SkeletalMesh -> authored LOD / material / morph target / clothing asset;
- clothing asset -> PhysicsAsset / config;
- PhysicsAsset -> preview SkeletalMesh / body / constraint / profile / collision-disable pair;
- physics body -> namespaced bone name / authored collision shape;
- physics constraint -> exact namespaced bone1/bone2 names.

Every specialist edge is `exact_semantic` and carries its canonical source stream plus authored index/name evidence. Package dependencies are never used to infer these joins.

Synthetic graph nodes such as `SkeletalMesh#lod:2`, `PhysicsAsset#bone-name:pelvis`, and `Body#shape:SphylElems:0` are deliberately namespaced by their canonical owner.

## Acceptance commands

After a representative schema-3 corpus exists:

```text
uatool animation-schema3-accept <corpus>
uatool derive <corpus>
uatool animation-schema3-graph-verify <corpus>
```

The acceptance command validates the real ContentExamples topology/boundary and writes the expected exact edge set. Graph verification requires exact equality: missing or extra specialist edges fail acceptance.

## Coverage statement

SkeletalMesh / PhysicsAsset is first-class for authored animation/physics context after schema-3 canonical acceptance and schema-29 graph verification.

Remaining mesh-related work is a separate StaticMesh/rendering-topology slice; runtime animation evaluation and physics simulation remain intentional non-goals.
