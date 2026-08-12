---
name: shogun-processing
description: >-
  Inspect processing settings and run explicit, bounded Vicon Shogun Post
  reconstruction, ROM labeling, subject calibration, labeling, occlusion
  fixing, solving, QuickPost, or retargeting through Vicon's official Offline
  SDK interface. Use only after inspecting the scene and choosing an explicit
  supported time scope. Never silently defaults to the complete play range.
license: MIT
metadata:
  dcc-mcp:
    dcc: shogun
    layer: domain
    compatibility: "Python 3.9+; capability-gated Vicon Shogun Post Offline SDK"
    version: "0.2.0" # x-release-please-version
    tags: [motion-capture, animation, vicon, processing]
    search-hint: >-
      Vicon Shogun Post reconstruct label ROM calibrate labeling solving subject
      auto label fix occlusion solve QuickPost retarget processing settings ranges
    tools: tools.yaml
---

# Vicon Shogun Post Processing

Start with `shogun-scene__inspect_scene`, then inspect the relevant processing
settings. For `selected_ranges`, first establish an explicit range with
`shogun-timeline__select_time_range`.

Every processing tool is a closed wrapper over one official `Offline` method.
No arbitrary HSL or Python is accepted. General processing and QuickPost expose
only `current_frame` and `selected_ranges`. ROM labeling and calibration expose
the exact ranges documented for those vendor methods, but always require the
caller to state `play_range` explicitly; it is never an implicit default.

Processing changes scene data and can affect many keys. Save to a new VDF path
before a production run. A host may expose the SDK surface yet reject a command;
the adapter reports that capability failure without UI fallback or partial-success
claims.
