#!/usr/bin/env python3
"""Read-only report joining Gameplay Camera directors to Chooser-driven rig selection."""
from __future__ import annotations

import argparse
import collections
from pathlib import Path
import sys

import uatool_chooser_decisions as chooser_decisions

CAMERA_MARKER = "/script/gameplaycameras."


def _rows_for(rows, path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [row for row in rows(path) if isinstance(row, dict)]


def _first(row: dict, *names: str) -> str:
    for name in names:
        value = str(row.get(name, "") or "")
        if value:
            return value
    return ""


def _is_camera_director_blueprint(row: dict) -> bool:
    path = _first(row, "object_path", "blueprint_path")
    parent = str(row.get("parent_class", "") or "")
    generated = str(row.get("generated_class", "") or "")
    text = " ".join((path, parent, generated)).lower()
    return "cameradirector" in text and (
        CAMERA_MARKER in text or "/game/" in path.lower()
    )


def build_report(output: Path, rows) -> dict:
    output = Path(output).expanduser().resolve()

    blueprints = _rows_for(rows, output / "blueprints.jsonl")
    blueprint_relations = _rows_for(rows, output / "blueprint_relations.jsonl")
    project_edges = _rows_for(rows, output / "project_edges.jsonl")
    chooser_tables = _rows_for(rows, output / "chooser_tables.jsonl")
    chooser_columns = _rows_for(rows, output / "chooser_columns.jsonl")
    chooser_results = _rows_for(rows, output / "chooser_results.jsonl")
    chooser_context = _rows_for(rows, output / "chooser_context.jsonl")
    struct_references = _rows_for(rows, output / "animation_struct_references.jsonl")
    camera_assets = _rows_for(rows, output / "gameplay_camera_assets.jsonl")
    camera_directors = _rows_for(rows, output / "gameplay_camera_directors.jsonl")
    camera_rigs = _rows_for(rows, output / "gameplay_camera_rigs.jsonl")
    systems_references = _rows_for(rows, output / "systems_references.jsonl")

    director_blueprints = [row for row in blueprints if _is_camera_director_blueprint(row)]
    director_bp_paths = {
        _first(row, "object_path", "blueprint_path") for row in director_blueprints
    }
    director_bp_paths.discard("")

    chooser_paths = {
        str(row.get("chooser_path", "") or "") for row in chooser_tables
    }
    chooser_paths.discard("")

    director_chooser_links: list[dict] = []
    seen_links: set[tuple[str, str, str]] = set()

    for row in blueprint_relations:
        bp = str(row.get("blueprint_path", "") or row.get("asset_path", "") or "")
        target = str(row.get("target", "") or "")
        if bp not in director_bp_paths or target not in chooser_paths:
            continue
        relation = str(row.get("relation", "") or "")
        key = (bp, relation, target)
        if key in seen_links:
            continue
        seen_links.add(key)
        director_chooser_links.append({
            "director_blueprint_path": bp,
            "relation": relation,
            "chooser_path": target,
            "source": "blueprint_relations",
            "source_id": str(row.get("source_id", "") or ""),
        })

    for row in project_edges:
        source = str(row.get("source", "") or "")
        target = str(row.get("target", "") or "")
        if source not in director_bp_paths or target not in chooser_paths:
            continue
        relation = str(row.get("relation", "") or "")
        key = (source, relation, target)
        if key in seen_links:
            continue
        seen_links.add(key)
        director_chooser_links.append({
            "director_blueprint_path": source,
            "relation": relation,
            "chooser_path": target,
            "source": "project_edges",
            "edge_quality": str(row.get("edge_quality", "") or ""),
        })

    selected_choosers = {
        str(row.get("chooser_path", "") or "") for row in director_chooser_links
    }
    selected_choosers.discard("")

    selected_tables = [
        row for row in chooser_tables
        if str(row.get("chooser_path", "") or "") in selected_choosers
    ]
    selected_columns = [
        row for row in chooser_columns
        if str(row.get("asset_path", "") or "") in selected_choosers
    ]
    selected_results = [
        row for row in chooser_results
        if str(row.get("asset_path", "") or "") in selected_choosers
    ]
    selected_context = [
        row for row in chooser_context
        if str(row.get("asset_path", "") or "") in selected_choosers
    ]
    selected_refs = [
        row for row in struct_references
        if str(row.get("owner_path", "") or "") in selected_choosers
    ]

    rig_paths = {
        str(row.get("rig_path", "") or "") for row in camera_rigs
    }
    rig_paths.discard("")

    result_refs: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    column_refs: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    context_refs: dict[tuple[str, int], list[dict]] = collections.defaultdict(list)
    for row in selected_refs:
        owner = str(row.get("owner_path", "") or "")
        kind = str(row.get("source_kind", "") or "")
        index = int(row.get("source_index", 0) or 0)
        if kind == "chooser_result":
            result_refs[(owner, index)].append(row)
        elif kind == "chooser_column":
            column_refs[(owner, index)].append(row)
        elif kind == "chooser_context":
            context_refs[(owner, index)].append(row)

    rig_result_count = 0
    unresolved_rig_result_count = 0
    for values in result_refs.values():
        for row in values:
            target = str(row.get("target_path", "") or "")
            target_class = str(row.get("target_class", "") or "")
            if CAMERA_MARKER in target_class.lower() and "camerarig" in target_class.lower():
                rig_result_count += 1
                if target not in rig_paths:
                    unresolved_rig_result_count += 1

    camera_asset_director_links: list[dict] = []
    generated_to_bp = {
        str(row.get("generated_class", "") or ""): _first(row, "object_path", "blueprint_path")
        for row in director_blueprints
        if str(row.get("generated_class", "") or "")
    }
    camera_asset_paths = {
        str(row.get("camera_asset_path", "") or "") for row in camera_assets
    }
    nested_director_paths = {
        str(row.get("director_path", "") or "") for row in camera_directors
    }
    for row in systems_references:
        asset = str(row.get("asset_path", "") or "")
        owner = str(row.get("owner_path", "") or "")
        target = str(row.get("target_path", "") or "")
        if asset not in camera_asset_paths:
            continue
        bp = generated_to_bp.get(target, "")
        if not bp:
            continue
        camera_asset_director_links.append({
            "camera_asset_path": asset,
            "director_object_path": owner if owner in nested_director_paths else owner,
            "property_path": str(row.get("property_path", "") or ""),
            "director_blueprint_path": bp,
            "generated_class": target,
        })

    decisions = chooser_decisions.decisions_for_output(output, rows, selected_choosers)

    director_chooser_links.sort(key=lambda row: (
        row.get("director_blueprint_path", ""), row.get("relation", ""), row.get("chooser_path", ""), row.get("source", "")
    ))
    selected_tables.sort(key=lambda row: str(row.get("chooser_path", "") or ""))
    selected_columns.sort(key=lambda row: (str(row.get("asset_path", "") or ""), int(row.get("index", 0) or 0)))
    selected_results.sort(key=lambda row: (str(row.get("asset_path", "") or ""), int(row.get("index", 0) or 0)))
    selected_context.sort(key=lambda row: (str(row.get("asset_path", "") or ""), int(row.get("index", 0) or 0)))

    return {
        "output": str(output),
        "director_blueprints": director_blueprints,
        "camera_asset_director_links": camera_asset_director_links,
        "director_chooser_links": director_chooser_links,
        "chooser_tables": selected_tables,
        "chooser_columns": selected_columns,
        "chooser_results": selected_results,
        "chooser_context": selected_context,
        "chooser_references": selected_refs,
        "chooser_decisions": decisions,
        "result_refs": result_refs,
        "column_refs": column_refs,
        "context_refs": context_refs,
        "camera_rig_paths": rig_paths,
        "rig_result_count": rig_result_count,
        "unresolved_rig_result_count": unresolved_rig_result_count,
    }


def _short(value: object, limit: int = 1400) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _print_refs(values: list[dict], *, indent: str = "      ") -> None:
    if not values:
        print(indent + "references: <none>")
        return
    for ref in values:
        print(
            indent + "reference: {target} | class={cls} | kind={kind}".format(
                target=ref.get("target_path", ""),
                cls=ref.get("target_class", ""),
                kind=ref.get("reference_kind", ""),
            )
        )


def print_report(report: dict, *, limit: int = 400) -> None:
    decisions = report.get("chooser_decisions", [])
    print("=== GAMEPLAY CAMERA SELECTION REPORT ===")
    print(report.get("output", ""))
    print(
        "director_blueprints={bp} asset_director_links={asset_links} director_chooser_links={chooser_links} "
        "choosers={choosers} columns={columns} results={results} context={context} references={refs} "
        "rig_result_refs={rig_refs} unresolved_rig_result_refs={unresolved} decisions={decisions} decoded_decisions={decoded}".format(
            bp=len(report.get("director_blueprints", [])),
            asset_links=len(report.get("camera_asset_director_links", [])),
            chooser_links=len(report.get("director_chooser_links", [])),
            choosers=len(report.get("chooser_tables", [])),
            columns=len(report.get("chooser_columns", [])),
            results=len(report.get("chooser_results", [])),
            context=len(report.get("chooser_context", [])),
            refs=len(report.get("chooser_references", [])),
            rig_refs=int(report.get("rig_result_count", 0) or 0),
            unresolved=int(report.get("unresolved_rig_result_count", 0) or 0),
            decisions=len(decisions),
            decoded=sum(int(bool(row.get("fully_decoded", False))) for row in decisions),
        )
    )

    print("\n[Camera director Blueprints]")
    values = report.get("director_blueprints", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        print(
            "  {path} | parent={parent} | generated={generated}".format(
                path=_first(row, "object_path", "blueprint_path"),
                parent=row.get("parent_class", ""),
                generated=row.get("generated_class", ""),
            )
        )

    print("\n[Camera Asset -> director Blueprint links]")
    values = report.get("camera_asset_director_links", [])
    if not values:
        print("<none found in systems_references>")
    for row in values[:limit]:
        print(
            "  {asset} -> {bp} | director_object={director} | property={property}".format(
                asset=row.get("camera_asset_path", ""),
                bp=row.get("director_blueprint_path", ""),
                director=row.get("director_object_path", ""),
                property=row.get("property_path", ""),
            )
        )

    print("\n[Director Blueprint -> Chooser links]")
    values = report.get("director_chooser_links", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        print(
            "  {bp} -> {chooser} | relation={relation} | source={source} | quality={quality}".format(
                bp=row.get("director_blueprint_path", ""),
                chooser=row.get("chooser_path", ""),
                relation=row.get("relation", ""),
                source=row.get("source", ""),
                quality=row.get("edge_quality", ""),
            )
        )

    print("\n[Chooser tables]")
    values = report.get("chooser_tables", [])
    if not values:
        print("<none>")
    for row in values[:limit]:
        print(
            "  {path} | output={output} | columns={columns} | results={results} | context={context}".format(
                path=row.get("chooser_path", ""),
                output=row.get("output_object_type", ""),
                columns=row.get("column_count", 0),
                results=row.get("result_count", 0),
                context=row.get("context_count", 0),
            )
        )

    print("\n[Chooser decision rows]")
    if not decisions:
        print("<none decoded>")
    rig_paths = report.get("camera_rig_paths", set())
    for row in decisions[:limit]:
        targets = [
            str(ref.get("target_path", "") or "")
            for ref in row.get("result_references", [])
            if str(ref.get("target_path", "") or "") in rig_paths
        ]
        result_text = ", ".join(targets) or "<non-camera or unresolved result>"
        print(
            "  [{index}] when {condition} -> {result} | disabled={disabled} | decoded={decoded}".format(
                index=row.get("row_index", 0),
                condition=row.get("condition_text", ""),
                result=result_text,
                disabled=bool(row.get("disabled", False)),
                decoded=bool(row.get("fully_decoded", False)),
            )
        )
        for predicate in row.get("predicates", []):
            print(
                "      c{column} {property} | comparison={comparison} | raw={raw} | value={display} | decoded={decoded}".format(
                    column=predicate.get("column_index", 0),
                    property=predicate.get("property_name", ""),
                    comparison=predicate.get("comparison", ""),
                    raw=predicate.get("raw_value_name", ""),
                    display=predicate.get("display_value", ""),
                    decoded=bool(predicate.get("decoded", False)),
                )
            )

    print("\n[Chooser context]")
    for row in report.get("chooser_context", [])[:limit]:
        owner = str(row.get("asset_path", "") or "")
        index = int(row.get("index", 0) or 0)
        print(f"  [{index}] {row.get('struct_type', '')}")
        print("      raw: " + _short(row.get("raw_value", "")))
        _print_refs(report.get("context_refs", {}).get((owner, index), []))

    print("\n[Chooser columns]")
    for row in report.get("chooser_columns", [])[:limit]:
        owner = str(row.get("asset_path", "") or "")
        index = int(row.get("index", 0) or 0)
        print(f"  [{index}] {row.get('struct_type', '')}")
        print("      raw: " + _short(row.get("raw_value", "")))
        _print_refs(report.get("column_refs", {}).get((owner, index), []))

    print("\n[Chooser results]")
    for row in report.get("chooser_results", [])[:limit]:
        owner = str(row.get("asset_path", "") or "")
        index = int(row.get("index", 0) or 0)
        print(
            "  [{index}] {struct} | disabled={disabled}".format(
                index=index,
                struct=row.get("struct_type", ""),
                disabled=bool(row.get("disabled", False)),
            )
        )
        print("      raw: " + _short(row.get("raw_value", "")))
        refs = report.get("result_refs", {}).get((owner, index), [])
        _print_refs(refs)
        rig_targets = [
            str(ref.get("target_path", "") or "") for ref in refs
            if str(ref.get("target_path", "") or "") in rig_paths
        ]
        if rig_targets:
            print("      normalized_camera_rigs: " + ", ".join(rig_targets))

    print("========================================")


def install(runtime_module) -> None:
    if getattr(runtime_module, "_gameplay_camera_selection_report_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "gameplay-camera-selection-report":
            parser = argparse.ArgumentParser(
                prog="uatool gameplay-camera-selection-report",
                description="report Gameplay Camera director -> Chooser -> rig-selection evidence",
            )
            parser.add_argument("output", help="source .uatool directory")
            parser.add_argument("--limit", type=int, default=400, help="maximum detailed rows per section")
            args = parser.parse_args(sys.argv[2:])
            if args.limit < 1:
                parser.error("--limit must be >= 1")
            report = build_report(Path(args.output), runtime_module._rows)
            print_report(report, limit=args.limit)
            return 0
        return original_main()

    runtime_module.main = main
    runtime_module._gameplay_camera_selection_report_installed = True
