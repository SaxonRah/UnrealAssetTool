#!/usr/bin/env python3
"""Normalized authored SkeletalMesh / PhysicsAsset support for public animation schema 3."""
from __future__ import annotations

import json
from pathlib import Path

MESH_PHYSICS_SCHEMA_VERSION = 1
PUBLIC_ANIMATION_SCHEMA_VERSION = 3

JSONL_FILES = (
    "skeletal_meshes.jsonl",
    "skeletal_mesh_lods.jsonl",
    "skeletal_mesh_materials.jsonl",
    "skeletal_mesh_morph_targets.jsonl",
    "skeletal_mesh_clothing_assets.jsonl",
    "skeletal_mesh_clothing_configs.jsonl",
    "physics_assets.jsonl",
    "physics_bodies.jsonl",
    "physics_body_shapes.jsonl",
    "physics_constraints.jsonl",
    "physics_constraint_profiles.jsonl",
    "physics_physical_animation_profiles.jsonl",
    "physics_collision_disable_pairs.jsonl",
)
RAW_FILES = ("animation_mesh_physics_manifest.json", *JSONL_FILES)

_SQL = """
CREATE TABLE skeletal_meshes(
    skeletal_mesh_path TEXT PRIMARY KEY,
    class_path TEXT NOT NULL,
    package_name TEXT NOT NULL,
    skeleton_path TEXT NOT NULL,
    physics_asset_path TEXT NOT NULL,
    shadow_physics_asset_path TEXT NOT NULL,
    lod_settings_path TEXT NOT NULL,
    bone_count INTEGER NOT NULL,
    lod_count INTEGER NOT NULL,
    material_count INTEGER NOT NULL,
    morph_target_count INTEGER NOT NULL,
    clothing_asset_count INTEGER NOT NULL,
    mesh_socket_count INTEGER NOT NULL,
    nanite_enabled TEXT NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX skeletal_meshes_skeleton_idx ON skeletal_meshes(skeleton_path);
CREATE INDEX skeletal_meshes_physics_idx ON skeletal_meshes(physics_asset_path);

CREATE TABLE skeletal_mesh_lods(
    skeletal_mesh_path TEXT NOT NULL,
    lod_index INTEGER NOT NULL,
    source_model_struct TEXT NOT NULL,
    build_settings_json TEXT NOT NULL,
    reduction_settings_json TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(skeletal_mesh_path,lod_index)
);

CREATE TABLE skeletal_mesh_materials(
    skeletal_mesh_path TEXT NOT NULL,
    material_index INTEGER NOT NULL,
    material_path TEXT NOT NULL,
    material_class TEXT NOT NULL,
    material_slot_name TEXT NOT NULL,
    imported_material_slot_name TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(skeletal_mesh_path,material_index)
);
CREATE INDEX skeletal_mesh_materials_target_idx ON skeletal_mesh_materials(material_path);

CREATE TABLE skeletal_mesh_morph_targets(
    skeletal_mesh_path TEXT NOT NULL,
    morph_index INTEGER NOT NULL,
    morph_target_path TEXT NOT NULL,
    object_name TEXT NOT NULL,
    class_path TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(skeletal_mesh_path,morph_index)
);
CREATE INDEX skeletal_mesh_morph_targets_target_idx ON skeletal_mesh_morph_targets(morph_target_path);

CREATE TABLE skeletal_mesh_clothing_assets(
    skeletal_mesh_path TEXT NOT NULL,
    clothing_index INTEGER NOT NULL,
    clothing_asset_path TEXT NOT NULL,
    clothing_asset_name TEXT NOT NULL,
    class_path TEXT NOT NULL,
    physics_asset_path TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(skeletal_mesh_path,clothing_index)
);
CREATE INDEX skeletal_mesh_clothing_target_idx ON skeletal_mesh_clothing_assets(clothing_asset_path);

CREATE TABLE skeletal_mesh_clothing_configs(
    skeletal_mesh_path TEXT NOT NULL,
    clothing_asset_path TEXT NOT NULL,
    config_index INTEGER NOT NULL,
    config_path TEXT NOT NULL,
    config_class TEXT NOT NULL,
    properties_json TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(clothing_asset_path,config_index)
);
CREATE INDEX skeletal_mesh_clothing_configs_class_idx ON skeletal_mesh_clothing_configs(config_class);

CREATE TABLE physics_assets(
    physics_asset_path TEXT PRIMARY KEY,
    class_path TEXT NOT NULL,
    package_name TEXT NOT NULL,
    preview_skeletal_mesh_path TEXT NOT NULL,
    body_count INTEGER NOT NULL,
    constraint_count INTEGER NOT NULL,
    constraint_profile_count INTEGER NOT NULL,
    physical_animation_profile_count INTEGER NOT NULL,
    json TEXT NOT NULL
);
CREATE INDEX physics_assets_preview_mesh_idx ON physics_assets(preview_skeletal_mesh_path);

CREATE TABLE physics_bodies(
    physics_asset_path TEXT NOT NULL,
    body_index INTEGER NOT NULL,
    body_path TEXT NOT NULL,
    body_class TEXT NOT NULL,
    bone_name TEXT NOT NULL,
    physics_type TEXT NOT NULL,
    collision_response TEXT NOT NULL,
    authored_properties_json TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(physics_asset_path,body_index)
);
CREATE INDEX physics_bodies_bone_idx ON physics_bodies(bone_name,physics_asset_path);
CREATE UNIQUE INDEX physics_bodies_path_idx ON physics_bodies(body_path);

CREATE TABLE physics_body_shapes(
    physics_asset_path TEXT NOT NULL,
    body_index INTEGER NOT NULL,
    body_path TEXT NOT NULL,
    shape_type TEXT NOT NULL,
    shape_index INTEGER NOT NULL,
    shape_struct TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    raw_value TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(physics_asset_path,body_index,shape_type,shape_index)
);
CREATE INDEX physics_body_shapes_body_idx ON physics_body_shapes(body_path,shape_type);

CREATE TABLE physics_constraints(
    physics_asset_path TEXT NOT NULL,
    constraint_index INTEGER NOT NULL,
    constraint_path TEXT NOT NULL,
    constraint_class TEXT NOT NULL,
    joint_name TEXT NOT NULL,
    constraint_bone1 TEXT NOT NULL,
    constraint_bone2 TEXT NOT NULL,
    default_instance_json TEXT NOT NULL,
    profile_instance_json TEXT NOT NULL,
    profile_handles TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(physics_asset_path,constraint_index)
);
CREATE INDEX physics_constraints_bones_idx ON physics_constraints(constraint_bone1,constraint_bone2);
CREATE UNIQUE INDEX physics_constraints_path_idx ON physics_constraints(constraint_path);

CREATE TABLE physics_constraint_profiles(
    physics_asset_path TEXT NOT NULL,
    profile_index INTEGER NOT NULL,
    profile_name TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(physics_asset_path,profile_index)
);
CREATE INDEX physics_constraint_profiles_name_idx ON physics_constraint_profiles(profile_name);

CREATE TABLE physics_physical_animation_profiles(
    physics_asset_path TEXT NOT NULL,
    profile_index INTEGER NOT NULL,
    profile_name TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(physics_asset_path,profile_index)
);
CREATE INDEX physics_physical_animation_profiles_name_idx ON physics_physical_animation_profiles(profile_name);

CREATE TABLE physics_collision_disable_pairs(
    physics_asset_path TEXT NOT NULL,
    pair_index INTEGER NOT NULL,
    key_text TEXT NOT NULL,
    value_text TEXT NOT NULL,
    key_fields_json TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(physics_asset_path,pair_index)
);
"""


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


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


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def _count_rows(output: Path, filename: str) -> int:
    return sum(1 for _ in _rows(output / filename))


