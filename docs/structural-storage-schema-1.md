# Structural storage schema 1

Structural storage schema 1 is a representation-only companion to logical structural schema 12. It does not change structural facts or the world schema-12 structural baseline.

## Blueprint node properties

`blueprint_node_properties.jsonl` is stored as one physical block per node using encoding:

`blueprint_node_property_blocks_v1`

Each block contains:

- `node_id`
- `property_count`
- `columns`

The following row fields are not repeated in the block because they are authoritative on the referenced `blueprint_nodes.jsonl` row and are reconstructed exactly when logical rows are read:

- `blueprint_path`
- `graph_name`
- `node_class`

The remaining property fields are stored as columns. A column that is identical for the whole node block is stored once as a scalar; otherwise it is stored as an array of `property_count` values.

Logical consumers, derived graph generation, and SQLite packing continue to receive the original per-property row model through the canonical row readers.

## Manifest

`manifest.json` keeps `schema_version: 12` and adds:

- `structural_storage_schema_version: 1`
- `blueprint_node_property_encoding`
- `blueprint_node_property_logical_count`
- `blueprint_node_property_block_count`
- `counts.blueprint_node_properties` as the logical property count
- `counts.blueprint_node_property_blocks` as the physical block count

Keeping storage versioning separate avoids changing the world schema-12 structural baseline for a storage-only transformation.

## Safety

Compaction is atomic and refuses the rewrite if:

- the legacy property field set is incomplete or contains unknown fields;
- a property references a missing Blueprint node;
- repeated `blueprint_path`, `graph_name`, or `node_class` differs from the authoritative Blueprint node row;
- a node's property rows are non-contiguous;
- the logical property count differs from the structural scanner manifest;
- compact blocks contain duplicate node identities, invalid columns, or missing node references.

No property values are removed, truncated, normalized, rounded, or semantically inferred.

Compatible schema-12 scans can be upgraded with `uatool.py derive` without rerunning Unreal.
