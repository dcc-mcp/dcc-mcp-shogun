from __future__ import annotations

import hashlib
import hmac
import json
import ntpath
import secrets
import unicodedata
import weakref
from asyncio import CancelledError
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Condition, Event, Lock, RLock, Thread

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "docs" / "contracts" / "restore-scene.yaml"
ADR_PATH = ROOT / "docs" / "adr" / "0001-bounded-recovery-scene-restore.md"
NOW_EPOCH_SECONDS = 1_800_000_000


def _contract():
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def _validator(schema_name: str):
    schema = _contract()[schema_name]
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _request(**overrides):
    request = {
        "request_id": "restore-0001",
        "trusted_root": "C:/operator-approved/recovery",
        "file_path": "C:/operator-approved/recovery/marked_take.vdf",
        "recovery_receipt": {
            "receipt_version": 1,
            "file_name": "marked_take.vdf",
            "file_size_bytes": 4096,
            "sha256": "a" * 64,
            "active_scene_changed": False,
        },
        "operator_confirmation": {
            "confirmation_id": "confirm-0001",
        },
    }
    request.update(overrides)
    return request


def _scene_receipt(file_name: str, canonical_path_digest: str, file_digest: str):
    identity_fields = {
        "canonical_path_sha256": canonical_path_digest,
        "frame_count": 240,
        "scene_name": file_name,
    }
    return {
        "active_scene_observed_via": "official_sdk",
        "file_evidence_observed_via": "filesystem",
        "file_name": file_name,
        "file_size_bytes": 4096,
        "sha256": file_digest,
        "scene_identity_fields": identity_fields,
        "scene_identity_sha256": _scene_identity_binding(identity_fields)[1],
    }


def _job_descriptor(
    *,
    status="awaiting_late_readback",
    snapshot_source="request_timeout",
    terminal_source=None,
    cancellation_disposition="not_requested",
    handle_retention_owner="trusted_adapter_local_restore_job_registry",
    dispatch_count=1,
    poll_allowed=True,
    late_completion_disposition="poll_exact_job_without_redispatch",
    cleanup_disposition="not_started",
):
    cancellation_requested = cancellation_disposition != "not_requested"
    cancellation_effective = cancellation_disposition == "honored_before_dispatch"
    terminal = status in {"terminal", "terminal_not_dispatched"}
    dispatch_attempt_reserved = status != "terminal_not_dispatched"
    return {
        "job_id": "rj1-" + "9" * 64,
        "job_generation": "0000000000000001",
        "request_id": "restore-0001",
        "operation": "restore_scene",
        "operation_binding_sha256": "e" * 64,
        "owner": "trusted_adapter_local_restore_job_registry",
        "status_tool": "jobs_get_status",
        "status": status,
        "snapshot_source": snapshot_source,
        "terminal_source": terminal_source,
        "cancellation_disposition": cancellation_disposition,
        "handle_retention_owner": handle_retention_owner,
        "dispatch_count": dispatch_count,
        "dispatch_attempt_reserved": dispatch_attempt_reserved,
        "poll_allowed": poll_allowed,
        "duplicate_execution_allowed": False,
        "late_completion_disposition": late_completion_disposition,
        "cleanup_disposition": cleanup_disposition,
        "record_revision": 5 if terminal else 3,
        "event_sequence": 4 if terminal else 2,
        "identity_tombstoned": True,
        "cancellation_requested": cancellation_requested,
        "cancellation_effective": cancellation_effective,
        "terminal_event_id": "rce1-" + "8" * 64 if terminal else None,
        "terminal_event_digest_sha256": "7" * 64 if terminal else None,
    }


def _job_for_state(state):
    if state in {"preflight_rejected", "confirmation_consume_rejected", "target_guard_rejected"}:
        source = {
            "preflight_rejected": "preflight",
            "confirmation_consume_rejected": "confirmation_cas",
            "target_guard_rejected": "target_guard",
        }[state]
        return _job_descriptor(
            status="terminal_not_dispatched",
            snapshot_source=source,
            terminal_source=source,
            handle_retention_owner="released_before_dispatch",
            dispatch_count=0,
            poll_allowed=False,
            late_completion_disposition="not_applicable",
            cleanup_disposition="released",
        )
    if state in {"succeeded", "failed_unchanged"}:
        return _job_descriptor(
            status="terminal",
            snapshot_source="official_sdk_readback",
            terminal_source="official_sdk_readback",
            handle_retention_owner="released_after_terminal_readback",
            poll_allowed=False,
            late_completion_disposition="not_applicable",
            cleanup_disposition="released",
        )
    if state == "failed_unknown":
        return _job_descriptor(
            status="terminal",
            snapshot_source="official_sdk_failure",
            terminal_source="official_sdk_failure",
            handle_retention_owner="released_after_terminal_unknown",
            poll_allowed=False,
            late_completion_disposition="not_applicable",
            cleanup_disposition="released",
        )
    if state == "indeterminate":
        return _job_descriptor(snapshot_source="transport_loss")
    return _job_descriptor()


def _result(state: str):
    before = _scene_receipt("working_scene.vdf", "b" * 64, "c" * 64)
    after = _scene_receipt("marked_take.vdf", "d" * 64, "a" * 64)
    common = {
        "receipt_version": "1.0",
        "request_id": "restore-0001",
        "state": state,
        "replay_allowed": False,
        "dispatch_performed": True,
        "confirmation_consumed": True,
        "approved_recovery_receipt": _request()["recovery_receipt"],
        "job": _job_for_state(state),
    }

    if state == "succeeded":
        target_identity = {
            "canonical_path_sha256": "d" * 64,
            "volume_serial": "00000000A1B2C3D4",
            "file_id": "00112233445566778899aabbccddeeff",
        }
        after["target_identity"] = dict(target_identity)
        return {
            "success": True,
            "message": "Recovery scene restore verified.",
            "prompt": None,
            "error": None,
            "context": {
                **common,
                "effect": "verified",
                "readback_performed": True,
                "approved_target_identity": target_identity,
                "postcondition_evidence": {
                    "active_scene_readback_performed": True,
                    "before_after_distinct": True,
                    "after_matches_approved_recovery_receipt": True,
                    "after_matches_guarded_confirmation_identity": True,
                },
                "before_receipt": before,
                "after_receipt": after,
            },
        }
    if state == "preflight_rejected":
        return {
            "success": False,
            "message": "Recovery scene restore rejected before host connection.",
            "prompt": None,
            "error": "RestorePreflightRejected",
            "context": {
                "receipt_version": "1.0",
                "request_id": "restore-0001",
                "state": state,
                "effect": "unchanged",
                "replay_allowed": False,
                "host_connection_performed": False,
                "dispatch_performed": False,
                "confirmation_consumed": False,
                "failed_precondition": "canonical_target_is_contained_by_canonical_trusted_root",
                "before_receipt": None,
                "after_receipt": None,
                "job": _job_for_state(state),
            },
        }
    if state == "failed_unchanged":
        return {
            "success": False,
            "message": "Recovery scene restore failed without changing the active scene.",
            "prompt": None,
            "error": "RestoreFailedUnchanged",
            "context": {
                **common,
                "effect": "unchanged",
                "readback_performed": True,
                "postcondition_evidence": {
                    "active_scene_readback_performed": True,
                    "before_after_equal": True,
                },
                "before_receipt": before,
                "after_receipt": dict(before),
            },
        }
    if state == "confirmation_consume_rejected":
        return {
            "success": False,
            "message": "Confirmation was consumed by a concurrent request before dispatch.",
            "prompt": None,
            "error": "RestoreConfirmationConsumeRejected",
            "context": {
                "receipt_version": "1.0",
                "request_id": "restore-0001",
                "state": state,
                "effect": "unknown",
                "replay_allowed": False,
                "host_connection_performed": True,
                "before_receipt_captured": True,
                "dispatch_performed": False,
                "confirmation_consumed": False,
                "consume_outcome": "lost_atomic_compare_and_set",
                "before_receipt": before,
                "after_receipt": None,
                "job": _job_for_state(state),
            },
        }
    if state == "target_guard_rejected":
        return {
            "success": False,
            "message": "Guarded target identity could not be reconfirmed before dispatch.",
            "prompt": None,
            "error": "RestoreTargetGuardRejected",
            "context": {
                "receipt_version": "1.0",
                "request_id": "restore-0001",
                "state": state,
                "effect": "unknown",
                "replay_allowed": False,
                "host_connection_performed": True,
                "before_receipt_captured": True,
                "dispatch_performed": False,
                "confirmation_consumed": False,
                "guard_outcome": "predispatch_identity_or_receipt_mismatch",
                "before_receipt": before,
                "after_receipt": None,
                "job": _job_for_state(state),
            },
        }
    return {
        "success": False,
        "message": "Recovery scene restore did not reach verified success.",
        "prompt": None,
        "error": {
            "failed_unknown": "RestoreFailedUnknown",
            "timed_out": "RestoreTimedOut",
            "indeterminate": "RestoreIndeterminate",
        }[state],
        "context": {
            **common,
            "effect": "unknown",
            "readback_performed": False,
            "before_receipt": before,
            "after_receipt": None,
        },
    }


