import hashlib
import os

import pytest

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
        loaded = WindowsSdkPathAdapter().open_scene(retained.dispatch_path)

        assert retained.all_handles_retained
        assert retained.dispatch_path.startswith("\\\\?\\Volume{")
        assert loaded.identity == retained.confirmed.identity
        assert (
            loaded.sha256
            == retained.confirmed.sha256
            == hashlib.sha256(confirmed_bytes).hexdigest()
        )

    os.replace(replacement, target)
    replaced = WindowsSdkPathAdapter().open_scene(retained.dispatch_path)
    assert replaced.identity != retained.confirmed.identity
    assert replaced.sha256 != retained.confirmed.sha256


def test_same_content_object_swap_is_blocked_across_actual_sdk_path_open(tmp_path):
    _, trusted_root, _, target, replacement, confirmed_bytes = _scene_layout(
        tmp_path,
        replacement_bytes=b"confirmed-scene",
    )
    replacement_before = WindowsSdkPathAdapter().open_scene(str(replacement))

    with RetainedWindowsPath(trusted_root, target) as retained:
        assert replacement_before.sha256 == retained.confirmed.sha256
        assert replacement_before.identity != retained.confirmed.identity
        with pytest.raises(OSError):
            os.replace(replacement, target)
        loaded = WindowsSdkPathAdapter().open_scene(retained.dispatch_path)

        assert loaded.identity == retained.confirmed.identity
        assert loaded.sha256 == hashlib.sha256(confirmed_bytes).hexdigest()

    os.replace(replacement, target)
    replaced = WindowsSdkPathAdapter().open_scene(retained.dispatch_path)
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
        loaded = WindowsSdkPathAdapter().open_scene(retained.dispatch_path)

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
            loaded = WindowsSdkPathAdapter().open_scene(retained.dispatch_path)

            assert loaded.identity == retained.confirmed.identity
            assert loaded.sha256 == retained.confirmed.sha256

        os.rename(scene_directory, parked)
        os.rename(junction_candidate, scene_directory)
        replaced = WindowsSdkPathAdapter().open_scene(retained.dispatch_path)
        assert replaced.identity != retained.confirmed.identity
        assert replaced.sha256 != retained.confirmed.sha256
        os.rename(scene_directory, junction_candidate)
        os.rename(parked, scene_directory)
    finally:
        if junction_candidate.exists():
            os.rmdir(junction_candidate)
