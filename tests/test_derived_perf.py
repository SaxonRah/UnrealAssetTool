from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_derived_freshness as freshness
import uatool_project_neighborhood_compact as compact_schema
import uatool_project_neighborhoods as neighborhoods


class DerivedPerfTest(unittest.TestCase):
    def test_direct_compact_neighborhood_matches_expand_then_compact(self) -> None:
        nodes = [
            {
                "node_kind": "blueprint",
                "path": "/Game/A.A",
                "coverage": "first_class",
                "root": True,
            },
            {
                "node_kind": "niagara_system",
                "path": "/Game/B.B",
                "coverage": "first_class",
                "root": True,
            },
        ]
        edges = [
            {
                "edge_id": "pedge:1",
                "source_kind": "blueprint",
                "source": "/Game/A.A",
                "relation": "references_vfx_asset",
                "target_kind": "niagara_system",
                "target": "/Game/B.B",
                "source_coverage": "first_class",
                "target_coverage": "first_class",
                "edge_quality": "exact_reference",
                "evidence_count": 1,
                "evidence": [{"stream": "blueprint_relations.jsonl", "kind": "test"}],
            }
        ]
        kwargs = dict(
            quality_rank={"exact_reference": 3},
            coverage_rank={"first_class": 4},
            max_depth=3,
            max_edges=256,
            max_chars=131072,
        )
        expanded = neighborhoods.rebuild(nodes, edges, **kwargs)
        old_compact = compact_schema.compact(expanded)
        direct_compact = neighborhoods.rebuild(nodes, edges, compact=True, **kwargs)
        self.assertEqual(direct_compact, old_compact)

    def test_freshness_stamp_invalidates_on_raw_or_python_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "out"
            scripts = root / "scripts"
            output.mkdir()
            scripts.mkdir()

            raw = output / "assets.jsonl"
            derived = output / "project_nodes.jsonl"
            raw.write_text('{"asset":"A"}\n', encoding="utf-8")
            derived.write_text('{"node":"A"}\n', encoding="utf-8")
            (output / "manifest.json").write_text(
                json.dumps(
                    {
                        "derived_schema_version": 14,
                        "derived_counts": {"project_nodes": 1},
                    }
                ) + "\n",
                encoding="utf-8",
            )
            source = scripts / "uatool_example.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")

            freshness.mark_fresh(output, schema_version=14, script_dir=scripts)
            self.assertTrue(freshness.is_fresh(output, schema_version=14, script_dir=scripts))

            with raw.open("a", encoding="utf-8") as handle:
                handle.write('{"asset":"B"}\n')
            self.assertFalse(freshness.is_fresh(output, schema_version=14, script_dir=scripts))

            freshness.mark_fresh(output, schema_version=14, script_dir=scripts)
            self.assertTrue(freshness.is_fresh(output, schema_version=14, script_dir=scripts))

            source.write_text("VALUE = 2\n", encoding="utf-8")
            os.utime(source, None)
            self.assertFalse(freshness.is_fresh(output, schema_version=14, script_dir=scripts))


if __name__ == "__main__":
    unittest.main()
