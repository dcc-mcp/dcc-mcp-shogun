"""Bounded access to the vendor-owned Vicon Shogun Post SDK."""

from __future__ import annotations

import ctypes
import importlib
import os
import socket
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, Optional

SDK_ENV = "DCC_MCP_SHOGUN_SDK_PATH"
CONTROL_PORT_ENV = "DCC_MCP_SHOGUN_CONTROL_PORT"
DEFAULT_CONTROL_PORT = 803
CONTROL_PORT_MAX = 899
_configured_control_port: Optional[int] = None
_interface_connection: Any = None
_INTERFACE_CLASSES = {"Offline", "Scene", "Timeline"}


class _TcpRowOwnerPid(ctypes.Structure):
    _fields_ = [
        ("state", wintypes.DWORD),
        ("local_address", wintypes.DWORD),
        ("local_port", wintypes.DWORD),
        ("remote_address", wintypes.DWORD),
        ("remote_port", wintypes.DWORD),
        ("owning_pid", wintypes.DWORD),
    ]


class _FixedFileInfo(ctypes.Structure):
    _fields_ = [
        (name, wintypes.DWORD)
        for name in (
            "signature",
            "struct_version",
            "file_version_ms",
            "file_version_ls",
            "product_version_ms",
            "product_version_ls",
            "file_flags_mask",
            "file_flags",
            "file_os",
            "file_type",
            "file_subtype",
            "file_date_ms",
            "file_date_ls",
        )
    ]


class ShogunSdkError(RuntimeError):
    """Raised when the official Shogun Post SDK cannot be located or connected."""


def _is_sdk_root(path: Path) -> bool:
    return (path / "vicon_shogun_post.py").is_file() and (path / "ViconShogunPostSDK").is_dir()


def process_executable(pid: int) -> Path:
    """Return the executable for one explicit Windows process id."""
    if os.name != "nt":
        raise ShogunSdkError("Automatic Shogun SDK discovery is supported on Windows only")
    if pid <= 0:
        raise ShogunSdkError("Shogun host PID must be positive")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        error = ctypes.get_last_error()
        raise ShogunSdkError(f"Unable to inspect Shogun host process: Windows error {error}")
    try:
        capacity = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(capacity)):
            error = ctypes.get_last_error()
            raise ShogunSdkError(f"Unable to resolve Shogun executable: Windows error {error}")
        return Path(buffer.value)
    finally:
        kernel32.CloseHandle(handle)


def _major_minor_version(value: int) -> str:
    return f"{value >> 16}.{value & 0xFFFF}"


def host_product_version(pid: int) -> str:
    """Read a language-independent major.minor product version from the host executable."""
    if os.name != "nt":
        return "unknown"
    executable = str(process_executable(pid))
    version = ctypes.WinDLL("version", use_last_error=True)
    size = version.GetFileVersionInfoSizeW(executable, None)
    if not size:
        return "unknown"
    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(executable, 0, size, buffer):
        return "unknown"
    value = ctypes.c_void_p()
    length = wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(length)):
        return "unknown"
    info = ctypes.cast(value, ctypes.POINTER(_FixedFileInfo)).contents
    return _major_minor_version(int(info.product_version_ms))


def resolve_sdk_path(host_pid: int, explicit: Optional[Path] = None) -> Path:
    """Resolve only explicit, operator-provided, or host-relative SDK roots."""
    candidates = []
    if explicit is not None:
        candidates.append(Path(explicit))
    configured = os.environ.get(SDK_ENV)
    if configured:
        candidates.append(Path(configured))
    if host_pid > 0:
        install_root = process_executable(host_pid).parent
        candidates.extend((install_root / "SDK" / "Win64", install_root / "SDK" / "Win32"))

    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if _is_sdk_root(resolved):
            return resolved
    raise ShogunSdkError(
        "The official Vicon Shogun Post SDK was not found beside the selected host; "
        f"set {SDK_ENV} to its Win64 SDK directory"
    )


def configure_sdk(path: Path) -> Path:
    """Expose the selected vendor SDK to this adapter process."""
    resolved = Path(path).resolve()
    if not _is_sdk_root(resolved):
        raise ShogunSdkError("The selected directory is not a Vicon Shogun Post SDK root")
    value = str(resolved)
    if value not in sys.path:
        sys.path.insert(0, value)
    return resolved


