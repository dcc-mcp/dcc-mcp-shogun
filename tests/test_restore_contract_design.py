from __future__ import annotations

import hashlib
import hmac
import json
import ntpath
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Condition, Lock, RLock

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
):
    cancellation_requested = cancellation_disposition != "not_requested"
    cancellation_effective = cancellation_disposition == "honored_before_dispatch"
    terminal = status in {"terminal", "terminal_not_dispatched"}
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
        "poll_allowed": poll_allowed,
        "duplicate_execution_allowed": False,
        "late_completion_disposition": late_completion_disposition,
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
        )
    if state in {"succeeded", "failed_unchanged"}:
        return _job_descriptor(
            status="terminal",
            snapshot_source="official_sdk_readback",
            terminal_source="official_sdk_readback",
            handle_retention_owner="released_after_terminal_readback",
            poll_allowed=False,
            late_completion_disposition="not_applicable",
        )
    if state == "failed_unknown":
        return _job_descriptor(
            status="terminal",
            snapshot_source="official_sdk_failure",
            terminal_source="official_sdk_failure",
            handle_retention_owner="released_after_terminal_unknown",
            poll_allowed=False,
            late_completion_disposition="not_applicable",
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


def _public_result(state, secret=b"adapter-private-test-key"):
    private_result = _result(state)
    private_context = private_result["context"]
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
        "failed_unknown": "official_sdk_failure",
        "timed_out": "request_timeout",
        "indeterminate": "transport_loss",
    }.get(state)
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
        workflow = FakeAsyncRestoreWorkflow(
            store,
            FakeOfficialSdkBoundary(),
            FakeGuardedTargetBoundary(),
            FakeAsyncRestoreJobRegistry(durable_store),
        )
        result = workflow.start(request, "request_timeout")
        job_ids.append(result["context"]["job"]["job_id"])

    assert job_ids[0] != job_ids[1]


def test_late_completion_event_is_bound_to_exact_job_generation_and_operation():
    workflow, jobs, sdk, job_id = _pending_async_workflow()
    event = jobs.make_completion_event(job_id)
    forged = dict(event, operation_binding_sha256="f" * 64)

    with pytest.raises(RuntimeError, match="completion event identity rejected"):
        jobs.claim_late_readback(forged)

    assert sdk.readback_count == 0
    assert jobs.descriptor(job_id)["status"] == "awaiting_late_readback"


def test_terminal_job_tombstone_survives_registry_restart_and_is_never_reused():
    durable_store = FakeDurableJobStore()
    workflow, jobs, _, job_id = _pending_async_workflow(durable_store)
    terminal = workflow.poll(job_id, late_success=True)["context"]["job"]

    restarted = FakeAsyncRestoreJobRegistry(durable_store)
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
    event = jobs.make_completion_event(job_id)
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
        jobs.make_completion_event(terminal["job_id"])
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


def _pending_async_workflow(durable_store=None):
    request = _request()
    confirmation_store = FakeTrustedConfirmationStore()
    confirmation_store.issue(request, authenticated=True)
    sdk = FakeOfficialSdkBoundary()
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


