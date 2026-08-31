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

import uatool_project_neighborhood_compact as storage


def write_jsonl(path: Path, values: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def sample_edges() -> list[dict]:
    return [
        {"edge_id": "pedge:aaaaaaaaaaaaaaaaaaaaaaaa"},
        {"edge_id": "pedge:bbbbbbbbbbbbbbbbbbbbbbbb"},
        {"edge_id": "pedge:cccccccccccccccccccccccc"},
    ]


def sample_neighborhood() -> dict:
    return {
        "root_path": "/Game/Test.Root",
        "root_kind": "blueprint",
        "root_coverage": "first_class",
        "max_depth": 3,
        "edge_count": 3,
        "node_count": 4,
        "truncated": False,
        "hops": [
            {"depth": 1, "direction": "out", "edge_id": "pedge:bbbbbbbbbbbbbbbbbbbbbbbb"},
            {"depth": 2, "direction": "in", "edge_id": "pedge:aaaaaaaaaaaaaaaaaaaaaaaa"},
            {"depth": 3, "direction": "out", "edge_id": "pedge:cccccccccccccccccccccccc"},
        ],
    }


class ProjectNeighborhoodOrdinalStorageTest(unittest.TestCase):
    def test_round_trip_exact_logical_neighborhood(self) -> None:
        edges = sample_edges()
        logical = sample_neighborhood()
        compacted = storage.compact_ordinals([logical], edges)
        self.assertEqual(len(compacted), 1)
        row = compacted[0]
        self.assertEqual(row["encoding"], storage.ENCODING)
        self.assertEqual(row["depth_ends"], [1, 2, 3])
        self.assertEqual(row["hop_edges"], [2, -1, 3])
        self.assertEqual(storage.expand(row, [edge["edge_id"] for edge in edges]), logical)

    def test_public_compact_helper_remains_schema15_compatible(self) -> None:
        logical = sample_neighborhood()
        expanded = dict(logical)
        expanded["text"] = "redundant"
        expanded["hops"] = [
            {
                **hop,
                "source": "ignored",
                "relation": "ignored",
                "evidence": [{"kind": "ignored"}],
            }
            for hop in logical["hops"]
        ]
        compacted = storage.compact([expanded])[0]
        self.assertNotIn("text", compacted)
        self.assertEqual(compacted, logical)

    def test_validation_records_independent_storage_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            edges = sample_edges()
            compacted = storage.compact_ordinals([sample_neighborhood()], edges)
            write_jsonl(output / "project_edges.jsonl", edges)
            write_jsonl(output / "project_neighborhoods.jsonl", compacted)
            (output / "manifest.json").write_text(
                json.dumps({"derived_schema_version": 15}, indent=2) + "\n",
                encoding="utf-8",
            )

            self.assertIsNone(storage.validation_error(output, rows))
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["derived_schema_version"], 15)
            self.assertEqual(
                manifest["project_neighborhood_storage_schema_version"],
                storage.STORAGE_SCHEMA_VERSION,
            )
            self.assertEqual(manifest["project_neighborhood_encoding"], storage.ENCODING)

    def test_refuses_unknown_duplicate_and_nonmonotonic_hops(self) -> None:
        edges = sample_edges()

        unknown = sample_neighborhood()
        unknown["hops"] = list(unknown["hops"])
        unknown["hops"][0] = {
            "depth": 1,
            "direction": "out",
            "edge_id": "pedge:dddddddddddddddddddddddd",
        }
        with self.assertRaises(RuntimeError):
            storage.compact_ordinals([unknown], edges)

        duplicate = sample_neighborhood()
        duplicate["hops"] = [
            {"depth": 1, "direction": "out", "edge_id": edges[0]["edge_id"]},
            {"depth": 2, "direction": "in", "edge_id": edges[0]["edge_id"]},
        ]
        duplicate["edge_count"] = 2
        with self.assertRaises(RuntimeError):
            storage.compact_ordinals([duplicate], edges)

        nonmonotonic = sample_neighborhood()
        nonmonotonic["hops"] = [
            {"depth": 2, "direction": "out", "edge_id": edges[0]["edge_id"]},
            {"depth": 1, "direction": "out", "edge_id": edges[1]["edge_id"]},
        ]
        nonmonotonic["edge_count"] = 2
        with self.assertRaises(RuntimeError):
            storage.compact_ordinals([nonmonotonic], edges)

    def test_sqlite_rowid_is_the_storage_ordinal(self) -> None:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute(
                "CREATE TABLE project_edges("
                "edge_id TEXT PRIMARY KEY,source_kind TEXT,source TEXT,relation TEXT,"
                "target_kind TEXT,target TEXT,source_coverage TEXT,target_coverage TEXT,"
                "edge_quality TEXT,evidence_count INTEGER,evidence_json TEXT)"
            )
            for edge_id, source in (
                ("pedge:aaaaaaaaaaaaaaaaaaaaaaaa", "A"),
                ("pedge:bbbbbbbbbbbbbbbbbbbbbbbb", "B"),
                ("pedge:cccccccccccccccccccccccc", "C"),
            ):
                conn.execute(
                    "INSERT INTO project_edges VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (edge_id, "object", source, "uses", "object", "Target", "first_class",
                     "first_class", "exact_semantic", 1, "[]"),
                )
            found = storage._edge_map_for_ordinals(conn, [1, 3])
            self.assertEqual(found[1]["edge_id"], "pedge:aaaaaaaaaaaaaaaaaaaaaaaa")
            self.assertEqual(found[3]["edge_id"], "pedge:cccccccccccccccccccccccc")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