def validation_error(output: Path, *, require_present: bool = False) -> str | None:
    output = Path(output)
    manifest_path = output / "animation_mesh_physics_manifest.json"
    if not manifest_path.is_file():
        return "animation_mesh_physics_manifest.json missing" if require_present else None
    try:
        manifest = _read_json(manifest_path)
        if manifest is None:
            return "animation_mesh_physics_manifest.json missing"
        if int(manifest.get("schema_version", 0) or 0) != MESH_PHYSICS_SCHEMA_VERSION:
            return f"unexpected mesh/physics schema {manifest.get('schema_version')!r}"
        if int(manifest.get("public_animation_schema_version", 0) or 0) != PUBLIC_ANIMATION_SCHEMA_VERSION:
            return f"unexpected mesh/physics public animation schema {manifest.get('public_animation_schema_version')!r}"
        if not bool(manifest.get("success", False)):
            return f"mesh/physics scanner failed: {manifest.get('error', '')}"
        for flag in (
            "runtime_state_captured", "render_buffers_captured", "cloth_simulation_state_captured",
            "chaos_runtime_state_captured", "maps_loaded",
        ):
            if bool(manifest.get(flag, True)):
                return f"mesh/physics authored boundary violated: {flag}=true"

        for filename in JSONL_FILES:
            if not (output / filename).is_file():
                return f"mesh/physics stream missing: {filename}"

        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        for filename in JSONL_FILES:
            key = filename.removesuffix(".jsonl")
            actual = _count_rows(output, filename)
            if int(counts.get(key, -1)) != actual:
                return f"mesh/physics count mismatch for {key}: manifest={counts.get(key)} actual={actual}"

        meshes = list(_rows(output / "skeletal_meshes.jsonl"))
        physics_assets = list(_rows(output / "physics_assets.jsonl"))
        mesh_paths = [str(r.get("skeletal_mesh_path", "")) for r in meshes]
        physics_paths = [str(r.get("physics_asset_path", "")) for r in physics_assets]
        if mesh_paths != sorted(set(mesh_paths)):
            return "skeletal_meshes identities must be unique and sorted"
        if physics_paths != sorted(set(physics_paths)):
            return "physics_assets identities must be unique and sorted"
        mesh_set = set(mesh_paths)
        physics_set = set(physics_paths)

        lods = list(_rows(output / "skeletal_mesh_lods.jsonl"))
        materials = list(_rows(output / "skeletal_mesh_materials.jsonl"))
        morphs = list(_rows(output / "skeletal_mesh_morph_targets.jsonl"))
        clothing = list(_rows(output / "skeletal_mesh_clothing_assets.jsonl"))
        configs = list(_rows(output / "skeletal_mesh_clothing_configs.jsonl"))
        bodies = list(_rows(output / "physics_bodies.jsonl"))
        shapes = list(_rows(output / "physics_body_shapes.jsonl"))
        constraints = list(_rows(output / "physics_constraints.jsonl"))
        constraint_profiles = list(_rows(output / "physics_constraint_profiles.jsonl"))
        physical_profiles = list(_rows(output / "physics_physical_animation_profiles.jsonl"))
        collision_pairs = list(_rows(output / "physics_collision_disable_pairs.jsonl"))

        for family, rows in (("lod", lods), ("material", materials), ("morph", morphs), ("clothing", clothing)):
            for row in rows:
                if str(row.get("skeletal_mesh_path", "")) not in mesh_set:
                    return f"{family} row has unresolved SkeletalMesh"
        clothing_paths = {str(r.get("clothing_asset_path", "")) for r in clothing}
        for row in configs:
            if str(row.get("skeletal_mesh_path", "")) not in mesh_set or str(row.get("clothing_asset_path", "")) not in clothing_paths:
                return "clothing config has unresolved owner"

        body_keys = set()
        body_paths = set()
        for row in bodies:
            asset = str(row.get("physics_asset_path", ""))
            key = (asset, int(row.get("body_index", -1)))
            path = str(row.get("body_path", ""))
            if asset not in physics_set or key in body_keys or not path or path in body_paths:
                return "physics body identity/owner invariant failed"
            body_keys.add(key); body_paths.add(path)
        for row in shapes:
            key = (str(row.get("physics_asset_path", "")), int(row.get("body_index", -1)))
            if key not in body_keys or str(row.get("body_path", "")) not in body_paths:
                return "physics shape has unresolved body"

        constraint_keys = set()
        constraint_paths = set()
        for row in constraints:
            asset = str(row.get("physics_asset_path", ""))
            key = (asset, int(row.get("constraint_index", -1)))
            path = str(row.get("constraint_path", ""))
            if asset not in physics_set or key in constraint_keys or not path or path in constraint_paths:
                return "physics constraint identity/owner invariant failed"
            constraint_keys.add(key); constraint_paths.add(path)
        for family, rows in (("constraint profile", constraint_profiles), ("physical animation profile", physical_profiles), ("collision pair", collision_pairs)):
            for row in rows:
                if str(row.get("physics_asset_path", "")) not in physics_set:
                    return f"{family} has unresolved PhysicsAsset"

        lod_count = {}
        material_count = {}
        morph_count = {}
        clothing_count = {}
        body_count = {}
        constraint_count = {}
        for row in lods: lod_count[str(row["skeletal_mesh_path"])] = lod_count.get(str(row["skeletal_mesh_path"]), 0) + 1
        for row in materials: material_count[str(row["skeletal_mesh_path"])] = material_count.get(str(row["skeletal_mesh_path"]), 0) + 1
        for row in morphs: morph_count[str(row["skeletal_mesh_path"])] = morph_count.get(str(row["skeletal_mesh_path"]), 0) + 1
        for row in clothing: clothing_count[str(row["skeletal_mesh_path"])] = clothing_count.get(str(row["skeletal_mesh_path"]), 0) + 1
        for row in bodies: body_count[str(row["physics_asset_path"])] = body_count.get(str(row["physics_asset_path"]), 0) + 1
        for row in constraints: constraint_count[str(row["physics_asset_path"])] = constraint_count.get(str(row["physics_asset_path"]), 0) + 1
        for row in meshes:
            path = str(row["skeletal_mesh_path"])
            if int(row.get("source_model_count", 0) or 0) != lod_count.get(path, 0): return f"SkeletalMesh LOD count mismatch: {path}"
            if int(row.get("material_count", 0) or 0) != material_count.get(path, 0): return f"SkeletalMesh material count mismatch: {path}"
            if int(row.get("morph_target_count", 0) or 0) != morph_count.get(path, 0): return f"SkeletalMesh morph count mismatch: {path}"
            if int(row.get("clothing_asset_count", 0) or 0) != clothing_count.get(path, 0): return f"SkeletalMesh clothing count mismatch: {path}"
        for row in physics_assets:
            path = str(row["physics_asset_path"])
            if int(row.get("body_count", 0) or 0) != body_count.get(path, 0): return f"PhysicsAsset body count mismatch: {path}"
            if int(row.get("constraint_count", 0) or 0) != constraint_count.get(path, 0): return f"PhysicsAsset constraint count mismatch: {path}"
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        return str(exc)
    return None


