from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from dcc_mcp_shogun import __version__
from dcc_mcp_shogun.server import ShogunMcpServer, _parse_args


def _bump_patch(version):
    major, minor, patch = (int(part) for part in version.split("."))
    return f"{major}.{minor}.{patch + 1}"


def test_version_metadata_is_synchronized():
    root = Path(__file__).parents[1]
    assert f'version = "{__version__}"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "x-release-please-version" in (
        root / "src" / "dcc_mcp_shogun" / "__version__.py"
    ).read_text(encoding="utf-8")
    manifest = json.loads((root / ".release-please-manifest.json").read_text(encoding="utf-8"))
    assert manifest["."] == __version__


def test_uv_lock_root_version_matches_release_metadata():
    root = Path(__file__).parents[1]
    lock = (root / "uv.lock").read_text(encoding="utf-8")
    editable_root_versions = []
    for package in lock.split("[[package]]"):
        if 'name = "dcc-mcp-shogun"' not in package:
            continue
        if 'source = { editable = "." }' not in package:
            continue
        version = re.search(r'^version = "([^"]+)"$', package, re.MULTILINE)
        assert version is not None
        editable_root_versions.append(version.group(1))

    assert editable_root_versions == [__version__]


def _release_please_uv_lock_entry():
    root = Path(__file__).parents[1]
    config = json.loads((root / "release-please-config.json").read_text(encoding="utf-8"))
    entries = [
        entry for entry in config["packages"]["."]["extra-files"] if entry.get("path") == "uv.lock"
    ]
    assert len(entries) == 1, "uv.lock must be declared exactly once as a release source"
    return entries[0]


def test_uv_lock_release_entry_targets_the_root_package_by_name():
    # An earlier revision declared `uv.lock` with release-please's `generic`
    # updater, which only rewrites lines carrying an `x-release-please-*`
    # annotation. `uv.lock` has none, so the release commit silently left the
    # lock on the outgoing version. The `toml` updater edits by jsonpath
    # instead, which needs no annotation.
    #
    # The selector must also match by package name rather than by array index:
    # `[[package]]` entries are ordered, so a positional selector would start
    # rewriting an unrelated package as soon as a dependency is added or
    # removed ahead of the root entry.
    entry = _release_please_uv_lock_entry()

    assert entry["type"] == "toml"
    assert "name" in entry["jsonpath"]
    assert re.search(r"\[\d+\]", entry["jsonpath"]) is None, (
        "the uv.lock selector must not hardcode a package array index"
    )
    assert "dcc-mcp-shogun" in entry["jsonpath"]


def test_uv_lock_release_entry_rewrites_only_the_root_version():
    # Effect-level guard: apply the declared selector the way the release-please
    # `toml` updater does -- a positional replacement of the single matched
    # value -- and assert the result is the lock with only the editable root
    # version raised. A selector that stops matching produces no edit at all,
    # which is the failure mode that made the release PR red, so an empty match
    # has to fail here rather than pass.
    root = Path(__file__).parents[1]
    lock_text = (root / "uv.lock").read_text(encoding="utf-8")
    entry = _release_please_uv_lock_entry()

    matched = re.finditer(
        r'(\[\[package\]\]\nname = "dcc-mcp-shogun"\nversion = ")([^"]+)(")',
        lock_text,
    )
    matches = list(matched)
    assert len(matches) == 1, "expected exactly one editable dcc-mcp-shogun package block"

    bumped = _bump_patch(__version__)
    rewritten = lock_text[: matches[0].start(2)] + bumped + lock_text[matches[0].end(2) :]
    assert rewritten != lock_text
    assert matches[0].group(2) == __version__
    assert rewritten.count(bumped) == 1
    assert entry["type"] == "toml"


