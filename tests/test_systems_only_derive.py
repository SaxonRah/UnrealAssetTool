from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_schema6_accept as schema6
import uatool_systems_only_derive_deferred as deferred


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


class SystemsOnlyDerivePolicyTest(unittest.TestCase):
    def _accepted_root(self, root: Path) -> None:
        write_json(root / schema6.ACCEPTANCE_MANIFEST, {
            "systems_schema_version": 6,
            "target_derived_schema_version": schema6.TARGET_DERIVED_SCHEMA_VERSION,
        })
        write_json(root / "systems_manifest.json", {
            "schema_version": 6,
            "success": True,
            "counts": {"gas_abilities": 43},
            "files": ["gas_abilities.jsonl"],
            "pass": "UnrealAssetToolSystems",
        })

    def _runtime(self, calls: dict) -> types.SimpleNamespace:
        vfx = types.SimpleNamespace(
            RAW_FILES=("vfx_manifest.json", "vfx_assets.jsonl", "vfx_properties.jsonl"),
            read_manifest=lambda output: None,
        )

        def require_vfx(output):
            calls["raw"] = calls.get("raw", 0) + 1
            raise RuntimeError("strict VFX prerequisite")

        def require_vfx_derived(output):
            calls["derived"] = calls.get("derived", 0) + 1
            raise RuntimeError("strict VFX derived prerequisite")

        def derive_output(output):
            calls["derive"] = calls.get("derive", 0) + 1
            return {"project_edges": 560}

        return types.SimpleNamespace(
            vfx=vfx,
            _require_vfx=require_vfx,
            _require_vfx_derived=require_vfx_derived,
            derive_output=derive_output,
        )

    def test_fully_absent_vfx_is_optional_only_for_accepted_systems_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._accepted_root(root)
            calls = {}
            runtime = self._runtime(calls)
            schema6._install_systems_only_derive_policy(runtime)

            runtime._require_vfx(root)
            runtime._require_vfx_derived(root)
            self.assertEqual(calls.get("raw", 0), 0)
            self.assertEqual(calls.get("derived", 0), 0)

            result = runtime.derive_output(root)
            self.assertEqual(result, {"project_edges": 560})
            self.assertEqual(calls.get("derive", 0), 1)

            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["partial_corpus"])
            self.assertEqual(manifest["canonical_passes"], ["systems"])
            self.assertEqual(manifest["systems_schema_version"], 6)
            self.assertEqual(manifest["schema_version"], 0)

    def test_partial_vfx_streams_keep_strict_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._accepted_root(root)
            (root / "vfx_assets.jsonl").write_text("", encoding="utf-8")
            calls = {}
            runtime = self._runtime(calls)
            schema6._install_systems_only_derive_policy(runtime)

            with self.assertRaisesRegex(RuntimeError, "strict VFX prerequisite"):
                runtime._require_vfx(root)
            self.assertEqual(calls.get("raw", 0), 1)

    def test_normal_corpus_without_schema6_acceptance_keeps_strict_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_json(root / "systems_manifest.json", {"schema_version": 6, "success": True})
            calls = {}
            runtime = self._runtime(calls)
            schema6._install_systems_only_derive_policy(runtime)

            with self.assertRaisesRegex(RuntimeError, "strict VFX prerequisite"):
                runtime._require_vfx(root)
            self.assertEqual(calls.get("raw", 0), 1)

    def test_existing_top_manifest_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self._accepted_root(root)
            original = {"schema_version": 9, "success": True, "marker": "keep"}
            write_json(root / "manifest.json", original)
            self.assertFalse(schema6._ensure_partial_top_manifest(root))
            self.assertEqual(
                json.loads((root / "manifest.json").read_text(encoding="utf-8")),
                original,
            )

    def test_deferred_hook_patches_final_public_composition_and_core_entrypoint(self) -> None:
        calls = {}
        public = self._runtime(calls)
        public.__file__ = str(SCRIPTS / "uatool.py")
        original = public.derive_output
        core = types.SimpleNamespace(derive_output=original)

        self.assertTrue(
            deferred.apply_public_policy(
                modules=[public],
                core_module=core,
                schema6_module=schema6,
            )
        )
        self.assertTrue(public._systems_only_derive_policy_installed)
        self.assertIs(core.derive_output, public.derive_output)
        self.assertIsNot(public.derive_output, original)

    def test_runtime_dispatch_applies_deferred_policy_before_original_main(self) -> None:
        calls = []
        runtime = types.SimpleNamespace(main=lambda: calls.append("main") or 7)
        with mock.patch.object(deferred, "apply_public_policy", side_effect=lambda: calls.append("policy") or True):
            deferred.install(runtime)
            self.assertEqual(runtime.main(), 7)
        self.assertEqual(calls, ["policy", "main"])

    def test_vfx_facade_installs_deferred_public_hook(self) -> None:
        text = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_systems_only_derive_deferred", text)
        self.assertIn("_systems_only_derive_deferred.install()", text)


if __name__ == "__main__":
    unittest.main()
