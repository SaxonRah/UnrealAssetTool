#!/usr/bin/env python3
"""Typed bounded project graph and retrieval neighborhoods for UnrealAssetTool.

Every edge retains provenance and a quality class. Generic Asset Registry package
dependencies remain traversable, but only as explicit low-quality package hops;
they are never promoted into exact asset semantics.
"""
from __future__ import annotations

import collections
import hashlib
import json
import re

DERIVED_SCHEMA_VERSION = 13
DERIVED_FILES = (
    "project_nodes.jsonl",
    "project_edges.jsonl",
    "project_neighborhoods.jsonl",
)
MAX_NEIGHBOR_DEPTH = 3
MAX_NEIGHBOR_EDGES = 256
MAX_NEIGHBOR_CHARS = 131072

_SQL = """
CREATE TABLE project_nodes(
 node_id TEXT PRIMARY KEY,node_kind TEXT NOT NULL,path TEXT NOT NULL,coverage TEXT NOT NULL,
 class_path TEXT NOT NULL,package_name TEXT NOT NULL,family TEXT NOT NULL,root INTEGER NOT NULL,json TEXT NOT NULL);
CREATE UNIQUE INDEX project_nodes_path_kind_idx ON project_nodes(path,node_kind);
CREATE INDEX project_nodes_path_idx ON project_nodes(path);
CREATE INDEX project_nodes_kind_idx ON project_nodes(node_kind,coverage);

CREATE TABLE project_edges(
 edge_id TEXT PRIMARY KEY,source_kind TEXT NOT NULL,source TEXT NOT NULL,relation TEXT NOT NULL,
 target_kind TEXT NOT NULL,target TEXT NOT NULL,source_coverage TEXT NOT NULL,target_coverage TEXT NOT NULL,
 edge_quality TEXT NOT NULL,evidence_count INTEGER NOT NULL,evidence_json TEXT NOT NULL);
CREATE INDEX project_edges_source_idx ON project_edges(source,relation);
CREATE INDEX project_edges_target_idx ON project_edges(target,relation);
CREATE INDEX project_edges_quality_idx ON project_edges(edge_quality,source_kind,target_kind);

CREATE TABLE project_neighborhoods(
 root_path TEXT PRIMARY KEY,root_kind TEXT NOT NULL,root_coverage TEXT NOT NULL,max_depth INTEGER NOT NULL,
 edge_count INTEGER NOT NULL,node_count INTEGER NOT NULL,truncated INTEGER NOT NULL,text TEXT NOT NULL,json TEXT NOT NULL);
CREATE INDEX project_neighborhoods_kind_idx ON project_neighborhoods(root_kind,root_coverage);
"""

QUALITY_RANK = {
    "generic_package_dependency": 0,
    "unique_dependency_resolution": 1,
    "exact_reference": 2,
    "exact_semantic": 3,
}
COVERAGE_RANK = {
    "external_or_excluded": 0,
    "generic_only": 1,
    "partial": 2,
    "first_class_depth_pending": 3,
    "first_class": 4,
}

# Combined systems schema 1 intentionally recognizes more asset families than it
# deeply normalizes. Keep this policy explicit so newly recognized systems never
# silently inherit first_class coverage merely by appearing in systems_assets.
SYSTEMS_KIND_COVERAGE = {
    "input_action": "first_class",
    "input_mapping_context": "first_class",
    "level_sequence": "first_class_depth_pending",
    "metasound_source": "first_class_depth_pending",
    "metasound_patch": "first_class_depth_pending",
    "sound_cue": "first_class_depth_pending",
    "sound_wave": "first_class_depth_pending",
    "sound_class": "first_class_depth_pending",
    "sound_mix": "first_class_depth_pending",
    "sound_attenuation": "first_class_depth_pending",
    "sound_concurrency": "first_class_depth_pending",
    "player_mappable_input_config": "first_class_depth_pending",
    "enhanced_input_platform_data": "first_class_depth_pending",
    "primary_asset_label": "first_class_depth_pending",
    "common_input_action_table": "first_class_depth_pending",
    "common_input_action_domain": "first_class_depth_pending",
    "common_input_action_domain_table": "first_class_depth_pending",
    "gameplay_tag_table": "first_class_depth_pending",
}


