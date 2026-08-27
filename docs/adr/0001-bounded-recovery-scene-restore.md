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
full Windows namespace chain remains pinned
       | change: target_guard_rejected, no consume or dispatch
                    v
atomic trusted-time, generation, request, target, receipt revalidation and consumption
       | CAS loss: confirmation_consume_rejected, no dispatch
       v exactly one winner
durable dispatch-uncertain reservation -> one official SDK path dispatch
       | crash/transport ambiguity: retain handles, poll only, never redispatch
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
- Reject alternate-data-stream syntax both before opening and in every
  handle-derived final path. Reject a pre-existing file symlink or directory
  junction even when its current target happens to resolve inside the trusted
  root. Because an NTFS hardlink can give the same immutable file identity an
  unapproved name outside the trusted root, this design accepts only a target
  whose handle reports exactly one hardlink. That deliberately strict rule
  makes cross-root hardlink aliases fail closed rather than leaving their
  authority undefined.
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
- Reject a file larger than the approved 8 GiB ceiling using the size obtained
  from the retained target handle before hashing or buffering any bytes. Hash
  allowed targets with streaming SHA-256 in fixed 64 KiB chunks and verify the
  exact streamed byte count. Guarded official-SDK completion receipts are also
  bounded to 64 KiB and hashed as a canonical stream rather than accumulated
  as one unbounded result value.
- The official SDK consumes a path, so holding only the target file handle does
  not close path-dispatch TOCTOU. Before the first namespace identity capture,
  open and retain the full directory chain from the volume root through the
  trusted root and every target ancestor, plus the target file. Directory opens
  use `CreateFileW`, `FILE_READ_ATTRIBUTES`, `FILE_FLAG_BACKUP_SEMANTICS`,
  `FILE_FLAG_OPEN_REPARSE_POINT`, `OPEN_EXISTING`, and only
  `FILE_SHARE_READ`. The target open adds `GENERIC_READ`. Treat an incompatible
  existing writer as rejection; the retained share contract denies conflicting
  write, delete, rename, junction retargeting, and replacement opens on every
  path component.
- Derive the SDK argument as a handle-backed volume-GUID path and keep the
  complete chain pinned through path dispatch and terminal official SDK
  read-back (or an unknown-effect terminal result). A drive-letter path, caller
  spelling, or path reconstructed after releasing an ancestor is not dispatch
  authority.
- Bind the volume root, trusted root, every intermediate directory, and target
  to a captured tuple of handle-derived volume-GUID final path, volume serial,
  128-bit file ID, file attributes, and reparse tag. Recapture that complete
  tuple and the target bytes immediately before and after every SDK path-adapter
  open. The adapter accepts the retained chain capability, not a bare path; its
  independently reopened object must equal the confirmed target identity and
  digest before any read-back can be trusted.
- Revalidate all pinned directory and target identities after the official SDK
  before receipt is captured, after recapturing target bytes and digest, and
  immediately before confirmation CAS. Dispatch entry is the final
  pre-consumption checkpoint: it must establish that every pin is still held
  before CAS can consume authority. The executable adversarial matrix tries
  namespace, junction, parent-directory, and same-content replacement swaps at
  preflight, recapture, CAS, and dispatch. Attempts while the chain is pinned
  must be blocked; any observed pre-dispatch identity or receipt change fails
  closed without consuming or dispatching.
- A real Windows filesystem harness retains the volume root, every directory
  component, and the target with native `CreateFileW` handles while a separate
  path adapter reopens the volume-GUID path. It compares the independently
  opened volume serial and 128-bit file ID with the confirmed target, and reads
  the bytes through that new handle. Target, parent, namespace, real NTFS
  junction, pre-existing symlink/junction, alternate-data-stream, hardlink, and
  same-content replacement attacks must fail while retained and the adapter
  must load the confirmed identity. Control operations repeat
  after the retained handles are released; they must then succeed and make the same
  path resolve to a different file identity. This harness never invokes Shogun
  and therefore proves Windows path mechanics, not official SDK compatibility.
- A false `CloseHandle` return is not itself proof that the numeric handle is
  still owned. Probe only for independent proof that the value is closed. A
  valid numeric value, even one that resolves to the same captured file identity,
  may be a different handle created after immediate value reuse; the available
  Windows APIs provide no generation proof tying it to the original open. Treat
  that case as indeterminate, remove it from retry ownership, and quarantine it
  without closing a possible later owner or claiming release. Cleanup diagnostics
  never replace an established primary operation outcome.
