# Project neighborhood storage 2

Logical derived schema remains **15**. This document describes only the physical representation of `project_neighborhoods.jsonl`.

## Motivation

Schema-15 neighborhoods already removed duplicated edge semantics and retained only:

```json
{"depth":2,"direction":"out","edge_id":"pedge:..."}
```

That is semantically minimal, but large corpora still repeat the same 30-character hashed edge IDs across many bounded roots. In UE 5.8.2 GASP there are 771,983 neighborhood hops referring to only 101,581 authoritative `project_edges.jsonl` rows.

## Encoding

Storage schema 2 uses:

```text
project_neighborhood_storage_schema_version = 2
project_neighborhood_encoding = project_neighborhood_ordinals_v1
```

Each physical neighborhood keeps the existing root metadata and replaces `hops` with:

```json
{
  "encoding":"project_neighborhood_ordinals_v1",
  "depth_ends":[12,97,256],
  "hop_edges":[42,-73,105,...]
}
```

`hop_edges` contains signed **1-based ordinals** into the physical order of `project_edges.jsonl`:

- positive: traversal direction `out`
- negative: traversal direction `in`
- `abs(value) - 1`: zero-based authoritative project-edge row index

`depth_ends` contains cumulative hop end offsets for depths `1..max_depth`. The neighborhood builder emits hops in nondecreasing traversal depth, so the original depth of every hop is reconstructed exactly.

## Logical compatibility

The logical schema-15 model is unchanged. Consumers reconstruct each physical hop as:

```json
{"depth":N,"direction":"in|out","edge_id":"pedge:..."}
```

The public `uatool_project_neighborhood_compact.compact()` helper remains schema-15 compatible. Ordinal conversion happens only at the canonical `project_neighborhoods.jsonl` write boundary.

`project_graph.validation_error` receives reconstructed logical rows, so existing semantic validation is preserved. Query rendering resolves ordinals through the disposable SQLite `project_edges` insertion order, which is rebuilt from `project_edges.jsonl` in canonical row order.

## Safety conditions

Compaction refuses to write ordinal storage if:

- any referenced edge ID is absent from `project_edges.jsonl`;
- project-edge IDs are missing or duplicated;
- a neighborhood repeats an edge;
- hop directions are not `in` or `out`;
- hop depths are outside `1..max_depth`;
- hop depths are not nondecreasing;
- `edge_count` does not equal the number of selected hops.

Physical validation additionally checks signed ordinal range, uniqueness, `depth_ends` monotonicity, the final depth boundary, and exact logical expansion count.

## GASP measurement

On the validated UE 5.8.2 Game Animation Sample corpus:

- authoritative project edges: **101,581**
- neighborhoods: **3,273**
- logical hops: **771,983**
- schema-15 edge-ID storage: **56,565,703 bytes raw / 6,393,296 bytes Deflate level 3**
- ordinal prototype: **6,320,917 bytes raw / ~471,216 bytes Deflate level 3**
- logical neighborhood SHA-256 before/after expansion: `294471f1fb0dfb964ed6b3c253f950d5ecef5c3d40288de8a8a6b7087dd23195`

No edge semantics, coverage, quality, evidence or provenance is moved into neighborhood storage; those remain authoritative in `project_edges.jsonl`.
