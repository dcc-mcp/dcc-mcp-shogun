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
                    |
                    v
single-use confirmation consumption -> one official SDK dispatch
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
- Reject symlink, junction, mount-point, or reparse-point escape; the resolved
  target must be a regular file inside the same approved scope.
- Require the complete receipt produced by the earlier `save_scene` contract:
  `receipt_version`, scene identity (`file_name`), `file_size_bytes`, `sha256`,
  and `active_scene_changed=false`. The canonical target basename, current byte
  count, and freshly computed SHA-256 must match before dispatch.
- Validate all fields before connecting to a host. A mismatch is a preflight
  failure and must not consume mutation authority.

### Capability and confirmation

- The capability is explicitly destructive, non-idempotent, single-use, and
  non-replayable. It must never run automatically as recovery or error handling.
- Require a fresh operator confirmation bound to the exact request ID and exact
  canonical path. It must separately acknowledge destructive and non-idempotent
  behavior. Consume its confirmation ID atomically immediately before dispatch;
  a consumed ID cannot authorize another call.
- A future public tool would use one typed official SDK scene-load method only.
  Active-scene identity before and after dispatch must be read through the
  official SDK. Arbitrary HSL, Python, UI automation, generic command text,
  script paths, and fallback routing remain prohibited.

### Terminal state and receipts

- Capture a bounded `before_receipt` through the official SDK before consuming
  the confirmation. Verified success requires an `after_receipt` from a fresh
  official SDK read-back and a scene identity matching the approved recovery
  receipt.
- `succeeded` is the only state allowed to report `effect=verified`.
- `failed` may report `effect=unchanged` only when read-back proves the before
  identity remains active; otherwise it reports `effect=unknown`.
- `timed_out` and `indeterminate` are terminal unknown-effect states. After the
  single dispatch, callers may poll status or inspect state, but must never
  replay the mutation or reuse the confirmation.
- Results must retain the repository's bounded success/failure envelope and
  exclude full paths, raw exception messages, SDK result text, and operator
  confirmation secrets.

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
