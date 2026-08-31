#!/usr/bin/env python3
"""Systems schema 4 Gameplay Cameras normalization over reflection-backed scanner rows."""
from __future__ import annotations

import collections
import json
from pathlib import Path

GAMEPLAY_CAMERA_FILES = (
    "gameplay_camera_assets.jsonl",
    "gameplay_camera_rigs.jsonl",
    "gameplay_camera_nodes.jsonl",
    "gameplay_camera_node_edges.jsonl",
    "gameplay_camera_transitions.jsonl",
    "gameplay_camera_directors.jsonl",
    "gameplay_camera_rig_references.jsonl",
)

_SQL = """
CREATE TABLE gameplay_camera_assets(
 camera_asset_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,class_path TEXT NOT NULL,
 director_path TEXT NOT NULL,director_class TEXT NOT NULL,
 enter_transition_count INTEGER NOT NULL,exit_transition_count INTEGER NOT NULL,loose_transition_count INTEGER NOT NULL,
 asset_rig_reference_count INTEGER NOT NULL,director_rig_reference_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX gameplay_camera_assets_director_idx ON gameplay_camera_assets(director_path,director_class);
CREATE TABLE gameplay_camera_rigs(
 rig_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,class_path TEXT NOT NULL,
 root_node_path TEXT NOT NULL,root_node_class TEXT NOT NULL,initial_orientation TEXT NOT NULL,gameplay_tags TEXT NOT NULL,
 node_count INTEGER NOT NULL,node_edge_count INTEGER NOT NULL,
 enter_transition_count INTEGER NOT NULL,exit_transition_count INTEGER NOT NULL,loose_transition_count INTEGER NOT NULL,
 rig_reference_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX gameplay_camera_rigs_root_idx ON gameplay_camera_rigs(root_node_path,root_node_class);
CREATE TABLE gameplay_camera_nodes(
 rig_path TEXT NOT NULL,node_index INTEGER NOT NULL,node_path TEXT NOT NULL,node_name TEXT NOT NULL,node_class TEXT NOT NULL,
 is_root INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(rig_path,node_index));
CREATE UNIQUE INDEX gameplay_camera_nodes_path_idx ON gameplay_camera_nodes(rig_path,node_path);
CREATE INDEX gameplay_camera_nodes_class_idx ON gameplay_camera_nodes(node_class);
CREATE TABLE gameplay_camera_node_edges(
 rig_path TEXT NOT NULL,source_node_path TEXT NOT NULL,property_path TEXT NOT NULL,target_node_path TEXT NOT NULL,
 target_node_class TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(rig_path,source_node_path,property_path,target_node_path));
CREATE INDEX gameplay_camera_node_edges_target_idx ON gameplay_camera_node_edges(rig_path,target_node_path);
CREATE TABLE gameplay_camera_transitions(
 asset_path TEXT NOT NULL,owner_path TEXT NOT NULL,owner_kind TEXT NOT NULL,transition_role TEXT NOT NULL,
 transition_index INTEGER NOT NULL,transition_path TEXT NOT NULL,transition_class TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(owner_path,transition_role,transition_index));
CREATE INDEX gameplay_camera_transitions_path_idx ON gameplay_camera_transitions(transition_path,transition_class);
CREATE TABLE gameplay_camera_directors(
 asset_path TEXT PRIMARY KEY,director_path TEXT NOT NULL,director_class TEXT NOT NULL,run_in_editor TEXT NOT NULL,
 nested_object_count INTEGER NOT NULL,rig_reference_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX gameplay_camera_directors_path_idx ON gameplay_camera_directors(director_path,director_class);
CREATE TABLE gameplay_camera_rig_references(
 asset_path TEXT NOT NULL,source_owner_path TEXT NOT NULL,source_owner_kind TEXT NOT NULL,property_path TEXT NOT NULL,
 target_rig_path TEXT NOT NULL,target_rig_class TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(asset_path,source_owner_path,property_path,target_rig_path));
CREATE INDEX gameplay_camera_rig_references_target_idx ON gameplay_camera_rig_references(target_rig_path,target_rig_class);
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


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def validation_error(output: Path, rows=None) -> str | None:
    output = Path(output)
    rows = rows or _read_rows
    assets = list(rows(output / "gameplay_camera_assets.jsonl"))
    rigs = list(rows(output / "gameplay_camera_rigs.jsonl"))
    nodes = list(rows(output / "gameplay_camera_nodes.jsonl"))
    edges = list(rows(output / "gameplay_camera_node_edges.jsonl"))
    transitions = list(rows(output / "gameplay_camera_transitions.jsonl"))
    directors = list(rows(output / "gameplay_camera_directors.jsonl"))
    rig_refs = list(rows(output / "gameplay_camera_rig_references.jsonl"))

    asset_paths = [str(row.get("camera_asset_path", "") or "") for row in assets]
    if any(not path for path in asset_paths) or len(asset_paths) != len(set(asset_paths)):
        return "Gameplay Camera asset paths are blank or duplicated"
    asset_set = set(asset_paths)
    for row in assets:
        if str(row.get("class_path", "")) != "/Script/GameplayCameras.CameraAsset":
            return f"Gameplay Camera asset has unexpected class: {row.get('camera_asset_path')} -> {row.get('class_path')}"

    rig_paths = [str(row.get("rig_path", "") or "") for row in rigs]
    if any(not path for path in rig_paths) or len(rig_paths) != len(set(rig_paths)):
        return "Gameplay Camera rig paths are blank or duplicated"
    rig_set = set(rig_paths)
    for row in rigs:
        if str(row.get("class_path", "")) != "/Script/GameplayCameras.CameraRigAsset":
            return f"Gameplay Camera rig has unexpected class: {row.get('rig_path')} -> {row.get('class_path')}"

    nodes_by_rig: dict[str, list[dict]] = collections.defaultdict(list)
    node_paths_by_rig: dict[str, set[str]] = collections.defaultdict(set)
    for row in nodes:
        rig = str(row.get("rig_path", "") or "")
        path = str(row.get("node_path", "") or "")
        if rig not in rig_set:
            return f"Gameplay Camera node references unknown rig: {rig}"
        if not path:
            return f"Gameplay Camera node has blank path in rig: {rig}"
        if path in node_paths_by_rig[rig]:
            return f"Gameplay Camera node path is duplicated in rig: {rig} -> {path}"
        node_paths_by_rig[rig].add(path)
        nodes_by_rig[rig].append(row)
    for rig, values in nodes_by_rig.items():
        indices = sorted(int(row.get("node_index", -1)) for row in values)
        if indices != list(range(len(values))):
            return f"Gameplay Camera node indices are not contiguous for {rig}"

    edge_counts = collections.Counter()
    edge_keys: set[tuple[str, str, str, str]] = set()
    for row in edges:
        rig = str(row.get("rig_path", "") or "")
        source = str(row.get("source_node_path", "") or "")
        target = str(row.get("target_node_path", "") or "")
        prop = str(row.get("property_path", "") or "")
        if rig not in rig_set:
            return f"Gameplay Camera node edge references unknown rig: {rig}"
        known = node_paths_by_rig.get(rig, set())
        if source not in known or target not in known:
            return f"Gameplay Camera node edge endpoint does not resolve inside rig: {rig} -> {source} / {target}"
        if not prop:
            return f"Gameplay Camera node edge has blank property path: {rig} -> {source} / {target}"
        key = (rig, source, prop, target)
        if key in edge_keys:
            return f"Gameplay Camera node edge is duplicated: {key}"
        edge_keys.add(key)
        edge_counts[rig] += 1

    transition_counts = collections.Counter()
    transition_indices: dict[tuple[str, str], list[int]] = collections.defaultdict(list)
    valid_owners = asset_set | rig_set
    valid_roles = {"enter", "exit", "graph_object"}
    for row in transitions:
        owner = str(row.get("owner_path", "") or "")
        role = str(row.get("transition_role", "") or "")
        path = str(row.get("transition_path", "") or "")
        if owner not in valid_owners:
            return f"Gameplay Camera transition references unknown owner: {owner}"
        if role not in valid_roles:
            return f"unexpected Gameplay Camera transition role: {role!r}"
        if not path:
            return f"Gameplay Camera transition has blank path: {owner} / {role}"
        transition_counts[(owner, role)] += 1
        transition_indices[(owner, role)].append(int(row.get("transition_index", -1)))
    for key, values in transition_indices.items():
        if sorted(values) != list(range(len(values))):
            return f"Gameplay Camera transition indices are not contiguous for {key[0]} / {key[1]}"

    director_by_asset: dict[str, dict] = {}
    for row in directors:
        asset = str(row.get("asset_path", "") or "")
        path = str(row.get("director_path", "") or "")
        if asset not in asset_set:
            return f"Gameplay Camera director references unknown Camera Asset: {asset}"
        if not path or asset in director_by_asset:
            return f"Gameplay Camera director is blank or duplicated for asset: {asset}"
        director_by_asset[asset] = row

    rig_refs_by_asset_owner = collections.Counter()
    for row in rig_refs:
        asset = str(row.get("asset_path", "") or "")
        source = str(row.get("source_owner_path", "") or "")
        target = str(row.get("target_rig_path", "") or "")
        prop = str(row.get("property_path", "") or "")
        if not asset or not source or not target or not prop:
            return "Gameplay Camera rig reference has blank identity"
        rig_refs_by_asset_owner[(asset, source)] += 1

    for row in rigs:
        rig = str(row.get("rig_path", "") or "")
        values = nodes_by_rig.get(rig, [])
        if int(row.get("node_count", 0) or 0) != len(values):
            return f"Gameplay Camera rig node_count mismatch: {rig}"
        if int(row.get("node_edge_count", 0) or 0) != edge_counts[rig]:
            return f"Gameplay Camera rig node_edge_count mismatch: {rig}"
        root = str(row.get("root_node_path", "") or "")
        roots = [value for value in values if bool(value.get("is_root", False))]
        if root:
            if len(roots) != 1 or str(roots[0].get("node_path", "")) != root:
                return f"Gameplay Camera rig root node does not resolve uniquely: {rig} -> {root}"
        elif roots:
            return f"Gameplay Camera rig has root-marked node but blank root_node_path: {rig}"
        if int(row.get("enter_transition_count", 0) or 0) != transition_counts[(rig, "enter")]:
            return f"Gameplay Camera rig enter transition count mismatch: {rig}"
        if int(row.get("exit_transition_count", 0) or 0) != transition_counts[(rig, "exit")]:
            return f"Gameplay Camera rig exit transition count mismatch: {rig}"
        if int(row.get("loose_transition_count", 0) or 0) != transition_counts[(rig, "graph_object")]:
            return f"Gameplay Camera rig loose transition count mismatch: {rig}"
        if int(row.get("rig_reference_count", 0) or 0) != rig_refs_by_asset_owner[(rig, rig)]:
            return f"Gameplay Camera rig direct rig-reference count mismatch: {rig}"

    for row in assets:
        asset = str(row.get("camera_asset_path", "") or "")
        director_path = str(row.get("director_path", "") or "")
        director = director_by_asset.get(asset)
        if director_path:
            if director is None or str(director.get("director_path", "") or "") != director_path:
                return f"Gameplay Camera asset director does not resolve: {asset} -> {director_path}"
        elif director is not None:
            return f"Gameplay Camera asset has director row but blank director_path: {asset}"
        if int(row.get("enter_transition_count", 0) or 0) != transition_counts[(asset, "enter")]:
            return f"Gameplay Camera asset enter transition count mismatch: {asset}"
        if int(row.get("exit_transition_count", 0) or 0) != transition_counts[(asset, "exit")]:
            return f"Gameplay Camera asset exit transition count mismatch: {asset}"
        if int(row.get("loose_transition_count", 0) or 0) != transition_counts[(asset, "graph_object")]:
            return f"Gameplay Camera asset loose transition count mismatch: {asset}"
        if int(row.get("asset_rig_reference_count", 0) or 0) != rig_refs_by_asset_owner[(asset, asset)]:
            return f"Gameplay Camera asset direct rig-reference count mismatch: {asset}"
        expected_director_refs = int(director.get("rig_reference_count", 0) or 0) if director else 0
        if int(row.get("director_rig_reference_count", 0) or 0) != expected_director_refs:
            return f"Gameplay Camera asset director rig-reference count mismatch: {asset}"

    return None


def load_database(conn, output: Path, rows=None) -> None:
    rows = rows or _read_rows
    for r in rows(output / "gameplay_camera_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_camera_assets VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("camera_asset_path", ""), r.get("package_name", ""), r.get("class_path", ""),
            r.get("director_path", ""), r.get("director_class", ""),
            int(r.get("enter_transition_count", 0) or 0), int(r.get("exit_transition_count", 0) or 0),
            int(r.get("loose_transition_count", 0) or 0), int(r.get("asset_rig_reference_count", 0) or 0),
            int(r.get("director_rig_reference_count", 0) or 0), _j(r)))
    for r in rows(output / "gameplay_camera_rigs.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_camera_rigs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("rig_path", ""), r.get("package_name", ""), r.get("class_path", ""),
            r.get("root_node_path", ""), r.get("root_node_class", ""), r.get("initial_orientation", ""),
            r.get("gameplay_tags", ""), int(r.get("node_count", 0) or 0), int(r.get("node_edge_count", 0) or 0),
            int(r.get("enter_transition_count", 0) or 0), int(r.get("exit_transition_count", 0) or 0),
            int(r.get("loose_transition_count", 0) or 0), int(r.get("rig_reference_count", 0) or 0), _j(r)))
    for r in rows(output / "gameplay_camera_nodes.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_camera_nodes VALUES(?,?,?,?,?,?,?)", (
            r.get("rig_path", ""), int(r.get("node_index", 0) or 0), r.get("node_path", ""),
            r.get("node_name", ""), r.get("node_class", ""), int(bool(r.get("is_root", False))), _j(r)))
    for r in rows(output / "gameplay_camera_node_edges.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_camera_node_edges VALUES(?,?,?,?,?,?)", (
            r.get("rig_path", ""), r.get("source_node_path", ""), r.get("property_path", ""),
            r.get("target_node_path", ""), r.get("target_node_class", ""), _j(r)))
    for r in rows(output / "gameplay_camera_transitions.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_camera_transitions VALUES(?,?,?,?,?,?,?,?)", (
            r.get("asset_path", ""), r.get("owner_path", ""), r.get("owner_kind", ""),
            r.get("transition_role", ""), int(r.get("transition_index", 0) or 0), r.get("transition_path", ""),
            r.get("transition_class", ""), _j(r)))
    for r in rows(output / "gameplay_camera_directors.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_camera_directors VALUES(?,?,?,?,?,?,?)", (
            r.get("asset_path", ""), r.get("director_path", ""), r.get("director_class", ""),
            r.get("run_in_editor", ""), int(r.get("nested_object_count", 0) or 0),
            int(r.get("rig_reference_count", 0) or 0), _j(r)))
    for r in rows(output / "gameplay_camera_rig_references.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gameplay_camera_rig_references VALUES(?,?,?,?,?,?,?)", (
            r.get("asset_path", ""), r.get("source_owner_path", ""), r.get("source_owner_kind", ""),
            r.get("property_path", ""), r.get("target_rig_path", ""), r.get("target_rig_class", ""), _j(r)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gameplay_camera_assets'").fetchone():
        return
    print("\n[Gameplay Camera assets / directors]")
    print_rows(conn.execute(
        """SELECT camera_asset_path,director_path,director_class,enter_transition_count,exit_transition_count,director_rig_reference_count
           FROM gameplay_camera_assets
           WHERE camera_asset_path LIKE ? OR director_path LIKE ? OR director_class LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("camera_asset_path", "director_path", "director_class", "enter_transition_count", "exit_transition_count", "director_rig_reference_count"))
    print("\n[Gameplay Camera rigs]")
    print_rows(conn.execute(
        """SELECT rig_path,root_node_path,root_node_class,initial_orientation,gameplay_tags,node_count,node_edge_count
           FROM gameplay_camera_rigs
           WHERE rig_path LIKE ? OR root_node_path LIKE ? OR root_node_class LIKE ? OR gameplay_tags LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, pattern, limit)),
        ("rig_path", "root_node_path", "root_node_class", "initial_orientation", "gameplay_tags", "node_count", "node_edge_count"))
    print("\n[Gameplay Camera nodes / transitions]")
    print_rows(conn.execute(
        """SELECT rig_path,node_path,node_class,is_root FROM gameplay_camera_nodes
           WHERE rig_path LIKE ? OR node_path LIKE ? OR node_name LIKE ? OR node_class LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, pattern, limit)),
        ("rig_path", "node_path", "node_class", "is_root"))
    print_rows(conn.execute(
        """SELECT asset_path,owner_path,transition_role,transition_path,transition_class
           FROM gameplay_camera_transitions
           WHERE asset_path LIKE ? OR owner_path LIKE ? OR transition_role LIKE ? OR transition_path LIKE ? OR transition_class LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("asset_path", "owner_path", "transition_role", "transition_path", "transition_class"))


def install(systems_module) -> None:
    if getattr(systems_module, "_gameplay_camera_schema_installed", False):
        return

    original_create_schema = systems_module.create_schema
    original_validation_error = systems_module.validation_error
    original_load_database = systems_module.load_database
    original_query = systems_module.query

    systems_module.SYSTEMS_SCHEMA_VERSION = 4
    systems_module.JSONL_FILES = tuple(dict.fromkeys((*systems_module.JSONL_FILES, *GAMEPLAY_CAMERA_FILES)))
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
    systems_module._gameplay_camera_schema_installed = True
