#!/usr/bin/env python3
"""Canonical authored Motion Warping support for public animation schema 4."""
from __future__ import annotations

import json
import os
from pathlib import Path

import uatool_motion_warping_capture as capture

MOTION_WARPING_SCHEMA_VERSION = 1
PUBLIC_ANIMATION_SCHEMA_VERSION = 4
MIN_BASE_ANIMATION_SCHEMA_VERSION = 3
MANIFEST_FILE = "animation_motion_warping_manifest.json"
NOTIFY_CLASS = "/Script/MotionWarping.AnimNotifyState_MotionWarping"

JSONL_FILES = (
    "motion_warping_windows.jsonl",
    "motion_warping_modifiers.jsonl",
    "motion_warping_modifier_properties.jsonl",
)
RAW_FILES = (MANIFEST_FILE, *JSONL_FILES)

_SQL = """
CREATE TABLE motion_warping_windows(
    asset_path TEXT NOT NULL,
    notify_index INTEGER NOT NULL,
    asset_class TEXT NOT NULL,
    notify_guid TEXT NOT NULL,
    notify_state_path TEXT NOT NULL,
    notify_state_class TEXT NOT NULL,
    trigger_time REAL NOT NULL,
    end_trigger_time REAL NOT NULL,
    duration REAL NOT NULL,
    track_index INTEGER NOT NULL,
    modifier_path TEXT NOT NULL,
    modifier_class TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(asset_path,notify_index)
);
CREATE INDEX motion_warping_windows_modifier_idx ON motion_warping_windows(modifier_path);

CREATE TABLE motion_warping_modifiers(
    asset_path TEXT NOT NULL,
    notify_index INTEGER NOT NULL,
    notify_state_path TEXT NOT NULL,
    modifier_path TEXT PRIMARY KEY,
    modifier_class TEXT NOT NULL,
    outer_path TEXT NOT NULL,
    outer_class TEXT NOT NULL,
    warp_target_name TEXT NOT NULL,
    warp_point_anim_provider TEXT NOT NULL,
    warp_point_anim_bone_name TEXT NOT NULL,
    warp_point_anim_transform TEXT NOT NULL,
    warp_translation INTEGER NOT NULL,
    ignore_z_axis INTEGER NOT NULL,
    warp_to_feet_location INTEGER NOT NULL,
    add_translation_easing_func TEXT NOT NULL,
    add_translation_easing_curve TEXT NOT NULL,
    add_translation_easing_curve_class TEXT NOT NULL,
    warp_rotation INTEGER NOT NULL,
    rotation_type TEXT NOT NULL,
    rotation_method TEXT NOT NULL,
    subtract_remaining_root_motion INTEGER NOT NULL,
    additional_rotation_offset TEXT NOT NULL,
    warp_rotation_time_multiplier TEXT NOT NULL,
    warp_max_rotation_rate TEXT NOT NULL,
    json TEXT NOT NULL,
    UNIQUE(asset_path,notify_index)
);
CREATE INDEX motion_warping_modifiers_target_idx ON motion_warping_modifiers(warp_target_name);
CREATE INDEX motion_warping_modifiers_class_idx ON motion_warping_modifiers(modifier_class);

CREATE TABLE motion_warping_modifier_properties(
    modifier_path TEXT NOT NULL,
    asset_path TEXT NOT NULL,
    notify_index INTEGER NOT NULL,
    declaring_type TEXT NOT NULL,
    property_name TEXT NOT NULL,
    static_index INTEGER NOT NULL,
    property_type TEXT NOT NULL,
    cpp_type TEXT NOT NULL,
    value TEXT NOT NULL,
    target_path TEXT NOT NULL,
    target_class TEXT NOT NULL,
    json TEXT NOT NULL,
    PRIMARY KEY(modifier_path,declaring_type,property_name,static_index)
);
CREATE INDEX motion_warping_modifier_properties_name_idx
    ON motion_warping_modifier_properties(property_name,modifier_path);
CREATE INDEX motion_warping_modifier_properties_target_idx
    ON motion_warping_modifier_properties(target_path);
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
    return text.casefold(), text


def _window_key(row: dict) -> tuple[tuple[str, str], int]:
    return _path_key(str(row.get("asset_path", ""))), int(row.get("notify_index", -1))


def _canonical_rows(capture_dir: Path) -> dict[str, list[dict]]:
    windows = []
    for row in _rows(capture_dir / "motion_warping_windows.jsonl"):
        windows.append({
            "asset_path": str(row.get("asset_path", "")),
            "asset_class": str(row.get("asset_class", "")),
            "notify_index": int(row.get("notify_index", -1)),
            "notify_guid": str(row.get("notify_guid", "")),
            "notify_state_path": str(row.get("notify_state_path", "")),
            "notify_state_class": str(row.get("notify_state_class", "")),
            "trigger_time": float(row.get("trigger_time", 0.0) or 0.0),
            "end_trigger_time": float(row.get("end_trigger_time", 0.0) or 0.0),
            "duration": float(row.get("duration", 0.0) or 0.0),
            "track_index": int(row.get("track_index", 0) or 0),
            "modifier_path": str(row.get("modifier_path", "")),
            "modifier_class": str(row.get("modifier_class", "")),
        })

    modifiers = []
    for row in _rows(capture_dir / "motion_warping_modifiers.jsonl"):
        modifiers.append({
            "asset_path": str(row.get("asset_path", "")),
            "notify_index": int(row.get("notify_index", -1)),
            "notify_state_path": str(row.get("notify_state_path", "")),
            "modifier_path": str(row.get("modifier_path", "")),
            "modifier_class": str(row.get("modifier_class", "")),
            "outer_path": str(row.get("outer_path", "")),
            "outer_class": str(row.get("outer_class", "")),
            "is_template": bool(row.get("is_template", False)),
            "warp_target_name": str(row.get("warp_target_name", "")),
            "warp_point_anim_provider": str(row.get("warp_point_anim_provider", "")),
            "warp_point_anim_bone_name": str(row.get("warp_point_anim_bone_name", "")),
            "warp_point_anim_transform": str(row.get("warp_point_anim_transform", "")),
            "warp_translation": bool(row.get("warp_translation", False)),
            "ignore_z_axis": bool(row.get("ignore_z_axis", False)),
            "warp_to_feet_location": bool(row.get("warp_to_feet_location", False)),
            "add_translation_easing_func": str(row.get("add_translation_easing_func", "")),
            "add_translation_easing_curve": str(row.get("add_translation_easing_curve", "")),
            "add_translation_easing_curve_class": str(row.get("add_translation_easing_curve_class", "")),
            "warp_rotation": bool(row.get("warp_rotation", False)),
            "rotation_type": str(row.get("rotation_type", "")),
            "rotation_method": str(row.get("rotation_method", "")),
            "subtract_remaining_root_motion": bool(row.get("subtract_remaining_root_motion", False)),
            "additional_rotation_offset": str(row.get("additional_rotation_offset", "")),
            "warp_rotation_time_multiplier": str(row.get("warp_rotation_time_multiplier", "")),
            "warp_max_rotation_rate": str(row.get("warp_max_rotation_rate", "")),
        })

    properties = []
    for row in _rows(capture_dir / "motion_warping_modifier_properties.jsonl"):
        properties.append({
            "asset_path": str(row.get("asset_path", "")),
            "notify_index": int(row.get("notify_index", -1)),
            "notify_state_path": str(row.get("notify_state_path", "")),
            "modifier_path": str(row.get("modifier_path", "")),
            "modifier_class": str(row.get("modifier_class", "")),
            "declaring_type": str(row.get("declaring_type", "")),
            "property_name": str(row.get("property_name", "")),
            "static_index": int(row.get("static_index", 0) or 0),
            "property_type": str(row.get("property_type", "")),
            "cpp_type": str(row.get("cpp_type", "")),
            "value": str(row.get("value", "")),
            "target_path": str(row.get("target_path", "")),
            "target_class": str(row.get("target_class", "")),
        })

    windows.sort(key=_window_key)
    modifiers.sort(key=_window_key)
    properties.sort(key=lambda row: (
        *_path_key(str(row.get("modifier_path", ""))),
        str(row.get("declaring_type", "")),
        str(row.get("property_name", "")),
        int(row.get("static_index", 0)),
    ))
    return {
        "motion_warping_windows.jsonl": windows,
        "motion_warping_modifiers.jsonl": modifiers,
        "motion_warping_modifier_properties.jsonl": properties,
    }


def _refresh_animation_manifest(corpus: Path, sidecar: dict) -> None:
    path = corpus / "animation_manifest.json"
    manifest = _read_json(path)
    if manifest is None:
        raise RuntimeError("animation_manifest.json missing while composing Motion Warping schema")
    schema = int(manifest.get("schema_version", 0) or 0)
    if schema < MIN_BASE_ANIMATION_SCHEMA_VERSION or schema > PUBLIC_ANIMATION_SCHEMA_VERSION:
        raise RuntimeError(f"cannot compose Motion Warping with animation schema {schema}")

    counts = manifest.get("counts", {})
    counts = counts if isinstance(counts, dict) else {}
    side_counts = sidecar.get("counts", {})
    side_counts = side_counts if isinstance(side_counts, dict) else {}
    for key in (
        "motion_warping_windows",
        "motion_warping_modifiers",
        "motion_warping_modifier_properties",
        "motion_warping_skew_warp_modifiers",
        "motion_warping_precomputed_warp_modifiers",
        "motion_warping_unique_target_names",
    ):
        counts[key] = int(side_counts.get(key, 0) or 0)
    manifest["counts"] = counts

    files = [str(v) for v in (manifest.get("files", []) or [])]
    for filename in JSONL_FILES:
        if filename not in files:
            files.append(filename)
    manifest["files"] = files
    manifest["schema_version"] = PUBLIC_ANIMATION_SCHEMA_VERSION
    manifest["motion_warping_schema_version"] = MOTION_WARPING_SCHEMA_VERSION
    manifest["motion_warping_pass"] = str(sidecar.get("pass", "UnrealAssetToolMotionWarping"))
    manifest["runtime_state_captured"] = False
    _write_json(path, manifest)

    top_path = corpus / "manifest.json"
    top = _read_json(top_path)
    if top is not None:
        top["animation_schema_version"] = PUBLIC_ANIMATION_SCHEMA_VERSION
        top["animation_counts"] = counts
        top["animation_files"] = files
        top["motion_warping_schema_version"] = MOTION_WARPING_SCHEMA_VERSION
        _write_json(top_path, top)


def promote_capture(corpus: Path, capture_dir: Path) -> dict:
    corpus = Path(corpus).expanduser().resolve()
    capture_dir = Path(capture_dir).expanduser().resolve()
    if not corpus.is_dir():
        raise FileNotFoundError(f"corpus directory does not exist: {corpus}")
    capture_manifest = capture.validate_capture(capture_dir)
    canonical = _canonical_rows(capture_dir)

    counts = {
        name.removesuffix(".jsonl"): _write_jsonl(corpus / name, rows)
        for name, rows in canonical.items()
    }
    modifiers = canonical["motion_warping_modifiers.jsonl"]
    counts["motion_warping_skew_warp_modifiers"] = sum(
        str(row.get("modifier_class", "")).endswith(".RootMotionModifier_SkewWarp") for row in modifiers
    )
    counts["motion_warping_precomputed_warp_modifiers"] = sum(
        str(row.get("modifier_class", "")).endswith(".RootMotionModifier_PrecomputedWarp") for row in modifiers
    )
    counts["motion_warping_unique_target_names"] = len({
        str(row.get("warp_target_name", ""))
        for row in modifiers
        if str(row.get("warp_target_name", "")) not in ("", "None")
    })

    manifest = {
        "schema_version": MOTION_WARPING_SCHEMA_VERSION,
        "public_animation_schema_version": PUBLIC_ANIMATION_SCHEMA_VERSION,
        "success": True,
        "pass": "UnrealAssetToolMotionWarping",
        "source_capture_schema_version": int(capture_manifest.get("schema_version", 0) or 0),
        "engine_version": str(capture_manifest.get("engine_version", "")),
        "runtime_state_captured": False,
        "live_warp_targets_captured": False,
        "active_root_motion_modifiers_captured": False,
        "root_motion_evaluated": False,
        "maps_loaded": False,
        "motion_warping_module_linked": False,
        "counts": counts,
        "files": list(JSONL_FILES),
        "capture_scope": (
            "authored AnimNotifyState_MotionWarping windows and their instanced RootMotionModifier templates, "
            "including common warp policy and exact editable modifier-class properties; live warp targets, "
            "active runtime modifiers, root-motion evaluation and map/runtime state are excluded"
        ),
    }
    _write_json(corpus / MANIFEST_FILE, manifest)
    _refresh_animation_manifest(corpus, manifest)
    try:
        import uatool_derived_freshness as freshness
        freshness.invalidate(corpus)
    except Exception:
        pass

    error = validation_error(corpus, require_present=True)
    if error:
        raise RuntimeError(f"promoted Motion Warping animation schema 4 is invalid: {error}")
    return manifest


def validation_error(output: Path, *, require_present: bool = False) -> str | None:
    output = Path(output)
    manifest = _read_json(output / MANIFEST_FILE)
    if manifest is None:
        return f"{MANIFEST_FILE} missing" if require_present else None
    try:
        if int(manifest.get("schema_version", 0) or 0) != MOTION_WARPING_SCHEMA_VERSION:
            return f"unexpected Motion Warping schema {manifest.get('schema_version')!r}"
        if int(manifest.get("public_animation_schema_version", 0) or 0) != PUBLIC_ANIMATION_SCHEMA_VERSION:
            return f"unexpected Motion Warping public animation schema {manifest.get('public_animation_schema_version')!r}"
        if not bool(manifest.get("success", False)):
            return f"Motion Warping scanner failed: {manifest.get('error', '')}"
        for flag in (
            "runtime_state_captured",
            "live_warp_targets_captured",
            "active_root_motion_modifiers_captured",
            "root_motion_evaluated",
            "maps_loaded",
            "motion_warping_module_linked",
        ):
            if bool(manifest.get(flag, True)):
                return f"Motion Warping authored boundary violated: {flag}=true"

        for filename in JSONL_FILES:
            if not (output / filename).is_file():
                return f"Motion Warping stream missing: {filename}"

        windows = list(_rows(output / "motion_warping_windows.jsonl"))
        modifiers = list(_rows(output / "motion_warping_modifiers.jsonl"))
        properties = list(_rows(output / "motion_warping_modifier_properties.jsonl"))
        if not windows:
            return "Motion Warping canonical schema must not be present with zero windows"
        if windows != sorted(windows, key=_window_key):
            return "Motion Warping windows are not deterministically sorted"
        window_keys = {(str(r.get("asset_path", "")), int(r.get("notify_index", -1))) for r in windows}
        if len(window_keys) != len(windows):
            return "Motion Warping window identities are not unique"
        if any(str(r.get("notify_state_class", "")) != NOTIFY_CLASS for r in windows):
            return "Motion Warping canonical window contains non-focus notify class"

        modifier_keys = set()
        modifier_paths = set()
        for row in modifiers:
            key = (str(row.get("asset_path", "")), int(row.get("notify_index", -1)))
            path = str(row.get("modifier_path", ""))
            if key not in window_keys or key in modifier_keys or not path or path in modifier_paths:
                return "Motion Warping modifier identity/owner invariant failed"
            if not bool(row.get("is_template", False)):
                return "Motion Warping modifier is not an authored notify-owned template"
            if not str(row.get("modifier_class", "")):
                return "Motion Warping modifier class is empty"
            modifier_keys.add(key)
            modifier_paths.add(path)
        if modifier_keys != window_keys:
            return "Motion Warping windows and modifier templates are not one-to-one"

        prop_keys = set()
        for row in properties:
            path = str(row.get("modifier_path", ""))
            key = (
                path,
                str(row.get("declaring_type", "")),
                str(row.get("property_name", "")),
                int(row.get("static_index", 0) or 0),
            )
            if path not in modifier_paths or key in prop_keys:
                return "Motion Warping modifier property identity/owner invariant failed"
            prop_keys.add(key)

        canonical_notifies = {}
        notify_path = output / "animation_notifies.jsonl"
        if not notify_path.is_file():
            return "animation_notifies.jsonl missing while validating Motion Warping schema"
        for row in _rows(notify_path):
            if str(row.get("notify_state_class", "")) != NOTIFY_CLASS:
                continue
            key = (str(row.get("asset_path", "")), int(row.get("notify_index", -1)))
            canonical_notifies[key] = str(row.get("notify_state_object", ""))
        if set(canonical_notifies) != window_keys:
            return (
                "Motion Warping canonical window set does not exactly match "
                f"animation_notifies.jsonl: notify={len(canonical_notifies)} motion={len(window_keys)}"
            )
        by_key = {(str(r.get("asset_path", "")), int(r.get("notify_index", -1))): r for r in windows}
        for key, notify_state in canonical_notifies.items():
            if str(by_key[key].get("notify_state_path", "")) != notify_state:
                return f"Motion Warping notify-state identity mismatch: {key}"

        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        physical = {
            "motion_warping_windows": len(windows),
            "motion_warping_modifiers": len(modifiers),
            "motion_warping_modifier_properties": len(properties),
        }
        for key, actual in physical.items():
            if int(counts.get(key, -1)) != actual:
                return f"Motion Warping count mismatch for {key}: manifest={counts.get(key)} actual={actual}"

        animation_manifest = _read_json(output / "animation_manifest.json")
        if animation_manifest is None:
            return "animation_manifest.json missing"
        if int(animation_manifest.get("schema_version", 0) or 0) != PUBLIC_ANIMATION_SCHEMA_VERSION:
            return f"unexpected public animation schema {animation_manifest.get('schema_version')!r}"
        if int(animation_manifest.get("motion_warping_schema_version", 0) or 0) != MOTION_WARPING_SCHEMA_VERSION:
            return "animation manifest missing Motion Warping schema marker"
    except (RuntimeError, ValueError, TypeError, KeyError) as exc:
        return str(exc)
    return None


def normalize_output(output: Path) -> bool:
    output = Path(output)
    sidecar = _read_json(output / MANIFEST_FILE)
    if sidecar is None:
        return False
    error = validation_error(output, require_present=True)
    if error:
        # validation checks the public manifest too; allow the initial promotion
        # path to set schema 4 before re-validating.
        animation_manifest = _read_json(output / "animation_manifest.json")
        if animation_manifest is None or int(animation_manifest.get("schema_version", 0) or 0) == PUBLIC_ANIMATION_SCHEMA_VERSION:
            raise RuntimeError(error)
    _refresh_animation_manifest(output, sidecar)
    error = validation_error(output, require_present=True)
    if error:
        raise RuntimeError(error)
    return True


def clear_schema(output: Path, *, base_animation_schema: int = MIN_BASE_ANIMATION_SCHEMA_VERSION) -> None:
    output = Path(output)
    for filename in RAW_FILES:
        (output / filename).unlink(missing_ok=True)

    animation_path = output / "animation_manifest.json"
    animation_manifest = _read_json(animation_path)
    if animation_manifest is not None:
        counts = animation_manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        for key in tuple(counts):
            if str(key).startswith("motion_warping_"):
                counts.pop(key, None)
        files = [
            str(v) for v in (animation_manifest.get("files", []) or [])
            if str(v) not in JSONL_FILES
        ]
        animation_manifest["counts"] = counts
        animation_manifest["files"] = files
        animation_manifest["schema_version"] = int(base_animation_schema)
        animation_manifest.pop("motion_warping_schema_version", None)
        animation_manifest.pop("motion_warping_pass", None)
        _write_json(animation_path, animation_manifest)

    top_path = output / "manifest.json"
    top = _read_json(top_path)
    if top is not None:
        top["animation_schema_version"] = int(base_animation_schema)
        top.pop("motion_warping_schema_version", None)
        if animation_manifest is not None:
            top["animation_counts"] = animation_manifest.get("counts", {})
            top["animation_files"] = animation_manifest.get("files", [])
        _write_json(top_path, top)
    try:
        import uatool_derived_freshness as freshness
        freshness.invalidate(output)
    except Exception:
        pass


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def load_database(conn, output: Path, rows) -> None:
    output = Path(output)
    for row in rows(output / "motion_warping_windows.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO motion_warping_windows VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("asset_path", ""),
                int(row.get("notify_index", 0) or 0),
                row.get("asset_class", ""),
                row.get("notify_guid", ""),
                row.get("notify_state_path", ""),
                row.get("notify_state_class", ""),
                float(row.get("trigger_time", 0.0) or 0.0),
                float(row.get("end_trigger_time", 0.0) or 0.0),
                float(row.get("duration", 0.0) or 0.0),
                int(row.get("track_index", 0) or 0),
                row.get("modifier_path", ""),
                row.get("modifier_class", ""),
                _j(row),
            ),
        )
    for row in rows(output / "motion_warping_modifiers.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO motion_warping_modifiers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("asset_path", ""),
                int(row.get("notify_index", 0) or 0),
                row.get("notify_state_path", ""),
                row.get("modifier_path", ""),
                row.get("modifier_class", ""),
                row.get("outer_path", ""),
                row.get("outer_class", ""),
                row.get("warp_target_name", ""),
                row.get("warp_point_anim_provider", ""),
                row.get("warp_point_anim_bone_name", ""),
                row.get("warp_point_anim_transform", ""),
                int(bool(row.get("warp_translation", False))),
                int(bool(row.get("ignore_z_axis", False))),
                int(bool(row.get("warp_to_feet_location", False))),
                row.get("add_translation_easing_func", ""),
                row.get("add_translation_easing_curve", ""),
                row.get("add_translation_easing_curve_class", ""),
                int(bool(row.get("warp_rotation", False))),
                row.get("rotation_type", ""),
                row.get("rotation_method", ""),
                int(bool(row.get("subtract_remaining_root_motion", False))),
                row.get("additional_rotation_offset", ""),
                row.get("warp_rotation_time_multiplier", ""),
                row.get("warp_max_rotation_rate", ""),
                _j(row),
            ),
        )
    for row in rows(output / "motion_warping_modifier_properties.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO motion_warping_modifier_properties VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("modifier_path", ""),
                row.get("asset_path", ""),
                int(row.get("notify_index", 0) or 0),
                row.get("declaring_type", ""),
                row.get("property_name", ""),
                int(row.get("static_index", 0) or 0),
                row.get("property_type", ""),
                row.get("cpp_type", ""),
                row.get("value", ""),
                row.get("target_path", ""),
                row.get("target_class", ""),
                _j(row),
            ),
        )


def query(conn, print_rows, term: str, limit: int) -> None:
    print("\n[motion warping windows]")
    print_rows(conn.execute(
        "SELECT asset_path,notify_index,modifier_class,trigger_time,duration FROM motion_warping_windows "
        "WHERE asset_path LIKE ? OR modifier_class LIKE ? LIMIT ?",
        (term, term, limit)),
        ("asset_path", "notify_index", "modifier_class", "trigger_time", "duration"),
    )
    print("\n[motion warping modifiers]")
    print_rows(conn.execute(
        "SELECT modifier_path,modifier_class,warp_target_name,warp_point_anim_provider,warp_point_anim_bone_name,"
        "warp_translation,warp_rotation FROM motion_warping_modifiers "
        "WHERE modifier_path LIKE ? OR modifier_class LIKE ? OR warp_target_name LIKE ? OR warp_point_anim_bone_name LIKE ? LIMIT ?",
        (term, term, term, term, limit)),
        (
            "modifier_path", "modifier_class", "warp_target_name", "warp_point_anim_provider",
            "warp_point_anim_bone_name", "warp_translation", "warp_rotation",
        ),
    )
    print("\n[motion warping modifier properties]")
    print_rows(conn.execute(
        "SELECT modifier_path,declaring_type,property_name,cpp_type,value,target_path "
        "FROM motion_warping_modifier_properties "
        "WHERE modifier_path LIKE ? OR declaring_type LIKE ? OR property_name LIKE ? OR value LIKE ? OR target_path LIKE ? LIMIT ?",
        (term, term, term, term, term, limit)),
        ("modifier_path", "declaring_type", "property_name", "cpp_type", "value", "target_path"),
    )


def install(animation_module) -> None:
    """Compose Motion Warping schema 1 on top of animation schema 3."""
    if getattr(animation_module, "_motion_warping_schema4_installed", False):
        animation_module.ANIMATION_SCHEMA_VERSION = PUBLIC_ANIMATION_SCHEMA_VERSION
        return
    previous_prepare = animation_module.prepare_output
    previous_validation = animation_module.validation_error

    def prepare_output(output, rows) -> None:
        previous_prepare(output, rows)
        normalize_output(Path(output))

    def animation_validation_error(output) -> str | None:
        output = Path(output)
        has_motion = (output / MANIFEST_FILE).is_file()
        expected = PUBLIC_ANIMATION_SCHEMA_VERSION if has_motion else MIN_BASE_ANIMATION_SCHEMA_VERSION
        saved = int(getattr(animation_module, "ANIMATION_SCHEMA_VERSION", PUBLIC_ANIMATION_SCHEMA_VERSION))
        animation_module.ANIMATION_SCHEMA_VERSION = expected
        try:
            error = previous_validation(output)
        finally:
            animation_module.ANIMATION_SCHEMA_VERSION = saved
        if error:
            return error
        if has_motion:
            return validation_error(output, require_present=True)
        return None

    animation_module.ANIMATION_SCHEMA_VERSION = PUBLIC_ANIMATION_SCHEMA_VERSION
    animation_module.prepare_output = prepare_output
    animation_module.validation_error = animation_validation_error
    animation_module._motion_warping_schema4_installed = True
