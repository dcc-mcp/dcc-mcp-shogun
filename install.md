# Install dcc-mcp-shogun

This adapter is a standalone Python service. It connects to one running Vicon
Shogun Post process through the official local SDK and does not copy files into
the host application.

## Requirements

- Windows 10 or Windows 11, 64-bit. macOS and Linux are not supported because
  Vicon Shogun Post and its Windows SDK are required.
- Vicon Shogun Post 1.19 or newer with the local control stream enabled.
- Python 3.9 or newer. CI covers Python 3.9 and 3.12.
- `dcc-mcp-core>=0.19.86,<1.0.0`.
- Permission to inspect the exact Shogun Post process and its owned local TCP
  listeners. Do not elevate or automate UAC, licensing, or security dialogs.

The package downloads no external binary or vendor payload. It creates no
adapter-owned cache. Pip and DCC-MCP Core retain ownership of their own caches
and lifecycle data.

## Supported versions

| Component | Supported |
|---|---|
| Operating system | Windows 10/11 x64 |
| Python | 3.9+; 3.9 and 3.12 are CI-tested |
| Vicon Shogun Post | 1.19+ |
| DCC-MCP Core | `>=0.19.86,<1.0.0` |
| Adapter | `0.11.0` <!-- x-release-please-version --> |

`doctor` and `verify` enforce the Python, Core, and Shogun floors. They report
unsupported versions instead of attempting a best-effort connection.

## Agent quick path

Generate and review the catalog-pinned plan:

```powershell
dcc-mcp-cli install --dcc-type shogun
```

Execute the approved wheel plan:

```powershell
dcc-mcp-cli install --dcc-type shogun --execute --json
```

Start Shogun Post normally, obtain the exact process id through your trusted
launcher or operator workflow, and bind it explicitly:

```powershell
$env:DCC_MCP_SHOGUN_HOST_PID = "<SHOGUN_POST_PID>"
dcc-mcp-shogun doctor --json
dcc-mcp-shogun verify --json
```

Proceed only when `directly_usable` is `true`. Then start the adapter:

```powershell
dcc-mcp-shogun --host-pid $env:DCC_MCP_SHOGUN_HOST_PID
```

The adapter never scans for another Shogun process or silently changes the PID.

## Manual path

Install the released wheel into the Python environment that runs the adapter:

```powershell
python -m pip install "dcc-mcp-shogun==0.11.0" # x-release-please-version
```

If the SDK is not installed beside the selected Shogun executable, provide its
validated Win64 SDK directory before verification:

```powershell
$env:DCC_MCP_SHOGUN_SDK_PATH = "<SHOGUN_INSTALL>\SDK\Win64"
```

For an operator-configured control-stream port outside the documented automatic
803-899 discovery window, set `DCC_MCP_SHOGUN_CONTROL_PORT`. The port must be
owned by the exact selected host process and pass the official SDK handshake.

## Verify

`doctor` aggregates installation and runtime prerequisites. A failed doctor
returns exit code 10. `verify` runs the same bounded checks as the final
usable-state gate and returns exit code 40 on failure:

```powershell
dcc-mcp-shogun doctor --json
dcc-mcp-shogun verify --json
```

The versioned JSON includes `steps[]`, `next_steps[]`, `failure_stage`,
`failure_reason`, and `directly_usable`. Remediation entries contain executable
commands plus structured environment requirements. Results disclose only
presence/readiness states and version numbers; they omit PIDs, paths, and ports.
`receipt_path` is `null` for these read-only checks. When installation is run
through the universal catalog command, `dcc-mcp-cli` owns its install receipt.

Stable exit codes:

| Code | Meaning |
|---:|---|
| 0 | Checks passed; directly usable |
| 10 | Preflight/doctor failure |
| 20 | Reserved for artifact acquisition failure |
| 30 | Reserved for installation failure |
| 40 | Verify-to-usable failure |
| 50 | Reserved for restart-required deferred cleanup |

## Upgrade

Stop the running adapter process first so its imported wheel is not locked.
Shogun Post itself does not need an adapter plug-in removed.

```powershell
python -m pip install --upgrade "dcc-mcp-shogun<1.0.0"
dcc-mcp-shogun doctor --json
dcc-mcp-shogun verify --json
```

The adapter has no auto-provisioned binary and no private cache to migrate or
clean. Re-run the catalog install plan when your environment is catalog-managed.

## Uninstall

Stop the running adapter process, then uninstall its wheel:

```powershell
python -m pip uninstall -y dcc-mcp-shogun
python -m pip show dcc-mcp-shogun
```

The final command should report that the package is not installed. Nothing is
left inside Shogun Post and there is no adapter-owned cache to delete. The shared
DCC-MCP gateway and Core installation are separate; remove them only when no
other adapter uses them.

## Troubleshooting

### `unsupported_platform`

Run the adapter on Windows. macOS and Linux runners can validate packaging but
cannot become directly usable Shogun hosts.

### `host_pid_required` or `host_process_exited`

Start Shogun Post, obtain its exact positive PID, set
`DCC_MCP_SHOGUN_HOST_PID`, and rerun doctor. The adapter intentionally performs
no process-name scan or automatic rebinding.

### `host_process_probe_failed`

Retry diagnostics for the same exact PID. The sidecar tolerates two consecutive
indeterminate probes and fails closed on the third; it never scans for or binds
another process. Its structured exit telemetry contains only the reason,
uptime, and consecutive failure count, without the PID, paths, or raw probe
errors, and is emitted as JSON to the sidecar's operator-visible standard error
stream. On Windows, the monitor holds one `SYNCHRONIZE` handle to the original
process identity for its lifecycle and closes it on exit, so PID reuse cannot
silently rebind the sidecar.

### `incompatible_core_version`

Install the reported Core range with the same interpreter:

```powershell
python -m pip install --upgrade "dcc-mcp-core>=0.19.86,<1.0.0"
```

### `official_sdk_unavailable`

Confirm that the selected host installation contains the official Win64 SDK,
or set `DCC_MCP_SHOGUN_SDK_PATH` to that SDK root. The directory must contain
both `vicon_shogun_post.py` and `ViconShogunPostSDK`.

### `control_stream_unavailable`

Wait for Shogun Post startup to finish and confirm its control stream is
enabled. Automatic discovery inspects only listeners owned by the exact PID in
the bounded 803-899 window. A configured custom port must also belong to that
PID. Doctor verifies the endpoint with a real SDK call and never falls back to
an unrelated listener.

### Permission, license, or security failures

Run Shogun Post and the adapter at compatible Windows integrity levels. Resolve
licensing, authentication, UAC, firewall, and security dialogs manually. The
adapter does not automate or bypass them.