def normalize_output(output: Path) -> bool:
    """Compose sidecar schema 1 into public animation schema 3 when present."""
    output = Path(output)
    sidecar = _read_json(output / "animation_mesh_physics_manifest.json")
    if sidecar is None:
        return False
    error = validation_error(output, require_present=True)
    if error:
        raise RuntimeError(error)
    manifest_path = output / "animation_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest is None:
        raise RuntimeError("animation_manifest.json missing while composing mesh/physics schema")
    schema = int(manifest.get("schema_version", 0) or 0)
    if schema != 2 and schema < PUBLIC_ANIMATION_SCHEMA_VERSION:
        raise RuntimeError(f"cannot compose mesh/physics with animation schema {schema}")
    counts = manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    side_counts = sidecar.get("counts", {})
    if isinstance(side_counts, dict):
        counts.update({str(k): int(v) for k, v in side_counts.items()})
    manifest["counts"] = counts
    files = [str(v) for v in (manifest.get("files", []) or [])]
    for filename in JSONL_FILES:
        if filename not in files:
            files.append(filename)
    manifest["files"] = files
    manifest["schema_version"] = max(schema, PUBLIC_ANIMATION_SCHEMA_VERSION)
    manifest["mesh_physics_schema_version"] = MESH_PHYSICS_SCHEMA_VERSION
    manifest["mesh_physics_pass"] = sidecar.get("pass", "UnrealAssetToolAnimationMeshPhysics")
    manifest["runtime_state_captured"] = False
    text = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    if not manifest_path.is_file() or manifest_path.read_text(encoding="utf-8") != text:
        manifest_path.write_text(text, encoding="utf-8", newline="\n")
    return True


