#!/usr/bin/env python3
"""Focused UE 5.8 SkeletalMesh / PhysicsAsset authored-topology capture."""
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
    "skeletalmesh_physicsasset_capture_manifest.json",
    "skeletalmesh_physicsasset_assets.jsonl",
    "skeletalmesh_physicsasset_asset_properties.jsonl",
    "skeletalmesh_physicsasset_asset_references.jsonl",
    "skeletalmesh_physicsasset_owned_objects.jsonl",
    "skeletalmesh_physicsasset_owned_object_properties.jsonl",
    "skeletalmesh_physicsasset_owned_object_references.jsonl",
)

SKELETAL_MESH_CLASS = "/Script/Engine.SkeletalMesh"
PHYSICS_ASSET_CLASS = "/Script/Engine.PhysicsAsset"

KEY_PROPERTY_TOKENS = (
    "skeleton",
    "physicsasset",
    "shadowphysicsasset",
    "lodinfo",
    "lodsettings",
    "materials",
    "materialslot",
    "morph",
    "cloth",
    "clothing",
    "socket",
    "bodysetup",
    "skeletalbodysetups",
    "agggeom",
    "sphereelem",
    "boxelem",
    "sphylelem",
    "capsule",
    "convexelem",
    "constraintsetup",
    "constraintbone",
    "defaultinstance",
    "collisiondisable",
    "physicalanimation",
    "profile",
)

