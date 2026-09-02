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
import uatool_inspect as _inspect
import uatool_project_intelligence as _project_intelligence
import uatool_smartobject_evidence as _smartobject_evidence
import uatool_smartobject_capture as _smartobject_capture
import uatool_ai_perception_evidence as _ai_perception_evidence

# Smart Objects schema 7 must be composed after the existing Mass -> GAS systems
# installers. uatool.py imports this facade before it calls build_perf.install(),
# so wrap that single existing composition point rather than adding another
# public launcher or relying on runtime dispatch order.
import uatool_build_perf as _build_perf
import uatool_systems as _systems
import uatool_systems_smartobjects as _systems_smartobjects
import uatool_project_graph as _project_graph
import uatool_smartobject_graph as _smartobject_graph
import uatool_systems_schema7_accept as _systems_schema7_accept


def _install_smartobject_capture_membership() -> None:
    import uatool_systems_capture as capture
    if not getattr(capture, "_smartobject_schema7_config_installed", False):
        original_configure = capture.configure_for_systems

        def configure_for_systems(systems_module) -> None:
            original_configure(systems_module)
            if int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0) < 7:
                return
            smart_files = tuple(
                name for name in getattr(systems_module, "JSONL_FILES", ())
                if name.startswith("smartobject_") and name.endswith(".jsonl")
            )
            capture.CAPTURE_FILES = tuple(dict.fromkeys((*capture.CAPTURE_FILES, *smart_files)))
            capture.SCHEMA_FILES = capture.CAPTURE_FILES[len(capture._BASE_CAPTURE_FILES):]

        capture.configure_for_systems = configure_for_systems
        capture._smartobject_schema7_config_installed = True

    # Preserve a raw archive even when a post-Unreal schema/semantic gate fails.
    # The base capture command historically checked the manifest version before
    # writing its ZIP; that made a complete failed capture harder to diagnose.
    if not getattr(capture, "_smartobject_schema7_raw_archive_guard_installed", False):
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
        capture._smartobject_schema7_raw_archive_guard_installed = True

    capture.configure_for_systems(_systems)


if not getattr(_build_perf, "_smartobject_schema7_composition_installed", False):
    _original_build_perf_install = _build_perf.install

    def _build_perf_install_with_smartobjects(core) -> None:
        _original_build_perf_install(core)
        _systems_smartobjects.install(_systems)
        _smartobject_graph.install(_project_graph)
        _systems_schema7_accept.install(_runtime, _systems)
        _install_smartobject_capture_membership()

    _build_perf.install = _build_perf_install_with_smartobjects
    _build_perf._smartobject_schema7_composition_installed = True

# uatool.py imports this facade before its final derive/VFX gates are defined.
# Install only deferred runtime dispatch hooks here; each hook waits until the
# public composition root is complete before consulting or patching it.
_smartobject_capabilities.install(_capabilities)
_systems_only_derive_deferred.install()
_capabilities.install()
_inspect.install()
_project_intelligence.install()
_smartobject_evidence.install(_runtime)
_smartobject_capture.install(_runtime)
_ai_perception_evidence.install(_runtime)

__all__ = (
    "VFX_SCHEMA_VERSION", "RAW_FILES", "create_schema", "read_manifest",
    "validation_error", "load_database", "query",
)
