"""Advisory MCP capability labels; they do not authorize or orchestrate calls.

``role`` describes what a capability returns or does. ``fallback_level``
distinguishes curated capabilities from generic/raw escape hatches. The
``action`` and ``generic_raw`` values are reserved for future capabilities;
this server currently exposes neither.
"""

from typing import Literal

CapabilityRole = Literal["workflow_discovery", "workflow_consume", "evidence", "action"]
FallbackLevel = Literal["curated", "generic_raw"]

CAPABILITY_META_KEY = "agent/capability"


def capability_meta(
    role: CapabilityRole, fallback_level: FallbackLevel = "curated"
) -> dict[str, object]:
    """Return versioned, domain-neutral metadata for an MCP capability."""
    return {
        CAPABILITY_META_KEY: {
            "version": 1,
            "role": role,
            "fallback_level": fallback_level,
        }
    }
