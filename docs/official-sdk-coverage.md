# Official Shogun Post SDK coverage

This matrix maps the public adapter surface to Vicon's official Shogun Post
workflow and SDK families. It is intentionally workflow-oriented: one DCC-MCP
tool may combine several low-level SDK calls with validation and rollback, and
not every SDK property should become a public tool.

Sources:

- [Shogun Post 1.18 documentation](https://vicon-help.atlassian.net/wiki/spaces/ShogunPost118/overview)
- [Python scripting with Vicon Shogun Post](https://vicon-help.atlassian.net/wiki/spaces/ShogunPost118/pages/544283341/Python%2Bscripting%2Bwith%2BVicon%2BShogun%2BPost)
- [Use Vicon ShogunPost SDK interfaces](https://vicon-help.atlassian.net/wiki/spaces/ShogunPost116/pages/341120839/Use%2BVicon%2BShogunPost%2BSDK%2Binterfaces)
- [Automatically set up a retarget](https://vicon-help.atlassian.net/wiki/spaces/ShogunPost118/pages/544277621)
- [Create constraints script](https://vicon-help.atlassian.net/wiki/spaces/ShogunPost118/pages/544279197/createConstraintsScript)
- [Rigid-body command](https://vicon-help.atlassian.net/wiki/spaces/Shogun111/pages/13208318/rigidBody)
- [Find non-rigid bodies](https://vicon-help.atlassian.net/wiki/spaces/ShogunPost118/pages/544279719/findNonRigid)
- Vicon Shogun Post 1.19 installed Python SDK and Getting Started manual

## Implemented surface

| Skill | Tools | Official contract | Workflow boundary |
|---|---:|---|---|
| `shogun-scene` | 27 | `ViconShogunPost`, `Scene`, `Object`, `Channel`, setup, rigid-body, camera, and skeleton reads | Bounded inspection plus selection/display state |
| `shogun-timeline` | 11 | `Timeline` | Explicit frame/range/playback state |
| `shogun-processing` | 12 | `Offline` and allowlisted settings | Explicit current-frame or selected-range processing |
| `shogun-files` | 3 | `ImportFile`, `SaveFile`, `ExportFile` | Extension/size/overwrite-gated file exchange |
| `shogun-editing` | 5 | trajectory setters, `Channel`, `FIRFilter`, `WeightedAverageFilter` | One verified sample or one explicit channel; filters default to selected keys |
| `shogun-production-context` | 8 | `Scene.ActiveClip`, `Clip`, `Character` | Bounded timing and QA state plus verified allowlisted updates; identities and notes excluded |
| `shogun-pipeline` | 1 | `ViconShogunPost.HSL` | Operator-allowlisted command identifier plus one fixed, fully typed production signature |

Total: 67 typed tools across seven progressively loaded Skills.

Wheel-installed and public-PyPI adapters registered all 27 `shogun-scene` tools
in live Shogun Post 1.19 hosts. In an initialized 100-frame blank session,
`inspect_scene`, `list_scene_objects`, `list_rigid_bodies`, and
`list_video_cameras` completed successfully with empty, bounded results.
Missing-object detail probes returned sanitized `ControlError` results.

A separate fresh zero-frame placeholder session accepted `inspect_scene` but
rejected the official Scene object-list commands with the same bounded
`ControlError`. A follow-up inspection completed and the exact host process
remained available. This state is not reported as an empty object inventory.
Successful object-detail reads still require a disposable non-empty scene.

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

## Setup, rigid-body, and camera decisions

- Setup inspection accepts only exact `LabelingSetup` or `SolvingSetup` objects.
  It lists existing static/dynamic parameter values and priors, but returns only
  `has_expression` for expression-backed values so retarget recipes are not
  copied into agent output.
- Parameter creation, deletion, renaming, and expression mutation remain absent.
  This avoids an ambiguous dynamic-parameter creation return type in the 1.19
  SDK and keeps recovery-copy workflows operator-owned.
- Rigid-body inspection uses the official `RigidBody` Scene type filter, reads
  transforms at one explicit frame, and bounds attached Marker children.
- `VideoCamera` inspection exposes calibration plus image inversion and
  sub-sampling. Device identifiers, firmware, capture paths, and video-file
  metadata remain excluded.

## Prioritized next families

| Priority | Official SDK family | Planned public boundary |
|---:|---|---|
| 1 | setup-constraint inspection | Exact `LabelingConstraint`/`SolvingConstraint` summaries after non-empty-scene stability evidence |
| 2 | labeling clusters and bones | Bounded marker/association summaries without creation or generic property mutation |
| 3 | rigid-body quality analysis | Read-only rigidity/tolerance summaries when the official object API exposes stable values |
| Deferred | `Database` | An isolated 1.19 read probe coincided with host termination; require reproducible stability evidence before any public tool |

## Intentionally not exposed

- arbitrary Python, HSL source, or unallowlisted command dispatch;
- generic attribute/property setters;
- unbounded key deletion or bulk raw trajectory replacement;
- scene-object creation/removal/reparenting without a workflow-specific typed
  contract;
- paths, device identifiers, or free-form production notes in public results.
- Eclipse database access until the 1.19 host-stability signal is understood.
