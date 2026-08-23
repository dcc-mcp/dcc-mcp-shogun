---
name: shogun-pipeline
description: >-
  Run one host-installed HSL pipeline command through Vicon Shogun Post using
  an operator-owned exact command allowlist and a fixed, typed parameter
  contract. Use for studio pipeline steps that have no official Offline SDK
  equivalent. Never accepts HSL source, script paths, or arbitrary arguments.
license: MIT
metadata:
  dcc-mcp:
    dcc: shogun
    layer: domain
    compatibility: "Python 3.9+; capability-gated Vicon Shogun Post HSL bridge"
    version: "0.10.0" # x-release-please-version
    tags: [motion-capture, animation, vicon, pipeline, destructive]
    search-hint: >-
      Vicon Shogun Post host-installed HSL production pipeline model traditional
      gap filling filter export allowlisted command
    tools: tools.yaml
---

# Vicon Shogun Post Pipeline

Use `shogun-pipeline__run_pipeline_command` only after inspecting the scene,
saving a recovery copy, and confirming the intended production parameters.
The host operator must set `DCC_MCP_SHOGUN_PIPELINE_ALLOWLIST` to a
comma-separated list of exact installed command identifiers before starting
the adapter. No commands are enabled by default.

The command contract is fixed and positional:

`command(load_type, processing_mode, export_c3d, export_fbx, fill_gap_mode, fill_gap_width, filter_cutoff, filter_threshold, label_threshold)`

Modes and Boolean values are converted to bounded numeric literals. The public
tool never accepts HSL source, script paths, free-form strings, extra arguments,
or command-line fragments. A command absent from the operator allowlist fails
before connecting to the host. Invalid configuration, missing HSL capability,
and host or scene rejection return bounded typed errors; there is no Python,
UI automation, or arbitrary HSL fallback.

The official HSL bridge returns a command result string but provides no generic
scene-state read-back for custom scripts. The tool therefore reports only
whether the host call returned and whether a result was present; it does not
expose the result text or claim that custom scene effects were verified. Follow
with the narrowest applicable typed scene inspection tool.
