#!/usr/bin/env python3
"""First-class capability contract for world-geometry schema 1."""
from __future__ import annotations
from pathlib import Path
import uatool_world_geometry_schema as schema
import uatool_world_geometry_graph as graph

BOUNDARY=(
    "Authored Landscape/Foliage/HLOD semantics: exact Landscape and streaming-proxy identities, component ownership, "
    "heightmap/weightmap texture references, weightmap layer allocations and LayerInfo targets, LandscapeGrassType varieties, "
    "FoliageType settings/mesh refs, painted InstancedFoliageActor FFoliageInfo/FFoliageInstance editor placement, and HLODLayer policy/parent/builder refs. "
    "Heightfield/render buffers, runtime grass/foliage clusters, HISM render-instance substitution, generated HLOD proxy geometry, "
    "World Partition runtime streaming state and map loading are excluded."
)
def _upsert(families,row):
    for i,existing in enumerate(families):
        if isinstance(existing,dict) and existing.get("family")==row["family"]: families[i]=row; return
    families.append(row)
def _acceptance(capabilities_module,output):
    accepted=capabilities_module._read_json(output/"world_geometry_schema1_acceptance.json")
    verified=capabilities_module._read_json(output/"world_geometry_schema1_graph_verification.json")
    return {"accepted":bool(accepted) and int(accepted.get("world_geometry_schema_version",0) or 0)==schema.WORLD_GEOMETRY_SCHEMA_VERSION,"verification":bool(verified.get("verified",False)) and int(verified.get("derived_schema_version",0) or 0)==graph.TARGET_DERIVED_SCHEMA_VERSION,"representative_content":str(accepted.get("representative_content","")),"runtime_state_captured":bool(accepted.get("runtime_state_captured",False))}
def install(capabilities_module):
    if getattr(capabilities_module,"_world_geometry_schema1_capabilities_installed",False): return
    original=capabilities_module.build_manifest
    def build_manifest(output: Path):
        output=Path(output).expanduser().resolve(); manifest=original(output); sidecar=capabilities_module._read_json(output/schema.MANIFEST_FILE); files=set(capabilities_module._manifest_files(sidecar))
        schemas=manifest.get("schemas",{}) if isinstance(manifest.get("schemas"),dict) else {}; schemas["world_geometry"]=int(sidecar.get("schema_version",0) or 0) if sidecar else 0; manifest["schemas"]=schemas
        available=bool(sidecar) and bool(sidecar.get("success",True)) and int(sidecar.get("schema_version",0) or 0)==schema.WORLD_GEOMETRY_SCHEMA_VERSION and all(name in files for name in schema.JSONL_FILES)
        row={"family":"world_geometry","contract_coverage":"first_class","corpus_coverage":"first_class" if available else "external_or_excluded","available_in_corpus":bool(available),"canonical_pass":"world_geometry","canonical_streams":sorted(name for name in schema.JSONL_FILES if name in files),"derived_streams":["project_nodes.jsonl","project_edges.jsonl"],"derived_relations":sorted(graph.RELATIONS),"runtime_state_captured":False,"boundary":BOUNDARY,"acceptance":_acceptance(capabilities_module,output)}
        families=manifest.get("families",[]); families=list(families) if isinstance(families,list) else []; _upsert(families,row); manifest["families"]=families
        passes=manifest.get("canonical_passes",[]); passes=list(passes) if isinstance(passes,list) else []
        if available and "world_geometry" not in passes: passes.append("world_geometry")
        manifest["canonical_passes"]=passes; return manifest
    capabilities_module.build_manifest=build_manifest; capabilities_module._world_geometry_schema1_capabilities_installed=True
