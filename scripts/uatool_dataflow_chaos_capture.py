#!/usr/bin/env python3
"""Focused UE 5.8 capture for Dataflow graphs and Geometry Collection authoring."""
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

DATAFLOW_CLASS = "/Script/DataflowEngine.Dataflow"
GEOMETRY_COLLECTION_CLASS = "/Script/GeometryCollectionEngine.GeometryCollection"

CAPTURE_FILES = (
    "dataflow_chaos_capture_manifest.json",
    "dataflow_chaos_focus_assets.txt",
    "dataflow_chaos_assets.jsonl",
    "dataflow_graphs.jsonl",
    "dataflow_nodes.jsonl",
    "dataflow_pins.jsonl",
    "dataflow_edges.jsonl",
    "dataflow_asset_properties.jsonl",
    "dataflow_asset_references.jsonl",
    "dataflow_node_properties.jsonl",
    "dataflow_node_references.jsonl",
    "geometry_collection_properties.jsonl",
    "geometry_collection_references.jsonl",
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


def _resolve_corpus(project: Path, value: str | None) -> Path:
    corpus = Path(value).expanduser().resolve() if value else project.parent / ".uatool"
    if not corpus.is_dir():
        raise FileNotFoundError(f"existing UnrealAssetTool corpus does not exist: {corpus}")
    return corpus


def _resolve_output(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / "dataflow-chaos-capture"


def _resolve_archive(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.dataflow-chaos-capture.zip"


def _resolve_report(project: Path, value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else project.parent / ".uatool" / f"{project.stem}.dataflow-chaos-capture.txt"


def _matches_prefix(path: str, prefixes: tuple[str, ...]) -> bool:
    if not prefixes:
        return True
    lowered = path.lower()
    return any(lowered.startswith(prefix.lower()) for prefix in prefixes)


def discover_focus_assets(corpus: Path, prefixes: tuple[str, ...] = ()) -> tuple[list[str], dict[str, int]]:
    focus: list[str] = []
    excluded = collections.Counter()
    seen: set[str] = set()
    for row in _rows(corpus / "assets.jsonl") or ():
        path = str(row.get("object_path", "") or "")
        class_path = str(row.get("class_path", "") or "")
        if class_path not in {DATAFLOW_CLASS, GEOMETRY_COLLECTION_CLASS} or not path:
            continue
        family = "dataflow" if class_path == DATAFLOW_CLASS else "geometry_collection"
        if not _matches_prefix(path, prefixes):
            excluded[family] += 1
            continue
        if path not in seen:
            focus.append(path)
            seen.add(path)
    focus.sort()
    return focus, dict(excluded)


def _write_archive(output: Path, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.unlink(missing_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for filename in CAPTURE_FILES:
            path = output / filename
            if not path.is_file():
                raise RuntimeError(f"focused Dataflow/Chaos capture missing expected file: {filename}")
            bundle.write(path, arcname=filename)


def _read_manifest(output: Path) -> dict:
    path = output / "dataflow_chaos_capture_manifest.json"
    if not path.is_file():
        raise RuntimeError("focused Dataflow/Chaos capture did not produce dataflow_chaos_capture_manifest.json")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid dataflow_chaos_capture_manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("dataflow_chaos_capture_manifest.json root is not an object")
    return value


def _focus_rows(output: Path) -> list[str]:
    return [
        line.strip()
        for line in (output / "dataflow_chaos_focus_assets.txt").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def validate_capture(output: Path) -> dict:
    manifest = _read_manifest(output)
    if int(manifest.get("schema_version", 0) or 0) != 1:
        raise RuntimeError(f"focused Dataflow/Chaos capture expected manifest schema 1, got {manifest.get('schema_version')}")
    if not bool(manifest.get("success", False)):
        raise RuntimeError(f"focused Dataflow/Chaos capture failed: {manifest.get('error', '')}")
    if not bool(manifest.get("diagnostic_only", False)):
        raise RuntimeError("focused Dataflow/Chaos manifest must remain diagnostic_only=true")
    if bool(manifest.get("semantic_promotion", True)) or bool(manifest.get("schema_promotion", True)):
        raise RuntimeError("focused Dataflow/Chaos capture must not promote semantic/schema state")
    if bool(manifest.get("runtime_state_captured", True)):
        raise RuntimeError("focused Dataflow/Chaos manifest must remain runtime_state_captured=false")

    focus = _focus_rows(output)
    assets = list(_rows(output / "dataflow_chaos_assets.jsonl"))
    graphs = list(_rows(output / "dataflow_graphs.jsonl"))
    nodes = list(_rows(output / "dataflow_nodes.jsonl"))
    pins = list(_rows(output / "dataflow_pins.jsonl"))
    edges = list(_rows(output / "dataflow_edges.jsonl"))
    asset_properties = list(_rows(output / "dataflow_asset_properties.jsonl"))
    asset_references = list(_rows(output / "dataflow_asset_references.jsonl"))
    node_properties = list(_rows(output / "dataflow_node_properties.jsonl"))
    node_references = list(_rows(output / "dataflow_node_references.jsonl"))
    gc_properties = list(_rows(output / "geometry_collection_properties.jsonl"))
    gc_references = list(_rows(output / "geometry_collection_references.jsonl"))

    if focus != sorted(set(focus)) or any(not value for value in focus):
        raise RuntimeError("focused Dataflow/Chaos focus list is not unique/sorted/nonblank")
    asset_paths = [str(row.get("asset_path", "") or "") for row in assets]
    if asset_paths != focus:
        raise RuntimeError("focused Dataflow/Chaos asset rows do not exactly match focus assets")
    if any(not bool(row.get("loaded", False)) for row in assets):
        raise RuntimeError("focused Dataflow/Chaos capture did not load every nominated asset")
    valid_kinds = {"dataflow", "geometry_collection"}
    if any(str(row.get("asset_kind", "") or "") not in valid_kinds for row in assets):
        raise RuntimeError("focused Dataflow/Chaos capture loaded an unsupported asset kind")

    dataflow_assets = {str(row["asset_path"]) for row in assets if row.get("asset_kind") == "dataflow"}
    gc_assets = {str(row["asset_path"]) for row in assets if row.get("asset_kind") == "geometry_collection"}
    graph_assets = [str(row.get("asset_path", "") or "") for row in graphs]
    if sorted(graph_assets) != sorted(dataflow_assets) or len(graph_assets) != len(set(graph_assets)):
        raise RuntimeError("focused Dataflow/Chaos graph rows must be exactly one per Dataflow asset")

    node_keys: set[tuple[str, str]] = set()
    for row in nodes:
        key = (str(row.get("asset_path", "") or ""), str(row.get("node_guid", "") or ""))
        if key[0] not in dataflow_assets or not key[1] or key in node_keys:
            raise RuntimeError(f"invalid/duplicate Dataflow node identity: {key}")
        node_keys.add(key)
        if not str(row.get("node_struct", "") or ""):
            raise RuntimeError(f"Dataflow node has no reflected concrete struct: {key}")

    pin_keys: set[tuple[str, str]] = set()
    pin_owner: dict[tuple[str, str], tuple[str, str]] = {}
    pin_direction: dict[tuple[str, str], str] = {}
    for row in pins:
        asset = str(row.get("asset_path", "") or "")
        guid = str(row.get("pin_guid", "") or "")
        node_guid = str(row.get("node_guid", "") or "")
        key = (asset, guid)
        if (asset, node_guid) not in node_keys or not guid or key in pin_keys:
            raise RuntimeError(f"invalid/duplicate Dataflow pin identity: {key}")
        direction = str(row.get("direction", "") or "")
        if direction not in {"input", "output"}:
            raise RuntimeError(f"Dataflow pin has invalid direction: {key} {direction}")
        pin_keys.add(key)
        pin_owner[key] = (asset, node_guid)
        pin_direction[key] = direction

    edge_keys: set[tuple[str, str, str, str, str]] = set()
    for row in edges:
        asset = str(row.get("asset_path", "") or "")
        source_node = str(row.get("source_node_guid", "") or "")
        source_pin = str(row.get("source_pin_guid", "") or "")
        target_node = str(row.get("target_node_guid", "") or "")
        target_pin = str(row.get("target_pin_guid", "") or "")
        edge = (asset, source_node, source_pin, target_node, target_pin)
        if edge in edge_keys:
            raise RuntimeError(f"duplicate Dataflow edge: {edge}")
        edge_keys.add(edge)
        source_key = (asset, source_pin)
        target_key = (asset, target_pin)
        if source_key not in pin_owner or target_key not in pin_owner:
            raise RuntimeError(f"Dataflow edge has unresolved pin endpoint: {edge}")
        if pin_owner[source_key] != (asset, source_node) or pin_owner[target_key] != (asset, target_node):
            raise RuntimeError(f"Dataflow edge node/pin ownership mismatch: {edge}")
        if pin_direction[source_key] != "output" or pin_direction[target_key] != "input":
            raise RuntimeError(f"Dataflow edge direction mismatch: {edge}")

    for row in node_properties + node_references:
        key = (str(row.get("source_path", "") or ""), str(row.get("owner_id", "") or ""))
        if key not in node_keys:
            raise RuntimeError(f"Dataflow node property/reference has unresolved owner: {key}")
    for row in asset_properties + asset_references:
        if str(row.get("source_path", "") or "") not in dataflow_assets:
            raise RuntimeError("Dataflow asset property/reference has unresolved source")
    for row in gc_properties + gc_references:
        if str(row.get("source_path", "") or "") not in gc_assets:
            raise RuntimeError("Geometry Collection property/reference has unresolved source")

    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    physical = {
        "focus_assets": len(focus),
        "loaded_assets": len(assets),
        "dataflow_assets": len(dataflow_assets),
        "geometry_collections": len(gc_assets),
        "graphs": len(graphs),
        "nodes": len(nodes),
        "pins": len(pins),
        "edges": len(edges),
        "disabled_nodes": sum(int(bool(row.get("disabled", False))) for row in nodes),
        "dataflow_asset_properties": len(asset_properties),
        "dataflow_asset_references": len(asset_references),
        "node_properties": len(node_properties),
        "node_references": len(node_references),
        "geometry_collection_properties": len(gc_properties),
        "geometry_collection_references": len(gc_references),
        "truncated_properties": sum(int(bool(row.get("truncated", False))) for row in asset_properties + node_properties + gc_properties),
    }
    for key, actual in physical.items():
        if int(counts.get(key, -1)) != actual:
            raise RuntimeError(f"focused Dataflow/Chaos count mismatch for {key}: manifest={counts.get(key)} actual={actual}")
    return manifest


def _counter_lines(title: str, values, limit: int = 80) -> list[str]:
    counter = collections.Counter(values)
    lines = [title]
    if not counter:
        return [title, "  <none>"]
    for value, count in counter.most_common(limit):
        lines.append(f"  {count:7d}  {value}")
    return lines


def semantic_report(output: Path, manifest: dict, excluded: dict[str, int] | None = None) -> str:
    assets = list(_rows(output / "dataflow_chaos_assets.jsonl"))
    graphs = list(_rows(output / "dataflow_graphs.jsonl"))
    nodes = list(_rows(output / "dataflow_nodes.jsonl"))
    pins = list(_rows(output / "dataflow_pins.jsonl"))
    edges = list(_rows(output / "dataflow_edges.jsonl"))
    node_properties = list(_rows(output / "dataflow_node_properties.jsonl"))
    node_references = list(_rows(output / "dataflow_node_references.jsonl"))
    gc_properties = list(_rows(output / "geometry_collection_properties.jsonl"))
    gc_references = list(_rows(output / "geometry_collection_references.jsonl"))
    counts = manifest.get("counts", {}) if isinstance(manifest.get("counts"), dict) else {}
    changed_gc = [row for row in gc_properties if bool(row.get("differs_from_default", False))]
    dataflow_bindings = [row for row in gc_references if str(row.get("root_property", "") or "") == "DataflowAsset"]
    terminal_nodes = [row for row in nodes if "GeometryCollectionTerminal" in str(row.get("node_struct", "") or "")]

    lines = [
        "UnrealAssetTool focused Dataflow / Geometry Collection / Chaos evidence capture",
        "diagnostic_only: True",
        "semantic_promotion: False",
        "schema_promotion: False",
        "runtime_state_captured: False",
        f"focus_assets: {int(counts.get('focus_assets', 0) or 0)}",
        f"loaded_assets: {int(counts.get('loaded_assets', 0) or 0)}",
        f"dataflow_assets: {int(counts.get('dataflow_assets', 0) or 0)}",
        f"geometry_collections: {int(counts.get('geometry_collections', 0) or 0)}",
        f"graphs: {len(graphs)}",
        f"nodes: {len(nodes)}",
        f"pins: {len(pins)}",
        f"edges: {len(edges)}",
        f"disabled_nodes: {int(counts.get('disabled_nodes', 0) or 0)}",
        f"node_properties: {len(node_properties)}",
        f"node_references: {len(node_references)}",
        f"geometry_collection_properties: {len(gc_properties)}",
        f"geometry_collection_references: {len(gc_references)}",
        f"geometry_collection_dataflow_bindings: {len(dataflow_bindings)}",
        f"geometry_collection_terminal_nodes: {len(terminal_nodes)}",
        f"truncated_properties: {int(counts.get('truncated_properties', 0) or 0)}",
        f"property_depth_limit_hits: {int(counts.get('property_depth_limit_hits', 0) or 0)}",
        f"property_row_limit_hits: {int(counts.get('property_row_limit_hits', 0) or 0)}",
        f"container_element_limit_hits: {int(counts.get('container_element_limit_hits', 0) or 0)}",
        "",
    ]
    if excluded:
        lines.append("[excluded exact assets outside requested prefixes]")
        for family, count in sorted(excluded.items()):
            lines.append(f"  {family}: {count}")
        lines.append("")
    lines.extend(_counter_lines("[Dataflow node structs]", (str(row.get("node_struct", "") or "<blank>") for row in nodes), 150))
    lines.append("")
    lines.extend(_counter_lines(
        "[Dataflow node authored/reflected roots]",
        (f"{row.get('owner_type','')} :: {row.get('root_property','')}" for row in node_properties),
        150,
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[Geometry Collection changed roots]",
        (f"{row.get('root_property','')} = {row.get('value','')}" for row in changed_gc),
        150,
    ))
    lines.append("")
    lines.extend(_counter_lines(
        "[Geometry Collection DataflowAsset bindings]",
        (f"{row.get('source_path','')} -> {row.get('target_path','')}" for row in dataflow_bindings),
        100,
    ))
    lines.append("")
    lines.extend(("[capture assessment]",))
    if len(graphs) and len(nodes) and len(pins):
        lines.append("  PASS: real UDataflow/FGraph topology and concrete node structs were captured.")
    else:
        lines.append("  BLOCKED: Dataflow graph topology was not recovered.")
    if edges:
        lines.append("  PASS: exact FGraph links were captured with node/pin GUID endpoints.")
    else:
        lines.append("  NOTE: no Dataflow links were captured; inspect whether focused graphs are actually disconnected.")
    if node_properties:
        lines.append("  PASS: concrete Dataflow node UScriptStruct properties were reflected.")
    else:
        lines.append("  BLOCKED: no Dataflow node properties were reflected.")
    if dataflow_bindings:
        lines.append("  PASS: Geometry Collection -> DataflowAsset authored bindings are now proven directly.")
    else:
        lines.append("  NOTE: no Geometry Collection DataflowAsset reference was authored in the focused assets; do not invent that relation.")
    if terminal_nodes:
        lines.append("  PASS: GeometryCollectionTerminal node type is present in the focused Dataflow graphs.")
    else:
        lines.append("  NOTE: no GeometryCollectionTerminal node was found in the focused Dataflow graphs.")
    if any(int(counts.get(key, 0) or 0) for key in (
        "truncated_properties", "property_depth_limit_hits", "property_row_limit_hits", "container_element_limit_hits"
    )):
        lines.append("  WARNING: one or more reflection safety limits were hit; schema promotion remains blocked until inspected.")
    lines.append("  Boundary: authored asset graph/default state only; no Dataflow evaluation, solver particles, break/collision/removal history, or dynamic Geometry Collection transforms were captured.")
    return "\n".join(lines) + "\n"


def _capture_cli(core_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool dataflow-chaos-capture",
        description="run a focused UE pass over corpus-proven UDataflow and Geometry Collection assets",
    )
    parser.add_argument("project", help="path to .uproject")
    parser.add_argument("--editor", required=True, help="exact UnrealEditor-Cmd executable")
    parser.add_argument("--corpus", help="existing .uatool corpus used to nominate assets")
    parser.add_argument("--asset-prefix", action="append", default=[], help="limit exact corpus candidates to one or more object-path prefixes")
    parser.add_argument("--asset", action="append", default=[], help="additional exact UDataflow/GeometryCollection object path")
    parser.add_argument("--build-script", help="optional explicit Build.bat path")
    parser.add_argument("--no-build", action="store_true", help="reuse already-built plugin module")
    parser.add_argument("--output", help="focused capture directory")
    parser.add_argument("--archive", help="focused capture ZIP")
    parser.add_argument("--report", help="semantic inspection report path")
    args = parser.parse_args(argv)

    project = _resolve_project(args.project)
    editor = core_module.require_editor(args.editor)
    corpus = _resolve_corpus(project, args.corpus)
    output = _resolve_output(project, args.output)
    archive = _resolve_archive(project, args.archive)
    report_path = _resolve_report(project, args.report)
    prefixes = tuple(str(value).strip() for value in args.asset_prefix if str(value).strip())
    discovered, excluded = discover_focus_assets(corpus, prefixes)
    focus = sorted(set((*discovered, *(str(value).strip() for value in args.asset if str(value).strip()))))
    if not focus:
        raise RuntimeError("existing corpus nominated no UDataflow/GeometryCollection assets in the requested scope")

    if output.exists():
        print(f"removing previous focused Dataflow/Chaos capture: {output}")
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=True)
    focus_file = output / "dataflow_chaos_focus_assets.txt"
    focus_file.write_text("".join(value + "\n" for value in focus), encoding="utf-8", newline="\n")
    print(f"focused Dataflow/Chaos nominated assets: {len(focus)}")
    for value in focus:
        print(f"  {value}")
    if excluded:
        print("excluded exact candidates outside requested prefixes:")
        for family, count in sorted(excluded.items()):
            print(f"  {family}: {count}")

    overall_started = time.perf_counter()
    with core_module.stage_invoking_plugin_checkout(project) as active_root:
        active_root = Path(active_root).resolve()
        core_module.ensure_plugin_binary(project, editor, args.build_script, args.no_build, active_root)
        command = [
            str(editor),
            str(project),
            "-run=UnrealAssetToolDataflowChaos",
            f"-Output={output}",
            f"-FocusFile={focus_file}",
            "-unattended",
            "-nop4",
            "-nosplash",
            "-nullrhi",
            "-nosound",
            "-UTF8Output",
        ]
        print("running focused Dataflow/Chaos capture:", subprocess.list2cmdline(command))
        started = time.perf_counter()
        result = subprocess.run(command, check=False).returncode
        print(f"focused Dataflow/Chaos editor elapsed: {time.perf_counter() - started:.2f}s")

    _write_archive(output, archive)
    print(f"focused Dataflow/Chaos raw archive: {archive}")
    if result != 0:
        raise RuntimeError(f"focused Dataflow/Chaos editor commandlet failed with exit code {result}; raw archive preserved")

    manifest = validate_capture(output)
    report = semantic_report(output, manifest, excluded)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8", newline="\n")
    print(report, end="")
    print(f"focused Dataflow/Chaos report: {report_path}")
    print(f"focused Dataflow/Chaos total elapsed: {time.perf_counter() - overall_started:.2f}s")
    print("normal project scan was not run")
    print("derive was not run")
    return 0


def install(runtime_module=None, core_module=None) -> None:
    if runtime_module is None:
        import uatool_runtime as runtime_module
    if core_module is None:
        import uatool_core as core_module
    if getattr(runtime_module, "_dataflow_chaos_capture_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "dataflow-chaos-capture":
            try:
                return _capture_cli(core_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 53
        return original_main()

    runtime_module.main = main
    runtime_module._dataflow_chaos_capture_installed = True
