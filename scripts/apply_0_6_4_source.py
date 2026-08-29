#!/usr/bin/env python3
"""Apply the UnrealAssetTool 0.6.4-dev scanner-schema-11 source update.

This updater is intentionally narrow and idempotent. It modifies only
Source/UnrealAssetTool/Private/UnrealAssetToolCommandlet.cpp in an existing
0.6.3/current-main checkout, adding exact UE 5.8 struct-node semantics and
bumping the scanner schema from 10 to 11.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sys

STRUCT_INCLUDES = '''#include "K2Node_BreakStruct.h"\n#include "K2Node_MakeStruct.h"\n#include "K2Node_SetFieldsInStruct.h"\n#include "K2Node_StructOperation.h"\n'''

STRUCT_BRANCH = r'''        else if (UK2Node_StructOperation* StructOperation = Cast<UK2Node_StructOperation>(Node))
        {
            // UK2Node_MakeStruct, UK2Node_BreakStruct, and
            // UK2Node_SetFieldsInStruct all inherit UK2Node_Variable through
            // UK2Node_StructOperation. Classify them before the generic
            // UK2Node_Variable fallback so they are not emitted as bogus
            // variable_reference nodes with member_name=None.
            if (Cast<UK2Node_SetFieldsInStruct>(Node))
            {
                OutOperation = TEXT("set_fields_in_struct");
            }
            else if (Cast<UK2Node_MakeStruct>(Node))
            {
                OutOperation = TEXT("make_struct");
            }
            else if (Cast<UK2Node_BreakStruct>(Node))
            {
                OutOperation = TEXT("break_struct");
            }
            else
            {
                OutOperation = TEXT("struct_operation");
            }

            if (UScriptStruct* StructType = StructOperation->StructType.Get())
            {
                OutSymbol = StructType->GetName();
                OutOwner = StructType->GetPathName();
                Semantic->SetStringField(TEXT("struct_type"), OutOwner);
                Semantic->SetStringField(TEXT("struct_name"), OutSymbol);
            }
            Semantic->SetBoolField(TEXT("pure"), StructOperation->IsNodePure());
            Semantic->SetStringField(TEXT("classification_source"), TEXT("node_class"));
            Semantic->SetStringField(TEXT("concrete_node_class"), Node->GetClass()->GetPathName());
        }
'''


def find_repo_root(start: Path) -> Path:
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / "UnrealAssetTool.uplugin").is_file() and (candidate / "Source" / "UnrealAssetTool").is_dir():
            return candidate
    raise FileNotFoundError(
        "Could not find UnrealAssetTool.uplugin and Source/UnrealAssetTool above "
        f"{start}"
    )


def update_source(root: Path, *, make_backup: bool = True) -> Path:
    source = root / "Source" / "UnrealAssetTool" / "Private" / "UnrealAssetToolCommandlet.cpp"
    if not source.is_file():
        raise FileNotFoundError(source)

    text = source.read_text(encoding="utf-8")

    already_schema11 = "static constexpr int32 SchemaVersion = 11;" in text
    already_branch = 'OutOperation = TEXT("set_fields_in_struct");' in text and 'Semantic->SetStringField(TEXT("struct_type"), OutOwner);' in text
    already_includes = all(line in text for line in STRUCT_INCLUDES.strip().splitlines())
    if already_schema11 and already_branch and already_includes:
        print(f"schema-11 source already ready: {source}")
        return source

    # Refuse to guess against an unrelated/older source shape.
    required_markers = [
        'static constexpr int32 SchemaVersion = 10;',
        '#include "K2Node_MacroInstance.h"',
        '        else if (UK2Node_VariableGet* VariableGet = Cast<UK2Node_VariableGet>(Node))\n',
        '        ApplyClassSemanticFallback(Node, Semantic, OutOperation, OutSymbol, OutOwner);',
    ]
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        raise RuntimeError(
            "The commandlet source does not match the expected current-main/schema-10 shape.\n"
            "No file was modified. Missing marker(s):\n  " + "\n  ".join(repr(m) for m in missing)
        )

    updated = text
    updated = updated.replace(
        '#include "K2Node_MacroInstance.h"\n',
        '#include "K2Node_MacroInstance.h"\n' + STRUCT_INCLUDES,
        1,
    )
    updated = updated.replace(
        'static constexpr int32 SchemaVersion = 10;',
        'static constexpr int32 SchemaVersion = 11;',
        1,
    )
    marker = '        else if (UK2Node_VariableGet* VariableGet = Cast<UK2Node_VariableGet>(Node))\n'
    updated = updated.replace(marker, STRUCT_BRANCH + marker, 1)

    if updated == text:
        raise RuntimeError("No source changes were produced; refusing to overwrite the file.")

    # Sanity checks on the generated source.
    checks = [
        'static constexpr int32 SchemaVersion = 11;',
        '#include "K2Node_StructOperation.h"',
        'OutOperation = TEXT("make_struct");',
        'OutOperation = TEXT("break_struct");',
        'OutOperation = TEXT("set_fields_in_struct");',
        'Semantic->SetStringField(TEXT("struct_type"), OutOwner);',
    ]
    for check in checks:
        if updated.count(check) != 1:
            raise RuntimeError(f"Generated source failed uniqueness check for: {check}")

    if make_backup:
        backup = source.with_suffix(source.suffix + ".pre-0.6.4-dev")
        if not backup.exists():
            shutil.copy2(source, backup)
            print(f"backup: {backup}")

    source.write_text(updated, encoding="utf-8", newline="\n")
    print(f"updated scanner source: {source}")
    print("scanner schema: 11")
    print("struct semantics: make_struct, break_struct, set_fields_in_struct")
    return source


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "repo",
        nargs="?",
        default=str(Path(__file__).resolve().parent.parent),
        help="UnrealAssetTool checkout root (defaults to the checkout containing this script)",
    )
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args()

    requested = Path(args.repo).expanduser()
    root = requested.resolve() if (requested / "UnrealAssetTool.uplugin").is_file() else find_repo_root(requested)
    update_source(root, make_backup=not args.no_backup)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"schema11 updater: error: {exc}", file=sys.stderr)
        raise SystemExit(1)
