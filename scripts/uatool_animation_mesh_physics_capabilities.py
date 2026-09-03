#!/usr/bin/env python3
"""First-class SkeletalMesh / PhysicsAsset capability contract for animation schema 3."""
from __future__ import annotations

from pathlib import Path

import uatool_animation_mesh_physics as mesh_physics
import uatool_animation_mesh_physics_graph as graph

BOUNDARY = (
    "Authored SkeletalMesh and PhysicsAsset topology: mesh identity, Skeleton/PhysicsAsset/ShadowPhysicsAsset/LODSettings references, "
    "source-model LOD settings, material slots, morph-target and clothing membership/configs, PhysicsAsset preview mesh, ordered bodies, "
    "AggGeom collision primitives, ordered constraints with exact bone-name endpoints, constraint/physical-animation profiles and collision-disable pairs. "
    "Render buffers, runtime skinning, cloth simulation state, Chaos runtime state, generated runtime bodies/constraints and map/runtime inference are excluded."
)


def _read_acceptance(capabilities_module, output: Path) -> dict:
    accepted = capabilities_module._read_json(output / "animation_schema3_acceptance.json")
    verified = capabilities_module._read_json(output / "animation_schema3_graph_verification.json")
    return {
        "accepted": bool(accepted)
        and int(accepted.get("animation_schema_version", 0) or 0) == 3
        and int(accepted.get("mesh_physics_schema_version", 0) or 0) == 1,
        "verification": bool(verified.get("verified", False))
        and int(verified.get("derived_schema_version", 0) or 0) == graph.TARGET_DERIVED_SCHEMA_VERSION,
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
    if getattr(capabilities_module, "_animation_mesh_physics_capabilities_installed", False):
        return
    original_build_manifest = capabilities_module.build_manifest

    def build_manifest(output: Path) -> dict:
        output = Path(output).expanduser().resolve()
        manifest = original_build_manifest(output)
        animation = capabilities_module._read_json(output / "animation_manifest.json")
        animation_files = set(capabilities_module._manifest_files(animation))
        schemas = manifest.get("schemas", {}) if isinstance(manifest.get("schemas"), dict) else {}
        animation_version = int(schemas.get("animation", 0) or 0)
        available = (
            bool(animation)
            and bool(animation.get("success", True))
            and animation_version >= mesh_physics.PUBLIC_ANIMATION_SCHEMA_VERSION
            and int(animation.get("mesh_physics_schema_version", 0) or 0) == mesh_physics.MESH_PHYSICS_SCHEMA_VERSION
            and all(name in animation_files for name in mesh_physics.JSONL_FILES)
        )
        row = {
            "family": "skeletal_mesh_physics_asset",
            "contract_coverage": "first_class",
            "corpus_coverage": "first_class" if available else "external_or_excluded",
            "available_in_corpus": bool(available),
            "canonical_pass": "animation",
            "canonical_streams": sorted(name for name in mesh_physics.JSONL_FILES if name in animation_files),
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
        return manifest

    capabilities_module.build_manifest = build_manifest
    capabilities_module._animation_mesh_physics_capabilities_installed = True
