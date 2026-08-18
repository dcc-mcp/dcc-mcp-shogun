from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from dcc_mcp_shogun import sdk


def _fake_sdk(root: Path) -> Path:
    root.mkdir()
    (root / "vicon_shogun_post.py").write_text("", encoding="utf-8")
    (root / "ViconShogunPostSDK").mkdir()
    return root


def test_explicit_sdk_path_is_validated(tmp_path):
    root = _fake_sdk(tmp_path / "sdk")
    assert sdk.resolve_sdk_path(0, root) == root.resolve()


def test_invalid_sdk_path_fails_without_searching_the_machine(tmp_path, monkeypatch):
    monkeypatch.delenv(sdk.SDK_ENV, raising=False)
    with pytest.raises(sdk.ShogunSdkError, match="official Vicon Shogun Post SDK"):
        sdk.resolve_sdk_path(0, tmp_path / "missing")


def test_configure_sdk_adds_only_the_validated_root(tmp_path):
    root = _fake_sdk(tmp_path / "sdk")
    original = list(sys.path)
    try:
        assert sdk.configure_sdk(root) == root.resolve()
        assert sys.path[0] == str(root.resolve())
    finally:
        sys.path[:] = original


@pytest.mark.parametrize("value", ["0", "65536", "not-a-port"])
def test_control_port_is_bounded(monkeypatch, value):
    monkeypatch.setattr(sdk, "_configured_control_port", None)
    monkeypatch.setenv(sdk.CONTROL_PORT_ENV, value)
    with pytest.raises(sdk.ShogunSdkError):
        sdk.control_port()


def test_control_port_is_resolved_from_selected_host(monkeypatch):
    monkeypatch.delenv(sdk.CONTROL_PORT_ENV, raising=False)
    monkeypatch.setattr(sdk, "listening_ports", lambda pid: [804, 49152] if pid == 42 else [])
    assert sdk.resolve_control_port(42) == 804


def test_explicit_control_port_must_belong_to_selected_host(monkeypatch):
    monkeypatch.setenv(sdk.CONTROL_PORT_ENV, "803")
    monkeypatch.setattr(sdk, "listening_ports", lambda _pid: [804])
    with pytest.raises(sdk.ShogunSdkError, match="does not belong"):
        sdk.resolve_control_port(42)


def test_major_minor_version_is_bounded():
    assert sdk._major_minor_version((1 << 16) | 19) == "1.19"


def test_official_interface_is_connected_and_allowlisted(monkeypatch):
    timeline = object()
    module = types.SimpleNamespace(Timeline=lambda: timeline)
    monkeypatch.setitem(sys.modules, "ViconShogunPostSDK.Timeline", module)
    connection = object()
    monkeypatch.setattr(sdk, "_interface_connection", None)
    monkeypatch.setattr(sdk, "connect_client", lambda: connection)

    assert sdk.official_interface("Timeline") is timeline
    assert sdk._interface_connection is connection

    with pytest.raises(sdk.ShogunSdkError, match="not an enabled SDK interface"):
        sdk.official_interface("Database")


def test_official_scene_interface_is_allowlisted(monkeypatch):
    scene = object()
    module = types.SimpleNamespace(Scene=lambda: scene)
    monkeypatch.setitem(sys.modules, "ViconShogunPostSDK.Scene", module)
    monkeypatch.setattr(sdk, "connect_client", object)

    assert sdk.official_interface("Scene") is scene


def test_official_filter_types_are_connected_and_allowlisted(monkeypatch):
    fir = object()
    module = types.SimpleNamespace(FIRFilter=lambda: fir)
    monkeypatch.setitem(sys.modules, "ViconShogunPostSDK.Filter", module)
    connection = object()
    monkeypatch.setattr(sdk, "_interface_connection", None)
    monkeypatch.setattr(sdk, "connect_client", lambda: connection)

    assert sdk.official_type("FIRFilter") is fir
    assert sdk._interface_connection is connection

    with pytest.raises(sdk.ShogunSdkError, match="not an enabled SDK type"):
        sdk.official_type("ArbitraryFilter")


