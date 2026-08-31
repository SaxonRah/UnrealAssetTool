#!/usr/bin/env python3
"""Generic Blueprint statement derivation over semantic nodes and provenance.

This is Phase 2 of Blueprint semantic derivation.  It does not re-traverse K2
classes and it does not contain gameplay-domain knowledge.  Existing canonical
pins, semantic nodes, recursive data dependencies, and execution basic blocks
remain authoritative.  This layer joins those facts into compact human/AI-useful
statements while retaining exact node/pin/dependency/block provenance.
"""
from __future__ import annotations

import collections
import hashlib
import json
from pathlib import Path

STATEMENT_SCHEMA_VERSION = 1
DERIVED_FILES = (
    "blueprint_semantic_statements.jsonl",
    "blueprint_semantic_blocks.jsonl",
)

_SQL = """
CREATE TABLE blueprint_semantic_statements(
 statement_id TEXT PRIMARY KEY,node_id TEXT NOT NULL UNIQUE,blueprint_path TEXT NOT NULL,
 graph_id TEXT NOT NULL,graph_name TEXT NOT NULL,block_id TEXT NOT NULL,block_position INTEGER NOT NULL,
 operation TEXT NOT NULL,semantic_kind TEXT NOT NULL,primary_effect TEXT NOT NULL,
 symbol TEXT NOT NULL,owner TEXT NOT NULL,target_kind TEXT NOT NULL,target TEXT NOT NULL,
 input_count INTEGER NOT NULL,dependency_count INTEGER NOT NULL,literal_count INTEGER NOT NULL,
 dependency_ids_json TEXT NOT NULL,inputs_json TEXT NOT NULL,text TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX bp_sem_stmt_blueprint_idx ON blueprint_semantic_statements(blueprint_path,graph_id);
CREATE INDEX bp_sem_stmt_block_idx ON blueprint_semantic_statements(block_id,block_position);
CREATE INDEX bp_sem_stmt_operation_idx ON blueprint_semantic_statements(operation,primary_effect);
CREATE INDEX bp_sem_stmt_symbol_idx ON blueprint_semantic_statements(symbol,owner,target);

CREATE TABLE blueprint_semantic_blocks(
 block_id TEXT PRIMARY KEY,blueprint_path TEXT NOT NULL,graph_id TEXT NOT NULL,graph_name TEXT NOT NULL,
 block_index INTEGER NOT NULL,node_count INTEGER NOT NULL,statement_count INTEGER NOT NULL,
 statement_ids_json TEXT NOT NULL,operations_json TEXT NOT NULL,call_count INTEGER NOT NULL,
 write_count INTEGER NOT NULL,branch_count INTEGER NOT NULL,text TEXT NOT NULL,json TEXT NOT NULL
);
CREATE INDEX bp_sem_blocks_blueprint_idx ON blueprint_semantic_blocks(blueprint_path,graph_id,block_index);
"""

_BOUNDARY_OPERATIONS = {
    "function_entry",
    "function_result",
    "event",
    "custom_event",
    "anim_graph_root",
    "anim_state_result",
    "anim_transition_result",
}


def _j(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _id(prefix: str, *parts: str) -> str:
    basis = "\x1f".join(str(part or "") for part in parts)
    return prefix + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:24]


def _is_exec_pin(pin: dict) -> bool:
    pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
    return str(pin_type.get("category", "") or "").lower() == "exec"


def _is_input_pin(pin: dict) -> bool:
    return str(pin.get("direction", "") or "").lower() in {"input", "egpd_input", "0"}


def _literal_value(pin: dict) -> tuple[str, str]:
    obj = str(pin.get("default_object", "") or "")
    if obj:
        return obj, "object"
    value = str(pin.get("default_value", "") or "")
    if value:
        return value, "value"
    text = str(pin.get("default_text", "") or "")
    if text:
        return text, "text"
    return "", ""


def _is_statement(node: dict) -> bool:
    if bool(node.get("has_exec_flow", False)):
        return True
    return str(node.get("operation", "") or "") in _BOUNDARY_OPERATIONS


