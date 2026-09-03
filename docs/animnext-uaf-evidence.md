# AnimNext / Unreal Animation Framework (UAF) evidence pass

This is an evidence diagnostic, not a new animation or systems schema.

UE 5.8 exposes the forward-looking animation framework primarily as **Unreal Animation Framework (UAF)** under the Experimental UAF plugins. Many public types, headers and editor identifiers still retain `AnimNext` names. UnrealAssetTool therefore treats **UAF / AnimNext** as one naming family for discovery while refusing to infer semantics from names alone.

The command is:

```text
uatool animnext-evidence <corpus> [--report <path>]
```

It is read-only:

```text
diagnostic_only=true
semantic_promotion=false
schema_promotion=false
runtime_state_captured=false
```

It does not launch Unreal and does not change the corpus.

## Current UE 5.8 evidence targets

The diagnostic recognizes exact current asset identities where present:

```text
/Script/UAFAnimGraph.UAFAnimGraph
/Script/UAF.UAFSystem
/Script/UAF.UAFSharedVariables
/Script/UAF.UAFBlendMask
/Script/UAF.UAFBlendProfile
```

It also keeps conservative legacy `/Script/AnimNext.*` aliases visible so older or transitional projects are not silently missed. Unknown UAF/AnimNext asset classes are placed in an `other_uaf_animnext` evidence bucket rather than promoted into a guessed semantic family.

## Evidence families

The report inventories:

1. **assets** — exact UAF/AnimNext asset identity/class distribution;
2. **rigvm_graph** — overlap with existing compact RigVM object/pin/link/property/reference streams;
3. **variables_bindings** — shared-variable/default/reference/property-binding signals;
4. **traits_entrypoints** — entry-point, trait-stack/shared-data and animation-graph signals;
5. **usage** — Blueprint/world/source UAF/AnimNext component and asset usage.

High-value proof counters include:

```text
unique_uaf_anim_graph_assets
unique_uaf_system_assets
unique_uaf_shared_variables_assets
unique_uaf_blend_mask_assets
unique_uaf_blend_profile_assets
unique_uaf_animnext_assets_total
unique_uaf_animnext_component_owners
rigvm_objects_for_uaf_assets
rigvm_pins_for_uaf_assets
rigvm_links_for_uaf_assets
rigvm_properties_for_uaf_assets
rigvm_references_for_uaf_assets
exact_reference_rows
variable_binding_rows
entry_point_rows
trait_rows
usage_rows
```

## Why inspect RigVM first

Current UE 5.8 `UUAFAnimGraph`, `UUAFSystem` and `UUAFSharedVariables` are RigVM-hosting assets. UnrealAssetTool already has compact generic Control Rig/RigVM streams, so the first question is not "can we dump another graph?" but whether the existing RigVM model already captures useful UAF graph ownership/topology.

If it does, the next design should reuse that substrate and add only UAF-specific authored semantics such as entry points, shared variables/bindings, trait/static-graph data and system/component relationships. If it does not, a focused native UAF/RigVM capture is required before schema design.

## Runtime boundary

This evidence pass does not claim or capture:

- graph evaluation results;
- live UAF system/component instances;
- runtime pose/value state;
- injection request state/history;
- runtime events/notifies/ticking;
- compiled VM execution state;
- generated transient graph-instance data.

## Initial corpus order

Start with existing UE 5.8.2 corpora rather than searching for a new sample immediately:

```text
GASP / GameAnimationSample
ContentExamples
```

If neither proves nontrivial authored UAF/AnimNext assets, then select a representative Epic sample or engine plugin test corpus specifically for UAF. A schema must not be designed from API documentation alone.
