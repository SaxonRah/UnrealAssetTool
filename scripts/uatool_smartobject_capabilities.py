#!/usr/bin/env python3
"""First-class Smart Objects capability contract extension after schema-7 acceptance."""
from __future__ import annotations

from pathlib import Path

SMARTOBJECT_STREAMS = (
    "smartobject_definitions.jsonl",
    "smartobject_slots.jsonl",
    "smartobject_behaviors.jsonl",
    "smartobject_behavior_properties.jsonl",
)

SMARTOBJECT_BOUNDARY = (
    "Authored Smart Object definitions, ordered slots, default/slot behavior definitions, "
    "selection/world-condition schemas and reflected behavior properties; live occupancy, "
    "claims, reservations, subsystem handles and execution history are not captured."
)


def _acceptance(capabilities_module, output: Path) -> dict:
    accepted = capabilities_module._read_json(output / "systems_schema7_acceptance.json")
    verified = capabilities_module._read_json(output / "smartobject_graph_verification.json")
    project = str(accepted.get("project", "") or "")
    return {
        "accepted": bool(accepted) and int(accepted.get("systems_schema_version", 0) or 0) == 7,
        "verification": bool(verified.get("verified", False))
        and int(verified.get("derived_schema_version", 0) or 0) == 23,
        "corpus_provenance": Path(project).name if project else "",
    }


def _relations() -> list[str]:
    try:
        import uatool_smartobject_graph as graph
        return sorted(str(value) for value in graph.RELATION_STREAMS)
    except Exception:
        return []


def install(capabilities_module) -> None:
    if getattr(capabilities_module, "_smartobject_capabilities_installed", False):
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
            and systems_version >= 7
            and all(name in systems_files for name in SMARTOBJECT_STREAMS)
        )

        row = {
            "family": "smart_objects",
            "contract_coverage": "first_class",
            "corpus_coverage": "first_class" if available else "external_or_excluded",
            "available_in_corpus": bool(available),
            "canonical_pass": "systems",
            "canonical_streams": sorted(name for name in SMARTOBJECT_STREAMS if name in systems_files),
            "derived_streams": [],
            "derived_relations": _relations(),
            "runtime_state_captured": False,
            "boundary": SMARTOBJECT_BOUNDARY,
            "acceptance": _acceptance(capabilities_module, output),
        }

        families = manifest.get("families", [])
        if isinstance(families, list):
            replaced = False
            for index, existing in enumerate(families):
                if isinstance(existing, dict) and existing.get("family") == "smart_objects":
                    families[index] = row
                    replaced = True
                    break
            if not replaced:
                families.append(row)
        manifest["families"] = families
        return manifest

    capabilities_module.build_manifest = build_manifest
    capabilities_module._smartobject_capabilities_installed = True
