#!/usr/bin/env python3
"""Canonical Blueprint user-defined enum support and readable enum rendering."""
from __future__ import annotations

import collections
import json
import sqlite3
import sys
from pathlib import Path

ENUM_SCHEMA_VERSION = 1
MANIFEST_FILE = "blueprint_enum_manifest.json"
RAW_FILES = (
    MANIFEST_FILE,
    "blueprint_enums.jsonl",
    "blueprint_enum_entries.jsonl",
)

_SQL = """
CREATE TABLE blueprint_enums(
 enum_path TEXT PRIMARY KEY,class_path TEXT NOT NULL,cpp_type TEXT NOT NULL,
 display_name TEXT NOT NULL,entry_count INTEGER NOT NULL,contains_existing_max INTEGER NOT NULL,json TEXT NOT NULL
);
CREATE TABLE blueprint_enum_entries(
 enum_path TEXT NOT NULL,enum_index INTEGER NOT NULL,numeric_value INTEGER NOT NULL,
 raw_name TEXT NOT NULL,authored_name TEXT NOT NULL,display_name TEXT NOT NULL,tooltip TEXT NOT NULL,
 hidden INTEGER NOT NULL,is_max INTEGER NOT NULL,json TEXT NOT NULL,
 PRIMARY KEY(enum_path,enum_index)
);
CREATE INDEX bp_enum_entries_raw_idx ON blueprint_enum_entries(enum_path,raw_name);
CREATE INDEX bp_enum_entries_display_idx ON blueprint_enum_entries(enum_path,display_name);
"""


def _rows(path: Path):
    if not path.is_file():
        return
    with path.open("r", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"invalid JSON in {path}:{line_number}: {exc}") from exc
            if not isinstance(row, dict):
                raise RuntimeError(f"expected JSON object in {path}:{line_number}")
            yield row


def read_manifest(output: Path) -> dict | None:
    path = Path(output) / MANIFEST_FILE
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def validation_error(output: Path) -> str | None:
    output = Path(output)
    manifest = read_manifest(output)
    if manifest is None:
        return f"{MANIFEST_FILE} missing or invalid"
    if int(manifest.get("schema_version", 0) or 0) != ENUM_SCHEMA_VERSION:
        return f"unexpected Blueprint enum schema {manifest.get('schema_version')!r}"
    if not bool(manifest.get("success", False)):
        return f"Blueprint enum scanner failed: {manifest.get('error', '')}"

    counts = manifest.get("counts", {})
    if not isinstance(counts, dict):
        return "Blueprint enum manifest counts missing or invalid"
    expected = {
        "blueprint_enums": sum(1 for _ in _rows(output / "blueprint_enums.jsonl") or ()),
        "blueprint_enum_entries": sum(1 for _ in _rows(output / "blueprint_enum_entries.jsonl") or ()),
    }
    for key, actual in expected.items():
        if int(counts.get(key, -1)) != actual:
            return f"Blueprint enum count mismatch for {key}: manifest={counts.get(key)} actual={actual}"
    return None


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SQL)


def load_database(conn: sqlite3.Connection, output: Path) -> None:
    for row in _rows(Path(output) / "blueprint_enums.jsonl") or ():
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_enums VALUES(?,?,?,?,?,?,?)",
            (
                row.get("enum_path", ""),
                row.get("class_path", ""),
                row.get("cpp_type", ""),
                row.get("display_name", ""),
                int(row.get("entry_count", 0) or 0),
                1 if row.get("contains_existing_max", False) else 0,
                json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            ),
        )
    for row in _rows(Path(output) / "blueprint_enum_entries.jsonl") or ():
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_enum_entries VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("enum_path", ""),
                int(row.get("enum_index", 0) or 0),
                int(row.get("numeric_value", 0) or 0),
                row.get("raw_name", ""),
                row.get("authored_name", ""),
                row.get("display_name", ""),
                row.get("tooltip", ""),
                1 if row.get("hidden", False) else 0,
                1 if row.get("is_max", False) else 0,
                json.dumps(row, ensure_ascii=False, separators=(",", ":")),
            ),
        )


