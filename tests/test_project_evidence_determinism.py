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

import uatool_project_graph as project_graph


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


def canonical(values: list[dict]) -> str:
    return "\n".join(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for value in values
    )


class ProjectEvidenceDeterminismTests(unittest.TestCase):
    def _corpus(
        self,
        root: Path,
        *,
        blueprint_node_id: str,
        blueprint_relation_id: str,
        meta_node_a: str,
        meta_node_b: str,
        from_vertex: str,
        to_vertex: str,
    ) -> None:
        bp = "/Game/Test/BP.BP"
        meta = "/Game/Audio/MS.MS"

        write_jsonl(root / "assets.jsonl", [
            {
                "object_path": bp,
                "package_name": "/Game/Test/BP",
                "class_path": "/Script/Engine.Blueprint",
            },
            {
                "object_path": meta,
                "package_name": "/Game/Audio/MS",
                "class_path": "/Script/MetasoundEngine.MetaSoundSource",
            },
        ])
        write_jsonl(root / "asset_dependencies.jsonl", [])
        write_jsonl(root / "blueprints.jsonl", [
            {
                "object_path": bp,
                "generated_class": bp + "_C",
                "class": "/Script/Engine.Blueprint",
            },
        ])
        write_jsonl(root / "blueprint_nodes.jsonl", [
            {
                "node_id": blueprint_node_id,
                "blueprint_path": bp,
                "graph_id": bp + "::graph::Calc",
                "graph_name": "Calc",
                "node_class": "/Script/BlueprintGraph.K2Node_CallFunction",
                "operation": "function_call",
                "symbol": "/Script/Engine.KismetMathLibrary:FTrunc",
                "owner": "/Script/Engine.KismetMathLibrary",
                "title": "Truncate",
                "x": 320,
                "y": 128,
            },
        ])
        write_jsonl(root / "blueprint_relations.jsonl", [
            {
                "relation_id": blueprint_relation_id,
                "blueprint_path": bp,
                "graph_id": bp + "::graph::Calc",
                "source_kind": "node",
                "source_id": blueprint_node_id,
                "relation": "calls_function",
                "target_kind": "function",
                "target": "/Script/Engine.KismetMathLibrary:FTrunc",
                "owner": "/Script/Engine.KismetMathLibrary",
                "detail": {},
            },
        ])
        write_jsonl(root / "systems_assets.jsonl", [
            {
                "systems_path": meta,
                "systems_kind": "metasound_source",
                "class_path": "/Script/MetasoundEngine.MetaSoundSource",
                "package_name": "/Game/Audio/MS",
            },
        ])
        write_jsonl(root / "metasound_nodes.jsonl", [
            {
                "asset_path": meta,
                "node_index": 0,
                "property_path": "RootGraph.Nodes[0]",
                "struct_type": "/Script/MetasoundFrontend.MetaSoundFrontendNode",
                "node_id": meta_node_a,
            },
            {
                "asset_path": meta,
                "node_index": 1,
                "property_path": "RootGraph.Nodes[1]",
                "struct_type": "/Script/MetasoundFrontend.MetaSoundFrontendNode",
                "node_id": meta_node_b,
            },
        ])
        write_jsonl(root / "metasound_edges.jsonl", [
            {
                "asset_path": meta,
                "edge_index": 0,
                "property_path": "RootGraph.Edges[0]",
                "struct_type": "/Script/MetasoundFrontend.MetaSoundFrontendEdge",
                "from_node_id": meta_node_a,
                "from_vertex_id": from_vertex,
                "to_node_id": meta_node_b,
                "to_vertex_id": to_vertex,
            },
        ])

    def test_capture_local_guids_do_not_change_project_edge_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            a = base / "a"
            b = base / "b"
            a.mkdir()
            b.mkdir()

            self._corpus(
                a,
                blueprint_node_id="/Game/Test/BP.BP::graph::Calc::node::aaaaaaaa",
                blueprint_relation_id="rel:aaaaaaaa",
                meta_node_a="AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
                meta_node_b="BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
                from_vertex="CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC",
                to_vertex="DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDD",
            )
            self._corpus(
                b,
                blueprint_node_id="/Game/Test/BP.BP::graph::Calc::node::11111111",
                blueprint_relation_id="rel:11111111",
                meta_node_a="11111111111111111111111111111111",
                meta_node_b="22222222222222222222222222222222",
                from_vertex="33333333333333333333333333333333",
                to_vertex="44444444444444444444444444444444",
            )

            _, edges_a, _ = project_graph.derive(a, rows)
            _, edges_b, _ = project_graph.derive(b, rows)

            self.assertEqual(canonical(edges_a), canonical(edges_b))

            blueprint_edges = [
                edge for edge in edges_a
                if edge.get("source") == "/Game/Test/BP.BP"
                and edge.get("relation") == "calls_function"
            ]
            self.assertEqual(len(blueprint_edges), 1)
            bp_evidence = blueprint_edges[0]["evidence"][0]
            self.assertNotIn("relation_id", bp_evidence)
            self.assertNotIn("source_id", bp_evidence)
            self.assertEqual(bp_evidence["source_locator"]["operation"], "function_call")
            self.assertEqual(bp_evidence["source_locator"]["x"], 320)
            self.assertEqual(bp_evidence["source_locator"]["y"], 128)

            metasound_evidence = [
                evidence
                for edge in edges_a
                for evidence in edge.get("evidence", [])
                if evidence.get("stream") in {"metasound_nodes.jsonl", "metasound_edges.jsonl"}
            ]
            self.assertTrue(metasound_evidence)
            for evidence in metasound_evidence:
                self.assertNotIn("node_id", evidence)
                self.assertNotIn("from_vertex_id", evidence)
                self.assertNotIn("to_vertex_id", evidence)


if __name__ == "__main__":
    unittest.main()
