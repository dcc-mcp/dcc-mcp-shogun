from __future__ import annotations

import pytest

from dcc_mcp_shogun import runtime


class FakeClient:
    def __init__(self):
        self.calls = []

    def GetSceneName(self):
        return "C:/private/show/shot", "C:/private/show/shot/Take01.vdf"

    def GetFrameCount(self):
        return 120

    def GetSubjectNames(self):
        return ["PerformerA", "PerformerB"]

    def GetMarkerNames(self, subject):
        assert subject == "PerformerA"
        return ["LFHD", "RFHD"]

    def GetBoneNames(self, subject, skeleton):
        return ["Hips", "Spine"]

    def GetRootBone(self, subject, skeleton):
        return "Hips"

    def GetTrajectoryAtFrame(self, subject, marker, frame):
        return 1.0, 2.0, 3.0, True


@pytest.fixture
def client(monkeypatch):
    value = FakeClient()
    monkeypatch.setattr(runtime, "connect_client", lambda: value)
    return value


def test_inspect_scene_redacts_full_paths(client):
    result = runtime.inspect_scene()
    assert result["scene_name"] == "Take01.vdf"
    assert "private" not in repr(result).lower()
    assert result["subjects"] == ["PerformerA", "PerformerB"]


def test_inspect_scene_reports_subject_truncation(client):
    result = runtime.inspect_scene(max_subjects=1)
    assert result["subject_count"] == 1
    assert result["subjects_truncated"] is True


def test_read_contracts_are_bounded(client):
    assert runtime.list_markers("PerformerA", 1)["markers"] == ["LFHD"]
    assert runtime.list_bones("PerformerA", "Solving")["root_bone"] == "Hips"
    assert runtime.trajectory_at_frame("PerformerA", "LFHD", 5)["position"] == [1.0, 2.0, 3.0]


def test_blank_scene_is_not_reported_as_saved(monkeypatch):
    client = FakeClient()
    client.GetSceneName = lambda: (".", ".vdf")
    monkeypatch.setattr(runtime, "connect_client", lambda: client)
    assert runtime.inspect_scene()["scene_saved"] is False