def load_database(conn, output: Path, rows) -> None:
    output = Path(output)
    for row in rows(output / "skeletal_meshes.jsonl"):
        conn.execute("INSERT OR REPLACE INTO skeletal_meshes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            row.get("skeletal_mesh_path", ""), row.get("class_path", ""), row.get("package_name", ""),
            row.get("skeleton_path", ""), row.get("physics_asset_path", ""), row.get("shadow_physics_asset_path", ""),
            row.get("lod_settings_path", ""), int(row.get("bone_count", 0) or 0), int(row.get("lod_count", 0) or 0),
            int(row.get("material_count", 0) or 0), int(row.get("morph_target_count", 0) or 0),
            int(row.get("clothing_asset_count", 0) or 0), int(row.get("mesh_socket_count", 0) or 0),
            str(row.get("nanite_enabled", "")), _j(row)))
    for row in rows(output / "skeletal_mesh_lods.jsonl"):
        conn.execute("INSERT OR REPLACE INTO skeletal_mesh_lods VALUES(?,?,?,?,?,?)", (
            row.get("skeletal_mesh_path", ""), int(row.get("lod_index", 0)), row.get("source_model_struct", ""),
            _j(row.get("build_settings", {})), _j(row.get("reduction_settings", {})), _j(row)))
    for row in rows(output / "skeletal_mesh_materials.jsonl"):
        conn.execute("INSERT OR REPLACE INTO skeletal_mesh_materials VALUES(?,?,?,?,?,?,?)", (
            row.get("skeletal_mesh_path", ""), int(row.get("material_index", 0)), row.get("material_path", ""),
            row.get("material_class", ""), row.get("material_slot_name", ""), row.get("imported_material_slot_name", ""), _j(row)))
    for row in rows(output / "skeletal_mesh_morph_targets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO skeletal_mesh_morph_targets VALUES(?,?,?,?,?,?)", (
            row.get("skeletal_mesh_path", ""), int(row.get("morph_index", 0)), row.get("morph_target_path", ""),
            row.get("object_name", ""), row.get("class_path", ""), _j(row)))
    for row in rows(output / "skeletal_mesh_clothing_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO skeletal_mesh_clothing_assets VALUES(?,?,?,?,?,?,?)", (
            row.get("skeletal_mesh_path", ""), int(row.get("clothing_index", 0)), row.get("clothing_asset_path", ""),
            row.get("clothing_asset_name", ""), row.get("class_path", ""), row.get("physics_asset_path", ""), _j(row)))
    for row in rows(output / "skeletal_mesh_clothing_configs.jsonl"):
        conn.execute("INSERT OR REPLACE INTO skeletal_mesh_clothing_configs VALUES(?,?,?,?,?,?,?)", (
            row.get("skeletal_mesh_path", ""), row.get("clothing_asset_path", ""), int(row.get("config_index", 0)),
            row.get("config_path", ""), row.get("config_class", ""), _j(row.get("properties", {})), _j(row)))
    for row in rows(output / "physics_assets.jsonl"):
        conn.execute("INSERT OR REPLACE INTO physics_assets VALUES(?,?,?,?,?,?,?,?,?)", (
            row.get("physics_asset_path", ""), row.get("class_path", ""), row.get("package_name", ""),
            row.get("preview_skeletal_mesh_path", ""), int(row.get("body_count", 0) or 0),
            int(row.get("constraint_count", 0) or 0), int(row.get("constraint_profile_count", 0) or 0),
            int(row.get("physical_animation_profile_count", 0) or 0), _j(row)))
    for row in rows(output / "physics_bodies.jsonl"):
        conn.execute("INSERT OR REPLACE INTO physics_bodies VALUES(?,?,?,?,?,?,?,?,?)", (
            row.get("physics_asset_path", ""), int(row.get("body_index", 0)), row.get("body_path", ""),
            row.get("body_class", ""), row.get("bone_name", ""), row.get("physics_type", ""),
            row.get("collision_response", ""), _j(row.get("authored_properties", {})), _j(row)))
    for row in rows(output / "physics_body_shapes.jsonl"):
        conn.execute("INSERT OR REPLACE INTO physics_body_shapes VALUES(?,?,?,?,?,?,?,?,?)", (
            row.get("physics_asset_path", ""), int(row.get("body_index", 0)), row.get("body_path", ""),
            row.get("shape_type", ""), int(row.get("shape_index", 0)), row.get("shape_struct", ""),
            _j(row.get("fields", {})), row.get("raw_value", ""), _j(row)))
    for row in rows(output / "physics_constraints.jsonl"):
        conn.execute("INSERT OR REPLACE INTO physics_constraints VALUES(?,?,?,?,?,?,?,?,?,?,?)", (
            row.get("physics_asset_path", ""), int(row.get("constraint_index", 0)), row.get("constraint_path", ""),
            row.get("constraint_class", ""), row.get("joint_name", ""), row.get("constraint_bone1", ""),
            row.get("constraint_bone2", ""), _j(row.get("default_instance", {})), _j(row.get("profile_instance", {})),
            row.get("profile_handles", ""), _j(row)))
    for filename, table in (("physics_constraint_profiles.jsonl", "physics_constraint_profiles"), ("physics_physical_animation_profiles.jsonl", "physics_physical_animation_profiles")):
        for row in rows(output / filename):
            conn.execute(f"INSERT OR REPLACE INTO {table} VALUES(?,?,?,?)", (
                row.get("physics_asset_path", ""), int(row.get("profile_index", 0)), row.get("profile_name", ""), _j(row)))
    for row in rows(output / "physics_collision_disable_pairs.jsonl"):
        conn.execute("INSERT OR REPLACE INTO physics_collision_disable_pairs VALUES(?,?,?,?,?,?)", (
            row.get("physics_asset_path", ""), int(row.get("pair_index", 0)), row.get("key", ""), row.get("value", ""),
            _j(row.get("key_fields", {})), _j(row)))


