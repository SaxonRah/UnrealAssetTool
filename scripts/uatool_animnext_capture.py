#!/usr/bin/env python3
"""Focused UE 5.8 capture of Epic's installed UAF plugin content."""
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
    "uaf_capture_manifest.json",
    "uaf_assets.jsonl",
    "uaf_asset_properties.jsonl",
    "uaf_asset_references.jsonl",
    "uaf_subobjects.jsonl",
    "uaf_subobject_properties.jsonl",
    "uaf_subobject_references.jsonl",
    "uaf_rigvm_graphs.jsonl",
    "uaf_rigvm_nodes.jsonl",
    "uaf_rigvm_pins.jsonl",
    "uaf_rigvm_links.jsonl",
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
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "animnext-uaf-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.animnext-uaf-capture.zip"


def _resolve_report(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.animnext-uaf-capture.txt"


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"focused UAF capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _manifest(output: Path) -> dict:
    path = output / "uaf_capture_manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid uaf_capture_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("uaf_capture_manifest.json root is not an object")
    return value


def validate_capture(output: Path) -> dict:
    manifest = _manifest(output)
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(f"focused UAF capture expected manifest schema 1, got {manifest.get('schema_version')}")
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"focused UAF capture failed: {manifest.get('error', '')}")
    if not bool(manifest.get("diagnostic_only", False)):
        raise RuntimeError("focused UAF capture must remain diagnostic_only=true")
    if bool(manifest.get("semantic_promotion", True)) or bool(manifest.get("schema_promotion", True)):
        raise RuntimeError("focused UAF capture must not promote semantic/schema state")
    if bool(manifest.get("runtime_state_captured", True)):
        raise RuntimeError("focused UAF capture must remain runtime_state_captured=false")

    assets = list(_rows(output / "uaf_assets.jsonl"))
    asset_properties = list(_rows(output / "uaf_asset_properties.jsonl"))
    asset_references = list(_rows(output / "uaf_asset_references.jsonl"))
    subobjects = list(_rows(output / "uaf_subobjects.jsonl"))
    subobject_properties = list(_rows(output / "uaf_subobject_properties.jsonl"))
    subobject_references = list(_rows(output / "uaf_subobject_references.jsonl"))
    graphs = list(_rows(output / "uaf_rigvm_graphs.jsonl"))
    nodes = list(_rows(output / "uaf_rigvm_nodes.jsonl"))
    pins = list(_rows(output / "uaf_rigvm_pins.jsonl"))
    links = list(_rows(output / "uaf_rigvm_links.jsonl"))

    asset_paths = [str(row.get("asset_path", "") or "") for row in assets]
    if not asset_paths or asset_paths != sorted(set(asset_paths)):
        raise RuntimeError("focused UAF assets must be non-empty, unique and sorted")
    if any(not bool(row.get("loaded", False)) for row in assets):
        raise RuntimeError("focused UAF capture did not load every registered asset")
    if any(not str(row.get("loaded_class", "") or "") for row in assets):
        raise RuntimeError("focused UAF asset missing exact loaded class")
    asset_set = set(asset_paths)

    for row in asset_properties + asset_references:
        if str(row.get("asset_path", "") or "") not in asset_set:
            raise RuntimeError("focused UAF asset property/reference has unresolved asset")

    subobject_keys: set[tuple[str, str]] = set()
    for row in subobjects:
        key = (str(row.get("asset_path", "") or ""), str(row.get("object_path", "") or ""))
        if key[0] not in asset_set or not key[1] or key in subobject_keys:
            raise RuntimeError(f"invalid/duplicate UAF subobject: {key}")
        subobject_keys.add(key)
    for row in subobject_properties + subobject_references:
        key = (str(row.get("asset_path", "") or ""), str(row.get("owner_path", "") or ""))
        if key not in subobject_keys:
            raise RuntimeError(f"UAF subobject property/reference has unresolved owner: {key}")

    graph_keys: set[tuple[str, str]] = set()
    graph_counts: dict[tuple[str, str], tuple[int, int]] = {}
    for row in graphs:
        key = (str(row.get("asset_path", "") or ""), str(row.get("graph_path", "") or ""))
        if key[0] not in asset_set or not key[1] or key in graph_keys:
            raise RuntimeError(f"invalid/duplicate UAF RigVM graph: {key}")
        graph_keys.add(key)
        graph_counts[key] = (int(row.get("node_count", 0) or 0), int(row.get("link_count", 0) or 0))

    node_keys: set[tuple[str, str, str]] = set()
    nodes_per_graph = collections.Counter()
    for row in nodes:
        key = (
            str(row.get("asset_path", "") or ""),
            str(row.get("graph_path", "") or ""),
            str(row.get("node_path", "") or ""),
        )
        if (key[0], key[1]) not in graph_keys or not key[2] or key in node_keys:
            raise RuntimeError(f"invalid/duplicate UAF RigVM node: {key}")
        node_keys.add(key)
        nodes_per_graph[(key[0], key[1])] += 1

    pin_keys: set[tuple[str, str, str]] = set()
    for row in pins:
        asset = str(row.get("asset_path", "") or "")
        graph = str(row.get("graph_path", "") or "")
        node = str(row.get("node_path", "") or "")
        pin = str(row.get("pin_path", "") or "")
        if (asset, graph, node) not in node_keys or not pin:
            raise RuntimeError("UAF RigVM pin has unresolved node or blank path")
        key = (asset, graph, pin)
        if key in pin_keys:
            raise RuntimeError(f"duplicate UAF RigVM pin path: {key}")
        pin_keys.add(key)

    links_per_graph = collections.Counter()
    link_keys: set[tuple[str, str, str, str]] = set()
    for row in links:
        asset = str(row.get("asset_path", "") or "")
        graph = str(row.get("graph_path", "") or "")
        source = str(row.get("source_pin_path", "") or "")
        target = str(row.get("target_pin_path", "") or "")
        key = (asset, graph, source, target)
        if (asset, graph) not in graph_keys or not source or not target or key in link_keys:
            raise RuntimeError(f"invalid/duplicate UAF RigVM link: {key}")
        if (asset, graph, source) not in pin_keys or (asset, graph, target) not in pin_keys:
            raise RuntimeError(f"UAF RigVM link has unresolved pin endpoint: {key}")
        link_keys.add(key)
        links_per_graph[(asset, graph)] += 1

    for graph_key, (expected_nodes, expected_links) in graph_counts.items():
        if nodes_per_graph[graph_key] != expected_nodes:
            raise RuntimeError(f"UAF RigVM graph node cardinality mismatch: {graph_key}")
        if links_per_graph[graph_key] != expected_links:
            raise RuntimeError(f"UAF RigVM graph link cardinality mismatch: {graph_key}")

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    physical = {
        "registry_candidates": len(assets),
        "loaded_assets": len(assets),
        "asset_properties": len(asset_properties),
        "asset_references": len(asset_references),
        "subobjects": len(subobjects),
        "subobject_properties": len(subobject_properties),
        "subobject_references": len(subobject_references),
        "rigvm_graphs": len(graphs),
        "rigvm_nodes": len(nodes),
        "rigvm_pins": len(pins),
        "rigvm_links": len(links),
        "unit_nodes": sum(1 for row in nodes if str(row.get("unit_script_struct", "") or "")),
        "truncated_properties": sum(int(bool(row.get("truncated", False))) for row in asset_properties + subobject_properties),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            raise RuntimeError(f"focused UAF count mismatch for {key}: manifest={counts.get(key)} actual={actual}")
    return manifest


def _counter_lines(title: str, values, limit: int = 120) -> list[str]:
    counter = collections.Counter(values)
    lines = [title]
    if not counter:
        return [title, "  <none>"]
    for value, count in counter.most_common(limit):
        lines.append(f"  {count:7d}  {value}")
    return lines


def semantic_report(output: Path, manifest: dict) -> str:
    assets = list(_rows(output / "uaf_assets.jsonl"))
    asset_properties = list(_rows(output / "uaf_asset_properties.jsonl"))
    asset_references = list(_rows(output / "uaf_asset_references.jsonl"))
    subobjects = list(_rows(output / "uaf_subobjects.jsonl"))
    subobject_properties = list(_rows(output / "uaf_subobject_properties.jsonl"))
    subobject_references = list(_rows(output / "uaf_subobject_references.jsonl"))
    graphs = list(_rows(output / "uaf_rigvm_graphs.jsonl"))
    nodes = list(_rows(output / "uaf_rigvm_nodes.jsonl"))
    pins = list(_rows(output / "uaf_rigvm_pins.jsonl"))
    links = list(_rows(output / "uaf_rigvm_links.jsonl"))
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}

    changed = [row for row in asset_properties + subobject_properties if bool(row.get("differs_from_default", False))]
    variable_rows = [
        row for row in asset_properties + subobject_properties
        if any(token in str(row.get("property_path", "") or "").lower() for token in ("variable", "binding", "defaultvalue", "entrypoint", "trait"))
    ]

    lines = [
        "UnrealAssetTool focused UE 5.8 AnimNext / Unreal Animation Framework evidence capture",
        "diagnostic_only: True",
        "semantic_promotion: False",
        "schema_promotion: False",
        "runtime_state_captured: False",
        f"registry_candidates: {int(counts.get('registry_candidates', 0) or 0)}",
        f"loaded_assets: {int(counts.get('loaded_assets', 0) or 0)}",
        f"asset_properties: {len(asset_properties)}",
        f"asset_references: {len(asset_references)}",
        f"subobjects: {len(subobjects)}",
        f"subobject_properties: {len(subobject_properties)}",
        f"subobject_references: {len(subobject_references)}",
        f"rigvm_graphs: {len(graphs)}",
        f"rigvm_nodes: {len(nodes)}",
        f"rigvm_pins: {len(pins)}",
        f"rigvm_links: {len(links)}",
        f"unit_nodes: {int(counts.get('unit_nodes', 0) or 0)}",
        f"truncated_properties: {int(counts.get('truncated_properties', 0) or 0)}",
        f"property_depth_limit_hits: {int(counts.get('property_depth_limit_hits', 0) or 0)}",
        f"property_row_limit_hits: {int(counts.get('property_row_limit_hits', 0) or 0)}",
        f"container_element_limit_hits: {int(counts.get('container_element_limit_hits', 0) or 0)}",
        "",
    ]
    lines.extend(_counter_lines("[exact loaded asset classes]", (str(row.get("loaded_class", "") or "<blank>") for row in assets)))
    lines.append("")
    lines.extend(_counter_lines("[subobject classes]", (str(row.get("class_path", "") or "<blank>") for row in subobjects), 200))
    lines.append("")
    lines.extend(_counter_lines("[RigVM graph schema classes]", (str(row.get("schema_class", "") or "<blank>") for row in graphs)))
    lines.append("")
    lines.extend(_counter_lines("[RigVM node classes]", (str(row.get("node_class", "") or "<blank>") for row in nodes), 200))
    lines.append("")
    lines.extend(_counter_lines("[RigVM unit structs]", (str(row.get("unit_script_struct", "") or "<non-unit>") for row in nodes), 200))
    lines.append("")
    lines.extend(_counter_lines("[changed authored property roots]", (f"{row.get('owner_type','')} :: {row.get('root_property','')}" for row in changed), 200))
    lines.append("")
    lines.extend(_counter_lines("[variable / binding / entry-point / trait property paths]", (str(row.get("property_path", "") or "") for row in variable_rows), 250))
    lines.append("")
    lines.extend(_counter_lines("[exact reference targets]", (f"{row.get('property_path','')} -> {row.get('target_path','')}" for row in asset_references + subobject_references), 200))
    lines.append("")
    lines.append("[capture assessment]")
    if graphs and nodes and pins:
        lines.append("  PASS: installed UAF authored assets expose editor-side RigVM graph topology directly; reuse the shared RigVM substrate rather than inventing a second generic graph model.")
    else:
        lines.append("  NOTE: no nested RigVM topology was recovered; UAF-specific editor data will require a narrower native accessor pass before schema design.")
    if variable_rows:
        lines.append("  PASS: UAF variable/binding/entry-point/trait-facing authored property structures are visible for semantic modeling.")
    else:
        lines.append("  NOTE: variable/binding/entry-point/trait semantics remain opaque in generic reflection and require a focused typed accessor pass.")
    if any(int(counts.get(key, 0) or 0) for key in ("truncated_properties", "property_depth_limit_hits", "property_row_limit_hits", "container_element_limit_hits")):
        lines.append("  WARNING: one or more reflection safety limits were hit; inspect exact rows before any schema promotion.")
    lines.append("  Boundary: authored/default plugin content only; no VM execution, live pose/value state, ticking, injection history or transient graph-instance state was captured.")
    return "\n".join(lines) + "\n"


