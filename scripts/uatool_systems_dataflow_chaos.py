#!/usr/bin/env python3
"""Systems schema 9: authored Dataflow graphs and Geometry Collection behavior state."""
from __future__ import annotations

import collections
import json
from pathlib import Path

DATAFLOW_CHAOS_FILES = (
    "dataflow_graphs.jsonl",
    "dataflow_nodes.jsonl",
    "dataflow_pins.jsonl",
    "dataflow_edges.jsonl",
    "dataflow_asset_properties.jsonl",
    "dataflow_asset_references.jsonl",
    "dataflow_node_properties.jsonl",
    "dataflow_node_references.jsonl",
    "geometry_collections.jsonl",
    "geometry_collection_properties.jsonl",
    "geometry_collection_references.jsonl",
)
DATAFLOW_CLASS = "/Script/DataflowEngine.Dataflow"
GEOMETRY_COLLECTION_CLASS = "/Script/GeometryCollectionEngine.GeometryCollection"
GEOMETRY_COLLECTION_BEHAVIOR_ROOTS = frozenset({
    "EnableClustering", "ClusterGroupIndex", "MaxClusterLevel",
    "DamageModel", "DamageThreshold", "bUseSizeSpecificDamageThreshold",
    "bUseMaterialDamageModifiers", "PerClusterOnlyDamageThreshold", "DamagePropagationData",
    "ClusterConnectionType", "ConnectionGraphBoundsFilteringMargin",
    "Mass", "MinimumMassClamp", "bMassAsDensity", "bDensityFromPhysicsMaterial", "PhysicsMaterial",
    "MaximumSleepTime", "SlowMovingVelocityThreshold", "bSlowMovingAsSleeping",
    "bRemoveOnMaxSleep", "RemovalDuration", "bScaleOnRemoval", "bAutomaticCrumblePartialClusters",
    "bOptimizeConvexes", "SizeSpecificData", "DataflowAsset", "DataflowInstance", "Overrides",
})

