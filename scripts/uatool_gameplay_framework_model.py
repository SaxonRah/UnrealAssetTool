#!/usr/bin/env python3
"""Exact authored Gameplay Framework joins over existing structural/world/config truth.

This module deliberately adds no native scanner and no systems-schema stream.  It
normalizes relationships that are already recoverable from structural schema 13,
world schema 12, and source/config chunks:

* exact/transitive Blueprint Gameplay Framework inheritance;
* explicit GameMode class-default selector overrides;
* explicit WorldSettings.DefaultGameMode overrides;
* GameMapsSettings class/map defaults;
* exact authored Pawn/Character AIControllerClass references.

Runtime spawning, possession, travel/session state, and inherited native defaults
that are not present in the corpus remain out of scope.
"""
from __future__ import annotations

import configparser
import io
import re
from pathlib import Path

TARGET_DERIVED_SCHEMA_VERSION = 28

NATIVE_ROOT_KINDS = {
    "/script/engine.gamemodebase": "game_mode",
    "/script/engine.gamemode": "game_mode",
    "/script/engine.gamestatebase": "game_state",
    "/script/engine.gamestate": "game_state",
    "/script/engine.playerstate": "player_state",
    "/script/engine.controller": "controller",
    "/script/engine.playercontroller": "player_controller",
    "/script/aimodule.aicontroller": "ai_controller",
    "/script/engine.pawn": "pawn",
    "/script/engine.character": "character",
    "/script/engine.spectatorpawn": "spectator_pawn",
    "/script/engine.hud": "hud",
    "/script/engine.gameinstance": "game_instance",
}

GAME_MODE_SELECTOR_RELATIONS = {
    "DefaultPawnClass": "game_mode_overrides_default_pawn_class",
    "HUDClass": "game_mode_overrides_hud_class",
    "PlayerControllerClass": "game_mode_overrides_player_controller_class",
    "GameStateClass": "game_mode_overrides_game_state_class",
    "PlayerStateClass": "game_mode_overrides_player_state_class",
    "SpectatorClass": "game_mode_overrides_spectator_class",
    "ReplaySpectatorPlayerControllerClass": "game_mode_overrides_replay_spectator_player_controller_class",
}

GAME_MAPS_SETTING_RELATIONS = {
    "GlobalDefaultGameMode": ("project_sets_global_default_game_mode_class", "game_mode"),
    "GlobalDefaultServerGameMode": ("project_sets_global_default_server_game_mode_class", "game_mode"),
    "GameInstanceClass": ("project_sets_game_instance_class", "game_instance"),
    "GameDefaultMap": ("project_sets_game_default_map", "world"),
    "ServerDefaultMap": ("project_sets_server_default_map", "world"),
    "EditorStartupMap": ("project_sets_editor_startup_map", "world"),
    "TransitionMap": ("project_sets_transition_map", "world"),
}

RELATIONS = {
    "defines_gameplay_framework_class",
    "inherits_gameplay_framework_class",
    *GAME_MODE_SELECTOR_RELATIONS.values(),
    "world_overrides_default_game_mode_class",
    "pawn_uses_ai_controller_class",
    *(relation for relation, _ in GAME_MAPS_SETTING_RELATIONS.values()),
}

GAME_MAPS_SETTINGS_NODE = "config:Config/DefaultEngine.ini#/Script/EngineSettings.GameMapsSettings"


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def _meaningful(value: object) -> str:
    text = str(value or "").strip()
    return "" if text in {"", "None", "none", "NULL", "null"} else text


def _object_path_from_export(value: object) -> str:
    text = _meaningful(value)
    if not text:
        return ""
    match = re.search(r"'([^']+)'", text)
    if match:
        return match.group(1)
    return text


def _iter_rows(rows, path: Path):
    if not path.is_file():
        return
    for row in rows(path):
        if isinstance(row, dict):
            yield row