def _input_text(item: dict) -> str:
    name = str(item.get("pin_name", "") or "")
    if item.get("source_kind") == "dependency":
        value = str(item.get("expression_text", "") or "")
    else:
        value = str(item.get("literal", "") or "")
    if not value:
        return ""
    return f"{name}={value}" if name else value


def _statement_text(node: dict, inputs: list[dict]) -> str:
    operation = str(node.get("operation", "") or "node")
    symbol = str(node.get("symbol", "") or "")
    target = str(node.get("target", "") or "")
    rendered = [text for text in (_input_text(item) for item in inputs) if text]

    def first_named(*names: str) -> str:
        wanted = {name.lower() for name in names}
        for item in inputs:
            if str(item.get("pin_name", "") or "").lower() in wanted:
                return _input_text(item).split("=", 1)[-1]
        return ""

    if operation in {"event", "custom_event"}:
        return f"event {symbol or target}".rstrip()
    if operation == "function_entry":
        return f"function {symbol or target}".rstrip()
    if operation == "function_result":
        return "return" + (" " + ", ".join(rendered) if rendered else "")
    if operation in {"anim_graph_root", "anim_state_result", "anim_transition_result"}:
        label = {
            "anim_graph_root": "animation output",
            "anim_state_result": "state output",
            "anim_transition_result": "transition result",
        }[operation]
        return label + (" " + ", ".join(rendered) if rendered else "")
    if operation == "branch":
        condition = first_named("Condition") or (rendered[0].split("=", 1)[-1] if rendered else "")
        return f"if {condition}".rstrip()
    if operation == "switch":
        selection = first_named("Selection", "Index") or (rendered[0].split("=", 1)[-1] if rendered else "")
        return f"switch {selection}".rstrip()
    if operation == "execution_sequence":
        return "sequence"
    if operation == "variable_set":
        meaningful = [item for item in inputs if str(item.get("pin_name", "") or "").lower() not in {"self", "target"}]
        if len(meaningful) == 1:
            rhs = _input_text(meaningful[0]).split("=", 1)[-1]
            if rhs:
                return f"{symbol or target} = {rhs}".strip()
        return f"set {symbol or target}".rstrip() + (f"({', '.join(rendered)})" if rendered else "")
    if operation == "function_call":
        name = symbol or target or "call"
        return f"{name}({', '.join(rendered)})"
    if operation == "spawn_actor":
        return f"spawn {target or symbol}".rstrip() + (f"({', '.join(rendered)})" if rendered else "")
    if operation == "dynamic_cast":
        return f"cast to {target or symbol}".rstrip() + (f"({', '.join(rendered)})" if rendered else "")
    if operation == "set_fields_in_struct":
        return f"set fields {target or symbol}".rstrip() + (f"({', '.join(rendered)})" if rendered else "")
    if operation == "macro_instance":
        return f"macro {symbol or target}".rstrip() + (f"({', '.join(rendered)})" if rendered else "")

    label = symbol or target or operation
    return label + (f"({', '.join(rendered)})" if rendered else "")


