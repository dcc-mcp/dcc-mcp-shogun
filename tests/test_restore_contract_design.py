from __future__ import annotations

import hashlib
import json
import ntpath
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

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

    def issue(self, request, *, authenticated, now=NOW_EPOCH_SECONDS):
        if not authenticated:
            raise PermissionError("authenticated operator issuance required")
        root = self.resolver.resolve(request["trusted_root"])
        target = self.resolver.resolve(request["file_path"])
        _, receipt_digest = _receipt_binding(request["recovery_receipt"])
        record = {
            "record_version": "1.0",
            "confirmation_id": request["operator_confirmation"]["confirmation_id"],
            "request_id": request["request_id"],
            "canonical_trusted_root_sha256": root["sha256"],
            "canonical_path_sha256": target["sha256"],
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
            "recovery_receipt_binding_sha256": receipt_digest,
        }
        matches = all(record[field] == value for field, value in expected.items())
        fresh = record["issued_at_epoch_seconds"] <= now < record["expires_at_epoch_seconds"]
        ttl = record["expires_at_epoch_seconds"] - record["issued_at_epoch_seconds"] <= 300
        if not (matches and fresh and ttl and not record["consumed"]):
            return None
        return {"confirmation_id": confirmation_id, "revision": record["revision"]}

    def cas_consume(self, ticket):
        with self._lock:
            record = self._records[ticket["confirmation_id"]]
            if record["consumed"] or record["revision"] != ticket["revision"]:
                return False
            record["consumed"] = True
            record["revision"] += 1
            return True


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
        "confirmation_consume_rejected",
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


def test_two_early_confirmation_lookups_have_exactly_one_cas_winner():
    request = _request()
    store = FakeTrustedConfirmationStore()
    store.issue(request, authenticated=True)
    tickets = [store.trusted_lookup_and_compare(request) for _ in range(2)]
    assert all(ticket is not None for ticket in tickets)

    with ThreadPoolExecutor(max_workers=2) as executor:
        consumed = list(executor.map(store.cas_consume, tickets))

    assert sorted(consumed) == [False, True]
    loser_result = _result("confirmation_consume_rejected")
    _validate_result(loser_result)
    assert loser_result["context"]["host_connection_performed"] is True
    assert loser_result["context"]["before_receipt"] is not None
    assert loser_result["context"]["dispatch_performed"] is False
    assert loser_result["context"]["confirmation_consumed"] is False
    assert loser_result["context"]["effect"] == "unknown"


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
        "recovery_receipt_binding_sha256",
    ]
    assert authority["consume"] == "atomic_compare_and_set_unconsumed_before_dispatch"
    assert authority["state_machine"] == [
        "authenticated_issue_to_trusted_store",
        "trusted_lookup_by_confirmation_id",
        "compare_request_path_receipt_freshness_and_unconsumed",
        "connect_host_and_capture_before_receipt",
        "atomic_compare_and_set_consume",
        "dispatch_only_for_consume_winner",
    ]


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
        "confirmation_consume_rejected",
        "exactly one winner",
        "handle-derived final path",
        "volume serial",
        "128-bit file ID",
        "dot segments",
        "reparse",
        "Unicode NFC",
        "golden vectors",
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
