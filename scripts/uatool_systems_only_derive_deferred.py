#!/usr/bin/env python3
"""Deferred systems-only derive policy for the canonical public launcher.

`uatool.py` imports its helper modules before it defines the final `_require_vfx`
and `derive_output` functions. Schema-6 support is composed from installers that
run during that import phase, so attempting to patch the public root immediately
is necessarily too early.

Install one lightweight `uatool_runtime.main` wrapper instead. At command
dispatch time `uatool.py` is fully constructed; locate that exact module by file
path, apply the schema-6 systems-only derive policy there, and keep
`uatool_core.derive_output` synchronized with the newly wrapped public function.
"""
from __future__ import annotations

from pathlib import Path
import sys


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
            hasattr(module, "_require_vfx")
            and hasattr(module, "derive_output")
            and hasattr(module, "vfx")
        ):
            return module
    return None


def apply_public_policy(*, modules=None, core_module=None, schema6_module=None) -> bool:
    public = _canonical_module(modules)
    if public is None:
        return False

    if schema6_module is None:
        import uatool_systems_schema6_accept as schema6_module
    if core_module is None:
        import uatool_core as core_module

    original = public.derive_output
    schema6_module._install_systems_only_derive_policy(public)
    patched = public.derive_output
    if not bool(getattr(public, "_systems_only_derive_policy_installed", False)):
        return False

    # The canonical composition publishes its derive function to uatool_core
    # before runtime.main is dispatched. Keep that public entry point pointing
    # at the deferred wrapper as well; otherwise runtime.main would still call
    # the pre-policy function object even though uatool.py's globals were fixed.
    if getattr(core_module, "derive_output", None) is original:
        core_module.derive_output = patched
    return True


def install(runtime_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if bool(getattr(runtime_module, "_systems_only_derive_deferred_installed", False)):
        return

    original_main = runtime_module.main

    def main():
        apply_public_policy()
        return original_main()

    runtime_module.main = main
    runtime_module._systems_only_derive_deferred_installed = True
