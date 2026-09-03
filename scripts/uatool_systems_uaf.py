#!/usr/bin/env python3
"""Systems schema 10: authored Unreal Animation Framework / AnimNext semantics."""
from __future__ import annotations

import collections
import json
from pathlib import Path

UAF_FILES = (
    "uaf_assets.jsonl",
    "uaf_entries.jsonl",
    "uaf_variables.jsonl",
    "uaf_components.jsonl",
    "uaf_entry_points.jsonl",
    "uaf_rigvm_graphs.jsonl",
    "uaf_rigvm_nodes.jsonl",
    "uaf_rigvm_pins.jsonl",
    "uaf_rigvm_links.jsonl",
    "uaf_variable_usages.jsonl",
)
UAF_SYSTEM_CLASS = "/Script/UAF.UAFSystem"
UAF_ANIM_GRAPH_CLASS = "/Script/UAFAnimGraph.UAFAnimGraph"
UAF_CLASSES = frozenset({UAF_SYSTEM_CLASS, UAF_ANIM_GRAPH_CLASS})
UAF_ENTRY_CLASSES = frozenset({
    "/Script/UAFAnimGraphUncookedOnly.AnimNextAnimationGraphEntry",
    "/Script/UAFUncookedOnly.AnimNextEventGraphEntry",
})

_SQL = """
CREATE TABLE uaf_assets(
 asset_path TEXT PRIMARY KEY,asset_class TEXT NOT NULL,asset_kind TEXT NOT NULL,rigvm_path TEXT NOT NULL,
 editor_data_path TEXT NOT NULL,required_plugins TEXT NOT NULL,default_entry_point TEXT NOT NULL,
 entry_count INTEGER NOT NULL,variable_count INTEGER NOT NULL,component_count INTEGER NOT NULL,
 entry_point_count INTEGER NOT NULL,rigvm_graph_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE uaf_entries(
 asset_path TEXT NOT NULL,entry_path TEXT PRIMARY KEY,entry_class TEXT NOT NULL,entry_kind TEXT NOT NULL,
 graph_name TEXT NOT NULL,access TEXT NOT NULL,graph_path TEXT NOT NULL,ed_graph_path TEXT NOT NULL,
 hidden_in_outliner TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX uaf_entries_asset_idx ON uaf_entries(asset_path,entry_kind,graph_name);
CREATE TABLE uaf_variables(
 asset_path TEXT NOT NULL,variable_path TEXT PRIMARY KEY,variable_guid TEXT NOT NULL,variable_name TEXT NOT NULL,
 access TEXT NOT NULL,type_value TEXT NOT NULL,type_container TEXT NOT NULL,type_object TEXT NOT NULL,
 default_value TEXT NOT NULL,binding TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX uaf_variables_asset_idx ON uaf_variables(asset_path,variable_name);
CREATE TABLE uaf_components(
 asset_path TEXT NOT NULL,component_index INTEGER NOT NULL,component_struct TEXT NOT NULL,component_type TEXT NOT NULL,
 value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(asset_path,component_index));
CREATE TABLE uaf_entry_points(
 asset_path TEXT NOT NULL,entry_point_index INTEGER NOT NULL,entry_point_name TEXT NOT NULL,
 packed_root_trait_handle TEXT NOT NULL,json TEXT NOT NULL,PRIMARY KEY(asset_path,entry_point_index));
CREATE TABLE uaf_rigvm_graphs(
 asset_path TEXT NOT NULL,graph_path TEXT PRIMARY KEY,graph_name TEXT NOT NULL,graph_class TEXT NOT NULL,
 schema_class TEXT NOT NULL,execute_context_struct TEXT NOT NULL,node_count INTEGER NOT NULL,link_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE uaf_rigvm_nodes(
 asset_path TEXT NOT NULL,graph_path TEXT NOT NULL,node_path TEXT NOT NULL,node_name TEXT NOT NULL,node_class TEXT NOT NULL,
 node_index INTEGER NOT NULL,top_level_pin_count INTEGER NOT NULL,operation TEXT NOT NULL,unit_script_struct TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(asset_path,graph_path,node_path));
CREATE TABLE uaf_rigvm_pins(
 asset_path TEXT NOT NULL,graph_path TEXT NOT NULL,node_path TEXT NOT NULL,pin_path TEXT NOT NULL,pin_name TEXT NOT NULL,
 direction TEXT NOT NULL,depth INTEGER NOT NULL,pin_index INTEGER NOT NULL,cpp_type TEXT NOT NULL,cpp_type_object TEXT NOT NULL,
 default_value TEXT NOT NULL,original_default_value TEXT NOT NULL,hidden INTEGER NOT NULL,subpin_count INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(asset_path,graph_path,pin_path));
CREATE TABLE uaf_rigvm_links(
 asset_path TEXT NOT NULL,graph_path TEXT NOT NULL,link_path TEXT NOT NULL,source_node_path TEXT NOT NULL,
 source_pin_path TEXT NOT NULL,target_node_path TEXT NOT NULL,target_pin_path TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(asset_path,graph_path,source_pin_path,target_pin_path));
CREATE TABLE uaf_variable_usages(
 asset_path TEXT NOT NULL,graph_path TEXT NOT NULL,node_path TEXT NOT NULL,variable_name TEXT NOT NULL,
 variable_guid TEXT NOT NULL,variable_path TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(asset_path,graph_path,node_path));
"""