def resolve_framework_blueprints(output: Path, rows) -> dict:
    blueprints = list(_iter_rows(rows, Path(output) / "blueprints.jsonl"))
    by_generated = {
        _norm(row.get("generated_class")): row
        for row in blueprints
        if _meaningful(row.get("generated_class"))
    }
    kind_by_object: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for row in blueprints:
            obj = _meaningful(row.get("object_path"))
            if not obj or obj in kind_by_object:
                continue
            parent = _norm(row.get("parent_class"))
            kind = NATIVE_ROOT_KINDS.get(parent, "")
            if not kind:
                parent_row = by_generated.get(parent)
                if parent_row:
                    kind = kind_by_object.get(_meaningful(parent_row.get("object_path")), "")
            if kind:
                kind_by_object[obj] = kind
                changed = True

    records = []
    kind_by_class = dict(NATIVE_ROOT_KINDS)
    object_by_generated: dict[str, str] = {}
    for row in blueprints:
        obj = _meaningful(row.get("object_path"))
        kind = kind_by_object.get(obj, "")
        if not kind:
            continue
        generated = _meaningful(row.get("generated_class"))
        parent = _meaningful(row.get("parent_class"))
        if generated:
            kind_by_class[_norm(generated)] = kind
            object_by_generated[_norm(generated)] = obj
        records.append({
            "blueprint_path": obj,
            "generated_class": generated,
            "parent_class": parent,
            "framework_kind": kind,
            "transitive": _norm(parent) in by_generated,
        })
    records.sort(key=lambda item: (item["framework_kind"], item["blueprint_path"]))
    return {
        "records": records,
        "kind_by_object": kind_by_object,
        "kind_by_class": kind_by_class,
        "object_by_generated": object_by_generated,
    }


def _class_node_kind(path: str, kind_by_class: dict[str, str], fallback_kind: str = "") -> str:
    kind = kind_by_class.get(_norm(path), "") or fallback_kind
    return f"{kind}_class" if kind else "class"


def _source_chunks_for_default_engine(output: Path, rows) -> list[dict]:
    result = []
    for row in _iter_rows(rows, Path(output) / "source_chunks.jsonl"):
        path = str(row.get("path", "") or "").replace("\\", "/")
        if path.lower().endswith("config/defaultengine.ini"):
            result.append(row)
    result.sort(key=lambda row: (int(row.get("start_line", 0) or 0), int(row.get("end_line", 0) or 0)))
    return result


def game_maps_settings(output: Path, rows) -> dict[str, dict]:
    chunks = _source_chunks_for_default_engine(output, rows)
    if not chunks:
        return {}
    lines: list[tuple[int, str]] = []
    for chunk in chunks:
        start = int(chunk.get("start_line", 1) or 1)
        for offset, line in enumerate(str(chunk.get("text", "") or "").splitlines()):
            lines.append((start + offset, line))

    section = ""
    result: dict[str, dict] = {}
    wanted_section = "/script/enginesettings.gamemapssettings"
    for line_number, raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith((";", "#")):
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1].strip().lower()
            continue
        if section != wanted_section or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key not in GAME_MAPS_SETTING_RELATIONS:
            continue
        value = value.strip()
        result[key] = {
            "key": key,
            "value": value,
            "line": line_number,
            "path": "Config/DefaultEngine.ini",
            "section": "/Script/EngineSettings.GameMapsSettings",
        }
    return result


