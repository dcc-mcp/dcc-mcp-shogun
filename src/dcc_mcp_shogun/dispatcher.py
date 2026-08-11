"""Execution bridge for the external Shogun Post control-stream SDK."""

from __future__ import annotations

from typing import Any, Callable


class ShogunSdkDispatcher:
    """Execute bounded SDK calls inline; Shogun owns its remote application thread."""

    def dispatch_callable(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        for key in (
            "affinity",
            "context",
            "action_name",
            "skill_name",
            "execution",
            "timeout_hint_secs",
            "thread_affinity",
        ):
            kwargs.pop(key, None)
        return func(*args, **kwargs)
