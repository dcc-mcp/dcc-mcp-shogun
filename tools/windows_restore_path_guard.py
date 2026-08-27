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
FILE_ATTRIBUTE_TAG_INFO_CLASS = 9
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
VOLUME_NAME_GUID = 0x00000001
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
MAX_RESTORE_FILE_SIZE_BYTES = 8_589_934_592
HASH_CHUNK_SIZE_BYTES = 65_536


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
    _kernel32.GetFileInformationByHandle.argtypes = (
        wintypes.HANDLE,
        wintypes.LPVOID,
    )
    _kernel32.GetFileInformationByHandle.restype = wintypes.BOOL
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


class _FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [
        ("file_attributes", wintypes.DWORD),
        ("reparse_tag", wintypes.DWORD),
    ]


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("file_attributes", wintypes.DWORD),
        ("creation_time", wintypes.FILETIME),
        ("last_access_time", wintypes.FILETIME),
        ("last_write_time", wintypes.FILETIME),
        ("volume_serial_number", wintypes.DWORD),
        ("file_size_high", wintypes.DWORD),
        ("file_size_low", wintypes.DWORD),
        ("number_of_links", wintypes.DWORD),
        ("file_index_high", wintypes.DWORD),
        ("file_index_low", wintypes.DWORD),
    ]


@dataclass(frozen=True)
class WindowsFileIdentity:
    volume_serial_number: int
    file_id: bytes


@dataclass(frozen=True)
class OpenedScene:
    identity: WindowsFileIdentity
    sha256: str
    file_size_bytes: int


@dataclass(frozen=True)
class WindowsPathComponentEvidence:
    final_path: str
    identity: WindowsFileIdentity
    file_attributes: int
    reparse_tag: int


def _require_windows():
    if _kernel32 is None:
        raise OSError("Windows path guard harness requires Windows")


def _win_error(message):
    error = ctypes.get_last_error()
    raise OSError(error, message, None, error)


def _open_handle(path, *, directory):
    _require_windows()
    desired_access = FILE_READ_ATTRIBUTES if directory else GENERIC_READ | FILE_READ_ATTRIBUTES
    flags = FILE_FLAG_OPEN_REPARSE_POINT
    if directory:
        flags |= FILE_FLAG_BACKUP_SEMANTICS
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


