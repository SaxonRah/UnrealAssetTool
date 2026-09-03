from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_gameplay_framework_derive_policy as policy


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, count: int) -> None:
    path.write_text("".join(json.dumps({"i": i}) + "\n" for i in range(count)), encoding="utf-8")


def _accepted_corpus(root: Path, *, corrupt_count: bool = False) -> None:
    _write_json(root / policy.ACCEPTANCE_MANIFEST, {
        "target_derived_schema_version": 28,
        "runtime_state_captured": False,
        "native_default_state_inferred": False,
    })
    _write_json(root / policy.EXPECTATIONS_MANIFEST, {
        "target_derived_schema_version": 28,
        "edge_quality": "exact_semantic",
        "expected_exact_semantic_edge_count": 187,
    })
    _write_jsonl(root / "systems_assets.jsonl", 2)
    _write_jsonl(root / "systems_properties.jsonl", 1)
    _write_json(root / "systems_manifest.json", {
        "schema_version": 9,
        "pass": "UnrealAssetToolSystems",
        "success": True,
        "files": ["systems_assets.jsonl", "systems_properties.jsonl"],
        "counts": {
            "systems_assets": 999 if corrupt_count else 2,
            "systems_properties": 1,
        },
    })


class GameplayFrameworkDerivePolicyTest(unittest.TestCase):
    def test_legacy_systems_self_validation_accepts_intact_schema9(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _accepted_corpus(root)
            systems = SimpleNamespace(SYSTEMS_SCHEMA_VERSION=11)
            self.assertTrue(policy._accepted_gameplay_framework_corpus(root))
            self.assertIsNone(policy.legacy_systems_error(root, systems))

    def test_legacy_systems_self_validation_rejects_corrupt_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _accepted_corpus(root, corrupt_count=True)
            systems = SimpleNamespace(SYSTEMS_SCHEMA_VERSION=11)
            self.assertIn("count mismatch", str(policy.legacy_systems_error(root, systems)))

    def test_public_policy_bypasses_only_accepted_intact_legacy_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _accepted_corpus(root)

            def strict_require(_output: Path) -> None:
                raise RuntimeError("systems scan incomplete: expected systems schema 11, got 9")

            public = SimpleNamespace(
                __file__=str(Path(policy.__file__).with_name("uatool.py")),
                _require_systems=strict_require,
                derive_output=lambda output: output,
                systems=SimpleNamespace(SYSTEMS_SCHEMA_VERSION=11),
            )
            self.assertTrue(policy.apply_public_policy(modules=[public]))
            self.assertIsNone(public._require_systems(root))

    def test_public_policy_preserves_strict_failure_for_unaccepted_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _write_jsonl(root / "systems_assets.jsonl", 1)
            _write_json(root / "systems_manifest.json", {
                "schema_version": 9,
                "pass": "UnrealAssetToolSystems",
                "success": True,
                "files": ["systems_assets.jsonl"],
                "counts": {"systems_assets": 1},
            })

            def strict_require(_output: Path) -> None:
                raise RuntimeError("systems scan incomplete: expected systems schema 11, got 9")

            public = SimpleNamespace(
                __file__=str(Path(policy.__file__).with_name("uatool.py")),
                _require_systems=strict_require,
                derive_output=lambda output: output,
                systems=SimpleNamespace(SYSTEMS_SCHEMA_VERSION=11),
            )
            self.assertTrue(policy.apply_public_policy(modules=[public]))
            with self.assertRaisesRegex(RuntimeError, "expected systems schema 11"):
                public._require_systems(root)


if __name__ == "__main__":
    unittest.main()
