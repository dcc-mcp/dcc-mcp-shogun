---
name: shogun-production-context
description: >-
  Inspect bounded Vicon Shogun Post clip timing and character QA state, select
  one existing active Clip, or apply allowlisted timing and QA updates through
  the official Scene, Clip, and Character SDK contracts. Artist identities and
  free-form notes are excluded.
license: MIT
metadata:
  dcc-mcp:
    dcc: shogun
    layer: domain
    compatibility: "Python 3.9+; capability-gated Vicon Shogun Post 1.19 SDK"
    version: "0.6.0" # x-release-please-version
    tags: [motion-capture, animation, vicon, clips, qa]
    search-hint: >-
      Vicon Shogun Post clips active clip NLE timing SMPTE character shot QA
      status verified rollback
    tools: tools.yaml
---

# Vicon Shogun Post Production Context

Start with the read-only inventory tools to orient a mocap workflow. The four
mutation tools call only Vicon's official Scene, Clip, and Character SDK
contracts, accept narrow typed fields, verify the vendor read-back, and attempt
rollback after a partial failure.

Character results contain bounded workflow state only. Artist identities, user
names, final character names, trial notes, production
notes, special-flag notes, and generic notes are never read or returned.

The Skill does not access the Eclipse database, create/remove/rename Clip
objects, expose generic attribute writes, or read/write artist identities and
free-form notes. Mutations remain capability-gated until validated against a
disposable non-empty scene for the selected host build.
