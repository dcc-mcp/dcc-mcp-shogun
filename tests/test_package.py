from __future__ import annotations

import json
import os
from pathlib import Path

from dcc_mcp_shogun import __version__
from dcc_mcp_shogun.server import ShogunMcpServer, _parse_args


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
    for name in (
        "shogun-scene",
        "shogun-files",
        "shogun-timeline",
        "shogun-processing",
        "shogun-editing",
        "shogun-production-context",
        "shogun-pipeline",
    ):
        assert (root / name / "SKILL.md").is_file()
        assert (root / name / "tools.yaml").is_file()


def test_skills_keep_read_and_mutation_boundaries_explicit():
    root = Path(__file__).parents[1] / "src" / "dcc_mcp_shogun" / "skills"
    scene_skill = (
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_shogun"
        / "skills"
        / "shogun-scene"
        / "tools.yaml"
    ).read_text(encoding="utf-8")
    assert scene_skill.count("  - name:") == 27
    for mutation in ("new_scene", "load_file", "save_scene", "import_motion", "set_trajectory"):
        assert mutation not in scene_skill
    assert scene_skill.count("read_only_hint: true") == 24
    assert scene_skill.count("read_only_hint: false") == 3
    assert "destructive_hint: true" not in scene_skill
    for tool_name in (
        "list_setup_parameters",
        "list_rigid_bodies",
        "get_rigid_body_details",
        "list_video_cameras",
        "get_video_camera_details",
    ):
        assert "  - name: {}".format(tool_name) in scene_skill
    for private_field in ("Device_ID", "Firmware", "Capture_File_Path", "Video_File"):
        assert private_field not in scene_skill

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
    save_scene_contract = files_skill.split("  - name: save_scene", 1)[1].split(
        "  - name: export_motion", 1
    )[0]
    assert "$schema: https://json-schema.org/draft/2020-12/schema" in save_scene_contract
    assert "oneOf:" in save_scene_contract
    assert save_scene_contract.count("required: [success, message, prompt, error, context]") == 2
    assert (
        "required: [receipt_version, file_name, file_size_bytes, sha256, active_scene_changed]"
        in save_scene_contract
    )
    assert "success: {type: boolean, const: true}" in save_scene_contract
    assert "success: {type: boolean, const: false}" in save_scene_contract
    assert 'error: {type: "null"}' in save_scene_contract
    assert "required: [error_type]" in save_scene_contract
    assert 'pattern: "^[A-Za-z_][A-Za-z0-9_]*$"' in save_scene_contract
    assert "receipt_version: {type: integer, const: 1}" in save_scene_contract
    assert 'sha256: {type: string, pattern: "^[0-9a-f]{64}$"}' in save_scene_contract
    assert "active_scene_changed: {type: boolean}" in save_scene_contract
    assert "additionalProperties: false" in save_scene_contract

    timeline_skill = (root / "shogun-timeline" / "tools.yaml").read_text(encoding="utf-8")
    assert timeline_skill.count("  - name:") == 11
    assert timeline_skill.count("additionalProperties: false") == 11
    assert "destructive_hint: true" not in timeline_skill

    processing_skill = (root / "shogun-processing" / "tools.yaml").read_text(encoding="utf-8")
    assert processing_skill.count("  - name:") == 12
    assert processing_skill.count("destructive_hint: true") == 8
    assert "arbitrary" not in processing_skill

    pipeline_skill = (root / "shogun-pipeline" / "tools.yaml").read_text(encoding="utf-8")
    assert pipeline_skill.count("  - name:") == 1
    assert pipeline_skill.count("additionalProperties: false") == 1
    assert pipeline_skill.count("destructive_hint: true") == 1
    assert "hsl_source" not in pipeline_skill
    assert "script_path" not in pipeline_skill

    pipeline_instructions = (root / "shogun-pipeline" / "SKILL.md").read_text(encoding="utf-8")
    for contract_term in (
        "DCC_MCP_SHOGUN_PIPELINE_ABI",
        "fixed9-v1",
        "no-argument",
        "audited host wrapper",
    ):
        assert contract_term in pipeline_instructions

    editing_skill = (root / "shogun-editing" / "tools.yaml").read_text(encoding="utf-8")
    assert editing_skill.count("  - name:") == 5
    assert editing_skill.count("additionalProperties: false") == 5
    assert editing_skill.count("destructive_hint: true") == 4
    assert "delete_all" not in editing_skill

    production_skill = (root / "shogun-production-context" / "tools.yaml").read_text(
        encoding="utf-8"
    )
    assert production_skill.count("  - name:") == 8
    assert production_skill.count("read_only_hint: true") == 5
    assert production_skill.count("destructive_hint: true") == 2
    assert production_skill.count("additionalProperties: false") == 8
    for tool_name in (
        "get_active_clip",
        "set_active_clip",
        "update_clip_timing",
        "update_character_qa_status",
    ):
        assert "  - name: {}".format(tool_name) in production_skill
    for private_field in ("Edit_Artist", "Review_Artist", "Production_Notes", "Trial_Notes"):
        assert private_field not in production_skill