def _capture_cli(core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool animnext-capture",
        description="run a focused UE 5.8 pass over Epic's mounted UAF/UAFAnimGraph/UAFSharedAssets plugin content",
    )
    parser.add_argument("project", help="path to a UE 5.8 .uproject used to host the commandlet")
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
        print(f"removing previous focused UAF capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)

    overall_started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(project, editor, args.build_script, args.no_build, active_root)
        command = [
            str(editor),
            str(project),
            "-run=UnrealAssetToolUAF",
            f"-Output={output}",
            "-EnablePlugins=UAF,UAFAnimGraph,UAFSharedAssets",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-UTF8Output",
        ]
        print("running focused AnimNext/UAF capture:", subprocess.list2cmdline(command))
        started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"focused AnimNext/UAF editor elapsed: {time.perf_counter() - started:.2f}s")

    if all((output / filename).is_file() for filename in CAPTURE_FILES):
        _write_archive(output, archive)
        print(f"focused AnimNext/UAF raw archive: {archive}")
    if result != 0:
        raise RuntimeError(f"focused AnimNext/UAF editor commandlet failed with exit code {result}; upload the raw archive if it was produced")

    manifest = validate_capture(output)
    report = semantic_report(output, manifest)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")
    print(f"focused AnimNext/UAF report: {report_path}")
    print(f"focused AnimNext/UAF total elapsed: {time.perf_counter() - overall_started:.2f}s")
    print("normal project scan was not run")
    print("derive was not run")
    return 0


def install(runtime_module=None, core_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if core_module is None:
        import uatool_core as core_module
    if getattr(runtime_module, "_animnext_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "animnext-capture":
            try:
                return _capture_cli(core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 56
        return original_main()

    runtime_module.main = main
    runtime_module._animnext_capture_installed = True
