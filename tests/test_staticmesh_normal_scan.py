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

import uatool_staticmesh_integration as integration
import uatool_staticmesh_schema as schema


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class StaticMeshNormalScanTest(unittest.TestCase):
    def test_world_commandlet_runs_staticmesh_compact_pass(self):
        source = (
            ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolModule.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn('RunCommandlet.Equals(TEXT("UnrealAssetToolWorld")', source)
        self.assertIn("UUnrealAssetToolStaticMeshCommandlet", source)
        self.assertIn('TEXT("staticmesh-native-capture")', source)
        self.assertIn("RunAnimationMeshPhysicsPass(OutputDir);", source)
        self.assertIn("RunStaticMeshPass(OutputDir);", source)

    def test_pending_capture_is_promoted_before_derived_graph(self):
        source = (SCRIPTS / "uatool_staticmesh_integration.py").read_text(encoding="utf-8")
        start = source.index("    def derive_output(output):")
        end = source.index("    def build_database(output):", start)
        block = source[start:end]
        self.assertLess(
            block.index("_promote_pending_capture(output)"),
            block.index("original_derive_output(output)"),
        )
        self.assertIn("StaticMesh normal-scan capture survived derive", source)

    def test_zero_mesh_normal_pass_clears_stale_mesh_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / ".uatool"
            capture = output / integration.AUTO_CAPTURE_DIR
            capture.mkdir(parents=True)
            write_json(output / "manifest.json", {
                "schema_version": 12,
                "derived_schema_version": 30,
                "mesh_schema_version": 1,
                "mesh_counts": {"static_meshes": 7},
                "mesh_files": list(schema.JSONL_FILES),
                "mesh_pass": "UnrealAssetToolStaticMesh",
                "canonical_passes": ["structural", "world", "animation", "mesh"],
            })
            write_json(output / schema.MANIFEST_FILE, {
                "schema_version": 1,
                "success": True,
                "counts": {"static_meshes": 7},
            })
            for filename in schema.JSONL_FILES:
                (output / filename).write_text('{"stale":true}\n', encoding="utf-8")
            write_json(capture / "staticmesh_capture_manifest.json", {
                "schema_version": 1,
                "success": True,
                "diagnostic_only": True,
                "semantic_promotion": False,
                "schema_promotion": False,
                "runtime_state_captured": False,
                "render_buffers_captured": False,
                "nanite_resources_captured": False,
                "runtime_physics_state_captured": False,
                "maps_loaded": False,
                "counts": {"static_meshes": 0, "load_failures": 0},
            })

            self.assertFalse(integration._promote_pending_capture(output))
            self.assertFalse(capture.exists())
            for filename in schema.RAW_FILES:
                self.assertFalse((output / filename).exists(), filename)
            top = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(top["schema_version"], 12)
            self.assertNotIn("mesh_schema_version", top)
            self.assertNotIn("mesh_counts", top)
            self.assertNotIn("mesh_files", top)
            self.assertNotIn("mesh_pass", top)
            self.assertNotIn("mesh", top["canonical_passes"])


if __name__ == "__main__":
    unittest.main()
