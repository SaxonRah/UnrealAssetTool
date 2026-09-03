#!/usr/bin/env python3
"""Real-corpus acceptance and graph verification for world-geometry schema 1."""
from __future__ import annotations
import argparse, collections, json, os, sys
from pathlib import Path
import uatool_world_geometry_schema as schema
import uatool_world_geometry_graph as graph
import uatool_world_geometry_model as model

ACCEPTANCE_MANIFEST="world_geometry_schema1_acceptance.json"
GRAPH_EXPECTATIONS_MANIFEST="world_geometry_schema1_graph_expectations.json"
GRAPH_VERIFICATION_MANIFEST="world_geometry_schema1_graph_verification.json"
CONTENTEXAMPLES_EXPECTED_EXACT_EDGES=1015
CONTENTEXAMPLES_EXACT_COUNTS={
 "world_geometry_landscapes":75,"world_geometry_landscape_components":100,"world_geometry_landscape_weightmaps":100,
 "world_geometry_landscape_layer_allocations":256,"world_geometry_landscape_layer_infos":5,"world_geometry_grass_types":1,
 "world_geometry_grass_varieties":3,"world_geometry_foliage_types":3,"world_geometry_foliage_actors":2,
 "world_geometry_foliage_infos":6,"world_geometry_foliage_instances":101,"world_geometry_hlod_layers":4,
 "landscape_components_with_heightmap":100,"landscape_weightmap_texture_refs":100,"landscape_allocations_with_layer_info":256,
 "grass_varieties_with_mesh":3,"foliage_types_with_mesh":3,"foliage_infos_native_editor_array":6,
 "foliage_instances_native_editor_array":101,"hlod_parent_layer_refs":2,"hlod_linked_layer_refs":0,"hlod_builder_settings_refs":4,
}
def _read(path):
    value=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise RuntimeError(f"{Path(path).name} root is not an object")
    return value
def _write(path,value):
    path=Path(path); temp=path.with_name(f".{path.name}.tmp"); temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n"); os.replace(temp,path)
def _corpus(value):
    p=Path(value).expanduser().resolve()
    if not p.is_dir(): raise FileNotFoundError(f"corpus directory does not exist: {p}")
    return p
def _expectations(corpus,rows):
    built=model.build_model(corpus,rows); edge_keys={(s["source"],s["relation"],s["target"]) for s in built["edge_specs"]}; rc=collections.Counter(r for _,r,_ in edge_keys)
    return {"schema_version":1,"target_derived_schema_version":graph.TARGET_DERIVED_SCHEMA_VERSION,"edge_quality":"exact_semantic","expected_exact_semantic_edge_count":len(edge_keys),"expected_relation_counts":{r:int(rc.get(r,0)) for r in sorted(model.RELATIONS)},"expected_edges":[{"source":s,"relation":r,"target":t} for s,r,t in sorted(edge_keys)]}
def _require_shape(corpus,rows):
    error=schema.validation_error(corpus,require_present=True)
    if error: raise RuntimeError(f"world-geometry schema 1 corpus invalid: {error}")
    manifest=_read(corpus/schema.MANIFEST_FILE); counts=manifest.get("counts",{})
    if not isinstance(counts,dict): raise RuntimeError("world_geometry_manifest counts missing")
    mismatches=[f"{k}:expected={v} actual={int(counts.get(k,-1))}" for k,v in CONTENTEXAMPLES_EXACT_COUNTS.items() if int(counts.get(k,-1))!=v]
    if mismatches: raise RuntimeError("ContentExamples world-geometry schema-1 acceptance mismatch: "+", ".join(mismatches))
    for flag in ("runtime_state_captured","generated_geometry_captured","render_resources_captured","world_runtime_streaming_state_captured","maps_loaded"):
        if bool(manifest.get(flag,True)): raise RuntimeError(f"authored-only boundary violated: {flag}=true")
    infos=list(rows(corpus/"world_geometry_foliage_infos.jsonl")); instances=list(rows(corpus/"world_geometry_foliage_instances.jsonl"))
    if not infos or not instances: raise RuntimeError("native painted foliage placement evidence missing")
    if any(str(r.get("capture_mode",""))!="native_editor_array" for r in (*infos,*instances)): raise RuntimeError("painted foliage placement contains non-native provenance")
    return {str(k):int(v or 0) for k,v in counts.items()}
def promote(corpus,capture_dir): return schema.promote_capture(corpus,capture_dir)
def accept(corpus,rows):
    counts=_require_shape(corpus,rows); expectations=_expectations(corpus,rows)
    actual_edge_count=int(expectations["expected_exact_semantic_edge_count"])
    if actual_edge_count!=CONTENTEXAMPLES_EXPECTED_EXACT_EDGES:
        raise RuntimeError(f"ContentExamples world-geometry exact graph contract mismatch: expected={CONTENTEXAMPLES_EXPECTED_EXACT_EDGES} actual={actual_edge_count}")
    result={"acceptance_schema_version":1,"world_geometry_schema_version":schema.WORLD_GEOMETRY_SCHEMA_VERSION,"target_derived_schema_version":graph.TARGET_DERIVED_SCHEMA_VERSION,"representative_content":"ContentExamples UE 5.8.2 authored Landscape/Foliage/HLOD topology","canonical_pass":schema.CANONICAL_PASS,"runtime_state_captured":False,"generated_geometry_captured":False,"render_resources_captured":False,"world_runtime_streaming_state_captured":False,"maps_loaded":False,"counts":counts,"expected_relation_counts":expectations["expected_relation_counts"],"expected_exact_semantic_edge_count":actual_edge_count}
    _write(corpus/ACCEPTANCE_MANIFEST,result); _write(corpus/GRAPH_EXPECTATIONS_MANIFEST,expectations); return result
