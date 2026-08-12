---
name: shogun-scene
description: >-
  Inspect Vicon Shogun Post motion-capture scenes through Vicon's official local
  control-stream SDK. Use for scene metadata, subjects, markers, skeletons,
  bounded trajectory values, object hierarchy, and transforms. The same package
  includes only official Scene selection and display-property controls.
license: MIT
metadata:
  dcc-mcp:
    dcc: shogun
    layer: domain
    compatibility: "Python 3.9+; Vicon Shogun Post with the official local SDK"
    version: "0.4.0" # x-release-please-version
    tags: [motion-capture, animation, vicon, scene]
    search-hint: >-
      Vicon Shogun Post mocap scene subjects markers skeleton bones trajectory
      objects hierarchy transforms attributes channels gaps cameras calibration
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
object-detail, channel, selection, or display-property call. Attribute inspection
returns names only because values may contain production notes. Channel reads
require one explicit frame, and gap lists are bounded. Camera inspection excludes
device identifiers. The three display/selection controls are non-destructive but
can change the user's current view/selection. The Skill does not expose object
creation, removal, renaming, reparenting, raw attribute/channel writes, or
arbitrary HSL/Python. Use the separate `shogun-files` Skill for the three
explicitly bounded file mutations implemented through the official SDK.

Paths returned by tools are reduced to file names. Adapter diagnostics must not
publish SDK install directories, machine names, credentials, or full production
scene paths.
