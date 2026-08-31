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

import uatool_blueprint_pin_storage as storage


def write_jsonl(path: Path, values: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def plain_rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def node(node_id: str, blueprint: str = "/Game/BP.BP", graph_id: str = "graph:1", graph_name: str = "EventGraph") -> dict:
    return {
        "node_id": node_id,
        "blueprint_path": blueprint,
        "graph_id": graph_id,
        "graph_name": graph_name,
    }


def pin(node_id: str, suffix: str, index: int, name: str, *, linked_count: int = 0) -> dict:
    return {
        "pin_id": node_id + "::" + suffix,
        "node_id": node_id,
        "blueprint_path": "/Game/BP.BP",
        "graph_id": "graph:1",
        "graph_name": "EventGraph",
        "pin_index": index,
        "name": name,
        "direction": "output" if index % 2 == 0 else "input",
        "type": {
            "category": "exec" if index == 0 else "object",
            "subcategory": "None",
            "container_type": 0,
            "is_reference": False,
            "is_const": False,
            "subcategory_object": "",
        },
        "default_value": "",
        "default_object": "",
        "default_text": "",
        "hidden": False,
        "not_connectable": False,
        "linked_count": linked_count,
    }


class BlueprintPinStorageTest(unittest.TestCase):
    def test_blocks_round_trip_manifest_idempotency_and_installed_readers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            nodes = [node("node:1"), node("node:2")]
            original = [
                pin("node:1", "11111111-1111-1111-1111-111111111111", 0, "then", linked_count=1),
                pin("node:1", "22222222-2222-2222-2222-222222222222", 1, "Target"),
                pin("node:2", "33333333-3333-3333-3333-333333333333", 4, "Value"),
                pin("node:2", "44444444-4444-4444-4444-444444444444", 6, "Other"),
            ]
            write_jsonl(output / "blueprint_nodes.jsonl", nodes)
            write_jsonl(output / "blueprint_pins.jsonl", original)
            (output / "manifest.json").write_text(
                json.dumps({"counts": {"blueprint_pins": len(original)}}, indent=2) + "\n",
                encoding="utf-8",
            )

            stats = storage.normalize_output(output)
            self.assertTrue(stats["rewritten"])
            self.assertEqual(stats["logical_pins"], len(original))
            self.assertEqual(stats["blocks"], 2)
            physical = list(plain_rows(output / "blueprint_pins.jsonl"))
            self.assertEqual(len(physical), 2)
            self.assertEqual(physical[0]["encoding"], storage.ENCODING)
            self.assertNotIn("blueprint_path", physical[0])
            self.assertNotIn("graph_id", physical[0])
            self.assertNotIn("graph_name", physical[0])
            self.assertNotIn("pin_index_start", physical[0])
            self.assertEqual(physical[1]["pin_indices"], [4, 6])
            self.assertEqual(list(storage.iter_logical_pins(output)), original)

            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["blueprint_pin_storage_schema_version"], storage.STORAGE_SCHEMA_VERSION)
            self.assertEqual(manifest["blueprint_pin_encoding"], storage.ENCODING)
            self.assertEqual(manifest["counts"]["blueprint_pins"], len(original))
            self.assertEqual(manifest["counts"]["blueprint_pin_blocks"], 2)
            self.assertIsNone(storage.manifest_validation_error(output))

            before = (output / "blueprint_pins.jsonl").read_bytes()
            second = storage.normalize_output(output)
            self.assertFalse(second["rewritten"])
            self.assertEqual((output / "blueprint_pins.jsonl").read_bytes(), before)

            core = types.SimpleNamespace(iter_jsonl=plain_rows)
            runtime = types.SimpleNamespace(_rows=plain_rows)
            storage.install(core, runtime)
            self.assertEqual(list(core.iter_jsonl(output / "blueprint_pins.jsonl")), original)
            self.assertEqual(list(runtime._rows(output / "blueprint_pins.jsonl")), original)

    def test_authoritative_node_mismatch_refuses_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            write_jsonl(output / "blueprint_nodes.jsonl", [node("node:1")])
            value = pin("node:1", "11111111-1111-1111-1111-111111111111", 0, "then")
            value["graph_name"] = "WrongGraph"
            write_jsonl(output / "blueprint_pins.jsonl", [value])
            before = (output / "blueprint_pins.jsonl").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "metadata differs from authoritative node"):
                storage.compact(output, expected_logical=1)
            self.assertEqual((output / "blueprint_pins.jsonl").read_bytes(), before)

    def test_manifest_count_and_unreconstructible_id_refuse_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            write_jsonl(output / "blueprint_nodes.jsonl", [node("node:1")])
            value = pin("node:1", "11111111-1111-1111-1111-111111111111", 0, "then")
            write_jsonl(output / "blueprint_pins.jsonl", [value])
            before = (output / "blueprint_pins.jsonl").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "scanner manifest"):
                storage.compact(output, expected_logical=2)
            self.assertEqual((output / "blueprint_pins.jsonl").read_bytes(), before)

            value["pin_id"] = "not-derived-from-node"
            write_jsonl(output / "blueprint_pins.jsonl", [value])
            before = (output / "blueprint_pins.jsonl").read_bytes()
            with self.assertRaisesRegex(RuntimeError, "not reconstructible from node_id"):
                storage.compact(output, expected_logical=1)
            self.assertEqual((output / "blueprint_pins.jsonl").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
