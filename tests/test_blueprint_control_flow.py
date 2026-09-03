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
            (branch, "B0", "B1", "then", "then", "Target1", "execute"),
            (branch, "B0", "B2", "else", "else", "Target2", "execute"),
            (switch, "B3", "B4", "NewEnumerator2", "Aim", "Target4", "execute"),
            (switch, "B3", "B5", "Default", "Default", "Target5", "execute"),
            (sequence, "B6", "B7", "then_0", "then_0", "Target7", "execute"),
            (call, "B8", "B9", "then", "then", "Target9", "execute"),
        ]
        block_ids = sorted({item for edge in edges for item in (edge[1], edge[2])})
        write_jsonl(self.output / "blueprint_execution_blocks.jsonl", [
            {
                "block_id": block_id,
                "blueprint_path": self.bp,
                "graph_id": self.graph,
                "graph_name": "Test",
            }
            for block_id in block_ids
        ])
        # Deliberately omit graph_name here. Real GASP block-edge rows expose
        # this shape; control-flow derivation must recover the name from blocks.
        write_jsonl(self.output / "blueprint_execution_block_edges.jsonl", [
            {
                "blueprint_path": self.bp,
                "graph_id": self.graph,
                "source_block_id": source_block,
                "target_block_id": target_block,
                "source_node_id": node,
                "target_node_id": target_node,
                "source_pin_name": raw_pin,
                "source_pin_display_name": display_pin,
                "target_pin_name": target_pin,
            }
            for node, source_block, target_block, raw_pin, display_pin, target_node, target_pin in edges
        ])

    def test_derives_branch_switch_sequence_and_flow(self) -> None:
        self._write_fixture()
        values = control_flow.derive(self.output, rows)
        self.assertEqual(len(values), 6)
        self.assertEqual({value["graph_name"] for value in values}, {"Test"})
        self.assertEqual({value["schema_version"] for value in values}, {2})

        by_kind: dict[str, list[dict]] = {}
        for value in values:
            by_kind.setdefault(value["control_kind"], []).append(value)

        self.assertEqual(len(by_kind["branch"]), 2)
        branch = sorted(by_kind["branch"], key=lambda row: row["source_pin_name"])
        self.assertEqual(branch[0]["source_pin_name"], "else")
        self.assertFalse(branch[0]["condition_polarity"])
        self.assertEqual(branch[0]["condition_text"], "PlayerInputState.WantsToSprint")
        self.assertEqual(branch[0]["target_node_id"], "Target2")
        self.assertEqual(branch[0]["target_pin_name"], "execute")
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

    def test_preserves_distinct_target_exec_pins_when_paths_share_target_block(self) -> None:
        self._write_fixture()
        branch = self.graph + "::node::branch"
        gate = self.graph + "::node::gate"
        write_jsonl(self.output / "blueprint_execution_blocks.jsonl", [
            {"block_id": "B0", "blueprint_path": self.bp, "graph_id": self.graph, "graph_name": "Test"},
            {"block_id": "B1", "blueprint_path": self.bp, "graph_id": self.graph, "graph_name": "Test"},
        ])
        write_jsonl(self.output / "blueprint_execution_block_edges.jsonl", [
            {
                "blueprint_path": self.bp,
                "graph_id": self.graph,
                "source_block_id": "B0",
                "target_block_id": "B1",
                "source_node_id": branch,
                "target_node_id": gate,
                "source_pin_name": "then",
                "target_pin_name": "Open",
            },
            {
                "blueprint_path": self.bp,
                "graph_id": self.graph,
                "source_block_id": "B0",
                "target_block_id": "B1",
                "source_node_id": branch,
                "target_node_id": gate,
                "source_pin_name": "else",
                "target_pin_name": "Close",
            },
        ])
        values = control_flow.derive(self.output, rows)
        self.assertEqual(len(values), 2)
        by_polarity = {bool(row["condition_polarity"]): row for row in values}
        self.assertEqual(by_polarity[True]["target_pin_name"], "Open")
        self.assertEqual(by_polarity[False]["target_pin_name"], "Close")
        self.assertNotEqual(by_polarity[True]["control_edge_id"], by_polarity[False]["control_edge_id"])
        write_jsonl(self.output / "blueprint_control_edges.jsonl", values)
        self.assertIsNone(control_flow.validation_error(self.output, rows))

    def test_validation_rejects_dropped_target_pin_identity(self) -> None:
        self._write_fixture()
        values = control_flow.derive(self.output, rows)
        values[0]["target_pin_name"] = ""
        write_jsonl(self.output / "blueprint_control_edges.jsonl", values)
        self.assertIn("complete execution-block endpoint set", str(control_flow.validation_error(self.output, rows)))

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
                "SELECT graph_name,case_raw_name,case_name,selector_text,target_node_id,target_pin_name "
                "FROM blueprint_control_edges WHERE control_kind='switch_case'"
            ).fetchone()
            self.assertEqual(row, ("Test", "NewEnumerator2", "Aim", "RotationMode", "Target4", "execute"))
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
