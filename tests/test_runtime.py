from __future__ import annotations

from pathlib import Path

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

    def GetBoneDetails(self, subject, bone, skeleton):
        assert (subject, bone, skeleton) == ("PerformerA", "Spine", "Solving")
        return "Hips", ["Chest", "Neck"]

    def GetConstraintNames(self, subject, skeleton):
        assert (subject, skeleton) == ("PerformerA", "Solving")
        return ["Floor", "LookAt"]

    def GetConstraintDetails(self, subject, constraint, skeleton):
        assert (subject, constraint, skeleton) == ("PerformerA", "Floor", "Solving")
        return True, "LFHD", "Head", [1.0, 2.0, 3.0], "Position"

    def GetSubjectParamNames(self, subject, skeleton):
        assert (subject, skeleton) == ("PerformerA", "Solving")
        return ["Mass", "Height"]

    def GetSubjectParamDetails(self, subject, param, skeleton):
        assert (subject, param, skeleton) == ("PerformerA", "Height", "Solving")
        return 1.8, "m", 1.7, True

    def GetTrajectoryAtFrame(self, subject, marker, frame):
        return float(frame), float(frame + 1), float(frame + 2), frame != 6

    def ImportFile(self, filename, import_type, create_second_figure):
        self.calls.append(("ImportFile", filename, import_type, create_second_figure))

    def SaveFile(self, filename, appendage):
        self.calls.append(("SaveFile", filename, appendage))
        Path(filename).write_bytes(b"vdf")

    def ExportFile(self, filename, extension):
        self.calls.append(("ExportFile", filename, extension))
        Path(filename).write_bytes(b"motion")


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
    assert runtime.trajectory_at_frame("PerformerA", "LFHD", 5)["position"] == [5.0, 6.0, 7.0]


def test_skeleton_details_constraints_and_parameters_are_typed_and_bounded(client):
    assert runtime.bone_details("PerformerA", "Spine", "Solving", max_children=1) == {
        "subject": "PerformerA",
        "skeleton": "Solving",
        "bone": "Spine",
        "parent": "Hips",
        "children": ["Chest"],
        "child_count": 2,
        "children_truncated": True,
    }
    assert runtime.list_constraints("PerformerA", "Solving", max_constraints=1)["constraints"] == [
        "Floor"
    ]
    assert runtime.constraint_details("PerformerA", "Floor", "Solving") == {
        "subject": "PerformerA",
        "skeleton": "Solving",
        "constraint": "Floor",
        "active": True,
        "source": "LFHD",
        "target": "Head",
        "offset": [1.0, 2.0, 3.0],
        "type": "Position",
    }
    assert runtime.list_subject_parameters("PerformerA", "Solving", max_parameters=1)[
        "parameters"
    ] == ["Mass"]
    assert runtime.subject_parameter("PerformerA", "Height", "Solving") == {
        "subject": "PerformerA",
        "skeleton": "Solving",
        "parameter": "Height",
        "value": 1.8,
        "unit": "m",
        "default": 1.7,
        "required": True,
    }


def test_trajectory_window_is_inclusive_and_bounded(client):
    result = runtime.trajectory_window("PerformerA", "LFHD", 5, 7)
    assert result["start_frame"] == 5
    assert result["end_frame"] == 7
    assert result["sample_count"] == 3
    assert result["existing_sample_count"] == 2
    assert result["samples"][1] == {
        "frame": 6,
        "position": [6.0, 7.0, 8.0],
        "exists": False,
    }
    with pytest.raises(ValueError, match="at most 2000"):
        runtime.trajectory_window("PerformerA", "LFHD", 0, 2000)


def test_file_operations_validate_paths_and_return_only_safe_labels(client, tmp_path):
    source = tmp_path / "anonymous.bvh"
    source.write_text("HIERARCHY", encoding="utf-8")
    imported = runtime.import_motion(source, import_type="selCreateNew")
    assert imported == {
        "file_name": "anonymous.bvh",
        "file_size_bytes": len(b"HIERARCHY"),
        "import_type": "selCreateNew",
        "create_second_figure": False,
    }
    assert client.calls[-1] == ("ImportFile", str(source.resolve()), "selCreateNew", False)
    assert str(tmp_path) not in repr(imported)

    scene = tmp_path / "result.vdf"
    saved = runtime.save_scene(scene)
    assert saved == {"file_name": "result.vdf", "file_size_bytes": 3}
    assert client.calls[-1] == ("SaveFile", str(scene.resolve()), "")

    export = tmp_path / "result.bvh"
    exported = runtime.export_motion(export)
    assert exported == {
        "file_name": "result.bvh",
        "file_size_bytes": 6,
        "format": "bvh",
    }
    assert client.calls[-1] == ("ExportFile", str(export.resolve()), "bvh")


def test_file_operations_fail_closed_for_wrong_extensions_and_overwrite(client, tmp_path):
    wrong = tmp_path / "payload.txt"
    wrong.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="supported motion format"):
        runtime.import_motion(wrong)

    existing = tmp_path / "existing.vdf"
    existing.write_bytes(b"old")
    with pytest.raises(FileExistsError):
        runtime.save_scene(existing)
    assert all(call[0] != "SaveFile" for call in client.calls)


def test_blank_scene_is_not_reported_as_saved(monkeypatch):
    client = FakeClient()
    client.GetSceneName = lambda: (".", ".vdf")
    monkeypatch.setattr(runtime, "connect_client", lambda: client)
    assert runtime.inspect_scene()["scene_saved"] is False