def derive(output: Path, rows) -> tuple[list[dict], list[dict]]:
    output = Path(output)
    semantic_nodes = list(rows(output / "blueprint_semantic_nodes.jsonl"))
    dependencies = list(rows(output / "blueprint_data_dependencies.jsonl"))
    execution_blocks = list(rows(output / "blueprint_execution_blocks.jsonl"))
    execution_block_edges = list(rows(output / "blueprint_execution_block_edges.jsonl"))
    pins = list(rows(output / "blueprint_pins.jsonl"))

    pins_by_node: dict[str, list[dict]] = collections.defaultdict(list)
    for pin in pins:
        node_id = str(pin.get("node_id", "") or "")
        if node_id:
            pins_by_node[node_id].append(pin)
    for node_pins in pins_by_node.values():
        node_pins.sort(key=lambda row: int(row.get("pin_index", 0) or 0))

    dependency_by_pin: dict[str, dict] = {}
    for dep in dependencies:
        dep_id = str(dep.get("dependency_id", "") or "")
        pin_id = str(dep.get("sink_pin_id", "") or "")
        if not dep_id or not pin_id:
            continue
        if pin_id in dependency_by_pin:
            raise RuntimeError(f"multiple Blueprint data dependencies for sink pin: {pin_id}")
        dependency_by_pin[pin_id] = dep

    block_info_by_node: dict[str, tuple[str, int]] = {}
    block_by_id: dict[str, dict] = {}
    for block in execution_blocks:
        block_id = str(block.get("block_id", "") or "")
        if not block_id:
            continue
        if block_id in block_by_id:
            raise RuntimeError(f"duplicate Blueprint execution block: {block_id}")
        block_by_id[block_id] = block
        node_ids = block.get("node_ids", []) if isinstance(block.get("node_ids"), list) else []
        for position, node_id_value in enumerate(node_ids):
            node_id = str(node_id_value or "")
            if not node_id:
                continue
            if node_id in block_info_by_node:
                raise RuntimeError(f"Blueprint node belongs to multiple execution blocks: {node_id}")
            block_info_by_node[node_id] = (block_id, position)

    statements: list[dict] = []
    statement_by_node: dict[str, dict] = {}
    for node in semantic_nodes:
        if not _is_statement(node):
            continue
        node_id = str(node.get("node_id", "") or "")
        block_id, block_position = block_info_by_node.get(node_id, ("", -1))
        input_rows: list[dict] = []
        used_dependencies: list[str] = []
        literal_count = 0
        declared_input_count = 0
        for pin in pins_by_node.get(node_id, []):
            if not _is_input_pin(pin) or _is_exec_pin(pin):
                continue
            declared_input_count += 1
            pin_id = str(pin.get("pin_id", "") or "")
            pin_type = pin.get("type", {}) if isinstance(pin.get("type"), dict) else {}
            dep = dependency_by_pin.get(pin_id)
            if dep:
                dep_id = str(dep.get("dependency_id", "") or "")
                used_dependencies.append(dep_id)
                input_rows.append({
                    "pin_id": pin_id,
                    "pin_name": str(pin.get("name", "") or ""),
                    "pin_type": pin_type,
                    "source_kind": "dependency",
                    "dependency_id": dep_id,
                    "expression_text": str(dep.get("text", "") or ""),
                    "expression_node_count": int(dep.get("expression_node_count", 0) or 0),
                    "truncated": bool(dep.get("truncated", False)),
                    "cycle": bool(dep.get("cycle", False)),
                })
                continue
            literal, literal_kind = _literal_value(pin)
            if literal:
                literal_count += 1
                input_rows.append({
                    "pin_id": pin_id,
                    "pin_name": str(pin.get("name", "") or ""),
                    "pin_type": pin_type,
                    "source_kind": "literal",
                    "literal_kind": literal_kind,
                    "literal": literal,
                })

        statement_id = _id("bpstmt:", node_id)
        statement = {
            "statement_id": statement_id,
            "node_id": node_id,
            "blueprint_path": str(node.get("blueprint_path", "") or ""),
            "graph_id": str(node.get("graph_id", "") or ""),
            "graph_name": str(node.get("graph_name", "") or ""),
            "block_id": block_id,
            "block_position": block_position,
            "operation": str(node.get("operation", "") or ""),
            "semantic_kind": str(node.get("semantic_kind", "") or ""),
            "primary_effect": str(node.get("primary_effect", "") or ""),
            "symbol": str(node.get("symbol", "") or ""),
            "owner": str(node.get("owner", "") or ""),
            "target_kind": str(node.get("target_kind", "") or ""),
            "target": str(node.get("target", "") or ""),
            "input_count": declared_input_count,
            "dependency_count": len(used_dependencies),
            "literal_count": literal_count,
            "dependency_ids": used_dependencies,
            "inputs": input_rows,
        }
        statement["text"] = _statement_text(statement, input_rows)
        statements.append(statement)
        statement_by_node[node_id] = statement

    outgoing_by_block = collections.Counter(
        str(edge.get("source_block_id", "") or "")
        for edge in execution_block_edges
        if edge.get("source_block_id")
    )
    semantic_blocks: list[dict] = []
    for block in execution_blocks:
        block_id = str(block.get("block_id", "") or "")
        node_ids = [str(value or "") for value in block.get("node_ids", [])] if isinstance(block.get("node_ids"), list) else []
        block_statements = [statement_by_node[node_id] for node_id in node_ids if node_id in statement_by_node]
        operations = [str(row.get("operation", "") or "") for row in block_statements]
        semantic_blocks.append({
            "block_id": block_id,
            "blueprint_path": str(block.get("blueprint_path", "") or ""),
            "graph_id": str(block.get("graph_id", "") or ""),
            "graph_name": str(block.get("graph_name", "") or ""),
            "block_index": int(block.get("block_index", 0) or 0),
            "node_count": int(block.get("node_count", len(node_ids)) or 0),
            "statement_count": len(block_statements),
            "statement_ids": [str(row.get("statement_id", "") or "") for row in block_statements],
            "operations": operations,
            "call_count": sum(1 for row in block_statements if row.get("primary_effect") == "call"),
            "write_count": sum(1 for row in block_statements if row.get("primary_effect") == "write"),
            "branch_count": sum(1 for row in block_statements if row.get("primary_effect") == "branch"),
            "outgoing_block_count": int(outgoing_by_block[block_id]),
            "text": " ; ".join(str(row.get("text", "") or "") for row in block_statements if row.get("text")),
        })

    statements.sort(key=lambda row: (row["blueprint_path"], row["graph_id"], row["block_id"], row["block_position"], row["node_id"]))
    semantic_blocks.sort(key=lambda row: (row["blueprint_path"], row["graph_id"], row["block_index"], row["block_id"]))
    return statements, semantic_blocks


