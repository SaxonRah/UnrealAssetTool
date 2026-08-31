# Animation schema 2

Animation schema 2 keeps the logical animation facts from schema 1 and changes the canonical storage representation of `animation_curve_keys.jsonl`.

## Motivation

Schema 1 wrote one JSON object per curve key. Large animation projects repeat the same asset path, curve name/type, component name, and JSON field names for every key.

On the UE 5.8.2 Game Animation Sample corpus:

- logical curve keys: 811,357
- curve-component groups: 7,689
- schema-1 row-per-key stream: 330,745,180 bytes raw / 13,651,482 bytes Deflate level 3
- schema-2 columnar blocks: 30,414,449 bytes raw / 2,822,338 bytes Deflate level 3
- raw reduction: 300,330,731 bytes (~90.8%)
- compressed reduction: 10,829,144 bytes (~79.3%)

The logical row set round-trips exactly: canonical JSON-object SHA-256 before compaction and after expansion matched across all 811,357 GASP keys.

## `animation_curve_keys.jsonl`

The filename remains unchanged, but each physical JSONL row now represents one `(asset_path, curve_name, curve_type, component)` block.

Each block contains:

- `encoding`: `columnar_blocks_v1`
- `asset_path`
- `curve_name`
- `curve_type`
- `component`
- `key_count`
- `columns`
- optional `key_index_start` or `key_indices`
- optional sparse `non_finite` markers

`columns` contains the logical per-key fields:

- `time`
- `value`
- `interp_mode`
- `tangent_mode`
- `tangent_weight_mode`
- `arrive_tangent`
- `leave_tangent`
- `arrive_tangent_weight`
- `leave_tangent_weight`

A column whose value is identical for the whole block is stored once as a scalar. Otherwise it is stored as an array of `key_count` values.

Sequential key indices beginning at zero are implicit. A contiguous non-zero sequence uses `key_index_start`; an irregular sequence uses explicit `key_indices`. This keeps the representation lossless rather than assuming all future scanner output is zero-based and contiguous.

Non-finite numeric values remain represented by the original nullable numeric value plus the original marker string. Markers are stored sparsely as `{offset, field, value}` entries and are restored to the original `<field>_non_finite` logical key fields when expanded.

## Compatibility

The Unreal animation scanners still emit their existing row-per-key pass output. Canonical post-scan normalization upgrades it to public animation schema 2 without rerunning Unreal.

Running `uatool.py derive <output>` on a compatible schema-1 output:

1. validates every legacy key field;
2. groups only contiguous identical curve identities;
3. preserves explicit key indices when needed;
4. writes the compact file atomically;
5. verifies the deep-pass logical key count;
6. updates `animation_manifest.json` to schema 2 with:
   - `curve_key_encoding`
   - `curve_key_logical_count`
   - `curve_key_block_count`
   - `counts.animation_curve_keys` as the logical key count
   - `counts.animation_curve_key_blocks` as the physical block count.

The operation is idempotent.

## SQLite / queries

`uat.db` remains a disposable retrieval cache. The animation loader expands schema-2 blocks through the same logical per-key iterator used for legacy rows before inserting them into the existing `animation_curve_keys` table. Existing query and derived consumers therefore continue to see the same logical key rows.

The compact JSONL representation is authoritative; SQLite is still rebuildable from it.

## Safety policy

Compaction refuses to discard information if it encounters:

- unknown legacy key fields;
- missing required logical fields;
- mixed legacy and compact rows;
- non-contiguous repeated curve groups;
- invalid block column lengths;
- invalid explicit key indices;
- invalid sparse non-finite markers;
- a logical key count that differs from `animation_deep_manifest.json`.

No numeric quantization, rounding, sampling, key removal, or semantic inference is performed.
