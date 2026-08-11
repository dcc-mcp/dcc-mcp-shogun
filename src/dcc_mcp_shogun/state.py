"""Process-local adapter state shared by the composition root and skill scripts."""

from __future__ import annotations

import weakref
from typing import Any, Optional

_server_ref: Optional[weakref.ReferenceType[Any]] = None


def bind_server(server: Any) -> None:
    global _server_ref
    _server_ref = weakref.ref(server)


def unbind_server(server: Any) -> None:
    global _server_ref
    current = _server_ref() if _server_ref is not None else None
    if current is server:
        _server_ref = None


def publish_scene_snapshot(snapshot: dict[str, Any]) -> bool:
    server = _server_ref() if _server_ref is not None else None
    if server is None:
        return False
    server.set_scene_resource(snapshot)
    return True
