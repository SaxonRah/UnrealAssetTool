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

    def test_deferred_animation_api_keeps_idempotent_storage_patches(self) -> None:
        source = inspect.getsource(integration.install)
        ensure_start = source.index("def ensure_animation_api()")
        ensure_end = source.index("def create_schema(conn)")
        ensure = source[ensure_start:ensure_end]
        self.assertIn("_patch_curve_storage_for_schema3()", ensure)
        self.assertIn("_patch_property_storage_for_schema3()", ensure)
        self.assertIn("mesh_physics.install(animation)", ensure)


if __name__ == "__main__":
    unittest.main()
