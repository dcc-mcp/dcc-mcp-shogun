---
name: shogun-scene
description: >-
  Inspect Vicon Shogun Post motion-capture scenes through Vicon's official local
  control-stream SDK. Use for scene metadata, subjects, markers, skeletons, and
  bounded trajectory values. Do not use for scene changes or controls not verified
  through the SDK; use the shared ui-control skill as an explicit fallback.
license: MIT
metadata:
  dcc-mcp:
    dcc: shogun
    layer: domain
    compatibility: "Python 3.9+; Vicon Shogun Post with the official local SDK"
    version: "0.1.0"
    tags: [motion-capture, animation, vicon, read-only]
    search-hint: >-
      Vicon Shogun Post mocap scene subjects markers skeleton bones trajectory
      inspect read-only VDF animation data
    tools: tools.yaml
---

# Vicon Shogun Post Scene

Use these typed operations before considering UI Control. They connect only to
the local Shogun Post control stream and never expose arbitrary Python or HSL
execution.

Start with `inspect_scene`, then use the returned subject names for marker,
skeleton, or trajectory queries. This initial public contract is deliberately
read-only because the installed Shogun Post 1.19 host rejected SDK mutation
commands during real-host validation.

Paths returned by tools are reduced to file names. Adapter diagnostics must not
publish SDK install directories, machine names, credentials, or full production
scene paths.
