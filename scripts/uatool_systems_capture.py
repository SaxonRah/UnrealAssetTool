#!/usr/bin/env python3
"""Isolated systems-only capture and offline capture diagnostics."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

CAPTURE_FILES = (
    "systems_manifest.json",
    "systems_assets.jsonl",
    "systems_properties.jsonl",
    "systems_references.jsonl",
    "mass_entity_configs.jsonl",
    "mass_entity_traits.jsonl",
    "mass_spawners.jsonl",
    "mass_spawner_entity_types.jsonl",
    "mass_spawner_generators.jsonl",
    "mass_spawn_generator_assets.jsonl",
    "mass_agent_components.jsonl",
    "zonegraph_shapes.jsonl",
    "zonegraph_shape_points.jsonl",
)

SCHEMA5_FILES = CAPTURE_FILES[4:]


def _resolve_project(value: str) -> Path:
    project = Path(value).expanduser().resolve()
    if not project.is_file() or project.suffix.lower() != ".uproject":
        raise FileNotFoundError(f"Unreal project does not exist: {project}")
    return project


def _resolve_output(project: Path, value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return project.parent / ".uatool" / "systems-schema5-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    if value:
        return Path(value).expanduser().resolve()
    return project.parent / ".uatool" / f"{project.stem}.systems-schema5-capture.zip"


def _write_capture_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive.unlink()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"systems capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _print_schema5_counts(output: Path) -> None:
    manifest_path = output / "systems_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    counts = manifest.get("counts", {}) if isinstance(manifest, dict) else {}
    keys = tuple(name.removesuffix(".jsonl") for name in SCHEMA5_FILES)
    print("systems schema 5 capture counts:")
    for key in keys:
        print(f"  {key}: {int(counts.get(key, 0) or 0)}")


def _capture_cli(runtime_module, core_module, systems_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool systems-capture",
        description=(
            "build/reuse UnrealAssetTool and run only the systems scanner; "
            "no world, animation, VFX, database pack, or derive"
        ),
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument(
        "--no-build",
        action="store_true",
        help="reuse the already-built staged plugin module without invoking UBT",
    )
    parser.add_argument(
        "--output",
        help="capture directory; defaults to <Project>/.uatool/systems-schema5-capture",
    )
    parser.add_argument(
        "--archive",
        help="output ZIP; defaults to <Project>/.uatool/<Project>.systems-schema5-capture.zip",
    )
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    editor = core_module.require_editor(args.editor)
    output = _resolve_output(project, args.output)
    archive = _resolve_archive(project, args.archive)

    if output.exists():
        print(f"removing previous isolated systems capture: {output}")
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
            "-UnrealAssetToolSystemsOnly",
            f"-Output={output}",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-UTF8Output",
        ]
        print("running isolated systems capture:", subprocess.list2cmdline(command))
        capture_started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"isolated systems editor elapsed: {time.perf_counter() - capture_started:.2f}s")

    manifest_path = output / "systems_manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            "isolated editor run did not produce systems_manifest.json; "
            f"editor exit code was {result}"
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid systems_manifest.json: {exc}") from exc
    if int(manifest.get("schema_version", 0) or 0) != 5:
        raise RuntimeError(
            f"isolated systems capture expected schema 5, got {manifest.get('schema_version')}"
        )
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"isolated systems capture failed: {manifest.get('error', '')}")

    # Preserve the raw native evidence before semantic/schema validation. If a
    # validator catches a malformed or unexpected real-corpus row, this archive
    # is still useful for diagnosis and avoids forcing another expensive capture
    # merely to share the failing files.
    _write_capture_archive(output, archive)
    print(f"raw systems capture archive: {archive}")

    error = systems_module.validation_error(output)
    if error:
        raise RuntimeError(
            "isolated systems capture validation failed: "
            f"{error}; raw archive preserved at {archive}"
        )

    _print_schema5_counts(output)
    print(f"systems capture archive: {archive}")
    print(f"systems capture total elapsed: {time.perf_counter() - overall_started:.2f}s")
    if result != 0:
        print(
            f"note: editor returned {result} after writing a valid systems capture; "
            "the validated manifest/archive are authoritative"
        )
    return 0


def _jsonl_diagnostic(data: bytes) -> dict:
    result = {
        "bytes": len(data),
        "valid_rows": 0,
        "nonblank_rows": 0,
        "error": "",
        "error_line": 0,
        "error_byte_offset": -1,
        "error_column": 0,
        "ends_with_newline": data.endswith(b"\n"),
        "tail_preview": "",
        "first_row": None,
        "last_valid_row": None,
    }
    offset = 0
    for line_number, raw_line in enumerate(data.splitlines(keepends=True), 1):
        body = raw_line.rstrip(b"\r\n")
        if not body:
            offset += len(raw_line)
            continue
        result["nonblank_rows"] += 1
        try:
            text = body.decode("utf-8", errors="strict")
            row = json.loads(text)
            if not isinstance(row, dict):
                raise ValueError("JSONL row root is not an object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            result["error"] = str(exc)
            result["error_line"] = line_number
            result["error_byte_offset"] = offset
            result["error_column"] = int(getattr(exc, "colno", 0) or 0)
            start = max(0, len(body) - 192)
            result["tail_preview"] = repr(body[start:])
            break
        result["valid_rows"] += 1
        if result["first_row"] is None:
            result["first_row"] = row
        result["last_valid_row"] = row
        offset += len(raw_line)
    return result


def _compact_row_identity(filename: str, row: dict | None) -> str:
    if not row:
        return "<none>"
    preferred = {
        "mass_entity_configs.jsonl": ("config_path", "parent_config_path", "trait_count"),
        "mass_entity_traits.jsonl": ("config_path", "trait_index", "trait_class"),
        "mass_spawners.jsonl": ("spawner_path", "entity_type_count", "spawn_generator_count"),
        "mass_spawner_entity_types.jsonl": ("spawner_path", "entity_type_index", "entity_config_path"),
        "mass_spawner_generators.jsonl": ("spawner_path", "generator_index", "generator_asset_path"),
        "mass_spawn_generator_assets.jsonl": ("generator_asset_path", "parent_class", "zonegraph_generator"),
        "mass_agent_components.jsonl": ("blueprint_path", "component_name", "entity_config_parent_path"),
        "zonegraph_shapes.jsonl": ("shape_path", "point_count", "shape_type"),
        "zonegraph_shape_points.jsonl": ("shape_path", "point_index", "point_type"),
    }.get(filename, ())
    if not preferred:
        preferred = tuple(list(row)[:3])
    parts = []
    for key in preferred:
        value = row.get(key, "")
        text = str(value)
        if len(text) > 160:
            text = text[:157] + "..."
        parts.append(f"{key}={text}")
    return " | ".join(parts)


def inspect_capture_archive(archive: Path) -> str:
    archive = Path(archive).expanduser().resolve()
    if not archive.is_file():
        raise FileNotFoundError(f"capture archive does not exist: {archive}")

    lines = [
        "UnrealAssetTool systems capture inspection",
        f"archive: {archive}",
        f"archive_bytes: {archive.stat().st_size}",
        "diagnostic_only: True",
        "semantic_promotion: False",
        "",
    ]

    with zipfile.ZipFile(archive, "r") as bundle:
        bad_crc = bundle.testzip()
        lines.append(f"zip_crc: {'OK' if bad_crc is None else 'FAILED ' + bad_crc}")
        members = {info.filename: info for info in bundle.infolist()}
        lines.append(f"members: {len(members)}")
        missing = [name for name in CAPTURE_FILES if name not in members]
        lines.append(f"missing_expected_members: {len(missing)}")
        for name in missing:
            lines.append(f"  MISSING {name}")

        manifest = {}
        if "systems_manifest.json" in members:
            try:
                manifest = json.loads(bundle.read("systems_manifest.json").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                lines.append(f"manifest_error: {exc}")
        counts = manifest.get("counts", {}) if isinstance(manifest, dict) else {}
        lines.extend([
            f"manifest_schema_version: {manifest.get('schema_version', '<missing>') if isinstance(manifest, dict) else '<invalid>'}",
            f"manifest_success: {manifest.get('success', '<missing>') if isinstance(manifest, dict) else '<invalid>'}",
            f"manifest_error: {manifest.get('error', '') if isinstance(manifest, dict) else ''}",
            "",
            "[JSONL integrity]",
        ])

        diagnostics = {}
        for filename in CAPTURE_FILES:
            if not filename.endswith(".jsonl") or filename not in members:
                continue
            info = members[filename]
            data = bundle.read(filename)
            diag = _jsonl_diagnostic(data)
            diagnostics[filename] = diag
            key = filename.removesuffix(".jsonl")
            declared = counts.get(key, "<undeclared>") if isinstance(counts, dict) else "<undeclared>"
            status = "OK" if not diag["error"] else "INVALID"
            lines.append(
                f"{filename}: {status} bytes={info.file_size} compressed={info.compress_size} "
                f"rows_valid={diag['valid_rows']} rows_nonblank={diag['nonblank_rows']} "
                f"declared={declared} newline={diag['ends_with_newline']} "
                f"size_mod_4096={info.file_size % 4096} size_mod_65536={info.file_size % 65536}"
            )
            if diag["error"]:
                lines.append(
                    f"  first_error: line={diag['error_line']} byte_offset={diag['error_byte_offset']} "
                    f"column={diag['error_column']} {diag['error']}"
                )
                lines.append(f"  tail_preview: {diag['tail_preview']}")

        lines.extend(["", "[Schema 5 manifest counts]"])
        for filename in SCHEMA5_FILES:
            key = filename.removesuffix(".jsonl")
            declared = counts.get(key, "<undeclared>") if isinstance(counts, dict) else "<undeclared>"
            diag = diagnostics.get(filename)
            physical = diag["valid_rows"] if diag else "<missing>"
            invalid = bool(diag and diag["error"])
            lines.append(
                f"{key}: declared={declared} valid_physical={physical} malformed_tail={invalid}"
            )

        lines.extend(["", "[Schema 5 surviving row identities]"])
        for filename in SCHEMA5_FILES:
            diag = diagnostics.get(filename)
            if not diag:
                lines.append(f"{filename}: <missing>")
                continue
            lines.append(f"{filename} first: {_compact_row_identity(filename, diag['first_row'])}")
            lines.append(f"{filename} last_valid: {_compact_row_identity(filename, diag['last_valid_row'])}")

        invalid_files = [name for name, diag in diagnostics.items() if diag["error"]]
        lines.extend([
            "",
            "[Summary]",
            f"jsonl_files_checked: {len(diagnostics)}",
            f"jsonl_files_invalid: {len(invalid_files)}",
        ])
        for name in invalid_files:
            lines.append(f"  INVALID {name}")

    return "\n".join(lines) + "\n"


def _write_console_safe(text: str) -> None:
    stream = sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    try:
        stream.write(text)
        stream.flush()
    except UnicodeEncodeError:
        if hasattr(stream, "buffer"):
            stream.buffer.write(text.encode(encoding, errors="backslashreplace"))
            stream.buffer.flush()
        else:
            stream.write(text.encode(encoding, errors="backslashreplace").decode(encoding, errors="strict"))
            stream.flush()


def _inspect_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool systems-capture-inspect",
        description="inspect an existing raw systems capture ZIP without Unreal, build, scan, or derive",
    )
    parser.add_argument("archive", help="systems capture ZIP")
    parser.add_argument("--report", type=Path, help="optional UTF-8 text report path")
    args = parser.parse_args(argv)
    rendered = inspect_capture_archive(Path(args.archive))
    if args.report:
        report = args.report.expanduser().resolve()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"systems capture inspection report: {report}")
    _write_console_safe(rendered)
    return 0


def install(runtime_module, core_module, systems_module) -> None:
    # Synthetic schema-unit-test objects also call the schema installer. Only
    # patch the real public systems module into the canonical runtime CLI.
    if getattr(systems_module, "__name__", "") != "uatool_systems":
        return
    if getattr(runtime_module, "_systems_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "systems-capture":
            try:
                return _capture_cli(runtime_module, core_module, systems_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 37
        if len(sys.argv) > 1 and sys.argv[1] == "systems-capture-inspect":
            try:
                return _inspect_cli(sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 38
        return original_main()

    runtime_module.main = main
    runtime_module._systems_capture_installed = True
