#!/usr/bin/env python3
"""Systems schema 7 Smart Objects normalization, validation and SQLite support."""
from __future__ import annotations

import collections
import json
from pathlib import Path

SMARTOBJECT_FILES = (
    "smartobject_definitions.jsonl",
    "smartobject_slots.jsonl",
    "smartobject_behaviors.jsonl",
    "smartobject_behavior_properties.jsonl",
)

_SQL = """
CREATE TABLE smartobject_definitions(
 definition_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,class_path TEXT NOT NULL,
 slot_count INTEGER NOT NULL,default_behavior_count INTEGER NOT NULL,
 activity_tags TEXT NOT NULL,user_tag_filter TEXT NOT NULL,object_tag_filter TEXT NOT NULL,
 preconditions TEXT NOT NULL,world_condition_schema_class TEXT NOT NULL,
 activity_tags_merging_policy TEXT NOT NULL,user_tags_filtering_policy TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX smartobject_definitions_class_idx ON smartobject_definitions(class_path,definition_path);
CREATE TABLE smartobject_slots(
 definition_path TEXT NOT NULL,slot_index INTEGER NOT NULL,slot_id TEXT NOT NULL,name TEXT NOT NULL,enabled INTEGER NOT NULL,
 offset_x REAL NOT NULL,offset_y REAL NOT NULL,offset_z REAL NOT NULL,
 rotation_pitch REAL NOT NULL,rotation_yaw REAL NOT NULL,rotation_roll REAL NOT NULL,
 user_tag_filter TEXT NOT NULL,activity_tags TEXT NOT NULL,runtime_tags TEXT NOT NULL,
 selection_preconditions TEXT NOT NULL,selection_schema_class TEXT NOT NULL,
 behavior_count INTEGER NOT NULL,definition_data_count INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(definition_path,slot_index));
CREATE UNIQUE INDEX smartobject_slots_id_idx ON smartobject_slots(definition_path,slot_id);
CREATE TABLE smartobject_behaviors(
 definition_path TEXT NOT NULL,scope TEXT NOT NULL,slot_index INTEGER NOT NULL,behavior_index INTEGER NOT NULL,
 behavior_path TEXT NOT NULL,behavior_class TEXT NOT NULL,property_count INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(definition_path,scope,slot_index,behavior_index));
CREATE INDEX smartobject_behaviors_path_idx ON smartobject_behaviors(behavior_path,behavior_class);
CREATE TABLE smartobject_behavior_properties(
 definition_path TEXT NOT NULL,behavior_path TEXT NOT NULL,property_index INTEGER NOT NULL,
 declaring_type TEXT NOT NULL,property_name TEXT NOT NULL,property_type TEXT NOT NULL,cpp_type TEXT NOT NULL,
 value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(definition_path,behavior_path,property_index));
CREATE INDEX smartobject_behavior_properties_name_idx ON smartobject_behavior_properties(property_name,behavior_path);
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


def _group_contiguous(rows: list[dict], owner_fields: tuple[str, ...], index_field: str, label: str) -> str | None:
    grouped: dict[tuple[str, ...], list[int]] = collections.defaultdict(list)
    for row in rows:
        owner = tuple(str(row.get(field, "") if row.get(field) is not None else "") for field in owner_fields)
        if any(not part for part in owner):
            return f"{label} has blank owner field"
        grouped[owner].append(int(row.get(index_field, -1)))
    for owner, indices in grouped.items():
        if sorted(indices) != list(range(len(indices))):
            return f"{label} indices are not contiguous for {' / '.join(owner)}"
    return None


def validation_error(output: Path, rows=None) -> str | None:
    output = Path(output)
    rows = rows or _read_rows
    definitions = list(rows(output / "smartobject_definitions.jsonl"))
    slots = list(rows(output / "smartobject_slots.jsonl"))
    behaviors = list(rows(output / "smartobject_behaviors.jsonl"))
    properties = list(rows(output / "smartobject_behavior_properties.jsonl"))

    error, definition_paths = _unique_nonblank(definitions, "definition_path", "Smart Object definition")
    if error:
        return error

    for row in definitions:
        path = str(row.get("definition_path", "") or "")
        package = str(row.get("package_name", "") or "")
        class_path = str(row.get("class_path", "") or "")
        if "." not in path or not package or not class_path:
            return f"Smart Object definition has incomplete identity: {path or '<blank>'}"
        if path.rsplit(".", 1)[0] != package:
            return f"Smart Object definition package mismatch: {path} -> {package}"
        if not class_path.endswith(".SmartObjectDefinition") and "SmartObjectDefinition" not in class_path:
            return f"Smart Object definition has unexpected class identity: {path} -> {class_path}"
        if int(row.get("slot_count", -1)) < 0 or int(row.get("default_behavior_count", -1)) < 0:
            return f"Smart Object definition has negative child count: {path}"

    error = _group_contiguous(slots, ("definition_path",), "slot_index", "Smart Object slot")
    if error:
        return error
    slot_counts = collections.Counter()
    slot_ids: dict[str, set[str]] = collections.defaultdict(set)
    for row in slots:
        definition = str(row.get("definition_path", "") or "")
        slot_id = str(row.get("slot_id", "") or "")
        if definition not in definition_paths:
            return f"Smart Object slot owner does not resolve: {definition}"
        if not slot_id:
            return f"Smart Object slot has blank slot_id: {definition}[{row.get('slot_index')}]"
        if slot_id in slot_ids[definition]:
            return f"Smart Object slot_id is duplicated for {definition}: {slot_id}"
        slot_ids[definition].add(slot_id)
        slot_counts[definition] += 1
        if int(row.get("behavior_count", -1)) < 0 or int(row.get("definition_data_count", -1)) < 0:
            return f"Smart Object slot has negative child count: {definition}[{row.get('slot_index')}]"

    for row in definitions:
        definition = str(row.get("definition_path", "") or "")
        if int(row.get("slot_count", 0) or 0) != slot_counts.get(definition, 0):
            return (
                f"Smart Object slot count mismatch for {definition}: "
                f"declared={row.get('slot_count')} actual={slot_counts.get(definition, 0)}"
            )

    behavior_groups: dict[tuple[str, str, int], list[int]] = collections.defaultdict(list)
    behavior_keys: set[tuple[str, str, int, int]] = set()
    default_counts = collections.Counter()
    slot_behavior_counts = collections.Counter()
    behavior_paths: set[tuple[str, str]] = set()
    for row in behaviors:
        definition = str(row.get("definition_path", "") or "")
        scope = str(row.get("scope", "") or "")
        slot_index = int(row.get("slot_index", -999))
        behavior_index = int(row.get("behavior_index", -1))
        behavior_path = str(row.get("behavior_path", "") or "")
        behavior_class = str(row.get("behavior_class", "") or "")
        if definition not in definition_paths:
            return f"Smart Object behavior owner does not resolve: {definition}"
        if scope not in {"default", "slot"}:
            return f"Smart Object behavior has invalid scope: {scope}"
        if scope == "default" and slot_index != -1:
            return f"Smart Object default behavior must use slot_index=-1: {definition}"
        if scope == "slot" and slot_index < 0:
            return f"Smart Object slot behavior has invalid slot_index: {definition}"
        if not behavior_path or not behavior_class:
            return f"Smart Object behavior has incomplete identity: {definition} {scope}[{behavior_index}]"
        if int(row.get("property_count", -1)) < 0:
            return f"Smart Object behavior has negative property_count: {behavior_path}"
        key = (definition, scope, slot_index, behavior_index)
        if key in behavior_keys:
            return f"Smart Object behavior key is duplicated: {key}"
        behavior_keys.add(key)
        behavior_groups[(definition, scope, slot_index)].append(behavior_index)
        behavior_paths.add((definition, behavior_path))
        if scope == "default":
            default_counts[definition] += 1
        else:
            slot_behavior_counts[(definition, slot_index)] += 1

    for owner, indices in behavior_groups.items():
        if sorted(indices) != list(range(len(indices))):
            return f"Smart Object behavior indices are not contiguous for {owner}"

    for row in definitions:
        definition = str(row.get("definition_path", "") or "")
        if int(row.get("default_behavior_count", 0) or 0) != default_counts.get(definition, 0):
            return (
                f"Smart Object default behavior count mismatch for {definition}: "
                f"declared={row.get('default_behavior_count')} actual={default_counts.get(definition, 0)}"
            )
    for row in slots:
        key = (str(row.get("definition_path", "") or ""), int(row.get("slot_index", -1)))
        if int(row.get("behavior_count", 0) or 0) != slot_behavior_counts.get(key, 0):
            return (
                f"Smart Object slot behavior count mismatch for {key[0]}[{key[1]}]: "
                f"declared={row.get('behavior_count')} actual={slot_behavior_counts.get(key, 0)}"
            )

    property_groups: dict[tuple[str, str], list[int]] = collections.defaultdict(list)
    for row in properties:
        definition = str(row.get("definition_path", "") or "")
        behavior_path = str(row.get("behavior_path", "") or "")
        if (definition, behavior_path) not in behavior_paths:
            return f"Smart Object behavior property owner does not resolve: {definition} -> {behavior_path}"
        if bool(row.get("truncated", False)):
            return f"Smart Object behavior property is truncated: {behavior_path}::{row.get('property_name')}"
        property_groups[(definition, behavior_path)].append(int(row.get("property_index", -1)))
    for owner, indices in property_groups.items():
        if sorted(indices) != list(range(len(indices))):
            return f"Smart Object behavior property indices are not contiguous for {owner[1]}"

    actual_property_counts = collections.Counter({key: len(indices) for key, indices in property_groups.items()})
    for row in behaviors:
        key = (str(row.get("definition_path", "") or ""), str(row.get("behavior_path", "") or ""))
        if int(row.get("property_count", 0) or 0) != actual_property_counts.get(key, 0):
            return (
                f"Smart Object behavior property count mismatch for {key[1]}: "
                f"declared={row.get('property_count')} actual={actual_property_counts.get(key, 0)}"
            )
    return None


def load_database(conn, output: Path, rows=None) -> None:
    output = Path(output)
    rows = rows or _read_rows
    for r in rows(output / "smartobject_definitions.jsonl"):
        conn.execute("INSERT OR REPLACE INTO smartobject_definitions VALUES(" + ",".join("?" * 13) + ")", (
            r.get("definition_path", ""), r.get("package_name", ""), r.get("class_path", ""),
            int(r.get("slot_count", 0) or 0), int(r.get("default_behavior_count", 0) or 0),
            r.get("activity_tags", ""), r.get("user_tag_filter", ""), r.get("object_tag_filter", ""),
            r.get("preconditions", ""), r.get("world_condition_schema_class", ""),
            r.get("activity_tags_merging_policy", ""), r.get("user_tags_filtering_policy", ""), _j(r)))
    for r in rows(output / "smartobject_slots.jsonl"):
        conn.execute("INSERT OR REPLACE INTO smartobject_slots VALUES(" + ",".join("?" * 19) + ")", (
            r.get("definition_path", ""), int(r.get("slot_index", 0) or 0), r.get("slot_id", ""), r.get("name", ""),
            int(bool(r.get("enabled", False))), float(r.get("offset_x", 0.0) or 0.0), float(r.get("offset_y", 0.0) or 0.0),
            float(r.get("offset_z", 0.0) or 0.0), float(r.get("rotation_pitch", 0.0) or 0.0),
            float(r.get("rotation_yaw", 0.0) or 0.0), float(r.get("rotation_roll", 0.0) or 0.0),
            r.get("user_tag_filter", ""), r.get("activity_tags", ""), r.get("runtime_tags", ""),
            r.get("selection_preconditions", ""), r.get("selection_schema_class", ""),
            int(r.get("behavior_count", 0) or 0), int(r.get("definition_data_count", 0) or 0), _j(r)))
    for r in rows(output / "smartobject_behaviors.jsonl"):
        conn.execute("INSERT OR REPLACE INTO smartobject_behaviors VALUES(?,?,?,?,?,?,?,?)", (
            r.get("definition_path", ""), r.get("scope", ""), int(r.get("slot_index", -1)),
            int(r.get("behavior_index", 0) or 0), r.get("behavior_path", ""), r.get("behavior_class", ""),
            int(r.get("property_count", 0) or 0), _j(r)))
    for r in rows(output / "smartobject_behavior_properties.jsonl"):
        conn.execute("INSERT OR REPLACE INTO smartobject_behavior_properties VALUES(?,?,?,?,?,?,?,?,?,?)", (
            r.get("definition_path", ""), r.get("behavior_path", ""), int(r.get("property_index", 0) or 0),
            r.get("declaring_type", ""), r.get("property_name", ""), r.get("property_type", ""), r.get("cpp_type", ""),
            r.get("value", ""), int(bool(r.get("truncated", False))), _j(r)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='smartobject_definitions'").fetchone():
        return
    print("\n[Smart Object definitions]")
    print_rows(conn.execute(
        """SELECT definition_path,slot_count,default_behavior_count,activity_tags_merging_policy,user_tags_filtering_policy
           FROM smartobject_definitions WHERE definition_path LIKE ? OR class_path LIKE ? LIMIT ?""",
        (pattern, pattern, limit)),
        ("definition_path", "slots", "default_behaviors", "activity_tag_policy", "user_tag_policy"))
    print("\n[Smart Object slots]")
    print_rows(conn.execute(
        """SELECT definition_path,slot_index,slot_id,name,enabled,offset_x,offset_y,offset_z,rotation_yaw,behavior_count
           FROM smartobject_slots WHERE definition_path LIKE ? OR slot_id LIKE ? OR name LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("definition_path", "slot_index", "slot_id", "name", "enabled", "x", "y", "z", "yaw", "behaviors"))
    print("\n[Smart Object behaviors]")
    print_rows(conn.execute(
        """SELECT definition_path,scope,slot_index,behavior_index,behavior_path,behavior_class,property_count
           FROM smartobject_behaviors WHERE definition_path LIKE ? OR behavior_path LIKE ? OR behavior_class LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("definition_path", "scope", "slot", "index", "behavior_path", "behavior_class", "properties"))
    print_rows(conn.execute(
        """SELECT behavior_path,property_index,property_name,value FROM smartobject_behavior_properties
           WHERE behavior_path LIKE ? OR property_name LIKE ? OR value LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("behavior_path", "index", "property", "value"))


def install(systems_module) -> None:
    if getattr(systems_module, "_smartobjects_schema_installed", False):
        return
    original_create_schema = systems_module.create_schema
    original_validation_error = systems_module.validation_error
    original_load_database = systems_module.load_database
    original_query = systems_module.query

    systems_module.SYSTEMS_SCHEMA_VERSION = 7
    systems_module.JSONL_FILES = tuple(dict.fromkeys((*systems_module.JSONL_FILES, *SMARTOBJECT_FILES)))
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
    systems_module._smartobjects_schema_installed = True
