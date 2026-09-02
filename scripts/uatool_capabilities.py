#!/usr/bin/env python3
"""Machine-readable capability/coverage contract for UnrealAssetTool corpora."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CAPABILITY_SCHEMA_VERSION = 1
CAPABILITIES_FILE = "capabilities.json"
RELEASE_LINE = "0.8.0"
VALIDATED_ENGINE = "UE 5.8.2"

COVERAGE_LEVELS = (
    "first_class",
    "first_class_depth_pending",
    "partial",
    "generic_only",
    "external_or_excluded",
)

# Contract coverage describes what the current tool can understand. Corpus
# coverage is computed separately so focused/partial captures never imply that
# absent passes ran.
_SYSTEM_FAMILIES = (
    {
        "family": "sequencer",
        "coverage": "first_class_depth_pending",
        "min_schema": 1,
        "canonical_streams": (
            "level_sequences.jsonl",
            "movie_scene_bindings.jsonl",
            "movie_scene_tracks.jsonl",
            "movie_scene_sections.jsonl",
            "movie_scene_channels.jsonl",
        ),
        "boundary": "Authored bindings/tracks/sections/channels; individual channel keys and runtime playback are not modeled.",
    },
    {
        "family": "audio",
        "coverage": "first_class_depth_pending",
        "min_schema": 1,
        "canonical_streams": (
            "audio_assets.jsonl",
            "sound_cue_nodes.jsonl",
            "metasound_nodes.jsonl",
            "metasound_edges.jsonl",
        ),
        "boundary": "Authored SoundCue/MetaSound topology and state; no audio rendering or runtime voice state.",
    },
    {
        "family": "enhanced_input",
        "coverage": "first_class",
        "min_schema": 1,
        "canonical_streams": (
            "input_actions.jsonl",
            "input_mapping_contexts.jsonl",
            "input_mappings.jsonl",
            "input_processors.jsonl",
        ),
        "boundary": "Authored actions/mappings/triggers/modifiers; runtime input stacks and user remaps are not captured.",
    },
    {
        "family": "gameplay_data",
        "coverage": "first_class",
        "min_schema": 2,
        "canonical_streams": (
            "gameplay_data_assets.jsonl",
            "data_table_rows.jsonl",
            "data_table_fields.jsonl",
            "curve_tables.jsonl",
            "curve_table_rows.jsonl",
            "curve_table_keys.jsonl",
        ),
        "boundary": "Exact table/curve authored data; arbitrary project-specific row semantics are not guessed.",
    },
    {
        "family": "primary_data_assets",
        "coverage": "first_class_depth_pending",
        "min_schema": 2,
        "canonical_streams": ("primary_data_assets.jsonl",),
        "boundary": "Primary Asset identity is normalized; arbitrary project-specific payload semantics remain reflected/raw.",
    },
    {
        "family": "gameplay_tags",
        "coverage": "first_class",
        "min_schema": 2,
        "canonical_streams": (
            "gameplay_tags.jsonl",
            "gameplay_tag_settings.jsonl",
            "gameplay_tag_sources.jsonl",
            "gameplay_tag_dictionary.jsonl",
            "gameplay_tag_redirects.jsonl",
        ),
        "boundary": "Project tag model and recoverable authored provenance; runtime tag containers are not captured.",
    },
    {
        "family": "mover",
        "coverage": "first_class",
        "min_schema": 3,
        "canonical_streams": (
            "mover_blueprints.jsonl",
            "mover_components.jsonl",
            "mover_modes.jsonl",
            "mover_settings.jsonl",
            "mover_transitions.jsonl",
        ),
        "boundary": "Authored Mover composition and transitions; movement simulation/layered-move execution is not run.",
    },
    {
        "family": "gameplay_cameras",
        "coverage": "first_class",
        "min_schema": 4,
        "canonical_streams": (
            "gameplay_camera_assets.jsonl",
            "gameplay_camera_rigs.jsonl",
            "gameplay_camera_nodes.jsonl",
            "gameplay_camera_node_edges.jsonl",
            "gameplay_camera_transitions.jsonl",
            "gameplay_camera_directors.jsonl",
            "gameplay_camera_rig_references.jsonl",
        ),
        "boundary": "Authored camera rigs/directors/transitions/selection facts; runtime evaluation and blending are not executed.",
    },
    {
        "family": "mass_zonegraph",
        "coverage": "first_class",
        "min_schema": 5,
        "canonical_streams": (
            "mass_entity_configs.jsonl",
            "mass_entity_traits.jsonl",
            "mass_spawners.jsonl",
            "mass_spawner_entity_types.jsonl",
            "mass_spawner_generators.jsonl",
            "mass_spawn_generator_assets.jsonl",
            "mass_agent_components.jsonl",
            "zonegraph_shapes.jsonl",
            "zonegraph_shape_points.jsonl",
        ),
        "boundary": "Authored Mass configuration and placed ZoneShape topology; generated ZoneGraph lane storage and runtime ECS state are not claimed.",
    },
    {
        "family": "gas",
        "coverage": "first_class",
        "min_schema": 6,
        "canonical_streams": (
            "gas_abilities.jsonl",
            "gas_ability_triggers.jsonl",
            "gas_ability_costs.jsonl",
            "gas_ability_sets.jsonl",
            "gas_ability_set_abilities.jsonl",
            "gas_ability_set_effects.jsonl",
            "gas_ability_set_attributes.jsonl",
            "gas_gameplay_effects.jsonl",
            "gas_gameplay_effect_components.jsonl",
            "gas_gameplay_effect_modifiers.jsonl",
            "gas_gameplay_effect_executions.jsonl",
            "gas_gameplay_effect_execution_modifiers.jsonl",
            "gas_gameplay_effect_cues.jsonl",
            "gas_gameplay_cues.jsonl",
            "gas_attribute_sets.jsonl",
            "gas_attributes.jsonl",
        ),
        "boundary": "Authored GAS definitions/defaults/relationships only; active specs, prediction, replication and live ASC/attribute state are not captured.",
    },
)

_GENERIC_GAPS = (
    ("smart_objects", "Dedicated schema 7 extraction and derived schema 23 semantics are implemented and raw-accepted on City Sample; maintained first-class capability promotion is pending final derived graph verification."),
    ("ai_perception", "Sense configs, dominant sense and stimuli-source relationships do not yet have a dedicated extractor."),
    ("authored_navigation", "Nav areas/links/agent/project settings do not yet have a dedicated authored-navigation model."),
    ("dataflow_chaos", "Dataflow/Geometry Collection/Chaos authoring graphs do not yet have a dedicated semantic model."),
    ("animnext", "AnimNext does not yet have a representative accepted UE 5.8 corpus or dedicated semantic model."),
)

MASS_ZONEGRAPH_RELATIONS = (
    "inherits_mass_entity_config",
    "has_mass_entity_trait",
    "spawns_mass_entity_config",
    "uses_mass_spawn_generator_asset",
    "uses_mass_spawn_generator_instance",
    "inherits_mass_spawn_generator_class",
    "inherits_zonegraph_spawn_generator_base",
    "owns_mass_agent_component",
    "uses_mass_entity_config",
    "contains_zonegraph_shape",
    "owns_zonegraph_shape_component",
    "has_zonegraph_shape_point",
)


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _manifest_files(manifest: dict) -> list[str]:
    files = manifest.get("files", [])
    if not isinstance(files, list):
        return []
    return sorted({str(value) for value in files if str(value).endswith(".jsonl")})


def _present(files: set[str], names) -> list[str]:
    return [name for name in names if name in files]


def _prefix_streams(files: set[str], prefix: str) -> list[str]:
    return sorted(name for name in files if name.startswith(prefix) and name.endswith(".jsonl"))


def _acceptance(output: Path, family: str) -> dict:
    if family == "mass_zonegraph":
        accepted = _read_json(output / "systems_schema5_acceptance.json")
        verified = _read_json(output / "mass_zonegraph_graph_verification.json")
    elif family == "gas":
        accepted = _read_json(output / "systems_schema6_acceptance.json")
        verified = _read_json(output / "gas_graph_verification.json")
    else:
        return {"accepted": False, "verification": False, "corpus_provenance": ""}
    project = str(accepted.get("project", "") or "")
    return {
        "accepted": bool(accepted),
        "verification": bool(verified.get("verified", False)),
        "corpus_provenance": Path(project).name if project else "",
    }


def _gas_relations() -> list[str]:
    try:
        import uatool_gas_graph as gas_graph
        return sorted(str(value) for value in gas_graph.RELATION_STREAMS)
    except Exception:
        return []


def build_manifest(output: Path) -> dict:
    output = Path(output).expanduser().resolve()
    top = _read_json(output / "manifest.json")
    world = _read_json(output / "world_manifest.json")
    animation = _read_json(output / "animation_manifest.json")
    vfx = _read_json(output / "vfx_manifest.json")
    systems = _read_json(output / "systems_manifest.json")

    top_files = set(_manifest_files(top))
    world_files = set(_manifest_files(world))
    animation_files = set(_manifest_files(animation))
    vfx_files = set(_manifest_files(vfx))
    systems_files = set(_manifest_files(systems))

    schemas = {
        "structural": int(top.get("schema_version", 0) or 0),
        "world": int(world.get("schema_version", 0) or 0),
        "animation": int(animation.get("schema_version", 0) or 0),
        "vfx": int(vfx.get("schema_version", 0) or 0),
        "systems": int(systems.get("schema_version", top.get("systems_schema_version", 0)) or 0),
        "derived": int(top.get("derived_schema_version", 0) or 0),
    }

    canonical_passes = top.get("canonical_passes")
    if not isinstance(canonical_passes, list):
        canonical_passes = []
        if top and schemas["structural"] > 0:
            canonical_passes.append("structural")
        if world:
            canonical_passes.append("world")
        if animation:
            canonical_passes.append("animation")
        if vfx:
            canonical_passes.append("vfx")
        if systems:
            canonical_passes.append("systems")

    families: list[dict] = []

    def add(
        family: str,
        contract_coverage: str,
        pass_name: str,
        available: bool,
        canonical_streams,
        boundary: str,
        *,
        derived_streams=(),
        derived_relations=(),
        acceptance=None,
    ) -> None:
        families.append({
            "family": family,
            "contract_coverage": contract_coverage,
            "corpus_coverage": contract_coverage if available else "external_or_excluded",
            "available_in_corpus": bool(available),
            "canonical_pass": pass_name,
            "canonical_streams": sorted(str(value) for value in canonical_streams),
            "derived_streams": sorted(str(value) for value in derived_streams),
            "derived_relations": sorted(str(value) for value in derived_relations),
            "runtime_state_captured": False,
            "boundary": boundary,
            "acceptance": acceptance or {
                "accepted": False,
                "verification": False,
                "corpus_provenance": "",
            },
        })

    structural_available = bool(top) and schemas["structural"] > 0
    add(
        "files_source_config", "first_class", "structural", structural_available,
        _present(top_files, ("files.jsonl", "source_chunks.jsonl")),
        "Physical files and bounded source/config text; not a C++ compiler or semantic source index.",
    )
    add(
        "asset_registry", "first_class", "structural", structural_available,
        _present(top_files, ("assets.jsonl", "asset_dependencies.jsonl")),
        "Asset identity/class/package/tags/dependencies; package dependencies are not semantic object references.",
    )
    add(
        "blueprint", "first_class", "structural", structural_available,
        _prefix_streams(top_files, "blueprint_") + _prefix_streams(top_files, "rigvm_"),
        "Authored Blueprint/K2/UMG/RigVM structure; runtime Blueprint VM execution is not simulated.",
    )
    ai_streams = []
    for prefix in ("behavior_", "blackboard", "eqs_", "statetree"):
        ai_streams.extend(_prefix_streams(top_files, prefix))
    add(
        "ai_authored", "first_class", "structural", structural_available,
        sorted(set(ai_streams)),
        "Behavior Tree/Blackboard/EQS/StateTree authored structure; runtime execution, perception history and query results are excluded.",
    )
    add(
        "pcg", "first_class", "structural", structural_available,
        _prefix_streams(top_files, "pcg_"),
        "Authored PCG graph topology/state; generated runtime/spatial output is not evaluated.",
    )
    add(
        "materials", "first_class", "structural", structural_available,
        _prefix_streams(top_files, "material"),
        "Authored material graph/state/references; shader compilation and runtime resources are excluded.",
    )
    add(
        "world", "first_class", "world", bool(world) and schemas["world"] > 0,
        world_files,
        "Authored worlds, actors, components, placement, overrides, Data Layers and World Partition descriptors; dynamic runtime state is excluded.",
    )
    add(
        "animation", "first_class", "animation", bool(animation) and schemas["animation"] > 0,
        animation_files,
        "Authored animation topology/data; runtime animation evaluation is not executed.",
    )
    add(
        "vfx", "first_class", "vfx", bool(vfx) and schemas["vfx"] > 0,
        vfx_files,
        "Authored Niagara/Niagara Stateless/Cascade topology; particle simulation is not executed; some Niagara stack semantics remain depth-pending.",
    )

    systems_available = bool(systems) and bool(systems.get("success", True))
    for contract in _SYSTEM_FAMILIES:
        available = systems_available and schemas["systems"] >= int(contract["min_schema"])
        relations = ()
        if contract["family"] == "mass_zonegraph":
            relations = MASS_ZONEGRAPH_RELATIONS
        elif contract["family"] == "gas":
            relations = _gas_relations()
        add(
            contract["family"],
            contract["coverage"],
            "systems",
            available,
            _present(systems_files, contract["canonical_streams"]),
            contract["boundary"],
            derived_streams=(
                ("mover_transition_behaviors.jsonl", "mover_transition_routes.jsonl")
                if contract["family"] == "mover" else ()
            ),
            derived_relations=relations,
            acceptance=_acceptance(output, contract["family"]),
        )

    graph_streams = [
        name for name in ("project_nodes.jsonl", "project_edges.jsonl", "project_neighborhoods.jsonl")
        if (output / name).is_file()
    ]
    add(
        "project_graph", "first_class", "derived", schemas["derived"] > 0 and bool(graph_streams),
        [],
        "Deterministic typed graph over extractor facts with provenance and edge quality; it never upgrades unsupported semantics by inference.",
        derived_streams=graph_streams,
    )

    for family, boundary in _GENERIC_GAPS:
        add(family, "generic_only", "structural", structural_available, [], boundary)

    return {
        "capability_schema_version": CAPABILITY_SCHEMA_VERSION,
        "tool": {
            "release_line": RELEASE_LINE,
            "validated_engine": VALIDATED_ENGINE,
        },
        "coverage_levels": list(COVERAGE_LEVELS),
        "corpus": {
            "partial": bool(top.get("partial_corpus", False)),
            "canonical_passes": sorted({str(value) for value in canonical_passes}),
        },
        "schemas": schemas,
        "families": families,
    }


def write_manifest(output: Path) -> Path:
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    path = output / CAPABILITIES_FILE
    text = json.dumps(build_manifest(output), ensure_ascii=False, indent=2) + "\n"
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8", newline="\n")
    return path


def validation_error(output: Path) -> str | None:
    manifest = _read_json(Path(output) / CAPABILITIES_FILE)
    if not manifest:
        return f"{CAPABILITIES_FILE} missing or invalid"
    if int(manifest.get("capability_schema_version", 0) or 0) != CAPABILITY_SCHEMA_VERSION:
        return f"expected capability schema {CAPABILITY_SCHEMA_VERSION}"
    if tuple(manifest.get("coverage_levels", [])) != COVERAGE_LEVELS:
        return "coverage level vocabulary mismatch"
    if not isinstance(manifest.get("schemas"), dict):
        return "schemas missing or invalid"
    families = manifest.get("families", [])
    if not isinstance(families, list) or not families:
        return "families missing or invalid"
    names = [str(row.get("family", "")) for row in families if isinstance(row, dict)]
    if len(names) != len(families) or len(names) != len(set(names)) or any(not name for name in names):
        return "family names are blank or duplicated"
    for row in families:
        if row.get("contract_coverage") not in COVERAGE_LEVELS:
            return f"invalid contract coverage for {row.get('family', '')}"
        if row.get("corpus_coverage") not in COVERAGE_LEVELS:
            return f"invalid corpus coverage for {row.get('family', '')}"
        if row.get("runtime_state_captured") is not False:
            return f"runtime capture claim is unsupported for {row.get('family', '')}"
    return None


def _canonical_module(modules=None):
    target = Path(__file__).with_name("uatool.py").resolve()
    values = tuple(modules if modules is not None else sys.modules.values())
    for module in values:
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            if Path(module_file).resolve() != target:
                continue
        except (OSError, RuntimeError, TypeError):
            continue
        if hasattr(module, "derive_output"):
            return module
    return None


def apply_public_policy(*, modules=None, core_module=None) -> bool:
    public = _canonical_module(modules)
    if public is None:
        return False
    if bool(getattr(public, "_capabilities_policy_installed", False)):
        return True
    if core_module is None:
        import uatool_core as core_module

    original = public.derive_output

    def derive_output(output):
        result = original(output)
        path = write_manifest(Path(output))
        error = validation_error(path.parent)
        if error:
            raise RuntimeError(f"capability manifest incomplete: {error}")
        return result

    public.derive_output = derive_output
    if getattr(core_module, "derive_output", None) is original:
        core_module.derive_output = derive_output
    core_module.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((
        *core_module.DEFAULT_BUNDLE_FILES,
        CAPABILITIES_FILE,
    )))
    public._capabilities_policy_installed = True
    return True


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool capabilities",
        description="emit and print the machine-readable capability contract for an existing corpus",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("--check", action="store_true", help="validate the generated capability contract")
    args = parser.parse_args(argv)
    path = write_manifest(Path(args.output))
    if args.check:
        error = validation_error(path.parent)
        if error:
            raise RuntimeError(error)
    print(path.read_text(encoding="utf-8"), end="")
    return 0


def install(runtime_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if bool(getattr(runtime_module, "_capabilities_deferred_installed", False)):
        return

    original_main = runtime_module.main

    def main():
        apply_public_policy()
        if len(sys.argv) > 1 and sys.argv[1] == "capabilities":
            try:
                return _cli(sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 45
        return original_main()

    runtime_module.main = main
    runtime_module._capabilities_deferred_installed = True
