#!/usr/bin/env python3
"""Read-only Landscape / Foliage / HLOD authored-evidence inventory.

The diagnostic measures only facts already present in a canonical corpus. Exact
class paths nominate candidate families; asset/object names never classify an
item. World-authored actor/component properties and references are kept separate
from asset-owned settings and World Partition descriptor metadata so a later
schema can preserve the correct ownership boundary.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import io
import json
from pathlib import Path
import sys

FAMILIES = ("landscape", "foliage", "hlod")

WORLD_STREAMS = (
    "world_actors.jsonl",
    "world_components.jsonl",
    "world_instance_properties.jsonl",
    "world_references.jsonl",
    "world_partition_actor_descs.jsonl",
)
ASSET_STREAMS = (
    "assets.jsonl",
    "systems_properties.jsonl",
    "systems_references.jsonl",
)
SUPPORT_STREAMS = (
    "blueprint_component_properties.jsonl",
    "blueprint_state_values.jsonl",
    "blueprint_node_references.jsonl",
    "project_edges.jsonl",
)

GENERIC_INSTANCE_COMPONENT_CLASSES = {
    "/Script/Engine.InstancedStaticMeshComponent",
    "/Script/Engine.HierarchicalInstancedStaticMeshComponent",
}

DETAIL_TOKENS = {
    "landscape": (
        "landscapematerial", "landscapeholematerial", "layerinfo", "weightmap",
        "heightmap", "editlayer", "landscapelayer", "componentsectionbase",
        "sectionbase", "subsection", "landscapespline", "grass",
    ),
    "foliage": (
        "foliagetype", "foliage", "instance", "mesh", "density", "radius",
        "scalemin", "scalemax", "align", "cull", "procedural",
    ),
    "hlod": (
        "hlodlayer", "hlod", "worldpartitionhlod", "cell", "sourceactors",
        "layer", "runtimegrid", "spatiallyloaded",
    ),
}


def _rows(path: Path, iterator):
    if not path.is_file():
        return
    for row in iterator(path):
        if isinstance(row, dict):
            yield row


def _family_for_class(class_path: object) -> str | None:
    """Classify only from exact reflected/native class paths, never object names."""
    value = str(class_path or "")
    lowered = value.lower()
    if lowered.startswith("/script/landscape."):
        return "landscape"
    if lowered.startswith("/script/foliage."):
        return "foliage"
    if lowered.startswith("/script/") and "hlod" in lowered:
        return "hlod"
    return None


def _first(row: dict, *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _text(row: dict) -> str:
    return json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _counter_dict() -> dict[str, collections.Counter]:
    return {family: collections.Counter() for family in FAMILIES}


def _examples_dict() -> dict[str, dict[str, list[dict]]]:
    return {family: collections.defaultdict(list) for family in FAMILIES}


def build_report(output: Path, iterator, *, example_limit: int = 40) -> dict:
    output = Path(output).expanduser().resolve()
    if example_limit < 1:
        raise ValueError("example_limit must be >= 1")

    class_counts = {
        "assets": _counter_dict(),
        "actors": _counter_dict(),
        "components": _counter_dict(),
        "partition_descs": _counter_dict(),
    }
    asset_paths: dict[str, set[str]] = {family: set() for family in FAMILIES}
    actor_paths: dict[str, set[str]] = {family: set() for family in FAMILIES}
    component_paths: dict[str, set[str]] = {family: set() for family in FAMILIES}
    actor_family_by_path: dict[str, str] = {}
    component_family_by_path: dict[str, str] = {}
    asset_family_by_path: dict[str, str] = {}
    examples = _examples_dict()
    tag_keys = _counter_dict()
    tag_rows = _counter_dict()

    # Exact asset identity/class evidence.
    for row in _rows(output / "assets.jsonl", iterator):
        family = _family_for_class(row.get("class_path"))
        path = str(row.get("object_path", "") or "")
        if not family or not path:
            continue
        cls = str(row.get("class_path", ""))
        asset_paths[family].add(path)
        asset_family_by_path[path] = family
        class_counts["assets"][family][cls] += 1
        if len(examples[family]["assets.jsonl"]) < example_limit:
            examples[family]["assets.jsonl"].append(row)
        for key, value in _tag_items(row.get("tags")):
            lowered = key.lower()
            if any(token in lowered for token in DETAIL_TOKENS[family]):
                tag_keys[family][key] += 1
                tag_rows[family][f"{key}={value}"] += 1

    # Exact actor classes first so generic child components can inherit only a
    # proven owner-family association (not a name-based foliage guess).
    actors = list(_rows(output / "world_actors.jsonl", iterator))
    for row in actors:
        family = _family_for_class(row.get("actor_class"))
        actor = str(row.get("actor_path", "") or "")
        if not family or not actor:
            continue
        actor_paths[family].add(actor)
        actor_family_by_path[actor] = family
        class_counts["actors"][family][str(row.get("actor_class", ""))] += 1
        if len(examples[family]["world_actors.jsonl"]) < example_limit:
            examples[family]["world_actors.jsonl"].append(row)

    generic_instance_components = collections.Counter()
    generic_instance_components_under_foliage_actor = 0
    for row in _rows(output / "world_components.jsonl", iterator):
        cls = str(row.get("component_class", "") or "")
        family = _family_for_class(cls)
        actor = str(row.get("actor_path", "") or "")
        component = str(row.get("component_path", "") or "")
        if cls in GENERIC_INSTANCE_COMPONENT_CLASSES:
            generic_instance_components[cls] += 1
            if actor_family_by_path.get(actor) == "foliage":
                generic_instance_components_under_foliage_actor += 1
        # A generic ISM/HISM component is not foliage by class. It is associated
        # with foliage only when its exact owning actor is already proven foliage.
        if not family and actor_family_by_path.get(actor) in FAMILIES:
            family = actor_family_by_path[actor]
        if not family or not component:
            continue
        component_paths[family].add(component)
        component_family_by_path[component] = family
        class_counts["components"][family][cls] += 1
        if len(examples[family]["world_components.jsonl"]) < example_limit:
            examples[family]["world_components.jsonl"].append(row)

    owner_family: dict[str, str] = {}
    owner_family.update(actor_family_by_path)
    owner_family.update(component_family_by_path)

    property_counts = _counter_dict()
    reference_property_counts = _counter_dict()
    world_property_rows = collections.Counter()
    world_reference_rows = collections.Counter()
    target_class_counts = _counter_dict()

    for row in _rows(output / "world_instance_properties.jsonl", iterator):
        owner = str(row.get("owner_path", "") or "")
        family = owner_family.get(owner)
        if not family:
            continue
        world_property_rows[family] += 1
        prop = _first(row, "property_path", "property_name", "root_property")
        if prop:
            property_counts[family][prop] += 1
        if len(examples[family]["world_instance_properties.jsonl"]) < example_limit:
            examples[family]["world_instance_properties.jsonl"].append(row)

    for row in _rows(output / "world_references.jsonl", iterator):
        owner = str(row.get("owner_path", "") or "")
        family = owner_family.get(owner)
        if family:
            world_reference_rows[family] += 1
            prop = _first(row, "property_path", "root_property")
            if prop:
                reference_property_counts[family][prop] += 1
            target_class = str(row.get("target_class", "") or "")
            if target_class:
                target_class_counts[family][target_class] += 1
            if len(examples[family]["world_references.jsonl"]) < example_limit:
                examples[family]["world_references.jsonl"].append(row)

    systems_property_rows = collections.Counter()
    systems_reference_rows = collections.Counter()
    asset_property_counts = _counter_dict()
    for filename in ("systems_properties.jsonl", "systems_references.jsonl"):
        for row in _rows(output / filename, iterator):
            owner = _first(row, "asset_path", "object_path", "owner_path", "source_path")
            family = asset_family_by_path.get(owner)
            if not family:
                continue
            if filename == "systems_properties.jsonl":
                systems_property_rows[family] += 1
                prop = _first(row, "property_path", "property_name", "field_name")
                if prop:
                    asset_property_counts[family][prop] += 1
            else:
                systems_reference_rows[family] += 1
            if len(examples[family][filename]) < example_limit:
                examples[family][filename].append(row)

    partition_hlod_relevant = 0
    for row in _rows(output / "world_partition_actor_descs.jsonl", iterator):
        if bool(row.get("hlod_relevant", False)):
            partition_hlod_relevant += 1
        cls = str(row.get("native_class", "") or "")
        family = _family_for_class(cls)
        if not family:
            continue
        class_counts["partition_descs"][family][cls] += 1
        if len(examples[family]["world_partition_actor_descs.jsonl"]) < example_limit:
            examples[family]["world_partition_actor_descs.jsonl"].append(row)

    # Supporting rows are marker inventory only. They never establish family
    # identity and therefore cannot promote semantics by themselves.
    support_marker_rows = _counter_dict()
    for filename in SUPPORT_STREAMS:
        for row in _rows(output / filename, iterator):
            lowered = _text(row).lower()
            for family in FAMILIES:
                if any(token in lowered for token in DETAIL_TOKENS[family]):
                    support_marker_rows[family][filename] += 1

    proof: dict[str, dict[str, int]] = {}
    gaps: dict[str, list[str]] = {family: [] for family in FAMILIES}
    for family in FAMILIES:
        proof[family] = {
            "exact_asset_candidates": len(asset_paths[family]),
            "exact_world_actor_candidates": len(actor_paths[family]),
            "exact_world_component_candidates": len(component_paths[family]),
            "world_authored_property_rows": int(world_property_rows[family]),
            "world_authored_reference_rows": int(world_reference_rows[family]),
            "asset_owned_system_property_rows": int(systems_property_rows[family]),
            "asset_owned_system_reference_rows": int(systems_reference_rows[family]),
            "partition_descriptor_candidates": int(sum(class_counts["partition_descs"][family].values())),
        }
        if not any(proof[family].values()):
            gaps[family].append(f"No exact {family} class-path candidates are proven in this corpus.")
        if family == "landscape" and actor_paths[family] and not world_property_rows[family]:
            gaps[family].append("Landscape actors/components exist but world12 has no owned property rows; focused authored capture is likely required.")
        if family == "foliage" and asset_paths[family] and not systems_property_rows[family]:
            gaps[family].append("Foliage assets exist but current systems streams do not prove asset-owned FoliageType settings.")
        if family == "hlod" and (asset_paths[family] or actor_paths[family]) and not (systems_property_rows[family] or world_property_rows[family]):
            gaps[family].append("HLOD candidates exist but current streams do not prove authored layer/composition settings.")

    gaps["landscape"].append(
        "World actor/component state must remain separate from generated heightfield/render resources and from independent Landscape layer-info assets."
    )
    gaps["foliage"].append(
        "Generic ISM/HISM components are not foliage evidence unless exact owning actor/class provenance proves the association; per-instance authored placement still needs explicit evidence."
    )
    gaps["hlod"].append(
        "WorldPartition descriptor hlod_relevant is supporting metadata only; it does not prove authored HLODLayer policy or generated proxy composition."
    )

    return {
        "output": str(output),
        "diagnostic_only": True,
        "semantic_promotion": False,
        "schema_promotion": False,
        "runtime_state_captured": False,
        "generated_geometry_captured": False,
        "proof": proof,
        "class_counts": class_counts,
        "property_counts": property_counts,
        "reference_property_counts": reference_property_counts,
        "target_class_counts": target_class_counts,
        "asset_property_counts": asset_property_counts,
        "asset_registry_tag_keys": tag_keys,
        "asset_registry_tag_rows": tag_rows,
        "support_marker_rows": support_marker_rows,
        "generic_instance_component_classes": generic_instance_components,
        "generic_instance_components_under_foliage_actor": generic_instance_components_under_foliage_actor,
        "partition_hlod_relevant_descriptors": partition_hlod_relevant,
        "gaps": gaps,
        "examples": examples,
    }


def _print_counter(title: str, values, limit: int = 100) -> None:
    counter = collections.Counter(values)
    print(f"\n[{title}]")
    if not counter:
        print("  <none>")
        return
    for value, count in counter.most_common(limit):
        print(f"  {count:7d}  {_short(value, 900)}")


def render_report(report: dict, *, row_limit: int = 30) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        print("=== LANDSCAPE / FOLIAGE / HLOD EVIDENCE REPORT ===")
        print(report["output"])
        print(
            "diagnostic_only=True semantic_promotion=False schema_promotion=False "
            "runtime_state_captured=False generated_geometry_captured=False"
        )
        print(f"partition_hlod_relevant_descriptors={report['partition_hlod_relevant_descriptors']}")
        print(f"generic_instance_components_under_foliage_actor={report['generic_instance_components_under_foliage_actor']}")

        for family in FAMILIES:
            print(f"\n========== {family.upper()} ==========")
            _print_counter("Corpus proof", report["proof"][family], 40)
            for domain in ("assets", "actors", "components", "partition_descs"):
                _print_counter(f"Exact {domain} classes", report["class_counts"][domain][family], 100)
            _print_counter("World authored property paths", report["property_counts"][family], 180)
            _print_counter("World reference property paths", report["reference_property_counts"][family], 120)
            _print_counter("World reference target classes", report["target_class_counts"][family], 120)
            _print_counter("Asset-owned systems property paths", report["asset_property_counts"][family], 160)
            _print_counter("Asset Registry tag keys", report["asset_registry_tag_keys"][family], 100)
            _print_counter("Supporting marker rows", report["support_marker_rows"][family], 80)
            print("\n[Evidence gaps / next capture requirements]")
            for gap in report["gaps"][family]:
                print("  - " + gap)

            print("\n[Representative rows]")
            for filename in (*ASSET_STREAMS, *WORLD_STREAMS):
                values = report["examples"][family].get(filename, [])
                if not values:
                    continue
                print(f"\n--- {filename} ---")
                for index, row in enumerate(values[:row_limit]):
                    print(f"[{index}] " + _short(_text(row)))

        _print_counter("Generic ISM/HISM component classes", report["generic_instance_component_classes"], 40)
        print("\n================================================")
    return buffer.getvalue()


def _cli(runtime_module, argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool landscape-foliage-hlod-evidence",
        description="inventory existing Landscape/Foliage/HLOD authored evidence without changing schemas",
    )
    parser.add_argument("output", help="source .uatool directory")
    parser.add_argument("--row-limit", type=int, default=30)
    parser.add_argument("--report")
    args = parser.parse_args(argv)
    if args.row_limit < 1:
        parser.error("--row-limit must be >= 1")
    output = Path(args.output).expanduser().resolve()
    if not output.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {output}")
    report = build_report(output, runtime_module._rows, example_limit=max(30, args.row_limit))
    text = render_report(report, row_limit=args.row_limit)
    if args.report:
        target = Path(args.report).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote Landscape/Foliage/HLOD evidence report: {target}")
    try:
        sys.stdout.write(text)
    except UnicodeEncodeError:
        encoding = sys.stdout.encoding or "utf-8"
        sys.stdout.write(text.encode(encoding, errors="backslashreplace").decode(encoding))
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_world_geometry_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "landscape-foliage-hlod-evidence":
            try:
                return _cli(runtime_module, sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 68
        return original_main()

    runtime_module.main = main
    runtime_module._world_geometry_evidence_installed = True
