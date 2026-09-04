"""Single source of truth for the UnrealAssetTool public release contract."""
from __future__ import annotations

RELEASE_VERSION = "1.0.0-beta.1"
PLUGIN_VERSION = 100001
VALIDATED_ENGINE = "UE 5.8.2"
ENGINE_TARGET = "UE 5.8+"

# Current full-corpus schema baseline for the beta release line.
# Individually versioned historical/focused subsystem schemas remain valid
# evidence contracts and are documented separately.
CURRENT_SCHEMAS = {
    "structural": 13,
    "world": 12,
    "animation": 4,
    "vfx": 1,
    "systems": 11,
    "mesh": 1,
    "world_geometry": 1,
    "derived": 39,
    "capabilities": 1,
}

BETA_COMPATIBILITY_POLICY = (
    "Canonical scanner schemas and derived schemas are independently versioned. "
    "A beta update may advance an individual schema when evidence requires it; "
    "older corpora remain identifiable by their manifests and must be re-derived "
    "or rescanned when the current command explicitly reports incompatibility."
)


def version_line() -> str:
    schema_text = " ".join(
        f"{name}={value}" for name, value in CURRENT_SCHEMAS.items()
    )
    return (
        f"UnrealAssetTool {RELEASE_VERSION}\n"
        f"validated_engine={VALIDATED_ENGINE}\n"
        f"schemas {schema_text}"
    )