def _attribute_tag(handle):
    info = _FileAttributeTagInfo()
    if not _kernel32.GetFileInformationByHandleEx(
        handle,
        FILE_ATTRIBUTE_TAG_INFO_CLASS,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        _win_error("GetFileInformationByHandleEx failed")
    return info


def _reject_reparse(handle):
    info = _attribute_tag(handle)
    if info.file_attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        raise ValueError("reparse path components are not restore authority")
    return info


def _reject_unsafe_hardlinks(handle):
    info = _ByHandleFileInformation()
    if not _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        _win_error("GetFileInformationByHandle failed")
    if info.number_of_links != 1:
        raise ValueError("hardlink aliases are not restore authority")


def _close_handle(handle):
    if handle not in (None, INVALID_HANDLE_VALUE) and not _kernel32.CloseHandle(handle):
        _win_error("CloseHandle failed")


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


def _file_size(handle):
    info = _ByHandleFileInformation()
    if not _kernel32.GetFileInformationByHandle(handle, ctypes.byref(info)):
        _win_error("GetFileInformationByHandle failed")
    return (info.file_size_high << 32) | info.file_size_low


def _streaming_sha256(handle, *, expected_size, chunk_size, on_chunk=None):
    if not _kernel32.SetFilePointerEx(handle, 0, None, FILE_BEGIN):
        _win_error("SetFilePointerEx failed")
    digest = hashlib.sha256()
    total = 0
    buffer = ctypes.create_string_buffer(chunk_size)
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
        digest.update(memoryview(buffer)[: read_count.value])
        total += read_count.value
        if on_chunk is not None:
            on_chunk(read_count.value)
    if total != expected_size:
        raise ValueError("file size changed while streaming restore target")
    return digest.hexdigest()


def _capture(
    handle,
    *,
    max_file_size_bytes=MAX_RESTORE_FILE_SIZE_BYTES,
    hash_chunk_size_bytes=HASH_CHUNK_SIZE_BYTES,
    on_chunk=None,
):
    file_size_bytes = _file_size(handle)
    if not 1 <= file_size_bytes <= max_file_size_bytes:
        raise ValueError("restore target exceeds approved resource limit")
    return OpenedScene(
        identity=_identity(handle),
        sha256=_streaming_sha256(
            handle,
            expected_size=file_size_bytes,
            chunk_size=hash_chunk_size_bytes,
            on_chunk=on_chunk,
        ),
        file_size_bytes=file_size_bytes,
    )


def _component_evidence(handle):
    attribute_tag = _reject_reparse(handle)
    final_path = _volume_guid_path(handle)
    _reject_alternate_data_stream(final_path)
    return WindowsPathComponentEvidence(
        final_path=final_path,
        identity=_identity(handle),
        file_attributes=attribute_tag.file_attributes,
        reparse_tag=attribute_tag.reparse_tag,
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


def _reject_alternate_data_stream(path):
    _, tail = os.path.splitdrive(os.path.abspath(path))
    if ":" in tail:
        raise ValueError("alternate data stream paths are not restore authority")


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

    def __init__(
        self,
        trusted_root,
        target,
        *,
        max_file_size_bytes=MAX_RESTORE_FILE_SIZE_BYTES,
        hash_chunk_size_bytes=HASH_CHUNK_SIZE_BYTES,
    ):
        if max_file_size_bytes < 1:
            raise ValueError("max file size must be positive")
        if hash_chunk_size_bytes < 1:
            raise ValueError("hash chunk size must be positive")
        self.trusted_root = Path(trusted_root).absolute()
        self.target = Path(target).absolute()
        self.max_file_size_bytes = max_file_size_bytes
        self.hash_chunk_size_bytes = hash_chunk_size_bytes
        self._handles = []
        self._directory_paths = []
        self._trusted_root_index = None
        self.confirmed = None
        self.dispatch_path = None
        self.component_evidence = ()
        self.recapture_count = 0
        self.streamed_chunk_count = 0

    def _record_streamed_chunk(self, _size):
        self.streamed_chunk_count += 1

    def _capture_target(self, handle):
        return _capture(
            handle,
            max_file_size_bytes=self.max_file_size_bytes,
            hash_chunk_size_bytes=self.hash_chunk_size_bytes,
            on_chunk=self._record_streamed_chunk,
        )

    def __enter__(self):
        _reject_alternate_data_stream(self.trusted_root)
        _reject_alternate_data_stream(self.target)
        if os.path.commonpath((self.trusted_root, self.target)) != str(self.trusted_root):
            raise ValueError("target must be contained by trusted root")
        try:
            self._directory_paths = _directory_chain(self.target)
            normalized_root = os.path.normcase(os.path.normpath(self.trusted_root))
            self._trusted_root_index = next(
                index
                for index, directory in enumerate(self._directory_paths)
                if os.path.normcase(os.path.normpath(directory)) == normalized_root
            )
            for directory in self._directory_paths:
                directory_handle = _open_handle(directory, directory=True)
                self._handles.append(directory_handle)
                _reject_reparse(directory_handle)
            target_handle = _open_handle(self.target, directory=False)
            self._handles.append(target_handle)
            _reject_reparse(target_handle)
            _reject_unsafe_hardlinks(target_handle)
            self.confirmed = self._capture_target(target_handle)
            self.component_evidence = self._capture_component_chain()
            self.dispatch_path = self.component_evidence[-1].final_path
            return self
        except Exception:
            try:
                self.close()
            except OSError:
                pass
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            self.close()
        except OSError:
            if exc_type is None:
                raise
        return False

    @property
    def all_handles_retained(self):
        return bool(self._handles) and all(
            handle not in (None, INVALID_HANDLE_VALUE) for handle in self._handles
        )

    def close(self):
        while self._handles:
            _close_handle(self._handles[-1])
            self._handles.pop()

    def _capture_component_chain(self):
        evidence = tuple(_component_evidence(handle) for handle in self._handles)
        volumes = {item.identity.volume_serial_number for item in evidence}
        if len(volumes) != 1:
            raise ValueError("path component identities must share one volume")
        for parent, child in zip(evidence, evidence[1:]):
            expected_parent = os.path.normcase(os.path.normpath(parent.final_path))
            observed_parent = os.path.normcase(os.path.normpath(os.path.dirname(child.final_path)))
            if observed_parent != expected_parent:
                raise ValueError("handle-derived path component chain is not contiguous")
        trusted_final = evidence[self._trusted_root_index].final_path
        target_final = evidence[-1].final_path
        if os.path.commonpath((trusted_final, target_final)) != os.path.normpath(trusted_final):
            raise ValueError("handle-derived target is outside handle-derived trusted root")
        return evidence

    def _recapture_for_use(self):
        if not self.all_handles_retained:
            raise RuntimeError("retained path is closed")
        _reject_unsafe_hardlinks(self._handles[-1])
        evidence = self._capture_component_chain()
        current_target = self._capture_target(self._handles[-1])
        self.recapture_count += 1
        if evidence != self.component_evidence or current_target != self.confirmed:
            raise ValueError("retained path identity changed before use")
        return evidence[-1].final_path

    def prepare_for_path_use(self):
        return self._recapture_for_use()

    def verify_path_use(self, opened_scene):
        self._recapture_for_use()
        if opened_scene != self.confirmed:
            raise ValueError("SDK path adapter did not open the confirmed scene")


class WindowsSdkPathAdapter:
    """Re-open the SDK argument by path and report the object actually read."""

    def open_scene(self, retained_path):
        if not isinstance(retained_path, RetainedWindowsPath):
            raise TypeError("open_scene requires a RetainedWindowsPath")
        dispatch_path = retained_path.prepare_for_path_use()
        handle = _open_handle(dispatch_path, directory=False)
        try:
            opened_scene = retained_path._capture_target(handle)
        finally:
            _close_handle(handle)
        retained_path.verify_path_use(opened_scene)
        return opened_scene

    def open_path_for_control(self, path):
        handle = _open_handle(path, directory=False)
        try:
            return _capture(handle)
        finally:
            _close_handle(handle)
