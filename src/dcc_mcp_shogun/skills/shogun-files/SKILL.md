---
name: shogun-files
description: >-
  Import bounded motion files and save or export Vicon Shogun Post scenes through
  the official local control-stream SDK. Use only with explicit local paths after
  inspecting the active scene. Does not expose NewScene, LoadFile, HSL, arbitrary
  Python, or trajectory mutation.
license: MIT
metadata:
  dcc-mcp:
    dcc: shogun
    layer: domain
    compatibility: "Python 3.9+; Vicon Shogun Post with the official local SDK"
    version: "0.3.0" # x-release-please-version
    tags: [motion-capture, animation, vicon, pipeline, destructive]
    search-hint: >-
      Vicon Shogun Post import BVH C3D MCP motion save VDF export FBX typed file
      operations official SDK exact local paths
    tools: tools.yaml
---

# Vicon Shogun Post Files

Use these typed file operations only after `shogun_scene__inspect_scene` and
only with exact operator-owned local paths. Imports are size-bounded and accept
only `.bvh`, `.c3d`, or `.mcp`. Saves require `.vdf`; exports accept `.bvh`,
`.c3d`, `.fbx`, or `.mcp`.

Existing output files fail closed unless `overwrite=true`. Results contain only
base names, byte counts, and formats; they never return full paths. The Skill
does not expose scene replacement, arbitrary HSL/Python execution, or raw
trajectory writes.

These operations are capability-gated by the selected Shogun Post build and
license. Shogun Post 1.19 is known to reject the official SDK `ImportFile` call
with `ControlError`; the tool reports that class without a traceback or local
path and does not claim the mutation succeeded. Use `shogun_scene__inspect_scene`
after every failed file call to confirm the scene remained unchanged.
