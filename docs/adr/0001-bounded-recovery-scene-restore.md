# ADR-0001: Bound recovery-scene restore before implementation

Status: Proposed

## Context

Issue #36 asks whether a typed recovery-scene restore can safely follow the
existing recovery-copy workflow. PR #39 added a path-redacted `save_scene`
receipt with a VDF base name, positive byte count, SHA-256 digest, and active
scene change flag. PR #40 strengthened host liveness, but liveness is not proof
that a scene mutation completed or had the intended effect.

Scene replacement is destructive and non-idempotent. A timeout, transport loss,
or liveness probe failure after dispatch cannot distinguish an unchanged scene
from a completed restore. Automatic retry could therefore replace the scene a
second time or apply an already-consumed operator decision to different state.

No restore implementation is authorized by this ADR or Issue #36. The proposed
machine contract is isolated in `docs/contracts/restore-scene.yaml`; it is not a
Skill manifest, does not register a tool, and does not add runtime, SDK, HSL,
pipeline, or UI behavior.

## Decision

Any later implementation proposal must preserve this bounded sequence:

```text
prior recovery receipt + exact operator confirmation
                    |
                    v
trusted-root containment and receipt preflight
       | reject: preflight_rejected, no host connection
       v pass
trusted confirmation lookup/compare -> official SDK before receipt
                    |
                    v
atomic single-use confirmation consumption
       | CAS loss: confirmation_consume_rejected, no dispatch
       v exactly one winner
one official SDK dispatch
                    |
                    v
poll/read only; never replay -> official SDK active-scene read-back
                    |
                    v
before/after terminal receipt or explicit unknown effect
```

### Preflight and path authority

- Accept one absolute `.vdf` and one absolute operator-approved trusted root.
- Resolve the root and target through the native filesystem before connection.
  Fail closed unless the canonical target has the canonical root as its parent
  or ancestor. A lexical prefix is insufficient for trusted-root containment.
- Collapse dot segments before opening each path, inspect every reparse point,
  and use the handle-derived final path from
  `GetFinalPathNameByHandleW`, not from caller text. Record the volume serial and
  128-bit file ID, and reject a symlink, junction, mount-point, device-identity
  change, or reparse escape. The resolved target must be a regular file inside
  the resolved approved root on the same volume.
- The normative path binding is `windows-final-path-v1`, followed by LF-delimited
  `volume_serial`, `file_id`, and `path` fields. Strip only the native extended
  path prefix, normalize separators and Unicode NFC, and apply Windows
  case-insensitive comparison without changing non-ASCII code points. Hash the
  UTF-8 payload. The contract's golden vectors define the exact bytes and cover
  a Windows alias with dot segments, a Unicode filename, and a rejected
  reparse/device alias.
- Require the complete receipt produced by the earlier `save_scene` contract:
  `receipt_version`, scene identity (`file_name`), `file_size_bytes`, `sha256`,
  and `active_scene_changed=false`. The canonical target basename, current byte
  count, and freshly computed SHA-256 must match before dispatch.
- Validate all fields before connecting to a host. A mismatch is a preflight
  failure and must not consume mutation authority. `preflight_rejected` is the
  legal terminal result for every precondition failure and records
  `host_connection_performed=false`, `dispatch_performed=false`,
  `confirmation_consumed=false`, and null before/after receipts.

### Capability and confirmation

- The capability is explicitly destructive, non-idempotent, single-use, and
  non-replayable. It must never run automatically as recovery or error handling.
- Accept only a confirmation ID in a restore request. The corresponding signed
  issuance record must come from an authenticated operator confirmation service
  and reside in a trusted adapter-local store; caller-supplied records are not
  authority. The record binds the confirmation to the request ID, a canonical
  trusted-root digest, a canonical-path digest, and a canonical digest of the
  complete recovery receipt. The receipt binding normalizes every string to
  Unicode NFC, includes only the fixed receipt members, sorts keys, emits
  integers and JSON booleans, and serializes as UTF-8 canonical JSON with
  `ensure_ascii=false`, comma/colon separators, and no whitespace before
  SHA-256. Its Unicode golden vector is normative across implementations.
- Enforce freshness and expiry with a maximum five-minute issuance lifetime.
  Authenticated issuance writes a private, revisioned record to the trusted
  adapter-local store. Lookup by confirmation ID from that store, then compare
  every binding plus both destructive acknowledgements before connection;
  caller-owned dictionaries cannot substitute for this lookup. A mismatch,
  expired record, future record, or already-consumed record discovered at that
  stage produces `preflight_rejected`.
