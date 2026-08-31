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

import uatool_blueprint_control_flow as control_flow


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class BlueprintControlFlowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)
        self.bp = "/Game/BP_Test.BP_Test"
        self.graph = self.bp + "::graph::Test"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        branch = self.graph + "::node::branch"
        switch = self.graph + "::node::switch"
        sequence = self.graph + "::node::sequence"
        call = self.graph + "::node::call"
        write_jsonl(self.output / "blueprint_nodes.jsonl", [
            {"node_id": branch, "node_class": "/Script/BlueprintGraph.K2Node_IfThenElse"},
            {"node_id": switch, "node_class": "/Script/BlueprintGraph.K2Node_SwitchEnum"},
            {"node_id": sequence, "node_class": "/Script/BlueprintGraph.K2Node_ExecutionSequence"},
            {"node_id": call, "node_class": "/Script/BlueprintGraph.K2Node_CallFunction"},
        ])
        write_jsonl(self.output / "blueprint_data_dependencies.jsonl", [
            {
                "dependency_id": "dep-condition",
                "sink_node_id": branch,
                "sink_operation": "branch",
                "sink_pin_name": "Condition",
                "text": "PlayerInputState.WantsToSprint",
            },
            {
                "dependency_id": "dep-selector",
                "sink_node_id": switch,
                "sink_operation": "switch",
                "sink_pin_name": "Selection",
                "text": "RotationMode",
            },
        ])
        edges = [
            (branch, "B0", "B1", "then", "then"),
            (branch, "B0", "B2", "else", "else"),
            (switch, "B3", "B4", "NewEnumerator2", "Aim"),
            (switch, "B3", "B5", "Default", "Default"),
            (sequence, "B6", "B7", "then_0", "then_0"),
            (call, "B8", "B9", "then", "then"),
        ]
        write_jsonl(self.output / "blueprint_execution_block_edges.jsonl", [
            {
                "blueprint_path": self.bp,
                "graph_id": self.graph,
                "graph_name": "Test",
                "source_block_id": source_block,
                "target_block_id": target_block,
                "source_node_id": node,
                "source_pin_name": raw_pin,
                "source_pin_display_name": display_pin,
            }
            for node, source_block, target_block, raw_pin, display_pin in edges
        ])

    def test_derives_branch_switch_sequence_and_flow(self) -> None:
        self._write_fixture()
        values = control_flow.derive(self.output, rows)
        self.assertEqual(len(values), 6)

        by_kind: dict[str, list[dict]] = {}
        for value in values:
            by_kind.setdefault(value["control_kind"], []).append(value)

        self.assertEqual(len(by_kind["branch"]), 2)
        branch = sorted(by_kind["branch"], key=lambda row: row["source_pin_name"])
        self.assertEqual(branch[0]["source_pin_name"], "else")
        self.assertFalse(branch[0]["condition_polarity"])
        self.assertEqual(branch[0]["condition_text"], "PlayerInputState.WantsToSprint")
        self.assertTrue(branch[1]["condition_polarity"])

        case = by_kind["switch_case"][0]
        self.assertEqual(case["case_raw_name"], "NewEnumerator2")
        self.assertEqual(case["case_name"], "Aim")
        self.assertEqual(case["selector_text"], "RotationMode")
        self.assertEqual(by_kind["switch_default"][0]["case_name"], "Default")

        sequence = by_kind["sequence"][0]
        self.assertEqual(sequence["sequence_index"], 0)
        self.assertEqual(sequence["source_operation"], "execution_sequence")
        self.assertEqual(len(by_kind["flow"]), 1)

        write_jsonl(self.output / "blueprint_control_edges.jsonl", values)
        self.assertIsNone(control_flow.validation_error(self.output, rows))

    def test_sqlite_round_trip(self) -> None:
        self._write_fixture()
        values = control_flow.derive(self.output, rows)
        write_jsonl(self.output / "blueprint_control_edges.jsonl", values)
        conn = sqlite3.connect(":memory:")
        try:
            control_flow.create_schema(conn)
            control_flow.load_database(conn, self.output, rows)
            self.assertEqual(conn.execute("SELECT count(*) FROM blueprint_control_edges").fetchone()[0], 6)
            row = conn.execute(
                "SELECT case_raw_name,case_name,selector_text FROM blueprint_control_edges WHERE control_kind='switch_case'"
            ).fetchone()
            self.assertEqual(row, ("NewEnumerator2", "Aim", "RotationMode"))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
