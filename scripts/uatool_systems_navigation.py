#!/usr/bin/env python3
"""Systems schema 11: authored Navigation definitions/defaults/config semantics."""
from __future__ import annotations

import json
from pathlib import Path

NAVIGATION_FILES = (
    "navigation_areas.jsonl",
    "navigation_area_agent_mappings.jsonl",
    "navigation_systems.jsonl",
    "navigation_agents.jsonl",
    "navigation_link_defaults.jsonl",
    "navigation_modifier_defaults.jsonl",
    "navigation_invoker_defaults.jsonl",
    "navigation_bounds_defaults.jsonl",
    "navigation_recast_defaults.jsonl",
)

NAV_AREA_BASE = "/Script/NavigationSystem.NavArea"
NAV_SYSTEM_CLASS = "/Script/NavigationSystem.NavigationSystemV1"
NAV_SYSTEM_CONFIG_CLASS = "/Script/Engine.NavigationSystemConfig"
RECAST_CLASS = "/Script/NavigationSystem.RecastNavMesh"

_SQL = """
CREATE TABLE navigation_areas(
 class_path TEXT PRIMARY KEY,parent_class TEXT NOT NULL,area_kind TEXT NOT NULL,
 default_cost TEXT NOT NULL,fixed_area_entering_cost TEXT NOT NULL,supported_agents TEXT NOT NULL,json TEXT NOT NULL);
CREATE TABLE navigation_area_agent_mappings(
 source_area TEXT NOT NULL,agent_index INTEGER NOT NULL,target_area TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(source_area,agent_index));
CREATE TABLE navigation_systems(
 class_path TEXT PRIMARY KEY,system_kind TEXT NOT NULL,default_agent_name TEXT NOT NULL,
 supported_agents TEXT NOT NULL,generate_navigation_only_around_invokers INTEGER NOT NULL,
 skip_agent_height_check_when_picking_nav_data INTEGER NOT NULL,crowd_manager_class TEXT NOT NULL,
 agent_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE navigation_agents(
 system_class TEXT NOT NULL,agent_index INTEGER NOT NULL,name TEXT NOT NULL,nav_data_class TEXT NOT NULL,
 preferred_nav_data TEXT NOT NULL,agent_radius TEXT NOT NULL,agent_height TEXT NOT NULL,
 agent_step_height TEXT NOT NULL,default_query_extent TEXT NOT NULL,nav_walking_search_height_scale TEXT NOT NULL,
 can_crouch INTEGER NOT NULL,can_jump INTEGER NOT NULL,can_walk INTEGER NOT NULL,can_swim INTEGER NOT NULL,
 can_fly INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(system_class,agent_index));
CREATE TABLE navigation_link_defaults(
 link_id TEXT PRIMARY KEY,class_path TEXT NOT NULL,link_kind TEXT NOT NULL,link_index INTEGER NOT NULL,
 direction TEXT NOT NULL,area_class TEXT NOT NULL,enabled_area_class TEXT NOT NULL,disabled_area_class TEXT NOT NULL,
 obstacle_area_class TEXT NOT NULL,supported_agents TEXT NOT NULL,left_value TEXT NOT NULL,right_value TEXT NOT NULL,
 left_project_height TEXT NOT NULL,max_fall_down_length TEXT NOT NULL,snap_radius TEXT NOT NULL,snap_height TEXT NOT NULL,
 use_snap_height INTEGER NOT NULL,snap_to_cheapest_area INTEGER NOT NULL,smart_link_relevant INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE navigation_modifier_defaults(
 modifier_id TEXT PRIMARY KEY,class_path TEXT NOT NULL,modifier_kind TEXT NOT NULL,
 area_class TEXT NOT NULL,area_class_to_replace TEXT NOT NULL,include_agent_height INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE navigation_invoker_defaults(
 invoker_id TEXT PRIMARY KEY,class_path TEXT NOT NULL,tile_generation_radius TEXT NOT NULL,
 tile_removal_radius TEXT NOT NULL,invoker_priority TEXT NOT NULL,supported_agents TEXT NOT NULL,json TEXT NOT NULL);
CREATE TABLE navigation_bounds_defaults(
 bounds_id TEXT PRIMARY KEY,class_path TEXT NOT NULL,supported_agents TEXT NOT NULL,json TEXT NOT NULL);
CREATE TABLE navigation_recast_defaults(
 recast_id TEXT PRIMARY KEY,class_path TEXT NOT NULL,runtime_generation TEXT NOT NULL,cell_size TEXT NOT NULL,
 cell_height TEXT NOT NULL,tile_size_uu TEXT NOT NULL,agent_radius TEXT NOT NULL,agent_height TEXT NOT NULL,
 agent_max_step_height TEXT NOT NULL,nav_data_config TEXT NOT NULL,jump_down_area_class TEXT NOT NULL,
 jump_up_area_class TEXT NOT NULL,json TEXT NOT NULL);
"""


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


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