def query(conn: sqlite3.Connection, print_rows, pattern: str, limit: int) -> None:
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='blueprint_enum_entries'"
    ).fetchone():
        return
    print("\n[Blueprint enum entries]")
    rows = conn.execute(
        """
        SELECT enum_path,raw_name,authored_name,display_name,numeric_value
        FROM blueprint_enum_entries
        WHERE enum_path LIKE ? OR raw_name LIKE ? OR authored_name LIKE ? OR display_name LIKE ?
        LIMIT ?
        """,
        (pattern, pattern, pattern, pattern, limit),
    )
    print_rows(rows, ("enum_path", "raw_name", "authored_name", "display_name", "numeric_value"))


def _entry_lookup(output: Path) -> dict[tuple[str, str], dict]:
    result: dict[tuple[str, str], dict] = {}
    for row in _rows(Path(output) / "blueprint_enum_entries.jsonl") or ():
        enum_path = str(row.get("enum_path", "") or "")
        raw_name = str(row.get("raw_name", "") or "")
        if enum_path and raw_name:
            result[(enum_path, raw_name)] = row
    return result


def _display_value(lookup: dict[tuple[str, str], dict], enum_path: str, raw: str) -> str:
    if not enum_path or not raw:
        return raw
    row = lookup.get((enum_path, raw))
    if not row:
        return raw
    return str(row.get("display_name", "") or row.get("authored_name", "") or raw)


def _pin_maps(output: Path, core_module):
    by_node_name: dict[str, dict[str, dict]] = collections.defaultdict(dict)
    by_id: dict[str, dict] = {}
    for pin in core_module.iter_blueprint_pin_rows(Path(output)):
        node_id = str(pin.get("node_id", "") or "")
        name = str(pin.get("name", "") or "")
        pin_id = str(pin.get("pin_id", "") or "")
        if node_id and name and name not in by_node_name[node_id]:
            by_node_name[node_id][name] = pin
        if pin_id:
            by_id[pin_id] = pin
    return by_node_name, by_id


def _pin_enum_path(pin: dict | None) -> str:
    if not isinstance(pin, dict):
        return ""
    pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
    return str(pin_type.get("subcategory_object", "") or "")


def _selector_enum_path(node_pins: dict[str, dict], operation: str) -> str:
    if operation != "select":
        return ""
    for name in ("Index", "Selection"):
        enum_path = _pin_enum_path(node_pins.get(name))
        if enum_path:
            return enum_path
    return ""


def _render_expression(expr: dict, lookup, pins_by_node, depth: int = 0, max_depth: int = 8) -> str:
    if not isinstance(expr, dict):
        return ""
    if depth >= max_depth:
        return "..."

    kind = str(expr.get("kind", "") or "")
    if kind == "multi":
        parts = [
            _render_expression(child, lookup, pins_by_node, depth + 1, max_depth)
            for child in expr.get("sources", [])
            if isinstance(child, dict)
        ]
        rendered = [part for part in parts if part]
        return "multi(" + ", ".join(rendered) + ")"

    node_id = str(expr.get("node_id", "") or "")
    operation = str(expr.get("operation", "") or "")
    node_pins = pins_by_node.get(node_id, {})
    selector_enum = _selector_enum_path(node_pins, operation)
    label = str(expr.get("label", "") or operation or kind)
    output_pin = str(expr.get("output_pin", "") or "")
    if kind in {"boundary", "cycle", "truncated", "missing"}:
        suffix = f".{output_pin}" if output_pin else ""
        return f"{kind}:{label}{suffix}"

    args: list[str] = []
    for item in expr.get("inputs", []):
        if not isinstance(item, dict):
            continue
        raw_pin_name = str(item.get("pin", "") or "")
        rendered_pin_name = _display_value(lookup, selector_enum, raw_pin_name)
        if "literal" in item:
            raw_value = str(item.get("literal", "") or "")
            enum_path = _pin_enum_path(node_pins.get(raw_pin_name))
            rendered_value = _display_value(lookup, enum_path, raw_value)
            args.append(f"{rendered_pin_name}={rendered_value}")
            continue
        child_text = [
            _render_expression(child, lookup, pins_by_node, depth + 1, max_depth)
            for child in item.get("sources", [])
            if isinstance(child, dict)
        ]
        child_text = [value for value in child_text if value]
        if child_text:
            rendered_sources = child_text[0] if len(child_text) == 1 else "multi(" + ", ".join(child_text) + ")"
            args.append(f"{rendered_pin_name}={rendered_sources}")

    suffix = f".{output_pin}" if output_pin else ""
    if args:
        return f"{label}({', '.join(args)}){suffix}"
    return f"{label}{suffix}"


