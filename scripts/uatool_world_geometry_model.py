#!/usr/bin/env python3
"""Exact authored graph model for world-geometry schema 1."""
from __future__ import annotations

RELATIONS = {
    "landscape_contains_component", "landscape_uses_material", "landscape_uses_hole_material",
    "landscape_component_uses_heightmap_texture", "landscape_component_uses_weightmap_texture",
    "landscape_component_has_layer_allocation", "landscape_allocation_uses_layer_info",
    "landscape_grass_type_has_variety", "grass_variety_uses_mesh", "foliage_type_uses_mesh",
    "foliage_actor_has_type_info", "foliage_info_uses_foliage_type", "foliage_info_has_instance",
    "foliage_instance_uses_base_component", "hlod_layer_has_parent_layer", "hlod_layer_has_linked_layer",
    "hlod_layer_uses_builder_settings",
}
RELATION_STREAMS = {
    "landscape_contains_component":"world_geometry_landscape_components.jsonl",
    "landscape_uses_material":"world_geometry_landscapes.jsonl", "landscape_uses_hole_material":"world_geometry_landscapes.jsonl",
    "landscape_component_uses_heightmap_texture":"world_geometry_landscape_components.jsonl",
    "landscape_component_uses_weightmap_texture":"world_geometry_landscape_weightmaps.jsonl",
    "landscape_component_has_layer_allocation":"world_geometry_landscape_layer_allocations.jsonl",
    "landscape_allocation_uses_layer_info":"world_geometry_landscape_layer_allocations.jsonl",
    "landscape_grass_type_has_variety":"world_geometry_grass_varieties.jsonl", "grass_variety_uses_mesh":"world_geometry_grass_varieties.jsonl",
    "foliage_type_uses_mesh":"world_geometry_foliage_types.jsonl", "foliage_actor_has_type_info":"world_geometry_foliage_infos.jsonl",
    "foliage_info_uses_foliage_type":"world_geometry_foliage_infos.jsonl", "foliage_info_has_instance":"world_geometry_foliage_instances.jsonl",
    "foliage_instance_uses_base_component":"world_geometry_foliage_instances.jsonl",
    "hlod_layer_has_parent_layer":"world_geometry_hlod_layers.jsonl", "hlod_layer_has_linked_layer":"world_geometry_hlod_layers.jsonl",
    "hlod_layer_uses_builder_settings":"world_geometry_hlod_layers.jsonl",
}

def allocation_path(component: str, index: int) -> str: return f"{component}#layer-allocation:{index}"
def grass_variety_path(grass_type: str, index: int) -> str: return f"{grass_type}#variety:{index}"
def foliage_info_path(actor: str, map_index: int) -> str: return f"{actor}#foliage-info:{map_index}"
def foliage_instance_path(actor: str, map_index: int, instance_index: int) -> str: return f"{actor}#foliage-info:{map_index}:instance:{instance_index}"

def _node(path: str, kind: str, *, class_path: str = "", package_name: str = "", family: str = "world_geometry", root: bool = False) -> dict:
    return {"path":str(path or ""),"kind":str(kind or "object"),"coverage":"first_class","class_path":str(class_path or ""),"package_name":str(package_name or ""),"family":family,"root":bool(root)}

def _edge(source: str, relation: str, target: str, source_kind: str, target_kind: str, stream: str, **detail) -> dict:
    evidence={"kind":"canonical_world_geometry","stream":stream,"quality":"exact_semantic"}; evidence.update({k:v for k,v in detail.items() if v not in (None,"")})
    return {"source":str(source or ""),"relation":str(relation or ""),"target":str(target or ""),"source_kind":str(source_kind or "object"),"target_kind":str(target_kind or "object"),"evidence":evidence}

