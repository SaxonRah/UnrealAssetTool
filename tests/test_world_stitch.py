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

import uatool_world_stitch as world_stitch


def write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class WorldStitchRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_exact_world_reference_and_unique_package_resolution(self) -> None:
        world = "/Game/Maps/Test.Test"
        actor = "/Game/Maps/Test.Test:PersistentLevel.BP_Enemy_C_0"
        blueprint = "/Game/BP/BP_Enemy.BP_Enemy"
        behavior_tree = "/Game/AI/BT_Enemy.BT_Enemy"

        write_jsonl(self.output / "blueprints.jsonl", [{
            "object_path": blueprint,
            "generated_class": "/Game/BP/BP_Enemy.BP_Enemy_C",
            "class": "/Script/Engine.Blueprint",
        }])
        write_jsonl(self.output / "behavior_trees.jsonl", [{
            "behavior_tree_path": behavior_tree,
            "class_path": "/Script/AIModule.BehaviorTree",
        }])
        write_jsonl(self.output / "world_references.jsonl", [{
            "world_path": world,
            "actor_path": actor,
            "owner_kind": "actor",
            "owner_path": actor,
            "property_path": "BehaviorTree",
            "reference_kind": "hard",
            "authored_override": True,
            "target_path": behavior_tree,
        }])
        write_jsonl(self.output / "world_actors.jsonl", [{
            "world_path": world,
            "actor_path": actor,
            "blueprint_asset": blueprint,
            "generated_class": "/Game/BP/BP_Enemy.BP_Enemy_C",
        }])
        write_jsonl(self.output / "asset_dependencies.jsonl", [{
            "source_package": "/Game/BP/BP_Enemy",
            "target_package": "/Game/AI/BT_Enemy",
            "category": "hard",
        }])

        relations = world_stitch.derive(self.output, read_rows)
        matches = [
            row for row in relations
            if row["source_id"] == actor
            and row["relation"] == "references_behavior_tree"
            and row["target"] == behavior_tree
        ]
        self.assertEqual(len(matches), 1)
        evidence_kinds = {item["kind"] for item in matches[0]["evidence"]}
        self.assertEqual(evidence_kinds, {"world_reference", "blueprint_asset_dependency"})
        self.assertEqual(matches[0]["evidence_count"], 2)

    def test_ambiguous_package_dependency_is_not_promoted(self) -> None:
        world = "/Game/Maps/Test.Test"
        actor = "/Game/Maps/Test.Test:PersistentLevel.BP_Enemy_C_0"
        blueprint = "/Game/BP/BP_Enemy.BP_Enemy"

        write_jsonl(self.output / "blueprints.jsonl", [{
            "object_path": blueprint,
            "generated_class": "/Game/BP/BP_Enemy.BP_Enemy_C",
            "class": "/Script/Engine.Blueprint",
        }])
        # Two specialist entities deliberately share one synthetic package. The
        # dependency may not be guessed into either semantic target.
        write_jsonl(self.output / "behavior_trees.jsonl", [{
            "behavior_tree_path": "/Game/AI/Shared.Shared:BT",
            "class_path": "/Script/AIModule.BehaviorTree",
        }])
        write_jsonl(self.output / "blackboards.jsonl", [{
            "blackboard_path": "/Game/AI/Shared.Shared:BB",
            "class_path": "/Script/AIModule.BlackboardData",
        }])
        write_jsonl(self.output / "world_actors.jsonl", [{
            "world_path": world,
            "actor_path": actor,
            "blueprint_asset": blueprint,
        }])
        write_jsonl(self.output / "asset_dependencies.jsonl", [{
            "source_package": "/Game/BP/BP_Enemy",
            "target_package": "/Game/AI/Shared",
            "category": "hard",
        }])

        relations = world_stitch.derive(self.output, read_rows)
        promoted = [
            row for row in relations
            if any(item.get("kind") == "blueprint_asset_dependency" for item in row["evidence"])
        ]
        self.assertEqual(promoted, [])
        self.assertEqual(
            [row for row in relations if row["relation"] == "instantiates_blueprint"],
            [row for row in relations if row["target"] == blueprint],
        )


if __name__ == "__main__":
    unittest.main()
