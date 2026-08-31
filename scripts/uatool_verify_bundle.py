#!/usr/bin/env python3
"""Deterministic, read-only validation for UnrealAssetTool upload bundles."""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import uatool_blueprint_pin_storage as pin_storage

PIN_FILE = "blueprint_pins.jsonl"
NODE_FILE = "blueprint_nodes.jsonl"
MANIFEST_FILE = "manifest.json"


def _canonical_row_bytes(row: dict) -> bytes:
    return (
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _jsonl_from_zip(archive: zipfile.ZipFile, name: str):
    try:
        source = archive.open(name, "r")
    except KeyError as exc:
        raise RuntimeError(f"bundle missing required member: {name}") from exc
    with source:
        for line_number, raw in enumerate(source, 1):
            if not raw.strip():
                continue
            try:
                row = json.loads(raw)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"invalid JSON in bundled {name}:{line_number}: {exc}"
                ) from exc
            if not isinstance(row, dict):
                raise RuntimeError(
                    f"expected JSON object in bundled {name}:{line_number}"
                )
            yield line_number, row


def _manifest_from_zip(archive: zipfile.ZipFile) -> dict:
    try:
        raw = archive.read(MANIFEST_FILE)
    except KeyError as exc:
        raise RuntimeError("bundle missing manifest.json") from exc
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid bundled manifest.json: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("bundled manifest.json root is not an object")
    return value


def _node_map_from_zip(archive: zipfile.ZipFile) -> dict[str, tuple[str, str, str]]:
    result: dict[str, tuple[str, str, str]] = {}
    for line_number, row in _jsonl_from_zip(archive, NODE_FILE):
        node_id = str(row.get("node_id", ""))
        if not node_id:
            raise RuntimeError(
                f"bundled Blueprint node missing node_id in {NODE_FILE}:{line_number}"
            )
        if node_id in result:
            raise RuntimeError(f"duplicate bundled Blueprint node_id: {node_id}")
        result[node_id] = tuple(
            str(row.get(field, ""))
            for field in pin_storage.AUTHORITATIVE_NODE_FIELDS
        )
    return result


def _expand_column(value, count: int, field: str, context: str) -> list:
    if isinstance(value, list):
        if len(value) != count:
            raise RuntimeError(
                f"Blueprint pin block column {field!r} length mismatch in {context}: "
                f"expected {count}, got {len(value)}"
            )
        return value
    return [value] * count


def _decode_indices(row: dict, count: int, context: str) -> list[int]:
    has_start = "pin_index_start" in row
    has_indices = "pin_indices" in row
    if has_start and has_indices:
        raise RuntimeError(f"Blueprint pin block has both index encodings in {context}")
    if has_indices:
        value = row.get("pin_indices")
        if not isinstance(value, list) or len(value) != count:
            raise RuntimeError(f"invalid pin_indices in {context}")
        if any(not isinstance(index, int) or index < 0 for index in value):
            raise RuntimeError(f"invalid pin_indices in {context}")
        if len(set(value)) != len(value):
            raise RuntimeError(f"duplicate pin_indices in {context}")
        return value
    start = row.get("pin_index_start", 0)
    if not isinstance(start, int) or start < 0:
        raise RuntimeError(f"invalid pin_index_start in {context}")
    return list(range(start, start + count))


