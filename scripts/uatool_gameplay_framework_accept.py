#!/usr/bin/env python3
"""Accept ContentExamples Gameplay Framework joins and verify derived schema 28."""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from pathlib import Path

import uatool_gameplay_framework_model as model

ACCEPTANCE_MANIFEST = "gameplay_framework_acceptance.json"
GRAPH_EXPECTATIONS_MANIFEST = "gameplay_framework_graph_expectations.json"
GRAPH_VERIFICATION_MANIFEST = "gameplay_framework_graph_verification.json"
TARGET_DERIVED_SCHEMA_VERSION = model.TARGET_DERIVED_SCHEMA_VERSION

RELATION_EVIDENCE_STREAMS = {
    "defines_gameplay_framework_class": {"blueprints.jsonl"},
    "inherits_gameplay_framework_class": {"blueprints.jsonl"},
    "game_mode_overrides_default_pawn_class": {"blueprint_state_values.jsonl"},
    "game_mode_overrides_hud_class": {"blueprint_state_values.jsonl"},
    "game_mode_overrides_player_controller_class": {"blueprint_state_values.jsonl"},
    "game_mode_overrides_game_state_class": {"blueprint_state_values.jsonl"},
    "game_mode_overrides_player_state_class": {"blueprint_state_values.jsonl"},
    "game_mode_overrides_spectator_class": {"blueprint_state_values.jsonl"},
    "game_mode_overrides_replay_spectator_player_controller_class": {"blueprint_state_values.jsonl"},
    "world_overrides_default_game_mode_class": {"world_instance_properties.jsonl"},
    "pawn_uses_ai_controller_class": {"blueprint_state_values.jsonl", "world_references.jsonl"},
    "project_sets_global_default_game_mode_class": {"source_chunks.jsonl"},
    "project_sets_global_default_server_game_mode_class": {"source_chunks.jsonl"},
    "project_sets_game_instance_class": {"source_chunks.jsonl"},
    "project_sets_game_default_map": {"source_chunks.jsonl"},
    "project_sets_server_default_map": {"source_chunks.jsonl"},
    "project_sets_editor_startup_map": {"source_chunks.jsonl"},
    "project_sets_transition_map": {"source_chunks.jsonl"},
}


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{path.name} root is not an object")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _resolve_corpus(value: str) -> Path:
    corpus = Path(value).expanduser().resolve()
    if not corpus.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {corpus}")
    return corpus


def _expectations(corpus: Path, rows) -> dict:
    data = model.build_model(corpus, rows)
    edges = {
        (spec["source"], spec["relation"], spec["target"])
        for spec in data["edge_specs"]
    }
    relation_counts = collections.Counter(relation for _, relation, _ in edges)
    return {
        "schema_version": 1,
        "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
        "edge_quality": "exact_semantic",
        "runtime_state_captured": False,
        "expected_relation_counts": {
            relation: int(relation_counts.get(relation, 0))
            for relation in sorted(model.RELATIONS)
        },
        "expected_exact_semantic_edge_count": len(edges),
        "expected_edges": [
            {"source": source, "relation": relation, "target": target}
            for source, relation, target in sorted(edges)
        ],
    }


