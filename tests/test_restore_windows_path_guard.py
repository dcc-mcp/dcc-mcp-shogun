import hashlib
import os

import pytest

import tools.windows_restore_path_guard as path_guard
from tools.windows_restore_path_guard import (
    RetainedWindowsPath,
    WindowsSdkPathAdapter,
    create_junction,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="requires real Windows handles")


def _scene_layout(tmp_path, *, replacement_bytes=b"replacement-scene"):
    namespace_root = tmp_path / "namespace"
    trusted_root = namespace_root / "trusted"
    scene_directory = trusted_root / "scene"
    scene_directory.mkdir(parents=True)
    target = scene_directory / "marked_take.vdf"
    confirmed_bytes = b"confirmed-scene"
    target.write_bytes(confirmed_bytes)
    replacement = scene_directory / "replacement.vdf"
    replacement.write_bytes(replacement_bytes)
    return namespace_root, trusted_root, scene_directory, target, replacement, confirmed_bytes


def test_target_swap_is_blocked_across_actual_sdk_path_open(tmp_path):
    _, trusted_root, _, target, replacement, confirmed_bytes = _scene_layout(tmp_path)

    with RetainedWindowsPath(trusted_root, target) as retained:
        with pytest.raises(OSError):
            os.replace(replacement, target)
        loaded = WindowsSdkPathAdapter().open_scene(retained)

        assert retained.all_handles_retained
        assert retained.dispatch_path.startswith("\\\\?\\Volume{")
        assert loaded.identity == retained.confirmed.identity
        assert (
            loaded.sha256
            == retained.confirmed.sha256
            == hashlib.sha256(confirmed_bytes).hexdigest()
        )

    os.replace(replacement, target)
    replaced = WindowsSdkPathAdapter().open_path_for_control(retained.dispatch_path)
    assert replaced.identity != retained.confirmed.identity
    assert replaced.sha256 != retained.confirmed.sha256


def test_same_content_object_swap_is_blocked_across_actual_sdk_path_open(tmp_path):
    _, trusted_root, _, target, replacement, confirmed_bytes = _scene_layout(
        tmp_path,
        replacement_bytes=b"confirmed-scene",
    )
    replacement_before = WindowsSdkPathAdapter().open_path_for_control(str(replacement))

    with RetainedWindowsPath(trusted_root, target) as retained:
        assert replacement_before.sha256 == retained.confirmed.sha256
        assert replacement_before.identity != retained.confirmed.identity
        with pytest.raises(OSError):
            os.replace(replacement, target)
        loaded = WindowsSdkPathAdapter().open_scene(retained)

        assert loaded.identity == retained.confirmed.identity
        assert loaded.sha256 == hashlib.sha256(confirmed_bytes).hexdigest()

    os.replace(replacement, target)
    replaced = WindowsSdkPathAdapter().open_path_for_control(retained.dispatch_path)
    assert replaced.sha256 == retained.confirmed.sha256
    assert replaced.identity != retained.confirmed.identity


@pytest.mark.parametrize("attack_component", ("parent", "namespace"))
def test_ancestor_swap_is_blocked_across_actual_sdk_path_open(tmp_path, attack_component):
    namespace_root, trusted_root, scene_directory, target, _, _ = _scene_layout(tmp_path)
    attacked = scene_directory if attack_component == "parent" else namespace_root
    parked = attacked.with_name(f"{attacked.name}-parked")

    with RetainedWindowsPath(trusted_root, target) as retained:
        with pytest.raises(OSError):
            os.rename(attacked, parked)
        loaded = WindowsSdkPathAdapter().open_scene(retained)

        assert loaded.identity == retained.confirmed.identity
        assert loaded.sha256 == retained.confirmed.sha256

    os.rename(attacked, parked)
    assert not attacked.exists()
    os.rename(parked, attacked)