KEY_CLASS_TOKENS = (
    "skeletalbodysetup",
    "physicsconstrainttemplate",
    "skeletalmeshsocket",
    "morphtarget",
    "clothingasset",
    "cloth",
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
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "skeletalmesh-physicsasset-native-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.skeletalmesh-physicsasset-native-capture.zip"


def _resolve_report(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.skeletalmesh-physicsasset-native-capture.txt"


def _manifest(output: Path) -> dict:
    path = output / "skeletalmesh_physicsasset_capture_manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid skeletalmesh_physicsasset_capture_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("skeletalmesh_physicsasset_capture_manifest.json root is not an object")
    return value


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"SkeletalMesh/PhysicsAsset capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def validate_capture(output: Path) -> dict:
    output = Path(output)
    manifest = _manifest(output)
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(f"SkeletalMesh/PhysicsAsset capture expected manifest schema 1, got {manifest.get('schema_version')}")
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"SkeletalMesh/PhysicsAsset capture failed: {manifest.get('error', '')}")
    if not bool(manifest.get("diagnostic_only", False)):
        raise RuntimeError("SkeletalMesh/PhysicsAsset capture must remain diagnostic_only=true")
    if bool(manifest.get("semantic_promotion", True)) or bool(manifest.get("schema_promotion", True)):
        raise RuntimeError("SkeletalMesh/PhysicsAsset capture must not promote semantic/schema state")
    for key in (
        "runtime_state_captured",
        "render_buffers_captured",
        "cloth_simulation_state_captured",
        "chaos_runtime_state_captured",
        "maps_loaded",
    ):
        if bool(manifest.get(key, True)):
            raise RuntimeError(f"SkeletalMesh/PhysicsAsset capture contract requires {key}=false")

    assets = list(_rows(output / "skeletalmesh_physicsasset_assets.jsonl"))
    asset_properties = list(_rows(output / "skeletalmesh_physicsasset_asset_properties.jsonl"))
    asset_references = list(_rows(output / "skeletalmesh_physicsasset_asset_references.jsonl"))
    owned = list(_rows(output / "skeletalmesh_physicsasset_owned_objects.jsonl"))
    owned_properties = list(_rows(output / "skeletalmesh_physicsasset_owned_object_properties.jsonl"))
    owned_references = list(_rows(output / "skeletalmesh_physicsasset_owned_object_references.jsonl"))

    asset_paths = [str(row.get("asset_path", "") or "") for row in assets]
    if not asset_paths or asset_paths != sorted(set(asset_paths)):
        raise RuntimeError("SkeletalMesh/PhysicsAsset assets must be non-empty, unique and sorted")
    asset_set = set(asset_paths)
    class_by_asset = {str(row.get("asset_path", "") or ""): str(row.get("class_path", "") or "") for row in assets}
    classes = set(class_by_asset.values())
    if not classes.issubset({SKELETAL_MESH_CLASS, PHYSICS_ASSET_CLASS}):
        raise RuntimeError("SkeletalMesh/PhysicsAsset capture contains a non-focus asset class")
    if SKELETAL_MESH_CLASS not in classes or PHYSICS_ASSET_CLASS not in classes:
        raise RuntimeError("representative capture must contain both SkeletalMesh and PhysicsAsset assets")
    for row in assets:
        if not bool(row.get("loaded", False)):
            raise RuntimeError("SkeletalMesh/PhysicsAsset asset row is not loaded")
        if str(row.get("loaded_class", "") or "") != str(row.get("class_path", "") or ""):
            raise RuntimeError("SkeletalMesh/PhysicsAsset loaded class differs from exact Asset Registry class")

    owned_paths = set()
    for row in owned:
        asset_path = str(row.get("asset_path", "") or "")
        object_path = str(row.get("object_path", "") or "")
        if asset_path not in asset_set or not object_path:
            raise RuntimeError("SkeletalMesh/PhysicsAsset owned object has unresolved asset/object identity")
        key = (asset_path, object_path)
        if key in owned_paths:
            raise RuntimeError("duplicate SkeletalMesh/PhysicsAsset owned object identity")
        owned_paths.add(key)

    for row in asset_properties:
        if str(row.get("asset_path", "") or "") not in asset_set:
            raise RuntimeError("SkeletalMesh/PhysicsAsset asset property has unresolved asset")
        if not str(row.get("property_path", "") or ""):
            raise RuntimeError("SkeletalMesh/PhysicsAsset asset property has blank property_path")
    for row in asset_references:
        if str(row.get("asset_path", "") or "") not in asset_set:
            raise RuntimeError("SkeletalMesh/PhysicsAsset asset reference has unresolved asset")
        if not str(row.get("target_path", "") or ""):
            raise RuntimeError("SkeletalMesh/PhysicsAsset asset reference has blank target_path")
    for row in owned_properties:
        key = (str(row.get("asset_path", "") or ""), str(row.get("owner_path", "") or ""))
        if key not in owned_paths:
            raise RuntimeError("SkeletalMesh/PhysicsAsset owned property has unresolved owner")
        if not str(row.get("property_path", "") or ""):
            raise RuntimeError("SkeletalMesh/PhysicsAsset owned property has blank property_path")
    for row in owned_references:
        key = (str(row.get("asset_path", "") or ""), str(row.get("owner_path", "") or ""))
        if key not in owned_paths:
            raise RuntimeError("SkeletalMesh/PhysicsAsset owned reference has unresolved owner")
        if not str(row.get("target_path", "") or ""):
            raise RuntimeError("SkeletalMesh/PhysicsAsset owned reference has blank target_path")

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    physical = {
        "loaded_assets": len(assets),
        "skeletal_meshes": sum(1 for row in assets if row.get("class_path") == SKELETAL_MESH_CLASS),
        "physics_assets": sum(1 for row in assets if row.get("class_path") == PHYSICS_ASSET_CLASS),
        "asset_properties": len(asset_properties),
        "asset_references": len(asset_references),
        "owned_objects": len(owned),
        "owned_object_properties": len(owned_properties),
        "owned_object_references": len(owned_references),
        "truncated_properties": sum(1 for row in (*asset_properties, *owned_properties) if bool(row.get("truncated", False))),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            raise RuntimeError(f"SkeletalMesh/PhysicsAsset count mismatch for {key}: manifest={counts.get(key)} actual={actual}")
    if int(counts.get("registry_candidates", -1)) != len(assets):
        raise RuntimeError("SkeletalMesh/PhysicsAsset registry candidate count must equal loaded asset rows")
    if int(counts.get("load_failures", -1)) != 0:
        raise RuntimeError("SkeletalMesh/PhysicsAsset capture reports asset load failures")
    return manifest


def _short(value: object, limit: int = 1200) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def semantic_report(output: Path, manifest: dict) -> str:
    output = Path(output)
    assets = list(_rows(output / "skeletalmesh_physicsasset_assets.jsonl"))
    asset_properties = list(_rows(output / "skeletalmesh_physicsasset_asset_properties.jsonl"))
    asset_references = list(_rows(output / "skeletalmesh_physicsasset_asset_references.jsonl"))
    owned = list(_rows(output / "skeletalmesh_physicsasset_owned_objects.jsonl"))
    owned_properties = list(_rows(output / "skeletalmesh_physicsasset_owned_object_properties.jsonl"))
    owned_references = list(_rows(output / "skeletalmesh_physicsasset_owned_object_references.jsonl"))
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}

    class_counts = collections.Counter(str(row.get("class_path", "") or "<blank>") for row in owned)
    key_classes = [(name, count) for name, count in class_counts.most_common() if any(token in name.lower() for token in KEY_CLASS_TOKENS)]
    key_asset_properties = [row for row in asset_properties if any(token in str(row.get("property_path", "") or "").lower() for token in KEY_PROPERTY_TOKENS)]
    key_owned_properties = [row for row in owned_properties if any(token in str(row.get("property_path", "") or "").lower() for token in KEY_PROPERTY_TOKENS)]
    key_references = [row for row in (*asset_references, *owned_references) if any(token in str(row.get("property_path", "") or "").lower() for token in KEY_PROPERTY_TOKENS)]

    lines = [
        "UnrealAssetTool focused UE 5.8 SkeletalMesh / PhysicsAsset authored-topology capture",
        "diagnostic_only: True",
        "semantic_promotion: False",
        "schema_promotion: False",
        "runtime_state_captured: False",
        "render_buffers_captured: False",
        "cloth_simulation_state_captured: False",
        "chaos_runtime_state_captured: False",
        "maps_loaded: False",
        f"registry_candidates: {int(counts.get('registry_candidates', 0) or 0)}",
        f"skeletal_meshes: {int(counts.get('skeletal_meshes', 0) or 0)}",
        f"physics_assets: {int(counts.get('physics_assets', 0) or 0)}",
        f"asset_properties: {len(asset_properties)}",
        f"asset_references: {len(asset_references)}",
        f"owned_objects: {len(owned)}",
        f"owned_object_properties: {len(owned_properties)}",
        f"owned_object_references: {len(owned_references)}",
        f"truncated_properties: {int(counts.get('truncated_properties', 0) or 0)}",
        f"property_depth_limit_hits: {int(counts.get('property_depth_limit_hits', 0) or 0)}",
        f"property_row_limit_hits: {int(counts.get('property_row_limit_hits', 0) or 0)}",
        f"container_element_limit_hits: {int(counts.get('container_element_limit_hits', 0) or 0)}",
        "",
        "[loaded assets and selected Asset Registry tags]",
    ]
    for row in assets:
        tags = row.get("registry_tags", {}) if isinstance(row.get("registry_tags"), dict) else {}
        tag_text = ", ".join(f"{key}={_short(value, 250)}" for key, value in sorted(tags.items())) or "<none>"
        lines.append(f"  {row.get('asset_kind','')} :: {row.get('asset_path','')} :: {tag_text}")

    lines.extend(("", "[owned object classes]"))
    for class_path, count in class_counts.most_common(200):
        lines.append(f"  {count:6d}  {class_path}")

    lines.extend(("", "[high-value owned object classes]"))
    if not key_classes:
        lines.append("  <none>")
    for class_path, count in key_classes:
        lines.append(f"  {count:6d}  {class_path}")

    lines.extend(("", "[high-value asset properties]"))
    if not key_asset_properties:
        lines.append("  <none>")
    for row in key_asset_properties[:1000]:
        lines.append(
            f"  {row.get('asset_path','')} :: {row.get('property_path','')} = {_short(row.get('value',''))}"
        )

    lines.extend(("", "[high-value owned-object properties]"))
    if not key_owned_properties:
        lines.append("  <none>")
    for row in key_owned_properties[:2000]:
        lines.append(
            f"  {row.get('owner_type','')} :: {row.get('owner_path','')} :: {row.get('property_path','')} = {_short(row.get('value',''))}"
        )

    lines.extend(("", "[high-value exact references]"))
    if not key_references:
        lines.append("  <none>")
    for row in key_references[:1000]:
        lines.append(
            f"  {row.get('owner_path','')} :: {row.get('property_path','')} -> {row.get('target_path','')} [{row.get('target_class','')}]"
        )

    lines.extend((
        "",
        "[capture assessment]",
        "  Asset Registry tags remain supporting evidence for counts/summary fields; reflected loaded-object and owned-object rows are the authority for topology promotion.",
        "  If body setups, constraint templates, sockets, morph targets and clothing objects appear as owned classes with stable authored fields, normalize those exact structures rather than parsing broad text dumps.",
        "  LOD/material/section semantics should be promoted only where stable authored properties or exact references identify them; render-resource buffers are intentionally absent.",
        "  Physics bodies/constraints must use exact reflected bone/end-point fields; never infer linkage from object names.",
        "  Use this report to decide the animation-schema-2 normalized streams and real-corpus acceptance minima.",
    ))
    return "\n".join(lines) + "\n"


def _capture_cli(core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool skeletalmesh-physicsasset-capture",
        description="capture exact UE 5.8 SkeletalMesh / PhysicsAsset authored properties and owned-object topology without maps/runtime simulation/render buffers",
    )
    parser.add_argument("project", help="path to the UE 5.8 .uproject used to host the commandlet")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument("--no-build", action="store_true", help="reuse already-built plugin module")
    parser.add_argument("--include-engine", action="store_true", help="also capture exact engine/plugin SkeletalMesh/PhysicsAsset assets outside the project directory")
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
        print(f"removing previous SkeletalMesh/PhysicsAsset native capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    overall_started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(project, editor, args.build_script, args.no_build, active_root)
        command = [
            str(editor),
            str(project),
            "-run=UnrealAssetToolSkeletalMeshPhysicsAsset",
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
        print("running focused SkeletalMesh/PhysicsAsset native capture:", subprocess.list2cmdline(command))
        started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"focused SkeletalMesh/PhysicsAsset editor elapsed: {time.perf_counter() - started:.2f}s")

    if all((output / filename).is_file() for filename in CAPTURE_FILES):
        _write_archive(output, archive)
        print(f"focused SkeletalMesh/PhysicsAsset raw archive: {archive}")
    if result != 0:
        raise RuntimeError(f"focused SkeletalMesh/PhysicsAsset commandlet failed with exit code {result}; upload the raw archive if it was produced")

    manifest = validate_capture(output)
    report = semantic_report(output, manifest)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")
    print(f"focused SkeletalMesh/PhysicsAsset report: {report_path}")
    print(f"focused SkeletalMesh/PhysicsAsset total elapsed: {time.perf_counter() - overall_started:.2f}s")
    print("normal project/world/animation scan was not run")
    print("derive was not run")
    return 0


def install(runtime_module=None, core_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if core_module is None:
        import uatool_core as core_module
    if getattr(runtime_module, "_skeletalmesh_physicsasset_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "skeletalmesh-physicsasset-capture":
            try:
                return _capture_cli(core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 61
        return original_main()

    runtime_module.main = main
    runtime_module._skeletalmesh_physicsasset_capture_installed = True