def _logical_pin_digest(archive: zipfile.ZipFile) -> tuple[int, int, str]:
    """Expand compact pin blocks and hash the ordered canonical logical rows."""
    nodes = _node_map_from_zip(archive)
    logical = 0
    blocks = 0
    seen_nodes: set[str] = set()
    seen_pins: set[str] = set()
    digest = hashlib.sha256()

    required_block_fields = {"encoding", "node_id", "pin_count", "columns"}
    allowed_block_fields = required_block_fields | {"pin_index_start", "pin_indices"}
    expected_columns = set(pin_storage.COLUMN_FIELDS)

    for line_number, row in _jsonl_from_zip(archive, PIN_FILE):
        context = f"{PIN_FILE}:{line_number}"
        missing = required_block_fields - set(row)
        extra = set(row) - allowed_block_fields
        if missing or extra:
            raise RuntimeError(
                f"Blueprint pin block fields mismatch in {context}: "
                f"missing={sorted(missing)} extra={sorted(extra)}"
            )
        if row.get("encoding") != pin_storage.ENCODING:
            raise RuntimeError(
                f"unexpected Blueprint pin encoding in {context}: "
                f"{row.get('encoding')!r}"
            )
        node_id = row.get("node_id")
        if not isinstance(node_id, str) or not node_id:
            raise RuntimeError(f"invalid node_id in {context}")
        if node_id not in nodes:
            raise RuntimeError(f"Blueprint pin block references missing node: {node_id}")
        if node_id in seen_nodes:
            raise RuntimeError(f"duplicate Blueprint pin block for node: {node_id}")
        seen_nodes.add(node_id)

        count = row.get("pin_count")
        if not isinstance(count, int) or count < 0:
            raise RuntimeError(f"invalid pin_count in {context}")
        columns = row.get("columns")
        if not isinstance(columns, dict) or set(columns) != expected_columns:
            raise RuntimeError(f"Blueprint pin block columns mismatch in {context}")
        indices = _decode_indices(row, count, context)
        expanded = {
            field: _expand_column(columns[field], count, field, context)
            for field in pin_storage.COLUMN_FIELDS
        }

        blueprint_path, graph_id, graph_name = nodes[node_id]
        for offset in range(count):
            suffix = str(expanded["pin_id_suffix"][offset])
            if not suffix:
                raise RuntimeError(f"empty pin_id suffix in {context}")
            pin_id = node_id + "::" + suffix
            if pin_id in seen_pins:
                raise RuntimeError(f"duplicate reconstructed Blueprint pin_id: {pin_id}")
            seen_pins.add(pin_id)
            logical_row = {
                "pin_id": pin_id,
                "node_id": node_id,
                "blueprint_path": blueprint_path,
                "graph_id": graph_id,
                "graph_name": graph_name,
                "pin_index": indices[offset],
                "name": expanded["name"][offset],
                "direction": expanded["direction"][offset],
                "type": {
                    "category": expanded["type_category"][offset],
                    "subcategory": expanded["type_subcategory"][offset],
                    "container_type": expanded["type_container_type"][offset],
                    "is_reference": expanded["type_is_reference"][offset],
                    "is_const": expanded["type_is_const"][offset],
                    "subcategory_object": expanded["type_subcategory_object"][offset],
                },
                "default_value": expanded["default_value"][offset],
                "default_object": expanded["default_object"][offset],
                "default_text": expanded["default_text"][offset],
                "hidden": expanded["hidden"][offset],
                "not_connectable": expanded["not_connectable"][offset],
                "linked_count": expanded["linked_count"][offset],
            }
            digest.update(_canonical_row_bytes(logical_row))
            logical += 1
        blocks += 1

    return logical, blocks, digest.hexdigest()


def _legacy_pin_digest(archive: zipfile.ZipFile) -> tuple[int, str]:
    """Hash an ordered legacy row-per-pin stream with the same canonicalization."""
    count = 0
    seen_pins: set[str] = set()
    digest = hashlib.sha256()
    for line_number, row in _jsonl_from_zip(archive, PIN_FILE):
        context = f"baseline {PIN_FILE}:{line_number}"
        if row.get("encoding") == pin_storage.ENCODING:
            logical, _blocks, logical_sha = _logical_pin_digest(archive)
            return logical, logical_sha
        if set(row) != pin_storage.LEGACY_FIELDS:
            raise RuntimeError(
                f"legacy Blueprint pin fields mismatch in {context}: "
                f"missing={sorted(pin_storage.LEGACY_FIELDS - set(row))} "
                f"extra={sorted(set(row) - pin_storage.LEGACY_FIELDS)}"
            )
        pin_id = row.get("pin_id")
        if not isinstance(pin_id, str) or not pin_id:
            raise RuntimeError(f"invalid legacy Blueprint pin_id in {context}")
        if pin_id in seen_pins:
            raise RuntimeError(f"duplicate legacy Blueprint pin_id in {context}: {pin_id}")
        seen_pins.add(pin_id)
        digest.update(_canonical_row_bytes(row))
        count += 1
    return count, digest.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _archive_member_hashes(path: Path) -> tuple[list[str], dict[str, str]]:
    with zipfile.ZipFile(path, "r") as archive:
        names = archive.namelist()
        hashes = {name: _sha256_bytes(archive.read(name)) for name in names}
    return names, hashes


