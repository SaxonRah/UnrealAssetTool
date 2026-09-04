from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_beta_rc as beta_rc
import uatool_capabilities as capabilities
import uatool_version as version


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8", newline="\n")


def write_jsonl(path: Path, count: int) -> None:
    path.write_text("{}\n" * count, encoding="utf-8", newline="\n")


class BetaReleaseCandidateTest(unittest.TestCase):
    def _current_cropout_fixture(self, root: Path) -> None:
        write_json(root / "manifest.json", {
            "schema_version": version.CURRENT_SCHEMAS["structural"],
            "derived_schema_version": version.CURRENT_SCHEMAS["derived"],
        })
        schemas = {
            key: value
            for key, value in version.CURRENT_SCHEMAS.items()
            if key != "capabilities"
        }
        families = []
        for name in (
            "blueprint",
            "world",
            "project_graph",
            "static_mesh",
            "world_geometry",
            "motion_warping",
        ):
            families.append({
                "family": name,
                "contract_coverage": "first_class",
                "corpus_coverage": "first_class",
                "available_in_corpus": True,
                "runtime_state_captured": False,
            })
        write_json(root / capabilities.CAPABILITIES_FILE, {
            "capability_schema_version": version.CURRENT_SCHEMAS["capabilities"],
            "tool": {
                "version": version.RELEASE_VERSION,
                "release_line": version.RELEASE_VERSION,
                "validated_engine": version.VALIDATED_ENGINE,
            },
            "coverage_levels": list(capabilities.COVERAGE_LEVELS),
            "schemas": schemas,
            "families": families,
        })
        for name in (
            "blueprint_nodes.jsonl",
            "blueprint_semantic_nodes.jsonl",
            "world_actors.jsonl",
            "project_edges.jsonl",
        ):
            write_jsonl(root / name, 1)

    def test_cropout_profile_accepts_current_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)
            record = beta_rc.check_corpus(
                root,
                "cropout",
                repo_root=ROOT,
            )
            self.assertTrue(record["accepted"])
            self.assertEqual(record["release_version"], version.RELEASE_VERSION)
            self.assertEqual(record["profile"], "cropout")
            self.assertEqual(record["schemas"], version.CURRENT_SCHEMAS)
            self.assertEqual(record["failures"], [])
            self.assertTrue(all(value == 1 for value in record["metrics"].values()))
            self.assertEqual(len(record["git_commit"]), 40)

    def test_schema_regression_fails_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)
            manifest = json.loads((root / capabilities.CAPABILITIES_FILE).read_text(encoding="utf-8"))
            manifest["schemas"]["derived"] = version.CURRENT_SCHEMAS["derived"] - 1
            write_json(root / capabilities.CAPABILITIES_FILE, manifest)

            record = beta_rc.check_corpus(root, "cropout", repo_root=ROOT)
            self.assertFalse(record["accepted"])
            self.assertTrue(
                any(failure.startswith("schema:derived:") for failure in record["failures"])
            )

    def test_absent_optional_companion_schema_is_allowed_when_family_is_explicitly_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)
            manifest = json.loads((root / capabilities.CAPABILITIES_FILE).read_text(encoding="utf-8"))
            manifest["schemas"]["world_geometry"] = 0
            for row in manifest["families"]:
                if row["family"] == "world_geometry":
                    row["available_in_corpus"] = False
                    row["corpus_coverage"] = "external_or_excluded"
            write_json(root / capabilities.CAPABILITIES_FILE, manifest)

            record = beta_rc.check_corpus(root, "cropout", repo_root=ROOT)
            self.assertTrue(record["accepted"])
            self.assertEqual(record["schemas"]["world_geometry"], 0)
            self.assertEqual(record["failures"], [])

    def test_absent_optional_companion_schema_fails_when_family_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)
            manifest = json.loads((root / capabilities.CAPABILITIES_FILE).read_text(encoding="utf-8"))
            manifest["schemas"]["world_geometry"] = 0
            write_json(root / capabilities.CAPABILITIES_FILE, manifest)

            record = beta_rc.check_corpus(root, "cropout", repo_root=ROOT)
            self.assertFalse(record["accepted"])
            self.assertTrue(
                any(failure.startswith("schema:world_geometry:") for failure in record["failures"])
            )

    def test_nonzero_optional_companion_mismatch_fails_when_family_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)
            manifest = json.loads((root / capabilities.CAPABILITIES_FILE).read_text(encoding="utf-8"))
            manifest["schemas"]["world_geometry"] = version.CURRENT_SCHEMAS["world_geometry"] + 1
            for row in manifest["families"]:
                if row["family"] == "world_geometry":
                    row["available_in_corpus"] = False
                    row["corpus_coverage"] = "external_or_excluded"
            write_json(root / capabilities.CAPABILITIES_FILE, manifest)

            record = beta_rc.check_corpus(root, "cropout", repo_root=ROOT)
            self.assertFalse(record["accepted"])
            self.assertTrue(
                any(failure.startswith("schema:world_geometry:") for failure in record["failures"])
            )


    def test_animation_schema3_is_allowed_only_when_motion_warping_is_explicitly_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)
            manifest = json.loads((root / capabilities.CAPABILITIES_FILE).read_text(encoding="utf-8"))
            manifest["schemas"]["animation"] = 3
            for row in manifest["families"]:
                if row["family"] == "motion_warping":
                    row["available_in_corpus"] = False
                    row["corpus_coverage"] = "external_or_excluded"
            write_json(root / capabilities.CAPABILITIES_FILE, manifest)

            record = beta_rc.check_corpus(root, "cropout", repo_root=ROOT)
            self.assertTrue(record["accepted"])
            self.assertEqual(record["schemas"]["animation"], 3)
            self.assertEqual(record["failures"], [])

    def test_animation_schema3_fails_when_motion_warping_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)
            manifest = json.loads((root / capabilities.CAPABILITIES_FILE).read_text(encoding="utf-8"))
            manifest["schemas"]["animation"] = 3
            write_json(root / capabilities.CAPABILITIES_FILE, manifest)

            record = beta_rc.check_corpus(root, "cropout", repo_root=ROOT)
            self.assertFalse(record["accepted"])
            self.assertTrue(
                any(failure.startswith("schema:animation:") for failure in record["failures"])
            )

    def test_animation_schema4_fails_when_motion_warping_is_explicitly_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)
            manifest = json.loads((root / capabilities.CAPABILITIES_FILE).read_text(encoding="utf-8"))
            for row in manifest["families"]:
                if row["family"] == "motion_warping":
                    row["available_in_corpus"] = False
                    row["corpus_coverage"] = "external_or_excluded"
            write_json(root / capabilities.CAPABILITIES_FILE, manifest)

            record = beta_rc.check_corpus(root, "cropout", repo_root=ROOT)
            self.assertFalse(record["accepted"])
            self.assertTrue(
                any(failure.startswith("schema:animation:") for failure in record["failures"])
            )

    def test_stale_animation_schema2_fails_when_motion_warping_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)
            manifest = json.loads((root / capabilities.CAPABILITIES_FILE).read_text(encoding="utf-8"))
            manifest["schemas"]["animation"] = 2
            for row in manifest["families"]:
                if row["family"] == "motion_warping":
                    row["available_in_corpus"] = False
                    row["corpus_coverage"] = "external_or_excluded"
            write_json(root / capabilities.CAPABILITIES_FILE, manifest)

            record = beta_rc.check_corpus(root, "cropout", repo_root=ROOT)
            self.assertFalse(record["accepted"])
            self.assertTrue(
                any(failure.startswith("schema:animation:") for failure in record["failures"])
            )

    def test_contentexamples_accepts_schema3_without_motion_warping_and_manager_tag_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)

            manifest = json.loads((root / capabilities.CAPABILITIES_FILE).read_text(encoding="utf-8"))
            manifest["schemas"]["animation"] = 3
            for row in manifest["families"]:
                if row["family"] == "motion_warping":
                    row["available_in_corpus"] = False
                    row["corpus_coverage"] = "external_or_excluded"

            existing = {row["family"] for row in manifest["families"]}
            for name, coverage in (
                ("sequencer", "first_class_depth_pending"),
                ("audio", "first_class_depth_pending"),
                ("materials", "first_class"),
                ("vfx", "first_class"),
                ("gameplay_data", "first_class"),
                ("gameplay_tags", "first_class"),
            ):
                if name not in existing:
                    manifest["families"].append({
                        "family": name,
                        "contract_coverage": coverage,
                        "corpus_coverage": coverage,
                        "available_in_corpus": True,
                        "runtime_state_captured": False,
                    })
            write_json(root / capabilities.CAPABILITIES_FILE, manifest)

            for name in (
                "level_sequences.jsonl",
                "audio_assets.jsonl",
                "material_expressions.jsonl",
                "vfx_assets.jsonl",
                "data_table_rows.jsonl",
                "gameplay_tag_settings.jsonl",
            ):
                write_jsonl(root / name, 1)
            write_jsonl(root / "gameplay_tags.jsonl", 0)

            record = beta_rc.check_corpus(root, "contentexamples", repo_root=ROOT)
            self.assertTrue(record["accepted"])
            self.assertEqual(record["schemas"]["animation"], 3)
            self.assertEqual(record["metrics"]["gameplay_tag_settings"], 1)
            self.assertNotIn("gameplay_tags", record["metrics"])
            self.assertEqual(record["failures"], [])

    def test_missing_profile_family_fails_record(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._current_cropout_fixture(root)
            manifest = json.loads((root / capabilities.CAPABILITIES_FILE).read_text(encoding="utf-8"))
            manifest["families"] = [
                row for row in manifest["families"]
                if row["family"] != "world"
            ]
            write_json(root / capabilities.CAPABILITIES_FILE, manifest)

            record = beta_rc.check_corpus(root, "cropout", repo_root=ROOT)
            self.assertFalse(record["accepted"])
            self.assertTrue(
                any(failure.startswith("family:world:") for failure in record["failures"])
            )

    def test_profile_aliases_are_stable(self) -> None:
        self.assertEqual(beta_rc.normalize_profile("Game-Animation-Sample"), "gasp")
        self.assertEqual(beta_rc.normalize_profile("ContentExamples"), "contentexamples")
        self.assertEqual(beta_rc.normalize_profile("City-Sample"), "citysample")
        with self.assertRaises(ValueError):
            beta_rc.normalize_profile("unknown")


if __name__ == "__main__":
    unittest.main()
