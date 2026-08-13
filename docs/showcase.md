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
7. Probe the official `Scene`, `Timeline`, and `Offline` interfaces through
   their typed Skills without running UI fallback.
8. On a disposable recovery copy, probe the official channel-key and filtering
   contracts through `shogun-editing`, then re-inspect the affected sample.
9. Inspect bounded Clip timing and Character QA state through the read-only
   `shogun-production-context` Skill.
10. Continue to save/export only when the selected host build accepts the import;
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
dcc-mcp-cli load-skill shogun-editing --dcc-type shogun --instance-id <instance>
dcc-mcp-cli call <instance>.shogun_editing__select_channel_keys --json-file select-keys.json --wait
dcc-mcp-cli load-skill shogun-production-context --dcc-type shogun --instance-id <instance>
dcc-mcp-cli call <instance>.shogun_production_context__list_clips --json '{"max_clips":100}' --wait
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
- Shogun Post 1.19 rejects the official `Scene`, `Timeline`, and `Offline`
  interface commands as invalid for that host application; typed calls return
  bounded errors, so support is not overclaimed and no processing mutation is
  attempted;
- channel editing and filtering expose only allowlisted official SDK calls;
  `DeleteAllKeys`, arbitrary HSL, arbitrary Python, and bulk trajectory writes
  remain unavailable;
- a live 1.19 empty-scene probe loaded and dispatched all five editing tools;
  each returned the same bounded `ControlError`, and a typed re-inspection
  confirmed zero frames and zero subjects. Filter effects on a non-empty
  disposable take remain a separate acceptance requirement;
- a separate live 1.19 blank-scene probe loaded all four Clip/Character tools;
  the list calls returned bounded `ControlError` responses and the host remained
  available. The Database interface is omitted after an isolated read probe
  coincided with host termination;
- returned scene paths are reduced to file names;
- vendor exceptions are reduced to exception class names without tracebacks;
- unit tests, skill validation, package build, metadata check, and CI all pass.

The illustration is an explanatory workflow graphic, not a Shogun screenshot.
Real-host acceptance retains separate CLI results and host-visible evidence.
