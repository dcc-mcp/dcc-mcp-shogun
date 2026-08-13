# Official Shogun Post SDK coverage

This matrix maps the public adapter surface to Vicon's official Shogun Post
workflow and SDK families. It is intentionally workflow-oriented: one DCC-MCP
tool may combine several low-level SDK calls with validation and rollback, and
not every SDK property should become a public tool.

Sources:

- [Shogun Post 1.18 documentation](https://vicon-help.atlassian.net/wiki/spaces/ShogunPost118/overview)
- [Python scripting with Vicon Shogun Post](https://vicon-help.atlassian.net/wiki/spaces/ShogunPost118/pages/544283341/Python%2Bscripting%2Bwith%2BVicon%2BShogun%2BPost)
- Vicon Shogun Post 1.19 installed Python SDK and Getting Started manual

## Implemented surface

| Skill | Tools | Official contract | Workflow boundary |
|---|---:|---|---|
| `shogun-scene` | 22 | `ViconShogunPost`, `Scene`, `Object`, `Channel`, camera and skeleton reads | Bounded inspection plus selection/display state |
| `shogun-timeline` | 11 | `Timeline` | Explicit frame/range/playback state |
| `shogun-processing` | 12 | `Offline` and allowlisted settings | Explicit current-frame or selected-range processing |
| `shogun-files` | 3 | `ImportFile`, `SaveFile`, `ExportFile` | Extension/size/overwrite-gated file exchange |
| `shogun-editing` | 5 | trajectory setters, `Channel`, `FIRFilter`, `WeightedAverageFilter` | One verified sample or one explicit channel; filters default to selected keys |
| `shogun-production-context` | 8 | `Scene.ActiveClip`, `Clip`, `Character` | Bounded timing and QA state plus verified allowlisted updates; identities and notes excluded |

Total: 61 typed tools across six progressively loaded Skills.

The five editing tools have been loaded and dispatched through a live Shogun
Post 1.19 instance. An empty-scene probe verified fail-closed behavior without
mutation. Successful trajectory and filtering effects still require a
non-empty disposable take and are not represented as live-supported evidence.

## Editing decisions

The Getting Started workflow uses the Graph and Marker Editing views to select
ranges, repair marker samples, remove bad keys, and filter noise. The public
contract mirrors that workflow while reducing mutation scope:

- `set_trajectory_sample` writes one subject, marker, and frame, then verifies
  the value returned by Shogun and attempts restoration if verification fails.
- `select_channel_keys` supports selected ranges, all, clear, or invert without
  changing motion values.
- `delete_channel_keys` supports one explicit frame or the already selected
  keys. The SDK's unbounded `DeleteAllKeys` method is intentionally absent.
- FIR parameters are bounded around Vicon's documented workflow, including the
  conservative cleanup defaults `LightCutoff=0.3` and `Threshold=15`.
- Both filters default to `selected_keys_only=true`; applying to a whole channel
  requires an explicit false value.

## Production-context decisions

- `set_active_clip` accepts one exact existing Clip name, verifies the official
  `Scene.ActiveClip` read-back, and restores the previous value on mismatch.
- `update_clip_timing` exposes only lock, start, offset, duration, positive time
  scale, and SMPTE alignment. Object creation, deletion, renaming, and generic
  attribute writes remain absent.
- `update_character_qa_status` exposes six Boolean workflow fields only. Artist
  identities, user/final names, priority, facing direction, and every free-form
  note remain unread and unwritable through this mutation path.
- All allowlisted updates validate every input before connecting, verify the
  resulting SDK values, and attempt reverse-order rollback on partial failure.

## Prioritized next families

| Priority | Official SDK family | Planned public boundary |
|---:|---|---|
| 1 | labeling/solving setup objects | Typed constraint and parameter recipes for retarget setup, with narrow object types and recovery copies |
| 2 | optical/video camera properties | Post-safe presentation fields; continue excluding device identifiers and capture-security configuration |
| 3 | rigid-body inspection | Bounded read-only object, marker, and solve-state summaries before any workflow-specific mutation |
| Deferred | `Database` | An isolated 1.19 read probe coincided with host termination; require reproducible stability evidence before any public tool |

## Intentionally not exposed

- arbitrary Python, HSL, or command dispatch;
- generic attribute/property setters;
- unbounded key deletion or bulk raw trajectory replacement;
- scene-object creation/removal/reparenting without a workflow-specific typed
  contract;
- paths, device identifiers, or free-form production notes in public results.
- Eclipse database access until the 1.19 host-stability signal is understood.
