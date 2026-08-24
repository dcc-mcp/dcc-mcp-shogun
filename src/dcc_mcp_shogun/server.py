"""Out-of-process DCC-MCP server bound to one Vicon Shogun Post process."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, ContextManager, Dict, Optional, Sequence

from dcc_mcp_core import DccServerOptions, HostExecutionBridge
from dcc_mcp_core.readiness import AdapterReadinessBinder
from dcc_mcp_core.server_base import DccServerBase

from .__version__ import __version__
from .dispatcher import ShogunSdkDispatcher
from .sdk import (
    ProcessLiveness,
    bind_process_liveness,
    configure_control_port,
    configure_sdk,
    connect_client,
    host_product_version,
    resolve_sdk_path,
)
from .state import bind_server, unbind_server

_server: Optional["ShogunMcpServer"] = None
_MAX_CONSECUTIVE_PROBE_FAILURES = 3


@dataclass(frozen=True)
class SidecarExitReceipt:
    """Sanitized reason for stopping one exact-host sidecar."""

    exit_reason: str
    uptime_seconds: float
    consecutive_probe_failures: int
    schema_version: str = "1.0"

    def as_dict(self) -> Dict[str, object]:
        """Return the stable telemetry payload without process or path details."""
        return {
            "schema_version": self.schema_version,
            "exit_reason": self.exit_reason,
            "uptime_seconds": self.uptime_seconds,
            "consecutive_probe_failures": self.consecutive_probe_failures,
        }


def monitor_host_liveness(
    host_pid: int,
    *,
    stopped: Optional[threading.Event] = None,
    probe: Optional[Callable[[int], ProcessLiveness]] = None,
    binding_factory: Callable[
        [int], ContextManager[Callable[[], ProcessLiveness]]
    ] = bind_process_liveness,
    monotonic: Callable[[], float] = time.monotonic,
    poll_interval_seconds: float = 1.0,
) -> SidecarExitReceipt:
    """Wait for a signal or the confirmed exit of one exact host process."""
    started_at = monotonic()
    stop_event = stopped or threading.Event()
    consecutive_probe_failures = 0
    binding = binding_factory(host_pid) if probe is None else nullcontext(lambda: probe(host_pid))
    with binding as bound_probe:
        while not stop_event.wait(poll_interval_seconds):
            try:
                liveness = ProcessLiveness(bound_probe())
            except Exception:
                liveness = ProcessLiveness.INDETERMINATE
            if liveness is ProcessLiveness.EXITED:
                return SidecarExitReceipt(
                    exit_reason="host_process_exited",
                    uptime_seconds=max(0.0, monotonic() - started_at),
                    consecutive_probe_failures=consecutive_probe_failures,
                )
            if liveness is ProcessLiveness.INDETERMINATE:
                consecutive_probe_failures += 1
                if consecutive_probe_failures >= _MAX_CONSECUTIVE_PROBE_FAILURES:
                    return SidecarExitReceipt(
                        exit_reason="host_process_probe_failed",
                        uptime_seconds=max(0.0, monotonic() - started_at),
                        consecutive_probe_failures=consecutive_probe_failures,
                    )
            else:
                consecutive_probe_failures = 0
        return SidecarExitReceipt(
            exit_reason="signal",
            uptime_seconds=max(0.0, monotonic() - started_at),
            consecutive_probe_failures=consecutive_probe_failures,
        )


class ShogunMcpServer(DccServerBase):
    """DCC-MCP server backed by Shogun Post's local official SDK."""

    def __init__(
        self,
        port: Optional[int] = None,
        host_pid: Optional[int] = None,
        sdk_path: Optional[Path] = None,
    ) -> None:
        resolved_pid = host_pid or int(os.environ.get("DCC_MCP_SHOGUN_HOST_PID", "0"))
        if resolved_pid <= 0:
            raise ValueError("A live Vicon Shogun Post host PID is required")
        self._host_version = host_product_version(resolved_pid)
        self._sdk_path = configure_sdk(resolve_sdk_path(resolved_pid, sdk_path))
        self._control_port = configure_control_port(resolved_pid)
        connect_client()
        options = DccServerOptions.from_env(
            "shogun",
            Path(__file__).resolve().parent / "skills",
            port=port,
            server_name="dcc-mcp-shogun",
            server_version=__version__,
            adapter_version=__version__,
            dcc_pid=resolved_pid,
            instance_type="gui",
            execution_bridge=HostExecutionBridge(
                dispatcher=ShogunSdkDispatcher(),
                default_thread_affinity="any",
                default_execution="sync",
                default_timeout_hint_secs=30,
            ),
        )
        super().__init__(options=options)
        self._readiness = AdapterReadinessBinder(self)
        self._set_readiness(True)

    def _set_readiness(self, ready: bool) -> None:
        self._readiness.mark_dispatcher_ready(
            ready,
            host_execution_bridge_ready=ready,
            main_thread_executor_ready=ready,
            dcc_ready=ready,
        )

    def stop(self) -> None:
        self._set_readiness(False)
        try:
            super().stop()
        finally:
            unbind_server(self)

    def _version_string(self) -> str:
        return os.environ.get("DCC_MCP_SHOGUN_VERSION", self._host_version)


def start_server(
    port: Optional[int] = None,
    host_pid: Optional[int] = None,
    sdk_path: Optional[Path] = None,
) -> ShogunMcpServer:
    """Start one adapter service for the selected Shogun Post process."""
    global _server
    if _server is None or not _server.is_running:
        _server = ShogunMcpServer(port=port, host_pid=host_pid, sdk_path=sdk_path)
        _server.register_builtin_actions()
        _server.start()
        bind_server(_server)
    return _server


def stop_server() -> None:
    """Stop the adapter service and remove its registry row."""
    global _server
    if _server is not None:
        _server.stop()
        _server = None


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Vicon Shogun Post DCC-MCP adapter.",
        epilog="Runtime checks: dcc-mcp-shogun doctor --json | verify --json",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--host-pid", type=int, required=True)
    parser.add_argument("--sdk-path", type=Path)
    parser.add_argument("--mcp-port", type=int)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    arguments = list(argv) if argv is not None else sys.argv[1:]
    if arguments and arguments[0] in {"doctor", "verify"}:
        from .diagnostics import run_cli

        raise SystemExit(run_cli(arguments))
    args = _parse_args(arguments)
    if args.host_pid <= 0:
        raise SystemExit("--host-pid must be a positive process id")

    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: stopped.set())

    start_server(port=args.mcp_port, host_pid=args.host_pid, sdk_path=args.sdk_path)
    try:
        receipt = monitor_host_liveness(args.host_pid, stopped=stopped)
        print(
            json.dumps(receipt.as_dict(), separators=(",", ":"), sort_keys=True),
            file=sys.stderr,
            flush=True,
        )
    finally:
        stop_server()


if __name__ == "__main__":
    main()
