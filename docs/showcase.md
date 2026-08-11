# Shogun MCP showcase

This showcase demonstrates a bounded motion-capture workflow without publishing
studio capture data, installation paths, machine names, or credentials.

## What it proves

1. Generate an original 240-frame, 30 FPS BVH motion source.
2. Launch Shogun Post through the operator's normal package environment.
3. Bind the adapter to one explicit Shogun Post PID and its owned control port.
4. Discover the instance and its typed tools through `dcc-mcp-cli`.
5. Inspect the active scene through Vicon's official external Python SDK.
6. Keep file import as an explicit UI fallback until the SDK mutation path is
   verified on a compatible Shogun Post host.

## Reproduce

```powershell
python examples/showcase/generate_showcase_bvh.py
thm +p vicon_shogun_post run shogunpost
dcc-mcp-shogun --host-pid <SHOGUN_POST_PID>
dcc-mcp-cli list
dcc-mcp-cli search scene --dcc-type shogun
dcc-mcp-cli call <instance>.shogun_scene__inspect_scene --json '{}' --wait
```

The generated asset is deterministic and safe to commit. It contains no actor,
production, or filesystem metadata. A real production scene is intentionally
not included.

## Acceptance evidence

- the selected Shogun PID owns the resolved local control-stream listener;
- the adapter registers as `shogun` and reports Shogun Post 1.19;
- `inspect_scene` completes against the live application;
- returned scene paths are reduced to file names;
- vendor exceptions are reduced to exception class names without tracebacks;
- unit tests, skill validation, package build, metadata check, and CI all pass.

The `VERIFIED SCENE` stage in the illustration means a scene observed through
the typed adapter. It does not claim that the bundled BVH was imported by the
current read-only tool contract.
