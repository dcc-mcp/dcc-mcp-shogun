"""Machine-readable install and runtime diagnostics for Shogun Post."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .__version__ import __version__
from .runtime import pipeline_policy_receipt
from .sdk import (
    CONTROL_PORT_ENV,
    SDK_ENV,
    ProcessLiveness,
    candidate_control_ports,
    configure_sdk,
    host_product_version,
    process_executable,
    process_is_alive,
    resolve_sdk_path,
    validate_control_port,
)

SCHEMA_VERSION = "1.0"
MIN_PYTHON_VERSION = "3.9"
MIN_CORE_VERSION = "0.19.86"
MAX_CORE_VERSION = "1.0.0"
MIN_HOST_VERSION = "1.19"
EXIT_OK = 0
EXIT_PREFLIGHT = 10
EXIT_VERIFY = 40
_HOST_PID_ENV = "DCC_MCP_SHOGUN_HOST_PID"


def _version_tuple(value: str) -> Optional[tuple[int, int, int]]:
    match = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?", value)
    if match is None:
        return None
    return tuple(int(part or 0) for part in match.groups())


def _version_in_range(value: str, minimum: str, maximum: Optional[str] = None) -> bool:
    observed = _version_tuple(value)
    floor = _version_tuple(minimum)
    ceiling = _version_tuple(maximum) if maximum is not None else None
    if observed is None or floor is None or observed < floor:
        return False
    return ceiling is None or observed < ceiling


def _installed_version(distribution: str) -> Optional[str]:
    try:
        return version(distribution)
    except (PackageNotFoundError, ValueError):
        return None


def _check(
    identifier: str,
    status: str,
    *,
    observed: Optional[str] = None,
    required: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"id": identifier, "status": status, "required": True}
    if observed is not None:
        result["observed"] = observed
    if required is not None:
        result["requirement"] = required
    if reason is not None:
        result["reason"] = reason
    return result


def _skipped(identifier: str, reason: str) -> Dict[str, Any]:
    return _check(identifier, "skipped", reason=reason)


def _next_step(
    identifier: str,
    description: str,
    command: List[str],
    why: str,
    *,
    requires: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "id": identifier,
        "description": description,
        "command": command,
        "why": why,
    }
    if requires:
        result["requires"] = requires
    return result


def _host_pid(explicit: Optional[int]) -> tuple[Optional[int], str]:
    if explicit is not None:
        return (explicit if explicit > 0 else None), "argument"
    raw = os.environ.get(_HOST_PID_ENV)
    if raw is None:
        return None, "missing"
    try:
        value = int(raw)
    except ValueError:
        return None, "environment_invalid"
    return (value if value > 0 else None), "environment"


def _failure(checks: List[Dict[str, Any]]) -> tuple[Optional[str], Optional[str]]:
    for item in checks:
        if item["status"] == "fail":
            return str(item["id"]), str(item.get("reason") or "check_failed")
    return None, None


def collect_diagnostics(
    *,
    mode: str,
    host_pid: Optional[int] = None,
    sdk_path: Optional[Path] = None,
    pipeline_command: Optional[str] = None,
) -> Dict[str, Any]:
    """Collect bounded prerequisites and a real control-stream handshake."""
    if mode not in {"doctor", "verify"}:
        raise ValueError("mode must be doctor or verify")

    checks: List[Dict[str, Any]] = []
    next_steps: List[Dict[str, Any]] = []
    host_version: Optional[str] = None
    platform_ok = sys.platform == "win32"
    checks.append(
        _check(
            "platform",
            "ok" if platform_ok else "fail",
            observed="windows" if platform_ok else "unsupported",
            required="Windows",
            reason=None if platform_ok else "unsupported_platform",
        )
    )

    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    python_ok = _version_in_range(python_version, MIN_PYTHON_VERSION)
    checks.append(
        _check(
            "python_version",
            "ok" if python_ok else "fail",
            observed=python_version,
            required=f">={MIN_PYTHON_VERSION}",
            reason=None if python_ok else "python_version_too_old",
        )
    )
    if not python_ok:
        next_steps.append(
            _next_step(
                "use_supported_python",
                "Install the adapter with a supported Python interpreter.",
                ["python3.12", "-m", "pip", "install", "dcc-mcp-shogun"],
                "The adapter requires Python 3.9 or newer.",
            )
        )

    core_version = _installed_version("dcc-mcp-core")
    core_ok = core_version is not None and _version_in_range(
        core_version, MIN_CORE_VERSION, MAX_CORE_VERSION
    )
    checks.append(
        _check(
            "core_version",
            "ok" if core_ok else "fail",
            observed=core_version or "not_installed",
            required=f">={MIN_CORE_VERSION},<{MAX_CORE_VERSION}",
            reason=None if core_ok else "incompatible_core_version",
        )
    )
    if not core_ok:
        next_steps.append(
            _next_step(
                "install_compatible_core",
                "Install a compatible DCC-MCP Core release.",
                [
                    "python",
                    "-m",
                    "pip",
                    "install",
                    "--upgrade",
                    f"dcc-mcp-core>={MIN_CORE_VERSION},<{MAX_CORE_VERSION}",
                ],
                "The adapter validates the Core runtime floor before host probing.",
            )
        )

    resolved_pid, pid_source = _host_pid(host_pid)
    base_ready = platform_ok and python_ok and core_ok
    if not base_ready:
        checks.extend(
            _skipped(identifier, "prerequisite_failed")
            for identifier in (
                "host_process",
                "host_executable",
                "host_version",
                "official_sdk",
                "control_stream",
            )
        )
    elif resolved_pid is None:
        pid_reason = (
            "invalid_host_pid"
            if pid_source in {"argument", "environment_invalid"}
            else "host_pid_required"
        )
        checks.append(_check("host_process", "fail", reason=pid_reason))
        checks.extend(
            _skipped(identifier, pid_reason)
            for identifier in (
                "host_executable",
                "host_version",
                "official_sdk",
                "control_stream",
            )
        )
        next_steps.append(
            _next_step(
                "bind_exact_host",
                "Set the exact Shogun Post process id and rerun doctor.",
                ["dcc-mcp-shogun", "doctor", "--json"],
                "Diagnostics never scan for or rebind an arbitrary host process.",
                requires=[{"environment": _HOST_PID_ENV, "type": "positive_integer"}],
            )
        )
    else:
        try:
            liveness = (
                ProcessLiveness.ALIVE if process_is_alive(resolved_pid) else ProcessLiveness.EXITED
            )
        except Exception:
            liveness = ProcessLiveness.INDETERMINATE
        host_failure_reason = {
            ProcessLiveness.EXITED: "host_process_exited",
            ProcessLiveness.INDETERMINATE: "host_process_probe_failed",
        }.get(liveness)
        checks.append(
            _check(
                "host_process",
                "ok" if liveness is ProcessLiveness.ALIVE else "fail",
                observed=liveness.value,
                reason=host_failure_reason,
            )
        )
        if liveness is not ProcessLiveness.ALIVE:
            checks.extend(
                _skipped(identifier, host_failure_reason or "host_process_probe_failed")
                for identifier in (
                    "host_executable",
                    "host_version",
                    "official_sdk",
                    "control_stream",
                )
            )
            probe_failed = liveness is ProcessLiveness.INDETERMINATE
            next_steps.append(
                _next_step(
                    "retry_exact_host_probe" if probe_failed else "rebind_exact_host",
                    (
                        "Retry diagnostics for the same exact Shogun Post process."
                        if probe_failed
                        else "Bind a live exact Shogun Post process and rerun doctor."
                    ),
                    ["dcc-mcp-shogun", "doctor", "--json"],
                    (
                        "The adapter could not determine whether the supplied process is alive."
                        if probe_failed
                        else "The supplied process has exited."
                    ),
                    requires=[{"environment": _HOST_PID_ENV, "type": "positive_integer"}],
                )
            )
        else:
            try:
                process_executable(resolved_pid)
                executable_ok = True
            except Exception:
                executable_ok = False
            checks.append(
                _check(
                    "host_executable",
                    "ok" if executable_ok else "fail",
                    observed="found" if executable_ok else "unavailable",
                    reason=None if executable_ok else "host_executable_unavailable",
                )
            )

            if not executable_ok:
                next_steps.append(
                    _next_step(
                        "rebind_inspectable_host",
                        "Bind an inspectable exact Shogun Post process and rerun doctor.",
                        ["dcc-mcp-shogun", "doctor", "--json"],
                        "The adapter could not inspect the executable for the supplied process.",
                        requires=[{"environment": _HOST_PID_ENV, "type": "positive_integer"}],
                    )
                )

            try:
                host_version = host_product_version(resolved_pid) if executable_ok else "unknown"
            except Exception:
                host_version = "unknown"
            host_version_ok = executable_ok and _version_in_range(host_version, MIN_HOST_VERSION)
            checks.append(
                _check(
                    "host_version",
                    "ok" if host_version_ok else "fail",
                    observed=host_version,
                    required=f">={MIN_HOST_VERSION}",
                    reason=None if host_version_ok else "unsupported_host_version",
                )
            )

            if not executable_ok or not host_version_ok:
                checks.extend(
                    _skipped(identifier, "host_version_unavailable")
                    for identifier in ("official_sdk", "control_stream")
                )
            else:
                try:
                    resolved_sdk = resolve_sdk_path(resolved_pid, sdk_path)
                    configure_sdk(resolved_sdk)
                    sdk_ok = True
                except Exception:
                    sdk_ok = False
                checks.append(
                    _check(
                        "official_sdk",
                        "ok" if sdk_ok else "fail",
                        observed="found" if sdk_ok else "unavailable",
                        reason=None if sdk_ok else "official_sdk_unavailable",
                    )
                )
                if not sdk_ok:
                    checks.append(_skipped("control_stream", "official_sdk_unavailable"))
                    next_steps.append(
                        _next_step(
                            "configure_sdk",
                            "Configure the official Shogun Post SDK root and rerun doctor.",
                            ["dcc-mcp-shogun", "doctor", "--json"],
                            "The adapter accepts only a validated vendor SDK directory.",
                            requires=[{"environment": SDK_ENV, "type": "directory"}],
                        )
                    )
                else:
                    try:
                        candidates = candidate_control_ports(resolved_pid)
                        endpoint_ok = any(
                            validate_control_port(port) is not None for port in candidates
                        )
                    except Exception:
                        endpoint_ok = False
                    checks.append(
                        _check(
                            "control_stream",
                            "ok" if endpoint_ok else "fail",
                            observed="ready" if endpoint_ok else "unavailable",
                            reason=None if endpoint_ok else "control_stream_unavailable",
                        )
                    )
                    if not endpoint_ok:
                        next_steps.append(
                            _next_step(
                                "recheck_control_stream",
                                "Enable the host control stream and rerun doctor.",
                                ["dcc-mcp-shogun", "doctor", "--json"],
                                (
                                    "The selected host must own a listener that passes the "
                                    "SDK handshake."
                                ),
                            )
                        )

    directly_usable = all(item["status"] == "ok" for item in checks)
    failure_stage, failure_reason = _failure(checks)
    status = (
        "ok" if directly_usable else ("preflight_failed" if mode == "doctor" else "verify_failed")
    )
    passed = sum(item["status"] == "ok" for item in checks)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "dcc_type": "shogun",
        "adapter_version": __version__,
        "core_version": core_version,
        "python_version": python_version,
        "host_version": host_version,
        "min_core_version": MIN_CORE_VERSION,
        "min_host_version": MIN_HOST_VERSION,
        "directly_usable": directly_usable,
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
        "pipeline_policy": pipeline_policy_receipt(pipeline_command),
        "config": {
            "host_pid_source": pid_source,
            "sdk_path_override": sdk_path is not None or SDK_ENV in os.environ,
            "control_port_override": CONTROL_PORT_ENV in os.environ,
        },
        "steps": checks,
        "next_steps": next_steps,
        "receipt_path": None,
        "verify": {
            "directly_usable": directly_usable,
            "checks_passed": passed,
            "checks_total": len(checks),
            "failure_stage": failure_stage,
            "failure_reason": failure_reason,
        },
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose the Shogun Post adapter runtime")
    parser.add_argument("verb", choices=("doctor", "verify"))
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--host-pid", type=int)
    parser.add_argument("--sdk-path", type=Path)
    parser.add_argument("--pipeline-command")
    return parser


def run_cli(argv: Sequence[str]) -> int:
    args = _parser().parse_args(argv)
    report = collect_diagnostics(
        mode=args.verb,
        host_pid=args.host_pid,
        sdk_path=args.sdk_path,
        pipeline_command=args.pipeline_command,
    )
    if args.as_json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Shogun {args.verb}: {report['status']}")
        print(f"directly_usable: {str(report['directly_usable']).lower()}")
        for item in report["steps"]:
            print(f"- {item['id']}: {item['status']}")
        for item in report["next_steps"]:
            print("next: " + " ".join(item["command"]))
    if report["directly_usable"]:
        return EXIT_OK
    return EXIT_PREFLIGHT if args.verb == "doctor" else EXIT_VERIFY
