# Systems schema 2

Systems schema 2 extends the combined systems pass with project-owned gameplay data and the resolved Gameplay Tags project model. It preserves every schema-1 stream and adds canonical DataTable, CurveTable, PrimaryDataAsset and Gameplay Tags facts.

Current baseline:

```text
structural schema: 12
world schema:      12
animation schema:   1
vfx schema:         1
systems schema:     2
derived schema:    14
```

The systems pass still runs inside the world Editor process. Schema 2 adds a direct dependency on the standard engine `GameplayTags` runtime module so the scanner can query Unreal's merged tag dictionary and source provenance instead of approximating the project model by parsing `.ini` text.

## Compatibility

Schema 2 is an additive raw-schema revision. All schema-1 streams remain present with their existing meanings. A schema-1 `.uatool` directory must be rescanned before it can be accepted by a schema-2 build; merely rerunning `derive` cannot manufacture the new canonical raw facts.

## Canonical streams

Schema-1 streams remain:

```text
systems_assets.jsonl
systems_properties.jsonl
systems_references.jsonl
level_sequences.jsonl
movie_scene_bindings.jsonl
movie_scene_tracks.jsonl
movie_scene_sections.jsonl
movie_scene_channels.jsonl
audio_assets.jsonl
sound_cue_nodes.jsonl
metasound_nodes.jsonl
metasound_edges.jsonl
input_actions.jsonl
input_mapping_contexts.jsonl
input_mappings.jsonl
input_processors.jsonl
gameplay_data_assets.jsonl
gameplay_tags.jsonl
```

Schema 2 adds:

```text
data_table_rows.jsonl
data_table_fields.jsonl
curve_tables.jsonl
curve_table_rows.jsonl
curve_table_keys.jsonl
primary_data_assets.jsonl
gameplay_tag_settings.jsonl
gameplay_tag_sources.jsonl
gameplay_tag_dictionary.jsonl
gameplay_tag_redirects.jsonl
```

`systems_manifest.json` declares schema version 2, the complete file list and exact row counts for every stream.

---

# General DataTables

Ordinary `UDataTable`, `UCompositeDataTable`, Gameplay Tag tables and Common Input action tables share the generic row model. `MirrorDataTable` remains owned by animation schema 1 and is deliberately not duplicated here.

## `data_table_rows.jsonl`

Each emitted row contains:

```text
table_path
table_kind
row_index
row_name
row_path
row_struct
field_count
declared_field_count
truncated
```

Synthetic row identity is deterministic:

```text
<TableObjectPath>::row[<RowName>]
```

Rows are sorted lexically by authored row name before assigning `row_index`.

## `data_table_fields.jsonl`

One record is emitted for each top-level reflected row property within the structured-row budget:

```text
table_path
row_index
row_name
row_path
field_index
field_name
declaring_type
property_type
cpp_type
value
truncated
```

`value` is Unreal's own exported property text. This is intentionally loss-minimizing rather than a guessed family-specific interpretation.

### Exact row references

Every emitted field is also traversed by the same hard/soft UObject reference collector used by the systems reflection layer. References found inside structs, arrays, sets or maps are written to `systems_references.jsonl` with:

```text
owner_path = <TableObjectPath>::row[<RowName>]
owner_kind = data_table_row
root_property = <field name>
```

This makes an authored DataTable row's object references exact graph/query facts rather than package-dependency guesses.

### Bounds

DataTable row/field extraction uses the existing schema bound:

```text
structured rows per asset = 65536
```

A row records both emitted and declared field counts and carries `truncated=true` when its field set is cut by the asset budget. Individual exported field values retain the 65,536-character property-value bound.

Ordinary DataTables are `first_class` because row identity, fields and exact object references are normalized. Composite DataTables are `first_class_depth_pending`: their resolved row view is normalized, but authored parent-table composition remains primarily reflected state/references.

---

# CurveTables

`curve_tables.jsonl` records:

```text
table_path
table_kind
class_path
package_name
curve_mode
row_count
```

Supported modes are `simple`, `rich` and `empty`.

`curve_table_rows.jsonl` records deterministic lexical row identity:

```text
<TableObjectPath>::curve[<RowName>]
```

plus:

```text
curve_mode
key_count
default_value
pre_infinity_extrap
post_infinity_extrap
simple_interp_mode
```

`curve_table_keys.jsonl` records ordered key time/value pairs. Rich curves additionally preserve interpolation mode, tangent mode, tangent-weight mode, arrive/leave tangents and arrive/leave tangent weights. Simple curves preserve their interpolation mode and use explicit sentinel values for tangent-only fields.

Non-finite floating-point values are encoded as JSON `null`, never non-standard JSON tokens.

Ordinary CurveTables are `first_class`. Composite CurveTables are `first_class_depth_pending` because the resolved curves are normalized while parent-table composition remains reflection-backed.

---

# PrimaryDataAsset identity

