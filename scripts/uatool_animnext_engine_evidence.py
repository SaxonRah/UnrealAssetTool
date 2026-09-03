#!/usr/bin/env python3
"""Read-only inventory of installed UE AnimNext/UAF plugin content.

This probe does not launch Unreal. It inspects the selected UE installation on
disk to determine whether Epic ships representative UAF/AnimNext plugin content
that can be used as the next evidence corpus.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ASSET_SUFFIXES = (".uasset", ".umap")
ROOT_CANDIDATES = (
    Path("Plugins/Experimental/UAF"),
    Path("Plugins/Experimental/AnimNext"),
)


def _engine_dir_from_editor(editor: Path) -> Path:
    editor = Path(editor).expanduser().resolve()
    for parent in (editor.parent, *editor.parents):
        if parent.name.lower() == "engine":
            return parent
    raise ValueError(f"editor path is not inside an Engine directory: {editor}")


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _plugin_record(engine_dir: Path, descriptor: Path) -> dict:
    data = _read_json(descriptor)
    plugin_dir = descriptor.parent
    content_dir = plugin_dir / "Content"
    assets = []
    if content_dir.is_dir():
        for path in sorted(content_dir.rglob("*")):
            if path.is_file() and path.suffix.lower() in ASSET_SUFFIXES:
                assets.append(path.relative_to(engine_dir).as_posix())
    modules = []
    for item in data.get("Modules", []) or []:
        if isinstance(item, dict):
            modules.append({
                "name": str(item.get("Name", "") or ""),
                "type": str(item.get("Type", "") or ""),
                "loading_phase": str(item.get("LoadingPhase", "") or ""),
            })
    dependencies = []
    for item in data.get("Plugins", []) or []:
        if isinstance(item, dict):
            dependencies.append({
                "name": str(item.get("Name", "") or ""),
                "enabled": bool(item.get("Enabled", False)),
                "optional": bool(item.get("Optional", False)),
            })
    return {
        "descriptor": descriptor.relative_to(engine_dir).as_posix(),
        "plugin_name": descriptor.stem,
        "friendly_name": str(data.get("FriendlyName", "") or ""),
        "category": str(data.get("Category", "") or ""),
        "can_contain_content": bool(data.get("CanContainContent", False)),
        "enabled_by_default": data.get("EnabledByDefault", None),
        "is_experimental": bool(data.get("IsExperimentalVersion", False)),
        "content_dir_exists": content_dir.is_dir(),
        "asset_count": len(assets),
        "assets": assets,
        "modules": modules,
        "dependencies": dependencies,
    }


def build_report(editor: Path) -> dict:
    editor = Path(editor).expanduser().resolve()
    engine_dir = _engine_dir_from_editor(editor)
    roots = [engine_dir / rel for rel in ROOT_CANDIDATES if (engine_dir / rel).is_dir()]
    descriptors = []
    for root in roots:
        descriptors.extend(sorted(root.rglob("*.uplugin")))
    records = [_plugin_record(engine_dir, path) for path in sorted(set(descriptors))]
    content_plugins = [row for row in records if row["asset_count"] > 0]
    total_assets = sum(int(row["asset_count"]) for row in records)
    test_like_assets = []
    sample_like_assets = []
    for row in records:
        plugin_name = row["plugin_name"].lower()
        for asset in row["assets"]:
            lower = asset.lower()
            if "test" in plugin_name or "/test" in lower or "/tests" in lower:
                test_like_assets.append(asset)
            if any(token in lower for token in ("example", "sample", "demo", "tutorial")):
                sample_like_assets.append(asset)
    return {
        "editor": str(editor),
        "engine_dir": str(engine_dir),
        "diagnostic_only": True,
        "unreal_was_run": False,
        "schema_promotion": False,
        "runtime_state_captured": False,
        "uaf_roots": [str(path) for path in roots],
        "plugin_count": len(records),
        "content_plugin_count": len(content_plugins),
        "total_content_assets": total_assets,
        "test_like_asset_count": len(test_like_assets),
        "sample_like_asset_count": len(sample_like_assets),
        "test_like_assets": test_like_assets,
        "sample_like_assets": sample_like_assets,
        "plugins": records,
    }


def render_report(report: dict) -> str:
    lines = [
        "=== ANIMNEXT / UAF INSTALLED ENGINE EVIDENCE ===",
        f"editor={report['editor']}",
        f"engine_dir={report['engine_dir']}",
        "diagnostic_only=True unreal_was_run=False schema_promotion=False runtime_state_captured=False",
        f"uaf_roots={len(report['uaf_roots'])}",
        f"plugin_count={report['plugin_count']}",
        f"content_plugin_count={report['content_plugin_count']}",
        f"total_content_assets={report['total_content_assets']}",
        f"test_like_asset_count={report['test_like_asset_count']}",
        f"sample_like_asset_count={report['sample_like_asset_count']}",
        "",
    ]
    for root in report["uaf_roots"]:
        lines.append(f"[root] {root}")
    if not report["uaf_roots"]:
        lines.append("[root] <no UE UAF/AnimNext experimental plugin root found>")
    lines.append("")

    for row in report["plugins"]:
        lines.extend([
            "########################################################################",
            f"PLUGIN: {row['plugin_name']}",
            f"descriptor={row['descriptor']}",
            f"friendly_name={row['friendly_name']}",
            f"category={row['category']}",
            f"can_contain_content={row['can_contain_content']}",
            f"enabled_by_default={row['enabled_by_default']}",
            f"is_experimental={row['is_experimental']}",
            f"content_dir_exists={row['content_dir_exists']}",
            f"asset_count={row['asset_count']}",
        ])
        if row["modules"]:
            lines.append("modules:")
            for module in row["modules"]:
                lines.append(f"  {module['name']} type={module['type']} loading_phase={module['loading_phase']}")
        if row["dependencies"]:
            lines.append("dependencies:")
            for dep in row["dependencies"]:
                lines.append(f"  {dep['name']} enabled={dep['enabled']} optional={dep['optional']}")
        if row["assets"]:
            lines.append("assets:")
            for asset in row["assets"]:
                lines.append(f"  {asset}")
        lines.append("")

    lines.append("========================================================================")
    if report["total_content_assets"]:
        lines.append("Representative installed plugin content exists. Use these exact files to design the next focused Unreal capture.")
    else:
        lines.append("No installed UAF/AnimNext plugin content assets were found. A separate authored representative project will be required.")
    return "\n".join(lines) + "\n"


def _cli(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="uatool animnext-engine-evidence",
        description="inspect installed UE UAF/AnimNext plugin content without launching Unreal",
    )
    parser.add_argument("--editor", required=True, help="path to UnrealEditor or UnrealEditor-Cmd executable")
    parser.add_argument("--report", help="optional UTF-8 report path")
    args = parser.parse_args(argv)
    report = build_report(Path(args.editor))
    rendered = render_report(report)
    if args.report:
        path = Path(args.report).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"wrote AnimNext/UAF installed-engine evidence report: {path}")
    print(rendered, end="")
    return 0


def install(runtime_module) -> None:
    if getattr(runtime_module, "_animnext_engine_evidence_installed", False):
        return
    original_main = runtime_module.main

    def main():
        if len(sys.argv) > 1 and sys.argv[1] == "animnext-engine-evidence":
            try:
                return _cli(sys.argv[2:])
            except Exception as exc:
                print(f"ERROR: {exc}", file=sys.stderr)
                return 54
        return original_main()

    runtime_module.main = main
    runtime_module._animnext_engine_evidence_installed = True
