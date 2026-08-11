from __future__ import annotations

import json
import os
from pathlib import Path

from dcc_mcp_shogun import __version__
from dcc_mcp_shogun.server import ShogunMcpServer, _parse_args, _process_is_alive


def test_version_metadata_is_synchronized():
    root = Path(__file__).parents[1]
    assert f'version = "{__version__}"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    manifest = json.loads((root / ".release-please-manifest.json").read_text(encoding="utf-8"))
    assert manifest["."] == __version__


def test_bundled_skill_exists():
    root = Path(__file__).parents[1] / "src" / "dcc_mcp_shogun" / "skills" / "shogun-scene"
    assert (root / "SKILL.md").is_file()
    assert (root / "tools.yaml").is_file()


def test_public_skill_contract_is_read_only():
    skill = (
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_shogun"
        / "skills"
        / "shogun-scene"
        / "tools.yaml"
    ).read_text(encoding="utf-8")
    assert skill.count("  - name:") == 4
    for mutation in ("new_scene", "load_file", "save_file", "import_motion", "set_trajectory"):
        assert mutation not in skill
    assert "read_only_hint: false" not in skill


def test_showcase_assets_are_present_and_bounded():
    root = Path(__file__).parents[1]
    image = root / "docs" / "images" / "shogun-scene-showcase.webp"
    motion = root / "examples" / "showcase" / "assets" / "dcc-mcp-shogun-showcase.bvh"
    assert image.is_file() and image.stat().st_size < 500 * 1024
    assert motion.is_file() and motion.stat().st_size < 500 * 1024


def test_server_options_bind_the_real_host_pid(monkeypatch, tmp_path):
    from dcc_mcp_shogun import server as server_module

    captured = {}
    monkeypatch.setattr(server_module, "resolve_sdk_path", lambda *_args: tmp_path)
    monkeypatch.setattr(server_module, "configure_sdk", lambda path: path)
    monkeypatch.setattr(server_module, "configure_control_port", lambda _pid: 803)
    monkeypatch.setattr(server_module, "host_product_version", lambda _pid: "1.19")
    monkeypatch.setattr(server_module, "connect_client", lambda: object())
    original = server_module.DccServerOptions.from_env

    def capture(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(server_module.DccServerOptions, "from_env", capture)
    instance = ShogunMcpServer(host_pid=os.getpid())
    assert captured["dcc_pid"] == os.getpid()
    assert captured["instance_type"] == "gui"
    assert captured["port"] is None
    assert instance is not None


def test_cli_requires_explicit_host_pid():
    options = _parse_args(["--host-pid", "123"])
    assert options.host_pid == 123


def test_process_probe_observes_current_process():
    assert _process_is_alive(os.getpid()) is True