class FakeTrustedConfirmationStore:
    def __init__(self, resolver=None):
        self.resolver = resolver or _resolver()
        self._records = {}
        self._lock = Lock()
        self.consume_count = 0

    def issue(self, request, *, authenticated, now=NOW_EPOCH_SECONDS):
        if not authenticated:
            raise PermissionError("authenticated operator issuance required")
        root = self.resolver.resolve(request["trusted_root"])
        target = self.resolver.resolve(request["file_path"])
        _, receipt_digest = _receipt_binding(request["recovery_receipt"])
        record = {
            "record_version": "1.1",
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
        with self._lock:
            if record["confirmation_id"] in self._records:
                raise ValueError("confirmation ID is immutable and nonreusable")
            self._records[record["confirmation_id"]] = record
        return record["confirmation_id"]

    def trusted_lookup_and_compare(self, request, *, now=NOW_EPOCH_SECONDS):
        confirmation_id = request["operator_confirmation"]["confirmation_id"]
        record = self._records.get(confirmation_id)
        if record is None:
            return None
        root = self.resolver.resolve(request["trusted_root"])
        target = self.resolver.resolve(request["file_path"])
        _, receipt_digest = _receipt_binding(request["recovery_receipt"])
        expected = {
            "request_id": request["request_id"],
            "canonical_trusted_root_sha256": root["sha256"],
            "canonical_path_sha256": target["sha256"],
            "target_volume_serial": target["volume_serial"],
            "target_file_id": target["file_id"],
            "recovery_receipt_binding_sha256": receipt_digest,
        }
        matches = all(record[field] == value for field, value in expected.items())
        fresh = record["issued_at_epoch_seconds"] <= now < record["expires_at_epoch_seconds"]
        ttl = record["expires_at_epoch_seconds"] - record["issued_at_epoch_seconds"] <= 300
        if not (matches and fresh and ttl and not record["consumed"]):
            return None
        return {
            "confirmation_id": confirmation_id,
            "revision": record["revision"],
            "approved_target_identity": {
                "canonical_path_sha256": record["canonical_path_sha256"],
                "volume_serial": record["target_volume_serial"],
                "file_id": record["target_file_id"],
            },
        }

    def cas_consume(self, ticket):
        with self._lock:
            record = self._records[ticket["confirmation_id"]]
            if record["consumed"] or record["revision"] != ticket["revision"]:
                return False
            record["consumed"] = True
            record["revision"] += 1
            self.consume_count += 1
            return True


class FakeOfficialSdkBoundary:
    def __init__(self):
        self._lock = Lock()
        self.before_capture_count = 0
        self.dispatch_count = 0
        self.readback_count = 0
        self.dispatch_evidence = []

    def capture_before(self):
        with self._lock:
            self.before_capture_count += 1
        return _scene_receipt("working_scene.vdf", "b" * 64, "c" * 64)

    def dispatch_restore(self, dispatch_capability):
        assert dispatch_capability["held"] is True
        with self._lock:
            self.dispatch_count += 1
            self.dispatch_evidence.append(dict(dispatch_capability))

    def readback_after(self):
        with self._lock:
            self.readback_count += 1


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
    ):
        self._lock = Lock()
        self.open_count = 0
        self.recapture_count = 0
        self.release_count = 0
        self._active_count = 0
        self.attempt_phase = attempt_phase
        self.observed_change_phase = observed_change_phase
        self.attack_kind = attack_kind
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
        return {
            "held": True,
            "dispatch_path": r"\\?\Volume{approved}\recovery\marked_take.vdf",
            "pinned_objects": self.PINNED_OBJECTS,
            "namespace_identity": {
                name: dict(identity) for name, identity in self.current_namespace_identity.items()
            },
        }

    def recapture(self, token):
        assert token["held"] is True
        with self._lock:
            self.recapture_count += 1

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

    def conflicting_replace_allowed(self):
        with self._lock:
            return self._active_count == 0

    def release(self, token):
        assert token["held"] is True
        token["held"] = False
        with self._lock:
            self.release_count += 1
            self._active_count -= 1


class FakeRestoreWorkflow:
    def __init__(self, store, sdk, guard, before_cas_barrier):
        self.store = store
        self.sdk = sdk
        self.guard = guard
        self.before_cas_barrier = before_cas_barrier
        self.conflicting_replace_observations = []

    def execute(self, request):
        ticket = self.store.trusted_lookup_and_compare(request)
        assert ticket is not None
        guard_token = self.guard.open()
        try:
            before_receipt = self.sdk.capture_before()
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
            if not self.store.cas_consume(ticket):
                result = _result("confirmation_consume_rejected")
                result["context"]["before_receipt"] = before_receipt
                return result
            self.sdk.dispatch_restore(self.guard.dispatch_capability(guard_token))
            self.sdk.readback_after()
            result = _result("succeeded")
            result["context"]["approved_target_identity"] = ticket["approved_target_identity"]
            result["context"]["after_receipt"]["target_identity"] = ticket[
                "approved_target_identity"
            ]
            after_identity_fields = result["context"]["after_receipt"]["scene_identity_fields"]
            after_identity_fields["canonical_path_sha256"] = ticket["approved_target_identity"][
                "canonical_path_sha256"
            ]
            result["context"]["after_receipt"]["scene_identity_sha256"] = _scene_identity_binding(
                after_identity_fields
            )[1]
            result["context"]["before_receipt"] = before_receipt
            return result
        finally:
            self.guard.release(guard_token)


