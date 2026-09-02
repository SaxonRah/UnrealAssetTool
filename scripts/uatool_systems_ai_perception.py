#!/usr/bin/env python3
"""Systems schema 8 AI Perception normalization, validation and SQLite support."""
from __future__ import annotations

import collections
import json
from pathlib import Path

AI_PERCEPTION_FILES = (
    "ai_perception_components.jsonl",
    "ai_perception_sense_configs.jsonl",
    "ai_perception_stimuli_sources.jsonl",
    "ai_perception_registered_senses.jsonl",
    "ai_perception_properties.jsonl",
)

_SQL = """
CREATE TABLE ai_perception_components(
 blueprint_path TEXT NOT NULL,generated_class TEXT NOT NULL,component_path TEXT PRIMARY KEY,
 component_name TEXT NOT NULL,component_class TEXT NOT NULL,dominant_sense_class TEXT NOT NULL,
 sense_config_count INTEGER NOT NULL,property_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX ai_perception_components_blueprint_idx ON ai_perception_components(blueprint_path,component_path);
CREATE TABLE ai_perception_sense_configs(
 blueprint_path TEXT NOT NULL,component_path TEXT NOT NULL,config_index INTEGER NOT NULL,
 config_path TEXT NOT NULL,config_class TEXT NOT NULL,implementation_class TEXT NOT NULL,is_null INTEGER NOT NULL,
 max_age REAL,detection_by_affiliation TEXT NOT NULL,detect_enemies INTEGER,detect_neutrals INTEGER,detect_friendlies INTEGER,
 hearing_range REAL,sight_radius REAL,lose_sight_radius REAL,peripheral_vision_angle_degrees REAL,
 property_count INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(component_path,config_index));
CREATE INDEX ai_perception_sense_configs_path_idx ON ai_perception_sense_configs(config_path,config_class,implementation_class);
CREATE TABLE ai_perception_stimuli_sources(
 blueprint_path TEXT NOT NULL,generated_class TEXT NOT NULL,component_path TEXT PRIMARY KEY,
 component_name TEXT NOT NULL,component_class TEXT NOT NULL,auto_register_as_source INTEGER NOT NULL,
 registered_sense_count INTEGER NOT NULL,property_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX ai_perception_stimuli_sources_blueprint_idx ON ai_perception_stimuli_sources(blueprint_path,component_path);
CREATE TABLE ai_perception_registered_senses(
 blueprint_path TEXT NOT NULL,component_path TEXT NOT NULL,sense_index INTEGER NOT NULL,
 sense_class TEXT NOT NULL,is_null INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(component_path,sense_index));
CREATE INDEX ai_perception_registered_senses_class_idx ON ai_perception_registered_senses(sense_class,component_path);
CREATE TABLE ai_perception_properties(
 blueprint_path TEXT NOT NULL,owner_path TEXT NOT NULL,owner_kind TEXT NOT NULL,property_index INTEGER NOT NULL,
 declaring_type TEXT NOT NULL,property_name TEXT NOT NULL,property_path TEXT NOT NULL,property_type TEXT NOT NULL,
 cpp_type TEXT NOT NULL,value TEXT NOT NULL,class_default_value TEXT NOT NULL,class_default_present INTEGER NOT NULL,
 differs_from_class_default INTEGER NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(owner_path,property_index));
CREATE INDEX ai_perception_properties_name_idx ON ai_perception_properties(property_name,owner_path);
CREATE INDEX ai_perception_properties_changed_idx ON ai_perception_properties(differs_from_class_default,owner_kind,owner_path);
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


def _nonnull_float(value):
    return None if value is None or value == "" else float(value)


def _nonnull_bool(value):
    return None if value is None else int(bool(value))


def _unique_nonblank(rows: list[dict], field: str, label: str) -> tuple[str | None, set[str]]:
    values = [str(row.get(field, "") or "") for row in rows]
    if any(not value for value in values):
        return f"{label} has blank {field}", set()
    if len(values) != len(set(values)):
        return f"{label} has duplicate {field}", set()
    return None, set(values)


def _contiguous(rows: list[dict], owner_field: str, index_field: str, label: str) -> str | None:
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
    components = list(rows(output / "ai_perception_components.jsonl"))
    configs = list(rows(output / "ai_perception_sense_configs.jsonl"))
    sources = list(rows(output / "ai_perception_stimuli_sources.jsonl"))
    registered = list(rows(output / "ai_perception_registered_senses.jsonl"))
    properties = list(rows(output / "ai_perception_properties.jsonl"))

    error, component_paths = _unique_nonblank(components, "component_path", "AI Perception component")
    if error:
        return error
    error, source_paths = _unique_nonblank(sources, "component_path", "AI Perception stimuli source")
    if error:
        return error

    owner_blueprints: dict[str, str] = {}
    owner_kinds: dict[str, str] = {}
    declared_property_counts: dict[str, int] = {}
    for row in components:
        path = str(row.get("component_path", "") or "")
        blueprint = str(row.get("blueprint_path", "") or "")
        generated = str(row.get("generated_class", "") or "")
        class_path = str(row.get("component_class", "") or "")
        if not blueprint or not generated or "AIPerceptionComponent" not in class_path or "StimuliSource" in class_path:
            return f"AI Perception component has incomplete/unexpected identity: {path}"
        if int(row.get("sense_config_count", -1)) < 0 or int(row.get("property_count", -1)) < 0:
            return f"AI Perception component has negative child count: {path}"
        owner_blueprints[path] = blueprint
        owner_kinds[path] = "perception_component_template"
        declared_property_counts[path] = int(row.get("property_count", 0) or 0)

    error = _contiguous(configs, "component_path", "config_index", "AI Perception sense config")
    if error:
        return error
    config_counts = collections.Counter()
    seen_config_paths: set[str] = set()
    for row in configs:
        component = str(row.get("component_path", "") or "")
        path = str(row.get("config_path", "") or "")
        blueprint = str(row.get("blueprint_path", "") or "")
        config_class = str(row.get("config_class", "") or "")
        implementation = str(row.get("implementation_class", "") or "")
        is_null = bool(row.get("is_null", False))
        if component not in component_paths:
            return f"AI Perception sense config owner does not resolve: {component}"
        if blueprint != owner_blueprints.get(component):
            return f"AI Perception sense config blueprint mismatch: {component}[{row.get('config_index')}]"
        if is_null:
            if path or config_class or implementation or int(row.get("property_count", 0) or 0) != 0:
                return f"AI Perception null sense config carries object state: {component}[{row.get('config_index')}]"
        else:
            if not path or path in seen_config_paths:
                return f"AI Perception sense config has blank/duplicate config_path: {path or '<blank>'}"
            seen_config_paths.add(path)
            if "AISenseConfig" not in config_class:
                return f"AI Perception sense config has unexpected class: {path} -> {config_class}"
            if int(row.get("property_count", -1)) < 0:
                return f"AI Perception sense config has negative property_count: {path}"
            owner_blueprints[path] = blueprint
            owner_kinds[path] = "sense_config"
            declared_property_counts[path] = int(row.get("property_count", 0) or 0)
        config_counts[component] += 1
    for row in components:
        component = str(row.get("component_path", "") or "")
        actual = int(config_counts.get(component, 0))
        if int(row.get("sense_config_count", 0) or 0) != actual:
            return f"AI Perception sense config count mismatch for {component}: declared={row.get('sense_config_count')} actual={actual}"

    for row in sources:
        path = str(row.get("component_path", "") or "")
        blueprint = str(row.get("blueprint_path", "") or "")
        generated = str(row.get("generated_class", "") or "")
        class_path = str(row.get("component_class", "") or "")
        if not blueprint or not generated or "AIPerceptionStimuliSourceComponent" not in class_path:
            return f"AI Perception stimuli source has incomplete/unexpected identity: {path}"
        if int(row.get("registered_sense_count", -1)) < 0 or int(row.get("property_count", -1)) < 0:
            return f"AI Perception stimuli source has negative child count: {path}"
        owner_blueprints[path] = blueprint
        owner_kinds[path] = "stimuli_source_component_template"
        declared_property_counts[path] = int(row.get("property_count", 0) or 0)

    error = _contiguous(registered, "component_path", "sense_index", "AI Perception registered sense")
    if error:
        return error
    registered_counts = collections.Counter()
    for row in registered:
        component = str(row.get("component_path", "") or "")
        blueprint = str(row.get("blueprint_path", "") or "")
        sense_class = str(row.get("sense_class", "") or "")
        is_null = bool(row.get("is_null", False))
        if component not in source_paths:
            return f"AI Perception registered sense owner does not resolve: {component}"
        if blueprint != owner_blueprints.get(component):
            return f"AI Perception registered sense blueprint mismatch: {component}[{row.get('sense_index')}]"
        if is_null != (not sense_class):
            return f"AI Perception registered sense null identity mismatch: {component}[{row.get('sense_index')}]"
        registered_counts[component] += 1
    for row in sources:
        component = str(row.get("component_path", "") or "")
        actual = int(registered_counts.get(component, 0))
        if int(row.get("registered_sense_count", 0) or 0) != actual:
            return f"AI Perception registered sense count mismatch for {component}: declared={row.get('registered_sense_count')} actual={actual}"

    property_indices: dict[str, list[int]] = collections.defaultdict(list)
    for row in properties:
        owner = str(row.get("owner_path", "") or "")
        blueprint = str(row.get("blueprint_path", "") or "")
        kind = str(row.get("owner_kind", "") or "")
        if owner not in owner_blueprints:
            return f"AI Perception property owner does not resolve: {owner}"
        if blueprint != owner_blueprints[owner] or kind != owner_kinds[owner]:
            return f"AI Perception property owner metadata mismatch: {owner}"
        if not str(row.get("property_name", "") or "") or not str(row.get("property_path", "") or ""):
            return f"AI Perception property has blank property identity: {owner}"
        if bool(row.get("truncated", False)):
            return f"AI Perception canonical property is truncated: {owner}::{row.get('property_path')}"
        property_indices[owner].append(int(row.get("property_index", -1)))
    for owner, indices in property_indices.items():
        if sorted(indices) != list(range(len(indices))):
            return f"AI Perception property indices are not contiguous for {owner}"
    for owner, declared in declared_property_counts.items():
        actual = len(property_indices.get(owner, ()))
        if declared != actual:
            return f"AI Perception property count mismatch for {owner}: declared={declared} actual={actual}"
    return None


def load_database(conn, output: Path, rows=None) -> None:
    output = Path(output)
    rows = rows or _read_rows
    for r in rows(output / "ai_perception_components.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ai_perception_components VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("blueprint_path", ""), r.get("generated_class", ""), r.get("component_path", ""),
            r.get("component_name", ""), r.get("component_class", ""), r.get("dominant_sense_class", ""),
            int(r.get("sense_config_count", 0) or 0), int(r.get("property_count", 0) or 0), _j(r)))
    for r in rows(output / "ai_perception_sense_configs.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ai_perception_sense_configs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("blueprint_path", ""), r.get("component_path", ""), int(r.get("config_index", 0) or 0),
            r.get("config_path", ""), r.get("config_class", ""), r.get("implementation_class", ""), int(bool(r.get("is_null", False))),
            _nonnull_float(r.get("max_age")), r.get("detection_by_affiliation", ""),
            _nonnull_bool(r.get("detect_enemies")), _nonnull_bool(r.get("detect_neutrals")), _nonnull_bool(r.get("detect_friendlies")),
            _nonnull_float(r.get("hearing_range")), _nonnull_float(r.get("sight_radius")), _nonnull_float(r.get("lose_sight_radius")),
            _nonnull_float(r.get("peripheral_vision_angle_degrees")), int(r.get("property_count", 0) or 0), _j(r)))
    for r in rows(output / "ai_perception_stimuli_sources.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ai_perception_stimuli_sources VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("blueprint_path", ""), r.get("generated_class", ""), r.get("component_path", ""),
            r.get("component_name", ""), r.get("component_class", ""), int(bool(r.get("auto_register_as_source", False))),
            int(r.get("registered_sense_count", 0) or 0), int(r.get("property_count", 0) or 0), _j(r)))
    for r in rows(output / "ai_perception_registered_senses.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ai_perception_registered_senses VALUES(?,?,?,?,?,?)", (
            r.get("blueprint_path", ""), r.get("component_path", ""), int(r.get("sense_index", 0) or 0),
            r.get("sense_class", ""), int(bool(r.get("is_null", False))), _j(r)))
    for r in rows(output / "ai_perception_properties.jsonl"):
        conn.execute("INSERT OR REPLACE INTO ai_perception_properties VALUES(" + ",".join("?" * 15) + ")", (
            r.get("blueprint_path", ""), r.get("owner_path", ""), r.get("owner_kind", ""), int(r.get("property_index", 0) or 0),
            r.get("declaring_type", ""), r.get("property_name", ""), r.get("property_path", ""), r.get("property_type", ""),
            r.get("cpp_type", ""), r.get("value", ""), r.get("class_default_value", ""), int(bool(r.get("class_default_present", False))),
            int(bool(r.get("differs_from_class_default", False))), int(bool(r.get("truncated", False))), _j(r)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_perception_components'").fetchone():
        return
    print("\n[AI Perception components]")
    print_rows(conn.execute(
        """SELECT blueprint_path,component_path,dominant_sense_class,sense_config_count,property_count
           FROM ai_perception_components WHERE blueprint_path LIKE ? OR component_path LIKE ? OR dominant_sense_class LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("blueprint", "component", "dominant_sense", "configs", "properties"))
    print("\n[AI Perception sense configs]")
    print_rows(conn.execute(
        """SELECT component_path,config_index,config_path,config_class,implementation_class,is_null,max_age,hearing_range,sight_radius,lose_sight_radius,peripheral_vision_angle_degrees
           FROM ai_perception_sense_configs WHERE component_path LIKE ? OR config_path LIKE ? OR config_class LIKE ? OR implementation_class LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, pattern, limit)),
        ("component", "index", "config", "config_class", "implementation", "is_null", "max_age", "hearing_range", "sight_radius", "lose_sight_radius", "peripheral_angle"))
    print("\n[AI Perception stimuli sources]")
    print_rows(conn.execute(
        """SELECT blueprint_path,component_path,auto_register_as_source,registered_sense_count,property_count
           FROM ai_perception_stimuli_sources WHERE blueprint_path LIKE ? OR component_path LIKE ? LIMIT ?""",
        (pattern, pattern, limit)),
        ("blueprint", "component", "auto_register", "registered_senses", "properties"))
    print_rows(conn.execute(
        """SELECT component_path,sense_index,sense_class,is_null FROM ai_perception_registered_senses
           WHERE component_path LIKE ? OR sense_class LIKE ? LIMIT ?""",
        (pattern, pattern, limit)),
        ("component", "index", "sense_class", "is_null"))
    print("\n[AI Perception authored/default differences]")
    print_rows(conn.execute(
        """SELECT owner_path,property_index,property_path,value,class_default_value FROM ai_perception_properties
           WHERE differs_from_class_default=1 AND (owner_path LIKE ? OR property_path LIKE ? OR value LIKE ?) LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("owner", "index", "property", "value", "class_default"))


def install(systems_module) -> None:
    if getattr(systems_module, "_ai_perception_schema_installed", False):
        return
    original_create_schema = systems_module.create_schema
    original_validation_error = systems_module.validation_error
    original_load_database = systems_module.load_database
    original_query = systems_module.query

    systems_module.SYSTEMS_SCHEMA_VERSION = 8
    systems_module.JSONL_FILES = tuple(dict.fromkeys((*systems_module.JSONL_FILES, *AI_PERCEPTION_FILES)))
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
    systems_module._ai_perception_schema_installed = True
