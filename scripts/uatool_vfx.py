#!/usr/bin/env python3
"""Canonical VFX schema 1 support facade for UnrealAssetTool."""
from pathlib import Path

from uatool_vfx_defs import VFX_SCHEMA_VERSION, RAW_FILES, create_schema, read_manifest
from uatool_vfx_validate import validation_error
from uatool_vfx_storage import load_database, query
import uatool_runtime as _runtime
import uatool_core as _core
import uatool_systems_only_derive_deferred as _systems_only_derive_deferred
import uatool_capabilities as _capabilities
import uatool_smartobject_capabilities as _smartobject_capabilities
import uatool_ai_perception_capabilities as _ai_perception_capabilities
import uatool_dataflow_chaos_capabilities as _dataflow_chaos_capabilities
import uatool_uaf_capabilities as _uaf_capabilities
import uatool_navigation_capabilities as _navigation_capabilities
import uatool_inspect as _inspect
import uatool_project_intelligence as _project_intelligence
import uatool_smartobject_evidence as _smartobject_evidence
import uatool_smartobject_capture as _smartobject_capture
import uatool_ai_perception_evidence as _ai_perception_evidence
import uatool_ai_perception_capture as _ai_perception_capture
import uatool_dataflow_chaos_evidence as _dataflow_chaos_evidence
import uatool_dataflow_chaos_capture as _dataflow_chaos_capture
import uatool_navigation_evidence as _navigation_evidence
import uatool_gameplay_framework_evidence as _gameplay_framework_evidence
import uatool_navigation_capture as _navigation_capture
import uatool_animnext_evidence as _animnext_evidence
import uatool_animnext_engine_evidence as _animnext_engine_evidence
import uatool_animnext_capture as _animnext_capture
import uatool_uaf_systems_capture as _uaf_systems_capture

# Specialist systems schemas are composed after the existing Mass -> GAS
# installers. uatool.py imports this facade before build_perf.install(), so
# extend that one canonical composition point monotonically through schema 11.
import uatool_build_perf as _build_perf
import uatool_systems as _systems
import uatool_systems_smartobjects as _systems_smartobjects
import uatool_systems_ai_perception as _systems_ai_perception
import uatool_systems_dataflow_chaos as _systems_dataflow_chaos
import uatool_systems_uaf as _systems_uaf
import uatool_systems_navigation as _systems_navigation
import uatool_project_graph as _project_graph
import uatool_smartobject_graph as _smartobject_graph
import uatool_ai_perception_graph as _ai_perception_graph
import uatool_dataflow_chaos_graph as _dataflow_chaos_graph
import uatool_uaf_graph as _uaf_graph
import uatool_navigation_graph as _navigation_graph
import uatool_systems_schema7_accept as _systems_schema7_accept
import uatool_systems_schema8_accept as _systems_schema8_accept
import uatool_systems_schema9_accept as _systems_schema9_accept
import uatool_systems_schema10_accept as _systems_schema10_accept
import uatool_systems_schema11_accept as _systems_schema11_accept


