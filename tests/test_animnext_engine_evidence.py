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

import uatool_animnext_engine_evidence as evidence


class AnimNextEngineEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.engine = self.root / "UE_5.8" / "Engine"
        self.editor = self.engine / "Binaries" / "Win64" / "UnrealEditor-Cmd.exe"
        self.editor.parent.mkdir(parents=True)
        self.editor.write_bytes(b"")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _plugin(self, relative: str, name: str, *, can_content: bool, assets: tuple[str, ...] = ()) -> None:
        plugin = self.engine / "Plugins" / "Experimental" / "UAF" / relative
        plugin.mkdir(parents=True, exist_ok=True)
        descriptor = plugin / f"{name}.uplugin"
        descriptor.write_text(json.dumps({
            "FileVersion": 3,
            "FriendlyName": name,
            "Category": "Animation",
            "CanContainContent": can_content,
            "IsExperimentalVersion": True,
            "Modules": [{"Name": name, "Type": "Editor", "LoadingPhase": "Default"}],
        }), encoding="utf-8")
        for asset in assets:
            path = plugin / "Content" / asset
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"asset")

    def test_finds_test_and_shared_plugin_content_without_running_unreal(self) -> None:
        self._plugin("UAF", "UAF", can_content=False)
        self._plugin("UAFTestSuites", "UAFTestSuites", can_content=True, assets=(
            "Tests/AG_TestGraph.uasset",
            "Maps/UAF_Test.umap",
        ))
        self._plugin("UAFSharedAssets", "UAFSharedAssets", can_content=True, assets=(
            "Examples/AG_Shared.uasset",
        ))
        report = evidence.build_report(self.editor)
        self.assertTrue(report["diagnostic_only"])
        self.assertFalse(report["unreal_was_run"])
        self.assertFalse(report["schema_promotion"])
        self.assertEqual(report["plugin_count"], 3)
        self.assertEqual(report["content_plugin_count"], 2)
        self.assertEqual(report["total_content_assets"], 3)
        self.assertEqual(report["test_like_asset_count"], 2)
        self.assertEqual(report["sample_like_asset_count"], 1)
        rendered = evidence.render_report(report)
        self.assertIn("UAFTestSuites", rendered)
        self.assertIn("AG_TestGraph.uasset", rendered)
        self.assertIn("Representative installed plugin content exists", rendered)

    def test_no_uaf_root_is_explicit(self) -> None:
        report = evidence.build_report(self.editor)
        self.assertEqual(report["uaf_roots"], [])
        self.assertEqual(report["plugin_count"], 0)
        self.assertEqual(report["total_content_assets"], 0)
        self.assertIn("separate authored representative project", evidence.render_report(report))

    def test_facade_wires_public_command(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_animnext_engine_evidence as _animnext_engine_evidence", facade)
        self.assertIn("_animnext_engine_evidence.install(_runtime)", facade)
        source = (SCRIPTS / "uatool_animnext_engine_evidence.py").read_text(encoding="utf-8")
        self.assertIn('sys.argv[1] == "animnext-engine-evidence"', source)
        self.assertIn("unreal_was_run", source)


if __name__ == "__main__":
    unittest.main()
