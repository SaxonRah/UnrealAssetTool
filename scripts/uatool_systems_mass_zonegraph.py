#!/usr/bin/env python3
"""Systems schema 5 Mass + ZoneGraph normalization over reflection-backed scanner rows."""
from __future__ import annotations

import collections
import json
from pathlib import Path

MASS_ZONEGRAPH_FILES = (
    "mass_entity_configs.jsonl",
    "mass_entity_traits.jsonl",
    "mass_spawners.jsonl",
    "mass_spawner_entity_types.jsonl",
    "mass_spawner_generators.jsonl",
    "mass_spawn_generator_assets.jsonl",
    "mass_agent_components.jsonl",
    "zonegraph_shapes.jsonl",
    "zonegraph_shape_points.jsonl",
)

_SQL = """
CREATE TABLE mass_entity_configs(
 config_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,class_path TEXT NOT NULL,
 config_property TEXT NOT NULL,config_guid TEXT NOT NULL,parent_config_path TEXT NOT NULL,
 parent_config_class TEXT NOT NULL,trait_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX mass_entity_configs_parent_idx ON mass_entity_configs(parent_config_path);
CREATE TABLE mass_entity_traits(
 config_path TEXT NOT NULL,trait_index INTEGER NOT NULL,trait_path TEXT NOT NULL,trait_class TEXT NOT NULL,
 json TEXT NOT NULL,PRIMARY KEY(config_path,trait_index));
CREATE INDEX mass_entity_traits_class_idx ON mass_entity_traits(trait_class,config_path);
CREATE TABLE mass_spawners(
 spawner_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,generated_class TEXT NOT NULL,cdo_path TEXT NOT NULL,
 entity_type_count INTEGER NOT NULL,spawn_generator_count INTEGER NOT NULL,count TEXT NOT NULL,
 auto_spawn_on_begin_play TEXT NOT NULL,json TEXT NOT NULL);
CREATE TABLE mass_spawner_entity_types(
 spawner_path TEXT NOT NULL,entity_type_index INTEGER NOT NULL,entity_config_path TEXT NOT NULL,
 entity_config_class TEXT NOT NULL,proportion TEXT NOT NULL,raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,
 json TEXT NOT NULL,PRIMARY KEY(spawner_path,entity_type_index));
CREATE INDEX mass_spawner_entity_types_config_idx ON mass_spawner_entity_types(entity_config_path,spawner_path);
CREATE TABLE mass_spawner_generators(
 spawner_path TEXT NOT NULL,generator_index INTEGER NOT NULL,generator_path TEXT NOT NULL,
 generator_class TEXT NOT NULL,generator_asset_path TEXT NOT NULL,proportion TEXT NOT NULL,
 raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(spawner_path,generator_index));
CREATE INDEX mass_spawner_generators_target_idx ON mass_spawner_generators(generator_asset_path,generator_class);
CREATE TABLE mass_spawn_generator_assets(
 generator_asset_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,generated_class TEXT NOT NULL,
 parent_class TEXT NOT NULL,cdo_path TEXT NOT NULL,zonegraph_generator INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE mass_agent_components(
 component_path TEXT PRIMARY KEY,blueprint_path TEXT NOT NULL,component_name TEXT NOT NULL,
 component_class TEXT NOT NULL,entity_config_parent_path TEXT NOT NULL,entity_config_parent_class TEXT NOT NULL,
 config_guid TEXT NOT NULL,raw_entity_config TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX mass_agent_components_blueprint_idx ON mass_agent_components(blueprint_path,component_name);
CREATE INDEX mass_agent_components_config_idx ON mass_agent_components(entity_config_parent_path);
CREATE TABLE zonegraph_shapes(
 shape_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,class_path TEXT NOT NULL,
 component_path TEXT NOT NULL,component_class TEXT NOT NULL,point_count INTEGER NOT NULL,
 shape_type TEXT NOT NULL,lane_profile TEXT NOT NULL,tags TEXT NOT NULL,reverse_lane_profile TEXT NOT NULL,
 polygon_routing_type TEXT NOT NULL,relative_location TEXT NOT NULL,relative_rotation TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX zonegraph_shapes_component_idx ON zonegraph_shapes(component_class,component_path);
CREATE TABLE zonegraph_shape_points(
 shape_path TEXT NOT NULL,point_index INTEGER NOT NULL,position TEXT NOT NULL,rotation TEXT NOT NULL,
 tangent_length TEXT NOT NULL,point_type TEXT NOT NULL,lane_profile TEXT NOT NULL,
 lane_connection_restrictions TEXT NOT NULL,raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(shape_path,point_index));
CREATE INDEX zonegraph_shape_points_shape_idx ON zonegraph_shape_points(shape_path,point_index);
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


def _unique_nonblank(rows: list[dict], field: str, label: str) -> tuple[str | None, set[str]]:
    values = [str(row.get(field, "") or "") for row in rows]
    if any(not value for value in values):
        return f"{label} has blank {field}", set()
    if len(values) != len(set(values)):
        return f"{label} has duplicate {field}", set()
    return None, set(values)


def _validate_contiguous(
    rows: list[dict],
    owner_field: str,
    index_field: str,
    label: str,
) -> str | None:
    grouped: dict[str, list[int]] = collections.defaultdict(list)
    for row in rows:
        owner = str(row.get(owner_field, "") or "")
        if not owner:
            return f"{label} has blank {owner_field}"
        grouped[owner].append(int(row.get(index_field, -1)))
    for owner, indices in grouped.items():
        if sorted(indices) != list(range(len(indices))):
            return f"{label} indices are not contiguous for {owner}"
    return None


def validation_error(output: Path, rows=None) -> str | None:
    output = Path(output)
    rows = rows or _read_rows
    configs = list(rows(output / "mass_entity_configs.jsonl"))
    traits = list(rows(output / "mass_entity_traits.jsonl"))
    spawners = list(rows(output / "mass_spawners.jsonl"))
    entity_types = list(rows(output / "mass_spawner_entity_types.jsonl"))
    generators = list(rows(output / "mass_spawner_generators.jsonl"))
    generator_assets = list(rows(output / "mass_spawn_generator_assets.jsonl"))
    agents = list(rows(output / "mass_agent_components.jsonl"))
    shapes = list(rows(output / "zonegraph_shapes.jsonl"))
    points = list(rows(output / "zonegraph_shape_points.jsonl"))

    error, config_set = _unique_nonblank(configs, "config_path", "Mass entity config")
    if error:
        return error
    error, spawner_set = _unique_nonblank(spawners, "spawner_path", "Mass spawner")
    if error:
        return error
    error, generator_asset_set = _unique_nonblank(
        generator_assets, "generator_asset_path", "Mass spawn generator asset"
    )
    if error:
        return error
    error, _ = _unique_nonblank(agents, "component_path", "Mass agent component")
    if error:
        return error
    error, shape_set = _unique_nonblank(shapes, "shape_path", "ZoneGraph shape")
    if error:
        return error

    for config in configs:
        cls = str(config.get("class_path", "") or "")
        if "MassEntityConfigAsset" not in cls:
            return f"Mass entity config has unexpected class: {config.get('config_path')} -> {cls}"
        if int(config.get("trait_count", -1)) < 0:
            return f"Mass entity config has negative trait_count: {config.get('config_path')}"

    error = _validate_contiguous(traits, "config_path", "trait_index", "Mass entity trait")
    if error:
        return error
    traits_by_config = collections.Counter(str(row.get("config_path", "")) for row in traits)
    for row in traits:
        if str(row.get("config_path", "")) not in config_set:
            return f"Mass entity trait references unknown config: {row.get('config_path')}"
    for config in configs:
        path = str(config.get("config_path", ""))
        if int(config.get("trait_count", 0) or 0) != traits_by_config[path]:
            return f"Mass entity config trait_count mismatch: {path}"

    error = _validate_contiguous(
        entity_types, "spawner_path", "entity_type_index", "Mass spawner entity type"
    )
    if error:
        return error
    error = _validate_contiguous(
        generators, "spawner_path", "generator_index", "Mass spawner generator"
    )
    if error:
        return error
    entity_counts = collections.Counter(str(row.get("spawner_path", "")) for row in entity_types)
    generator_counts = collections.Counter(str(row.get("spawner_path", "")) for row in generators)
    for row in entity_types:
        if str(row.get("spawner_path", "")) not in spawner_set:
            return f"Mass entity type references unknown spawner: {row.get('spawner_path')}"
    for row in generators:
        if str(row.get("spawner_path", "")) not in spawner_set:
            return f"Mass generator references unknown spawner: {row.get('spawner_path')}"
        target_asset = str(row.get("generator_asset_path", "") or "")
        if target_asset and target_asset not in generator_asset_set:
            return f"Mass spawner generator asset does not resolve: {target_asset}"
    for spawner in spawners:
        path = str(spawner.get("spawner_path", ""))
        if int(spawner.get("entity_type_count", 0) or 0) != entity_counts[path]:
            return f"Mass spawner entity_type_count mismatch: {path}"
        if int(spawner.get("spawn_generator_count", 0) or 0) != generator_counts[path]:
            return f"Mass spawner spawn_generator_count mismatch: {path}"

    for row in agents:
        cls = str(row.get("component_class", "") or "")
        if "MassAgentComponent" not in cls:
            return f"Mass agent component has unexpected class: {row.get('component_path')} -> {cls}"

    error = _validate_contiguous(points, "shape_path", "point_index", "ZoneGraph shape point")
    if error:
        return error
    point_counts = collections.Counter(str(row.get("shape_path", "")) for row in points)
    for row in points:
        if str(row.get("shape_path", "")) not in shape_set:
            return f"ZoneGraph point references unknown shape: {row.get('shape_path')}"
    for shape in shapes:
        path = str(shape.get("shape_path", "") or "")
        if "ZoneShape" not in str(shape.get("class_path", "") or ""):
            return f"ZoneGraph shape has unexpected class: {path} -> {shape.get('class_path')}"
        if "ZoneShapeComponent" not in str(shape.get("component_class", "") or ""):
            return f"ZoneGraph shape has unexpected component class: {path} -> {shape.get('component_class')}"
        if int(shape.get("point_count", 0) or 0) != point_counts[path]:
            return f"ZoneGraph shape point_count mismatch: {path}"

    return None


def load_database(conn, output: Path, rows=None) -> None:
    rows = rows or _read_rows
    for r in rows(output / "mass_entity_configs.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mass_entity_configs VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("config_path", ""), r.get("package_name", ""), r.get("class_path", ""),
            r.get("config_property", ""), r.get("config_guid", ""), r.get("parent_config_path", ""),
            r.get("parent_config_class", ""), int(r.get("trait_count", 0) or 0), _j(r)))
    for r in rows(output / "mass_entity_traits.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mass_entity_traits VALUES(?,?,?,?,?)", (
            r.get("config_path", ""), int(r.get("trait_index", 0) or 0), r.get("trait_path", ""),
            r.get("trait_class", ""), _j(r)))
    for r in rows(output / "mass_spawners.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mass_spawners VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("spawner_path", ""), r.get("package_name", ""), r.get("generated_class", ""),
            r.get("cdo_path", ""), int(r.get("entity_type_count", 0) or 0),
            int(r.get("spawn_generator_count", 0) or 0), r.get("count", ""),
            r.get("auto_spawn_on_begin_play", ""), _j(r)))
    for r in rows(output / "mass_spawner_entity_types.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mass_spawner_entity_types VALUES(?,?,?,?,?,?,?,?)", (
            r.get("spawner_path", ""), int(r.get("entity_type_index", 0) or 0),
            r.get("entity_config_path", ""), r.get("entity_config_class", ""), r.get("proportion", ""),
            r.get("raw_value", ""), int(bool(r.get("truncated", False))), _j(r)))
    for r in rows(output / "mass_spawner_generators.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mass_spawner_generators VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("spawner_path", ""), int(r.get("generator_index", 0) or 0), r.get("generator_path", ""),
            r.get("generator_class", ""), r.get("generator_asset_path", ""), r.get("proportion", ""),
            r.get("raw_value", ""), int(bool(r.get("truncated", False))), _j(r)))
    for r in rows(output / "mass_spawn_generator_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mass_spawn_generator_assets VALUES(?,?,?,?,?,?,?)", (
            r.get("generator_asset_path", ""), r.get("package_name", ""), r.get("generated_class", ""),
            r.get("parent_class", ""), r.get("cdo_path", ""), int(bool(r.get("zonegraph_generator", False))),
            _j(r)))
    for r in rows(output / "mass_agent_components.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mass_agent_components VALUES(?,?,?,?,?,?,?,?,?,?)", (
            r.get("component_path", ""), r.get("blueprint_path", ""), r.get("component_name", ""),
            r.get("component_class", ""), r.get("entity_config_parent_path", ""),
            r.get("entity_config_parent_class", ""), r.get("config_guid", ""),
            r.get("raw_entity_config", ""), int(bool(r.get("truncated", False))), _j(r)))
    for r in rows(output / "zonegraph_shapes.jsonl"):
        conn.execute("INSERT OR REPLACE INTO zonegraph_shapes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("shape_path", ""), r.get("package_name", ""), r.get("class_path", ""),
            r.get("component_path", ""), r.get("component_class", ""), int(r.get("point_count", 0) or 0),
            r.get("shape_type", ""), r.get("lane_profile", ""), r.get("tags", ""),
            r.get("reverse_lane_profile", ""), r.get("polygon_routing_type", ""),
            r.get("relative_location", ""), r.get("relative_rotation", ""), _j(r)))
    for r in rows(output / "zonegraph_shape_points.jsonl"):
        conn.execute("INSERT OR REPLACE INTO zonegraph_shape_points VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("shape_path", ""), int(r.get("point_index", 0) or 0), r.get("position", ""),
            r.get("rotation", ""), r.get("tangent_length", ""), r.get("point_type", ""),
            r.get("lane_profile", ""), r.get("lane_connection_restrictions", ""),
            r.get("raw_value", ""), int(bool(r.get("truncated", False))), _j(r)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mass_entity_configs'"
    ).fetchone():
        return

    print("\n[Mass entity configs / traits]")
    print_rows(conn.execute(
        """SELECT config_path,parent_config_path,trait_count,class_path
           FROM mass_entity_configs
           WHERE config_path LIKE ? OR parent_config_path LIKE ? OR class_path LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("config_path", "parent_config_path", "trait_count", "class_path"))
    print_rows(conn.execute(
        """SELECT config_path,trait_index,trait_path,trait_class FROM mass_entity_traits
           WHERE config_path LIKE ? OR trait_path LIKE ? OR trait_class LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("config_path", "trait_index", "trait_path", "trait_class"))

    print("\n[Mass spawners]")
    print_rows(conn.execute(
        """SELECT spawner_path,generated_class,entity_type_count,spawn_generator_count,count,auto_spawn_on_begin_play
           FROM mass_spawners
           WHERE spawner_path LIKE ? OR generated_class LIKE ? LIMIT ?""",
        (pattern, pattern, limit)),
        ("spawner_path", "generated_class", "entity_type_count", "spawn_generator_count", "count", "auto_spawn_on_begin_play"))
    print_rows(conn.execute(
        """SELECT spawner_path,entity_type_index,entity_config_path,proportion
           FROM mass_spawner_entity_types
           WHERE spawner_path LIKE ? OR entity_config_path LIKE ? LIMIT ?""",
        (pattern, pattern, limit)),
        ("spawner_path", "entity_type_index", "entity_config_path", "proportion"))
    print_rows(conn.execute(
        """SELECT spawner_path,generator_index,generator_asset_path,generator_class,proportion
           FROM mass_spawner_generators
           WHERE spawner_path LIKE ? OR generator_asset_path LIKE ? OR generator_class LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("spawner_path", "generator_index", "generator_asset_path", "generator_class", "proportion"))

    print("\n[Mass agents / spawn generator assets]")
    print_rows(conn.execute(
        """SELECT blueprint_path,component_name,component_class,entity_config_parent_path
           FROM mass_agent_components
           WHERE blueprint_path LIKE ? OR component_name LIKE ? OR component_class LIKE ? OR entity_config_parent_path LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, pattern, limit)),
        ("blueprint_path", "component_name", "component_class", "entity_config_parent_path"))
    print_rows(conn.execute(
        """SELECT generator_asset_path,generated_class,parent_class,zonegraph_generator
           FROM mass_spawn_generator_assets
           WHERE generator_asset_path LIKE ? OR generated_class LIKE ? OR parent_class LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("generator_asset_path", "generated_class", "parent_class", "zonegraph_generator"))

    print("\n[ZoneGraph authored shapes / points]")
    print_rows(conn.execute(
        """SELECT shape_path,point_count,shape_type,lane_profile,tags,polygon_routing_type
           FROM zonegraph_shapes
           WHERE shape_path LIKE ? OR shape_type LIKE ? OR lane_profile LIKE ? OR tags LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, pattern, limit)),
        ("shape_path", "point_count", "shape_type", "lane_profile", "tags", "polygon_routing_type"))
    print_rows(conn.execute(
        """SELECT shape_path,point_index,position,rotation,tangent_length,point_type,lane_profile
           FROM zonegraph_shape_points
           WHERE shape_path LIKE ? OR position LIKE ? OR point_type LIKE ? OR lane_profile LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, pattern, limit)),
        ("shape_path", "point_index", "position", "rotation", "tangent_length", "point_type", "lane_profile"))


def install(systems_module) -> None:
    if getattr(systems_module, "_mass_zonegraph_schema_installed", False):
        return

    original_create_schema = systems_module.create_schema
    original_validation_error = systems_module.validation_error
    original_load_database = systems_module.load_database
    original_query = systems_module.query

    systems_module.SYSTEMS_SCHEMA_VERSION = 5
    systems_module.JSONL_FILES = tuple(dict.fromkeys((*systems_module.JSONL_FILES, *MASS_ZONEGRAPH_FILES)))
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
    systems_module._mass_zonegraph_schema_installed = True
