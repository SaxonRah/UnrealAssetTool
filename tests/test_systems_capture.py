from __future__ import annotations

import json
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

    def test_capture_inspector_reports_exact_malformed_tail(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "capture.zip"
            manifest = {
                "schema_version": 5,
                "success": True,
                "error": "",
                "counts": {name.removesuffix(".jsonl"): 0 for name in capture.CAPTURE_FILES if name.endswith(".jsonl")},
            }
            manifest["counts"]["mass_entity_configs"] = 2
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                bundle.writestr("systems_manifest.json", json.dumps(manifest))
                for name in capture.CAPTURE_FILES:
                    if name == "systems_manifest.json":
                        continue
                    if name == "mass_entity_configs.jsonl":
                        bundle.writestr(name, b'{"config_path":"/Game/A","trait_count":0}\n{"config_path":"/Game/B')
                    else:
                        bundle.writestr(name, b"")

            report = capture.inspect_capture_archive(archive)
            self.assertIn("zip_crc: OK", report)
            self.assertIn("mass_entity_configs.jsonl: INVALID", report)
            self.assertIn("rows_valid=1", report)
            self.assertIn("declared=2", report)
            self.assertIn("first_error: line=2", report)
            self.assertIn("malformed_tail=True", report)
            self.assertIn("jsonl_files_invalid: 1", report)

    def test_native_isolated_gate_runs_systems_requests_exit_and_finalizes_on_pre_exit(self):
        driver = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsDriver.inl").read_text(
            encoding="utf-8"
        )
        scanner = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp").read_text(
            encoding="utf-8"
        )
        finalizer = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsFinalize.inl").read_text(
            encoding="utf-8"
        )
        self.assertIn('TEXT("UnrealAssetToolSystemsOnly")', driver)
        self.assertIn("if (!bSystemsOnly && !RunCommandlet.Equals", driver)
        self.assertIn("FPlatformMisc::RequestExit(false)", driver)
        self.assertIn('#include "HAL/PlatformMisc.h"', scanner)
        self.assertIn('#include "UnrealAssetToolSystemsDriver.inl"', scanner)
        self.assertIn('#include "UnrealAssetToolSystemsFinalize.inl"', scanner)
        self.assertIn("FCoreDelegates::OnEnginePreExit.AddStatic", finalizer)
        self.assertNotIn("GetOnPostEngineInit().AddStatic", finalizer)
        self.assertIn("GSystemsOnlyWriterBuffersFinalized", finalizer)
        self.assertIn("GMoverWriters = FMoverWriters();", finalizer)
        self.assertIn("GGameplayCameraWriters = FGameplayCameraWriters();", finalizer)
        self.assertIn("GMassZoneGraphWriters = FMassZoneGraphWriters();", finalizer)

    def test_canonical_composition_installs_systems_capture_command(self):
        import uatool  # noqa: F401
        import uatool_runtime

        self.assertTrue(getattr(uatool_runtime, "_systems_capture_installed", False))


if __name__ == "__main__":
    unittest.main()
