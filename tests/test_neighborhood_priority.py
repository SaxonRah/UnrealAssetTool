from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_project_neighborhoods as neighborhoods


class NeighborhoodPriorityTest(unittest.TestCase):
    def test_strong_edges_precede_package_plumbing(self) -> None:
        root = "/Game/Test/A.A"
        nodes = [
            {"path": root, "node_kind": "blueprint", "coverage": "first_class", "root": True},
            {"path": "/Game/Test/B.B", "node_kind": "asset", "coverage": "first_class", "root": False},
            {"path": "/Game/Test/C.C", "node_kind": "asset", "coverage": "first_class", "root": False},
            {"path": "/Game/Test/A", "node_kind": "package", "coverage": "generic_only", "root": False},
            {"path": "/Game/Test/P1", "node_kind": "package", "coverage": "generic_only", "root": False},
        ]
        edges = [
            {
                "edge_id": "generic",
                "source_kind": "package", "source": "/Game/Test/A",
                "relation": "depends_on_package",
                "target_kind": "package", "target": "/Game/Test/P1",
                "source_coverage": "generic_only", "target_coverage": "generic_only",
                "edge_quality": "generic_package_dependency", "evidence_count": 1,
                "evidence": [{"stream": "asset_dependencies.jsonl"}],
            },
            {
                "edge_id": "membership",
                "source_kind": "blueprint", "source": root,
                "relation": "member_of_package",
                "target_kind": "package", "target": "/Game/Test/A",
                "source_coverage": "first_class", "target_coverage": "generic_only",
                "edge_quality": "exact_semantic", "evidence_count": 1,
                "evidence": [{"stream": "assets.jsonl"}],
            },
            {
                "edge_id": "reference",
                "source_kind": "blueprint", "source": root,
                "relation": "references_object",
                "target_kind": "asset", "target": "/Game/Test/B.B",
                "source_coverage": "first_class", "target_coverage": "first_class",
                "edge_quality": "exact_reference", "evidence_count": 1,
                "evidence": [{"stream": "blueprint_relations.jsonl"}],
            },
            {
                "edge_id": "semantic",
                "source_kind": "blueprint", "source": root,
                "relation": "uses_asset",
                "target_kind": "asset", "target": "/Game/Test/C.C",
                "source_coverage": "first_class", "target_coverage": "first_class",
                "edge_quality": "exact_semantic", "evidence_count": 1,
                "evidence": [{"stream": "test"}],
            },
        ]

        result = neighborhoods.rebuild(
            nodes,
            edges,
            quality_rank={
                "generic_package_dependency": 0,
                "unique_dependency_resolution": 1,
                "exact_reference": 2,
                "exact_semantic": 3,
            },
            coverage_rank={"generic_only": 1, "first_class": 4},
            max_depth=3,
            max_edges=2,
            max_chars=131072,
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(
            [hop["edge_id"] for hop in result[0]["hops"]],
            ["semantic", "reference"],
        )


if __name__ == "__main__":
    unittest.main()
