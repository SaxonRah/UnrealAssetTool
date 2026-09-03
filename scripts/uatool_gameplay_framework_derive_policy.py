#!/usr/bin/env python3
"""Narrow derive compatibility for accepted Gameplay Framework corpora.

Gameplay Framework derived schema 28 is a join over structural/world/source truth;
it does not require UAF systems schema 10 or Navigation systems schema 11.  A full
corpus captured before those specialist additions may therefore be re-derived
without rerunning Unreal, provided its older systems pass is still internally
self-consistent.

This policy never weakens the canonical systems validator globally.  It wraps
only the public derive prerequisite and only for a corpus that already passed
`gameplay-framework-accept`.  Older systems streams remain truthfully absent and
cannot produce UAF/Navigation graph semantics.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

ACCEPTANCE_MANIFEST = "gameplay_framework_acceptance.json"
EXPECTATIONS_MANIFEST = "gameplay_framework_graph_expectations.json"
TARGET_DERIVED_SCHEMA_VERSION = 28
MIN_COMPAT_SYSTEMS_SCHEMA = 9


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _count_rows(path: Path) -> int:
    if not path.is_file():
        return -1
    count = 0
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for line in handle:
                if line.strip():
                    count += 1
    except OSError:
        return -1
    return count


def _accepted_gameplay_framework_corpus(output: Path) -> bool:
    output = Path(output).expanduser().resolve()
    accepted = _read_json(output / ACCEPTANCE_MANIFEST)
    expected = _read_json(output / EXPECTATIONS_MANIFEST)
    return (
        int(accepted.get("target_derived_schema_version", 0) or 0) == TARGET_DERIVED_SCHEMA_VERSION
        and int(expected.get("target_derived_schema_version", 0) or 0) == TARGET_DERIVED_SCHEMA_VERSION
        and str(expected.get("edge_quality", "") or "") == "exact_semantic"
        and int(expected.get("expected_exact_semantic_edge_count", 0) or 0) > 0
        and accepted.get("runtime_state_captured") is False
        and accepted.get("native_default_state_inferred") is False
    )


def legacy_systems_error(output: Path, systems_module) -> str | None:
    """Validate an older systems pass against its own declared schema contract.

    This intentionally does not pretend the corpus is current schema 11.  It
    proves only that the older successful pass is intact enough to be reused by
    an unrelated derived-only feature.
    """
    output = Path(output).expanduser().resolve()
    manifest = _read_json(output / "systems_manifest.json")
    if not manifest:
        return "systems_manifest.json missing or invalid"

    version = int(manifest.get("schema_version", 0) or 0)
    current = int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0)
    if version < MIN_COMPAT_SYSTEMS_SCHEMA:
        return f"systems schema {version} is older than compatibility floor {MIN_COMPAT_SYSTEMS_SCHEMA}"
    if current and version >= current:
        return f"systems schema {version} is not an older compatibility corpus (current={current})"
    if manifest.get("pass") != "UnrealAssetToolSystems":
        return f"unexpected systems pass {manifest.get('pass')!r}"
    if not bool(manifest.get("success", False)):
        return f"systems scanner failed: {manifest.get('error', '')}"

    files = manifest.get("files", [])
    counts = manifest.get("counts", {})
    if not isinstance(files, list) or not files:
        return "systems manifest files missing or invalid"
    if not isinstance(counts, dict):
        return "systems manifest counts missing or invalid"

    seen = set()
    for filename in files:
        filename = str(filename or "")
        if not filename.endswith(".jsonl") or filename in seen:
            return f"invalid or duplicate systems stream declaration: {filename!r}"
        seen.add(filename)
        actual = _count_rows(output / filename)
        if actual < 0:
            return f"systems stream missing: {filename}"
        key = filename.removesuffix(".jsonl")
        try:
            declared = int(counts.get(key, -1))
        except (TypeError, ValueError):
            declared = -1
        if declared != actual:
            return f"systems count mismatch for {key}: manifest={counts.get(key)} actual={actual}"
    return None


def _canonical_module(modules=None):
    target = Path(__file__).with_name("uatool.py").resolve()
    values = tuple(modules if modules is not None else sys.modules.values())
    for module in values:
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            if Path(module_file).resolve() != target:
                continue
        except (OSError, RuntimeError, TypeError):
            continue
        if (
            hasattr(module, "_require_systems")
            and hasattr(module, "derive_output")
            and hasattr(module, "systems")
        ):
            return module
    return None


def apply_public_policy(*, modules=None) -> bool:
    public = _canonical_module(modules)
    if public is None:
        return False
    if bool(getattr(public, "_gameplay_framework_legacy_systems_derive_policy_installed", False)):
        return True

    original_require_systems = public._require_systems
    systems_module = public.systems

    def require_systems(output: Path) -> None:
        output = Path(output).expanduser().resolve()
        try:
            return original_require_systems(output)
        except RuntimeError:
            if not _accepted_gameplay_framework_corpus(output):
                raise
            error = legacy_systems_error(output, systems_module)
            if error:
                raise
            manifest = _read_json(output / "systems_manifest.json")
            version = int(manifest.get("schema_version", 0) or 0)
            current = int(getattr(systems_module, "SYSTEMS_SCHEMA_VERSION", 0) or 0)
            print(
                "systems compatibility: reusing accepted legacy systems schema "
                f"{version} for Gameplay Framework derived-only promotion (current={current}); "
                "later specialist streams remain absent/unpromoted"
            )
            return None

    public._require_systems = require_systems
    public._gameplay_framework_legacy_systems_derive_policy_installed = True
    return True


def install(runtime_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if bool(getattr(runtime_module, "_gameplay_framework_derive_policy_deferred_installed", False)):
        return

    original_main = runtime_module.main

    def main():
        apply_public_policy()
        return original_main()

    runtime_module.main = main
    runtime_module._gameplay_framework_derive_policy_deferred_installed = True
