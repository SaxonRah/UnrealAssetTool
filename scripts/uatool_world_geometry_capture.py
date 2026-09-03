#!/usr/bin/env python3
"""Focused UE 5.8 Landscape / Foliage / HLOD authored capture."""
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
    "world_geometry_capture_manifest.json",
    "landscape_roots.jsonl",
    "landscape_components.jsonl",
    "landscape_weightmap_allocations.jsonl",
    "landscape_layer_infos.jsonl",
    "landscape_grass_types.jsonl",
    "landscape_grass_varieties.jsonl",
    "foliage_types.jsonl",
    "foliage_actors.jsonl",
    "foliage_actor_type_infos.jsonl",
    "foliage_instances.jsonl",
    "hlod_layers.jsonl",
    "world_geometry_properties.jsonl",
)

COUNT_FILES = {
    "landscape_roots": "landscape_roots.jsonl",
    "landscape_components": "landscape_components.jsonl",
    "landscape_weightmap_allocations": "landscape_weightmap_allocations.jsonl",
    "landscape_layer_infos": "landscape_layer_infos.jsonl",
    "landscape_grass_types": "landscape_grass_types.jsonl",
    "landscape_grass_varieties": "landscape_grass_varieties.jsonl",
    "foliage_types": "foliage_types.jsonl",
    "foliage_actors": "foliage_actors.jsonl",
    "foliage_actor_type_infos": "foliage_actor_type_infos.jsonl",
    "foliage_instances": "foliage_instances.jsonl",
    "hlod_layers": "hlod_layers.jsonl",
    "property_rows": "world_geometry_properties.jsonl",
}

EXACT_ROOT_CLASSES = {
    "/Script/Landscape.Landscape",
    "/Script/Landscape.LandscapeStreamingProxy",
}
FOLIAGE_TYPE_CLASS = "/Script/Foliage.FoliageType_InstancedStaticMesh"
FOLIAGE_ACTOR_CLASS = "/Script/Foliage.InstancedFoliageActor"
HLOD_LAYER_CLASS = "/Script/Engine.HLODLayer"


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
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "world-geometry-native-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.world-geometry-native-capture.zip"


def _resolve_report(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.world-geometry-native-capture.txt"


def _manifest(output: Path) -> dict:
    path = output / "world_geometry_capture_manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid world_geometry_capture_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("world_geometry_capture_manifest.json root is not an object")
    return value


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"world-geometry capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _unique(rows: list[dict], fields: tuple[str, ...], label: str) -> None:
    seen = set()
    for row in rows:
        key = tuple(row.get(field) for field in fields)
        if key in seen:
            raise RuntimeError(f"duplicate {label} identity: {key}")
        seen.add(key)


def validate_capture(output: Path) -> dict:
    output = Path(output)
    manifest = _manifest(output)
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(f"world-geometry capture expected manifest schema 1, got {manifest.get('schema_version')}")
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"world-geometry capture failed: {manifest.get('error', '')}")
    if not bool(manifest.get("diagnostic_only", False)):
        raise RuntimeError("world-geometry capture must remain diagnostic_only=true")
    if bool(manifest.get("semantic_promotion", True)) or bool(manifest.get("schema_promotion", True)):
        raise RuntimeError("world-geometry capture must not promote semantic/schema state")
    for key in (
        "runtime_state_captured",
        "generated_geometry_captured",
        "render_resources_captured",
        "world_runtime_streaming_state_captured",
        "maps_loaded",
    ):
        if bool(manifest.get(key, True)):
            raise RuntimeError(f"world-geometry capture contract requires {key}=false")

    loaded = {name: list(_rows(output / filename)) for name, filename in COUNT_FILES.items()}
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    for key, rows in loaded.items():
        if int(counts.get(key, -1)) != len(rows):
            raise RuntimeError(f"world-geometry count mismatch for {key}: manifest={counts.get(key)} actual={len(rows)}")
    if int(counts.get("load_failures", -1)) != 0:
        raise RuntimeError("world-geometry capture reports asset load failures")

    roots = loaded["landscape_roots"]
    layer_infos = loaded["landscape_layer_infos"]
    grass_types = loaded["landscape_grass_types"]
    foliage_types = loaded["foliage_types"]
    foliage_actors = loaded["foliage_actors"]
    hlod_layers = loaded["hlod_layers"]
    primary_count = len(roots) + len(layer_infos) + len(grass_types) + len(foliage_types) + len(foliage_actors) + len(hlod_layers)
    if int(counts.get("registry_candidates", -1)) != primary_count:
        raise RuntimeError(
            f"world-geometry registry candidate mismatch: manifest={counts.get('registry_candidates')} primary_rows={primary_count}"
        )

    for row in roots:
        if str(row.get("class_path", "")) not in EXACT_ROOT_CLASSES:
            raise RuntimeError("world-geometry capture contains non-Landscape root class")
    for row in foliage_types:
        if str(row.get("class_path", "")) != FOLIAGE_TYPE_CLASS:
            raise RuntimeError("world-geometry capture contains non-FoliageType class")
    for row in foliage_actors:
        if str(row.get("class_path", "")) != FOLIAGE_ACTOR_CLASS:
            raise RuntimeError("world-geometry capture contains non-InstancedFoliageActor class")
    for row in hlod_layers:
        if str(row.get("class_path", "")) != HLOD_LAYER_CLASS:
            raise RuntimeError("world-geometry capture contains non-HLODLayer class")

    _unique(roots, ("landscape_path",), "Landscape root")
    _unique(loaded["landscape_components"], ("landscape_path", "component_index"), "Landscape component")
    _unique(loaded["landscape_weightmap_allocations"], ("component_path", "allocation_index"), "Landscape weightmap allocation")
    _unique(layer_infos, ("layer_info_path",), "Landscape layer info")
    _unique(grass_types, ("grass_type_path",), "Landscape grass type")
    _unique(loaded["landscape_grass_varieties"], ("grass_type_path", "variety_index"), "Landscape grass variety")
    _unique(foliage_types, ("foliage_type_path",), "FoliageType")
    _unique(foliage_actors, ("foliage_actor_path",), "InstancedFoliageActor")
    _unique(loaded["foliage_actor_type_infos"], ("foliage_actor_path", "map_index"), "foliage actor type info")
    _unique(loaded["foliage_instances"], ("foliage_actor_path", "map_index", "instance_index"), "foliage instance")
    _unique(hlod_layers, ("hlod_layer_path",), "HLODLayer")
    _unique(loaded["property_rows"], ("owner_path", "property_name"), "world-geometry property")
    return manifest


