#!/usr/bin/env python3
"""Enhanced Input processor validation for sparse/null processor arrays.

Unreal InputAction and mapping rows expose the physical Triggers/Modifiers array
length. input_processors.jsonl intentionally emits only populated UObject slots
and preserves each populated slot's original processor_index. A null authored
slot therefore makes populated processor rows fewer than the declared slot count
without making the canonical scan inconsistent.
"""
from __future__ import annotations

import collections
from pathlib import Path


def validate_processor_topology(actions: list[dict], mappings: list[dict], processors: list[dict]) -> str | None:
    action_by_path = {str(row.get("action_path", "")): row for row in actions}
    mapping_by_key = {
        (str(row.get("context_path", "")), int(row.get("mapping_index", -1))): row
        for row in mappings
    }
    seen: set[tuple[str, str, int, str, int]] = set()

    for row in processors:
        scope = str(row.get("owner_scope", ""))
        kind = str(row.get("processor_kind", ""))
        asset_path = str(row.get("asset_path", ""))
        mapping_index = int(row.get("mapping_index", -1))
        processor_index = int(row.get("processor_index", -1))

        if scope not in {"action", "mapping"}:
            return f"input processor has invalid owner_scope: {scope!r}"
        if kind not in {"trigger", "modifier"}:
            return f"input processor has invalid processor_kind: {kind!r}"
        if processor_index < 0:
            return f"input processor has negative processor_index: {asset_path} {scope} {kind} {processor_index}"
        if not str(row.get("processor_path", "")) or not str(row.get("processor_class", "")):
            return f"input processor populated slot is missing object identity: {asset_path} {scope} {kind} {processor_index}"

        identity = (asset_path, scope, mapping_index, kind, processor_index)
        if identity in seen:
            return f"duplicate input processor slot identity: {identity}"
        seen.add(identity)

        if scope == "action":
            if mapping_index != -1:
                return f"InputAction processor has unexpected mapping_index: {asset_path} {mapping_index}"
            owner = action_by_path.get(asset_path)
            if owner is None:
                return f"input processor references unknown InputAction: {asset_path}"
        else:
            owner = mapping_by_key.get((asset_path, mapping_index))
            if owner is None:
                return f"input processor references unknown input mapping: {(asset_path, mapping_index)}"

        declared = int(owner.get(f"{kind}_count", 0) or 0)
        if processor_index >= declared:
            label = "InputAction" if scope == "action" else "input mapping"
            return (
                f"{label} {kind} processor_index out of bounds: "
                f"owner={asset_path} mapping_index={mapping_index} "
                f"index={processor_index} declared_slots={declared}"
            )

    return None


def _populated_counts(processors: list[dict]):
    action = collections.Counter()
    mapping = collections.Counter()
    for row in processors:
        scope = str(row.get("owner_scope", ""))
        kind = str(row.get("processor_kind", ""))
        asset_path = str(row.get("asset_path", ""))
        if scope == "action":
            action[(asset_path, kind)] += 1
        elif scope == "mapping":
            mapping[(asset_path, int(row.get("mapping_index", -1)), kind)] += 1
    return action, mapping


def install(systems_module) -> None:
    """Patch the legacy equality invariant while preserving every other check."""
    if getattr(systems_module, "_sparse_input_processor_validation_installed", False):
        return

    original_validation = systems_module.validation_error
    original_rows = systems_module._rows

    def validation_error(output: Path) -> str | None:
        output = Path(output)
        actions = list(original_rows(output / "input_actions.jsonl"))
        mappings = list(original_rows(output / "input_mappings.jsonl"))
        processors = list(original_rows(output / "input_processors.jsonl"))

        error = validate_processor_topology(actions, mappings, processors)
        if error:
            return error

        action_counts, mapping_counts = _populated_counts(processors)

        def validation_rows(path: Path):
            path = Path(path)
            name = path.name
            if name == "input_actions.jsonl":
                for row in original_rows(path):
                    copy = dict(row)
                    asset_path = str(copy.get("action_path", ""))
                    copy["trigger_count"] = action_counts[(asset_path, "trigger")]
                    copy["modifier_count"] = action_counts[(asset_path, "modifier")]
                    yield copy
                return
            if name == "input_mappings.jsonl":
                for row in original_rows(path):
                    copy = dict(row)
                    key = (str(copy.get("context_path", "")), int(copy.get("mapping_index", -1)))
                    copy["trigger_count"] = mapping_counts[(key[0], key[1], "trigger")]
                    copy["modifier_count"] = mapping_counts[(key[0], key[1], "modifier")]
                    yield copy
                return
            yield from original_rows(path)

        systems_module._rows = validation_rows
        try:
            return original_validation(output)
        finally:
            systems_module._rows = original_rows

    systems_module.validation_error = validation_error
    systems_module._sparse_input_processor_validation_installed = True
