#!/usr/bin/env python3
"""Derived VFX relations, summaries, and bounded asset context.

Only exact normalized VFX topology, exact reflected object references, exact
world references, and exact Blueprint relations are promoted. Generic package
dependencies are deliberately excluded from semantic VFX relations.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re

DERIVED_SCHEMA_VERSION = 12
DERIVED_FILES = (
    "vfx_relations.jsonl",
    "vfx_context.jsonl",
    "vfx_summaries.jsonl",
)
MAX_CONTEXT_LINKS_PER_ASSET = 250
MAX_CONTEXT_CHARS = 262144

_SQL = """
CREATE TABLE vfx_relations(
 relation_id TEXT PRIMARY KEY,source_kind TEXT NOT NULL,source TEXT NOT NULL,
 relation TEXT NOT NULL,target_kind TEXT NOT NULL,target TEXT NOT NULL,
 target_coverage TEXT NOT NULL,evidence_count INTEGER NOT NULL,evidence_json TEXT NOT NULL);
CREATE INDEX vfx_relations_source_idx ON vfx_relations(source,relation);
CREATE INDEX vfx_relations_target_idx ON vfx_relations(target,relation);
CREATE INDEX vfx_relations_kind_idx ON vfx_relations(source_kind,target_kind,relation);
CREATE TABLE vfx_context(
 asset_path TEXT PRIMARY KEY,asset_kind TEXT NOT NULL,class_path TEXT NOT NULL,
 coverage TEXT NOT NULL,outgoing_count INTEGER NOT NULL,incoming_count INTEGER NOT NULL,
 truncated INTEGER NOT NULL,text TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX vfx_context_kind_idx ON vfx_context(asset_kind);
CREATE TABLE vfx_summaries(
 asset_path TEXT PRIMARY KEY,asset_kind TEXT NOT NULL,class_path TEXT NOT NULL,
 coverage TEXT NOT NULL,package_name TEXT NOT NULL,outgoing_count INTEGER NOT NULL,
 incoming_count INTEGER NOT NULL,relation_counts_json TEXT NOT NULL,text TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX vfx_summaries_kind_idx ON vfx_summaries(asset_kind);
"""


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def _class_leaf(class_path: str) -> str:
    value = str(class_path or "").rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower() or "asset"


def _generic_coverage(class_path: str) -> str:
    if class_path in {"/Script/Engine.UserDefinedStruct", "/Script/Engine.UserDefinedEnum"}:
        return "partial"
    return "generic_only"


def _summary_lines(meta: dict) -> list[str]:
    lines = [
        f"VFX asset: {meta.get('path', '')}",
        f"Kind: {meta.get('kind', '')}",
        f"Class: {meta.get('class_path', '')}",
        f"Coverage: {meta.get('coverage', '')}",
    ]
    if meta.get("package_name"):
        lines.append(f"Package: {meta['package_name']}")
    facts = meta.get("facts", {})
    keys = (
        "emitter_count", "version_count", "renderer_count", "simulation_stage_count",
        "module_count", "variable_count", "parameter_count", "effect_type_path",
        "source_collection_path", "update_frequency", "cull_reaction",
    )
    values = [f"{key}={facts[key]}" for key in keys if key in facts and facts[key] not in ("", None)]
    if values:
        lines.append("Facts: " + " ".join(values))
    return lines


def derive(output, rows) -> tuple[list[dict], list[dict], list[dict]]:
    registry: dict[str, dict] = {}
    roots: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    rank = {
        "external_or_excluded": 0,
        "generic_only": 1,
        "partial": 2,
        "first_class_depth_pending": 3,
        "first_class": 4,
    }

    def register(path, kind, coverage, class_path="", package_name="", root=False, facts=None):
        path = str(path or "")
        if not path:
            return
        candidate = {
            "path": path,
            "kind": str(kind or "object"),
            "coverage": str(coverage or "generic_only"),
            "class_path": str(class_path or ""),
            "package_name": str(package_name or ""),
        }
        current = registry.get(path)
        if current is None or rank.get(candidate["coverage"], 0) >= rank.get(current.get("coverage", ""), 0):
            registry[path] = candidate
        if root:
            roots[path] = {**registry[path], "facts": dict(facts or {})}

    for row in rows(output / "assets.jsonl"):
        class_path = str(row.get("class_path", ""))
        register(
            row.get("object_path"),
            _class_leaf(class_path),
            _generic_coverage(class_path),
            class_path,
            row.get("package_name"),
        )

    for row in rows(output / "blueprints.jsonl"):
        path = str(row.get("object_path", ""))
        register(path, "blueprint", "first_class", row.get("class"), path.split(".", 1)[0])
        generated = str(row.get("generated_class", ""))
        if generated and path:
            aliases[generated] = path

    for row in rows(output / "world_actors.jsonl"):
        register(row.get("actor_path"), "actor", "first_class", row.get("actor_class"))
    for row in rows(output / "world_components.jsonl"):
        register(row.get("component_path"), "component", "first_class", row.get("component_class"))

    vfx_asset_rows = list(rows(output / "vfx_assets.jsonl"))
    for row in vfx_asset_rows:
        register(
            row.get("vfx_path"), row.get("vfx_kind", "vfx_asset"), "first_class",
            row.get("class_path"), row.get("package_name"), True, row,
        )

    for row in rows(output / "vfx_properties.jsonl"):
        register(
            row.get("owner_path"), row.get("owner_kind", "vfx_object"), "first_class",
            row.get("owner_class"), str(row.get("asset_path", "")).split(".", 1)[0],
        )

    for row in rows(output / "niagara_emitters.jsonl"):
        register(row.get("emitter_path"), "niagara_emitter", "first_class", row.get("class_path"))
    for row in rows(output / "niagara_stateless_emitters.jsonl"):
        register(row.get("emitter_path"), "niagara_stateless_emitter", "first_class", row.get("class_path"))
    for row in rows(output / "niagara_renderers.jsonl"):
        register(row.get("renderer_path"), "niagara_renderer", "first_class", row.get("renderer_class"))
    for row in rows(output / "niagara_stateless_renderers.jsonl"):
        register(row.get("renderer_path"), "niagara_renderer", "first_class", row.get("renderer_class"))
    for row in rows(output / "niagara_stateless_modules.jsonl"):
        register(row.get("module_path"), "niagara_stateless_module", "first_class", row.get("module_class"))
    for row in rows(output / "niagara_simulation_stages.jsonl"):
        register(row.get("stage_path"), "niagara_simulation_stage", "first_class", row.get("stage_class"))
    for row in rows(output / "cascade_emitters.jsonl"):
        register(row.get("emitter_path"), "cascade_emitter", "first_class", row.get("emitter_class"))
    for row in rows(output / "cascade_lods.jsonl"):
        register(row.get("lod_path"), "cascade_lod", "first_class")
    for row in rows(output / "cascade_modules.jsonl"):
        register(row.get("module_path"), "cascade_module", "first_class", row.get("module_class"))

    root_fact_streams = (
        ("niagara_systems.jsonl", "system_path"),
        ("niagara_emitters.jsonl", "asset_path"),
        ("niagara_scripts.jsonl", "script_path"),
        ("niagara_data_channels.jsonl", "data_channel_path"),
        ("niagara_parameter_collections.jsonl", "collection_path"),
        ("niagara_effect_types.jsonl", "effect_type_path"),
        ("cascade_systems.jsonl", "system_path"),
    )
    for filename, path_key in root_fact_streams:
        for row in rows(output / filename):
            path = str(row.get(path_key, ""))
            if path in roots:
                roots[path].setdefault("facts", {}).update(row)

    def resolve(path, desired_kind="object"):
        canonical = aliases.get(str(path or ""), str(path or ""))
        if canonical in registry:
            return registry[canonical]
        return {
            "path": canonical,
            "kind": desired_kind or "object",
            "coverage": "external_or_excluded",
            "class_path": "",
            "package_name": canonical.split(".", 1)[0] if canonical else "",
        }

    evidence_by_key = collections.defaultdict(dict)
    keys_by_pair = collections.defaultdict(set)

    def add(source, relation, target, desired_target_kind="object", evidence=None,
            generic_reference=False, source_kind=""):
        source = aliases.get(str(source or ""), str(source or ""))
        target = str(target or "")
        if not source or not relation or not target:
            return
        if source not in registry:
            if source_kind:
                register(source, source_kind, "first_class")
            else:
                return
        tm = resolve(target, desired_target_kind)
        target_path = str(tm.get("path", ""))
        if not target_path or target_path == source:
            return
        pair = (source, target_path)
        evidence = dict(evidence or {})
        encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if generic_reference and pair in keys_by_pair:
            for key in keys_by_pair[pair]:
                evidence_by_key[key][encoded] = evidence
            return
        sm = registry.get(source, {})
        key = (
            str(sm.get("kind", source_kind or "vfx_object")), source, str(relation),
            str(tm.get("kind", desired_target_kind)), target_path,
            str(tm.get("coverage", "external_or_excluded")),
        )
        evidence_by_key[key][encoded] = evidence
        keys_by_pair[pair].add(key)

    def field(source, relation, target, target_kind, stream, field_name):
        if target:
            add(source, relation, target, target_kind, {
                "kind": "canonical_vfx_field",
                "stream": stream,
                "field": field_name,
            })

    for row in rows(output / "niagara_system_emitters.jsonl"):
        detail = {
            "kind": "canonical_vfx_structure",
            "stream": "niagara_system_emitters.jsonl",
            "emitter_index": int(row.get("emitter_index", 0)),
            "name": str(row.get("name", "")),
            "id": str(row.get("id", "")),
            "enabled": row.get("enabled"),
            "emitter_mode": str(row.get("emitter_mode", "")),
            "emitter_version": str(row.get("emitter_version", "")),
            "versioned_emitter_path": str(row.get("emitter_path", "")),
        }
        stateless = str(row.get("stateless_emitter_path", ""))
        if stateless:
            add(row.get("system_path"), "uses_stateless_emitter", stateless,
                "niagara_stateless_emitter", detail)
        elif row.get("emitter_path"):
            add(row.get("system_path"), "uses_emitter", row.get("emitter_path"),
                "niagara_emitter", detail)

    for row in rows(output / "niagara_systems.jsonl"):
        field(row.get("system_path"), "uses_effect_type", row.get("effect_type_path"),
              "niagara_effect_type", "niagara_systems.jsonl", "effect_type_path")

    for row in rows(output / "niagara_renderers.jsonl"):
        add(row.get("emitter_path"), "uses_renderer", row.get("renderer_path"), "niagara_renderer", {
            "kind": "canonical_vfx_structure",
            "stream": "niagara_renderers.jsonl",
            "version_index": int(row.get("version_index", 0)),
            "renderer_index": int(row.get("renderer_index", 0)),
            "renderer_class": str(row.get("renderer_class", "")),
            "enabled": row.get("enabled"),
            "sort_order_hint": str(row.get("sort_order_hint", "")),
        })
    for row in rows(output / "niagara_simulation_stages.jsonl"):
        add(row.get("emitter_path"), "uses_simulation_stage", row.get("stage_path"),
            "niagara_simulation_stage", {
                "kind": "canonical_vfx_structure",
                "stream": "niagara_simulation_stages.jsonl",
                "version_index": int(row.get("version_index", 0)),
                "stage_index": int(row.get("stage_index", 0)),
                "stage_class": str(row.get("stage_class", "")),
                "iteration_source": str(row.get("iteration_source", "")),
            })

    for row in rows(output / "niagara_stateless_modules.jsonl"):
        add(row.get("emitter_path"), "uses_module", row.get("module_path"),
            "niagara_stateless_module", {
                "kind": "canonical_vfx_structure",
                "stream": "niagara_stateless_modules.jsonl",
                "module_index": int(row.get("module_index", 0)),
                "module_class": str(row.get("module_class", "")),
                "enabled": row.get("enabled"),
            })
    for row in rows(output / "niagara_stateless_renderers.jsonl"):
        add(row.get("emitter_path"), "uses_renderer", row.get("renderer_path"), "niagara_renderer", {
            "kind": "canonical_vfx_structure",
            "stream": "niagara_stateless_renderers.jsonl",
            "renderer_index": int(row.get("renderer_index", 0)),
            "renderer_class": str(row.get("renderer_class", "")),
            "enabled": row.get("enabled"),
            "sort_order_hint": str(row.get("sort_order_hint", "")),
        })

    for row in rows(output / "niagara_parameter_collections.jsonl"):
        field(row.get("collection_path"), "uses_material_parameter_collection",
              row.get("source_collection_path"), "material_parameter_collection",
              "niagara_parameter_collections.jsonl", "source_collection_path")

    for row in rows(output / "cascade_emitters.jsonl"):
        add(row.get("system_path"), "uses_cascade_emitter", row.get("emitter_path"),
            "cascade_emitter", {
                "kind": "canonical_vfx_structure",
                "stream": "cascade_emitters.jsonl",
                "emitter_index": int(row.get("emitter_index", 0)),
                "emitter_name": str(row.get("emitter_name", "")),
                "significance_level": str(row.get("significance_level", "")),
            })
    cascade_emitter_by_key = {
        (str(row.get("system_path", "")), int(row.get("emitter_index", 0))): str(row.get("emitter_path", ""))
        for row in rows(output / "cascade_emitters.jsonl")
    }
    for row in rows(output / "cascade_lods.jsonl"):
        emitter_path = cascade_emitter_by_key.get(
            (str(row.get("system_path", "")), int(row.get("emitter_index", 0))), ""
        )
        add(emitter_path, "uses_cascade_lod", row.get("lod_path"), "cascade_lod", {
            "kind": "canonical_vfx_structure",
            "stream": "cascade_lods.jsonl",
            "lod_index": int(row.get("lod_index", 0)),
            "level": str(row.get("level", "")),
            "enabled": row.get("enabled"),
        })
    cascade_lod_by_key = {
        (
            str(row.get("system_path", "")), int(row.get("emitter_index", 0)),
            int(row.get("lod_index", 0)),
        ): str(row.get("lod_path", ""))
        for row in rows(output / "cascade_lods.jsonl")
    }
    for row in rows(output / "cascade_modules.jsonl"):
        lod_path = cascade_lod_by_key.get((
            str(row.get("system_path", "")), int(row.get("emitter_index", 0)),
            int(row.get("lod_index", 0)),
        ), "")
        add(lod_path, "uses_cascade_module", row.get("module_path"), "cascade_module", {
            "kind": "canonical_vfx_structure",
            "stream": "cascade_modules.jsonl",
            "module_index": int(row.get("module_index", 0)),
            "role": str(row.get("role", "")),
            "module_class": str(row.get("module_class", "")),
        })

    for row in rows(output / "vfx_references.jsonl"):
        source = str(row.get("owner_path", ""))
        target = str(row.get("target_path", ""))
        if source not in registry or not target:
            continue
        add(source, "references_object", target, evidence={
            "kind": "canonical_vfx_reference",
            "stream": "vfx_references.jsonl",
            "asset_path": str(row.get("asset_path", "")),
            "owner_kind": str(row.get("owner_kind", "")),
            "root_property": str(row.get("root_property", "")),
            "property_path": str(row.get("property_path", "")),
            "reference_kind": str(row.get("reference_kind", "")),
            "target_class": str(row.get("target_class", "")),
        }, generic_reference=True)

    vfx_roots = set(roots)

    for row in rows(output / "world_references.jsonl"):
        target = str(row.get("target_path", ""))
        if target not in vfx_roots:
            continue
        source = str(row.get("owner_path", ""))
        source_kind = str(row.get("owner_kind", "object"))
        add(source, "references_vfx_asset", target, evidence={
            "kind": "canonical_world_reference",
            "stream": "world_references.jsonl",
            "world_path": str(row.get("world_path", "")),
            "actor_path": str(row.get("actor_path", "")),
            "owner_kind": source_kind,
            "root_property": str(row.get("root_property", "")),
            "property_path": str(row.get("property_path", "")),
            "reference_kind": str(row.get("reference_kind", "")),
            "target_class": str(row.get("target_class", "")),
            "authored_override": bool(row.get("authored_override", False)),
        }, source_kind=source_kind)

    for row in rows(output / "blueprint_relations.jsonl"):
        target = str(row.get("target", ""))
        if target not in vfx_roots:
            continue
        source = str(row.get("blueprint_path", ""))
        add(source, "references_vfx_asset", target, evidence={
            "kind": "exact_blueprint_relation",
            "stream": "blueprint_relations.jsonl",
            "upstream_relation_id": str(row.get("relation_id", "")),
            "graph_id": str(row.get("graph_id", "")),
            "source_kind": str(row.get("source_kind", "")),
            "source_id": str(row.get("source_id", "")),
            "relation": str(row.get("relation", "")),
            "owner": str(row.get("owner", "")),
            "detail": row.get("detail", {}),
        }, source_kind="blueprint")

    relations = []
    for key in sorted(evidence_by_key):
        source_kind, source, relation, target_kind, target, target_coverage = key
        evidence = [evidence_by_key[key][token] for token in sorted(evidence_by_key[key])]
        identity = key[:-1]
        relation_id = "vrel:" + hashlib.sha1("\x1f".join(identity).encode("utf-8")).hexdigest()[:24]
        relations.append({
            "relation_id": relation_id,
            "source_kind": source_kind,
            "source": source,
            "relation": relation,
            "target_kind": target_kind,
            "target": target,
            "target_coverage": target_coverage,
            "evidence_count": len(evidence),
            "evidence": evidence,
        })

    outgoing = collections.defaultdict(list)
    incoming = collections.defaultdict(list)
    for relation in relations:
        outgoing[relation["source"]].append(relation)
        incoming[relation["target"]].append(relation)

    summaries, contexts = [], []
    for path in sorted(roots):
        meta = roots[path]
        out = sorted(outgoing.get(path, []), key=lambda r: (r["relation"], r["target_kind"], r["target"], r["relation_id"]))
        inc = sorted(incoming.get(path, []), key=lambda r: (r["relation"], r["source_kind"], r["source"], r["relation_id"]))
        relation_counts = dict(sorted(collections.Counter(r["relation"] for r in out).items()))
        lines = _summary_lines(meta)
        lines.append(f"Relations: outgoing={len(out)} incoming={len(inc)} {relation_counts}")
        summary = {
            "asset_path": path,
            "asset_kind": meta.get("kind", ""),
            "class_path": meta.get("class_path", ""),
            "coverage": meta.get("coverage", ""),
            "package_name": meta.get("package_name", ""),
            "outgoing_count": len(out),
            "incoming_count": len(inc),
            "relation_counts": relation_counts,
            "text": "\n".join(lines),
        }
        summaries.append(summary)

        context_lines = list(lines)
        shown_out = min(len(out), MAX_CONTEXT_LINKS_PER_ASSET)
        if shown_out:
            context_lines.append("Outgoing:")
            for relation in out[:shown_out]:
                context_lines.append(
                    f"  {relation['relation']} -> {relation['target_kind']} {relation['target']} "
                    f"coverage={relation['target_coverage']} evidence={relation['evidence_count']}"
                )
        remaining = max(0, MAX_CONTEXT_LINKS_PER_ASSET - shown_out)
        shown_inc = min(len(inc), remaining)
        if shown_inc:
            context_lines.append("Incoming:")
            for relation in inc[:shown_inc]:
                context_lines.append(
                    f"  {relation['source_kind']} {relation['source']} -> "
                    f"{relation['relation']} evidence={relation['evidence_count']}"
                )
        omitted = (len(out) - shown_out) + (len(inc) - shown_inc)
        if omitted:
            context_lines.append(f"... {omitted} more relations omitted by context link bound")
        text = "\n".join(context_lines)
        char_truncated = len(text) > MAX_CONTEXT_CHARS
        if char_truncated:
            text = text[:MAX_CONTEXT_CHARS] + "\n...[truncated]"
        contexts.append({
            "asset_path": path,
            "asset_kind": meta.get("kind", ""),
            "class_path": meta.get("class_path", ""),
            "coverage": meta.get("coverage", ""),
            "outgoing_count": len(out),
            "incoming_count": len(inc),
            "truncated": bool(omitted or char_truncated),
            "text": text,
        })

    return relations, contexts, summaries


def validation_error(output, rows) -> str | None:
    try:
        relations = list(rows(output / "vfx_relations.jsonl"))
        contexts = list(rows(output / "vfx_context.jsonl"))
        summaries = list(rows(output / "vfx_summaries.jsonl"))
    except RuntimeError as exc:
        return str(exc)

    if len({row.get("relation_id", "") for row in relations}) != len(relations):
        return "duplicate VFX derived relation_id"

    roots = {str(row.get("vfx_path", "")) for row in rows(output / "vfx_assets.jsonl") if row.get("vfx_path")}
    if {str(row.get("asset_path", "")) for row in summaries} != roots:
        return "VFX summaries do not exactly cover first-class VFX assets"
    if {str(row.get("asset_path", "")) for row in contexts} != roots:
        return "VFX context does not exactly cover first-class VFX assets"

    by_edge = collections.defaultdict(list)
    for relation in relations:
        by_edge[(str(relation.get("source", "")), str(relation.get("relation", "")), str(relation.get("target", "")))].append(relation)
        for evidence in relation.get("evidence", []) or []:
            if str(evidence.get("stream", "")) == "asset_dependencies.jsonl":
                return "generic package dependency promoted into VFX semantic relation"

    for row in rows(output / "niagara_system_emitters.jsonl"):
        source = str(row.get("system_path", ""))
        stateless = str(row.get("stateless_emitter_path", ""))
        if stateless:
            key = (source, "uses_stateless_emitter", stateless)
        else:
            target = str(row.get("emitter_path", ""))
            if not target:
                continue
            key = (source, "uses_emitter", target)
        if key not in by_edge:
            return f"missing Niagara system/emitter derived edge: {source}"

    for row in rows(output / "niagara_renderers.jsonl"):
        key = (str(row.get("emitter_path", "")), "uses_renderer", str(row.get("renderer_path", "")))
        if key not in by_edge:
            return f"missing stateful renderer derived edge: {key[0]}"
    for row in rows(output / "niagara_stateless_renderers.jsonl"):
        key = (str(row.get("emitter_path", "")), "uses_renderer", str(row.get("renderer_path", "")))
        if key not in by_edge:
            return f"missing stateless renderer derived edge: {key[0]}"
    for row in rows(output / "niagara_stateless_modules.jsonl"):
        key = (str(row.get("emitter_path", "")), "uses_module", str(row.get("module_path", "")))
        if key not in by_edge:
            return f"missing stateless module derived edge: {key[0]}"

    for row in rows(output / "niagara_systems.jsonl"):
        target = str(row.get("effect_type_path", ""))
        if target and (str(row.get("system_path", "")), "uses_effect_type", target) not in by_edge:
            return "missing Niagara System -> Effect Type derived edge"

    for row in rows(output / "niagara_parameter_collections.jsonl"):
        target = str(row.get("source_collection_path", ""))
        if target and (str(row.get("collection_path", "")), "uses_material_parameter_collection", target) not in by_edge:
            return "missing Niagara Parameter Collection -> Material Parameter Collection derived edge"

    for row in rows(output / "world_references.jsonl"):
        target = str(row.get("target_path", ""))
        if target in roots:
            key = (str(row.get("owner_path", "")), "references_vfx_asset", target)
            if key not in by_edge:
                return "missing exact world -> VFX derived edge"

    for row in rows(output / "blueprint_relations.jsonl"):
        target = str(row.get("target", ""))
        if target in roots:
            key = (str(row.get("blueprint_path", "")), "references_vfx_asset", target)
            if key not in by_edge:
                return "missing exact Blueprint -> VFX derived edge"

    return None


def load_database(conn, output, rows) -> None:
    for row in rows(output / "vfx_relations.jsonl"):
        conn.execute("INSERT OR REPLACE INTO vfx_relations VALUES(?,?,?,?,?,?,?,?,?)", (
            row.get("relation_id", ""), row.get("source_kind", ""), row.get("source", ""),
            row.get("relation", ""), row.get("target_kind", ""), row.get("target", ""),
            row.get("target_coverage", ""), int(row.get("evidence_count", 0)),
            json.dumps(row.get("evidence", []), ensure_ascii=False, separators=(",", ":")),
        ))
    for row in rows(output / "vfx_context.jsonl"):
        conn.execute("INSERT OR REPLACE INTO vfx_context VALUES(?,?,?,?,?,?,?,?,?)", (
            row.get("asset_path", ""), row.get("asset_kind", ""), row.get("class_path", ""),
            row.get("coverage", ""), int(row.get("outgoing_count", 0)), int(row.get("incoming_count", 0)),
            int(bool(row.get("truncated", False))), row.get("text", ""),
            json.dumps(row, ensure_ascii=False, separators=(",", ":")),
        ))
    for row in rows(output / "vfx_summaries.jsonl"):
        conn.execute("INSERT OR REPLACE INTO vfx_summaries VALUES(?,?,?,?,?,?,?,?,?,?)", (
            row.get("asset_path", ""), row.get("asset_kind", ""), row.get("class_path", ""),
            row.get("coverage", ""), row.get("package_name", ""), int(row.get("outgoing_count", 0)),
            int(row.get("incoming_count", 0)),
            json.dumps(row.get("relation_counts", {}), ensure_ascii=False, separators=(",", ":")),
            row.get("text", ""), json.dumps(row, ensure_ascii=False, separators=(",", ":")),
        ))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='vfx_summaries'").fetchone():
        return
    print("\n[vfx summaries]")
    print_rows(conn.execute(
        "SELECT asset_path,asset_kind,coverage,outgoing_count,incoming_count,substr(text,1,1200) text "
        "FROM vfx_summaries WHERE asset_path LIKE ? OR asset_kind LIKE ? OR text LIKE ? LIMIT ?",
        (pattern, pattern, pattern, limit),
    ), ("asset_path", "asset_kind", "coverage", "outgoing_count", "incoming_count", "text"))
    print("\n[vfx relations]")
    print_rows(conn.execute(
        "SELECT source_kind,source,relation,target_kind,target,target_coverage,evidence_count "
        "FROM vfx_relations WHERE source LIKE ? OR relation LIKE ? OR target LIKE ? "
        "OR source_kind LIKE ? OR target_kind LIKE ? OR evidence_json LIKE ? LIMIT ?",
        (pattern, pattern, pattern, pattern, pattern, pattern, limit),
    ), ("source_kind", "source", "relation", "target_kind", "target", "target_coverage", "evidence_count"))
    print("\n[vfx context]")
    print_rows(conn.execute(
        "SELECT asset_path,asset_kind,substr(text,1,1600) text FROM vfx_context "
        "WHERE asset_path LIKE ? OR asset_kind LIKE ? OR text LIKE ? LIMIT ?",
        (pattern, pattern, pattern, limit),
    ), ("asset_path", "asset_kind", "text"))
