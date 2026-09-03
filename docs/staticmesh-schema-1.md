# StaticMesh mesh schema 1

StaticMesh authored topology is an independently versioned **mesh schema**, not a structural-schema bump.

Current target baseline after acceptance:

```text
structural=12
world=12
animation=3
mesh=1
vfx=1
systems=11
derived=30
capabilities=1
```

Structural schema 12 continues to own package/source/Blueprint/AI/PCG/material structural facts. Mesh schema 1 owns authored geometry/build/collision facts that do not belong to Blueprint storage, world placement or animation.

## Evidence gate

The existing ContentExamples corpus contained 307 exact `/Script/Engine.StaticMesh` assets, many thousands of exact consumer references and StaticMeshComponent instances, but no mesh-owned authored topology. GASP independently showed the same boundary on 12 meshes. Asset Registry tags therefore remained supporting evidence only.

A focused UE 5.8.2 commandlet loaded exact project StaticMeshes without maps and produced the bounded authored capture:

```text
static_meshes=307
source_models=413
materials=389
sockets=9
body_setups=307
collision_shapes=297
load_failures=0
```

The recovered ContentExamples report also established:

```text
registry_multi_lod_assets=29
registry_nanite_enabled_assets=77
registry_collision_primitive_assets=167
material_count_mismatches=0
collision_prim_count_mismatches=0
lod_count_mismatches=32
```

The 32 LOD mismatches are not topology failures. In every reported case the Asset Registry `LODs` summary was `0` while the loaded asset contained one real authored `SourceModels[0]`. Mesh schema 1 therefore treats the loaded `SourceModels` array as canonical LOD truth and retains Registry counts only as provenance/supporting summaries.

## Canonical streams

`staticmesh_manifest.json` advertises mesh schema 1 and these durable streams:

- `static_meshes.jsonl`
- `static_mesh_lods.jsonl`
- `static_mesh_material_slots.jsonl`
- `static_mesh_sockets.jsonl`
- `static_mesh_body_setups.jsonl`
- `static_mesh_collision_shapes.jsonl`

The focused `staticmesh-native-capture` directory remains diagnostic evidence and is not the public corpus contract.

### `static_meshes.jsonl`

One exact `/Script/Engine.StaticMesh` root per asset. The row contains canonical counts derived from loaded owned arrays, BodySetup and optional complex-collision-mesh identity, exact Nanite enabled state, LOD/lightmap summary fields, and a compact `authored_settings` object.

The selected authored settings are folded into the root rather than emitted as thousands of row-per-property records. They include:

- `NaniteSettings`
- `SectionInfoMap`
- `OriginalSectionInfoMap`
- `LightMapCoordinateIndex`
- `LightMapResolution`
- `MinLOD`
- `LODGroup`
- CPU-access/ray-tracing/physical-material-mask/distance-field flags
- distance-field self-shadow bias
- `ComplexCollisionMesh`
- automatic LOD-screen-size and uniform-sampling flags
- positive/negative bounds extensions

Section-info maps remain exact authored node data. Mesh schema 1 does not infer section topology from render data and does not invent section-to-material relationships beyond what the authored map itself proves.

### `static_mesh_lods.jsonl`

One ordered row per loaded `SourceModels[index]` containing:

- owner StaticMesh and exact LOD index;
- authored screen-size value;
- source import filename when retained by Unreal;
- import-with-base-mesh flag;
- exact reflected `FMeshBuildSettings` fields;
- exact reflected `FMeshReductionSettings` fields.

`StaticMeshDescriptionBulkData`, cached triangle/vertex counters and render buffers are deliberately not promoted as mesh-semantic topology.

### `static_mesh_material_slots.jsonl`

One ordered authored `StaticMaterials[index]` row with exact material reference, class, slot name, imported slot name and UV-channel data. World/component `OverrideMaterials` remain world/Blueprint instance facts and are not merged into asset ownership.

### `static_mesh_sockets.jsonl`

One exact owned `UStaticMeshSocket` row preserving array index, UObject path/class, socket name, relative transform/scale and tag.

### `static_mesh_body_setups.jsonl`

One exact owned BodySetup row when present. It preserves authored collision trace policy, default body-instance export, physical material, build scale, walkable-slope override, double-sided geometry and the never-needs-cooked-collision flag.

### `static_mesh_collision_shapes.jsonl`

One authored simple-collision primitive per `AggGeom` element. ContentExamples proves four shape families:

```text
ConvexElems 276
BoxElems     15
SphereElems   5
SphylElems    1
```

Rows preserve shape family/index, reflected struct type and fields. Cooked collision and runtime Chaos state are not captured.

## Derived schema 30

Derived schema 30 adds only exact relationships with canonical endpoints:

- `static_mesh_has_lod`
- `static_mesh_has_material_slot`
- `material_slot_uses_material`
- `static_mesh_owns_socket`
- `static_mesh_has_body_setup`
- `body_setup_has_collision_shape`
- `static_mesh_uses_complex_collision_mesh` when the exact authored reference is non-empty

Synthetic identities are owner-namespaced:

```text
<mesh>#lod:<index>
<mesh>#material-slot:<index>
<body-setup>#shape:<shape-type>:<index>
```

Sockets and BodySetups use their real UObject paths.

Nanite/build/reduction/lightmap/section settings are data on first-class nodes, not graph relationships. The project graph does not treat Asset Registry package dependencies as equivalent to these exact semantic edges.

## Explicit non-claims

Mesh schema 1 captures authored state only:

```text
runtime_state_captured=False
render_buffers_captured=False
nanite_resources_captured=False
runtime_physics_state_captured=False
maps_loaded=False
```

It does not capture or infer:

- vertex/index/render buffers;
- generated Nanite clusters, pages or streaming resources;
- cooked collision meshes/data;
- runtime Chaos body state or contacts;
- runtime component transforms/material overrides;
- generated HLOD/foliage/landscape runtime output;
- section topology reconstructed from render resources.

## Acceptance lifecycle

The focused capture can be promoted offline:

```text
uatool staticmesh-schema1-promote <corpus>
uatool staticmesh-schema1-accept <corpus>
uatool derive <corpus>
uatool staticmesh-graph-verify <corpus>
uatool pack <corpus>
```

Acceptance snapshots the exact expected specialist edge set before derive. Graph verification requires exact set equality, `exact_semantic` quality and the correct canonical evidence stream for every relation.

After this promotion/graph gate is accepted on ContentExamples, the same canonical normalization can be wired into the normal scan lifecycle so future scans produce mesh schema 1 directly rather than requiring a separate focused-capture promotion step.
