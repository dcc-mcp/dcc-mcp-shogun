from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

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


def _persist_owner_claim(tmp_path: Path) -> None:
    owner = _run_harness("owner-claim", tmp_path, tmp_path / "owner-result.json")
    assert owner.returncode == 0, owner.stderr


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
    assert durable["dispatch_count"] == 1
    assert durable["sdk_readback_count"] == 0
    assert durable["handle_disposition"] == "kernel_closed_on_process_death"
    assert durable["cleanup_disposition"] == "released_after_error_verified_closed"


def test_cleanup_and_tombstone_reconcile_after_successor_crash(tmp_path):
    _persist_owner_claim(tmp_path)
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


def test_notification_baseexception_replays_to_multiple_process_waiters(tmp_path):
    _persist_owner_claim(tmp_path)
    endpoint_path = tmp_path / "notification-broker.json"
    broker = _start_harness("broker", endpoint_path)
    waiters: list[subprocess.Popen[str]] = []
    try:
        assert broker.stdout is not None
        broker_ready = broker.stdout.readline().strip()
        assert broker_ready == "READY", broker.stderr.read() if broker.stderr else ""
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
            assert waiter.stdout.readline().strip() == "READY"

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
            wakeups.append(json.loads(waiter.stdout.readline()))
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
        "request-local locks, weak references, guards, and waiters",
        "kernel_closed_on_process_death",
        "surviving authenticated local notification broker",
        "notification `BaseException`",
    ):
        assert phrase in adr
