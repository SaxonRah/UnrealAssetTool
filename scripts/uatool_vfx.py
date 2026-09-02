#!/usr/bin/env python3
"""Canonical VFX schema 1 support facade for UnrealAssetTool."""
from uatool_vfx_defs import VFX_SCHEMA_VERSION, RAW_FILES, create_schema, read_manifest
from uatool_vfx_validate import validation_error
from uatool_vfx_storage import load_database, query
import uatool_systems_only_derive_deferred as _systems_only_derive_deferred
import uatool_capabilities as _capabilities

# uatool.py imports this facade before its final derive/VFX gates are defined.
# Install only deferred runtime dispatch hooks here; each hook waits until the
# public composition root is complete before patching the final public pipeline.
_systems_only_derive_deferred.install()
_capabilities.install()

__all__ = (
    "VFX_SCHEMA_VERSION", "RAW_FILES", "create_schema", "read_manifest",
    "validation_error", "load_database", "query",
)
