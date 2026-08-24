from __future__ import annotations

import json

import pytest

from dcc_mcp_shogun import diagnostics


def _successful_host(monkeypatch, tmp_path):
    monkeypatch.setattr(diagnostics.sys, "platform", "win32")
    monkeypatch.setattr(diagnostics, "_installed_version", lambda _name: "0.19.92")
    monkeypatch.setattr(diagnostics, "process_is_alive", lambda pid: pid == 42)
    monkeypatch.setattr(diagnostics, "process_executable", lambda _pid: tmp_path / "host.exe")
    monkeypatch.setattr(diagnostics, "host_product_version", lambda _pid: "1.19")
    monkeypatch.setattr(diagnostics, "resolve_sdk_path", lambda *_args: tmp_path / "sdk")
    monkeypatch.setattr(diagnostics, "configure_sdk", lambda path: path)
    monkeypatch.setattr(diagnostics, "candidate_control_ports", lambda _pid: [803])
    monkeypatch.setattr(diagnostics, "validate_control_port", lambda _port: object())


def test_verify_reports_directly_usable_without_sensitive_bindings(monkeypatch, tmp_path):
    _successful_host(monkeypatch, tmp_path)
    monkeypatch.delenv("DCC_MCP_SHOGUN_PIPELINE_ALLOWLIST", raising=False)

    report = diagnostics.collect_diagnostics(mode="verify", host_pid=42, sdk_path=tmp_path)

    assert report["status"] == "ok"
    assert report["directly_usable"] is True
    assert report["failure_stage"] is None
    assert report["verify"]["checks_passed"] == report["verify"]["checks_total"] == 8
    assert {item["status"] for item in report["steps"]} == {"ok"}
    assert report["pipeline_policy"] == {
        "configured": False,
        "valid": True,
        "command_count": 0,
        "restart_required": True,
        "abi_configured": False,
        "abi_valid": False,
        "abi_version": None,
    }
    serialized = json.dumps(report)
    assert "42" not in serialized
    assert str(tmp_path) not in serialized
    assert "803" not in serialized


def test_verify_reports_requested_pipeline_membership_without_command_names(monkeypatch, tmp_path):
    _successful_host(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "DCC_MCP_SHOGUN_PIPELINE_ALLOWLIST",
        "otherCommand, studioPipeline",
    )

    report = diagnostics.collect_diagnostics(
        mode="verify",
        host_pid=42,
        sdk_path=tmp_path,
        pipeline_command="studioPipeline",
    )

    assert report["pipeline_policy"] == {
        "configured": True,
        "valid": True,
        "command_count": 2,
        "restart_required": True,
        "requested_command_enabled": True,
        "abi_configured": False,
        "abi_valid": False,
        "abi_version": None,
    }
    serialized = json.dumps(report)
    assert "studioPipeline" not in serialized
    assert "otherCommand" not in serialized


def test_verify_reports_invalid_pipeline_policy_without_gating_adapter(monkeypatch, tmp_path):
    _successful_host(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "DCC_MCP_SHOGUN_PIPELINE_ALLOWLIST",
        "studioPipeline;DeleteAllKeys",
    )

    report = diagnostics.collect_diagnostics(mode="verify", host_pid=42, sdk_path=tmp_path)

    assert report["directly_usable"] is True
    assert report["pipeline_policy"] == {
        "configured": True,
        "valid": False,
        "command_count": 1,
        "restart_required": True,
        "abi_configured": False,
        "abi_valid": False,
        "abi_version": None,
    }
    assert "DeleteAllKeys" not in json.dumps(report)


def test_verify_distinguishes_oversized_pipeline_policy_by_bounded_count(monkeypatch, tmp_path):
    _successful_host(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "DCC_MCP_SHOGUN_PIPELINE_ALLOWLIST",
        ",".join(f"pipeline{index}" for index in range(33)),
    )

    report = diagnostics.collect_diagnostics(mode="verify", host_pid=42, sdk_path=tmp_path)

    assert report["pipeline_policy"] == {
        "configured": True,
        "valid": False,
        "command_count": 33,
        "restart_required": True,
        "abi_configured": False,
        "abi_valid": False,
        "abi_version": None,
    }
    assert "pipeline0" not in json.dumps(report)


def test_doctor_requires_an_explicit_host_binding(monkeypatch):
    monkeypatch.setattr(diagnostics.sys, "platform", "win32")
    monkeypatch.setattr(diagnostics, "_installed_version", lambda _name: "0.19.92")
    monkeypatch.delenv("DCC_MCP_SHOGUN_HOST_PID", raising=False)

    report = diagnostics.collect_diagnostics(mode="doctor")

    assert report["directly_usable"] is False
    assert report["failure_stage"] == "host_process"
    assert report["failure_reason"] == "host_pid_required"
    assert report["config"]["host_pid_source"] == "missing"
    assert report["next_steps"][0]["command"] == ["dcc-mcp-shogun", "doctor", "--json"]
    assert report["next_steps"][0]["requires"] == [
        {"environment": "DCC_MCP_SHOGUN_HOST_PID", "type": "positive_integer"}
    ]


def test_invalid_environment_host_pid_is_typed_and_never_probed(monkeypatch):
    monkeypatch.setattr(diagnostics.sys, "platform", "win32")
    monkeypatch.setattr(diagnostics, "_installed_version", lambda _name: "0.19.92")
    monkeypatch.setenv("DCC_MCP_SHOGUN_HOST_PID", "not-a-pid")
    monkeypatch.setattr(
        diagnostics,
        "process_is_alive",
        lambda _pid: pytest.fail("invalid host must not be probed"),
    )

    report = diagnostics.collect_diagnostics(mode="doctor")

    assert report["failure_reason"] == "invalid_host_pid"
    assert report["config"]["host_pid_source"] == "environment_invalid"
    assert all(item.get("reason") == "invalid_host_pid" for item in report["steps"][3:])


