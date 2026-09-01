from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_runtime as runtime
import uatool_validation_perf as validation_perf


class ValidationPerfTests(unittest.TestCase):
    def test_validation_failures_are_not_cached(self) -> None:
        calls = []
        results = ["intermediate failure", None]

        def validate(output, *args, **kwargs):
            calls.append(Path(output))
            return results[len(calls) - 1]

        module = SimpleNamespace(validation_error=validate)
        validation_perf._wrap(module, ("state.jsonl",), "test")

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            (output / "state.jsonl").write_text("same\n", encoding="utf-8")

            self.assertEqual(module.validation_error(output), "intermediate failure")
            self.assertIsNone(module.validation_error(output))
            self.assertEqual(len(calls), 2)

    def test_runtime_write_revision_invalidates_same_stat_success_cache(self) -> None:
        validation_perf._install_write_tracking()
        calls = []

        def validate(output, *args, **kwargs):
            path = Path(output) / "state.jsonl"
            calls.append(path.read_text(encoding="utf-8"))
            return None

        module = SimpleNamespace(validation_error=validate)
        validation_perf._wrap(module, ("state.jsonl",), "test")

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            path = output / "state.jsonl"
            fixed_ns = 1_700_000_000_000_000_000

            runtime._write(path, [{"value": "A"}])
            os.utime(path, ns=(fixed_ns, fixed_ns))
            first_stat = path.stat()
            first_signature = validation_perf._signature(output, ("state.jsonl",))

            self.assertIsNone(module.validation_error(output))
            self.assertIsNone(module.validation_error(output))
            self.assertEqual(len(calls), 1)

            runtime._write(path, [{"value": "B"}])
            os.utime(path, ns=(fixed_ns, fixed_ns))
            second_stat = path.stat()
            second_signature = validation_perf._signature(output, ("state.jsonl",))

            self.assertEqual(first_stat.st_size, second_stat.st_size)
            self.assertEqual(first_stat.st_mtime_ns, second_stat.st_mtime_ns)
            self.assertNotEqual(first_signature, second_signature)

            self.assertIsNone(module.validation_error(output))
            self.assertEqual(len(calls), 2)
            self.assertIn('"B"', calls[-1])


if __name__ == "__main__":
    unittest.main()
