#!/usr/bin/env python3
"""Canonical UnrealAssetTool CLI with schema-8 world derivation."""

from __future__ import annotations

import builtins
import collections
import hashlib
import json
import sqlite3
from pathlib import Path

import uatool_core as core


DERIVED_SCHEMA_VERSION = 8
WORLD_DERIVED_FILES = (
    "world_relations.jsonl",
    "world_context.jsonl",
    "world_summaries.jsonl",
)


def _rows(path: Path):
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    f"Invalid JSON in {path}:{line_number}: {exc}"
                ) from exc


def _write(path: Path, rows: list[dict]) -> int:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
    return len(rows)


def _derive_world(output: Path) -> tuple[list[dict], list[dict], list[dict]]:
    data_layers = {
        (row.get("world_path", ""), row.get("instance_name", "")): row
        for row in _rows(output / "world_data_layers.jsonl")
    }
    actors = list(_rows(output / "world_actors.jsonl"))
    descs = list(_rows(output / "world_partition_actor_descs.jsonl"))
    loaded_by_guid = {
        (row.get("world_path", ""), row.get("actor_guid", "")): row
        for row in actors
        if row.get("actor_guid")
    }
    desc_by_guid = {
        (row.get("world_path", ""), row.get("actor_guid", "")): row
        for row in descs
        if row.get("actor_guid")
    }

    relations: list[dict] = []
    seen: set[tuple[str, ...]] = set()

    def add(
        world_path: str,
        source_kind: str,
        source_id: str,
        relation: str,
        target_kind: str,
        target: str,
        detail: dict | None = None,
    ) -> None:
        if not (world_path and source_id and relation and target):
            return
        detail = detail or {}
        detail_json = json.dumps(
            detail, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        key = (
            world_path,
            source_kind,
            source_id,
            relation,
            target_kind,
            target,
            detail_json,
        )
        if key in seen:
            return
        seen.add(key)
        relations.append(
            {
                "relation_id": "wrel:"
                + hashlib.sha1("\x1f".join(key).encode()).hexdigest()[:24],
                "world_path": world_path,
                "source_kind": source_kind,
                "source_id": source_id,
                "relation": relation,
                "target_kind": target_kind,
                "target": target,
                "detail": detail,
            }
        )

    worlds = list(_rows(output / "worlds.jsonl"))
    levels = list(_rows(output / "world_levels.jsonl"))
    components = list(_rows(output / "world_components.jsonl"))
    properties = list(_rows(output / "world_instance_properties.jsonl"))
    references = list(_rows(output / "world_references.jsonl"))
    data_layer_rows = list(_rows(output / "world_data_layers.jsonl"))

    for world in worlds:
        world_path = world.get("world_path", "")
        persistent_level = world.get("persistent_level_path", "")
        if persistent_level:
            add(
                world_path,
                "world",
                world_path,
                "has_persistent_level",
                "level",
                persistent_level,
                {"package": world.get("package_name", "")},
            )
        partition_path = world.get("world_partition_path", "")
        if world.get("world_partitioned") and partition_path:
            add(
                world_path,
                "world",
                world_path,
                "has_world_partition",
                "world_partition",
                partition_path,
            )

    for level in levels:
        if level.get("level_kind") == "persistent":
            continue
        world_path = level.get("world_path", "")
        add(
            world_path,
            "world",
            world_path,
            "streams_world_package",
            "world_package",
            level.get("target_world_package", ""),
            {
                "streaming_class": level.get("streaming_class", ""),
                "streaming_owner_path": level.get("streaming_owner_path", ""),
            },
        )

    for actor in actors:
        world_path = actor.get("world_path", "")
        actor_path = actor.get("actor_path", "")
        add(
            world_path,
            "world",
            world_path,
            "contains_loaded_actor",
            "actor",
            actor_path,
            {
                "class": actor.get("actor_class", ""),
                "guid": actor.get("actor_guid", ""),
            },
        )
        if actor.get("blueprint_asset"):
            add(
                world_path,
                "actor",
                actor_path,
                "instantiates_blueprint",
                "blueprint",
                actor["blueprint_asset"],
                {"generated_class": actor.get("generated_class", "")},
            )
        if actor.get("attach_parent_actor_path"):
            add(
                world_path,
                "actor",
                actor_path,
                "attached_to_actor",
                "actor",
                actor["attach_parent_actor_path"],
                {"socket": actor.get("attach_parent_socket", "")},
            )
        if actor.get("owner_actor_path"):
            add(
                world_path,
                "actor",
                actor_path,
                "owned_by_actor",
                "actor",
                actor["owner_actor_path"],
            )
        if actor.get("child_actor_parent_path"):
            add(
                world_path,
                "actor",
                actor_path,
                "child_actor_parent",
                "actor",
                actor["child_actor_parent_path"],
            )
        for instance_name in actor.get("data_layer_instance_names", []) or []:
            layer = data_layers.get((world_path, str(instance_name)))
            target = layer.get("instance_path", "") if layer else str(instance_name)
            add(
                world_path,
                "actor",
                actor_path,
                "member_of_data_layer",
                "data_layer_instance" if layer else "data_layer_name",
                target,
                {"instance_name": str(instance_name)},
            )
        for target in actor.get("data_layer_assets", []) or []:
            add(
                world_path,
                "actor",
                actor_path,
                "references_data_layer_asset",
                "data_layer_asset",
                str(target),
            )

    for component in components:
        world_path = component.get("world_path", "")
        actor_path = component.get("actor_path", "")
        component_path = component.get("component_path", "")
        add(
            world_path,
            "actor",
            actor_path,
            "owns_component",
            "component",
            component_path,
            {"class": component.get("component_class", "")},
        )
        if component.get("attach_parent_component_path"):
            add(
                world_path,
                "component",
                component_path,
                "attached_to_component",
                "component",
                component["attach_parent_component_path"],
                {"socket": component.get("attach_socket", "")},
            )

    for reference in references:
        reference_kind = reference.get("reference_kind", "")
        relation = {
            "hard_object": "hard_object_reference",
            "soft_object": "soft_object_reference",
        }.get(reference_kind, "object_reference")
        add(
            reference.get("world_path", ""),
            reference.get("owner_kind", "object"),
            reference.get("owner_path", ""),
            relation,
            reference.get("target_kind", "object"),
            reference.get("target_path", ""),
            {
                "root_property": reference.get("root_property", ""),
                "property_path": reference.get("property_path", ""),
                "target_class": reference.get("target_class", ""),
                "reference_kind": reference_kind,
                "authored_override": bool(reference.get("authored_override", False)),
            },
        )

    for layer in data_layer_rows:
        world_path = layer.get("world_path", "")
        instance_path = layer.get("instance_path", "")
        add(
            world_path,
            "world",
            world_path,
            "contains_data_layer",
            "data_layer_instance",
            instance_path,
            {
                "name": layer.get("short_name", ""),
                "runtime": bool(layer.get("runtime", False)),
            },
        )
        if layer.get("parent_instance_path"):
            add(
                world_path,
                "data_layer_instance",
                instance_path,
                "child_of_data_layer",
                "data_layer_instance",
                layer["parent_instance_path"],
            )
        if layer.get("asset_path"):
            add(
                world_path,
                "data_layer_instance",
                instance_path,
                "uses_data_layer_asset",
                "data_layer_asset",
                layer["asset_path"],
                {"asset_class": layer.get("asset_class", "")},
            )

    for desc in descs:
        world_path = desc.get("world_path", "")
        soft_path = desc.get("actor_soft_path", "")
        guid = desc.get("actor_guid", "")
        add(
            world_path,
            "world",
            world_path,
            "contains_partition_actor_desc",
            "partition_actor",
            soft_path,
            {
                "guid": guid,
                "package": desc.get("actor_package", ""),
                "class": desc.get("native_class", ""),
            },
        )
        loaded = loaded_by_guid.get((world_path, guid))
        if loaded and loaded.get("actor_path"):
            add(
                world_path,
                "partition_actor",
                soft_path,
                "describes_loaded_actor",
                "actor",
                loaded["actor_path"],
                {"guid": guid},
            )
        parent_guid = desc.get("parent_actor_guid", "")
        if parent_guid:
            parent_desc = desc_by_guid.get((world_path, parent_guid))
            add(
                world_path,
                "partition_actor",
                soft_path,
                "parent_partition_actor",
                "partition_actor" if parent_desc else "partition_actor_guid",
                parent_desc.get("actor_soft_path", "") if parent_desc else parent_guid,
                {"target_guid": parent_guid},
            )
        for instance_name in desc.get("data_layer_instance_names", []) or []:
            layer = data_layers.get((world_path, str(instance_name)))
            target = layer.get("instance_path", "") if layer else str(instance_name)
            add(
                world_path,
                "partition_actor",
                soft_path,
                "member_of_data_layer",
                "data_layer_instance" if layer else "data_layer_name",
                target,
                {"instance_name": str(instance_name)},
            )
        for target_guid in desc.get("actor_reference_guids", []) or []:
            target_guid = str(target_guid)
            target_desc = desc_by_guid.get((world_path, target_guid))
            add(
                world_path,
                "partition_actor",
                soft_path,
                "references_partition_actor",
                "partition_actor" if target_desc else "partition_actor_guid",
                target_desc.get("actor_soft_path", "") if target_desc else target_guid,
                {"target_guid": target_guid},
            )

    relations.sort(
        key=lambda row: (
            row["world_path"],
            row["source_kind"],
            row["source_id"],
            row["relation"],
            row["target_kind"],
            row["target"],
            row["relation_id"],
        )
    )

    def count_values(sequence, key):
        return collections.Counter(
            str(row.get(key, "")) for row in sequence if row.get(key)
        )

    actors_by_world = collections.defaultdict(list)
    components_by_world = collections.defaultdict(list)
    properties_by_world = collections.defaultdict(list)
    references_by_world = collections.defaultdict(list)
    levels_by_world = collections.defaultdict(list)
    layers_by_world = collections.defaultdict(list)
    descs_by_world = collections.defaultdict(list)
    relations_by_world = collections.defaultdict(list)

    for row in actors:
        actors_by_world[row.get("world_path", "")].append(row)
    for row in components:
        components_by_world[row.get("world_path", "")].append(row)
    for row in properties:
        properties_by_world[row.get("world_path", "")].append(row)
    for row in references:
        references_by_world[row.get("world_path", "")].append(row)
    for row in levels:
        levels_by_world[row.get("world_path", "")].append(row)
    for row in data_layer_rows:
        layers_by_world[row.get("world_path", "")].append(row)
    for row in descs:
        descs_by_world[row.get("world_path", "")].append(row)
    for row in relations:
        relations_by_world[row["world_path"]].append(row)

    summaries = []
    for world in worlds:
        world_path = world.get("world_path", "")
        loaded_actors = actors_by_world[world_path]
        world_descs = descs_by_world[world_path]
        overlap = len(
            {row.get("actor_guid") for row in loaded_actors if row.get("actor_guid")}
            & {row.get("actor_guid") for row in world_descs if row.get("actor_guid")}
        )
        streaming_count = sum(
            1
            for row in levels_by_world[world_path]
            if row.get("level_kind") != "persistent"
        )
        relation_counts = collections.Counter(
            row["relation"] for row in relations_by_world[world_path]
        )
        summary = {
            "world_path": world_path,
            "world_name": world.get("world_name", ""),
            "package_name": world.get("package_name", ""),
            "persistent_level_path": world.get("persistent_level_path", ""),
            "world_partitioned": bool(world.get("world_partitioned", False)),
            "level_count": len(levels_by_world[world_path]),
            "streaming_relationship_count": streaming_count,
            "loaded_actor_count": len(loaded_actors),
            "partition_actor_desc_count": len(world_descs),
            "descriptor_loaded_overlap_count": overlap,
            "logical_actor_count": len(loaded_actors) + len(world_descs) - overlap,
            "component_count": len(components_by_world[world_path]),
            "instance_override_count": len(properties_by_world[world_path]),
            "reference_count": len(references_by_world[world_path]),
            "data_layer_count": len(layers_by_world[world_path]),
            "actor_class_counts": dict(
                sorted(count_values(loaded_actors, "actor_class").items())
            ),
            "partition_actor_class_counts": dict(
                sorted(count_values(world_descs, "native_class").items())
            ),
            "component_class_counts": dict(
                sorted(
                    count_values(
                        components_by_world[world_path], "component_class"
                    ).items()
                )
            ),
            "relation_counts": dict(sorted(relation_counts.items())),
        }
        summary["text"] = (
            f"World: {world_path}\n"
            f"Partitioned: {summary['world_partitioned']}\n"
            f"Levels: {summary['level_count']} streaming={streaming_count}\n"
            f"Actors: loaded={len(loaded_actors)} partition_desc={len(world_descs)} "
            f"overlap={overlap} logical={summary['logical_actor_count']}\n"
            f"Components: {summary['component_count']} "
            f"Overrides: {summary['instance_override_count']} "
            f"References: {summary['reference_count']} "
            f"DataLayers: {summary['data_layer_count']}\n"
            f"Relations: {dict(sorted(relation_counts.items()))}"
        )
        summaries.append(summary)

    summaries.sort(key=lambda row: row["world_path"])
    summary_by_world = {row["world_path"]: row for row in summaries}

    context = []
    for world_path in sorted(summary_by_world):
        summary = summary_by_world[world_path]
        lines = [summary["text"]]
        if layers_by_world[world_path]:
            lines.append("Data Layers:")
            lines.extend(
                f"  {row.get('instance_name', '')} {row.get('short_name', '')} "
                f"asset={row.get('asset_path', '')}"
                for row in sorted(
                    layers_by_world[world_path],
                    key=lambda row: str(row.get("instance_name", "")),
                )
            )
        streaming = [
            row
            for row in levels_by_world[world_path]
            if row.get("level_kind") != "persistent"
        ]
        if streaming:
            lines.append("Streaming:")
            lines.extend(
                f"  {row.get('streaming_class', '')} -> "
                f"{row.get('target_world_package', '')}"
                for row in streaming
            )
        lines.append("Loaded actors:")
        lines.extend(
            f"  {row.get('actor_label', '')} | {row.get('actor_class', '')} | "
            f"{row.get('actor_path', '')}"
            for row in sorted(
                actors_by_world[world_path],
                key=lambda row: str(row.get("actor_path", "")),
            )
        )
        if descs_by_world[world_path]:
            lines.append("Partition descriptors:")
            lines.extend(
                f"  {row.get('actor_label', '')} | {row.get('native_class', '')} | "
                f"{row.get('actor_soft_path', '')}"
                for row in sorted(
                    descs_by_world[world_path],
                    key=lambda row: str(row.get("actor_soft_path", "")),
                )
            )
        text = "\n".join(lines)
        truncated = len(text) > 524288
        if truncated:
            text = text[:524288] + "\n...[truncated]"
        context.append(
            {
                "world_path": world_path,
                "world_name": summary["world_name"],
                "world_partitioned": summary["world_partitioned"],
                "loaded_actor_count": summary["loaded_actor_count"],
                "partition_actor_desc_count": summary[
                    "partition_actor_desc_count"
                ],
                "logical_actor_count": summary["logical_actor_count"],
                "component_count": summary["component_count"],
                "data_layer_count": summary["data_layer_count"],
                "streaming_relationship_count": summary[
                    "streaming_relationship_count"
                ],
                "truncated": truncated,
                "text": text,
            }
        )

    return relations, context, summaries


WORLD_DERIVED_SQL = """
CREATE TABLE world_relations(
    relation_id TEXT PRIMARY KEY,
    world_path TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    source_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    target_kind TEXT NOT NULL,
    target TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE INDEX world_relations_world_idx ON world_relations(world_path, relation);
CREATE INDEX world_relations_source_idx ON world_relations(source_id, relation);
CREATE INDEX world_relations_target_idx ON world_relations(target, relation);
CREATE TABLE world_context(
    world_path TEXT PRIMARY KEY,
    world_name TEXT NOT NULL,
    world_partitioned INTEGER NOT NULL,
    loaded_actor_count INTEGER NOT NULL,
    partition_actor_desc_count INTEGER NOT NULL,
    logical_actor_count INTEGER NOT NULL,
    component_count INTEGER NOT NULL,
    data_layer_count INTEGER NOT NULL,
    streaming_relationship_count INTEGER NOT NULL,
    truncated INTEGER NOT NULL,
    text TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE TABLE world_summaries(
    world_path TEXT PRIMARY KEY,
    world_name TEXT NOT NULL,
    package_name TEXT NOT NULL,
    persistent_level_path TEXT NOT NULL,
    world_partitioned INTEGER NOT NULL,
    level_count INTEGER NOT NULL,
    streaming_relationship_count INTEGER NOT NULL,
    loaded_actor_count INTEGER NOT NULL,
    partition_actor_desc_count INTEGER NOT NULL,
    descriptor_loaded_overlap_count INTEGER NOT NULL,
    logical_actor_count INTEGER NOT NULL,
    component_count INTEGER NOT NULL,
    instance_override_count INTEGER NOT NULL,
    reference_count INTEGER NOT NULL,
    data_layer_count INTEGER NOT NULL,
    actor_class_counts_json TEXT NOT NULL,
    partition_actor_class_counts_json TEXT NOT NULL,
    component_class_counts_json TEXT NOT NULL,
    relation_counts_json TEXT NOT NULL,
    text TEXT NOT NULL,
    json TEXT NOT NULL
);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    core.create_schema(conn)
    conn.executescript(WORLD_DERIVED_SQL)


def derive_output(output: Path) -> dict[str, int]:
    output = Path(output).expanduser().resolve()
    counts = dict(core.derive_output(output))
    relations, context, summaries = _derive_world(output)
    world_counts = {
        "world_relations": _write(output / "world_relations.jsonl", relations),
        "world_context": _write(output / "world_context.jsonl", context),
        "world_summaries": _write(output / "world_summaries.jsonl", summaries),
    }
    counts.update(world_counts)

    manifest_path = output / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["derived_schema_version"] = DERIVED_SCHEMA_VERSION
        derived_counts = manifest.get("derived_counts", {})
        if not isinstance(derived_counts, dict):
            derived_counts = {}
        derived_counts.update(world_counts)
        manifest["derived_counts"] = derived_counts
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    return counts


def build_database(output: Path) -> Path:
    output = Path(output).expanduser().resolve()
    db_path = core.build_database(output)
    conn = sqlite3.connect(db_path)
    try:
        for row in _rows(output / "world_relations.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO world_relations VALUES(?,?,?,?,?,?,?,?)",
                (
                    row.get("relation_id", ""),
                    row.get("world_path", ""),
                    row.get("source_kind", ""),
                    row.get("source_id", ""),
                    row.get("relation", ""),
                    row.get("target_kind", ""),
                    row.get("target", ""),
                    json.dumps(
                        row.get("detail", {}),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                ),
            )
        for row in _rows(output / "world_context.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO world_context VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row.get("world_path", ""),
                    row.get("world_name", ""),
                    int(bool(row.get("world_partitioned"))),
                    row.get("loaded_actor_count", 0),
                    row.get("partition_actor_desc_count", 0),
                    row.get("logical_actor_count", 0),
                    row.get("component_count", 0),
                    row.get("data_layer_count", 0),
                    row.get("streaming_relationship_count", 0),
                    int(bool(row.get("truncated"))),
                    row.get("text", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )
        for row in _rows(output / "world_summaries.jsonl"):
            conn.execute(
                "INSERT OR REPLACE INTO world_summaries VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    row.get("world_path", ""),
                    row.get("world_name", ""),
                    row.get("package_name", ""),
                    row.get("persistent_level_path", ""),
                    int(bool(row.get("world_partitioned"))),
                    row.get("level_count", 0),
                    row.get("streaming_relationship_count", 0),
                    row.get("loaded_actor_count", 0),
                    row.get("partition_actor_desc_count", 0),
                    row.get("descriptor_loaded_overlap_count", 0),
                    row.get("logical_actor_count", 0),
                    row.get("component_count", 0),
                    row.get("instance_override_count", 0),
                    row.get("reference_count", 0),
                    row.get("data_layer_count", 0),
                    json.dumps(
                        row.get("actor_class_counts", {}), separators=(",", ":")
                    ),
                    json.dumps(
                        row.get("partition_actor_class_counts", {}),
                        separators=(",", ":"),
                    ),
                    json.dumps(
                        row.get("component_class_counts", {}), separators=(",", ":")
                    ),
                    json.dumps(
                        row.get("relation_counts", {}), separators=(",", ":")
                    ),
                    row.get("text", ""),
                    json.dumps(row, ensure_ascii=False, separators=(",", ":")),
                ),
            )
        conn.commit()
    finally:
        conn.close()
    return db_path


def query(args) -> int:
    root = Path(args.output).expanduser().resolve()
    db_path = root if root.suffix.lower() == ".db" else root / core.DB_NAME
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    pattern = f"%{args.term}%"
    try:
        if conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='world_summaries'"
        ).fetchone():
            print("[world summaries]")
            core._print_rows(
                conn.execute(
                    "SELECT world_path,logical_actor_count,data_layer_count,"
                    "substr(text,1,1200) text FROM world_summaries "
                    "WHERE world_path LIKE ? OR text LIKE ? LIMIT ?",
                    (pattern, pattern, args.limit),
                ),
                ("world_path", "logical_actor_count", "data_layer_count", "text"),
            )
            print("\n[world relations]")
            core._print_rows(
                conn.execute(
                    "SELECT world_path,source_kind,source_id,relation,target_kind,target "
                    "FROM world_relations WHERE world_path LIKE ? OR source_id LIKE ? "
                    "OR relation LIKE ? OR target LIKE ? OR detail_json LIKE ? LIMIT ?",
                    (pattern, pattern, pattern, pattern, pattern, args.limit),
                ),
                (
                    "world_path",
                    "source_kind",
                    "source_id",
                    "relation",
                    "target_kind",
                    "target",
                ),
            )
            print("\n[world context]")
            core._print_rows(
                conn.execute(
                    "SELECT world_path,world_name,substr(text,1,1600) text "
                    "FROM world_context WHERE world_path LIKE ? OR world_name LIKE ? "
                    "OR text LIKE ? LIMIT ?",
                    (pattern, pattern, pattern, args.limit),
                ),
                ("world_path", "world_name", "text"),
            )
    finally:
        conn.close()
    return int(_original_query(args))


def _count_line(counts: dict, names: tuple[str, ...]) -> str:
    return " ".join(f"{name}={counts.get(name, 0)}" for name in names)


def _manifest_output(args) -> Path:
    output = (
        Path(args.output).expanduser()
        if args.output
        else Path(args.project).expanduser().resolve().parent / ".uatool"
    )
    return output.resolve()


def _print_summary(args) -> None:
    output = _manifest_output(args)
    manifest_path = output / "manifest.json"
    world_manifest_path = output / "world_manifest.json"
    if not (manifest_path.is_file() and world_manifest_path.is_file()):
        return

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    world_manifest = json.loads(world_manifest_path.read_text(encoding="utf-8"))
    structural_counts = (
        manifest.get("counts", {})
        if isinstance(manifest.get("counts", {}), dict)
        else {}
    )
    world_counts = (
        world_manifest.get("counts", {})
        if isinstance(world_manifest.get("counts", {}), dict)
        else {}
    )
    derived_counts = (
        manifest.get("derived_counts", {})
        if isinstance(manifest.get("derived_counts", {}), dict)
        else {}
    )

    print()
    print("=== UATOOL FINAL SUMMARY ===")
    print(
        "structural scan complete: "
        + _count_line(
            structural_counts,
            (
                "files",
                "assets",
                "blueprints",
                "blueprint_graphs",
                "blueprint_nodes",
                "blueprint_pins",
                "blueprint_edges",
            ),
        )
    )
    print(
        "world scan complete: "
        + _count_line(
            world_counts,
            (
                "worlds",
                "levels",
                "streaming_relationships",
                "actors",
                "components",
                "instance_overrides",
                "references",
                "data_layers",
                "world_partition_worlds",
                "world_partition_initialized_for_scan",
                "world_partition_actor_descs",
            ),
        )
    )
    print(
        "derived complete: "
        + _count_line(
            derived_counts,
            (
                "world_relations",
                "world_context",
                "world_summaries",
                "blueprint_call_bindings",
                "blueprint_data_dependencies",
                "blueprint_relations",
                "ai_relations",
                "visual_relations",
            ),
        )
    )
    print(
        f"schemas: structural={manifest.get('schema_version', 0)} "
        f"world={world_manifest.get('schema_version', 0)} "
        f"derived={manifest.get('derived_schema_version', 0)}"
    )
    print(f"database: {output / core.DB_NAME}")
    if not args.no_bundle:
        project = Path(args.project).expanduser().resolve()
        print(f"upload bundle: {project.parent / f'{project.stem}.uatool.zip'}")
    print("============================")


_original_create_schema = core.create_schema
_original_derive_output = core.derive_output
_original_build_database = core.build_database
_original_query = core.query
_original_scan = core.scan


def scan(args) -> int:
    suppress_summary = False
    had_print = "print" in core.__dict__
    previous_print = core.__dict__.get("print", builtins.print)

    def filtered_print(*values, **kwargs):
        nonlocal suppress_summary
        text = " ".join(str(value) for value in values)
        if not suppress_summary and text == "=== UATOOL FINAL SUMMARY ===":
            suppress_summary = True
            return None
        if suppress_summary:
            if text == "============================":
                suppress_summary = False
            return None
        return previous_print(*values, **kwargs)

    core.print = filtered_print
    try:
        result = int(_original_scan(args))
    finally:
        if had_print:
            core.print = previous_print
        else:
            core.__dict__.pop("print", None)
    if result == 0:
        _print_summary(args)
    return result


# Preserve the validated schema-12 core and install schema-8 extensions before
# the parser binds handlers. `python scripts/uatool.py ...` remains canonical.
core.DERIVED_SCHEMA_VERSION = DERIVED_SCHEMA_VERSION
core.create_schema = create_schema
core.derive_output = derive_output
core.build_database = build_database
core.query = query
core.scan = scan
core.DEFAULT_BUNDLE_FILES = tuple(
    dict.fromkeys((*core.DEFAULT_BUNDLE_FILES, *WORLD_DERIVED_FILES))
)


def main() -> int:
    return int(core.main())


if __name__ == "__main__":
    raise SystemExit(main())
