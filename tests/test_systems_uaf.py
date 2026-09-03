from __future__ import annotations

import collections
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_systems_uaf as systems
import uatool_uaf_graph as graph


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def rows(path: Path):
    if not path.is_file(): return
    for line in path.read_text(encoding="utf-8").splitlines():
        if line: yield json.loads(line)


class SystemsUAFTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(); self.output = Path(self.temp.name)
        self.asset = "/UAF/Test/S_Test.S_Test"; self.graph = self.asset + ":EditorData.RigVMGraph"
        self.var = self.asset + ":EditorData.AnimNextVariableEntry_0"
        self._write_fixture()

    def tearDown(self) -> None: self.temp.cleanup()

    def _write_fixture(self) -> None:
        write_jsonl(self.output / "uaf_assets.jsonl", [{
            "asset_path":self.asset,"asset_class":systems.UAF_SYSTEM_CLASS,"asset_kind":"system",
            "rigvm_path":self.asset+":VM","editor_data_path":self.asset+":EditorData","required_plugins":"(UAF,RigVM)",
            "default_entry_point":"","entry_count":1,"variable_count":1,"component_count":1,"entry_point_count":0,"rigvm_graph_count":1,
        }])
        write_jsonl(self.output / "uaf_entries.jsonl", [{
            "asset_path":self.asset,"entry_path":self.asset+":EditorData.AnimNextEventGraphEntry_0",
            "entry_class":"/Script/UAFUncookedOnly.AnimNextEventGraphEntry","entry_kind":"event_graph","graph_name":"PrePhysics",
            "access":"Private","graph_path":self.graph,"ed_graph_path":self.asset+":EditorData.AnimNextEventGraphEntry_0.PrePhysics","hidden_in_outliner":"False",
        }])
        write_jsonl(self.output / "uaf_variables.jsonl", [{
            "asset_path":self.asset,"variable_path":self.var,"variable_guid":"11111111111111111111111111111111","variable_name":"Graph",
            "access":"Private","type_value":"Object","type_container":"None","type_object":"/Script/UAFAnimGraph.UAFAnimGraph",
            "default_value":"None","binding":"None",
        }])
        write_jsonl(self.output / "uaf_components.jsonl", [{
            "asset_path":self.asset,"component_index":0,"component_struct":"/Script/UAF.UAFRigVMComponent","component_type":"","value":"()","truncated":False,
        }])
        write_jsonl(self.output / "uaf_entry_points.jsonl", [])
        write_jsonl(self.output / "uaf_rigvm_graphs.jsonl", [{
            "asset_path":self.asset,"graph_path":self.graph,"graph_name":"RigVMGraph","graph_class":"/Script/RigVMDeveloper.RigVMGraph",
            "schema_class":"/Script/UAFUncookedOnly.AnimNextEventGraphSchema","execute_context_struct":"/Script/UAF.AnimNextExecuteContext","node_count":2,"link_count":1,
        }])
        write_jsonl(self.output / "uaf_rigvm_nodes.jsonl", [
            {"asset_path":self.asset,"graph_path":self.graph,"node_path":"VariableNode","node_name":"VariableNode","node_class":"/Script/RigVMDeveloper.RigVMVariableNode","node_index":0,"top_level_pin_count":2,"operation":"rigvm_variable","unit_script_struct":""},
            {"asset_path":self.asset,"graph_path":self.graph,"node_path":"Run","node_name":"Run","node_class":"/Script/RigVMDeveloper.RigVMUnitNode","node_index":1,"top_level_pin_count":1,"operation":"rigvm_unit","unit_script_struct":"/Script/UAFAnimGraph.RigUnit_AnimNextRunAnimationGraph_v2"},
        ])
        write_jsonl(self.output / "uaf_rigvm_pins.jsonl", [
            {"asset_path":self.asset,"graph_path":self.graph,"node_path":"VariableNode","pin_path":"VariableNode.Variable","pin_name":"Variable","direction":"Hidden","depth":0,"pin_index":0,"cpp_type":"FName","cpp_type_object":"","default_value":"Graph","original_default_value":"Graph","hidden":True,"subpin_count":0},
            {"asset_path":self.asset,"graph_path":self.graph,"node_path":"VariableNode","pin_path":"VariableNode.Value","pin_name":"Value","direction":"Output","depth":0,"pin_index":1,"cpp_type":"UUAFAnimGraph*","cpp_type_object":"/Script/UAFAnimGraph.UAFAnimGraph","default_value":"","original_default_value":"","hidden":False,"subpin_count":0},
            {"asset_path":self.asset,"graph_path":self.graph,"node_path":"Run","pin_path":"Run.Graph","pin_name":"Graph","direction":"Input","depth":0,"pin_index":0,"cpp_type":"UUAFAnimGraph*","cpp_type_object":"/Script/UAFAnimGraph.UAFAnimGraph","default_value":"","original_default_value":"","hidden":False,"subpin_count":0},
        ])
        write_jsonl(self.output / "uaf_rigvm_links.jsonl", [{
            "asset_path":self.asset,"graph_path":self.graph,"link_path":self.graph+":Link_0","source_node_path":"VariableNode","source_pin_path":"VariableNode.Value","target_node_path":"Run","target_pin_path":"Run.Graph",
        }])
        write_jsonl(self.output / "uaf_variable_usages.jsonl", [{
            "asset_path":self.asset,"graph_path":self.graph,"node_path":"VariableNode","variable_name":"Graph","variable_guid":"11111111111111111111111111111111","variable_path":self.var,
        }])
        counts = {"uaf_assets":1,"uaf_entries":1,"uaf_variables":1,"uaf_components":1,"uaf_entry_points":0,"uaf_rigvm_graphs":1,"uaf_rigvm_nodes":2,"uaf_rigvm_pins":3,"uaf_rigvm_links":1,"uaf_variable_usages":1,"uaf_truncated_values":0}
        (self.output / "systems_manifest.json").write_text(json.dumps({"schema_version":10,"success":True,"counts":counts}), encoding="utf-8")

    def test_fixture_validates(self) -> None:
        self.assertIsNone(systems.validation_error(self.output, rows))

    def test_exact_graph_contract(self) -> None:
        edges = graph.expected_edge_keys(self.output, rows)
        counts = collections.Counter(r for _,r,_ in edges)
        self.assertEqual(counts["has_uaf_entry"],1)
        self.assertEqual(counts["uaf_entry_uses_rigvm_graph"],1)
        self.assertEqual(counts["has_uaf_variable"],1)
        self.assertEqual(counts["uaf_variable_uses_type"],1)
        self.assertEqual(counts["has_uaf_component"],1)
        self.assertEqual(counts["instance_of_uaf_component_struct"],1)
        self.assertEqual(counts["has_uaf_rigvm_graph"],1)
        self.assertEqual(counts["has_rigvm_node"],2)
        self.assertEqual(counts["instance_of_rigvm_node_class"],2)
        self.assertEqual(counts["instance_of_rigvm_unit_struct"],1)
        self.assertEqual(counts["has_rigvm_pin"],3)
        self.assertEqual(counts["rigvm_connects"],1)
        self.assertEqual(counts["uaf_rigvm_node_uses_variable"],1)
        self.assertEqual(len(edges),17)

    def test_unresolved_link_rejected(self) -> None:
        link = list(rows(self.output / "uaf_rigvm_links.jsonl"))[0]
        link["target_pin_path"] = "Missing.Pin"
        write_jsonl(self.output / "uaf_rigvm_links.jsonl", [link])
        self.assertIn("unresolved pin endpoint", systems.validation_error(self.output, rows) or "")

    def test_variable_usage_requires_exact_declaration(self) -> None:
        usage = list(rows(self.output / "uaf_variable_usages.jsonl"))[0]
        usage["variable_guid"] = "bad"
        write_jsonl(self.output / "uaf_variable_usages.jsonl", [usage])
        self.assertIn("usage/declaration mismatch", systems.validation_error(self.output, rows) or "")

    def test_native_schema10_contract(self) -> None:
        scanner = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.cpp").read_text(encoding="utf-8")
        scanner_header = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsScanner.h").read_text(encoding="utf-8")
        commandlet = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsCommandlet.cpp").read_text(encoding="utf-8")
        commandlet_header = (ROOT / "Source/UnrealAssetTool/Public/UnrealAssetToolSystemsCommandlet.h").read_text(encoding="utf-8")
        native = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsUAF.inl").read_text(encoding="utf-8")
        policy = (ROOT / "Source/UnrealAssetTool/Private/UnrealAssetToolSystemsUAFPolicy.inl").read_text(encoding="utf-8")
        facade = (SCRIPTS / "uatool_vfx.py").read_text(encoding="utf-8")
        capture = (SCRIPTS / "uatool_uaf_systems_capture.py").read_text(encoding="utf-8")
        self.assertIn('#include "RigVMModel/RigVMSchema.h"', scanner)
        self.assertIn('#include "UnrealAssetToolSystemsScanner.h"', scanner)
        self.assertIn("RunSystemsScanForCommandlet", scanner_header)
        self.assertIn("RunSystemsScanForCommandlet", scanner)
        self.assertIn("UUnrealAssetToolSystemsCommandlet", commandlet_header)
        self.assertIn("RunSystemsScanForCommandlet", commandlet)
        self.assertIn("/Script/UAF.UAFSystem", native)
        self.assertIn("/Script/UAFAnimGraph.UAFAnimGraph", native)
        self.assertIn("AnimNextVariableEntry", native)
        self.assertIn("Pin->GetName() == TEXT(\"Variable\")", native)
        self.assertIn("Pin->GetDirection() == ERigVMPinDirection::Hidden", native)
        self.assertNotIn("Pin->IsHidden()", native)
        self.assertIn("if (!UAFIsExactAssetClass(ClassPath)) return true", native)
        self.assertIn("EnsureUAFRepresentativeMounts", policy)
        self.assertIn("Plugin->GetMountedAssetPath()", policy)
        self.assertIn("Plugin->GetContentDir()", policy)
        self.assertIn("Plugin->IsMounted()", policy)
        self.assertIn("FPackageName::MountPointExists", policy)
        self.assertIn("FPackageName::RegisterMountPoint", policy)
        self.assertIn("FARFilter Filter", policy)
        self.assertIn("Filter.PackagePaths.Add(FName(*Path))", policy)
        self.assertIn("Filter.bRecursivePaths = true", policy)
        self.assertIn("Registry.GetAssets(Filter, PathAssets)", policy)
        self.assertIn("AddCandidate(Asset, false)", policy)
        self.assertIn("AddCandidate(Asset, true)", policy)
        self.assertIn("bRequireExactRegistryClass && !UAFIsExactAssetClass", policy)
        self.assertNotIn("GetAssetsByClass", policy)
        self.assertIn("/UAFSharedAssets/", policy)
        self.assertIn("UpgradeSystemsManifestToSchema10", policy)
        self.assertIn("FDataflowChaosSystemsFileHelperProxy::SaveStringToFile", policy)
        self.assertIn("FUAFSystemsFileHelperProxy", scanner)
        self.assertIn("_systems_uaf.install(_systems)", facade)
        self.assertIn("_uaf_graph.install(_project_graph)", facade)
        self.assertIn("_systems_schema10_accept.install(_runtime, _systems)", facade)
        self.assertIn('"-run=UnrealAssetToolSystems"', capture)
        self.assertNotIn('"-UnrealAssetToolSystemsOnly"', capture)
        self.assertIn('"-UAFEngineContent"', capture)
        self.assertIn('"-EnablePlugins=UAF,UAFAnimGraph,UAFSharedAssets"', capture)


if __name__ == "__main__": unittest.main()
