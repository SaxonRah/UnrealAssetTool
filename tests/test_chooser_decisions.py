from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_chooser_decisions as decisions


class ChooserDecisionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.enum_path = "/Game/Cameras/E_Mode.E_Mode"
        self.entries = [
            {
                "enum_path": self.enum_path,
                "raw_name": "E_Mode::NewEnumerator0",
                "authored_name": "Freecam",
                "display_name": "Freecam",
            },
            {
                "enum_path": self.enum_path,
                "raw_name": "E_Mode::NewEnumerator1",
                "authored_name": "Strafe",
                "display_name": "Strafe",
            },
            {
                "enum_path": self.enum_path,
                "raw_name": "E_Mode::NewEnumerator3",
                "authored_name": "TwinStick",
                "display_name": "TwinStick",
            },
        ]

    def _column(self, row_values: str) -> str:
        return (
            "/Script/Chooser.EnumColumn("
            "InputValue=/Script/Chooser.EnumContextProperty(Binding=("
            f"Enum=\"/Script/Engine.UserDefinedEnum'{self.enum_path}'\","
            "PropertyBindingChain=(\"CameraMode_GUID\"),ContextIndex=0,"
            "IsBoundToRoot=False,DisplayName=\"CameraMode\")),"
            "DefaultRowValue=(ValueName=\"\",Comparison=MatchEqual,Value=0),"
            f"RowValues=({row_values}),bDisabled=False)"
        )

    def test_default_match_any_and_not_equal(self) -> None:
        raw = self._column(
            '(ValueName="E_Mode::NewEnumerator0"),'
            '(ValueName="E_Mode::NewEnumerator1",Comparison=MatchAny,Value=1),'
            '(ValueName="E_Mode::NewEnumerator3",Comparison=MatchNotEqual,Value=3)'
        )
        parsed = decisions.parse_enum_column(
            raw,
            column_index=2,
            result_count=3,
            enum_entries=self.entries,
        )
        self.assertIsNotNone(parsed)
        values = parsed["rows"]
        self.assertEqual(values[0]["comparison"], "MatchEqual")
        self.assertEqual(values[0]["text"], "CameraMode == Freecam")
        self.assertEqual(values[1]["comparison"], "MatchAny")
        self.assertEqual(values[1]["text"], "any")
        self.assertEqual(values[2]["text"], "CameraMode != TwinStick")
        self.assertTrue(all(row["decoded"] for row in values))

    def test_refuses_row_cardinality_mismatch(self) -> None:
        raw = self._column('(ValueName="E_Mode::NewEnumerator0")')
        self.assertIsNone(decisions.parse_enum_column(
            raw,
            column_index=0,
            result_count=2,
            enum_entries=self.entries,
        ))


if __name__ == "__main__":
    unittest.main()
