from __future__ import annotations

import pytest

from dcc_mcp_shogun import runtime
from dcc_mcp_shogun.sdk import ShogunSdkError


class FakeClient:
    def __init__(self, result: str = "") -> None:
        self.result = result
        self.calls = []

    def HSL(self, command: str) -> str:
        self.calls.append(command)
        return self.result


def _arguments(**overrides):
    values = {
        "command_name": "studioPipeline",
        "load_type": 2,
        "processing_mode": "model",
        "export_c3d": True,
        "export_fbx": False,
        "fill_gap_mode": "labeling_constraint",
        "fill_gap_width": 50,
        "filter_cutoff": 0.3,
        "filter_threshold": 15.0,
        "label_threshold": 10.0,
    }
    values.update(overrides)
    return values


def test_pipeline_command_maps_only_typed_values_to_fixed_hsl(monkeypatch):
    client = FakeClient("completed")
    monkeypatch.setenv(runtime.PIPELINE_ALLOWLIST_ENV, "otherCommand, studioPipeline")
    monkeypatch.setattr(runtime, "connect_client", lambda: client)

    result = runtime.run_pipeline_command(**_arguments())

    assert client.calls == ["studioPipeline(2, 1, 1, 0, 2, 50, 0.3, 15.0, 10.0);"]
    assert result == {
        "command_name": "studioPipeline",
        "parameters": {
            "load_type": 2,
            "processing_mode": "model",
            "export_c3d": True,
            "export_fbx": False,
            "fill_gap_mode": "labeling_constraint",
            "fill_gap_width": 50,
            "filter_cutoff": 0.3,
            "filter_threshold": 15.0,
            "label_threshold": 10.0,
        },
        "host_acknowledged": True,
        "host_result_reported": True,
    }
    assert "completed" not in repr(result)


def test_pipeline_has_no_commands_enabled_by_default(monkeypatch):
    monkeypatch.delenv(runtime.PIPELINE_ALLOWLIST_ENV, raising=False)
    monkeypatch.setattr(runtime, "connect_client", lambda: pytest.fail("must not connect"))

    with pytest.raises(ShogunSdkError, match="No pipeline commands"):
        runtime.run_pipeline_command(**_arguments())


def test_pipeline_rejects_unallowlisted_or_injectable_command_before_connect(monkeypatch):
    monkeypatch.setenv(runtime.PIPELINE_ALLOWLIST_ENV, "studioPipeline")
    monkeypatch.setattr(runtime, "connect_client", lambda: pytest.fail("must not connect"))

    with pytest.raises(ShogunSdkError, match="not enabled"):
        runtime.run_pipeline_command(**_arguments(command_name="otherCommand"))
    with pytest.raises(ValueError, match="simple HSL command"):
        runtime.run_pipeline_command(**_arguments(command_name="studioPipeline;DeleteAllKeys"))


def test_pipeline_rejects_invalid_operator_allowlist(monkeypatch):
    monkeypatch.setenv(runtime.PIPELINE_ALLOWLIST_ENV, "studioPipeline;DeleteAllKeys")
    monkeypatch.setattr(runtime, "connect_client", lambda: pytest.fail("must not connect"))

    with pytest.raises(ShogunSdkError, match="invalid command name"):
        runtime.run_pipeline_command(**_arguments())


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("load_type", 4, "load_type"),
        ("processing_mode", "arbitrary", "processing_mode"),
        ("export_c3d", "yes", "true or false"),
        ("fill_gap_mode", "arbitrary", "fill_gap_mode"),
        ("fill_gap_width", 10_001, "fill_gap_width"),
        ("filter_cutoff", float("nan"), "filter_cutoff"),
    ],
)
def test_pipeline_parameters_are_bounded_before_connect(monkeypatch, field, value, message):
    monkeypatch.setenv(runtime.PIPELINE_ALLOWLIST_ENV, "studioPipeline")
    monkeypatch.setattr(runtime, "connect_client", lambda: pytest.fail("must not connect"))

    with pytest.raises(ValueError, match=message):
        runtime.run_pipeline_command(**_arguments(**{field: value}))


def test_pipeline_fails_closed_when_hsl_capability_is_missing(monkeypatch):
    monkeypatch.setenv(runtime.PIPELINE_ALLOWLIST_ENV, "studioPipeline")
    monkeypatch.setattr(runtime, "connect_client", object)

    with pytest.raises(ShogunSdkError, match="does not expose HSL"):
        runtime.run_pipeline_command(**_arguments())


def test_pipeline_rejects_invalid_host_result(monkeypatch):
    client = FakeClient("x" * (runtime.MAX_PIPELINE_RESULT_LENGTH + 1))
    monkeypatch.setenv(runtime.PIPELINE_ALLOWLIST_ENV, "studioPipeline")
    monkeypatch.setattr(runtime, "connect_client", lambda: client)

    with pytest.raises(ShogunSdkError, match="invalid HSL result"):
        runtime.run_pipeline_command(**_arguments())
