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

import uatool_world_geometry_integration as integration
import uatool_world_geometry_schema as schema


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class WorldGeometryNormalScanTest(unittest.TestCase):
    def test_world_commandlet_runs_both_authored_geometry_passes(self):
        source = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolModule.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn('#include "UnrealAssetToolWorldGeometryCommandlet.h"', source)
        self.assertIn('#include "UnrealAssetToolWorldGeometryFoliageCommandlet.h"', source)
        self.assertIn('RunCommandlet.Equals(TEXT("UnrealAssetToolWorld")', source)
        self.assertIn('TEXT("world-geometry-native-capture")', source)
        self.assertIn("UUnrealAssetToolWorldGeometryCommandlet", source)
        self.assertIn("UUnrealAssetToolWorldGeometryFoliageCommandlet", source)
        self.assertIn("GeometryCommandlet->Main(Params)", source)
        self.assertIn("FoliageCommandlet->Main(Params)", source)
        self.assertIn("RunWorldGeometryPass(OutputDir);", source)
        self.assertLess(source.index("RunStaticMeshPass(OutputDir);"), source.index("RunWorldGeometryPass(OutputDir);"))
        self.assertNotIn("LoadMap(", source)
        self.assertNotIn("CreateProc(", source)
        self.assertNotIn("UnrealEditor-Cmd", source)

    def test_pending_capture_is_promoted_before_derived31(self):
        source = (SCRIPTS / "uatool_world_geometry_integration.py").read_text(encoding="utf-8")
        start = source.index("    def derive_output(output):")
        end = source.index("    def build_database(output):", start)
        block = source[start:end]
        self.assertLess(block.index("_promote_pending_capture(output)"), block.index("original_derive_output(output)"))
        self.assertIn("world-geometry normal-scan capture survived derive", source)
        self.assertIn("_world_geometry_schema31_composition_installed", source)

    def test_native_foliage_composition_installs_schema_before_build_perf(self):
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        native = (SCRIPTS / "uatool_world_geometry_foliage_native_integration.py").read_text(encoding="utf-8")
        self.assertIn("uatool_world_geometry_foliage_native_integration", facade)
        self.assertIn("_world_geometry_foliage_native_integration.install(_core)", facade)
        self.assertIn("canonical_integration.install(runtime, core_module)", native)
        self.assertIn("derived schema 31", native)

    def test_zero_candidate_normal_pass_clears_stale_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / ".uatool"
            capture = output / integration.AUTO_CAPTURE_DIR
            capture.mkdir(parents=True)
            write_json(output / "manifest.json", {
                "schema_version": 12,
                "derived_schema_version": 31,
                "world_geometry_schema_version": 1,
                "world_geometry_counts": {"world_geometry_landscapes": 7},
                "world_geometry_files": list(schema.JSONL_FILES),
                "world_geometry_pass": schema.CANONICAL_PASS,
                "canonical_passes": ["structural", "world", "animation", "mesh", "world_geometry"],
            })
            write_json(output / schema.MANIFEST_FILE, {
                "schema_version": 1,
                "success": True,
                "counts": {"world_geometry_landscapes": 7},
            })
            for filename in schema.JSONL_FILES:
                (output / filename).write_text('{"stale":true}\n', encoding="utf-8")
            write_json(capture / "world_geometry_capture_manifest.json", {
                "schema_version": 1,
                "success": True,
                "counts": {"registry_candidates": 0, "load_failures": 0},
            })

            self.assertFalse(integration._promote_pending_capture(output))
            self.assertFalse(capture.exists())
            for filename in schema.RAW_FILES:
                self.assertFalse((output / filename).exists(), filename)
            top = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(top["schema_version"], 12)
            self.assertNotIn("world_geometry_schema_version", top)
            self.assertNotIn("world_geometry_counts", top)
            self.assertNotIn("world_geometry_files", top)
            self.assertNotIn("world_geometry_pass", top)
            self.assertNotIn("world_geometry", top["canonical_passes"])


if __name__ == "__main__":
    unittest.main()
