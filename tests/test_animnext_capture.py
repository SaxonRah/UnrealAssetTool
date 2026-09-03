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

import uatool_animnext_capture as capture


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


class AnimNextCaptureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_valid(self) -> None:
        asset = "/UAF/Templates/BasicCharacter/AG_DefaultCharacter.AG_DefaultCharacter"
        graph = asset + ":EditorData.RigVMModel"
        node = "EntryPoint"
        source = "EntryPoint.Pose"
        target = "Result.Result"
        rows = {
            "uaf_assets.jsonl": [{
                "asset_path": asset,
                "loaded": True,
                "loaded_class": "/Script/UAFAnimGraph.UAFAnimGraph",
            }],
            "uaf_asset_properties.jsonl": [{
                "asset_path": asset,
                "owner_path": asset,
                "root_property": "SharedVariables",
                "property_path": "SharedVariables",
                "truncated": False,
            }],
            "uaf_asset_references.jsonl": [],
            "uaf_subobjects.jsonl": [{
                "asset_path": asset,
                "object_path": asset + ":EditorData",
                "class_path": "/Script/UAFUncookedOnly.UAFAssetEditorData",
            }],
            "uaf_subobject_properties.jsonl": [{
                "asset_path": asset,
                "owner_path": asset + ":EditorData",
                "root_property": "Entries",
                "property_path": "Entries[0]",
                "truncated": False,
            }],
            "uaf_subobject_references.jsonl": [],
            "uaf_rigvm_graphs.jsonl": [{
                "asset_path": asset,
                "graph_path": graph,
                "node_count": 2,
                "link_count": 1,
            }],
            "uaf_rigvm_nodes.jsonl": [
                {"asset_path": asset, "graph_path": graph, "node_path": node, "unit_script_struct": "/Script/UAFAnimGraph.AnimNextGraphEntryPoint"},
                {"asset_path": asset, "graph_path": graph, "node_path": "Result", "unit_script_struct": ""},
            ],
            "uaf_rigvm_pins.jsonl": [
                {"asset_path": asset, "graph_path": graph, "node_path": node, "pin_path": source},
                {"asset_path": asset, "graph_path": graph, "node_path": "Result", "pin_path": target},
            ],
            "uaf_rigvm_links.jsonl": [{
                "asset_path": asset,
                "graph_path": graph,
                "source_pin_path": source,
                "target_pin_path": target,
            }],
        }
        for name, values in rows.items():
            write_jsonl(self.output / name, values)
        counts = {
            "registry_candidates": 1,
            "loaded_assets": 1,
            "asset_properties": 1,
            "asset_references": 0,
            "subobjects": 1,
            "subobject_properties": 1,
            "subobject_references": 0,
            "rigvm_graphs": 1,
            "rigvm_nodes": 2,
            "rigvm_pins": 2,
            "rigvm_links": 1,
            "unit_nodes": 1,
            "truncated_properties": 0,
            "property_depth_limit_hits": 0,
            "property_row_limit_hits": 0,
            "container_element_limit_hits": 0,
        }
        (self.output / "uaf_capture_manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "success": True,
            "diagnostic_only": True,
            "semantic_promotion": False,
            "schema_promotion": False,
            "runtime_state_captured": False,
            "counts": counts,
        }), encoding="utf-8")

    def test_valid_synthetic_capture(self) -> None:
        self._write_valid()
        manifest = capture.validate_capture(self.output)
        self.assertTrue(manifest["success"])
        report = capture.semantic_report(self.output, manifest)
        self.assertIn("reuse the shared RigVM substrate", report)

    def test_unresolved_link_is_rejected(self) -> None:
        self._write_valid()
        write_jsonl(self.output / "uaf_rigvm_links.jsonl", [{
            "asset_path": "/UAF/Templates/BasicCharacter/AG_DefaultCharacter.AG_DefaultCharacter",
            "graph_path": "/UAF/Templates/BasicCharacter/AG_DefaultCharacter.AG_DefaultCharacter:EditorData.RigVMModel",
            "source_pin_path": "Missing.Pin",
            "target_pin_path": "Result.Result",
        }])
        with self.assertRaisesRegex(RuntimeError, "unresolved pin endpoint"):
            capture.validate_capture(self.output)

    def test_native_contract_uses_rigvm_model_without_uaf_headers(self) -> None:
        source = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolUAFCommandlet.cpp").read_text(encoding="utf-8")
        build = (ROOT / "Source/UnrealAssetTool/UnrealAssetTool.Build.cs").read_text(encoding="utf-8")
        descriptor = (ROOT / "UnrealAssetTool.uplugin").read_text(encoding="utf-8")
        self.assertIn('#include "RigVMModel/RigVMGraph.h"', source)
        self.assertIn("GetObjectsWithOuter(Asset, Objects, EGetObjectsFlags::IncludeNestedObjects)", source)
        self.assertNotIn("GetObjectsWithOuter(Asset, Objects, true)", source)
        self.assertIn("Filter.PackagePaths.Add(FName(MountRoot))", source)
        self.assertNotIn("Filter.PackagePaths.Add(*MountRoot)", source)
        self.assertIn("Graph->GetNodes()", source)
        self.assertIn("Graph->GetLinks()", source)
        self.assertIn("UnitNode->GetScriptStruct()", source)
        self.assertIn("Pin->GetSubPins()", source)
        self.assertIn('"RigVMDeveloper"', build)
        self.assertIn('"Name": "RigVM"', descriptor)
        self.assertNotIn('#include "AnimNextRigVMAsset.h"', source)
        self.assertNotIn('#include "Graph/AnimNextAnimationGraph.h"', source)

    def test_launcher_enables_installed_uaf_plugins(self) -> None:
        source = (SCRIPTS / "uatool_animnext_capture.py").read_text(encoding="utf-8")
        self.assertIn('"-EnablePlugins=UAF,UAFAnimGraph,UAFSharedAssets"', source)
        self.assertIn('"-run=UnrealAssetToolUAF"', source)
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn("import uatool_animnext_capture as _animnext_capture", facade)
        self.assertIn("_animnext_capture.install(_runtime)", facade)


if __name__ == "__main__":
    unittest.main()
