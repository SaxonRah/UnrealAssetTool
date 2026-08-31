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


class GameplayDataSystemsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_fixture(self) -> None:
        rows: dict[str, list[dict]] = {name: [] for name in systems.JSONL_FILES}
        data_table = "/Game/Data/DT_Items.DT_Items"
        curve_table = "/Game/Data/CT_Damage.CT_Damage"
        primary = "/Game/Data/DA_Item.DA_Item"

        rows["systems_assets.jsonl"] = [
            {"systems_path": data_table, "systems_kind": "data_table", "family": "gameplay", "class_path": "/Script/Engine.DataTable", "package_name": "/Game/Data/DT_Items"},
            {"systems_path": curve_table, "systems_kind": "curve_table", "family": "gameplay", "class_path": "/Script/Engine.CurveTable", "package_name": "/Game/Data/CT_Damage"},
            {"systems_path": primary, "systems_kind": "primary_data_asset", "family": "gameplay", "class_path": "/Script/Test.ItemDefinition", "package_name": "/Game/Data/DA_Item"},
        ]
        rows["gameplay_data_assets.jsonl"] = [{
            "asset_path": data_table, "gameplay_kind": "data_table", "class_path": "/Script/Engine.DataTable",
            "package_name": "/Game/Data/DT_Items", "row_struct": "/Script/Test.ItemRow", "row_count": 1,
            "primary_asset_rules": "",
        }]
        rows["data_table_rows.jsonl"] = [{
            "table_path": data_table, "table_kind": "data_table", "row_index": 0, "row_name": "Potion",
            "row_path": data_table + "::row[Potion]", "row_struct": "/Script/Test.ItemRow",
            "field_count": 2, "declared_field_count": 2, "truncated": False,
        }]
        rows["data_table_fields.jsonl"] = [
            {"table_path": data_table, "row_index": 0, "row_name": "Potion", "row_path": data_table + "::row[Potion]", "field_index": 0,
             "field_name": "Power", "declaring_type": "/Script/Test.ItemRow", "property_type": "FloatProperty", "cpp_type": "float", "value": "50.000000", "truncated": False},
            {"table_path": data_table, "row_index": 0, "row_name": "Potion", "row_path": data_table + "::row[Potion]", "field_index": 1,
             "field_name": "Icon", "declaring_type": "/Script/Test.ItemRow", "property_type": "ObjectProperty", "cpp_type": "UTexture2D*", "value": "/Game/UI/T_Potion.T_Potion", "truncated": False},
        ]
        rows["systems_references.jsonl"] = [{
            "asset_path": data_table, "owner_path": data_table + "::row[Potion]", "owner_kind": "data_table_row",
            "root_property": "Icon", "property_path": "Icon", "reference_kind": "hard_object",
            "target_path": "/Game/UI/T_Potion.T_Potion", "target_class": "/Script/Engine.Texture2D",
        }]
        rows["curve_tables.jsonl"] = [{
            "table_path": curve_table, "table_kind": "curve_table", "class_path": "/Script/Engine.CurveTable",
            "package_name": "/Game/Data/CT_Damage", "curve_mode": "rich", "row_count": 1,
        }]
        rows["curve_table_rows.jsonl"] = [{
            "table_path": curve_table, "row_index": 0, "row_name": "Damage", "row_path": curve_table + "::curve[Damage]",
            "curve_mode": "rich", "key_count": 2, "default_value": 0.0, "pre_infinity_extrap": 0,
            "post_infinity_extrap": 0, "simple_interp_mode": -1,
        }]
        rows["curve_table_keys.jsonl"] = [
            {"table_path": curve_table, "row_index": 0, "row_name": "Damage", "row_path": curve_table + "::curve[Damage]", "key_index": 0,
             "curve_mode": "rich", "time": 0.0, "value": 10.0, "interp_mode": 1, "tangent_mode": 0, "tangent_weight_mode": 0,
             "arrive_tangent": 0.0, "leave_tangent": 0.0, "arrive_tangent_weight": 0.0, "leave_tangent_weight": 0.0},
            {"table_path": curve_table, "row_index": 0, "row_name": "Damage", "row_path": curve_table + "::curve[Damage]", "key_index": 1,
             "curve_mode": "rich", "time": 1.0, "value": 20.0, "interp_mode": 1, "tangent_mode": 0, "tangent_weight_mode": 0,
             "arrive_tangent": 0.0, "leave_tangent": 0.0, "arrive_tangent_weight": 0.0, "leave_tangent_weight": 0.0},
        ]
        rows["primary_data_assets.jsonl"] = [{
            "asset_path": primary, "asset_kind": "primary_data_asset", "class_path": "/Script/Test.ItemDefinition",
            "package_name": "/Game/Data/DA_Item", "primary_asset_id_valid": True,
            "primary_asset_type": "Item", "primary_asset_name": "DA_Item", "primary_asset_id": "Item:DA_Item",
        }]
        rows["gameplay_tag_settings.jsonl"] = [{
            "settings_path": "/Script/GameplayTags.Default__GameplayTagsSettings", "class_path": "/Script/GameplayTags.GameplayTagsSettings",
            "config_file_name": "DefaultGameplayTags.ini", "import_tags_from_config": "True", "warn_on_invalid_tags": "True",
            "fast_replication": "False", "invalid_tag_characters": "\"'", "gameplay_tag_table_list": "()",
            "restricted_config_files": "()", "num_bits_for_container_size": 6, "net_index_first_bit_segment": 16,
        }]
        rows["gameplay_tag_sources.jsonl"] = [{
            "source_index": 0, "source_name": "DefaultGameplayTags.ini", "source_type": "default_tag_list",
            "config_file": "DefaultGameplayTags.ini", "source_tag_list_path": "/Script/GameplayTags.Default__GameplayTagsSettings",
            "source_restricted_tag_list_path": "", "tag_count": 2, "owners": [],
        }]
        rows["gameplay_tag_dictionary.jsonl"] = [
            {"tag_index": 0, "tag": "Item", "parent_tag": "", "comment": "", "explicit": True, "restricted": False,
             "allow_non_restricted_children": False, "depth": 1, "sources": ["DefaultGameplayTags.ini"]},
            {"tag_index": 1, "tag": "Item.Consumable", "parent_tag": "Item", "comment": "Potion family", "explicit": True,
             "restricted": False, "allow_non_restricted_children": False, "depth": 2, "sources": ["DefaultGameplayTags.ini"]},
        ]
        rows["gameplay_tag_redirects.jsonl"] = [{
            "redirect_index": 0, "source_name": "DefaultGameplayTags.ini", "old_tag": "Item.Potion", "new_tag": "Item.Consumable",
        }]

        for filename, file_rows in rows.items():
            write_jsonl(self.output / filename, file_rows)
        counts = {name.removesuffix(".jsonl"): len(file_rows) for name, file_rows in rows.items()}
        (self.output / "systems_manifest.json").write_text(json.dumps({
            "schema_version": systems.SYSTEMS_SCHEMA_VERSION,
            "pass": "UnrealAssetToolSystems",
            "success": True,
            "error": "",
            "files": list(systems.JSONL_FILES),
            "counts": counts,
        }, indent=2) + "\n", encoding="utf-8")

    def test_schema2_validation_and_sqlite(self) -> None:
        self._write_fixture()
        self.assertIsNone(systems.validation_error(self.output))
        conn = sqlite3.connect(":memory:")
        try:
            systems.create_schema(conn)
            systems.load_database(conn, self.output, read_rows)
            self.assertEqual(conn.execute("SELECT count(*) FROM data_table_rows").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT count(*) FROM data_table_fields").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT count(*) FROM curve_table_keys").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT primary_asset_id FROM primary_data_assets").fetchone()[0], "Item:DA_Item")
            self.assertEqual(conn.execute("SELECT count(*) FROM gameplay_tag_dictionary").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT new_tag FROM gameplay_tag_redirects").fetchone()[0], "Item.Consumable")
        finally:
            conn.close()

    def test_schema2_rejects_broken_field_and_source_invariants(self) -> None:
        self._write_fixture()
        rows = list(read_rows(self.output / "data_table_rows.jsonl"))
        rows[0]["field_count"] = 99
        write_jsonl(self.output / "data_table_rows.jsonl", rows)
        self.assertIn("data table field_count mismatch", str(systems.validation_error(self.output)))

        self._write_fixture()
        dictionary = list(read_rows(self.output / "gameplay_tag_dictionary.jsonl"))
        dictionary[1]["sources"] = ["Missing.ini"]
        write_jsonl(self.output / "gameplay_tag_dictionary.jsonl", dictionary)
        self.assertIn("unknown sources", str(systems.validation_error(self.output)))


if __name__ == "__main__":
    unittest.main()
