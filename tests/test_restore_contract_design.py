from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

ROOT = Path(__file__).parents[1]
CONTRACT_PATH = ROOT / "docs" / "contracts" / "restore-scene.yaml"
ADR_PATH = ROOT / "docs" / "adr" / "0001-bounded-recovery-scene-restore.md"


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
            "scope": "exact_request_and_path",
            "destructive_acknowledged": True,
            "non_idempotent_acknowledged": True,
        },
    }
    request.update(overrides)
    return request


def _scene_receipt(file_name: str, digest: str):
    return {
        "observed_via": "official_sdk",
        "file_name": file_name,
        "scene_identity_sha256": digest,
    }


def _result(state: str):
    before = _scene_receipt("working_scene.vdf", "b" * 64)
    after = _scene_receipt("marked_take.vdf", "a" * 64)
    if state == "succeeded":
        return {
            "success": True,
            "message": "Recovery scene restore verified.",
            "prompt": None,
            "error": None,
            "context": {
                "receipt_version": "1.0",
                "request_id": "restore-0001",
                "state": state,
                "effect": "verified",
                "replay_allowed": False,
                "before_receipt": before,
                "after_receipt": after,
            },
        }
    return {
        "success": False,
        "message": "Recovery scene restore did not reach verified success.",
        "prompt": None,
        "error": {
            "failed": "RestoreFailed",
            "timed_out": "RestoreTimedOut",
            "indeterminate": "RestoreIndeterminate",
        }[state],
        "context": {
            "receipt_version": "1.0",
            "request_id": "restore-0001",
            "state": state,
            "effect": "unknown" if state != "failed" else "unchanged",
            "replay_allowed": False,
            "before_receipt": before,
            "after_receipt": None if state != "failed" else before,
        },
    }


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


@pytest.mark.parametrize("state", ("succeeded", "failed", "timed_out", "indeterminate"))
def test_restore_result_models_every_terminal_state_without_replay(state):
    validator = _validator("output_schema")
    result = _result(state)

    validator.validate(result)
    assert result["context"]["replay_allowed"] is False
    assert result["context"]["before_receipt"]["observed_via"] == "official_sdk"
    after = result["context"]["after_receipt"]
    assert after is None or after["observed_via"] == "official_sdk"


def test_timeout_and_indeterminate_cannot_claim_unchanged_or_verified_effects():
    validator = _validator("output_schema")

    for state in ("timed_out", "indeterminate"):
        for effect in ("unchanged", "verified"):
            invalid = _result(state)
            invalid["context"]["effect"] = effect
            with pytest.raises(ValidationError):
                validator.validate(invalid)


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