def query(conn, print_rows, term: str, limit: int) -> None:
    print("\n[skeletal meshes]")
    print_rows(conn.execute(
        "SELECT skeletal_mesh_path,skeleton_path,physics_asset_path,lod_count,material_count,morph_target_count,clothing_asset_count FROM skeletal_meshes WHERE skeletal_mesh_path LIKE ? OR skeleton_path LIKE ? OR physics_asset_path LIKE ? LIMIT ?",
        (term, term, term, limit)),
        ("skeletal_mesh_path", "skeleton_path", "physics_asset_path", "lod_count", "material_count", "morph_target_count", "clothing_asset_count"))
    print("\n[physics bodies]")
    print_rows(conn.execute(
        "SELECT physics_asset_path,body_index,bone_name,physics_type,collision_response FROM physics_bodies WHERE physics_asset_path LIKE ? OR bone_name LIKE ? OR authored_properties_json LIKE ? LIMIT ?",
        (term, term, term, limit)),
        ("physics_asset_path", "body_index", "bone_name", "physics_type", "collision_response"))
    print("\n[physics constraints]")
    print_rows(conn.execute(
        "SELECT physics_asset_path,constraint_index,joint_name,constraint_bone1,constraint_bone2 FROM physics_constraints WHERE physics_asset_path LIKE ? OR joint_name LIKE ? OR constraint_bone1 LIKE ? OR constraint_bone2 LIKE ? OR profile_instance_json LIKE ? LIMIT ?",
        (term, term, term, term, term, limit)),
        ("physics_asset_path", "constraint_index", "joint_name", "constraint_bone1", "constraint_bone2"))