def test_doctor_distinguishes_indeterminate_host_probe(monkeypatch):
    monkeypatch.setattr(diagnostics.sys, "platform", "win32")
    monkeypatch.setattr(diagnostics, "_installed_version", lambda _name: "0.19.92")
    monkeypatch.setattr(
        diagnostics,
        "process_is_alive",
        lambda _pid: (_ for _ in ()).throw(OSError("sensitive probe detail")),
    )

    report = diagnostics.collect_diagnostics(mode="doctor", host_pid=42)
    host_check = next(item for item in report["steps"] if item["id"] == "host_process")

    assert host_check["observed"] == "indeterminate"
    assert host_check["reason"] == "host_process_probe_failed"
    assert report["failure_reason"] == "host_process_probe_failed"
    assert "sensitive probe detail" not in json.dumps(report)


def test_doctor_reports_confirmed_host_exit_separately(monkeypatch):
    monkeypatch.setattr(diagnostics.sys, "platform", "win32")
    monkeypatch.setattr(diagnostics, "_installed_version", lambda _name: "0.19.92")
    monkeypatch.setattr(diagnostics, "process_is_alive", lambda _pid: False)

    report = diagnostics.collect_diagnostics(mode="doctor", host_pid=42)
    host_check = next(item for item in report["steps"] if item["id"] == "host_process")

    assert host_check["observed"] == "exited"
    assert host_check["reason"] == "host_process_exited"
    assert report["failure_reason"] == "host_process_exited"
    assert report["next_steps"][0]["id"] == "rebind_exact_host"


def test_core_and_platform_floors_fail_before_host_probe(monkeypatch):
    monkeypatch.setattr(diagnostics.sys, "platform", "linux")
    monkeypatch.setattr(diagnostics, "_installed_version", lambda _name: "0.19.85")
    monkeypatch.setattr(
        diagnostics,
        "process_is_alive",
        lambda _pid: pytest.fail("host must not be probed"),
    )

    report = diagnostics.collect_diagnostics(mode="doctor", host_pid=42)

    assert report["directly_usable"] is False
    assert report["failure_stage"] == "platform"
    assert report["steps"][0]["reason"] == "unsupported_platform"
    assert report["steps"][2]["reason"] == "incompatible_core_version"
    assert all(item["status"] == "skipped" for item in report["steps"][3:])


def test_host_and_sdk_version_floors_are_enforced(monkeypatch, tmp_path):
    _successful_host(monkeypatch, tmp_path)
    monkeypatch.setattr(diagnostics, "host_product_version", lambda _pid: "1.18")
    monkeypatch.setattr(
        diagnostics,
        "resolve_sdk_path",
        lambda *_args: pytest.fail("unsupported host must not load the SDK"),
    )

    report = diagnostics.collect_diagnostics(mode="verify", host_pid=42)

    assert report["failure_stage"] == "host_version"
    assert report["failure_reason"] == "unsupported_host_version"
    assert report["min_host_version"] == "1.19"
    assert report["steps"][-2]["status"] == "skipped"
    assert report["steps"][-1]["status"] == "skipped"


def test_control_stream_requires_a_real_sdk_handshake(monkeypatch, tmp_path):
    _successful_host(monkeypatch, tmp_path)
    monkeypatch.setattr(diagnostics, "validate_control_port", lambda _port: None)

    report = diagnostics.collect_diagnostics(mode="verify", host_pid=42)

    assert report["directly_usable"] is False
    assert report["failure_stage"] == "control_stream"
    assert report["failure_reason"] == "control_stream_unavailable"
    assert report["next_steps"][-1]["id"] == "recheck_control_stream"


@pytest.mark.parametrize(("verb", "expected"), (("doctor", 10), ("verify", 40)))
def test_cli_json_contract_and_failure_exit_codes(monkeypatch, capsys, verb, expected):
    monkeypatch.setattr(
        diagnostics,
        "collect_diagnostics",
        lambda **_kwargs: {
            "schema_version": "1.0",
            "status": "preflight_failed" if verb == "doctor" else "verify_failed",
            "dcc_type": "shogun",
            "adapter_version": "0.9.0",
            "core_version": "0.19.92",
            "directly_usable": False,
            "steps": [],
            "next_steps": [],
            "verify": {},
        },
    )

    assert diagnostics.run_cli([verb, "--json"]) == expected
    expected_status = "preflight_failed" if verb == "doctor" else "verify_failed"
    assert json.loads(capsys.readouterr().out)["status"] == expected_status


def test_cli_success_exit_code(monkeypatch, capsys):
    monkeypatch.setattr(
        diagnostics,
        "collect_diagnostics",
        lambda **_kwargs: {
            "status": "ok",
            "directly_usable": True,
            "steps": [],
            "next_steps": [],
        },
    )

    assert diagnostics.run_cli(["verify"]) == 0
    assert "directly_usable: true" in capsys.readouterr().out


def test_cli_accepts_bounded_pipeline_membership_query(monkeypatch, capsys):
    captured = {}

    def collect(**kwargs):
        captured.update(kwargs)
        return {
            "status": "ok",
            "directly_usable": True,
            "pipeline_policy": {
                "configured": True,
                "valid": True,
                "command_count": 1,
                "restart_required": True,
                "requested_command_enabled": True,
            },
            "steps": [],
            "next_steps": [],
        }

    monkeypatch.setattr(diagnostics, "collect_diagnostics", collect)

    assert diagnostics.run_cli(["verify", "--pipeline-command", "studioPipeline", "--json"]) == 0
    assert captured["pipeline_command"] == "studioPipeline"
    assert "studioPipeline" not in capsys.readouterr().out