def systems_kind_coverage(kind: str) -> str:
    """Return truthful graph coverage for a systems schema-1 asset kind.

    Unknown future systems kinds default to depth-pending instead of first-class,
    preventing the graph from overclaiming semantic depth before a dedicated
    normalizer/validator exists.
    """
    return SYSTEMS_KIND_COVERAGE.get(str(kind or ""), "first_class_depth_pending")


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def _class_leaf(class_path: str) -> str:
    value = str(class_path or "").rsplit(".", 1)[-1].rsplit("/", 1)[-1]
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value).lower() or "asset"


def _node_id(kind: str, path: str) -> str:
    return "pnode:" + hashlib.sha1(f"{kind}\x1f{path}".encode("utf-8")).hexdigest()[:24]


def _edge_id(source_kind: str, source: str, relation: str, target_kind: str, target: str) -> str:
    basis = "\x1f".join((source_kind, source, relation, target_kind, target))
    return "pedge:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


def _package(path: str) -> str:
    value = str(path or "")
    return value.split(".", 1)[0] if value.startswith("/") else ""


def _bp_kind(row: dict) -> str:
    cls = str(row.get("class", ""))
    if cls == "/Script/Engine.AnimBlueprint":
        return "animation_blueprint"
    if "ControlRigBlueprint" in cls:
        return "control_rig_blueprint"
    if "WidgetBlueprint" in cls:
        return "widget_blueprint"
    return "blueprint"


