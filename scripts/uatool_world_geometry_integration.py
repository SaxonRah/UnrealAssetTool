#!/usr/bin/env python3
"""Canonical composition for independent world-geometry schema 1."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import uatool_world_geometry_schema as geometry_schema
import uatool_world_geometry_graph as geometry_graph
import uatool_world_geometry_accept as geometry_accept
import uatool_world_geometry_capabilities as geometry_capabilities
import uatool_project_graph as project_graph
import uatool_capabilities as capabilities
import uatool_build_perf as build_perf

AUTO_CAPTURE_DIR = "world-geometry-native-capture"

def _read_json(path: Path) -> dict | None:
    try: value=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError): return None
    return value if isinstance(value,dict) else None

def _clear_canonical(output: Path) -> None:
    output=Path(output)
    for filename in geometry_schema.RAW_FILES: (output/filename).unlink(missing_ok=True)
    top_path=output/"manifest.json"; top=_read_json(top_path)
    if top is not None:
        for key in ("world_geometry_schema_version","world_geometry_counts","world_geometry_files","world_geometry_pass"): top.pop(key,None)
        passes=top.get("canonical_passes",[])
        if isinstance(passes,list): top["canonical_passes"]=[v for v in passes if v!="world_geometry"]
        temp=top_path.with_name(f".{top_path.name}.tmp"); temp.write_text(json.dumps(top,ensure_ascii=False,indent=2)+"\n",encoding="utf-8",newline="\n"); temp.replace(top_path)
    try:
        import uatool_derived_freshness as freshness
        freshness.invalidate(output)
    except Exception: pass

def _promote_pending_capture(output: Path) -> bool:
    output=Path(output).expanduser().resolve(); capture_dir=output/AUTO_CAPTURE_DIR; manifest_path=capture_dir/"world_geometry_capture_manifest.json"
    if not manifest_path.is_file(): return (output/geometry_schema.MANIFEST_FILE).is_file()
    capture_manifest=_read_json(manifest_path)
    if capture_manifest is None: raise RuntimeError("normal world-geometry pass wrote an invalid capture manifest")
    if not bool(capture_manifest.get("success",False)): raise RuntimeError(f"normal world-geometry pass failed: {capture_manifest.get('error','')}")
    counts=capture_manifest.get("counts",{}); counts=counts if isinstance(counts,dict) else {}
    if int(counts.get("load_failures",-1))!=0: raise RuntimeError("normal world-geometry pass reports asset load failures")
    if int(counts.get("registry_candidates",0) or 0)==0:
        _clear_canonical(output); shutil.rmtree(capture_dir); print("world-geometry pass: project contains no Landscape/Foliage/HLOD candidates; stale facts cleared"); return False
    manifest=geometry_schema.promote_capture(output,capture_dir); shutil.rmtree(capture_dir); c=manifest.get("counts",{}) if isinstance(manifest.get("counts"),dict) else {}
    print("world-geometry schema 1 promoted: " f"landscapes={c.get('world_geometry_landscapes',0)} components={c.get('world_geometry_landscape_components',0)} " f"foliage_infos={c.get('world_geometry_foliage_infos',0)} foliage_instances={c.get('world_geometry_foliage_instances',0)} hlod_layers={c.get('world_geometry_hlod_layers',0)}")
    return True

def install(runtime_module, core_module) -> None:
    if getattr(runtime_module,"_world_geometry_schema1_integration_installed",False):
        geometry_graph.promote_public_derived_version(project_graph,core_module,runtime_module); return
    geometry_graph.install(project_graph,core_module,runtime_module); geometry_accept.install(runtime_module); geometry_capabilities.install(capabilities)
    if not getattr(build_perf,"_world_geometry_schema31_composition_installed",False):
        original_build_perf_install=build_perf.install
        def build_perf_install_with_schema31(core) -> None:
            original_build_perf_install(core); geometry_graph.install(project_graph,core,runtime_module); geometry_graph.promote_public_derived_version(project_graph,core,runtime_module)
        build_perf.install=build_perf_install_with_schema31; build_perf._world_geometry_schema31_composition_installed=True
    original_create_schema=core_module.create_schema; original_derive_output=core_module.derive_output; original_build_database=core_module.build_database; original_query=core_module.query; original_scan=core_module.scan
    def create_schema(conn) -> None:
        original_create_schema(conn); exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_geometry_landscapes'").fetchone()
        if not exists: geometry_schema.create_schema(conn)
    def derive_output(output):
        output=Path(output).expanduser().resolve(); _promote_pending_capture(output); error=geometry_schema.validation_error(output,require_present=False)
        if error: raise RuntimeError(f"world-geometry schema 1 incomplete: {error}")
        geometry_graph.promote_public_derived_version(project_graph,core_module,runtime_module); return original_derive_output(output)
    def build_database(output):
        output=Path(output).expanduser().resolve(); _promote_pending_capture(output); error=geometry_schema.validation_error(output,require_present=False)
        if error: raise RuntimeError(f"world-geometry schema 1 incomplete: {error}")
        db=original_build_database(output)
        if (output/geometry_schema.MANIFEST_FILE).is_file():
            conn=sqlite3.connect(db)
            try:
                exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_geometry_landscapes'").fetchone()
                if not exists: geometry_schema.create_schema(conn)
                geometry_schema.load_database(conn,output,runtime_module._rows); conn.commit()
            finally: conn.close()
        return db
    def query(args):
        result=int(original_query(args)); root=Path(args.output).expanduser().resolve(); db=root if root.suffix.lower()==".db" else root/core_module.DB_NAME
        if not db.is_file(): return result
        conn=sqlite3.connect(db); conn.row_factory=sqlite3.Row
        try:
            exists=conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='world_geometry_landscapes'").fetchone()
            if exists: geometry_schema.query(conn,core_module._print_rows,f"%{args.term}%",args.limit)
        finally: conn.close()
        return result
    def scan(args):
        result=int(original_scan(args))
        if result!=0: return result
        output=(Path(args.output).expanduser() if getattr(args,"output",None) else Path(args.project).expanduser().resolve().parent/".uatool").resolve()
        if (output/AUTO_CAPTURE_DIR).exists(): print("ERROR: world-geometry normal-scan capture survived derive; canonical promotion did not run",file=__import__("sys").stderr); return 27
        error=geometry_schema.validation_error(output,require_present=False)
        if error: print(f"ERROR: world-geometry schema 1 incomplete: {error}",file=__import__("sys").stderr); return 27
        manifest=_read_json(output/geometry_schema.MANIFEST_FILE)
        if manifest is not None:
            c=manifest.get("counts",{}) if isinstance(manifest.get("counts"),dict) else {}
            print("world-geometry scan complete: " f"landscapes={c.get('world_geometry_landscapes',0)} components={c.get('world_geometry_landscape_components',0)} allocations={c.get('world_geometry_landscape_layer_allocations',0)} foliage_instances={c.get('world_geometry_foliage_instances',0)} hlod_layers={c.get('world_geometry_hlod_layers',0)}")
        return 0
    runtime_module.create_schema=create_schema; runtime_module.derive_output=derive_output; runtime_module.build_database=build_database; runtime_module.query=query; runtime_module.scan=scan
    core_module.create_schema=create_schema; core_module.derive_output=derive_output; core_module.build_database=build_database; core_module.query=query; core_module.scan=scan
    core_module.DEFAULT_BUNDLE_FILES=tuple(dict.fromkeys((*core_module.DEFAULT_BUNDLE_FILES,*geometry_schema.RAW_FILES)))
    runtime_module._world_geometry_schema1_integration_installed=True
