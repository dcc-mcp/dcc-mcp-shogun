from __future__ import annotations

import json
import logging
import threading

from dcc_mcp_shogun import server
from dcc_mcp_shogun.sdk import ProcessLiveness


def test_monitor_stops_immediately_for_confirmed_exact_pid_exit():
    probed_pids = []

    def probe(pid):
        probed_pids.append(pid)
        return ProcessLiveness.EXITED

    clock = iter([10.0, 11.25])
    receipt = server.monitor_host_liveness(
        4242,
        probe=probe,
        monotonic=lambda: next(clock),
        poll_interval_seconds=0,
    )

    assert receipt.as_dict() == {
        "schema_version": "1.0",
        "exit_reason": "host_process_exited",
        "uptime_seconds": 1.25,
        "consecutive_probe_failures": 0,
    }
    assert probed_pids == [4242]
    assert "4242" not in str(receipt.as_dict())


def test_monitor_fails_closed_after_bounded_indeterminate_probes():
    probed_pids = []
    safety_stop = threading.Event()

    def probe(pid):
        probed_pids.append(pid)
        if len(probed_pids) == 4:
            safety_stop.set()
        return ProcessLiveness.INDETERMINATE

    clock = iter([20.0, 22.0])
    receipt = server.monitor_host_liveness(
        5151,
        stopped=safety_stop,
        probe=probe,
        monotonic=lambda: next(clock),
        poll_interval_seconds=0,
    )

    assert receipt.exit_reason == "host_process_probe_failed"
    assert receipt.consecutive_probe_failures == 3
    assert probed_pids == [5151, 5151, 5151]


def test_monitor_sanitizes_probe_exceptions_as_indeterminate():
    probes = 0

    def probe(_pid):
        nonlocal probes
        probes += 1
        raise OSError(r"sensitive C:\host\detail")

    clock = iter([25.0, 26.0])
    receipt = server.monitor_host_liveness(
        5656,
        probe=probe,
        monotonic=lambda: next(clock),
        poll_interval_seconds=0,
    )

    assert receipt.exit_reason == "host_process_probe_failed"
    assert receipt.consecutive_probe_failures == 3
    assert "sensitive" not in str(receipt.as_dict())
    assert probes == 3


def test_monitor_retries_transient_failure_and_resets_the_failure_count():
    statuses = iter(
        [
            ProcessLiveness.INDETERMINATE,
            ProcessLiveness.ALIVE,
            ProcessLiveness.INDETERMINATE,
            ProcessLiveness.INDETERMINATE,
            ProcessLiveness.EXITED,
        ]
    )
    clock = iter([30.0, 34.0])

    receipt = server.monitor_host_liveness(
        6262,
        probe=lambda _pid: next(statuses),
        monotonic=lambda: next(clock),
        poll_interval_seconds=0,
    )

    assert receipt.exit_reason == "host_process_exited"
    assert receipt.consecutive_probe_failures == 2


def test_monitor_reports_signal_without_probing_again():
    stopped = threading.Event()
    stopped.set()
    clock = iter([40.0, 40.5])

    receipt = server.monitor_host_liveness(
        7373,
        stopped=stopped,
        probe=lambda _pid: (_ for _ in ()).throw(AssertionError("must not probe")),
        monotonic=lambda: next(clock),
        poll_interval_seconds=0,
    )

    assert receipt.exit_reason == "signal"
    assert receipt.uptime_seconds == 0.5


def test_monitor_keeps_sustained_liveness_until_signaled():
    stopped = threading.Event()
    probes = 0

    def probe(_pid):
        nonlocal probes
        probes += 1
        if probes == 4:
            stopped.set()
        return ProcessLiveness.ALIVE

    clock = iter([50.0, 55.0])
    receipt = server.monitor_host_liveness(
        8484,
        stopped=stopped,
        probe=probe,
        monotonic=lambda: next(clock),
        poll_interval_seconds=0,
    )

    assert receipt.exit_reason == "signal"
    assert receipt.consecutive_probe_failures == 0
    assert probes == 4


def test_main_emits_a_sanitized_structured_exit_receipt(monkeypatch, caplog):
    class ImmediateEvent:
        def set(self):
            pass

        def wait(self, _timeout):
            return False

    receipt = server.SidecarExitReceipt(
        exit_reason="host_process_probe_failed",
        uptime_seconds=12.5,
        consecutive_probe_failures=3,
    )
    stopped = []
    monkeypatch.setattr(server.threading, "Event", ImmediateEvent)
    monkeypatch.setattr(server.signal, "signal", lambda *_args: None)
    monkeypatch.setattr(server, "start_server", lambda **_kwargs: object())
    monkeypatch.setattr(server, "stop_server", lambda: stopped.append(True))
    monkeypatch.setattr(
        server,
        "monitor_host_liveness",
        lambda host_pid, *, stopped: receipt if host_pid == 9595 else None,
    )

    with caplog.at_level(logging.INFO, logger=server.__name__):
        server.main(["--host-pid", "9595", "--sdk-path", r"C:\sensitive\sdk"])

    payload = json.loads(caplog.records[-1].getMessage())
    assert payload == receipt.as_dict()
    assert "9595" not in caplog.text
    assert "sensitive" not in caplog.text
    assert stopped == [True]
