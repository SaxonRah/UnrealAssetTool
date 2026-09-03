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

import uatool_navigation_capture as capture


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


class NavigationCaptureTest(unittest.TestCase):
    def test_synthetic_capture_validation_preserves_authored_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            classes = []
            for class_path in sorted(capture.REQUIRED_CLASSES):
                classes.append({
                    "class_path": class_path,
                    "parent_class": "/Script/CoreUObject.Object",
                    "kind": "nav_area" if ".NavArea" in class_path else "navigation_class",
                    "cdo_path": class_path.replace(".", ".Default__", 1),
                    "native": True,
                    "config_class": True,
                    "abstract": False,
                })
            properties = [
                {
                    "class_path": "/Script/NavigationSystem.NavArea_Default",
                    "cdo_path": "/Script/NavigationSystem.Default__NavArea_Default",
                    "depth": 0,
                    "root_property": "DefaultCost",
                    "property_name": "DefaultCost",
                    "property_path": "DefaultCost",
                    "property_type": "FloatProperty",
                    "cpp_type": "float",
                    "value": "1.000000",
                    "config_property": True,
                    "edit_property": True,
                    "truncated": False,
                },
                {
                    "class_path": "/Script/NavigationSystem.NavigationSystemV1",
                    "cdo_path": "/Script/NavigationSystem.Default__NavigationSystemV1",
                    "depth": 0,
                    "root_property": "SupportedAgents",
                    "property_name": "SupportedAgents",
                    "property_path": "SupportedAgents",
                    "property_type": "ArrayProperty",
                    "cpp_type": "TArray",
                    "value": "()",
                    "config_property": True,
                    "edit_property": True,
                    "truncated": False,
                },
            ]
            references = [
                {
                    "class_path": "/Script/AIModule.NavLinkProxy",
                    "property_path": "PointLinks[0].AreaClass",
                    "reference_kind": "hard_object",
                    "target_path": "/Script/NavigationSystem.NavArea_Default",
                    "target_class": "/Script/CoreUObject.Class",
                },
            ]
            write_jsonl(root / "navigation_classes.jsonl", classes)
            write_jsonl(root / "navigation_cdo_properties.jsonl", properties)
            write_jsonl(root / "navigation_cdo_references.jsonl", references)
            (root / "navigation_capture_manifest.json").write_text(json.dumps({
                "schema_version": 1,
                "success": True,
                "diagnostic_only": True,
                "semantic_promotion": False,
                "schema_promotion": False,
                "runtime_state_captured": False,
                "generated_navmesh_instances_captured": False,
                "generated_navmesh_promoted": False,
                "counts": {
                    "classes": len(classes),
                    "area_classes": sum(1 for row in classes if row["kind"] == "nav_area"),
                    "cdo_properties": len(properties),
                    "cdo_references": len(references),
                    "config_properties": 2,
                    "truncated_values": 0,
                    "missing_expected_classes": 0,
                },
            }), encoding="utf-8")

            manifest = capture.validate_capture(root)
            self.assertTrue(manifest["diagnostic_only"])
            report = capture.semantic_report(root, manifest)
            self.assertIn("generated_navmesh_instances_captured: False", report)
            self.assertIn("NavArea_Default :: DefaultCost", report)
            self.assertIn("NavigationSystemV1 :: SupportedAgents", report)

    def test_native_commandlet_is_reflection_first_and_generated_state_free(self) -> None:
        native = (ROOT / "Source" / "UnrealAssetTool" / "Private" / "UnrealAssetToolNavigationCommandlet.cpp").read_text(encoding="utf-8")
        header = (ROOT / "Source" / "UnrealAssetTool" / "Public" / "UnrealAssetToolNavigationCommandlet.h").read_text(encoding="utf-8")
        self.assertIn("UUnrealAssetToolNavigationCommandlet", header)
        self.assertIn('LoadModule(TEXT("NavigationSystem"))', native)
        self.assertIn('LoadModule(TEXT("AIModule"))', native)
        self.assertIn("GetDerivedClasses(NavAreaBase, DerivedAreas, true)", native)
        self.assertIn("FCString::Strcmp(*A, *B) < 0", native)
        self.assertNotIn("ClassPaths.Sort();", native)
        self.assertIn('TEXT("/Script/NavigationSystem.NavigationSystemV1")', native)
        self.assertIn('TEXT("/Script/NavigationSystem.NavigationInvokerComponent")', native)
        self.assertIn('TEXT("/Script/NavigationSystem.NavModifierVolume")', native)
        self.assertIn('TEXT("/Script/AIModule.NavLinkProxy")', native)
        self.assertIn('TEXT("/Script/NavigationSystem.RecastNavMesh")', native)
        self.assertIn('TEXT("generated_navmesh_instances_captured"), false', native)
        self.assertIn('TEXT("generated_navmesh_promoted"), false', native)
        self.assertNotIn("GetNavMeshTiles", native)
        self.assertNotIn("GetPoly", native)
        self.assertNotIn("FindPath", native)

    def test_runner_and_canonical_facade_use_one_command(self) -> None:
        runner = (SCRIPTS / "uatool_navigation_capture.py").read_text(encoding="utf-8")
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        self.assertIn('"-run=UnrealAssetToolNavigation"', runner)
        self.assertNotIn("-IncludeEngine", runner)
        self.assertIn("import uatool_navigation_capture as _navigation_capture", facade)
        self.assertIn("_navigation_capture.install(_runtime, _core)", facade)


if __name__ == "__main__":
    unittest.main()
