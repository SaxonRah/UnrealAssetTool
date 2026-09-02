#!/usr/bin/env python3
"""Canonical VFX schema 1 support facade for UnrealAssetTool."""
from pathlib import Path

from uatool_vfx_defs import VFX_SCHEMA_VERSION, RAW_FILES, create_schema, read_manifest
from uatool_vfx_validate import validation_error
from uatool_vfx_storage import load_database, query
import uatool_runtime as _runtime
import uatool_systems_only_derive_deferred as _systems_only_derive_deferred
import uatool_capabilities as _capabilities
import uatool_smartobject_capabilities as _smartobject_capabilities
import uatool_ai_perception_capabilities as _ai_perception_capabilities
import uatool_inspect as _inspect
import uatool_project_intelligence as _project_intelligence
import uatool_smartobject_evidence as _smartobject_evidence
import uatool_smartobject_capture as _smartobject_capture
import uatool_ai_perception_evidence as _ai_perception_evidence
import uatool_ai_perception_capture as _ai_perception_capture
import uatool_dataflow_chaos_evidence as _dataflow_chaos_evidence
import uatool_dataflow_chaos_capture as _dataflow_chaos_capture

# Smart Objects schema 7, AI Perception schema 8 and Dataflow/Geometry
# Collection schema 9 are composed after the existing Mass -> GAS systems
# installers. uatool.py imports this facade before it calls build_perf.install(),
# so extend that one canonical composition point.
import uatool_build_perf as _build_perf
import uatool_systems as _systems
import uatool_systems_smartobjects as _systems_smartobjects
import uatool_systems_ai_perception as _systems_ai_perception
import uatool_systems_dataflow_chaos as _systems_dataflow_chaos
import uatool_project_graph as _project_graph
import uatool_smartobject_graph as _smartobject_graph
import uatool_ai_perception_graph as _ai_perception_graph
import uatool_dataflow_chaos_graph as _dataflow_chaos_graph
import uatool_systems_schema7_accept as _systems_schema7_accept
import uatool_systems_schema8_accept as _systems_schema8_accept
import uatool_systems_schema9_accept as _systems_schema9_accept


def _install_specialist_capture_membership() -> None:
    import uatool_systems_capture as capture
    if not getattr(capture, "_schema7plus_specialist_config_installed", False):
        original_configure = capture.configure_for_systems

        def configure_for_systems(systems_module) -> None:
            original_configure(systems_module)
            schema = int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0)
            extra_files = []
            if schema >= 7:
                extra_files.extend(
                    name for name in getattr(systems_module, "JSONL_FILES", ())
                    if name.startswith("smartobject_") and name.endswith(".jsonl")
                )
            if schema >= 8:
                extra_files.extend(
                    name for name in getattr(systems_module, "JSONL_FILES", ())
                    if name.startswith("ai_perception_") and name.endswith(".jsonl")
                )
            if schema >= 9:
                extra_files.extend(
                    name for name in getattr(systems_module, "JSONL_FILES", ())
                    if (name.startswith("dataflow_") or name.startswith("geometry_collection"))
                    and name.endswith(".jsonl")
                )
            capture.CAPTURE_FILES = tuple(dict.fromkeys((*capture.CAPTURE_FILES, *extra_files)))
            capture.SCHEMA_FILES = capture.CAPTURE_FILES[len(capture._BASE_CAPTURE_FILES):]

        capture.configure_for_systems = configure_for_systems
        capture._schema7plus_specialist_config_installed = True

    # Preserve a raw archive even when a post-Unreal schema/semantic gate fails.
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
                        if value == "--output" and index + 1 < len(argv):
                            output_value = argv[index + 1]
                        elif value == "--archive" and index + 1 < len(argv):
                            archive_value = argv[index + 1]
                    output = (
                        Path(output_value).expanduser().resolve()
                        if output_value
                        else project.parent / ".uatool" / f"systems-schema{capture.CAPTURE_SCHEMA_VERSION}-capture"
                    )
                    archive = (
                        Path(archive_value).expanduser().resolve()
                        if archive_value
                        else project.parent / ".uatool" / f"{project.stem}.systems-schema{capture.CAPTURE_SCHEMA_VERSION}-capture.zip"
                    )
                    if all((output / filename).is_file() for filename in capture.CAPTURE_FILES):
                        capture._write_capture_archive(output, archive)
                        print(f"raw systems capture archive preserved after failure: {archive}")
                except Exception as archive_exc:
                    print(f"note: could not preserve raw systems capture archive: {archive_exc}")
                raise

        capture._capture_cli = capture_cli
        capture._schema7plus_raw_archive_guard_installed = True

    capture.configure_for_systems(_systems)


if not getattr(_build_perf, "_systems_schema9_composition_installed", False):
    _original_build_perf_install = _build_perf.install

    def _build_perf_install_with_schema9(core) -> None:
        _original_build_perf_install(core)
        _systems_smartobjects.install(_systems)
        _systems_ai_perception.install(_systems)
        _systems_dataflow_chaos.install(_systems)
        _smartobject_graph.install(_project_graph)
        _ai_perception_graph.install(_project_graph)
        _dataflow_chaos_graph.install(_project_graph)
        _systems_schema7_accept.install(_runtime, _systems)
        _systems_schema8_accept.install(_runtime, _systems)
        _systems_schema9_accept.install(_runtime, _systems)
        _install_specialist_capture_membership()

    _build_perf.install = _build_perf_install_with_schema9
    _build_perf._systems_schema9_composition_installed = True

# uatool.py imports this facade before its final derive/VFX gates are defined.
# Install only deferred runtime dispatch hooks here; each hook waits until the
# public composition root is complete before consulting or patching it.
_smartobject_capabilities.install(_capabilities)
_ai_perception_capabilities.install(_capabilities)
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

__all__ = (
    "VFX_SCHEMA_VERSION", "RAW_FILES", "create_schema", "read_manifest",
    "validation_error", "load_database", "query",
)
