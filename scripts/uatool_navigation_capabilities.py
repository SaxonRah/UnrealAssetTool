#!/usr/bin/env python3
"""First-class authored Navigation capability contract after schema-11 acceptance."""
from __future__ import annotations

from pathlib import Path

NAVIGATION_STREAMS = (
    "navigation_areas.jsonl",
    "navigation_area_agent_mappings.jsonl",
    "navigation_systems.jsonl",
    "navigation_agents.jsonl",
    "navigation_link_defaults.jsonl",
    "navigation_modifier_defaults.jsonl",
    "navigation_invoker_defaults.jsonl",
    "navigation_bounds_defaults.jsonl",
    "navigation_recast_defaults.jsonl",
)

NAVIGATION_BOUNDARY = (
    "Authored/default Navigation definitions and project-applied config: NavArea costs/agent masks/meta mappings, "
    "NavigationSystem supported-agent records, NavLink/SmartLink defaults, modifier/invoker/bounds defaults and "
    "Recast authored defaults. World schema 12 remains authoritative for placed Navigation actors/components, "
    "transforms and instance overrides. Generated RecastNavMesh instances/tiles/polys, runtime path queries, "
    "dirty-tile history and path-following state are not captured or promoted."
)


def _acceptance(capabilities_module, output: Path) -> dict:
    accepted = capabilities_module._read_json(output / "systems_schema11_acceptance.json")
    verified = capabilities_module._read_json(output / "navigation_graph_verification.json")
    project = str(accepted.get("project", "") or "")
    return {
        "accepted": bool(accepted) and int(accepted.get("systems_schema_version", 0) or 0) == 11,
        "verification": bool(verified.get("verified", False))
        and int(verified.get("derived_schema_version", 0) or 0) == 27,
        "corpus_provenance": Path(project).name if project else "",
        "world_placement_authority": str(accepted.get("world_placement_authority", "world schema 12") or "world schema 12"),
        "generated_navmesh_instances_captured": bool(accepted.get("generated_navmesh_instances_captured", False)),
    }


def _relations() -> list[str]:
    try:
        import uatool_navigation_graph as graph
        return sorted(str(relation) for relation in graph.RELATION_STREAMS)
    except Exception:
        return []


def _upsert(families: list, row: dict) -> None:
    for index, existing in enumerate(families):
        if isinstance(existing, dict) and existing.get("family") == row["family"]:
            families[index] = row
            return
    families.append(row)


def install(capabilities_module) -> None:
    if getattr(capabilities_module, "_navigation_capabilities_installed", False):
        return

    original_build_manifest = capabilities_module.build_manifest

    def build_manifest(output: Path) -> dict:
        output = Path(output).expanduser().resolve()
        manifest = original_build_manifest(output)
        systems = capabilities_module._read_json(output / "systems_manifest.json")
        systems_files = set(capabilities_module._manifest_files(systems))
        schemas = manifest.get("schemas", {}) if isinstance(manifest.get("schemas"), dict) else {}
        systems_version = int(schemas.get("systems", 0) or 0)
        systems_ok = bool(systems) and bool(systems.get("success", True)) and systems_version >= 11
        available = systems_ok and all(name in systems_files for name in NAVIGATION_STREAMS)

        row = {
            "family": "authored_navigation",
            "contract_coverage": "first_class",
            "corpus_coverage": "first_class" if available else "external_or_excluded",
            "available_in_corpus": bool(available),
            "canonical_pass": "systems+world",
            "canonical_streams": sorted(name for name in NAVIGATION_STREAMS if name in systems_files),
            "derived_streams": [],
            "derived_relations": _relations(),
            "runtime_state_captured": False,
            "boundary": NAVIGATION_BOUNDARY,
            "acceptance": _acceptance(capabilities_module, output),
        }

        families = manifest.get("families", [])
        if not isinstance(families, list):
            families = []
        _upsert(families, row)
        manifest["families"] = families
        return manifest

    capabilities_module.build_manifest = build_manifest
    capabilities_module._navigation_capabilities_installed = True
