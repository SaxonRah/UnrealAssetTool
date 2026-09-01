from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_capture as capture


class SystemsCaptureTests(unittest.TestCase):
    def test_archive_contains_only_focused_capture_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "capture"
            output.mkdir()
            for name in capture.CAPTURE_FILES:
                (output / name).write_text("{}\n", encoding="utf-8")
            (output / "world_actors.jsonl").write_text("should-not-ship\n", encoding="utf-8")

            archive = root / "capture.zip"
            capture._write_capture_archive(output, archive)
            with zipfile.ZipFile(archive, "r") as bundle:
                self.assertEqual(bundle.namelist(), list(capture.CAPTURE_FILES))
                self.assertNotIn("world_actors.jsonl", bundle.namelist())

    def test_native_isolated_gate_runs_systems_and_requests_exit(self):
        driver = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsDriver.inl").read_text(
            encoding="utf-8"
        )
        scanner = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn('TEXT("UnrealAssetToolSystemsOnly")', driver)
        self.assertIn("if (!bSystemsOnly && !RunCommandlet.Equals", driver)
        self.assertIn("FPlatformMisc::RequestExit(false)", driver)
        self.assertIn('#include "HAL/PlatformMisc.h"', scanner)

    def test_canonical_composition_installs_systems_capture_command(self):
        import uatool  # noqa: F401
        import uatool_runtime

        self.assertTrue(getattr(uatool_runtime, "_systems_capture_installed", False))


if __name__ == "__main__":
    unittest.main()