def test_release_sources_are_synchronized_by_release_please():
    root = Path(__file__).parents[1]
    config = (root / "release-please-config.json").read_text(encoding="utf-8")
    for path in (
        "pyproject.toml",
        "src/dcc_mcp_shogun/__version__.py",
        "README.md",
        "install.md",
        "src/dcc_mcp_shogun/skills/shogun-scene/SKILL.md",
        "src/dcc_mcp_shogun/skills/shogun-files/SKILL.md",
        "src/dcc_mcp_shogun/skills/shogun-timeline/SKILL.md",
        "src/dcc_mcp_shogun/skills/shogun-processing/SKILL.md",
        "src/dcc_mcp_shogun/skills/shogun-editing/SKILL.md",
        "src/dcc_mcp_shogun/skills/shogun-production-context/SKILL.md",
        "src/dcc_mcp_shogun/skills/shogun-pipeline/SKILL.md",
    ):
        assert path in config


def test_release_please_dispatches_package_publication():
    root = Path(__file__).parents[1]
    orchestrator = (root / ".github" / "workflows" / "release-please.yml").read_text(
        encoding="utf-8"
    )
    publisher = (root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")

    assert "  actions: write" in orchestrator
    assert "      - id: release" in orchestrator
    assert "if: ${{ steps.release.outputs.release_created == 'true' }}" in orchestrator
    assert "RELEASE_TAG: ${{ steps.release.outputs.tag_name }}" in orchestrator
    assert (
        'gh workflow run release.yml --repo "$GITHUB_REPOSITORY" --ref "$RELEASE_TAG"'
        in orchestrator
    )
    assert "  workflow_dispatch:" in publisher
    assert "  release:" not in publisher


def test_documentation_images_are_excluded_from_sdist():
    pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"docs/**/*.png"' in pyproject
    assert '"docs/**/*.svg"' in pyproject
    assert '"docs/**/*.webp"' in pyproject
    assert '"install.md"' in pyproject


def test_install_sop_documents_the_machine_contract():
    root = Path(__file__).parents[1]
    install = (root / "install.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    for heading in (
        "## Requirements",
        "## Supported versions",
        "## Agent quick path",
        "## Manual path",
        "## Verify",
        "## Upgrade",
        "## Uninstall",
        "## Troubleshooting",
    ):
        assert heading in install
    assert "dcc-mcp-shogun doctor --json" in install
    assert "dcc-mcp-shogun verify --json" in install
    assert "directly_usable" in install
    assert "install.md" in readme
    assert 'dependencies = ["dcc-mcp-core>=0.19.86,<1.0.0"]' in (root / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_showcase_assets_are_present_and_bounded():
    root = Path(__file__).parents[1]
    image = root / "docs" / "images" / "shogun-scene-showcase.webp"
    motion = root / "examples" / "showcase" / "assets" / "dcc-mcp-shogun-showcase.bvh"
    assert image.is_file() and image.stat().st_size < 500 * 1024
    assert motion.is_file() and motion.stat().st_size < 500 * 1024


def test_official_sdk_coverage_tracks_production_context_contracts():
    root = Path(__file__).parents[1]
    coverage = (root / "docs" / "official-sdk-coverage.md").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")

    assert "Total: 67 typed tools" in coverage
    for contract in (
        "set_active_clip",
        "update_clip_timing",
        "update_character_qa_status",
        "LabelingSetup",
        "RigidBody",
        "VideoCamera",
    ):
        assert contract in coverage
    assert "read-back verification and rollback" in readme


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
