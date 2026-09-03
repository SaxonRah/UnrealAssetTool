#!/usr/bin/env python3
"""First-class AnimNext / UAF capability contract after schema-10 acceptance."""
from __future__ import annotations

from pathlib import Path

UAF_STREAMS = (
    "uaf_assets.jsonl",
    "uaf_entries.jsonl",
    "uaf_variables.jsonl",
    "uaf_components.jsonl",
    "uaf_entry_points.jsonl",
    "uaf_rigvm_graphs.jsonl",
    "uaf_rigvm_nodes.jsonl",
    "uaf_rigvm_pins.jsonl",
    "uaf_rigvm_links.jsonl",
    "uaf_variable_usages.jsonl",
)

UAF_BOUNDARY = (
    "Authored/default UAF systems and animation graphs, entries, variables/bindings/defaults, components, "
    "runtime entry-point declarations and editor-side RigVM topology. Exact first-class asset identity is "
    "proven from loaded UObject classes. RigVM/VM execution, live pose/value state, ticking, runtime event "
    "execution, injection history, compiled execution state and transient graph instances are not captured."
)


def _acceptance(capabilities_module, output: Path) -> dict:
    accepted = capabilities_module._read_json(output / "systems_schema10_acceptance.json")
    verified = capabilities_module._read_json(output / "uaf_graph_verification.json")
    project = str(accepted.get("project", "") or "")
    return {
        "accepted": bool(accepted) and int(accepted.get("systems_schema_version", 0) or 0) == 10,
        "verification": bool(verified.get("verified", False))
        and int(verified.get("derived_schema_version", 0) or 0) == 26,
        "corpus_provenance": Path(project).name if project else "",
    }


def _relations() -> list[str]:
    try:
        import uatool_uaf_graph as graph
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
    if getattr(capabilities_module, "_uaf_capabilities_installed", False):
        return

    original_build_manifest = capabilities_module.build_manifest

    def build_manifest(output: Path) -> dict:
        output = Path(output).expanduser().resolve()
        manifest = original_build_manifest(output)
        systems = capabilities_module._read_json(output / "systems_manifest.json")
        systems_files = set(capabilities_module._manifest_files(systems))
        schemas = manifest.get("schemas", {}) if isinstance(manifest.get("schemas"), dict) else {}
        systems_version = int(schemas.get("systems", 0) or 0)
        systems_ok = bool(systems) and bool(systems.get("success", True)) and systems_version >= 10
        available = systems_ok and all(name in systems_files for name in UAF_STREAMS)

        row = {
            "family": "animnext",
            "contract_coverage": "first_class",
            "corpus_coverage": "first_class" if available else "external_or_excluded",
            "available_in_corpus": bool(available),
            "canonical_pass": "systems",
            "canonical_streams": sorted(name for name in UAF_STREAMS if name in systems_files),
            "derived_streams": [],
            "derived_relations": _relations(),
            "runtime_state_captured": False,
            "boundary": UAF_BOUNDARY,
            "acceptance": _acceptance(capabilities_module, output),
        }

        families = manifest.get("families", [])
        if not isinstance(families, list):
            families = []
        _upsert(families, row)
        manifest["families"] = families
        return manifest

    capabilities_module.build_manifest = build_manifest
    capabilities_module._uaf_capabilities_installed = True
