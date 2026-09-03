#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_staticmesh_capture as capture


class StaticMeshCaptureOrderingTest(unittest.TestCase):
    def test_accepts_unreal_case_insensitive_path_order(self) -> None:
        paths = [
            "/Game/a/SM_First.SM_First",
            "/Game/B/SM_Second.SM_Second",
        ]
        self.assertNotEqual(paths, sorted(set(paths)))
        capture._validate_unreal_path_order(paths)

    def test_rejects_reverse_case_insensitive_path_order(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "case-insensitive path order"):
            capture._validate_unreal_path_order([
                "/Game/B/SM_Second.SM_Second",
                "/Game/a/SM_First.SM_First",
            ])

    def test_rejects_case_insensitive_duplicate_identity(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "duplicate case-insensitive"):
            capture._validate_unreal_path_order([
                "/Game/Mesh/SM_Box.SM_Box",
                "/game/mesh/sm_box.sm_box",
            ])

    def test_offline_report_command_is_installed(self) -> None:
        class Runtime:
            _staticmesh_capture_installed = False

            @staticmethod
            def main():
                return 17

        original_argv = sys.argv
        try:
            capture.install(Runtime, object())
            sys.argv = ["uatool.py", "unrelated"]
            self.assertEqual(Runtime.main(), 17)
        finally:
            sys.argv = original_argv
        self.assertTrue(Runtime._staticmesh_capture_installed)


if __name__ == "__main__":
    unittest.main()
