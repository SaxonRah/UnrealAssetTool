#!/usr/bin/env python3
"""Read-only authored Gameplay Framework evidence inventory.

The diagnostic inventories exact Blueprint inheritance, project/default settings,
world overrides and authored class-selector/reference evidence before any schema
promotion. It deliberately does not infer framework identity from asset names and
does not inspect runtime spawned/possessed state.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
from pathlib import Path
import sys

BASE_STREAMS = (
    "files.jsonl",
    "assets.jsonl",
    "blueprints.jsonl",
    "blueprint_component_properties.jsonl",
    "blueprint_state_values.jsonl",
    "blueprint_node_properties.jsonl",
    "blueprint_node_references.jsonl",
    "blueprint_semantic_nodes.jsonl",
    "blueprint_semantic_statements.jsonl",
    "worlds.jsonl",
    "world_actors.jsonl",
    "world_components.jsonl",
    "world_instance_properties.jsonl",
    "world_references.jsonl",
    "systems_assets.jsonl",
    "systems_properties.jsonl",
    "systems_references.jsonl",
    "project_nodes.jsonl",
    "project_edges.jsonl",
)
SOURCE_STREAMS = ("source_chunks.jsonl",)

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

GAME_MODE_SELECTOR_PROPERTIES = {
    "defaultpawnclass",
    "hudclass",
    "playercontrollerclass",
    "gamestateclass",
    "playerstateclass",
    "spectatorclass",
    "replayspectatorplayercontrollerclass",
}

PROJECT_GAME_MODE_PROPERTIES = {
    "globaldefaultgamemode",
    "globaldefaultservergamemode",
    "defaultgamemode",
}

PROJECT_MAP_PROPERTIES = {
    "gamedefaultmap",
    "serverdefaultmap",
    "editorstartupmap",
    "transitionmap",
    "localmapoptions",
}

FRAMEWORK_USAGE_MARKERS = (
    "possess",
    "unpossess",
    "restartplayer",
    "restartplayeratplayerstart",
    "findplayerstart",
    "chooseplayerstart",
    "spawnplayactor",
    "postlogin",
    "logout",
    "handlematchhasstarted",
    "startmatch",
    "setviewtarget",
)


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def _row_text(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _iter_rows(rows, path: Path):
    if not path.is_file():
        return
    for row in rows(path):
        if isinstance(row, dict):
            yield row


def _value(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _blueprint_identity(row: dict) -> str:
    return _value(row, ("object_path", "blueprint_path", "asset_path", "path"))


def _owner(row: dict, filename: str, line_number: int) -> str:
    return _value(row, (
        "owner_path", "owner_id", "object_path", "blueprint_path", "asset_path",
        "actor_path", "component_path", "systems_path", "source", "path",
    )) or f"{filename}:{line_number}"


def _property_name(row: dict) -> str:
    return _value(row, (
        "property_path", "property_name", "root_property", "source_property", "field_name", "name",
    ))


def _class_value(row: dict) -> str:
    return _value(row, (
        "class_path", "class", "asset_class", "component_class", "owner_class", "target_class",
        "referenced_object_class", "actor_class", "node_class", "generated_class", "parent_class",
    ))


def _resolve_blueprint_kinds(blueprints: list[dict]) -> tuple[dict[str, str], dict[str, dict], list[dict]]:
    by_generated: dict[str, dict] = {}
    by_object: dict[str, dict] = {}
    for row in blueprints:
        obj = _blueprint_identity(row)
        generated = str(row.get("generated_class", "") or "")
        if obj:
            by_object[obj] = row
        if generated:
            by_generated[_norm(generated)] = row

    kind_by_object: dict[str, str] = {}
    changed = True
    while changed:
        changed = False
        for row in blueprints:
            obj = _blueprint_identity(row)
            if not obj or obj in kind_by_object:
                continue
            parent = _norm(row.get("parent_class", ""))
            kind = NATIVE_ROOT_KINDS.get(parent, "")
            if not kind:
                parent_row = by_generated.get(parent)
                if parent_row:
                    kind = kind_by_object.get(_blueprint_identity(parent_row), "")
            if kind:
                kind_by_object[obj] = kind
                changed = True

    inheritance = []
    for row in blueprints:
        obj = _blueprint_identity(row)
        if obj not in kind_by_object:
            continue
        inheritance.append({
            "blueprint": obj,
            "kind": kind_by_object[obj],
            "generated_class": str(row.get("generated_class", "") or ""),
            "parent_class": str(row.get("parent_class", "") or ""),
            "parent_is_framework_blueprint": _norm(row.get("parent_class", "")) in by_generated,
        })
    inheritance.sort(key=lambda item: (item["kind"], item["blueprint"]))
    return kind_by_object, by_object, inheritance


def build_report(output: Path, rows, *, include_source: bool = True, example_limit: int = 40) -> dict:
    output = Path(output).expanduser().resolve()
    if example_limit < 1:
        raise ValueError("example_limit must be >= 1")

    blueprints = list(_iter_rows(rows, output / "blueprints.jsonl"))
    kind_by_object, blueprint_by_object, inheritance = _resolve_blueprint_kinds(blueprints)
    categories = collections.Counter(kind_by_object.values())

    generated_to_object = {
        _norm(row.get("generated_class", "")): obj
        for obj, row in blueprint_by_object.items()
        if str(row.get("generated_class", "") or "")
    }
    framework_generated = set(generated_to_object)
    native_framework = set(NATIVE_ROOT_KINDS)

    selector_rows: list[dict] = []
    project_game_mode_rows: list[dict] = []
    project_map_rows: list[dict] = []
    world_override_rows: list[dict] = []
    reference_rows: list[dict] = []
    usage_rows: list[dict] = []
    high_signal_examples: list[dict] = []

    selector_owners: set[str] = set()
    project_setting_owners: set[str] = set()
    world_override_owners: set[str] = set()
    reference_owners: set[str] = set()
    stream_totals = collections.Counter()
    property_counts = collections.Counter()
    class_counts = collections.Counter()

    streams = list(BASE_STREAMS)
    if include_source:
        streams.extend(SOURCE_STREAMS)

    for filename in streams:
        path = output / filename
        if not path.is_file():
            continue
        for line_number, row in enumerate(_iter_rows(rows, path), 1):
            stream_totals[filename] += 1
            text = _row_text(row)
            lower = text.lower()
            prop = _property_name(row)
            prop_lower = prop.lower().split(".")[-1]
            owner = _owner(row, filename, line_number)
            cls = _class_value(row)
            if cls:
                class_counts[cls] += 1
            if prop:
                property_counts[prop] += 1

            is_selector = prop_lower in GAME_MODE_SELECTOR_PROPERTIES
            if is_selector:
                item = {"stream": filename, "line": line_number, "owner": owner, "property": prop, "row": row}
                selector_rows.append(item)
                selector_owners.add(owner)
                if len(high_signal_examples) < example_limit:
                    high_signal_examples.append(item)

            has_game_maps_settings = "gamemapssettings" in lower
            if prop_lower in PROJECT_GAME_MODE_PROPERTIES or (
                filename == "source_chunks.jsonl" and any(name in lower for name in PROJECT_GAME_MODE_PROPERTIES)
            ):
                item = {"stream": filename, "line": line_number, "owner": owner, "property": prop, "row": row}
                project_game_mode_rows.append(item)
                project_setting_owners.add(owner)
                if len(high_signal_examples) < example_limit:
                    high_signal_examples.append(item)
            elif has_game_maps_settings and "gamemode" in lower:
                item = {"stream": filename, "line": line_number, "owner": owner, "property": prop, "row": row}
                project_game_mode_rows.append(item)
                project_setting_owners.add(owner)

            if prop_lower in PROJECT_MAP_PROPERTIES or (
                filename == "source_chunks.jsonl" and any(name in lower for name in PROJECT_MAP_PROPERTIES)
            ):
                item = {"stream": filename, "line": line_number, "owner": owner, "property": prop, "row": row}
                project_map_rows.append(item)
                project_setting_owners.add(owner)
                if len(high_signal_examples) < example_limit:
                    high_signal_examples.append(item)

            if filename in ("world_instance_properties.jsonl", "world_references.jsonl", "world_actors.jsonl"):
                if prop_lower == "defaultgamemode" or ("worldsettings" in lower and "defaultgamemode" in lower):
                    item = {"stream": filename, "line": line_number, "owner": owner, "property": prop, "row": row}
                    world_override_rows.append(item)
                    world_override_owners.add(owner)
                    if len(high_signal_examples) < example_limit:
                        high_signal_examples.append(item)

            if filename in ("world_references.jsonl", "systems_references.jsonl", "blueprint_node_references.jsonl"):
                target = _norm(_value(row, (
                    "target", "target_path", "object_path", "referenced_object", "referenced_object_path", "class_path",
                )))
                target_class = _norm(_value(row, ("target_class", "object_class", "referenced_object_class")))
                if target in framework_generated or target_class in native_framework or target_class in framework_generated:
                    item = {"stream": filename, "line": line_number, "owner": owner, "property": prop, "row": row}
                    reference_rows.append(item)
                    reference_owners.add(owner)
                    if len(high_signal_examples) < example_limit:
                        high_signal_examples.append(item)

            if filename in (
                "blueprint_node_properties.jsonl", "blueprint_node_references.jsonl",
                "blueprint_semantic_nodes.jsonl", "blueprint_semantic_statements.jsonl", "source_chunks.jsonl",
            ) and any(marker in lower for marker in FRAMEWORK_USAGE_MARKERS):
                item = {"stream": filename, "line": line_number, "owner": owner, "property": prop, "row": row}
                usage_rows.append(item)

    direct_framework_blueprints = sum(1 for item in inheritance if not item["parent_is_framework_blueprint"])
    transitive_framework_blueprints = sum(1 for item in inheritance if item["parent_is_framework_blueprint"])
    proof = collections.Counter({
        "blueprint_rows": len(blueprints),
        "framework_blueprints": len(kind_by_object),
        "direct_framework_blueprints": direct_framework_blueprints,
        "transitive_framework_blueprints": transitive_framework_blueprints,
        "game_mode_blueprints": categories["game_mode"],
        "game_state_blueprints": categories["game_state"],
        "player_state_blueprints": categories["player_state"],
        "player_controller_blueprints": categories["player_controller"],
        "ai_controller_blueprints": categories["ai_controller"],
        "controller_blueprints": categories["controller"],
        "pawn_blueprints": categories["pawn"],
        "character_blueprints": categories["character"],
        "hud_blueprints": categories["hud"],
        "spectator_pawn_blueprints": categories["spectator_pawn"],
        "game_instance_blueprints": categories["game_instance"],
        "game_mode_selector_rows": len(selector_rows),
        "game_mode_selector_owners": len(selector_owners),
        "project_game_mode_rows": len(project_game_mode_rows),
        "project_map_rows": len(project_map_rows),
        "project_setting_owners": len(project_setting_owners),
        "world_game_mode_override_rows": len(world_override_rows),
        "world_game_mode_override_owners": len(world_override_owners),
        "exact_framework_reference_rows": len(reference_rows),
        "exact_framework_reference_owners": len(reference_owners),
        "framework_usage_rows": len(usage_rows),
    })

    gaps: list[str] = []
    if categories["game_mode"] == 0 and not project_game_mode_rows:
        gaps.append(
            "No authored GameMode Blueprint or project GameMode-default evidence is proven; use a more representative corpus before schema design."
        )
    if categories["game_mode"] and not selector_rows:
        gaps.append(
            "GameMode Blueprint inheritance is proven, but DefaultPawn/GameState/PlayerState/PlayerController/HUD/Spectator class selectors are not anchored as canonical property rows; focused CDO/default capture is likely required."
        )
    if not project_game_mode_rows:
        gaps.append(
            "Project GameMapsSettings GameMode defaults are not normalized in current rows; focused config/default capture may be required."
        )
    if not project_map_rows:
        gaps.append(
            "Project startup/default map settings are not normalized in current rows; preserve them only if exact GameMapsSettings evidence can be captured."
        )
    if stream_totals.get("worlds.jsonl", 0) and not world_override_rows:
        gaps.append(
            "Worlds are present but no exact WorldSettings DefaultGameMode override is anchored; do not infer per-map GameMode selection from package names or dependencies."
        )
    if usage_rows:
        gaps.append(
            "Framework API usage is visible, but calls such as Possess/RestartPlayer remain usage evidence only; they must not be treated as runtime possession or spawn-state facts."
        )

    return {
        "output": str(output),
        "diagnostic_only": True,
        "semantic_promotion": False,
        "schema_promotion": False,
        "runtime_state_captured": False,
        "include_source": bool(include_source),
        "proof": proof,
        "categories": categories,
        "inheritance": inheritance,
        "selector_rows": selector_rows[:example_limit],
        "project_game_mode_rows": project_game_mode_rows[:example_limit],
        "project_map_rows": project_map_rows[:example_limit],
        "world_override_rows": world_override_rows[:example_limit],
        "reference_rows": reference_rows[:example_limit],
        "usage_rows": usage_rows[:example_limit],
        "stream_totals": stream_totals,
        "property_counts": property_counts,
        "class_counts": class_counts,
        "gaps": gaps,
        "examples": high_signal_examples[:example_limit],
    }


def _short(value: object, limit: int = 3200) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _print_counter(title: str, counter: collections.Counter, limit: int = 80) -> None:
    print(f"\n[{title}]")
    if not counter:
        print("<none>")
        return
    for value, count in counter.most_common(limit):
        print(f"  {count:7d}  {_short(value, 700)}")


def _print_rows(title: str, values: list[dict], limit: int) -> None:
    print(f"\n[{title}]")
    if not values:
        print("<none>")
        return
    for index, item in enumerate(values[:limit]):
        print(f"[{index}] {item.get('stream','')}:{item.get('line','')} owner={_short(item.get('owner',''), 500)} property={_short(item.get('property',''), 500)}")
        print("  " + _short(json.dumps(item.get("row", {}), ensure_ascii=False, sort_keys=True, separators=(",", ":"))))


def render_report(report: dict, *, row_limit: int = 30) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print("=== GAMEPLAY FRAMEWORK EVIDENCE REPORT ===")
        print(report.get("output", ""))
        print("diagnostic_only=True semantic_promotion=False schema_promotion=False runtime_state_captured=False")
        print(f"include_source={bool(report.get('include_source', False))}")
        _print_counter("Corpus proof", collections.Counter(report.get("proof", {})), 80)
        _print_counter("Framework Blueprint categories", collections.Counter(report.get("categories", {})), 80)

        print("\n[Exact framework Blueprint inheritance]")
        inheritance = report.get("inheritance", []) or []
        if not inheritance:
            print("<none>")
        for item in inheritance[:200]:
            mode = "transitive" if item.get("parent_is_framework_blueprint") else "native-root"
            print(
                f"  {item.get('kind',''):18s} {mode:11s} {item.get('blueprint','')}\n"
                f"    generated={item.get('generated_class','')}\n"
                f"    parent={item.get('parent_class','')}"
            )

        _print_rows("GameMode class-selector evidence", report.get("selector_rows", []), row_limit)
        _print_rows("Project GameMode settings evidence", report.get("project_game_mode_rows", []), row_limit)
        _print_rows("Project map settings evidence", report.get("project_map_rows", []), row_limit)
        _print_rows("WorldSettings GameMode override evidence", report.get("world_override_rows", []), row_limit)
        _print_rows("Exact framework reference evidence", report.get("reference_rows", []), row_limit)
        _print_rows("Framework API usage evidence (not runtime state)", report.get("usage_rows", []), row_limit)

        print("\n[Evidence gaps / next capture requirements]")
        gaps = report.get("gaps", []) or []
        if not gaps:
            print("  <none identified by this diagnostic>")
        for gap in gaps:
            print("  - " + gap)

        _print_counter("Matched streams", collections.Counter(report.get("stream_totals", {})), 80)
        _print_counter("High-signal property names/paths", collections.Counter(report.get("property_counts", {})), 120)
        print("\n========================================================================")
    return buffer.getvalue()


def _write_console_safe(text: str, stream=None) -> None:
    stream = sys.stdout if stream is None else stream
    try:
        stream.write(text)
    except UnicodeEncodeError:
        encoding = getattr(stream, "encoding", None) or "utf-8"
        stream.write(text.encode(encoding, errors="backslashreplace").decode(encoding))
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


def _cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool gameplay-framework-evidence",
        description="inventory authored Gameplay Framework defaults/relationships without changing the corpus or defining a schema",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("--no-source", action="store_true", help="skip source_chunks.jsonl")
    parser.add_argument("--row-limit", type=int, default=30, help="maximum example rows per evidence section")
    parser.add_argument("--report", help="optional UTF-8 report path")
    args = parser.parse_args(argv)
    if args.row_limit < 1:
        parser.error("--row-limit must be >= 1")
    output = Path(args.output).expanduser().resolve()
    if not output.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {output}")
    report = build_report(
        output,
        runtime_module._rows,
        include_source=not args.no_source,
        example_limit=max(args.row_limit, 40),
    )
    rendered = render_report(report, row_limit=args.row_limit)
    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"wrote Gameplay Framework evidence report: {report_path}")
    _write_console_safe(rendered)
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_gameplay_framework_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "gameplay-framework-evidence":
            try:
                return _cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 59
        return original_main()

    runtime_module.main = main
    runtime_module._gameplay_framework_evidence_installed = True
