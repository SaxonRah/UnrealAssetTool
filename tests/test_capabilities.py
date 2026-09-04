from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_capabilities as capabilities


def write_json(root: Path, filename: str, value: dict) -> None:
    (root / filename).write_text(json.dumps(value), encoding="utf-8", newline="\n")


class CapabilityManifestTest(unittest.TestCase):
    def test_full_schema6_corpus_reports_current_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root, "manifest.json", {
                "schema_version": 12,
                "derived_schema_version": 22,
                "files": [
                    "files.jsonl", "source_chunks.jsonl", "assets.jsonl", "asset_dependencies.jsonl",
                    "blueprints.jsonl", "blueprint_graphs.jsonl",
                ],
            })
            write_json(root, "world_manifest.json", {"schema_version": 12, "files": ["worlds.jsonl"]})
            write_json(root, "animation_manifest.json", {"schema_version": 1, "files": ["animation_assets.jsonl"]})
            write_json(root, "vfx_manifest.json", {"schema_version": 1, "files": ["vfx_assets.jsonl"]})
            write_json(root, "systems_manifest.json", {
                "schema_version": 6,
                "success": True,
                "files": [
                    "systems_assets.jsonl", "mover_blueprints.jsonl", "gameplay_camera_assets.jsonl",
                    "mass_entity_configs.jsonl", "zonegraph_shapes.jsonl", "gas_abilities.jsonl",
                    "gas_gameplay_effects.jsonl",
                ],
            })
            for filename in (
                "project_nodes.jsonl",
                "project_edges.jsonl",
                "project_neighborhoods.jsonl",
                "blueprint_interprocedural_execution_edges.jsonl",
                "blueprint_interprocedural_execution_terminals.jsonl",
                "blueprint_interprocedural_data_routes.jsonl",
                "blueprint_interprocedural_function_execution_edges.jsonl",
                "blueprint_interprocedural_function_execution_terminals.jsonl",
                "blueprint_interprocedural_function_data_routes.jsonl",
            ):
                (root / filename).write_text("", encoding="utf-8")

            path = capabilities.write_manifest(root)
            self.assertIsNone(capabilities.validation_error(root))
            manifest = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["schemas"], {
                "structural": 12,
                "world": 12,
                "animation": 1,
                "vfx": 1,
                "systems": 6,
                "derived": 22,
            })
            by_family = {row["family"]: row for row in manifest["families"]}
            self.assertEqual(by_family["gas"]["contract_coverage"], "first_class")
            self.assertEqual(by_family["gas"]["corpus_coverage"], "first_class")
            self.assertIn("gas_abilities.jsonl", by_family["gas"]["canonical_streams"])
            self.assertEqual(by_family["smart_objects"]["corpus_coverage"], "generic_only")
            self.assertTrue(by_family["project_graph"]["available_in_corpus"])
            self.assertIn("project_edges.jsonl", by_family["project_graph"]["derived_streams"])
            self.assertIn(
                "blueprint_interprocedural_execution_edges.jsonl",
                by_family["blueprint"]["derived_streams"],
            )
            self.assertIn("macro_enter", by_family["blueprint"]["derived_relations"])
            self.assertIn("macro_return", by_family["blueprint"]["derived_relations"])
            self.assertIn(
                "blueprint_interprocedural_data_routes.jsonl",
                by_family["blueprint"]["derived_streams"],
            )
            self.assertIn("macro_data_input", by_family["blueprint"]["derived_relations"])
            self.assertIn("macro_data_output", by_family["blueprint"]["derived_relations"])
            self.assertIn(
                "blueprint_interprocedural_function_execution_edges.jsonl",
                by_family["blueprint"]["derived_streams"],
            )
            self.assertIn("function_enter", by_family["blueprint"]["derived_relations"])
            self.assertIn("function_return", by_family["blueprint"]["derived_relations"])
            self.assertIn(
                "blueprint_interprocedural_function_data_routes.jsonl",
                by_family["blueprint"]["derived_streams"],
            )
            self.assertIn("function_argument_data", by_family["blueprint"]["derived_relations"])
            self.assertIn("function_return_data", by_family["blueprint"]["derived_relations"])
            self.assertTrue(all(row["runtime_state_captured"] is False for row in manifest["families"]))

    def test_focused_systems_corpus_does_not_claim_absent_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root, "manifest.json", {
                "schema_version": 0,
                "derived_schema_version": 22,
                "partial_corpus": True,
                "canonical_passes": ["systems"],
            })
            write_json(root, "systems_manifest.json", {
                "schema_version": 6,
                "success": True,
                "files": ["gas_abilities.jsonl"],
            })
            write_json(root, "systems_schema6_acceptance.json", {
                "systems_schema_version": 6,
                "project": "E:/UE/Lyra/Lyra.uproject",
            })

            manifest = capabilities.build_manifest(root)
            by_family = {row["family"]: row for row in manifest["families"]}
            self.assertTrue(manifest["corpus"]["partial"])
            self.assertEqual(manifest["corpus"]["canonical_passes"], ["systems"])
            self.assertEqual(by_family["gas"]["corpus_coverage"], "first_class")
            self.assertTrue(by_family["gas"]["acceptance"]["accepted"])
            self.assertEqual(by_family["gas"]["acceptance"]["corpus_provenance"], "Lyra.uproject")
            self.assertEqual(by_family["blueprint"]["corpus_coverage"], "external_or_excluded")
            self.assertFalse(by_family["world"]["available_in_corpus"])

    def test_write_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root, "manifest.json", {"schema_version": 12, "derived_schema_version": 22, "files": []})
            first = capabilities.write_manifest(root).read_bytes()
            second = capabilities.write_manifest(root).read_bytes()
            self.assertEqual(first, second)

    def test_deferred_policy_wraps_public_derive_and_bundle_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            write_json(root, "manifest.json", {"schema_version": 12, "derived_schema_version": 22, "files": []})
            calls = []

            def derive(output):
                calls.append(Path(output))
                return {"ok": 1}

            public = types.SimpleNamespace(__file__=str(SCRIPTS / "uatool.py"), derive_output=derive)
            core = types.SimpleNamespace(derive_output=derive, DEFAULT_BUNDLE_FILES=("manifest.json",))
            self.assertTrue(capabilities.apply_public_policy(modules=[public], core_module=core))
            self.assertIs(public.derive_output, core.derive_output)
            self.assertEqual(public.derive_output(root), {"ok": 1})
            self.assertEqual(calls, [root])
            self.assertTrue((root / "capabilities.json").is_file())
            self.assertIn("capabilities.json", core.DEFAULT_BUNDLE_FILES)


if __name__ == "__main__":
    unittest.main()
