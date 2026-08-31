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

import uatool_blueprint_enum_edges as enum_edges


class BlueprintEnumEdgeTest(unittest.TestCase):
    def test_execution_edge_keeps_raw_name_and_adds_readable_enum_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            entry = {
                "enum_path": "/Game/Data/E_RotationMode.E_RotationMode",
                "enum_index": 1,
                "numeric_value": 1,
                "raw_name": "NewEnumerator1",
                "authored_name": "Strafe",
                "display_name": "Strafe",
                "tooltip": "",
                "hidden": False,
                "is_max": False,
            }
            (output / "blueprint_enum_entries.jsonl").write_text(
                json.dumps(entry) + "\n",
                encoding="utf-8",
            )
            pins = [
                {
                    "node_id": "switch-node",
                    "name": "Selection",
                    "type": {
                        "subcategory_object": "/Game/Data/E_RotationMode.E_RotationMode"
                    },
                }
            ]
            core = types.SimpleNamespace(iter_blueprint_pin_rows=lambda _: iter(pins))
            rows = [
                {
                    "source_node_id": "switch-node",
                    "source_pin_name": "NewEnumerator1",
                    "target_block_id": "block-b",
                }
            ]

            result = enum_edges._decorate_execution_edges(output, rows, core)
            edge = result[0]
            self.assertEqual(edge["source_pin_name"], "NewEnumerator1")
            self.assertEqual(
                edge["source_pin_enum_path"],
                "/Game/Data/E_RotationMode.E_RotationMode",
            )
            self.assertEqual(edge["source_pin_enum_index"], 1)
            self.assertEqual(edge["source_pin_enum_value"], 1)
            self.assertEqual(edge["source_pin_authored_name"], "Strafe")
            self.assertEqual(edge["source_pin_display_name"], "Strafe")

    def test_ambiguous_enum_types_do_not_guess(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            entries = [
                {
                    "enum_path": "/Game/Data/E_A.E_A",
                    "enum_index": 0,
                    "numeric_value": 0,
                    "raw_name": "NewEnumerator0",
                    "authored_name": "A",
                    "display_name": "A",
                },
                {
                    "enum_path": "/Game/Data/E_B.E_B",
                    "enum_index": 0,
                    "numeric_value": 0,
                    "raw_name": "NewEnumerator0",
                    "authored_name": "B",
                    "display_name": "B",
                },
            ]
            with (output / "blueprint_enum_entries.jsonl").open("w", encoding="utf-8") as handle:
                for row in entries:
                    handle.write(json.dumps(row) + "\n")
            pins = [
                {"node_id": "switch", "type": {"subcategory_object": "/Game/Data/E_A.E_A"}},
                {"node_id": "switch", "type": {"subcategory_object": "/Game/Data/E_B.E_B"}},
            ]
            core = types.SimpleNamespace(iter_blueprint_pin_rows=lambda _: iter(pins))
            rows = [{"source_node_id": "switch", "source_pin_name": "NewEnumerator0"}]

            edge = enum_edges._decorate_execution_edges(output, rows, core)[0]
            self.assertEqual(edge, rows[0])
            self.assertNotIn("source_pin_display_name", edge)

    def test_program_report_uses_display_name_but_retains_raw_name(self) -> None:
        report = {
            "outgoing": {
                "block-a": [
                    {
                        "source_pin_name": "NewEnumerator2",
                        "source_pin_display_name": "Aim",
                        "target_block_id": "block-b",
                    }
                ]
            }
        }
        rendered = enum_edges._decorate_report(report)
        edge = rendered["outgoing"]["block-a"][0]
        self.assertEqual(edge["source_pin_name"], "Aim")
        self.assertEqual(edge["source_pin_raw_name"], "NewEnumerator2")


if __name__ == "__main__":
    unittest.main()