def validation_error(output: Path, rows) -> str | None:
    output = Path(output)
    semantic_nodes = list(rows(output / "blueprint_semantic_nodes.jsonl"))
    dependencies = list(rows(output / "blueprint_data_dependencies.jsonl"))
    execution_blocks = list(rows(output / "blueprint_execution_blocks.jsonl"))
    statements = list(rows(output / "blueprint_semantic_statements.jsonl"))
    semantic_blocks = list(rows(output / "blueprint_semantic_blocks.jsonl"))

    expected_statement_nodes = {
        str(row.get("node_id", "") or "")
        for row in semantic_nodes
        if _is_statement(row)
    }
    statement_nodes = [str(row.get("node_id", "") or "") for row in statements]
    if len(statement_nodes) != len(set(statement_nodes)):
        return "duplicate Blueprint semantic statement node_id"
    if set(statement_nodes) != expected_statement_nodes:
        return (
            "Blueprint semantic statements do not exactly cover statement-bearing semantic nodes: "
            f"expected={len(expected_statement_nodes)} actual={len(set(statement_nodes))}"
        )

    dependency_by_id = {
        str(row.get("dependency_id", "") or ""): row
        for row in dependencies
        if row.get("dependency_id")
    }
    for statement in statements:
        node_id = str(statement.get("node_id", "") or "")
        for dep_id_value in statement.get("dependency_ids", []) if isinstance(statement.get("dependency_ids"), list) else []:
            dep_id = str(dep_id_value or "")
            dep = dependency_by_id.get(dep_id)
            if not dep:
                return f"Blueprint semantic statement references missing dependency: {dep_id}"
            if str(dep.get("sink_node_id", "") or "") != node_id:
                return f"Blueprint semantic statement dependency sink mismatch: {dep_id}"

    block_by_id = {str(row.get("block_id", "") or ""): row for row in execution_blocks if row.get("block_id")}
    semantic_block_by_id = {str(row.get("block_id", "") or ""): row for row in semantic_blocks if row.get("block_id")}
    if len(semantic_block_by_id) != len(semantic_blocks):
        return "duplicate Blueprint semantic block_id"
    if set(semantic_block_by_id) != set(block_by_id):
        return "Blueprint semantic blocks do not exactly cover execution blocks"

    statement_by_node = {str(row.get("node_id", "") or ""): row for row in statements}
    for block_id, block in block_by_id.items():
        node_ids = [str(value or "") for value in block.get("node_ids", [])] if isinstance(block.get("node_ids"), list) else []
        expected_ids = [str(statement_by_node[node_id].get("statement_id", "") or "") for node_id in node_ids if node_id in statement_by_node]
        actual = semantic_block_by_id[block_id]
        actual_ids = [str(value or "") for value in actual.get("statement_ids", [])] if isinstance(actual.get("statement_ids"), list) else []
        if actual_ids != expected_ids:
            return f"Blueprint semantic block statement order mismatch: {block_id}"
        if int(actual.get("statement_count", -1)) != len(expected_ids):
            return f"Blueprint semantic block statement_count mismatch: {block_id}"
    return None


