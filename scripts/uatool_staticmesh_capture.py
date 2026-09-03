#!/usr/bin/env python3
"""Focused UE 5.8 StaticMesh authored-topology capture."""
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
    "staticmesh_capture_manifest.json",
    "staticmesh_assets.jsonl",
    "staticmesh_source_models.jsonl",
    "staticmesh_materials.jsonl",
    "staticmesh_sockets.jsonl",
    "staticmesh_body_setups.jsonl",
    "staticmesh_collision_shapes.jsonl",
    "staticmesh_properties.jsonl",
)
STATIC_MESH_CLASS = "/Script/Engine.StaticMesh"


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
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "staticmesh-native-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.staticmesh-native-capture.zip"


def _resolve_report(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.staticmesh-native-capture.txt"


def _manifest(output: Path) -> dict:
    path = output / "staticmesh_capture_manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid staticmesh_capture_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("staticmesh_capture_manifest.json root is not an object")
    return value


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"StaticMesh capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _unique(rows: list[dict], fields: tuple[str, ...], label: str) -> None:
    seen = set()
    for row in rows:
        key = tuple(row.get(field) for field in fields)
        if key in seen:
            raise RuntimeError(f"duplicate {label} identity: {key}")
        seen.add(key)


def _validate_unreal_path_order(paths: list[str]) -> None:
    """Validate the case-insensitive ordering used by Unreal object/package paths."""
    if not paths or any(not path for path in paths):
        raise RuntimeError("StaticMesh asset rows must be non-empty")
    folded = [path.casefold() for path in paths]
    if len(set(folded)) != len(folded):
        raise RuntimeError("StaticMesh asset rows contain duplicate case-insensitive object paths")
    if folded != sorted(folded):
        raise RuntimeError("StaticMesh asset rows are not in Unreal case-insensitive path order")


def validate_capture(output: Path) -> dict:
    output = Path(output)
    manifest = _manifest(output)
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(f"StaticMesh capture expected manifest schema 1, got {manifest.get('schema_version')}")
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"StaticMesh capture failed: {manifest.get('error', '')}")
    if not bool(manifest.get("diagnostic_only", False)):
        raise RuntimeError("StaticMesh capture must remain diagnostic_only=true")
    if bool(manifest.get("semantic_promotion", True)) or bool(manifest.get("schema_promotion", True)):
        raise RuntimeError("StaticMesh capture must not promote semantic/schema state")
    for key in ("runtime_state_captured", "render_buffers_captured", "nanite_resources_captured", "runtime_physics_state_captured", "maps_loaded"):
        if bool(manifest.get(key, True)):
            raise RuntimeError(f"StaticMesh capture contract requires {key}=false")

    assets = list(_rows(output / "staticmesh_assets.jsonl"))
    source_models = list(_rows(output / "staticmesh_source_models.jsonl"))
    materials = list(_rows(output / "staticmesh_materials.jsonl"))
    sockets = list(_rows(output / "staticmesh_sockets.jsonl"))
    bodies = list(_rows(output / "staticmesh_body_setups.jsonl"))
    shapes = list(_rows(output / "staticmesh_collision_shapes.jsonl"))
    properties = list(_rows(output / "staticmesh_properties.jsonl"))

    paths = [str(row.get("static_mesh_path", "") or "") for row in assets]
    _validate_unreal_path_order(paths)
    asset_set = set(paths)
    for row in assets:
        if str(row.get("class_path", "") or "") != STATIC_MESH_CLASS:
            raise RuntimeError("StaticMesh capture contains a non-focus asset class")
    for rows, label in ((source_models, "source model"), (materials, "material"), (sockets, "socket"), (bodies, "body setup"), (shapes, "collision shape"), (properties, "property")):
        for row in rows:
            if str(row.get("static_mesh_path", "") or "") not in asset_set:
                raise RuntimeError(f"StaticMesh {label} row has unresolved asset")

    _unique(source_models, ("static_mesh_path", "lod_index"), "source model")
    _unique(materials, ("static_mesh_path", "material_index"), "material")
    _unique(sockets, ("static_mesh_path", "socket_index"), "socket")
    _unique(bodies, ("static_mesh_path", "body_setup_path"), "body setup")
    _unique(shapes, ("static_mesh_path", "body_setup_path", "shape_type", "shape_index"), "collision shape")
    _unique(properties, ("static_mesh_path", "property_name"), "selected property")

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    physical = {
        "registry_candidates": len(assets),
        "static_meshes": len(assets),
        "source_models": len(source_models),
        "materials": len(materials),
        "sockets": len(sockets),
        "body_setups": len(bodies),
        "collision_shapes": len(shapes),
        "selected_properties": len(properties),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            raise RuntimeError(f"StaticMesh count mismatch for {key}: manifest={counts.get(key)} actual={actual}")
    if int(counts.get("load_failures", -1)) != 0:
        raise RuntimeError("StaticMesh capture reports asset load failures")
    return manifest


def _short(value: object, limit: int = 1800) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def semantic_report(output: Path, manifest: dict) -> str:
    output = Path(output)
    assets = list(_rows(output / "staticmesh_assets.jsonl"))
    source_models = list(_rows(output / "staticmesh_source_models.jsonl"))
    materials = list(_rows(output / "staticmesh_materials.jsonl"))
    sockets = list(_rows(output / "staticmesh_sockets.jsonl"))
    bodies = list(_rows(output / "staticmesh_body_setups.jsonl"))
    shapes = list(_rows(output / "staticmesh_collision_shapes.jsonl"))
    properties = list(_rows(output / "staticmesh_properties.jsonl"))
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}

    source_by_mesh = collections.Counter(str(row.get("static_mesh_path", "")) for row in source_models)
    material_by_mesh = collections.Counter(str(row.get("static_mesh_path", "")) for row in materials)
    shape_by_mesh = collections.Counter(str(row.get("static_mesh_path", "")) for row in shapes)
    socket_by_mesh = collections.Counter(str(row.get("static_mesh_path", "")) for row in sockets)
    property_names = collections.Counter(str(row.get("property_name", "")) for row in properties)
    shape_types = collections.Counter(str(row.get("shape_type", "")) for row in shapes)

    lod_mismatches = []
    material_mismatches = []
    collision_mismatches = []
    for row in assets:
        path = str(row.get("static_mesh_path", ""))
        registry_lods = int(row.get("registry_lod_count", 0) or 0)
        registry_materials = int(row.get("registry_material_count", 0) or 0)
        registry_collision = int(row.get("registry_collision_prim_count", 0) or 0)
        if registry_lods != source_by_mesh[path]:
            lod_mismatches.append((path, registry_lods, source_by_mesh[path]))
        if registry_materials != material_by_mesh[path]:
            material_mismatches.append((path, registry_materials, material_by_mesh[path]))
        if registry_collision != shape_by_mesh[path]:
            collision_mismatches.append((path, registry_collision, shape_by_mesh[path]))

    lines = [
        "=== STATICMESH NATIVE AUTHORED CAPTURE ===",
        str(output),
        "diagnostic_only=True semantic_promotion=False schema_promotion=False",
        "runtime_state_captured=False render_buffers_captured=False nanite_resources_captured=False runtime_physics_state_captured=False maps_loaded=False",
        "",
        "[Counts]",
    ]
    for key in sorted(counts):
        lines.append(f"  {key}: {counts[key]}")
    lines.extend((
        "",
        "[Cross-checks against Asset Registry summary tags]",
        f"  lod_count_mismatches: {len(lod_mismatches)}",
        f"  material_count_mismatches: {len(material_mismatches)}",
        f"  collision_prim_count_mismatches: {len(collision_mismatches)}",
        f"  meshes_with_sockets: {sum(1 for value in socket_by_mesh.values() if value > 0)}",
        f"  meshes_with_body_setup: {len(bodies)}",
        "",
        "[Collision shape types]",
    ))
    if shape_types:
        for name, count in shape_types.most_common():
            lines.append(f"  {count:6d}  {name}")
    else:
        lines.append("  <none>")

    lines.extend(("", "[Selected authored properties]"))
    if property_names:
        for name, count in property_names.most_common():
            lines.append(f"  {count:6d}  {name}")
    else:
        lines.append("  <none>")

    for title, values in (
        ("LOD count mismatches", lod_mismatches),
        ("Material count mismatches", material_mismatches),
        ("Collision primitive count mismatches", collision_mismatches),
    ):
        lines.extend(("", f"[{title}]"))
        if not values:
            lines.append("  <none>")
        for path, registry, captured in values[:100]:
            lines.append(f"  {path} :: registry={registry} captured={captured}")

    def examples(title: str, rows: list[dict], limit: int = 80) -> None:
        lines.extend(("", f"[{title}]"))
        if not rows:
            lines.append("  <none>")
            return
        for row in rows[:limit]:
            lines.append("  " + _short(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))

    examples("Representative multi-LOD meshes", [row for row in assets if int(row.get("registry_lod_count", 0) or 0) > 1])
    examples("Representative Nanite-enabled meshes", [row for row in assets if bool(row.get("registry_nanite_enabled", False))])
    examples("Source model rows", source_models)
    examples("Material slot rows", materials)
    examples("Socket rows", sockets)
    examples("BodySetup rows", bodies)
    examples("Collision shape rows", shapes)
    examples("Selected property rows", properties)

    lines.extend((
        "",
        "[Assessment]",
        "  Registry tags are supporting summary evidence only; canonical promotion should use loaded authored source-model/material/socket/BodySetup/property rows.",
        "  If source-model rows match representative multi-LOD tag counts and expose stable BuildSettings/ReductionSettings, they are suitable for authored LOD normalization.",
        "  Static material rows are exact ordered slot ownership; component OverrideMaterials remain a separate world/Blueprint instance concern.",
        "  BodySetup/AggGeom rows describe authored simple collision only; cooked collision and runtime physics are deliberate non-claims.",
        "  SectionInfoMap/NaniteSettings may be normalized only from their authored property rows; do not infer sections from render data or Nanite resource counts.",
        "================================================",
    ))
    return "\n".join(lines) + "\n"


