#!/usr/bin/env python3
"""Focused native SmartObjectDefinition reflection capture launcher."""
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
    "smartobject_capture_manifest.json",
    "smartobject_assets.jsonl",
    "smartobject_objects.jsonl",
    "smartobject_properties.jsonl",
    "smartobject_references.jsonl",
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
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "smartobject-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.smartobject-capture.zip"


def _resolve_report(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.smartobject-capture.txt"


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"focused Smart Object capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _read_manifest(output: Path) -> dict:
    path = output / "smartobject_capture_manifest.json"
    if not path.is_file():
        raise RuntimeError("focused Smart Object capture did not produce smartobject_capture_manifest.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid smartobject_capture_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("smartobject_capture_manifest.json root is not an object")
    return value


def _validate_capture(output: Path) -> dict:
    manifest = _read_manifest(output)
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(
            f"focused Smart Object capture expected manifest schema 1, got {manifest.get('schema_version')}"
        )
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"focused Smart Object capture failed: {manifest.get('error', '')}")
    if not bool(manifest.get("diagnostic_only", False)):
        raise RuntimeError("focused Smart Object manifest must remain diagnostic_only=true")
    if bool(manifest.get("semantic_promotion", True)):
        raise RuntimeError("focused Smart Object manifest must remain semantic_promotion=false")
    if bool(manifest.get("runtime_state_captured", True)):
        raise RuntimeError("focused Smart Object manifest must remain runtime_state_captured=false")

    assets = list(_rows(output / "smartobject_assets.jsonl"))
    objects = list(_rows(output / "smartobject_objects.jsonl"))
    properties = list(_rows(output / "smartobject_properties.jsonl"))
    references = list(_rows(output / "smartobject_references.jsonl"))

    asset_paths = [str(row.get("asset_path", "") or "") for row in assets]
    object_paths = [str(row.get("object_path", "") or "") for row in objects]
    if any(not value for value in asset_paths) or len(asset_paths) != len(set(asset_paths)):
        raise RuntimeError("focused Smart Object assets contain blank or duplicate asset_path rows")
    if any(not value for value in object_paths) or len(object_paths) != len(set(object_paths)):
        raise RuntimeError("focused Smart Object objects contain blank or duplicate object_path rows")

    asset_path_set = set(asset_paths)
    object_path_set = set(object_paths)
    for row in objects:
        if str(row.get("source_path", "") or "") not in asset_path_set:
            raise RuntimeError(f"focused Smart Object object has unresolved source: {row.get('source_path')}")
        if not str(row.get("object_kind", "") or "") or not str(row.get("object_class", "") or ""):
            raise RuntimeError(f"focused Smart Object object has blank kind/class: {row.get('object_path')}")

    for row in properties:
        source = str(row.get("source_path", "") or "")
        owner = str(row.get("owner_path", "") or "")
        path = str(row.get("property_path", "") or "")
        if source not in asset_path_set or owner not in object_path_set:
            raise RuntimeError(f"focused Smart Object property has unresolved source/owner: {path}")
        if not path or not str(row.get("root_property", "") or ""):
            raise RuntimeError("focused Smart Object property has blank path/root")

    for row in references:
        source = str(row.get("source_path", "") or "")
        owner = str(row.get("owner_path", "") or "")
        target = str(row.get("target_path", "") or "")
        if source not in asset_path_set or owner not in object_path_set:
            raise RuntimeError(f"focused Smart Object reference has unresolved source/owner: {row.get('property_path')}")
        if not target:
            raise RuntimeError("focused Smart Object reference has blank target_path")

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts", {}), dict) else {}
    physical = {
        "candidate_assets": len(assets),
        "smartobject_objects": len(objects),
        "smartobject_properties": len(properties),
        "smartobject_references": len(references),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            raise RuntimeError(
                f"focused Smart Object count mismatch for {key}: manifest={counts.get(key)} actual={actual}"
            )
    loaded = sum(int(bool(row.get("loaded", False))) for row in assets)
    definitions = sum(int(bool(row.get("is_definition", False))) for row in assets)
    nested = sum(int(str(row.get("object_kind", "")) == "nested_object") for row in objects)
    truncated = sum(int(bool(row.get("truncated", False))) for row in properties)
    expected = {
        "loaded_assets": loaded,
        "definition_assets": definitions,
        "nested_objects": nested,
        "truncated_properties": truncated,
    }
    for key, actual in expected.items():
        if int(counts.get(key, -1)) != actual:
            raise RuntimeError(
                f"focused Smart Object count mismatch for {key}: manifest={counts.get(key)} actual={actual}"
            )
    return manifest


def _short(value, limit: int = 260) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _counter_lines(label: str, counter: collections.Counter, limit: int = 24) -> list[str]:
    lines = [label]
    if not counter:
        lines.append("  <none>")
        return lines
    for value, count in counter.most_common(limit):
        lines.append(f"  {count:8d}  {_short(value)}")
    if len(counter) > limit:
        lines.append(f"  ... {len(counter) - limit} more distinct values")
    return lines


def _is_slot_row(row: dict) -> bool:
    root = str(row.get("root_property", "") or "").lower()
    path = str(row.get("property_path", "") or "").lower()
    cpp_type = str(row.get("cpp_type", "") or "").lower()
    return root == "slots" or path.startswith("slots[") or "smartobjectslot" in cpp_type


def _is_behavior_row(row: dict) -> bool:
    text = "\n".join(
        str(row.get(key, "") or "")
        for key in ("owner_class", "declaring_type", "property_name", "property_path", "cpp_type", "value")
    ).lower()
    return "behavior" in text or "smartobjectbehaviordefinition" in text


def _semantic_report(output: Path, manifest: dict) -> str:
    assets = list(_rows(output / "smartobject_assets.jsonl"))
    objects = list(_rows(output / "smartobject_objects.jsonl"))
    properties = list(_rows(output / "smartobject_properties.jsonl"))
    references = list(_rows(output / "smartobject_references.jsonl"))
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts", {}), dict) else {}

    definitions = [row for row in assets if bool(row.get("is_definition", False))]
    slot_rows = [row for row in properties if _is_slot_row(row)]
    behavior_rows = [row for row in properties if _is_behavior_row(row)]
    behavior_objects = [
        row for row in objects
        if "behavior" in str(row.get("object_class", "") or "").lower()
    ]
    behavior_refs = [
        row for row in references
        if "behavior" in (str(row.get("target_class", "") or "") + " " + str(row.get("property_path", "") or "")).lower()
    ]

    lines = [
        "UnrealAssetTool focused Smart Objects evidence capture",
        "diagnostic_only: True",
        "semantic_promotion: False",
        "runtime_state_captured: False",
        f"assets_considered: {int(counts.get('assets_considered', 0) or 0)}",
        f"candidate_assets: {len(assets)}",
        f"loaded_assets: {int(counts.get('loaded_assets', 0) or 0)}",
        f"definition_assets: {len(definitions)}",
        f"objects: {len(objects)}",
        f"nested_objects: {int(counts.get('nested_objects', 0) or 0)}",
        f"properties: {len(properties)}",
        f"references: {len(references)}",
        f"slot_property_rows: {len(slot_rows)}",
        f"behavior_property_rows: {len(behavior_rows)}",
        f"behavior_objects: {len(behavior_objects)}",
        f"behavior_references: {len(behavior_refs)}",
        f"truncated_properties: {int(counts.get('truncated_properties', 0) or 0)}",
        f"property_depth_limit_hits: {int(counts.get('property_depth_limit_hits', 0) or 0)}",
        f"property_row_limit_hits: {int(counts.get('property_row_limit_hits', 0) or 0)}",
        f"container_element_limit_hits: {int(counts.get('container_element_limit_hits', 0) or 0)}",
    ]

    lines.extend(("", "[definition assets]"))
    if definitions:
        lines.extend(f"  {row.get('asset_path', '')}" for row in definitions)
    else:
        lines.append("  <none>")

    lines.append("")
    lines.extend(_counter_lines(
        "[object classes]",
        collections.Counter(str(row.get("object_class", "") or "<blank>") for row in objects),
        32,
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[top root properties]",
        collections.Counter(str(row.get("root_property", "") or "<blank>") for row in properties),
        40,
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[slot property paths]",
        collections.Counter(str(row.get("property_path", "") or "<blank>") for row in slot_rows),
        80,
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[behavior property paths]",
        collections.Counter(str(row.get("property_path", "") or "<blank>") for row in behavior_rows),
        80,
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[reference target classes]",
        collections.Counter(str(row.get("target_class", "") or "<soft/unknown>") for row in references),
        32,
    ))

    lines.extend(("", "[capture assessment]"))
    if not definitions:
        lines.append("  BLOCKED: no loaded SmartObjectDefinition asset was proven by reflection.")
    elif not slot_rows:
        lines.append("  BLOCKED: definition loaded, but recursive reflection exposed no Smart Object slot rows.")
    else:
        lines.append("  PASS: recursive definition reflection exposed Smart Object slot structure.")
    if behavior_rows or behavior_objects or behavior_refs:
        lines.append("  PASS: behavior-definition evidence is present in definition-owned reflected state.")
    else:
        lines.append("  NOTE: no behavior-definition evidence was found in this definition; this may be authored data, not a capture failure.")
    if any(int(counts.get(key, 0) or 0) for key in (
        "property_depth_limit_hits", "property_row_limit_hits", "container_element_limit_hits"
    )):
        lines.append("  WARNING: one or more traversal limits were hit; acceptance must inspect the raw capture before normalization.")
    lines.append("  Boundary: authored/default definition state only; runtime claims, occupancy, reservations and subsystem handles were not captured.")

    return "\n".join(lines) + "\n"


def _capture_cli(core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool smartobject-capture",
        description=(
            "run a focused AssetRegistry+recursive-reflection SmartObjectDefinition evidence pass; "
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
        print(f"removing previous focused Smart Object capture: {output}")
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
            "-run=UnrealAssetToolSmartObject",
            f"-Output={output}",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-UTF8Output",
        ]
        print("running focused Smart Object capture:", subprocess.list2cmdline(command))
        started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"focused Smart Object editor elapsed: {time.perf_counter() - started:.2f}s")

    # Preserve the raw evidence before any Python-side acceptance invariant can reject it.
    _write_archive(output, archive)
    print(f"focused Smart Object raw archive: {archive}")
    if result != 0:
        raise RuntimeError(
            f"focused Smart Object editor commandlet failed with exit code {result}; raw archive preserved"
        )

    manifest = _validate_capture(output)
    report = _semantic_report(output, manifest)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")
    print(f"focused Smart Object report: {report_path}")
    print(f"focused Smart Object total elapsed: {time.perf_counter() - overall_started:.2f}s")
    print("normal project scan was not run")
    print("derive was not run")
    return 0


def install(runtime_module=None, core_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if core_module is None:
        import uatool_core as core_module
    if getattr(runtime_module, "_smartobject_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "smartobject-capture":
            try:
                return _capture_cli(core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 47
        return original_main()

    runtime_module.main = main
    runtime_module._smartobject_capture_installed = True
