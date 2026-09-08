#!/usr/bin/env python3
"""libclang cursor orchestration for native compiler semantic capture."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


def discover_libclang(frontend: Path) -> tuple[Path | None, list[str]]:
    frontend = frontend.resolve()
    checked: list[str] = []
    candidates = [
        frontend.parent / "libclang.dll",
        frontend.parent.parent / "lib" / "libclang.dll",
        frontend.parent.parent / "bin" / "libclang.dll",
    ]
    seen: set[str] = set()
    for candidate in candidates:
        candidate = candidate.resolve()
        key = candidate.as_posix().lower()
        if key in seen:
            continue
        seen.add(key)
        checked.append(candidate.as_posix())
        if candidate.is_file():
            return candidate, checked
    return None, checked


def run_cursor_probe(
    *,
    frontend: Path,
    libclang: Path,
    row: dict,
    source: Path,
    language: str,
    compatibility_overrides: list[str],
    syntax_arguments: list[str],
    project_root: Path,
    output: Path,
) -> dict:
    source_key = str(row.get("source_path", ""))
    digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:12]
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", source.stem)[:48] or "tu"
    stem = f"native_ast_libclang_{language}_{base}_{digest}"
    config_path = output / f"{stem}_config.json"
    result_path = output / f"{stem}_result.json"
    worker = Path(__file__).with_name("uatool_libclang_worker.py")

    # FullArgv uses argv[0] to select clang-cl driver semantics. The source is
    # already the final element of syntax_arguments.
    arguments = [str(frontend)] + list(syntax_arguments)
    config = {
        "libclang": libclang.as_posix(),
        "frontend": frontend.as_posix(),
        "arguments": arguments,
        "project_root": project_root.as_posix(),
        "translation_unit": str(row.get("source_path", "")),
        "language": language,
        "compatibility_overrides": list(compatibility_overrides),
        "output_dir": output.as_posix(),
        "output_stem": stem,
        "result_path": result_path.as_posix(),
    }
    config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    command = [sys.executable, str(worker), str(config_path)]
    run = subprocess.run(
        command,
        cwd=str(Path(row["directory"])),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        errors="replace",
        check=False,
    )

    result: dict = {}
    if result_path.is_file():
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            result = {}

    return {
        "kind": "libclang_cursor_probe",
        "language": language,
        "source_path": str(row.get("source_path", "")),
        "success": run.returncode == 0 and bool(result.get("success")),
        "worker_exit_code": run.returncode,
        "command": subprocess.list2cmdline(command),
        "libclang": libclang.as_posix(),
        "config": config_path.as_posix(),
        "result_file": result_path.as_posix(),
        "worker_stdout_tail": "\n".join((run.stdout or "").splitlines()[-80:]),
        "worker_stderr_tail": "\n".join((run.stderr or "").splitlines()[-120:]),
        "compatibility_overrides": list(compatibility_overrides),
        "parse_error_code": result.get("parse_error_code"),
        "diagnostics": result.get("diagnostics", []),
        "counts": result.get(
            "counts",
            {
                "symbols": 0,
                "parameters": 0,
                "calls": 0,
                "parameter_owner_mismatches": 0,
                "nested_callable_calls_suppressed": 0,
                "referenced_target_symbols_materialized": 0,
            },
        ),
        "files": result.get("files", {}),
        "exception": result.get("exception", ""),
        "backend": "libclang_cursor",
    }


def read_probe_rows(diagnostic: dict) -> tuple[list[dict], list[dict], list[dict]]:
    files = diagnostic.get("files") or {}

    def read(name: str) -> list[dict]:
        value = files.get(name)
        if not value:
            return []
        path = Path(str(value))
        if not path.is_file():
            return []
        rows: list[dict] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
        return rows

    return read("symbols"), read("parameters"), read("calls")