def install(animation_module) -> None:
    """Compose schema 3 while retaining schema-2 compatibility for old corpora."""
    if getattr(animation_module, "_mesh_physics_schema3_installed", False):
        return
    previous_prepare = animation_module.prepare_output
    previous_validation = animation_module.validation_error

    def prepare_output(output, rows) -> None:
        previous_prepare(output, rows)
        normalize_output(Path(output))

    def animation_validation_error(output) -> str | None:
        output = Path(output)
        has_sidecar = (output / "animation_mesh_physics_manifest.json").is_file()
        manifest = _read_json(output / "animation_manifest.json")
        public_schema = int(manifest.get("schema_version", 0) or 0) if manifest is not None else 0
        if has_sidecar:
            if public_schema < PUBLIC_ANIMATION_SCHEMA_VERSION:
                return (
                    f"unexpected public animation schema {public_schema!r}; "
                    f"expected at least {PUBLIC_ANIMATION_SCHEMA_VERSION}"
                )
            expected = public_schema
        else:
            expected = 2
        saved = int(getattr(animation_module, "ANIMATION_SCHEMA_VERSION", PUBLIC_ANIMATION_SCHEMA_VERSION))
        animation_module.ANIMATION_SCHEMA_VERSION = expected
        try:
            error = previous_validation(output)
        finally:
            animation_module.ANIMATION_SCHEMA_VERSION = saved
        if error:
            return error
        if manifest is not None and int(manifest.get("schema_version", 0) or 0) != expected:
            return f"unexpected public animation schema {manifest.get('schema_version')!r}; expected {expected}"
        if has_sidecar:
            return validation_error(output, require_present=True)
        return None

    animation_module.ANIMATION_SCHEMA_VERSION = PUBLIC_ANIMATION_SCHEMA_VERSION
    animation_module.prepare_output = prepare_output
    animation_module.validation_error = animation_validation_error
    animation_module._mesh_physics_schema3_installed = True
