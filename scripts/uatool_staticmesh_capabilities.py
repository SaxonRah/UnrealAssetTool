#!/usr/bin/env python3
"""First-class StaticMesh capability contract for mesh schema 1."""
from __future__ import annotations

from pathlib import Path

import uatool_staticmesh_schema as mesh_schema
import uatool_staticmesh_graph as graph

BOUNDARY = (
    "Authored StaticMesh topology and settings: exact asset identity, SourceModel LODs with build/reduction settings, ordered material slots, "
    "owned sockets, BodySetup/simple AggGeom collision, exact complex-collision-mesh reference when authored, and selected Nanite/section/lightmap/LOD/build settings. "
    "Render/vertex/index buffers, generated Nanite clusters/pages/resources, cooked collision, runtime physics state, world placement and component material overrides are excluded."
)


def _read_acceptance(capabilities_module, output: Path) -> dict:
    accepted = capabilities_module._read_json(output / "staticmesh_schema1_acceptance.json")
    verified = capabilities_module._read_json(output / "staticmesh_schema1_graph_verification.json")
    return {
        "accepted": bool(accepted) and int(accepted.get("mesh_schema_version", 0) or 0) == mesh_schema.MESH_SCHEMA_VERSION,
        "verification": bool(verified.get("verified", False)) and int(verified.get("derived_schema_version", 0) or 0) == graph.TARGET_DERIVED_SCHEMA_VERSION,
        "representative_content": str(accepted.get("representative_content", "")),
        "runtime_state_captured": bool(accepted.get("runtime_state_captured", False)),
    }


def _upsert(families: list, row: dict) -> None:
    for index, existing in enumerate(families):
        if isinstance(existing, dict) and existing.get("family") == row["family"]:
            families[index] = row
            return
    families.append(row)


def install(capabilities_module) -> None:
    if getattr(capabilities_module, "_staticmesh_schema1_capabilities_installed", False):
        return
    original_build_manifest = capabilities_module.build_manifest

    def build_manifest(output: Path) -> dict:
        output = Path(output).expanduser().resolve()
        manifest = original_build_manifest(output)
        mesh = capabilities_module._read_json(output / mesh_schema.MANIFEST_FILE)
        mesh_files = set(capabilities_module._manifest_files(mesh))
        schemas = manifest.get("schemas", {}) if isinstance(manifest.get("schemas"), dict) else {}
        schemas["mesh"] = int(mesh.get("schema_version", 0) or 0) if mesh else 0
        manifest["schemas"] = schemas

        available = (
            bool(mesh)
            and bool(mesh.get("success", True))
            and int(mesh.get("schema_version", 0) or 0) == mesh_schema.MESH_SCHEMA_VERSION
            and all(name in mesh_files for name in mesh_schema.JSONL_FILES)
        )
        row = {
            "family": "static_mesh",
            "contract_coverage": "first_class",
            "corpus_coverage": "first_class" if available else "external_or_excluded",
            "available_in_corpus": bool(available),
            "canonical_pass": "mesh",
            "canonical_streams": sorted(name for name in mesh_schema.JSONL_FILES if name in mesh_files),
            "derived_streams": ["project_nodes.jsonl", "project_edges.jsonl"],
            "derived_relations": sorted(graph.RELATIONS),
            "runtime_state_captured": False,
            "boundary": BOUNDARY,
            "acceptance": _read_acceptance(capabilities_module, output),
        }
        families = manifest.get("families", [])
        if not isinstance(families, list):
            families = []
        _upsert(families, row)
        manifest["families"] = families

        passes = manifest.get("canonical_passes", [])
        passes = list(passes) if isinstance(passes, list) else []
        if available and "mesh" not in passes:
            passes.append("mesh")
        manifest["canonical_passes"] = passes
        return manifest

    capabilities_module.build_manifest = build_manifest
    capabilities_module._staticmesh_schema1_capabilities_installed = True
