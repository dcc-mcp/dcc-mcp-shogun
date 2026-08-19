---
name: shogun-editing
description: >-
  Safely edit Vicon Shogun Post marker trajectories and channel keys through
  Vicon's official SDK. Use for bounded Graph and Marker Editing cleanup after
  inspecting scene objects, channel samples, gaps, and selected time ranges.
  Do not use for reconstruction, labeling, solving, or retargeting; use
  shogun-processing for those workflows.
license: MIT
metadata:
  dcc-mcp:
    dcc: shogun
    layer: domain
    compatibility: "Python 3.9+; capability-gated Vicon Shogun Post 1.19 SDK"
    version: "0.8.3" # x-release-please-version
    tags: [motion-capture, animation, vicon, cleanup, destructive]
    search-hint: >-
      Vicon Shogun Post Graph Marker Editing cleanup trajectory sample channel
      keys selected ranges FIR weighted average filter noise smoothing
    tools: tools.yaml
---

# Vicon Shogun Post Editing

Inspect the target with `shogun-scene` and select an explicit range with
`shogun-timeline` before changing keys or filtering data. The tools call only
Vicon's official trajectory, Channel, FIRFilter, and WeightedAverageFilter SDK
contracts. Arbitrary HSL/Python and unbounded `DeleteAllKeys` are not exposed.

`set_trajectory_sample` changes exactly one subject/marker/frame and verifies
the value returned by Shogun. `select_channel_keys` changes selection state
only. `delete_channel_keys` accepts one explicit frame or the already selected
keys. Filters default to selected keys only; setting `selected_keys_only=false`
explicitly applies the filter to the whole target channel.

Filtering and key deletion change motion data. Save a recovery copy first,
validate the affected samples after every call, and run the final solve over the
whole play range after cleanup as required by Vicon's Shogun Post workflow.