def _short(value: object, limit: int = 1800) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def semantic_report(output: Path, manifest: dict) -> str:
    output = Path(output)
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    roots = list(_rows(output / "landscape_roots.jsonl"))
    components = list(_rows(output / "landscape_components.jsonl"))
    allocations = list(_rows(output / "landscape_weightmap_allocations.jsonl"))
    layer_infos = list(_rows(output / "landscape_layer_infos.jsonl"))
    grass_types = list(_rows(output / "landscape_grass_types.jsonl"))
    grass_varieties = list(_rows(output / "landscape_grass_varieties.jsonl"))
    foliage_types = list(_rows(output / "foliage_types.jsonl"))
    foliage_actors = list(_rows(output / "foliage_actors.jsonl"))
    foliage_infos = list(_rows(output / "foliage_actor_type_infos.jsonl"))
    foliage_instances = list(_rows(output / "foliage_instances.jsonl"))
    hlod_layers = list(_rows(output / "hlod_layers.jsonl"))
    properties = list(_rows(output / "world_geometry_properties.jsonl"))

    root_classes = collections.Counter(str(row.get("class_path", "")) for row in roots)
    property_names = collections.Counter(
        (str(row.get("family", "")), str(row.get("role", "")), str(row.get("property_name", "")))
        for row in properties
    )
    allocation_structs = collections.Counter(str(row.get("struct_type", "")) for row in allocations)
    foliage_info_structs = collections.Counter(str(row.get("info_struct", "")) for row in foliage_infos)
    foliage_instance_structs = collections.Counter(str(row.get("instance_struct", "")) for row in foliage_instances)
    foliage_type_meshes = sum(bool(row.get("mesh_path")) for row in foliage_types)
    hlod_parent_refs = sum(bool(row.get("parentlayer_path")) for row in hlod_layers)
    hlod_linked_refs = sum(bool(row.get("linkedlayer_path")) for row in hlod_layers)
    hlod_builder_refs = sum(bool(row.get("hlodbuildersettings_path")) for row in hlod_layers)
    heightmap_refs = sum(bool(row.get("heightmap_texture_path")) for row in components)
    weightmap_texture_refs = sum(len(row.get("weightmap_textures", [])) for row in components if isinstance(row.get("weightmap_textures"), list))

    lines = [
        "=== LANDSCAPE / FOLIAGE / HLOD NATIVE AUTHORED CAPTURE ===",
        str(output),
        "diagnostic_only=True semantic_promotion=False schema_promotion=False",
        "runtime_state_captured=False generated_geometry_captured=False render_resources_captured=False world_runtime_streaming_state_captured=False maps_loaded=False",
        "",
        "[Counts]",
    ]
    for key in sorted(counts):
        lines.append(f"  {key}: {counts[key]}")
    lines.extend((
        "",
        "[High-value authored evidence]",
        f"  landscape_heightmap_texture_refs: {heightmap_refs}",
        f"  landscape_weightmap_texture_refs: {weightmap_texture_refs}",
        f"  foliage_types_with_mesh_ref: {foliage_type_meshes}",
        f"  foliage_infos_with_reflected_instance_array: {sum(bool(row.get('instances_reflected_as_struct_array')) for row in foliage_infos)}",
        f"  hlod_parent_layer_refs: {hlod_parent_refs}",
        f"  hlod_linked_layer_refs: {hlod_linked_refs}",
        f"  hlod_builder_settings_refs: {hlod_builder_refs}",
    ))

    def counter(title: str, values) -> None:
        lines.extend(("", f"[{title}]"))
        values = collections.Counter(values)
        if not values:
            lines.append("  <none>")
        for value, count in values.most_common(120):
            lines.append(f"  {count:7d}  {value}")

    counter("Landscape root classes", root_classes)
    counter("Landscape weightmap allocation structs", allocation_structs)
    counter("Foliage info structs", foliage_info_structs)
    counter("Foliage instance structs", foliage_instance_structs)
    counter("Captured property names", {f"{family}/{role}/{name}": count for (family, role, name), count in property_names.items()})

    def examples(title: str, rows: list[dict], limit: int = 80) -> None:
        lines.extend(("", f"[{title}]"))
        if not rows:
            lines.append("  <none>")
            return
        for row in rows[:limit]:
            lines.append("  " + _short(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))

    examples("Landscape roots", roots)
    examples("Landscape components", components)
    examples("Landscape weightmap allocations", allocations)
    examples("Landscape layer infos", layer_infos)
    examples("Landscape grass types", grass_types)
    examples("Landscape grass varieties", grass_varieties)
    examples("Foliage types", foliage_types)
    examples("Foliage actors", foliage_actors)
    examples("Foliage actor type infos", foliage_infos)
    examples("Foliage instances", foliage_instances)
    examples("HLOD layers", hlod_layers)
    examples("Selected/direct property rows", properties)

    lines.extend((
        "",
        "[Assessment]",
        "  Landscape root/component/texture/allocation rows are authored loaded-object evidence; no heightfield vertex/render buffers are captured.",
        "  LandscapeLayerInfo and LandscapeGrassType remain independent asset-owned authoring and must not be inferred from Landscape material/package dependencies.",
        "  FoliageType settings and mesh references are asset-owned; InstancedFoliageActor info/instance rows are accepted as placement evidence only when the reflected serialized editor container is structurally visible.",
        "  If foliage_info_maps_opaque is nonzero, do not substitute FoliageInstancedStaticMeshComponent transforms for missing authored foliage-info topology.",
        "  HLODLayer properties/references describe authored policy only; generated proxy meshes/cells and hlod_relevant descriptor flags are not HLOD composition truth.",
        "===============================================================",
    ))
    return "\n".join(lines) + "\n"