def build_model(output, rows) -> dict:
    nodes={}; edges={}
    def add_node(spec):
        path=str(spec.get("path","")); kind=str(spec.get("kind",""))
        if path and kind: nodes[(kind,path)]=spec
    def add_edge(spec):
        if not spec["source"] or not spec["target"] or not spec["relation"]: return
        edges[(spec["source_kind"],spec["source"],spec["relation"],spec["target_kind"],spec["target"])]=spec

    for r in rows(output/"world_geometry_landscapes.jsonl"):
        p=str(r.get("landscape_path","")); add_node(_node(p,"landscape",class_path=str(r.get("class_path","")),package_name=str(r.get("package_name","")),root=True))
        m=str(r.get("landscape_material_path",""))
        if m: add_node(_node(m,"material",family="material")); add_edge(_edge(p,"landscape_uses_material",m,"landscape","material","world_geometry_landscapes.jsonl",field="landscape_material_path"))
        h=str(r.get("landscape_hole_material_path",""))
        if h: add_node(_node(h,"material",family="material")); add_edge(_edge(p,"landscape_uses_hole_material",h,"landscape","material","world_geometry_landscapes.jsonl",field="landscape_hole_material_path"))
    for r in rows(output/"world_geometry_landscape_components.jsonl"):
        owner=str(r.get("landscape_path","")); p=str(r.get("component_path","")); add_node(_node(p,"landscape_component",class_path=str(r.get("component_class",""))))
        add_edge(_edge(owner,"landscape_contains_component",p,"landscape","landscape_component","world_geometry_landscape_components.jsonl",component_index=int(r.get("component_index",0) or 0)))
        t=str(r.get("heightmap_texture_path",""))
        if t: add_node(_node(t,"texture2d",class_path=str(r.get("heightmap_texture_class","")),family="texture")); add_edge(_edge(p,"landscape_component_uses_heightmap_texture",t,"landscape_component","texture2d","world_geometry_landscape_components.jsonl",field="heightmap_texture_path"))
    for r in rows(output/"world_geometry_landscape_weightmaps.jsonl"):
        p=str(r.get("component_path","")); t=str(r.get("texture_path",""))
        if t: add_node(_node(t,"texture2d",class_path=str(r.get("texture_class","")),family="texture")); add_edge(_edge(p,"landscape_component_uses_weightmap_texture",t,"landscape_component","texture2d","world_geometry_landscape_weightmaps.jsonl",texture_index=int(r.get("texture_index",0) or 0)))
    for r in rows(output/"world_geometry_landscape_layer_infos.jsonl"):
        p=str(r.get("layer_info_path","")); add_node(_node(p,"landscape_layer_info",class_path=str(r.get("class_path","")),package_name=str(r.get("package_name","")),root=True))
    for r in rows(output/"world_geometry_landscape_layer_allocations.jsonl"):
        comp=str(r.get("component_path","")); idx=int(r.get("allocation_index",0) or 0); p=allocation_path(comp,idx); add_node(_node(p,"landscape_layer_allocation",class_path=str(r.get("struct_type",""))))
        add_edge(_edge(comp,"landscape_component_has_layer_allocation",p,"landscape_component","landscape_layer_allocation","world_geometry_landscape_layer_allocations.jsonl",allocation_index=idx))
        li=str(r.get("layer_info_path",""))
        if li: add_node(_node(li,"landscape_layer_info")); add_edge(_edge(p,"landscape_allocation_uses_layer_info",li,"landscape_layer_allocation","landscape_layer_info","world_geometry_landscape_layer_allocations.jsonl",weightmap_texture_index=str(r.get("weightmap_texture_index","")),weightmap_texture_channel=str(r.get("weightmap_texture_channel",""))))
    for r in rows(output/"world_geometry_grass_types.jsonl"):
        p=str(r.get("grass_type_path","")); add_node(_node(p,"landscape_grass_type",class_path=str(r.get("class_path","")),package_name=str(r.get("package_name","")),root=True))
    for r in rows(output/"world_geometry_grass_varieties.jsonl"):
        g=str(r.get("grass_type_path","")); idx=int(r.get("variety_index",0) or 0); p=grass_variety_path(g,idx); add_node(_node(p,"landscape_grass_variety",class_path=str(r.get("struct_type",""))))
        add_edge(_edge(g,"landscape_grass_type_has_variety",p,"landscape_grass_type","landscape_grass_variety","world_geometry_grass_varieties.jsonl",variety_index=idx))
        m=str(r.get("grass_mesh_path",""))
        if m: add_node(_node(m,"static_mesh",family="static_mesh")); add_edge(_edge(p,"grass_variety_uses_mesh",m,"landscape_grass_variety","static_mesh","world_geometry_grass_varieties.jsonl",variety_index=idx))
    for r in rows(output/"world_geometry_foliage_types.jsonl"):
        p=str(r.get("foliage_type_path","")); add_node(_node(p,"foliage_type",class_path=str(r.get("class_path","")),package_name=str(r.get("package_name","")),root=True)); m=str(r.get("mesh_path",""))
        if m: add_node(_node(m,"static_mesh",class_path=str(r.get("mesh_class","")),family="static_mesh")); add_edge(_edge(p,"foliage_type_uses_mesh",m,"foliage_type","static_mesh","world_geometry_foliage_types.jsonl",field="mesh_path"))
    for r in rows(output/"world_geometry_foliage_actors.jsonl"):
        p=str(r.get("foliage_actor_path","")); add_node(_node(p,"instanced_foliage_actor",class_path=str(r.get("class_path","")),package_name=str(r.get("package_name","")),root=True))
    for r in rows(output/"world_geometry_foliage_infos.jsonl"):
        actor=str(r.get("foliage_actor_path","")); idx=int(r.get("map_index",0) or 0); p=foliage_info_path(actor,idx); add_node(_node(p,"foliage_info",class_path="FFoliageInfo")); add_edge(_edge(actor,"foliage_actor_has_type_info",p,"instanced_foliage_actor","foliage_info","world_geometry_foliage_infos.jsonl",map_index=idx,capture_mode=str(r.get("capture_mode",""))))
        ft=str(r.get("foliage_type_path",""))
        if ft: add_node(_node(ft,"foliage_type",class_path=str(r.get("foliage_type_class","")))); add_edge(_edge(p,"foliage_info_uses_foliage_type",ft,"foliage_info","foliage_type","world_geometry_foliage_infos.jsonl",map_index=idx))
    for r in rows(output/"world_geometry_foliage_instances.jsonl"):
        actor=str(r.get("foliage_actor_path","")); mi=int(r.get("map_index",0) or 0); ii=int(r.get("instance_index",0) or 0); info=foliage_info_path(actor,mi); p=foliage_instance_path(actor,mi,ii); add_node(_node(p,"foliage_instance",class_path=str(r.get("instance_struct",""))))
        add_edge(_edge(info,"foliage_info_has_instance",p,"foliage_info","foliage_instance","world_geometry_foliage_instances.jsonl",instance_index=ii,capture_mode=str(r.get("capture_mode",""))))
        base=str(r.get("base_component_path",""))
        if base: add_node(_node(base,"component",class_path=str(r.get("base_component_class","")),family="world")); add_edge(_edge(p,"foliage_instance_uses_base_component",base,"foliage_instance","component","world_geometry_foliage_instances.jsonl",base_id=int(r.get("base_id",-1))))
    for r in rows(output/"world_geometry_hlod_layers.jsonl"):
        p=str(r.get("hlod_layer_path","")); add_node(_node(p,"hlod_layer",class_path=str(r.get("class_path","")),package_name=str(r.get("package_name","")),root=True))
        parent=str(r.get("parent_layer_path",""))
        if parent: add_node(_node(parent,"hlod_layer",class_path=str(r.get("parent_layer_class","")))); add_edge(_edge(p,"hlod_layer_has_parent_layer",parent,"hlod_layer","hlod_layer","world_geometry_hlod_layers.jsonl",field="parent_layer_path"))
        linked=str(r.get("linked_layer_path",""))
        if linked: add_node(_node(linked,"hlod_layer",class_path=str(r.get("linked_layer_class","")))); add_edge(_edge(p,"hlod_layer_has_linked_layer",linked,"hlod_layer","hlod_layer","world_geometry_hlod_layers.jsonl",field="linked_layer_path"))
        settings=str(r.get("builder_settings_path",""))
        if settings: add_node(_node(settings,"hlod_builder_settings",class_path=str(r.get("builder_settings_class","")))); add_edge(_edge(p,"hlod_layer_uses_builder_settings",settings,"hlod_layer","hlod_builder_settings","world_geometry_hlod_layers.jsonl",field="builder_settings_path"))
    return {"nodes":[nodes[k] for k in sorted(nodes)],"edge_specs":[edges[k] for k in sorted(edges)],"counts":{"first_class_nodes":len(nodes),"exact_semantic_edges":len(edges)}}

def expected_edge_keys(output, rows) -> set[tuple[str,str,str]]:
    return {(s["source"],s["relation"],s["target"]) for s in build_model(output,rows)["edge_specs"]}