def verify_bundle(
    output: Path,
    bundle: Path,
    *,
    baseline: Path | None = None,
    expect_blueprint_pin_sha256: str | None = None,
    expect_changed: set[str] | None = None,
) -> dict:
    output = Path(output).expanduser().resolve()
    bundle = Path(bundle).expanduser().resolve()
    baseline = Path(baseline).expanduser().resolve() if baseline else None

    if not output.is_dir():
        raise RuntimeError(f".uatool output directory does not exist: {output}")
    if not bundle.is_file():
        raise RuntimeError(f"bundle ZIP does not exist: {bundle}")
    if baseline is not None and not baseline.is_file():
        raise RuntimeError(f"baseline ZIP does not exist: {baseline}")

    local_error = pin_storage.manifest_validation_error(output)
    if local_error:
        raise RuntimeError(f"local Blueprint pin storage invalid: {local_error}")

    bundle_size = bundle.stat().st_size
    with zipfile.ZipFile(bundle, "r") as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise RuntimeError(f"ZIP CRC failure: {bad_member}")
        infos = archive.infolist()
        if len({info.filename for info in infos}) != len(infos):
            raise RuntimeError("bundle contains duplicate member names")
        non_deflate = [
            info.filename for info in infos
            if info.compress_type != zipfile.ZIP_DEFLATED
        ]
        if non_deflate:
            raise RuntimeError(
                f"bundle contains non-DEFLATE members: {non_deflate[:10]}"
            )
        raw_size = sum(info.file_size for info in infos)
        manifest = _manifest_from_zip(archive)

        if int(manifest.get("blueprint_pin_storage_schema_version", 0) or 0) != pin_storage.STORAGE_SCHEMA_VERSION:
            raise RuntimeError(
                "unexpected bundled Blueprint pin storage schema: "
                f"{manifest.get('blueprint_pin_storage_schema_version')!r}"
            )
        if manifest.get("blueprint_pin_encoding") != pin_storage.ENCODING:
            raise RuntimeError(
                "unexpected bundled Blueprint pin encoding: "
                f"{manifest.get('blueprint_pin_encoding')!r}"
            )

        logical, blocks, logical_sha = _logical_pin_digest(archive)
        counts = manifest.get("counts", {})
        counts = counts if isinstance(counts, dict) else {}
        expected_logical = int(
            counts.get("blueprint_pins", manifest.get("blueprint_pin_logical_count", -1))
        )
        expected_blocks = int(
            counts.get("blueprint_pin_blocks", manifest.get("blueprint_pin_block_count", -1))
        )
        if logical != expected_logical:
            raise RuntimeError(
                f"Blueprint pin logical count mismatch: manifest={expected_logical} actual={logical}"
            )
        if blocks != expected_blocks:
            raise RuntimeError(
                f"Blueprint pin block count mismatch: manifest={expected_blocks} actual={blocks}"
            )

        source_mismatches: list[str] = []
        missing_source_members: list[str] = []
        for info in infos:
            local = output / info.filename
            if not local.is_file():
                missing_source_members.append(info.filename)
                continue
            local_hash = hashlib.sha256(local.read_bytes()).hexdigest()
            zip_hash = hashlib.sha256(archive.read(info.filename)).hexdigest()
            if local_hash != zip_hash:
                source_mismatches.append(info.filename)
        if missing_source_members:
            raise RuntimeError(
                "bundle members are missing from local .uatool output: "
                f"{missing_source_members[:10]}"
            )
        if source_mismatches:
            raise RuntimeError(
                "bundle members differ from local .uatool source bytes: "
                f"{source_mismatches[:10]}"
            )
        pin_info = archive.getinfo(PIN_FILE)

    baseline_pin_count: int | None = None
    baseline_pin_sha: str | None = None
    changed: list[str] = []
    added: list[str] = []
    removed: list[str] = []
    if baseline is not None:
        with zipfile.ZipFile(baseline, "r") as baseline_archive:
            bad_member = baseline_archive.testzip()
            if bad_member is not None:
                raise RuntimeError(f"baseline ZIP CRC failure: {bad_member}")
            baseline_pin_count, baseline_pin_sha = _legacy_pin_digest(baseline_archive)
        if baseline_pin_count != logical or baseline_pin_sha != logical_sha:
            raise RuntimeError(
                "Blueprint pin logical stream differs from baseline: "
                f"baseline_count={baseline_pin_count} current_count={logical} "
                f"baseline_sha256={baseline_pin_sha} current_sha256={logical_sha}"
            )

        baseline_names, baseline_hashes = _archive_member_hashes(baseline)
        bundle_names, bundle_hashes = _archive_member_hashes(bundle)
        baseline_set = set(baseline_names)
        bundle_set = set(bundle_names)
        added = sorted(bundle_set - baseline_set)
        removed = sorted(baseline_set - bundle_set)
        changed = sorted(
            name for name in baseline_set & bundle_set
            if baseline_hashes[name] != bundle_hashes[name]
        )
        if expect_changed is not None:
            actual = set(changed) | set(added) | set(removed)
            if actual != expect_changed:
                raise RuntimeError(
                    "archive diff scope mismatch: "
                    f"expected={sorted(expect_changed)} actual={sorted(actual)}"
                )

    if expect_blueprint_pin_sha256 is not None:
        expected_sha = expect_blueprint_pin_sha256.lower().strip()
        if logical_sha != expected_sha:
            raise RuntimeError(
                "Blueprint pin logical SHA-256 mismatch: "
                f"expected={expected_sha} actual={logical_sha}"
            )

    return {
        "bundle_bytes": bundle_size,
        "raw_bytes": raw_size,
        "members": len(infos),
        "blueprint_pins": logical,
        "blueprint_pin_blocks": blocks,
        "blueprint_pin_logical_sha256": logical_sha,
        "baseline_blueprint_pins": baseline_pin_count,
        "baseline_blueprint_pin_logical_sha256": baseline_pin_sha,
        "blueprint_pins_raw_bytes": pin_info.file_size,
        "blueprint_pins_compressed_bytes": pin_info.compress_size,
        "changed": changed,
        "added": added,
        "removed": removed,
    }