_SQL = """
CREATE TABLE dataflow_graphs(
 asset_path TEXT PRIMARY KEY,asset_class TEXT NOT NULL,node_count INTEGER NOT NULL,edge_count INTEGER NOT NULL,
 asset_property_count INTEGER NOT NULL,asset_reference_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE dataflow_nodes(
 asset_path TEXT NOT NULL,node_guid TEXT NOT NULL,node_name TEXT NOT NULL,node_struct TEXT NOT NULL,
 input_count INTEGER NOT NULL,output_count INTEGER NOT NULL,property_count INTEGER NOT NULL,reference_count INTEGER NOT NULL,
 json TEXT NOT NULL,PRIMARY KEY(asset_path,node_guid));
CREATE INDEX dataflow_nodes_struct_idx ON dataflow_nodes(node_struct,asset_path);
CREATE TABLE dataflow_pins(
 asset_path TEXT NOT NULL,node_guid TEXT NOT NULL,pin_guid TEXT NOT NULL,pin_name TEXT NOT NULL,direction TEXT NOT NULL,
 pin_index INTEGER NOT NULL,original_type TEXT NOT NULL,property_name TEXT NOT NULL,property_type TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(asset_path,pin_guid));
CREATE INDEX dataflow_pins_node_idx ON dataflow_pins(asset_path,node_guid,direction,pin_index);
CREATE TABLE dataflow_edges(
 asset_path TEXT NOT NULL,source_node_guid TEXT NOT NULL,source_pin_guid TEXT NOT NULL,
 target_node_guid TEXT NOT NULL,target_pin_guid TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(asset_path,source_pin_guid,target_pin_guid));
CREATE TABLE dataflow_asset_properties(
 source_path TEXT NOT NULL,owner_id TEXT NOT NULL,owner_kind TEXT NOT NULL,owner_type TEXT NOT NULL,
 property_index INTEGER NOT NULL,declaring_type TEXT NOT NULL,root_property TEXT NOT NULL,property_name TEXT NOT NULL,
 property_path TEXT NOT NULL,property_type TEXT NOT NULL,cpp_type TEXT NOT NULL,container_kind TEXT NOT NULL,
 value TEXT NOT NULL,default_value TEXT NOT NULL,default_present INTEGER NOT NULL,differs_from_default INTEGER NOT NULL,
 truncated INTEGER NOT NULL,dataflow_input INTEGER NOT NULL,dataflow_output INTEGER NOT NULL,
 dataflow_passthrough INTEGER NOT NULL,dataflow_intrinsic INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(source_path,property_index));
CREATE TABLE dataflow_asset_references(
 source_path TEXT NOT NULL,owner_id TEXT NOT NULL,owner_kind TEXT NOT NULL,owner_type TEXT NOT NULL,
 root_property TEXT NOT NULL,property_path TEXT NOT NULL,reference_kind TEXT NOT NULL,target_path TEXT NOT NULL,
 target_class TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX dataflow_asset_refs_source_idx ON dataflow_asset_references(source_path,property_path,target_path);
CREATE TABLE dataflow_node_properties(
 source_path TEXT NOT NULL,owner_id TEXT NOT NULL,owner_kind TEXT NOT NULL,owner_type TEXT NOT NULL,
 property_index INTEGER NOT NULL,declaring_type TEXT NOT NULL,root_property TEXT NOT NULL,property_name TEXT NOT NULL,
 property_path TEXT NOT NULL,property_type TEXT NOT NULL,cpp_type TEXT NOT NULL,container_kind TEXT NOT NULL,
 value TEXT NOT NULL,default_value TEXT NOT NULL,default_present INTEGER NOT NULL,differs_from_default INTEGER NOT NULL,
 truncated INTEGER NOT NULL,dataflow_input INTEGER NOT NULL,dataflow_output INTEGER NOT NULL,
 dataflow_passthrough INTEGER NOT NULL,dataflow_intrinsic INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(source_path,owner_id,property_index));
CREATE INDEX dataflow_node_props_root_idx ON dataflow_node_properties(owner_type,root_property,source_path);
CREATE TABLE dataflow_node_references(
 source_path TEXT NOT NULL,owner_id TEXT NOT NULL,owner_kind TEXT NOT NULL,owner_type TEXT NOT NULL,
 root_property TEXT NOT NULL,property_path TEXT NOT NULL,reference_kind TEXT NOT NULL,target_path TEXT NOT NULL,
 target_class TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX dataflow_node_refs_owner_idx ON dataflow_node_references(source_path,owner_id,target_path);
CREATE TABLE geometry_collections(
 asset_path TEXT PRIMARY KEY,asset_class TEXT NOT NULL,dataflow_asset TEXT NOT NULL,dataflow_terminal TEXT NOT NULL,
 property_count INTEGER NOT NULL,reference_count INTEGER NOT NULL,geometry_source_in_behavior_schema INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE geometry_collection_properties(
 source_path TEXT NOT NULL,owner_id TEXT NOT NULL,owner_kind TEXT NOT NULL,owner_type TEXT NOT NULL,
 property_index INTEGER NOT NULL,declaring_type TEXT NOT NULL,root_property TEXT NOT NULL,property_name TEXT NOT NULL,
 property_path TEXT NOT NULL,property_type TEXT NOT NULL,cpp_type TEXT NOT NULL,container_kind TEXT NOT NULL,
 value TEXT NOT NULL,default_value TEXT NOT NULL,default_present INTEGER NOT NULL,differs_from_default INTEGER NOT NULL,
 truncated INTEGER NOT NULL,dataflow_input INTEGER NOT NULL,dataflow_output INTEGER NOT NULL,
 dataflow_passthrough INTEGER NOT NULL,dataflow_intrinsic INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(source_path,property_index));
CREATE INDEX geometry_collection_props_root_idx ON geometry_collection_properties(root_property,source_path);
CREATE TABLE geometry_collection_references(
 source_path TEXT NOT NULL,owner_id TEXT NOT NULL,owner_kind TEXT NOT NULL,owner_type TEXT NOT NULL,
 root_property TEXT NOT NULL,property_path TEXT NOT NULL,reference_kind TEXT NOT NULL,target_path TEXT NOT NULL,
 target_class TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX geometry_collection_refs_source_idx ON geometry_collection_references(source_path,root_property,target_path);
"""


