---
name: shogun-production-context
description: >-
  Inspect bounded Vicon Shogun Post clip timing and character QA state through
  the official Scene, Clip, and Character SDK contracts. Use for NLE timing,
  SMPTE alignment, and shot status. Artist identities and free-form notes are
  excluded.
license: MIT
metadata:
  dcc-mcp:
    dcc: shogun
    layer: domain
    compatibility: "Python 3.9+; capability-gated Vicon Shogun Post 1.19 SDK"
    version: "0.6.0" # x-release-please-version
    tags: [motion-capture, animation, vicon, clips, qa]
    search-hint: >-
      Vicon Shogun Post clips NLE timing SMPTE character shot QA status
    tools: tools.yaml
---

# Vicon Shogun Post Production Context

Use these read-only tools to orient a mocap workflow before changing clip timing
or updating QA metadata. They call only Vicon's official Scene, Clip, and
Character SDK contracts.

Character results contain bounded workflow state only. Artist identities, user
names, final character names, trial notes, production
notes, special-flag notes, and generic notes are never read or returned.

The Skill does not access the Eclipse database, activate clips, change clip
timing, or write character metadata.