- A detected change after host connection returns `target_guard_rejected` with
  unknown effect, the bounded before receipt, null after receipt, and both
  confirmation consumption and SDK dispatch false. The executable invariant is
  `consume_count == dispatch_count == 0` for every such trace.
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
  trusted-root digest, a canonical-path digest, the target volume serial and
  128-bit file ID, and a canonical digest of the complete recovery receipt.
  The receipt binding normalizes every string to
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
- Every issuer instance uses one shared durable atomic confirmation store that
  survives authority restarts. Issuance is an atomic insert-if-absent that
  creates both the private issuance record and a permanent insert-only
  tombstone. Concurrent issuers of the same ID therefore have exactly one
  winner. A confirmation ID is an immutable,
  permanently nonreusable identity: neither an unconsumed nor consumed record
  may be overwritten, reset, or deleted to authorize another request. Any new
  authorization requires a newly generated confirmation ID; duplicate issuance
  fails closed. Expired and consumed IDs remain as durable tombstones so record
  pruning cannot make an old identifier issuable again.
- After connecting and capturing the official SDK `before_receipt`, immediately
  before dispatch, use one atomic compare-and-set critical section to obtain
  trusted current time and revalidate expiry, maximum TTL, authority generation,
  record revision, every request/path/recovery-receipt binding, the freshly
  guarded target identity/size/streaming digest, both destructive
  acknowledgements, and the unconsumed bit before changing unconsumed to
  consumed. Expiry between lookup and consume therefore loses authority rather
  than inheriting the earlier freshness decision. Concurrent consumers can both pass the early
  lookup, but exactly one winner may consume and dispatch. A CAS loser returns
  `confirmation_consume_rejected`: host connection and before capture are true,
  dispatch and consumption are false, the bounded before receipt is present,
  and the after receipt is null. This state is not a preflight failure and must
  never retry.
- The executable concurrency invariant is
  `consume_count == dispatch_count == 1` for two or more callers that passed an
  early lookup for one confirmation. Every caller runs lookup, before capture,
  CAS, and conditional dispatch; the losing workflow itself constructs
  `confirmation_consume_rejected` and never reaches the SDK dispatch boundary.
- A future public tool would use one typed official SDK scene-load method only.
  Active-scene identity before and after dispatch must be read through the
  official SDK. Arbitrary HSL, Python, UI automation, generic command text,
  script paths, and fallback routing remain prohibited.

### Asynchronous job ownership

- Create an immutable identity and revisioned record in a durable, atomic,
  trusted adapter-local restore job registry before host connection or
  dispatch. A fresh registry process obtains a durable monotonic generation;
  job identity is derived from that generation, an atomically reserved
  sequence, and the immutable operation-binding digest. Reservation immediately
  creates a permanent tombstone, so restart, pruning, or terminal completion
  can never make a prior job ID reusable. Its operation-binding digest covers
  the request ID, confirmation ID and revision, trusted-root and target
  identity, and recovery-receipt digest.
- Raw job generation, caller request ID, operation binding, completion-event
  identity, scene/take/operator names, paths, and before/after/approved receipts
  remain only in the private audit record. The public result is a complete
  adapter-secret HMAC projection: it exposes a separately domain-separated
  public job handle, request correlation, generation, operation-binding,
  terminal-event, and receipt/observation projections plus bounded lifecycle
  enums and counters. It never copies a private audit object into a public
  context.
- `jobs_get_status` accepts only one exact `job_id`. It performs a trusted
  registry lookup and never dispatches, retries, or reconstructs the restore
  request. Every result binds `context.request_id` to the job's request ID, and
  a job permits at most one dispatch for its lifetime.
- For cancellation before dispatch, terminate the job without host connection,
  confirmation consumption, or SDK dispatch and release any request-owned
  handles. For cancellation after dispatch, do not abort, retry, or claim a
  terminal effect: the operation continues under the same job, polling remains
  available, and the registry retains the full pinned handle chain.
- Persist `cancellation_requested`, `cancellation_effective`, and a typed
  disposition separately. A pre-dispatch request is effective; a post-dispatch
  request is recorded but cannot abort or duplicate the operation. A request
  after any terminal state returns `ignored_after_terminal` without writing the
  terminal record.