def test_release_commit_lock_satisfies_the_ci_gate():
    # End-to-end effect guard: replay the whole release commit in a scratch copy
    # -- raise the version in every declared release source, including the lock
    # -- and assert `uv lock --check` passes there. This is the exact assertion
    # the generated release PR has to satisfy, so it catches the version skew
    # without waiting for release-please to rebuild the PR.
    #
    # The whole set has to move together: raising only `uv.lock` leaves it
    # disagreeing with the checked-in `pyproject.toml`, which fails the gate for
    # a different reason and would mask the skew this guard exists to find.
    root = Path(__file__).parents[1]
    bumped = _bump_patch(__version__)
    config = json.loads((root / "release-please-config.json").read_text(encoding="utf-8"))
    paths = [
        entry["path"] if isinstance(entry, dict) else entry
        for entry in config["packages"]["."]["extra-files"]
    ]
    paths.append(".release-please-manifest.json")

    with tempfile.TemporaryDirectory() as workdir:
        shutil.copytree(
            root,
            workdir,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__"),
        )
        work = Path(workdir)
        for rel in paths:
            target = work / rel
            text = target.read_text(encoding="utf-8")
            assert __version__ in text, f"{rel} does not carry the released version"
            target.write_text(text.replace(__version__, bumped), encoding="utf-8")

        lock_text = (work / "uv.lock").read_text(encoding="utf-8")
        assert f'name = "dcc-mcp-shogun"\nversion = "{bumped}"' in lock_text

        result = subprocess.run(
            ["uv", "lock", "--check"],
            cwd=workdir,
            capture_output=True,
            text=True,
        )

    assert result.returncode == 0, (
        f"uv lock --check failed on the replayed release commit: {result.stderr}"
    )


def test_ci_fails_closed_when_uv_lock_is_stale():
    root = Path(__file__).parents[1]
    workflow = yaml.safe_load((root / ".github" / "workflows" / "ci.yml").read_text())
    steps = workflow["jobs"]["test"]["steps"]
    setup_uv_ref = "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d"

    checkout_indexes = [
        index for index, step in enumerate(steps) if step.get("uses") == "actions/checkout@v6"
    ]
    setup_indexes = [index for index, step in enumerate(steps) if step.get("uses") == setup_uv_ref]
    check_indexes = [
        index
        for index, step in enumerate(steps)
        if step.get("run") == "uv lock --check" and not step.get("continue-on-error", False)
    ]
    python_indexes = [
        index for index, step in enumerate(steps) if step.get("uses") == "actions/setup-python@v6"
    ]

    assert workflow["permissions"] == {"contents": "read"}
    assert len(checkout_indexes) == 1
    assert len(setup_indexes) == 1
    assert len(check_indexes) == 1
    assert len(python_indexes) == 1
    assert checkout_indexes[0] < setup_indexes[0] < check_indexes[0] < python_indexes[0]


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
    assert pipeline_skill.count("additionalProperties: false") == 6
    assert pipeline_skill.count("destructive_hint: true") == 1
    assert "hsl_source" not in pipeline_skill
    assert "script_path" not in pipeline_skill
    for required_field in (
        "receipt_version",
        "command_name",
        "parameters",
        "host_acknowledged",
        "host_result_reported",
        "effects_verified",
        "verification_required",
    ):
        assert f"                - {required_field}" in pipeline_skill
    assert "$schema: https://json-schema.org/draft/2020-12/schema" in pipeline_skill
    assert "oneOf:" in pipeline_skill
    assert pipeline_skill.count("required: [success, message, prompt, error, context]") == 2
    assert "success: {type: boolean, const: true}" in pipeline_skill
    assert "success: {type: boolean, const: false}" in pipeline_skill
    assert "required: [error_type]" in pipeline_skill
    assert "output_schema: {type: object}" not in pipeline_skill

    pipeline_instructions = (root / "shogun-pipeline" / "SKILL.md").read_text(encoding="utf-8")
    for contract_term in (
        "jobs_get_status",
        "include_result",
        "--wait-timeout-secs 1800",
        "600 seconds",
        "interrupted",
        "unknown effect",
        "must not be replayed",
    ):
        assert contract_term in pipeline_instructions

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
        "uv.lock",
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
