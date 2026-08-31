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
import uatool_animation_property_storage as property_storage

curve_storage.install(animation)
property_storage.install(animation)


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


def prop(owner: str, name: str, value: str, *, kind: str = "asset") -> dict:
    return {
        "asset_path": "/Game/A.A",
        "owner_path": owner,
        "owner_kind": kind,
        "owner_class": "/Script/Engine.AnimSequence",
        "declaring_type": "/Script/Engine.AnimationAsset",
        "property_name": name,
        "property_type": "StrProperty",
        "cpp_type": "FString",
        "value": value,
        "truncated": False,
    }


class AnimationPropertyStorageTest(unittest.TestCase):
    def test_owner_blocks_round_trip_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "animation_properties.jsonl"
            original = [
                prop("/Game/A.A", "A", "one"),
                prop("/Game/A.A", "B", "two"),
                prop("/Game/A.A:Sub", "C", "three", kind="subobject"),
            ]
            write_jsonl(path, original)

            stats = property_storage.compact(path)
            self.assertEqual(stats["logical_properties"], 3)
            self.assertEqual(stats["blocks"], 2)
            self.assertTrue(stats["rewritten"])
            self.assertEqual(list(property_storage.iter_logical_properties(path)), original)

            physical = list(rows(path))
            self.assertEqual(len(physical), 2)
            self.assertEqual(physical[0]["encoding"], property_storage.ENCODING)
            self.assertEqual(physical[0]["property_count"], 2)
            self.assertEqual(physical[0]["columns"]["declaring_type"], "/Script/Engine.AnimationAsset")

            before = path.read_bytes()
            again = property_storage.compact(path)
            self.assertFalse(again["rewritten"])
            self.assertEqual(path.read_bytes(), before)

    def test_manifest_count_gate_rejects_partial_legacy_stream(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            write_jsonl(output / "animation_properties.jsonl", [prop("/Game/A.A", "A", "one")])
            (output / "animation_manifest.json").write_text(
                json.dumps({"schema_version": 2, "counts": {"animation_properties": 2}}) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "count changed"):
                property_storage.normalize_output(output)

    def test_schema2_manifest_and_sqlite_load_preserve_logical_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            original = [
                prop("/Game/A.A", "A", "one"),
                prop("/Game/A.A", "B", "two"),
            ]
            write_jsonl(output / "animation_properties.jsonl", original)
            (output / "animation_curve_keys.jsonl").write_text("", encoding="utf-8")
            (output / "animation_manifest.json").write_text(
                json.dumps({
                    "schema_version": 2,
                    "success": True,
                    "error": "",
                    "files": ["animation_properties.jsonl", "animation_curve_keys.jsonl"],
                    "counts": {
                        "animation_properties": len(original),
                        "animation_curve_keys": 0,
                        "animation_curve_key_blocks": 0,
                    },
                    "curve_key_encoding": curve_storage.ENCODING,
                    "curve_key_logical_count": 0,
                    "curve_key_block_count": 0,
                }, indent=2) + "\n",
                encoding="utf-8",
            )
            (output / "animation_deep_manifest.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "success": True,
                    "error": "",
                    "files": [],
                    "counts": {"animation_curve_keys": 0},
                }, indent=2) + "\n",
                encoding="utf-8",
            )

            stats = property_storage.normalize_output(output)
            self.assertTrue(stats["rewritten"])
            self.assertEqual(stats["logical_properties"], len(original))
            self.assertEqual(stats["blocks"], 1)
            manifest = json.loads((output / "animation_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["animation_property_encoding"], property_storage.ENCODING)
            self.assertEqual(manifest["counts"]["animation_properties"], len(original))
            self.assertEqual(manifest["counts"]["animation_property_blocks"], 1)
            self.assertIsNone(property_storage.manifest_validation_error(output))

            conn = sqlite3.connect(":memory:")
            try:
                animation.create_schema(conn)
                animation.load_database(conn, output, rows)
                loaded = conn.execute(
                    "SELECT owner_path,property_name,value,truncated "
                    "FROM animation_properties ORDER BY property_name"
                ).fetchall()
                self.assertEqual(loaded, [
                    ("/Game/A.A", "A", "one", 0),
                    ("/Game/A.A", "B", "two", 0),
                ])
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
