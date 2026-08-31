#!/usr/bin/env python3
"""Bundle compression policy for UnrealAssetTool upload ZIPs.

The canonical/derived JSONL payload is unchanged by this module. It only exposes
Deflate compression level as a controlled performance knob so large corpus
bundles can trade a small amount of compressed size for substantially lower CPU
cost when appropriate.
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

ENV_NAME = "UATOOL_BUNDLE_LEVEL"
# Measured on the validated StackOBot corpus: level 3 produced a 30.8 MB bundle
# in 4.52 s versus level 6 at 24.0 MB in 6.84 s. Both are substantially smaller
# and faster than the pre-schema-14 33.69 MB / ~46-48 s path, while level 3 is
# the best balanced default. Users can override 0..9 through ENV_NAME.
DEFAULT_LEVEL = 3


def compression_level() -> int:
    raw = os.environ.get(ENV_NAME, str(DEFAULT_LEVEL)).strip()
    try:
        level = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{ENV_NAME} must be an integer from 0 through 9, got {raw!r}") from exc
    if level < 0 or level > 9:
        raise RuntimeError(f"{ENV_NAME} must be from 0 through 9, got {level}")
    return level


def create_upload_bundle(
    core,
    output: Path,
    destination: Path | None = None,
    *,
    include_raw_rigvm: bool = False,
) -> Path:
    output = Path(output).expanduser().resolve()
    if destination is None:
        destination = output / "uatool-upload.zip"
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()

    names = list(core.DEFAULT_BUNDLE_FILES)
    if include_raw_rigvm:
        names.append("rigvm_properties.jsonl")

    level = compression_level()
    print(f"bundle compression: deflate level={level}")
    with zipfile.ZipFile(
        destination,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=level,
    ) as archive:
        for name in names:
            path = output / name
            if path.is_file():
                archive.write(path, arcname=name)

    return destination


def install(core) -> None:
    def wrapped(
        output: Path,
        destination: Path | None = None,
        *,
        include_raw_rigvm: bool = False,
    ) -> Path:
        return create_upload_bundle(
            core,
            output,
            destination,
            include_raw_rigvm=include_raw_rigvm,
        )

    core.create_upload_bundle = wrapped
