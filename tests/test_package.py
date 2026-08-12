from __future__ import annotations

import json
import os
from pathlib import Path

from dcc_mcp_shogun import __version__
from dcc_mcp_shogun.server import ShogunMcpServer, _parse_args, _process_is_alive


def test_version_metadata_is_synchronized():
    root = Path(__file__).parents[1]
    assert f'version = "{__version__}"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "x-release-please-version" in (
        root / "src" / "dcc_mcp_shogun" / "__version__.py"
    ).read_text(encoding="utf-8")
    manifest = json.loads((root / ".release-please-manifest.json").read_text(encoding="utf-8"))
    assert manifest["."] == __version__


def test_bundled_skills_exist():
    root = Path(__file__).parents[1] / "src" / "dcc_mcp_shogun" / "skills"
    for name in ("shogun-scene", "shogun-files", "shogun-timeline", "shogun-processing"):
        assert (root / name / "SKILL.md").is_file()
        assert (root / name / "tools.yaml").is_file()


def test_scene_skill_is_read_only_and_file_skill_is_narrowly_mutating():
    root = Path(__file__).parents[1] / "src" / "dcc_mcp_shogun" / "skills"
    scene_skill = (
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_shogun"
        / "skills"
        / "shogun-scene"
        / "tools.yaml"
    ).read_text(encoding="utf-8")
    assert scene_skill.count("  - name:") == 10
    for mutation in ("new_scene", "load_file", "save_scene", "import_motion", "set_trajectory"):
        assert mutation not in scene_skill
    assert "read_only_hint: false" not in scene_skill

    files_skill = (
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_shogun"
        / "skills"
        / "shogun-files"
        / "tools.yaml"
    ).read_text(encoding="utf-8")
    assert files_skill.count("  - name:") == 3
    assert "new_scene" not in files_skill
    assert "load_file" not in files_skill
    assert files_skill.count("destructive_hint: true") == 3
    assert "additionalProperties: false" in files_skill

    timeline_skill = (root / "shogun-timeline" / "tools.yaml").read_text(encoding="utf-8")
    assert timeline_skill.count("  - name:") == 5
    assert timeline_skill.count("additionalProperties: false") == 5

    processing_skill = (root / "shogun-processing" / "tools.yaml").read_text(encoding="utf-8")
    assert processing_skill.count("  - name:") == 6
    assert processing_skill.count("destructive_hint: true") == 5
    assert "play_range" not in processing_skill


def test_release_sources_are_synchronized_by_release_please():
    root = Path(__file__).parents[1]
    config = (root / "release-please-config.json").read_text(encoding="utf-8")
    for path in (
        "pyproject.toml",
        "src/dcc_mcp_shogun/__version__.py",
        "src/dcc_mcp_shogun/skills/shogun-scene/SKILL.md",
        "src/dcc_mcp_shogun/skills/shogun-files/SKILL.md",
        "src/dcc_mcp_shogun/skills/shogun-timeline/SKILL.md",
        "src/dcc_mcp_shogun/skills/shogun-processing/SKILL.md",
    ):
        assert path in config


def test_documentation_images_are_excluded_from_sdist():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"docs/**/*.png"' in pyproject
    assert '"docs/**/*.svg"' in pyproject
    assert '"docs/**/*.webp"' in pyproject


def test_showcase_assets_are_present_and_bounded():
    root = Path(__file__).parents[1]
    image = root / "docs" / "images" / "shogun-scene-showcase.webp"
    motion = root / "examples" / "showcase" / "assets" / "dcc-mcp-shogun-showcase.bvh"
    assert image.is_file() and image.stat().st_size < 500 * 1024
    assert motion.is_file() and motion.stat().st_size < 500 * 1024


def test_shogun_119_file_operation_boundary_is_disclosed():
    root = Path(__file__).parents[1]
    documents = (
        root / "README.md",
        root / "docs" / "showcase.md",
        root / "src" / "dcc_mcp_shogun" / "skills" / "shogun-files" / "SKILL.md",
    )
    for document in documents:
        text = document.read_text(encoding="utf-8")
        assert "1.19" in text
        assert "ControlError" in text


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