def _projection_hmac(secret, domain, value):
    canonical = json.dumps(
        _normalize_receipt_strings(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hmac.new(secret, domain.encode() + b"\0" + canonical, hashlib.sha256).hexdigest()


def _public_job_for_state(state, private_job, request_correlation, secret):
    public_job = {
        key: value
        for key, value in private_job.items()
        if key
        not in {
            "job_id",
            "job_generation",
            "request_id",
            "operation_binding_sha256",
            "terminal_event_id",
            "terminal_event_digest_sha256",
        }
    }
    return {
        "job_id": (
            "rj1-"
            + _projection_hmac(
                secret,
                "public-job-id",
                [private_job["job_id"], private_job["operation_binding_sha256"]],
            )
        ),
        "request_correlation_hmac_sha256": request_correlation,
        "job_generation_hmac_sha256": _projection_hmac(
            secret,
            "public-job-generation",
            private_job["job_generation"],
        ),
        "operation_binding_hmac_sha256": _projection_hmac(
            secret,
            "public-operation-binding",
            private_job["operation_binding_sha256"],
        ),
        "terminal_event_hmac_sha256": (
            _projection_hmac(
                secret,
                "public-terminal-event",
                [
                    private_job["terminal_event_id"],
                    private_job["terminal_event_digest_sha256"],
                ],
            )
            if private_job["terminal_event_id"] is not None
            else None
        ),
        **public_job,
    }


def _public_result(
    state,
    secret=b"adapter-private-test-key",
    *,
    terminal_source=None,
):
    private_result = _result(state)
    private_context = private_result["context"]
    if terminal_source is not None:
        if state != "failed_unknown" or terminal_source != "readback_owner_lost":
            raise ValueError("public terminal source override rejected")
        private_context["job"]["snapshot_source"] = terminal_source
        private_context["job"]["terminal_source"] = terminal_source
    request_correlation = _projection_hmac(
        secret,
        "public-request-correlation",
        private_context["request_id"],
    )
    dispatched = state in {
        "succeeded",
        "failed_unchanged",
        "failed_unknown",
        "timed_out",
        "indeterminate",
    }
    before_captured = state != "preflight_rejected"
    readback = state in {"succeeded", "failed_unchanged"}
    before_projection = (
        {
            "projection_version": "1.0",
            "observation_hmac_sha256": _projection_hmac(
                secret,
                "public-scene-observation",
                private_context["before_receipt"],
            ),
        }
        if before_captured
        else None
    )
    after_projection = None
    if state == "succeeded":
        after_projection = {
            "projection_version": "1.0",
            "observation_hmac_sha256": _projection_hmac(
                secret,
                "public-scene-observation",
                private_context["after_receipt"],
            ),
        }
    elif state == "failed_unchanged":
        after_projection = dict(before_projection)
    effect = {
        "preflight_rejected": "unchanged",
        "succeeded": "verified",
        "failed_unchanged": "unchanged",
    }.get(state, "unknown")
    failure_stage = {
        "preflight_rejected": "preflight",
        "confirmation_consume_rejected": "confirmation_cas",
        "target_guard_rejected": "target_guard",
        "timed_out": "request_timeout",
        "indeterminate": "transport_loss",
    }.get(state)
    if state == "failed_unknown":
        failure_stage = {
            "official_sdk_failure": "official_sdk_failure",
            "readback_owner_lost": "readback_owner_loss",
        }[private_context["job"]["terminal_source"]]
    postcondition_status = {
        "succeeded": "verified",
        "failed_unchanged": "unchanged",
        "preflight_rejected": "not_evaluated",
    }.get(state, "unknown")
    message = {
        "preflight_rejected": "Recovery scene restore rejected before host connection.",
        "confirmation_consume_rejected": (
            "Confirmation was consumed by a concurrent request before dispatch."
        ),
        "target_guard_rejected": (
            "Guarded target identity could not be reconfirmed before dispatch."
        ),
        "succeeded": "Recovery scene restore verified.",
        "failed_unchanged": ("Recovery scene restore failed without changing the active scene."),
    }.get(state, "Recovery scene restore did not reach verified success.")
    error = {
        "preflight_rejected": "RestorePreflightRejected",
        "confirmation_consume_rejected": "RestoreConfirmationConsumeRejected",
        "target_guard_rejected": "RestoreTargetGuardRejected",
        "succeeded": None,
        "failed_unchanged": "RestoreFailedUnchanged",
        "failed_unknown": "RestoreFailedUnknown",
        "timed_out": "RestoreTimedOut",
        "indeterminate": "RestoreIndeterminate",
    }[state]
    return {
        "success": state == "succeeded",
        "message": message,
        "prompt": None,
        "error": error,
        "context": {
            "receipt_version": "1.0",
            "request_correlation_hmac_sha256": request_correlation,
            "state": state,
            "effect": effect,
            "replay_allowed": False,
            "host_connection_performed": state != "preflight_rejected",
            "before_receipt_captured": before_captured,
            "dispatch_performed": dispatched,
            "confirmation_consumed": dispatched,
            "readback_performed": readback,
            "approved_recovery_receipt_hmac_sha256": (
                _projection_hmac(
                    secret,
                    "public-approved-recovery",
                    private_context["approved_recovery_receipt"],
                )
                if dispatched
                else None
            ),
            "approved_target_identity_hmac_sha256": (
                _projection_hmac(
                    secret,
                    "public-approved-target",
                    private_context["approved_target_identity"],
                )
                if state == "succeeded"
                else None
            ),
            "before_receipt": before_projection,
            "after_receipt": after_projection,
            "postcondition_status": postcondition_status,
            "failure_stage": failure_stage,
            "job": _public_job_for_state(
                state,
                private_context["job"],
                request_correlation,
                secret,
            ),
        },
    }


def _pointer(document, pointer: str):
    value = document
    for token in pointer.lstrip("/").split("/"):
        value = value[token.replace("~1", "/").replace("~0", "~")]
    return value


def _validate_result(result):
    _validator("private_audit_result_schema").validate(result)
    errors = []
    contract = _contract()
    for rules in (
        contract["semantic_invariants"],
        contract["semantic_postconditions"][result["context"]["state"]],
    ):
        for left, right in rules.get("equal", []):
            if _pointer(result, left) != _pointer(result, right):
                errors.append(f"{left} must equal {right}")
        for left, right in rules.get("not_equal", []):
            if _pointer(result, left) == _pointer(result, right):
                errors.append(f"{left} must not equal {right}")
    for receipt_name in _contract()["scene_receipt_validation"]["apply_to"]:
        receipt = result["context"].get(receipt_name)
        if receipt is None:
            continue
        expected = _scene_identity_binding(receipt["scene_identity_fields"])[1]
        if receipt["scene_identity_sha256"] != expected:
            errors.append(f"/{receipt_name}/scene_identity_sha256 must match canonical fields")
        if receipt["scene_identity_fields"]["scene_name"] != receipt["file_name"]:
            errors.append(f"/{receipt_name}/scene_name must equal file_name")
    if errors:
        raise ValidationError("; ".join(errors))


@pytest.mark.parametrize(
    "state",
    (
        "preflight_rejected",
        "confirmation_consume_rejected",
        "target_guard_rejected",
        "succeeded",
        "failed_unchanged",
        "failed_unknown",
        "timed_out",
        "indeterminate",
    ),
)
@pytest.mark.parametrize("field", ("message", "prompt"))
def test_output_schema_rejects_unbounded_public_text_in_every_terminal_state(state, field):
    result = _public_result(state)
    result[field] = (
        r"C:\operator-approved\recovery\marked_take.vdf "
        "SDK exception: confirmation_secret=confirm-0001"
    )

    with pytest.raises(ValidationError):
        _validator("output_schema").validate(result)


@pytest.mark.parametrize(
    "state",
    (
        "preflight_rejected",
        "confirmation_consume_rejected",
        "target_guard_rejected",
        "succeeded",
        "failed_unchanged",
        "failed_unknown",
        "timed_out",
        "indeterminate",
    ),
)
def test_public_output_rejects_raw_caller_operator_take_and_scene_audit_data(state):
    sensitive = _result(state)
    sensitive["context"]["request_id"] = "operator-token-007"
    sensitive["context"]["job"]["request_id"] = "operator-token-007"
    for receipt_name in ("before_receipt", "after_receipt"):
        receipt = sensitive["context"].get(receipt_name)
        if receipt is not None:
            receipt["file_name"] = "operator_alice_secret_take.vdf"
            receipt["scene_identity_fields"]["scene_name"] = "operator_alice_secret_take.vdf"

    with pytest.raises(ValidationError):
        _validator("output_schema").validate(sensitive)


@pytest.mark.parametrize(
    "state",
    (
        "preflight_rejected",
        "confirmation_consume_rejected",
        "target_guard_rejected",
        "succeeded",
        "failed_unchanged",
        "failed_unknown",
        "timed_out",
        "indeterminate",
    ),
)
def test_public_output_is_a_complete_keyed_projection_for_every_state(state):
    result = _public_result(state)

    _validator("output_schema").validate(result)
    serialized = json.dumps(result, sort_keys=True)
    for forbidden_key in (
        '"request_id"',
        '"file_name"',
        '"scene_name"',
        '"canonical_path_sha256"',
        '"confirmation_id"',
        '"job_generation"',
        '"terminal_event_id"',
        '"terminal_event_digest_sha256"',
        '"approved_recovery_receipt"',
        '"approved_target_identity"',
        '"scene_identity_fields"',
    ):
        assert forbidden_key not in serialized
    for forbidden_value in (
        "restore-0001",
        "confirm-0001",
        "marked_take",
        "working_scene",
        "operator",
    ):
        assert forbidden_value not in serialized


def test_public_owner_loss_stage_is_bound_to_nested_terminal_source():
    owner_loss = _public_result(
        "failed_unknown",
        terminal_source="readback_owner_lost",
    )

    _validator("output_schema").validate(owner_loss)
    sdk_entry_owner_loss = json.loads(json.dumps(owner_loss))
    sdk_entry_owner_loss["context"]["job"]["dispatch_count"] = 0
    _validator("output_schema").validate(sdk_entry_owner_loss)

    contradictory = json.loads(json.dumps(owner_loss))
    contradictory["context"]["failure_stage"] = "official_sdk_failure"
    with pytest.raises(ValidationError):
        _validator("output_schema").validate(contradictory)


def test_private_owner_loss_accepts_unconfirmed_sdk_entry_without_false_dispatch_count():
    owner_loss = _result("failed_unknown")
    owner_loss["context"]["job"]["snapshot_source"] = "readback_owner_lost"
    owner_loss["context"]["job"]["terminal_source"] = "readback_owner_lost"
    owner_loss["context"]["job"]["dispatch_count"] = 0

    _validate_result(owner_loss)


def test_public_official_sdk_failure_rejects_owner_loss_stage():
    sdk_failure = _public_result("failed_unknown")
    _validator("output_schema").validate(sdk_failure)

    contradictory = json.loads(json.dumps(sdk_failure))
    contradictory["context"]["failure_stage"] = "readback_owner_loss"
    with pytest.raises(ValidationError):
        _validator("output_schema").validate(contradictory)


def test_public_projection_is_keyed_and_domain_separated_from_private_audit_data():
    first = _public_result("succeeded", secret=b"adapter-secret-one")
    second = _public_result("succeeded", secret=b"adapter-secret-two")

    _validator("output_schema").validate(first)
    _validator("output_schema").validate(second)
    assert (
        first["context"]["request_correlation_hmac_sha256"]
        != second["context"]["request_correlation_hmac_sha256"]
    )
    assert first["context"]["job"]["job_id"] != second["context"]["job"]["job_id"]
    assert (
        first["context"]["job"]["job_generation_hmac_sha256"]
        != second["context"]["job"]["job_generation_hmac_sha256"]
    )
    assert (
        first["context"]["job"]["terminal_event_hmac_sha256"]
        != second["context"]["job"]["terminal_event_hmac_sha256"]
    )
    assert first["context"]["before_receipt"] != second["context"]["before_receipt"]
    assert (
        first["context"]["approved_recovery_receipt_hmac_sha256"]
        != second["context"]["approved_recovery_receipt_hmac_sha256"]
    )


def test_timeout_requires_exact_pollable_job_correlation_descriptor():
    validator = _validator("private_audit_result_schema")
    correlated = _result("timed_out")

    validator.validate(correlated)

    uncorrelated = _result("timed_out")
    uncorrelated["context"].pop("job")
    with pytest.raises(ValidationError):
        validator.validate(uncorrelated)


def test_jobs_get_status_accepts_only_an_exact_job_id_and_never_execution_input():
    status_schema = _contract()["async_job_contract"]["jobs_get_status_input_schema"]
    Draft202012Validator.check_schema(status_schema)
    validator = Draft202012Validator(status_schema)

    valid_job_id = "rj1-" + "9" * 64
    validator.validate({"job_id": valid_job_id})
    for invalid in (
        {},
        {"job_id": valid_job_id, "request_id": "restore-0001"},
        {"job_id": valid_job_id, "retry": True},
        {"job_id": valid_job_id, "file_path": r"C:\secret\take.vdf"},
        {"job_id": "bad job id"},
        {"job_id": "restore-job-0001"},
    ):
        with pytest.raises(ValidationError):
            validator.validate(invalid)


def test_cancellation_before_dispatch_is_terminal_and_consumes_no_authority():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary()
    jobs = FakeAsyncRestoreJobRegistry()
    workflow = FakeAsyncRestoreWorkflow(store, sdk, guard, jobs)

    result = workflow.start(request, "cancellation_before_dispatch")

    _validate_result(result)
    assert store.consume_count == sdk.dispatch_count == sdk.readback_count == 0
    assert sdk.before_capture_count == 0
    assert guard.open_count == guard.release_count == 1
    assert guard.conflicting_replace_allowed() is True
    job = result["context"]["job"]
    assert job["status"] == "terminal_not_dispatched"
    assert job["snapshot_source"] == job["terminal_source"] == ("cancellation_before_dispatch")
    assert job["cancellation_disposition"] == "honored_before_dispatch"
    assert job["cancellation_requested"] is job["cancellation_effective"] is True
    assert job["handle_retention_owner"] == "released_before_dispatch"
    assert job["dispatch_count"] == 0
    assert job["poll_allowed"] is False
    assert job["identity_tombstoned"] is True
    assert job["terminal_event_id"].startswith("rce1-")
    assert len(job["terminal_event_digest_sha256"]) == 64


def test_cancellation_before_dispatch_cleanup_failure_retains_owner_and_tombstones():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary(release_failure_phase="before_close")
    jobs = FakeAsyncRestoreJobRegistry()
    workflow = FakeAsyncRestoreWorkflow(store, sdk, guard, jobs)

    result = workflow.start(request, "cancellation_before_dispatch")

    _validate_result(result)
    job = result["context"]["job"]
    assert job["status"] == "terminal_not_dispatched"
    assert job["handle_retention_owner"] == "trusted_adapter_local_restore_job_registry"
    assert job["cleanup_disposition"] == "release_failed_owner_retained"
    assert jobs.tombstone(job["job_id"])["cleanup_disposition"] == ("release_failed_owner_retained")
    assert jobs.store.waiter_notification_count == 1
    assert guard.release_count == 0
    assert guard.conflicting_replace_allowed() is False
    assert guard.release_error_text not in json.dumps(result, sort_keys=True)


def test_cancellation_cleanup_crash_reconciles_terminal_state_after_restart():
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    durable_store = FakeDurableJobStore()
    durable_store.cleanup_store.crash_after_release_once = True
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary()
    jobs = FakeAsyncRestoreJobRegistry(durable_store)
    workflow = FakeAsyncRestoreWorkflow(confirmation_store, sdk, guard, jobs)

    with pytest.raises(RuntimeError, match="simulated crash after guard release"):
        workflow.start(request, "cancellation_before_dispatch")

    job_id = next(iter(durable_store.records))
    assert durable_store.records[job_id]["status"] == "cleanup_pending"
    assert guard.release_count == 1
    assert durable_store.waiter_notification_count == 0

    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(durable_store)
    terminal = restarted.descriptor(job_id)

    assert terminal["status"] == "terminal_not_dispatched"
    assert terminal["terminal_source"] == "cancellation_before_dispatch"
    assert terminal["cancellation_disposition"] == "honored_before_dispatch"
    assert terminal["cleanup_disposition"] == "released_after_error_verified_closed"
    assert restarted.tombstone(job_id)["cleanup_disposition"] == (
        "released_after_error_verified_closed"
    )
    assert durable_store.waiter_notification_count == 1
    assert confirmation_store.consume_count == sdk.dispatch_count == sdk.readback_count == 0


@pytest.mark.parametrize(
    ("outcome", "state", "cancellation_disposition"),
    (
        ("request_timeout", "timed_out", "not_requested"),
        ("transport_loss", "indeterminate", "not_requested"),
        (
            "cancellation_after_dispatch",
            "indeterminate",
            "requested_after_dispatch_operation_continues",
        ),
    ),
)
def test_dispatched_unknown_outcomes_remain_owned_and_poll_without_redispatch(
    outcome, state, cancellation_disposition
):
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary()
    jobs = FakeAsyncRestoreJobRegistry()
    workflow = FakeAsyncRestoreWorkflow(store, sdk, guard, jobs)

    result = workflow.start(request, outcome)
    job = result["context"]["job"]

    _validate_result(result)
    assert result["context"]["state"] == state
    assert job["snapshot_source"] == outcome
    assert job["terminal_source"] is None
    assert job["cancellation_disposition"] == cancellation_disposition
    assert job["handle_retention_owner"] == "trusted_adapter_local_restore_job_registry"
    assert job["dispatch_count"] == 1
    assert job["poll_allowed"] is True
    assert store.consume_count == sdk.dispatch_count == 1
    assert sdk.readback_count == guard.release_count == 0

    for _ in range(3):
        assert (
            workflow.poll(job["job_id"])["operation_binding_sha256"]
            == (job["operation_binding_sha256"])
        )
    assert jobs.poll_count == 3
    assert store.consume_count == sdk.dispatch_count == 1
    assert sdk.readback_count == guard.release_count == 0
    with pytest.raises(RuntimeError, match="duplicate restore dispatch forbidden"):
        jobs.mark_dispatched(job["job_id"])


def test_crash_after_sdk_entry_process_loss_terminalizes_without_guard_inheritance():
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    durable_store = FakeDurableJobStore()
    sdk = FakeOfficialSdkBoundary(crash_after_dispatch=True)
    jobs = FakeAsyncRestoreJobRegistry(durable_store)
    guard = FakeGuardedTargetBoundary()
    workflow = FakeAsyncRestoreWorkflow(
        confirmation_store,
        sdk,
        guard,
        jobs,
    )

    with pytest.raises(RuntimeError, match="simulated crash after SDK dispatch entry"):
        workflow.start(request, "request_timeout")

    job_id = next(iter(durable_store.records))
    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(durable_store)
    descriptor = restarted.descriptor(job_id)
    assert sdk.dispatch_count == 1
    assert descriptor["status"] == "terminal"
    assert descriptor["dispatch_attempt_reserved"] is True
    assert descriptor["dispatch_count"] == 0
    assert descriptor["poll_allowed"] is False
    assert descriptor["handle_retention_owner"] == "released_after_terminal_unknown"
    assert descriptor["terminal_source"] == "readback_owner_lost"
    assert descriptor["cleanup_disposition"] == "released_after_error_verified_closed"
    assert descriptor["duplicate_execution_allowed"] is False
    assert guard.release_count == 0
    with durable_store.condition:
        assert durable_store.records[job_id]["guard"] is None
        assert durable_store.records[job_id]["guard_token"] is None
    assert restarted.tombstone(job_id)["terminal_event_id"] == descriptor["terminal_event_id"]
    assert durable_store.waiter_notification_count == 1
    with pytest.raises(RuntimeError, match="duplicate restore dispatch forbidden"):
        restarted.reserve_dispatch(job_id)
    cancellation = restarted.request_cancellation(job_id)
    assert cancellation["effective"] is False
    assert cancellation["disposition"] == "ignored_after_terminal"
    assert restarted.descriptor(job_id) == descriptor


def test_dispatch_uncertain_can_only_complete_by_exact_readback_without_redispatch():
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary(crash_after_dispatch=True)
    jobs = FakeAsyncRestoreJobRegistry()
    workflow = FakeAsyncRestoreWorkflow(
        confirmation_store,
        sdk,
        FakeGuardedTargetBoundary(),
        jobs,
    )

    with pytest.raises(RuntimeError, match="simulated crash after SDK dispatch entry"):
        workflow.start(request, "request_timeout")
    job_id = next(iter(jobs.store.records))

    result = workflow.poll(job_id, late_success=True)

    _validate_result(result)
    assert result["context"]["state"] == "succeeded"
    assert result["context"]["job"]["dispatch_count"] == 1
    assert sdk.dispatch_count == sdk.readback_count == 1


def test_late_success_uses_exact_job_readback_terminal_source_and_releases_handles():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary()
    jobs = FakeAsyncRestoreJobRegistry()
    workflow = FakeAsyncRestoreWorkflow(store, sdk, guard, jobs)
    timed_out = workflow.start(request, "request_timeout")
    original_job = timed_out["context"]["job"]

    succeeded = workflow.poll(original_job["job_id"], late_success=True)
    terminal_job = succeeded["context"]["job"]

    _validate_result(succeeded)
    assert terminal_job["job_id"] == original_job["job_id"]
    assert terminal_job["operation_binding_sha256"] == original_job["operation_binding_sha256"]
    assert terminal_job["snapshot_source"] == "late_official_sdk_readback"
    assert terminal_job["terminal_source"] == "official_sdk_readback"
    assert terminal_job["handle_retention_owner"] == "released_after_terminal_readback"
    assert terminal_job["dispatch_count"] == 1
    assert terminal_job["poll_allowed"] is False
    assert terminal_job["late_completion_disposition"] == ("terminalized_by_official_sdk_readback")
    assert (
        jobs.tombstone(original_job["job_id"])["completion_receipt_sha256"]
        == (_completion_receipt_binding(sdk.after_receipt)[1])
    )
    assert (
        store.consume_count == sdk.dispatch_count == sdk.readback_count == guard.release_count == 1
    )

    same_terminal = workflow.poll(original_job["job_id"], late_success=True)
    assert same_terminal == terminal_job
    assert (
        store.consume_count == sdk.dispatch_count == sdk.readback_count == guard.release_count == 1
    )

    missing_terminal_source = json.loads(json.dumps(succeeded))
    missing_terminal_source["context"]["job"]["terminal_source"] = None
    with pytest.raises(ValidationError):
        _validate_result(missing_terminal_source)


def test_late_pre_close_failure_terminalizes_tombstones_notifies_and_retains_owner():
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary(release_failure_phase="before_close")
    jobs = FakeAsyncRestoreJobRegistry()
    workflow = FakeAsyncRestoreWorkflow(confirmation_store, sdk, guard, jobs)
    pending = workflow.start(request, "request_timeout")
    job_id = pending["context"]["job"]["job_id"]

    result = workflow.poll(job_id, late_success=True)

    _validate_result(result)
    terminal = result["context"]["job"]
    assert result["context"]["state"] == "succeeded"
    assert terminal["status"] == "terminal"
    assert terminal["handle_retention_owner"] == ("trusted_adapter_local_restore_job_registry")
    assert terminal["cleanup_disposition"] == "release_failed_owner_retained"
    tombstone = jobs.tombstone(job_id)
    assert tombstone["terminal_revision"] == terminal["record_revision"]
    assert tombstone["cleanup_disposition"] == "release_failed_owner_retained"
    assert tombstone["handle_retention_owner"] == ("trusted_adapter_local_restore_job_registry")
    assert (
        tombstone["cleanup_binding_sha256"]
        == (jobs.cleanup_record(job_id)["cleanup_binding_sha256"])
    )
    assert jobs.store.waiter_notification_count == 1
    assert jobs.cleanup_record(job_id)["disposition"] == "release_failed_owner_retained"
    assert guard.release_count == 0
    assert guard.conflicting_replace_allowed() is False
    serialized = json.dumps({"result": result, "cleanup": jobs.cleanup_record(job_id)})
    assert guard.release_error_text not in serialized
    assert r"C:\secret" not in serialized

    duplicate = workflow.poll(job_id, late_success=True)
    assert duplicate == terminal
    assert sdk.dispatch_count == sdk.readback_count == 1
    assert guard.release_count == 0

    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(jobs.store)
    assert restarted.descriptor(job_id) == terminal
    assert restarted.tombstone(job_id) == jobs.tombstone(job_id)
    assert restarted.cleanup_record(job_id) == jobs.cleanup_record(job_id)


def test_late_post_close_failure_terminalizes_with_verified_release_and_tombstone():
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary(release_failure_phase="after_close")
    jobs = FakeAsyncRestoreJobRegistry()
    workflow = FakeAsyncRestoreWorkflow(confirmation_store, sdk, guard, jobs)
    pending = workflow.start(request, "request_timeout")
    job_id = pending["context"]["job"]["job_id"]

    result = workflow.poll(job_id, late_success=True)

    _validate_result(result)
    terminal = result["context"]["job"]
    assert result["context"]["state"] == "succeeded"
    assert terminal["handle_retention_owner"] == "released_after_terminal_readback"
    assert terminal["cleanup_disposition"] == "released_after_error_verified_closed"
    tombstone = jobs.tombstone(job_id)
    assert tombstone["terminal_revision"] == terminal["record_revision"]
    assert tombstone["cleanup_disposition"] == "released_after_error_verified_closed"
    assert tombstone["handle_retention_owner"] == "released_after_terminal_readback"
    assert (
        tombstone["cleanup_binding_sha256"]
        == (jobs.cleanup_record(job_id)["cleanup_binding_sha256"])
    )
    assert jobs.store.waiter_notification_count == 1
    assert jobs.cleanup_record(job_id)["disposition"] == ("released_after_error_verified_closed")
    assert guard.release_count == 1
    assert guard.conflicting_replace_allowed() is True
    serialized = json.dumps({"result": result, "cleanup": jobs.cleanup_record(job_id)})
    assert guard.release_error_text not in serialized
    assert r"C:\secret" not in serialized


def test_late_indeterminate_close_is_quarantined_without_false_release_claim():
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary(release_failure_phase="indeterminate_after_close")
    jobs = FakeAsyncRestoreJobRegistry()
    workflow = FakeAsyncRestoreWorkflow(confirmation_store, sdk, guard, jobs)
    job_id = workflow.start(request, "request_timeout")["context"]["job"]["job_id"]

    result = workflow.poll(job_id, late_success=True)

    _validate_result(result)
    terminal = result["context"]["job"]
    assert terminal["status"] == "terminal"
    assert terminal["cleanup_disposition"] == "release_indeterminate_quarantined"
    assert terminal["handle_retention_owner"] == (
        "cleanup_ownership_indeterminate_registry_quarantine"
    )
    assert jobs.tombstone(job_id)["cleanup_disposition"] == ("release_indeterminate_quarantined")
    assert jobs.cleanup_record(job_id)["disposition"] == ("release_indeterminate_quarantined")
    assert guard.release_count == 1
    assert guard.conflicting_replace_allowed() is True
    assert guard.release_error_text not in json.dumps(result, sort_keys=True)


def test_cleanup_resolution_crash_after_release_reconciles_on_registry_restart():
    durable_store = FakeDurableJobStore()
    durable_store.cleanup_store.crash_after_release_once = True
    workflow, jobs, sdk, job_id = _pending_async_workflow(durable_store)
    guard = jobs._records[job_id]["guard"]

    with pytest.raises(RuntimeError, match="simulated crash after guard release"):
        workflow.poll(job_id, late_success=True)

    stranded = durable_store.records[job_id]
    assert stranded["status"] == "cleanup_pending"
    assert stranded["cleanup_pending"] == {
        "cleanup_version": "2.0",
        "cleanup_binding_sha256": stranded["cleanup_pending"]["cleanup_binding_sha256"],
        "phase": "late_readback_terminal",
        "guard_owner": stranded["retained_guard_owner"],
        "guard_generation": stranded["retained_guard_generation"],
        "release_observation": "not_recorded",
    }
    assert guard.release_count == 1
    assert durable_store.waiter_notification_count == 0
    assert sdk.dispatch_count == sdk.readback_count == 1

    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(durable_store)
    terminal = restarted.descriptor(job_id)

    assert terminal["status"] == "terminal"
    assert terminal["terminal_source"] == "official_sdk_readback"
    assert terminal["cleanup_disposition"] == "released_after_error_verified_closed"
    assert terminal["handle_retention_owner"] == "released_after_terminal_readback"
    assert restarted.tombstone(job_id)["cleanup_disposition"] == (
        "released_after_error_verified_closed"
    )
    assert restarted.cleanup_record(job_id)["disposition"] == (
        "released_after_error_verified_closed"
    )
    assert durable_store.waiter_notification_count == 1
    assert sdk.dispatch_count == sdk.readback_count == 1


def test_tombstone_write_crash_replays_terminalization_and_notification_after_restart():
    durable_store = FakeDurableJobStore()
    durable_store.fail_tombstone_write_once = True
    workflow, _, sdk, job_id = _pending_async_workflow(durable_store)

    with pytest.raises(RuntimeError, match="simulated crash during tombstone commit"):
        workflow.poll(job_id, late_success=True)

    stranded = durable_store.records[job_id]
    assert stranded["status"] == "terminal"
    assert job_id not in durable_store.tombstones
    assert durable_store.waiter_notification_count == 0
    assert sdk.dispatch_count == sdk.readback_count == 1

    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(durable_store)
    terminal = restarted.descriptor(job_id)

    assert terminal["status"] == "terminal"
    assert restarted.tombstone(job_id)["terminal_event_id"] == terminal["terminal_event_id"]
    assert durable_store.waiter_notification_count == 1
    assert sdk.dispatch_count == sdk.readback_count == 1


def test_waiter_notification_crash_replays_after_durable_tombstone_on_restart():
    durable_store = FakeDurableJobStore()
    durable_store.fail_waiter_notification_once = True
    workflow, _, sdk, job_id = _pending_async_workflow(durable_store)

    with pytest.raises(RuntimeError, match="simulated crash before waiter notification"):
        workflow.poll(job_id, late_success=True)

    stranded = durable_store.records[job_id]
    assert stranded["status"] == "terminal"
    assert durable_store.tombstones[job_id]["terminal_event_id"] == stranded["terminal_event_id"]
    assert durable_store.waiter_notification_count == 0
    assert sdk.dispatch_count == sdk.readback_count == 1

    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(durable_store)
    terminal = restarted.descriptor(job_id)

    assert restarted.tombstone(job_id)["terminal_event_id"] == terminal["terminal_event_id"]
    assert durable_store.waiter_notification_count == 1
    assert sdk.dispatch_count == sdk.readback_count == 1


def test_notification_intent_crash_replays_wakeup_before_cleanup_commit_clears():
    durable_store = FakeDurableJobStore()
    durable_store.fail_after_notification_intent_once = True
    workflow, _, sdk, job_id = _pending_async_workflow(durable_store)

    with pytest.raises(RuntimeError, match="simulated crash after durable notification intent"):
        workflow.poll(job_id, late_success=True)

    stranded = durable_store.records[job_id]
    assert stranded["status"] == "terminal"
    assert stranded["cleanup_commit_pending"] is True
    assert durable_store.tombstones[job_id]["terminal_event_id"] == stranded["terminal_event_id"]
    assert job_id in durable_store.notification_pending_jobs
    assert durable_store.waiter_notification_count == 0
    assert sdk.dispatch_count == sdk.readback_count == 1

    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(durable_store)
    terminal = restarted.descriptor(job_id)

    assert terminal["status"] == "terminal"
    assert durable_store.waiter_notification_count == 1
    assert job_id not in durable_store.notification_pending_jobs
    assert durable_store.records[job_id]["cleanup_commit_pending"] is False
    assert sdk.dispatch_count == sdk.readback_count == 1


def test_status_read_reconciles_cleanup_pending_before_publication():
    durable_store = FakeDurableJobStore()
    durable_store.cleanup_store.crash_after_release_once = True
    workflow, jobs, sdk, job_id = _pending_async_workflow(durable_store)

    with pytest.raises(RuntimeError, match="simulated crash after guard release"):
        workflow.poll(job_id, late_success=True)

    assert durable_store.records[job_id]["status"] == "cleanup_pending"
    terminal = jobs.descriptor(job_id)

    assert terminal["status"] == "terminal"
    assert terminal["cleanup_disposition"] == "released_after_error_verified_closed"
    assert jobs.tombstone(job_id)["cleanup_disposition"] == ("released_after_error_verified_closed")
    assert durable_store.waiter_notification_count == 1
    assert sdk.dispatch_count == sdk.readback_count == 1


def test_late_readback_with_a_wrong_canonical_digest_terminalizes_unknown_not_success():
    bad_readback = _scene_receipt("marked_take.vdf", "d" * 64, "a" * 64)
    bad_readback["scene_identity_sha256"] = "f" * 64
    sdk = FakeOfficialSdkBoundary()
    sdk.after_receipt = bad_readback
    workflow, jobs, _, job_id = _pending_async_workflow(sdk=sdk)

    result = workflow.poll(job_id, late_success=True)

    assert result["context"]["state"] == "failed_unknown"
    assert result["success"] is False
    assert result["context"]["job"]["terminal_source"] == "official_sdk_failure"
    assert (
        jobs.tombstone(job_id)["terminal_event_id"] == result["context"]["job"]["terminal_event_id"]
    )


def test_late_readback_digest_must_equal_the_exact_completion_event_receipt():
    resolver = _resolver()
    event_receipt = _approved_after_receipt(_request(), resolver)
    different_readback = json.loads(json.dumps(event_receipt))
    different_readback["sha256"] = "d" * 64
    sdk = FakeOfficialSdkBoundary(
        after_receipt=different_readback,
        completion_event_receipt=event_receipt,
    )
    workflow, _, _, job_id = _pending_async_workflow(sdk=sdk)

    result = workflow.poll(job_id, late_success=True)

    assert result["context"]["state"] == "failed_unknown"
    assert result["context"]["job"]["terminal_source"] == "official_sdk_failure"


def test_malformed_completion_receipt_with_extra_sdk_data_fails_unknown():
    malformed = _approved_after_receipt(_request(), _resolver())
    malformed["sdk_internal_text"] = "must-not-authorize-success"
    sdk = FakeOfficialSdkBoundary(
        after_receipt=malformed,
        completion_event_receipt=malformed,
    )
    workflow, _, _, job_id = _pending_async_workflow(sdk=sdk)

    result = workflow.poll(job_id, late_success=True)

    _validate_result(result)
    assert result["context"]["state"] == "failed_unknown"
    assert result["context"]["job"]["terminal_source"] == "official_sdk_failure"


def test_limit_plus_one_late_readback_terminalizes_unknown_and_never_replays():
    valid_event_receipt = _approved_after_receipt(_request(), _resolver())
    oversized_readback = json.loads(json.dumps(valid_event_receipt))
    oversized_readback["sdk_internal_text"] = ""
    base_size, _ = _completion_receipt_binding(oversized_readback, max_bytes=1_000_000)
    oversized_readback["sdk_internal_text"] = "x" * (65_537 - base_size)
    assert _completion_receipt_binding(oversized_readback, max_bytes=65_537)[0] == 65_537
    sdk = FakeOfficialSdkBoundary(
        after_receipt=oversized_readback,
        completion_event_receipt=valid_event_receipt,
    )
    workflow, jobs, _, job_id = _pending_async_workflow(sdk=sdk)

    result = workflow.poll(job_id, late_success=True)

    _validate_result(result)
    assert result["context"]["state"] == "failed_unknown"
    assert result["context"]["after_receipt"] is None
    assert "sdk_internal_text" not in json.dumps(result, sort_keys=True)
    assert result["context"]["job"]["status"] == "terminal"
    assert jobs.descriptor(job_id)["status"] == "terminal"
    assert workflow.guard.release_count == 1
    assert sdk.dispatch_count == sdk.readback_count == 1

    terminal = workflow.poll(job_id, late_success=True)
    assert terminal == result["context"]["job"]
    assert workflow.guard.release_count == 1
    assert sdk.dispatch_count == sdk.readback_count == 1


def test_unserializable_late_readback_terminalizes_redacted_unknown():
    sdk = FakeOfficialSdkBoundary()
    sdk.after_receipt = {"sdk_internal_text": object()}
    workflow, jobs, _, job_id = _pending_async_workflow(sdk=sdk)

    result = workflow.poll(job_id, late_success=True)

    _validate_result(result)
    assert result["context"]["state"] == "failed_unknown"
    assert result["context"]["after_receipt"] is None
    assert result["message"] == "Recovery scene restore did not reach verified success."
    assert result["error"] == "RestoreFailedUnknown"
    assert jobs.descriptor(job_id)["status"] == "terminal"
    assert workflow.guard.release_count == 1
    assert sdk.dispatch_count == sdk.readback_count == 1


def test_late_readback_equal_to_before_terminalizes_failed_unchanged():
    before_receipt = _scene_receipt("working_scene.vdf", "b" * 64, "c" * 64)
    sdk = FakeOfficialSdkBoundary(after_receipt=before_receipt)
    workflow, _, _, job_id = _pending_async_workflow(sdk=sdk)

    result = workflow.poll(job_id, late_success=True)

    _validate_result(result)
    assert result["context"]["state"] == "failed_unchanged"
    assert result["context"]["effect"] == "unchanged"
    assert result["context"]["before_receipt"] == result["context"]["after_receipt"]


def test_operation_binding_changes_with_the_request_and_unknown_job_ids_fail_closed():
    bindings = []
    for request in (_request(), _request(request_id="restore-0002")):
        store = FakeTrustedConfirmationStore()
        store.issue(request, authenticated=True)
        jobs = FakeAsyncRestoreJobRegistry()
        result = FakeAsyncRestoreWorkflow(
            store,
            FakeOfficialSdkBoundary(),
            FakeGuardedTargetBoundary(),
            jobs,
        ).start(request, "request_timeout")
        bindings.append(result["context"]["job"]["operation_binding_sha256"])
        with pytest.raises(KeyError):
            jobs.poll("restore-job-does-not-exist")

    assert bindings[0] != bindings[1]


def test_fresh_registry_generation_cannot_reuse_a_previous_job_identity():
    request = _request()
    durable_store = FakeDurableJobStore()
    job_ids = []
    for _ in range(2):
        store = FakeTrustedConfirmationStore()
        store.issue(request, authenticated=True)
        registry = (
            FakeAsyncRestoreJobRegistry(durable_store)
            if not job_ids
            else FakeAsyncRestoreJobRegistry.restart_after_process_loss(durable_store)
        )
        workflow = FakeAsyncRestoreWorkflow(
            store,
            FakeOfficialSdkBoundary(),
            FakeGuardedTargetBoundary(),
            registry,
        )
        result = workflow.start(request, "request_timeout")
        job_ids.append(result["context"]["job"]["job_id"])

    assert job_ids[0] != job_ids[1]


def test_live_registry_process_epoch_lease_cannot_be_stolen():
    jobs = FakeAsyncRestoreJobRegistry()

    with pytest.raises(RuntimeError, match="registry process epoch lease is still owned"):
        FakeAsyncRestoreJobRegistry(jobs.store)


def test_late_completion_event_is_bound_to_exact_job_generation_and_operation():
    workflow, jobs, sdk, job_id = _pending_async_workflow()
    event = jobs.make_completion_event(job_id, sdk.completion_receipt())
    forged = dict(event, operation_binding_sha256="f" * 64)

    with pytest.raises(RuntimeError, match="completion event identity rejected"):
        jobs.claim_late_readback(forged)

    assert sdk.readback_count == 0
    assert jobs.descriptor(job_id)["status"] == "awaiting_late_readback"


def test_terminal_job_tombstone_survives_registry_restart_and_is_never_reused():
    durable_store = FakeDurableJobStore()
    workflow, jobs, _, job_id = _pending_async_workflow(durable_store)
    terminal = workflow.poll(job_id, late_success=True)["context"]["job"]

    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(durable_store)
    assert restarted.descriptor(job_id) == terminal
    tombstone = restarted.tombstone(job_id)
    assert tombstone["job_id"] == job_id
    assert tombstone["operation_binding_sha256"] == terminal["operation_binding_sha256"]
    assert tombstone["terminal_event_id"] == terminal["terminal_event_id"]
    with pytest.raises(RuntimeError, match="job identity reuse forbidden"):
        durable_store.reserve_job_id(
            terminal["job_generation"],
            1,
            terminal["operation_binding_sha256"],
        )


def test_duplicate_concurrent_late_completion_reads_back_and_terminalizes_once():
    workflow, jobs, sdk, job_id = _pending_async_workflow()
    barrier = Barrier(2)

    def poll_once():
        barrier.wait()
        return workflow.poll(job_id, late_success=True)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: poll_once(), range(2)))

    descriptors = [result.get("context", {}).get("job", result) for result in results]
    assert sdk.readback_count == 1
    assert all(descriptor["status"] == "terminal" for descriptor in descriptors)
    assert descriptors[0] == descriptors[1]
    assert jobs.tombstone(job_id)["terminal_event_id"] == descriptors[0]["terminal_event_id"]


