from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_schema8_accept as accept


class SystemsSchema8AcceptanceTest(unittest.TestCase):
    def test_loss_counters_are_required_and_must_be_zero(self) -> None:
        good_counts = {key: 0 for key in accept.LOSS_COUNT_KEYS}
        manifest = {"counts": good_counts}
        self.assertEqual(accept._require_lossless_manifest(manifest), good_counts)

        for key in accept.LOSS_COUNT_KEYS:
            bad = {"counts": dict(good_counts)}
            bad["counts"][key] = 1
            with self.assertRaisesRegex(RuntimeError, key):
                accept._require_lossless_manifest(bad)

            missing = {"counts": dict(good_counts)}
            del missing["counts"][key]
            with self.assertRaisesRegex(RuntimeError, key):
                accept._require_lossless_manifest(missing)

    def test_schema8_contract_and_composition_are_public(self) -> None:
        self.assertEqual(accept.TARGET_DERIVED_SCHEMA_VERSION, 24)
        self.assertEqual(accept.ACCEPTANCE_MANIFEST, "systems_schema8_acceptance.json")
        self.assertEqual(accept.GRAPH_EXPECTATIONS_MANIFEST, "ai_perception_graph_expectations.json")
        self.assertEqual(accept.GRAPH_VERIFICATION_MANIFEST, "ai_perception_graph_verification.json")

        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_systems_ai_perception as _systems_ai_perception", facade)
        self.assertIn("import uatool_ai_perception_graph as _ai_perception_graph", facade)
        self.assertIn("import uatool_systems_schema8_accept as _systems_schema8_accept", facade)
        self.assertIn("_systems_ai_perception.install(_systems)", facade)
        self.assertIn("_ai_perception_graph.install(_project_graph)", facade)
        self.assertIn("_systems_schema8_accept.install(_runtime, _systems)", facade)
        self.assertIn('name.startswith("ai_perception_")', facade)


if __name__ == "__main__":
    unittest.main()
