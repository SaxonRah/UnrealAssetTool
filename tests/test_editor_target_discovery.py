from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_build_perf as build_perf


class EditorTargetDiscoveryTest(unittest.TestCase):
    def _project(self, root: Path, name: str = "LyraStarterGame") -> Path:
        project = root / f"{name}.uproject"
        project.write_text("{}\n", encoding="utf-8")
        (root / "Source").mkdir()
        return project

    def test_lyra_style_project_name_can_differ_from_editor_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._project(root)
            (root / "Source" / "LyraGame.Target.cs").write_text(
                "public class LyraGameTarget : TargetRules { public LyraGameTarget(TargetInfo Target) : base(Target) { Type = TargetType.Game; } }\n",
                encoding="utf-8",
            )
            (root / "Source" / "LyraEditor.Target.cs").write_text(
                "public class LyraEditorTarget : TargetRules { public LyraEditorTarget(TargetInfo Target) : base(Target) { Type = TargetType.Editor; } }\n",
                encoding="utf-8",
            )
            self.assertEqual(build_perf._resolve_editor_target(project), "LyraEditor")

    def test_conventional_editor_target_remains_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._project(root, "Example")
            for name in ("ExampleEditor", "ToolsEditor"):
                (root / "Source" / f"{name}.Target.cs").write_text(
                    f"public class {name}Target : TargetRules {{ public {name}Target(TargetInfo Target) : base(Target) {{ Type = TargetType.Editor; }} }}\n",
                    encoding="utf-8",
                )
            self.assertEqual(build_perf._resolve_editor_target(project), "ExampleEditor")

    def test_no_explicit_editor_target_falls_back_to_historical_convention(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = self._project(root, "Legacy")
            (root / "Source" / "Legacy.Target.cs").write_text(
                "public class LegacyTarget : TargetRules { public LegacyTarget(TargetInfo Target) : base(Target) { Type = TargetType.Game; } }\n",
                encoding="utf-8",
            )
            self.assertEqual(build_perf._resolve_editor_target(project), "LegacyEditor")


if __name__ == "__main__":
    unittest.main()