def _decorate_dependencies(output: Path, rows: list[dict], core_module) -> list[dict]:
    if not (Path(output) / "blueprint_enum_entries.jsonl").is_file():
        return rows
    lookup = _entry_lookup(output)
    if not lookup:
        return rows
    pins_by_node, _ = _pin_maps(output, core_module)
    for row in rows:
        expr = row.get("expression", {})
        if isinstance(expr, dict):
            row["text"] = _render_expression(expr, lookup, pins_by_node)
    return rows


def _decorate_statements(output: Path, statements: list[dict], blocks: list[dict], statement_module):
    if not (Path(output) / "blueprint_enum_entries.jsonl").is_file():
        return statements, blocks
    lookup = _entry_lookup(output)
    if not lookup:
        return statements, blocks

    by_id: dict[str, dict] = {}
    for statement in statements:
        display_inputs: list[dict] = []
        for item in statement.get("inputs", []) or []:
            if not isinstance(item, dict):
                continue
            rendered = dict(item)
            if rendered.get("source_kind") == "literal":
                pin_type = rendered.get("pin_type", {}) if isinstance(rendered.get("pin_type"), dict) else {}
                enum_path = str(pin_type.get("subcategory_object", "") or "")
                rendered["literal"] = _display_value(
                    lookup,
                    enum_path,
                    str(rendered.get("literal", "") or ""),
                )
            display_inputs.append(rendered)
        statement["text"] = statement_module._statement_text(statement, display_inputs)
        by_id[str(statement.get("statement_id", "") or "")] = statement

    for block in blocks:
        block_statements = [
            by_id.get(str(statement_id or ""))
            for statement_id in block.get("statement_ids", []) or []
        ]
        block["text"] = " ; ".join(
            str(row.get("text", "") or "")
            for row in block_statements
            if isinstance(row, dict) and row.get("text")
        )
    return statements, blocks


def _augment_debug_input_events(output: Path, base_events: list[dict], core_module) -> list[dict]:
    existing = {str(row.get("event_id", "") or "") for row in base_events}
    properties = core_module._node_property_lookup(Path(output))
    pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for pin in core_module.iter_blueprint_pin_rows(Path(output)):
        pins_by_node[str(pin.get("node_id", "") or "")].append(pin)

    rows = list(base_events)
    for node in core_module.iter_jsonl(Path(output) / "blueprint_nodes.jsonl"):
        if str(node.get("operation", "") or "") != "input_debug_key":
            continue
        node_id = str(node.get("node_id", "") or "")
        if not node_id or node_id in existing:
            continue
        props = properties.get(node_id, {})
        sem = node.get("semantic", {}) if isinstance(node.get("semantic"), dict) else {}
        input_name = (
            str(sem.get("input_action", "") or sem.get("action_name", "") or "")
            or core_module._property_value(props, "InputKey", "Key")
        )
        name = str(node.get("symbol", "") or node.get("title", "") or input_name)
        parameters = [
            core_module._pin_signature(pin)
            for pin in pins_by_node.get(node_id, [])
            if core_module._pin_direction_is_output(pin)
            and not core_module._is_exec_pin(pin)
            and pin.get("name") != "OutputDelegate"
        ]
        rows.append({
            "event_id": node_id,
            "blueprint_path": node.get("blueprint_path", ""),
            "graph_id": node.get("graph_id", ""),
            "graph_name": node.get("graph_name", ""),
            "node_class": node.get("node_class", ""),
            "operation": "input_debug_key",
            "event_kind": "input_key",
            "name": name,
            "owner": node.get("owner", ""),
            "component_name": "",
            "delegate_name": "",
            "delegate_owner": "",
            "input_name": input_name,
            "override_function": False,
            "parameters": parameters,
            "consume_input": core_module._property_value(props, "bConsumeInput"),
            "execute_when_paused": core_module._property_value(props, "bExecuteWhenPaused"),
            "override_parent_binding": core_module._property_value(props, "bOverrideParentBinding"),
        })
        existing.add(node_id)
    rows.sort(key=lambda row: (
        str(row.get("blueprint_path", "") or ""),
        str(row.get("graph_id", "") or ""),
        str(row.get("event_id", "") or ""),
    ))
    return rows


