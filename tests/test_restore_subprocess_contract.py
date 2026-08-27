from __future__ import annotations

import json
import queue
import runpy
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parents[1]
HARNESS = ROOT / "tests" / "restore_subprocess_harness.py"
CONTRACT = ROOT / "docs" / "contracts" / "restore-scene.yaml"
ADR = ROOT / "docs" / "adr" / "0001-bounded-recovery-scene-restore.md"


def _run_harness(*args: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(HARNESS), *(str(arg) for arg in args)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def _start_harness(*args: object) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, str(HARNESS), *(str(arg) for arg in args)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _readline_with_timeout(
    process: subprocess.Popen[str],
    *,
    timeout: float = 10,
) -> str:
    assert process.stdout is not None
    lines: queue.Queue[str] = queue.Queue(maxsize=1)
    reader = threading.Thread(
        target=lambda: lines.put(process.stdout.readline()),
        daemon=True,
    )
    reader.start()
    try:
        return lines.get(timeout=timeout).strip()
    except queue.Empty as exc:
        raise subprocess.TimeoutExpired(process.args, timeout) from exc


def test_broker_listener_capacity_covers_concurrent_waiters():
    namespace = runpy.run_path(
        str(HARNESS),
        run_name="restore_subprocess_contract_capacity",
    )

    assert "_open_broker_listener" in namespace
    open_listener = namespace["_open_broker_listener"]
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_listener(address, *, backlog, authkey):
        captured.update(address=address, backlog=backlog, authkey=authkey)
        return sentinel

    open_listener.__globals__["Listener"] = fake_listener

    assert open_listener(b"bounded-test-authkey") is sentinel
    assert captured == {
        "address": ("127.0.0.1", 0),
        "backlog": 8,
        "authkey": b"bounded-test-authkey",
    }


def test_process_readiness_timeout_is_bounded():
    sleeper = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            _readline_with_timeout(sleeper, timeout=0.05)
    finally:
        sleeper.terminate()
        sleeper.wait(timeout=10)


def _persist_owner_claim(tmp_path: Path, command: str = "owner-claim") -> None:
    owner = _run_harness(command, tmp_path, tmp_path / "owner-result.json")
    assert owner.returncode == 0, owner.stderr


def test_sdk_entry_process_exit_terminalizes_without_guard_inheritance_or_redispatch(
    tmp_path,
):
    result_path = tmp_path / "dispatch-owner-result.json"

    owner = _run_harness("dispatch-owner", tmp_path, result_path)

    assert owner.returncode == 0, owner.stderr
    owner_result = json.loads(result_path.read_text(encoding="utf-8"))
    assert owner_result == {
        "job_id": "restore-job-cross-process-0001",
        "status": "dispatch_uncertain",
        "handle_disposition": "owned_by_process_epoch",
        "sdk_entry_count": 1,
        "dispatch_count": 0,
        "process_exited_without_request_cleanup": True,
    }
    result_paths = [tmp_path / f"dispatch-successor-{index}.json" for index in range(2)]
    successors = [_start_harness("recover", tmp_path, path) for path in result_paths]
    completed = [successor.communicate(timeout=10) for successor in successors]
    for successor, (_, stderr) in zip(successors, completed):
        assert successor.returncode == 0, stderr

    results = [json.loads(path.read_text(encoding="utf-8")) for path in result_paths]
    assert sorted(result["terminalized_by_this_process"] for result in results) == [False, True]
    assert {result["status"] for result in results} == {"terminal"}
    assert {result["outcome"] for result in results} == {"failed_unknown"}
    assert {result["terminal_source"] for result in results} == {"readback_owner_lost"}

    query = _run_harness("query", tmp_path)
    assert query.returncode == 0, query.stderr
    durable = json.loads(query.stdout)
    assert durable["sdk_entry_count"] == 1
    assert durable["dispatch_count"] == 0
    assert durable["sdk_readback_count"] == 0
    assert durable["terminalize_count"] == 1
    assert durable["claim_epoch"] == durable["terminalizer_epoch"]
    assert durable["handle_disposition"] == "kernel_closed_on_process_death"
    assert durable["cleanup_disposition"] == "released_after_error_verified_closed"
    assert durable["tombstone"]["terminal_source"] == "readback_owner_lost"
    assert durable["notification"]["pending"] == 1


def test_process_a_persists_readback_claim_before_real_process_exit(tmp_path):
    result_path = tmp_path / "owner-result.json"

    owner = _run_harness("owner-claim", tmp_path, result_path)

    assert owner.returncode == 0, owner.stderr
    owner_result = json.loads(result_path.read_text(encoding="utf-8"))
    assert owner_result == {
        "job_id": "restore-job-cross-process-0001",
        "status": "readback_in_progress",
        "handle_disposition": "owned_by_process",
        "process_exited_without_request_cleanup": True,
    }
    query = _run_harness("query", tmp_path)
    assert query.returncode == 0, query.stderr
    assert json.loads(query.stdout)["status"] == "readback_in_progress"


def test_exactly_one_successor_recovers_the_dead_process_claim(tmp_path):
    _persist_owner_claim(tmp_path)
    result_paths = [tmp_path / f"successor-{index}.json" for index in range(2)]
    successors = [_start_harness("recover", tmp_path, result_path) for result_path in result_paths]

    completed = [successor.communicate(timeout=10) for successor in successors]

    assert len(successors) == len(completed)
    for successor, (_, stderr) in zip(successors, completed):
        assert successor.returncode == 0, stderr
    results = [json.loads(path.read_text(encoding="utf-8")) for path in result_paths]
    assert sorted(result["terminalized_by_this_process"] for result in results) == [False, True]
    assert {result["status"] for result in results} == {"terminal"}
    assert {result["outcome"] for result in results} == {"failed_unknown"}
    assert {result["terminal_source"] for result in results} == {"readback_owner_lost"}

    query = _run_harness("query", tmp_path)
    assert query.returncode == 0, query.stderr
    durable = json.loads(query.stdout)
    assert durable["terminalize_count"] == 1
    assert durable["claim_epoch"] == durable["terminalizer_epoch"]
    assert durable["dispatch_count"] == 1
    assert durable["sdk_readback_count"] == 0
    assert durable["handle_disposition"] == "kernel_closed_on_process_death"
    assert durable["cleanup_disposition"] == "released_after_error_verified_closed"


@pytest.mark.parametrize("owner_command", ("owner-claim", "dispatch-owner"))
def test_cleanup_and_tombstone_reconcile_after_successor_crash(tmp_path, owner_command):
    _persist_owner_claim(tmp_path, owner_command)
    crashed = _run_harness(
        "recover",
        tmp_path,
        tmp_path / "crashed-successor.json",
        "--crash-after-cleanup-pending",
    )

    assert crashed.returncode == 23
    pending = _run_harness("query", tmp_path)
    assert pending.returncode == 0, pending.stderr
    pending_state = json.loads(pending.stdout)
    assert pending_state["status"] == "cleanup_pending"
    assert pending_state["handle_disposition"] == "kernel_closed_on_process_death"
    assert pending_state["tombstone"] is None

    recovered = _run_harness("recover", tmp_path, tmp_path / "recovered-successor.json")

    assert recovered.returncode == 0, recovered.stderr
    durable = _run_harness("query", tmp_path)
    assert durable.returncode == 0, durable.stderr
    durable_state = json.loads(durable.stdout)
    assert durable_state["status"] == "terminal"
    assert durable_state["terminalize_count"] == 1
    assert durable_state["tombstone"] == {
        "job_id": "restore-job-cross-process-0001",
        "outcome": "failed_unknown",
        "terminal_source": "readback_owner_lost",
        "terminalizer_epoch": durable_state["terminalizer_epoch"],
    }
    assert durable_state["notification"] == {
        "job_id": "restore-job-cross-process-0001",
        "pending": 1,
        "attempts": 0,
        "acknowledged": 0,
    }


@pytest.mark.parametrize("owner_command", ("owner-claim", "dispatch-owner"))
def test_notification_baseexception_replays_to_multiple_process_waiters(
    tmp_path,
    owner_command,
):
    _persist_owner_claim(tmp_path, owner_command)
    endpoint_path = tmp_path / "notification-broker.json"
    broker = _start_harness("broker", endpoint_path)
    waiters: list[subprocess.Popen[str]] = []
    try:
        assert broker.stdout is not None
        broker_ready = _readline_with_timeout(broker)
        assert broker_ready == "READY"
        waiters = [
            _start_harness(
                "wait",
                endpoint_path,
                "restore-job-cross-process-0001",
            )
            for _ in range(4)
        ]
        for waiter in waiters:
            assert waiter.stdout is not None
            assert _readline_with_timeout(waiter) == "READY"

        cleanup_crash = _run_harness(
            "recover",
            tmp_path,
            tmp_path / "cleanup-crash.json",
            "--crash-after-cleanup-pending",
        )
        assert cleanup_crash.returncode == 23
        notification_crash = _run_harness(
            "recover",
            tmp_path,
            tmp_path / "notification-crash.json",
            "--broker-endpoint",
            endpoint_path,
            "--crash-before-notify",
        )
        assert notification_crash.returncode != 0
        assert "InjectedNotificationBaseException" in notification_crash.stderr

        pending = _run_harness("query", tmp_path)
        assert pending.returncode == 0, pending.stderr
        pending_state = json.loads(pending.stdout)
        assert pending_state["status"] == "terminal"
        assert pending_state["tombstone"]["terminal_source"] == "readback_owner_lost"
        assert pending_state["notification"]["pending"] == 1
        assert pending_state["notification"]["acknowledged"] == 0

        replay_path = tmp_path / "notification-replay.json"
        replay = _run_harness(
            "recover",
            tmp_path,
            replay_path,
            "--broker-endpoint",
            endpoint_path,
        )
        assert replay.returncode == 0, replay.stderr
        replay_result = json.loads(replay_path.read_text(encoding="utf-8"))
        assert replay_result["notification_delivered_by_this_process"] is True
        assert replay_result["waiters_woken"] == 4

        wakeups = []
        for waiter in waiters:
            assert waiter.stdout is not None
            wakeups.append(json.loads(_readline_with_timeout(waiter)))
            assert waiter.wait(timeout=10) == 0
        assert (
            wakeups
            == [
                {
                    "job_id": "restore-job-cross-process-0001",
                    "terminal_source": "readback_owner_lost",
                }
            ]
            * 4
        )

        durable = _run_harness("query", tmp_path)
        assert durable.returncode == 0, durable.stderr
        notification = json.loads(durable.stdout)["notification"]
        assert notification == {
            "job_id": "restore-job-cross-process-0001",
            "pending": 0,
            "attempts": 1,
            "acknowledged": 1,
        }
    finally:
        if broker.poll() is None:
            stopped = _run_harness("broker-stop", endpoint_path)
            assert stopped.returncode == 0, stopped.stderr
            assert broker.wait(timeout=10) == 0
        for waiter in waiters:
            if waiter.poll() is None:
                waiter.terminate()
                waiter.wait(timeout=10)


def test_published_contract_requires_the_executable_process_boundary():
    contract = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))

    assert contract["async_job_contract"]["process_boundary"] == {
        "executable_harness": "subprocess_sqlite_and_kernel_lease",
        "owner_claim_persistence": "sqlite_full_sync_before_process_exit",
        "request_local_objects": "forbidden_across_process_boundary",
        "lease": "kernel_released_exclusive_file_lock",
        "lease_binding": "prior_epoch_token_must_match_durable_owner",
        "dispatch_reservation_owner": "exact_process_epoch_lease",
        "dispatch_owner_exit": "terminalize_failed_unknown_without_guard_inheritance",
        "dispatch_recovery": "zero_redispatch_cleanup_tombstone_notification",
        "takeover": "only_after_prior_process_lease_release",
        "successor_race": "exactly_one_terminal_compare_and_set",
        "orphan_readback": "zero_sdk_readback_failed_unknown_readback_owner_lost",
        "handle_recovery": "kernel_closed_on_process_death_no_numeric_handle_inheritance",
        "cleanup_recovery": "cleanup_pending_replayed_after_successor_crash",
        "tombstone": "durable_before_notification",
        "notification_intent": "durable_until_surviving_broker_ack",
        "waiter_broker": "authenticated_local_surviving_process",
        "notification_delivery": "at_least_once_after_baseexception",
        "public_cleanup_projection": "released_after_error_verified_closed",
    }
    adr = ADR.read_text(encoding="utf-8")
    for phrase in (
        "real subprocess boundary",
        "SQLite",
        "kernel-released exclusive file lease",
        "dispatch reservation is bound to the exact process-epoch lease",
        "`BaseException` abandons the durable readback claim",
        "request-local locks, weak references, guards, and waiters",
        "kernel_closed_on_process_death",
        "surviving authenticated local notification broker",
        "notification `BaseException`",
    ):
        assert phrase in adr
