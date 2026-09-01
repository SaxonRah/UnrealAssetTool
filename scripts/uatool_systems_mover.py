#!/usr/bin/env python3
"""Systems schema 3 Mover normalization over reflection-backed scanner rows."""
from __future__ import annotations

import collections
import json
from pathlib import Path

MOVER_FILES = (
    "mover_blueprints.jsonl",
    "mover_components.jsonl",
    "mover_modes.jsonl",
    "mover_settings.jsonl",
    "mover_transitions.jsonl",
)

_SQL = """
CREATE TABLE mover_blueprints(
 blueprint_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,mover_kind TEXT NOT NULL,
 generated_class TEXT NOT NULL,parent_class TEXT NOT NULL,cdo_path TEXT NOT NULL,cdo_class TEXT NOT NULL,
 shared_setting_class_count INTEGER NOT NULL,transition_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX mover_blueprints_kind_idx ON mover_blueprints(mover_kind,parent_class);
CREATE TABLE mover_components(
 component_path TEXT PRIMARY KEY,blueprint_path TEXT NOT NULL,component_name TEXT NOT NULL,
 component_class TEXT NOT NULL,component_kind TEXT NOT NULL,backend_class TEXT NOT NULL,
 starting_movement_mode TEXT NOT NULL,sync_inputs_for_sim_proxy TEXT NOT NULL,
 mode_count INTEGER NOT NULL,shared_setting_count INTEGER NOT NULL,transition_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX mover_components_blueprint_idx ON mover_components(blueprint_path,component_kind);
CREATE TABLE mover_modes(
 component_path TEXT NOT NULL,mode_index INTEGER NOT NULL,blueprint_path TEXT NOT NULL,mode_name TEXT NOT NULL,
 mode_path TEXT NOT NULL,mode_class TEXT NOT NULL,mode_asset_path TEXT NOT NULL,is_starting INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(component_path,mode_index));
CREATE UNIQUE INDEX mover_modes_name_idx ON mover_modes(component_path,mode_name);
CREATE INDEX mover_modes_class_idx ON mover_modes(mode_class,mode_asset_path);
CREATE TABLE mover_settings(
 owner_path TEXT NOT NULL,relation TEXT NOT NULL,setting_index INTEGER NOT NULL,asset_path TEXT NOT NULL,
 owner_kind TEXT NOT NULL,setting_path TEXT NOT NULL,setting_class TEXT NOT NULL,setting_asset_path TEXT NOT NULL,
 target_kind TEXT NOT NULL,json TEXT NOT NULL,PRIMARY KEY(owner_path,relation,setting_index));
CREATE INDEX mover_settings_target_idx ON mover_settings(setting_path,setting_class);
CREATE TABLE mover_transitions(
 owner_path TEXT NOT NULL,transition_index INTEGER NOT NULL,asset_path TEXT NOT NULL,owner_kind TEXT NOT NULL,
 transition_path TEXT NOT NULL,transition_class TEXT NOT NULL,transition_asset_path TEXT NOT NULL,target_kind TEXT NOT NULL,
 json TEXT NOT NULL,PRIMARY KEY(owner_path,transition_index));
CREATE INDEX mover_transitions_target_idx ON mover_transitions(transition_path,transition_class);
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
    blueprints = list(rows(output / "mover_blueprints.jsonl"))
    components = list(rows(output / "mover_components.jsonl"))
    modes = list(rows(output / "mover_modes.jsonl"))
    settings = list(rows(output / "mover_settings.jsonl"))
    transitions = list(rows(output / "mover_transitions.jsonl"))

    blueprint_paths = [str(row.get("blueprint_path", "")) for row in blueprints]
    if any(not path for path in blueprint_paths) or len(blueprint_paths) != len(set(blueprint_paths)):
        return "Mover Blueprint paths are blank or duplicated"
    blueprint_kinds = {
        str(row.get("blueprint_path", "")): str(row.get("mover_kind", ""))
        for row in blueprints
    }
    for path, kind in blueprint_kinds.items():
        if kind not in {"movement_mode", "movement_transition", "mover_blueprint"}:
            return f"unexpected Mover Blueprint kind: {path} -> {kind!r}"

    component_paths = [str(row.get("component_path", "")) for row in components]
    if any(not path for path in component_paths) or len(component_paths) != len(set(component_paths)):
        return "Mover component paths are blank or duplicated"
    component_set = set(component_paths)
    for row in components:
        cls = str(row.get("component_class", ""))
        if not (cls.startswith("/Script/Mover.") or cls.startswith("/Script/ChaosMover.")):
            return f"Mover component has non-Mover class: {row.get('component_path')} -> {cls}"

    modes_by_component: dict[str, list[dict]] = collections.defaultdict(list)
    for row in modes:
        component_path = str(row.get("component_path", ""))
        if component_path not in component_set:
            return f"Mover mode references unknown component: {component_path}"
        if not str(row.get("mode_name", "")) or not str(row.get("mode_path", "")):
            return f"Mover mode has blank identity for component: {component_path}"
        mode_asset = str(row.get("mode_asset_path", "") or "")
        if mode_asset and blueprint_kinds.get(mode_asset) != "movement_mode":
            return f"Mover mode asset does not resolve to movement_mode Blueprint: {row.get('mode_path')} -> {mode_asset}"
        modes_by_component[component_path].append(row)
    for component_path, values in modes_by_component.items():
        indices = sorted(int(row.get("mode_index", -1)) for row in values)
        if indices != list(range(len(values))):
            return f"Mover mode indices are not contiguous for {component_path}"
        names = [str(row.get("mode_name", "")) for row in values]
        if len(names) != len(set(names)):
            return f"Mover mode names are duplicated for {component_path}"

    settings_by_owner_relation = collections.Counter(
        (str(row.get("owner_path", "")), str(row.get("relation", ""))) for row in settings
    )
    transition_counts = collections.Counter(str(row.get("owner_path", "")) for row in transitions)
    for row in settings:
        if not str(row.get("owner_path", "")) or not str(row.get("setting_path", "")):
            return "Mover setting has blank owner/target path"
        if str(row.get("relation", "")) not in {"shared_setting", "shared_setting_class"}:
            return f"unexpected Mover setting relation: {row.get('relation')!r}"
    for row in transitions:
        if not str(row.get("owner_path", "")) or not str(row.get("transition_path", "")):
            return "Mover transition has blank owner/target path"
        transition_asset = str(row.get("transition_asset_path", "") or "")
        if transition_asset and blueprint_kinds.get(transition_asset) != "movement_transition":
            return (
                "Mover transition asset does not resolve to movement_transition Blueprint: "
                f"{row.get('transition_path')} -> {transition_asset}"
            )

    for row in components:
        component_path = str(row.get("component_path", ""))
        values = modes_by_component.get(component_path, [])
        if int(row.get("mode_count", 0) or 0) != len(values):
            return f"Mover component mode_count mismatch: {component_path}"
        if int(row.get("shared_setting_count", 0) or 0) != settings_by_owner_relation[(component_path, "shared_setting")]:
            return f"Mover component shared_setting_count mismatch: {component_path}"
        if int(row.get("transition_count", 0) or 0) != transition_counts[component_path]:
            return f"Mover component transition_count mismatch: {component_path}"
        starting = str(row.get("starting_movement_mode", "") or "")
        if starting and values:
            matches = [value for value in values if str(value.get("mode_name", "")) == starting]
            if len(matches) != 1 or not bool(matches[0].get("is_starting", False)):
                return f"Mover starting mode does not resolve uniquely: {component_path} -> {starting}"

    for row in blueprints:
        cdo = str(row.get("cdo_path", "") or "")
        if int(row.get("shared_setting_class_count", 0) or 0) != settings_by_owner_relation[(cdo, "shared_setting_class")]:
            return f"Mover Blueprint shared_setting_class_count mismatch: {row.get('blueprint_path')}"
        if int(row.get("transition_count", 0) or 0) != transition_counts[cdo]:
            return f"Mover Blueprint transition_count mismatch: {row.get('blueprint_path')}"

    return None


def load_database(conn, output: Path, rows=None) -> None:
    rows = rows or _read_rows
    for r in rows(output / "mover_blueprints.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mover_blueprints VALUES(?,?,?,?,?,?,?,?,?,?)", (
            r.get("blueprint_path", ""), r.get("package_name", ""), r.get("mover_kind", ""),
            r.get("generated_class", ""), r.get("parent_class", ""), r.get("cdo_path", ""),
            r.get("cdo_class", ""), int(r.get("shared_setting_class_count", 0) or 0),
            int(r.get("transition_count", 0) or 0), _j(r)))
    for r in rows(output / "mover_components.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mover_components VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (
            r.get("component_path", ""), r.get("blueprint_path", ""), r.get("component_name", ""),
            r.get("component_class", ""), r.get("component_kind", ""), r.get("backend_class", ""),
            r.get("starting_movement_mode", ""), r.get("sync_inputs_for_sim_proxy", ""),
            int(r.get("mode_count", 0) or 0), int(r.get("shared_setting_count", 0) or 0),
            int(r.get("transition_count", 0) or 0), _j(r)))
    for r in rows(output / "mover_modes.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mover_modes VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("component_path", ""), int(r.get("mode_index", 0) or 0), r.get("blueprint_path", ""),
            r.get("mode_name", ""), r.get("mode_path", ""), r.get("mode_class", ""),
            r.get("mode_asset_path", ""), int(bool(r.get("is_starting", False))), _j(r)))
    for r in rows(output / "mover_settings.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mover_settings VALUES(?,?,?,?,?,?,?,?,?,?)", (
            r.get("owner_path", ""), r.get("relation", ""), int(r.get("setting_index", 0) or 0),
            r.get("asset_path", ""), r.get("owner_kind", ""), r.get("setting_path", ""),
            r.get("setting_class", ""), r.get("setting_asset_path", ""), r.get("target_kind", ""), _j(r)))
    for r in rows(output / "mover_transitions.jsonl"):
        conn.execute("INSERT OR REPLACE INTO mover_transitions VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("owner_path", ""), int(r.get("transition_index", 0) or 0), r.get("asset_path", ""),
            r.get("owner_kind", ""), r.get("transition_path", ""), r.get("transition_class", ""),
            r.get("transition_asset_path", ""), r.get("target_kind", ""), _j(r)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mover_components'").fetchone():
        return
    print("\n[Mover components]")
    print_rows(conn.execute(
        """SELECT blueprint_path,component_name,component_kind,component_class,starting_movement_mode,backend_class,mode_count
           FROM mover_components
           WHERE blueprint_path LIKE ? OR component_name LIKE ? OR component_class LIKE ? OR starting_movement_mode LIKE ? OR backend_class LIKE ?
           LIMIT ?""",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("blueprint_path", "component_name", "component_kind", "component_class", "starting_movement_mode", "backend_class", "mode_count"))
    print("\n[Mover modes]")
    print_rows(conn.execute(
        """SELECT blueprint_path,component_path,mode_name,mode_class,mode_asset_path,is_starting
           FROM mover_modes
           WHERE blueprint_path LIKE ? OR component_path LIKE ? OR mode_name LIKE ? OR mode_class LIKE ? OR mode_asset_path LIKE ?
           LIMIT ?""",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("blueprint_path", "component_path", "mode_name", "mode_class", "mode_asset_path", "is_starting"))
    print("\n[Mover settings / transitions]")
    print_rows(conn.execute(
        """SELECT asset_path,owner_path,owner_kind,relation,setting_path,setting_class
           FROM mover_settings
           WHERE asset_path LIKE ? OR owner_path LIKE ? OR relation LIKE ? OR setting_path LIKE ? OR setting_class LIKE ?
           LIMIT ?""",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("asset_path", "owner_path", "owner_kind", "relation", "setting_path", "setting_class"))
    print_rows(conn.execute(
        """SELECT asset_path,owner_path,owner_kind,transition_path,transition_class,transition_asset_path
           FROM mover_transitions
           WHERE asset_path LIKE ? OR owner_path LIKE ? OR transition_path LIKE ? OR transition_class LIKE ? OR transition_asset_path LIKE ?
           LIMIT ?""",
        (pattern, pattern, pattern, pattern, pattern, limit)),
        ("asset_path", "owner_path", "owner_kind", "transition_path", "transition_class", "transition_asset_path"))


def install(systems_module) -> None:
    if getattr(systems_module, "_mover_schema_installed", False):
        return

    original_create_schema = systems_module.create_schema
    original_validation_error = systems_module.validation_error
    original_load_database = systems_module.load_database
    original_query = systems_module.query

    systems_module.SYSTEMS_SCHEMA_VERSION = 3
    systems_module.JSONL_FILES = tuple(dict.fromkeys((*systems_module.JSONL_FILES, *MOVER_FILES)))
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
    systems_module._mover_schema_installed = True
