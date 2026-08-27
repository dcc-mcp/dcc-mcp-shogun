from __future__ import annotations

import hashlib
import json
import ntpath
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock

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


def test_restore_contract_is_design_only_and_fail_closed():
    contract = _contract()

    assert contract["contract_version"] == "1.4"
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
        "share_mode": ["FILE_SHARE_READ"],
        "creation_disposition": "OPEN_EXISTING",
        "pinned_objects": [
            "volume_root",
            "every_directory_component_including_trusted_root",
            "target_file",
        ],
        "deny_conflicting_access": ["write", "delete", "rename", "replace"],
        "identity_fields": ["canonical_path_sha256", "volume_serial", "file_id"],
        "dispatch_path": "volume_guid_final_path_derived_from_pinned_target",
        "sdk_dispatch": "path_only_while_entire_namespace_chain_remains_pinned",
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
            "identity_assertion": (
                "reopened_volume_serial_and_128_bit_file_id_equal_confirmed_target"
            ),
            "attack_kinds": ["target", "parent", "junction", "namespace", "same_content"],
            "attack_outcome_while_retained": (
                "windows_sharing_violation_and_confirmed_identity_loaded"
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
        "identity_assertion": ("reopened_volume_serial_and_128_bit_file_id_equal_confirmed_target"),
        "attack_kinds": ["target", "parent", "junction", "namespace", "same_content"],
        "attack_outcome_while_retained": (
            "windows_sharing_violation_and_confirmed_identity_loaded"
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
        "semantic_postconditions",
        "scene_identity_digest",
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
        "CreateFileW",
        "FILE_SHARE_READ",
        "full directory chain",
        "volume-GUID path",
        "same-content replacement",
        "real Windows filesystem harness",
        "reopens the volume-GUID path",
        "after the retained handles are released",
        "target_guard_rejected",
        "atomic insert-if-absent",
        "permanently nonreusable",
        "durable tombstones",
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