def test_out_of_order_completion_event_is_rejected_without_state_change():
    _, jobs, sdk, job_id = _pending_async_workflow()
    before = jobs.descriptor(job_id)
    event = jobs.make_completion_event(job_id, sdk.completion_receipt())
    event["event_sequence"] += 1
    event["event_digest_sha256"] = jobs.digest_completion_event(event)

    with pytest.raises(RuntimeError, match="completion event sequence rejected"):
        jobs.claim_late_readback(event)

    assert jobs.descriptor(job_id) == before
    assert sdk.readback_count == 0


def test_cancellation_after_terminal_is_ignored_without_mutating_terminal_record():
    workflow, jobs, _, job_id = _pending_async_workflow()
    workflow.poll(job_id, late_success=True)
    before = jobs.descriptor(job_id)

    disposition = jobs.request_cancellation(job_id)

    assert disposition == {
        "requested": True,
        "effective": False,
        "disposition": "ignored_after_terminal",
    }
    assert jobs.descriptor(job_id) == before


def test_stale_late_readback_claim_cannot_commit_or_release_a_replaced_guard():
    _, jobs, sdk, job_id = _pending_async_workflow()
    event = jobs.make_completion_event(job_id, sdk.completion_receipt())
    claim = jobs.claim_late_readback(event)
    foreign_guard = FakeGuardedTargetBoundary()
    foreign_token = foreign_guard.open()
    with jobs.store.condition:
        record = jobs._records[job_id]
        original_guard = record["guard"]
        jobs._advance(
            record,
            guard=foreign_guard,
            guard_token=foreign_token,
        )
        replaced_revision = record["record_revision"]

    with pytest.raises(RuntimeError, match="late completion fence rejected"):
        jobs.complete_guarded_readback(claim, sdk.readback_after())

    assert original_guard.release_count == 0
    assert foreign_guard.release_count == 0
    with jobs.store.condition:
        assert jobs._records[job_id]["record_revision"] == replaced_revision
        assert jobs._records[job_id]["status"] == "readback_in_progress"


def test_forged_late_readback_claim_owner_cannot_commit_or_release_guard():
    _, jobs, sdk, job_id = _pending_async_workflow()
    event = jobs.make_completion_event(job_id, sdk.completion_receipt())
    claim = jobs.claim_late_readback(event)
    forged = dict(claim, claim_owner="rco1-" + "0" * 64)
    with jobs.store.condition:
        guard = jobs._records[job_id]["guard"]
        revision = jobs._records[job_id]["record_revision"]

    with pytest.raises(RuntimeError, match="late completion fence rejected"):
        jobs.complete_guarded_readback(forged, sdk.readback_after())

    assert guard.release_count == 0
    with jobs.store.condition:
        assert jobs._records[job_id]["record_revision"] == revision
        assert jobs._records[job_id]["status"] == "readback_in_progress"


@pytest.mark.parametrize(
    "claim_update",
    (
        {"claimed_record_revision": None},
        {"fence_revision": "7"},
        {"retained_guard_generation": None},
    ),
)
def test_malformed_late_readback_fence_fails_closed_without_releasing_guard(
    claim_update,
):
    _, jobs, sdk, job_id = _pending_async_workflow()
    event = jobs.make_completion_event(job_id, sdk.completion_receipt())
    claim = jobs.claim_late_readback(event)
    malformed = dict(claim, **claim_update)
    with jobs.store.condition:
        guard = jobs._records[job_id]["guard"]
        revision = jobs._records[job_id]["record_revision"]

    with pytest.raises(RuntimeError, match="late completion fence rejected"):
        jobs.complete_guarded_readback(malformed, sdk.readback_after())

    assert guard.release_count == 0
    with jobs.store.condition:
        assert jobs._records[job_id]["record_revision"] == revision
        assert jobs._records[job_id]["status"] == "readback_in_progress"


def test_late_readback_recaptures_guard_immediately_before_terminal_cas_and_release():
    _, jobs, sdk, job_id = _pending_async_workflow()
    event = jobs.make_completion_event(job_id, sdk.completion_receipt())
    claim = jobs.claim_late_readback(event)
    with jobs.store.condition:
        guard = jobs._records[job_id]["guard"]
        revision = jobs._records[job_id]["record_revision"]
        guard.observed_change_phase = "late_readback_commit"
        guard.attack_kind = "same_content"

    with pytest.raises(RuntimeError, match="late completion fence rejected"):
        jobs.complete_guarded_readback(claim, sdk.readback_after())

    assert guard.recapture_count == 2
    assert guard.release_count == 0
    with jobs.store.condition:
        assert jobs._records[job_id]["record_revision"] == revision
        assert jobs._records[job_id]["status"] == "readback_in_progress"


def test_old_late_readback_claim_is_epoch_fenced_after_registry_restart():
    _, jobs, sdk, job_id = _pending_async_workflow()
    event = jobs.make_completion_event(job_id, sdk.completion_receipt())
    claim = jobs.claim_late_readback(event)
    with jobs.store.condition:
        record = jobs._records[job_id]
        guard = record["guard"]
        assert record["readback_claim_owner"] == claim["claim_owner"]
        assert record["readback_claim_generation"] == claim["claim_generation"]
        assert record["readback_claim_record_revision"] == claim["claimed_record_revision"]
        assert record["readback_claim_fence_revision"] == claim["fence_revision"]
        assert record["readback_claim_registry_epoch"] == claim["registry_epoch"]

    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(jobs.store)
    with pytest.raises(RuntimeError, match="late completion fence rejected"):
        restarted.complete_guarded_readback(claim, sdk.completion_receipt())

    terminal = restarted.descriptor(job_id)
    assert terminal["status"] == "terminal"
    assert restarted.audit_context(job_id)["terminal_outcome"] == "failed_unknown"
    assert restarted.generation != claim["registry_epoch"]
    assert sdk.readback_count == 0
    assert guard.release_count == 1


def test_orphaned_readback_claim_without_request_local_object_fails_closed_on_restart():
    workflow, jobs, sdk, job_id = _pending_async_workflow()
    event = jobs.make_completion_event(job_id, sdk.completion_receipt())
    jobs.claim_late_readback(event)
    durable_store = jobs.store
    guard = workflow.guard
    del event, jobs, workflow

    restarted = FakeAsyncRestoreJobRegistry(durable_store)
    observed = {}
    poller = Thread(
        target=lambda: observed.setdefault("terminal", restarted.poll(job_id)),
        daemon=True,
    )
    poller.start()
    poller.join(timeout=0.25)

    assert poller.is_alive() is False, "orphaned durable readback claim blocked status polling"
    terminal = observed["terminal"]
    assert terminal["status"] == "terminal"
    assert terminal["snapshot_source"] == terminal["terminal_source"] == "readback_owner_lost"
    assert restarted.audit_context(job_id)["terminal_outcome"] == "failed_unknown"
    assert restarted.tombstone(job_id)["terminal_event_id"] == terminal["terminal_event_id"]
    assert durable_store.waiter_notification_count == 1
    assert sdk.dispatch_count == 1
    assert sdk.readback_count == 0
    assert guard.release_count == 1

    contract = _contract()
    Draft202012Validator(
        {
            "$defs": contract["private_audit_result_schema"]["$defs"],
            "$ref": "#/$defs/terminal_unknown_job_descriptor",
        }
    ).validate(terminal)
    public_terminal = _public_job_for_state(
        "failed_unknown",
        terminal,
        "a" * 64,
        b"adapter-private-test-key",
    )
    Draft202012Validator(
        {
            "$defs": contract["output_schema"]["$defs"],
            "$ref": "#/$defs/public_terminal_unknown_job",
        }
    ).validate(public_terminal)


def test_undispatched_terminal_record_rejects_every_late_transition_entrypoint():
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    jobs = FakeAsyncRestoreJobRegistry()
    workflow = FakeAsyncRestoreWorkflow(
        confirmation_store,
        FakeOfficialSdkBoundary(),
        FakeGuardedTargetBoundary(),
        jobs,
    )
    terminal = workflow.start(request, "cancellation_before_dispatch")["context"]["job"]

    with pytest.raises(RuntimeError, match="terminal record is immutable"):
        jobs.retain_handles(
            terminal["job_id"],
            FakeGuardedTargetBoundary(),
            {"held": True},
        )
    with pytest.raises(RuntimeError, match="terminal record is immutable"):
        jobs.make_completion_event(terminal["job_id"], {})
    assert jobs.descriptor(terminal["job_id"]) == terminal


def test_pending_snapshot_cannot_be_published_after_a_newer_terminal_revision():
    workflow, jobs, _, job_id = _pending_async_workflow()
    stale = jobs.descriptor(job_id)
    workflow.poll(job_id, late_success=True)

    with pytest.raises(RuntimeError, match="stale job snapshot rejected"):
        jobs.publish_descriptor(stale)


def test_cancel_and_completion_race_is_monotonic_and_never_redispatches():
    workflow, jobs, sdk, job_id = _pending_async_workflow()
    barrier = Barrier(2)

    def complete():
        barrier.wait()
        return workflow.poll(job_id, late_success=True)

    def cancel():
        barrier.wait()
        return jobs.request_cancellation(job_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        completion = pool.submit(complete)
        cancellation = pool.submit(cancel)
        completed = completion.result()
        cancellation_result = cancellation.result()

    terminal = jobs.descriptor(job_id)
    assert completed["context"]["job"] == terminal
    assert terminal["status"] == "terminal"
    assert terminal["dispatch_count"] == sdk.dispatch_count == 1
    assert sdk.readback_count == 1
    assert cancellation_result["effective"] is False
    assert cancellation_result["disposition"] in {
        "requested_after_dispatch_operation_continues",
        "ignored_after_terminal",
    }


@pytest.mark.parametrize("readback_raises", (False, True))
def test_cancellation_during_active_readback_claim_preserves_fence_and_terminalizes(
    readback_raises,
):
    workflow, jobs, sdk, job_id = _pending_async_workflow()
    readback_entered = Event()
    release_readback = Event()
    original_readback = sdk.readback_after
    secret = "late SDK failure C:\\secret\\take.vdf token-456"

    def blocking_readback():
        readback_entered.set()
        assert release_readback.wait(timeout=5)
        if readback_raises:
            with sdk._lock:
                sdk.readback_count += 1
            raise RuntimeError(secret)
        return original_readback()

    sdk.readback_after = blocking_readback
    with ThreadPoolExecutor(max_workers=1) as pool:
        completion = pool.submit(workflow.poll, job_id, late_success=True)
        assert readback_entered.wait(timeout=5)
        with jobs.store.condition:
            claimed_revision = jobs._records[job_id]["record_revision"]
            assert jobs._records[job_id]["status"] == "readback_in_progress"

        cancellation = jobs.request_cancellation(job_id)
        with jobs.store.condition:
            cancellation_revision = jobs._records[job_id]["record_revision"]
            cancellation_intent = getattr(jobs.store, "cancellation_intents", {}).get(job_id)
        repeated_cancellation = jobs.request_cancellation(job_id)
        with jobs.store.condition:
            assert jobs.store.cancellation_intents[job_id] == cancellation_intent
            assert jobs._records[job_id]["record_revision"] == cancellation_revision
        release_readback.set()
        completed = completion.result(timeout=5)

    _validate_result(completed)
    assert cancellation_revision == claimed_revision
    assert cancellation_intent["fence_revision"] == claimed_revision
    expected_state = "failed_unknown" if readback_raises else "succeeded"
    assert completed["context"]["state"] == expected_state
    assert secret not in json.dumps(completed, sort_keys=True)
    assert cancellation == {
        "requested": True,
        "effective": False,
        "disposition": "requested_after_dispatch_operation_continues",
    }
    assert repeated_cancellation == cancellation
    terminal = jobs.descriptor(job_id)
    assert terminal["status"] == "terminal"
    assert terminal["cancellation_requested"] is True
    assert terminal["cancellation_effective"] is False
    assert terminal["cancellation_disposition"] == ("requested_after_dispatch_operation_continues")
    assert workflow.guard.release_count == 1
    assert sdk.dispatch_count == sdk.readback_count == 1

    assert workflow.poll(job_id, late_success=True) == terminal
    assert workflow.guard.release_count == 1
    assert sdk.dispatch_count == sdk.readback_count == 1


@pytest.mark.parametrize("failure_type", (CancelledError, KeyboardInterrupt))
def test_readback_claim_baseexception_abandons_durably_before_propagation(failure_type):
    workflow, jobs, sdk, job_id = _pending_async_workflow()
    secret = "private readback cancellation C:\\secret\\take.vdf token-789"

    def interrupted_readback():
        with sdk._lock:
            sdk.readback_count += 1
        raise failure_type(secret)

    sdk.readback_after = interrupted_readback
    with jobs.store.condition:
        guard = jobs._records[job_id]["guard"]

    with pytest.raises(failure_type, match="private readback cancellation"):
        workflow.poll(job_id, late_success=True)

    with jobs.store.condition:
        record = jobs._records[job_id]
        assert record["status"] == "terminal"
        assert record["terminal_outcome"] == "failed_unknown"
        assert record["snapshot_source"] == "readback_owner_lost"
        assert record["terminal_source"] == "readback_owner_lost"
        assert record["readback_claim_owner"] is None
    assert jobs.tombstone(job_id)["terminal_event_id"] is not None
    assert jobs.store.waiter_notification_count == 1
    assert job_id not in jobs.store.notification_pending_jobs
    assert sdk.dispatch_count == sdk.readback_count == 1
    assert guard.release_count == 1


def test_readback_baseexception_cleanup_commit_replays_without_stranding_waiters():
    durable_store = FakeDurableJobStore()
    durable_store.fail_tombstone_write_once = True
    workflow, jobs, sdk, job_id = _pending_async_workflow(durable_store)
    secret = "private cancellation detail C:\\secret\\take.vdf token-987"

    def interrupted_readback():
        with sdk._lock:
            sdk.readback_count += 1
        raise CancelledError(secret)

    sdk.readback_after = interrupted_readback

    with pytest.raises(CancelledError, match="private cancellation detail"):
        workflow.poll(job_id, late_success=True)

    with jobs.store.condition:
        record = jobs._records[job_id]
        assert record["status"] == "terminal"
        assert record["cleanup_commit_pending"] is True
        assert job_id not in durable_store.tombstones
    terminal = jobs.descriptor(job_id)
    assert terminal["terminal_source"] == "readback_owner_lost"
    assert terminal["cleanup_disposition"] == "released"
    assert jobs.tombstone(job_id)["terminal_event_id"] == terminal["terminal_event_id"]
    assert durable_store.waiter_notification_count == 1
    assert job_id not in durable_store.notification_pending_jobs
    assert secret not in json.dumps(terminal, sort_keys=True)


def test_claim_bound_cancellation_intent_is_folded_during_orphan_recovery():
    _, jobs, sdk, job_id = _pending_async_workflow()
    event = jobs.make_completion_event(job_id, sdk.completion_receipt())
    claim = jobs.claim_late_readback(event)
    claimed_revision = claim["fence_revision"]

    cancellation = jobs.request_cancellation(job_id)
    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(jobs.store)
    with pytest.raises(RuntimeError, match="late completion fence rejected"):
        restarted.complete_guarded_readback(claim, sdk.completion_receipt())

    assert cancellation["effective"] is False
    terminal = restarted.descriptor(job_id)
    assert terminal["record_revision"] > claimed_revision
    assert terminal["cancellation_requested"] is True
    assert terminal["cancellation_effective"] is False
    assert terminal["cancellation_disposition"] == ("requested_after_dispatch_operation_continues")
    assert restarted.audit_context(job_id)["terminal_outcome"] == "failed_unknown"
    assert restarted.tombstone(job_id)["terminal_event_id"] == terminal["terminal_event_id"]
    assert sdk.dispatch_count == 1
    assert sdk.readback_count == 0


def _pending_async_workflow(durable_store=None, *, sdk=None):
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    sdk = sdk or FakeOfficialSdkBoundary()
    jobs = FakeAsyncRestoreJobRegistry(durable_store)
    workflow = FakeAsyncRestoreWorkflow(
        confirmation_store,
        sdk,
        FakeGuardedTargetBoundary(),
        jobs,
    )
    result = workflow.start(request, "request_timeout")
    return workflow, jobs, sdk, result["context"]["job"]["job_id"]


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("terminal_source", "official_sdk_readback"),
        ("dispatch_count", 0),
        ("handle_retention_owner", "released_after_terminal_readback"),
        ("poll_allowed", False),
        ("duplicate_execution_allowed", True),
        ("late_completion_disposition", "not_applicable"),
    ),
)
def test_pending_job_descriptor_rejects_false_lifecycle_claims(field, value):
    invalid = _result("timed_out")
    invalid["context"]["job"][field] = value

    with pytest.raises(ValidationError):
        _validate_result(invalid)


@pytest.mark.parametrize(
    ("state", "updates"),
    (
        ("timed_out", {"cancellation_requested": True}),
        ("indeterminate", {"cancellation_effective": True}),
        (
            "preflight_rejected",
            {
                "cancellation_disposition": "honored_before_dispatch",
                "cancellation_requested": False,
                "cancellation_effective": False,
            },
        ),
        ("succeeded", {"cancellation_effective": True}),
    ),
)
def test_job_schema_rejects_inconsistent_requested_vs_effective_cancellation(state, updates):
    invalid = _result(state)
    invalid["context"]["job"].update(updates)

    with pytest.raises(ValidationError):
        _validate_result(invalid)


def test_job_id_is_typed_inside_context_not_as_an_unowned_top_level_field():
    invalid = _result("timed_out")
    invalid["job_id"] = invalid["context"]["job"]["job_id"]

    with pytest.raises(ValidationError):
        _validate_result(invalid)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalize_final_path(final_path: str) -> str:
    normalized = unicodedata.normalize("NFC", final_path).replace("/", "\\")
    if normalized.startswith("\\\\?\\UNC\\"):
        normalized = "\\\\" + normalized[8:]
    elif normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    normalized = ntpath.normpath(normalized)
    return "".join(
        character.lower() if "A" <= character <= "Z" else character for character in normalized
    )


def _path_binding(final_path: str, volume_serial: str, file_id: str):
    canonical_text = "\n".join(
        (
            "windows-final-path-v1",
            f"volume_serial={volume_serial.upper()}",
            f"file_id={file_id.lower()}",
            f"path={_normalize_final_path(final_path)}",
        )
    )
    canonical_bytes = canonical_text.encode("utf-8")
    return canonical_bytes, hashlib.sha256(canonical_bytes).hexdigest()


def _normalize_receipt_strings(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, dict):
        return {key: _normalize_receipt_strings(item) for key, item in value.items()}
    return value


