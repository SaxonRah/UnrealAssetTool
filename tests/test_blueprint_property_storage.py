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

import uatool_blueprint_property_storage as storage


def write_jsonl(path: Path, values: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def raw_rows(path: Path):
    path = Path(path)
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


def node(node_id: str, blueprint: str, graph: str, node_class: str) -> dict:
    return {
        "node_id": node_id,
        "blueprint_path": blueprint,
        "graph_name": graph,
        "node_class": node_class,
    }


def prop(
    node_id: str,
    blueprint: str,
    graph: str,
    node_class: str,
    name: str,
    value: str,
    *,
    declaring_type: str | None = None,
) -> dict:
    return {
        "node_id": node_id,
        "blueprint_path": blueprint,
        "graph_name": graph,
        "node_class": node_class,
        "property_name": name,
        "property_path": name,
        "owner_class": node_class,
        "declaring_type": declaring_type or node_class,
        "depth": 0,
        "property_type": "StrProperty",
        "cpp_type": "FString",
        "value": value,
        "object_path": "",
        "object_class": "",
        "property_flags": 1,
        "truncated": False,
    }


class BlueprintPropertyStorageTest(unittest.TestCase):
    def test_blocks_round_trip_manifest_and_installed_readers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            nodes = [
                node("node:A", "/Game/BP_A.BP_A", "GraphA", "/Script/Test.NodeA"),
                node("node:B", "/Game/BP_B.BP_B", "GraphB", "/Script/Test.NodeB"),
            ]
            original = [
                prop("node:A", "/Game/BP_A.BP_A", "GraphA", "/Script/Test.NodeA", "One", "1"),
                prop("node:A", "/Game/BP_A.BP_A", "GraphA", "/Script/Test.NodeA", "Two", "2"),
                prop("node:B", "/Game/BP_B.BP_B", "GraphB", "/Script/Test.NodeB", "Three", "3"),
            ]
            write_jsonl(output / storage.NODE_FILE, nodes)
            write_jsonl(output / storage.PROPERTY_FILE, original)
            (output / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 12,
                        "counts": {"blueprint_node_properties": len(original)},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

            stats = storage.normalize_output(output)
            self.assertEqual(stats["logical_properties"], 3)
            self.assertEqual(stats["blocks"], 2)
            self.assertTrue(stats["rewritten"])

            physical = list(raw_rows(output / storage.PROPERTY_FILE))
            self.assertEqual(len(physical), 2)
            self.assertEqual(physical[0]["encoding"], storage.ENCODING)
            self.assertEqual(physical[0]["property_count"], 2)
            self.assertNotIn("blueprint_path", physical[0])
            self.assertNotIn("graph_name", physical[0])
            self.assertNotIn("node_class", physical[0])
            self.assertEqual(list(storage.iter_logical_properties(output)), original)
            self.assertIsNone(storage.manifest_validation_error(output))

            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema_version"], 12)
            self.assertEqual(
                manifest["structural_storage_schema_version"], storage.STORAGE_SCHEMA_VERSION
            )
            self.assertEqual(manifest["blueprint_node_property_encoding"], storage.ENCODING)
            self.assertEqual(manifest["counts"]["blueprint_node_properties"], 3)
            self.assertEqual(manifest["counts"]["blueprint_node_property_blocks"], 2)

            before = (output / storage.PROPERTY_FILE).read_bytes()
            second = storage.normalize_output(output)
            self.assertFalse(second["rewritten"])
            self.assertEqual((output / storage.PROPERTY_FILE).read_bytes(), before)

            core = types.SimpleNamespace(iter_jsonl=raw_rows)
            runtime = types.SimpleNamespace(_rows=raw_rows)
            storage.install(core, runtime)
            self.assertEqual(list(core.iter_jsonl(output / storage.PROPERTY_FILE)), original)
            self.assertEqual(list(runtime._rows(output / storage.PROPERTY_FILE)), original)

            other = output / "other.jsonl"
            other_rows = [{"x": 1}, {"x": 2}]
            write_jsonl(other, other_rows)
            self.assertEqual(list(core.iter_jsonl(other)), other_rows)
            self.assertEqual(list(runtime._rows(other)), other_rows)

    def test_authoritative_node_mismatch_refuses_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            write_jsonl(
                output / storage.NODE_FILE,
                [node("node:A", "/Game/BP_A.BP_A", "GraphA", "/Script/Test.NodeA")],
            )
            values = [
                prop(
                    "node:A",
                    "/Game/BP_A.BP_A",
                    "WrongGraph",
                    "/Script/Test.NodeA",
                    "One",
                    "1",
                )
            ]
            path = output / storage.PROPERTY_FILE
            write_jsonl(path, values)
            before = path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "metadata differs"):
                storage.compact(output, expected_logical=1)
            self.assertEqual(path.read_bytes(), before)

    def test_manifest_count_mismatch_refuses_without_rewrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            write_jsonl(
                output / storage.NODE_FILE,
                [node("node:A", "/Game/BP_A.BP_A", "GraphA", "/Script/Test.NodeA")],
            )
            values = [
                prop("node:A", "/Game/BP_A.BP_A", "GraphA", "/Script/Test.NodeA", "One", "1")
            ]
            path = output / storage.PROPERTY_FILE
            write_jsonl(path, values)
            before = path.read_bytes()
            with self.assertRaisesRegex(RuntimeError, "manifest=2 actual=1"):
                storage.compact(output, expected_logical=2)
            self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
