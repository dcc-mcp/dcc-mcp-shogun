# dcc-mcp-shogun

![dcc-mcp-shogun brand lockup](docs/assets/dcc-mcp-shogun.svg)

[![CI](https://github.com/dcc-mcp/dcc-mcp-shogun/actions/workflows/ci.yml/badge.svg)](https://github.com/dcc-mcp/dcc-mcp-shogun/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/dcc-mcp-shogun.svg)](https://pypi.org/project/dcc-mcp-shogun/)
[![Python](https://img.shields.io/pypi/pyversions/dcc-mcp-shogun.svg)](https://pypi.org/project/dcc-mcp-shogun/)

A typed, local-first DCC-MCP adapter for Vicon Shogun Post motion-capture
inspection, timeline control, bounded processing, and file workflows.

![Motion data to typed tools to verified scene](docs/images/shogun-scene-showcase.webp)

The adapter uses Vicon's official local `ViconShogunPost` control-stream SDK and
its `Scene`, `Timeline`, and `Offline` interfaces. It does not expose arbitrary
Python or HSL execution. Application controls not exposed by the SDK remain an
explicit, exact-window DCC UI Control fallback.

Shogun Post ships an external Python SDK. The adapter runs in its own Python
process and connects to the application's local control stream; it does not rely
on a general-purpose Python interpreter embedded in the Shogun Post UI.

## Capabilities

- inspect path-redacted scene metadata and bounded subject lists;
- inspect subject markers, skeleton hierarchy, constraints, and static subject
  parameters;
- query one marker trajectory value or an inclusive window of at most 2,000
  frames;
- inspect the capability-gated Scene object graph, hierarchy, transforms,
  selection, visibility, selectability, and opacity;
- inspect and explicitly change current frame, selected time ranges,
  play/animation ranges, and playback through the capability-gated `Timeline`
  interface;
- inspect a stable allowlist of processing settings and invoke reconstruct,
  ROM labeling, subject calibration, auto-label, occlusion fixing, solve,
  QuickPost, or retarget through the official `Offline` interface;
- expose capability-gated import, save, and export calls that map directly to
  the official SDK;
- register one Shogun Post GUI instance with the DCC-MCP local gateway.

The mutating surface is deliberately narrow. Processing requires an explicit
`current_frame` or `selected_ranges` scope; the complete play range is not an
available implicit default. The adapter does not expose scene replacement,
arbitrary HSL/Python execution, or raw trajectory writes. Existing outputs fail
closed unless `overwrite=true`, and public results omit full file-system paths.
The Scene surface does not expose object creation, removal, reparenting, raw
attribute/channel writes, or raw trajectory mutation.

The subject, marker, skeleton, constraint, parameter, and trajectory queries in
`shogun-scene` are live-validated against Shogun Post 1.19. The newer official
`Scene` object model remains capability-gated because that host can ship the SDK
surface while rejecting its commands. The same host rejected the SDK's
`ImportFile` call with `ControlError`, without partially changing the scene. The
separate `shogun-files` Skill therefore remains explicitly host-build and
license-capability gated: its tools are typed and fail closed, but
import/save/export are not claimed as live-supported on 1.19.

The same 1.19 host exposes the official `Timeline` and `Offline` Python classes
but rejects their commands as invalid for that host application. The
`shogun-timeline` and `shogun-processing` Skills therefore remain explicitly
capability-gated: their schemas and SDK mappings are tested, while 1.19 support
is not claimed. A rejection is returned as a bounded typed error and never
triggers UI automation.

The implemented contracts follow Vicon's official
[Python SDK interface guide](https://vicon-help.atlassian.net/wiki/spaces/ShogunPost116/pages/341120839/Use%2BVicon%2BShogunPost%2BSDK%2Binterfaces)
and [HSL command reference](https://help.vicon.com/download/attachments/196380086/HSL%20scripting%20with%20Vicon%20Shogun.pdf).

## Showcase

The repository includes an original, deterministic 240-frame BVH motion source
and generator under [`examples/showcase`](examples/showcase). It is intended for
reproducible import experiments without redistributing production capture data.

See [`docs/showcase.md`](docs/showcase.md) for the full launch, discovery,
inspection, and evidence workflow.

## Local development

Start Vicon Shogun Post with your normal application launcher. Then install
this adapter in a Python environment that can import `dcc-mcp-core`:

```powershell
python -m pip install -e ".[dev]"
dcc-mcp-shogun --host-pid <SHOGUN_POST_PID>
```

The adapter discovers the official SDK beside the selected host process. An
operator can instead set `DCC_MCP_SHOGUN_SDK_PATH` to the SDK's `Win64`
directory. The adapter resolves the selected host process's control-stream
listener; `DCC_MCP_SHOGUN_CONTROL_PORT` may override it only when that port is
owned by the same host process.

The DCC-MCP listener uses an OS-assigned loopback port unless `--mcp-port` or
`DCC_MCP_SHOGUN_PORT` is explicitly set. Use `dcc-mcp-cli list`, `search`,
`describe`, and `call` rather than storing the resolved endpoint.

## Validation

```powershell
python -m ruff check src tests tools
python -m ruff format --check src tests tools
python -m pytest
python tools/lint_skills.py
python -m build
```

## Privacy and safety

- Connections are limited to the local Shogun control stream.
- Tool results reduce file paths to base names.
- Errors report exception classes, not SDK install paths or machine details.
- The scene Skill limits mutation to selection and display state; the file Skill
  exposes only bounded import/save/export operations; processing never defaults
  to the full play range.
- Authentication, licensing, UAC, and security dialogs are never automated.

Vicon and Shogun are trademarks of Vicon Motion Systems Ltd. This independent
adapter is not affiliated with or endorsed by Vicon.

## License

MIT