def _receipt_binding(receipt):
    canonical_bytes = json.dumps(
        _normalize_receipt_strings(receipt),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return canonical_bytes, hashlib.sha256(canonical_bytes).hexdigest()


def _completion_receipt_binding(
    receipt,
    *,
    max_bytes=65_536,
    chunk_size=4_096,
    on_chunk=None,
):
    if max_bytes < 1 or chunk_size < 1:
        raise ValueError("completion receipt resource limits must be positive")
    payload = {
        "receipt_version": "guarded-official-sdk-completion-v1",
        "receipt": _normalize_receipt_strings(receipt),
    }
    encoder = json.JSONEncoder(
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256()
    total = 0
    for text_chunk in encoder.iterencode(payload):
        encoded = text_chunk.encode("utf-8")
        for offset in range(0, len(encoded), chunk_size):
            bounded_chunk = encoded[offset : offset + chunk_size]
            if total + len(bounded_chunk) > max_bytes:
                raise ValueError("completion receipt exceeds approved resource limit")
            digest.update(bounded_chunk)
            total += len(bounded_chunk)
            if on_chunk is not None:
                on_chunk(len(bounded_chunk))
    return total, digest.hexdigest()


def _scene_identity_binding(observation):
    canonical_bytes = json.dumps(
        _normalize_receipt_strings(observation),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return canonical_bytes, hashlib.sha256(canonical_bytes).hexdigest()


def _scene_identity_from_raw(get_scene_name_result, frame_count, resolver):
    if (
        not isinstance(get_scene_name_result, tuple)
        or len(get_scene_name_result) != 2
        or not all(isinstance(item, str) for item in get_scene_name_result)
    ):
        raise ValueError("GetSceneName must return exactly two strings")
    if type(frame_count) is not int or frame_count < 0:
        raise ValueError("GetFrameCount must return a nonnegative integer")

    scene_path, name_or_path = (
        unicodedata.normalize("NFC", item) for item in get_scene_name_result
    )
    if [scene_path, name_or_path] == [".", ".vdf"]:
        raise ValueError("unsaved scene sentinel cannot produce a receipt")

    normalized_scene_path = ntpath.normpath(scene_path.replace("/", "\\"))
    scene_drive, scene_tail = ntpath.splitdrive(normalized_scene_path)
    if not scene_drive or not scene_tail.startswith("\\"):
        raise ValueError("scene path must be an absolute Windows directory")

    normalized_name_or_path = ntpath.normpath(name_or_path.replace("/", "\\"))
    name_drive, name_tail = ntpath.splitdrive(normalized_name_or_path)
    if name_drive and name_tail.startswith("\\"):
        candidate_path = normalized_name_or_path
        if _normalize_final_path(ntpath.dirname(candidate_path)) != _normalize_final_path(
            normalized_scene_path
        ):
            raise ValueError("scene path parent mismatch")
    elif "\\" not in name_or_path and "/" not in name_or_path:
        candidate_path = ntpath.join(normalized_scene_path, normalized_name_or_path)
    else:
        raise ValueError("relative scene name must not contain a path separator")

    scene_name = unicodedata.normalize("NFC", ntpath.basename(normalized_name_or_path))
    if len(scene_name) <= 4 or not scene_name.lower().endswith(".vdf"):
        raise ValueError("saved scene name must be a bounded VDF basename")
    evidence = resolver.resolve(candidate_path)
    return {
        "canonical_path_sha256": evidence["sha256"],
        "frame_count": frame_count,
        "scene_name": scene_name,
    }


class FakeTrustedPathResolver:
    def __init__(self):
        self._evidence = {}

    def add(self, raw_path, *, final_path, volume_serial, file_id, approved=True):
        self._evidence[raw_path] = {
            "final_path": final_path,
            "volume_serial": volume_serial,
            "file_id": file_id,
            "approved": approved,
        }

    def resolve(self, raw_path):
        evidence = dict(self._evidence[raw_path])
        if not evidence.pop("approved"):
            raise ValueError("unapproved reparse or device identity")
        canonical_bytes, digest = _path_binding(**evidence)
        return {"canonical_bytes": canonical_bytes, "sha256": digest, **evidence}


def _resolver():
    resolver = FakeTrustedPathResolver()
    root_evidence = {
        "final_path": "\\\\?\\C:\\Approved\\recovery",
        "volume_serial": "00000000A1B2C3D4",
        "file_id": "ffeeddccbbaa99887766554433221100",
    }
    file_evidence = {
        "final_path": "\\\\?\\C:\\Approved\\recovery\\marked_take.vdf",
        "volume_serial": "00000000A1B2C3D4",
        "file_id": "00112233445566778899aabbccddeeff",
    }
    resolver.add("C:/operator-approved/recovery", **root_evidence)
    resolver.add("C:/operator-approved/recovery/marked_take.vdf", **file_evidence)
    resolver.add("C:/operator-approved/recovery/../recovery/marked_take.vdf", **file_evidence)
    resolver.add(
        "D:/different-approved-root",
        final_path="\\\\?\\D:\\different-approved-root",
        volume_serial="00000000D4C3B2A1",
        file_id="11112222333344445555666677778888",
    )
    resolver.add(
        "C:/operator-approved/recovery/different_take.vdf",
        final_path="\\\\?\\C:\\Approved\\recovery\\different_take.vdf",
        volume_serial="00000000A1B2C3D4",
        file_id="88887777666655554444333322221111",
    )
    return resolver


def _trusted_target_binding(request, resolver):
    target = resolver.resolve(request["file_path"])
    receipt = request["recovery_receipt"]
    _, receipt_digest = _receipt_binding(receipt)
    return {
        "canonical_path_sha256": target["sha256"],
        "target_volume_serial": target["volume_serial"],
        "target_file_id": target["file_id"],
        "file_name": receipt["file_name"],
        "file_size_bytes": receipt["file_size_bytes"],
        "sha256": receipt["sha256"],
        "recovery_receipt_binding_sha256": receipt_digest,
    }


def _approved_after_receipt(request, resolver):
    target = resolver.resolve(request["file_path"])
    recovery_receipt = request["recovery_receipt"]
    receipt = _scene_receipt(
        recovery_receipt["file_name"],
        target["sha256"],
        recovery_receipt["sha256"],
    )
    receipt["file_size_bytes"] = recovery_receipt["file_size_bytes"]
    receipt["target_identity"] = {
        "canonical_path_sha256": target["sha256"],
        "volume_serial": target["volume_serial"],
        "file_id": target["file_id"],
    }
    return receipt


def _completion_receipt_is_canonical(receipt):
    try:
        required_fields = {
            "active_scene_observed_via",
            "file_evidence_observed_via",
            "file_name",
            "file_size_bytes",
            "sha256",
            "scene_identity_fields",
            "scene_identity_sha256",
        }
        if frozenset(receipt) not in {
            frozenset(required_fields),
            frozenset(required_fields | {"target_identity"}),
        }:
            return False
        identity_fields = receipt["scene_identity_fields"]
        if set(identity_fields) != {
            "canonical_path_sha256",
            "frame_count",
            "scene_name",
        }:
            return False
        _, identity_digest = _scene_identity_binding(identity_fields)
        valid = (
            receipt["active_scene_observed_via"] == "official_sdk"
            and receipt["file_evidence_observed_via"] == "filesystem"
            and receipt["scene_identity_sha256"] == identity_digest
            and identity_fields["scene_name"] == receipt["file_name"]
            and isinstance(receipt["file_name"], str)
            and 0 < len(receipt["file_name"]) <= 255
            and not {"/", "\\"}.intersection(receipt["file_name"])
            and type(receipt["file_size_bytes"]) is int
            and 0 < receipt["file_size_bytes"] <= 8_589_934_592
            and isinstance(receipt["sha256"], str)
            and len(receipt["sha256"]) == 64
            and all(character in "0123456789abcdef" for character in receipt["sha256"])
            and isinstance(identity_fields["canonical_path_sha256"], str)
            and len(identity_fields["canonical_path_sha256"]) == 64
            and type(identity_fields["frame_count"]) is int
            and identity_fields["frame_count"] >= 0
        )
        target_identity = receipt.get("target_identity")
        if target_identity is not None:
            valid = valid and set(target_identity) == {
                "canonical_path_sha256",
                "volume_serial",
                "file_id",
            }
        return valid
    except (KeyError, TypeError):
        return False


def _classify_guarded_completion(
    *,
    before_receipt,
    actual_receipt,
    approved_recovery_receipt,
    approved_target_identity,
):
    if not _completion_receipt_is_canonical(actual_receipt):
        return "failed_unknown"
    if actual_receipt == before_receipt:
        return "failed_unchanged"
    expected_target_members = {
        "file_name": approved_recovery_receipt["file_name"],
        "file_size_bytes": approved_recovery_receipt["file_size_bytes"],
        "sha256": approved_recovery_receipt["sha256"],
        "target_identity": approved_target_identity,
    }
    observed_target_members = {key: actual_receipt.get(key) for key in expected_target_members}
    scene_path_matches = (
        actual_receipt["scene_identity_fields"].get("canonical_path_sha256")
        == approved_target_identity["canonical_path_sha256"]
    )
    if observed_target_members == expected_target_members and scene_path_matches:
        return "succeeded"
    return "failed_unknown"


class FakeTrustedClock:
    def __init__(self, now=NOW_EPOCH_SECONDS):
        self._now = now

    def now(self):
        return self._now

    def advance(self, seconds):
        self._now += seconds


class FakeDurableConfirmationStore:
    def __init__(self):
        self.condition = Condition(RLock())
        self.records = {}
        self.tombstones = {}
        self.consume_count = 0

    def insert_if_absent(self, record):
        confirmation_id = record["confirmation_id"]
        with self.condition:
            if confirmation_id in self.tombstones:
                raise ValueError("confirmation ID is immutable and nonreusable")
            self.tombstones[confirmation_id] = {
                "confirmation_id": confirmation_id,
                "permanent": True,
            }
            self.records[confirmation_id] = record

    def tombstone(self, confirmation_id):
        with self.condition:
            return dict(self.tombstones[confirmation_id])


class FakeTrustedConfirmationStore:
    def __init__(
        self,
        resolver=None,
        *,
        authority_generation="0000000000000001",
        trusted_clock=None,
        durable_store=None,
    ):
        self.resolver = resolver or _resolver()
        self.authority_generation = authority_generation
        self.trusted_clock = trusted_clock or FakeTrustedClock()
        self.store = durable_store or FakeDurableConfirmationStore()

    @property
    def consume_count(self):
        return self.store.consume_count

    def issue(self, request, *, authenticated, now=None):
        if not authenticated:
            raise PermissionError("authenticated operator issuance required")
        now = self.trusted_clock.now() if now is None else now
        root = self.resolver.resolve(request["trusted_root"])
        target = self.resolver.resolve(request["file_path"])
        _, receipt_digest = _receipt_binding(request["recovery_receipt"])
        record = {
            "record_version": "1.1",
            "authority_generation": self.authority_generation,
            "confirmation_id": request["operator_confirmation"]["confirmation_id"],
            "request_id": request["request_id"],
            "canonical_trusted_root_sha256": root["sha256"],
            "canonical_path_sha256": target["sha256"],
            "target_volume_serial": target["volume_serial"],
            "target_file_id": target["file_id"],
            "recovery_receipt_binding_sha256": receipt_digest,
            "issued_at_epoch_seconds": now - 30,
            "expires_at_epoch_seconds": now + 270,
            "destructive_acknowledged": True,
            "non_idempotent_acknowledged": True,
            "consumed": False,
            "revision": 1,
        }
        schema = _contract()["confirmation_authority"]["issuance_record_schema"]
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(record)
        self.store.insert_if_absent(record)
        return record["confirmation_id"]

    def _binding_for_request(self, request):
        root = self.resolver.resolve(request["trusted_root"])
        target = self.resolver.resolve(request["file_path"])
        _, receipt_digest = _receipt_binding(request["recovery_receipt"])
        return {
            "request_id": request["request_id"],
            "canonical_trusted_root_sha256": root["sha256"],
            "canonical_path_sha256": target["sha256"],
            "target_volume_serial": target["volume_serial"],
            "target_file_id": target["file_id"],
            "recovery_receipt_binding_sha256": receipt_digest,
        }

    def trusted_lookup_and_compare(self, request):
        now = self.trusted_clock.now()
        confirmation_id = request["operator_confirmation"]["confirmation_id"]
        with self.store.condition:
            record = self.store.records.get(confirmation_id)
            if record is None:
                return None
            expected = self._binding_for_request(request)
            matches = all(record[field] == value for field, value in expected.items())
            fresh = record["issued_at_epoch_seconds"] <= now < record["expires_at_epoch_seconds"]
            ttl = record["expires_at_epoch_seconds"] - record["issued_at_epoch_seconds"] <= 300
            if not (matches and fresh and ttl and not record["consumed"]):
                return None
            return {
                "confirmation_id": confirmation_id,
                "authority_generation": record["authority_generation"],
                "revision": record["revision"],
                "approved_target_identity": {
                    "canonical_path_sha256": record["canonical_path_sha256"],
                    "volume_serial": record["target_volume_serial"],
                    "file_id": record["target_file_id"],
                },
            }

    def cas_consume(
        self,
        ticket,
        request,
        *,
        guarded_target_binding,
    ):
        with self.store.condition:
            now = self.trusted_clock.now()
            record = self.store.records[ticket["confirmation_id"]]
            expected = self._binding_for_request(request)
            fresh = record["issued_at_epoch_seconds"] <= now < record["expires_at_epoch_seconds"]
            ttl = record["expires_at_epoch_seconds"] - record["issued_at_epoch_seconds"] <= 300
            binding_matches = all(record[field] == value for field, value in expected.items())
            ticket_matches = (
                record["authority_generation"] == ticket.get("authority_generation")
                and record["revision"] == ticket["revision"]
            )
            trusted_target_matches = guarded_target_binding == _trusted_target_binding(
                request,
                self.resolver,
            )
            if not (
                ticket_matches
                and binding_matches
                and trusted_target_matches
                and fresh
                and ttl
                and record["destructive_acknowledged"]
                and record["non_idempotent_acknowledged"]
                and not record["consumed"]
            ):
                return False
            record["consumed"] = True
            record["revision"] += 1
            self.store.consume_count += 1
            return True


class FakeOfficialSdkBoundary:
    def __init__(
        self,
        *,
        crash_after_dispatch=False,
        after_receipt=None,
        completion_event_receipt=None,
    ):
        self._lock = Lock()
        self.crash_after_dispatch = crash_after_dispatch
        self.before_capture_count = 0
        self.dispatch_count = 0
        self.readback_count = 0
        self.dispatch_evidence = []
        self.after_receipt = after_receipt or _approved_after_receipt(_request(), _resolver())
        self.completion_event_receipt = completion_event_receipt or self.after_receipt

    def capture_before(self):
        with self._lock:
            self.before_capture_count += 1
        return _scene_receipt("working_scene.vdf", "b" * 64, "c" * 64)

    def dispatch_restore(self, dispatch_capability):
        assert dispatch_capability["held"] is True
        with self._lock:
            self.dispatch_count += 1
            self.dispatch_evidence.append(dict(dispatch_capability))
        if self.crash_after_dispatch:
            raise RuntimeError("simulated crash after SDK dispatch entry")

    def readback_after(self):
        with self._lock:
            self.readback_count += 1
        return json.loads(json.dumps(self.after_receipt))

    def completion_receipt(self):
        return json.loads(json.dumps(self.completion_event_receipt))


class FakeDurableCleanupStore:
    def __init__(self):
        self.condition = Condition(RLock())
        self.records = []
        self.pending_records = {}
        self.crash_after_release_once = False

    @staticmethod
    def _binding_digest(binding):
        canonical = json.dumps(binding, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(canonical).hexdigest()

    def prepare(self, *, binding, phase):
        cleanup_binding_sha256 = self._binding_digest(binding)
        pending = {
            "cleanup_version": "2.0",
            "cleanup_binding_sha256": cleanup_binding_sha256,
            "phase": phase,
            "guard_owner": binding["guard_owner"],
            "guard_generation": binding["guard_generation"],
            "release_observation": "not_recorded",
        }
        with self.condition:
            self.pending_records[cleanup_binding_sha256] = dict(pending)
        return pending

    def resolve(self, pending, disposition):
        if self.crash_after_release_once:
            self.crash_after_release_once = False
            raise RuntimeError("simulated crash after guard release")
        cleanup_record = {
            "cleanup_version": pending["cleanup_version"],
            "cleanup_binding_sha256": pending["cleanup_binding_sha256"],
            "phase": pending["phase"],
            "disposition": disposition,
        }
        with self.condition:
            self.records.append(cleanup_record)
            self.pending_records.pop(pending["cleanup_binding_sha256"], None)
        return dict(cleanup_record)

    def record(self, *, binding, phase, disposition):
        canonical = json.dumps(binding, separators=(",", ":"), sort_keys=True).encode()
        cleanup_record = {
            "cleanup_version": "1.0",
            "cleanup_binding_sha256": hashlib.sha256(canonical).hexdigest(),
            "phase": phase,
            "disposition": disposition,
        }
        with self.condition:
            self.records.append(cleanup_record)
        return dict(cleanup_record)

    def last_record(self):
        with self.condition:
            return dict(self.records[-1])


def _release_guard_preserving_primary(
    cleanup_store,
    *,
    binding,
    phase,
    guard,
    guard_token,
    prepared=None,
):
    try:
        guard.release(guard_token)
    except Exception:
        disposition = {
            "still_owned": "release_failed_owner_retained",
            "closed": "released_after_error_verified_closed",
            "indeterminate": "release_indeterminate_quarantined",
        }[guard.cleanup_state(guard_token)]
    else:
        disposition = "released"
    exact_binding = {
        **binding,
        "guard_owner": guard_token["guard_owner"],
        "guard_generation": guard_token["guard_generation"],
    }
    if prepared is None:
        return cleanup_store.record(
            binding=exact_binding,
            phase=phase,
            disposition=disposition,
        )
    return cleanup_store.resolve(prepared, disposition)


class FakeGuardedTargetBoundary:
    PINNED_OBJECTS = (
        "volume_root",
        "trusted_root",
        "recovery_directory",
        "target_file",
    )

    def __init__(
        self,
        *,
        attempt_phase=None,
        observed_change_phase=None,
        attack_kind=None,
        release_failure_phase=None,
    ):
        self._lock = Lock()
        self._owner_secret = secrets.token_hex(32)
        self._next_guard_generation = 1
        self.open_count = 0
        self.recapture_count = 0
        self.release_count = 0
        self._active_count = 0
        self._active_generations = set()
        self._cleanup_indeterminate_generations = set()
        self.attempt_phase = attempt_phase
        self.observed_change_phase = observed_change_phase
        self.attack_kind = attack_kind
        self.release_failure_phase = release_failure_phase
        self.release_error_text = r"CloseHandle failed C:\secret\take.vdf token-123"
        self.attack_log = []
        self.changed_objects = []
        self.baseline_namespace_identity = {
            "volume_root": {"object_id": "volume-root-1"},
            "trusted_root": {"object_id": "trusted-root-1"},
            "recovery_directory": {"object_id": "recovery-directory-1"},
            "target_file": {
                "object_id": "target-file-1",
                "content_sha256": "a" * 64,
            },
        }
        self.current_namespace_identity = {
            name: dict(identity) for name, identity in self.baseline_namespace_identity.items()
        }

    def open(self):
        with self._lock:
            self.open_count += 1
            self._active_count += 1
            guard_generation = f"{self._next_guard_generation:016x}"
            self._next_guard_generation += 1
            self._active_generations.add(guard_generation)
        return {
            "held": True,
            "guard_owner": "rgo1-" + self._owner_secret,
            "guard_generation": guard_generation,
            "dispatch_path": r"\\?\Volume{approved}\recovery\marked_take.vdf",
            "pinned_objects": self.PINNED_OBJECTS,
            "namespace_identity": {
                name: dict(identity) for name, identity in self.current_namespace_identity.items()
            },
        }

    def recapture(self, token):
        if not self.owns(token):
            raise RuntimeError("guard ownership rejected")
        with self._lock:
            self.recapture_count += 1

    def owns(self, token):
        return (
            token.get("held") is True
            and token.get("guard_owner") == "rgo1-" + self._owner_secret
            and token.get("guard_generation") in self._active_generations
        )

    def cleanup_state(self, token):
        generation = token.get("guard_generation")
        if generation in self._active_generations:
            return "still_owned"
        if generation in self._cleanup_indeterminate_generations:
            return "indeterminate"
        return "closed"

    def checkpoint_identity(self, token, phase):
        assert token["held"] is True
        if self.observed_change_phase == phase:
            changed_object = {
                "namespace": "volume_root",
                "junction": "trusted_root",
                "parent": "recovery_directory",
                "same_content": "target_file",
            }[self.attack_kind]
            self.current_namespace_identity[changed_object]["object_id"] += "-swapped"
            self.changed_objects.append(changed_object)
            self.attack_log.append(
                {
                    "phase": phase,
                    "kind": self.attack_kind,
                    "outcome": "identity_changed",
                }
            )
        if self.attempt_phase == phase:
            self.attack_log.append(
                {
                    "phase": phase,
                    "kind": self.attack_kind,
                    "outcome": "blocked_by_pinned_chain",
                }
            )
        return self.current_namespace_identity == token["namespace_identity"]

    def dispatch_capability(self, token):
        assert token["held"] is True
        return {
            "dispatch_path": token["dispatch_path"],
            "pinned_objects": token["pinned_objects"],
            "held": token["held"],
        }

    def cas_binding(self, token, request, resolver):
        assert token["held"] is True
        binding = _trusted_target_binding(request, resolver)
        target = self.current_namespace_identity["target_file"]
        binding["sha256"] = target["content_sha256"]
        return binding

    def conflicting_replace_allowed(self):
        with self._lock:
            return self._active_count == 0

    def release(self, token):
        if not self.owns(token):
            raise RuntimeError("guard ownership rejected")
        if self.release_failure_phase == "before_close":
            raise RuntimeError(self.release_error_text)
        token["held"] = False
        with self._lock:
            self._active_generations.remove(token["guard_generation"])
            self.release_count += 1
            self._active_count -= 1
        if self.release_failure_phase == "after_close":
            raise RuntimeError(self.release_error_text)
        if self.release_failure_phase == "indeterminate_after_close":
            self._cleanup_indeterminate_generations.add(token["guard_generation"])
            raise RuntimeError(self.release_error_text)


class FakeRestoreWorkflow:
    def __init__(
        self,
        store,
        sdk,
        guard,
        before_cas_barrier,
        cleanup_store=None,
        durable_store=None,
    ):
        self.store = store
        self.sdk = sdk
        self.guard = guard
        self.before_cas_barrier = before_cas_barrier
        self.jobs = FakeAsyncRestoreJobRegistry(durable_store or FakeDurableJobStore())
        if cleanup_store is not None:
            self.jobs.store.cleanup_store = cleanup_store
        self.cleanup_store = self.jobs.store.cleanup_store
        self.conflicting_replace_observations = []

    def execute(self, request):
        ticket = self.store.trusted_lookup_and_compare(request)
        assert ticket is not None
        job_id = self.jobs.create_before_host_connection(request, ticket, self.store.resolver)
        guard_token = self.guard.open()
        self.jobs.retain_handles(job_id, self.guard, guard_token)
        try:
            before_receipt = self.sdk.capture_before()
            self.jobs.record_before_receipt(job_id, before_receipt)
            if not self.guard.checkpoint_identity(guard_token, "preflight"):
                result = _result("target_guard_rejected")
                result["context"]["before_receipt"] = before_receipt
                return result
            self.guard.recapture(guard_token)
            if not self.guard.checkpoint_identity(guard_token, "recapture"):
                result = _result("target_guard_rejected")
                result["context"]["before_receipt"] = before_receipt
                return result
            self.conflicting_replace_observations.append(self.guard.conflicting_replace_allowed())
            self.before_cas_barrier.wait()
            if not self.guard.checkpoint_identity(guard_token, "cas"):
                result = _result("target_guard_rejected")
                result["context"]["before_receipt"] = before_receipt
                return result
            if not self.guard.checkpoint_identity(guard_token, "dispatch"):
                result = _result("target_guard_rejected")
                result["context"]["before_receipt"] = before_receipt
                return result
            if not self.store.cas_consume(
                ticket,
                request,
                guarded_target_binding=self.guard.cas_binding(
                    guard_token,
                    request,
                    self.store.resolver,
                ),
            ):
                result = _result("confirmation_consume_rejected")
                result["context"]["before_receipt"] = before_receipt
                return result
            self.jobs.reserve_dispatch(job_id)
            self.sdk.dispatch_restore(self.guard.dispatch_capability(guard_token))
            self.jobs.mark_dispatched(job_id)
            try:
                actual_receipt = self.sdk.readback_after()
                outcome = _classify_guarded_completion(
                    before_receipt=before_receipt,
                    actual_receipt=actual_receipt,
                    approved_recovery_receipt=request["recovery_receipt"],
                    approved_target_identity=ticket["approved_target_identity"],
                )
            except Exception:
                actual_receipt = None
                outcome = "failed_unknown"
            result = _result(outcome)
            result["context"]["approved_recovery_receipt"] = json.loads(
                json.dumps(request["recovery_receipt"])
            )
            if outcome == "succeeded":
                result["context"]["approved_target_identity"] = ticket["approved_target_identity"]
                result["context"]["after_receipt"] = actual_receipt
            elif outcome == "failed_unchanged":
                result["context"]["after_receipt"] = actual_receipt
            result["context"]["before_receipt"] = before_receipt
            return result
        finally:
            if "result" in locals():
                self.jobs.complete_synchronous(job_id, result["context"]["state"])
                result["context"]["job"] = self.jobs.descriptor(job_id)


class FakeRegistryProcessEpochLease:
    pass


class FakeDurableJobStore:
    def __init__(self):
        self.condition = Condition(RLock())
        self._next_generation = 1
        self._next_claim_generation = 1
        self.active_registry_epoch = None
        self.retired_registry_epochs = set()
        self._active_registry_epoch_lease = None
        self.claim_owner_secret = secrets.token_bytes(32)
        self.records = {}
        self.tombstones = {}
        self.cancellation_intents = {}
        self.reserved_job_ids = set()
        self.cleanup_store = FakeDurableCleanupStore()
        self.fail_tombstone_write_once = False
        self.fail_waiter_notification_once = False
        self.fail_after_notification_intent_once = False
        self.notification_pending_jobs = set()
        self.waiter_notification_count = 0

    def start_generation(self):
        with self.condition:
            active_lease = (
                self._active_registry_epoch_lease()
                if self._active_registry_epoch_lease is not None
                else None
            )
            if active_lease is not None:
                raise RuntimeError("registry process epoch lease is still owned")
            generation = f"{self._next_generation:016x}"
            self._next_generation += 1
            if self.active_registry_epoch is not None:
                self.retired_registry_epochs.add(self.active_registry_epoch)
            self.active_registry_epoch = generation
            lease = FakeRegistryProcessEpochLease()
            self._active_registry_epoch_lease = weakref.ref(lease)
            return generation, lease

    def mark_registry_process_lost_for_restart(self):
        with self.condition:
            lost_epoch = self.active_registry_epoch
            for record in self.records.values():
                if (
                    record.get("job_generation") == lost_epoch
                    and record.get("status") == "dispatch_uncertain"
                ):
                    record["guard"] = None
                    record["guard_token"] = None
            self._active_registry_epoch_lease = None

    def reserve_claim_generation(self):
        with self.condition:
            generation = f"{self._next_claim_generation:016x}"
            self._next_claim_generation += 1
            return generation

    def reserve_job_id(self, generation, sequence, operation_binding_sha256):
        identity = {
            "generation": generation,
            "sequence": sequence,
            "operation_binding_sha256": operation_binding_sha256,
        }
        canonical = json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
        job_id = "rj1-" + hashlib.sha256(canonical).hexdigest()
        with self.condition:
            if job_id in self.reserved_job_ids:
                raise RuntimeError("job identity reuse forbidden")
            self.reserved_job_ids.add(job_id)
        return job_id


class FakeAsyncRestoreJobRegistry:
    _INTERNAL_FIELDS = {
        "guard",
        "guard_token",
        "completion_event",
        "operation_binding",
        "approved_recovery_receipt",
        "approved_target_identity",
        "before_receipt",
        "terminal_outcome",
        "retained_guard_owner",
        "retained_guard_generation",
        "readback_claim_owner",
        "readback_claim_generation",
        "readback_claim_record_revision",
        "readback_claim_fence_revision",
        "readback_claim_registry_epoch",
        "cleanup_pending",
        "cleanup_terminal_plan",
        "cleanup_commit_pending",
        "cleanup_commit_record",
    }

    def __init__(self, durable_store=None):
        self.store = durable_store or FakeDurableJobStore()
        self.generation, self._process_epoch_lease = self.store.start_generation()
        self._records = self.store.records
        self._next_id = 1
        self.poll_count = 0
        self._reconcile_pending_cleanups()
        self._reconcile_orphaned_dispatches()
        self._reconcile_orphaned_readbacks()

    @classmethod
    def restart_after_process_loss(cls, durable_store):
        durable_store.mark_registry_process_lost_for_restart()
        return cls(durable_store)

    def create_before_host_connection(self, request, ticket, resolver):
        root = resolver.resolve(request["trusted_root"])
        target = resolver.resolve(request["file_path"])
        _, receipt_digest = _receipt_binding(request["recovery_receipt"])
        binding = {
            "job_generation": self.generation,
            "request_id": request["request_id"],
            "confirmation_id": ticket["confirmation_id"],
            "confirmation_revision": ticket["revision"],
            "canonical_trusted_root_sha256": root["sha256"],
            "canonical_path_sha256": target["sha256"],
            "target_volume_serial": target["volume_serial"],
            "target_file_id": target["file_id"],
            "recovery_receipt_binding_sha256": receipt_digest,
        }
        binding_bytes = json.dumps(binding, separators=(",", ":"), sort_keys=True).encode()
        operation_binding_sha256 = hashlib.sha256(binding_bytes).hexdigest()
        with self.store.condition:
            sequence = self._next_id
            self._next_id += 1
            job_id = self.store.reserve_job_id(
                self.generation,
                sequence,
                operation_binding_sha256,
            )
            self._records[job_id] = {
                "job_id": job_id,
                "job_generation": self.generation,
                "request_id": request["request_id"],
                "operation": "restore_scene",
                "operation_binding_sha256": operation_binding_sha256,
                "owner": "trusted_adapter_local_restore_job_registry",
                "status_tool": "jobs_get_status",
                "status": "created",
                "snapshot_source": "created",
                "terminal_source": None,
                "cancellation_disposition": "not_requested",
                "handle_retention_owner": "released_before_dispatch",
                "dispatch_count": 0,
                "dispatch_attempt_reserved": False,
                "poll_allowed": False,
                "duplicate_execution_allowed": False,
                "late_completion_disposition": "not_applicable",
                "cleanup_disposition": "not_started",
                "record_revision": 1,
                "event_sequence": 0,
                "identity_tombstoned": True,
                "cancellation_requested": False,
                "cancellation_effective": False,
                "terminal_event_id": None,
                "terminal_event_digest_sha256": None,
                "operation_binding": dict(binding),
                "approved_recovery_receipt": json.loads(json.dumps(request["recovery_receipt"])),
                "approved_target_identity": dict(ticket["approved_target_identity"]),
                "before_receipt": None,
                "terminal_outcome": None,
                "guard": None,
                "guard_token": None,
                "retained_guard_owner": None,
                "retained_guard_generation": None,
                "readback_claim_owner": None,
                "readback_claim_generation": None,
                "readback_claim_record_revision": None,
                "readback_claim_fence_revision": None,
                "readback_claim_registry_epoch": None,
                "completion_event": None,
                "cleanup_pending": None,
                "cleanup_terminal_plan": None,
                "cleanup_commit_pending": False,
                "cleanup_commit_record": None,
            }
        return job_id

    @staticmethod
    def _advance(record, *, advance_event=True, **updates):
        record["record_revision"] += 1
        if advance_event:
            record["event_sequence"] += 1
        record.update(updates)

    @staticmethod
    def digest_completion_event(event):
        payload = {key: value for key, value in event.items() if key != "event_digest_sha256"}
        canonical = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def _completion_event_for_digest(cls, record, completion_receipt_sha256):
        if not (
            isinstance(completion_receipt_sha256, str)
            and len(completion_receipt_sha256) == 64
            and all(character in "0123456789abcdef" for character in completion_receipt_sha256)
        ):
            raise RuntimeError("completion event identity rejected")
        identity = {
            "job_id": record["job_id"],
            "job_generation": record["job_generation"],
            "operation_binding_sha256": record["operation_binding_sha256"],
            "expected_revision": record["record_revision"],
            "event_sequence": record["event_sequence"] + 1,
            "terminal_source": "official_sdk_readback",
            "completion_receipt_sha256": completion_receipt_sha256,
        }
        canonical = json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
        event = {"event_id": "rce1-" + hashlib.sha256(canonical).hexdigest(), **identity}
        event["event_digest_sha256"] = cls.digest_completion_event(event)
        return event

    @classmethod
    def _completion_event_for_record(cls, record, completion_receipt):
        _, completion_receipt_sha256 = _completion_receipt_binding(completion_receipt)
        return cls._completion_event_for_digest(record, completion_receipt_sha256)

    @staticmethod
    def _terminal_event(record, source):
        identity = {
            "job_id": record["job_id"],
            "job_generation": record["job_generation"],
            "operation_binding_sha256": record["operation_binding_sha256"],
            "expected_revision": record["record_revision"],
            "event_sequence": record["event_sequence"] + 1,
            "terminal_source": source,
        }
        canonical = json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
        event_id = "rce1-" + hashlib.sha256(canonical).hexdigest()
        digest = hashlib.sha256(event_id.encode() + b"\0" + canonical).hexdigest()
        return event_id, digest

    def _write_tombstone(self, record, cleanup_record=None):
        completion_event = record["completion_event"]
        tombstone = {
            "job_id": record["job_id"],
            "job_generation": record["job_generation"],
            "operation_binding_sha256": record["operation_binding_sha256"],
            "terminal_revision": record["record_revision"],
            "terminal_event_id": record["terminal_event_id"],
            "terminal_event_digest_sha256": record["terminal_event_digest_sha256"],
            "completion_receipt_sha256": (
                completion_event["completion_receipt_sha256"]
                if completion_event is not None
                else None
            ),
            "cleanup_binding_sha256": (
                cleanup_record["cleanup_binding_sha256"] if cleanup_record is not None else None
            ),
            "cleanup_disposition": record["cleanup_disposition"],
            "handle_retention_owner": record["handle_retention_owner"],
        }
        existing = self.store.tombstones.get(record["job_id"])
        if existing is not None:
            if existing != tombstone:
                raise RuntimeError("durable tombstone binding rejected")
            return
        if self.store.fail_tombstone_write_once:
            self.store.fail_tombstone_write_once = False
            raise RuntimeError("simulated crash during tombstone commit")
        self.store.tombstones[record["job_id"]] = tombstone

    def _commit_cleanup_artifacts(self, record):
        cleanup_record = record.get("cleanup_commit_record")
        if not record.get("cleanup_commit_pending") or cleanup_record is None:
            raise RuntimeError("durable cleanup commit marker rejected")
        self._write_tombstone(record, cleanup_record)
        job_id = record["job_id"]
        if self.store.fail_waiter_notification_once:
            self.store.fail_waiter_notification_once = False
            raise RuntimeError("simulated crash before waiter notification")
        self.store.notification_pending_jobs.add(job_id)
        if self.store.fail_after_notification_intent_once:
            self.store.fail_after_notification_intent_once = False
            raise RuntimeError("simulated crash after durable notification intent")
        self.store.condition.notify_all()
        self.store.waiter_notification_count += 1
        self.store.notification_pending_jobs.discard(job_id)
        record["cleanup_pending"] = None
        record["cleanup_terminal_plan"] = None
        record["cleanup_commit_pending"] = False
        record["cleanup_commit_record"] = None

    def _finalize_cleanup(self, record, cleanup_record):
        plan = record["cleanup_terminal_plan"]
        cleanup_disposition = cleanup_record["disposition"]
        release_confirmed = cleanup_disposition in {
            "released",
            "released_after_error_verified_closed",
        }
        cleanup_indeterminate = cleanup_disposition == "release_indeterminate_quarantined"
        self._advance(
            record,
            advance_event=False,
            status=plan["status"],
            snapshot_source=plan["snapshot_source"],
            terminal_source=plan["terminal_source"],
            handle_retention_owner=(
                (
                    "cleanup_ownership_indeterminate_registry_quarantine"
                    if cleanup_indeterminate
                    else "trusted_adapter_local_restore_job_registry"
                )
                if not release_confirmed
                else plan["released_handle_owner"]
            ),
            poll_allowed=False,
            late_completion_disposition=plan["late_completion_disposition"],
            terminal_event_id=plan["terminal_event_id"],
            terminal_event_digest_sha256=plan["terminal_event_digest_sha256"],
            dispatch_count=plan["dispatch_count"],
            terminal_outcome=plan["outcome"],
            cancellation_requested=plan["cancellation_requested"],
            cancellation_effective=plan["cancellation_effective"],
            cancellation_disposition=plan["cancellation_disposition"],
            cleanup_disposition=cleanup_disposition,
            guard=(
                record["guard"] if cleanup_disposition == "release_failed_owner_retained" else None
            ),
            guard_token=(
                record["guard_token"]
                if cleanup_disposition == "release_failed_owner_retained"
                else None
            ),
            readback_claim_owner=None,
            readback_claim_generation=None,
            readback_claim_record_revision=None,
            readback_claim_fence_revision=None,
            readback_claim_registry_epoch=None,
            cleanup_commit_pending=True,
            cleanup_commit_record=dict(cleanup_record),
        )
        self._commit_cleanup_artifacts(record)

    def _reconcile_cleanup_record(self, record):
        if record.get("cleanup_commit_pending"):
            self._commit_cleanup_artifacts(record)
            return
        pending = record.get("cleanup_pending")
        plan = record.get("cleanup_terminal_plan")
        guard = record.get("guard")
        guard_token = record.get("guard_token")
        if pending is None or plan is None or guard is None or guard_token is None:
            raise RuntimeError("durable cleanup binding rejected")
        exact_owner = (
            pending["guard_owner"] == record["retained_guard_owner"]
            and pending["guard_generation"] == record["retained_guard_generation"]
        )
        if not exact_owner:
            raise RuntimeError("durable cleanup binding rejected")
        disposition = {
            "still_owned": "release_failed_owner_retained",
            "closed": "released_after_error_verified_closed",
            "indeterminate": "release_indeterminate_quarantined",
        }[guard.cleanup_state(guard_token)]
        cleanup_record = self.store.cleanup_store.resolve(pending, disposition)
        self._finalize_cleanup(record, cleanup_record)

    def _reconcile_pending_cleanups(self):
        with self.store.condition:
            for record in self._records.values():
                if record.get("status") == "cleanup_pending" or record.get(
                    "cleanup_commit_pending"
                ):
                    self._reconcile_cleanup_record(record)

    def _reconcile_orphaned_dispatches(self):
        with self.store.condition:
            for record in self._records.values():
                if (
                    record.get("status") != "dispatch_uncertain"
                    or record.get("job_generation") not in self.store.retired_registry_epochs
                ):
                    continue
                if not record.get("dispatch_attempt_reserved") or record.get("dispatch_count"):
                    raise RuntimeError("orphaned dispatch reservation rejected")
                if record.get("guard") is not None or record.get("guard_token") is not None:
                    raise RuntimeError("orphaned dispatch request-local guard was inherited")
                if not record.get("retained_guard_owner") or not record.get(
                    "retained_guard_generation"
                ):
                    raise RuntimeError("orphaned dispatch reservation rejected")
                event_id, event_digest = self._terminal_event(
                    record,
                    "readback_owner_lost",
                )
                cleanup_binding = {
                    "job_id": record["job_id"],
                    "job_generation": record["job_generation"],
                    "operation_binding_sha256": record["operation_binding_sha256"],
                    "terminal_event_id": event_id,
                    "guard_owner": record["retained_guard_owner"],
                    "guard_generation": record["retained_guard_generation"],
                }
                cleanup_pending = self.store.cleanup_store.prepare(
                    binding=cleanup_binding,
                    phase="orphaned_dispatch_process_epoch",
                )
                self._advance(
                    record,
                    advance_event=False,
                    status="cleanup_pending",
                    guard=None,
                    guard_token=None,
                    cleanup_pending=cleanup_pending,
                    cleanup_terminal_plan={
                        "outcome": "failed_unknown",
                        "status": "terminal",
                        "snapshot_source": "readback_owner_lost",
                        "terminal_source": "readback_owner_lost",
                        "released_handle_owner": "released_after_terminal_unknown",
                        "late_completion_disposition": "not_applicable",
                        "dispatch_count": 0,
                        "terminal_event_id": event_id,
                        "terminal_event_digest_sha256": event_digest,
                        "cancellation_requested": record["cancellation_requested"],
                        "cancellation_effective": False,
                        "cancellation_disposition": record["cancellation_disposition"],
                    },
                )
                cleanup_record = self.store.cleanup_store.resolve(
                    cleanup_pending,
                    "released_after_error_verified_closed",
                )
                self._finalize_cleanup(record, cleanup_record)

    def _reconcile_orphaned_readbacks(self):
        with self.store.condition:
            for record in self._records.values():
                claim_epoch = record.get("readback_claim_registry_epoch")
                if (
                    record.get("status") != "readback_in_progress"
                    or claim_epoch not in self.store.retired_registry_epochs
                ):
                    continue
                event = record.get("completion_event")
                guard = record.get("guard")
                guard_token = record.get("guard_token")
                if event is None or guard is None or guard_token is None:
                    raise RuntimeError("orphaned readback binding rejected")
                if (
                    guard_token.get("guard_owner") != record["retained_guard_owner"]
                    or guard_token.get("guard_generation") != record["retained_guard_generation"]
                ):
                    raise RuntimeError("orphaned readback binding rejected")
                cancellation_intent = self.store.cancellation_intents.get(record["job_id"])
                if cancellation_intent is not None and cancellation_intent != (
                    self._cancellation_intent_for_active_claim(record)
                ):
                    raise RuntimeError("cancellation intent binding rejected")
                cleanup_binding = {
                    "job_id": record["job_id"],
                    "job_generation": record["job_generation"],
                    "operation_binding_sha256": record["operation_binding_sha256"],
                    "terminal_event_id": event["event_id"],
                    "guard_owner": guard_token["guard_owner"],
                    "guard_generation": guard_token["guard_generation"],
                }
                cleanup_pending = self.store.cleanup_store.prepare(
                    binding=cleanup_binding,
                    phase="orphaned_readback_claim",
                )
                self._advance(
                    record,
                    advance_event=False,
                    status="cleanup_pending",
                    cleanup_pending=cleanup_pending,
                    cleanup_terminal_plan={
                        "outcome": "failed_unknown",
                        "status": "terminal",
                        "snapshot_source": "readback_owner_lost",
                        "terminal_source": "readback_owner_lost",
                        "released_handle_owner": "released_after_terminal_unknown",
                        "late_completion_disposition": "not_applicable",
                        "dispatch_count": 1,
                        "terminal_event_id": event["event_id"],
                        "terminal_event_digest_sha256": event["event_digest_sha256"],
                        "cancellation_requested": cancellation_intent is not None,
                        "cancellation_effective": False,
                        "cancellation_disposition": (
                            "requested_after_dispatch_operation_continues"
                            if cancellation_intent is not None
                            else record["cancellation_disposition"]
                        ),
                    },
                )
                cleanup_record = _release_guard_preserving_primary(
                    self.store.cleanup_store,
                    binding=cleanup_binding,
                    phase="orphaned_readback_claim",
                    guard=guard,
                    guard_token=guard_token,
                    prepared=cleanup_pending,
                )
                self._finalize_cleanup(record, cleanup_record)

    def retain_handles(self, job_id, guard, guard_token):
        with self.store.condition:
            record = self._records[job_id]
            if record["status"] in {"terminal", "terminal_not_dispatched"}:
                raise RuntimeError("terminal record is immutable")
            if record["dispatch_count"] != 0:
                raise RuntimeError("handles may only transfer before dispatch")
            self._advance(
                record,
                guard=guard,
                guard_token=guard_token,
                retained_guard_owner=guard_token["guard_owner"],
                retained_guard_generation=guard_token["guard_generation"],
                handle_retention_owner="trusted_adapter_local_restore_job_registry",
            )

    def record_before_receipt(self, job_id, before_receipt):
        with self.store.condition:
            record = self._records[job_id]
            if record["status"] != "created" or record["before_receipt"] is not None:
                raise RuntimeError("before receipt transition rejected")
            self._advance(
                record,
                before_receipt=json.loads(json.dumps(before_receipt)),
            )

    def cancel_before_dispatch(self, job_id):
        return self.request_cancellation(job_id)

    def mark_dispatched(self, job_id):
        with self.store.condition:
            record = self._records[job_id]
            if record["dispatch_count"] or not record["dispatch_attempt_reserved"]:
                raise RuntimeError("duplicate restore dispatch forbidden")
            self._advance(
                record,
                dispatch_count=1,
                status="awaiting_late_readback",
                poll_allowed=True,
                late_completion_disposition="poll_exact_job_without_redispatch",
            )

    def reserve_dispatch(self, job_id):
        with self.store.condition:
            record = self._records[job_id]
            if record["dispatch_attempt_reserved"] or record["dispatch_count"]:
                raise RuntimeError("duplicate restore dispatch forbidden")
            if record["status"] != "created" or record["guard"] is None:
                raise RuntimeError("dispatch reservation precondition rejected")
            self._advance(
                record,
                status="dispatch_uncertain",
                snapshot_source="durable_dispatch_reservation",
                dispatch_attempt_reserved=True,
                poll_allowed=True,
                late_completion_disposition="poll_exact_job_without_redispatch",
            )

    def snapshot_unknown(self, job_id, source):
        if source == "cancellation_after_dispatch":
            self.request_cancellation(job_id)
            return
        if source not in {"request_timeout", "transport_loss"}:
            raise RuntimeError("unknown snapshot source rejected")
        with self.store.condition:
            record = self._records[job_id]
            if record["dispatch_count"] != 1 or record["status"] != "awaiting_late_readback":
                raise RuntimeError("unknown snapshot transition rejected")
            self._advance(record, snapshot_source=source)

    def complete_synchronous(self, job_id, outcome):
        with self.store.condition:
            record = self._records[job_id]
            if record["status"] in {"terminal", "terminal_not_dispatched"}:
                return
            source = {
                "succeeded": "official_sdk_readback",
                "failed_unchanged": "official_sdk_readback",
                "failed_unknown": "official_sdk_failure",
                "confirmation_consume_rejected": "confirmation_cas",
                "target_guard_rejected": "target_guard",
            }[outcome]
            dispatched = record["dispatch_count"] == 1
            terminal_event_id, terminal_event_digest = self._terminal_event(record, source)
            guard = record["guard"]
            guard_token = record["guard_token"]
            cleanup_binding = {
                "job_id": record["job_id"],
                "job_generation": record["job_generation"],
                "operation_binding_sha256": record["operation_binding_sha256"],
                "terminal_event_id": terminal_event_id,
                "guard_owner": guard_token["guard_owner"],
                "guard_generation": guard_token["guard_generation"],
            }
            cleanup_pending = self.store.cleanup_store.prepare(
                binding=cleanup_binding,
                phase="synchronous_result",
            )
            self._advance(
                record,
                status="cleanup_pending",
                cleanup_pending=cleanup_pending,
                cleanup_terminal_plan={
                    "outcome": outcome,
                    "status": "terminal" if dispatched else "terminal_not_dispatched",
                    "snapshot_source": source,
                    "terminal_source": source,
                    "released_handle_owner": (
                        (
                            "released_after_terminal_unknown"
                            if outcome == "failed_unknown"
                            else "released_after_terminal_readback"
                        )
                        if dispatched
                        else "released_before_dispatch"
                    ),
                    "late_completion_disposition": "not_applicable",
                    "dispatch_count": record["dispatch_count"],
                    "terminal_event_id": terminal_event_id,
                    "terminal_event_digest_sha256": terminal_event_digest,
                    "cancellation_requested": False,
                    "cancellation_effective": False,
                    "cancellation_disposition": "not_requested",
                },
            )
            cleanup_record = _release_guard_preserving_primary(
                self.store.cleanup_store,
                binding=cleanup_binding,
                phase="synchronous_result",
                guard=guard,
                guard_token=guard_token,
                prepared=cleanup_pending,
            )
            self._finalize_cleanup(record, cleanup_record)

    def request_cancellation(self, job_id):
        with self.store.condition:
            record = self._records[job_id]
            if record["status"] in {"terminal", "terminal_not_dispatched"}:
                return {
                    "requested": True,
                    "effective": False,
                    "disposition": "ignored_after_terminal",
                }
            if record["status"] == "readback_in_progress":
                intent = self._cancellation_intent_for_active_claim(record)
                existing = self.store.cancellation_intents.get(job_id)
                if existing is not None and existing != intent:
                    raise RuntimeError("cancellation intent binding rejected")
                self.store.cancellation_intents[job_id] = intent
                return {
                    "requested": True,
                    "effective": False,
                    "disposition": "requested_after_dispatch_operation_continues",
                }
            if record["dispatch_attempt_reserved"]:
                if not record["cancellation_requested"]:
                    self._advance(
                        record,
                        snapshot_source="cancellation_after_dispatch",
                        cancellation_disposition=("requested_after_dispatch_operation_continues"),
                        cancellation_requested=True,
                        cancellation_effective=False,
                    )
                return {
                    "requested": True,
                    "effective": False,
                    "disposition": "requested_after_dispatch_operation_continues",
                }
            if record["dispatch_count"] == 0:
                guard = record["guard"]
                guard_token = record["guard_token"]
                if guard is None or guard_token is None:
                    raise RuntimeError("cancellation guard ownership rejected")
                event_id, event_digest = self._terminal_event(
                    record,
                    "cancellation_before_dispatch",
                )
                cleanup_binding = {
                    "job_id": record["job_id"],
                    "job_generation": record["job_generation"],
                    "operation_binding_sha256": record["operation_binding_sha256"],
                    "terminal_event_id": event_id,
                    "guard_owner": guard_token["guard_owner"],
                    "guard_generation": guard_token["guard_generation"],
                }
                cleanup_pending = self.store.cleanup_store.prepare(
                    binding=cleanup_binding,
                    phase="cancellation_before_dispatch",
                )
                self._advance(
                    record,
                    status="cleanup_pending",
                    cleanup_pending=cleanup_pending,
                    cleanup_terminal_plan={
                        "outcome": "preflight_rejected",
                        "status": "terminal_not_dispatched",
                        "snapshot_source": "cancellation_before_dispatch",
                        "terminal_source": "cancellation_before_dispatch",
                        "released_handle_owner": "released_before_dispatch",
                        "late_completion_disposition": "not_applicable",
                        "dispatch_count": 0,
                        "terminal_event_id": event_id,
                        "terminal_event_digest_sha256": event_digest,
                        "cancellation_requested": True,
                        "cancellation_effective": True,
                        "cancellation_disposition": "honored_before_dispatch",
                    },
                )
                cleanup_record = _release_guard_preserving_primary(
                    self.store.cleanup_store,
                    binding=cleanup_binding,
                    phase="cancellation_before_dispatch",
                    guard=guard,
                    guard_token=guard_token,
                    prepared=cleanup_pending,
                )
                self._finalize_cleanup(record, cleanup_record)
                return {
                    "requested": True,
                    "effective": True,
                    "disposition": "honored_before_dispatch",
                }
            if not record["cancellation_requested"]:
                self._advance(
                    record,
                    snapshot_source="cancellation_after_dispatch",
                    cancellation_disposition="requested_after_dispatch_operation_continues",
                    cancellation_requested=True,
                    cancellation_effective=False,
                )
            return {
                "requested": True,
                "effective": False,
                "disposition": "requested_after_dispatch_operation_continues",
            }

    def _cancellation_intent_for_active_claim(self, record):
        binding = {
            "job_id": record["job_id"],
            "job_generation": record["job_generation"],
            "operation_binding_sha256": record["operation_binding_sha256"],
            "claim_owner": record["readback_claim_owner"],
            "claim_generation": record["readback_claim_generation"],
            "fence_revision": record["readback_claim_fence_revision"],
            "registry_epoch": record["readback_claim_registry_epoch"],
        }
        canonical = json.dumps(binding, separators=(",", ":"), sort_keys=True).encode()
        intent_id = (
            "rci1-"
            + hmac.new(
                self.store.claim_owner_secret,
                b"restore-cancellation-intent-v1\0" + canonical,
                hashlib.sha256,
            ).hexdigest()
        )
        return {
            "intent_version": "1.0",
            "intent_id": intent_id,
            **binding,
            "intent_revision": 1,
            "requested": True,
            "effective": False,
            "disposition": "requested_after_dispatch_operation_continues",
        }

    def make_completion_event(self, job_id, completion_receipt):
        with self.store.condition:
            record = self._records[job_id]
            if record["status"] == "terminal_not_dispatched":
                raise RuntimeError("terminal record is immutable")
            if record["completion_event"] is None:
                record["completion_event"] = self._completion_event_for_record(
                    record,
                    completion_receipt,
                )
            return dict(record["completion_event"])

    def _claim_owner_for(
        self,
        record,
        event,
        claim_generation,
        claimed_revision,
        registry_epoch,
    ):
        binding = {
            "job_id": record["job_id"],
            "job_generation": record["job_generation"],
            "operation_binding_sha256": record["operation_binding_sha256"],
            "event_id": event["event_id"],
            "claim_generation": claim_generation,
            "claimed_record_revision": claimed_revision,
            "registry_epoch": registry_epoch,
            "retained_guard_owner": record["retained_guard_owner"],
            "retained_guard_generation": record["retained_guard_generation"],
        }
        canonical = json.dumps(binding, separators=(",", ":"), sort_keys=True).encode()
        return (
            "rco1-"
            + hmac.new(
                self.store.claim_owner_secret,
                b"restore-readback-claim-v1\0" + canonical,
                hashlib.sha256,
            ).hexdigest()
        )

    def claim_late_readback(self, event):
        claimed_job_id = event.get("job_id")
        with self.store.condition:
            record = self._records[claimed_job_id]
            if event.get("event_sequence") != record["event_sequence"] + 1:
                if (
                    record["status"] == "readback_in_progress"
                    and event == record["completion_event"]
                ):
                    while record["status"] == "readback_in_progress":
                        self.store.condition.wait(timeout=2)
                    return None
                if record["status"] == "terminal" and event == record["completion_event"]:
                    return None
                raise RuntimeError("completion event sequence rejected")
            if event.get("expected_revision") != record["record_revision"]:
                raise RuntimeError("completion event revision rejected")
            expected = self._completion_event_for_digest(
                record,
                event.get("completion_receipt_sha256"),
            )
            if event != expected or event.get(
                "event_digest_sha256"
            ) != self.digest_completion_event(event):
                raise RuntimeError("completion event identity rejected")
            if record["status"] not in {"dispatch_uncertain", "awaiting_late_readback"}:
                raise RuntimeError("completion event state rejected")
            claimed_revision = record["record_revision"]
            claim_generation = self.store.reserve_claim_generation()
            claim_owner = self._claim_owner_for(
                record,
                event,
                claim_generation,
                claimed_revision,
                self.generation,
            )
            fence_revision = claimed_revision + 1
            record["completion_event"] = dict(event)
            self._advance(
                record,
                status="readback_in_progress",
                event_sequence=event["event_sequence"],
                readback_claim_owner=claim_owner,
                readback_claim_generation=claim_generation,
                readback_claim_record_revision=claimed_revision,
                readback_claim_fence_revision=fence_revision,
                readback_claim_registry_epoch=self.generation,
            )
            assert record["record_revision"] == fence_revision
            return {
                "claim_version": "1.0",
                "job_id": record["job_id"],
                "job_generation": record["job_generation"],
                "event_id": event["event_id"],
                "operation_binding_sha256": record["operation_binding_sha256"],
                "claim_owner": claim_owner,
                "claim_generation": claim_generation,
                "claimed_record_revision": claimed_revision,
                "fence_revision": fence_revision,
                "registry_epoch": self.generation,
                "retained_guard_owner": record["retained_guard_owner"],
                "retained_guard_generation": record["retained_guard_generation"],
            }

    @staticmethod
    def _receipt_is_canonical(receipt):
        return _completion_receipt_is_canonical(receipt)

    def _classify_completion(self, record, actual_receipt):
        return _classify_guarded_completion(
            before_receipt=record["before_receipt"],
            actual_receipt=actual_receipt,
            approved_recovery_receipt=record["approved_recovery_receipt"],
            approved_target_identity=record["approved_target_identity"],
        )

    def _claim_fence_matches(self, record, claim, event):
        expected_owner = self._claim_owner_for(
            record,
            event,
            claim.get("claim_generation"),
            claim.get("claimed_record_revision"),
            claim.get("registry_epoch"),
        )
        return (
            claim.get("claim_version") == "1.0"
            and record["status"] == "readback_in_progress"
            and record["job_id"] == claim.get("job_id")
            and record["job_generation"] == claim.get("job_generation")
            and record["operation_binding_sha256"] == claim.get("operation_binding_sha256")
            and event["event_id"] == claim.get("event_id")
            and record["record_revision"] == claim.get("fence_revision")
            and record["readback_claim_owner"] == claim.get("claim_owner")
            and record["readback_claim_generation"] == claim.get("claim_generation")
            and record["readback_claim_record_revision"] == claim.get("claimed_record_revision")
            and record["readback_claim_fence_revision"] == claim.get("fence_revision")
            and record["readback_claim_registry_epoch"] == claim.get("registry_epoch")
            and claim.get("registry_epoch") == self.generation
            and claim.get("fence_revision") == claim.get("claimed_record_revision") + 1
            and record["retained_guard_owner"] == claim.get("retained_guard_owner")
            and record["retained_guard_generation"] == claim.get("retained_guard_generation")
            and claim.get("claim_owner") == expected_owner
        )

    def abandon_late_readback(self, claim):
        with self.store.condition:
            record = self._records[claim["job_id"]]
            event = record["completion_event"]
            if event is None or not self._claim_fence_matches(record, claim, event):
                raise RuntimeError("late completion fence rejected")
            guard = record["guard"]
            guard_token = record["guard_token"]
            if (
                guard is None
                or guard_token is None
                or not guard.owns(guard_token)
                or guard_token["guard_owner"] != claim["retained_guard_owner"]
                or guard_token["guard_generation"] != claim["retained_guard_generation"]
            ):
                raise RuntimeError("late completion fence rejected")
            cancellation_intent = self.store.cancellation_intents.get(record["job_id"])
            if cancellation_intent is not None and cancellation_intent != (
                self._cancellation_intent_for_active_claim(record)
            ):
                raise RuntimeError("cancellation intent binding rejected")
            cleanup_binding = {
                "job_id": record["job_id"],
                "job_generation": record["job_generation"],
                "operation_binding_sha256": record["operation_binding_sha256"],
                "terminal_event_id": event["event_id"],
                "guard_owner": guard_token["guard_owner"],
                "guard_generation": guard_token["guard_generation"],
            }
            cleanup_pending = self.store.cleanup_store.prepare(
                binding=cleanup_binding,
                phase="late_readback_claim_abandoned",
            )
            self._advance(
                record,
                advance_event=False,
                status="cleanup_pending",
                cleanup_pending=cleanup_pending,
                cleanup_terminal_plan={
                    "outcome": "failed_unknown",
                    "status": "terminal",
                    "snapshot_source": "readback_owner_lost",
                    "terminal_source": "readback_owner_lost",
                    "released_handle_owner": "released_after_terminal_unknown",
                    "late_completion_disposition": "not_applicable",
                    "dispatch_count": 1,
                    "terminal_event_id": event["event_id"],
                    "terminal_event_digest_sha256": event["event_digest_sha256"],
                    "cancellation_requested": cancellation_intent is not None,
                    "cancellation_effective": False,
                    "cancellation_disposition": (
                        "requested_after_dispatch_operation_continues"
                        if cancellation_intent is not None
                        else record["cancellation_disposition"]
                    ),
                },
            )
            cleanup_record = _release_guard_preserving_primary(
                self.store.cleanup_store,
                binding=cleanup_binding,
                phase="late_readback_claim_abandoned",
                guard=guard,
                guard_token=guard_token,
                prepared=cleanup_pending,
            )
            self._finalize_cleanup(record, cleanup_record)

    def complete_guarded_readback(self, claim, actual_receipt):
        with self.store.condition:
            record = self._records[claim["job_id"]]
            event = record["completion_event"]
            if event is None or not self._claim_fence_matches(record, claim, event):
                raise RuntimeError("late completion fence rejected")
            guard = record["guard"]
            guard_token = record["guard_token"]
            if (
                guard is None
                or guard_token is None
                or not guard.owns(guard_token)
                or guard_token["guard_owner"] != claim["retained_guard_owner"]
                or guard_token["guard_generation"] != claim["retained_guard_generation"]
            ):
                raise RuntimeError("late completion fence rejected")
            guard.recapture(guard_token)
            if not guard.checkpoint_identity(guard_token, "late_readback_commit"):
                raise RuntimeError("late completion fence rejected")
            if not self._claim_fence_matches(record, claim, event):
                raise RuntimeError("late completion fence rejected")
            cancellation_intent = self.store.cancellation_intents.get(record["job_id"])
            if cancellation_intent is not None and cancellation_intent != (
                self._cancellation_intent_for_active_claim(record)
            ):
                raise RuntimeError("cancellation intent binding rejected")
            try:
                _, actual_receipt_digest = _completion_receipt_binding(actual_receipt)
                outcome = self._classify_completion(record, actual_receipt)
            except Exception:
                actual_receipt_digest = None
                outcome = "failed_unknown"
            if actual_receipt_digest != event["completion_receipt_sha256"]:
                outcome = "failed_unknown"
            cleanup_binding = {
                "job_id": record["job_id"],
                "job_generation": record["job_generation"],
                "operation_binding_sha256": record["operation_binding_sha256"],
                "terminal_event_id": event["event_id"],
                "guard_owner": guard_token["guard_owner"],
                "guard_generation": guard_token["guard_generation"],
            }
            cleanup_pending = self.store.cleanup_store.prepare(
                binding=cleanup_binding,
                phase="late_readback_terminal",
            )
            self._advance(
                record,
                advance_event=False,
                status="cleanup_pending",
                cleanup_pending=cleanup_pending,
                cleanup_terminal_plan={
                    "outcome": outcome,
                    "status": "terminal",
                    "snapshot_source": (
                        "late_official_sdk_readback"
                        if outcome in {"succeeded", "failed_unchanged"}
                        else "official_sdk_failure"
                    ),
                    "terminal_source": (
                        "official_sdk_readback"
                        if outcome in {"succeeded", "failed_unchanged"}
                        else "official_sdk_failure"
                    ),
                    "released_handle_owner": (
                        "released_after_terminal_readback"
                        if outcome in {"succeeded", "failed_unchanged"}
                        else "released_after_terminal_unknown"
                    ),
                    "late_completion_disposition": (
                        "terminalized_by_official_sdk_readback"
                        if outcome in {"succeeded", "failed_unchanged"}
                        else "not_applicable"
                    ),
                    "dispatch_count": 1,
                    "terminal_event_id": event["event_id"],
                    "terminal_event_digest_sha256": event["event_digest_sha256"],
                    "cancellation_requested": cancellation_intent is not None,
                    "cancellation_effective": False,
                    "cancellation_disposition": (
                        "requested_after_dispatch_operation_continues"
                        if cancellation_intent is not None
                        else record["cancellation_disposition"]
                    ),
                },
            )
            cleanup_record = _release_guard_preserving_primary(
                self.store.cleanup_store,
                binding={
                    "job_id": record["job_id"],
                    "job_generation": record["job_generation"],
                    "operation_binding_sha256": record["operation_binding_sha256"],
                    "terminal_event_id": event["event_id"],
                },
                phase="late_readback_terminal",
                guard=guard,
                guard_token=guard_token,
                prepared=cleanup_pending,
            )
            self._finalize_cleanup(record, cleanup_record)
            return outcome

    def audit_context(self, job_id):
        with self.store.condition:
            record = self._records[job_id]
            return {
                "before_receipt": json.loads(json.dumps(record["before_receipt"])),
                "approved_recovery_receipt": json.loads(
                    json.dumps(record["approved_recovery_receipt"])
                ),
                "approved_target_identity": dict(record["approved_target_identity"]),
                "terminal_outcome": record["terminal_outcome"],
            }

    def descriptor(self, job_id):
        with self.store.condition:
            record = self._records[job_id]
            if record["status"] == "cleanup_pending" or record.get("cleanup_commit_pending"):
                self._reconcile_cleanup_record(record)
            if record["status"] == "readback_in_progress":
                while record["status"] == "readback_in_progress":
                    self.store.condition.wait(timeout=2)
            return {key: value for key, value in record.items() if key not in self._INTERNAL_FIELDS}

    def poll(self, job_id):
        with self.store.condition:
            self.poll_count += 1
        return self.descriptor(job_id)

    def publish_descriptor(self, snapshot):
        current = self.descriptor(snapshot["job_id"])
        for member in (
            "job_generation",
            "operation_binding_sha256",
            "record_revision",
            "event_sequence",
            "status",
        ):
            if snapshot.get(member) != current[member]:
                raise RuntimeError("stale job snapshot rejected")
        return dict(snapshot)

    def tombstone(self, job_id):
        with self.store.condition:
            return dict(self.store.tombstones[job_id])

    def cleanup_record(self, job_id):
        with self.store.condition:
            record = self._records[job_id]
            completion_event = record["completion_event"]
            cleanup_binding = {
                "job_id": record["job_id"],
                "job_generation": record["job_generation"],
                "operation_binding_sha256": record["operation_binding_sha256"],
                "terminal_event_id": (
                    completion_event["event_id"]
                    if completion_event is not None
                    else record["terminal_event_id"]
                ),
                "guard_owner": record["retained_guard_owner"],
                "guard_generation": record["retained_guard_generation"],
            }
            canonical = json.dumps(
                cleanup_binding,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            expected_digest = hashlib.sha256(canonical).hexdigest()
            matches = [
                item
                for item in self.store.cleanup_store.records
                if item["cleanup_binding_sha256"] == expected_digest
            ]
            return dict(matches[-1])


class FakeAsyncRestoreWorkflow:
    def __init__(self, store, sdk, guard, jobs):
        self.store = store
        self.sdk = sdk
        self.guard = guard
        self.jobs = jobs

    def start(self, request, outcome):
        ticket = self.store.trusted_lookup_and_compare(request)
        assert ticket is not None
        job_id = self.jobs.create_before_host_connection(request, ticket, self.store.resolver)
        if outcome == "cancellation_before_dispatch":
            guard_token = self.guard.open()
            self.jobs.retain_handles(job_id, self.guard, guard_token)
            self.jobs.cancel_before_dispatch(job_id)
            result = _result("preflight_rejected")
            result["context"]["failed_precondition"] = "cancellation_requested_before_dispatch"
            result["context"]["job"] = self.jobs.descriptor(job_id)
            return result

        guard_token = self.guard.open()
        before_receipt = self.sdk.capture_before()
        self.guard.recapture(guard_token)
        self.jobs.retain_handles(job_id, self.guard, guard_token)
        self.jobs.record_before_receipt(job_id, before_receipt)
        assert self.store.cas_consume(
            ticket,
            request,
            guarded_target_binding=self.guard.cas_binding(
                guard_token,
                request,
                self.store.resolver,
            ),
        )
        self.jobs.reserve_dispatch(job_id)
        self.sdk.dispatch_restore(self.guard.dispatch_capability(guard_token))
        self.jobs.mark_dispatched(job_id)
        self.jobs.snapshot_unknown(job_id, outcome)
        state = "timed_out" if outcome == "request_timeout" else "indeterminate"
        result = _result(state)
        result["context"]["before_receipt"] = before_receipt
        result["context"]["job"] = self.jobs.descriptor(job_id)
        return result

    def poll(self, job_id, *, late_success=False):
        descriptor = self.jobs.poll(job_id)
        if late_success and descriptor["status"] in {
            "dispatch_uncertain",
            "awaiting_late_readback",
        }:
            for attempt in range(2):
                event = self.jobs.make_completion_event(
                    job_id,
                    self.sdk.completion_receipt(),
                )
                try:
                    claim = self.jobs.claim_late_readback(event)
                    break
                except RuntimeError as error:
                    if attempt or not str(error).startswith(
                        ("completion event sequence", "completion event revision")
                    ):
                        raise
                    with self.jobs.store.condition:
                        self.jobs._records[job_id]["completion_event"] = None
            if claim is None:
                terminal = self.jobs.descriptor(job_id)
                audit = self.jobs.audit_context(job_id)
                result = _result(audit["terminal_outcome"])
                result["context"]["job"] = terminal
                return result
            try:
                actual_receipt = self.sdk.readback_after()
            except Exception:
                actual_receipt = None
            except BaseException:
                try:
                    self.jobs.abandon_late_readback(claim)
                except Exception:
                    pass
                raise
            outcome = self.jobs.complete_guarded_readback(claim, actual_receipt)
            audit = self.jobs.audit_context(job_id)
            result = _result(outcome)
            result["context"]["job"] = self.jobs.descriptor(job_id)
            result["context"]["before_receipt"] = audit["before_receipt"]
            if outcome == "succeeded":
                result["context"]["approved_recovery_receipt"] = audit["approved_recovery_receipt"]
                result["context"]["approved_target_identity"] = audit["approved_target_identity"]
                result["context"]["after_receipt"] = actual_receipt
            elif outcome == "failed_unchanged":
                result["context"]["after_receipt"] = actual_receipt
            return result
        return descriptor


def test_restore_contract_is_design_only_and_fail_closed():
    contract = _contract()

    assert contract["contract_version"] == "2.0"
    assert contract["status"] == "proposed-design-only"
    assert contract["implementation_authorized"] is False
    assert contract["operation"] == {
        "name": "restore_scene",
        "destructive": True,
        "idempotent": False,
        "single_use": True,
        "replay_allowed": False,
        "route": "official_sdk_only",
    }
    assert contract["prohibited_routes"] == ["arbitrary_hsl", "python", "ui_automation"]


def test_restore_request_requires_trusted_vdf_receipt_and_operator_confirmation():
    validator = _validator("input_schema")
    validator.validate(_request())

    for missing in (
        "request_id",
        "trusted_root",
        "file_path",
        "recovery_receipt",
        "operator_confirmation",
    ):
        invalid = _request()
        invalid.pop(missing)
        with pytest.raises(ValidationError):
            validator.validate(invalid)

    for file_path in (
        "C:/operator-approved/recovery/marked_take.bvh",
        "C:/operator-approved/recovery/marked_take.vdf/extra",
    ):
        with pytest.raises(ValidationError):
            validator.validate(_request(file_path=file_path))

    with pytest.raises(ValidationError):
        validator.validate(_request(trusted_root="C:/operator-approved/recovery:trailing-garbage"))


def test_restore_request_binds_the_complete_prior_recovery_receipt():
    validator = _validator("input_schema")
    receipt = _request()["recovery_receipt"]

    for missing in (
        "receipt_version",
        "file_name",
        "file_size_bytes",
        "sha256",
        "active_scene_changed",
    ):
        invalid_receipt = dict(receipt)
        invalid_receipt.pop(missing)
        with pytest.raises(ValidationError):
            validator.validate(_request(recovery_receipt=invalid_receipt))

    for field, value in (
        ("receipt_version", 2),
        ("file_size_bytes", 0),
        ("sha256", "not-a-digest"),
        ("active_scene_changed", True),
    ):
        invalid_receipt = dict(receipt)
        invalid_receipt[field] = value
        with pytest.raises(ValidationError):
            validator.validate(_request(recovery_receipt=invalid_receipt))


def test_restore_request_rejects_one_byte_over_the_approved_resource_ceiling():
    limit = _contract()["resource_limits"]["approved_file_size_max_bytes"]
    validator = _validator("input_schema")
    at_limit = dict(_request()["recovery_receipt"], file_size_bytes=limit)
    over_limit = dict(_request()["recovery_receipt"], file_size_bytes=limit + 1)

    validator.validate(_request(recovery_receipt=at_limit))
    with pytest.raises(ValidationError):
        validator.validate(_request(recovery_receipt=over_limit))

    assert _contract()["resource_limits"] == {
        "approved_file_size_max_bytes": 8_589_934_592,
        "filesystem_hash_chunk_size_bytes": 65_536,
        "sdk_readback_receipt_max_bytes": 65_536,
        "size_source": "guarded_target_handle",
        "oversize_disposition": "reject_before_hashing_or_buffering",
        "file_hashing": "streaming_sha256_exact_size",
        "sdk_readback": "bounded_canonical_receipt_stream",
    }


def test_sdk_completion_receipt_digest_streams_and_rejects_limit_plus_one():
    receipt = _approved_after_receipt(_request(), _resolver())
    chunk_sizes = []
    size, digest = _completion_receipt_binding(
        receipt,
        max_bytes=_contract()["resource_limits"]["sdk_readback_receipt_max_bytes"],
        chunk_size=7,
        on_chunk=chunk_sizes.append,
    )

    assert size == sum(chunk_sizes)
    assert len(chunk_sizes) > 1
    assert digest == _completion_receipt_binding(receipt)[1]
    with pytest.raises(ValueError, match="resource limit"):
        _completion_receipt_binding(receipt, max_bytes=size - 1, chunk_size=7)


def test_restore_request_rejects_alternate_data_stream_syntax():
    validator = _validator("input_schema")

    with pytest.raises(ValidationError):
        validator.validate(
            _request(file_path=("C:/operator-approved/recovery/primary.vdf:marked_take.vdf"))
        )


def test_restore_request_has_no_code_or_ui_escape_hatch():
    properties = set(_contract()["input_schema"]["properties"])

    assert properties == {
        "request_id",
        "trusted_root",
        "file_path",
        "recovery_receipt",
        "operator_confirmation",
    }
    assert not properties.intersection(
        {"hsl", "hsl_source", "script_path", "python", "python_source", "ui_action"}
    )


@pytest.mark.parametrize(
    "state",
    (
        "preflight_rejected",
        "succeeded",
        "failed_unchanged",
        "confirmation_consume_rejected",
        "target_guard_rejected",
        "failed_unknown",
        "timed_out",
        "indeterminate",
    ),
)
def test_restore_result_models_every_terminal_state_without_replay(state):
    result = _result(state)

    _validate_result(result)
    assert result["context"]["replay_allowed"] is False
    before = result["context"]["before_receipt"]
    assert before is None or before["active_scene_observed_via"] == "official_sdk"
    after = result["context"]["after_receipt"]
    assert after is None or after["active_scene_observed_via"] == "official_sdk"


@pytest.mark.parametrize(
    "state",
    (
        "preflight_rejected",
        "confirmation_consume_rejected",
        "target_guard_rejected",
        "succeeded",
        "failed_unchanged",
        "failed_unknown",
        "timed_out",
        "indeterminate",
    ),
)
def test_every_result_rejects_a_job_bound_to_another_request(state):
    mismatched = _result(state)
    mismatched["context"]["job"]["request_id"] = "restore-0002"

    with pytest.raises(ValidationError, match="job/request_id"):
        _validate_result(mismatched)


@pytest.mark.parametrize(
    "failed_precondition",
    (
        "canonical_target_is_contained_by_canonical_trusted_root",
        "target_is_regular_vdf_without_symlink_or_reparse_escape",
        "target_basename_size_and_sha256_match_recovery_receipt",
        "recovery_receipt_reports_active_scene_unchanged",
        "operator_confirmation_is_fresh_exact_scope_and_unused",
    ),
)
def test_each_precondition_can_reject_before_host_connection(failed_precondition):
    result = _result("preflight_rejected")
    result["context"]["failed_precondition"] = failed_precondition

    _validate_result(result)
    assert result["context"]["dispatch_performed"] is False
    assert result["context"]["host_connection_performed"] is False
    assert result["context"]["confirmation_consumed"] is False
    assert result["context"]["before_receipt"] is None
    assert result["context"]["after_receipt"] is None


def test_timeout_and_indeterminate_cannot_claim_unchanged_or_verified_effects():
    validator = _validator("private_audit_result_schema")

    for state in ("timed_out", "indeterminate"):
        for effect in ("unchanged", "verified"):
            invalid = _result(state)
            invalid["context"]["effect"] = effect
            with pytest.raises(ValidationError):
                validator.validate(invalid)


def test_verified_result_rejects_identical_before_and_after_scene():
    invalid = _result("succeeded")
    invalid["context"]["after_receipt"] = dict(invalid["context"]["before_receipt"])

    with pytest.raises(ValidationError):
        _validate_result(invalid)


def test_verified_result_rejects_an_unapproved_after_scene():
    invalid = _result("succeeded")
    invalid["context"]["after_receipt"] = _scene_receipt("other_scene.vdf", "d" * 64, "d" * 64)

    with pytest.raises(ValidationError):
        _validate_result(invalid)


def test_unchanged_result_requires_official_sdk_readback():
    invalid = _result("failed_unchanged")
    invalid["context"]["readback_performed"] = False
    invalid["context"]["after_receipt"] = None

    with pytest.raises(ValidationError):
        _validate_result(invalid)


def test_unchanged_result_rejects_different_before_and_after_scene():
    invalid = _result("failed_unchanged")
    invalid["context"]["after_receipt"] = _scene_receipt("different_scene.vdf", "d" * 64, "d" * 64)

    with pytest.raises(ValidationError):
        _validate_result(invalid)


@pytest.mark.parametrize(
    "mutation",
    (
        {"request_id": "restore-0002"},
        {"trusted_root": "D:/different-approved-root"},
        {"file_path": "C:/operator-approved/recovery/different_take.vdf"},
        {
            "recovery_receipt": {
                "receipt_version": 1,
                "file_name": "different_take.vdf",
                "file_size_bytes": 8192,
                "sha256": "d" * 64,
                "active_scene_changed": False,
            }
        },
    ),
)
def test_confirmation_cannot_be_reused_across_request_root_path_or_receipt(mutation):
    original = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(original, authenticated=True)
    changed = _request(**mutation)

    assert store.trusted_lookup_and_compare(original) is not None
    assert store.trusted_lookup_and_compare(changed) is None


def test_confirmation_rejects_expired_future_and_consumed_records():
    request = _request()

    expired = FakeTrustedConfirmationStore()
    expired.issue(request, authenticated=True, now=NOW_EPOCH_SECONDS - 301)
    future = FakeTrustedConfirmationStore()
    future.issue(request, authenticated=True, now=NOW_EPOCH_SECONDS + 60)
    consumed = FakeTrustedConfirmationStore()
    consumed.issue(request, authenticated=True)
    ticket = consumed.trusted_lookup_and_compare(request)
    assert ticket is not None
    assert consumed.cas_consume(
        ticket,
        request,
        guarded_target_binding=_trusted_target_binding(request, consumed.resolver),
    )

    assert expired.trusted_lookup_and_compare(request) is None
    assert future.trusted_lookup_and_compare(request) is None
    assert consumed.trusted_lookup_and_compare(request) is None


def test_confirmation_expiring_between_lookup_and_consume_is_rejected_atomically():
    request = _request()
    trusted_clock = FakeTrustedClock()
    store = FakeTrustedConfirmationStore(trusted_clock=trusted_clock)
    store.issue(request, authenticated=True)
    ticket = store.trusted_lookup_and_compare(request)

    assert ticket is not None
    trusted_clock.advance(271)
    assert not store.cas_consume(
        ticket,
        request,
        guarded_target_binding=_trusted_target_binding(request, store.resolver),
    )
    assert store.consume_count == 0
    assert store.trusted_lookup_and_compare(request) is None


def test_confirmation_cas_rejects_a_changed_guarded_target_body_binding():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    ticket = store.trusted_lookup_and_compare(request)
    guard = FakeGuardedTargetBoundary()
    guard_token = guard.open()
    guarded_binding = guard.cas_binding(guard_token, request, store.resolver)
    guarded_binding["sha256"] = "d" * 64

    try:
        assert not store.cas_consume(
            ticket,
            request,
            guarded_target_binding=guarded_binding,
        )
        assert store.consume_count == 0
    finally:
        guard.release(guard_token)


def test_caller_owned_confirmation_dict_cannot_authorize():
    request = _request()
    store = FakeTrustedConfirmationStore()

    with pytest.raises(PermissionError):
        store.issue(request, authenticated=False)
    assert store.trusted_lookup_and_compare(request) is None


def test_consumed_confirmation_id_cannot_be_reissued_or_resurrected():
    request = _request()
    store = FakeTrustedConfirmationStore()
    authority = _contract()["confirmation_authority"]
    assert authority["issuance_write"] == "atomic_insert_if_absent"
    assert authority["confirmation_id_reuse"] == "forbidden_forever"
    assert authority["reauthorization_requires"] == "new_confirmation_id"
    assert authority["record_retention"] == "durable_tombstone_after_expiry_or_consumption"
    store.issue(request, authenticated=True)
    ticket = store.trusted_lookup_and_compare(request)
    assert ticket is not None
    assert store.cas_consume(
        ticket,
        request,
        guarded_target_binding=_trusted_target_binding(request, store.resolver),
    )

    with pytest.raises(ValueError, match="confirmation ID is immutable and nonreusable"):
        store.issue(request, authenticated=True)
    assert store.trusted_lookup_and_compare(request) is None


def test_consumed_confirmation_id_tombstone_survives_authority_restart():
    request = _request()
    durable_store = FakeDurableConfirmationStore()
    original = FakeTrustedConfirmationStore(
        durable_store=durable_store,
        authority_generation="0000000000000001",
    )
    original.issue(request, authenticated=True)
    ticket = original.trusted_lookup_and_compare(request)
    assert ticket is not None
    assert original.cas_consume(
        ticket,
        request,
        guarded_target_binding=_trusted_target_binding(request, original.resolver),
    )

    restarted = FakeTrustedConfirmationStore(
        durable_store=durable_store,
        authority_generation="0000000000000002",
    )
    with pytest.raises(ValueError, match="confirmation ID is immutable and nonreusable"):
        restarted.issue(request, authenticated=True)

    confirmation_id = request["operator_confirmation"]["confirmation_id"]
    assert restarted.trusted_lookup_and_compare(request) is None
    assert durable_store.tombstone(confirmation_id) == {
        "confirmation_id": confirmation_id,
        "permanent": True,
    }
    assert durable_store.consume_count == 1


def test_expired_confirmation_id_tombstone_survives_authority_restart():
    request = _request()
    durable_store = FakeDurableConfirmationStore()
    original = FakeTrustedConfirmationStore(durable_store=durable_store)
    original.issue(request, authenticated=True, now=NOW_EPOCH_SECONDS - 301)
    assert original.trusted_lookup_and_compare(request) is None

    restarted = FakeTrustedConfirmationStore(
        durable_store=durable_store,
        authority_generation="0000000000000002",
    )
    with pytest.raises(ValueError, match="confirmation ID is immutable and nonreusable"):
        restarted.issue(request, authenticated=True)

    confirmation_id = request["operator_confirmation"]["confirmation_id"]
    assert restarted.trusted_lookup_and_compare(request) is None
    assert durable_store.tombstone(confirmation_id)["permanent"] is True
    assert durable_store.consume_count == 0


def test_concurrent_authorities_atomically_issue_one_permanent_confirmation_id():
    request = _request()
    durable_store = FakeDurableConfirmationStore()
    authorities = (
        FakeTrustedConfirmationStore(
            durable_store=durable_store,
            authority_generation="0000000000000001",
        ),
        FakeTrustedConfirmationStore(
            durable_store=durable_store,
            authority_generation="0000000000000002",
        ),
    )
    barrier = Barrier(2)

    def issue(authority):
        barrier.wait()
        try:
            authority.issue(request, authenticated=True)
        except ValueError as error:
            return str(error)
        return "issued"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(issue, authorities))

    assert sorted(outcomes) == [
        "confirmation ID is immutable and nonreusable",
        "issued",
    ]
    confirmation_id = request["operator_confirmation"]["confirmation_id"]
    assert list(durable_store.records) == [confirmation_id]
    assert list(durable_store.tombstones) == [confirmation_id]
    assert durable_store.tombstone(confirmation_id)["permanent"] is True


def test_concurrent_restore_workflows_consume_and_dispatch_exactly_once():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary()
    workflow = FakeRestoreWorkflow(store, sdk, guard, Barrier(2))
    assert _contract()["confirmation_authority"]["concurrency_invariant"] == (
        "consume_count_equals_dispatch_count_equals_one"
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(workflow.execute, (request, request)))

    assert store.consume_count == sdk.dispatch_count == 1
    assert sdk.before_capture_count == 2
    assert sdk.readback_count == 1
    assert guard.open_count == guard.recapture_count == guard.release_count == 2
    assert workflow.conflicting_replace_observations == [False, False]
    assert guard.conflicting_replace_allowed() is True
    assert sorted(result["context"]["state"] for result in results) == [
        "confirmation_consume_rejected",
        "succeeded",
    ]
    for result in results:
        _validate_result(result)
    loser_result = next(
        result
        for result in results
        if result["context"]["state"] == "confirmation_consume_rejected"
    )
    assert loser_result["context"]["host_connection_performed"] is True
    assert loser_result["context"]["before_receipt"] is not None
    assert loser_result["context"]["dispatch_performed"] is False
    assert loser_result["context"]["confirmation_consumed"] is False
    assert loser_result["context"]["effect"] == "unknown"


def test_synchronous_restore_uses_actual_readback_and_rejects_mismatched_sha():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    mismatched_readback = _approved_after_receipt(request, store.resolver)
    mismatched_readback["sha256"] = "f" * 64
    sdk = FakeOfficialSdkBoundary(after_receipt=mismatched_readback)
    workflow = FakeRestoreWorkflow(
        store,
        sdk,
        FakeGuardedTargetBoundary(),
        Barrier(1),
    )

    result = workflow.execute(request)

    _validate_result(result)
    assert result["context"]["state"] == "failed_unknown"
    assert result["context"]["after_receipt"] is None
    assert "f" * 64 not in json.dumps(result, sort_keys=True)
    assert store.consume_count == sdk.dispatch_count == sdk.readback_count == 1


def test_synchronous_restore_without_actual_readback_fails_unknown_without_payload():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    sdk.after_receipt = None
    workflow = FakeRestoreWorkflow(
        store,
        sdk,
        FakeGuardedTargetBoundary(),
        Barrier(1),
    )

    result = workflow.execute(request)

    _validate_result(result)
    assert result["context"]["state"] == "failed_unknown"
    assert result["context"]["after_receipt"] is None
    assert result["message"] == "Recovery scene restore did not reach verified success."
    assert result["error"] == "RestoreFailedUnknown"
    assert store.consume_count == sdk.dispatch_count == sdk.readback_count == 1


@pytest.mark.parametrize("failure_kind", ("sdk_exception", "unserializable"))
def test_synchronous_restore_readback_failure_is_redacted_failed_unknown(failure_kind):
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    secret = "SDK readback leaked C:\\secret\\take.vdf token-123"
    if failure_kind == "sdk_exception":

        def failing_readback():
            with sdk._lock:
                sdk.readback_count += 1
            raise RuntimeError(secret)

        sdk.readback_after = failing_readback
    else:
        sdk.after_receipt = {"sdk_internal_text": object()}
    guard = FakeGuardedTargetBoundary()
    workflow = FakeRestoreWorkflow(store, sdk, guard, Barrier(1))

    result = workflow.execute(request)

    _validate_result(result)
    assert result["context"]["state"] == "failed_unknown"
    assert result["context"]["after_receipt"] is None
    assert result["message"] == "Recovery scene restore did not reach verified success."
    assert result["error"] == "RestoreFailedUnknown"
    assert secret not in json.dumps(result, sort_keys=True)
    assert "sdk_internal_text" not in json.dumps(result, sort_keys=True)
    assert store.consume_count == sdk.dispatch_count == sdk.readback_count == 1
    assert guard.release_count == 1


def test_synchronous_pre_close_failure_preserves_primary_result_and_guard_owner():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    cleanup_store = FakeDurableCleanupStore()
    guard = FakeGuardedTargetBoundary(release_failure_phase="before_close")
    workflow = FakeRestoreWorkflow(
        store,
        sdk,
        guard,
        Barrier(1),
        cleanup_store=cleanup_store,
    )

    result = workflow.execute(request)

    _validate_result(result)
    assert result["context"]["state"] == "succeeded"
    assert result["context"]["job"]["handle_retention_owner"] == (
        "trusted_adapter_local_restore_job_registry"
    )
    assert result["context"]["job"]["cleanup_disposition"] == ("release_failed_owner_retained")
    assert guard.release_count == 0
    assert guard.conflicting_replace_allowed() is False
    assert cleanup_store.last_record() == {
        "cleanup_version": "2.0",
        "cleanup_binding_sha256": cleanup_store.last_record()["cleanup_binding_sha256"],
        "phase": "synchronous_result",
        "disposition": "release_failed_owner_retained",
    }
    serialized = json.dumps({"result": result, "cleanup": cleanup_store.last_record()})
    assert guard.release_error_text not in serialized
    assert r"C:\secret" not in serialized


def test_synchronous_post_close_failure_preserves_primary_and_verified_release():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    cleanup_store = FakeDurableCleanupStore()
    guard = FakeGuardedTargetBoundary(release_failure_phase="after_close")
    workflow = FakeRestoreWorkflow(
        store,
        sdk,
        guard,
        Barrier(1),
        cleanup_store=cleanup_store,
    )

    result = workflow.execute(request)

    _validate_result(result)
    assert result["context"]["state"] == "succeeded"
    assert result["context"]["job"]["handle_retention_owner"] == (
        "released_after_terminal_readback"
    )
    assert result["context"]["job"]["cleanup_disposition"] == (
        "released_after_error_verified_closed"
    )
    assert guard.release_count == 1
    assert guard.conflicting_replace_allowed() is True
    assert cleanup_store.last_record()["disposition"] == ("released_after_error_verified_closed")
    serialized = json.dumps({"result": result, "cleanup": cleanup_store.last_record()})
    assert guard.release_error_text not in serialized
    assert r"C:\secret" not in serialized


def test_synchronous_cleanup_uses_the_same_durable_job_registry():
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    durable_store = FakeDurableJobStore()
    workflow = FakeRestoreWorkflow(
        confirmation_store,
        FakeOfficialSdkBoundary(),
        FakeGuardedTargetBoundary(),
        Barrier(1),
        durable_store=durable_store,
    )

    result = workflow.execute(request)

    _validate_result(result)
    job_id = result["context"]["job"]["job_id"]
    assert job_id in durable_store.records
    assert durable_store.records[job_id]["status"] == "terminal"
    assert durable_store.records[job_id]["guard"] is None
    assert (
        durable_store.tombstones[job_id]["cleanup_binding_sha256"]
        == (workflow.jobs.cleanup_record(job_id)["cleanup_binding_sha256"])
    )
    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(durable_store)
    assert restarted.descriptor(job_id) == result["context"]["job"]
    assert restarted.tombstone(job_id) == workflow.jobs.tombstone(job_id)


def test_synchronous_cleanup_crash_reconciles_from_the_durable_registry():
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    durable_store = FakeDurableJobStore()
    durable_store.cleanup_store.crash_after_release_once = True
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary()
    workflow = FakeRestoreWorkflow(
        confirmation_store,
        sdk,
        guard,
        Barrier(1),
        durable_store=durable_store,
    )

    with pytest.raises(RuntimeError, match="simulated crash after guard release"):
        workflow.execute(request)

    job_id = next(iter(durable_store.records))
    assert durable_store.records[job_id]["status"] == "cleanup_pending"
    assert durable_store.records[job_id]["cleanup_pending"]["phase"] == ("synchronous_result")
    assert guard.release_count == 1
    assert durable_store.waiter_notification_count == 0

    restarted = FakeAsyncRestoreJobRegistry.restart_after_process_loss(durable_store)
    terminal = restarted.descriptor(job_id)

    assert terminal["status"] == "terminal"
    assert terminal["cleanup_disposition"] == "released_after_error_verified_closed"
    assert restarted.tombstone(job_id)["cleanup_disposition"] == (
        "released_after_error_verified_closed"
    )
    assert durable_store.waiter_notification_count == 1
    assert confirmation_store.consume_count == sdk.dispatch_count == sdk.readback_count == 1


@pytest.mark.parametrize(
    ("cleanup_disposition", "handle_retention_owner"),
    (
        ("release_failed_owner_retained", "released_after_terminal_readback"),
        ("released", "trusted_adapter_local_restore_job_registry"),
        (
            "released_after_error_verified_closed",
            "trusted_adapter_local_restore_job_registry",
        ),
        (
            "release_indeterminate_quarantined",
            "released_after_terminal_readback",
        ),
    ),
)
def test_terminal_schema_rejects_false_cleanup_ownership_claims(
    cleanup_disposition,
    handle_retention_owner,
):
    private_result = _result("succeeded")
    private_job = private_result["context"]["job"]
    private_job["cleanup_disposition"] = cleanup_disposition
    private_job["handle_retention_owner"] = handle_retention_owner

    with pytest.raises(ValidationError):
        _validate_result(private_result)

    public_result = _public_result("succeeded")
    public_job = public_result["context"]["job"]
    public_job["cleanup_disposition"] = cleanup_disposition
    public_job["handle_retention_owner"] = handle_retention_owner
    with pytest.raises(ValidationError):
        _validator("output_schema").validate(public_result)


@pytest.mark.parametrize("phase", ("preflight", "recapture", "cas"))
@pytest.mark.parametrize("attack_kind", ("namespace", "junction", "parent", "same_content"))
def test_windows_namespace_change_before_cas_rejects_without_consume_or_dispatch(
    phase, attack_kind
):
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary(
        observed_change_phase=phase,
        attack_kind=attack_kind,
    )
    workflow = FakeRestoreWorkflow(store, sdk, guard, Barrier(1))

    result = workflow.execute(request)

    assert result["context"]["state"] == "target_guard_rejected"
    assert store.consume_count == sdk.dispatch_count == 0
    assert sdk.readback_count == 0
    assert guard.release_count == 1
    assert guard.attack_log == [
        {
            "phase": phase,
            "kind": attack_kind,
            "outcome": "identity_changed",
        }
    ]
    changed_object = {
        "namespace": "volume_root",
        "junction": "trusted_root",
        "parent": "recovery_directory",
        "same_content": "target_file",
    }[attack_kind]
    assert guard.changed_objects == [changed_object]
    assert guard.current_namespace_identity != guard.baseline_namespace_identity
    if attack_kind == "same_content":
        assert (
            guard.current_namespace_identity["target_file"]["content_sha256"]
            == (guard.baseline_namespace_identity["target_file"]["content_sha256"])
        )
        assert (
            guard.current_namespace_identity["target_file"]["object_id"]
            != (guard.baseline_namespace_identity["target_file"]["object_id"])
        )
    _validate_result(result)


@pytest.mark.parametrize("phase", ("preflight", "recapture", "cas", "dispatch"))
@pytest.mark.parametrize("attack_kind", ("namespace", "junction", "parent", "same_content"))
def test_windows_swap_attempt_is_blocked_by_full_pinned_chain_through_dispatch(phase, attack_kind):
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary(attempt_phase=phase, attack_kind=attack_kind)
    workflow = FakeRestoreWorkflow(store, sdk, guard, Barrier(1))

    result = workflow.execute(request)

    assert result["context"]["state"] == "succeeded"
    assert store.consume_count == sdk.dispatch_count == sdk.readback_count == 1
    assert guard.attack_log == [
        {
            "phase": phase,
            "kind": attack_kind,
            "outcome": "blocked_by_pinned_chain",
        }
    ]
    assert guard.changed_objects == []
    assert guard.current_namespace_identity == guard.baseline_namespace_identity
    assert sdk.dispatch_evidence == [
        {
            "dispatch_path": r"\\?\Volume{approved}\recovery\marked_take.vdf",
            "pinned_objects": (
                "volume_root",
                "trusted_root",
                "recovery_directory",
                "target_file",
            ),
            "held": True,
        }
    ]
    assert guard.release_count == 1
    _validate_result(result)


def test_dispatch_entry_identity_change_rejects_before_confirmation_consumption():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
    guard = FakeGuardedTargetBoundary(
        observed_change_phase="dispatch",
        attack_kind="same_content",
    )
    workflow = FakeRestoreWorkflow(store, sdk, guard, Barrier(1))

    result = workflow.execute(request)

    assert result["context"]["state"] == "target_guard_rejected"
    assert store.consume_count == sdk.dispatch_count == sdk.readback_count == 0
    assert guard.changed_objects == ["target_file"]
    assert guard.release_count == 1
    _validate_result(result)


def test_confirmation_authority_defines_trusted_issuance_lookup_compare_and_consume():
    authority = _contract()["confirmation_authority"]

    assert authority["issuer"] == "authenticated_operator_confirmation_service"
    assert authority["store"] == "trusted_adapter_local_store"
    assert authority["persistence"] == ("shared_durable_atomic_store_survives_authority_restart")
    assert authority["identity_reservation"] == (
        "atomic_insert_only_tombstone_created_on_first_issue"
    )
    assert authority["concurrent_issuers"] == ("exactly_one_insert_winner_for_each_confirmation_id")
    assert authority["caller_supplied_records_accepted"] is False
    assert authority["path_canonicalization"] == "windows_handle_final_path_identity_v1"
    assert authority["receipt_canonicalization"] == "nfc_sorted_compact_json_utf8_v1"
    assert authority["lookup_key"] == "confirmation_id"
    assert authority["comparison_fields"] == [
        "request_id",
        "canonical_trusted_root_sha256",
        "canonical_path_sha256",
        "target_volume_serial",
        "target_file_id",
        "recovery_receipt_binding_sha256",
    ]
    assert authority["consume"] == (
        "atomic_compare_and_set_revalidate_time_generation_request_target_and_receipt"
    )
    assert authority["consume_revalidation"] == [
        "trusted_current_time_precedes_expiry",
        "maximum_ttl_not_exceeded",
        "authority_generation_and_record_revision_match_lookup_ticket",
        "all_request_path_and_recovery_receipt_bindings_match",
        "guarded_target_identity_size_and_streaming_sha256_match",
        "destructive_and_non_idempotent_acknowledgements_remain_true",
        "confirmation_remains_unconsumed",
    ]
    assert authority["state_machine"] == [
        "authenticated_issue_to_trusted_store",
        "trusted_lookup_by_confirmation_id",
        "compare_request_path_receipt_freshness_and_unconsumed",
        "open_and_pin_volume_root_full_directory_chain_and_target",
        "connect_host_and_capture_before_receipt",
        "recapture_all_pinned_handle_identities_and_target_receipt",
        "reject_any_guard_change_before_consumption",
        "atomic_revalidate_all_authority_and_guard_bindings_then_consume",
        "dispatch_volume_guid_path_while_full_chain_remains_pinned",
        "official_sdk_readback_matches_guarded_confirmation_identity",
    ]


def test_target_guard_freezes_exact_confirmed_file_through_dispatch_and_readback():
    guard = _contract()["target_guard"]

    assert guard == {
        "strategy": "pin_full_windows_namespace_chain_through_dispatch",
        "open_api": "CreateFileW",
        "dispatch_path_api": "GetFinalPathNameByHandleW_VOLUME_NAME_GUID",
        "directory_desired_access": ["FILE_READ_ATTRIBUTES"],
        "directory_flags": ["FILE_FLAG_BACKUP_SEMANTICS", "FILE_FLAG_OPEN_REPARSE_POINT"],
        "target_desired_access": ["GENERIC_READ", "FILE_READ_ATTRIBUTES"],
        "target_flags": ["FILE_FLAG_OPEN_REPARSE_POINT"],
        "share_mode": ["FILE_SHARE_READ"],
        "creation_disposition": "OPEN_EXISTING",
        "pinned_objects": [
            "volume_root",
            "every_directory_component_including_trusted_root",
            "target_file",
        ],
        "deny_conflicting_access": ["write", "delete", "rename", "replace"],
        "identity_fields": ["canonical_path_sha256", "volume_serial", "file_id"],
        "component_identity_fields": [
            "volume_guid_final_path",
            "volume_serial",
            "file_id",
            "reparse_tag",
        ],
        "namespace_validation": [
            "handle_derived_component_chain_is_contiguous",
            "handle_derived_target_is_within_handle_derived_trusted_root",
            "reject_every_reparse_component_and_target",
            "reject_alternate_data_streams_before_and_after_open",
            "target_link_count_equals_one",
        ],
        "dispatch_path": "volume_guid_final_path_derived_from_pinned_target",
        "sdk_dispatch": "adapter_requires_retained_chain_not_bare_path",
        "per_use_recapture": "immediately_before_and_after_each_sdk_path_open",
        "hold_from": "before_first_namespace_identity_capture",
        "hold_until": "terminal_official_sdk_readback_or_unknown_effect",
        "validation_checkpoints": [
            "after_official_sdk_before_receipt_capture_completed",
            "after_all_pinned_handle_and_target_receipt_recapture",
            "immediately_before_confirmation_cas",
            "dispatch_entry_before_confirmation_cas_with_full_chain_still_held",
        ],
        "predispatch_recapture": (
            "all_pinned_handle_identities_and_target_receipt_immediately_before_confirmation_cas"
        ),
        "change_before_cas": "target_guard_rejected_without_consume_or_dispatch",
        "swap_attempt_while_pinned": "blocked_by_windows_share_contract",
        "close_semantics": {
            "close_api": "CloseHandle",
            "false_return": "independently_probe_only_for_verified_closed",
            "observations": ["closed", "indeterminate"],
            "closed": "remove_numeric_handle_and_never_retry",
            "valid_numeric_after_false": "indeterminate_due_to_unprovable_handle_generation",
            "same_file_same_numeric_reuse": "cannot_prove_original_ownership",
            "indeterminate": "quarantine_without_retry_or_release_claim",
            "retry_after_false_return": "forbidden",
            "primary_outcome": "preserved",
        },
        "adversarial_proof": {
            "phases": ["preflight", "recapture", "cas", "dispatch"],
            "swap_kinds": ["namespace", "junction", "parent", "same_content"],
            "predispatch_change_invariant": "consume_count_equals_dispatch_count_equals_zero",
        },
        "windows_integration_proof": {
            "platform": "windows_ci_real_filesystem",
            "sdk_boundary": "CreateFileW_reopens_volume_guid_path",
            "retained_through_open": "volume_root_every_directory_and_target_handles",
            "identity_assertion": "full_handle_chain_and_reopened_target_equal_confirmation",
            "attack_kinds": [
                "target",
                "parent",
                "junction",
                "namespace",
                "same_content",
                "preexisting_file_symlink",
                "preexisting_junction",
                "alternate_data_stream",
                "cross_root_hardlink",
            ],
            "attack_outcome_while_retained": (
                "preexisting_aliases_rejected_runtime_swaps_blocked_confirmed_identity_loaded"
            ),
            "control_after_release": "same_swap_succeeds_and_path_identity_changes",
            "real_shogun_invoked": False,
        },
        "readback_match": "official_sdk_active_scene_to_guarded_confirmation_identity",
    }


def test_windows_path_adapter_integration_proves_the_confirmed_object_is_opened():
    proof = _contract()["target_guard"]["windows_integration_proof"]

    assert proof == {
        "platform": "windows_ci_real_filesystem",
        "sdk_boundary": "CreateFileW_reopens_volume_guid_path",
        "retained_through_open": "volume_root_every_directory_and_target_handles",
        "identity_assertion": "full_handle_chain_and_reopened_target_equal_confirmation",
        "attack_kinds": [
            "target",
            "parent",
            "junction",
            "namespace",
            "same_content",
            "preexisting_file_symlink",
            "preexisting_junction",
            "alternate_data_stream",
            "cross_root_hardlink",
        ],
        "attack_outcome_while_retained": (
            "preexisting_aliases_rejected_runtime_swaps_blocked_confirmed_identity_loaded"
        ),
        "control_after_release": "same_swap_succeeds_and_path_identity_changes",
        "real_shogun_invoked": False,
    }


def test_predispatch_guard_recapture_failure_has_a_legal_not_dispatched_state():
    result = {
        "success": False,
        "message": "Guarded target identity could not be reconfirmed before dispatch.",
        "prompt": None,
        "error": "RestoreTargetGuardRejected",
        "context": {
            "receipt_version": "1.0",
            "request_id": "restore-0001",
            "state": "target_guard_rejected",
            "effect": "unknown",
            "replay_allowed": False,
            "host_connection_performed": True,
            "before_receipt_captured": True,
            "dispatch_performed": False,
            "confirmation_consumed": False,
            "guard_outcome": "predispatch_identity_or_receipt_mismatch",
            "before_receipt": _scene_receipt("working_scene.vdf", "b" * 64, "c" * 64),
            "after_receipt": None,
            "job": _job_for_state("target_guard_rejected"),
        },
    }

    _validate_result(result)


def test_success_requires_readback_to_match_exact_guarded_confirmation_identity():
    identity = {
        "canonical_path_sha256": "d" * 64,
        "volume_serial": "00000000A1B2C3D4",
        "file_id": "00112233445566778899aabbccddeeff",
    }
    result = _result("succeeded")
    result["context"]["approved_target_identity"] = dict(identity)
    result["context"]["after_receipt"]["target_identity"] = dict(identity)
    result["context"]["postcondition_evidence"]["after_matches_guarded_confirmation_identity"] = (
        True
    )
    _validate_result(result)

    replaced = json.loads(json.dumps(result))
    replaced["context"]["after_receipt"]["target_identity"]["file_id"] = "f" * 32
    with pytest.raises(ValidationError, match="file_id"):
        _validate_result(replaced)


def test_windows_final_path_alias_and_dotdot_share_golden_identity():
    vector = _contract()["canonicalization"]["windows_final_path"]["golden_vectors"][0]
    resolver = FakeTrustedPathResolver()
    for alias in vector["raw_aliases"]:
        resolver.add(
            alias,
            final_path=vector["final_path"],
            volume_serial=vector["volume_serial"],
            file_id=vector["file_id"],
        )
    canonical_bytes, digest = _path_binding(
        vector["final_path"], vector["volume_serial"], vector["file_id"]
    )

    assert vector["raw_aliases"] == [
        "C:/Approved/shots/../shots/镜头_É.vdf",
        "c:\\approved\\shots\\镜头_É.vdf",
    ]
    assert canonical_bytes.hex() == (
        "77696e646f77732d66696e616c2d706174682d76310a766f6c756d655f73657269616c3d"
        "303030303030303041314232433344340a66696c655f69643d303031313232333334343535"
        "36363737383839396161626263636464656566660a706174683d633a5c617070726f766564"
        "5c73686f74735ce9959ce5a4b45fc3892e766466"
    )
    resolved = [resolver.resolve(alias) for alias in vector["raw_aliases"]]
    assert all(evidence["canonical_bytes"] == canonical_bytes for evidence in resolved)
    assert vector["canonical_utf8_hex"] == canonical_bytes.hex()
    assert digest == "ba82b4305ccab53ae1e023659d21fee8e3361b031c6abc4a4c2d9c226986104a"
    assert vector["sha256"] == digest


def test_windows_reparse_escape_is_rejected_and_device_identity_changes_digest():
    resolver = _resolver()
    alias = "C:/operator-approved/recovery/reparse/marked_take.vdf"
    resolver.add(
        alias,
        final_path="\\\\?\\D:\\outside\\marked_take.vdf",
        volume_serial="00000000D4C3B2A1",
        file_id="99990000aaaabbbbccccddddeeeeffff",
        approved=False,
    )

    with pytest.raises(ValueError, match="reparse or device identity"):
        resolver.resolve(alias)
    approved_digest = resolver.resolve(_request()["file_path"])["sha256"]
    _, outside_digest = _path_binding(
        "\\\\?\\D:\\outside\\marked_take.vdf",
        "00000000D4C3B2A1",
        "99990000aaaabbbbccccddddeeeeffff",
    )
    assert outside_digest != approved_digest


def test_unicode_receipt_has_cross_language_golden_bytes_and_digest():
    vector = _contract()["canonicalization"]["recovery_receipt"]["golden_vectors"][0]
    decomposed = dict(vector["receipt"])
    decomposed["file_name"] = "镜头_É.vdf"
    composed_bytes, composed_digest = _receipt_binding(vector["receipt"])
    decomposed_bytes, decomposed_digest = _receipt_binding(decomposed)

    assert composed_bytes == decomposed_bytes
    assert vector["canonical_utf8_hex"] == composed_bytes.hex()
    assert composed_digest == "ce41a69eec6594a5511ea7d219a26bb84af1d7db033876a1124a5b7cbbe12e58"
    assert vector["sha256"] == composed_digest


def test_scene_identity_is_derived_from_raw_get_scene_name_shapes_and_golden_digests():
    identity_contract = _contract()["canonicalization"]["scene_identity"]

    assert identity_contract["official_sdk_calls"] == ["GetSceneName", "GetFrameCount"]
    assert identity_contract["get_scene_name_tuple_rule"] == {
        "shape": "exactly_two_strings_scene_path_and_name_or_path",
        "scene_path": "absolute_windows_directory_for_saved_scene",
        "full_path": "name_or_path_parent_must_equal_scene_path",
        "basename": "join_name_or_path_to_scene_path",
        "relative_path_with_separator": "reject",
        "scene_name": "unicode_nfc_basename_of_name_or_path",
        "unsaved_sentinel": [".", ".vdf"],
        "malformed_or_unsaved": "reject_before_receipt",
    }
    assert identity_contract["members"] == [
        "canonical_path_sha256",
        "frame_count",
        "scene_name",
    ]
    accepted = [
        vector
        for vector in identity_contract["golden_vectors"]
        if vector["disposition"] == "accept"
    ]
    assert [vector["name"] for vector in accepted] == [
        "full_path_return_shape",
        "basename_return_shape",
        "unicode_nfc_full_path",
    ]
    derived = []
    for vector in accepted:
        resolver = FakeTrustedPathResolver()
        resolver.add(vector["resolver_input"], **vector["handle_observation"])

        identity = _scene_identity_from_raw(
            tuple(vector["raw_get_scene_name"]),
            vector["raw_get_frame_count"],
            resolver,
        )
        canonical_bytes, digest = _scene_identity_binding(identity)

        assert identity == vector["derived_identity"]
        assert vector["canonical_utf8_hex"] == canonical_bytes.hex()
        assert vector["sha256"] == digest
        derived.append(identity)

    assert derived[0] == derived[1]
    assert derived[2]["scene_name"] == "镜头_É.vdf"


@pytest.mark.parametrize(
    ("vector_name", "error_match"),
    (
        ("unsaved_dot_vdf", "unsaved scene"),
        ("malformed_parent_mismatch", "scene path parent mismatch"),
        ("negative_frame_count", "nonnegative integer"),
        ("relative_forward_slash", "must not contain a path separator"),
        ("relative_backslash", "must not contain a path separator"),
        ("wrong_arity_one", "exactly two strings"),
        ("wrong_arity_three", "exactly two strings"),
        ("non_string_scene_path", "exactly two strings"),
        ("non_string_name_or_path", "exactly two strings"),
    ),
)
def test_scene_identity_rejects_invalid_raw_get_scene_name_observations(vector_name, error_match):
    identity_contract = _contract()["canonicalization"]["scene_identity"]
    vector = next(
        item for item in identity_contract["golden_vectors"] if item["name"] == vector_name
    )

    with pytest.raises(ValueError, match=error_match):
        _scene_identity_from_raw(
            tuple(vector["raw_get_scene_name"]),
            vector["raw_get_frame_count"],
            FakeTrustedPathResolver(),
        )


def test_scene_receipt_rejects_digest_not_derived_from_its_sdk_observation():
    result = _result("succeeded")
    before_fields = {
        "scene_name": "working_scene.vdf",
        "frame_count": 240,
        "canonical_path_sha256": "e" * 64,
    }
    after_fields = {
        "scene_name": "marked_take.vdf",
        "frame_count": 240,
        "canonical_path_sha256": "d" * 64,
    }
    for receipt, fields in (
        (result["context"]["before_receipt"], before_fields),
        (result["context"]["after_receipt"], after_fields),
    ):
        receipt["scene_identity_fields"] = fields
        receipt["scene_identity_sha256"] = _scene_identity_binding(fields)[1]
    _validate_result(result)

    nondeterministic = json.loads(json.dumps(result))
    nondeterministic["context"]["after_receipt"]["scene_identity_sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="scene_identity_sha256"):
        _validate_result(nondeterministic)

    contradictory = json.loads(json.dumps(result))
    fields = contradictory["context"]["after_receipt"]["scene_identity_fields"]
    fields["scene_name"] = "different_scene.vdf"
    contradictory["context"]["after_receipt"]["scene_identity_sha256"] = _scene_identity_binding(
        fields
    )[1]
    with pytest.raises(ValidationError, match="scene_name must equal file_name"):
        _validate_result(contradictory)


def test_result_validation_requires_schema_and_semantic_postconditions():
    assert _contract()["result_validation_pipeline"] == [
        "draft2020_schema",
        "latest_durable_job_revision",
        "semantic_invariants",
        "semantic_postconditions",
        "scene_identity_digest",
    ]


def test_result_validation_requires_latest_durable_job_revision_before_projection():
    invariant = _contract()["semantic_invariants"]["latest_durable_job_revision"]

    assert invariant == {
        "lookup": "exact_private_job_id",
        "compare": [
            "job_generation",
            "operation_binding_sha256",
            "record_revision",
            "event_sequence",
            "status",
        ],
        "mismatch": "reject_stale_result_before_public_projection",
    }


def test_contract_records_semantic_gates_not_expressible_in_json_schema():
    contract = _contract()

    assert contract["preconditions"] == [
        "canonical_target_is_contained_by_canonical_trusted_root",
        "target_is_regular_vdf_without_symlink_or_reparse_escape",
        "target_basename_size_and_sha256_match_recovery_receipt",
        "recovery_receipt_reports_active_scene_unchanged",
        "operator_confirmation_is_fresh_exact_scope_and_unused",
    ]
    assert contract["terminal_rules"] == {
        "poll_only_after_dispatch": True,
        "mutation_retry_allowed": False,
        "timeout_state": "timed_out",
        "unknown_state": "indeterminate",
        "timeout_or_unknown_effect": "unknown",
    }
    assert contract["real_host_acceptance"] == {
        "authorized_by_this_contract": False,
        "requires_disposable_marked_take": True,
        "requires_explicit_approved_path_scope": True,
        "requires_separate_operator_authorization": True,
    }
    assert contract["synchronous_completion"] == {
        "registry": "same_durable_job_registry_as_async_completion",
        "guard_record": "persisted_before_confirmation_cas_or_sdk_dispatch",
        "readback_value": "exact_official_sdk_readback_return",
        "synthetic_fixture_success": "forbidden",
        "classification": "shared_guarded_completion_classifier",
        "mismatch_or_absence": "failed_unknown",
        "readback_exception": "failed_unknown_without_public_diagnostic",
        "unserializable_readback": "failed_unknown_without_public_payload",
        "failed_unknown_after_receipt": "null",
        "public_payload_projection": "fixed_message_and_error_only",
        "cleanup_store": "durable_exact_guard_bound_cleanup_record_v2",
        "cleanup_pending": "persisted_before_guard_release",
        "cleanup_commit_marker": "retained_until_terminal_tombstone_and_waiter_wakeup_complete",
        "restart_reconciliation": (
            "exact_pending_or_commit_marker_to_terminal_tombstone_and_waiter_notification"
        ),
        "cleanup_failure": "preserve_primary_result_and_retain_owner_until_verified_closed",
    }


def test_contract_freezes_public_text_and_exact_async_job_ownership():
    contract = _contract()

    assert contract["public_output_policy"] == {
        "message_source": "fixed_state_constants_only",
        "prompt": "always_null",
        "prohibited_public_text": [
            "full_paths",
            "raw_exceptions",
            "sdk_result_text",
            "confirmation_secrets",
            "raw_scene_or_take_names",
            "operator_identifiers",
            "caller_request_ids",
        ],
        "schema_enforcement": "branch_specific_message_const_and_null_prompt",
        "projection": "adapter_secret_hmac_sha256_v1",
        "public_schema": "output_schema",
        "private_schema": "private_audit_result_schema",
        "private_schema_public_exposure": "forbidden",
        "internal_diagnostics": "trusted_registry_only_outside_public_result",
    }
    assert contract["private_audit_contract"] == {
        "owner": "trusted_adapter_local_restore_job_registry",
        "schema": "private_audit_result_schema",
        "public_exposure": "forbidden",
        "contains": [
            "caller_request_id",
            "confirmation_record",
            "canonical_paths_and_target_identity",
            "raw_scene_and_take_names",
            "full_before_after_and_recovery_receipts",
            "raw_sdk_and_internal_diagnostics",
            "durable_readback_claim_fence",
            "durable_claim_bound_cancellation_intent",
        ],
        "public_projection": "adapter_secret_hmac_sha256_v1",
    }
    async_contract = contract["async_job_contract"]
    assert async_contract["owner"] == "trusted_adapter_local_restore_job_registry"
    assert async_contract["persistence"] == "durable_atomic_store_survives_adapter_restart"
    assert async_contract["create_record"] == "before_host_connection_and_dispatch"
    assert async_contract["result_member"] == "context.job"
    assert async_contract["status_descriptor_schemas"] == {
        "private_dispatch_uncertain": (
            "private_audit_result_schema.$defs.dispatch_uncertain_job_descriptor"
        ),
        "public_dispatch_uncertain": "output_schema.$defs.public_dispatch_uncertain_job",
    }
    assert async_contract["identity"] == {
        "format": "rj1_sha256_generation_sequence_operation_binding_v1",
        "generation": "durable_monotonic_registry_generation",
        "allocation": "atomic_reserve_before_host_connection",
        "reuse": "forbidden_forever",
        "tombstone": "durable_from_reservation_through_terminal_retention",
        "operation_binding": "immutable_after_reservation",
    }
    assert async_contract["exact_operation_binding"] == {
        "algorithm": "nfc_sorted_compact_json_sha256_v1",
        "members": [
            "job_generation",
            "request_id",
            "confirmation_id",
            "confirmation_revision",
            "canonical_trusted_root_sha256",
            "canonical_path_sha256",
            "target_volume_serial",
            "target_file_id",
            "recovery_receipt_binding_sha256",
        ],
    }
    assert async_contract["status_lookup"] == "trusted_record_by_exact_job_id"
    assert async_contract["poll_may_dispatch"] is False
    assert async_contract["retry_may_dispatch"] is False
    assert async_contract["max_dispatch_count_per_job"] == 1
    assert async_contract["dispatch_boundary"] == {
        "durable_state_before_sdk_call": "dispatch_uncertain",
        "reservation_binding": "exact_job_generation_operation_confirmation_target_and_receipt",
        "sdk_call_attempts_after_reservation": 1,
        "dispatch_count_semantics": "official_sdk_call_return_confirmed",
        "crash_after_reservation": "possible_dispatch_unknown",
        "recovery_redispatch": "forbidden",
        "terminal_not_dispatched_after_reservation": "forbidden",
        "handle_owner": "exact_process_epoch_lease_until_terminal_cleanup",
        "guarantee_without_sdk_transaction_or_idempotency": "at_most_once_not_exactly_once",
    }
    assert async_contract["handle_ownership"] == {
        "transfer": ("request_scope_to_trusted_adapter_local_restore_job_registry_before_dispatch"),
        "retain_after_dispatch": ("through_late_official_sdk_readback_or_terminal_unknown_effect"),
        "release_before_dispatch": "cancellation_or_guard_rejection",
        "release_after_dispatch": "only_after_terminal_readback_or_terminal_unknown_effect",
    }
    assert async_contract["cleanup"] == {
        "store": "durable_exact_guard_bound_cleanup_record_v2",
        "binding": "sha256_exact_job_generation_operation_event_and_guard_identity",
        "pending_state": "cleanup_pending_not_publicly_publishable",
        "pending_write": "atomic_before_guard_release_under_exact_claim_fence",
        "release_attempt": "only_after_durable_cleanup_pending",
        "release_observation": ("verified_not_attempted_still_owned_closed_or_indeterminate"),
        "commit_marker": "durable_until_terminal_tombstone_and_waiter_wakeup_complete",
        "tombstone_commit": "idempotent_exact_binding",
        "waiter_notification_intent": "durable_replayable_until_notify_all_returns",
        "waiter_delivery": "at_least_once",
        "pre_notify_completion_flag": "forbidden",
        "restart_reconciliation": (
            "exact_pending_or_commit_marker_to_terminal_tombstone_and_waiter_notification"
        ),
        "synchronous_path": "same_durable_job_registry_and_cleanup_protocol",
        "dispositions": [
            "not_started",
            "released",
            "release_failed_owner_retained",
            "released_after_error_verified_closed",
            "release_indeterminate_quarantined",
        ],
        "failure_policy": "preserve_primary_outcome_and_never_claim_false_release",
        "retained_failure_owner": "trusted_adapter_local_restore_job_registry",
        "indeterminate_owner": "cleanup_ownership_indeterminate_registry_quarantine",
        "terminal_record": "durable_with_cleanup_disposition",
        "tombstone": "always_persisted_for_terminal_outcome",
        "waiter_notification": "always_after_terminal_record_and_tombstone",
    }
    assert async_contract["late_completion"] == {
        "correlation": ("exact_job_id_generation_operation_binding_event_id_and_event_digest"),
        "event_identity": "rce1_sha256_exact_completion_event_v1",
        "event_members": [
            "job_id",
            "job_generation",
            "operation_binding_sha256",
            "expected_revision",
            "event_sequence",
            "terminal_source",
            "completion_receipt_sha256",
        ],
        "digest": "sorted_compact_json_sha256",
        "polling": "jobs_get_status_never_redispatches",
        "event_receipt_source": "actual_official_sdk_completion_receipt",
        "readback_source": "fresh_official_sdk_and_guarded_filesystem_receipt",
        "verified_bindings": [
            "job_id",
            "job_generation",
            "operation_binding_sha256",
            "confirmation_and_approved_target",
            "canonical_scene_identity_sha256",
            "completion_event_receipt_sha256",
        ],
        "terminal_outcomes": {
            "approved_distinct_readback": "succeeded",
            "exact_before_readback": "failed_unchanged",
            "malformed_mismatched_or_unbounded_readback": "failed_unknown",
        },
        "receipt_digest_mismatch": "failed_unknown",
        "readback_boundary_failure": {
            "sdk_exception": "terminal_failed_unknown_under_exact_claim_fence",
            "resource_limit_plus_one": "terminal_failed_unknown_under_exact_claim_fence",
            "unserializable_receipt": "terminal_failed_unknown_under_exact_claim_fence",
            "after_receipt": "null",
            "public_diagnostic": "fixed_message_and_error_only",
            "guard_release": "after_durable_exact_guard_bound_cleanup_pending",
            "waiter_notification": ("after_terminal_record_and_tombstone_even_when_cleanup_fails"),
            "duplicate_poll": "return_terminal_without_readback_or_dispatch",
        },
        "claim_fence": {
            "persistence": "durable_atomic_job_record",
            "owner": "adapter_secret_hmac_sha256_v1",
            "generation": "durable_monotonic_claim_generation",
            "registry_process_epoch": "durable_exclusive_epoch_lease",
            "epoch_acquisition": "only_after_previous_owner_death_is_proven",
            "live_epoch_takeover": "rejected",
            "orphan_detection": "claimed_epoch_retired_by_exclusive_lease_takeover",
            "orphan_recovery": (
                "terminal_failed_unknown_without_sdk_readback_then_durable_cleanup"
            ),
            "orphan_terminal_source": "readback_owner_lost",
            "old_claim_after_takeover": "fenced_and_rejected",
            "claimed_revision": "completion_event_expected_revision",
            "fence_revision": "claimed_record_revision_plus_one",
            "bindings": [
                "job_id",
                "job_generation",
                "operation_binding_sha256",
                "completion_event_id",
                "retained_guard_owner_and_generation",
                "registry_process_epoch",
            ],
            "completion_cas": "exact_latest_owner_generation_and_fence_revision",
            "guard_recapture": "immediately_before_terminal_cas",
            "guard_release": "exact_claimed_guard_only_after_durable_cleanup_pending",
            "stale_foreign_or_replaced": "reject_without_commit_or_guard_release",
            "active_claim_cancellation": (
                "durable_hmac_bound_side_intent_without_job_revision_advance"
            ),
        },
        "claim_schema": {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "required": [
                "claim_version",
                "job_id",
                "job_generation",
                "event_id",
                "operation_binding_sha256",
                "claim_owner",
                "claim_generation",
                "claimed_record_revision",
                "fence_revision",
                "registry_epoch",
                "retained_guard_owner",
                "retained_guard_generation",
            ],
            "properties": {
                "claim_version": {"type": "string", "const": "1.0"},
                "job_id": {"type": "string", "pattern": "^rj1-[0-9a-f]{64}$"},
                "job_generation": {"type": "string", "pattern": "^[0-9a-f]{16}$"},
                "event_id": {"type": "string", "pattern": "^rce1-[0-9a-f]{64}$"},
                "operation_binding_sha256": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{64}$",
                },
                "claim_owner": {
                    "type": "string",
                    "pattern": "^rco1-[0-9a-f]{64}$",
                },
                "claim_generation": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{16}$",
                },
                "claimed_record_revision": {"type": "integer", "minimum": 1},
                "fence_revision": {"type": "integer", "minimum": 2},
                "registry_epoch": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{16}$",
                },
                "retained_guard_owner": {
                    "type": "string",
                    "pattern": "^rgo1-[0-9a-f]{64}$",
                },
                "retained_guard_generation": {
                    "type": "string",
                    "pattern": "^[0-9a-f]{16}$",
                },
            },
            "additionalProperties": False,
        },
        "handles": "released_retained_or_quarantined_by_typed_cleanup_disposition",
    }
    assert async_contract["transitions"] == {
        "synchronization": "durable_store_compare_and_set_lock",
        "record_revision": "strictly_monotonic_every_record_write",
        "event_sequence": "strictly_monotonic_exact_event_order",
        "terminal_immutability": "no_writes_after_terminal",
        "readback_claim": "durable_hmac_owner_generation_revision_and_process_epoch_fence",
        "orphaned_readback_claim": ("failed_unknown_without_sdk_readback_then_durable_cleanup"),
        "completion_commit": ("immediate_guard_recapture_then_cleanup_pending_then_terminal_cas"),
        "handle_release": "only_after_durable_exact_guard_bound_cleanup_pending",
        "cancellation_during_readback_claim": ("fold_exact_durable_side_intent_into_terminal_cas"),
        "readback": "at_most_once_per_job",
        "duplicate_completion": "return_existing_terminal_without_readback",
        "out_of_order_completion": "reject_without_state_change",
        "stale_snapshot_publication": "reject_against_latest_durable_revision",
    }


def test_late_readback_claim_has_a_strict_private_schema_and_revision_fence():
    _, jobs, sdk, job_id = _pending_async_workflow()
    event = jobs.make_completion_event(job_id, sdk.completion_receipt())
    claim = jobs.claim_late_readback(event)
    schema = _contract()["async_job_contract"]["late_completion"]["claim_schema"]

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(claim)
    assert claim["fence_revision"] == claim["claimed_record_revision"] + 1
    for invalid in (
        dict(claim, claim_owner="foreign-owner"),
        dict(claim, claim_generation="1"),
        dict(claim, registry_epoch="1"),
        dict(claim, retained_guard_owner="operator-name"),
    ):
        with pytest.raises(ValidationError):
            Draft202012Validator(schema).validate(invalid)


def test_dispatch_uncertain_has_strict_private_and_public_status_schemas():
    contract = _contract()
    private_defs = contract["private_audit_result_schema"]["$defs"]
    public_defs = contract["output_schema"]["$defs"]
    private_job = _job_descriptor(
        status="dispatch_uncertain",
        snapshot_source="durable_dispatch_reservation",
        dispatch_count=0,
    )
    public_job = _public_job_for_state(
        "timed_out",
        private_job,
        "c" * 64,
        b"adapter-private-test-key",
    )

    Draft202012Validator(
        {
            "$defs": private_defs,
            "$ref": "#/$defs/dispatch_uncertain_job_descriptor",
        }
    ).validate(private_job)
    Draft202012Validator(
        {
            "$defs": public_defs,
            "$ref": "#/$defs/public_dispatch_uncertain_job",
        }
    ).validate(public_job)

    for invalid in (
        dict(private_job, dispatch_attempt_reserved=False),
        dict(private_job, status="terminal_not_dispatched"),
        dict(private_job, poll_allowed=False),
        dict(private_job, handle_retention_owner="released_before_dispatch"),
    ):
        with pytest.raises(ValidationError):
            Draft202012Validator(
                {
                    "$defs": private_defs,
                    "$ref": "#/$defs/dispatch_uncertain_job_descriptor",
                }
            ).validate(invalid)


def test_adr_preserves_the_design_only_acceptance_boundary():
    adr = ADR_PATH.read_text(encoding="utf-8")

    for phrase in (
        "Status: Proposed",
        "No restore implementation is authorized",
        "trusted-root containment",
        "single-use",
        "official SDK",
        "timed_out",
        "indeterminate",
        "preflight_rejected",
        "host_connection_performed=false",
        "failed_unchanged",
        "failed_unknown",
        "semantic_postconditions",
        "fixed state-specific public messages",
        "`prompt=null`",
        "trusted adapter-local restore job registry",
        "operation-binding digest",
        "`jobs_get_status`",
        "cancellation before dispatch",
        "cancellation after dispatch",
        "late official SDK read-back",
        "never dispatches",
        "authenticated operator confirmation service",
        "trusted adapter-local store",
        "canonical-path digest",
        "freshness and expiry",
        "atomic compare-and-set",
        "trusted current time",
        "dispatch-uncertain",
        "at-most-once",
        "SDK transaction or idempotency",
        "completion-receipt digest",
        "failed unknown",
        "exact value returned by the official SDK",
        "must never synthesize success",
        "durable read-back claim owner",
        "claim generation",
        "fence revision",
        "immediately recapture",
        "foreign or replaced",
        "claim-bound cancellation intent",
        "does not advance the claimed job revision",
        "terminal CAS folds",
        "SDK read-back exceptions",
        "resource-limit-plus-one",
        "CloseHandle",
        "shared durable atomic confirmation store",
        "cleanup disposition",
        "preserves the primary restore outcome",
        "never claims that a guard was released",
        "unserializable read-back",
        "notify every waiter",
        "8 GiB",
        "streaming SHA-256",
        "64 KiB",
        "confirmation_consume_rejected",
        "exactly one winner",
        "handle-derived final path",
        "volume serial",
        "128-bit file ID",
        "dot segments",
        "reparse",
        "Unicode NFC",
        "golden vectors",
        "CreateFileW",
        "FILE_SHARE_READ",
        "full directory chain",
        "volume-GUID path",
        "same-content replacement",
        "real Windows filesystem harness",
        "reopens the volume-GUID path",
        "after the retained handles are released",
        "alternate-data-stream",
        "hardlink",
        "file attributes",
        "immediately before and after every",
        "target_guard_rejected",
        "atomic insert-if-absent",
        "permanently nonreusable",
        "durable tombstones",
        "durable monotonic generation",
        "permanent tombstone",
        "adapter-secret HMAC projection",
        "cancellation_requested",
        "cancellation_effective",
        "ignored_after_terminal",
        "completion event",
        "record_revision",
        "event_sequence",
        "Terminal records are immutable",
        "At most one read-back",
        "registry-process epoch lease",
        "retired claim epoch",
        "zero-read-back fail-closed branch",
        "old pending descriptor",
        "consume_count == dispatch_count == 1",
        "GetSceneName",
        "GetFrameCount",
        "name-or-path",
        '(".", ".vdf")',
        "strict nonnegative integer",
        "timestamps",
        "disposable marked take",
        "Refs #36",
    ):
        assert phrase in adr
    for forbidden_claim in (
        "real restore verified",
        "production restore verified",
        "Shogun restore passed",
    ):
        assert forbidden_claim not in adr.lower()