def verify(corpus,rows):
    expectations=_read(corpus/GRAPH_EXPECTATIONS_MANIFEST); top=_read(corpus/"manifest.json"); actual_version=int(top.get("derived_schema_version",0) or 0)
    if actual_version!=graph.TARGET_DERIVED_SCHEMA_VERSION: raise RuntimeError(f"world-geometry graph verification requires derived schema {graph.TARGET_DERIVED_SCHEMA_VERSION}; got {actual_version}")
    expected=model.expected_edge_keys(corpus,rows)
    if len(expected)!=CONTENTEXAMPLES_EXPECTED_EXACT_EDGES: raise RuntimeError(f"world-geometry graph expectation count drifted: expected={CONTENTEXAMPLES_EXPECTED_EXACT_EDGES} actual={len(expected)}")
    actual_rows=[r for r in rows(corpus/"project_edges.jsonl") if str(r.get("relation","")) in model.RELATIONS]
    actual={(str(r.get("source","")),str(r.get("relation","")),str(r.get("target",""))) for r in actual_rows}
    if actual!=expected:
        missing=sorted(expected-actual); extra=sorted(actual-expected); parts=[]
        if missing: parts.append(f"missing={len(missing)} first={missing[0]}")
        if extra: parts.append(f"extra={len(extra)} first={extra[0]}")
        raise RuntimeError("world-geometry exact graph edge set mismatch: "+"; ".join(parts))
    rc=collections.Counter()
    for r in actual_rows:
        relation=str(r.get("relation","")); rc[relation]+=1
        if str(r.get("edge_quality",""))!="exact_semantic": raise RuntimeError(f"world-geometry relation is not exact_semantic: {relation}")
        stream=model.RELATION_STREAMS[relation]; evidence=r.get("evidence",[]) if isinstance(r.get("evidence",[]),list) else []
        if not any(isinstance(item,dict) and str(item.get("stream",""))==stream for item in evidence): raise RuntimeError(f"world-geometry relation lacks canonical evidence stream: {relation}")
    expected_counts=expectations.get("expected_relation_counts",{})
    for relation in sorted(model.RELATIONS):
        if int(expected_counts.get(relation,0) or 0)!=int(rc.get(relation,0)): raise RuntimeError(f"world-geometry relation count mismatch for {relation}")
    result={"schema_version":1,"verified":True,"world_geometry_schema_version":schema.WORLD_GEOMETRY_SCHEMA_VERSION,"derived_schema_version":actual_version,"edge_quality":"exact_semantic","verified_exact_semantic_edge_count":len(actual),"relation_counts":{r:int(rc.get(r,0)) for r in sorted(model.RELATIONS)},"runtime_state_captured":False}; _write(corpus/GRAPH_VERIFICATION_MANIFEST,result); return result
def install(runtime_module):
    if getattr(runtime_module,"_world_geometry_schema1_accept_installed",False): return
    try:
        import uatool_core as core
        core.DEFAULT_BUNDLE_FILES=tuple(dict.fromkeys((*core.DEFAULT_BUNDLE_FILES,ACCEPTANCE_MANIFEST,GRAPH_EXPECTATIONS_MANIFEST,GRAPH_VERIFICATION_MANIFEST)))
    except Exception: pass
    original_main=runtime_module.main
    def main():
        command=sys.argv[1] if len(sys.argv)>1 else ""
        try:
            if command=="world-geometry-schema1-promote":
                p=argparse.ArgumentParser(prog="uatool world-geometry-schema1-promote"); p.add_argument("corpus"); p.add_argument("--capture"); a=p.parse_args(sys.argv[2:]); corpus=_corpus(a.corpus); cap=Path(a.capture).expanduser().resolve() if a.capture else corpus/"world-geometry-native-capture"; result=promote(corpus,cap)
                print(f"promoted focused world geometry capture to schema 1: {corpus}"); [print(f"  {k}: {result['counts'][k]}") for k in sorted(result["counts"])]; return 0
            if command=="world-geometry-schema1-accept":
                p=argparse.ArgumentParser(prog="uatool world-geometry-schema1-accept"); p.add_argument("corpus"); a=p.parse_args(sys.argv[2:]); result=accept(_corpus(a.corpus),runtime_module._rows); print(f"accepted ContentExamples world-geometry schema 1: {a.corpus}"); print(f"  expected_exact_semantic_edges: {result['expected_exact_semantic_edge_count']}"); return 0
            if command=="world-geometry-graph-verify":
                p=argparse.ArgumentParser(prog="uatool world-geometry-graph-verify"); p.add_argument("corpus"); a=p.parse_args(sys.argv[2:]); result=verify(_corpus(a.corpus),runtime_module._rows); print(f"verified world-geometry derived-schema-{graph.TARGET_DERIVED_SCHEMA_VERSION} graph: {a.corpus}"); print(f"  exact_semantic_edges: {result['verified_exact_semantic_edge_count']}"); return 0
        except Exception as exc: print(f"ERROR: {exc}",file=sys.stderr); return 68
        return original_main()
    runtime_module.main=main; runtime_module._world_geometry_schema1_accept_installed=True
