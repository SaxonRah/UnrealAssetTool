from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_animation as animation
import uatool_animation_curve_storage as curve_storage

curve_storage.install(animation)


def write_jsonl(path: Path, values: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


def legacy_key(
    asset: str,
    curve: str,
    index: int,
    time: float,
    value: float | None,
    *,
    component: str = "value",
    non_finite: str | None = None,
) -> dict:
    row = {
        "asset_path": asset,
        "curve_name": curve,
        "curve_type": "float",
        "component": component,
        "key_index": index,
        "time": time,
        "value": value,
        "interp_mode": 2,
        "tangent_mode": 1,
        "tangent_weight_mode": 0,
        "arrive_tangent": 0.0,
        "leave_tangent": 0.0,
        "arrive_tangent_weight": 0.0,
        "leave_tangent_weight": 0.0,
    }
    if non_finite is not None:
        row["value_non_finite"] = non_finite
    return row


class AnimationCurveStorageTest(unittest.TestCase):
    def test_columnar_blocks_round_trip_exact_logical_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "animation_curve_keys.jsonl"
            original = [
                legacy_key("/Game/A.A", "Speed", 0, 0.0, 1.0),
                legacy_key("/Game/A.A", "Speed", 1, 0.5, 2.0),
                legacy_key("/Game/A.A", "Speed", 2, 1.0, None, non_finite="nan"),
                legacy_key("/Game/A.A", "Turn", 4, 0.0, -1.0),
                legacy_key("/Game/A.A", "Turn", 6, 1.0, 1.0),
            ]
            write_jsonl(path, original)

            stats = curve_storage.compact(path)
            self.assertEqual(stats["logical_keys"], len(original))
            self.assertEqual(stats["blocks"], 2)
            self.assertTrue(stats["rewritten"])

            physical = list(rows(path))
            self.assertEqual(len(physical), 2)
            self.assertTrue(all(row["encoding"] == curve_storage.ENCODING for row in physical))
            self.assertEqual(physical[0]["columns"]["interp_mode"], 2)
            self.assertEqual(physical[1]["key_indices"], [4, 6])
            self.assertEqual(list(curve_storage.iter_logical_keys(path)), original)
            self.assertIsNone(
                curve_storage.validation_error(
                    path, expected_logical_keys=len(original), expected_blocks=2
                )
            )

            before = path.read_bytes()
            second = curve_storage.compact(path)
            self.assertFalse(second["rewritten"])
            self.assertEqual(path.read_bytes(), before)

    def test_schema2_upgrade_and_sqlite_load_preserve_logical_key_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            original = [
                legacy_key("/Game/A.A", "Speed", 0, 0.0, 1.0),
                legacy_key("/Game/A.A", "Speed", 1, 1.0, 2.0),
            ]
            write_jsonl(output / "animation_curve_keys.jsonl", original)

            (output / "animation_manifest.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "success": True,
                    "error": "",
                    "files": ["animation_curve_keys.jsonl"],
                    "counts": {},
                }, indent=2) + "\n",
                encoding="utf-8",
            )
            (output / "animation_deep_manifest.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "success": True,
                    "error": "",
                    "files": ["animation_curve_keys.jsonl"],
                    "counts": {"animation_curve_keys": len(original)},
                }, indent=2) + "\n",
                encoding="utf-8",
            )
            for filename in animation.DEEP_RAW_FILES:
                if filename not in {"animation_deep_manifest.json", "animation_curve_keys.jsonl"}:
                    (output / filename).write_text("", encoding="utf-8")

            animation.prepare_output(output, rows)
            manifest = json.loads((output / "animation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["curve_key_encoding"], curve_storage.ENCODING)
            self.assertEqual(manifest["counts"]["animation_curve_keys"], len(original))
            self.assertEqual(manifest["counts"]["animation_curve_key_blocks"], 1)
            self.assertIsNone(animation.validation_error(output))

            conn = sqlite3.connect(":memory:")
            try:
                animation.create_schema(conn)
                animation.load_database(conn, output, rows)
                loaded = conn.execute(
                    "SELECT key_index,time,value,interp_mode,tangent_mode,tangent_weight_mode "
                    "FROM animation_curve_keys ORDER BY key_index"
                ).fetchall()
                self.assertEqual(len(loaded), len(original))
                self.assertEqual(loaded[0], (0, 0.0, 1.0, 2, 1, 0))
                self.assertEqual(loaded[1], (1, 1.0, 2.0, 2, 1, 0))
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