def print_report(result: dict) -> None:
    print("=== UATOOL BUNDLE VERIFY ===")
    print("status: PASS")
    print(
        f"archive: zip_bytes={result['bundle_bytes']} raw_bytes={result['raw_bytes']} "
        f"members={result['members']} crc=ok compression=deflate"
    )
    print(
        f"blueprint pins: logical={result['blueprint_pins']} "
        f"blocks={result['blueprint_pin_blocks']} "
        f"raw_bytes={result['blueprint_pins_raw_bytes']} "
        f"compressed_bytes={result['blueprint_pins_compressed_bytes']}"
    )
    print(
        "blueprint pin logical sha256: "
        f"{result['blueprint_pin_logical_sha256']}"
    )
    if result.get("baseline_blueprint_pins") is not None:
        print(
            "baseline blueprint pins: "
            f"logical={result['baseline_blueprint_pins']} "
            f"sha256={result['baseline_blueprint_pin_logical_sha256']} match=yes"
        )
    if result["changed"] or result["added"] or result["removed"]:
        print("baseline changed: " + ", ".join(result["changed"]))
        if result["added"]:
            print("baseline added: " + ", ".join(result["added"]))
        if result["removed"]:
            print("baseline removed: " + ", ".join(result["removed"]))
    print("source bytes: exact match")
    print("============================")
