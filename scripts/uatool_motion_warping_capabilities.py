#!/usr/bin/env python3
"""First-class Motion Warping capability contract for animation schema 4."""
from __future__ import annotations

from pathlib import Path

import uatool_motion_warping_schema as schema
import uatool_motion_warping_graph as graph

BOUNDARY = (
    "Authored Motion Warping only: exact AnimNotifyState_MotionWarping windows, instanced notify-owned "
    "RootMotionModifier templates, common warp target/translation/rotation policy, and exact editable "
    "modifier-class properties. Live UMotionWarpingComponent warp targets, active runtime modifiers, "
    "root-motion evaluation, runtime transforms and map/runtime state are excluded."
)


def _read_acceptance(capabilities_module, output: Path) -> dict:
    accepted = capabilities_module._read_json(output / "animation_schema4_motion_warping_acceptance.json")
    verified = capabilities_module._read_json(output / "animation_schema4_motion_warping_graph_verification.json")
    return {
        "accepted": bool(accepted)
        and int(accepted.get("animation_schema_version", 0) or 0) == schema.PUBLIC_ANIMATION_SCHEMA_VERSION
        and int(accepted.get("motion_warping_schema_version", 0) or 0) == schema.MOTION_WARPING_SCHEMA_VERSION,
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
    if getattr(capabilities_module, "_motion_warping_schema4_capabilities_installed", False):
        return
    original_build_manifest = capabilities_module.build_manifest

    def build_manifest(output: Path) -> dict:
        output = Path(output).expanduser().resolve()
        manifest = original_build_manifest(output)
        sidecar = capabilities_module._read_json(output / schema.MANIFEST_FILE)
        files = set(capabilities_module._manifest_files(sidecar))
        available = (
            bool(sidecar)
            and bool(sidecar.get("success", True))
            and int(sidecar.get("schema_version", 0) or 0) == schema.MOTION_WARPING_SCHEMA_VERSION
            and int(sidecar.get("public_animation_schema_version", 0) or 0) == schema.PUBLIC_ANIMATION_SCHEMA_VERSION
            and all(name in files for name in schema.JSONL_FILES)
        )

        schemas = manifest.get("schemas", {}) if isinstance(manifest.get("schemas"), dict) else {}
        schemas["motion_warping"] = int(sidecar.get("schema_version", 0) or 0) if sidecar else 0
        manifest["schemas"] = schemas

        row = {
            "family": "motion_warping",
            "contract_coverage": "first_class",
            "corpus_coverage": "first_class" if available else "external_or_excluded",
            "available_in_corpus": bool(available),
            "canonical_pass": "animation",
            "canonical_streams": sorted(name for name in schema.JSONL_FILES if name in files),
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
    capabilities_module._motion_warping_schema4_capabilities_installed = True