def derive(output, rows):
    nodes: dict[tuple[str, str], dict] = {}
    path_best: dict[str, dict] = {}
    aliases: dict[str, str] = {}

    def register(path, kind="object", coverage="external_or_excluded", class_path="",
                 package_name="", family="", root=False):
        path = str(path or "")
        if not path:
            return None
        kind = str(kind or "object")
        coverage = str(coverage or "external_or_excluded")
        package_name = str(package_name or _package(path))
        candidate = {
            "node_id": _node_id(kind, path), "node_kind": kind, "path": path,
            "coverage": coverage, "class_path": str(class_path or ""),
            "package_name": package_name, "family": str(family or ""),
            "root": bool(root),
        }
        key = (kind, path)
        current = nodes.get(key)
        if current is None or COVERAGE_RANK.get(coverage, 0) >= COVERAGE_RANK.get(current["coverage"], 0):
            if current and current.get("root"):
                candidate["root"] = True
            nodes[key] = candidate
        elif root:
            current["root"] = True
        best = path_best.get(path)
        stored = nodes[key]
        if best is None or COVERAGE_RANK.get(stored["coverage"], 0) > COVERAGE_RANK.get(best["coverage"], 0):
            path_best[path] = stored
        return nodes[key]

    # Universal registry fallback.
    assets = list(rows(output / "assets.jsonl"))
    for r in assets:
        register(r.get("object_path"), _class_leaf(r.get("class_path")), "generic_only",
                 r.get("class_path"), r.get("package_name"), "asset_registry", False)
    for r in rows(output / "blueprints.jsonl"):
        path = str(r.get("object_path", ""))
        register(path, _bp_kind(r), "first_class", r.get("class"), _package(path), "blueprint", True)
        if r.get("generated_class") and path:
            aliases[str(r["generated_class"])] = path

    specialist_streams = (
        ("animation_assets.jsonl", "animation_path", "animation_kind", "animation", "class_path", "package_name"),
        ("vfx_assets.jsonl", "vfx_path", "vfx_kind", "vfx", "class_path", "package_name"),
        ("systems_assets.jsonl", "systems_path", "systems_kind", "systems", "class_path", "package_name"),
        ("behavior_trees.jsonl", "behavior_tree_path", None, "ai", "class_path", None),
        ("blackboards.jsonl", "blackboard_path", None, "ai", "class_path", None),
        ("eqs_queries.jsonl", "eqs_path", None, "ai", "class_path", None),
        ("statetrees.jsonl", "statetree_path", None, "ai", "class_path", None),
        ("pcg_graphs.jsonl", "pcg_path", None, "pcg", "class_path", None),
        ("materials.jsonl", "material_path", "material_kind", "material", "class_path", None),
    )
    fixed_kinds = {
        "behavior_trees.jsonl":"behavior_tree", "blackboards.jsonl":"blackboard",
        "eqs_queries.jsonl":"eqs_query", "statetrees.jsonl":"statetree",
        "pcg_graphs.jsonl":"pcg_graph",
    }
    for filename, path_key, kind_key, family, class_key, package_key in specialist_streams:
        for r in rows(output / filename):
            kind = fixed_kinds.get(filename) or str(r.get(kind_key, "asset"))
            coverage = systems_kind_coverage(kind) if filename == "systems_assets.jsonl" else "first_class"
            register(r.get(path_key), kind, coverage, r.get(class_key, ""),
                     r.get(package_key, "") if package_key else "", family, True)

    # World instance nodes are typed, but not precomputed neighborhood roots.
    for r in rows(output / "worlds.jsonl"):
        register(r.get("world_path"), "world", "first_class", "/Script/Engine.World", r.get("package_name"), "world", True)
    for r in rows(output / "world_actors.jsonl"):
        register(r.get("actor_path"), "actor", "first_class", r.get("actor_class"), "", "world", False)
    for r in rows(output / "world_components.jsonl"):
        register(r.get("component_path"), "component", "first_class", r.get("component_class"), "", "world", False)

    evidence_by_key: dict[tuple[str, str, str, str, str], dict[str, tuple[dict, str]]] = collections.defaultdict(dict)

    def resolve_path(path: str) -> str:
        path = str(path or "")
        return aliases.get(path, path)

    def infer(path: str, desired_kind="object", coverage="external_or_excluded") -> dict:
        path = resolve_path(path)
        if path in path_best:
            return path_best[path]
        return register(path, desired_kind, coverage, "", _package(path), "external", False)

    def add(source, relation, target, *, source_kind="", target_kind="object",
            quality="exact_semantic", evidence=None):
        source = resolve_path(source)
        target = resolve_path(target)
        if not source or not relation or not target or source == target:
            return
        sm = path_best.get(source)
        if sm is None:
            sm = register(source, source_kind or "object", "external_or_excluded")
        tm = infer(target, target_kind)
        if not sm or not tm:
            return
        sk = str(source_kind or sm["node_kind"])
        # Preserve a more specific already-registered source kind when caller uses a generic label.
        if source in path_best and source_kind in ("", "object"):
            sk = path_best[source]["node_kind"]
        tk = str(tm["node_kind"] if target in path_best else target_kind or "object")
        key = (sk, source, str(relation), tk, target)
        ev = dict(evidence or {})
        ev.setdefault("quality", quality)
        token = json.dumps(ev, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        evidence_by_key[key][token] = (ev, quality)
        # Ensure endpoint nodes exist with the exact edge kinds.
        register(source, sk, sm.get("coverage", "external_or_excluded"), sm.get("class_path", ""), sm.get("package_name", ""), sm.get("family", ""), sm.get("root", False))
        register(target, tk, tm.get("coverage", "external_or_excluded"), tm.get("class_path", ""), tm.get("package_name", ""), tm.get("family", ""), tm.get("root", False))

    # Package nodes make generic dependency traversal explicit rather than guessing object targets.
    package_assets = collections.defaultdict(list)
    for node in list(nodes.values()):
        package = node.get("package_name", "")
        if package and node["path"] != package:
            package_assets[package].append(node)
    for package in sorted(package_assets):
        register(package, "package", "generic_only", "", package, "package", False)
        for node in sorted(package_assets[package], key=lambda n:(n["node_kind"], n["path"])):
            add(node["path"], "member_of_package", package, source_kind=node["node_kind"], target_kind="package",
                quality="exact_semantic", evidence={"stream":"assets.jsonl","kind":"canonical_package_membership"})
            add(package, "contains_asset", node["path"], source_kind="package", target_kind=node["node_kind"],
                quality="exact_semantic", evidence={"stream":"assets.jsonl","kind":"canonical_package_membership"})
    for r in rows(output / "asset_dependencies.jsonl"):
        source = str(r.get("source_package", "")); target = str(r.get("target_package", ""))
        if source and target:
            register(source, "package", "generic_only", "", source, "package", False)
            register(target, "package", "generic_only", "", target, "package", False)
            add(source, "depends_on_package", target, source_kind="package", target_kind="package",
                quality="generic_package_dependency", evidence={
                    "stream":"asset_dependencies.jsonl","kind":"generic_package_dependency",
                    "category":str(r.get("category", ""))})

    # Existing exact/derived domain relations.
    for r in rows(output / "animation_relations.jsonl"):
        add(r.get("source"), r.get("relation"), r.get("target"),
            source_kind=r.get("source_kind", "animation_asset"), target_kind=r.get("target_kind", "object"),
            quality="exact_semantic", evidence={"stream":"animation_relations.jsonl","kind":"domain_relation","relation_id":r.get("relation_id","")})
    for r in rows(output / "vfx_relations.jsonl"):
        add(r.get("source"), r.get("relation"), r.get("target"),
            source_kind=r.get("source_kind", "vfx_object"), target_kind=r.get("target_kind", "object"),
            quality="exact_semantic", evidence={"stream":"vfx_relations.jsonl","kind":"domain_relation","relation_id":r.get("relation_id","")})
    for r in rows(output / "world_relations.jsonl"):
        relation = str(r.get("relation", "")); detail = r.get("detail", {}) if isinstance(r.get("detail", {}), dict) else {}
        quality = "exact_reference" if "reference" in relation else "exact_semantic"
        if detail.get("resolution") == "unique_world_asset_dependency":
            quality = "unique_dependency_resolution"
        add(r.get("source_id"), relation, r.get("target"), source_kind=r.get("source_kind", "object"),
            target_kind=r.get("target_kind", "object"), quality=quality,
            evidence={"stream":"world_relations.jsonl","kind":"domain_relation","relation_id":r.get("relation_id","")})
    for r in rows(output / "world_system_relations.jsonl"):
        evidence = r.get("evidence", []) if isinstance(r.get("evidence", []), list) else []
        kinds = {str(e.get("kind", "")) for e in evidence if isinstance(e, dict)}
        quality = "unique_dependency_resolution" if any("dependency" in k for k in kinds) else "exact_reference"
        add(r.get("source_id"), r.get("relation"), r.get("target"), source_kind=r.get("source_kind", "object"),
            target_kind=r.get("target_kind", "object"), quality=quality,
            evidence={"stream":"world_system_relations.jsonl","kind":"domain_relation","relation_id":r.get("relation_id","")})
    for r in rows(output / "blueprint_relations.jsonl"):
        add(r.get("blueprint_path"), r.get("relation"), r.get("target"), source_kind="blueprint",
            target_kind=r.get("target_kind", "object"), quality="exact_reference",
            evidence={"stream":"blueprint_relations.jsonl","kind":"blueprint_relation","relation_id":r.get("relation_id",""),
                      "source_kind":r.get("source_kind",""),"source_id":r.get("source_id","")})
    for filename in ("ai_relations.jsonl", "visual_relations.jsonl"):
        for r in rows(output / filename):
            source = r.get("asset_path") or r.get("source") or r.get("source_id")
            target = r.get("target") or r.get("target_path")
            relation = r.get("relation") or "references_object"
            if source and target:
                add(source, relation, target, source_kind=r.get("source_kind") or r.get("system") or "asset",
                    target_kind=r.get("target_kind", "object"), quality="exact_semantic",
                    evidence={"stream":filename,"kind":"domain_relation","relation_id":r.get("relation_id","")})

    # New systems topology.
    track_by_path = {}
    for r in rows(output / "movie_scene_tracks.jsonl"):
        track = str(r.get("track_path", "")); sequence = str(r.get("sequence_path", ""))
        register(track, "movie_scene_track", "first_class", r.get("track_class", ""), _package(sequence), "cinematic", False)
        track_by_path[track] = r
        add(sequence, "contains_movie_scene_track", track, target_kind="movie_scene_track",
            quality="exact_semantic", evidence={"stream":"movie_scene_tracks.jsonl","kind":"canonical_structure","track_index":r.get("track_index",0)})
    for r in rows(output / "movie_scene_sections.jsonl"):
        section = str(r.get("section_path", "")); track = str(r.get("track_path", ""))
        register(section, "movie_scene_section", "first_class", r.get("section_class", ""), _package(r.get("sequence_path", "")), "cinematic", False)
        if track:
            add(track, "contains_movie_scene_section", section, source_kind="movie_scene_track", target_kind="movie_scene_section",
                quality="exact_semantic", evidence={"stream":"movie_scene_sections.jsonl","kind":"canonical_structure","section_index":r.get("section_index",0)})
    for r in rows(output / "movie_scene_channels.jsonl"):
        channel = f"{r.get('section_path','')}::channel[{int(r.get('channel_index',0))}]"
        register(channel, "movie_scene_channel", "first_class", r.get("channel_type", ""), _package(r.get("sequence_path", "")), "cinematic", False)
        add(r.get("section_path"), "contains_movie_scene_channel", channel, source_kind="movie_scene_section", target_kind="movie_scene_channel",
            quality="exact_semantic", evidence={"stream":"movie_scene_channels.jsonl","kind":"canonical_structure","property_path":r.get("property_path","")})
    for r in rows(output / "movie_scene_bindings.jsonl"):
        binding = f"{r.get('sequence_path','')}::binding[{int(r.get('binding_index',0))}]"
        register(binding, "movie_scene_binding", "first_class", r.get("struct_type", ""), _package(r.get("sequence_path", "")), "cinematic", False)
        add(r.get("sequence_path"), "contains_movie_scene_binding", binding, target_kind="movie_scene_binding",
            quality="exact_semantic", evidence={"stream":"movie_scene_bindings.jsonl","kind":"canonical_structure","binding_kind":r.get("binding_kind","")})
        if r.get("object_template_path"):
            add(binding, "uses_object_template", r.get("object_template_path"), source_kind="movie_scene_binding",
                target_kind="object", quality="exact_reference", evidence={"stream":"movie_scene_bindings.jsonl","kind":"canonical_field"})

    cue_nodes = {}
    for r in rows(output / "sound_cue_nodes.jsonl"):
        node = str(r.get("node_path", "")); cue = str(r.get("sound_cue_path", ""))
        register(node, "sound_cue_node", "first_class", r.get("node_class", ""), _package(cue), "audio", False)
        cue_nodes[node] = r
        add(cue, "contains_sound_cue_node", node, target_kind="sound_cue_node", quality="exact_semantic",
            evidence={"stream":"sound_cue_nodes.jsonl","kind":"canonical_structure","node_index":r.get("node_index",0)})
    meta_node_id = {}
    for r in rows(output / "metasound_nodes.jsonl"):
        asset = str(r.get("asset_path", "")); idx = int(r.get("node_index",0)); raw_id = str(r.get("node_id", ""))
        node = f"{asset}::metasound_node[{idx}]"
        register(node, "metasound_node", "first_class", r.get("struct_type", ""), _package(asset), "audio", False)
        if raw_id:
            meta_node_id[(asset, raw_id)] = node
        add(asset, "contains_metasound_node", node, target_kind="metasound_node", quality="exact_semantic",
            evidence={"stream":"metasound_nodes.jsonl","kind":"canonical_structure","node_index":idx,"node_id":raw_id})
    for r in rows(output / "metasound_edges.jsonl"):
        asset = str(r.get("asset_path", "")); src = meta_node_id.get((asset, str(r.get("from_node_id", ""))))
        dst = meta_node_id.get((asset, str(r.get("to_node_id", ""))))
        if src and dst:
            add(src, "metasound_connects_to", dst, source_kind="metasound_node", target_kind="metasound_node",
                quality="exact_semantic", evidence={"stream":"metasound_edges.jsonl","kind":"canonical_structure",
                    "edge_index":r.get("edge_index",0),"from_vertex_id":r.get("from_vertex_id",""),"to_vertex_id":r.get("to_vertex_id","")})

    for r in rows(output / "input_mappings.jsonl"):
        context = str(r.get("context_path", "")); idx = int(r.get("mapping_index",0))
        mapping = f"{context}::mapping[{idx}]"
        register(mapping, "input_mapping", "first_class", r.get("struct_type", ""), _package(context), "input", False)
        add(context, "contains_input_mapping", mapping, target_kind="input_mapping", quality="exact_semantic",
            evidence={"stream":"input_mappings.jsonl","kind":"canonical_structure","mapping_index":idx,"key":r.get("key","")})
        if r.get("action_path"):
            add(mapping, "maps_input_action", r.get("action_path"), source_kind="input_mapping", target_kind="input_action",
                quality="exact_reference", evidence={"stream":"input_mappings.jsonl","kind":"canonical_field","key":r.get("key","")})
    for r in rows(output / "input_processors.jsonl"):
        owner = str(r.get("asset_path", "")) if r.get("owner_scope") == "action" else \
            f"{r.get('asset_path','')}::mapping[{int(r.get('mapping_index',-1))}]"
        processor = str(r.get("processor_path", ""))
        kind = "input_trigger" if r.get("processor_kind") == "trigger" else "input_modifier"
        register(processor, kind, "first_class", r.get("processor_class", ""), _package(r.get("asset_path", "")), "input", False)
        add(owner, "uses_" + kind, processor,
            source_kind="input_action" if r.get("owner_scope") == "action" else "input_mapping",
            target_kind=kind, quality="exact_semantic",
            evidence={"stream":"input_processors.jsonl","kind":"canonical_structure","processor_index":r.get("processor_index",0)})
    for r in rows(output / "gameplay_tags.jsonl"):
        tag_node = f"gameplay_tag:{r.get('tag','')}"
        register(tag_node, "gameplay_tag", "first_class", r.get("row_struct", ""), _package(r.get("table_path", "")), "gameplay", False)
        add(r.get("table_path"), "declares_gameplay_tag", tag_node, target_kind="gameplay_tag", quality="exact_semantic",
            evidence={"stream":"gameplay_tags.jsonl","kind":"canonical_structure","row_name":r.get("row_name","")})

    # Exact reflected references from the combined systems pass.
    for r in rows(output / "systems_references.jsonl"):
        source = str(r.get("owner_path", "")); target = str(r.get("target_path", ""))
        if source and target:
            add(source, "references_object", target, source_kind=r.get("owner_kind", "object"), target_kind="object",
                quality="exact_reference", evidence={"stream":"systems_references.jsonl","kind":"canonical_reference",
                    "asset_path":r.get("asset_path",""),"root_property":r.get("root_property",""),
                    "property_path":r.get("property_path",""),"reference_kind":r.get("reference_kind","")})

    edges = []
    for key in sorted(evidence_by_key):
        sk, source, relation, tk, target = key
        evidence_pairs = [evidence_by_key[key][token] for token in sorted(evidence_by_key[key])]
        evidence = [pair[0] for pair in evidence_pairs]
        quality = max((pair[1] for pair in evidence_pairs), key=lambda q: QUALITY_RANK.get(q, -1))
        sm = nodes.get((sk, source)) or path_best.get(source) or register(source, sk)
        tm = nodes.get((tk, target)) or path_best.get(target) or register(target, tk)
        edges.append({
            "edge_id":_edge_id(sk,source,relation,tk,target),"source_kind":sk,"source":source,
            "relation":relation,"target_kind":tk,"target":target,
            "source_coverage":sm.get("coverage","external_or_excluded"),
            "target_coverage":tm.get("coverage","external_or_excluded"),
            "edge_quality":quality,"evidence_count":len(evidence),"evidence":evidence,
        })

    # Root neighborhoods use both incoming and outgoing graph directions.
    adjacency = collections.defaultdict(list)
    for edge in edges:
        adjacency[edge["source"]].append(("out", edge, edge["target"]))
        adjacency[edge["target"]].append(("in", edge, edge["source"]))
    for path in adjacency:
        adjacency[path].sort(key=lambda item:(item[0],item[1]["relation"],item[1]["source_kind"],item[1]["source"],item[1]["target_kind"],item[1]["target"],item[1]["edge_id"]))

    root_nodes = {}
    for node in nodes.values():
        if node.get("root") and node["path"] in adjacency:
            previous = root_nodes.get(node["path"])
            if previous is None or COVERAGE_RANK.get(node["coverage"],0) > COVERAGE_RANK.get(previous["coverage"],0):
                root_nodes[node["path"]] = node

    neighborhoods = []
    for root_path in sorted(root_nodes):
        root = root_nodes[root_path]
        queue = collections.deque([(root_path, 0)])
        expanded_depth = {root_path: 0}
        seen_edges = set()
        touched_nodes = {root_path}
        hops = []
        truncated = False
        while queue and len(hops) < MAX_NEIGHBOR_EDGES:
            current, depth = queue.popleft()
            if depth >= MAX_NEIGHBOR_DEPTH:
                continue
            for direction, edge, other in adjacency.get(current, []):
                if edge["edge_id"] in seen_edges:
                    continue
                seen_edges.add(edge["edge_id"])
                hop = {
                    "depth":depth + 1,"direction":direction,"edge_id":edge["edge_id"],
                    "source_kind":edge["source_kind"],"source":edge["source"],"relation":edge["relation"],
                    "target_kind":edge["target_kind"],"target":edge["target"],
                    "source_coverage":edge["source_coverage"],"target_coverage":edge["target_coverage"],
                    "edge_quality":edge["edge_quality"],"evidence_count":edge["evidence_count"],
                    "evidence":edge["evidence"],
                }
                hops.append(hop); touched_nodes.add(other)
                if len(hops) >= MAX_NEIGHBOR_EDGES:
                    truncated = True
                    break
                next_depth = depth + 1
                if next_depth < MAX_NEIGHBOR_DEPTH and (other not in expanded_depth or next_depth < expanded_depth[other]):
                    expanded_depth[other] = next_depth
                    queue.append((other, next_depth))
            if truncated:
                break
        if queue:
            truncated = True
        lines = [
            f"Root: {root_path}", f"Kind: {root['node_kind']} coverage={root['coverage']}",
            f"Neighborhood: depth<={MAX_NEIGHBOR_DEPTH} edges={len(hops)} nodes={len(touched_nodes)} truncated={truncated}",
        ]
        for hop in hops:
            arrow = "->" if hop["direction"] == "out" else "<-"
            lines.append(
                f"d{hop['depth']} {hop['source_kind']} {hop['source']} {arrow} {hop['relation']} {arrow} "
                f"{hop['target_kind']} {hop['target']} quality={hop['edge_quality']} "
                f"coverage={hop['source_coverage']}->{hop['target_coverage']} evidence={hop['evidence_count']}"
            )
        text = "\n".join(lines)
        if len(text) > MAX_NEIGHBOR_CHARS:
            text = text[:MAX_NEIGHBOR_CHARS] + "\n...[truncated]"
            truncated = True
        neighborhoods.append({
            "root_path":root_path,"root_kind":root["node_kind"],"root_coverage":root["coverage"],
            "max_depth":MAX_NEIGHBOR_DEPTH,"edge_count":len(hops),"node_count":len(touched_nodes),
            "truncated":truncated,"text":text,"hops":hops,
        })

    node_rows = sorted(nodes.values(), key=lambda n:(n["path"],n["node_kind"],n["node_id"]))
    edges.sort(key=lambda e:(e["source"],e["relation"],e["target"],e["edge_id"]))
    return node_rows, edges, neighborhoods


def validation_error(output, rows) -> str | None:
    try:
        nodes = list(rows(output / "project_nodes.jsonl"))
        edges = list(rows(output / "project_edges.jsonl"))
        neighborhoods = list(rows(output / "project_neighborhoods.jsonl"))
    except RuntimeError as exc:
        return str(exc)
    if len({n.get("node_id", "") for n in nodes}) != len(nodes):
        return "duplicate project node_id"
    if len({e.get("edge_id", "") for e in edges}) != len(edges):
        return "duplicate project edge_id"
    node_keys = {(str(n.get("node_kind","")),str(n.get("path",""))):n for n in nodes}
    edge_ids = {str(e.get("edge_id","")) for e in edges}
    for e in edges:
        sk=(str(e.get("source_kind","")),str(e.get("source",""))); tk=(str(e.get("target_kind","")),str(e.get("target","")))
        if sk not in node_keys or tk not in node_keys:
            return f"project edge endpoint missing: {e.get('edge_id')}"
        if e.get("source_coverage") != node_keys[sk].get("coverage") or e.get("target_coverage") != node_keys[tk].get("coverage"):
            return f"project edge coverage mismatch: {e.get('edge_id')}"
        quality=str(e.get("edge_quality",""))
        if quality not in QUALITY_RANK:
            return f"invalid project edge quality: {quality}"
        evidence=e.get("evidence",[]) if isinstance(e.get("evidence",[]),list) else []
        if int(e.get("evidence_count",0)) != len(evidence) or not evidence:
            return f"project edge evidence mismatch: {e.get('edge_id')}"
        if any(ev.get("stream")=="asset_dependencies.jsonl" for ev in evidence if isinstance(ev,dict)) and quality != "generic_package_dependency":
            return "generic package dependency promoted above generic quality"
        expected=_edge_id(sk[0],sk[1],str(e.get("relation","")),tk[0],tk[1])
        if expected != e.get("edge_id"):
            return f"non-deterministic project edge id: {e.get('edge_id')}"
    roots={str(n.get("path","")) for n in nodes if n.get("root")}
    seen_roots=set()
    for n in neighborhoods:
        root=str(n.get("root_path","")); seen_roots.add(root)
        if root not in roots:
            return f"project neighborhood root is not a graph root: {root}"
        hops=n.get("hops",[]) if isinstance(n.get("hops",[]),list) else []
        if int(n.get("edge_count",0)) != len(hops) or len(hops)>MAX_NEIGHBOR_EDGES:
            return f"project neighborhood edge bound/count mismatch: {root}"
        for hop in hops:
            if int(hop.get("depth",0))<1 or int(hop.get("depth",0))>MAX_NEIGHBOR_DEPTH:
                return f"project neighborhood depth invalid: {root}"
            if str(hop.get("edge_id","")) not in edge_ids:
                return f"project neighborhood references unknown edge: {root}"
            if hop.get("edge_quality") not in QUALITY_RANK or not hop.get("source_coverage") or not hop.get("target_coverage"):
                return f"project neighborhood hop lacks quality/coverage: {root}"
    expected_roots={str(n.get("path","")) for n in nodes if n.get("root") and any(e.get("source")==n.get("path") or e.get("target")==n.get("path") for e in edges)}
    if seen_roots != expected_roots:
        return "project neighborhoods do not exactly cover connected graph roots"
    return None


def load_database(conn, output, rows) -> None:
    for r in rows(output / "project_nodes.jsonl"):
        conn.execute("INSERT OR REPLACE INTO project_nodes VALUES(?,?,?,?,?,?,?,?,?)",(
            r.get("node_id",""),r.get("node_kind",""),r.get("path",""),r.get("coverage",""),r.get("class_path",""),
            r.get("package_name",""),r.get("family",""),int(bool(r.get("root",False))),json.dumps(r,ensure_ascii=False,separators=(",",":"))))
    for r in rows(output / "project_edges.jsonl"):
        conn.execute("INSERT OR REPLACE INTO project_edges VALUES(?,?,?,?,?,?,?,?,?,?,?)",(
            r.get("edge_id",""),r.get("source_kind",""),r.get("source",""),r.get("relation",""),r.get("target_kind",""),r.get("target",""),
            r.get("source_coverage",""),r.get("target_coverage",""),r.get("edge_quality",""),int(r.get("evidence_count",0)),
            json.dumps(r.get("evidence",[]),ensure_ascii=False,separators=(",",":"))))
    for r in rows(output / "project_neighborhoods.jsonl"):
        conn.execute("INSERT OR REPLACE INTO project_neighborhoods VALUES(?,?,?,?,?,?,?,?,?)",(
            r.get("root_path",""),r.get("root_kind",""),r.get("root_coverage",""),int(r.get("max_depth",0)),int(r.get("edge_count",0)),
            int(r.get("node_count",0)),int(bool(r.get("truncated",False))),r.get("text",""),json.dumps(r,ensure_ascii=False,separators=(",",":"))))


def query(conn, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_nodes'").fetchone():
        return
    print("\n[project nodes]")
    print_rows(conn.execute(
        "SELECT node_kind,path,coverage,family,class_path FROM project_nodes WHERE path LIKE ? OR node_kind LIKE ? OR family LIKE ? OR class_path LIKE ? LIMIT ?",
        (pattern,pattern,pattern,pattern,limit)),("node_kind","path","coverage","family","class_path"))
    print("\n[project edges]")
    print_rows(conn.execute(
        "SELECT source_kind,source,relation,target_kind,target,edge_quality,source_coverage,target_coverage FROM project_edges "
        "WHERE source LIKE ? OR relation LIKE ? OR target LIKE ? OR edge_quality LIKE ? OR evidence_json LIKE ? LIMIT ?",
        (pattern,pattern,pattern,pattern,pattern,limit)),
        ("source_kind","source","relation","target_kind","target","edge_quality","source_coverage","target_coverage"))
    print("\n[project neighborhoods]")
    print_rows(conn.execute(
        "SELECT root_path,root_kind,root_coverage,edge_count,node_count,truncated,substr(text,1,2200) text FROM project_neighborhoods "
        "WHERE root_path LIKE ? OR root_kind LIKE ? OR text LIKE ? LIMIT ?",(pattern,pattern,pattern,limit)),
        ("root_path","root_kind","root_coverage","edge_count","node_count","truncated","text"))