def build_model(output: Path, rows) -> dict:
    output = Path(output)
    framework = resolve_framework_blueprints(output, rows)
    records = framework["records"]
    kind_by_class = framework["kind_by_class"]
    edge_specs: list[dict] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    def add(source: object, relation: str, target: object, source_kind: str, target_kind: str, evidence: dict):
        source_text = _meaningful(source)
        target_text = _meaningful(target)
        if not source_text or not target_text or source_text == target_text:
            return
        key = (source_kind, source_text, relation, target_kind, target_text)
        if key in seen:
            return
        seen.add(key)
        edge_specs.append({
            "source_kind": source_kind,
            "source": source_text,
            "relation": relation,
            "target_kind": target_kind,
            "target": target_text,
            "evidence": dict(evidence),
        })

    for record in records:
        bp = record["blueprint_path"]
        generated = record["generated_class"]
        parent = record["parent_class"]
        kind = record["framework_kind"]
        generated_kind = f"{kind}_class"
        if generated:
            add(
                bp,
                "defines_gameplay_framework_class",
                generated,
                "blueprint",
                generated_kind,
                {
                    "stream": "blueprints.jsonl",
                    "kind": "framework_blueprint_generated_class",
                    "framework_kind": kind,
                },
            )
        if generated and parent:
            add(
                generated,
                "inherits_gameplay_framework_class",
                parent,
                generated_kind,
                _class_node_kind(parent, kind_by_class, kind),
                {
                    "stream": "blueprints.jsonl",
                    "kind": "framework_blueprint_parent_class",
                    "framework_kind": kind,
                    "transitive": bool(record["transitive"]),
                },
            )

    selector_counts: dict[str, int] = {}
    for row in _iter_rows(rows, output / "blueprint_state_values.jsonl"):
        property_name = str(row.get("property_name", "") or "")
        relation = GAME_MODE_SELECTOR_RELATIONS.get(property_name)
        if not relation:
            continue
        if int(row.get("depth", 0) or 0) != 0:
            continue
        owner_class = _meaningful(row.get("owner_class") or row.get("owner_id"))
        if kind_by_class.get(_norm(owner_class)) != "game_mode":
            continue
        target = _meaningful(row.get("referenced_object_path")) or _object_path_from_export(row.get("value"))
        if not target:
            continue
        target_kind = _class_node_kind(target, kind_by_class)
        add(
            owner_class,
            relation,
            target,
            "game_mode_class",
            target_kind,
            {
                "stream": "blueprint_state_values.jsonl",
                "kind": "authored_game_mode_class_selector_override",
                "property": property_name,
                "blueprint_path": str(row.get("blueprint_path", "") or ""),
                "baseline_class": str(row.get("baseline_class", "") or ""),
                "baseline_object_path": str(row.get("baseline_object_path", "") or ""),
            },
        )
        selector_counts[property_name] = selector_counts.get(property_name, 0) + 1

    world_override_count = 0
    for row in _iter_rows(rows, output / "world_instance_properties.jsonl"):
        if str(row.get("owner_class", "") or "") != "/Script/Engine.WorldSettings":
            continue
        if str(row.get("property_name", "") or "") != "DefaultGameMode":
            continue
        world = _meaningful(row.get("world_path"))
        target = _object_path_from_export(row.get("value"))
        if not world or not target:
            continue
        add(
            world,
            "world_overrides_default_game_mode_class",
            target,
            "world",
            _class_node_kind(target, kind_by_class, "game_mode"),
            {
                "stream": "world_instance_properties.jsonl",
                "kind": "authored_world_settings_default_game_mode",
                "actor_path": str(row.get("actor_path", "") or ""),
                "property": "DefaultGameMode",
            },
        )
        world_override_count += 1

    pawn_ai_controller_count = 0
    for row in _iter_rows(rows, output / "blueprint_state_values.jsonl"):
        if str(row.get("property_name", "") or "") != "AIControllerClass" or int(row.get("depth", 0) or 0) != 0:
            continue
        owner_class = _meaningful(row.get("owner_class") or row.get("owner_id"))
        owner_kind = kind_by_class.get(_norm(owner_class), "")
        if owner_kind not in {"pawn", "character", "spectator_pawn"}:
            continue
        target = _meaningful(row.get("referenced_object_path")) or _object_path_from_export(row.get("value"))
        if not target:
            continue
        target_kind = _class_node_kind(target, kind_by_class, "ai_controller")
        add(
            owner_class,
            "pawn_uses_ai_controller_class",
            target,
            f"{owner_kind}_class",
            target_kind,
            {
                "stream": "blueprint_state_values.jsonl",
                "kind": "authored_pawn_ai_controller_class",
                "property": "AIControllerClass",
                "blueprint_path": str(row.get("blueprint_path", "") or ""),
            },
        )
        pawn_ai_controller_count += 1

    # World references retain exact inherited/instance class references.  Only
    # promote AIControllerClass when the target is a proven AIController class.
    for row in _iter_rows(rows, output / "world_references.jsonl"):
        prop = str(row.get("root_property", "") or row.get("property_path", "") or "")
        if prop != "AIControllerClass":
            continue
        target = _meaningful(row.get("target_path"))
        if kind_by_class.get(_norm(target), "") != "ai_controller":
            continue
        source = _meaningful(row.get("owner_path") or row.get("actor_path"))
        if not source:
            continue
        add(
            source,
            "pawn_uses_ai_controller_class",
            target,
            "actor",
            "ai_controller_class",
            {
                "stream": "world_references.jsonl",
                "kind": "exact_world_pawn_ai_controller_class_reference",
                "property": "AIControllerClass",
                "world_path": str(row.get("world_path", "") or ""),
                "authored_override": bool(row.get("authored_override", False)),
            },
        )
        pawn_ai_controller_count += 1

    settings = game_maps_settings(output, rows)
    project_setting_count = 0
    for key, item in sorted(settings.items()):
        relation, target_role = GAME_MAPS_SETTING_RELATIONS[key]
        target = _meaningful(item.get("value"))
        if not target:
            continue
        target_kind = "world" if target_role == "world" else _class_node_kind(target, kind_by_class, target_role)
        add(
            GAME_MAPS_SETTINGS_NODE,
            relation,
            target,
            "game_maps_settings",
            target_kind,
            {
                "stream": "source_chunks.jsonl",
                "kind": "game_maps_settings_assignment",
                "path": item["path"],
                "section": item["section"],
                "key": key,
                "line": int(item["line"]),
            },
        )
        project_setting_count += 1

    relation_counts: dict[str, int] = {}
    for edge in edge_specs:
        relation = edge["relation"]
        relation_counts[relation] = relation_counts.get(relation, 0) + 1
    category_counts: dict[str, int] = {}
    transitive = 0
    for record in records:
        kind = record["framework_kind"]
        category_counts[kind] = category_counts.get(kind, 0) + 1
        transitive += int(bool(record["transitive"]))

    return {
        "framework_blueprints": records,
        "kind_by_class": kind_by_class,
        "game_maps_settings": settings,
        "edge_specs": sorted(
            edge_specs,
            key=lambda edge: (edge["source_kind"], edge["source"], edge["relation"], edge["target_kind"], edge["target"]),
        ),
        "counts": {
            "framework_blueprints": len(records),
            "transitive_framework_blueprints": transitive,
            "game_mode_blueprints": category_counts.get("game_mode", 0),
            "character_blueprints": category_counts.get("character", 0),
            "player_controller_blueprints": category_counts.get("player_controller", 0),
            "ai_controller_blueprints": category_counts.get("ai_controller", 0),
            "pawn_blueprints": category_counts.get("pawn", 0),
            "hud_blueprints": category_counts.get("hud", 0),
            "game_mode_selector_overrides": sum(selector_counts.values()),
            "world_game_mode_overrides": world_override_count,
            "pawn_ai_controller_references": pawn_ai_controller_count,
            "project_game_maps_settings": project_setting_count,
            "exact_semantic_edges": len(edge_specs),
        },
        "category_counts": category_counts,
        "selector_counts": selector_counts,
        "relation_counts": relation_counts,
        "runtime_state_captured": False,
    }


def expected_edge_keys(output: Path, rows) -> set[tuple[str, str, str]]:
    return {
        (edge["source"], edge["relation"], edge["target"])
        for edge in build_model(Path(output), rows)["edge_specs"]
    }
