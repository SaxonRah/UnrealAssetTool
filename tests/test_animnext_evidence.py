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

import uatool_animnext_evidence as evidence


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if line:
                yield json.loads(line)


class AnimNextEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_current_ue58_uaf_assets_and_rigvm_overlap_are_diagnostic_only(self) -> None:
        graph = "/Game/Anim/UAF/AG_Locomotion.AG_Locomotion"
        system = "/Game/Anim/UAF/SYS_Player.SYS_Player"
        variables = "/Game/Anim/UAF/SV_Player.SV_Player"
        write_jsonl(self.output / "assets.jsonl", [
            {"object_path": graph, "class_path": "/Script/UAFAnimGraph.UAFAnimGraph"},
            {"object_path": system, "class_path": "/Script/UAF.UAFSystem"},
            {"object_path": variables, "class_path": "/Script/UAF.UAFSharedVariables"},
            {"object_path": "/Game/Anim/UAF/BM_Upper.BM_Upper", "class_path": "/Script/UAF.UAFBlendMask"},
        ])
        write_jsonl(self.output / "rigvm_objects.jsonl", [{
            "blueprint_path": graph,
            "object_id": graph + "#Node:1",
            "class_path": "/Script/RigVMDeveloper.RigVMUnitNode",
            "name": "EntryPoint",
        }])
        write_jsonl(self.output / "rigvm_pins.jsonl", [{
            "blueprint_path": graph,
            "node_id": graph + "#Node:1",
            "pin_path": "Result",
        }])
        write_jsonl(self.output / "rigvm_links.jsonl", [{
            "blueprint_path": graph,
            "source_pin": "Pose",
            "target_pin": "Result",
        }])
        write_jsonl(self.output / "rigvm_properties.jsonl", [{
            "blueprint_path": variables,
            "property_path": "SharedVariables[0].DefaultValue",
            "value": "0.5",
        }])
        write_jsonl(self.output / "rigvm_references.jsonl", [{
            "blueprint_path": graph,
            "property_path": "SharedVariables",
            "target_path": variables,
            "target_class": "/Script/UAF.UAFSharedVariables",
        }])
        write_jsonl(self.output / "world_components.jsonl", [{
            "component_path": "/Game/Maps/Test.Test:PersistentLevel.Player.UAFComponent0",
            "component_class": "/Script/UAF.UAFComponent",
        }])
        write_jsonl(self.output / "world_references.jsonl", [{
            "owner_path": "/Game/Maps/Test.Test:PersistentLevel.Player.UAFComponent0",
            "property_path": "System",
            "target_path": system,
            "target_class": "/Script/UAF.UAFSystem",
        }])
        write_jsonl(self.output / "systems_properties.jsonl", [{
            "owner_path": variables,
            "property_path": "VariableBinding",
            "value": "Speed",
        }])

        report = evidence.build_report(self.output, rows, include_source=False)
        self.assertTrue(report["diagnostic_only"])
        self.assertFalse(report["semantic_promotion"])
        self.assertFalse(report["schema_promotion"])
        self.assertFalse(report["runtime_state_captured"])
        proof = report["proof"]
        self.assertEqual(proof["unique_uaf_anim_graph_assets"], 1)
        self.assertEqual(proof["unique_uaf_system_assets"], 1)
        self.assertEqual(proof["unique_uaf_shared_variables_assets"], 1)
        self.assertEqual(proof["unique_uaf_blend_mask_assets"], 1)
        self.assertEqual(proof["unique_uaf_animnext_assets_total"], 4)
        self.assertEqual(proof["unique_uaf_animnext_component_owners"], 1)
        self.assertEqual(proof["rigvm_objects_for_uaf_assets"], 1)
        self.assertEqual(proof["rigvm_pins_for_uaf_assets"], 1)
        self.assertEqual(proof["rigvm_links_for_uaf_assets"], 1)
        self.assertEqual(proof["rigvm_properties_for_uaf_assets"], 1)
        self.assertEqual(proof["rigvm_references_for_uaf_assets"], 1)
        self.assertGreaterEqual(proof["variable_binding_rows"], 1)
        self.assertGreaterEqual(proof["entry_point_rows"], 1)
        self.assertGreaterEqual(proof["exact_reference_rows"], 1)
        self.assertTrue(any("Existing RigVM rows overlap" in gap for gap in report["gaps"]))

    def test_legacy_animnext_aliases_remain_visible_without_promoting_unknown_classes(self) -> None:
        write_jsonl(self.output / "assets.jsonl", [
            {"object_path": "/Game/Old/AM_Test.AM_Test", "class_path": "/Script/AnimNext.AnimNextModule"},
            {"object_path": "/Game/Old/Unknown.Unknown", "class_path": "/Script/AnimNext.SomeFutureAsset"},
        ])
        report = evidence.build_report(self.output, rows, include_source=False)
        self.assertEqual(report["proof"]["unique_uaf_system_assets"], 1)
        self.assertEqual(report["proof"]["unique_other_uaf_animnext_assets"], 1)
        self.assertEqual(report["proof"]["unique_uaf_animnext_assets_total"], 2)

    def test_negative_corpus_refuses_schema_implication(self) -> None:
        write_jsonl(self.output / "assets.jsonl", [
            {"object_path": "/Game/Anim/A_Run.A_Run", "class_path": "/Script/Engine.AnimSequence"},
        ])
        report = evidence.build_report(self.output, rows, include_source=False)
        self.assertEqual(report["proof"]["unique_uaf_animnext_assets_total"], 0)
        self.assertEqual(report["proof"]["unique_uaf_animnext_component_owners"], 0)
        self.assertTrue(any("do not design" in gap for gap in report["gaps"]))

    def test_focus_validation(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown AnimNext/UAF focus"):
            evidence.build_report(self.output, rows, focuses=("not_real",))

    def test_facade_wires_public_command(self) -> None:
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_animnext_evidence as _animnext_evidence", facade)
        self.assertIn("_animnext_evidence.install(_runtime)", facade)
        source = (SCRIPTS / "uatool_animnext_evidence.py").read_text(encoding="utf-8")
        self.assertIn('sys.argv[1] == "animnext-evidence"', source)
        self.assertIn("schema_promotion", source)
        self.assertIn("/script/uafanimgraph.uafanimgraph", source.lower())


if __name__ == "__main__":
    unittest.main()
