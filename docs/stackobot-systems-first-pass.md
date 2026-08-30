# StackOBot systems schema 1 / project graph 13 first pass

Corpus: StackOBot + Fab Niagara Examples, UE 5.8.2.

The first successful combined scan produced 192 bundled files and validated the new raw systems pass plus schema-13 graph construction far enough to expose two corpus-specific normalization issues before the final gate.

## Raw systems counts from the first successful pass

```text
systems_assets             92
systems_properties       6587
systems_references        435
level_sequences             5
movie_scene_bindings       48
movie_scene_tracks         49
movie_scene_sections       46
movie_scene_channels      345
audio_assets               53
sound_cue_nodes              0
metasound_nodes            248
metasound_edges            279
input_actions               30
input_mapping_contexts       4
input_mappings               0
input_processors            23
gameplay_data_assets         0
gameplay_tags                0
```

All manifest counts matched their JSONL streams. All five LevelSequence summary counts reconciled exactly with normalized binding/track/section/channel rows. Every track section count and every section channel count matched. All 279 MetaSound edges resolved to normalized nodes in the same MetaSound asset. No normalized natural-key duplicates were found.

One generic reflected MetaSound document property reached the 65536-character bound; the dedicated normalized MetaSound node/edge streams remained complete for the observed graph topology.

## UE 5.8 Enhanced Input storage

All four InputMappingContext assets had an empty reflected top-level `Mappings` array but non-empty authored mappings under:

```text
DefaultKeyMappings.Mappings
```

The raw reference stream exposed 55 exact InputAction references across those default mappings. The scanner now prefers a populated direct `Mappings` array when available and otherwise normalizes `DefaultKeyMappings.Mappings`, preserving compatibility with both shapes.

## Project graph canonical root typing

The first schema-13 output showed some first-class asset paths represented by both their Asset Registry-derived kind and their specialist kind. Because edge insertion could propagate first-class coverage/root state to the alternate type, paths such as MetaSound Sources could have two root nodes.

The finalization layer now uses the first-class raw specialist streams as the authority for root typing, folds edge identities after canonicalization, retains all evidence, rejects whitespace-only endpoints, and rebuilds bounded neighborhoods. Validation now rejects multiple canonical roots for the same path.

## Regression

Compared with the previous StackOBot bundle, 161 of 170 pre-existing files were byte-for-byte identical. The four changed Blueprint JSONL streams retained identical row counts; their differences were confined to the already-observed loaded/FIB nondeterministic fields and generated pin IDs. The new systems pass did not change the pre-existing schema boundaries.