def _capture_cli(core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool landscape-foliage-hlod-capture",
        description="capture exact UE 5.8 authored Landscape/Foliage/HLOD state without render/generated/runtime geometry",
    )
    parser.add_argument("project", help="path to the UE 5.8 .uproject used to host the commandlet")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument("--no-build", action="store_true", help="reuse already-built plugin module")
    parser.add_argument("--include-engine", action="store_true", help="also inspect matching engine/plugin candidates outside project content")
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
        print(f"removing previous world-geometry native capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(project, editor, args.build_script, args.no_build, active_root)
        command = [
            str(editor), str(project), "-run=UnrealAssetToolWorldGeometry", f"-Output={output}",
            "-unattended", "-nop4", "-nosplash", "-nullrhi", "-nosound", "-UTF8Output",
        ]
        if args.include_engine:
            command.append("-IncludeEngine")
        print("world-geometry capture:", subprocess.list2cmdline(command))
        result = subprocess.run(command, cwd=str(project.parent))
        if result.returncode:
            if all((output / filename).is_file() for filename in CAPTURE_FILES):
                _write_archive(output, archive)
                print(f"raw world-geometry capture archive preserved after commandlet failure: {archive}")
            raise RuntimeError(f"UnrealAssetToolWorldGeometry commandlet failed with exit code {result.returncode}")

    try:
        manifest = validate_capture(output)
        _write_archive(output, archive)
        text = semantic_report(output, manifest)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text, encoding="utf-8", newline="\n")
    except Exception:
        if all((output / filename).is_file() for filename in CAPTURE_FILES):
            _write_archive(output, archive)
            print(f"raw world-geometry capture archive preserved after validation failure: {archive}")
        raise

    print(text, end="")
    print(f"world-geometry capture archive: {archive}")
    print(f"world-geometry capture report: {report_path}")
    print(f"world-geometry capture elapsed: {time.perf_counter() - started:.2f}s")
    return 0


def _report_cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool landscape-foliage-hlod-capture-report",
        description="validate and report an existing focused world-geometry capture without launching Unreal",
    )
    parser.add_argument("output", help="existing focused capture directory")
    parser.add_argument("--report", help="optional report output path")
    args = parser.parse_args(argv)
    output = Path(args.output).expanduser().resolve()
    if not output.is_dir():
        raise FileNotFoundError(f"capture directory does not exist: {output}")
    manifest = validate_capture(output)
    text = semantic_report(output, manifest)
    if args.report:
        target = Path(args.report).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote world-geometry capture report: {target}")
    print(text, end="")
    return 0


def install(runtime_module, core_module) -> None:
    if getattr(runtime_module, "_world_geometry_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "landscape-foliage-hlod-capture":
            try:
                return _capture_cli(core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 69
        if len(sys.argv) > 1 and sys.argv[1] == "landscape-foliage-hlod-capture-report":
            try:
                return _report_cli(sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 69
        return original_main()

    runtime_module.main = main
    runtime_module._world_geometry_capture_installed = True
