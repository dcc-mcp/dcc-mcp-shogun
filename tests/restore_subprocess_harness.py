from __future__ import annotations

import argparse
import json
import os
import sqlite3
import uuid
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path

JOB_ID = "restore-job-cross-process-0001"
BROKER_CONNECTION_BACKLOG = 8


class InjectedNotificationBaseException(BaseException):
    pass


class ProcessEpochLease:
    def __init__(self, state_dir: Path, epoch: str):
        state_dir.mkdir(parents=True, exist_ok=True)
        if len(epoch) != 32 or any(character not in "0123456789abcdef" for character in epoch):
            raise ValueError("process epoch identity rejected")
        lease_path = state_dir / "registry-process.lock"
        lease_path.touch(exist_ok=True)
        self._handle = lease_path.open("r+b")
        self._handle.seek(0, os.SEEK_END)
        if self._handle.tell() == 0:
            self._handle.write(b"0")
            self._handle.flush()
        self._handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        self._handle.seek(0)
        self.previous_epoch = self._handle.read().decode("ascii")
        self.epoch = epoch
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(epoch.encode("ascii"))
        self._handle.flush()
        os.fsync(self._handle.fileno())


def _connect(state_dir: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(state_dir / "restore-contract.sqlite3", timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            claim_epoch TEXT NOT NULL,
            owner_pid INTEGER NOT NULL,
            handle_disposition TEXT NOT NULL,
            record_revision INTEGER NOT NULL,
            sdk_entry_count INTEGER NOT NULL DEFAULT 0,
            dispatch_count INTEGER NOT NULL,
            sdk_readback_count INTEGER NOT NULL,
            outcome TEXT,
            terminal_source TEXT,
            cleanup_disposition TEXT,
            notification_pending INTEGER NOT NULL DEFAULT 0,
            terminalize_count INTEGER NOT NULL DEFAULT 0,
            terminalizer_epoch TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tombstones (
            job_id TEXT PRIMARY KEY,
            terminal_source TEXT NOT NULL,
            outcome TEXT NOT NULL,
            terminalizer_epoch TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS notification_intents (
            job_id TEXT PRIMARY KEY,
            pending INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            acknowledged INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    connection.commit()
    return connection


def _write_json(path: Path, value: dict[str, object]) -> None:
    pending = path.with_suffix(path.suffix + ".pending")
    pending.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    pending.replace(path)


def _read_endpoint(path: Path) -> tuple[tuple[str, int], bytes]:
    endpoint = json.loads(path.read_text(encoding="utf-8"))
    return (endpoint["host"], endpoint["port"]), bytes.fromhex(endpoint["authkey"])


def _open_broker_listener(authkey: bytes) -> Listener:
    return Listener(
        ("127.0.0.1", 0),
        backlog=BROKER_CONNECTION_BACKLOG,
        authkey=authkey,
    )


def run_broker(endpoint_path_value: str) -> None:
    endpoint_path = Path(endpoint_path_value)
    authkey = os.urandom(32)
    listener = _open_broker_listener(authkey)
    host, port = listener.address
    _write_json(
        endpoint_path,
        {"host": host, "port": port, "authkey": authkey.hex()},
    )
    print("READY", flush=True)
    waiters: dict[str, list[Connection]] = {}
    running = True
    while running:
        connection = listener.accept()
        message = connection.recv()
        action = message.get("action")
        if action == "wait":
            waiters.setdefault(message["job_id"], []).append(connection)
            connection.send({"registered": True})
        elif action == "notify":
            job_id = message["job_id"]
            wakeup = {
                "job_id": job_id,
                "terminal_source": message["terminal_source"],
            }
            delivered = 0
            for waiter in waiters.pop(job_id, []):
                waiter.send(wakeup)
                waiter.close()
                delivered += 1
            connection.send({"acknowledged": True, "delivered": delivered})
            connection.close()
        elif action == "stop":
            connection.send({"stopped": True})
            connection.close()
            running = False
        else:
            connection.close()
            raise RuntimeError("unsupported broker action")
    listener.close()


def wait_for_notification(endpoint_path_value: str, job_id: str) -> None:
    address, authkey = _read_endpoint(Path(endpoint_path_value))
    connection = Client(address, authkey=authkey)
    connection.send({"action": "wait", "job_id": job_id})
    registration = connection.recv()
    if registration != {"registered": True}:
        raise RuntimeError("waiter registration was not acknowledged")
    print("READY", flush=True)
    wakeup = connection.recv()
    connection.close()
    print(json.dumps(wakeup, sort_keys=True), flush=True)


def notify_broker(endpoint_path: Path) -> int:
    address, authkey = _read_endpoint(endpoint_path)
    connection = Client(address, authkey=authkey)
    connection.send(
        {
            "action": "notify",
            "job_id": JOB_ID,
            "terminal_source": "readback_owner_lost",
        }
    )
    acknowledgement = connection.recv()
    connection.close()
    if acknowledgement.get("acknowledged") is not True:
        raise RuntimeError("notification was not acknowledged")
    return int(acknowledgement["delivered"])


def stop_broker(endpoint_path_value: str) -> None:
    address, authkey = _read_endpoint(Path(endpoint_path_value))
    connection = Client(address, authkey=authkey)
    connection.send({"action": "stop"})
    acknowledgement = connection.recv()
    connection.close()
    if acknowledgement != {"stopped": True}:
        raise RuntimeError("broker stop was not acknowledged")


def persist_owner_claim(state_dir_value: str, result_path_value: str) -> None:
    state_dir = Path(state_dir_value)
    claim_epoch = uuid.uuid4().hex
    _lease = ProcessEpochLease(state_dir, claim_epoch)
    connection = _connect(state_dir)
    with connection:
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, status, claim_epoch, owner_pid,
                handle_disposition, record_revision,
                dispatch_count, sdk_readback_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                JOB_ID,
                "readback_in_progress",
                claim_epoch,
                os.getpid(),
                "owned_by_process",
                1,
                1,
                0,
            ),
        )
    _write_json(
        Path(result_path_value),
        {
            "job_id": JOB_ID,
            "status": "readback_in_progress",
            "handle_disposition": "owned_by_process",
            "process_exited_without_request_cleanup": True,
        },
    )
    os._exit(0)


def persist_dispatch_reservation(state_dir_value: str, result_path_value: str) -> None:
    state_dir = Path(state_dir_value)
    claim_epoch = uuid.uuid4().hex
    _lease = ProcessEpochLease(state_dir, claim_epoch)
    connection = _connect(state_dir)
    with connection:
        connection.execute(
            """
            INSERT INTO jobs (
                job_id, status, claim_epoch, owner_pid,
                handle_disposition, record_revision,
                sdk_entry_count, dispatch_count, sdk_readback_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                JOB_ID,
                "dispatch_uncertain",
                claim_epoch,
                os.getpid(),
                "owned_by_process_epoch",
                1,
                1,
                0,
                0,
            ),
        )
    _write_json(
        Path(result_path_value),
        {
            "job_id": JOB_ID,
            "status": "dispatch_uncertain",
            "handle_disposition": "owned_by_process_epoch",
            "sdk_entry_count": 1,
            "dispatch_count": 0,
            "process_exited_without_request_cleanup": True,
        },
    )
    os._exit(0)


def query(state_dir_value: str) -> None:
    connection = _connect(Path(state_dir_value))
    row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (JOB_ID,)).fetchone()
    if row is None:
        raise RuntimeError("durable restore job was not found")
    tombstone = connection.execute(
        "SELECT * FROM tombstones WHERE job_id = ?", (JOB_ID,)
    ).fetchone()
    notification = connection.execute(
        "SELECT * FROM notification_intents WHERE job_id = ?", (JOB_ID,)
    ).fetchone()
    result = dict(row)
    result["tombstone"] = dict(tombstone) if tombstone is not None else None
    result["notification"] = dict(notification) if notification is not None else None
    print(json.dumps(result, sort_keys=True))


def recover(
    state_dir_value: str,
    result_path_value: str,
    *,
    crash_after_cleanup_pending: bool,
    crash_before_notify: bool,
    broker_endpoint: str | None,
) -> None:
    state_dir = Path(state_dir_value)
    successor_epoch = uuid.uuid4().hex
    _lease = ProcessEpochLease(state_dir, successor_epoch)
    connection = _connect(state_dir)
    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (JOB_ID,)).fetchone()
    if row is None:
        connection.rollback()
        raise RuntimeError("durable restore job was not found")
    entered_cleanup = False
    if row["status"] in {"dispatch_uncertain", "readback_in_progress"}:
        if row["claim_epoch"] != _lease.previous_epoch:
            connection.rollback()
            raise RuntimeError("process epoch lease binding rejected")
        orphaned_status = row["status"]
        updated = connection.execute(
            """
            UPDATE jobs
            SET status = ?, handle_disposition = ?, record_revision = record_revision + 1,
                cleanup_disposition = ?, claim_epoch = ?, owner_pid = ?
            WHERE job_id = ? AND status = ?
            """,
            (
                "cleanup_pending",
                "kernel_closed_on_process_death",
                "released_after_error_verified_closed",
                successor_epoch,
                os.getpid(),
                JOB_ID,
                orphaned_status,
            ),
        )
        if updated.rowcount != 1:
            connection.rollback()
            raise RuntimeError("orphan recovery CAS was lost")
        entered_cleanup = True
    elif row["status"] == "cleanup_pending":
        if row["claim_epoch"] != _lease.previous_epoch:
            connection.rollback()
            raise RuntimeError("process epoch lease binding rejected")
        updated = connection.execute(
            """
            UPDATE jobs SET claim_epoch = ?, owner_pid = ?
            WHERE job_id = ? AND status = ? AND claim_epoch = ?
            """,
            (
                successor_epoch,
                os.getpid(),
                JOB_ID,
                "cleanup_pending",
                _lease.previous_epoch,
            ),
        )
        if updated.rowcount != 1:
            connection.rollback()
            raise RuntimeError("cleanup process epoch CAS was lost")
    connection.commit()
    if crash_after_cleanup_pending and entered_cleanup:
        os._exit(23)

    connection.execute("BEGIN IMMEDIATE")
    row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (JOB_ID,)).fetchone()
    if row is None:
        connection.rollback()
        raise RuntimeError("durable restore job was not found")
    terminalized = row["status"] == "cleanup_pending"
    if terminalized:
        updated = connection.execute(
            """
            UPDATE jobs
            SET status = ?, record_revision = record_revision + 1,
                outcome = ?, terminal_source = ?, notification_pending = 1,
                terminalize_count = terminalize_count + 1, terminalizer_epoch = ?
            WHERE job_id = ? AND status = ?
            """,
            (
                "terminal",
                "failed_unknown",
                "readback_owner_lost",
                successor_epoch,
                JOB_ID,
                "cleanup_pending",
            ),
        )
        if updated.rowcount != 1:
            connection.rollback()
            raise RuntimeError("orphan terminal CAS was lost")
        connection.execute(
            """
            INSERT INTO tombstones (job_id, terminal_source, outcome, terminalizer_epoch)
            VALUES (?, ?, ?, ?)
            """,
            (JOB_ID, "readback_owner_lost", "failed_unknown", successor_epoch),
        )
        connection.execute(
            """
            INSERT INTO notification_intents (job_id, pending) VALUES (?, 1)
            """,
            (JOB_ID,),
        )
    connection.commit()
    if crash_before_notify:
        raise InjectedNotificationBaseException("simulated failure before notification")

    delivered_notification = False
    waiters_woken = 0
    notification = connection.execute(
        "SELECT * FROM notification_intents WHERE job_id = ?", (JOB_ID,)
    ).fetchone()
    if notification is not None and notification["pending"] == 1 and broker_endpoint is not None:
        waiters_woken = notify_broker(Path(broker_endpoint))
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            UPDATE notification_intents
            SET pending = 0, attempts = attempts + 1, acknowledged = 1
            WHERE job_id = ? AND pending = 1
            """,
            (JOB_ID,),
        )
        connection.execute(
            "UPDATE jobs SET notification_pending = 0 WHERE job_id = ?",
            (JOB_ID,),
        )
        connection.commit()
        delivered_notification = True
    durable = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (JOB_ID,)).fetchone()
    if durable is None:
        raise RuntimeError("durable restore job was not found")
    _write_json(
        Path(result_path_value),
        {
            "terminalized_by_this_process": terminalized,
            "status": durable["status"],
            "outcome": durable["outcome"],
            "terminal_source": durable["terminal_source"],
            "notification_delivered_by_this_process": delivered_notification,
            "waiters_woken": waiters_woken,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    owner = subparsers.add_parser("owner-claim")
    owner.add_argument("state_dir")
    owner.add_argument("result_path")
    dispatch_owner = subparsers.add_parser("dispatch-owner")
    dispatch_owner.add_argument("state_dir")
    dispatch_owner.add_argument("result_path")
    query_parser = subparsers.add_parser("query")
    query_parser.add_argument("state_dir")
    recover_parser = subparsers.add_parser("recover")
    recover_parser.add_argument("state_dir")
    recover_parser.add_argument("result_path")
    recover_parser.add_argument("--crash-after-cleanup-pending", action="store_true")
    recover_parser.add_argument("--crash-before-notify", action="store_true")
    recover_parser.add_argument("--broker-endpoint")
    broker_parser = subparsers.add_parser("broker")
    broker_parser.add_argument("endpoint_path")
    waiter_parser = subparsers.add_parser("wait")
    waiter_parser.add_argument("endpoint_path")
    waiter_parser.add_argument("job_id")
    broker_stop_parser = subparsers.add_parser("broker-stop")
    broker_stop_parser.add_argument("endpoint_path")
    args = parser.parse_args()

    if args.command == "owner-claim":
        persist_owner_claim(args.state_dir, args.result_path)
    elif args.command == "dispatch-owner":
        persist_dispatch_reservation(args.state_dir, args.result_path)
    elif args.command == "query":
        query(args.state_dir)
    elif args.command == "recover":
        recover(
            args.state_dir,
            args.result_path,
            crash_after_cleanup_pending=args.crash_after_cleanup_pending,
            crash_before_notify=args.crash_before_notify,
            broker_endpoint=args.broker_endpoint,
        )
    elif args.command == "broker":
        run_broker(args.endpoint_path)
    elif args.command == "wait":
        wait_for_notification(args.endpoint_path, args.job_id)
    elif args.command == "broker-stop":
        stop_broker(args.endpoint_path)


if __name__ == "__main__":
    main()
