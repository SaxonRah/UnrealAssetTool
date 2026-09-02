#!/usr/bin/env python3
"""Focused native Gameplay Ability System evidence capture launcher."""
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
    "gas_capture_manifest.json",
    "gas_assets.jsonl",
    "gas_classes.jsonl",
    "gas_properties.jsonl",
    "gas_references.jsonl",
)


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield row


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def _resolve_output(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "gas-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.gas-capture.zip"


def _resolve_report(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.gas-capture.txt"


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"focused GAS capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _read_manifest(output: Path) -> dict:
    path = output / "gas_capture_manifest.json"
    if not path.is_file():
        raise RuntimeError("focused GAS capture did not produce gas_capture_manifest.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid gas_capture_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("gas_capture_manifest.json root is not an object")
    return value


def _validate_capture(output: Path) -> dict:
    manifest = _read_manifest(output)
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(f"focused GAS capture expected manifest schema 1, got {manifest.get('schema_version')}")
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"focused GAS capture failed: {manifest.get('error', '')}")
    if not bool(manifest.get("diagnostic_only", False)):
        raise RuntimeError("focused GAS manifest must remain diagnostic_only=true")
    if bool(manifest.get("semantic_promotion", True)):
        raise RuntimeError("focused GAS manifest must remain semantic_promotion=false")
    if bool(manifest.get("runtime_state_captured", True)):
        raise RuntimeError("focused GAS manifest must remain runtime_state_captured=false")

    assets = list(_rows(output / "gas_assets.jsonl"))
    classes = list(_rows(output / "gas_classes.jsonl"))
    properties = list(_rows(output / "gas_properties.jsonl"))
    references = list(_rows(output / "gas_references.jsonl"))

    asset_paths = [str(row.get("asset_path", "") or "") for row in assets]
    class_paths = [str(row.get("class_path", "") or "") for row in classes]
    if any(not path for path in asset_paths) or len(asset_paths) != len(set(asset_paths)):
        raise RuntimeError("focused GAS assets contain blank or duplicate asset_path rows")
    if any(not path for path in class_paths) or len(class_paths) != len(set(class_paths)):
        raise RuntimeError("focused GAS classes contain blank or duplicate class_path rows")

    source_paths = set(asset_paths) | set(class_paths)
    for label, rows in (("property", properties), ("reference", references)):
        for row in rows:
            source = str(row.get("source_path", "") or "")
            owner = str(row.get("owner_path", "") or "")
            kind = str(row.get("gas_kind", "") or "")
            if source not in source_paths:
                raise RuntimeError(f"focused GAS {label} source does not resolve: {source}")
            if not owner or not kind:
                raise RuntimeError(f"focused GAS {label} has blank owner/kind for source: {source}")
    for row in references:
        if not str(row.get("target_path", "") or ""):
            raise RuntimeError("focused GAS reference has blank target_path")

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts", {}), dict) else {}
    physical = {
        "gas_assets": len(assets),
        "gas_classes": len(classes),
        "gas_properties": len(properties),
        "gas_references": len(references),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            raise RuntimeError(f"focused GAS count mismatch for {key}: manifest={counts.get(key)} actual={actual}")
    if int(counts.get("candidate_assets", -1)) != len(assets):
        raise RuntimeError(
            "focused GAS candidate count must equal emitted asset rows: "
            f"manifest={counts.get('candidate_assets')} assets={len(assets)}"
        )
    loaded = sum(int(bool(row.get("loaded", False))) for row in assets)
    if int(counts.get("loaded_assets", -1)) != loaded:
        raise RuntimeError(f"focused GAS loaded asset count mismatch: manifest={counts.get('loaded_assets')} actual={loaded}")
    truncated = sum(int(bool(row.get("truncated", False))) for row in properties)
    if int(counts.get("truncated_properties", -1)) != truncated:
        raise RuntimeError(
            f"focused GAS truncated property count mismatch: manifest={counts.get('truncated_properties')} actual={truncated}"
        )
    return manifest


def _short(value, limit: int = 220) -> str:
    if value is None:
        text = ""
    else:
        text = str(value)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _counter_lines(label: str, counter: collections.Counter, limit: int = 16) -> list[str]:
    lines = [label]
    for value, count in counter.most_common(limit):
        lines.append(f"  {count:8d}  {_short(value)}")
    if len(counter) > limit:
        lines.append(f"  ... {len(counter) - limit} more distinct values")
    return lines


def _semantic_report(output: Path, manifest: dict) -> str:
    assets = list(_rows(output / "gas_assets.jsonl"))
    classes = list(_rows(output / "gas_classes.jsonl"))
    properties = list(_rows(output / "gas_properties.jsonl"))
    references = list(_rows(output / "gas_references.jsonl"))
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts", {}), dict) else {}

    lines = [
        "UnrealAssetTool focused Gameplay Ability System evidence capture",
        "diagnostic_only: True",
        "semantic_promotion: False",
        "runtime_state_captured: False",
        f"assets_considered: {int(counts.get('assets_considered', 0) or 0)}",
        f"candidate_assets: {len(assets)}",
        f"loaded_assets: {int(counts.get('loaded_assets', 0) or 0)}",
        f"gas_classes: {len(classes)}",
        f"gas_properties: {len(properties)}",
        f"gas_references: {len(references)}",
        f"nested_objects: {int(counts.get('nested_objects', 0) or 0)}",
        f"truncated_properties: {sum(int(bool(row.get('truncated', False))) for row in properties)}",
    ]

    lines.append("")
    lines.extend(_counter_lines(
        "[asset kinds]",
        collections.Counter(str(row.get("gas_kind", "") or "<blank>") for row in assets),
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[class kinds]",
        collections.Counter(str(row.get("gas_kind", "") or "<blank>") for row in classes),
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[property owner kinds]",
        collections.Counter(str(row.get("owner_kind", "") or "<blank>") for row in properties),
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[top property names]",
        collections.Counter(str(row.get("property_name", "") or "<blank>") for row in properties),
        30,
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[top property cpp types]",
        collections.Counter(str(row.get("cpp_type", "") or "<blank>") for row in properties),
        20,
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[reference roots]",
        collections.Counter(str(row.get("root_property", "") or "<blank>") for row in references),
        24,
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[reference target classes]",
        collections.Counter(str(row.get("target_class", "") or "<soft/unknown>") for row in references),
        20,
    ))

    if assets:
        lines.extend((
            "",
            "[sample assets]",
            "first: " + " | ".join(
                f"{field}={_short(assets[0].get(field, ''))}"
                for field in ("asset_path", "gas_kind", "asset_class", "parent_class_tag", "generated_class", "loaded")
            ),
            "last: " + " | ".join(
                f"{field}={_short(assets[-1].get(field, ''))}"
                for field in ("asset_path", "gas_kind", "asset_class", "parent_class_tag", "generated_class", "loaded")
            ),
        ))
    if classes:
        lines.extend((
            "",
            "[sample classes]",
            "first: " + " | ".join(
                f"{field}={_short(classes[0].get(field, ''))}"
                for field in ("class_path", "gas_kind", "super_class", "native", "cdo_path")
            ),
            "last: " + " | ".join(
                f"{field}={_short(classes[-1].get(field, ''))}"
                for field in ("class_path", "gas_kind", "super_class", "native", "cdo_path")
            ),
        ))
    if references:
        lines.extend((
            "",
            "[sample references]",
            "first: " + " | ".join(
                f"{field}={_short(references[0].get(field, ''))}"
                for field in ("source_path", "owner_kind", "root_property", "property_path", "reference_kind", "target_path", "target_class")
            ),
            "last: " + " | ".join(
                f"{field}={_short(references[-1].get(field, ''))}"
                for field in ("source_path", "owner_kind", "root_property", "property_path", "reference_kind", "target_path", "target_class")
            ),
        ))
    return "\n".join(lines) + "\n"


def _capture_cli(runtime_module, core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool gas-capture",
        description=(
            "run a focused AssetRegistry+reflection Gameplay Ability System evidence pass; "
            "does not run the normal scan or derive pipeline"
        ),
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument("--no-build", action="store_true", help="reuse already-built plugin module")
    parser.add_argument("--output", help="focused capture directory")
    parser.add_argument("--archive", help="focused capture ZIP")
    parser.add_argument("--report", help="semantic inspection report path")
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    editor = core_module.require_editor(args.editor)
    output = _resolve_output(project, args.output)
    archive = _resolve_archive(project, args.archive)
    report_path = _resolve_report(project, args.report)

    if output.exists():
        print(f"removing previous focused GAS capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    overall_started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(
            project,
            editor,
            args.build_script,
            args.no_build,
            active_root,
        )
        command = [
            str(editor),
            str(project),
            "-run=UnrealAssetToolGAS",
            f"-Output={output}",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-UTF8Output",
        ]
        print("running focused GAS capture:", subprocess.list2cmdline(command))
        started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"focused GAS editor elapsed: {time.perf_counter() - started:.2f}s")

    # Preserve the raw focused artifact even when a later invariant rejects it.
    _write_archive(output, archive)
    print(f"focused GAS raw archive: {archive}")
    if result != 0:
        raise RuntimeError(f"focused GAS editor commandlet failed with exit code {result}; raw archive preserved")

    manifest = _validate_capture(output)
    report = _semantic_report(output, manifest)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")
    print(f"focused GAS report: {report_path}")
    print(f"focused GAS total elapsed: {time.perf_counter() - overall_started:.2f}s")
    print("normal project scan was not run")
    print("derive was not run")
    return 0


def install(runtime_module, core_module) -> None:
    if getattr(runtime_module, "_gas_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "gas-capture":
            try:
                return _capture_cli(runtime_module, core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 43
        return original_main()

    runtime_module.main = main
    runtime_module._gas_capture_installed = True