def _require_contentexamples_shape(data: dict) -> None:
    counts = data["counts"]
    # The original evidence report saw each authored WorldSettings.DefaultGameMode
    # twice: once as a canonical property row and once as its exact reference row.
    # Schema 28 uses world_instance_properties.jsonl as the authoritative edge
    # source, so acceptance is based on the 70 unique WorldSettings owners/edges,
    # not the 140 duplicated evidence rows.
    minimums = {
        "framework_blueprints": 36,
        "transitive_framework_blueprints": 4,
        "game_mode_blueprints": 8,
        "character_blueprints": 17,
        "player_controller_blueprints": 4,
        "ai_controller_blueprints": 1,
        "game_mode_selector_overrides": 15,
        "world_game_mode_overrides": 70,
        "project_game_maps_settings": 5,
    }
    missing = [
        f"{key}<{minimum}"
        for key, minimum in minimums.items()
        if int(counts.get(key, 0) or 0) < minimum
    ]
    if missing:
        raise RuntimeError("Gameplay Framework representative corpus is incomplete: " + ", ".join(missing))

    records = {item["blueprint_path"]: item for item in data["framework_blueprints"]}
    required_blueprints = {
        "/Game/Global/Blueprints/CE_Game.CE_Game": "game_mode",
        "/Game/ExampleContent/StateTree/Blueprints/Gameplay/CE_Game_Gameplay.CE_Game_Gameplay": "game_mode",
        "/Game/Global/Blueprints/PlayerCharacter.PlayerCharacter": "character",
        "/Game/ExampleContent/Blueprint_Communication/Blueprints/MyCharacter_BP_Comms.MyCharacter_BP_Comms": "character",
        "/Game/ExampleContent/StateTree/Blueprints/Enemies/BP_AIController.BP_AIController": "ai_controller",
    }
    absent = [
        path for path, kind in required_blueprints.items()
        if path not in records or records[path]["framework_kind"] != kind
    ]
    if absent:
        raise RuntimeError("Gameplay Framework representative Blueprint identity missing: " + ", ".join(absent))
    for path in (
        "/Game/ExampleContent/StateTree/Blueprints/Gameplay/CE_Game_Gameplay.CE_Game_Gameplay",
        "/Game/ExampleContent/Blueprint_Communication/Blueprints/MyCharacter_BP_Comms.MyCharacter_BP_Comms",
    ):
        if not bool(records[path]["transitive"]):
            raise RuntimeError(f"Gameplay Framework representative transitive inheritance not proven: {path}")

    settings = data["game_maps_settings"]
    required_settings = {
        "GlobalDefaultGameMode": "/Script/Engine.GameModeBase",
        "GameInstanceClass": "/Script/Engine.GameInstance",
        "GameDefaultMap": "/Game/Maps/ExampleProjectWelcome.ExampleProjectWelcome",
        "ServerDefaultMap": "/Game/Maps/ExampleProjectWelcome.ExampleProjectWelcome",
        "EditorStartupMap": "/Game/Maps/ExampleProjectWelcome.ExampleProjectWelcome",
    }
    wrong = [
        f"{key}={settings.get(key, {}).get('value', '<missing>')}"
        for key, expected in required_settings.items()
        if str(settings.get(key, {}).get("value", "")) != expected
    ]
    if wrong:
        raise RuntimeError("Gameplay Framework GameMapsSettings mismatch: " + ", ".join(wrong))

    edges = {
        (spec["source"], spec["relation"], spec["target"])
        for spec in data["edge_specs"]
    }
    required_edges = {
        (
            "/Game/ExampleContent/StateTree/Blueprints/Gameplay/CE_Game_Gameplay.CE_Game_Gameplay_C",
            "inherits_gameplay_framework_class",
            "/Game/Global/Blueprints/CE_Game.CE_Game_C",
        ),
        (
            "/Game/ExampleContent/Blueprint_Communication/Blueprints/BP_GameMode_BP_Comms.BP_GameMode_BP_Comms_C",
            "game_mode_overrides_default_pawn_class",
            "/Game/ExampleContent/Blueprint_Communication/Blueprints/MyCharacter_BP_Comms.MyCharacter_BP_Comms_C",
        ),
        (
            "/Game/Maps/AI/AI_StateTree.AI_StateTree",
            "world_overrides_default_game_mode_class",
            "/Game/ExampleContent/StateTree/Blueprints/Gameplay/CE_Game_Gameplay.CE_Game_Gameplay_C",
        ),
        (
            model.GAME_MAPS_SETTINGS_NODE,
            "project_sets_global_default_game_mode_class",
            "/Script/Engine.GameModeBase",
        ),
    }
    missing_edges = sorted(required_edges - edges)
    if missing_edges:
        raise RuntimeError(f"Gameplay Framework representative exact joins missing: first={missing_edges[0]}")


