---
name: shogun-timeline
description: >-
  Inspect and explicitly adjust Vicon Shogun Post timeline state through Vicon's
  official Timeline SDK interface. Use for current frame, play and animation
  ranges, selected time ranges, frame rate, and timecode state. Do not use for
  data processing; use shogun-processing with an explicit bounded range instead.
license: MIT
metadata:
  dcc-mcp:
    dcc: shogun
    layer: domain
    compatibility: "Python 3.9+; capability-gated Vicon Shogun Post Timeline SDK"
    version: "0.2.0" # x-release-please-version
    tags: [motion-capture, animation, vicon, timeline]
    search-hint: >-
      Vicon Shogun Post timeline current frame play range selected time ranges
      animation range frame rate timecode
    tools: tools.yaml
---

# Vicon Shogun Post Timeline

Start with `inspect_timeline`. The adapter calls only Vicon's closed `Timeline`
interface; it does not expose arbitrary HSL or Python execution.

Frame setters require explicit, non-negative values. `select_time_range` replaces
the current selection by default. Play and animation range setters attempt to
restore the prior values if the second SDK setter fails. Playback start/stop are
typed wrappers over `Timeline.Play` and `Timeline.Stop`; they do not change motion
data.

This Skill is capability-gated because a Shogun host can ship an SDK surface but
reject a command for that host application. Such rejections return a bounded
error without paths, tracebacks, or fallback UI actions.
