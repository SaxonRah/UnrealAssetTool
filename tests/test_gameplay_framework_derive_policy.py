from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import uatool_gameplay_framework_derive_policy as policy


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


def test_legacy_systems_self_validation_accepts_intact_schema9(tmp_path: Path) -> None:
    _accepted_corpus(tmp_path)
    systems = SimpleNamespace(SYSTEMS_SCHEMA_VERSION=11)
    assert policy._accepted_gameplay_framework_corpus(tmp_path)
    assert policy.legacy_systems_error(tmp_path, systems) is None


def test_legacy_systems_self_validation_rejects_corrupt_counts(tmp_path: Path) -> None:
    _accepted_corpus(tmp_path, corrupt_count=True)
    systems = SimpleNamespace(SYSTEMS_SCHEMA_VERSION=11)
    assert "count mismatch" in str(policy.legacy_systems_error(tmp_path, systems))


def test_public_policy_bypasses_only_accepted_intact_legacy_corpus(tmp_path: Path) -> None:
    _accepted_corpus(tmp_path)

    def strict_require(_output: Path) -> None:
        raise RuntimeError("systems scan incomplete: expected systems schema 11, got 9")

    public = SimpleNamespace(
        __file__=str(Path(policy.__file__).with_name("uatool.py")),
        _require_systems=strict_require,
        derive_output=lambda output: output,
        systems=SimpleNamespace(SYSTEMS_SCHEMA_VERSION=11),
    )
    assert policy.apply_public_policy(modules=[public])
    assert public._require_systems(tmp_path) is None


def test_public_policy_preserves_strict_failure_for_unaccepted_corpus(tmp_path: Path) -> None:
    _write_jsonl(tmp_path / "systems_assets.jsonl", 1)
    _write_json(tmp_path / "systems_manifest.json", {
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
    assert policy.apply_public_policy(modules=[public])
    with pytest.raises(RuntimeError, match="expected systems schema 11"):
        public._require_systems(tmp_path)