def accept(corpus: Path, rows) -> dict:
    required_files = (
        "blueprints.jsonl",
        "blueprint_state_values.jsonl",
        "worlds.jsonl",
        "world_instance_properties.jsonl",
        "world_references.jsonl",
        "source_chunks.jsonl",
    )
    missing = [name for name in required_files if not (corpus / name).is_file()]
    if missing:
        raise RuntimeError("Gameplay Framework acceptance missing canonical files: " + ", ".join(missing))

    data = model.build_model(corpus, rows)
    _require_contentexamples_shape(data)
    expectations = _expectations(corpus, rows)
    if expectations["expected_exact_semantic_edge_count"] <= 0:
        raise RuntimeError("Gameplay Framework acceptance produced no exact semantic graph edges")

    acceptance = {
        "acceptance_schema_version": 1,
        "target_derived_schema_version": TARGET_DERIVED_SCHEMA_VERSION,
        "representative_content": "ContentExamples UE 5.8.2 structural/world/config authored Gameplay Framework evidence",
        "canonical_passes": ["structural", "world", "source"],
        "canonical_schema_requirements": {"structural": 13, "world": 12},
        "systems_schema_version_unchanged": True,
        "runtime_state_captured": False,
        "runtime_possession_state_captured": False,
        "runtime_spawn_state_captured": False,
        "native_default_state_inferred": False,
        "counts": data["counts"],
        "category_counts": data["category_counts"],
        "selector_counts": data["selector_counts"],
        "expected_relation_counts": expectations["expected_relation_counts"],
        "expected_exact_semantic_edge_count": expectations["expected_exact_semantic_edge_count"],
    }
    _write_json(corpus / ACCEPTANCE_MANIFEST, acceptance)
    _write_json(corpus / GRAPH_EXPECTATIONS_MANIFEST, expectations)
    return acceptance


def verify(corpus: Path, rows) -> dict:
    expectations = _read_json(corpus / GRAPH_EXPECTATIONS_MANIFEST)
    top = _read_json(corpus / "manifest.json")
    actual_version = int(top.get("derived_schema_version", 0) or 0)
    if actual_version != TARGET_DERIVED_SCHEMA_VERSION:
        raise RuntimeError(
            f"Gameplay Framework graph verification requires derived schema {TARGET_DERIVED_SCHEMA_VERSION}; got {actual_version}"
        )

    expected = model.expected_edge_keys(corpus, rows)
    project_edges = list(_iter_project_edges(corpus, rows))
    actual_rows = [row for row in project_edges if str(row.get("relation", "") or "") in model.RELATIONS]
    actual = {
        (str(row.get("source", "") or ""), str(row.get("relation", "") or ""), str(row.get("target", "") or ""))
        for row in actual_rows
    }
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        detail = []
        if missing:
            detail.append(f"missing={len(missing)} first={missing[0]}")
        if extra:
            detail.append(f"extra={len(extra)} first={extra[0]}")
        raise RuntimeError("Gameplay Framework exact graph edge set mismatch: " + "; ".join(detail))

    counts = collections.Counter()
    for row in actual_rows:
        relation = str(row.get("relation", "") or "")
        counts[relation] += 1
        if str(row.get("edge_quality", "") or "") != "exact_semantic":
            raise RuntimeError(f"Gameplay Framework relation is not exact_semantic: {relation}")
        allowed = RELATION_EVIDENCE_STREAMS.get(relation, set())
        evidence = row.get("evidence", []) if isinstance(row.get("evidence", []), list) else []
        if allowed and not any(
            isinstance(item, dict) and str(item.get("stream", "")) in allowed
            for item in evidence
        ):
            raise RuntimeError(f"Gameplay Framework relation lacks canonical evidence: {relation}")

    expected_counts = expectations.get("expected_relation_counts", {})
    for relation in sorted(model.RELATIONS):
        if int(expected_counts.get(relation, 0) or 0) != int(counts.get(relation, 0)):
            raise RuntimeError(
                f"Gameplay Framework relation count mismatch for {relation}: "
                f"expected={expected_counts.get(relation,0)} actual={counts.get(relation,0)}"
            )

    result = {
        "schema_version": 1,
        "verified": True,
        "derived_schema_version": actual_version,
        "edge_quality": "exact_semantic",
        "expected_exact_semantic_edge_count": len(expected),
        "verified_exact_semantic_edge_count": len(actual),
        "relation_counts": {
            relation: int(counts.get(relation, 0))
            for relation in sorted(model.RELATIONS)
        },
        "runtime_state_captured": False,
        "runtime_possession_state_captured": False,
        "runtime_spawn_state_captured": False,
        "native_default_state_inferred": False,
    }
    _write_json(corpus / GRAPH_VERIFICATION_MANIFEST, result)
    return result


