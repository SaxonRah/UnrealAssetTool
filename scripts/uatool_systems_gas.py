#!/usr/bin/env python3
"""Systems schema 6 Gameplay Ability System normalization and validation."""
from __future__ import annotations

import collections
import json
from pathlib import Path

GAS_FILES = (
    "gas_abilities.jsonl",
    "gas_ability_triggers.jsonl",
    "gas_ability_costs.jsonl",
    "gas_ability_sets.jsonl",
    "gas_ability_set_abilities.jsonl",
    "gas_ability_set_effects.jsonl",
    "gas_ability_set_attributes.jsonl",
    "gas_gameplay_effects.jsonl",
    "gas_gameplay_effect_components.jsonl",
    "gas_gameplay_effect_modifiers.jsonl",
    "gas_gameplay_effect_executions.jsonl",
    "gas_gameplay_effect_execution_modifiers.jsonl",
    "gas_gameplay_effect_cues.jsonl",
    "gas_gameplay_cues.jsonl",
    "gas_attribute_sets.jsonl",
    "gas_attributes.jsonl",
)

_SQL = """
CREATE TABLE gas_abilities(
 ability_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,generated_class TEXT NOT NULL,parent_class TEXT NOT NULL,
 cdo_path TEXT NOT NULL,activation_policy TEXT NOT NULL,activation_group TEXT NOT NULL,
 replication_policy TEXT NOT NULL,instancing_policy TEXT NOT NULL,net_execution_policy TEXT NOT NULL,
 net_security_policy TEXT NOT NULL,ability_tags TEXT NOT NULL,cancel_abilities_with_tag TEXT NOT NULL,
 block_abilities_with_tag TEXT NOT NULL,activation_owned_tags TEXT NOT NULL,activation_required_tags TEXT NOT NULL,
 activation_blocked_tags TEXT NOT NULL,source_required_tags TEXT NOT NULL,source_blocked_tags TEXT NOT NULL,
 target_required_tags TEXT NOT NULL,target_blocked_tags TEXT NOT NULL,cost_gameplay_effect_class TEXT NOT NULL,
 cooldown_gameplay_effect_class TEXT NOT NULL,trigger_count INTEGER NOT NULL,additional_cost_count INTEGER NOT NULL,
 json TEXT NOT NULL);
CREATE INDEX gas_abilities_class_idx ON gas_abilities(generated_class,parent_class);
CREATE TABLE gas_ability_triggers(
 ability_path TEXT NOT NULL,trigger_index INTEGER NOT NULL,trigger_tag TEXT NOT NULL,trigger_source TEXT NOT NULL,
 raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(ability_path,trigger_index));
CREATE INDEX gas_ability_triggers_tag_idx ON gas_ability_triggers(trigger_tag,ability_path);
CREATE TABLE gas_ability_costs(
 ability_path TEXT NOT NULL,cost_index INTEGER NOT NULL,cost_path TEXT NOT NULL,cost_class TEXT NOT NULL,
 raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(ability_path,cost_index));
CREATE INDEX gas_ability_costs_class_idx ON gas_ability_costs(cost_class,ability_path);
CREATE TABLE gas_ability_sets(
 ability_set_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,class_path TEXT NOT NULL,
 ability_count INTEGER NOT NULL,gameplay_effect_count INTEGER NOT NULL,attribute_set_count INTEGER NOT NULL,
 json TEXT NOT NULL);
CREATE TABLE gas_ability_set_abilities(
 ability_set_path TEXT NOT NULL,grant_index INTEGER NOT NULL,ability_class TEXT NOT NULL,input_tag TEXT NOT NULL,
 raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(ability_set_path,grant_index));
CREATE INDEX gas_ability_set_abilities_class_idx ON gas_ability_set_abilities(ability_class,ability_set_path);
CREATE TABLE gas_ability_set_effects(
 ability_set_path TEXT NOT NULL,grant_index INTEGER NOT NULL,gameplay_effect_class TEXT NOT NULL,
 raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(ability_set_path,grant_index));
CREATE INDEX gas_ability_set_effects_class_idx ON gas_ability_set_effects(gameplay_effect_class,ability_set_path);
CREATE TABLE gas_ability_set_attributes(
 ability_set_path TEXT NOT NULL,grant_index INTEGER NOT NULL,attribute_set_class TEXT NOT NULL,
 raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(ability_set_path,grant_index));
CREATE INDEX gas_ability_set_attributes_class_idx ON gas_ability_set_attributes(attribute_set_class,ability_set_path);
CREATE TABLE gas_gameplay_effects(
 gameplay_effect_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,generated_class TEXT NOT NULL,parent_class TEXT NOT NULL,
 cdo_path TEXT NOT NULL,duration_policy TEXT NOT NULL,duration_magnitude TEXT NOT NULL,period TEXT NOT NULL,
 execute_periodic_on_application TEXT NOT NULL,periodic_inhibition_policy TEXT NOT NULL,effect_tags TEXT NOT NULL,
 owned_tags TEXT NOT NULL,blocked_ability_tags TEXT NOT NULL,ongoing_tag_requirements TEXT NOT NULL,
 application_tag_requirements TEXT NOT NULL,removal_tag_requirements TEXT NOT NULL,stacking_type TEXT NOT NULL,
 stack_limit_count TEXT NOT NULL,component_count INTEGER NOT NULL,modifier_count INTEGER NOT NULL,
 execution_count INTEGER NOT NULL,cue_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX gas_gameplay_effects_class_idx ON gas_gameplay_effects(generated_class,parent_class);
CREATE TABLE gas_gameplay_effect_components(
 gameplay_effect_path TEXT NOT NULL,component_index INTEGER NOT NULL,component_path TEXT NOT NULL,
 component_class TEXT NOT NULL,asset_tags TEXT NOT NULL,target_tags TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(gameplay_effect_path,component_index));
CREATE INDEX gas_gameplay_effect_components_class_idx ON gas_gameplay_effect_components(component_class,gameplay_effect_path);
CREATE TABLE gas_gameplay_effect_modifiers(
 gameplay_effect_path TEXT NOT NULL,modifier_index INTEGER NOT NULL,attribute_name TEXT NOT NULL,
 attribute_owner_class TEXT NOT NULL,modifier_op TEXT NOT NULL,magnitude TEXT NOT NULL,raw_value TEXT NOT NULL,
 truncated INTEGER NOT NULL,json TEXT NOT NULL,PRIMARY KEY(gameplay_effect_path,modifier_index));
CREATE INDEX gas_gameplay_effect_modifiers_attribute_idx ON gas_gameplay_effect_modifiers(attribute_owner_class,attribute_name);
CREATE TABLE gas_gameplay_effect_executions(
 gameplay_effect_path TEXT NOT NULL,execution_index INTEGER NOT NULL,calculation_class TEXT NOT NULL,
 modifier_count INTEGER NOT NULL,passed_in_tags TEXT NOT NULL,raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,
 json TEXT NOT NULL,PRIMARY KEY(gameplay_effect_path,execution_index));
CREATE INDEX gas_gameplay_effect_executions_class_idx ON gas_gameplay_effect_executions(calculation_class,gameplay_effect_path);
CREATE TABLE gas_gameplay_effect_execution_modifiers(
 gameplay_effect_path TEXT NOT NULL,execution_index INTEGER NOT NULL,modifier_index INTEGER NOT NULL,
 attribute_name TEXT NOT NULL,attribute_owner_class TEXT NOT NULL,snapshot TEXT NOT NULL,modifier_op TEXT NOT NULL,
 magnitude TEXT NOT NULL,raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(gameplay_effect_path,execution_index,modifier_index));
CREATE INDEX gas_gameplay_effect_execution_modifiers_attribute_idx ON gas_gameplay_effect_execution_modifiers(attribute_owner_class,attribute_name);
CREATE TABLE gas_gameplay_effect_cues(
 gameplay_effect_path TEXT NOT NULL,cue_index INTEGER NOT NULL,gameplay_cue_tags TEXT NOT NULL,
 magnitude_attribute_name TEXT NOT NULL,magnitude_attribute_owner_class TEXT NOT NULL,min_level TEXT NOT NULL,
 max_level TEXT NOT NULL,raw_value TEXT NOT NULL,truncated INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(gameplay_effect_path,cue_index));
CREATE INDEX gas_gameplay_effect_cues_attribute_idx ON gas_gameplay_effect_cues(magnitude_attribute_owner_class,magnitude_attribute_name);
CREATE TABLE gas_gameplay_cues(
 gameplay_cue_path TEXT PRIMARY KEY,package_name TEXT NOT NULL,generated_class TEXT NOT NULL,parent_class TEXT NOT NULL,
 cdo_path TEXT NOT NULL,gameplay_cue_tag TEXT NOT NULL,gameplay_cue_name TEXT NOT NULL,is_override TEXT NOT NULL,
 json TEXT NOT NULL);
CREATE INDEX gas_gameplay_cues_tag_idx ON gas_gameplay_cues(gameplay_cue_tag,gameplay_cue_path);
CREATE TABLE gas_attribute_sets(
 attribute_set_class TEXT PRIMARY KEY,super_class TEXT NOT NULL,module_package TEXT NOT NULL,cdo_path TEXT NOT NULL,
 native INTEGER NOT NULL,attribute_count INTEGER NOT NULL,json TEXT NOT NULL);
CREATE TABLE gas_attributes(
 attribute_set_class TEXT NOT NULL,attribute_index INTEGER NOT NULL,attribute_name TEXT NOT NULL,cpp_type TEXT NOT NULL,
 base_value TEXT NOT NULL,current_value TEXT NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(attribute_set_class,attribute_index));
CREATE INDEX gas_attributes_name_idx ON gas_attributes(attribute_name,attribute_set_class);
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


def _contiguous(rows: list[dict], owner_fields: tuple[str, ...], index_field: str, label: str) -> str | None:
    grouped: dict[tuple[str, ...], list[int]] = collections.defaultdict(list)
    for row in rows:
        owner = tuple(str(row.get(field, "") or "") for field in owner_fields)
        if any(not part for part in owner):
            return f"{label} has blank owner field"
        grouped[owner].append(int(row.get(index_field, -1)))
    for owner, indices in grouped.items():
        if sorted(indices) != list(range(len(indices))):
            return f"{label} indices are not contiguous for {' / '.join(owner)}"
    return None


def _reject_truncation(rows: list[dict], label: str) -> str | None:
    for row in rows:
        if bool(row.get("truncated", False)):
            return f"{label} raw value is truncated"
    return None


def validation_error(output: Path, rows=None) -> str | None:
    output = Path(output)
    rows = rows or _read_rows
    abilities = list(rows(output / "gas_abilities.jsonl"))
    triggers = list(rows(output / "gas_ability_triggers.jsonl"))
    costs = list(rows(output / "gas_ability_costs.jsonl"))
    ability_sets = list(rows(output / "gas_ability_sets.jsonl"))
    set_abilities = list(rows(output / "gas_ability_set_abilities.jsonl"))
    set_effects = list(rows(output / "gas_ability_set_effects.jsonl"))
    set_attributes = list(rows(output / "gas_ability_set_attributes.jsonl"))
    effects = list(rows(output / "gas_gameplay_effects.jsonl"))
    components = list(rows(output / "gas_gameplay_effect_components.jsonl"))
    modifiers = list(rows(output / "gas_gameplay_effect_modifiers.jsonl"))
    executions = list(rows(output / "gas_gameplay_effect_executions.jsonl"))
    execution_modifiers = list(rows(output / "gas_gameplay_effect_execution_modifiers.jsonl"))
    effect_cues = list(rows(output / "gas_gameplay_effect_cues.jsonl"))
    cues = list(rows(output / "gas_gameplay_cues.jsonl"))
    attribute_sets = list(rows(output / "gas_attribute_sets.jsonl"))
    attributes = list(rows(output / "gas_attributes.jsonl"))

    error, ability_paths = _unique_nonblank(abilities, "ability_path", "GAS ability")
    if error: return error
    error, ability_set_paths = _unique_nonblank(ability_sets, "ability_set_path", "GAS ability set")
    if error: return error
    error, effect_paths = _unique_nonblank(effects, "gameplay_effect_path", "GAS GameplayEffect")
    if error: return error
    error, _ = _unique_nonblank(cues, "gameplay_cue_path", "GAS GameplayCue")
    if error: return error
    error, attribute_set_paths = _unique_nonblank(attribute_sets, "attribute_set_class", "GAS AttributeSet")
    if error: return error

    for row in abilities:
        generated = str(row.get("generated_class", "") or "")
        parent = str(row.get("parent_class", "") or "")
        if not generated or not parent or "Ability" not in (generated + parent):
            return f"GAS ability has unexpected class identity: {row.get('ability_path')}"
        if int(row.get("trigger_count", -1)) < 0 or int(row.get("additional_cost_count", -1)) < 0:
            return f"GAS ability has negative child count: {row.get('ability_path')}"

    for row in effects:
        generated = str(row.get("generated_class", "") or "")
        parent = str(row.get("parent_class", "") or "")
        if not generated or "GameplayEffect" not in (generated + parent):
            return f"GAS GameplayEffect has unexpected class identity: {row.get('gameplay_effect_path')}"
        for field in ("component_count", "modifier_count", "execution_count", "cue_count"):
            if int(row.get(field, -1)) < 0:
                return f"GAS GameplayEffect has negative {field}: {row.get('gameplay_effect_path')}"

    for row in cues:
        if "GameplayCue" not in (str(row.get("generated_class", "")) + str(row.get("parent_class", ""))):
            return f"GAS GameplayCue has unexpected class identity: {row.get('gameplay_cue_path')}"

    for row in ability_sets:
        if "AbilitySet" not in str(row.get("class_path", "")):
            return f"GAS ability set has unexpected class: {row.get('ability_set_path')}"

    for row in attribute_sets:
        if "AttributeSet" not in (str(row.get("attribute_set_class", "")) + str(row.get("super_class", ""))):
            return f"GAS AttributeSet has unexpected class identity: {row.get('attribute_set_class')}"
        if int(row.get("attribute_count", -1)) < 0:
            return f"GAS AttributeSet has negative attribute_count: {row.get('attribute_set_class')}"

    child_specs = (
        (triggers, ("ability_path",), "trigger_index", "GAS ability trigger", ability_paths),
        (costs, ("ability_path",), "cost_index", "GAS ability cost", ability_paths),
        (set_abilities, ("ability_set_path",), "grant_index", "GAS ability-set ability grant", ability_set_paths),
        (set_effects, ("ability_set_path",), "grant_index", "GAS ability-set effect grant", ability_set_paths),
        (set_attributes, ("ability_set_path",), "grant_index", "GAS ability-set attribute grant", ability_set_paths),
        (components, ("gameplay_effect_path",), "component_index", "GAS GameplayEffect component", effect_paths),
        (modifiers, ("gameplay_effect_path",), "modifier_index", "GAS GameplayEffect modifier", effect_paths),
        (executions, ("gameplay_effect_path",), "execution_index", "GAS GameplayEffect execution", effect_paths),
        (effect_cues, ("gameplay_effect_path",), "cue_index", "GAS GameplayEffect cue", effect_paths),
        (attributes, ("attribute_set_class",), "attribute_index", "GAS attribute", attribute_set_paths),
    )
    for child_rows, owner_fields, index_field, label, parent_set in child_specs:
        error = _contiguous(child_rows, owner_fields, index_field, label)
        if error: return error
        owner_field = owner_fields[0]
        for row in child_rows:
            if str(row.get(owner_field, "") or "") not in parent_set:
                return f"{label} references unknown parent: {row.get(owner_field)}"

    execution_keys = {
        (str(row.get("gameplay_effect_path", "")), int(row.get("execution_index", -1)))
        for row in executions
    }
    error = _contiguous(
        execution_modifiers,
        ("gameplay_effect_path", "execution_index"),
        "modifier_index",
        "GAS execution modifier",
    )
    if error: return error
    for row in execution_modifiers:
        key = (str(row.get("gameplay_effect_path", "")), int(row.get("execution_index", -1)))
        if key not in execution_keys:
            return f"GAS execution modifier references unknown execution: {key[0]}[{key[1]}]"

    for child_rows, label in (
        (triggers, "GAS ability trigger"),
        (costs, "GAS ability cost"),
        (set_abilities, "GAS ability-set ability grant"),
        (set_effects, "GAS ability-set effect grant"),
        (set_attributes, "GAS ability-set attribute grant"),
        (modifiers, "GAS GameplayEffect modifier"),
        (executions, "GAS GameplayEffect execution"),
        (execution_modifiers, "GAS execution modifier"),
        (effect_cues, "GAS GameplayEffect cue"),
    ):
        error = _reject_truncation(child_rows, label)
        if error: return error

    trigger_counts = collections.Counter(str(row.get("ability_path", "")) for row in triggers)
    cost_counts = collections.Counter(str(row.get("ability_path", "")) for row in costs)
    for row in abilities:
        path = str(row.get("ability_path", ""))
        if int(row.get("trigger_count", 0) or 0) != trigger_counts[path]:
            return f"GAS ability trigger_count mismatch: {path}"
        if int(row.get("additional_cost_count", 0) or 0) != cost_counts[path]:
            return f"GAS ability additional_cost_count mismatch: {path}"

    set_ability_counts = collections.Counter(str(row.get("ability_set_path", "")) for row in set_abilities)
    set_effect_counts = collections.Counter(str(row.get("ability_set_path", "")) for row in set_effects)
    set_attribute_counts = collections.Counter(str(row.get("ability_set_path", "")) for row in set_attributes)
    for row in ability_sets:
        path = str(row.get("ability_set_path", ""))
        if int(row.get("ability_count", 0) or 0) != set_ability_counts[path]:
            return f"GAS ability set ability_count mismatch: {path}"
        if int(row.get("gameplay_effect_count", 0) or 0) != set_effect_counts[path]:
            return f"GAS ability set gameplay_effect_count mismatch: {path}"
        if int(row.get("attribute_set_count", 0) or 0) != set_attribute_counts[path]:
            return f"GAS ability set attribute_set_count mismatch: {path}"

    component_counts = collections.Counter(str(row.get("gameplay_effect_path", "")) for row in components)
    modifier_counts = collections.Counter(str(row.get("gameplay_effect_path", "")) for row in modifiers)
    execution_counts = collections.Counter(str(row.get("gameplay_effect_path", "")) for row in executions)
    cue_counts = collections.Counter(str(row.get("gameplay_effect_path", "")) for row in effect_cues)
    execution_modifier_counts = collections.Counter(
        (str(row.get("gameplay_effect_path", "")), int(row.get("execution_index", -1)))
        for row in execution_modifiers
    )
    for row in effects:
        path = str(row.get("gameplay_effect_path", ""))
        if int(row.get("component_count", 0) or 0) != component_counts[path]:
            return f"GAS GameplayEffect component_count mismatch: {path}"
        if int(row.get("modifier_count", 0) or 0) != modifier_counts[path]:
            return f"GAS GameplayEffect modifier_count mismatch: {path}"
        if int(row.get("execution_count", 0) or 0) != execution_counts[path]:
            return f"GAS GameplayEffect execution_count mismatch: {path}"
        if int(row.get("cue_count", 0) or 0) != cue_counts[path]:
            return f"GAS GameplayEffect cue_count mismatch: {path}"
    for row in executions:
        key = (str(row.get("gameplay_effect_path", "")), int(row.get("execution_index", -1)))
        if int(row.get("modifier_count", 0) or 0) != execution_modifier_counts[key]:
            return f"GAS execution modifier_count mismatch: {key[0]}[{key[1]}]"

    attribute_counts = collections.Counter(str(row.get("attribute_set_class", "")) for row in attributes)
    for row in attribute_sets:
        cls = str(row.get("attribute_set_class", ""))
        if int(row.get("attribute_count", 0) or 0) != attribute_counts[cls]:
            return f"GAS AttributeSet attribute_count mismatch: {cls}"

    # This schema is authored/default-state only. No active specs, prediction
    # keys, live attribute values, active effects, or replicated ASC state are
    # represented as first-class rows.
    return None


def load_database(conn, output: Path, rows=None) -> None:
    rows = rows or _read_rows
    for r in rows(output / "gas_abilities.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gas_abilities VALUES(" + ",".join("?" * 26) + ")", (
            r.get("ability_path", ""), r.get("package_name", ""), r.get("generated_class", ""), r.get("parent_class", ""),
            r.get("cdo_path", ""), r.get("activation_policy", ""), r.get("activation_group", ""),
            r.get("replication_policy", ""), r.get("instancing_policy", ""), r.get("net_execution_policy", ""),
            r.get("net_security_policy", ""), r.get("ability_tags", ""), r.get("cancel_abilities_with_tag", ""),
            r.get("block_abilities_with_tag", ""), r.get("activation_owned_tags", ""), r.get("activation_required_tags", ""),
            r.get("activation_blocked_tags", ""), r.get("source_required_tags", ""), r.get("source_blocked_tags", ""),
            r.get("target_required_tags", ""), r.get("target_blocked_tags", ""), r.get("cost_gameplay_effect_class", ""),
            r.get("cooldown_gameplay_effect_class", ""), int(r.get("trigger_count", 0) or 0),
            int(r.get("additional_cost_count", 0) or 0), _j(r)))
    simple_specs = (
        ("gas_ability_triggers.jsonl", "gas_ability_triggers", ("ability_path", "trigger_index", "trigger_tag", "trigger_source", "raw_value", "truncated")),
        ("gas_ability_costs.jsonl", "gas_ability_costs", ("ability_path", "cost_index", "cost_path", "cost_class", "raw_value", "truncated")),
        ("gas_ability_set_abilities.jsonl", "gas_ability_set_abilities", ("ability_set_path", "grant_index", "ability_class", "input_tag", "raw_value", "truncated")),
        ("gas_ability_set_effects.jsonl", "gas_ability_set_effects", ("ability_set_path", "grant_index", "gameplay_effect_class", "raw_value", "truncated")),
        ("gas_ability_set_attributes.jsonl", "gas_ability_set_attributes", ("ability_set_path", "grant_index", "attribute_set_class", "raw_value", "truncated")),
        ("gas_gameplay_effect_components.jsonl", "gas_gameplay_effect_components", ("gameplay_effect_path", "component_index", "component_path", "component_class", "asset_tags", "target_tags")),
        ("gas_gameplay_effect_modifiers.jsonl", "gas_gameplay_effect_modifiers", ("gameplay_effect_path", "modifier_index", "attribute_name", "attribute_owner_class", "modifier_op", "magnitude", "raw_value", "truncated")),
        ("gas_gameplay_effect_executions.jsonl", "gas_gameplay_effect_executions", ("gameplay_effect_path", "execution_index", "calculation_class", "modifier_count", "passed_in_tags", "raw_value", "truncated")),
        ("gas_gameplay_effect_execution_modifiers.jsonl", "gas_gameplay_effect_execution_modifiers", ("gameplay_effect_path", "execution_index", "modifier_index", "attribute_name", "attribute_owner_class", "snapshot", "modifier_op", "magnitude", "raw_value", "truncated")),
        ("gas_gameplay_effect_cues.jsonl", "gas_gameplay_effect_cues", ("gameplay_effect_path", "cue_index", "gameplay_cue_tags", "magnitude_attribute_name", "magnitude_attribute_owner_class", "min_level", "max_level", "raw_value", "truncated")),
        ("gas_gameplay_cues.jsonl", "gas_gameplay_cues", ("gameplay_cue_path", "package_name", "generated_class", "parent_class", "cdo_path", "gameplay_cue_tag", "gameplay_cue_name", "is_override")),
        ("gas_attribute_sets.jsonl", "gas_attribute_sets", ("attribute_set_class", "super_class", "module_package", "cdo_path", "native", "attribute_count")),
        ("gas_attributes.jsonl", "gas_attributes", ("attribute_set_class", "attribute_index", "attribute_name", "cpp_type", "base_value", "current_value")),
    )
    int_fields = {"trigger_index", "cost_index", "grant_index", "component_index", "modifier_index", "execution_index", "cue_index", "attribute_index", "modifier_count", "attribute_count"}
    bool_fields = {"truncated", "native"}
    for filename, table, fields in simple_specs:
        placeholders = ",".join("?" * (len(fields) + 1))
        for r in rows(output / filename):
            values = []
            for field in fields:
                value = r.get(field, "")
                if field in int_fields:
                    value = int(value or 0)
                elif field in bool_fields:
                    value = int(bool(value))
                values.append(value)
            values.append(_j(r))
            conn.execute(f"INSERT OR REPLACE INTO {table} VALUES({placeholders})", tuple(values))

    for r in rows(output / "gas_ability_sets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gas_ability_sets VALUES(?,?,?,?,?,?,?)", (
            r.get("ability_set_path", ""), r.get("package_name", ""), r.get("class_path", ""),
            int(r.get("ability_count", 0) or 0), int(r.get("gameplay_effect_count", 0) or 0),
            int(r.get("attribute_set_count", 0) or 0), _j(r)))
    for r in rows(output / "gas_gameplay_effects.jsonl"):
        conn.execute("INSERT OR REPLACE INTO gas_gameplay_effects VALUES(" + ",".join("?" * 23) + ")", (
            r.get("gameplay_effect_path", ""), r.get("package_name", ""), r.get("generated_class", ""), r.get("parent_class", ""),
            r.get("cdo_path", ""), r.get("duration_policy", ""), r.get("duration_magnitude", ""), r.get("period", ""),
            r.get("execute_periodic_on_application", ""), r.get("periodic_inhibition_policy", ""), r.get("effect_tags", ""),
            r.get("owned_tags", ""), r.get("blocked_ability_tags", ""), r.get("ongoing_tag_requirements", ""),
            r.get("application_tag_requirements", ""), r.get("removal_tag_requirements", ""), r.get("stacking_type", ""),
            r.get("stack_limit_count", ""), int(r.get("component_count", 0) or 0), int(r.get("modifier_count", 0) or 0),
            int(r.get("execution_count", 0) or 0), int(r.get("cue_count", 0) or 0), _j(r)))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='gas_abilities'").fetchone():
        return
    print("\n[GAS abilities]")
    print_rows(conn.execute(
        """SELECT ability_path,activation_policy,activation_group,net_execution_policy,trigger_count,additional_cost_count,
                  cost_gameplay_effect_class,cooldown_gameplay_effect_class
           FROM gas_abilities WHERE ability_path LIKE ? OR generated_class LIKE ? OR ability_tags LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("ability_path", "activation_policy", "activation_group", "net_execution_policy", "trigger_count", "additional_cost_count", "cost_effect", "cooldown_effect"))
    print("\n[GAS ability sets / grants]")
    print_rows(conn.execute(
        """SELECT ability_set_path,ability_count,gameplay_effect_count,attribute_set_count FROM gas_ability_sets
           WHERE ability_set_path LIKE ? OR class_path LIKE ? LIMIT ?""",
        (pattern, pattern, limit)),
        ("ability_set_path", "ability_count", "effect_count", "attribute_count"))
    print_rows(conn.execute(
        """SELECT ability_set_path,grant_index,ability_class,input_tag FROM gas_ability_set_abilities
           WHERE ability_set_path LIKE ? OR ability_class LIKE ? OR input_tag LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("ability_set_path", "grant_index", "ability_class", "input_tag"))
    print("\n[GAS GameplayEffects]")
    print_rows(conn.execute(
        """SELECT gameplay_effect_path,duration_policy,component_count,modifier_count,execution_count,cue_count
           FROM gas_gameplay_effects WHERE gameplay_effect_path LIKE ? OR generated_class LIKE ? LIMIT ?""",
        (pattern, pattern, limit)),
        ("gameplay_effect_path", "duration_policy", "components", "modifiers", "executions", "cues"))
    print_rows(conn.execute(
        """SELECT gameplay_effect_path,modifier_index,attribute_owner_class,attribute_name,modifier_op
           FROM gas_gameplay_effect_modifiers
           WHERE gameplay_effect_path LIKE ? OR attribute_owner_class LIKE ? OR attribute_name LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("gameplay_effect_path", "modifier_index", "attribute_owner", "attribute", "op"))
    print("\n[GAS cues / attributes]")
    print_rows(conn.execute(
        """SELECT gameplay_cue_path,gameplay_cue_tag,parent_class FROM gas_gameplay_cues
           WHERE gameplay_cue_path LIKE ? OR gameplay_cue_tag LIKE ? OR parent_class LIKE ? LIMIT ?""",
        (pattern, pattern, pattern, limit)),
        ("gameplay_cue_path", "gameplay_cue_tag", "parent_class"))
    print_rows(conn.execute(
        """SELECT attribute_set_class,attribute_index,attribute_name,base_value,current_value FROM gas_attributes
           WHERE attribute_set_class LIKE ? OR attribute_name LIKE ? LIMIT ?""",
        (pattern, pattern, limit)),
        ("attribute_set_class", "index", "attribute_name", "base_value", "current_value"))


def install(systems_module) -> None:
    if getattr(systems_module, "_gas_schema_installed", False):
        return
    original_create_schema = systems_module.create_schema
    original_validation_error = systems_module.validation_error
    original_load_database = systems_module.load_database
    original_query = systems_module.query

    systems_module.SYSTEMS_SCHEMA_VERSION = 6
    systems_module.JSONL_FILES = tuple(dict.fromkeys((*systems_module.JSONL_FILES, *GAS_FILES)))
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
    systems_module._gas_schema_installed = True
