from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_derived_freshness as freshness
import uatool_world_geometry_foliage_native_integration as native


class WorldGeometryNativeFoliageTest(unittest.TestCase):
    def test_native_capture_uses_editor_authoring_api_not_render_instances(self):
        source = (
            ROOT
            / "Source/UnrealAssetTool/Private/UnrealAssetToolWorldGeometryFoliageCommandlet.cpp"
        ).read_text(encoding="utf-8")
        header = (
            ROOT
            / "Source/UnrealAssetTool/Public/UnrealAssetToolWorldGeometryFoliageCommandlet.h"
        ).read_text(encoding="utf-8")
        build = (ROOT / "Source/UnrealAssetTool/UnrealAssetTool.Build.cs").read_text(encoding="utf-8")

        self.assertIn("AInstancedFoliageActor", source)
        self.assertIn("ForEachFoliageInfo", source)
        self.assertIn("FFoliageInfo", source)
        self.assertIn("Info.Instances", source)
        self.assertIn("FFoliageInstance", source)
        self.assertIn("BaseComponent", source)
        self.assertIn("ProceduralGuid", source)
        self.assertIn("native_editor_array", source)
        self.assertIn("foliage_native_api_captured", source)
        self.assertIn("UUnrealAssetToolWorldGeometryFoliageCommandlet", header)
        self.assertIn('"Foliage"', build)

        for forbidden in (
            "GetInstanceTransform(",
            "PerInstanceSMData",
            "GetResourceForRendering",
            "GetStaticMeshRenderData",
            "LoadMap(",
            "CreatePhysicsState",
            "StartSimulation",
        ):
            self.assertNotIn(forbidden, source)

    def test_canonical_launcher_composes_native_refinement_after_base_capture(self):
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        base = "_world_geometry_capture.install(_runtime, _core)"
        native_install = "_world_geometry_foliage_native_integration.install(_core)"
        self.assertIn("uatool_world_geometry_foliage_native_integration", facade)
        self.assertIn(base, facade)
        self.assertIn(native_install, facade)
        self.assertLess(facade.index(base), facade.index(native_install))
        self.assertIn(
            "uatool_world_geometry_foliage_native_integration.py",
            freshness.NON_DERIVED_SCRIPTS,
        )

    def test_native_count_helper_distinguishes_native_from_reflection(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            (output / "foliage_actor_type_infos.jsonl").write_text(
                "".join(
                    json.dumps(row, separators=(",", ":")) + "\n"
                    for row in (
                        {
                            "foliage_actor_path": "/Game/Map.Map:PersistentLevel.IFA",
                            "map_index": 0,
                            "instances_captured_via_native_api": True,
                            "instances_reflected_as_struct_array": False,
                        },
                        {
                            "foliage_actor_path": "/Game/Map.Map:PersistentLevel.IFA",
                            "map_index": 1,
                            "instances_captured_via_native_api": True,
                            "instances_reflected_as_struct_array": False,
                        },
                    )
                ),
                encoding="utf-8",
            )
            (output / "foliage_instances.jsonl").write_text(
                "".join(
                    json.dumps(
                        {
                            "foliage_actor_path": "/Game/Map.Map:PersistentLevel.IFA",
                            "map_index": 0,
                            "instance_index": index,
                            "capture_mode": "native_editor_array",
                        },
                        separators=(",", ":"),
                    )
                    + "\n"
                    for index in range(3)
                ),
                encoding="utf-8",
            )
            self.assertEqual(native._native_counts(output), (2, 3))


if __name__ == "__main__":
    unittest.main()