class FakeDurableJobStore:
    def __init__(self):
        self.condition = Condition(RLock())
        self._next_generation = 1
        self.records = {}
        self.tombstones = {}
        self.reserved_job_ids = set()

    def start_generation(self):
        with self.condition:
            generation = f"{self._next_generation:016x}"
            self._next_generation += 1
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
    _INTERNAL_FIELDS = {"guard", "guard_token", "completion_event"}

    def __init__(self, durable_store=None):
        self.store = durable_store or FakeDurableJobStore()
        self.generation = self.store.start_generation()
        self._records = self.store.records
        self._next_id = 1
        self.poll_count = 0

    def create_before_host_connection(self, request, ticket, resolver):
        root = resolver.resolve(request["trusted_root"])
        target = resolver.resolve(request["file_path"])
        _, receipt_digest = _receipt_binding(request["recovery_receipt"])
        binding = {
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
                "poll_allowed": False,
                "duplicate_execution_allowed": False,
                "late_completion_disposition": "not_applicable",
                "record_revision": 1,
                "event_sequence": 0,
                "identity_tombstoned": True,
                "cancellation_requested": False,
                "cancellation_effective": False,
                "terminal_event_id": None,
                "terminal_event_digest_sha256": None,
                "guard": None,
                "guard_token": None,
                "completion_event": None,
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
    def _completion_event_for_record(cls, record):
        identity = {
            "job_id": record["job_id"],
            "job_generation": record["job_generation"],
            "operation_binding_sha256": record["operation_binding_sha256"],
            "expected_revision": record["record_revision"],
            "event_sequence": record["event_sequence"] + 1,
            "terminal_source": "official_sdk_readback",
            "completion_receipt_sha256": "1" * 64,
        }
        canonical = json.dumps(identity, separators=(",", ":"), sort_keys=True).encode()
        event = {"event_id": "rce1-" + hashlib.sha256(canonical).hexdigest(), **identity}
        event["event_digest_sha256"] = cls.digest_completion_event(event)
        return event

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

    def _write_tombstone(self, record):
        self.store.tombstones[record["job_id"]] = {
            "job_id": record["job_id"],
            "job_generation": record["job_generation"],
            "operation_binding_sha256": record["operation_binding_sha256"],
            "terminal_revision": record["record_revision"],
            "terminal_event_id": record["terminal_event_id"],
            "terminal_event_digest_sha256": record["terminal_event_digest_sha256"],
        }

    def retain_handles(self, job_id, guard, guard_token):
        with self.store.condition:
            record = self._records[job_id]
            if record["status"] in {"terminal", "terminal_not_dispatched"}:
                raise RuntimeError("terminal record is immutable")
            if record["dispatch_count"] != 0:
                raise RuntimeError("handles may only transfer before dispatch")
            record["guard"] = guard
            record["guard_token"] = guard_token
            record["handle_retention_owner"] = "trusted_adapter_local_restore_job_registry"

    def cancel_before_dispatch(self, job_id):
        return self.request_cancellation(job_id)

    def mark_dispatched(self, job_id):
        with self.store.condition:
            record = self._records[job_id]
            if record["dispatch_count"]:
                raise RuntimeError("duplicate restore dispatch forbidden")
            self._advance(
                record,
                dispatch_count=1,
                status="awaiting_late_readback",
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

    def request_cancellation(self, job_id):
        with self.store.condition:
            record = self._records[job_id]
            if record["status"] in {"terminal", "terminal_not_dispatched"}:
                return {
                    "requested": True,
                    "effective": False,
                    "disposition": "ignored_after_terminal",
                }
            if record["dispatch_count"] == 0:
                guard = record["guard"]
                guard_token = record["guard_token"]
                if guard is not None and guard_token is not None:
                    guard.release(guard_token)
                event_id, event_digest = self._terminal_event(
                    record,
                    "cancellation_before_dispatch",
                )
                self._advance(
                    record,
                    status="terminal_not_dispatched",
                    snapshot_source="cancellation_before_dispatch",
                    terminal_source="cancellation_before_dispatch",
                    cancellation_disposition="honored_before_dispatch",
                    cancellation_requested=True,
                    cancellation_effective=True,
                    handle_retention_owner="released_before_dispatch",
                    terminal_event_id=event_id,
                    terminal_event_digest_sha256=event_digest,
                    guard=None,
                    guard_token=None,
                )
                self._write_tombstone(record)
                self.store.condition.notify_all()
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

    def make_completion_event(self, job_id):
        with self.store.condition:
            record = self._records[job_id]
            if record["status"] == "terminal_not_dispatched":
                raise RuntimeError("terminal record is immutable")
            if record["completion_event"] is None:
                record["completion_event"] = self._completion_event_for_record(record)
            return dict(record["completion_event"])

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
            expected = self._completion_event_for_record(record)
            if event != expected or event.get(
                "event_digest_sha256"
            ) != self.digest_completion_event(event):
                raise RuntimeError("completion event identity rejected")
            if record["status"] != "awaiting_late_readback":
                raise RuntimeError("completion event state rejected")
            record["completion_event"] = dict(event)
            self._advance(
                record,
                status="readback_in_progress",
                event_sequence=event["event_sequence"],
            )
            return {
                "job_id": record["job_id"],
                "event_id": event["event_id"],
                "operation_binding_sha256": record["operation_binding_sha256"],
            }

    def complete_late_success(self, claim):
        with self.store.condition:
            record = self._records[claim["job_id"]]
            event = record["completion_event"]
            if (
                record["status"] != "readback_in_progress"
                or event["event_id"] != claim["event_id"]
                or record["operation_binding_sha256"] != claim["operation_binding_sha256"]
            ):
                raise RuntimeError("late completion claim rejected")
            guard = record["guard"]
            guard_token = record["guard_token"]
            if guard is None or guard_token is None:
                raise RuntimeError("late completion handle ownership rejected")
            guard.release(guard_token)
            self._advance(
                record,
                advance_event=False,
                status="terminal",
                snapshot_source="late_official_sdk_readback",
                terminal_source="official_sdk_readback",
                handle_retention_owner="released_after_terminal_readback",
                poll_allowed=False,
                late_completion_disposition="terminalized_by_official_sdk_readback",
                terminal_event_id=event["event_id"],
                terminal_event_digest_sha256=event["event_digest_sha256"],
                guard=None,
                guard_token=None,
            )
            self._write_tombstone(record)
            self.store.condition.notify_all()

    def descriptor(self, job_id):
        with self.store.condition:
            record = self._records[job_id]
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
        assert self.store.cas_consume(ticket)
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
        if late_success and descriptor["status"] == "awaiting_late_readback":
            for attempt in range(2):
                event = self.jobs.make_completion_event(job_id)
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
                result = _result("succeeded")
                result["context"]["job"] = terminal
                return result
            self.sdk.readback_after()
            self.jobs.complete_late_success(claim)
            result = _result("succeeded")
            result["context"]["job"] = self.jobs.descriptor(job_id)
            return result
        return descriptor


def test_restore_contract_is_design_only_and_fail_closed():
    contract = _contract()

    assert contract["contract_version"] == "1.6"
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
    assert consumed.cas_consume(ticket)

    assert expired.trusted_lookup_and_compare(request) is None
    assert future.trusted_lookup_and_compare(request) is None
    assert consumed.trusted_lookup_and_compare(request) is None


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
    assert store.cas_consume(ticket)

    with pytest.raises(ValueError, match="confirmation ID is immutable and nonreusable"):
        store.issue(request, authenticated=True)
    assert store.trusted_lookup_and_compare(request) is None


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
    assert authority["consume"] == "atomic_compare_and_set_unconsumed_before_dispatch"
    assert authority["state_machine"] == [
        "authenticated_issue_to_trusted_store",
        "trusted_lookup_by_confirmation_id",
        "compare_request_path_receipt_freshness_and_unconsumed",
        "open_and_pin_volume_root_full_directory_chain_and_target",
        "connect_host_and_capture_before_receipt",
        "recapture_all_pinned_handle_identities_and_target_receipt",
        "reject_any_guard_change_before_consumption",
        "atomic_compare_and_set_consume",
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
        ],
        "public_projection": "adapter_secret_hmac_sha256_v1",
    }
    async_contract = contract["async_job_contract"]
    assert async_contract["owner"] == "trusted_adapter_local_restore_job_registry"
    assert async_contract["persistence"] == "durable_atomic_store_survives_adapter_restart"
    assert async_contract["create_record"] == "before_host_connection_and_dispatch"
    assert async_contract["result_member"] == "context.job"
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
    assert async_contract["handle_ownership"] == {
        "transfer": ("request_scope_to_trusted_adapter_local_restore_job_registry_before_dispatch"),
        "retain_after_dispatch": ("through_late_official_sdk_readback_or_terminal_unknown_effect"),
        "release_before_dispatch": "cancellation_or_guard_rejection",
        "release_after_dispatch": "only_after_terminal_readback_or_terminal_unknown_effect",
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
        "success_source": "official_sdk_readback",
        "result_state": "succeeded",
        "handles": "released_after_terminal_readback",
    }
    assert async_contract["transitions"] == {
        "synchronization": "durable_store_compare_and_set_lock",
        "record_revision": "strictly_monotonic_every_record_write",
        "event_sequence": "strictly_monotonic_exact_event_order",
        "terminal_immutability": "no_writes_after_terminal",
        "readback_claim": "exact_completion_event_single_owner_before_sdk_readback",
        "readback": "exactly_once_per_job",
        "duplicate_completion": "return_existing_terminal_without_readback",
        "out_of_order_completion": "reject_without_state_change",
        "stale_snapshot_publication": "reject_against_latest_durable_revision",
    }


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
        "Exactly one read-back",
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
