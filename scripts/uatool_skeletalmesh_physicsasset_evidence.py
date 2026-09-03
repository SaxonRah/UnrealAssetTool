#!/usr/bin/env python3
"""Read-only SkeletalMesh / PhysicsAsset animation-context evidence inventory.

The command inventories what current canonical corpora already prove. It does
not define animation schema 2 and does not infer runtime physics/skinning state.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
from pathlib import Path
import sys

SKELETAL_MESH_CLASS = "/Script/Engine.SkeletalMesh"
PHYSICS_ASSET_CLASS = "/Script/Engine.PhysicsAsset"

STREAMS = (
    "assets.jsonl",
    "asset_dependencies.jsonl",
    "animation_assets.jsonl",
    "animation_optional_assets.jsonl",
    "animation_properties.jsonl",
    "animation_references.jsonl",
    "blueprints.jsonl",
    "blueprint_component_properties.jsonl",
    "blueprint_state_values.jsonl",
    "blueprint_node_properties.jsonl",
    "blueprint_node_references.jsonl",
    "blueprint_semantic_nodes.jsonl",
    "blueprint_semantic_statements.jsonl",
    "world_actors.jsonl",
    "world_components.jsonl",
    "world_instance_properties.jsonl",
    "world_references.jsonl",
    "project_nodes.jsonl",
    "project_edges.jsonl",
)
SOURCE_STREAM = "source_chunks.jsonl"

DETAIL_TOKENS = (
    "skeleton", "physicsasset", "shadowphysicsasset", "lodinfo", "lodsettings",
    "materials", "materialslot", "morphtarget", "clothing", "cloth", "socket",
    "skeletalbodysetup", "bodysetup", "constraintsetup", "constrainttemplate",
    "collisiondisabletable", "physicalanimation", "physicsblendprofile", "agggeom",
    "sphylelems", "boxelems", "sphereelems", "convexelems", "previewmesh",
    "skeletalmeshcomponent", "overridephysicsasset", "setphysicsasset",
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


def build_report(output: Path, iterator, *, include_source: bool = True, example_limit: int = 30) -> dict:
    output = Path(output).expanduser().resolve()
    if example_limit < 1:
        raise ValueError("example_limit must be >= 1")

    streams = list(STREAMS)
    if include_source:
        streams.append(SOURCE_STREAM)

    meshes: set[str] = set()
    physics_assets: set[str] = set()
    class_by_path: dict[str, str] = {}
    stream_counts = collections.Counter()
    token_counts = collections.Counter()
    class_counts = collections.Counter()
    property_counts = collections.Counter()
    relation_counts = collections.Counter()
    examples: dict[str, list[dict]] = collections.defaultdict(list)

    animation_classified = collections.Counter()
    animation_owned_properties = collections.Counter()
    animation_owned_references = collections.Counter()
    incoming_reference_rows = collections.Counter()
    incoming_reference_owners: dict[str, set[str]] = collections.defaultdict(set)
    property_owners: dict[str, set[str]] = collections.defaultdict(set)

    # First pass establishes exact asset identity before attributing references.
    for row in _rows(output / "assets.jsonl", iterator):
        path = str(row.get("object_path", "") or "")
        cls = str(row.get("class_path", "") or "")
        if path:
            class_by_path[path] = cls
        if cls == SKELETAL_MESH_CLASS and path:
            meshes.add(path)
        elif cls == PHYSICS_ASSET_CLASS and path:
            physics_assets.add(path)

    for filename in streams:
        path = output / filename
        if not path.is_file():
            continue
        for line_number, row in enumerate(_rows(path, iterator), 1):
            stream_counts[filename] += 1
            raw = _text(row)
            lowered = raw.lower()
            hits = [token for token in DETAIL_TOKENS if token in lowered]
            token_counts.update(hits)

            cls = _first(row, "class_path", "asset_class", "owner_class", "component_class", "target_class", "node_class")
            if cls:
                class_counts[cls] += 1
            prop = _first(row, "property_path", "property_name", "root_property", "source_property", "field_name")
            owner = _first(row, "owner_path", "owner_id", "object_path", "asset_path", "blueprint_path", "component_path", "actor_path", "animation_path")
            relation = str(row.get("relation", "") or "")
            if relation:
                relation_counts[relation] += 1
            if prop and hits:
                property_counts[prop] += 1
                for token in hits:
                    property_owners[token].add(owner or f"{filename}:{line_number}")

            if filename in {"animation_assets.jsonl", "animation_optional_assets.jsonl"}:
                row_cls = str(row.get("class_path", "") or "")
                if row_cls in {SKELETAL_MESH_CLASS, PHYSICS_ASSET_CLASS}:
                    animation_classified[row_cls] += 1

            asset_path = _first(row, "asset_path", "animation_path")
            family = "skeletal_mesh" if asset_path in meshes else "physics_asset" if asset_path in physics_assets else ""
            if filename == "animation_properties.jsonl" and family:
                animation_owned_properties[family] += 1
            if filename == "animation_references.jsonl" and family:
                animation_owned_references[family] += 1

            target_path = _first(row, "target_path", "referenced_object_path", "reference_path", "target")
            target_class = _first(row, "target_class", "referenced_object_class", "object_class")
            target_family = ""
            if target_class == SKELETAL_MESH_CLASS or target_path in meshes:
                target_family = "skeletal_mesh"
            elif target_class == PHYSICS_ASSET_CLASS or target_path in physics_assets:
                target_family = "physics_asset"
            if target_family and filename in {"animation_references.jsonl", "blueprint_node_references.jsonl", "world_references.jsonl", "project_edges.jsonl"}:
                incoming_reference_rows[target_family] += 1
                incoming_reference_owners[target_family].add(owner or f"{filename}:{line_number}")

            if ("skeletalmesh" in lowered or "physicsasset" in lowered) and len(examples[filename]) < example_limit:
                examples[filename].append(row)

    proof = collections.Counter({
        "unique_skeletal_mesh_assets": len(meshes),
        "unique_physics_asset_assets": len(physics_assets),
        "skeletal_mesh_animation_classified_assets": animation_classified[SKELETAL_MESH_CLASS],
        "physics_asset_animation_classified_assets": animation_classified[PHYSICS_ASSET_CLASS],
        "skeletal_mesh_owned_animation_property_rows": animation_owned_properties["skeletal_mesh"],
        "physics_asset_owned_animation_property_rows": animation_owned_properties["physics_asset"],
        "skeletal_mesh_owned_animation_reference_rows": animation_owned_references["skeletal_mesh"],
        "physics_asset_owned_animation_reference_rows": animation_owned_references["physics_asset"],
        "skeletal_mesh_exact_incoming_reference_rows": incoming_reference_rows["skeletal_mesh"],
        "physics_asset_exact_incoming_reference_rows": incoming_reference_rows["physics_asset"],
        "skeletal_mesh_exact_incoming_reference_owners": len(incoming_reference_owners["skeletal_mesh"]),
        "physics_asset_exact_incoming_reference_owners": len(incoming_reference_owners["physics_asset"]),
    })
    for token, owners in sorted(property_owners.items()):
        proof[f"{token}_owners"] = len(owners)

    gaps: list[str] = []
    if not meshes:
        gaps.append("No exact /Script/Engine.SkeletalMesh assets are proven in this corpus.")
    if not physics_assets:
        gaps.append("No exact /Script/Engine.PhysicsAsset assets are proven in this corpus.")
    if meshes and animation_classified[SKELETAL_MESH_CLASS] == 0:
        gaps.append("SkeletalMesh is structurally visible but animation schema 1 does not classify/load it.")
    if physics_assets and animation_classified[PHYSICS_ASSET_CLASS] == 0:
        gaps.append("PhysicsAsset is structurally visible but animation schema 1 does not classify/load it.")
    if meshes and animation_owned_properties["skeletal_mesh"] == 0:
        gaps.append("No mesh-owned animation property rows exist; LOD/material/morph/cloth/socket internals likely require a focused native load/capture.")
    if physics_assets and animation_owned_properties["physics_asset"] == 0:
        gaps.append("No PhysicsAsset-owned animation property rows exist; body/constraint/collision/profile internals likely require a focused native load/capture.")
    if meshes and incoming_reference_rows["skeletal_mesh"] == 0:
        gaps.append("No exact incoming SkeletalMesh reference was found in the selected canonical streams.")
    if physics_assets and incoming_reference_rows["physics_asset"] == 0:
        gaps.append("No exact incoming PhysicsAsset reference was found in the selected canonical streams.")

    return {
        "output": str(output),
        "diagnostic_only": True,
        "semantic_promotion": False,
        "schema_promotion": False,
        "runtime_state_captured": False,
        "include_source": include_source,
        "proof": proof,
        "skeletal_mesh_assets": sorted(meshes),
        "physics_asset_assets": sorted(physics_assets),
        "stream_counts": stream_counts,
        "token_counts": token_counts,
        "class_counts": class_counts,
        "property_counts": property_counts,
        "relation_counts": relation_counts,
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
        print("=== SKELETALMESH / PHYSICSASSET EVIDENCE REPORT ===")
        print(report["output"])
        print("diagnostic_only=True semantic_promotion=False schema_promotion=False runtime_state_captured=False")
        print(f"include_source={report['include_source']}")
        _print_counter("Corpus proof", report["proof"], 160)

        for title, key in (("SkeletalMesh assets", "skeletal_mesh_assets"), ("PhysicsAsset assets", "physics_asset_assets")):
            values = report[key]
            if values:
                print(f"\n[{title}]")
                for value in values[:300]:
                    print("  " + value)

        print("\n[Evidence gaps / next capture requirements]")
        if not report["gaps"]:
            print("  <none identified by this diagnostic>")
        for gap in report["gaps"]:
            print("  - " + gap)

        _print_counter("High-value marker hits", report["token_counts"], 160)
        _print_counter("Property names/paths", report["property_counts"], 180)
        _print_counter("Relevant classes", report["class_counts"], 120)
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
        print("\n====================================================")
    return buffer.getvalue()


def _cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool skeletalmesh-physicsasset-evidence",
        description="inventory existing SkeletalMesh / PhysicsAsset authored evidence without changing schemas",
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
    report = build_report(output, runtime_module._rows, include_source=not args.no_source, example_limit=max(30, args.row_limit))
    text = render_report(report, row_limit=args.row_limit)
    if args.report:
        target = Path(args.report).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote SkeletalMesh/PhysicsAsset evidence report: {target}")
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        sys.stdout.write(text.encode(encoding, errors="backslashreplace").decode(encoding))
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_skeletalmesh_physicsasset_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "skeletalmesh-physicsasset-evidence":
            try:
                return _cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 62
        return original_main()

    runtime_module.main = main
    runtime_module._skeletalmesh_physicsasset_evidence_installed = True
