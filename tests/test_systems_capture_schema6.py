from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_capture as capture
import uatool_systems_gas as gas


class SystemsCaptureSchema6Test(unittest.TestCase):
    def test_canonical_capture_retains_schema6_and_gas_streams(self) -> None:
        import uatool  # noqa: F401
        import uatool_systems

        capture.configure_for_systems(uatool_systems)
        self.assertGreaterEqual(capture.CAPTURE_SCHEMA_VERSION, 6)
        self.assertTrue(set(gas.GAS_FILES).issubset(capture.CAPTURE_FILES))
        self.assertTrue(set(capture.SCHEMA5_FILES).issubset(capture.CAPTURE_FILES))
        self.assertNotIn("world_actors.jsonl", capture.CAPTURE_FILES)

    def test_capture_command_uses_composed_schema_not_hardcoded_five(self) -> None:
        source = (SCRIPTS / "uatool_systems_capture.py").read_text(encoding="utf-8")
        self.assertIn("actual_schema != CAPTURE_SCHEMA_VERSION", source)
        self.assertNotIn("expected schema 5, got", source)
        self.assertIn('print("normal project scan was not run")', source)
        self.assertIn('print("derive was not run")', source)


if __name__ == "__main__":
    unittest.main()
