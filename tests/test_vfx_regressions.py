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

import uatool_vfx_stitch as vfx_stitch
import uatool_vfx_validate as vfx_validate


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


class VFXRegressionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_exact_topology_absorbs_reference_evidence_without_dependency_promotion(self) -> None:
        system = "/Game/VFX/NS_Test.NS_Test"
        emitter = "/Game/VFX/NSE_Test.NSE_Test"
        write_jsonl(self.output / "assets.jsonl", [
            {"object_path": system, "class_path": "/Script/Niagara.NiagaraSystem", "package_name": "/Game/VFX/NS_Test"},
            {"object_path": emitter, "class_path": "/Script/Niagara.NiagaraStatelessEmitter", "package_name": "/Game/VFX/NSE_Test"},
        ])
        write_jsonl(self.output / "vfx_assets.jsonl", [
            {"vfx_path": system, "vfx_kind": "niagara_system", "family": "niagara", "class_path": "/Script/Niagara.NiagaraSystem", "package_name": "/Game/VFX/NS_Test"},
            {"vfx_path": emitter, "vfx_kind": "niagara_stateless_emitter", "family": "niagara", "class_path": "/Script/Niagara.NiagaraStatelessEmitter", "package_name": "/Game/VFX/NSE_Test"},
        ])
        write_jsonl(self.output / "niagara_system_emitters.jsonl", [{
            "system_path": system,
            "emitter_index": 0,
            "name": "Emitter",
            "id": "stable-id",
            "enabled": True,
            "emitter_mode": "Stateless",
            "emitter_path": "",
            "emitter_version": "",
            "stateless_emitter_path": emitter,
        }])
        write_jsonl(self.output / "vfx_references.jsonl", [{
            "asset_path": system,
            "owner_path": system,
            "owner_kind": "niagara_system",
            "root_property": "EmitterHandles",
            "property_path": "EmitterHandles[0].StatelessEmitter",
            "reference_kind": "hard",
            "target_path": emitter,
            "target_class": "/Script/Niagara.NiagaraStatelessEmitter",
        }])
        write_jsonl(self.output / "asset_dependencies.jsonl", [{
            "source_package": "/Game/VFX/NS_Test",
            "target_package": "/Game/VFX/NSE_Test",
            "category": "hard",
        }])

        relations, contexts, summaries = vfx_stitch.derive(self.output, read_rows)
        edge = [
            row for row in relations
            if row["source"] == system
            and row["relation"] == "uses_stateless_emitter"
            and row["target"] == emitter
        ]
        self.assertEqual(len(edge), 1)
        self.assertEqual(edge[0]["target_coverage"], "first_class")
        self.assertEqual(edge[0]["evidence_count"], 2)
        self.assertEqual(
            {item["stream"] for item in edge[0]["evidence"]},
            {"niagara_system_emitters.jsonl", "vfx_references.jsonl"},
        )
        self.assertFalse(any(
            item.get("stream") == "asset_dependencies.jsonl"
            for row in relations for item in row["evidence"]
        ))
        self.assertEqual({row["asset_path"] for row in contexts}, {system, emitter})
        self.assertEqual({row["asset_path"] for row in summaries}, {system, emitter})

    def test_context_bound_and_generated_bookkeeping_guards(self) -> None:
        emitter = "/Game/VFX/NSE_Dense.NSE_Dense"
        modules = [f"{emitter}:Module_{index:03d}" for index in range(260)]
        write_jsonl(self.output / "vfx_assets.jsonl", [{
            "vfx_path": emitter,
            "vfx_kind": "niagara_stateless_emitter",
            "family": "niagara",
            "class_path": "/Script/Niagara.NiagaraStatelessEmitter",
            "package_name": "/Game/VFX/NSE_Dense",
        }])
        write_jsonl(self.output / "niagara_stateless_modules.jsonl", [{
            "emitter_path": emitter,
            "module_index": index,
            "asset_path": emitter,
            "module_path": module,
            "module_class": "/Script/Niagara.NiagaraStatelessModule",
            "enabled": True,
        } for index, module in enumerate(modules)])

        relations, contexts, summaries = vfx_stitch.derive(self.output, read_rows)
        self.assertEqual(len([row for row in relations if row["source"] == emitter]), 260)
        context = next(row for row in contexts if row["asset_path"] == emitter)
        summary = next(row for row in summaries if row["asset_path"] == emitter)
        self.assertEqual(context["outgoing_count"], 260)
        self.assertEqual(summary["outgoing_count"], 260)
        self.assertTrue(context["truncated"])
        self.assertIn("more relations omitted by context link bound", context["text"])

        write_jsonl(self.output / "vfx_properties.jsonl", [{
            "asset_path": emitter,
            "owner_path": modules[0],
            "owner_kind": "niagara_stateless_module",
            "property_name": "MergeId",
        }])
        error = vfx_validate._validate_stable_authored_facts(self.output, [])
        self.assertIn("generated Niagara bookkeeping leaked", str(error))

    def test_generated_data_channel_version_is_rejected(self) -> None:
        error = vfx_validate._validate_stable_authored_facts(self.output, [{
            "data_channel_path": "/Game/VFX/NDC_Test.NDC_Test",
            "version": "01234567-89ab-cdef-0123-456789abcdef",
            "raw_value": "",
        }])
        self.assertEqual(error, "Niagara Data Channel variable contains generated Version GUID")


if __name__ == "__main__":
    unittest.main()