def _capture_cli(core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool staticmesh-capture",
        description="capture exact UE 5.8 StaticMesh authored source models/materials/sockets/collision/settings without maps/render buffers/runtime physics",
    )
    parser.add_argument("project", help="path to the UE 5.8 .uproject used to host the commandlet")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument("--no-build", action="store_true", help="reuse already-built plugin module")
    parser.add_argument("--include-engine", action="store_true", help="also capture exact engine/plugin StaticMesh assets outside the project directory")
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
        print(f"removing previous StaticMesh native capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    overall_started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(project, editor, args.build_script, args.no_build, active_root)
        command = [
            str(editor), str(project), "-run=UnrealAssetToolStaticMesh", f"-Output={output}",
            "-unattended", "-nop4", "-nosplash", "-nullrhi", "-nosound", "-UTF8Output",
        ]
        if args.include_engine:
            command.append("-IncludeEngine")
        print("running focused StaticMesh native capture:", subprocess.list2cmdline(command))
        started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"focused StaticMesh editor elapsed: {time.perf_counter() - started:.2f}s")

    if all((output / filename).is_file() for filename in CAPTURE_FILES):
        _write_archive(output, archive)
        print(f"focused StaticMesh raw archive: {archive}")
    if result != 0:
        raise RuntimeError(f"focused StaticMesh commandlet failed with exit code {result}; upload the raw archive if it was produced")

    manifest = validate_capture(output)
    report = semantic_report(output, manifest)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")
    print(f"focused StaticMesh report: {report_path}")
    print(f"focused StaticMesh total elapsed: {time.perf_counter() - overall_started:.2f}s")
    print("normal project/world/animation scan was not run")
    print("derive was not run")
    return 0