def _iter_project_edges(corpus: Path, rows):
    path = corpus / "project_edges.jsonl"
    if not path.is_file():
        raise RuntimeError("project_edges.jsonl is missing; run derive first")
    yield from rows(path)


def _accept_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool gameplay-framework-accept")
    parser.add_argument("corpus", help="full canonical corpus directory, e.g. ContentExamples/.uatool")
    args = parser.parse_args(argv)
    corpus = _resolve_corpus(args.corpus)
    result = accept(corpus, runtime_module._rows)
    print(f"accepted ContentExamples Gameplay Framework authored joins: {corpus}")
    print(f"acceptance manifest: {corpus / ACCEPTANCE_MANIFEST}")
    print(f"graph expectations: {corpus / GRAPH_EXPECTATIONS_MANIFEST}")
    print(f"  target_derived_schema_version: {TARGET_DERIVED_SCHEMA_VERSION}")
    print(f"  framework_blueprints: {result['counts']['framework_blueprints']}")
    print(f"  transitive_framework_blueprints: {result['counts']['transitive_framework_blueprints']}")
    print(f"  game_mode_selector_overrides: {result['counts']['game_mode_selector_overrides']}")
    print(f"  world_game_mode_overrides: {result['counts']['world_game_mode_overrides']}")
    print(f"  project_game_maps_settings: {result['counts']['project_game_maps_settings']}")
    print(f"  expected_exact_semantic_edges: {result['expected_exact_semantic_edge_count']}")
    for relation, count in sorted(result["expected_relation_counts"].items()):
        if count:
            print(f"    {relation}: {count}")
    print("  runtime_state_captured: False")
    print("  native_default_state_inferred: False")
    print("Unreal was not run")
    print("derive was not run")
    return 0


def _verify_cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="uatool gameplay-framework-graph-verify")
    parser.add_argument("corpus", help="accepted/derived full corpus directory")
    args = parser.parse_args(argv)
    corpus = _resolve_corpus(args.corpus)
    result = verify(corpus, runtime_module._rows)
    print(f"verified Gameplay Framework derived-schema-{TARGET_DERIVED_SCHEMA_VERSION} project graph: {corpus}")
    print(f"verification manifest: {corpus / GRAPH_VERIFICATION_MANIFEST}")
    print(f"  exact_semantic_edges: {result['verified_exact_semantic_edge_count']}")
    for relation, count in sorted(result["relation_counts"].items()):
        if count:
            print(f"  {relation}: {count}")
    print("  runtime_state_captured: False")
    print("  native_default_state_inferred: False")
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_gameplay_framework_accept_installed", False):
        return
    try:
        import uatool_core as core
        core.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((
            *core.DEFAULT_BUNDLE_FILES,
            ACCEPTANCE_MANIFEST,
            GRAPH_EXPECTATIONS_MANIFEST,
            GRAPH_VERIFICATION_MANIFEST,
        )))
    except Exception:
        pass

    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "gameplay-framework-accept":
            try:
                return _accept_cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 57
        if len(sys.argv) > 1 and sys.argv[1] == "gameplay-framework-graph-verify":
            try:
                return _verify_cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 58
        return original_main()

    runtime_module.main = main
    runtime_module._gameplay_framework_accept_installed = True
