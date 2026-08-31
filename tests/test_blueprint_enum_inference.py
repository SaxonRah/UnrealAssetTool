from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_blueprint_enums as enums
import uatool_blueprint_enum_inference as inference


class BlueprintEnumInferenceTest(unittest.TestCase):
    def test_comparison_literal_uses_connected_enum_type(self) -> None:
        enum_path = "/Game/Data/E_RotationMode.E_RotationMode"
        lookup = {
            (enum_path, "NewEnumerator1"): {
                "display_name": "Strafe",
                "authored_name": "Strafe",
            }
        }
        pins_by_node = {
            "compare": {
                "A": {"type": {"subcategory_object": ""}},
                "B": {"type": {"subcategory_object": ""}},
            },
            "break": {
                "RotationMode": {"type": {"subcategory_object": enum_path}},
            },
        }
        expression = {
            "kind": "expression",
            "node_id": "compare",
            "operation": "enum_equal",
            "label": "Equal (Enum)",
            "output_pin": "ReturnValue",
            "inputs": [
                {
                    "pin": "A",
                    "sources": [
                        {
                            "kind": "expression",
                            "node_id": "break",
                            "operation": "break_struct",
                            "label": "Break S_MoverCustomInputs",
                            "output_pin": "RotationMode",
                            "inputs": [],
                        }
                    ],
                },
                {"pin": "B", "literal": "NewEnumerator1"},
            ],
        }

        text = inference.render_expression(
            expression,
            lookup,
            pins_by_node,
            enums._render_expression,
        )
        self.assertIn("B=Strafe", text)
        self.assertEqual(expression["inputs"][1]["literal"], "NewEnumerator1")

    def test_ambiguous_connected_enum_types_preserve_raw_literal(self) -> None:
        enum_a = "/Game/Data/E_A.E_A"
        enum_b = "/Game/Data/E_B.E_B"
        lookup = {
            (enum_a, "NewEnumerator0"): {
                "display_name": "Alpha",
                "authored_name": "Alpha",
            },
            (enum_b, "NewEnumerator0"): {
                "display_name": "Beta",
                "authored_name": "Beta",
            },
        }
        pins_by_node = {
            "compare": {
                "A": {"type": {"subcategory_object": ""}},
                "B": {"type": {"subcategory_object": ""}},
                "C": {"type": {"subcategory_object": ""}},
            },
            "source-a": {
                "Value": {"type": {"subcategory_object": enum_a}},
            },
            "source-b": {
                "Value": {"type": {"subcategory_object": enum_b}},
            },
        }
        expression = {
            "kind": "expression",
            "node_id": "compare",
            "operation": "enum_equal",
            "label": "Equal (Enum)",
            "output_pin": "ReturnValue",
            "inputs": [
                {
                    "pin": "A",
                    "sources": [
                        {
                            "kind": "expression",
                            "node_id": "source-a",
                            "operation": "variable_get",
                            "label": "A",
                            "output_pin": "Value",
                            "inputs": [],
                        }
                    ],
                },
                {
                    "pin": "C",
                    "sources": [
                        {
                            "kind": "expression",
                            "node_id": "source-b",
                            "operation": "variable_get",
                            "label": "C",
                            "output_pin": "Value",
                            "inputs": [],
                        }
                    ],
                },
                {"pin": "B", "literal": "NewEnumerator0"},
            ],
        }

        text = inference.render_expression(
            expression,
            lookup,
            pins_by_node,
            enums._render_expression,
        )
        self.assertIn("B=NewEnumerator0", text)
        self.assertNotIn("B=Alpha", text)
        self.assertNotIn("B=Beta", text)


if __name__ == "__main__":
    unittest.main()
