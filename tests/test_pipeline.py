from __future__ import annotations

import importlib.util
from pathlib import Path
from threading import Event

import pytest
import yaml
from dcc_mcp_core import InProcessCallableDispatcher
from jsonschema import Draft202012Validator

from dcc_mcp_shogun import runtime
from dcc_mcp_shogun.sdk import ShogunSdkError


def _pipeline_skill_module():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_shogun"
        / "skills"
        / "shogun-pipeline"
        / "scripts"
        / "run_pipeline_command.py"
    )
    spec = importlib.util.spec_from_file_location("shogun_pipeline_skill", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _pipeline_output_validator():
    manifest = (
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_shogun"
        / "skills"
        / "shogun-pipeline"
        / "tools.yaml"
    )
    tool = yaml.safe_load(manifest.read_text(encoding="utf-8"))["tools"][0]
    schema = tool["output_schema"]
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


@pytest.fixture(autouse=True)
def _fixed_pipeline_abi(monkeypatch):
    monkeypatch.setenv("DCC_MCP_SHOGUN_PIPELINE_ABI", "fixed9-v1")


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
        "receipt_version": "1.0",
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
        "effects_verified": False,
        "verification_required": True,
    }
    assert "completed" not in repr(result)


def test_pipeline_async_envelope_reaches_a_terminal_unverified_receipt(monkeypatch):
    started = Event()
    release = Event()
    completed = Event()
    outcomes = []

    class BlockingClient(FakeClient):
        def HSL(self, command: str) -> str:
            self.calls.append(command)
            started.set()
            assert release.wait(1.0)
            return "completed"

    client = BlockingClient()
    monkeypatch.setenv(runtime.PIPELINE_ALLOWLIST_ENV, "studioPipeline")
    monkeypatch.setattr(runtime, "connect_client", lambda: client)
    dispatcher = InProcessCallableDispatcher()
    pipeline_skill = _pipeline_skill_module()

    def record(outcome):
        outcomes.append(outcome)
        completed.set()

    pending = dispatcher.submit_async_callable(
        "pipeline-request",
        lambda: pipeline_skill.main(**_arguments()),
        affinity="any",
        timeout_ms=1_800_000,
        on_complete=record,
    )

    assert pending.request_id == "pipeline-request"
    assert pending.job_id
    assert started.wait(1.0)
    assert outcomes == []

    release.set()
    assert completed.wait(1.0)
    assert outcomes[0].ok is True
    result = outcomes[0].value
    assert result["success"] is True
    assert result["context"]["host_acknowledged"] is True
    assert result["context"]["effects_verified"] is False
    assert result["context"]["verification_required"] is True
    _pipeline_output_validator().validate(result)


def test_pipeline_async_terminal_failure_does_not_replay(monkeypatch):
    completed = Event()
    outcomes = []

    class FailingClient(FakeClient):
        def HSL(self, command: str) -> str:
            self.calls.append(command)
            raise RuntimeError("host rejected command")

    client = FailingClient()
    monkeypatch.setenv(runtime.PIPELINE_ALLOWLIST_ENV, "studioPipeline")
    monkeypatch.setattr(runtime, "connect_client", lambda: client)
    dispatcher = InProcessCallableDispatcher()
    pipeline_skill = _pipeline_skill_module()

    def record(outcome):
        outcomes.append(outcome)
        completed.set()

    dispatcher.submit_async_callable(
        "pipeline-request",
        lambda: pipeline_skill.main(**_arguments()),
        affinity="any",
        on_complete=record,
    )

    assert completed.wait(1.0)
    assert outcomes[0].ok is True
    result = outcomes[0].value
    assert result["success"] is False
    assert result["error"] == "ShogunSdkError"
    assert result["context"] == {"error_type": "ShogunSdkError"}
    _pipeline_output_validator().validate(result)
    assert len(client.calls) == 1


def test_pipeline_has_no_commands_enabled_by_default(monkeypatch):
    monkeypatch.delenv(runtime.PIPELINE_ALLOWLIST_ENV, raising=False)
    monkeypatch.setattr(runtime, "connect_client", lambda: pytest.fail("must not connect"))

    with pytest.raises(ShogunSdkError, match="No pipeline commands"):
        runtime.run_pipeline_command(**_arguments())


@pytest.mark.parametrize("abi", (None, "fixed9-v2", "pipeline_processer"))
def test_pipeline_requires_explicit_fixed9_v1_abi_before_connect(monkeypatch, abi):
    monkeypatch.setenv(runtime.PIPELINE_ALLOWLIST_ENV, "studioPipeline")
    if abi is None:
        monkeypatch.delenv("DCC_MCP_SHOGUN_PIPELINE_ABI", raising=False)
    else:
        monkeypatch.setenv("DCC_MCP_SHOGUN_PIPELINE_ABI", abi)
    monkeypatch.setattr(runtime, "connect_client", lambda: pytest.fail("must not connect"))

    with pytest.raises(ShogunSdkError, match="pipeline command ABI"):
        runtime.run_pipeline_command(**_arguments())


def test_pipeline_policy_reports_only_bounded_abi_attestation(monkeypatch):
    monkeypatch.setenv(runtime.PIPELINE_ALLOWLIST_ENV, "studioPipeline")
    monkeypatch.setenv("DCC_MCP_SHOGUN_PIPELINE_ABI", "secret-unsupported-value")

    receipt = runtime.pipeline_policy_receipt("studioPipeline")

    assert receipt == {
        "configured": True,
        "valid": True,
        "command_count": 1,
        "restart_required": True,
        "requested_command_enabled": True,
        "abi_configured": True,
        "abi_valid": False,
        "abi_version": None,
    }
    assert "secret-unsupported-value" not in repr(receipt)


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
