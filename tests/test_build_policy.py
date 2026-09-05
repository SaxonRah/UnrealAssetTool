from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_build_perf as build_perf


class BuildPolicyRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "TestProject.uproject"
        self.project.write_text("{}\n", encoding="utf-8")
        self.editor = self.root / "Engine" / "Binaries" / "Win64" / "UnrealEditor-Win64-DebugGame-Cmd.exe"
        self.editor.parent.mkdir(parents=True)
        self.editor.write_text("", encoding="utf-8")
        self.manifest = self.root / "Binaries" / "Win64" / "UnrealEditor-Win64-DebugGame.modules"
        self.manifest.parent.mkdir(parents=True)
        self.manifest.write_text(json.dumps({"BuildId": "build-1", "Modules": {}}), encoding="utf-8")
        now = time.time()
        os.utime(self.project, (now - 30, now - 30))
        os.utime(self.manifest, (now - 10, now - 10))

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _core_for_manifest(self):
        return SimpleNamespace(project_runtime_manifest=lambda project, editor: self.manifest)

    def test_module_only_gate_ignores_active_scanner_but_not_target_native_changes(self) -> None:
        active = self.root / "Plugins" / "UnrealAssetTool"
        scanner_cpp = active / "Source" / "UnrealAssetTool" / "Private" / "Scanner.cpp"
        scanner_cpp.parent.mkdir(parents=True)
        scanner_cpp.write_text("// scanner\n", encoding="utf-8")
        now = time.time()
        os.utime(scanner_cpp, (now, now))

        game_cpp = self.root / "Source" / "TestProject" / "Game.cpp"
        game_cpp.parent.mkdir(parents=True)
        game_cpp.write_text("// game\n", encoding="utf-8")
        os.utime(game_cpp, (now - 20, now - 20))

        core = self._core_for_manifest()
        self.assertTrue(build_perf._module_only_is_safe(core, self.project, self.editor, active))

        os.utime(game_cpp, (now, now))
        self.assertFalse(build_perf._module_only_is_safe(core, self.project, self.editor, active))

    def test_plugin_discovery_stops_at_plugin_roots_and_prunes_payloads(self) -> None:
        plugins = self.root / "Plugins"

        ordinary = plugins / "Category" / "Ordinary"
        ordinary.mkdir(parents=True)
        (ordinary / "Ordinary.uplugin").write_text("{}\n", encoding="utf-8")
        # A descriptor hidden inside an existing plugin's Content tree must not
        # be treated as a separately discoverable project plugin.
        fake_nested = ordinary / "Content" / "Huge" / "UnrealAssetTool.uplugin"
        fake_nested.parent.mkdir(parents=True)
        fake_nested.write_text("{}\n", encoding="utf-8")

        actual = plugins / "Tools" / "UnrealAssetTool"
        actual.mkdir(parents=True)
        (actual / "UnrealAssetTool.uplugin").write_text("{}\n", encoding="utf-8")

        all_roots = build_perf._discover_plugin_roots(plugins)
        self.assertEqual(set(all_roots), {ordinary.resolve(), actual.resolve()})

        matching = build_perf._discover_plugin_roots(plugins, "UnrealAssetTool.uplugin")
        self.assertEqual(matching, [actual.resolve()])

    def test_native_freshness_ignores_plugin_content_but_checks_source(self) -> None:
        plugin = self.root / "Plugins" / "Category" / "OtherPlugin"
        plugin.mkdir(parents=True)
        descriptor = plugin / "OtherPlugin.uplugin"
        descriptor.write_text("{}\n", encoding="utf-8")
        source = plugin / "Source" / "OtherPlugin" / "Private" / "Other.cpp"
        source.parent.mkdir(parents=True)
        source.write_text("// source\n", encoding="utf-8")
        payload = plugin / "Content" / "Generated" / "ShouldNotCount.cpp"
        payload.parent.mkdir(parents=True)
        payload.write_text("// not a native build input\n", encoding="utf-8")

        now = time.time()
        os.utime(descriptor, (now - 20, now - 20))
        os.utime(source, (now - 20, now - 20))
        os.utime(payload, (now, now))

        active = self.root / "Plugins" / "UnrealAssetTool"
        core = self._core_for_manifest()
        self.assertTrue(build_perf._module_only_is_safe(core, self.project, self.editor, active))

        os.utime(source, (now, now))
        self.assertFalse(build_perf._module_only_is_safe(core, self.project, self.editor, active))

    def test_cache_enable_flag_and_round_trip(self) -> None:
        cache_root = self.root / "Saved" / build_perf.CACHE_DIR_NAME
        stage_root = self.root / "Plugins" / "UnrealAssetTool"
        (cache_root / "Binaries").mkdir(parents=True)
        (cache_root / "Binaries" / "module.dll").write_text("binary", encoding="utf-8")
        (cache_root / "Intermediate").mkdir(parents=True)
        (cache_root / "Intermediate" / "state.txt").write_text("state", encoding="utf-8")
        stage_root.mkdir(parents=True)

        with patch.dict(os.environ, {"UATOOL_BUILD_CACHE": "1"}, clear=False):
            self.assertTrue(build_perf._cache_enabled())
            build_perf._restore_cache(cache_root, stage_root)
            self.assertTrue((stage_root / "Binaries" / "module.dll").is_file())
            self.assertFalse((cache_root / "Binaries").exists())
            build_perf._save_cache(cache_root, stage_root)
            self.assertTrue((cache_root / "Binaries" / "module.dll").is_file())
            self.assertFalse((stage_root / "Binaries").exists())

        with patch.dict(os.environ, {"UATOOL_BUILD_CACHE": "0"}, clear=False):
            self.assertFalse(build_perf._cache_enabled())

    def test_staged_plugin_cleanup_retries_transient_windows_lock(self) -> None:
        stage = self.root / "Plugins" / "UnrealAssetTool"
        stage.mkdir(parents=True)
        (stage / "locked.dll").write_text("x", encoding="utf-8")

        with patch.object(
            build_perf.shutil,
            "rmtree",
            side_effect=[PermissionError(5, "Access is denied"), None],
        ) as remove, patch.object(build_perf.time, "sleep") as sleep:
            self.assertTrue(build_perf._remove_staged_plugin_tree(stage))

        self.assertEqual(remove.call_count, 2)
        sleep.assert_called_once_with(build_perf.STAGE_CLEANUP_RETRY_DELAYS[0])

    def test_staged_plugin_cleanup_persistent_lock_is_nonthrowing(self) -> None:
        stage = self.root / "Plugins" / "UnrealAssetTool"
        stage.mkdir(parents=True)

        with patch.object(
            build_perf.shutil,
            "rmtree",
            side_effect=PermissionError(5, "Access is denied"),
        ) as remove, patch.object(build_perf.time, "sleep"):
            self.assertFalse(build_perf._remove_staged_plugin_tree(stage))

        self.assertEqual(
            remove.call_count,
            len(build_perf.STAGE_CLEANUP_RETRY_DELAYS) + 1,
        )

    def test_module_failure_falls_back_to_full_target_and_reuses_produced_module(self) -> None:
        build_script = self.root / "Build.bat"
        build_script.write_text("", encoding="utf-8")
        active = self.root / "Plugins" / "UnrealAssetTool"
        core = SimpleNamespace(
            MODULE_NAME="UnrealAssetTool",
            resolve_build_script=lambda editor, arg: build_script,
            editor_configuration=lambda editor: "DebugGame",
            resolve_plugin_binary=lambda project, editor, active_root: self.root / "Binaries" / "UnrealEditor-UnrealAssetTool.dll",
        )

        calls: list[tuple[str, list[str]]] = []

        def fake_run(command: list[str], label: str) -> int:
            calls.append((label, command))
            return 1 if len(calls) == 1 else 0

        with patch.object(build_perf, "_module_only_is_safe", return_value=True), \
             patch.object(build_perf, "_run_timed", side_effect=fake_run):
            result = build_perf._optimized_build_project(core, self.project, self.editor, None, active)

        self.assertEqual(result, 0)
        self.assertEqual([label for label, _ in calls], [
            "building UnrealAssetTool module",
            "building target",
        ])
        self.assertIn("-ForceUnity", calls[0][1])
        self.assertIn("-DisableAdaptiveUnity", calls[0][1])
        self.assertFalse(any("-Module=UnrealAssetTool" in arg for arg in calls[1][1]))


if __name__ == "__main__":
    unittest.main()
