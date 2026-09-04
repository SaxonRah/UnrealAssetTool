#!/usr/bin/env python3
"""1.0 beta multi-corpus release-candidate checker."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import uatool_capabilities as capabilities
import uatool_version as version

RECORD_SCHEMA_VERSION = 1

# These canonical companion passes are content-dependent. Their version in
# CURRENT_SCHEMAS describes the current tool contract, while an individual
# corpus legitimately reports schema 0 when no authored candidates exist.
OPTIONAL_COMPANION_SCHEMAS = {
    "mesh": "static_mesh",
    "world_geometry": "world_geometry",
}

# Some public schemas are additive content-dependent extensions over a valid
# lower full-corpus baseline. Animation schema 4 adds authored Motion Warping
# to the current schema-3 animation contract; projects without any authored
# Motion Warping windows intentionally remain animation schema 3.
CONTENT_DEPENDENT_SCHEMA_FALLBACKS = {
    "animation": {
        "family": "motion_warping",
        "fallback_schema": 3,
    },
}

PROFILE_ALIASES = {
    "gasp": "gasp",
    "gameanimationsample": "gasp",
    "game-animation-sample": "gasp",
    "contentexamples": "contentexamples",
    "content-examples": "contentexamples",
    "citysample": "citysample",
    "city-sample": "citysample",
    "lyra": "lyra",
    "cropout": "cropout",
    "stackobot": "stackobot",
}

PROFILE_SPECS = {
    "gasp": {
        "label": "Game Animation Sample (GASP)",
        "required_families": ("blueprint", "animation", "mover", "project_graph"),
        "streams": {
            "blueprint_nodes.jsonl": ("exact", 18329),
            "blueprint_semantic_nodes.jsonl": ("exact", 18329),
            "blueprint_interprocedural_data_routes.jsonl": ("exact", 47),
            "blueprint_interprocedural_function_execution_edges.jsonl": ("exact", 668),
            "blueprint_interprocedural_function_data_routes.jsonl": ("exact", 872),
            "blueprint_delegate_bindings.jsonl": ("exact", 24),
            "blueprint_call_bindings.jsonl": ("exact", 908),
            "rigvm_editor_links.jsonl": ("exact", 6646),
            "mover_transition_behaviors.jsonl": ("exact", 2),
            "mover_transition_routes.jsonl": ("exact", 2),
            "motion_warping_windows.jsonl": ("exact", 145),
            "pose_search_databases.jsonl": ("min", 1),
        },
    },
    "contentexamples": {
        "label": "Content Examples",
        "required_families": (
            "sequencer",
            "audio",
            "materials",
            "vfx",
            "gameplay_data",
            "gameplay_tags",
            "project_graph",
        ),
        "streams": {
            "level_sequences.jsonl": ("min", 1),
            "audio_assets.jsonl": ("min", 1),
            "material_expressions.jsonl": ("min", 1),
            "vfx_assets.jsonl": ("min", 1),
            "data_table_rows.jsonl": ("min", 1),
            "gameplay_tag_settings.jsonl": ("exact", 1),
            "project_edges.jsonl": ("min", 1),
        },
    },
    "citysample": {
        "label": "City Sample",
        "required_families": (
            "mass_zonegraph",
            "smart_objects",
            "world",
            "project_graph",
        ),
        "streams": {
            "mass_entity_configs.jsonl": ("min", 1),
            "zonegraph_shapes.jsonl": ("min", 1),
            "smartobject_definitions.jsonl": ("min", 1),
            "world_actors.jsonl": ("min", 1),
            "project_edges.jsonl": ("min", 1),
        },
    },
    "lyra": {
        "label": "Lyra Starter Game",
        "required_families": ("gas", "gameplay_framework", "project_graph"),
        "streams": {
            "gas_abilities.jsonl": ("min", 1),
            "gas_gameplay_effects.jsonl": ("min", 1),
            "blueprints.jsonl": ("min", 1),
            "worlds.jsonl": ("min", 1),
            "project_edges.jsonl": ("min", 1),
        },
    },
    "cropout": {
        "label": "Cropout",
        "required_families": ("blueprint", "world", "project_graph"),
        "streams": {
            "blueprint_nodes.jsonl": ("min", 1),
            "blueprint_semantic_nodes.jsonl": ("min", 1),
            "world_actors.jsonl": ("min", 1),
            "project_edges.jsonl": ("min", 1),
        },
    },
    "stackobot": {
        "label": "StackOBot",
        "required_families": ("pcg", "world", "project_graph"),
        "streams": {
            "pcg_graphs.jsonl": ("min", 1),
            "pcg_nodes.jsonl": ("min", 1),
            "world_actors.jsonl": ("min", 1),
            "project_edges.jsonl": ("min", 1),
        },
    },
}


def normalize_profile(value: str) -> str:
    key = str(value or "").strip().lower().replace("_", "-")
    compact = key.replace("-", "")
    profile = PROFILE_ALIASES.get(key) or PROFILE_ALIASES.get(compact)
    if not profile:
        raise ValueError(
            f"unknown beta RC profile {value!r}; expected one of "
            + ", ".join(sorted(PROFILE_SPECS))
        )
    return profile


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def _git_commit(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("could not resolve git HEAD for beta RC record")
    value = result.stdout.strip()
    if len(value) != 40:
        raise RuntimeError(f"unexpected git HEAD: {value!r}")
    return value


def _family_map(manifest: dict) -> dict[str, dict]:
    families = manifest.get("families", [])
    if not isinstance(families, list):
        return {}
    return {
        str(row.get("family", "") or ""): row
        for row in families
        if isinstance(row, dict) and row.get("family")
    }


def check_corpus(
    output: Path,
    profile: str,
    *,
    repo_root: Path,
) -> dict:
    output = Path(output).expanduser().resolve()
    profile = normalize_profile(profile)
    spec = PROFILE_SPECS[profile]

    if not output.is_dir():
        raise FileNotFoundError(f"not a .uatool corpus directory: {output}")

    capability_error = capabilities.validation_error(output)
    if capability_error:
        raise RuntimeError(f"capability contract invalid: {capability_error}")

    capability = _read_json(output / capabilities.CAPABILITIES_FILE)
    top = _read_json(output / "manifest.json")
    if not top:
        raise RuntimeError("manifest.json missing or invalid")

    checks: list[dict] = []
    failures: list[str] = []

    def add_check(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})
        if not ok:
            failures.append(f"{name}: {detail}")

    tool = capability.get("tool", {}) if isinstance(capability.get("tool"), dict) else {}
    add_check(
        "release_version",
        str(tool.get("version", "") or "") == version.RELEASE_VERSION,
        f"observed={tool.get('version')!r} expected={version.RELEASE_VERSION!r}",
    )
    add_check(
        "validated_engine",
        str(tool.get("validated_engine", "") or "") == version.VALIDATED_ENGINE,
        f"observed={tool.get('validated_engine')!r} expected={version.VALIDATED_ENGINE!r}",
    )

    schemas = capability.get("schemas", {}) if isinstance(capability.get("schemas"), dict) else {}
    observed_schemas = dict(schemas)
    observed_schemas["capabilities"] = int(
        capability.get("capability_schema_version", 0) or 0
    )
    families = _family_map(capability)
    for name, expected in version.CURRENT_SCHEMAS.items():
        observed = int(observed_schemas.get(name, 0) or 0)
        fallback = CONTENT_DEPENDENT_SCHEMA_FALLBACKS.get(name)
        companion_family = OPTIONAL_COMPANION_SCHEMAS.get(name)
        if fallback:
            family = str(fallback["family"])
            fallback_schema = int(fallback["fallback_schema"])
            row = families.get(family, {})
            available = bool(row.get("available_in_corpus", False))
            coverage = str(row.get("corpus_coverage", "") or "")
            explicitly_absent = (
                bool(row)
                and not available
                and coverage == "external_or_excluded"
            )
            if available:
                ok = observed == expected
            else:
                ok = observed == fallback_schema and explicitly_absent
            detail = (
                f"observed={observed} expected={expected} "
                f"fallback={fallback_schema} family={family} "
                f"available={available} corpus_coverage={coverage or '<missing>'}"
            )
        elif companion_family:
            row = families.get(companion_family, {})
            available = bool(row.get("available_in_corpus", False))
            coverage = str(row.get("corpus_coverage", "") or "")
            explicitly_absent = (
                bool(row)
                and not available
                and coverage == "external_or_excluded"
            )
            ok = observed == expected if available else observed == 0 and explicitly_absent
            detail = (
                f"observed={observed} expected={expected} "
                f"family={companion_family} available={available} "
                f"corpus_coverage={coverage or '<missing>'}"
            )
        else:
            ok = observed == expected
            detail = f"observed={observed} expected={expected}"
        add_check(f"schema:{name}", ok, detail)

    family_result = {}
    for name in spec["required_families"]:
        row = families.get(name, {})
        available = bool(row.get("available_in_corpus", False))
        coverage = str(row.get("corpus_coverage", "") or "")
        ok = available and coverage not in {"external_or_excluded", "generic_only", ""}
        add_check(
            f"family:{name}",
            ok,
            f"available={available} corpus_coverage={coverage or '<missing>'}",
        )
        family_result[name] = {
            "available": available,
            "contract_coverage": str(row.get("contract_coverage", "") or ""),
            "corpus_coverage": coverage,
        }

    metrics = {}
    for filename, rule in spec["streams"].items():
        mode, expected = rule
        count = _line_count(output / filename)
        metrics[filename.removesuffix(".jsonl")] = count
        if mode == "exact":
            ok = count == expected
            detail = f"rows={count} expected_exact={expected}"
        else:
            ok = count >= expected
            detail = f"rows={count} expected_min={expected}"
        add_check(f"stream:{filename}", ok, detail)

    project_name = output.parent.name
    record = {
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "release_version": version.RELEASE_VERSION,
        "git_commit": _git_commit(repo_root),
        "profile": profile,
        "profile_label": spec["label"],
        "project_name": project_name,
        "schemas": {
            name: int(observed_schemas.get(name, 0) or 0)
            for name in version.CURRENT_SCHEMAS
        },
        "families": family_result,
        "metrics": metrics,
        "checks": checks,
        "accepted": not failures,
        "failures": failures,
    }
    return record


def print_record(record: dict) -> None:
    print(
        f"beta RC {record['profile']}: "
        f"accepted={record['accepted']} "
        f"release={record['release_version']} "
        f"commit={record['git_commit'][:12]}"
    )
    print(
        "schemas: "
        + " ".join(
            f"{name}={value}" for name, value in record.get("schemas", {}).items()
        )
    )
    print("[families]")
    for name, row in record.get("families", {}).items():
        print(
            f"  {name}: available={row.get('available')} "
            f"coverage={row.get('corpus_coverage')}"
        )
    print("[metrics]")
    for name, count in record.get("metrics", {}).items():
        print(f"  {name}: {count}")
    if record.get("failures"):
        print("[failures]")
        for failure in record["failures"]:
            print(f"  {failure}")
    else:
        print("failures: <none>")
