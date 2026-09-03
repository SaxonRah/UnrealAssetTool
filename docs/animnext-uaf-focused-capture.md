# AnimNext / UAF focused UE 5.8 capture

This diagnostic is the native evidence gate after project-level evidence showed that neither GameAnimationSample nor ContentExamples contains authored UAF/AnimNext assets, while the installed UE 5.8 engine ships representative UAF plugin content.

## Representative content

The installed engine probe found 11 content assets under the enabled plugin mount roots:

- `/UAF`
- `/UAFAnimGraph`
- `/UAFSharedAssets`

The focused capture deliberately does not infer asset classes from filenames. It mounts the plugins, queries Asset Registry, loads every asset in those roots, and records the exact loaded class/hierarchy.

## Command

```text
uatool animnext-capture <project> --editor <UnrealEditor-Cmd>
```

The launcher enables:

```text
UAF,UAFAnimGraph,UAFSharedAssets
```

for the commandlet process only. It does not edit the `.uproject` descriptor.

## Accepted UE 5.8.2 evidence

The real GameAnimationSample-hosted capture against UE `5.8.2-56702186` succeeded with zero reflection safety-limit loss:

```text
registry_candidates              11
loaded_assets                    11
asset_properties                428
asset_references                 42
subobjects                      212
subobject_properties           1853
subobject_references            101
rigvm_graphs                      6
rigvm_nodes                      22
rigvm_pins                       90
rigvm_links                      19
unit_nodes                       11
truncated_properties              0
property_depth_limit_hits         0
property_row_limit_hits           0
container_element_limit_hits      0
```

The three first-class authored/runtime UAF assets in the shipped corpus are:

```text
/UAF/Templates/BasicCharacter/AG_DefaultCharacter.AG_DefaultCharacter
    /Script/UAFAnimGraph.UAFAnimGraph

/UAF/Templates/BasicCharacter/S_DefaultCharacter.S_DefaultCharacter
    /Script/UAF.UAFSystem

/UAFAnimGraph/Internal/S_SingleGraph.S_SingleGraph
    /Script/UAF.UAFSystem
```

The remaining eight mounted assets are supporting editor/template/browser/workspace/redirector/texture content and are not promoted merely because they live under a UAF mount root.

The exact loaded inheritance chain proves that both `UAFAnimGraph` and `UAFSystem` reuse `UAFSharedVariables` -> `UAFRigVMAsset` -> `RigVMHost`.

### RigVM reuse is proven

The authored editor models are ordinary `URigVMGraph` topology. The six captured graphs use these exact schemas:

```text
3  /Script/UAFUncookedOnly.UAFRigVMAssetSchema
2  /Script/UAFUncookedOnly.AnimNextEventGraphSchema
1  /Script/UAFAnimGraphUncookedOnly.AnimNextAnimationGraphSchema
```

The 22 nodes are exactly:

```text
11  /Script/RigVMDeveloper.RigVMUnitNode
10  /Script/RigVMDeveloper.RigVMVariableNode
 1  /Script/RigVMDeveloper.RigVMDispatchNode
```

The 11 unit nodes expose concrete UAF structs such as:

```text
/Script/UAF.RigUnit_AnimNextInitializeEvent
/Script/UAF.RigUnit_AnimNextPrePhysicsEvent
/Script/UAF.RigUnit_MakeReferencePoseFromSkeletalMeshComponent
/Script/UAFAnimGraph.RigUnit_AnimNextRunAnimationGraph_v2
/Script/UAF.RigUnit_AnimNextWriteSkeletalMeshComponentPose
/Script/UAFAnimGraph.RigUnit_AnimNextGraphRoot
```

All 19 links resolve between emitted RigVM pins. Therefore the canonical implementation must reuse UnrealAssetTool's shared RigVM substrate rather than introduce a second generic UAF graph representation.

### UAF-specific authored semantics are visible

The focused reflection surface proves reusable specialist facts above RigVM:

- `AnimNextAnimationGraphEntry` and `AnimNextEventGraphEntry` objects map named UAF entries to exact RigVM/EdGraph objects;
- six `AnimNextVariableEntry` objects expose GUID, parameter name, access, type/value-type object, default value and binding data;
- RigVM variable nodes expose their referenced UAF variable through the hidden `Variable` pin, so variable use is exact rather than name-inferred;
- `UAFAnimGraph.EntryPoints` exposes the authored runtime entry point and `RootTraitHandle` (`Root` in the representative graph);
- `UAFSystem` exposes authored `Components`, `RequiredPlugins`, shared variable/default property-bag state, `RigVM` and `EditorData`;
- the representative systems prove the recurring component structs `UAFRigVMComponent`, `AnimNextSkeletalMeshComponentReferenceComponent` and `AnimNextModuleInjectionComponent`.

The basic-character `S_DefaultCharacter` also proves a direct authored graph default referencing `AG_DefaultCharacter`, while the internal `S_SingleGraph` proves the same system/variable/event model without requiring an authored graph asset reference.

## Captured evidence streams

- exact asset identity, class and inheritance chain;
- recursive non-transient authored/default property state;
- hard/soft object references;
- recursive subobject inventory, including UAF uncooked/editor objects;
- nested `URigVMGraph` identity and ownership;
- exact RigVM nodes, unit `UScriptStruct` identities, pins/defaults/directions and links.

The commandlet intentionally uses no UAF C++ headers. UAF asset/subobject semantics are discovered through reflection. The shared RigVMDeveloper model API is used only for editor-side graph topology after nested `URigVMGraph` objects are proven.

## Boundary

```text
diagnostic_only=true
semantic_promotion=false
schema_promotion=false
runtime_state_captured=false
```

Excluded: RigVM execution, live UAF system/component state, current pose/value state, ticking, event execution, runtime injection history, compiled execution state and transient graph instances.

## Promotion decision

The focused gate is accepted.

The next canonical layer should add UAF-specific authored asset/entry/variable/component/entry-point semantics while reusing the existing RigVM graph substrate. Candidate identity must come from exact UAF classes, not mount-root or filename heuristics. Supporting UAF editor assets remain generic unless independently promoted.

No runtime execution or live animation state is implied by this acceptance.