def _j(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, separators=(",", ":"))


def _rows(path: Path):
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


def _manifest(output: Path) -> dict:
    try:
        value = json.loads((Path(output) / "systems_manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid systems_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("systems_manifest.json root is not an object")
    return value


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def _unique(rows: list[dict], fields: tuple[str, ...], label: str) -> str | None:
    seen = set()
    for row in rows:
        key = tuple(str(row.get(field, "") or "") for field in fields)
        if any(not item for item in key):
            return f"{label} has blank identity: {key}"
        if key in seen:
            return f"{label} has duplicate identity: {key}"
        seen.add(key)
    return None


def validation_error(output: Path, rows=None) -> str | None:
    output = Path(output)
    rows = rows or _rows
    try:
        manifest = _manifest(output)
    except RuntimeError as exc:
        return str(exc)
    version = int(manifest.get("schema_version", 0) or 0)
    present = [name for name in UAF_FILES if (output / name).is_file()]
    if version < 10:
        if present:
            return f"UAF canonical streams require systems schema >=10, got {version}"
        return None
    missing = [name for name in UAF_FILES if not (output / name).is_file()]
    if missing:
        return f"systems schema 10 is missing UAF canonical file: {missing[0]}"

    assets = list(rows(output / "uaf_assets.jsonl"))
    entries = list(rows(output / "uaf_entries.jsonl"))
    variables = list(rows(output / "uaf_variables.jsonl"))
    components = list(rows(output / "uaf_components.jsonl"))
    entry_points = list(rows(output / "uaf_entry_points.jsonl"))
    graphs = list(rows(output / "uaf_rigvm_graphs.jsonl"))
    nodes = list(rows(output / "uaf_rigvm_nodes.jsonl"))
    pins = list(rows(output / "uaf_rigvm_pins.jsonl"))
    links = list(rows(output / "uaf_rigvm_links.jsonl"))
    usages = list(rows(output / "uaf_variable_usages.jsonl"))

    error = _unique(assets, ("asset_path",), "UAF asset")
    if error: return error
    asset_rows = {str(r.get("asset_path", "") or ""): r for r in assets}
    for path, row in asset_rows.items():
        cls = str(row.get("asset_class", "") or "")
        if cls not in UAF_CLASSES:
            return f"UAF asset has unexpected class: {path} -> {cls}"
        expected_kind = "system" if cls == UAF_SYSTEM_CLASS else "animation_graph"
        if row.get("asset_kind") != expected_kind:
            return f"UAF asset kind/class mismatch: {path}"
        for field in ("entry_count", "variable_count", "component_count", "entry_point_count", "rigvm_graph_count"):
            if int(row.get(field, -1)) < 0:
                return f"UAF asset has negative count {field}: {path}"

    error = _unique(entries, ("entry_path",), "UAF entry")
    if error: return error
    entry_counts = collections.Counter()
    for row in entries:
        asset = str(row.get("asset_path", "") or "")
        if asset not in asset_rows:
            return f"UAF entry owner does not resolve: {asset}"
        if str(row.get("entry_class", "") or "") not in UAF_ENTRY_CLASSES:
            return f"UAF entry has unexpected class: {row.get('entry_path')}"
        if not str(row.get("graph_path", "") or "") or not str(row.get("ed_graph_path", "") or ""):
            return f"UAF entry lacks exact graph ownership: {row.get('entry_path')}"
        entry_counts[asset] += 1

    error = _unique(variables, ("variable_path",), "UAF variable")
    if error: return error
    variable_counts = collections.Counter()
    variables_by_path = {}
    variables_by_name = collections.defaultdict(list)
    for row in variables:
        asset = str(row.get("asset_path", "") or "")
        path = str(row.get("variable_path", "") or "")
        guid = str(row.get("variable_guid", "") or "")
        name = str(row.get("variable_name", "") or "")
        if asset not in asset_rows:
            return f"UAF variable owner does not resolve: {asset}"
        if not guid or not name:
            return f"UAF variable has blank GUID/name: {path}"
        variables_by_path[path] = row
        variables_by_name[(asset, name)].append(row)
        variable_counts[asset] += 1

    error = _unique(components, ("asset_path", "component_index"), "UAF component")
    if error: return error
    component_counts = collections.Counter()
    component_indices = collections.defaultdict(list)
    for row in components:
        asset = str(row.get("asset_path", "") or "")
        if asset not in asset_rows:
            return f"UAF component owner does not resolve: {asset}"
        if not str(row.get("component_struct", "") or ""):
            return f"UAF component has blank struct: {asset}"
        if bool(row.get("truncated", False)):
            return f"UAF component value is truncated: {asset} index={row.get('component_index')}"
        index = int(row.get("component_index", -1))
        component_indices[asset].append(index)
        component_counts[asset] += 1
    for asset, indices in component_indices.items():
        if sorted(indices) != list(range(len(indices))):
            return f"UAF component indices are not contiguous: {asset}"

    error = _unique(entry_points, ("asset_path", "entry_point_index"), "UAF entry point")
    if error: return error
    entry_point_counts = collections.Counter()
    for row in entry_points:
        asset = str(row.get("asset_path", "") or "")
        if asset not in asset_rows:
            return f"UAF entry-point owner does not resolve: {asset}"
        if asset_rows[asset].get("asset_class") != UAF_ANIM_GRAPH_CLASS:
            return f"UAF entry point is owned by non-animation-graph asset: {asset}"
        if not str(row.get("entry_point_name", "") or ""):
            return f"UAF entry point has blank name: {asset}"
        entry_point_counts[asset] += 1

    error = _unique(graphs, ("graph_path",), "UAF RigVM graph")
    if error: return error
    graph_rows = {str(r.get("graph_path", "") or ""): r for r in graphs}
    graph_counts = collections.Counter(str(r.get("asset_path", "") or "") for r in graphs)
    for graph, row in graph_rows.items():
        if str(row.get("asset_path", "") or "") not in asset_rows:
            return f"UAF RigVM graph owner does not resolve: {graph}"
        if not str(row.get("schema_class", "") or ""):
            return f"UAF RigVM graph has blank schema: {graph}"
        if min(int(row.get("node_count", -1)), int(row.get("link_count", -1))) < 0:
            return f"UAF RigVM graph has negative child count: {graph}"

    error = _unique(nodes, ("asset_path", "graph_path", "node_path"), "UAF RigVM node")
    if error: return error
    node_rows = {}
    nodes_per_graph = collections.Counter()
    for row in nodes:
        asset = str(row.get("asset_path", "") or "")
        graph = str(row.get("graph_path", "") or "")
        node = str(row.get("node_path", "") or "")
        if graph not in graph_rows or str(graph_rows[graph].get("asset_path", "") or "") != asset:
            return f"UAF RigVM node graph does not resolve: {asset}::{graph}::{node}"
        node_rows[(asset, graph, node)] = row
        nodes_per_graph[graph] += 1

    error = _unique(pins, ("asset_path", "graph_path", "pin_path"), "UAF RigVM pin")
    if error: return error
    pin_rows = {}
    top_pins_per_node = collections.Counter()
    for row in pins:
        asset = str(row.get("asset_path", "") or "")
        graph = str(row.get("graph_path", "") or "")
        node = str(row.get("node_path", "") or "")
        pin = str(row.get("pin_path", "") or "")
        if (asset, graph, node) not in node_rows:
            return f"UAF RigVM pin node does not resolve: {asset}::{graph}::{node}::{pin}"
        if str(row.get("direction", "") or "") not in {"Input", "Output", "IO", "Hidden", "Visible"}:
            return f"UAF RigVM pin has unexpected direction: {pin} -> {row.get('direction')}"
        pin_rows[(asset, graph, pin)] = row
        if int(row.get("depth", -1)) == 0:
            top_pins_per_node[(asset, graph, node)] += 1
    for key, row in node_rows.items():
        if top_pins_per_node[key] != int(row.get("top_level_pin_count", 0) or 0):
            return f"UAF RigVM node top-level pin count mismatch: {key}"

    error = _unique(links, ("asset_path", "graph_path", "source_pin_path", "target_pin_path"), "UAF RigVM link")
    if error: return error
    links_per_graph = collections.Counter()
    for row in links:
        asset = str(row.get("asset_path", "") or "")
        graph = str(row.get("graph_path", "") or "")
        source_pin = str(row.get("source_pin_path", "") or "")
        target_pin = str(row.get("target_pin_path", "") or "")
        source = pin_rows.get((asset, graph, source_pin))
        target = pin_rows.get((asset, graph, target_pin))
        if not source or not target:
            return f"UAF RigVM link has unresolved pin endpoint: {asset}::{source_pin}->{target_pin}"
        if str(source.get("node_path", "") or "") != str(row.get("source_node_path", "") or "") or \
           str(target.get("node_path", "") or "") != str(row.get("target_node_path", "") or ""):
            return f"UAF RigVM link node/pin ownership mismatch: {asset}::{source_pin}->{target_pin}"
        links_per_graph[graph] += 1
    for graph, row in graph_rows.items():
        if nodes_per_graph[graph] != int(row.get("node_count", 0) or 0):
            return f"UAF RigVM graph node count mismatch: {graph}"
        if links_per_graph[graph] != int(row.get("link_count", 0) or 0):
            return f"UAF RigVM graph link count mismatch: {graph}"

    error = _unique(usages, ("asset_path", "graph_path", "node_path"), "UAF variable usage")
    if error: return error
    for row in usages:
        asset = str(row.get("asset_path", "") or "")
        graph = str(row.get("graph_path", "") or "")
        node = str(row.get("node_path", "") or "")
        variable_path = str(row.get("variable_path", "") or "")
        if (asset, graph, node) not in node_rows:
            return f"UAF variable usage node does not resolve: {asset}::{graph}::{node}"
        variable = variables_by_path.get(variable_path)
        if not variable or str(variable.get("asset_path", "") or "") != asset:
            return f"UAF variable usage declaration does not resolve: {variable_path}"
        if str(variable.get("variable_guid", "") or "") != str(row.get("variable_guid", "") or "") or \
           str(variable.get("variable_name", "") or "") != str(row.get("variable_name", "") or ""):
            return f"UAF variable usage/declaration mismatch: {asset}::{node}"
        if len(variables_by_name[(asset, str(row.get("variable_name", "") or ""))]) != 1:
            return f"UAF variable usage is not uniquely resolvable by authored name: {asset}::{row.get('variable_name')}"

    for asset, row in asset_rows.items():
        expected = {
            "entry_count": entry_counts[asset],
            "variable_count": variable_counts[asset],
            "component_count": component_counts[asset],
            "entry_point_count": entry_point_counts[asset],
            "rigvm_graph_count": graph_counts[asset],
        }
        for field, actual in expected.items():
            if int(row.get(field, -1)) != actual:
                return f"UAF asset child count mismatch {asset}::{field}: row={row.get(field)} actual={actual}"

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    physical = {
        "uaf_assets": len(assets), "uaf_entries": len(entries), "uaf_variables": len(variables),
        "uaf_components": len(components), "uaf_entry_points": len(entry_points),
        "uaf_rigvm_graphs": len(graphs), "uaf_rigvm_nodes": len(nodes), "uaf_rigvm_pins": len(pins),
        "uaf_rigvm_links": len(links), "uaf_variable_usages": len(usages),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            return f"UAF manifest count mismatch for {key}: manifest={counts.get(key)} actual={actual}"
    if "uaf_truncated_values" not in counts:
        return "UAF manifest missing uaf_truncated_values loss counter"
    if int(counts.get("uaf_truncated_values", 0) or 0):
        return f"UAF canonical capture has truncated values: {counts.get('uaf_truncated_values')}"
    return None


def load_database(conn, output: Path, rows=None) -> None:
    output = Path(output)
    rows = rows or _rows
    if int(_manifest(output).get("schema_version", 0) or 0) < 10:
        return
    specs = {
        "uaf_assets.jsonl": ("uaf_assets", ("asset_path","asset_class","asset_kind","rigvm_path","editor_data_path","required_plugins","default_entry_point","entry_count","variable_count","component_count","entry_point_count","rigvm_graph_count")),
        "uaf_entries.jsonl": ("uaf_entries", ("asset_path","entry_path","entry_class","entry_kind","graph_name","access","graph_path","ed_graph_path","hidden_in_outliner")),
        "uaf_variables.jsonl": ("uaf_variables", ("asset_path","variable_path","variable_guid","variable_name","access","type_value","type_container","type_object","default_value","binding")),
        "uaf_components.jsonl": ("uaf_components", ("asset_path","component_index","component_struct","component_type","value","truncated")),
        "uaf_entry_points.jsonl": ("uaf_entry_points", ("asset_path","entry_point_index","entry_point_name","packed_root_trait_handle")),
        "uaf_rigvm_graphs.jsonl": ("uaf_rigvm_graphs", ("asset_path","graph_path","graph_name","graph_class","schema_class","execute_context_struct","node_count","link_count")),
        "uaf_rigvm_nodes.jsonl": ("uaf_rigvm_nodes", ("asset_path","graph_path","node_path","node_name","node_class","node_index","top_level_pin_count","operation","unit_script_struct")),
        "uaf_rigvm_pins.jsonl": ("uaf_rigvm_pins", ("asset_path","graph_path","node_path","pin_path","pin_name","direction","depth","pin_index","cpp_type","cpp_type_object","default_value","original_default_value","hidden","subpin_count")),
        "uaf_rigvm_links.jsonl": ("uaf_rigvm_links", ("asset_path","graph_path","link_path","source_node_path","source_pin_path","target_node_path","target_pin_path")),
        "uaf_variable_usages.jsonl": ("uaf_variable_usages", ("asset_path","graph_path","node_path","variable_name","variable_guid","variable_path")),
    }
    integer_fields = {"entry_count","variable_count","component_count","entry_point_count","rigvm_graph_count","component_index","truncated","entry_point_index","node_count","link_count","node_index","top_level_pin_count","depth","pin_index","hidden","subpin_count"}
    for filename, (table, fields) in specs.items():
        placeholders = ",".join("?" for _ in range(len(fields)+1))
        for row in rows(output / filename):
            values = []
            for field in fields:
                value = row.get(field, "")
                if field in integer_fields:
                    value = int(bool(value)) if field in {"truncated","hidden"} else int(value or 0)
                values.append(value)
            conn.execute(f"INSERT OR REPLACE INTO {table} VALUES({placeholders})", (*values, _j(row)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='uaf_assets'").fetchone():
        return
    print("\n[UAF assets]")
    print_rows(conn.execute(
        "SELECT asset_path,asset_kind,entry_count,variable_count,component_count,rigvm_graph_count FROM uaf_assets WHERE asset_path LIKE ? LIMIT ?",
        (pattern, limit)), ("asset","kind","entries","variables","components","graphs"))
    print("\n[UAF variables]")
    print_rows(conn.execute(
        "SELECT asset_path,variable_name,access,type_object FROM uaf_variables WHERE asset_path LIKE ? OR variable_name LIKE ? OR type_object LIKE ? LIMIT ?",
        (pattern, pattern, pattern, limit)), ("asset","variable","access","type"))
    print("\n[UAF entries]")
    print_rows(conn.execute(
        "SELECT asset_path,entry_kind,graph_name,graph_path FROM uaf_entries WHERE asset_path LIKE ? OR graph_name LIKE ? LIMIT ?",
        (pattern, pattern, limit)), ("asset","kind","name","graph"))


def install(systems_module) -> None:
    if getattr(systems_module, "_uaf_schema_installed", False):
        return
    original_create_schema = systems_module.create_schema
    original_validation_error = systems_module.validation_error
    original_load_database = systems_module.load_database
    original_query = systems_module.query
    systems_module.SYSTEMS_SCHEMA_VERSION = 10
    systems_module.JSONL_FILES = tuple(dict.fromkeys((*systems_module.JSONL_FILES, *UAF_FILES)))
    systems_module.RAW_FILES = ("systems_manifest.json", *systems_module.JSONL_FILES)

    def create_schema_wrapper(conn):
        original_create_schema(conn)
        create_schema(conn)

    def validation_wrapper(output):
        error = original_validation_error(output)
        if error: return error
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
    systems_module._uaf_schema_installed = True
