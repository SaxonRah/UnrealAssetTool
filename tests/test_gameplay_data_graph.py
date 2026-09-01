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
import uatool_project_graph_finalize as project_graph_finalize
import uatool_systems as systems


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


class GameplayDataGraphTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _fixture(self) -> None:
        data_table = "/Game/Data/DT_Items.DT_Items"
        curve_table = "/Game/Data/CT_Damage.CT_Damage"
        primary = "/Game/Data/DA_Item.DA_Item"
        texture = "/Game/UI/T_Potion.T_Potion"
        row_path = data_table + "::row[Potion]"

        rows: dict[str, list[dict]] = {name: [] for name in systems.JSONL_FILES}
        rows["systems_assets.jsonl"] = [
            {"systems_path": data_table, "systems_kind": "data_table", "family": "gameplay", "class_path": "/Script/Engine.DataTable", "package_name": "/Game/Data/DT_Items"},
            {"systems_path": curve_table, "systems_kind": "curve_table", "family": "gameplay", "class_path": "/Script/Engine.CurveTable", "package_name": "/Game/Data/CT_Damage"},
            {"systems_path": primary, "systems_kind": "primary_data_asset", "family": "gameplay", "class_path": "/Script/Test.ItemDefinition", "package_name": "/Game/Data/DA_Item"},
        ]
        rows["data_table_rows.jsonl"] = [{
            "table_path": data_table,
            "table_kind": "data_table",
            "row_index": 0,
            "row_name": "Potion",
            "row_path": row_path,
            "row_struct": "/Script/Test.ItemRow",
            "field_count": 1,
            "declared_field_count": 1,
            "truncated": False,
        }]
        rows["systems_references.jsonl"] = [{
            "asset_path": data_table,
            "owner_path": row_path,
            "owner_kind": "data_table_row",
            "root_property": "Icon",
            "property_path": "Icon",
            "reference_kind": "hard_object",
            "target_path": texture,
            "target_class": "/Script/Engine.Texture2D",
        }]
        rows["curve_table_rows.jsonl"] = [{
            "table_path": curve_table,
            "row_index": 0,
            "row_name": "Damage",
            "row_path": curve_table + "::curve[Damage]",
            "curve_mode": "rich",
            "key_count": 2,
        }]
        rows["primary_data_assets.jsonl"] = [{
            "asset_path": primary,
            "asset_kind": "primary_data_asset",
            "class_path": "/Script/Test.ItemDefinition",
            "package_name": "/Game/Data/DA_Item",
            "primary_asset_id_valid": True,
            "primary_asset_type": "Item",
            "primary_asset_name": "DA_Item",
            "primary_asset_id": "Item:DA_Item",
        }]
        rows["gameplay_tag_settings.jsonl"] = [{
            "settings_path": "/Script/GameplayTags.Default__GameplayTagsSettings",
            "class_path": "/Script/GameplayTags.GameplayTagsSettings",
        }]
        rows["gameplay_tag_sources.jsonl"] = [{
            "source_index": 0,
            "source_name": "DefaultGameplayTags.ini",
            "source_type": "default_tag_list",
            "config_file": "DefaultGameplayTags.ini",
            "tag_count": 2,
            "owners": [],
        }]
        rows["gameplay_tag_dictionary.jsonl"] = [
            {"tag_index": 0, "tag": "Item", "parent_tag": "", "sources": ["DefaultGameplayTags.ini"]},
            {"tag_index": 1, "tag": "Item.Consumable", "parent_tag": "Item", "sources": ["DefaultGameplayTags.ini"]},
        ]
        rows["gameplay_tag_redirects.jsonl"] = [{
            "redirect_index": 0,
            "source_name": "DefaultGameplayTags.ini",
            "old_tag": "Item.Potion",
            "new_tag": "Item.Consumable",
        }]

        for filename, file_rows in rows.items():
            write_jsonl(self.output / filename, file_rows)

        write_jsonl(self.output / "assets.jsonl", [
            {"object_path": data_table, "class_path": "/Script/Engine.DataTable", "package_name": "/Game/Data/DT_Items"},
            {"object_path": curve_table, "class_path": "/Script/Engine.CurveTable", "package_name": "/Game/Data/CT_Damage"},
            {"object_path": primary, "class_path": "/Script/Test.ItemDefinition", "package_name": "/Game/Data/DA_Item"},
            {"object_path": texture, "class_path": "/Script/Engine.Texture2D", "package_name": "/Game/UI/T_Potion"},
        ])
        write_jsonl(self.output / "asset_dependencies.jsonl", [])

    def test_schema2_nodes_edges_coverage_and_reference_join(self) -> None:
        self._fixture()
        nodes, edges, _ = project_graph.derive(self.output, read_rows)
        nodes, edges, neighborhoods = project_graph_finalize.finalize(
            self.output, read_rows, nodes, edges
        )
        write_jsonl(self.output / "project_nodes.jsonl", nodes)
        write_jsonl(self.output / "project_edges.jsonl", edges)
        write_jsonl(self.output / "project_neighborhoods.jsonl", neighborhoods)

        self.assertIsNone(project_graph.validation_error(self.output, read_rows))
        self.assertIsNone(project_graph_finalize.validation_error(self.output, read_rows))

        node_by_key = {(node["node_kind"], node["path"]): node for node in nodes}
        self.assertEqual(
            node_by_key[("data_table", "/Game/Data/DT_Items.DT_Items")]["coverage"],
            "first_class",
        )
        self.assertEqual(
            node_by_key[("primary_data_asset", "/Game/Data/DA_Item.DA_Item")]["coverage"],
            "first_class_depth_pending",
        )
        self.assertEqual(
            node_by_key[("data_table_row", "/Game/Data/DT_Items.DT_Items::row[Potion]")]["coverage"],
            "first_class",
        )
        self.assertTrue(
            node_by_key[("gameplay_tag_settings", "/Script/GameplayTags.Default__GameplayTagsSettings")]["root"]
        )

        edge_by_relation = {}
        for edge in edges:
            edge_by_relation.setdefault(edge["relation"], []).append(edge)

        self.assertEqual(len(edge_by_relation["contains_data_table_row"]), 1)
        self.assertEqual(len(edge_by_relation["contains_curve_table_row"]), 1)
        self.assertEqual(len(edge_by_relation["declares_primary_asset_id"]), 1)
        self.assertEqual(len(edge_by_relation["defines_gameplay_tag_source"]), 1)
        self.assertEqual(len(edge_by_relation["declares_gameplay_tag"]), 2)
        self.assertEqual(len(edge_by_relation["parent_gameplay_tag"]), 1)
        self.assertEqual(len(edge_by_relation["contains_gameplay_tag_redirect"]), 1)
        self.assertEqual(len(edge_by_relation["redirects_from_gameplay_tag"]), 1)
        self.assertEqual(len(edge_by_relation["redirects_to_gameplay_tag"]), 1)

        row_reference = [
            edge for edge in edge_by_relation["references_object"]
            if edge["source"] == "/Game/Data/DT_Items.DT_Items::row[Potion]"
        ]
        self.assertEqual(len(row_reference), 1)
        self.assertEqual(row_reference[0]["edge_quality"], "exact_reference")
        self.assertEqual(row_reference[0]["source_coverage"], "first_class")
        self.assertEqual(row_reference[0]["target"], "/Game/UI/T_Potion.T_Potion")

        roots = [node["path"] for node in nodes if node.get("root")]
        self.assertEqual(len(roots), len(set(roots)))


if __name__ == "__main__":
    unittest.main()
