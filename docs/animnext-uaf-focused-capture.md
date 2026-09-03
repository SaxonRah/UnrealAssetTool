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

## Captured evidence

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

Excluded: RigVM execution, live UAF system/component state, current pose/value state, ticking, events/notifies, runtime injection history, compiled execution state and transient graph instances.

## Promotion rule

No animation/systems schema is designed until the real UE 5.8 capture is inspected. If UAF graph topology is ordinary RigVM model topology, the canonical implementation should reuse UnrealAssetTool's shared RigVM substrate and add only UAF-specific authored semantics above it.