- After confirmation consumption but before calling the irreversible SDK,
  durably CAS the job to `dispatch-uncertain`, bind that reservation to the
  exact job generation, operation, confirmation, target, and receipt, and
  transfer the retained handle chain to the registry. Only that reservation may
  enter the SDK call, and it authorizes one attempt. `dispatch_count` counts an
  SDK call whose return was durably confirmed; a crash after call entry may
  therefore retain count zero while still being possible dispatch. Recovery
  must never classify such a record as terminal-not-dispatched or safely retry
  it. Without an SDK transaction or idempotency key this contract promises
  at-most-once execution, not exactly-once completion.
- Timeout and transport loss after dispatch have the same non-replay boundary.
  They report a null terminal source and transfer handle-retention ownership to
  the registry. A late official SDK read-back may terminalize only that exact
  job and operation binding; only then may it report success and release the
  retained handles. The terminal signal is a typed completion event bound to
  the exact job ID, durable generation, immutable operation binding, expected
  record revision, next event sequence, terminal source, and completion-receipt
  digest derived from the actual official-SDK completion observation. Its exact
  event ID and canonical digest are checked before one caller can claim SDK
  read-back ownership. The durable read-back claim owner is an adapter-secret
  HMAC over the job, event, operation, retained guard, durable claim generation,
  claimed record revision, and next fence revision. That owner performs a fresh
  official-SDK scene read-back plus guarded filesystem receipt capture and
  revalidates every binding. Immediately before the terminal commit it must
  immediately recapture the exact retained guard, then CAS the exact current
  owner, claim generation, and fence revision. A stale, foreign or replaced
  claim or guard fails closed without committing and without releasing another
  owner's guard. While the exact claim fence and guard ownership are still
  current, the adapter first atomically writes `cleanup_pending`, bound by
  digest to the job, event, operation, and exact guard owner/generation. Only
  then may it attempt release. A failure before release is attempted can leave the
  exact guard with its registry owner. Once `CloseHandle` returns false, the
  typed, redacted close observation is only independently verified closed or
  indeterminate; numeric validity and same-file identity cannot prove the original
  handle generation. The cleanup protocol preserves the primary restore outcome.
  A guard retained before any close attempt remains with the exact registry owner;
  an indeterminate numeric value moves to a non-retry quarantine and is never
  described as released. It never claims that a guard was released without an
  independent closed observation. A crash between release and disposition persistence is
  restart-recoverable from the exact pending record. Terminalization retains a
  durable cleanup-commit marker until the terminal record and exact idempotent
  tombstone are durable and `notify_all` has actually returned. Before attempting
  notification it persists only a replayable pending intent, never a completion
  flag. A crash after that intent but before or during notification therefore
  retries wakeup on restart. A crash after wakeup but before marker removal may
  notify again, providing at-least-once delivery without a second dispatch or
  read-back.
  A cancellation arriving while that claim owns read-back is written as a
  durable, HMAC-bound claim-bound cancellation intent in a separate audit
  record. It does not advance the claimed job revision. The terminal CAS folds
  the exact intent into `cancellation_requested=true` and
  `cancellation_effective=false`; a foreign intent cannot invalidate the claim.
  An approved distinct read-back succeeds; an exact before receipt is failed
  unchanged; malformed, unbounded, wrong-target, wrong-digest, or event/read-back
  mismatch is failed unknown. Repeated polling of either pending or terminal
  state cannot increment the dispatch count.
- Every durable record write uses the registry CAS lock, increments a strictly
  monotonic `record_revision`, and consumes only the next `event_sequence`.
  Terminal records are immutable. Concurrent duplicate completion events share
  one read-back claim and return the same tombstone; out-of-order or mismatched
  events fail without a state change. Cancellation racing completion is either
  recorded as requested-but-ineffective before the terminal CAS or ignored
  after it. Exactly one read-back and terminal confirmation may occur.
- A status result is publishable only if its generation, immutable binding,
  revision, event sequence, and state still equal the latest durable record.
  Thus an old pending descriptor cannot remain a valid emitted status after a
  newer terminal revision, even though its standalone JSON shape is valid.

### Terminal state and receipts

- Capture a bounded `before_receipt` through the official SDK before consuming
  the confirmation. Verified success requires an `after_receipt` from a fresh
  official SDK read-back. Both receipts include SDK scene identity and bounded
  filesystem name, byte-count, and SHA-256 evidence. Late completion cannot
  construct success from a status flag: the guarded read-back receipt itself
  must match the exact completion-receipt digest and all confirmation/job/target
  bindings.
