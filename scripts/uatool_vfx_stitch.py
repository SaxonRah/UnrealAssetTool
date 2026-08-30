#!/usr/bin/env python3
"""Derived VFX relations, summaries, and bounded asset context."""
from __future__ import annotations

import collections
import hashlib
import json
import re

DERIVED_SCHEMA_VERSION = 12
DERIVED_FILES = ("vfx_relations.jsonl", "vfx_context.jsonl", "vfx_summaries.jsonl")
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


def _leaf(class_path: str) -> str:
    value = str(class_path or "").rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower() or "asset"


def _coverage(class_path: str) -> str:
    return "partial" if class_path in {
        "/Script/Engine.UserDefinedStruct", "/Script/Engine.UserDefinedEnum"
    } else "generic_only"


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
    values = [f"{k}={facts[k]}" for k in keys if facts.get(k) not in ("", None)]
    if values:
        lines.append("Facts: " + " ".join(values))
    return lines


def derive(output, rows) -> tuple[list[dict], list[dict], list[dict]]:
    registry: dict[str, dict] = {}
    roots: dict[str, dict] = {}
    aliases: dict[str, str] = {}
    rank = {"external_or_excluded": 0, "generic_only": 1, "partial": 2, "first_class": 4}

    def register(path, kind, coverage, class_path="", package_name="", root=False, facts=None):
        path = str(path or "")
        if not path:
            return
        candidate = {
            "path": path, "kind": str(kind or "object"), "coverage": str(coverage),
            "class_path": str(class_path or ""), "package_name": str(package_name or ""),
        }
        current = registry.get(path)
        if current is None or rank.get(candidate["coverage"], 0) >= rank.get(current.get("coverage", ""), 0):
            registry[path] = candidate
        if root:
            roots[path] = {**registry[path], "facts": dict(facts or {})}

    for row in rows(output / "assets.jsonl"):
        cls = str(row.get("class_path", ""))
        register(row.get("object_path"), _leaf(cls), _coverage(cls), cls, row.get("package_name"))
    for row in rows(output / "blueprints.jsonl"):
        path = str(row.get("object_path", ""))
        register(path, "blueprint", "first_class", row.get("class"), path.split(".", 1)[0])
        if row.get("generated_class") and path:
            aliases[str(row["generated_class"])] = path
    for row in rows(output / "world_actors.jsonl"):
        register(row.get("actor_path"), "actor", "first_class", row.get("actor_class"))
    for row in rows(output / "world_components.jsonl"):
        register(row.get("component_path"), "component", "first_class", row.get("component_class"))

    for row in rows(output / "vfx_assets.jsonl"):
        register(row.get("vfx_path"), row.get("vfx_kind", "vfx_asset"), "first_class",
                 row.get("class_path"), row.get("package_name"), True, row)
    for row in rows(output / "vfx_properties.jsonl"):
        register(row.get("owner_path"), row.get("owner_kind", "vfx_object"), "first_class",
                 row.get("owner_class"), str(row.get("asset_path", "")).split(".", 1)[0])

    nested = (
        ("niagara_emitters.jsonl", "emitter_path", "niagara_emitter", "class_path"),
        ("niagara_stateless_emitters.jsonl", "emitter_path", "niagara_stateless_emitter", "class_path"),
        ("niagara_renderers.jsonl", "renderer_path", "niagara_renderer", "renderer_class"),
        ("niagara_stateless_renderers.jsonl", "renderer_path", "niagara_renderer", "renderer_class"),
        ("niagara_stateless_modules.jsonl", "module_path", "niagara_stateless_module", "module_class"),
        ("niagara_simulation_stages.jsonl", "stage_path", "niagara_simulation_stage", "stage_class"),
        ("cascade_emitters.jsonl", "emitter_path", "cascade_emitter", "emitter_class"),
        ("cascade_lods.jsonl", "lod_path", "cascade_lod", ""),
        ("cascade_modules.jsonl", "module_path", "cascade_module", "module_class"),
    )
    for filename, path_key, kind, class_key in nested:
        for row in rows(output / filename):
            register(row.get(path_key), kind, "first_class", row.get(class_key, "") if class_key else "")

    for filename, path_key in (
        ("niagara_systems.jsonl", "system_path"),
        ("niagara_scripts.jsonl", "script_path"),
        ("niagara_data_channels.jsonl", "data_channel_path"),
        ("niagara_parameter_collections.jsonl", "collection_path"),
        ("niagara_effect_types.jsonl", "effect_type_path"),
        ("cascade_systems.jsonl", "system_path"),
    ):
        for row in rows(output / filename):
            path = str(row.get(path_key, ""))
            if path in roots:
                roots[path]["facts"].update(row)
    # Standalone NiagaraEmitter assets are keyed by emitter_path. asset_path can
    # be the owning System for embedded emitters, so it must not enrich a System.
    for row in rows(output / "niagara_emitters.jsonl"):
        path = str(row.get("emitter_path", ""))
        if path in roots:
            roots[path]["facts"].update(row)

    def resolve(path, desired="object"):
        canonical = aliases.get(str(path or ""), str(path or ""))
        if canonical in registry:
            return registry[canonical]
        return {
            "path": canonical, "kind": desired or "object", "coverage": "external_or_excluded",
            "class_path": "", "package_name": canonical.split(".", 1)[0] if canonical else "",
        }

    evidence_by_key = collections.defaultdict(dict)
    keys_by_pair = collections.defaultdict(set)

    def add(source, relation, target, target_kind="object", evidence=None,
            supporting_reference=False, source_kind=""):
        source = aliases.get(str(source or ""), str(source or ""))
        target = str(target or "")
        if not source or not relation or not target:
            return
        if source not in registry:
            if not source_kind:
                return
            register(source, source_kind, "first_class")
        tm = resolve(target, target_kind)
        target = str(tm.get("path", ""))
        if not target or source == target:
            return
        pair = (source, target)
        evidence = dict(evidence or {})
        encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if supporting_reference and pair in keys_by_pair:
            for key in keys_by_pair[pair]:
                evidence_by_key[key][encoded] = evidence
            return
        sm = registry[source]
        key = (sm.get("kind", source_kind or "vfx_object"), source, relation,
               tm.get("kind", target_kind), target, tm.get("coverage", "external_or_excluded"))
        evidence_by_key[key][encoded] = evidence
        keys_by_pair[pair].add(key)

    def field(source, relation, target, target_kind, stream, name):
        if target:
            add(source, relation, target, target_kind, {
                "kind": "canonical_vfx_field", "stream": stream, "field": name,
            })

    for row in rows(output / "niagara_system_emitters.jsonl"):
        evidence = {
            "kind": "canonical_vfx_structure", "stream": "niagara_system_emitters.jsonl",
            "emitter_index": int(row.get("emitter_index", 0)), "name": str(row.get("name", "")),
            "id": str(row.get("id", "")), "enabled": row.get("enabled"),
            "emitter_mode": str(row.get("emitter_mode", "")),
            "emitter_version": str(row.get("emitter_version", "")),
            "versioned_emitter_path": str(row.get("emitter_path", "")),
        }
        stateless = str(row.get("stateless_emitter_path", ""))
        if stateless:
            add(row.get("system_path"), "uses_stateless_emitter", stateless,
                "niagara_stateless_emitter", evidence)
        elif row.get("emitter_path"):
            add(row.get("system_path"), "uses_emitter", row.get("emitter_path"),
                "niagara_emitter", evidence)

    for row in rows(output / "niagara_systems.jsonl"):
        field(row.get("system_path"), "uses_effect_type", row.get("effect_type_path"),
              "niagara_effect_type", "niagara_systems.jsonl", "effect_type_path")

    for row in rows(output / "niagara_renderers.jsonl"):
        add(row.get("emitter_path"), "uses_renderer", row.get("renderer_path"), "niagara_renderer", {
            "kind": "canonical_vfx_structure", "stream": "niagara_renderers.jsonl",
            "version_index": int(row.get("version_index", 0)),
            "renderer_index": int(row.get("renderer_index", 0)),
            "renderer_class": str(row.get("renderer_class", "")), "enabled": row.get("enabled"),
            "sort_order_hint": str(row.get("sort_order_hint", "")),
        })
    for row in rows(output / "niagara_simulation_stages.jsonl"):
        add(row.get("emitter_path"), "uses_simulation_stage", row.get("stage_path"),
            "niagara_simulation_stage", {
                "kind": "canonical_vfx_structure", "stream": "niagara_simulation_stages.jsonl",
                "version_index": int(row.get("version_index", 0)),
                "stage_index": int(row.get("stage_index", 0)),
                "stage_class": str(row.get("stage_class", "")),
                "iteration_source": str(row.get("iteration_source", "")),
            })
    for row in rows(output / "niagara_stateless_modules.jsonl"):
        add(row.get("emitter_path"), "uses_module", row.get("module_path"),
            "niagara_stateless_module", {
                "kind": "canonical_vfx_structure", "stream": "niagara_stateless_modules.jsonl",
                "module_index": int(row.get("module_index", 0)),
                "module_class": str(row.get("module_class", "")), "enabled": row.get("enabled"),
            })
    for row in rows(output / "niagara_stateless_renderers.jsonl"):
        add(row.get("emitter_path"), "uses_renderer", row.get("renderer_path"), "niagara_renderer", {
            "kind": "canonical_vfx_structure", "stream": "niagara_stateless_renderers.jsonl",
            "renderer_index": int(row.get("renderer_index", 0)),
            "renderer_class": str(row.get("renderer_class", "")), "enabled": row.get("enabled"),
            "sort_order_hint": str(row.get("sort_order_hint", "")),
        })

    for row in rows(output / "niagara_parameter_collections.jsonl"):
        field(row.get("collection_path"), "uses_material_parameter_collection",
              row.get("source_collection_path"), "material_parameter_collection",
              "niagara_parameter_collections.jsonl", "source_collection_path")

    cascade_emitters = {
        (str(r.get("system_path", "")), int(r.get("emitter_index", 0))): str(r.get("emitter_path", ""))
        for r in rows(output / "cascade_emitters.jsonl")
    }
    for row in rows(output / "cascade_emitters.jsonl"):
        add(row.get("system_path"), "uses_cascade_emitter", row.get("emitter_path"), "cascade_emitter", {
            "kind": "canonical_vfx_structure", "stream": "cascade_emitters.jsonl",
            "emitter_index": int(row.get("emitter_index", 0)),
            "emitter_name": str(row.get("emitter_name", "")),
            "significance_level": str(row.get("significance_level", "")),
        })
    cascade_lods = {}
    for row in rows(output / "cascade_lods.jsonl"):
        key = (str(row.get("system_path", "")), int(row.get("emitter_index", 0)))
        source = cascade_emitters.get(key, "")
        cascade_lods[(key[0], key[1], int(row.get("lod_index", 0)))] = str(row.get("lod_path", ""))
        add(source, "uses_cascade_lod", row.get("lod_path"), "cascade_lod", {
            "kind": "canonical_vfx_structure", "stream": "cascade_lods.jsonl",
            "lod_index": int(row.get("lod_index", 0)), "level": str(row.get("level", "")),
            "enabled": row.get("enabled"),
        })
    for row in rows(output / "cascade_modules.jsonl"):
        key = (str(row.get("system_path", "")), int(row.get("emitter_index", 0)), int(row.get("lod_index", 0)))
        add(cascade_lods.get(key, ""), "uses_cascade_module", row.get("module_path"), "cascade_module", {
            "kind": "canonical_vfx_structure", "stream": "cascade_modules.jsonl",
            "module_index": int(row.get("module_index", 0)), "role": str(row.get("role", "")),
            "module_class": str(row.get("module_class", "")),
        })

    # Exact reflected VFX references support stronger topology on the same pair;
    # otherwise they remain explicit references_object edges.
    for row in rows(output / "vfx_references.jsonl"):
        source, target = str(row.get("owner_path", "")), str(row.get("target_path", ""))
        if source not in registry or not target:
            continue
        add(source, "references_object", target, evidence={
            "kind": "canonical_vfx_reference", "stream": "vfx_references.jsonl",
            "asset_path": str(row.get("asset_path", "")), "owner_kind": str(row.get("owner_kind", "")),
            "root_property": str(row.get("root_property", "")),
            "property_path": str(row.get("property_path", "")),
            "reference_kind": str(row.get("reference_kind", "")),
            "target_class": str(row.get("target_class", "")),
        }, supporting_reference=True)

    vfx_roots = set(roots)
    for row in rows(output / "world_references.jsonl"):
        target = str(row.get("target_path", ""))
        if target not in vfx_roots:
            continue
        source_kind = str(row.get("owner_kind", "object"))
        add(row.get("owner_path"), "references_vfx_asset", target, evidence={
            "kind": "canonical_world_reference", "stream": "world_references.jsonl",
            "world_path": str(row.get("world_path", "")), "actor_path": str(row.get("actor_path", "")),
            "owner_kind": source_kind, "root_property": str(row.get("root_property", "")),
            "property_path": str(row.get("property_path", "")),
            "reference_kind": str(row.get("reference_kind", "")),
            "target_class": str(row.get("target_class", "")),
            "authored_override": bool(row.get("authored_override", False)),
        }, source_kind=source_kind)

    # blueprint_relations is already an exact, evidence-bearing structural
    # derivation. Only exact targets present in the VFX root registry are lifted.
    for row in rows(output / "blueprint_relations.jsonl"):
        target = str(row.get("target", ""))
        if target not in vfx_roots:
            continue
        add(row.get("blueprint_path"), "references_vfx_asset", target, evidence={
            "kind": "exact_blueprint_relation", "stream": "blueprint_relations.jsonl",
            "upstream_relation_id": str(row.get("relation_id", "")),
            "graph_id": str(row.get("graph_id", "")), "source_kind": str(row.get("source_kind", "")),
            "source_id": str(row.get("source_id", "")), "relation": str(row.get("relation", "")),
            "owner": str(row.get("owner", "")), "detail": row.get("detail", {}),
        }, source_kind="blueprint")

    relations = []
    for key in sorted(evidence_by_key):
        source_kind, source, relation, target_kind, target, target_coverage = key
        evidence = [evidence_by_key[key][token] for token in sorted(evidence_by_key[key])]
        relation_id = "vrel:" + hashlib.sha1("\x1f".join(key[:-1]).encode("utf-8")).hexdigest()[:24]
        relations.append({
            "relation_id": relation_id, "source_kind": source_kind, "source": source,
            "relation": relation, "target_kind": target_kind, "target": target,
            "target_coverage": target_coverage, "evidence_count": len(evidence), "evidence": evidence,
        })

    outgoing, incoming = collections.defaultdict(list), collections.defaultdict(list)
    for relation in relations:
        outgoing[relation["source"]].append(relation)
        incoming[relation["target"]].append(relation)

    summaries, contexts = [], []
    for path in sorted(roots):
        meta = roots[path]
        out = sorted(outgoing[path], key=lambda r: (r["relation"], r["target_kind"], r["target"], r["relation_id"]))
        inc = sorted(incoming[path], key=lambda r: (r["relation"], r["source_kind"], r["source"], r["relation_id"]))
        counts = dict(sorted(collections.Counter(r["relation"] for r in out).items()))
        lines = _summary_lines(meta)
        lines.append(f"Relations: outgoing={len(out)} incoming={len(inc)} {counts}")
        summaries.append({
            "asset_path": path, "asset_kind": meta.get("kind", ""), "class_path": meta.get("class_path", ""),
            "coverage": meta.get("coverage", ""), "package_name": meta.get("package_name", ""),
            "outgoing_count": len(out), "incoming_count": len(inc), "relation_counts": counts,
            "text": "\n".join(lines),
        })

        context_lines = list(lines)
        shown_out = min(len(out), MAX_CONTEXT_LINKS_PER_ASSET)
        if shown_out:
            context_lines.append("Outgoing:")
            context_lines.extend(
                f"  {r['relation']} -> {r['target_kind']} {r['target']} coverage={r['target_coverage']} evidence={r['evidence_count']}"
                for r in out[:shown_out]
            )
        remaining = max(0, MAX_CONTEXT_LINKS_PER_ASSET - shown_out)
        shown_inc = min(len(inc), remaining)
        if shown_inc:
            context_lines.append("Incoming:")
            context_lines.extend(
                f"  {r['source_kind']} {r['source']} -> {r['relation']} evidence={r['evidence_count']}"
                for r in inc[:shown_inc]
            )
        omitted = len(out) - shown_out + len(inc) - shown_inc
        if omitted:
            context_lines.append(f"... {omitted} more relations omitted by context link bound")
        text = "\n".join(context_lines)
        char_truncated = len(text) > MAX_CONTEXT_CHARS
        if char_truncated:
            text = text[:MAX_CONTEXT_CHARS] + "\n...[truncated]"
        contexts.append({
            "asset_path": path, "asset_kind": meta.get("kind", ""), "class_path": meta.get("class_path", ""),
            "coverage": meta.get("coverage", ""), "outgoing_count": len(out), "incoming_count": len(inc),
            "truncated": bool(omitted or char_truncated), "text": text,
        })
    return relations, contexts, summaries