def test_candidate_ports_prefer_documented_range(monkeypatch):
    monkeypatch.delenv(sdk.CONTROL_PORT_ENV, raising=False)
    monkeypatch.setattr(sdk, "listening_ports", lambda _pid: [49152, 850, 804])
    assert sdk.candidate_control_ports(42) == [804, 850, 49152]


def test_candidate_ports_keep_unusual_listeners(monkeypatch):
    monkeypatch.delenv(sdk.CONTROL_PORT_ENV, raising=False)
    monkeypatch.setattr(sdk, "listening_ports", lambda _pid: [52800])
    assert sdk.candidate_control_ports(42) == [52800]


def test_wait_for_control_port_validates_candidates(monkeypatch):
    monkeypatch.delenv(sdk.CONTROL_PORT_ENV, raising=False)
    # 804 ranks first (documented range) but fails validation; 52800 is the
    # actual control stream and must be reached through the fallback.
    monkeypatch.setattr(sdk, "listening_ports", lambda _pid: [804, 52800])
    monkeypatch.setattr(sdk, "_pid_alive", lambda _pid: True)
    tried = []

    def fake_validator(port):
        tried.append(port)
        return object() if port == 52800 else None

    assert sdk.wait_for_control_port(42, timeout=5, interval=0.0, validator=fake_validator) == 52800
    assert tried == [804, 52800]


def test_wait_for_control_port_waits_for_late_listener(monkeypatch):
    snapshots = iter([[], [], [803]])
    monkeypatch.delenv(sdk.CONTROL_PORT_ENV, raising=False)
    monkeypatch.setattr(sdk, "listening_ports", lambda _pid: next(snapshots))
    monkeypatch.setattr(sdk, "_pid_alive", lambda _pid: True)
    assert (
        sdk.wait_for_control_port(42, timeout=5, interval=0.0, validator=lambda p: object()) == 803
    )


def test_wait_for_control_port_times_out(monkeypatch):
    monkeypatch.delenv(sdk.CONTROL_PORT_ENV, raising=False)
    monkeypatch.setattr(sdk, "listening_ports", lambda _pid: [])
    monkeypatch.setattr(sdk, "_pid_alive", lambda _pid: True)
    with pytest.raises(sdk.ShogunSdkError, match="did not open"):
        sdk.wait_for_control_port(42, timeout=0.0, interval=0.0, validator=lambda p: object())


def test_wait_for_control_port_stops_when_host_exits(monkeypatch):
    monkeypatch.delenv(sdk.CONTROL_PORT_ENV, raising=False)
    monkeypatch.setattr(sdk, "listening_ports", lambda _pid: [])
    monkeypatch.setattr(sdk, "_pid_alive", lambda _pid: False)
    with pytest.raises(sdk.ShogunSdkError, match="exited before"):
        sdk.wait_for_control_port(42, timeout=30, interval=0.0, validator=lambda p: object())


def test_wait_for_control_port_env_override_is_validated(monkeypatch):
    monkeypatch.setenv(sdk.CONTROL_PORT_ENV, "803")
    monkeypatch.setattr(sdk, "listening_ports", lambda _pid: [803])
    monkeypatch.setattr(sdk, "_pid_alive", lambda _pid: True)
    assert (
        sdk.wait_for_control_port(42, timeout=5, interval=0.0, validator=lambda p: object()) == 803
    )


def test_control_port_timeout_env_is_bounded(monkeypatch):
    monkeypatch.setenv(sdk.CONTROL_PORT_TIMEOUT_ENV, "not-a-number")
    with pytest.raises(sdk.ShogunSdkError, match="must be a number of seconds"):
        sdk._control_port_timeout()
    monkeypatch.setenv(sdk.CONTROL_PORT_TIMEOUT_ENV, "0")
    with pytest.raises(sdk.ShogunSdkError, match="must be positive"):
        sdk._control_port_timeout()
    monkeypatch.setenv(sdk.CONTROL_PORT_TIMEOUT_ENV, "42")
    assert sdk._control_port_timeout() == 42.0
