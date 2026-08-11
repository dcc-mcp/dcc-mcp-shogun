# dcc-mcp-shogun

[![CI](https://github.com/dcc-mcp/dcc-mcp-shogun/actions/workflows/ci.yml/badge.svg)](https://github.com/dcc-mcp/dcc-mcp-shogun/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/dcc-mcp-shogun.svg)](https://pypi.org/project/dcc-mcp-shogun/)
[![Python](https://img.shields.io/pypi/pyversions/dcc-mcp-shogun.svg)](https://pypi.org/project/dcc-mcp-shogun/)

A typed, local-first DCC-MCP adapter for Vicon Shogun Post motion-capture inspection.

![Motion data to typed tools to verified scene](docs/images/shogun-scene-showcase.webp)

The adapter uses Vicon's official local `ViconShogunPost` control-stream SDK
for scene and trajectory inspection. It does not expose arbitrary Python or HSL
execution. Application controls not verified through the SDK remain an explicit,
exact-window DCC UI Control fallback.

Shogun Post ships an external Python SDK. The adapter runs in its own Python
process and connects to the application's local control stream; it does not rely
on a general-purpose Python interpreter embedded in the Shogun Post UI.

## Capabilities

- inspect path-redacted scene metadata and bounded subject lists;
- list subject markers and labeling/solving skeleton bones;
- query one marker trajectory value at one frame;
- register one Shogun Post GUI instance with the DCC-MCP local gateway.

The initial public tool contract is deliberately read-only. The official SDK
declares mutation APIs, but the tested Shogun Post 1.19 host rejected those
commands. They will not be exposed until a compatible host path is proven.

## Showcase

The repository includes an original, deterministic 240-frame BVH motion source
and generator under [`examples/showcase`](examples/showcase). It is intended for
reproducible import experiments without redistributing production capture data.

See [`docs/showcase.md`](docs/showcase.md) for the full launch, discovery,
inspection, and evidence workflow.

## Local development

Start Vicon Shogun Post with your studio's normal package or application
launcher. Then install this adapter in a Python environment that can import
`dcc-mcp-core`:

```powershell
thm +p vicon_shogun_post run shogunpost
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
- The published scene skill is read-only; mutations remain outside its contract.
- Authentication, licensing, UAC, and security dialogs are never automated.

Vicon and Shogun are trademarks of Vicon Motion Systems Ltd. This independent
adapter is not affiliated with or endorsed by Vicon.

## License

MIT
