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

import uatool_core as core


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8", newline="\n")


def write_jsonl(path: Path, count: int) -> None:
    path.write_text("{}\n" * count, encoding="utf-8", newline="\n")


class PostCompletionWorldExitRecoveryTest(unittest.TestCase):
    def _fixture(self, root: Path) -> None:
        write_json(root / "manifest.json", {
            "schema_version": 13,
        })
        counts = {
            "worlds": 2,
            "levels": 3,
            "streaming_relationships": 1,
            "actors": 4,
            "components": 5,
            "instance_overrides": 6,
            "references": 7,
            "data_layers": 1,
            "world_partition_worlds": 1,
            "world_partition_already_initialized": 0,
            "world_partition_initialized_for_scan": 1,
            "world_partition_initialize_unavailable": 0,
            "world_partition_initialize_failed": 0,
            "world_partition_actor_descs": 8,
        }
        files = list(core.WORLD_COMPLETION_COUNT_FILES)
        write_json(root / "world_manifest.json", {
            "schema_version": 12,
            "schema_name": "world",
            "pass": "UnrealAssetToolWorld",
            "structural_schema_baseline": 13,
            "counts": counts,
            "files": files,
        })
        for filename, count_name in core.WORLD_COMPLETION_COUNT_FILES.items():
            write_jsonl(root / filename, counts[count_name])
        write_json(root / "vfx_manifest.json", {
            "schema_version": 1,
            "success": True,
        })
        write_json(root / "systems_manifest.json", {
            "schema_version": 11,
            "success": True,
        })

    def test_completed_current_world_vfx_systems_outputs_allow_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            self.assertIsNone(core.world_pass_completion_error(root))

    def test_missing_world_manifest_rejects_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            (root / "world_manifest.json").unlink()
            self.assertIn(
                "current world manifest is missing",
                core.world_pass_completion_error(root) or "",
            )

    def test_world_row_count_mismatch_rejects_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            write_jsonl(root / "world_actors.jsonl", 3)
            error = core.world_pass_completion_error(root) or ""
            self.assertIn("world output count mismatch for world_actors.jsonl", error)
            self.assertIn("rows=3 manifest=4", error)

    def test_missing_vfx_manifest_rejects_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            (root / "vfx_manifest.json").unlink()
            self.assertIn(
                "current vfx_manifest.json is missing",
                core.world_pass_completion_error(root) or "",
            )

    def test_failed_systems_manifest_rejects_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            write_json(root / "systems_manifest.json", {
                "schema_version": 11,
                "success": False,
            })
            self.assertEqual(
                core.world_pass_completion_error(root),
                "current systems_manifest.json reports failure",
            )

    def test_stale_or_wrong_schema_manifests_reject_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._fixture(root)
            structural = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            structural["schema_version"] = 12
            write_json(root / "manifest.json", structural)
            self.assertIn(
                "not schema 13",
                core.world_pass_completion_error(root) or "",
            )


if __name__ == "__main__":
    unittest.main()
