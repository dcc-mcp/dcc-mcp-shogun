"""Privacy-bounded result envelopes shared by Shogun Skill entry points."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Dict

from dcc_mcp_core.skill import skill_error, skill_success


def safe_result(message: str, operation: Callable[[], Dict[str, Any]]):
    """Return a bounded result without propagating vendor paths or tracebacks."""
    try:
        return skill_success(message, **operation())
    except Exception as error:
        return skill_error(
            "Shogun operation failed.",
            type(error).__name__,
            error_type=type(error).__name__,
            prompt="Inspect the active scene and verify the requested subject, marker, or file.",
        )