def test_junction_swap_is_blocked_across_actual_sdk_path_open(tmp_path):
    _, trusted_root, scene_directory, target, _, _ = _scene_layout(tmp_path)
    decoy_directory = tmp_path / "decoy"
    decoy_directory.mkdir()
    decoy_target = decoy_directory / target.name
    decoy_target.write_bytes(b"decoy-scene")
    junction_candidate = trusted_root / "junction-candidate"
    create_junction(junction_candidate, decoy_directory)
    parked = scene_directory.with_name("scene-confirmed")

    try:
        with RetainedWindowsPath(trusted_root, target) as retained:
            with pytest.raises(OSError):
                os.replace(junction_candidate, scene_directory)
            with pytest.raises(OSError):
                os.rename(scene_directory, parked)
            loaded = WindowsSdkPathAdapter().open_scene(retained)

            assert loaded.identity == retained.confirmed.identity
            assert loaded.sha256 == retained.confirmed.sha256

        os.rename(scene_directory, parked)
        os.rename(junction_candidate, scene_directory)
        replaced = WindowsSdkPathAdapter().open_path_for_control(retained.dispatch_path)
        assert replaced.identity != retained.confirmed.identity
        assert replaced.sha256 != retained.confirmed.sha256
        os.rename(scene_directory, junction_candidate)
        os.rename(parked, scene_directory)
    finally:
        if junction_candidate.exists():
            os.rmdir(junction_candidate)


def test_preexisting_target_symlink_to_outside_trusted_root_is_rejected(tmp_path):
    trusted_root = tmp_path / "trusted"
    scene_directory = trusted_root / "scene"
    scene_directory.mkdir(parents=True)
    outside = tmp_path / "outside.vdf"
    outside.write_bytes(b"outside-scene")
    target_alias = scene_directory / "marked_take.vdf"
    target_alias.symlink_to(outside)

    with pytest.raises(ValueError, match="reparse"):
        with RetainedWindowsPath(trusted_root, target_alias):
            pass


def test_alternate_data_stream_target_is_rejected(tmp_path):
    trusted_root = tmp_path / "trusted"
    scene_directory = trusted_root / "scene"
    scene_directory.mkdir(parents=True)
    primary = scene_directory / "primary.vdf"
    primary.write_bytes(b"primary-scene")
    alternate_stream = primary.with_name(f"{primary.name}:marked_take.vdf")
    alternate_stream.write_bytes(b"hidden-scene")

    with pytest.raises(ValueError, match="alternate data stream"):
        with RetainedWindowsPath(trusted_root, alternate_stream):
            pass


def test_cross_root_hardlink_alias_is_rejected(tmp_path):
    trusted_root = tmp_path / "trusted"
    scene_directory = trusted_root / "scene"
    scene_directory.mkdir(parents=True)
    outside = tmp_path / "outside.vdf"
    outside.write_bytes(b"outside-scene")
    target_alias = scene_directory / "marked_take.vdf"
    os.link(outside, target_alias)

    with pytest.raises(ValueError, match="hardlink"):
        with RetainedWindowsPath(trusted_root, target_alias):
            pass


def test_preexisting_junction_to_outside_trusted_root_is_rejected(tmp_path):
    trusted_root = tmp_path / "trusted"
    trusted_root.mkdir()
    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()
    (outside_directory / "marked_take.vdf").write_bytes(b"outside-scene")
    junction = trusted_root / "linked-scene"
    create_junction(junction, outside_directory)

    try:
        with pytest.raises(ValueError, match="reparse"):
            with RetainedWindowsPath(trusted_root, junction / "marked_take.vdf"):
                pass
    finally:
        if junction.exists():
            os.rmdir(junction)


def test_sdk_adapter_recaptures_handle_derived_component_chain_around_path_use(tmp_path):
    _, trusted_root, _, target, _, _ = _scene_layout(tmp_path)
    adapter = WindowsSdkPathAdapter()

    with RetainedWindowsPath(trusted_root, target) as retained:
        baseline = retained.component_evidence
        loaded = adapter.open_scene(retained)

        assert len(baseline) >= 4
        assert all(item.final_path.startswith("\\\\?\\Volume{") for item in baseline)
        assert all(item.reparse_tag == 0 for item in baseline)
        assert retained.recapture_count == 2
        assert loaded == retained.confirmed
        with pytest.raises(TypeError, match="RetainedWindowsPath"):
            adapter.open_scene(retained.dispatch_path)


def test_oversize_target_is_rejected_before_streaming_or_buffering(tmp_path):
    _, trusted_root, _, target, _, _ = _scene_layout(tmp_path)

    retained = RetainedWindowsPath(
        trusted_root,
        target,
        max_file_size_bytes=target.stat().st_size - 1,
    )
    with pytest.raises(ValueError, match="resource limit"):
        with retained:
            pass

    assert retained.streamed_chunk_count == 0
    assert not retained.all_handles_retained


