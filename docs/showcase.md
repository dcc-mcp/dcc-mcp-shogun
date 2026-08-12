# Shogun MCP showcase

This showcase demonstrates a bounded motion-capture workflow without publishing
studio capture data, installation paths, machine names, or credentials.

## What it proves

1. Generate an original 240-frame, 30 FPS BVH motion source.
2. Launch Shogun Post through the operator's normal package environment.
3. Bind the adapter to one explicit Shogun Post PID and its owned control port.
4. Discover the instance and its typed tools through `dcc-mcp-cli`.
5. Inspect the active scene through Vicon's official external Python SDK.
6. Probe the host's file-operation capability with the anonymous BVH through
   the typed `shogun-files` Skill.
7. Probe the official `Timeline` and `Offline` interfaces through their typed
   Skills without running UI fallback.
8. Continue to save/export only when the selected host build accepts the import;
   otherwise retain the fail-closed result as compatibility evidence.

## Reproduce

```powershell
python examples/showcase/generate_showcase_bvh.py
dcc-mcp-shogun --host-pid <SHOGUN_POST_PID>
dcc-mcp-cli list
dcc-mcp-cli search scene --dcc-type shogun
dcc-mcp-cli call <instance>.shogun_scene__inspect_scene --json '{}' --wait
dcc-mcp-cli load-skill shogun-timeline --dcc-type shogun --instance-id <instance>
dcc-mcp-cli call <instance>.shogun_timeline__inspect_timeline --json '{}' --wait
dcc-mcp-cli load-skill shogun-processing --dcc-type shogun --instance-id <instance>
dcc-mcp-cli call <instance>.shogun_processing__inspect_processing_settings --json '{"section":"reconstruct"}' --wait
dcc-mcp-cli load-skill shogun-files --dcc-type shogun --instance-id <instance>
dcc-mcp-cli call <instance>.shogun_files__import_motion --json-file import.json --wait
```

The generated asset is deterministic and safe to commit. It contains no actor,
production, or filesystem metadata. A real production scene is intentionally
not included.

## Acceptance evidence

- the selected Shogun PID owns the resolved local control-stream listener;
- the adapter registers as `shogun` and reports Shogun Post 1.19;
- `inspect_scene` completes against the live application;
- Shogun Post 1.19 rejects the official SDK `ImportFile` call with
  `ControlError`, and a follow-up typed inspection confirms no partial scene
  mutation;
- import, save, and export implementations use only the official SDK and return
  path-redacted result metadata, but are not presented as live-supported on
  that host build;
- Shogun Post 1.19 rejects the official `Timeline` and `Offline` interface
  commands as invalid for that host application; typed calls return bounded
  errors, so support is not overclaimed and no processing mutation is attempted;
- returned scene paths are reduced to file names;
- vendor exceptions are reduced to exception class names without tracebacks;
- unit tests, skill validation, package build, metadata check, and CI all pass.

The illustration is an explanatory workflow graphic, not a Shogun screenshot.
Real-host acceptance retains separate CLI results and host-visible evidence.