The scanner asks the Asset Registry for classes derived from `UPrimaryDataAsset`, allowing project-specific native and discoverable generated subclasses to become candidates without loading every project asset.

`primary_data_assets.jsonl` records:

```text
asset_path
asset_kind
class_path
package_name
primary_asset_id_valid
primary_asset_type
primary_asset_name
primary_asset_id
```

The ID comes from Unreal's `GetPrimaryAssetId()` implementation on the loaded object. No ID is inferred from names or paths.

Arbitrary PrimaryDataAsset subclasses are `first_class_depth_pending`: the stable primary-asset identity plus reflected authored state/references are first-class facts, but subclass-specific gameplay meaning is not guessed. `PrimaryAssetLabel` keeps its existing recognized kind while also receiving Primary Asset identity.

---

# Gameplay Tags project model

Schema 1 normalized Gameplay Tag DataTable rows. Schema 2 adds the project-level model from `UGameplayTagsSettings` and `UGameplayTagsManager`.

This is deliberately manager-backed rather than config-file scraping. It therefore represents Unreal's merged view of native, default-list, additional config-list, restricted-list and DataTable sources.

## `gameplay_tag_settings.jsonl`

Exactly one settings row is expected. It records the loaded Gameplay Tags settings object and important project-level authored settings including:

```text
config_file_name
import_tags_from_config
warn_on_invalid_tags
fast_replication
invalid_tag_characters
gameplay_tag_table_list
restricted_config_files
num_bits_for_container_size
net_index_first_bit_segment
```

## `gameplay_tag_sources.jsonl`

Sources are grouped by Unreal source type and deterministically sorted by source name. Records contain:

```text
source_index
source_name
source_type
config_file
source_tag_list_path
source_restricted_tag_list_path
tag_count
owners
```

Normalized source-type names are:

```text
native
default_tag_list
tag_list
restricted_tag_list
data_table
```

## `gameplay_tag_dictionary.jsonl`

The dictionary comes from:

```text
UGameplayTagsManager::RequestAllGameplayTags(..., true)
```

and is sorted lexically before deterministic `tag_index` assignment. Each row preserves:

```text
tag_index
tag
parent_tag
comment
explicit
restricted
allow_non_restricted_children
depth
sources
```

Editor/source metadata is read from Unreal's Gameplay Tags manager. The dictionary is not silently capped by the generic per-asset structured-row budget: this stream represents the project model and emits the complete manager result.

## `gameplay_tag_redirects.jsonl`

Redirects preserve exact authored old/new tag names and their source:

```text
redirect_index
source_name
old_tag
new_tag
```

Duplicate source/old/new triples are removed deterministically. Redirect enumeration is likewise not silently capped.

The validator requires deterministic contiguous indices, unique nonblank dictionary tags and source references that resolve to a declared tag source.

---

# Typed project graph

Schema-2 canonical facts extend the project graph without turning every scalar value into a graph node.

Added structural relations include:

```text
DataTable -> contains_data_table_row -> data_table_row
CurveTable -> contains_curve_table_row -> curve_table_row
PrimaryDataAsset -> declares_primary_asset_id -> primary_asset_id
GameplayTagSettings -> defines_gameplay_tag_source -> gameplay_tag_source
gameplay_tag_source -> declares_gameplay_tag -> gameplay_tag
gameplay_tag -> parent_gameplay_tag -> gameplay_tag
gameplay_tag_source -> contains_gameplay_tag_redirect -> gameplay_tag_redirect
gameplay_tag_redirect -> redirects_from_gameplay_tag -> gameplay_tag
gameplay_tag_redirect -> redirects_to_gameplay_tag -> gameplay_tag
```

DataTable row object references continue to enter as `references_object` edges from `systems_references.jsonl` with `edge_quality=exact_reference`.

Individual DataTable scalar fields and CurveTable keys remain raw/queryable facts rather than project-graph nodes. This keeps bounded neighborhoods focused on relationships instead of exploding them with value cells.

Gameplay Tag settings are a project-graph root. Dictionary tags and sources are first-class semantic nodes. A redirect or hierarchy target that is mentioned but absent from the resolved dictionary remains representable with lower coverage rather than being silently dropped.

Generic Asset Registry package dependencies remain package-to-package fallback only and are never promoted into DataTable, PrimaryAsset or Gameplay Tag semantics.

---

# Validation

Python regression coverage checks:

- exact schema-2 manifest/file/count contracts;
- DataTable row and field-count reconciliation;
- CurveTable row/key reconciliation;
- Primary Asset ID invariants;
- deterministic Gameplay Tag source/dictionary/redirect indices;
- dictionary source resolution;
- graph coverage promotion for synthetic DataTable rows;
- DataTable-row exact reference joins;
- tag source, hierarchy and redirect topology;
- canonical root uniqueness.

The real UE 5.8.2 ContentExamples corpus is the first runtime/serialization gate for schema 2. Until that gate is recorded, the implementation should be treated as **draft schema-2 work**, not as corpus-validated stable coverage.
