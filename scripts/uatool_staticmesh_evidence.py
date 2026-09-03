#!/usr/bin/env python3
"""Read-only StaticMesh authored-topology evidence inventory.

The command measures what an existing canonical corpus already proves. Asset
Registry tags and incoming consumer references are kept distinct from mesh-owned
authored topology; neither is promoted into a StaticMesh semantic schema here.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
from pathlib import Path
import sys

STATIC_MESH_CLASS = "/Script/Engine.StaticMesh"
STATIC_MESH_COMPONENT_CLASS = "/Script/Engine.StaticMeshComponent"

STREAMS = (
    "assets.jsonl",
    "asset_dependencies.jsonl",
    "blueprint_component_properties.jsonl",
    "blueprint_state_values.jsonl",
    "blueprint_node_properties.jsonl",
    "blueprint_node_references.jsonl",
    "world_components.jsonl",
    "world_instance_properties.jsonl",
    "world_references.jsonl",
    "systems_properties.jsonl",
    "systems_references.jsonl",
    "dataflow_node_properties.jsonl",
    "dataflow_node_references.jsonl",
    "pcg_node_properties.jsonl",
    "pcg_node_references.jsonl",
    "project_nodes.jsonl",
    "project_edges.jsonl",
)
SOURCE_STREAM = "source_chunks.jsonl"

TAG_TOKENS = (
    "lod", "nanite", "material", "socket", "collision", "bodysetup",
    "lightmap", "uvchannel", "distancefield", "complexcollision",
)
DETAIL_TOKENS = (
    "staticmesh", "staticmaterials", "sourcemodels", "sectioninfo",
    "sectioninfomap", "sockets", "bodysetup", "agggeom", "collisiontraceflag",
    "complexcollisionmesh", "nanitesettings", "buildsettings", "reductionssettings",
    "reductionsettings", "materialslot", "lightmapcoordinateindex", "lightmapresolution",
)


def _rows(path: Path, iterator):
    if not path.is_file():
        return
    for row in iterator(path):
        if isinstance(row, dict):
            yield row


def _text(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _first(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _short(value: object, limit: int = 3600) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _tag_items(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key), str(item)
        return
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                key = item.get("key", item.get("name", item.get("tag", "")))
                val = item.get("value", item.get("text", ""))
                if key:
                    yield str(key), str(val)
        return
    if isinstance(value, str) and value.strip().startswith(("{", "[")):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return
        yield from _tag_items(parsed)


def build_report(output: Path, iterator, *, include_source: bool = True, example_limit: int = 30) -> dict:
    output = Path(output).expanduser().resolve()
    if example_limit < 1:
        raise ValueError("example_limit must be >= 1")

    meshes: set[str] = set()
    relevant_tags: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    tag_key_counts = collections.Counter()
    tag_token_counts = collections.Counter()

    # Establish exact identity first. Names never classify StaticMesh assets.
    for row in _rows(output / "assets.jsonl", iterator):
        path = str(row.get("object_path", "") or "")
        cls = str(row.get("class_path", "") or "")
        if cls != STATIC_MESH_CLASS or not path:
            continue
        meshes.add(path)
        for key, value in _tag_items(row.get("tags")):
            lowered = key.lower()
            hits = [token for token in TAG_TOKENS if token in lowered]
            if not hits:
                continue
            relevant_tags[path].append((key, value))
            tag_key_counts[key] += 1
            tag_token_counts.update(hits)

    streams = list(STREAMS)
    if include_source:
        streams.append(SOURCE_STREAM)

    stream_counts = collections.Counter()
    detail_token_counts = collections.Counter()
    property_counts = collections.Counter()
    relation_counts = collections.Counter()
    incoming_rows = collections.Counter()
    incoming_owners: dict[str, set[str]] = collections.defaultdict(set)
    static_mesh_component_rows = 0
    static_mesh_component_with_mesh_evidence = 0
    owned_detail_rows = collections.Counter()
    examples: dict[str, list[dict]] = collections.defaultdict(list)

    for filename in streams:
        path = output / filename
        if not path.is_file():
            continue
        for line_number, row in enumerate(_rows(path, iterator), 1):
            stream_counts[filename] += 1
            raw = _text(row)
            lowered = raw.lower()
            hits = [token for token in DETAIL_TOKENS if token in lowered]
            detail_token_counts.update(hits)

            prop = _first(row, "property_path", "property_name", "root_property", "source_property", "field_name")
            if prop and hits:
                property_counts[prop] += 1

            relation = str(row.get("relation", "") or "")
            if relation:
                relation_counts[relation] += 1

            owner = _first(
                row, "owner_path", "owner_id", "asset_path", "object_path",
                "component_path", "actor_path", "blueprint_path", "source_path",
            )
            owner_asset = _first(row, "asset_path", "object_path", "source_path")
            if owner_asset in meshes and filename != "assets.jsonl" and hits:
                owned_detail_rows[filename] += 1

            component_class = _first(row, "component_class", "class_path", "owner_class")
            if filename == "world_components.jsonl" and component_class == STATIC_MESH_COMPONENT_CLASS:
                static_mesh_component_rows += 1

            target = _first(row, "target_path", "referenced_object_path", "reference_path", "target")
            target_class = _first(row, "target_class", "referenced_object_class", "object_class")
            if target in meshes or target_class == STATIC_MESH_CLASS:
                incoming_rows[filename] += 1
                incoming_owners[filename].add(owner or f"{filename}:{line_number}")
                if "component" in filename or "world" in filename:
                    static_mesh_component_with_mesh_evidence += 1

            if ("staticmesh" in lowered or any(token in lowered for token in DETAIL_TOKENS[1:])) and len(examples[filename]) < example_limit:
                examples[filename].append(row)

    proof = collections.Counter({
        "unique_static_mesh_assets": len(meshes),
        "static_mesh_assets_with_relevant_registry_tags": sum(bool(relevant_tags[path]) for path in meshes),
        "relevant_registry_tag_rows": sum(len(values) for values in relevant_tags.values()),
        "static_mesh_component_rows": static_mesh_component_rows,
        "static_mesh_consumer_reference_rows": sum(incoming_rows.values()),
        "static_mesh_consumer_reference_owners": len({owner for owners in incoming_owners.values() for owner in owners}),
        "mesh_owned_detail_rows_in_existing_streams": sum(owned_detail_rows.values()),
    })

    gaps: list[str] = []
    if not meshes:
        gaps.append("No exact /Script/Engine.StaticMesh assets are proven in this corpus.")
    if meshes and not relevant_tags:
        gaps.append("StaticMesh identity is present, but no relevant Asset Registry summary tags were recovered.")
    if meshes and sum(incoming_rows.values()) == 0:
        gaps.append("No exact incoming StaticMesh consumer references were found in the selected canonical streams.")
    if meshes and sum(owned_detail_rows.values()) == 0:
        gaps.append(
            "No existing canonical stream proves mesh-owned LOD/material/socket/collision/Nanite topology; "
            "a focused native authored capture is likely required."
        )
    gaps.append(
        "Asset Registry tags and consumer references are evidence only; they do not prove ordered source LODs, "
        "mesh-owned material slots, sockets, BodySetup collision primitives, section mappings or authored Nanite settings."
    )

    return {
        "output": str(output),
        "diagnostic_only": True,
        "semantic_promotion": False,
        "schema_promotion": False,
        "runtime_state_captured": False,
        "render_buffers_captured": False,
        "include_source": include_source,
        "proof": proof,
        "static_mesh_assets": sorted(meshes),
        "relevant_registry_tags": {
            path: [{"key": key, "value": value} for key, value in sorted(values)]
            for path, values in sorted(relevant_tags.items())
        },
        "tag_key_counts": tag_key_counts,
        "tag_token_counts": tag_token_counts,
        "detail_token_counts": detail_token_counts,
        "property_counts": property_counts,
        "relation_counts": relation_counts,
        "incoming_reference_rows_by_stream": incoming_rows,
        "owned_detail_rows_by_stream": owned_detail_rows,
        "stream_counts": stream_counts,
        "gaps": gaps,
        "examples": dict(examples),
    }


def _print_counter(title: str, values, limit: int = 100) -> None:
    counter = collections.Counter(values)
    print(f"\n[{title}]")
    if not counter:
        print("  <none>")
        return
    for value, count in counter.most_common(limit):
        print(f"  {count:7d}  {_short(value, 700)}")


def render_report(report: dict, *, row_limit: int = 30) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print("=== STATICMESH EVIDENCE REPORT ===")
        print(report["output"])
        print(
            "diagnostic_only=True semantic_promotion=False schema_promotion=False "
            "runtime_state_captured=False render_buffers_captured=False"
        )
        print(f"include_source={report['include_source']}")
        _print_counter("Corpus proof", report["proof"], 80)

        print("\n[StaticMesh assets]")
        values = report["static_mesh_assets"]
        if not values:
            print("  <none>")
        for value in values[:500]:
            print("  " + value)

        print("\n[Relevant Asset Registry tags]")
        tags = report["relevant_registry_tags"]
        if not tags:
            print("  <none>")
        for asset_path, entries in list(tags.items())[:200]:
            print("  " + asset_path)
            for entry in entries[:40]:
                print(f"    {entry['key']}={_short(entry['value'], 900)}")

        print("\n[Evidence gaps / next capture requirements]")
        for gap in report["gaps"]:
            print("  - " + gap)

        _print_counter("Registry tag keys", report["tag_key_counts"], 100)
        _print_counter("Registry tag marker hits", report["tag_token_counts"], 80)
        _print_counter("Authored-topology marker hits", report["detail_token_counts"], 120)
        _print_counter("Property names/paths", report["property_counts"], 160)
        _print_counter("Incoming StaticMesh refs by stream", report["incoming_reference_rows_by_stream"], 80)
        _print_counter("Mesh-owned detail rows by stream", report["owned_detail_rows_by_stream"], 80)
        _print_counter("Project/reference relations", report["relation_counts"], 100)
        _print_counter("Scanned streams", report["stream_counts"], 80)

        print("\n[Representative rows by stream]")
        for filename in STREAMS + (SOURCE_STREAM,):
            values = report["examples"].get(filename, [])
            if not values:
                continue
            print(f"\n--- {filename} ---")
            for index, row in enumerate(values[:row_limit]):
                print(f"[{index}] " + _short(_text(row)))
        print("\n==================================")
    return buffer.getvalue()


def _cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool staticmesh-evidence",
        description="inventory existing StaticMesh authored evidence without changing schemas",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("--no-source", action="store_true")
    parser.add_argument("--row-limit", type=int, default=30)
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    if args.row_limit < 1:
        parser.error("--row-limit must be >= 1")
    output = Path(args.output).expanduser().resolve()
    if not output.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {output}")
    report = build_report(
        output,
        runtime_module._rows,
        include_source=not args.no_source,
        example_limit=max(30, args.row_limit),
    )
    text = render_report(report, row_limit=args.row_limit)
    if args.report:
        target = Path(args.report).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote StaticMesh evidence report: {target}")
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        sys.stdout.write(text.encode(encoding, errors="backslashreplace").decode(encoding))
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_staticmesh_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "staticmesh-evidence":
            try:
                return _cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 64
        return original_main()

    runtime_module.main = main
    runtime_module._staticmesh_evidence_installed = True
