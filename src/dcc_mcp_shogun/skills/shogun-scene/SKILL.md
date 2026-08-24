---
name: shogun-scene
description: >-
  Inspect Vicon Shogun Post motion-capture scenes through Vicon's official local
  control-stream SDK. Use for scene metadata, subjects, markers, skeletons,
  bounded trajectory values, object hierarchy, setup parameters, rigid bodies,
  and camera presentation state. The same package includes only official Scene
  selection and display-property controls.
license: MIT
metadata:
  dcc-mcp:
    dcc: shogun
    layer: domain
    compatibility: "Python 3.9+; Vicon Shogun Post with the official local SDK"
    version: "0.11.0" # x-release-please-version
    tags: [motion-capture, animation, vicon, scene]
    search-hint: >-
      Vicon Shogun Post mocap scene subjects markers skeleton bones trajectory
      objects hierarchy transforms attributes channels gaps setup parameters
      rigid bodies markers optical video cameras calibration presentation
      selection visibility opacity VDF animation data
    tools: tools.yaml
---

# Vicon Shogun Post Scene

Use these typed operations before considering UI Control. They connect only to
the local Shogun Post control stream and never expose arbitrary Python or HSL
execution.

Start with `inspect_scene`, then use the returned subject names for marker,
skeleton, constraint, subject-parameter, or trajectory queries. The official
`Scene` object model is capability-gated: use `list_scene_objects` before an
object-detail, setup-parameter, channel, selection, or display-property call.
Attribute inspection returns names only because values may contain production
notes. Setup inspection accepts only `LabelingSetup` and `SolvingSetup`, and
reports whether an expression exists without returning its source text. Rigid
bodies are exact-type filtered; their details require one frame and return a
bounded attached-marker inventory. Channel reads require one explicit frame,
and gap lists are bounded. Camera inspection excludes device identifiers,
firmware, and capture/video file paths. The three display/selection controls are
non-destructive but can change the user's current view/selection. The Skill does
not expose object creation, removal, renaming, reparenting, setup-parameter
creation/expression edits, raw attribute/channel writes, or arbitrary HSL/Python.
Use the separate `shogun-files` Skill for the three explicitly bounded file
mutations implemented through the official SDK.

Paths returned by tools are reduced to file names. Adapter diagnostics must not
publish SDK install directories, machine names, credentials, or full production
scene paths.
