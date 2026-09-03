# Authored Navigation evidence gate

This diagnostic is the first evidence step for issue #45. It does **not** define a new canonical schema and does not promote Navigation semantics merely because a class/property/source row contains a navigation-related token.

## Command

```text
uatool navigation-evidence <corpus>
```

Useful options:

```text
--focus areas
--focus modifiers
--focus links
--focus invokers
--focus system_agents
--focus bounds_usage
--no-source
--row-limit 30
--report <path>
```

The report always declares:

```text
diagnostic_only=true
semantic_promotion=false
schema_promotion=false
runtime_state_captured=false
generated_navmesh_promoted=false
```

## Evidence buckets

The diagnostic inventories current canonical evidence for:

- NavArea-derived authored classes/defaults and agent restrictions;
- `NavModifierVolume` / `NavModifierComponent` area-class state;
- `NavLinkProxy` simple/segment/smart-link topology and area policy;
- `NavigationInvokerComponent` authored generation/removal settings;
- Navigation System / supported-agent / project settings;
- `NavMeshBoundsVolume` placement and authored Blueprint/source navigation API use.

Exact actor/component class identities are counted separately from broad textual markers. Text/config/source evidence is useful for locating authored settings but is not treated as a normalized semantic relationship by itself.

## Generated Navigation boundary

`RecastNavMesh` and other generated NavMesh evidence may appear in a corpus. The diagnostic reports that evidence only to enforce the boundary:

- no generated tile/poly dump;
- no inferred polygon connectivity;
- no runtime path query results;
- no dynamic dirty-tile/rebuild history;
- no current path-following/open-list state.

The first-class target is the **authored inputs/configuration** that determine navigation behavior.

## Representative corpus decision

Run the diagnostic on real UE 5.8.2 corpora before deciding whether the eventual canonical model belongs in systems schema 11, a world-schema evolution, or a split world/systems representation.

Preferred first checks:

1. ContentExamples;
2. GameAnimationSample;
3. Cropout.

The existing world layer already owns actor/component placement and transforms. A future Navigation model should reference those authored world identities rather than duplicating transform facts.
