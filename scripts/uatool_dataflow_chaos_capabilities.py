#!/usr/bin/env python3
"""First-class Dataflow and Geometry Collection capability contracts after schema-9 acceptance."""
from __future__ import annotations

from pathlib import Path

DATAFLOW_STREAMS = (
    "dataflow_graphs.jsonl",
    "dataflow_nodes.jsonl",
    "dataflow_pins.jsonl",
    "dataflow_edges.jsonl",
    "dataflow_asset_properties.jsonl",
    "dataflow_asset_references.jsonl",
    "dataflow_node_properties.jsonl",
    "dataflow_node_references.jsonl",
)

GEOMETRY_COLLECTION_STREAMS = (
    "geometry_collections.jsonl",
    "geometry_collection_properties.jsonl",
    "geometry_collection_references.jsonl",
)

DATAFLOW_BOUNDARY = (
    "Authored UDataflow graph identity, concrete node structs, ordered input/output pins, exact links, "
    "bounded authored asset/node property state and direct hard/soft object references. Runtime graph "
    "evaluation/results are not captured, and higher-level Cloth/Flesh/Hair/Vehicles semantics are not "
    "inferred merely because those systems can consume Dataflow."
)

GEOMETRY_COLLECTION_BOUNDARY = (
    "Authored Geometry Collection destruction behavior including clustering, damage, connection, "
    "mass/sleep/removal, SizeSpecificData, physics material, DataflowInstance/Overrides and nullable "
    "DataflowAsset state. GeometrySource editor/construction provenance is explicitly excluded from the "
    "first-class behavior stream. Chaos solver state, dynamic transforms, break/collision/removal history, "
    "cache playback and runtime Field System results are not captured."
)


def _acceptance(capabilities_module, output: Path) -> dict:
    accepted = capabilities_module._read_json(output / "systems_schema9_acceptance.json")
    verified = capabilities_module._read_json(output / "dataflow_chaos_graph_verification.json")
    project = str(accepted.get("project", "") or "")
    return {
        "accepted": bool(accepted) and int(accepted.get("systems_schema_version", 0) or 0) == 9,
        "verification": bool(verified.get("verified", False))
        and int(verified.get("derived_schema_version", 0) or 0) == 25,
        "corpus_provenance": Path(project).name if project else "",
    }


def _relations(prefix: str) -> list[str]:
    try:
        import uatool_dataflow_chaos_graph as graph
        if prefix == "dataflow":
            return sorted(
                relation
                for relation in graph.RELATION_STREAMS
                if relation.startswith("dataflow_")
                or relation.startswith("has_dataflow_")
                or relation == "instance_of_dataflow_node_struct"
            )
        return sorted(
            relation
            for relation in graph.RELATION_STREAMS
            if relation.startswith("geometry_collection_")
        )
    except Exception:
        return []


def _upsert(families: list, row: dict) -> None:
    for index, existing in enumerate(families):
        if isinstance(existing, dict) and existing.get("family") == row["family"]:
            families[index] = row
            return
    families.append(row)


def install(capabilities_module) -> None:
    if getattr(capabilities_module, "_dataflow_chaos_capabilities_installed", False):
        return

    original_build_manifest = capabilities_module.build_manifest

    def build_manifest(output: Path) -> dict:
        output = Path(output).expanduser().resolve()
        manifest = original_build_manifest(output)
        systems = capabilities_module._read_json(output / "systems_manifest.json")
        systems_files = set(capabilities_module._manifest_files(systems))
        schemas = manifest.get("schemas", {}) if isinstance(manifest.get("schemas"), dict) else {}
        systems_version = int(schemas.get("systems", 0) or 0)
        systems_ok = bool(systems) and bool(systems.get("success", True)) and systems_version >= 9

        dataflow_available = systems_ok and all(name in systems_files for name in DATAFLOW_STREAMS)
        geometry_available = systems_ok and all(name in systems_files for name in GEOMETRY_COLLECTION_STREAMS)
        acceptance = _acceptance(capabilities_module, output)

        dataflow_row = {
            "family": "dataflow",
            "contract_coverage": "first_class",
            "corpus_coverage": "first_class" if dataflow_available else "external_or_excluded",
            "available_in_corpus": bool(dataflow_available),
            "canonical_pass": "systems",
            "canonical_streams": sorted(name for name in DATAFLOW_STREAMS if name in systems_files),
            "derived_streams": [],
            "derived_relations": _relations("dataflow"),
            "runtime_state_captured": False,
            "boundary": DATAFLOW_BOUNDARY,
            "acceptance": dict(acceptance),
        }
        geometry_row = {
            "family": "geometry_collection",
            "contract_coverage": "first_class",
            "corpus_coverage": "first_class" if geometry_available else "external_or_excluded",
            "available_in_corpus": bool(geometry_available),
            "canonical_pass": "systems",
            "canonical_streams": sorted(name for name in GEOMETRY_COLLECTION_STREAMS if name in systems_files),
            "derived_streams": [],
            "derived_relations": _relations("geometry_collection"),
            "runtime_state_captured": False,
            "boundary": GEOMETRY_COLLECTION_BOUNDARY,
            "acceptance": dict(acceptance),
        }

        families = manifest.get("families", [])
        if not isinstance(families, list):
            families = []
        _upsert(families, dataflow_row)
        _upsert(families, geometry_row)
        manifest["families"] = families
        return manifest

    capabilities_module.build_manifest = build_manifest
    capabilities_module._dataflow_chaos_capabilities_installed = True