- After connecting and capturing the official SDK `before_receipt`, immediately
  before dispatch, use an atomic compare-and-set on the stored revision to
  change unconsumed to consumed. Concurrent consumers can both pass the early
  lookup, but exactly one winner may consume and dispatch. A CAS loser returns
  `confirmation_consume_rejected`: host connection and before capture are true,
  dispatch and consumption are false, the bounded before receipt is present,
  and the after receipt is null. This state is not a preflight failure and must
  never retry.
- A future public tool would use one typed official SDK scene-load method only.
  Active-scene identity before and after dispatch must be read through the
  official SDK. Arbitrary HSL, Python, UI automation, generic command text,
  script paths, and fallback routing remain prohibited.

### Terminal state and receipts

- Capture a bounded `before_receipt` through the official SDK before consuming
  the confirmation. Verified success requires an `after_receipt` from a fresh
  official SDK read-back. Both receipts include SDK scene identity and bounded
  filesystem name, byte-count, and SHA-256 evidence.
- `confirmation_consume_rejected` is the only connected but not dispatched
  terminal state. It reports `effect=unknown` because the winning concurrent
  consumer may dispatch after this request's before capture; it does not claim
  an after read-back.
- `succeeded` is the only state allowed to report `effect=verified`. Its
  machine-readable `semantic_postconditions` require distinct before/after
  scene identities and require the after name, bytes, and digest to equal the
  approved recovery receipt. The branch also requires const-true evidence for
  official SDK read-back, distinct identities, and approved-receipt matching.
- `failed_unchanged` requires a completed official SDK read-back and exact
  equality of before/after identity, name, bytes, and digest. It is the only
  dispatched failure allowed to report `effect=unchanged`, and it requires
  const-true read-back and before/after equality evidence.
- `failed_unknown` requires `effect=unknown`, no claimed read-back, and a null
  after receipt. It cannot inherit the evidence privileges of
  `failed_unchanged`.
- `timed_out` and `indeterminate` are terminal unknown-effect states. After the
  single dispatch, callers may poll status or inspect state, but must never
  replay the mutation or reuse the confirmation.
- Results must retain the repository's bounded success/failure envelope and
  exclude full paths, raw exception messages, SDK result text, and operator
  confirmation secrets. Validation is a mandatory two-stage pipeline: first the
  Draft 2020-12 schema, then the JSON-pointer `semantic_postconditions`.
  Structural schema validation alone is insufficient because standard JSON
  Schema cannot compare two dynamic receipt values.

## Real-host acceptance boundary

Contract and CI validation do not prove a real restore. Real-host acceptance
requires a separate operator authorization, one disposable marked take, and an
explicitly approved path scope containing no production scene. Acceptance must
read the marked identity before and after through the official SDK and verify
the approved recovery file's bytes and digest. No production path, arbitrary
HSL/Python, UI action, process control, pidfile, gateway change, or automatic
recovery is part of this ADR.

## Consequences

### Positive

- Path authority, receipt identity, confirmation, dispatch, and verification
  are separate fail-closed gates.
- Preflight rejection, confirmation-consume rejection, verified effects, proven
  unchanged effects, and unknown effects have disjoint executable schema
  branches.
- Timeout and liveness ambiguity cannot silently become a retry or success.
- The design reuses PR #39 evidence without treating PR #39 or PR #40 as proof
  of a scene replacement.

### Negative

- A future implementation needs durable single-use confirmation state and a
  stable official SDK scene-load capability before it can be proposed.
- Hashing the approved VDF twice adds bounded I/O and can reject a file changed
  between recovery save and restore.

### Neutral

- Existing Skills, public tool counts, runtime behavior, and bilingual agent
  instructions remain unchanged because this ADR is design-only.

## Alternatives considered

- **Automatic restore after a failed mutation:** rejected because failure and
  timeout can have unknown effects and do not grant destructive authority.
- **Retry the restore after timeout:** rejected because the operation is
  non-idempotent and the first dispatch may have completed.
- **Trust an arbitrary absolute VDF path:** rejected because an absolute path is
  not an operator-approved scope and does not prevent reparse escape.
- **Use arbitrary HSL, Python, or UI fallback:** rejected because those routes
  broaden authority and cannot preserve the typed receipt boundary.
- **Treat process liveness as restore success:** rejected because PR #40 proves
  only bounded process identity/liveness observations, not scene effects.

## References

- Refs #36
- PR #39: verifiable recovery-copy receipt
- PR #40: sidecar liveness and original-process identity
- `docs/contracts/restore-scene.yaml`