def _j(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def _read_rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield row


def _read_manifest(output: Path) -> dict:
    path = Path(output) / "systems_manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid systems_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("systems_manifest.json root is not an object")
    return value


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def _unique(items: list[dict], fields: tuple[str, ...], label: str) -> str | None:
    seen = set()
    for row in items:
        key = tuple(str(row.get(field, "") or "") for field in fields)
        if any(not value for value in key):
            return f"{label} has blank identity: {key}"
        if key in seen:
            return f"{label} has duplicate identity: {key}"
        seen.add(key)
    return None


def _check_property_rows(items: list[dict], owners: set[tuple[str, str]], kind: str, label: str,
                         allowed_roots: frozenset[str] | None = None):
    by_owner: dict[tuple[str, str], list[int]] = collections.defaultdict(list)
    counts = collections.Counter()
    for row in items:
        source = str(row.get("source_path", "") or "")
        owner = str(row.get("owner_id", "") or "")
        key = (source, owner)
        if key not in owners:
            return f"{label} owner does not resolve: {key}", counts
        if str(row.get("owner_kind", "") or "") != kind:
            return f"{label} owner kind mismatch: {key}", counts
        root = str(row.get("root_property", "") or "")
        path = str(row.get("property_path", "") or "")
        if not root or not path:
            return f"{label} has blank property identity: {key}", counts
        if allowed_roots is not None and root not in allowed_roots:
            return f"{label} leaked non-behavior root into canonical schema: {source}::{root}", counts
        if root == "GeometrySource":
            return f"{label} leaked excluded construction provenance GeometrySource: {source}", counts
        if bool(row.get("truncated", False)):
            return f"{label} canonical property is truncated: {source}::{path}", counts
        by_owner[key].append(int(row.get("property_index", -1)))
        counts[key] += 1
    for key, indices in by_owner.items():
        if sorted(indices) != list(range(len(indices))):
            return f"{label} property indices are not contiguous for {key}", counts
    return None, counts


def _check_references(items: list[dict], owners: set[tuple[str, str]], kind: str, label: str,
                      allowed_roots: frozenset[str] | None = None):
    counts = collections.Counter()
    seen = set()
    for row in items:
        source = str(row.get("source_path", "") or "")
        owner = str(row.get("owner_id", "") or "")
        key = (source, owner)
        if key not in owners:
            return f"{label} owner does not resolve: {key}", counts
        if str(row.get("owner_kind", "") or "") != kind:
            return f"{label} owner kind mismatch: {key}", counts
        root = str(row.get("root_property", "") or "")
        path = str(row.get("property_path", "") or "")
        target = str(row.get("target_path", "") or "")
        if not root or not path or not target:
            return f"{label} has blank reference identity: {key}", counts
        if allowed_roots is not None and root not in allowed_roots:
            return f"{label} leaked non-behavior reference root: {source}::{root}", counts
        identity = (source, owner, path, target)
        if identity in seen:
            return f"{label} has duplicate reference: {identity}", counts
        seen.add(identity)
        counts[key] += 1
    return None, counts


def validation_error(output: Path, rows=None) -> str | None:
    output = Path(output)
    rows = rows or _read_rows
    try:
        manifest = _read_manifest(output)
    except RuntimeError as exc:
        return str(exc)

    manifest_version = int(manifest.get("schema_version", 0) or 0)
    present = [name for name in DATAFLOW_CHAOS_FILES if (output / name).is_file()]
    if manifest_version < 9:
        # This installer is part of the public composition, so historical schema
        # fixtures must remain valid when they contain no schema-9 specialist
        # files. A partial specialist surface on an older manifest is never OK.
        if present:
            return f"Dataflow/Chaos canonical streams require systems schema >=9, got {manifest_version}"
        return None
    missing = [name for name in DATAFLOW_CHAOS_FILES if not (output / name).is_file()]
    if missing:
        return f"systems schema 9 is missing Dataflow/Chaos canonical file: {missing[0]}"

    graphs = list(rows(output / "dataflow_graphs.jsonl"))
    nodes = list(rows(output / "dataflow_nodes.jsonl"))
    pins = list(rows(output / "dataflow_pins.jsonl"))
    edges = list(rows(output / "dataflow_edges.jsonl"))
    asset_props = list(rows(output / "dataflow_asset_properties.jsonl"))
    asset_refs = list(rows(output / "dataflow_asset_references.jsonl"))
    node_props = list(rows(output / "dataflow_node_properties.jsonl"))
    node_refs = list(rows(output / "dataflow_node_references.jsonl"))
    geometry_collections = list(rows(output / "geometry_collections.jsonl"))
    gc_props = list(rows(output / "geometry_collection_properties.jsonl"))
    gc_refs = list(rows(output / "geometry_collection_references.jsonl"))

    error = _unique(graphs, ("asset_path",), "Dataflow graph")
    if error:
        return error
    graph_paths = {str(row.get("asset_path", "") or "") for row in graphs}
    for row in graphs:
        if str(row.get("asset_class", "") or "") != DATAFLOW_CLASS:
            return f"Dataflow graph has unexpected asset class: {row.get('asset_path')} -> {row.get('asset_class')}"
        if min(int(row.get("node_count", -1)), int(row.get("edge_count", -1)),
               int(row.get("asset_property_count", -1)), int(row.get("asset_reference_count", -1))) < 0:
            return f"Dataflow graph has negative count: {row.get('asset_path')}"

    error = _unique(nodes, ("asset_path", "node_guid"), "Dataflow node")
    if error:
        return error
    node_keys = set()
    node_rows = {}
    nodes_per_graph = collections.Counter()
    for row in nodes:
        asset = str(row.get("asset_path", "") or "")
        guid = str(row.get("node_guid", "") or "")
        if asset not in graph_paths:
            return f"Dataflow node graph does not resolve: {asset}::{guid}"
        if not str(row.get("node_struct", "") or ""):
            return f"Dataflow node has blank concrete script struct: {asset}::{guid}"
        if min(int(row.get("input_count", -1)), int(row.get("output_count", -1)),
               int(row.get("property_count", -1)), int(row.get("reference_count", -1))) < 0:
            return f"Dataflow node has negative child count: {asset}::{guid}"
        key = (asset, guid)
        node_keys.add(key)
        node_rows[key] = row
        nodes_per_graph[asset] += 1

    error = _unique(pins, ("asset_path", "pin_guid"), "Dataflow pin")
    if error:
        return error
    pin_rows = {}
    pin_indices: dict[tuple[str, str, str], list[int]] = collections.defaultdict(list)
    pins_by_node_direction = collections.Counter()
    for row in pins:
        asset = str(row.get("asset_path", "") or "")
        node = str(row.get("node_guid", "") or "")
        pin = str(row.get("pin_guid", "") or "")
        direction = str(row.get("direction", "") or "")
        if (asset, node) not in node_keys:
            return f"Dataflow pin node does not resolve: {asset}::{node}::{pin}"
        if direction not in {"input", "output"}:
            return f"Dataflow pin has invalid direction: {asset}::{pin} -> {direction}"
        pin_rows[(asset, pin)] = row
        key = (asset, node, direction)
        pin_indices[key].append(int(row.get("pin_index", -1)))
        pins_by_node_direction[key] += 1
    for key, indices in pin_indices.items():
        if sorted(indices) != list(range(len(indices))):
            return f"Dataflow pin indices are not contiguous for {key}"
    for (asset, node), row in node_rows.items():
        if pins_by_node_direction[(asset, node, "input")] != int(row.get("input_count", 0) or 0):
            return f"Dataflow node input count mismatch: {asset}::{node}"
        if pins_by_node_direction[(asset, node, "output")] != int(row.get("output_count", 0) or 0):
            return f"Dataflow node output count mismatch: {asset}::{node}"

    error = _unique(edges, ("asset_path", "source_pin_guid", "target_pin_guid"), "Dataflow edge")
    if error:
        return error
    edges_per_graph = collections.Counter()
    for row in edges:
        asset = str(row.get("asset_path", "") or "")
        source_node = str(row.get("source_node_guid", "") or "")
        source_pin = str(row.get("source_pin_guid", "") or "")
        target_node = str(row.get("target_node_guid", "") or "")
        target_pin = str(row.get("target_pin_guid", "") or "")
        source = pin_rows.get((asset, source_pin))
        target = pin_rows.get((asset, target_pin))
        if not source or not target:
            return f"Dataflow edge endpoint does not resolve: {asset}::{source_pin}->{target_pin}"
        if str(source.get("node_guid", "") or "") != source_node or str(target.get("node_guid", "") or "") != target_node:
            return f"Dataflow edge node/pin ownership mismatch: {asset}::{source_pin}->{target_pin}"
        if source.get("direction") != "output" or target.get("direction") != "input":
            return f"Dataflow edge direction mismatch: {asset}::{source_pin}->{target_pin}"
        edges_per_graph[asset] += 1
    for row in graphs:
        asset = str(row.get("asset_path", "") or "")
        if nodes_per_graph[asset] != int(row.get("node_count", 0) or 0):
            return f"Dataflow graph node count mismatch: {asset}"
        if edges_per_graph[asset] != int(row.get("edge_count", 0) or 0):
            return f"Dataflow graph edge count mismatch: {asset}"

    asset_owners = {(asset, asset) for asset in graph_paths}
    error, asset_prop_counts = _check_property_rows(asset_props, asset_owners, "dataflow_asset", "Dataflow asset property")
    if error:
        return error
    error, asset_ref_counts = _check_references(asset_refs, asset_owners, "dataflow_asset", "Dataflow asset reference")
    if error:
        return error
    error, node_prop_counts = _check_property_rows(node_props, node_keys, "dataflow_node", "Dataflow node property")
    if error:
        return error
    error, node_ref_counts = _check_references(node_refs, node_keys, "dataflow_node", "Dataflow node reference")
    if error:
        return error
    for row in graphs:
        asset = str(row.get("asset_path", "") or "")
        if asset_prop_counts[(asset, asset)] != int(row.get("asset_property_count", 0) or 0):
            return f"Dataflow asset property count mismatch: {asset}"
        if asset_ref_counts[(asset, asset)] != int(row.get("asset_reference_count", 0) or 0):
            return f"Dataflow asset reference count mismatch: {asset}"
    for key, row in node_rows.items():
        if node_prop_counts[key] != int(row.get("property_count", 0) or 0):
            return f"Dataflow node property count mismatch: {key}"
        if node_ref_counts[key] != int(row.get("reference_count", 0) or 0):
            return f"Dataflow node reference count mismatch: {key}"

    error = _unique(geometry_collections, ("asset_path",), "Geometry Collection")
    if error:
        return error
    gc_paths = {str(row.get("asset_path", "") or "") for row in geometry_collections}
    gc_owners = {(asset, asset) for asset in gc_paths}
    for row in geometry_collections:
        asset = str(row.get("asset_path", "") or "")
        if str(row.get("asset_class", "") or "") != GEOMETRY_COLLECTION_CLASS:
            return f"Geometry Collection has unexpected class: {asset} -> {row.get('asset_class')}"
        if bool(row.get("geometry_source_in_behavior_schema", True)):
            return f"Geometry Collection incorrectly includes GeometrySource in behavior schema: {asset}"
        if min(int(row.get("property_count", -1)), int(row.get("reference_count", -1))) < 0:
            return f"Geometry Collection has negative child count: {asset}"
    error, gc_prop_counts = _check_property_rows(
        gc_props, gc_owners, "geometry_collection", "Geometry Collection property", GEOMETRY_COLLECTION_BEHAVIOR_ROOTS)
    if error:
        return error
    error, gc_ref_counts = _check_references(
        gc_refs, gc_owners, "geometry_collection", "Geometry Collection reference", GEOMETRY_COLLECTION_BEHAVIOR_ROOTS)
    if error:
        return error
    gc_dataflow_refs: dict[str, list[str]] = collections.defaultdict(list)
    for row in gc_refs:
        if str(row.get("root_property", "") or "") == "DataflowAsset":
            gc_dataflow_refs[str(row.get("source_path", "") or "")].append(str(row.get("target_path", "") or ""))
    for row in geometry_collections:
        asset = str(row.get("asset_path", "") or "")
        if gc_prop_counts[(asset, asset)] != int(row.get("property_count", 0) or 0):
            return f"Geometry Collection property count mismatch: {asset}"
        if gc_ref_counts[(asset, asset)] != int(row.get("reference_count", 0) or 0):
            return f"Geometry Collection reference count mismatch: {asset}"
        dataflow_asset = str(row.get("dataflow_asset", "") or "")
        refs = gc_dataflow_refs.get(asset, [])
        if dataflow_asset and refs != [dataflow_asset]:
            return f"Geometry Collection DataflowAsset specialized/reference mismatch: {asset} -> {dataflow_asset} refs={refs}"
        if not dataflow_asset and refs:
            return f"Geometry Collection has DataflowAsset reference while specialized value is null: {asset}"

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    physical = {
        "dataflow_assets": len(graphs),
        "geometry_collections": len(geometry_collections),
        "dataflow_graphs": len(graphs),
        "dataflow_nodes": len(nodes),
        "dataflow_pins": len(pins),
        "dataflow_edges": len(edges),
        "dataflow_asset_properties": len(asset_props),
        "dataflow_asset_references": len(asset_refs),
        "dataflow_node_properties": len(node_props),
        "dataflow_node_references": len(node_refs),
        "geometry_collection_properties": len(gc_props),
        "geometry_collection_references": len(gc_refs),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            return f"Dataflow/Chaos manifest count mismatch for {key}: manifest={counts.get(key)} actual={actual}"
    for key in ("dataflow_chaos_truncated_properties", "dataflow_chaos_property_row_limit_hits"):
        if key not in counts:
            return f"Dataflow/Chaos manifest missing loss counter: {key}"
        if int(counts.get(key, 0) or 0) != 0:
            return f"Dataflow/Chaos canonical capture has nonzero loss counter {key}={counts.get(key)}"
    return None


def _property_values(row: dict) -> tuple:
    return (
        row.get("source_path", ""), row.get("owner_id", ""), row.get("owner_kind", ""), row.get("owner_type", ""),
        int(row.get("property_index", 0) or 0), row.get("declaring_type", ""), row.get("root_property", ""),
        row.get("property_name", ""), row.get("property_path", ""), row.get("property_type", ""), row.get("cpp_type", ""),
        row.get("container_kind", ""), row.get("value", ""), row.get("default_value", ""),
        int(bool(row.get("default_present", False))), int(bool(row.get("differs_from_default", False))),
        int(bool(row.get("truncated", False))), int(bool(row.get("dataflow_input", False))),
        int(bool(row.get("dataflow_output", False))), int(bool(row.get("dataflow_passthrough", False))),
        int(bool(row.get("dataflow_intrinsic", False))), _j(row),
    )


def _reference_values(row: dict) -> tuple:
    return (
        row.get("source_path", ""), row.get("owner_id", ""), row.get("owner_kind", ""), row.get("owner_type", ""),
        row.get("root_property", ""), row.get("property_path", ""), row.get("reference_kind", ""),
        row.get("target_path", ""), row.get("target_class", ""), _j(row),
    )


def load_database(conn, output: Path, rows=None) -> None:
    output = Path(output)
    rows = rows or _read_rows
    # Older accepted corpora may be loaded through the current public facade.
    # Their schema-9 tables remain empty rather than making them unreadable.
    manifest = _read_manifest(output)
    if int(manifest.get("schema_version", 0) or 0) < 9:
        return
    for r in rows(output / "dataflow_graphs.jsonl"):
        conn.execute("INSERT OR REPLACE INTO dataflow_graphs VALUES(?,?,?,?,?,?,?)", (
            r.get("asset_path", ""), r.get("asset_class", ""), int(r.get("node_count", 0) or 0),
            int(r.get("edge_count", 0) or 0), int(r.get("asset_property_count", 0) or 0),
            int(r.get("asset_reference_count", 0) or 0), _j(r)))
    for r in rows(output / "dataflow_nodes.jsonl"):
        conn.execute("INSERT OR REPLACE INTO dataflow_nodes VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("asset_path", ""), r.get("node_guid", ""), r.get("node_name", ""), r.get("node_struct", ""),
            int(r.get("input_count", 0) or 0), int(r.get("output_count", 0) or 0), int(r.get("property_count", 0) or 0),
            int(r.get("reference_count", 0) or 0), _j(r)))
    for r in rows(output / "dataflow_pins.jsonl"):
        conn.execute("INSERT OR REPLACE INTO dataflow_pins VALUES(?,?,?,?,?,?,?,?,?,?)", (
            r.get("asset_path", ""), r.get("node_guid", ""), r.get("pin_guid", ""), r.get("pin_name", ""),
            r.get("direction", ""), int(r.get("pin_index", 0) or 0), r.get("original_type", ""),
            r.get("property_name", ""), r.get("property_type", ""), _j(r)))
    for r in rows(output / "dataflow_edges.jsonl"):
        conn.execute("INSERT OR REPLACE INTO dataflow_edges VALUES(?,?,?,?,?,?)", (
            r.get("asset_path", ""), r.get("source_node_guid", ""), r.get("source_pin_guid", ""),
            r.get("target_node_guid", ""), r.get("target_pin_guid", ""), _j(r)))
    for filename, table in (
        ("dataflow_asset_properties.jsonl", "dataflow_asset_properties"),
        ("dataflow_node_properties.jsonl", "dataflow_node_properties"),
        ("geometry_collection_properties.jsonl", "geometry_collection_properties"),
    ):
        for r in rows(output / filename):
            conn.execute(f"INSERT OR REPLACE INTO {table} VALUES(" + ",".join("?" * 22) + ")", _property_values(r))
    for filename, table in (
        ("dataflow_asset_references.jsonl", "dataflow_asset_references"),
        ("dataflow_node_references.jsonl", "dataflow_node_references"),
        ("geometry_collection_references.jsonl", "geometry_collection_references"),
    ):
        for r in rows(output / filename):
            conn.execute(f"INSERT INTO {table} VALUES(" + ",".join("?" * 10) + ")", _reference_values(r))
    for r in rows(output / "geometry_collections.jsonl"):
        conn.execute("INSERT OR REPLACE INTO geometry_collections VALUES(?,?,?,?,?,?,?,?)", (
            r.get("asset_path", ""), r.get("asset_class", ""), r.get("dataflow_asset", ""), r.get("dataflow_terminal", ""),
            int(r.get("property_count", 0) or 0), int(r.get("reference_count", 0) or 0),
            int(bool(r.get("geometry_source_in_behavior_schema", False))), _j(r)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='dataflow_graphs'").fetchone():
        return
    print("\n[Dataflow graphs]")
    print_rows(conn.execute(
        "SELECT asset_path,node_count,edge_count,asset_property_count FROM dataflow_graphs WHERE asset_path LIKE ? LIMIT ?",
        (pattern, limit)), ("asset", "nodes", "edges", "asset_properties"))
    print("\n[Dataflow node types]")
    print_rows(conn.execute(
        """SELECT node_struct,COUNT(*) AS count FROM dataflow_nodes
           WHERE asset_path LIKE ? OR node_struct LIKE ? GROUP BY node_struct ORDER BY count DESC,node_struct LIMIT ?""",
        (pattern, pattern, limit)), ("node_struct", "count"))
    print("\n[Geometry Collections]")
    print_rows(conn.execute(
        """SELECT asset_path,dataflow_asset,dataflow_terminal,property_count,reference_count FROM geometry_collections
           WHERE asset_path LIKE ? OR dataflow_asset LIKE ? OR dataflow_terminal LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)), ("asset", "dataflow_asset", "terminal", "properties", "references"))


def install(systems_module) -> None:
    if getattr(systems_module, "_dataflow_chaos_schema_installed", False):
        return
    original_create_schema = systems_module.create_schema
    original_validation_error = systems_module.validation_error
    original_load_database = systems_module.load_database
    original_query = systems_module.query

    systems_module.SYSTEMS_SCHEMA_VERSION = 9
    systems_module.JSONL_FILES = tuple(dict.fromkeys((*systems_module.JSONL_FILES, *DATAFLOW_CHAOS_FILES)))
    systems_module.RAW_FILES = ("systems_manifest.json", *systems_module.JSONL_FILES)

    def create_schema_wrapper(conn):
        original_create_schema(conn)
        create_schema(conn)

    def validation_wrapper(output):
        error = original_validation_error(output)
        if error:
            return error
        return validation_error(Path(output), systems_module._rows)

    def load_database_wrapper(conn, output, rows=None):
        original_load_database(conn, output, rows)
        load_database(conn, Path(output), rows or systems_module._rows)

    def query_wrapper(conn, print_rows, pattern, limit):
        original_query(conn, print_rows, pattern, limit)
        query(conn, print_rows, pattern, limit)

    systems_module.create_schema = create_schema_wrapper
    systems_module.validation_error = validation_wrapper
    systems_module.load_database = load_database_wrapper
    systems_module.query = query_wrapper
    systems_module._dataflow_chaos_schema_installed = True