def validation_error(output, rows) -> str | None:
    try:
        relations = list(rows(output / "vfx_relations.jsonl"))
        contexts = list(rows(output / "vfx_context.jsonl"))
        summaries = list(rows(output / "vfx_summaries.jsonl"))
    except RuntimeError as exc:
        return str(exc)

    if len({r.get("relation_id", "") for r in relations}) != len(relations):
        return "duplicate VFX derived relation_id"
    roots = {str(r.get("vfx_path", "")) for r in rows(output / "vfx_assets.jsonl") if r.get("vfx_path")}
    if {str(r.get("asset_path", "")) for r in summaries} != roots:
        return "VFX summaries do not exactly cover first-class VFX assets"
    if {str(r.get("asset_path", "")) for r in contexts} != roots:
        return "VFX context does not exactly cover first-class VFX assets"

    by_edge = collections.defaultdict(list)
    pair_set = set()
    for relation in relations:
        source, rel, target = str(relation.get("source", "")), str(relation.get("relation", "")), str(relation.get("target", ""))
        by_edge[(source, rel, target)].append(relation)
        pair_set.add((source, target))
        for evidence in relation.get("evidence", []) or []:
            if evidence.get("stream") == "asset_dependencies.jsonl":
                return "generic package dependency promoted into VFX semantic relation"

    for row in rows(output / "niagara_system_emitters.jsonl"):
        source = str(row.get("system_path", ""))
        target = str(row.get("stateless_emitter_path", ""))
        key = (source, "uses_stateless_emitter", target) if target else (
            source, "uses_emitter", str(row.get("emitter_path", ""))
        )
        if key[2] and key not in by_edge:
            return f"missing Niagara system/emitter derived edge: {source}"
    for filename, relation, source_key, target_key, label in (
        ("niagara_renderers.jsonl", "uses_renderer", "emitter_path", "renderer_path", "stateful renderer"),
        ("niagara_stateless_renderers.jsonl", "uses_renderer", "emitter_path", "renderer_path", "stateless renderer"),
        ("niagara_stateless_modules.jsonl", "uses_module", "emitter_path", "module_path", "stateless module"),
        ("niagara_simulation_stages.jsonl", "uses_simulation_stage", "emitter_path", "stage_path", "simulation stage"),
    ):
        for row in rows(output / filename):
            key = (str(row.get(source_key, "")), relation, str(row.get(target_key, "")))
            if key not in by_edge:
                return f"missing {label} derived edge: {key[0]}"
    for row in rows(output / "niagara_systems.jsonl"):
        target = str(row.get("effect_type_path", ""))
        if target and (str(row.get("system_path", "")), "uses_effect_type", target) not in by_edge:
            return "missing Niagara System -> Effect Type derived edge"
    for row in rows(output / "niagara_parameter_collections.jsonl"):
        target = str(row.get("source_collection_path", ""))
        if target and (str(row.get("collection_path", "")), "uses_material_parameter_collection", target) not in by_edge:
            return "missing Niagara Parameter Collection -> Material Parameter Collection derived edge"

    emitters = {
        (str(r.get("system_path", "")), int(r.get("emitter_index", 0))): str(r.get("emitter_path", ""))
        for r in rows(output / "cascade_emitters.jsonl")
    }
    for row in rows(output / "cascade_emitters.jsonl"):
        if (str(row.get("system_path", "")), "uses_cascade_emitter", str(row.get("emitter_path", ""))) not in by_edge:
            return "missing Cascade system/emitter derived edge"
    lods = {}
    for row in rows(output / "cascade_lods.jsonl"):
        key = (str(row.get("system_path", "")), int(row.get("emitter_index", 0)))
        source, target = emitters.get(key, ""), str(row.get("lod_path", ""))
        lods[(key[0], key[1], int(row.get("lod_index", 0)))] = target
        if source and (source, "uses_cascade_lod", target) not in by_edge:
            return "missing Cascade emitter/LOD derived edge"
    for row in rows(output / "cascade_modules.jsonl"):
        key = (str(row.get("system_path", "")), int(row.get("emitter_index", 0)), int(row.get("lod_index", 0)))
        source, target = lods.get(key, ""), str(row.get("module_path", ""))
        if source and (source, "uses_cascade_module", target) not in by_edge:
            return "missing Cascade LOD/module derived edge"

    aliases = {
        str(r.get("generated_class", "")): str(r.get("object_path", ""))
        for r in rows(output / "blueprints.jsonl") if r.get("generated_class") and r.get("object_path")
    }
    for row in rows(output / "vfx_references.jsonl"):
        source = str(row.get("owner_path", ""))
        target = aliases.get(str(row.get("target_path", "")), str(row.get("target_path", "")))
        if source and target and source != target and (source, target) not in pair_set:
            return "missing exact reflected VFX reference in derived graph"
    for row in rows(output / "world_references.jsonl"):
        target = str(row.get("target_path", ""))
        if target in roots and (str(row.get("owner_path", "")), "references_vfx_asset", target) not in by_edge:
            return "missing exact world -> VFX derived edge"
    for row in rows(output / "blueprint_relations.jsonl"):
        target = str(row.get("target", ""))
        if target in roots and (str(row.get("blueprint_path", "")), "references_vfx_asset", target) not in by_edge:
            return "missing exact Blueprint -> VFX derived edge"

    outgoing = collections.Counter(str(r.get("source", "")) for r in relations)
    incoming = collections.Counter(str(r.get("target", "")) for r in relations)
    for row in (*summaries, *contexts):
        path = str(row.get("asset_path", ""))
        if int(row.get("outgoing_count", 0)) != outgoing[path] or int(row.get("incoming_count", 0)) != incoming[path]:
            return f"VFX summary/context relation counts mismatch: {path}"
    return None