def listening_ports(pid: int) -> list[int]:
    """Return IPv4 TCP listener ports owned by one exact Windows process."""
    if os.name != "nt":
        return []
    if pid <= 0:
        raise ShogunSdkError("Shogun host PID must be positive")

    iphlpapi = ctypes.WinDLL("iphlpapi")
    get_table = iphlpapi.GetExtendedTcpTable
    get_table.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.BOOL,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
    ]
    get_table.restype = wintypes.DWORD
    size = wintypes.DWORD(0)
    result = get_table(None, ctypes.byref(size), False, socket.AF_INET, 3, 0)
    if result != 122:
        raise ShogunSdkError(f"Unable to size the Windows TCP listener table: error {result}")
    buffer = ctypes.create_string_buffer(size.value)
    result = get_table(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0)
    if result != 0:
        raise ShogunSdkError(f"Unable to read the Windows TCP listener table: error {result}")

    count = wintypes.DWORD.from_buffer_copy(buffer.raw[:4]).value
    row_size = ctypes.sizeof(_TcpRowOwnerPid)
    ports = []
    for index in range(count):
        start = 4 + index * row_size
        row = _TcpRowOwnerPid.from_buffer_copy(buffer.raw[start : start + row_size])
        if int(row.owning_pid) == pid:
            ports.append(socket.ntohs(int(row.local_port) & 0xFFFF))
    return sorted(set(ports))


def _validated_port(raw: str) -> int:
    try:
        port = int(raw)
    except ValueError as error:
        raise ShogunSdkError(f"{CONTROL_PORT_ENV} must be an integer") from error
    if not 1 <= port <= 65535:
        raise ShogunSdkError(f"{CONTROL_PORT_ENV} must be between 1 and 65535")
    return port


def resolve_control_port(host_pid: int) -> int:
    """Resolve the control stream owned by the selected Shogun Post process."""
    owned_ports = listening_ports(host_pid)
    configured = os.environ.get(CONTROL_PORT_ENV)
    if configured is not None:
        port = _validated_port(configured)
        if owned_ports and port not in owned_ports:
            raise ShogunSdkError(
                f"{CONTROL_PORT_ENV} does not belong to the selected Shogun host process"
            )
        return port

    candidates = [port for port in owned_ports if DEFAULT_CONTROL_PORT <= port <= CONTROL_PORT_MAX]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise ShogunSdkError(
            "The selected Shogun host does not own a control-stream listener in the expected range"
        )
    raise ShogunSdkError("The selected Shogun host owns multiple possible control-stream listeners")


def configure_control_port(host_pid: int) -> int:
    global _configured_control_port
    _configured_control_port = resolve_control_port(host_pid)
    return _configured_control_port


def control_port() -> int:
    if _configured_control_port is not None:
        return _configured_control_port
    return _validated_port(os.environ.get(CONTROL_PORT_ENV, str(DEFAULT_CONTROL_PORT)))


def connect_client() -> Any:
    """Connect to the local Shogun Post control stream through its official SDK."""
    try:
        from vicon_shogun_post import ViconShogunPost
    except ImportError as error:
        raise ShogunSdkError("The official Vicon Shogun Post SDK is not configured") from error
    try:
        return ViconShogunPost("localhost", control_port())
    except Exception as error:
        raise ShogunSdkError(
            f"Unable to connect to the local Shogun Post control stream ({type(error).__name__})"
        ) from error


def official_interface(name: str) -> Any:
    """Create one allowlisted interface from Vicon's official SDK package."""
    global _interface_connection
    if name not in _INTERFACE_CLASSES:
        raise ShogunSdkError(f"{name} is not an enabled SDK interface")
    _interface_connection = connect_client()
    try:
        module = importlib.import_module(f"ViconShogunPostSDK.{name}")
        interface_class = getattr(module, name)
        return interface_class()
    except (ImportError, AttributeError) as error:
        raise ShogunSdkError(f"The official {name} SDK interface is unavailable") from error