def _merge_manifest(output: Path) -> None:
    enum_manifest = read_manifest(output)
    top_path = Path(output) / "manifest.json"
    if not enum_manifest or not top_path.is_file():
        return
    try:
        top = json.loads(top_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(top, dict):
        return
    top["blueprint_enum_schema_version"] = int(enum_manifest.get("schema_version", 0) or 0)
    top["blueprint_enum_counts"] = enum_manifest.get("counts", {})
    top["blueprint_enum_files"] = enum_manifest.get("files", [])
    top["blueprint_enum_pass"] = enum_manifest.get("pass", "UnrealAssetToolBlueprintEnums")
    top_path.write_text(
        json.dumps(top, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def install(core_module, runtime_module=None) -> None:
    if getattr(core_module, "_blueprint_enum_support_installed", False):
        return

    import uatool_blueprint_statements as statement_module

    original_events = core_module.derive_blueprint_events
    original_dependencies = core_module.derive_blueprint_data_dependencies
    original_derive = core_module.derive_output
    original_schema = core_module.create_schema
    original_database = core_module.build_database
    original_query = core_module.query
    original_scan = core_module.scan
    original_statement_derive = statement_module.derive

    def derive_events(output):
        return _augment_debug_input_events(Path(output), original_events(output), core_module)

    def derive_dependencies(output, *args, **kwargs):
        rows = original_dependencies(output, *args, **kwargs)
        return _decorate_dependencies(Path(output), rows, core_module)

    def derive_output(output):
        result = original_derive(output)
        _merge_manifest(Path(output))
        manifest = read_manifest(Path(output))
        if manifest:
            counts = manifest.get("counts", {}) if isinstance(manifest.get("counts", {}), dict) else {}
            print(
                "blueprint enums: "
                f"enums={counts.get('blueprint_enums', 0)} "
                f"entries={counts.get('blueprint_enum_entries', 0)}"
            )
        return result

    def schema_wrapper(conn):
        original_schema(conn)
        create_schema(conn)

    def build_database(output):
        db = original_database(output)
        conn = sqlite3.connect(db)
        try:
            load_database(conn, Path(output))
            conn.commit()
        finally:
            conn.close()
        return db

    def query_wrapper(args):
        result = int(original_query(args))
        root = Path(args.output).expanduser().resolve()
        db = root if root.suffix.lower() == ".db" else root / core_module.DB_NAME
        if db.is_file():
            conn = sqlite3.connect(db)
            conn.row_factory = sqlite3.Row
            try:
                query(conn, core_module._print_rows, f"%{args.term}%", args.limit)
            finally:
                conn.close()
        return result

    def scan_wrapper(args):
        if runtime_module is not None and hasattr(runtime_module, "_output"):
            output = runtime_module._output(args)
        else:
            project = Path(args.project).expanduser().resolve()
            output = Path(args.output).expanduser().resolve() if args.output else project.parent / ".uatool"
        output = Path(output).expanduser().resolve()
        # A failed/old staged binary must not make a new scan look successful
        # by leaving a previous enum manifest or data stream behind.
        for filename in RAW_FILES:
            (output / filename).unlink(missing_ok=True)
        result = int(original_scan(args))
        if result != 0:
            return result
        error = validation_error(output)
        if error:
            print(f"ERROR: Blueprint enum scan incomplete: {error}", file=sys.stderr)
            return 35
        return 0

    def statement_derive(output, rows):
        statements, blocks = original_statement_derive(output, rows)
        return _decorate_statements(Path(output), statements, blocks, statement_module)

    core_module.derive_blueprint_events = derive_events
    core_module.derive_blueprint_data_dependencies = derive_dependencies
    core_module.derive_output = derive_output
    core_module.create_schema = schema_wrapper
    core_module.build_database = build_database
    core_module.query = query_wrapper
    core_module.scan = scan_wrapper
    core_module.DEFAULT_BUNDLE_FILES = tuple(dict.fromkeys((*core_module.DEFAULT_BUNDLE_FILES, *RAW_FILES)))
    statement_module.derive = statement_derive
    core_module._blueprint_enum_support_installed = True
