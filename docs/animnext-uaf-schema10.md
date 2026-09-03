# AnimNext / UAF systems schema 10

Systems schema 10 promotes the accepted UE 5.8.2 AnimNext / Unreal Animation Framework evidence into canonical authored facts. Derived schema 26 promotes only exact relationships proven by those facts.

The slice deliberately models authored/default UAF content rather than runtime animation execution. UAF's editor-side RigVM graphs reuse UnrealAssetTool's existing typed RigVM project-graph substrate instead of introducing a second generic graph model.

## Canonical systems streams

```text
uaf_assets.jsonl
uaf_entries.jsonl
uaf_variables.jsonl
uaf_components.jsonl
uaf_entry_points.jsonl
uaf_rigvm_graphs.jsonl
uaf_rigvm_nodes.jsonl
uaf_rigvm_pins.jsonl
uaf_rigvm_links.jsonl
uaf_variable_usages.jsonl
```

The systems manifest is schema 10. Structural schema 12 is intentionally unchanged because its compact `rigvm_*` streams are Blueprint-scoped and retain `blueprint_path` as part of that contract.

## Exact first-class identity

First-class UAF identity is proven only from the loaded UObject class:

```text
/Script/UAF.UAFSystem
/Script/UAFAnimGraph.UAFAnimGraph
```

The acceptance capture enables only:

```text
UAF
UAFAnimGraph
UAFSharedAssets
```

and admits those installed representative plugin roots through `-UAFEngineContent`. It does not use global `-IncludeEngine`.

The representative roots are deliberately enumerated before exact loaded-class promotion. This matches the accepted focused evidence gate: every asset under the three explicit roots may be inspected, but only an object whose loaded class is exactly `UAFSystem` or `UAFAnimGraph` is promoted as a first-class UAF asset. Supporting editor/template/browser/workspace/redirector/texture content remains unpromoted.

Normal project-wide `/Game` discovery remains narrow and uses Asset Registry class identity as a cheap candidate filter before exact loaded-class verification.

## Authored semantic model

For each exact UAF asset, schema 10 records:

- exact asset class and kind;
- editor data and RigVM ownership paths;
- authored UAF entries, including event and animation graph entries;
- variable declarations with exact GUID/name/access/type/default/binding data;
- authored component structs and values;
- authored runtime entry points;
- every nested editor-side `URigVMGraph`;
- exact RigVM nodes, pins, links and unit structs;
- exact RigVM variable-node -> UAF variable declaration resolution.

The canonical entry classes proven by the UE 5.8.2 corpus include:

```text
/Script/UAFAnimGraphUncookedOnly.AnimNextAnimationGraphEntry
/Script/UAFUncookedOnly.AnimNextEventGraphEntry
```

Variable declarations are represented by `AnimNextVariableEntry` editor objects. Variable uses are resolved from the RigVM variable node's hidden `Variable` pin against the exact declaration set rather than inferred from neighboring names.

## RigVM reuse

UAF graphs map into the existing typed project-graph kinds:

```text
rigvm_graph
rigvm_node
rigvm_pin
```

Schema 10 therefore does not create a parallel generic `uaf_graph_node` abstraction. UAF-specific ownership and semantics are represented by dedicated UAF relations around the shared RigVM substrate.

## Derived schema 26 relations

The accepted exact semantic relations are:

```text
has_rigvm_node
has_rigvm_pin
has_uaf_component
has_uaf_entry
has_uaf_entry_point
has_uaf_rigvm_graph
has_uaf_variable
instance_of_rigvm_node_class
instance_of_rigvm_unit_struct
instance_of_uaf_component_struct
rigvm_connects
uaf_entry_uses_rigvm_graph
uaf_rigvm_node_uses_variable
uaf_variable_uses_type
```

Every specialist UAF edge is emitted as `exact_semantic` with canonical stream evidence. The verifier requires exact set equality against expectations generated from schema-10 facts.

## Runtime boundary

Schema 10 does not capture or simulate:

- RigVM execution;
- current animation pose/value state;
- UAF system ticking;
- runtime event execution;
- live component/system mutation;
- injection history;
- compiled execution state;
- transient graph instances.

`runtime_state_captured` is false in both acceptance and graph-verification manifests.

## Accepted GameAnimationSample UE 5.8.2 result

The real schema-10 capture ran against UE `5.8.2-56702186` with GameAnimationSample as the host project.

Canonical counts:

```text
uaf_candidates             11
uaf_scoped_candidates      11
uaf_loaded_assets           3
uaf_assets                  3
uaf_entries                 3
uaf_variables               6
uaf_components              7
uaf_entry_points            1
uaf_rigvm_graphs            6
uaf_rigvm_nodes            22
uaf_rigvm_pins             90
uaf_rigvm_links            19
uaf_variable_usages        10
uaf_truncated_values        0
```

The three promoted first-class assets remain the same identities proven by the focused gate:

```text
/UAF/Templates/BasicCharacter/AG_DefaultCharacter.AG_DefaultCharacter
    /Script/UAFAnimGraph.UAFAnimGraph

/UAF/Templates/BasicCharacter/S_DefaultCharacter.S_DefaultCharacter
    /Script/UAF.UAFSystem

/UAFAnimGraph/Internal/S_SingleGraph.S_SingleGraph
    /Script/UAF.UAFSystem
```

The six editor-side RigVM graphs contain exactly 22 nodes, 90 pins and 19 links, matching the accepted focused topology. Schema 10 additionally normalizes 3 entries, 6 variable declarations, 7 authored components, 1 runtime entry point and 10 exact variable-node uses.

No UAF value truncation was accepted.

## Accepted derived graph

`systems-schema10-accept` generated exactly 213 expected specialist edges for derived schema 26:

```text
has_rigvm_node                    22
has_rigvm_pin                     90
has_uaf_component                  7
has_uaf_entry                      3
has_uaf_entry_point                1
has_uaf_rigvm_graph                6
has_uaf_variable                   6
instance_of_rigvm_node_class      22
instance_of_rigvm_unit_struct     11
instance_of_uaf_component_struct   7
rigvm_connects                    19
uaf_entry_uses_rigvm_graph         3
uaf_rigvm_node_uses_variable      10
uaf_variable_uses_type             6
                                  ---
TOTAL                            213
```

A canonical derive over the partial systems-only acceptance corpus completed with:

```text
project_nodes          2049
project_edges          2830
project_neighborhoods   347
```

`uaf-graph-verify` then confirmed exact set equality for all 213 UAF specialist edges under derived schema 26. No extra or missing specialist edge was accepted.

## Acceptance commands

The real-corpus publication sequence is:

```text
uatool uaf-systems-capture <project> --editor <UnrealEditor-Cmd>
uatool systems-schema10-accept <project>
uatool derive <acceptance-corpus>
uatool uaf-graph-verify <project>
```

The acceptance corpus is intentionally marked `partial_corpus=true`: it is a focused systems-schema gate and does not claim that structural/world/animation/VFX passes were rerun as part of this acceptance.

## Maintained capability status

After the accepted GameAnimationSample gate:

```text
AnimNext / UAF first_class
```

The capability contract remains corpus-aware. A corpus must contain the schema-10 canonical UAF streams to report the family as available; the tool-level contract does not manufacture corpus coverage.