def load_database(conn, output, rows) -> None:
    for r in rows(output / "vfx_relations.jsonl"):
        conn.execute("INSERT OR REPLACE INTO vfx_relations VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("relation_id", ""), r.get("source_kind", ""), r.get("source", ""), r.get("relation", ""),
            r.get("target_kind", ""), r.get("target", ""), r.get("target_coverage", ""),
            int(r.get("evidence_count", 0)), json.dumps(r.get("evidence", []), ensure_ascii=False, separators=(",", ":")),
        ))
    for r in rows(output / "vfx_context.jsonl"):
        conn.execute("INSERT OR REPLACE INTO vfx_context VALUES(?,?,?,?,?,?,?,?,?)", (
            r.get("asset_path", ""), r.get("asset_kind", ""), r.get("class_path", ""), r.get("coverage", ""),
            int(r.get("outgoing_count", 0)), int(r.get("incoming_count", 0)), int(bool(r.get("truncated", False))),
            r.get("text", ""), json.dumps(r, ensure_ascii=False, separators=(",", ":")),
        ))
    for r in rows(output / "vfx_summaries.jsonl"):
        conn.execute("INSERT OR REPLACE INTO vfx_summaries VALUES(?,?,?,?,?,?,?,?,?,?)", (
            r.get("asset_path", ""), r.get("asset_kind", ""), r.get("class_path", ""), r.get("coverage", ""),
            r.get("package_name", ""), int(r.get("outgoing_count", 0)), int(r.get("incoming_count", 0)),
            json.dumps(r.get("relation_counts", {}), ensure_ascii=False, separators=(",", ":")),
            r.get("text", ""), json.dumps(r, ensure_ascii=False, separators=(",", ":")),
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
