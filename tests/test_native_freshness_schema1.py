from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import uatool_native_freshness as native_freshness


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


class NativeFreshnessSchema1Test(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        project = write(root / "Sample.uproject", '{"FileVersion":3}\n')
        write(
            root / "Source" / "Sample" / "Sample.Build.cs",
            "public class Sample {}\n",
        )
        write(
            root / "Source" / "Sample" / "Sample.cpp",
            "int sample(void) { return 1; }\n",
        )
        write(
            root / "Source" / "Sample" / "Sample.h",
            "#pragma once\nint sample(void);\n",
        )
        write(
            root / "Source" / "SampleEditor.Target.cs",
            "public class SampleEditorTarget {}\n",
        )
        write(
            root / "Plugins" / "Feature" / "Feature.uplugin",
            '{"FileVersion":3}\n',
        )
        write(
            root / "Plugins" / "Feature" / "Source" /
            "Feature" / "Feature.Build.cs",
            "public class Feature {}\n",
        )
        write(
            root / "Plugins" / "Feature" / "Source" /
            "Feature" / "Private" / "Feature.cpp",
            "int feature(void) { return 2; }\n",
        )
        write(
            root / "Plugins" / "UnrealAssetTool" / "Source" /
            "UnrealAssetTool" / "Private" / "Tool.cpp",
            "int tool(void) { return 3; }\n",
        )
        write(
            root / "Saved" / "Generated.cpp",
            "int generated(void) { return 4; }\n",
        )
        return project

    def test_snapshot_covers_project_native_build_and_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.make_project(root)
            snapshot = native_freshness.capture_snapshot(project)
            self.assertIsNone(
                native_freshness.validation_error(snapshot)
            )
            paths = {row["path"] for row in snapshot["files"]}
            self.assertIn("Sample.uproject", paths)
            self.assertIn("Source/Sample/Sample.Build.cs", paths)
            self.assertIn("Source/Sample/Sample.cpp", paths)
            self.assertIn("Source/Sample/Sample.h", paths)
            self.assertIn("Source/SampleEditor.Target.cs", paths)
            self.assertIn("Plugins/Feature/Feature.uplugin", paths)
            self.assertIn(
                "Plugins/Feature/Source/Feature/Feature.Build.cs",
                paths,
            )
            self.assertIn(
                "Plugins/Feature/Source/Feature/Private/Feature.cpp",
                paths,
            )
            self.assertFalse(
                any("UnrealAssetTool" in path for path in paths)
            )
            self.assertFalse(
                any(path.startswith("Saved/") for path in paths)
            )

    def test_unchanged_snapshot_is_same(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.make_project(root)
            expected = native_freshness.capture_snapshot(project)
            report = native_freshness.compare_snapshot(
                expected,
                project,
            )
            self.assertEqual(report["status"], "same")
            self.assertEqual(report["difference_count"], 0)

    def test_source_change_is_compiler_input_difference(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.make_project(root)
            expected = native_freshness.capture_snapshot(project)
            source = root / "Source" / "Sample" / "Sample.cpp"
            source.write_text(
                "int sample(void) { return 99; }\n",
                encoding="utf-8",
                newline="\n",
            )
            report = native_freshness.compare_snapshot(
                expected,
                project,
            )
            self.assertEqual(report["status"], "different")
            self.assertEqual(report["difference_count"], 1)
            self.assertEqual(
                report["differences"][0]["kind"],
                "changed",
            )
            self.assertEqual(
                report["differences"][0]["path"],
                "Source/Sample/Sample.cpp",
            )

    def test_build_descriptor_change_is_compiler_input_difference(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.make_project(root)
            expected = native_freshness.capture_snapshot(project)
            build_cs = root / "Source" / "Sample" / "Sample.Build.cs"
            build_cs.write_text(
                "public class Sample { public int Changed = 1; }\n",
                encoding="utf-8",
                newline="\n",
            )
            report = native_freshness.compare_snapshot(
                expected,
                project,
            )
            self.assertEqual(report["status"], "different")
            self.assertEqual(
                report["differences"][0]["path"],
                "Source/Sample/Sample.Build.cs",
            )

    def test_added_and_removed_inputs_are_differences(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = self.make_project(root)
            expected = native_freshness.capture_snapshot(project)
            (root / "Source" / "Sample" / "Sample.h").unlink()
            write(
                root / "Source" / "Sample" / "Added.inl",
                "inline int added() { return 1; }\n",
            )
            report = native_freshness.compare_snapshot(
                expected,
                project,
                limit=10,
            )
            self.assertEqual(report["status"], "different")
            kinds = {
                (row["kind"], row["path"])
                for row in report["differences"]
            }
            self.assertIn(
                ("removed", "Source/Sample/Sample.h"),
                kinds,
            )
            self.assertIn(
                ("added", "Source/Sample/Added.inl"),
                kinds,
            )


if __name__ == "__main__":
    unittest.main()