def _install_specialist_capture_membership() -> None:
    import uatool_systems_capture as capture
    if not getattr(capture, "_schema7plus_specialist_config_installed", False):
        original_configure = capture.configure_for_systems

        def configure_for_systems(systems_module) -> None:
            original_configure(systems_module)
            schema = int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0)
            extra_files = []
            if schema >= 7:
                extra_files.extend(name for name in getattr(systems_module, "JSONL_FILES", ()) if name.startswith("smartobject_") and name.endswith(".jsonl"))
            if schema >= 8:
                extra_files.extend(name for name in getattr(systems_module, "JSONL_FILES", ()) if name.startswith("ai_perception_") and name.endswith(".jsonl"))
            if schema >= 9:
                extra_files.extend(name for name in getattr(systems_module, "JSONL_FILES", ()) if (name.startswith("dataflow_") or name.startswith("geometry_collection")) and name.endswith(".jsonl"))
            if schema >= 10:
                extra_files.extend(name for name in getattr(systems_module, "JSONL_FILES", ()) if name.startswith("uaf_") and name.endswith(".jsonl"))
            if schema >= 11:
                extra_files.extend(name for name in getattr(systems_module, "JSONL_FILES", ()) if name.startswith("navigation_") and name.endswith(".jsonl"))
            capture.CAPTURE_FILES = tuple(dict.fromkeys((*capture.CAPTURE_FILES, *extra_files)))
            capture.SCHEMA_FILES = capture.CAPTURE_FILES[len(capture._BASE_CAPTURE_FILES):]

        capture.configure_for_systems = configure_for_systems
        capture._schema7plus_specialist_config_installed = True

    if not getattr(capture, "_schema7plus_raw_archive_guard_installed", False):
        original_capture_cli = capture._capture_cli

        def capture_cli(runtime_module, core_module, systems_module, argv):
            try:
                return original_capture_cli(runtime_module, core_module, systems_module, argv)
            except Exception:
                try:
                    project = Path(argv[0]).expanduser().resolve()
                    output_value = None
                    archive_value = None
                    for index, value in enumerate(argv):
                        if value == "--output" and index + 1 < len(argv): output_value = argv[index + 1]
                        elif value == "--archive" and index + 1 < len(argv): archive_value = argv[index + 1]
                    output = Path(output_value).expanduser().resolve() if output_value else project.parent / ".uatool" / f"systems-schema{capture.CAPTURE_SCHEMA_VERSION}-capture"
                    archive = Path(archive_value).expanduser().resolve() if archive_value else project.parent / ".uatool" / f"{project.stem}.systems-schema{capture.CAPTURE_SCHEMA_VERSION}-capture.zip"
                    if all((output / filename).is_file() for filename in capture.CAPTURE_FILES):
                        capture._write_capture_archive(output, archive)
                        print(f"raw systems capture archive preserved after failure: {archive}")
                except Exception as archive_exc:
                    print(f"note: could not preserve raw systems capture archive: {archive_exc}")
                raise

        capture._capture_cli = capture_cli
        capture._schema7plus_raw_archive_guard_installed = True

    capture.configure_for_systems(_systems)


if not getattr(_build_perf, "_systems_schema11_composition_installed", False):
    _original_build_perf_install = _build_perf.install

    def _build_perf_install_with_schema11(core) -> None:
        _original_build_perf_install(core)
        _systems_smartobjects.install(_systems)
        _systems_ai_perception.install(_systems)
        _systems_dataflow_chaos.install(_systems)
        _systems_uaf.install(_systems)
        _systems_navigation.install(_systems)
        _smartobject_graph.install(_project_graph)
        _ai_perception_graph.install(_project_graph)
        _dataflow_chaos_graph.install(_project_graph)
        _uaf_graph.install(_project_graph)
        _navigation_graph.install(_project_graph)
        _systems_schema7_accept.install(_runtime, _systems)
        _systems_schema8_accept.install(_runtime, _systems)
        _systems_schema9_accept.install(_runtime, _systems)
        _systems_schema10_accept.install(_runtime, _systems)
        _systems_schema11_accept.install(_runtime, _systems)
        _install_specialist_capture_membership()

    _build_perf.install = _build_perf_install_with_schema11
    _build_perf._systems_schema11_composition_installed = True

_smartobject_capabilities.install(_capabilities)
_ai_perception_capabilities.install(_capabilities)
_dataflow_chaos_capabilities.install(_capabilities)
_uaf_capabilities.install(_capabilities)
_navigation_capabilities.install(_capabilities)
_systems_only_derive_deferred.install()
_capabilities.install()
_inspect.install()
_project_intelligence.install()
_smartobject_evidence.install(_runtime)
_smartobject_capture.install(_runtime)
_ai_perception_evidence.install(_runtime)
_ai_perception_capture.install(_runtime)
_dataflow_chaos_evidence.install(_runtime)
_dataflow_chaos_capture.install(_runtime)
_navigation_evidence.install(_runtime)
_gameplay_framework_evidence.install(_runtime)
_navigation_capture.install(_runtime, _core)
_animnext_evidence.install(_runtime)
_animnext_engine_evidence.install(_runtime)
_animnext_capture.install(_runtime)
_uaf_systems_capture.install(_runtime, _core, _systems)

__all__ = (
    "VFX_SCHEMA_VERSION", "RAW_FILES", "create_schema", "read_manifest",
    "validation_error", "load_database", "query",
)