def _report_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool staticmesh-capture-report",
        description="validate and report an existing focused StaticMesh capture without launching Unreal",
    )
    parser.add_argument("output", help="existing staticmesh-native-capture directory")
    parser.add_argument("--report", help="report output path")
    parser.add_argument("--archive", help="optionally rebuild the raw capture ZIP")
    args = parser.parse_args(argv)

    output = Path(args.output).expanduser().resolve()
    if not output.is_dir():
        raise FileNotFoundError(f"StaticMesh capture directory does not exist: {output}")
    manifest = validate_capture(output)
    report = semantic_report(output, manifest)
    report_path = Path(args.report).expanduser().resolve() if args.report else output.parent / "StaticMesh.native-capture.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    if args.archive:
        archive = Path(args.archive).expanduser().resolve()
        _write_archive(output, archive)
        print(f"focused StaticMesh raw archive: {archive}")
    print(report, end="")
    print(f"focused StaticMesh report: {report_path}")
    print("Unreal was not launched")
    print("derive was not run")
    return 0


def install(runtime_module=None, core_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if core_module is None:
        import uatool_core as core_module
    if getattr(runtime_module, "_staticmesh_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "staticmesh-capture":
            try:
                return _capture_cli(core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 63
        if len(sys.argv) > 1 and sys.argv[1] == "staticmesh-capture-report":
            try:
                return _report_cli(sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 63
        return original_main()

    runtime_module.main = main
    runtime_module._staticmesh_capture_installed = True
