"""Vicon Shogun Post adapter for DCC-MCP."""

from .__version__ import __version__

__all__ = ["ShogunMcpServer", "__version__", "start_server", "stop_server"]


def __getattr__(name: str):
    if name in {"ShogunMcpServer", "start_server", "stop_server"}:
        from .server import ShogunMcpServer, start_server, stop_server

        return {
            "ShogunMcpServer": ShogunMcpServer,
            "start_server": start_server,
            "stop_server": stop_server,
        }[name]
    raise AttributeError(name)