def _indices(value, label: str) -> list[int]:
    if not isinstance(value, list):
        raise ValueError(f"{label} supported_agents is not an array")
    result = []
    seen = set()
    for raw in value:
        if isinstance(raw, bool):
            raise ValueError(f"{label} supported_agents contains boolean index")
        try:
            index = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} supported_agents contains non-integer index: {raw!r}") from exc
        if index < 0 or index > 30:
            raise ValueError(f"{label} supported_agents index out of range: {index}")
        if index in seen:
            raise ValueError(f"{label} supported_agents contains duplicate index: {index}")
        seen.add(index)
        result.append(index)
    if result != sorted(result):
        raise ValueError(f"{label} supported_agents is not sorted")
    return result


def _unique(rows: list[dict], fields: tuple[str, ...], label: str) -> str | None:
    seen = set()
    for row in rows:
        key = tuple(str(row.get(field, "") if row.get(field, "") is not None else "") for field in fields)
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
    present = [name for name in NAVIGATION_FILES if (output / name).is_file()]
    if version < 11:
        if present:
            return f"Navigation canonical streams require systems schema >=11, got {version}"
        return None
    missing = [name for name in NAVIGATION_FILES if not (output / name).is_file()]
    if missing:
        return f"systems schema 11 is missing Navigation canonical file: {missing[0]}"

    areas = list(rows(output / "navigation_areas.jsonl"))
    mappings = list(rows(output / "navigation_area_agent_mappings.jsonl"))
    systems = list(rows(output / "navigation_systems.jsonl"))
    agents = list(rows(output / "navigation_agents.jsonl"))
    links = list(rows(output / "navigation_link_defaults.jsonl"))
    modifiers = list(rows(output / "navigation_modifier_defaults.jsonl"))
    invokers = list(rows(output / "navigation_invoker_defaults.jsonl"))
    bounds = list(rows(output / "navigation_bounds_defaults.jsonl"))
    recast = list(rows(output / "navigation_recast_defaults.jsonl"))

    for items, fields, label in (
        (areas, ("class_path",), "Navigation area"),
        (mappings, ("source_area", "agent_index"), "Navigation area mapping"),
        (systems, ("class_path",), "Navigation system"),
        (agents, ("system_class", "agent_index"), "Navigation agent"),
        (links, ("link_id",), "Navigation link default"),
        (modifiers, ("modifier_id",), "Navigation modifier default"),
        (invokers, ("invoker_id",), "Navigation invoker default"),
        (bounds, ("bounds_id",), "Navigation bounds default"),
        (recast, ("recast_id",), "Navigation Recast default"),
    ):
        error = _unique(items, fields, label)
        if error:
            return error

    area_rows = {str(row.get("class_path", "") or ""): row for row in areas}
    if NAV_AREA_BASE not in area_rows:
        return "Navigation areas are missing /Script/NavigationSystem.NavArea"
    for path, row in area_rows.items():
        if not str(row.get("area_kind", "") or ""):
            return f"Navigation area has blank kind: {path}"
        try:
            _indices(row.get("supported_agents"), f"Navigation area {path}")
        except ValueError as exc:
            return str(exc)

    for row in mappings:
        source = str(row.get("source_area", "") or "")
        target = str(row.get("target_area", "") or "")
        index = int(row.get("agent_index", -1))
        if source not in area_rows or target not in area_rows:
            return f"Navigation area mapping has unresolved area: {source} agent={index} -> {target}"
        if index < 0 or index > 30:
            return f"Navigation area mapping has invalid agent index: {source}::{index}"

    system_rows = {str(row.get("class_path", "") or ""): row for row in systems}
    if NAV_SYSTEM_CLASS not in system_rows or NAV_SYSTEM_CONFIG_CLASS not in system_rows:
        return "Navigation systems are missing NavigationSystemV1 or NavigationSystemConfig"
    if str(system_rows[NAV_SYSTEM_CLASS].get("system_kind", "")) != "navigation_system":
        return "NavigationSystemV1 row has wrong system_kind"
    if str(system_rows[NAV_SYSTEM_CONFIG_CLASS].get("system_kind", "")) != "navigation_system_config":
        return "NavigationSystemConfig row has wrong system_kind"
    for path, row in system_rows.items():
        try:
            _indices(row.get("supported_agents"), f"Navigation system {path}")
        except ValueError as exc:
            return str(exc)
        if int(row.get("agent_count", -1)) < 0:
            return f"Navigation system has negative agent_count: {path}"

    agent_counts: dict[str, int] = {}
    agent_indices: dict[str, set[int]] = {}
    for row in agents:
        system = str(row.get("system_class", "") or "")
        index = int(row.get("agent_index", -1))
        if system not in system_rows:
            return f"Navigation agent owner does not resolve: {system}::{index}"
        if index < 0:
            return f"Navigation agent has negative index: {system}::{index}"
        if not str(row.get("name", "") or ""):
            return f"Navigation agent has blank name: {system}::{index}"
        if not str(row.get("nav_data_class", "") or ""):
            return f"Navigation agent has blank nav_data_class: {system}::{index}"
        agent_counts[system] = agent_counts.get(system, 0) + 1
        agent_indices.setdefault(system, set()).add(index)
    for system, row in system_rows.items():
        expected = int(row.get("agent_count", 0) or 0)
        if agent_counts.get(system, 0) != expected:
            return f"Navigation system agent_count mismatch: {system} row={expected} actual={agent_counts.get(system,0)}"
        if agent_indices.get(system, set()) and agent_indices[system] != set(range(expected)):
            return f"Navigation agent indices are not contiguous: {system}"

    for row in links:
        link_id = str(row.get("link_id", "") or "")
        kind = str(row.get("link_kind", "") or "")
        if kind not in {"simple", "smart"}:
            return f"Navigation link has unexpected kind: {link_id} -> {kind}"
        try:
            _indices(row.get("supported_agents"), f"Navigation link {link_id}")
        except ValueError as exc:
            return str(exc)
        for field in ("area_class", "enabled_area_class", "disabled_area_class", "obstacle_area_class"):
            area = str(row.get(field, "") or "")
            if area and area not in area_rows:
                return f"Navigation link area does not resolve: {link_id}::{field} -> {area}"

    for row in modifiers:
        modifier = str(row.get("modifier_id", "") or "")
        if str(row.get("modifier_kind", "") or "") not in {"component", "volume"}:
            return f"Navigation modifier has unexpected kind: {modifier}"
        for field in ("area_class", "area_class_to_replace"):
            area = str(row.get(field, "") or "")
            if area and area not in area_rows:
                return f"Navigation modifier area does not resolve: {modifier}::{field} -> {area}"

    for row in invokers:
        try:
            _indices(row.get("supported_agents"), f"Navigation invoker {row.get('invoker_id','')}")
        except ValueError as exc:
            return str(exc)
    for row in bounds:
        try:
            _indices(row.get("supported_agents"), f"Navigation bounds {row.get('bounds_id','')}")
        except ValueError as exc:
            return str(exc)

    if len(recast) != 1 or str(recast[0].get("class_path", "") or "") != RECAST_CLASS:
        return "Navigation schema 11 requires one RecastNavMesh authored-default row"
    for field in ("jump_down_area_class", "jump_up_area_class"):
        area = str(recast[0].get(field, "") or "")
        if area and area not in area_rows:
            return f"Navigation Recast area does not resolve: {field} -> {area}"

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    physical = {
        "navigation_areas": len(areas),
        "navigation_area_agent_mappings": len(mappings),
        "navigation_systems": len(systems),
        "navigation_agents": len(agents),
        "navigation_link_defaults": len(links),
        "navigation_modifier_defaults": len(modifiers),
        "navigation_invoker_defaults": len(invokers),
        "navigation_bounds_defaults": len(bounds),
        "navigation_recast_defaults": len(recast),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            return f"Navigation manifest count mismatch for {key}: manifest={counts.get(key)} actual={actual}"
    if int(counts.get("navigation_truncated_values", -1)) != 0:
        return f"Navigation canonical capture has truncated values: {counts.get('navigation_truncated_values')}"
    if int(counts.get("navigation_missing_expected_classes", -1)) != 0:
        return f"Navigation canonical capture is missing expected UE 5.8 classes: {counts.get('navigation_missing_expected_classes')}"
    return None


def load_database(conn, output: Path, rows=None) -> None:
    output = Path(output)
    rows = rows or _rows
    if int(_manifest(output).get("schema_version", 0) or 0) < 11:
        return

    specs = {
        "navigation_areas.jsonl": ("navigation_areas", ("class_path","parent_class","area_kind","default_cost","fixed_area_entering_cost","supported_agents")),
        "navigation_area_agent_mappings.jsonl": ("navigation_area_agent_mappings", ("source_area","agent_index","target_area")),
        "navigation_systems.jsonl": ("navigation_systems", ("class_path","system_kind","default_agent_name","supported_agents","generate_navigation_only_around_invokers","skip_agent_height_check_when_picking_nav_data","crowd_manager_class","agent_count")),
        "navigation_agents.jsonl": ("navigation_agents", ("system_class","agent_index","name","nav_data_class","preferred_nav_data","agent_radius","agent_height","agent_step_height","default_query_extent","nav_walking_search_height_scale","can_crouch","can_jump","can_walk","can_swim","can_fly")),
        "navigation_link_defaults.jsonl": ("navigation_link_defaults", ("link_id","class_path","link_kind","link_index","direction","area_class","enabled_area_class","disabled_area_class","obstacle_area_class","supported_agents","left","right","left_project_height","max_fall_down_length","snap_radius","snap_height","use_snap_height","snap_to_cheapest_area","smart_link_relevant")),
        "navigation_modifier_defaults.jsonl": ("navigation_modifier_defaults", ("modifier_id","class_path","modifier_kind","area_class","area_class_to_replace","include_agent_height")),
        "navigation_invoker_defaults.jsonl": ("navigation_invoker_defaults", ("invoker_id","class_path","tile_generation_radius","tile_removal_radius","invoker_priority","supported_agents")),
        "navigation_bounds_defaults.jsonl": ("navigation_bounds_defaults", ("bounds_id","class_path","supported_agents")),
        "navigation_recast_defaults.jsonl": ("navigation_recast_defaults", ("recast_id","class_path","runtime_generation","cell_size","cell_height","tile_size_uu","agent_radius","agent_height","agent_max_step_height","nav_data_config","jump_down_area_class","jump_up_area_class")),
    }
    integer_fields = {
        "agent_index","agent_count","link_index","generate_navigation_only_around_invokers",
        "skip_agent_height_check_when_picking_nav_data","can_crouch","can_jump","can_walk",
        "can_swim","can_fly","use_snap_height","snap_to_cheapest_area","smart_link_relevant",
        "include_agent_height",
    }
    array_fields = {"supported_agents"}
    bool_fields = {
        "generate_navigation_only_around_invokers","skip_agent_height_check_when_picking_nav_data",
        "can_crouch","can_jump","can_walk","can_swim","can_fly","use_snap_height",
        "snap_to_cheapest_area","smart_link_relevant","include_agent_height",
    }
    for filename, (table, fields) in specs.items():
        placeholders = ",".join("?" for _ in range(len(fields) + 1))
        for row in rows(output / filename):
            values = []
            for field in fields:
                value = row.get(field, "")
                if field in array_fields:
                    value = _j(value if isinstance(value, list) else [])
                elif field in integer_fields:
                    value = int(bool(value)) if field in bool_fields else int(value or 0)
                values.append(value)
            conn.execute(f"INSERT OR REPLACE INTO {table} VALUES({placeholders})", (*values, _j(row)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='navigation_areas'").fetchone():
        return
    print("\n[Navigation areas]")
    print_rows(conn.execute(
        "SELECT class_path,area_kind,default_cost,fixed_area_entering_cost FROM navigation_areas WHERE class_path LIKE ? LIMIT ?",
        (pattern, limit)), ("area","kind","cost","enter_cost"))
    print("\n[Navigation agents]")
    print_rows(conn.execute(
        "SELECT system_class,agent_index,name,nav_data_class,agent_radius,agent_height FROM navigation_agents WHERE system_class LIKE ? OR name LIKE ? LIMIT ?",
        (pattern, pattern, limit)), ("system","index","name","nav_data","radius","height"))
    print("\n[Navigation authored defaults]")
    print_rows(conn.execute(
        "SELECT link_id,link_kind,direction,area_class FROM navigation_link_defaults WHERE link_id LIKE ? OR class_path LIKE ? LIMIT ?",
        (pattern, pattern, limit)), ("link","kind","direction","area"))


def install(systems_module) -> None:
    if getattr(systems_module, "_navigation_schema_installed", False):
        return
    original_create_schema = systems_module.create_schema
    original_validation_error = systems_module.validation_error
    original_load_database = systems_module.load_database
    original_query = systems_module.query
    systems_module.SYSTEMS_SCHEMA_VERSION = 11
    systems_module.JSONL_FILES = tuple(dict.fromkeys((*systems_module.JSONL_FILES, *NAVIGATION_FILES)))
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
    systems_module._navigation_schema_installed = True
