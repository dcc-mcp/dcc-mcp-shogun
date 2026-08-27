"""Real Windows path-open harness for the proposed restore contract.

This module is test-only evidence. It does not connect to Shogun or dispatch a
scene mutation.
"""

import ctypes
import hashlib
import os
import subprocess
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

GENERIC_READ = 0x80000000
FILE_READ_ATTRIBUTES = 0x0080
FILE_SHARE_READ = 0x00000001
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_BEGIN = 0
FILE_ID_INFO_CLASS = 18
VOLUME_NAME_GUID = 0x00000001
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


if os.name == "nt":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateFileW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    )
    _kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _kernel32.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    _kernel32.GetFileInformationByHandleEx.restype = wintypes.BOOL
    _kernel32.SetFilePointerEx.argtypes = (
        wintypes.HANDLE,
        ctypes.c_longlong,
        ctypes.POINTER(ctypes.c_longlong),
        wintypes.DWORD,
    )
    _kernel32.SetFilePointerEx.restype = wintypes.BOOL
    _kernel32.ReadFile.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    )
    _kernel32.ReadFile.restype = wintypes.BOOL
else:
    _kernel32 = None


class _FileId128(ctypes.Structure):
    _fields_ = [("identifier", ctypes.c_ubyte * 16)]


class _FileIdInfo(ctypes.Structure):
    _fields_ = [
        ("volume_serial_number", ctypes.c_ulonglong),
        ("file_id", _FileId128),
    ]


@dataclass(frozen=True)
class WindowsFileIdentity:
    volume_serial_number: int
    file_id: bytes


@dataclass(frozen=True)
class OpenedScene:
    identity: WindowsFileIdentity
    sha256: str


def _require_windows():
    if _kernel32 is None:
        raise OSError("Windows path guard harness requires Windows")


def _win_error(message):
    error = ctypes.get_last_error()
    raise OSError(error, message, None, error)


def _open_handle(path, *, directory):
    _require_windows()
    desired_access = FILE_READ_ATTRIBUTES if directory else GENERIC_READ | FILE_READ_ATTRIBUTES
    flags = FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT if directory else 0
    handle = _kernel32.CreateFileW(
        str(path),
        desired_access,
        FILE_SHARE_READ,
        None,
        OPEN_EXISTING,
        flags,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        _win_error("CreateFileW failed")
    return handle


def _close_handle(handle):
    if handle not in (None, INVALID_HANDLE_VALUE):
        _kernel32.CloseHandle(handle)


def _identity(handle):
    info = _FileIdInfo()
    if not _kernel32.GetFileInformationByHandleEx(
        handle,
        FILE_ID_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        _win_error("GetFileInformationByHandleEx failed")
    return WindowsFileIdentity(
        volume_serial_number=info.volume_serial_number,
        file_id=bytes(info.file_id.identifier),
    )


def _read_all(handle):
    if not _kernel32.SetFilePointerEx(handle, 0, None, FILE_BEGIN):
        _win_error("SetFilePointerEx failed")
    chunks = []
    buffer = ctypes.create_string_buffer(64 * 1024)
    while True:
        read_count = wintypes.DWORD()
        if not _kernel32.ReadFile(
            handle,
            buffer,
            len(buffer),
            ctypes.byref(read_count),
            None,
        ):
            _win_error("ReadFile failed")
        if read_count.value == 0:
            break
        chunks.append(buffer.raw[: read_count.value])
    return b"".join(chunks)


def _capture(handle):
    return OpenedScene(
        identity=_identity(handle),
        sha256=hashlib.sha256(_read_all(handle)).hexdigest(),
    )


def _volume_guid_path(handle):
    buffer = ctypes.create_unicode_buffer(32768)
    length = _kernel32.GetFinalPathNameByHandleW(
        handle,
        buffer,
        len(buffer),
        VOLUME_NAME_GUID,
    )
    if length == 0 or length >= len(buffer):
        _win_error("GetFinalPathNameByHandleW failed")
    return buffer.value


def _directory_chain(target):
    parent = target.parent
    parts = parent.parts
    current = Path(parts[0])
    chain = [current]
    for part in parts[1:]:
        current = current / part
        chain.append(current)
    return chain


def create_junction(link, target):
    """Create a real directory junction for the Windows adversarial harness."""

    _require_windows()
    link = Path(link).absolute()
    target = Path(target).absolute()
    if link.exists():
        raise ValueError("junction path must not already exist")
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if completed.returncode != 0:
        raise OSError("mklink /J failed")


class RetainedWindowsPath:
    """Retain every directory handle and the confirmed target across dispatch."""

    def __init__(self, trusted_root, target):
        self.trusted_root = Path(trusted_root).absolute()
        self.target = Path(target).absolute()
        self._handles = []
        self.confirmed = None
        self.dispatch_path = None

    def __enter__(self):
        if os.path.commonpath((self.trusted_root, self.target)) != str(self.trusted_root):
            raise ValueError("target must be contained by trusted root")
        try:
            for directory in _directory_chain(self.target):
                self._handles.append(_open_handle(directory, directory=True))
            target_handle = _open_handle(self.target, directory=False)
            self._handles.append(target_handle)
            self.confirmed = _capture(target_handle)
            self.dispatch_path = _volume_guid_path(target_handle)
            return self
        except Exception:
            self.close()
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    @property
    def all_handles_retained(self):
        return bool(self._handles) and all(
            handle not in (None, INVALID_HANDLE_VALUE) for handle in self._handles
        )

    def close(self):
        while self._handles:
            _close_handle(self._handles.pop())


class WindowsSdkPathAdapter:
    """Re-open the SDK argument by path and report the object actually read."""

    def open_scene(self, dispatch_path):
        handle = _open_handle(dispatch_path, directory=False)
        try:
            return _capture(handle)
        finally:
            _close_handle(handle)
