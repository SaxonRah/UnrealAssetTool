#!/usr/bin/env python3
"""Canonical authored StaticMesh support for independent mesh schema 1.

The focused UE commandlet is an evidence/capture mechanism. This module turns
that bounded capture into the durable corpus contract used by derive, SQLite,
query, capabilities and graph semantics. Structural schema 12 remains unchanged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import uatool_staticmesh_capture as capture

MESH_SCHEMA_VERSION = 1
STATIC_MESH_CLASS = "/Script/Engine.StaticMesh"
MANIFEST_FILE = "staticmesh_manifest.json"
JSONL_FILES = (
    "static_meshes.jsonl",
    "static_mesh_lods.jsonl",
    "static_mesh_material_slots.jsonl",
    "static_mesh_sockets.jsonl",
    "static_mesh_body_setups.jsonl",
    "static_mesh_collision_shapes.jsonl",
)
RAW_FILES = (MANIFEST_FILE, *JSONL_FILES)

_SQL = """
CREATE TABLE static_meshes(
    static_mesh_path TEXT PRIMARY KEY,
    class_path TEXT NOT NULL,
    package_name TEXT NOT NULL,
    lod_count INTEGER NOT NULL,
    material_slot_count INTEGER NOT NULL,
    socket_count INTEGER NOT NULL,
    body_setup_path TEXT NOT NULL,
    collision_shape_count INTEGER NOT NULL,
    complex_collision_mesh_path TEXT NOT NULL,
    nanite_enabled INTEGER NOT NULL,
    lod_group TEXT NOT NULL,
    light_map_coordinate_index TEXT NOT NULL,
    light_map_resolution TEXT NOT NULL,
    authored_settings_json TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX static_meshes_complex_collision_idx ON static_meshes(complex_collision_mesh_path);

CREATE TABLE static_mesh_lods(
    static_mesh_path TEXT NOT NULL,
    lod_index INTEGER NOT NULL,
    screen_size TEXT NOT NULL,
    source_import_filename TEXT NOT NULL,
    import_with_base_mesh TEXT NOT NULL,
    build_settings_json TEXT NOT NULL,
    reduction_settings_json TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(static_mesh_path,lod_index)
);

CREATE TABLE static_mesh_material_slots(
    static_mesh_path TEXT NOT NULL,
    material_index INTEGER NOT NULL,
    material_path TEXT NOT NULL,
    material_class TEXT NOT NULL,
    material_slot_name TEXT NOT NULL,
    imported_material_slot_name TEXT NOT NULL,
    uv_channel_data TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(static_mesh_path,material_index)
);
CREATE INDEX static_mesh_material_slots_target_idx ON static_mesh_material_slots(material_path);

CREATE TABLE static_mesh_sockets(
    static_mesh_path TEXT NOT NULL,
    socket_index INTEGER NOT NULL,
    socket_path TEXT NOT NULL,
    socket_class TEXT NOT NULL,
    socket_name TEXT NOT NULL,
    relative_location TEXT NOT NULL,
    relative_rotation TEXT NOT NULL,
    relative_scale TEXT NOT NULL,
    tag TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(static_mesh_path,socket_index)
);
CREATE UNIQUE INDEX static_mesh_sockets_path_idx ON static_mesh_sockets(socket_path);

CREATE TABLE static_mesh_body_setups(
    static_mesh_path TEXT NOT NULL,
    body_setup_path TEXT PRIMARY KEY,
    body_setup_class TEXT NOT NULL,
    collision_trace_flag TEXT NOT NULL,
    default_instance TEXT NOT NULL,
    phys_material TEXT NOT NULL,
    build_scale3d TEXT NOT NULL,
    walkable_slope_override TEXT NOT NULL,
    double_sided_geometry TEXT NOT NULL,
    never_needs_cooked_collision_data TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE UNIQUE INDEX static_mesh_body_setups_mesh_idx ON static_mesh_body_setups(static_mesh_path);

CREATE TABLE static_mesh_collision_shapes(
    static_mesh_path TEXT NOT NULL,
    body_setup_path TEXT NOT NULL,
    shape_type TEXT NOT NULL,
    shape_index INTEGER NOT NULL,
    shape_struct TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(body_setup_path,shape_type,shape_index)
);
CREATE INDEX static_mesh_collision_shapes_mesh_idx ON static_mesh_collision_shapes(static_mesh_path,shape_type);
"""


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"JSON root is not an object: {path}")
    return value


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield value


def _write_json(path: Path, value: dict) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temp, path)


def _write_jsonl(path: Path, rows: list[dict]) -> int:
    temp = path.with_name(f".{path.name}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(_j(row) + "\n")
    os.replace(temp, path)
    return len(rows)


def _path_key(value: str) -> tuple[str, str]:
    text = str(value or "")
    return (text.casefold(), text)


def _property_payload(row: dict) -> dict:
    result = {
        "property_type": str(row.get("property_type", "")),
        "cpp_type": str(row.get("cpp_type", "")),
        "value": str(row.get("value", "")),
    }
    if isinstance(row.get("fields"), dict):
        result["fields"] = dict(row["fields"])
    if row.get("struct_type"):
        result["struct_type"] = str(row["struct_type"])
    if row.get("target_path"):
        result["target_path"] = str(row["target_path"])
    if row.get("target_class"):
        result["target_class"] = str(row["target_class"])
    return result


def _bool_text(value: object) -> bool:
    return str(value or "").strip().lower() in {"true", "1"}


def _canonical_rows(capture_dir: Path) -> dict[str, list[dict]]:
    assets = list(_rows(capture_dir / "staticmesh_assets.jsonl"))
    source_models = list(_rows(capture_dir / "staticmesh_source_models.jsonl"))
    materials = list(_rows(capture_dir / "staticmesh_materials.jsonl"))
    sockets = list(_rows(capture_dir / "staticmesh_sockets.jsonl"))
    bodies = list(_rows(capture_dir / "staticmesh_body_setups.jsonl"))
    shapes = list(_rows(capture_dir / "staticmesh_collision_shapes.jsonl"))
    properties = list(_rows(capture_dir / "staticmesh_properties.jsonl"))

    properties_by_mesh: dict[str, dict[str, dict]] = {}
    for row in properties:
        mesh = str(row.get("static_mesh_path", ""))
        name = str(row.get("property_name", ""))
        properties_by_mesh.setdefault(mesh, {})[name] = _property_payload(row)

    lod_counts: dict[str, int] = {}
    material_counts: dict[str, int] = {}
    socket_counts: dict[str, int] = {}
    shape_counts: dict[str, int] = {}
    for row in source_models:
        mesh = str(row.get("static_mesh_path", "")); lod_counts[mesh] = lod_counts.get(mesh, 0) + 1
    for row in materials:
        mesh = str(row.get("static_mesh_path", "")); material_counts[mesh] = material_counts.get(mesh, 0) + 1
    for row in sockets:
        mesh = str(row.get("static_mesh_path", "")); socket_counts[mesh] = socket_counts.get(mesh, 0) + 1
    for row in shapes:
        mesh = str(row.get("static_mesh_path", "")); shape_counts[mesh] = shape_counts.get(mesh, 0) + 1

    root_rows: list[dict] = []
    for row in assets:
        mesh = str(row.get("static_mesh_path", ""))
        settings = properties_by_mesh.get(mesh, {})
        nanite = settings.get("NaniteSettings", {})
        nanite_fields = nanite.get("fields", {}) if isinstance(nanite.get("fields"), dict) else {}
        root_rows.append({
            "static_mesh_path": mesh,
            "class_path": str(row.get("class_path", "")),
            "package_name": str(row.get("package_name", "")),
            # SourceModels is canonical. Registry LODs=0 is known to occur on
            # valid one-LOD ContentExamples assets and is provenance only.
            "lod_count": int(lod_counts.get(mesh, 0)),
            "material_slot_count": int(material_counts.get(mesh, 0)),
            "socket_count": int(socket_counts.get(mesh, 0)),
            "body_setup_path": str(row.get("body_setup_path", "")),
            "collision_shape_count": int(shape_counts.get(mesh, 0)),
            "complex_collision_mesh_path": str(row.get("complex_collision_mesh_path", "")),
            "nanite_enabled": _bool_text(nanite_fields.get("bEnabled", "False")),
            "lod_group": str(settings.get("LODGroup", {}).get("value", "")),
            "light_map_coordinate_index": str(settings.get("LightMapCoordinateIndex", {}).get("value", "")),
            "light_map_resolution": str(settings.get("LightMapResolution", {}).get("value", "")),
            "authored_settings": settings,
            "registry_summary": {
                "lod_count": int(row.get("registry_lod_count", 0) or 0),
                "material_count": int(row.get("registry_material_count", 0) or 0),
                "collision_prim_count": int(row.get("registry_collision_prim_count", 0) or 0),
                "nanite_enabled": bool(row.get("registry_nanite_enabled", False)),
            },
        })

    lod_rows: list[dict] = []
    for row in source_models:
        fields = row.get("fields", {}) if isinstance(row.get("fields"), dict) else {}
        lod_rows.append({
            "static_mesh_path": str(row.get("static_mesh_path", "")),
            "lod_index": int(row.get("lod_index", 0) or 0),
            "source_model_struct": str(row.get("source_model_struct", "")),
            "screen_size": str(fields.get("ScreenSize", "")),
            "source_import_filename": str(fields.get("SourceImportFilename", "")),
            "import_with_base_mesh": str(fields.get("bImportWithBaseMesh", "")),
            "build_settings_struct": str(row.get("build_settings_struct", "")),
            "build_settings": dict(row.get("build_settings", {})) if isinstance(row.get("build_settings"), dict) else {},
            "reduction_settings_struct": str(row.get("reduction_settings_struct", "")),
            "reduction_settings": dict(row.get("reduction_settings", {})) if isinstance(row.get("reduction_settings"), dict) else {},
        })

    material_rows = [{
        "static_mesh_path": str(row.get("static_mesh_path", "")),
        "material_index": int(row.get("material_index", 0) or 0),
        "material_path": str(row.get("material_path", "")),
        "material_class": str(row.get("material_class", "")),
        "material_slot_name": str(row.get("material_slot_name", "")),
        "imported_material_slot_name": str(row.get("imported_material_slot_name", "")),
        "uv_channel_data": str(row.get("uv_channel_data", "")),
    } for row in materials]

    socket_rows = [{
        "static_mesh_path": str(row.get("static_mesh_path", "")),
        "socket_index": int(row.get("socket_index", 0) or 0),
        "socket_path": str(row.get("socket_path", "")),
        "socket_class": str(row.get("socket_class", "")),
        "socket_name": str(row.get("socket_name", "")),
        "relative_location": str(row.get("relative_location", "")),
        "relative_rotation": str(row.get("relative_rotation", "")),
        "relative_scale": str(row.get("relative_scale", "")),
        "tag": str(row.get("tag", "")),
    } for row in sockets]

    body_rows = [{
        "static_mesh_path": str(row.get("static_mesh_path", "")),
        "body_setup_path": str(row.get("body_setup_path", "")),
        "body_setup_class": str(row.get("body_setup_class", "")),
        "collision_trace_flag": str(row.get("collision_trace_flag", "")),
        "default_instance": str(row.get("default_instance", "")),
        "phys_material": str(row.get("phys_material", "")),
        "build_scale3d": str(row.get("build_scale3d", "")),
        "walkable_slope_override": str(row.get("walkable_slope_override", "")),
        "double_sided_geometry": str(row.get("double_sided_geometry", "")),
        "never_needs_cooked_collision_data": str(row.get("never_needs_cooked_collision_data", "")),
    } for row in bodies]

    shape_rows = [{
        "static_mesh_path": str(row.get("static_mesh_path", "")),
        "body_setup_path": str(row.get("body_setup_path", "")),
        "shape_type": str(row.get("shape_type", "")),
        "shape_index": int(row.get("shape_index", 0) or 0),
        "shape_struct": str(row.get("shape_struct", "")),
        "fields": dict(row.get("fields", {})) if isinstance(row.get("fields"), dict) else {},
        "raw_value": str(row.get("raw_value", "")),
    } for row in shapes]

    root_rows.sort(key=lambda row: _path_key(row["static_mesh_path"]))
    lod_rows.sort(key=lambda row: (*_path_key(row["static_mesh_path"]), row["lod_index"]))
    material_rows.sort(key=lambda row: (*_path_key(row["static_mesh_path"]), row["material_index"]))
    socket_rows.sort(key=lambda row: (*_path_key(row["static_mesh_path"]), row["socket_index"]))
    body_rows.sort(key=lambda row: (*_path_key(row["static_mesh_path"]), _path_key(row["body_setup_path"])))
    shape_rows.sort(key=lambda row: (*_path_key(row["static_mesh_path"]), _path_key(row["body_setup_path"]), row["shape_type"], row["shape_index"]))
    return {
        "static_meshes.jsonl": root_rows,
        "static_mesh_lods.jsonl": lod_rows,
        "static_mesh_material_slots.jsonl": material_rows,
        "static_mesh_sockets.jsonl": socket_rows,
        "static_mesh_body_setups.jsonl": body_rows,
        "static_mesh_collision_shapes.jsonl": shape_rows,
    }


def promote_capture(corpus: Path, capture_dir: Path) -> dict:
    corpus = Path(corpus).expanduser().resolve()
    capture_dir = Path(capture_dir).expanduser().resolve()
    if not corpus.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {corpus}")
    capture_manifest = capture.validate_capture(capture_dir)
    canonical = _canonical_rows(capture_dir)
    counts = {name.removesuffix(".jsonl"): _write_jsonl(corpus / name, rows) for name, rows in canonical.items()}
    roots = canonical["static_meshes.jsonl"]
    counts["nanite_enabled_static_meshes"] = sum(int(bool(row.get("nanite_enabled", False))) for row in roots)
    counts["multi_lod_static_meshes"] = sum(int(int(row.get("lod_count", 0)) > 1) for row in roots)
    counts["material_references"] = sum(
        int(bool(str(row.get("material_path", "")))) for row in canonical["static_mesh_material_slots.jsonl"]
    )
    counts["complex_collision_mesh_references"] = sum(
        int(bool(str(row.get("complex_collision_mesh_path", "")))) for row in roots
    )

    manifest = {
        "schema_version": MESH_SCHEMA_VERSION,
        "success": True,
        "pass": "UnrealAssetToolStaticMesh",
        "source_capture_schema_version": int(capture_manifest.get("schema_version", 0) or 0),
        "engine_version": str(capture_manifest.get("engine_version", "")),
        "runtime_state_captured": False,
        "render_buffers_captured": False,
        "nanite_resources_captured": False,
        "runtime_physics_state_captured": False,
        "maps_loaded": False,
        "counts": counts,
        "files": list(JSONL_FILES),
        "capture_scope": (
            "authored StaticMesh identity, SourceModels/build/reduction settings, ordered material slots, sockets, "
            "BodySetup/simple AggGeom collision and selected Nanite/section/lightmap/build settings; "
            "render buffers, generated Nanite resources, cooked collision, runtime physics and world instance overrides excluded"
        ),
    }
    _write_json(corpus / MANIFEST_FILE, manifest)

    top_path = corpus / "manifest.json"
    top = _read_json(top_path)
    if top is None:
        raise RuntimeError("manifest.json missing from target corpus")
    top["mesh_schema_version"] = MESH_SCHEMA_VERSION
    top["mesh_counts"] = counts
    top["mesh_files"] = list(JSONL_FILES)
    top["mesh_pass"] = manifest["pass"]
    passes = top.get("canonical_passes", [])
    passes = list(passes) if isinstance(passes, list) else []
    if "mesh" not in passes:
        passes.append("mesh")
    top["canonical_passes"] = passes
    _write_json(top_path, top)
    try:
        import uatool_derived_freshness as freshness
        freshness.invalidate(corpus)
    except Exception:
        pass
    error = validation_error(corpus, require_present=True)
    if error:
        raise RuntimeError(f"promoted StaticMesh mesh schema 1 is invalid: {error}")
    return manifest


def validation_error(output: Path, *, require_present: bool = False) -> str | None:
    output = Path(output)
    manifest = _read_json(output / MANIFEST_FILE)
    if manifest is None:
        return f"{MANIFEST_FILE} missing" if require_present else None
    try:
        if int(manifest.get("schema_version", 0) or 0) != MESH_SCHEMA_VERSION:
            return f"unexpected mesh schema {manifest.get('schema_version')!r}"
        if not bool(manifest.get("success", False)):
            return f"StaticMesh mesh scanner failed: {manifest.get('error', '')}"
        for flag in ("runtime_state_captured", "render_buffers_captured", "nanite_resources_captured", "runtime_physics_state_captured", "maps_loaded"):
            if bool(manifest.get(flag, True)):
                return f"StaticMesh authored boundary violated: {flag}=true"
        for filename in JSONL_FILES:
            if not (output / filename).is_file():
                return f"mesh stream missing: {filename}"

        roots = list(_rows(output / "static_meshes.jsonl"))
        lods = list(_rows(output / "static_mesh_lods.jsonl"))
        materials = list(_rows(output / "static_mesh_material_slots.jsonl"))
        sockets = list(_rows(output / "static_mesh_sockets.jsonl"))
        bodies = list(_rows(output / "static_mesh_body_setups.jsonl"))
        shapes = list(_rows(output / "static_mesh_collision_shapes.jsonl"))
        paths = [str(row.get("static_mesh_path", "")) for row in roots]
        if not paths or paths != sorted(paths, key=_path_key):
            return "StaticMesh canonical identities must be non-empty and deterministically sorted"
        if len({path.casefold() for path in paths}) != len(paths):
            return "StaticMesh canonical identities are not case-insensitively unique"
        if any(str(row.get("class_path", "")) != STATIC_MESH_CLASS for row in roots):
            return "StaticMesh canonical root contains non-StaticMesh class"
        mesh_set = set(paths)

        body_by_mesh: dict[str, str] = {}
        for row in bodies:
            mesh = str(row.get("static_mesh_path", "")); body = str(row.get("body_setup_path", ""))
            if mesh not in mesh_set or not body or mesh in body_by_mesh:
                return "StaticMesh BodySetup identity/owner invariant failed"
            body_by_mesh[mesh] = body
        body_paths = set(body_by_mesh.values())

        def require_owner(rows, label):
            for row in rows:
                if str(row.get("static_mesh_path", "")) not in mesh_set:
                    return f"StaticMesh {label} has unresolved mesh owner"
            return None
        for rows, label in ((lods, "LOD"), (materials, "material slot"), (sockets, "socket"), (shapes, "collision shape")):
            error = require_owner(rows, label)
            if error: return error
        for row in shapes:
            if str(row.get("body_setup_path", "")) not in body_paths:
                return "StaticMesh collision shape has unresolved BodySetup"

        unique_specs = (
            (lods, lambda r: (r.get("static_mesh_path"), int(r.get("lod_index", -1))), "LOD"),
            (materials, lambda r: (r.get("static_mesh_path"), int(r.get("material_index", -1))), "material slot"),
            (sockets, lambda r: (r.get("static_mesh_path"), int(r.get("socket_index", -1))), "socket"),
            (shapes, lambda r: (r.get("body_setup_path"), r.get("shape_type"), int(r.get("shape_index", -1))), "collision shape"),
        )
        for rows, key_fn, label in unique_specs:
            keys = [key_fn(row) for row in rows]
            if len(set(keys)) != len(keys):
                return f"StaticMesh duplicate {label} identity"

        lod_count: dict[str, int] = {}; material_count: dict[str, int] = {}; socket_count: dict[str, int] = {}; shape_count: dict[str, int] = {}
        for row in lods: lod_count[str(row["static_mesh_path"])] = lod_count.get(str(row["static_mesh_path"]), 0) + 1
        for row in materials: material_count[str(row["static_mesh_path"])] = material_count.get(str(row["static_mesh_path"]), 0) + 1
        for row in sockets: socket_count[str(row["static_mesh_path"])] = socket_count.get(str(row["static_mesh_path"]), 0) + 1
        for row in shapes: shape_count[str(row["static_mesh_path"])] = shape_count.get(str(row["static_mesh_path"]), 0) + 1
        for row in roots:
            mesh = str(row["static_mesh_path"])
            if int(row.get("lod_count", 0) or 0) != lod_count.get(mesh, 0): return f"StaticMesh LOD count mismatch: {mesh}"
            if int(row.get("material_slot_count", 0) or 0) != material_count.get(mesh, 0): return f"StaticMesh material-slot count mismatch: {mesh}"
            if int(row.get("socket_count", 0) or 0) != socket_count.get(mesh, 0): return f"StaticMesh socket count mismatch: {mesh}"
            if int(row.get("collision_shape_count", 0) or 0) != shape_count.get(mesh, 0): return f"StaticMesh collision-shape count mismatch: {mesh}"
            body = str(row.get("body_setup_path", ""))
            if bool(body) != bool(body_by_mesh.get(mesh, "")): return f"StaticMesh BodySetup count mismatch: {mesh}"
            settings = row.get("authored_settings", {})
            if not isinstance(settings, dict) or "NaniteSettings" not in settings or "SectionInfoMap" not in settings:
                return f"StaticMesh authored settings incomplete: {mesh}"

        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        physical = {
            "static_meshes": len(roots),
            "static_mesh_lods": len(lods),
            "static_mesh_material_slots": len(materials),
            "static_mesh_sockets": len(sockets),
            "static_mesh_body_setups": len(bodies),
            "static_mesh_collision_shapes": len(shapes),
        }
        for key, actual in physical.items():
            if int(counts.get(key, -1)) != actual:
                return f"mesh schema count mismatch for {key}: manifest={counts.get(key)} actual={actual}"
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        return str(exc)
    return None


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def load_database(conn, output: Path, rows=_rows) -> None:
    output = Path(output)
    for row in rows(output / "static_meshes.jsonl"):
        settings = row.get("authored_settings", {}) if isinstance(row.get("authored_settings"), dict) else {}
        conn.execute("INSERT OR REPLACE INTO static_meshes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            row.get("static_mesh_path", ""), row.get("class_path", ""), row.get("package_name", ""),
            int(row.get("lod_count", 0) or 0), int(row.get("material_slot_count", 0) or 0), int(row.get("socket_count", 0) or 0),
            row.get("body_setup_path", ""), int(row.get("collision_shape_count", 0) or 0), row.get("complex_collision_mesh_path", ""),
            1 if row.get("nanite_enabled", False) else 0, row.get("lod_group", ""), row.get("light_map_coordinate_index", ""),
            row.get("light_map_resolution", ""), _j(settings), _j(row),
        ))
    for row in rows(output / "static_mesh_lods.jsonl"):
        conn.execute("INSERT OR REPLACE INTO static_mesh_lods VALUES (?,?,?,?,?,?,?,?)", (
            row.get("static_mesh_path", ""), int(row.get("lod_index", 0) or 0), row.get("screen_size", ""),
            row.get("source_import_filename", ""), row.get("import_with_base_mesh", ""), _j(row.get("build_settings", {})),
            _j(row.get("reduction_settings", {})), _j(row),
        ))
    for row in rows(output / "static_mesh_material_slots.jsonl"):
        conn.execute("INSERT OR REPLACE INTO static_mesh_material_slots VALUES (?,?,?,?,?,?,?,?)", (
            row.get("static_mesh_path", ""), int(row.get("material_index", 0) or 0), row.get("material_path", ""),
            row.get("material_class", ""), row.get("material_slot_name", ""), row.get("imported_material_slot_name", ""),
            row.get("uv_channel_data", ""), _j(row),
        ))
    for row in rows(output / "static_mesh_sockets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO static_mesh_sockets VALUES (?,?,?,?,?,?,?,?,?,?)", (
            row.get("static_mesh_path", ""), int(row.get("socket_index", 0) or 0), row.get("socket_path", ""), row.get("socket_class", ""),
            row.get("socket_name", ""), row.get("relative_location", ""), row.get("relative_rotation", ""), row.get("relative_scale", ""),
            row.get("tag", ""), _j(row),
        ))
    for row in rows(output / "static_mesh_body_setups.jsonl"):
        conn.execute("INSERT OR REPLACE INTO static_mesh_body_setups VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
            row.get("static_mesh_path", ""), row.get("body_setup_path", ""), row.get("body_setup_class", ""), row.get("collision_trace_flag", ""),
            row.get("default_instance", ""), row.get("phys_material", ""), row.get("build_scale3d", ""), row.get("walkable_slope_override", ""),
            row.get("double_sided_geometry", ""), row.get("never_needs_cooked_collision_data", ""), _j(row),
        ))
    for row in rows(output / "static_mesh_collision_shapes.jsonl"):
        conn.execute("INSERT OR REPLACE INTO static_mesh_collision_shapes VALUES (?,?,?,?,?,?,?,?)", (
            row.get("static_mesh_path", ""), row.get("body_setup_path", ""), row.get("shape_type", ""), int(row.get("shape_index", 0) or 0),
            row.get("shape_struct", ""), _j(row.get("fields", {})), row.get("raw_value", ""), _j(row),
        ))


def query(conn, print_rows, term: str, limit: int) -> None:
    print("\n[StaticMesh]")
    rows = conn.execute(
        "SELECT static_mesh_path,lod_count,material_slot_count,socket_count,collision_shape_count,nanite_enabled,lod_group "
        "FROM static_meshes WHERE static_mesh_path LIKE ? OR lod_group LIKE ? OR authored_settings_json LIKE ? LIMIT ?",
        (term, term, term, limit),
    )
    print_rows(rows, ("static_mesh_path", "lod_count", "material_slot_count", "socket_count", "collision_shape_count", "nanite_enabled", "lod_group"))
    print("\n[StaticMesh material slots]")
    rows = conn.execute(
        "SELECT static_mesh_path,material_index,material_slot_name,material_path FROM static_mesh_material_slots "
        "WHERE static_mesh_path LIKE ? OR material_slot_name LIKE ? OR material_path LIKE ? LIMIT ?",
        (term, term, term, limit),
    )
    print_rows(rows, ("static_mesh_path", "material_index", "material_slot_name", "material_path"))
    print("\n[StaticMesh sockets/collision]")
    rows = conn.execute(
        "SELECT static_mesh_path,socket_index,socket_name,socket_path FROM static_mesh_sockets "
        "WHERE static_mesh_path LIKE ? OR socket_name LIKE ? OR socket_path LIKE ? LIMIT ?",
        (term, term, term, limit),
    )
    print_rows(rows, ("static_mesh_path", "socket_index", "socket_name", "socket_path"))
    rows = conn.execute(
        "SELECT static_mesh_path,shape_type,shape_index,body_setup_path FROM static_mesh_collision_shapes "
        "WHERE static_mesh_path LIKE ? OR shape_type LIKE ? OR body_setup_path LIKE ? LIMIT ?",
        (term, term, term, limit),
    )
    print_rows(rows, ("static_mesh_path", "shape_type", "shape_index", "body_setup_path"))
