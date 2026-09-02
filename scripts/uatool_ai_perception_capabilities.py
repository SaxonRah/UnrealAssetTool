#!/usr/bin/env python3
"""First-class AI Perception capability contract extension after schema-8 acceptance."""
from __future__ import annotations

from pathlib import Path

AI_PERCEPTION_STREAMS = (
    "ai_perception_components.jsonl",
    "ai_perception_sense_configs.jsonl",
    "ai_perception_stimuli_sources.jsonl",
    "ai_perception_registered_senses.jsonl",
    "ai_perception_properties.jsonl",
)

AI_PERCEPTION_BOUNDARY = (
    "Authored AIPerceptionComponent templates, ordered sense configs and dominant sense, "
    "stimuli-source templates, ordered registered senses and bounded reflected authored/default "
    "property state; live listener state, perceived actors, stimulus history, runtime registration "
    "state and sense-query results are not captured."
)


def _acceptance(capabilities_module, output: Path) -> dict:
    accepted = capabilities_module._read_json(output / "systems_schema8_acceptance.json")
    verified = capabilities_module._read_json(output / "ai_perception_graph_verification.json")
    project = str(accepted.get("project", "") or "")
    return {
        "accepted": bool(accepted) and int(accepted.get("systems_schema_version", 0) or 0) == 8,
        "verification": bool(verified.get("verified", False))
        and int(verified.get("derived_schema_version", 0) or 0) == 24,
        "corpus_provenance": Path(project).name if project else "",
    }


def _relations() -> list[str]:
    try:
        import uatool_ai_perception_graph as graph
        return sorted(str(value) for value in graph.RELATION_STREAMS)
    except Exception:
        return []


def install(capabilities_module) -> None:
    if getattr(capabilities_module, "_ai_perception_capabilities_installed", False):
        return

    original_build_manifest = capabilities_module.build_manifest

    def build_manifest(output: Path) -> dict:
        output = Path(output).expanduser().resolve()
        manifest = original_build_manifest(output)
        systems = capabilities_module._read_json(output / "systems_manifest.json")
        systems_files = set(capabilities_module._manifest_files(systems))
        schemas = manifest.get("schemas", {}) if isinstance(manifest.get("schemas"), dict) else {}
        systems_version = int(schemas.get("systems", 0) or 0)
        available = (
            bool(systems)
            and bool(systems.get("success", True))
            and systems_version >= 8
            and all(name in systems_files for name in AI_PERCEPTION_STREAMS)
        )

        row = {
            "family": "ai_perception",
            "contract_coverage": "first_class",
            "corpus_coverage": "first_class" if available else "external_or_excluded",
            "available_in_corpus": bool(available),
            "canonical_pass": "systems",
            "canonical_streams": sorted(name for name in AI_PERCEPTION_STREAMS if name in systems_files),
            "derived_streams": [],
            "derived_relations": _relations(),
            "runtime_state_captured": False,
            "boundary": AI_PERCEPTION_BOUNDARY,
            "acceptance": _acceptance(capabilities_module, output),
        }

        families = manifest.get("families", [])
        if isinstance(families, list):
            replaced = False
            for index, existing in enumerate(families):
                if isinstance(existing, dict) and existing.get("family") == "ai_perception":
                    families[index] = row
                    replaced = True
                    break
            if not replaced:
                families.append(row)
        manifest["families"] = families
        return manifest

    capabilities_module.build_manifest = build_manifest
    capabilities_module._ai_perception_capabilities_installed = True