def test_target_hashing_streams_multiple_bounded_chunks(tmp_path):
    _, trusted_root, _, target, _, confirmed_bytes = _scene_layout(tmp_path)

    with RetainedWindowsPath(
        trusted_root,
        target,
        hash_chunk_size_bytes=4,
    ) as retained:
        assert retained.confirmed.file_size_bytes == len(confirmed_bytes)
        assert retained.confirmed.sha256 == hashlib.sha256(confirmed_bytes).hexdigest()
        assert retained.streamed_chunk_count >= 4


def test_close_handle_failure_is_observable_and_retains_exact_cleanup_owner(
    tmp_path,
    monkeypatch,
):
    _, trusted_root, _, target, _, _ = _scene_layout(tmp_path)
    retained = RetainedWindowsPath(trusted_root, target)
    retained.__enter__()
    original_close_handle = path_guard._kernel32.CloseHandle

    try:
        monkeypatch.setattr(path_guard._kernel32, "CloseHandle", lambda _handle: 0)
        with pytest.raises(OSError, match="CloseHandle failed"):
            retained.close()

        assert retained.all_handles_retained
    finally:
        monkeypatch.setattr(path_guard._kernel32, "CloseHandle", original_close_handle)
        retained.close()

    assert retained.all_handles_retained is False


def test_close_handle_false_after_real_close_is_verified_and_never_retried(
    tmp_path,
    monkeypatch,
):
    _, trusted_root, _, target, _, _ = _scene_layout(tmp_path)
    retained = RetainedWindowsPath(trusted_root, target)
    retained.__enter__()
    original_close_handle = path_guard._kernel32.CloseHandle
    target_handle = retained._handles[-1]
    close_calls = []

    def close_then_report_false(handle):
        close_calls.append(handle)
        assert original_close_handle(handle)
        return 0

    monkeypatch.setattr(path_guard._kernel32, "CloseHandle", close_then_report_false)
    try:
        retained.close()
    finally:
        monkeypatch.setattr(path_guard._kernel32, "CloseHandle", original_close_handle)
        retained.close()

    assert close_calls.count(target_handle) == 1
    assert len(close_calls) == len(set(close_calls))
    assert target_handle not in retained._handles
    assert retained.all_handles_retained is False


def test_close_handle_indeterminate_is_neither_released_nor_retried(
    tmp_path,
    monkeypatch,
):
    _, trusted_root, _, target, _, _ = _scene_layout(tmp_path)
    retained = RetainedWindowsPath(trusted_root, target)
    retained.__enter__()
    original_close_handle = path_guard._kernel32.CloseHandle
    original_get_handle_information = path_guard._kernel32.GetHandleInformation
    target_handle = retained._handles[-1]
    close_calls = []

    def close_then_report_false(handle):
        close_calls.append(handle)
        assert original_close_handle(handle)
        return 0

    def unverifiable_handle(_handle, _flags):
        path_guard.ctypes.set_last_error(5)
        return 0

    monkeypatch.setattr(path_guard._kernel32, "CloseHandle", close_then_report_false)
    monkeypatch.setattr(
        path_guard._kernel32,
        "GetHandleInformation",
        unverifiable_handle,
    )
    try:
        with pytest.raises(OSError, match="ownership indeterminate"):
            retained.close()
        assert retained.cleanup_state == "indeterminate"
        assert retained.all_handles_retained is False
        assert close_calls == [target_handle]
        assert target_handle not in retained._handles
    finally:
        monkeypatch.setattr(path_guard._kernel32, "CloseHandle", original_close_handle)
        monkeypatch.setattr(
            path_guard._kernel32,
            "GetHandleInformation",
            original_get_handle_information,
        )
        retained.close()

    assert close_calls == [target_handle]


def test_context_cleanup_failure_does_not_replace_the_primary_operation_error(
    tmp_path,
    monkeypatch,
):
    _, trusted_root, _, target, _, _ = _scene_layout(tmp_path)
    retained = RetainedWindowsPath(trusted_root, target)
    original_close_handle = path_guard._kernel32.CloseHandle
    primary_error = "primary SDK result failed_unknown"

    try:
        with pytest.raises(RuntimeError, match=primary_error):
            with retained:
                monkeypatch.setattr(path_guard._kernel32, "CloseHandle", lambda _handle: 0)
                raise RuntimeError(primary_error)

        assert retained.all_handles_retained
    finally:
        monkeypatch.setattr(path_guard._kernel32, "CloseHandle", original_close_handle)
        retained.close()

    assert retained.all_handles_retained is False
