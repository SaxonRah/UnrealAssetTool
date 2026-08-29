#!/usr/bin/env python3
"""UE 5.8 launcher fix for UnrealAssetTool 0.6.x.

Place this file beside scripts/uatool.py and run it instead of uatool.py.
It loads the existing full launcher implementation, then replaces only the
cross-project plugin selection and build/scan orchestration.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

_THIS = Path(__file__).resolve()
_ORIGINAL = _THIS.with_name("uatool.py")
if not _ORIGINAL.is_file():
    raise FileNotFoundError(f"Expected the existing launcher beside this file: {_ORIGINAL}")

_spec = importlib.util.spec_from_file_location("_uatool_impl", _ORIGINAL)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Could not load {_ORIGINAL}")
_impl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_impl)

MODULE_NAME = _impl.MODULE_NAME


def plugin_root() -> Path:
    return _THIS.parent.parent


def plugin_descriptor() -> Path:
    descriptor = plugin_root() / "UnrealAssetTool.uplugin"
    if not descriptor.is_file():
        raise FileNotFoundError(
            "UnrealAssetTool.uplugin was not found beside this launcher checkout:\n"
            f"  {descriptor}"
        )
    return descriptor


@contextmanager
def prefer_invoking_plugin_checkout(project: Path):
    """Temporarily mask stale same-name project-local UATool descriptors."""
    active = plugin_descriptor().resolve()
    plugins_root = project.parent / "Plugins"
    masked: list[tuple[Path, Path]] = []

    if plugins_root.is_dir():
        for descriptor in sorted(plugins_root.rglob(f"{MODULE_NAME}.uplugin")):
            try:
                resolved = descriptor.resolve()
            except OSError:
                resolved = descriptor.absolute()
            if resolved == active:
                continue

            hidden = descriptor.with_name(descriptor.name + f".uatool-hidden-{os.getpid()}")
            if hidden.exists():
                raise RuntimeError(
                    "Cannot mask duplicate UnrealAssetTool plugin because the temporary "
                    f"descriptor already exists:\n  {hidden}"
                )
            print(f"temporarily hiding duplicate project plugin: {descriptor}")
            descriptor.rename(hidden)
            masked.append((descriptor, hidden))

    try:
        yield
    finally:
        for descriptor, hidden in reversed(masked):
            if hidden.exists():
                hidden.rename(descriptor)
                print(f"restored project plugin descriptor: {descriptor}")


def expected_plugin_binary(editor: Path) -> Path:
    binaries = plugin_root() / "Binaries" / "Win64"
    configuration = _impl.editor_configuration(editor)
    if configuration == "Development":
        filename = f"UnrealEditor-{MODULE_NAME}.dll"
    else:
        filename = f"UnrealEditor-{MODULE_NAME}-Win64-{configuration}.dll"
    return binaries / filename


def build_project(project: Path, editor: Path, build_script_arg: str | None = None) -> int:
    """Build the UATool module explicitly for the selected Editor configuration."""
    build_script = _impl.resolve_build_script(editor, build_script_arg)
    target = f"{project.stem}Editor"
    configuration = _impl.editor_configuration(editor)
    command = [
        str(build_script),
        f"-Target={target} Win64 {configuration}",
        f"-Module={MODULE_NAME}",
        f"-Project={project}",
        f"-Plugin={plugin_descriptor()}",
        "-WaitMutex",
        "-NoHotReloadFromIDE",
    ]
    print("building:", subprocess.list2cmdline(command))
    return subprocess.run(command, check=False).returncode


def ensure_plugin_binary(
    project: Path,
    editor: Path,
    build_script_arg: str | None,
    no_build: bool,
) -> None:
    configuration = _impl.editor_configuration(editor)
    expected = expected_plugin_binary(editor)

    if no_build:
        if not expected.is_file():
            existing = _impl.plugin_binary_candidates() if hasattr(_impl, "plugin_binary_candidates") else []
            existing_text = ""
            if existing:
                existing_text = "\nModule DLLs currently present:\n" + "\n".join(f"  {p}" for p in existing)
            raise RuntimeError(
                f"{MODULE_NAME} is not built for {configuration}.\n"
                f"Expected: {expected}{existing_text}\n"
                "Run without --no-build so UBT can build the explicit module."
            )
        print(f"module ready: {expected}")
        return

    # Always invoke UBT. It is incremental, catches stale scanner source, and
    # reproduces the known-good DebugGame behavior that emits the suffixed DLL.
    result = build_project(project, editor, build_script_arg)
    if result != 0:
        raise RuntimeError(f"Unreal build failed with exit code {result}")

    if not expected.is_file():
        existing = _impl.plugin_binary_candidates() if hasattr(_impl, "plugin_binary_candidates") else []
        existing_text = ""
        if existing:
            existing_text = "\nModule DLLs currently present:\n" + "\n".join(f"  {p}" for p in existing)
        raise RuntimeError(
            "UBT completed the explicit UnrealAssetTool module build, but the exact "
            "configuration-specific module binary is missing.\n"
            f"Selected editor configuration: {configuration}\n"
            f"Expected: {expected}{existing_text}"
        )
    print(f"module ready: {expected}")


def scan(args) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Not a .uproject file: {project}")

    output = Path(args.output).expanduser() if args.output else project.parent / ".uatool"
    if not output.is_absolute():
        output = (project.parent / output).resolve()
    output.mkdir(parents=True, exist_ok=True)

    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()

    editor = _impl.require_editor(args.editor)
    command = [
        str(editor),
        str(project),
        "-run=UnrealAssetTool",
        f"-Plugin={plugin_descriptor()}",
        f"-Output={output}",
        f"-EnablePlugins={MODULE_NAME}",
        "-unattended",
        "-RUNNINGUNATTENDEDSCRIPT",
        "-nop4",
        "-nosplash",
        "-NoShaderCompile",
        "-stdout",
        "-FullStdOutLogOutput",
        "-forcelogflush",
    ]
    if getattr(args, "include_generated", False):
        command.append("-IncludeGenerated")
    if getattr(args, "include_engine", False):
        command.append("-IncludeEngine")
    if getattr(args, "include_self", False):
        command.append("-IncludeSelf")
    if getattr(args, "include_raw_rigvm_properties", False):
        command.append("-IncludeRawRigVMProperties")

    with prefer_invoking_plugin_checkout(project):
        ensure_plugin_binary(project, editor, args.build_script, args.no_build)
        print("running:", subprocess.list2cmdline(command))
        result = subprocess.run(command, check=False)
        if result.returncode != 0:
            _impl.report_editor_failure(project, result.returncode)
            return result.returncode

    if not manifest_path.is_file():
        print(
            "ERROR: Unreal exited successfully but UnrealAssetTool did not write manifest.json.",
            file=sys.stderr,
        )
        latest_log = _impl.newest_project_log(project)
        if latest_log is not None:
            print(f"latest Unreal log: {latest_log}", file=sys.stderr)
        return 20

    derived_counts = _impl.derive_output(output)
    print("derived:", ", ".join(f"{key}={value}" for key, value in derived_counts.items()))
    db_path = _impl.build_database(output)
    print(f"database: {db_path}")
    if not getattr(args, "no_bundle", False):
        bundle_path = _impl.create_upload_bundle(
            output,
            project.parent / f"{project.stem}.uatool.zip",
            include_raw_rigvm=getattr(args, "bundle_include_raw_rigvm", False),
        )
        print(f"upload bundle: {bundle_path}")
    return 0


def build(args) -> int:
    project = Path(args.project).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Not a .uproject file: {project}")
    editor = _impl.require_editor(args.editor)
    with prefer_invoking_plugin_checkout(project):
        return build_project(project, editor, args.build_script)


# make_parser() resolves these globals when it is called, so replacing them on
# the implementation module preserves all existing pack/derive/bundle/query code.
_impl.plugin_root = plugin_root
_impl.plugin_descriptor = plugin_descriptor
_impl.prefer_invoking_plugin_checkout = prefer_invoking_plugin_checkout
_impl.expected_plugin_binary = expected_plugin_binary
_impl.build_project = build_project
_impl.ensure_plugin_binary = ensure_plugin_binary
_impl.scan = scan
_impl.build = build


if __name__ == "__main__":
    raise SystemExit(_impl.main())
