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


class FakeTimeline:
    def __init__(self):
        self.calls = []

    def GetTimeFrames(self):
        return 42

    def GetPlayStart(self):
        return 1

    def GetPlayEnd(self):
        return 120

    def GetAnimationStart(self):
        return 0

    def GetAnimationEnd(self):
        return 150

    def GetFrameRate(self):
        return 120.0

    def GetTimeCodeStandard(self):
        return "120hz"

    def GetSelectedRanges(self):
        return [(10, 20), (30, 40)]

    def SetTimeFrames(self, frame):
        self.calls.append(("SetTimeFrames", frame))

    def DeselectAll(self):
        self.calls.append(("DeselectAll",))

    def SelectRange(self, start, end):
        self.calls.append(("SelectRange", start, end))

    def SetPlayStart(self, frame):
        self.calls.append(("SetPlayStart", frame))

    def SetPlayEnd(self, frame):
        self.calls.append(("SetPlayEnd", frame))


class FakeOffline:
    def __init__(self):
        self.calls = []

    def GetReconstructSettings(self):
        return type(
            "Settings",
            (),
            {
                "MinCamsToStartTrajectory": 3,
                "MinCamsToContinueTrajectory": 2,
                "MinReconstructionRadius": 0.5,
                "MaxReconstructionRadius": 50.0,
            },
        )()

    def GetSolvingSettings(self):
        return type(
            "Settings",
            (),
            {
                "PriorImportance": 1.0,
                "MeanPoseRatio": 0.25,
                "PlausibilityImportance": 2.0,
                "NumThreads": 8,
            },
        )()

    def GetOcclusionFixingSettings(self):
        return type(
            "Settings",
            (),
            {
                "Enabled": True,
                "ApplyFixedMarkers": False,
                "MarkerSmoothing": 0.1,
                "DataFidelity": 0.9,
                "TransitionTime": 5,
            },
        )()

    def Reconstruct(self, range_mode):
        self.calls.append(("Reconstruct", range_mode))

    def AutoLabel(self, subjects, range_mode):
        self.calls.append(("AutoLabel", subjects, range_mode))

    def FixOcclusion(self, subjects, range_mode):
        self.calls.append(("FixOcclusion", subjects, range_mode))

    def Solve(self, range_mode):
        self.calls.append(("Solve", range_mode))

    def Retarget(self, range_mode):
        self.calls.append(("Retarget", range_mode))


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


def test_timeline_snapshot_is_typed_and_bounded(monkeypatch):
    timeline = FakeTimeline()
    monkeypatch.setattr(runtime, "official_interface", lambda name: timeline)

    assert runtime.inspect_timeline(max_selected_ranges=1) == {
        "current_frame": 42,
        "play_range": {"start": 1, "end": 120},
        "animation_range": {"start": 0, "end": 150},
        "frame_rate": 120.0,
        "timecode_standard": "120hz",
        "selected_ranges": [{"start": 10, "end": 20}],
        "selected_range_count": 2,
        "selected_ranges_truncated": True,
    }


def test_timeline_mutations_require_explicit_ordered_frames(monkeypatch):
    timeline = FakeTimeline()
    monkeypatch.setattr(runtime, "official_interface", lambda name: timeline)

    assert runtime.set_current_frame(24) == {"current_frame": 24}
    assert runtime.select_time_range(10, 20, replace=True) == {
        "start_frame": 10,
        "end_frame": 20,
        "replaced_existing_selection": True,
    }
    assert runtime.clear_time_selection() == {"selection_cleared": True}
    assert runtime.set_play_range(1, 100) == {"start_frame": 1, "end_frame": 100}
    assert timeline.calls == [
        ("SetTimeFrames", 24),
        ("DeselectAll",),
        ("SelectRange", 10, 20),
        ("DeselectAll",),
        ("SetPlayStart", 1),
        ("SetPlayEnd", 100),
    ]

    with pytest.raises(ValueError, match="ordered"):
        runtime.select_time_range(20, 10)
    with pytest.raises(ValueError, match="non-negative"):
        runtime.set_current_frame(-1)


def test_play_range_restores_previous_values_after_partial_failure(monkeypatch):
    timeline = FakeTimeline()
    end_calls = 0

    def fail_once(frame):
        nonlocal end_calls
        end_calls += 1
        timeline.calls.append(("SetPlayEnd", frame))
        if end_calls == 1:
            raise RuntimeError("vendor failure")

    timeline.SetPlayEnd = fail_once
    monkeypatch.setattr(runtime, "official_interface", lambda name: timeline)

    with pytest.raises(RuntimeError, match="vendor failure"):
        runtime.set_play_range(10, 20)
    assert timeline.calls == [
        ("SetPlayStart", 10),
        ("SetPlayEnd", 20),
        ("SetPlayStart", 1),
        ("SetPlayEnd", 120),
    ]


@pytest.mark.parametrize(
    ("section", "expected"),
    [
        (
            "reconstruct",
            {
                "min_cameras_to_start": 3,
                "min_cameras_to_continue": 2,
                "min_radius": 0.5,
                "max_radius": 50.0,
            },
        ),
        (
            "solving",
            {
                "prior_importance": 1.0,
                "mean_pose_ratio": 0.25,
                "plausibility_importance": 2.0,
                "thread_count": 8,
            },
        ),
        (
            "occlusion",
            {
                "enabled": True,
                "apply_fixed_markers": False,
                "marker_smoothing": 0.1,
                "data_fidelity": 0.9,
                "transition_time": 5.0,
            },
        ),
    ],
)
def test_processing_settings_expose_only_allowlisted_fields(monkeypatch, section, expected):
    monkeypatch.setattr(runtime, "official_interface", lambda name: FakeOffline())
    assert runtime.inspect_processing_settings(section) == {"section": section, **expected}


@pytest.mark.parametrize(
    ("operation", "expected_call"),
    [
        ("reconstruct", ("Reconstruct", "CurrentFrame")),
        ("auto_label", ("AutoLabel", "SubjectsActive", "CurrentFrame")),
        ("fix_occlusion", ("FixOcclusion", "SubjectsActive", "CurrentFrame")),
        ("solve", ("Solve", "CurrentFrame")),
        ("retarget", ("Retarget", "CurrentFrame")),
    ],
)
def test_processing_steps_map_to_official_sdk_enums(monkeypatch, operation, expected_call):
    offline = FakeOffline()
    monkeypatch.setattr(runtime, "official_interface", lambda name: offline)
    result = runtime.run_processing_step(operation, "current_frame", "active")
    assert result == {
        "operation": operation,
        "range_mode": "current_frame",
        "subjects": "active" if operation in {"auto_label", "fix_occlusion"} else None,
    }
    assert offline.calls == [expected_call]


def test_processing_steps_forbid_implicit_whole_play_range(monkeypatch):
    offline = FakeOffline()
    monkeypatch.setattr(runtime, "official_interface", lambda name: offline)
    with pytest.raises(ValueError, match="current_frame or selected_ranges"):
        runtime.run_processing_step("solve", "play_range", "active")
    assert offline.calls == []
