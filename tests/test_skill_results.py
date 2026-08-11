from __future__ import annotations

import importlib.util
from pathlib import Path


def _result_module():
    path = (
        Path(__file__).parents[1]
        / "src"
        / "dcc_mcp_shogun"
        / "skills"
        / "shogun-scene"
        / "scripts"
        / "_result.py"
    )
    spec = importlib.util.spec_from_file_location("shogun_skill_result", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_safe_result_redacts_exception_details():
    def fail():
        raise RuntimeError("C:/private/production/scene.vdf")

    result = _result_module().safe_result("unused", fail)
    assert result["success"] is False
    assert result["error"] == "RuntimeError"
    assert result["context"]["error_type"] == "RuntimeError"
    assert "private" not in repr(result).lower()
    assert "traceback" not in repr(result).lower()