- Synchronous completion uses the exact value returned by the official SDK
  read-back and the same guarded completion classifier as late completion. It
  must never synthesize success from approved or fixture receipt values. An
  absent, malformed, mismatched, or unverifiable actual read-back terminates as
  stable `failed_unknown`, publishes a null after receipt and fixed public
  message/error only, and keeps the raw observation in private audit data.
  SDK read-back exceptions and an unserializable read-back follow that same
  branch; their raw exception text and payload never enter the public result.
  The synchronous path creates its guard-bound durable job record in the same
  registry before confirmation CAS or SDK dispatch and uses the same
  `cleanup_pending` and restart-reconciliation protocol as late completion; it
  may not claim registry ownership from a request-local object alone.
- During late completion, an SDK exception, a resource-limit-plus-one receipt,
  or an unserializable read-back must terminalize as `failed_unknown` under the
  exact durable claim fence. The adapter persists the exact guard-bound
  `cleanup_pending` record before attempting cleanup for that claimant. It then
  writes the typed cleanup disposition, terminal record, and permanent tombstone
  and must notify every waiter even when release fails. The durable commit marker
  remains replayable across failures between terminal publication, tombstone
  persistence, durable notification intent, and actual waiter wakeup. A restart
  reconciles either a release-pending or commit-pending cleanup to those same
  terminal artifacts. A verified retained owner or indeterminate quarantine
  remains explicit in both private and public-safe lifecycle fields; raw close
  diagnostics never replace or enter the primary result. Later or duplicate
  polling returns the terminal descriptor without another read-back or dispatch.
- `scene_identity_sha256` is not an opaque implementation choice. Treat
  `GetSceneName` as an exact two-string `(scene_path, name-or-path)` tuple. For a
  saved scene, `scene_path` is an absolute Windows directory. If the second
  value is an absolute full path, its parent must equal `scene_path`; if it is a
  separator-free basename, join it to `scene_path`. Reject any other relative
  path, malformed tuple, parent contradiction, or the unsaved sentinel
  `(".", ".vdf")` before constructing a receipt.
- Derive the bounded `scene_name` as the Unicode NFC basename of the tuple's
  second value, never as that raw full path. Resolve the exact derived candidate
  to the guarded Windows final-path identity for `canonical_path_sha256`, and
  accept `GetFrameCount` only as a strict nonnegative integer. Then hash compact,
  sorted-key UTF-8 JSON containing exactly `canonical_path_sha256`,
  `frame_count`, and `scene_name`. Independent golden vectors start from raw
  full-path, basename, and decomposed-Unicode observations; rejection vectors
  cover the unsaved sentinel, malformed parent path, forward- and backslash
  relative paths, under- and over-arity tuples, non-string tuple members, and
  negative frame count; timestamps, random values, object addresses, and
  nondeterministic serialization are forbidden. The derived scene name must
  also equal the receipt's bounded `file_name`.
- `confirmation_consume_rejected` is the CAS-loss connected-but-not-dispatched
  terminal state. It reports `effect=unknown` because the winning concurrent
  consumer may dispatch after this request's before capture; it does not claim
  an after read-back. `target_guard_rejected` is the other connected,
  not-dispatched state and represents failed immediate guard recapture.
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
- `timed_out` and `indeterminate` terminate the request call with unknown effect,
  while the correlated adapter job remains pending for a terminal source. After
  the single dispatch, callers may poll status or inspect state, but must never
  replay the mutation or reuse the confirmation.
- Results must retain the repository's bounded success/failure envelope and
  use fixed state-specific public messages with `prompt=null`. Full paths, raw
  exception messages, SDK result text, operator confirmation secrets, raw
  caller IDs, scene/take/operator names, receipt objects, and terminal event
  identifiers are forbidden in every public branch; detailed diagnostics and
  raw audit evidence belong only in the trusted registry. Validation applies
  the Draft 2020-12 schema,
  global JSON-pointer semantic invariants, state `semantic_postconditions`, and
  scene-identity digest checks. Structural schema validation alone is
  insufficient because standard JSON Schema cannot compare dynamic values.

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
- Streaming the approved VDF twice adds bounded I/O and can reject a file changed
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
