from __future__ import annotations

import hashlib
import json
from pathlib import Path

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


def _scene_receipt(file_name: str, identity_digest: str, file_digest: str):
    return {
        "active_scene_observed_via": "official_sdk",
        "file_evidence_observed_via": "filesystem",
        "file_name": file_name,
        "file_size_bytes": 4096,
        "sha256": file_digest,
        "scene_identity_sha256": identity_digest,
    }


def _result(state: str):
    before = _scene_receipt("working_scene.vdf", "b" * 64, "c" * 64)
    after = _scene_receipt("marked_take.vdf", "a" * 64, "a" * 64)
    common = {
        "receipt_version": "1.0",
        "request_id": "restore-0001",
        "state": state,
        "replay_allowed": False,
        "dispatch_performed": True,
        "confirmation_consumed": True,
        "approved_recovery_receipt": _request()["recovery_receipt"],
    }
    if state == "succeeded":
        return {
            "success": True,
            "message": "Recovery scene restore verified.",
            "prompt": None,
            "error": None,
            "context": {
                **common,
                "effect": "verified",
                "readback_performed": True,
                "postcondition_evidence": {
                    "active_scene_readback_performed": True,
                    "before_after_distinct": True,
                    "after_matches_approved_recovery_receipt": True,
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


def _pointer(document, pointer: str):
    value = document
    for token in pointer.lstrip("/").split("/"):
        value = value[token.replace("~1", "/").replace("~0", "~")]
    return value


def _validate_result(result):
    _validator("output_schema").validate(result)
    rules = _contract()["semantic_postconditions"][result["context"]["state"]]
    errors = []
    for left, right in rules.get("equal", []):
        if _pointer(result, left) != _pointer(result, right):
            errors.append(f"{left} must equal {right}")
    for left, right in rules.get("not_equal", []):
        if _pointer(result, left) == _pointer(result, right):
            errors.append(f"{left} must not equal {right}")
    if errors:
        raise ValidationError("; ".join(errors))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_path(value: str) -> str:
    return value.replace("\\", "/").lower()


def _receipt_binding(receipt) -> str:
    return _sha256_text(json.dumps(receipt, separators=(",", ":"), sort_keys=True))


def _confirmation_record(request=None, *, now=NOW_EPOCH_SECONDS):
    request = request or _request()
    return {
        "record_version": "1.0",
        "confirmation_id": request["operator_confirmation"]["confirmation_id"],
        "request_id": request["request_id"],
        "canonical_trusted_root_sha256": _sha256_text(_canonical_path(request["trusted_root"])),
        "canonical_path_sha256": _sha256_text(_canonical_path(request["file_path"])),
        "recovery_receipt_binding_sha256": _receipt_binding(request["recovery_receipt"]),
        "issued_at_epoch_seconds": now - 30,
        "expires_at_epoch_seconds": now + 270,
        "destructive_acknowledged": True,
        "non_idempotent_acknowledged": True,
        "consumed": False,
    }


def _confirmation_authorized(request, record, *, now=NOW_EPOCH_SECONDS):
    authority = _contract()["confirmation_authority"]
    Draft202012Validator.check_schema(authority["issuance_record_schema"])
    Draft202012Validator(authority["issuance_record_schema"]).validate(record)
    expected = {
        "confirmation_id": request["operator_confirmation"]["confirmation_id"],
        "request_id": request["request_id"],
        "canonical_trusted_root_sha256": _sha256_text(_canonical_path(request["trusted_root"])),
        "canonical_path_sha256": _sha256_text(_canonical_path(request["file_path"])),
        "recovery_receipt_binding_sha256": _receipt_binding(request["recovery_receipt"]),
    }
    return (
        authority["store"] == "trusted_adapter_local_store"
        and authority["caller_supplied_records_accepted"] is False
        and all(record[field] == value for field, value in expected.items())
        and record["issued_at_epoch_seconds"] <= now < record["expires_at_epoch_seconds"]
        and record["expires_at_epoch_seconds"] - record["issued_at_epoch_seconds"]
        <= authority["max_ttl_seconds"]
        and record["consumed"] is False
        and record["destructive_acknowledged"] is True
        and record["non_idempotent_acknowledged"] is True
        and authority["consume"] == "atomic_compare_and_set_unconsumed_before_dispatch"
    )


def test_restore_contract_is_design_only_and_fail_closed():
    contract = _contract()

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
    validator = _validator("output_schema")

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
    record = _confirmation_record(original)
    changed = _request(**mutation)

    assert _confirmation_authorized(original, record)
    assert not _confirmation_authorized(changed, record)


def test_confirmation_rejects_expired_future_and_consumed_records():
    request = _request()

    expired = _confirmation_record(request)
    expired["expires_at_epoch_seconds"] = NOW_EPOCH_SECONDS
    future = _confirmation_record(request)
    future["issued_at_epoch_seconds"] = NOW_EPOCH_SECONDS + 1
    consumed = _confirmation_record(request)
    consumed["consumed"] = True

    assert not _confirmation_authorized(request, expired)
    assert not _confirmation_authorized(request, future)
    assert not _confirmation_authorized(request, consumed)


def test_confirmation_authority_defines_trusted_issuance_lookup_compare_and_consume():
    authority = _contract()["confirmation_authority"]

    assert authority["issuer"] == "authenticated_operator_confirmation_service"
    assert authority["store"] == "trusted_adapter_local_store"
    assert authority["caller_supplied_records_accepted"] is False
    assert authority["path_canonicalization"] == "windows_final_path_casefold_utf8_v1"
    assert authority["receipt_canonicalization"] == "sorted_compact_json_utf8_v1"
    assert authority["lookup_key"] == "confirmation_id"
    assert authority["comparison_fields"] == [
        "request_id",
        "canonical_trusted_root_sha256",
        "canonical_path_sha256",
        "recovery_receipt_binding_sha256",
    ]
    assert authority["consume"] == "atomic_compare_and_set_unconsumed_before_dispatch"


def test_result_validation_requires_schema_and_semantic_postconditions():
    assert _contract()["result_validation_pipeline"] == [
        "draft2020_schema",
        "semantic_postconditions",
    ]


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
        "authenticated operator confirmation service",
        "trusted adapter-local store",
        "canonical-path digest",
        "freshness and expiry",
        "atomic compare-and-set",
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
