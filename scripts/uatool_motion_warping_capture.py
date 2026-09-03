#!/usr/bin/env python3
"""Focused UE 5.8 Motion Warping authored modifier-template capture."""
from __future__ import annotations

import argparse
import collections
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

CAPTURE_FILES = (
    "motion_warping_capture_manifest.json",
    "motion_warping_windows.jsonl",
    "motion_warping_modifiers.jsonl",
    "motion_warping_modifier_properties.jsonl",
)
NOTIFY_CLASS = "/Script/MotionWarping.AnimNotifyState_MotionWarping"


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield value


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def _resolve_output(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "motion-warping-native-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.motion-warping-native-capture.zip"


def _resolve_report(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.motion-warping-native-capture.txt"


def _manifest(output: Path) -> dict:
    path = output / "motion_warping_capture_manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid motion_warping_capture_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("motion_warping_capture_manifest.json root is not an object")
    return value


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"Motion Warping capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _unique(rows: list[dict], fields: tuple[str, ...], label: str) -> None:
    seen = set()
    for row in rows:
        key = tuple(row.get(field) for field in fields)
        if key in seen:
            raise RuntimeError(f"duplicate {label} identity: {key}")
        seen.add(key)


def _canonical_windows(corpus: Path) -> dict[tuple[str, int], dict]:
    path = corpus / "animation_notifies.jsonl"
    result: dict[tuple[str, int], dict] = {}
    if not path.is_file():
        return result
    for row in _rows(path):
        if str(row.get("notify_state_class", "") or "") != NOTIFY_CLASS:
            continue
        key = (str(row.get("asset_path", "") or ""), int(row.get("notify_index", -1)))
        if key in result:
            raise RuntimeError(f"duplicate canonical Motion Warping notify identity: {key}")
        result[key] = row
    return result


def validate_capture(output: Path) -> dict:
    output = Path(output).expanduser().resolve()
    manifest = _manifest(output)
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(f"Motion Warping capture expected schema 1, got {manifest.get('schema_version')}")
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"Motion Warping capture failed: {manifest.get('error', '')}")
    if not bool(manifest.get("diagnostic_only", False)):
        raise RuntimeError("Motion Warping capture must remain diagnostic_only=true")
    if bool(manifest.get("semantic_promotion", True)) or bool(manifest.get("schema_promotion", True)):
        raise RuntimeError("Motion Warping focused capture must not promote schema/semantic state")
    for key in (
        "runtime_state_captured",
        "live_warp_targets_captured",
        "active_root_motion_modifiers_captured",
        "root_motion_evaluated",
        "maps_loaded",
    ):
        if bool(manifest.get(key, True)):
            raise RuntimeError(f"Motion Warping authored-only contract requires {key}=false")

    windows = list(_rows(output / "motion_warping_windows.jsonl"))
    modifiers = list(_rows(output / "motion_warping_modifiers.jsonl"))
    properties = list(_rows(output / "motion_warping_modifier_properties.jsonl"))
    _unique(windows, ("asset_path", "notify_index"), "Motion Warping window")
    _unique(modifiers, ("asset_path", "notify_index"), "Motion Warping modifier")
    _unique(
        properties,
        ("asset_path", "notify_index", "declaring_type", "property_name", "static_index"),
        "Motion Warping modifier property",
    )

    window_keys = {(str(r.get("asset_path", "") or ""), int(r.get("notify_index", -1))) for r in windows}
    modifier_keys = {(str(r.get("asset_path", "") or ""), int(r.get("notify_index", -1))) for r in modifiers}
    for row in windows:
        if str(row.get("notify_state_class", "") or "") != NOTIFY_CLASS:
            raise RuntimeError("Motion Warping capture contains a non-focus notify-state class")
        if not str(row.get("notify_state_path", "") or ""):
            raise RuntimeError("Motion Warping window is missing exact notify_state_path")
    for row in modifiers:
        key = (str(row.get("asset_path", "") or ""), int(row.get("notify_index", -1)))
        if key not in window_keys:
            raise RuntimeError(f"Motion Warping modifier has unresolved window: {key}")
        if not str(row.get("modifier_path", "") or "") or not str(row.get("modifier_class", "") or ""):
            raise RuntimeError(f"Motion Warping modifier is missing exact object identity: {key}")
        if not bool(row.get("is_template", False)):
            raise RuntimeError(f"Motion Warping modifier row is not marked as authored template: {key}")
    for row in properties:
        key = (str(row.get("asset_path", "") or ""), int(row.get("notify_index", -1)))
        if key not in modifier_keys:
            raise RuntimeError(f"Motion Warping property has unresolved modifier: {key}")

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    physical = {
        "motion_warping_windows": len(windows),
        "modifiers": len(modifiers),
        "modifier_properties": len(properties),
        "windows_without_modifier": len(window_keys - modifier_keys),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            raise RuntimeError(f"Motion Warping count mismatch for {key}: manifest={counts.get(key)} actual={actual}")
    if int(counts.get("load_failures", -1)) != 0:
        raise RuntimeError("Motion Warping capture reports animation load failures")

    corpus = output.parent
    canonical = _canonical_windows(corpus)
    if canonical:
        if set(canonical) != window_keys:
            missing = sorted(set(canonical) - window_keys)
            extra = sorted(window_keys - set(canonical))
            parts = []
            if missing:
                parts.append(f"missing={len(missing)} first={missing[0]}")
            if extra:
                parts.append(f"extra={len(extra)} first={extra[0]}")
            raise RuntimeError("Motion Warping native/canonical window mismatch: " + "; ".join(parts))
        by_key = {(
            str(row.get("asset_path", "") or ""),
            int(row.get("notify_index", -1)),
        ): row for row in windows}
        for key, canonical_row in canonical.items():
            captured = by_key[key]
            if str(captured.get("notify_state_path", "") or "") != str(canonical_row.get("notify_state_object", "") or ""):
                raise RuntimeError(f"Motion Warping notify-state object mismatch for {key}")
    return manifest


def semantic_report(output: Path, manifest: dict) -> str:
    output = Path(output)
    windows = list(_rows(output / "motion_warping_windows.jsonl"))
    modifiers = list(_rows(output / "motion_warping_modifiers.jsonl"))
    properties = list(_rows(output / "motion_warping_modifier_properties.jsonl"))
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    modifier_classes = collections.Counter(str(row.get("modifier_class", "") or "") for row in modifiers)
    warp_targets = collections.Counter(str(row.get("warp_target_name", "") or "") for row in modifiers)
    property_names = collections.Counter(str(row.get("property_name", "") or "") for row in properties)
    assets = collections.Counter(str(row.get("asset_path", "") or "") for row in windows)
    canonical_count = len(_canonical_windows(output.parent))

    lines = [
        "=== MOTION WARPING NATIVE AUTHORED CAPTURE ===",
        str(output),
        "diagnostic_only=True semantic_promotion=False schema_promotion=False",
        "runtime_state_captured=False live_warp_targets_captured=False active_root_motion_modifiers_captured=False root_motion_evaluated=False maps_loaded=False",
        "",
        "[Counts]",
    ]
    for key in sorted(counts):
        lines.append(f"  {key}: {counts[key]}")
    lines.extend((
        f"  canonical_motion_warping_windows: {canonical_count}",
        f"  captured_animation_assets_with_windows: {len(assets)}",
        "",
        "[Modifier classes]",
    ))
    if modifier_classes:
        for name, count in modifier_classes.most_common():
            lines.append(f"  {count:6d}  {name}")
    else:
        lines.append("  <none>")
    lines.extend(("", "[WarpTargetName values]"))
    if warp_targets:
        for name, count in warp_targets.most_common():
            lines.append(f"  {count:6d}  {name or '<None>'}")
    else:
        lines.append("  <none>")
    lines.extend(("", "[Editable authored modifier properties]"))
    if property_names:
        for name, count in property_names.most_common():
            lines.append(f"  {count:6d}  {name}")
    else:
        lines.append("  <none>")

    for title, rows in (
        ("Window rows", windows),
        ("Modifier template rows", modifiers),
        ("Modifier property rows", properties),
    ):
        lines.extend(("", f"[{title}]"))
        if not rows:
            lines.append("  <none>")
        for row in rows[:100]:
            lines.append("  " + json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

    lines.extend((
        "",
        "[Assessment]",
        "  animation_notifies.jsonl remains authoritative for authored window timing/index identity.",
        "  modifier rows are instanced notify-owned templates, not UMotionWarpingComponent runtime modifier instances.",
        "  editable property rows are candidate authored normalization facts; transient/runtime fields are excluded at capture time.",
        "  live warp targets, active modifier state, evaluated warped root motion and maps remain deliberate non-claims.",
        "================================================",
    ))
    return "\n".join(lines) + "\n"


def _capture_cli(core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool motion-warping-capture",
        description="capture exact UE 5.8 Motion Warping notify-owned modifier templates without runtime targets/modifier state/root-motion evaluation",
    )
    parser.add_argument("project")
    parser.add_argument("--editor", required=True)
    parser.add_argument("--build-script")
    parser.add_argument("--no-build", action="store_true")
    parser.add_argument("--include-engine", action="store_true")
    parser.add_argument("--output")
    parser.add_argument("--archive")
    parser.add_argument("--report")
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    editor = core_module.require_editor(args.editor)
    output = _resolve_output(project, args.output)
    archive = _resolve_archive(project, args.archive)
    report_path = _resolve_report(project, args.report)

    if output.exists():
        print(f"removing previous Motion Warping native capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    overall_started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(project, editor, args.build_script, args.no_build, active_root)
        command = [
            str(editor),
            str(project),
            "-run=UnrealAssetToolMotionWarping",
            f"-Output={output}",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-UTF8Output",
        ]
        if args.include_engine:
            command.append("-IncludeEngine")
        print("running focused Motion Warping native capture:", subprocess.list2cmdline(command))
        started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"focused Motion Warping editor elapsed: {time.perf_counter() - started:.2f}s")

    if all((output / filename).is_file() for filename in CAPTURE_FILES):
        _write_archive(output, archive)
        print(f"focused Motion Warping raw archive: {archive}")
    if result != 0:
        raise RuntimeError(
            f"focused Motion Warping commandlet failed with exit code {result}; upload the raw archive if it was produced"
        )

    manifest = validate_capture(output)
    report = semantic_report(output, manifest)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")
    print(f"focused Motion Warping report: {report_path}")
    print(f"focused Motion Warping total elapsed: {time.perf_counter() - overall_started:.2f}s")
    print("normal scan was not run")
    print("derive was not run")
    return 0


def _report_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool motion-warping-capture-report",
        description="validate/report an existing focused Motion Warping capture without launching Unreal",
    )
    parser.add_argument("output")
    parser.add_argument("--report")
    parser.add_argument("--archive")
    args = parser.parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    if not output.is_dir():
        raise FileNotFoundError(f"Motion Warping capture directory does not exist: {output}")
    manifest = validate_capture(output)
    report = semantic_report(output, manifest)
    target = Path(args.report).expanduser().resolve() if args.report else output.parent / "MotionWarping.native-capture.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report, encoding="utf-8", newline="\n")
    if args.archive:
        archive = Path(args.archive).expanduser().resolve()
        _write_archive(output, archive)
        print(f"focused Motion Warping raw archive: {archive}")
    print(report, end="")
    print(f"focused Motion Warping report: {target}")
    print("Unreal was not launched")
    print("derive was not run")
    return 0


def install(runtime_module=None, core_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if core_module is None:
        import uatool_core as core_module
    if getattr(runtime_module, "_motion_warping_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "motion-warping-capture":
            try:
                return _capture_cli(core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 71
        if len(sys.argv) > 1 and sys.argv[1] == "motion-warping-capture-report":
            try:
                return _report_cli(sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 71
        return original_main()

    runtime_module.main = main
    runtime_module._motion_warping_capture_installed = True
