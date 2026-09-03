# Animation schema 3 real-corpus acceptance

ContentExamples on UE 5.8.2 is the accepted representative corpus for authored SkeletalMesh / PhysicsAsset topology.

## Canonical schema 3 counts

```text
animation_schema_version:                   3
mesh_physics_schema_version:                1
mesh_physics_registry_candidates:          73
skeletal_meshes:                           45
skeletal_mesh_lods:                        77
skeletal_mesh_materials:                  134
skeletal_mesh_morph_targets:              186
skeletal_mesh_clothing_assets:             11
skeletal_mesh_clothing_configs:            11
physics_assets:                            28
physics_bodies:                           263
physics_body_shapes:                      289
physics_constraints:                      221
physics_constraint_profiles:               10
physics_physical_animation_profiles:        0
physics_collision_disable_pairs:            0
```

Zero physical-animation-profile and collision-disable-pair rows are valid authored corpus facts. Those streams are supported and validated without inventing representative content.

## Exact derived schema 29 graph

`animation-schema3-accept` produced an expectation set of exactly 1,982 specialist semantic edges. After `uatool derive`, `animation-schema3-graph-verify` matched that set exactly: no missing edges, no extra edges, and every specialist edge retained `exact_semantic` quality with canonical stream provenance.

```text
exact_semantic_edges:                         1982
clothing_asset_has_config:                     11
clothing_asset_uses_physics_asset:              5
physics_asset_has_constraint_profile:          10
physics_asset_owns_body:                       263
physics_asset_owns_constraint:                 221
physics_asset_uses_preview_mesh:                28
physics_body_bound_to_bone_name:               263
physics_body_has_shape:                        289
physics_constraint_uses_bone1_name:            221
physics_constraint_uses_bone2_name:            221
skeletal_mesh_has_lod:                          77
skeletal_mesh_owns_clothing_asset:              11
skeletal_mesh_owns_morph_target:               186
skeletal_mesh_uses_lod_settings:                 3
skeletal_mesh_uses_material:                    98
skeletal_mesh_uses_physics_asset:               30
skeletal_mesh_uses_skeleton:                    45
```

The full project graph moved from 105,717 nodes / 318,582 edges before schema-29 promotion to 107,052 nodes / 320,564 edges afterward.

## Final accepted schema baseline

```text
structural=12
world=12
animation=3
vfx=1
systems=11
derived=29
capabilities=1
```

## Boundary

This acceptance is for authored asset topology. It does not claim runtime skinning, current pose state, render buffers, cloth simulation output, Chaos solver state, generated physics contacts, break history, map placement, or live component overrides.

See `animation-schema-3.md` for the canonical stream and model specification.
