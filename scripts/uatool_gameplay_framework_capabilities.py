#!/usr/bin/env python3
"""First-class authored Gameplay Framework capability contract for derived schema 28."""
from __future__ import annotations

from pathlib import Path

import uatool_gameplay_framework_model as model

CANONICAL_STREAMS = (
    "blueprints.jsonl",
    "blueprint_state_values.jsonl",
    "source_chunks.jsonl",
    "worlds.jsonl",
    "world_instance_properties.jsonl",
    "world_references.jsonl",
)

BOUNDARY = (
    "Exact authored Gameplay Framework project joins: Blueprint -> generated class -> immediate framework parent, "
    "explicit GameMode class-selector overrides, GameMapsSettings global/default map and GameInstance choices, "
    "WorldSettings.DefaultGameMode overrides, and exact Pawn/Character AIControllerClass references. "
    "Unchanged native GameMode defaults are not invented when absent from the corpus; runtime GameMode selection, "
    "spawned Pawn/Controller/PlayerState instances, possession history, travel/session state and live framework state "
    "are not captured."
)


def _upsert(families: list, row: dict) -> None:
    for index, existing in enumerate(families):
        if isinstance(existing, dict) and existing.get("family") == row["family"]:
            families[index] = row
            return
    families.append(row)


def _acceptance(capabilities_module, output: Path) -> dict:
    accepted = capabilities_module._read_json(output / "gameplay_framework_acceptance.json")
    verified = capabilities_module._read_json(output / "gameplay_framework_graph_verification.json")
    return {
        "accepted": bool(accepted)
        and int(accepted.get("target_derived_schema_version", 0) or 0) == model.TARGET_DERIVED_SCHEMA_VERSION,
        "verification": bool(verified.get("verified", False))
        and int(verified.get("derived_schema_version", 0) or 0) == model.TARGET_DERIVED_SCHEMA_VERSION,
        "corpus_provenance": "ContentExamples UE 5.8.2" if accepted else "",
        "native_default_state_inferred": bool(accepted.get("native_default_state_inferred", False)),
    }


def install(capabilities_module) -> None:
    if getattr(capabilities_module, "_gameplay_framework_capabilities_installed", False):
        return
    original_build_manifest = capabilities_module.build_manifest

    def build_manifest(output: Path) -> dict:
        output = Path(output).expanduser().resolve()
        manifest = original_build_manifest(output)
        schemas = manifest.get("schemas", {}) if isinstance(manifest.get("schemas"), dict) else {}
        structural_ok = int(schemas.get("structural", 0) or 0) >= 12
        world_ok = int(schemas.get("world", 0) or 0) >= 12
        derived_ok = int(schemas.get("derived", 0) or 0) >= model.TARGET_DERIVED_SCHEMA_VERSION
        available_streams = [name for name in CANONICAL_STREAMS if (output / name).is_file()]
        available = structural_ok and world_ok and derived_ok and len(available_streams) == len(CANONICAL_STREAMS)

        row = {
            "family": "gameplay_framework",
            "contract_coverage": "first_class",
            "corpus_coverage": "first_class" if available else "external_or_excluded",
            "available_in_corpus": bool(available),
            "canonical_pass": "structural+world+source",
            "canonical_streams": sorted(available_streams),
            "derived_streams": ["project_nodes.jsonl", "project_edges.jsonl"],
            "derived_relations": sorted(model.RELATIONS),
            "runtime_state_captured": False,
            "boundary": BOUNDARY,
            "acceptance": _acceptance(capabilities_module, output),
        }
        families = manifest.get("families", [])
        if not isinstance(families, list):
            families = []
        _upsert(families, row)
        manifest["families"] = families
        return manifest

    capabilities_module.build_manifest = build_manifest
    capabilities_module._gameplay_framework_capabilities_installed = True
