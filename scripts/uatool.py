#!/usr/bin/env python3
"""Canonical UnrealAssetTool CLI extended with derived world schema 8."""
from __future__ import annotations
import builtins, collections, hashlib, json, sqlite3
from pathlib import Path
import uatool_core as core

DERIVED_SCHEMA_VERSION = 8
WORLD_DERIVED_FILES = ("world_relations.jsonl","world_context.jsonl","world_summaries.jsonl")

def _rows(path):
    if not path.exists(): return
    with path.open("r",encoding="utf-8") as f:
        for n,line in enumerate(f,1):
            line=line.strip()
            if not line: continue
            try: yield json.loads(line)
            except json.JSONDecodeError as e: raise RuntimeError(f"Invalid JSON in {path}:{n}: {e}") from e

def _write(path, rows):
    with path.open("w",encoding="utf-8",newline="\n") as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False,separators=(",",":"))+"\n")
    return len(rows)

def _derive_world(output):
    dl={(r.get("world_path",""),r.get("instance_name","")):r for r in _rows(output/"world_data_layers.jsonl")}
    actors=list(_rows(output/"world_actors.jsonl")); descs=list(_rows(output/"world_partition_actor_descs.jsonl"))
    loaded={(r.get("world_path",""),r.get("actor_guid","")):r for r in actors if r.get("actor_guid")}
    dguid={(r.get("world_path",""),r.get("actor_guid","")):r for r in descs if r.get("actor_guid")}
    rel=[]; seen=set()
    def add(w,sk,sid,r,tk,t,d=None):
        if not (w and sid and r and t): return
        d=d or {}; dj=json.dumps(d,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        k=(w,sk,sid,r,tk,t,dj)
        if k in seen:return
        seen.add(k)
        rel.append({"relation_id":"wrel:"+hashlib.sha1("\x1f".join(k).encode()).hexdigest()[:24],
                    "world_path":w,"source_kind":sk,"source_id":sid,"relation":r,
                    "target_kind":tk,"target":t,"detail":d})
    worlds=list(_rows(output/"worlds.jsonl")); levels=list(_rows(output/"world_levels.jsonl"))
    comps=list(_rows(output/"world_components.jsonl")); props=list(_rows(output/"world_instance_properties.jsonl"))
    refs=list(_rows(output/"world_references.jsonl")); dls=list(_rows(output/"world_data_layers.jsonl"))
    for x in worlds:
        w=x.get("world_path",""); p=x.get("persistent_level_path","")
        if p:add(w,"world",w,"has_persistent_level","level",p,{"package":x.get("package_name","")})
        p=x.get("world_partition_path","")
        if x.get("world_partitioned") and p:add(w,"world",w,"has_world_partition","world_partition",p)
    for x in levels:
        if x.get("level_kind")!="persistent":
            w=x.get("world_path",""); add(w,"world",w,"streams_world_package","world_package",x.get("target_world_package",""),
                {"streaming_class":x.get("streaming_class",""),"streaming_owner_path":x.get("streaming_owner_path","")})
    for x in actors:
        w=x.get("world_path",""); a=x.get("actor_path","")
        add(w,"world",w,"contains_loaded_actor","actor",a,{"class":x.get("actor_class",""),"guid":x.get("actor_guid","")})
        if x.get("blueprint_asset"):add(w,"actor",a,"instantiates_blueprint","blueprint",x["blueprint_asset"],{"generated_class":x.get("generated_class","")})
        if x.get("attach_parent_actor_path"):add(w,"actor",a,"attached_to_actor","actor",x["attach_parent_actor_path"],{"socket":x.get("attach_parent_socket","")})
        if x.get("owner_actor_path"):add(w,"actor",a,"owned_by_actor","actor",x["owner_actor_path"])
        if x.get("child_actor_parent_path"):add(w,"actor",a,"child_actor_parent","actor",x["child_actor_parent_path"])
        for n in x.get("data_layer_instance_names",[]) or []:
            q=dl.get((w,str(n))); t=q.get("instance_path","") if q else str(n)
            add(w,"actor",a,"member_of_data_layer","data_layer_instance" if q else "data_layer_name",t,{"instance_name":str(n)})
        for t in x.get("data_layer_assets",[]) or []:add(w,"actor",a,"references_data_layer_asset","data_layer_asset",str(t))
    for x in comps:
        w=x.get("world_path",""); a=x.get("actor_path",""); c=x.get("component_path","")
        add(w,"actor",a,"owns_component","component",c,{"class":x.get("component_class","")})
        if x.get("attach_parent_component_path"):add(w,"component",c,"attached_to_component","component",x["attach_parent_component_path"],{"socket":x.get("attach_socket","")})
    for x in refs:
        k=x.get("reference_kind",""); rr={"hard_object":"hard_object_reference","soft_object":"soft_object_reference"}.get(k,"object_reference")
        add(x.get("world_path",""),x.get("owner_kind","object"),x.get("owner_path",""),rr,x.get("target_kind","object"),x.get("target_path",""),
            {"root_property":x.get("root_property",""),"property_path":x.get("property_path",""),"target_class":x.get("target_class",""),
             "reference_kind":k,"authored_override":bool(x.get("authored_override",False))})
    for x in dls:
        w=x.get("world_path",""); p=x.get("instance_path","")
        add(w,"world",w,"contains_data_layer","data_layer_instance",p,{"name":x.get("short_name",""),"runtime":bool(x.get("runtime",False))})
        if x.get("parent_instance_path"):add(w,"data_layer_instance",p,"child_of_data_layer","data_layer_instance",x["parent_instance_path"])
        if x.get("asset_path"):add(w,"data_layer_instance",p,"uses_data_layer_asset","data_layer_asset",x["asset_path"],{"asset_class":x.get("asset_class","")})
    for x in descs:
        w=x.get("world_path",""); s=x.get("actor_soft_path",""); g=x.get("actor_guid","")
        add(w,"world",w,"contains_partition_actor_desc","partition_actor",s,{"guid":g,"package":x.get("actor_package",""),"class":x.get("native_class","")})
        q=loaded.get((w,g))
        if q and q.get("actor_path"):add(w,"partition_actor",s,"describes_loaded_actor","actor",q["actor_path"],{"guid":g})
        pg=x.get("parent_actor_guid","")
        if pg:
            q=dguid.get((w,pg)); add(w,"partition_actor",s,"parent_partition_actor","partition_actor" if q else "partition_actor_guid",q.get("actor_soft_path","") if q else pg,{"target_guid":pg})
        for n in x.get("data_layer_instance_names",[]) or []:
            q=dl.get((w,str(n))); t=q.get("instance_path","") if q else str(n)
            add(w,"partition_actor",s,"member_of_data_layer","data_layer_instance" if q else "data_layer_name",t,{"instance_name":str(n)})
        for rg in x.get("actor_reference_guids",[]) or []:
            rg=str(rg); q=dguid.get((w,rg)); add(w,"partition_actor",s,"references_partition_actor","partition_actor" if q else "partition_actor_guid",q.get("actor_soft_path","") if q else rg,{"target_guid":rg})
    rel.sort(key=lambda x:(x["world_path"],x["source_kind"],x["source_id"],x["relation"],x["target_kind"],x["target"],x["relation_id"]))
    by=lambda seq,key: collections.Counter(str(x.get(key,"")) for x in seq if x.get(key))
    aw=collections.defaultdict(list); cw=collections.defaultdict(list); pw=collections.defaultdict(list); rw=collections.defaultdict(list); lw=collections.defaultdict(list); dw=collections.defaultdict(list)
    for x in actors:aw[x.get("world_path","")].append(x)
    for x in comps:cw[x.get("world_path","")].append(x)
    for x in props:pw[x.get("world_path","")].append(x)
    for x in refs:rw[x.get("world_path","")].append(x)
    for x in levels:lw[x.get("world_path","")].append(x)
    for x in dls:dw[x.get("world_path","")].append(x)
    dd=collections.defaultdict(list); rr=collections.defaultdict(list)
    for x in descs:dd[x.get("world_path","")].append(x)
    for x in rel:rr[x["world_path"]].append(x)
    sums=[]
    for x in worlds:
        w=x.get("world_path",""); la=aw[w]; ds=dd[w]; overlap=len({a.get("actor_guid") for a in la if a.get("actor_guid")} & {d.get("actor_guid") for d in ds if d.get("actor_guid")})
        stream=sum(1 for z in lw[w] if z.get("level_kind")!="persistent")
        rc=collections.Counter(z["relation"] for z in rr[w])
        s={"world_path":w,"world_name":x.get("world_name",""),"package_name":x.get("package_name",""),"persistent_level_path":x.get("persistent_level_path",""),
           "world_partitioned":bool(x.get("world_partitioned",False)),"level_count":len(lw[w]),"streaming_relationship_count":stream,
           "loaded_actor_count":len(la),"partition_actor_desc_count":len(ds),"descriptor_loaded_overlap_count":overlap,"logical_actor_count":len(la)+len(ds)-overlap,
           "component_count":len(cw[w]),"instance_override_count":len(pw[w]),"reference_count":len(rw[w]),"data_layer_count":len(dw[w]),
           "actor_class_counts":dict(sorted(by(la,"actor_class").items())),"partition_actor_class_counts":dict(sorted(by(ds,"native_class").items())),
           "component_class_counts":dict(sorted(by(cw[w],"component_class").items())),"relation_counts":dict(sorted(rc.items()))}
        s["text"]=(f"World: {w}\nPartitioned: {s['world_partitioned']}\nLevels: {s['level_count']} streaming={stream}\n"
                   f"Actors: loaded={len(la)} partition_desc={len(ds)} overlap={overlap} logical={s['logical_actor_count']}\n"
                   f"Components: {len(cw[w])} Overrides: {len(pw[w])} References: {len(rw[w])} DataLayers: {len(dw[w])}\nRelations: {dict(sorted(rc.items()))}")
        sums.append(s)
    sums.sort(key=lambda x:x["world_path"]); sm={x["world_path"]:x for x in sums}; ctx=[]
    for w in sorted(sm):
        s=sm[w]; lines=[s["text"]]
        if dw[w]:
            lines.append("Data Layers:"); lines += [f"  {z.get('instance_name','')} {z.get('short_name','')} asset={z.get('asset_path','')}" for z in sorted(dw[w],key=lambda z:str(z.get("instance_name","")))]
        st=[z for z in lw[w] if z.get("level_kind")!="persistent"]
        if st: lines.append("Streaming:"); lines += [f"  {z.get('streaming_class','')} -> {z.get('target_world_package','')}" for z in st]
        lines.append("Loaded actors:"); lines += [f"  {z.get('actor_label','')} | {z.get('actor_class','')} | {z.get('actor_path','')}" for z in sorted(aw[w],key=lambda z:str(z.get("actor_path","")))]
        if dd[w]: lines.append("Partition descriptors:"); lines += [f"  {z.get('actor_label','')} | {z.get('native_class','')} | {z.get('actor_soft_path','')}" for z in sorted(dd[w],key=lambda z:str(z.get("actor_soft_path","")))]
        text="\n".join(lines); trunc=len(text)>524288
        if trunc:text=text[:524288]+"\n...[truncated]"
        ctx.append({"world_path":w,"world_name":s["world_name"],"world_partitioned":s["world_partitioned"],"loaded_actor_count":s["loaded_actor_count"],
                    "partition_actor_desc_count":s["partition_actor_desc_count"],"logical_actor_count":s["logical_actor_count"],"component_count":s["component_count"],
                    "data_layer_count":s["data_layer_count"],"streaming_relationship_count":s["streaming_relationship_count"],"truncated":trunc,"text":text})
    return rel,ctx,sums

_SQL="""CREATE TABLE world_relations(relation_id TEXT PRIMARY KEY,world_path TEXT NOT NULL,source_kind TEXT NOT NULL,source_id TEXT NOT NULL,relation TEXT NOT NULL,target_kind TEXT NOT NULL,target TEXT NOT NULL,detail_json TEXT NOT NULL);
CREATE INDEX world_relations_world_idx ON world_relations(world_path,relation); CREATE INDEX world_relations_source_idx ON world_relations(source_id,relation); CREATE INDEX world_relations_target_idx ON world_relations(target,relation);
CREATE TABLE world_context(world_path TEXT PRIMARY KEY,world_name TEXT NOT NULL,world_partitioned INTEGER NOT NULL,loaded_actor_count INTEGER NOT NULL,partition_actor_desc_count INTEGER NOT NULL,logical_actor_count INTEGER NOT NULL,component_count INTEGER NOT NULL,data_layer_count INTEGER NOT NULL,streaming_relationship_count INTEGER NOT NULL,truncated INTEGER NOT NULL,text TEXT NOT NULL,json TEXT NOT NULL);
CREATE TABLE world_summaries(world_path TEXT PRIMARY KEY,world_name TEXT NOT NULL,package_name TEXT NOT NULL,persistent_level_path TEXT NOT NULL,world_partitioned INTEGER NOT NULL,level_count INTEGER NOT NULL,streaming_relationship_count INTEGER NOT NULL,loaded_actor_count INTEGER NOT NULL,partition_actor_desc_count INTEGER NOT NULL,descriptor_loaded_overlap_count INTEGER NOT NULL,logical_actor_count INTEGER NOT NULL,component_count INTEGER NOT NULL,instance_override_count INTEGER NOT NULL,reference_count INTEGER NOT NULL,data_layer_count INTEGER NOT NULL,actor_class_counts_json TEXT NOT NULL,partition_actor_class_counts_json TEXT NOT NULL,component_class_counts_json TEXT NOT NULL,relation_counts_json TEXT NOT NULL,text TEXT NOT NULL,json TEXT NOT NULL);"""

_old_schema=core.create_schema; _old_derive=core.derive_output; _old_db=core.build_database; _old_query=core.query; _old_scan=core.scan
def create_schema(c): _old_schema(c); c.executescript(_SQL)
def derive_output(output):
    output=Path(output).expanduser().resolve(); counts=dict(_old_derive(output)); rel,ctx,sums=_derive_world(output)
    wc={"world_relations":_write(output/"world_relations.jsonl",rel),"world_context":_write(output/"world_context.jsonl",ctx),"world_summaries":_write(output/"world_summaries.jsonl",sums)}; counts.update(wc)
    p=output/"manifest.json"
    if p.is_file():
        m=json.loads(p.read_text(encoding="utf-8")); m["derived_schema_version"]=8; d=m.get("derived_counts",{}); d=d if isinstance(d,dict) else {}; d.update(wc); m["derived_counts"]=d
        p.write_text(json.dumps(m,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n")
    return counts
def build_database(output):
    output=Path(output).expanduser().resolve(); db=_old_db(output); c=sqlite3.connect(db)
    try:
        for x in _rows(output/"world_relations.jsonl"): c.execute("INSERT OR REPLACE INTO world_relations VALUES(?,?,?,?,?,?,?,?)",(x.get("relation_id",""),x.get("world_path",""),x.get("source_kind",""),x.get("source_id",""),x.get("relation",""),x.get("target_kind",""),x.get("target",""),json.dumps(x.get("detail",{}),ensure_ascii=False,separators=(",",":"))))
        for x in _rows(output/"world_context.jsonl"): c.execute("INSERT OR REPLACE INTO world_context VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(x.get("world_path",""),x.get("world_name",""),int(bool(x.get("world_partitioned"))),x.get("loaded_actor_count",0),x.get("partition_actor_desc_count",0),x.get("logical_actor_count",0),x.get("component_count",0),x.get("data_layer_count",0),x.get("streaming_relationship_count",0),int(bool(x.get("truncated"))),x.get("text",""),json.dumps(x,ensure_ascii=False,separators=(",",":"))))
        for x in _rows(output/"world_summaries.jsonl"): c.execute("INSERT OR REPLACE INTO world_summaries VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(x.get("world_path",""),x.get("world_name",""),x.get("package_name",""),x.get("persistent_level_path",""),int(bool(x.get("world_partitioned"))),x.get("level_count",0),x.get("streaming_relationship_count",0),x.get("loaded_actor_count",0),x.get("partition_actor_desc_count",0),x.get("descriptor_loaded_overlap_count",0),x.get("logical_actor_count",0),x.get("component_count",0),x.get("instance_override_count",0),x.get("reference_count",0),x.get("data_layer_count",0),json.dumps(x.get("actor_class_counts",{}),separators=(",",":")),json.dumps(x.get("partition_actor_class_counts",{}),separators=(",",":")),json.dumps(x.get("component_class_counts",{}),separators=(",",":")),json.dumps(x.get("relation_counts",{}),separators=(",",":")),x.get("text",""),json.dumps(x,ensure_ascii=False,separators=(",",":"))))
        c.commit()
    finally:c.close()
    return db
def query(a):
    root=Path(a.output).expanduser().resolve(); db=root if root.suffix.lower()==".db" else root/core.DB_NAME; c=sqlite3.connect(db); c.row_factory=sqlite3.Row; q=f"%{a.term}%"
    try:
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_summaries'").fetchone():
            print("[world summaries]"); core._print_rows(c.execute("SELECT world_path,logical_actor_count,data_layer_count,substr(text,1,1200) text FROM world_summaries WHERE world_path LIKE ? OR text LIKE ? LIMIT ?",(q,q,a.limit)),("world_path","logical_actor_count","data_layer_count","text"))
            print("\n[world relations]"); core._print_rows(c.execute("SELECT world_path,source_kind,source_id,relation,target_kind,target FROM world_relations WHERE world_path LIKE ? OR source_id LIKE ? OR relation LIKE ? OR target LIKE ? OR detail_json LIKE ? LIMIT ?",(q,q,q,q,q,a.limit)),("world_path","source_kind","source_id","relation","target_kind","target"))
            print("\n[world context]"); core._print_rows(c.execute("SELECT world_path,world_name,substr(text,1,1600) text FROM world_context WHERE world_path LIKE ? OR world_name LIKE ? OR text LIKE ? LIMIT ?",(q,q,q,a.limit)),("world_path","world_name","text"))
    finally:c.close()
    return int(_old_query(a))
def _summary(a):
    o=Path(a.output).expanduser() if a.output else Path(a.project).expanduser().resolve().parent/".uatool"; o=o.resolve(); p=o/"manifest.json"; wp=o/"world_manifest.json"
    if not(p.is_file() and wp.is_file()):return
    m=json.loads(p.read_text(encoding="utf-8")); w=json.loads(wp.read_text(encoding="utf-8")); d=m.get("derived_counts",{})
    sc=m.get("counts",{}) if isinstance(m.get("counts",{}),dict) else {}; wc=w.get("counts",{}) if isinstance(w.get("counts",{}),dict) else {}
    line=lambda c,n:" ".join(f"{k}={c.get(k,0)}" for k in n)
    print(); print("=== UATOOL FINAL SUMMARY ===")
    print("structural scan complete: "+line(sc,("files","assets","blueprints","blueprint_graphs","blueprint_nodes","blueprint_pins","blueprint_edges")))
    print("world scan complete: "+line(wc,("worlds","levels","streaming_relationships","actors","components","instance_overrides","references","data_layers","world_partition_worlds","world_partition_initialized_for_scan","world_partition_actor_descs")))
    print("derived complete: "+line(d,("world_relations","world_context","world_summaries","blueprint_call_bindings","blueprint_data_dependencies","blueprint_relations","ai_relations","visual_relations")))
    print(f"schemas: structural={m.get('schema_version',0)} world={w.get('schema_version',0)} derived={m.get('derived_schema_version',0)}")
    print(f"database: {o/core.DB_NAME}")
    if not a.no_bundle:
        project=Path(a.project).expanduser().resolve(); print(f"upload bundle: {project.parent / f'{project.stem}.uatool.zip'}")
    print("============================")
def scan(a):
    mute=False; had="print" in core.__dict__; old=core.__dict__.get("print",builtins.print)
    def fp(*v,**kw):
        nonlocal mute
        t=" ".join(map(str,v))
        if not mute and t=="=== UATOOL FINAL SUMMARY ===":mute=True; return
        if mute:
            if t=="============================":mute=False
            return
        return old(*v,**kw)
    core.print=fp
    try:r=int(_old_scan(a))
    finally:
        if had:core.print=old
        else:core.__dict__.pop("print",None)
    if r==0:_summary(a)
    return r

core.create_schema=create_schema; core.derive_output=derive_output; core.build_database=build_database; core.query=query; core.scan=scan
core.DEFAULT_BUNDLE_FILES=tuple(dict.fromkeys((*core.DEFAULT_BUNDLE_FILES,*WORLD_DERIVED_FILES)))
def main(): return int(core.main())
if __name__=="__main__": raise SystemExit(main())