def create_schema(conn) -> None:
    conn.executescript(_SQL)


def load_database(conn, output: Path, rows) -> None:
    for row in rows(Path(output) / "blueprint_semantic_statements.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_semantic_statements VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("statement_id", ""), row.get("node_id", ""), row.get("blueprint_path", ""),
                row.get("graph_id", ""), row.get("graph_name", ""), row.get("block_id", ""),
                int(row.get("block_position", -1)), row.get("operation", ""), row.get("semantic_kind", ""),
                row.get("primary_effect", ""), row.get("symbol", ""), row.get("owner", ""),
                row.get("target_kind", ""), row.get("target", ""), int(row.get("input_count", 0) or 0),
                int(row.get("dependency_count", 0) or 0), int(row.get("literal_count", 0) or 0),
                _j(row.get("dependency_ids", [])), _j(row.get("inputs", [])), row.get("text", ""), _j(row),
            ),
        )
    for row in rows(Path(output) / "blueprint_semantic_blocks.jsonl"):
        conn.execute(
            "INSERT OR REPLACE INTO blueprint_semantic_blocks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                row.get("block_id", ""), row.get("blueprint_path", ""), row.get("graph_id", ""),
                row.get("graph_name", ""), int(row.get("block_index", 0) or 0), int(row.get("node_count", 0) or 0),
                int(row.get("statement_count", 0) or 0), _j(row.get("statement_ids", [])),
                _j(row.get("operations", [])), int(row.get("call_count", 0) or 0),
                int(row.get("write_count", 0) or 0), int(row.get("branch_count", 0) or 0),
                row.get("text", ""), _j(row),
            ),
        )


def query(conn, print_rows, pattern: str, limit: int) -> None:
    print("\n[blueprint semantic statements]")
    print_rows(
        conn.execute(
            """
            SELECT blueprint_path,graph_name,block_id,block_position,operation,primary_effect,symbol,target,text
            FROM blueprint_semantic_statements
            WHERE blueprint_path LIKE ? OR graph_name LIKE ? OR operation LIKE ? OR symbol LIKE ? OR target LIKE ? OR text LIKE ?
            ORDER BY blueprint_path,graph_id,block_id,block_position
            LIMIT ?
            """,
            (pattern,) * 6 + (limit,),
        ),
        ("blueprint_path","graph_name","block_id","block_position","operation","primary_effect","symbol","target","text"),
    )
    print("\n[blueprint semantic blocks]")
    print_rows(
        conn.execute(
            """
            SELECT blueprint_path,graph_name,block_index,node_count,statement_count,call_count,write_count,branch_count,text
            FROM blueprint_semantic_blocks
            WHERE blueprint_path LIKE ? OR graph_name LIKE ? OR operations_json LIKE ? OR text LIKE ?
            ORDER BY blueprint_path,graph_id,block_index
            LIMIT ?
            """,
            (pattern,) * 4 + (limit,),
        ),
        ("blueprint_path","graph_name","block_index","node_count","statement_count","call_count","write_count","branch_count","text"),
    )
