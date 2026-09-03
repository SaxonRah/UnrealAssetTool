from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_animation_mesh_physics_integration as integration


class AnimationMeshPhysicsInstallOrderTest(unittest.TestCase):
    def test_storage_compatibility_is_installed_before_core_wrappers(self) -> None:
        source = inspect.getsource(integration.install)
        capture_point = source.index("original_create_schema = core_module.create_schema")
        early = source[:capture_point]
        self.assertIn("_patch_curve_storage_for_schema3()", early)
        self.assertIn("_patch_property_storage_for_schema3()", early)

    def test_public_schema29_is_promoted_at_canonical_build_composition(self) -> None:
        source = inspect.getsource(integration.install)
        wrapper_start = source.index("if not getattr(build_perf, \"_animation_schema29_composition_installed\"")
        capture_point = source.index("original_create_schema = core_module.create_schema")
        wrapper = source[wrapper_start:capture_point]
        self.assertIn("original_build_perf_install(core)", wrapper)
        self.assertIn("mesh_physics_graph.install(project_graph, core, runtime_module)", wrapper)
        self.assertIn("mesh_physics_graph.promote_public_derived_version(project_graph, core, runtime_module)", wrapper)
        self.assertIn("build_perf.install = build_perf_install_with_schema29", wrapper)

    def test_deferred_animation_api_keeps_idempotent_storage_and_version_patches(self) -> None:
        source = inspect.getsource(integration.install)
        ensure_start = source.index("def ensure_animation_api()")
        ensure_end = source.index("def create_schema(conn)")
        ensure = source[ensure_start:ensure_end]
        self.assertIn("_patch_curve_storage_for_schema3()", ensure)
        self.assertIn("_patch_property_storage_for_schema3()", ensure)
        self.assertIn("mesh_physics.install(animation)", ensure)
        self.assertIn("mesh_physics_graph.promote_public_derived_version(project_graph, core_module, runtime_module)", ensure)


if __name__ == "__main__":
    unittest.main()
