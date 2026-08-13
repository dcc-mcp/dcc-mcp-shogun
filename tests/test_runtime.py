from __future__ import annotations

from pathlib import Path

import pytest

from dcc_mcp_shogun import runtime


class FakeClient:
    def __init__(self):
        self.calls = []
        self.trajectory_overrides = {}

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
        override = self.trajectory_overrides.get((subject, marker, frame))
        if override is not None:
            return override
        return float(frame), float(frame + 1), float(frame + 2), frame != 6

    def SetTrajectoryAtFrame(self, subject, marker, frame, x, y, z, exists):
        self.calls.append(("SetTrajectoryAtFrame", subject, marker, frame, x, y, z, exists))
        self.trajectory_overrides[(subject, marker, frame)] = (x, y, z, exists)

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

    def DeselectRange(self, start, end):
        self.calls.append(("DeselectRange", start, end))

    def InvertRangeSelection(self):
        self.calls.append(("InvertRangeSelection",))

    def SelectRangeFromKeys(self):
        self.calls.append(("SelectRangeFromKeys",))

    def SetPlayStart(self, frame):
        self.calls.append(("SetPlayStart", frame))

    def SetPlayEnd(self, frame):
        self.calls.append(("SetPlayEnd", frame))

    def SetAnimationStart(self, frame):
        self.calls.append(("SetAnimationStart", frame))

    def SetAnimationEnd(self, frame):
        self.calls.append(("SetAnimationEnd", frame))

    def Play(self):
        self.calls.append(("Play",))

    def Stop(self):
        self.calls.append(("Stop",))


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

    def GetLabelROMSettings(self):
        return type(
            "Settings",
            (),
            {"StandardDeviation": 2.5, "SeparationDistance": 50.0},
        )()

    def GetLabelingSubjectCalibrationSettings(self):
        return type(
            "Settings",
            (),
            {
                "JointImportance": 1.0,
                "MarkerImportance": 2.0,
                "SegmentImportance": 3.0,
                "Quality": "Normal",
                "StatsMode": "CopyTemplate",
                "CalibrationMode": "Full",
                "ActiveFrames": 120,
            },
        )()

    def GetCircleFitSettings(self):
        return type(
            "Settings",
            (),
            {
                "Enabled": True,
                "StoreCentroids": False,
                "EnableVideoCentroids": True,
                "NumThreads": 4,
            },
        )()

    def SetReconstructSettings(self, settings):
        self.calls.append(("SetReconstructSettings", settings))

    def SetOcclusionFixingSettings(self, settings):
        self.calls.append(("SetOcclusionFixingSettings", settings))

    def SetSolvingSettings(self, settings):
        self.calls.append(("SetSolvingSettings", settings))

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

    def LabelROM(self, subjects, range_mode):
        self.calls.append(("LabelROM", subjects, range_mode))

    def CalibrateLabelingSubjects(self, subjects, range_mode):
        self.calls.append(("CalibrateLabelingSubjects", subjects, range_mode))

    def CalibrateSolvingSubjects(self, subjects, range_mode):
        self.calls.append(("CalibrateSolvingSubjects", subjects, range_mode))

    def QuickPost(self, process_level, range_mode):
        self.calls.append(("QuickPost", process_level, range_mode))


class FakeVectorChannel:
    def __init__(self, value):
        self.value = value

    def __getitem__(self, frame):
        assert frame == 42
        return self.value


class FakeChannel:
    def __init__(self, name, value, gaps=()):
        self.Name = name
        self._value = value
        self._gaps = list(gaps)
        self.calls = []

    def __getitem__(self, frame):
        assert frame == 42
        return self._value

    def HasKey(self, frame):
        assert frame == 42
        return True

    def GetGaps(self, any_subchannel=False):
        assert isinstance(any_subchannel, bool)
        return list(self._gaps)

    def SelectKeysFromRanges(self):
        self.calls.append(("SelectKeysFromRanges",))

    def DeselectKeysFromRanges(self):
        self.calls.append(("DeselectKeysFromRanges",))

    def SelectAllKeys(self):
        self.calls.append(("SelectAllKeys",))

    def DeselectAllKeys(self):
        self.calls.append(("DeselectAllKeys",))

    def InvertKeySelection(self):
        self.calls.append(("InvertKeySelection",))

    def DeleteKey(self, frame):
        self.calls.append(("DeleteKey", frame))

    def DeleteSelectedKeys(self):
        self.calls.append(("DeleteSelectedKeys",))


class FakeNamedList:
    def __init__(self, values):
        self._values = values

    def __getitem__(self, name):
        return next((value for value in self._values if value.Name == name), None)

    def ToList(self):
        return list(self._values)


class FakeSceneObject:
    def __init__(self, name, path, object_type, parent=None):
        self.Name = name
        self.Path = path
        self.Type = object_type
        self.Showing = True
        self.Selectable = True
        self.Opacity = 1.0
        self.Translation = FakeVectorChannel([1.0, 2.0, 3.0])
        self.Rotation = FakeVectorChannel([10.0, 20.0, 30.0])
        self.Scale = FakeVectorChannel([1.0, 1.0, 1.0])
        self.Attributes = FakeNamedList(
            [type("Attribute", (), {"Name": "Active", "Value": True})()]
        )
        self.Channels = FakeNamedList(
            [FakeChannel("Translation", [1.0, 2.0, 3.0], [(5, 7), (20, 22)])]
        )
        self._parent = parent
        self._children = []

    def GetParent(self):
        return self._parent

    def GetChildren(self):
        return self._children


class FakeObjectList:
    def __init__(self, objects):
        self._objects = objects

    def __getitem__(self, path):
        return next((value for value in self._objects if value.Path == path), None)

    def ToList(self):
        return list(self._objects)

    def FilterByType(self, object_type):
        return [value for value in self._objects if value.Type == object_type]


class FakeScene:
    def __init__(self):
        self.root = FakeSceneObject("Actor", "/Actor", "Character")
        self.marker = FakeSceneObject("LFHD", "/Actor/LFHD", "Marker", self.root)
        self.root._children = [self.marker]
        self.Objects = FakeObjectList([self.root, self.marker])
        self.selected = [self.root]
        self.calls = []

    def GetSelectedObjects(self):
        return list(self.selected)

    def GetPrimarySelectedObject(self):
        return self.selected[-1] if self.selected else None

    def DeselectAllObjects(self):
        self.calls.append(("DeselectAllObjects",))
        self.selected = []

    def SelectObject(self, value):
        self.calls.append(("SelectObject", value.Path))
        self.selected.append(value)


class FakeCamera(FakeSceneObject):
    def __init__(self):
        super().__init__("Vero1", "/Cameras/Vero1", "OpticalCamera")
        self.Camera_Number = 1
        self.Enabled = True
        self.Record = True
        self.Model = "Vero"
        self.FOV = 70.0
        self.Focal_Length = 12.5
        self.Sensor_Width = 2048
        self.Sensor_Height = 1088
        self.Residual = 0.15


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


def test_trajectory_sample_update_is_typed_verified_and_bounded(client):
    result = runtime.set_trajectory_sample(
        "PerformerA",
        "LFHD",
        5,
        x=101.25,
        y=-22.5,
        z=3.0,
        exists=True,
    )
    assert result == {
        "subject": "PerformerA",
        "marker": "LFHD",
        "frame": 5,
        "previous": {"position": [5.0, 6.0, 7.0], "exists": True},
        "current": {"position": [101.25, -22.5, 3.0], "exists": True},
        "verified": True,
    }
    assert client.calls[-1] == (
        "SetTrajectoryAtFrame",
        "PerformerA",
        "LFHD",
        5,
        101.25,
        -22.5,
        3.0,
        True,
    )

    with pytest.raises(ValueError, match="finite"):
        runtime.set_trajectory_sample("PerformerA", "LFHD", 5, x=float("nan"), y=0, z=0)
    with pytest.raises(ValueError, match="marker"):
        runtime.set_trajectory_sample("PerformerA", " ", 5, x=0, y=0, z=0)
    assert len(client.calls) == 1


def test_trajectory_sample_restores_previous_value_after_verification_failure(monkeypatch):
    client = FakeClient()
    attempts = 0

    def mismatching_set(subject, marker, frame, x, y, z, exists):
        nonlocal attempts
        attempts += 1
        client.calls.append(("SetTrajectoryAtFrame", subject, marker, frame, x, y, z, exists))
        if attempts == 1:
            client.trajectory_overrides[(subject, marker, frame)] = (x + 1.0, y, z, exists)
        else:
            client.trajectory_overrides[(subject, marker, frame)] = (x, y, z, exists)

    client.SetTrajectoryAtFrame = mismatching_set
    monkeypatch.setattr(runtime, "connect_client", lambda: client)

    with pytest.raises(RuntimeError, match="did not verify"):
        runtime.set_trajectory_sample("PerformerA", "LFHD", 5, x=1, y=2, z=3)
    assert client.calls[-1] == (
        "SetTrajectoryAtFrame",
        "PerformerA",
        "LFHD",
        5,
        5.0,
        6.0,
        7.0,
        True,
    )


def test_channel_key_selection_maps_only_allowlisted_sdk_operations(monkeypatch):
    scene = FakeScene()
    channel = scene.root.Channels["Translation"]
    monkeypatch.setattr(runtime, "official_interface", lambda name: scene)

    for mode in ("selected_ranges", "all", "clear", "invert"):
        assert runtime.select_channel_keys("/Actor", "Translation", mode) == {
            "object_path": "/Actor",
            "channel": "Translation",
            "selection_mode": mode,
        }
    assert channel.calls == [
        ("SelectKeysFromRanges",),
        ("SelectAllKeys",),
        ("DeselectAllKeys",),
        ("InvertKeySelection",),
    ]

    with pytest.raises(ValueError, match="selection_mode"):
        runtime.select_channel_keys("/Actor", "Translation", "arbitrary")


def test_delete_channel_keys_forbids_unbounded_delete_all(monkeypatch):
    scene = FakeScene()
    channel = scene.root.Channels["Translation"]
    monkeypatch.setattr(runtime, "official_interface", lambda name: scene)

    assert runtime.delete_channel_keys("/Actor", "Translation", delete_mode="frame", frame=42) == {
        "object_path": "/Actor",
        "channel": "Translation",
        "delete_mode": "frame",
        "frame": 42,
        "key_existed": True,
    }
    assert runtime.delete_channel_keys("/Actor", "Translation", delete_mode="selected") == {
        "object_path": "/Actor",
        "channel": "Translation",
        "delete_mode": "selected",
        "frame": None,
        "key_existed": None,
    }
    assert channel.calls == [("DeleteKey", 42), ("DeleteSelectedKeys",)]

    with pytest.raises(ValueError, match="frame is required"):
        runtime.delete_channel_keys("/Actor", "Translation", delete_mode="frame")
    with pytest.raises(ValueError, match="delete_mode"):
        runtime.delete_channel_keys("/Actor", "Translation", delete_mode="all")
    assert all(call[0] != "DeleteAllKeys" for call in channel.calls)


class FakeFilter:
    def __init__(self):
        self.calls = []

    def Apply(self, channel):
        self.calls.append(channel)


def test_fir_filter_uses_official_filter_contract_and_validates_boundaries(monkeypatch):
    scene = FakeScene()
    created = []

    def factory(name):
        assert name == "FIRFilter"
        value = FakeFilter()
        created.append(value)
        return value

    monkeypatch.setattr(runtime, "official_interface", lambda name: scene)
    monkeypatch.setattr(runtime, "official_type", factory)

    result = runtime.apply_fir_filter(
        "/Actor",
        "Translation",
        selected_keys_only=True,
        length=49,
        transition_width=0.0198,
        light_cutoff=0.3,
        threshold=15.0,
    )
    filter_value = created[-1]
    assert result == {
        "object_path": "/Actor",
        "channel": "Translation",
        "filter": "fir",
        "selected_keys_only": True,
        "length": 49,
        "transition_width": 0.0198,
        "light_cutoff": 0.3,
        "threshold": 15.0,
    }
    assert filter_value.SelectedKeysOnly is True
    assert filter_value.Length == 49
    assert filter_value.TransitionWidth == 0.0198
    assert filter_value.LightCutoff == 0.3
    assert filter_value.Threshold == 15.0
    assert filter_value.calls == [scene.root.Channels["Translation"]]

    with pytest.raises(ValueError, match="odd"):
        runtime.apply_fir_filter("/Actor", "Translation", length=48)
    with pytest.raises(ValueError, match="threshold"):
        runtime.apply_fir_filter("/Actor", "Translation", threshold=101)


def test_weighted_average_filter_maps_official_width_and_strength(monkeypatch):
    scene = FakeScene()
    created = []

    def factory(name):
        assert name == "WeightedAverageFilter"
        value = FakeFilter()
        created.append(value)
        return value

    monkeypatch.setattr(runtime, "official_interface", lambda name: scene)
    monkeypatch.setattr(runtime, "official_type", factory)

    assert runtime.apply_weighted_average_filter(
        "/Actor", "Translation", selected_keys_only=False, width=5, strength=7
    ) == {
        "object_path": "/Actor",
        "channel": "Translation",
        "filter": "weighted_average",
        "selected_keys_only": False,
        "width": 5,
        "strength": 7,
    }
    value = created[-1]
    assert value.SelectedKeysOnly is False
    assert value.Width == 5
    assert value.Strength == 7
    assert value.calls == [scene.root.Channels["Translation"]]

    with pytest.raises(ValueError, match="odd"):
        runtime.apply_weighted_average_filter("/Actor", "Translation", width=2)
    with pytest.raises(ValueError, match="strength"):
        runtime.apply_weighted_average_filter("/Actor", "Translation", strength=11)


def test_scene_object_reads_are_bounded_and_typed(monkeypatch):
    scene = FakeScene()
    monkeypatch.setattr(runtime, "official_interface", lambda name: scene)

    listed = runtime.list_scene_objects(max_objects=1)
    assert listed["object_count"] == 2
    assert listed["truncated"] is True
    assert listed["objects"] == [
        {
            "name": "Actor",
            "path": "/Actor",
            "type": "Character",
            "showing": True,
            "selectable": True,
        }
    ]
    assert runtime.list_scene_objects(object_type="Marker")["objects"][0]["name"] == "LFHD"

    details = runtime.scene_object_details("/Actor", frame=42, max_children=1)
    assert details["translation"] == [1.0, 2.0, 3.0]
    assert details["rotation"] == [10.0, 20.0, 30.0]
    assert details["scale"] == [1.0, 1.0, 1.0]
    assert details["children"][0]["path"] == "/Actor/LFHD"
    assert details["parent"] is None


def test_object_attributes_channels_samples_and_gaps_are_bounded(monkeypatch):
    scene = FakeScene()
    monkeypatch.setattr(runtime, "official_interface", lambda name: scene)

    attributes = runtime.list_object_attributes("/Actor", max_attributes=1)
    assert attributes["attributes"] == ["Active"]
    assert "Value" not in repr(attributes)
    channels = runtime.list_object_channels("/Actor", max_channels=1)
    assert channels["channels"] == ["Translation"]
    sample = runtime.channel_sample("/Actor", "Translation", 42)
    assert sample["value"] == [1.0, 2.0, 3.0]
    assert sample["has_key"] is True
    gaps = runtime.list_channel_gaps("/Actor", "Translation", any_subchannel=True, max_gaps=1)
    assert gaps["gaps"] == [{"start": 5, "end": 7}]
    assert gaps["gap_count"] == 2
    assert gaps["truncated"] is True
    scene.root.Channels = FakeNamedList([FakeChannel("Opaque", object())])
    with pytest.raises(RuntimeError, match="unsupported channel value"):
        runtime.channel_sample("/Actor", "Opaque", 42)
    scene.root.Channels = FakeNamedList([FakeChannel("Invalid", float("nan"))])
    with pytest.raises(RuntimeError, match="non-finite channel value"):
        runtime.channel_sample("/Actor", "Invalid", 42)


def test_optical_camera_inventory_excludes_device_identifier(monkeypatch):
    camera = FakeCamera()
    scene = FakeScene()
    scene.Objects = FakeObjectList([scene.root, camera])
    monkeypatch.setattr(runtime, "official_interface", lambda name: scene)

    assert runtime.list_optical_cameras()["cameras"][0]["name"] == "Vero1"
    details = runtime.optical_camera_details("/Cameras/Vero1")
    assert details["camera_number"] == 1
    assert details["sensor_width"] == 2048
    assert "device" not in repr(details).lower()


def test_scene_selection_and_display_updates_are_explicit(monkeypatch):
    scene = FakeScene()
    monkeypatch.setattr(runtime, "official_interface", lambda name: scene)

    selected = runtime.inspect_object_selection()
    assert selected["primary_object"]["path"] == "/Actor"
    result = runtime.select_scene_object("/Actor/LFHD", replace=True)
    assert result["object"]["name"] == "LFHD"
    assert scene.selected == [scene.marker]
    assert runtime.clear_object_selection() == {"selection_cleared": True}

    updated = runtime.set_scene_object_display(
        "/Actor/LFHD", showing=False, selectable=False, opacity=0.25
    )
    assert updated["previous"] == {"showing": True, "selectable": True, "opacity": 1.0}
    assert updated["current"] == {"showing": False, "selectable": False, "opacity": 0.25}
    assert scene.marker.Showing is False
    assert scene.marker.Selectable is False
    assert scene.marker.Opacity == 0.25

    with pytest.raises(ValueError, match="at least one"):
        runtime.set_scene_object_display("/Actor")
    with pytest.raises(ValueError, match="between 0 and 1"):
        runtime.set_scene_object_display("/Actor", opacity=2.0)
    with pytest.raises(ValueError, match="not found"):
        runtime.scene_object_details("/Missing", frame=42)


def test_scene_selection_restores_previous_values_after_failure(monkeypatch):
    scene = FakeScene()
    original_select = scene.SelectObject

    def fail_for_marker(value):
        if value is scene.marker:
            raise RuntimeError("vendor failure")
        original_select(value)

    scene.SelectObject = fail_for_marker
    monkeypatch.setattr(runtime, "official_interface", lambda name: scene)

    with pytest.raises(RuntimeError, match="vendor failure"):
        runtime.select_scene_object("/Actor/LFHD", replace=True)
    assert scene.selected == [scene.root]


def test_scene_display_restores_previous_values_after_partial_failure(monkeypatch):
    scene = FakeScene()
    original_class = scene.marker.__class__

    class FailingDisplayObject(original_class):
        @property
        def Selectable(self):
            return self._selectable

        @Selectable.setter
        def Selectable(self, value):
            if hasattr(self, "_selectable") and value is False:
                raise RuntimeError("vendor failure")
            self._selectable = value

    failing = FailingDisplayObject("LFHD", "/Actor/LFHD", "Marker", scene.root)
    scene.marker = failing
    scene.Objects = FakeObjectList([scene.root, failing])
    monkeypatch.setattr(runtime, "official_interface", lambda name: scene)

    with pytest.raises(RuntimeError, match="vendor failure"):
        runtime.set_scene_object_display("/Actor/LFHD", showing=False, selectable=False)
    assert failing.Showing is True
    assert failing.Selectable is True


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


def test_additional_timeline_selection_operations_are_bounded(monkeypatch):
    timeline = FakeTimeline()
    monkeypatch.setattr(runtime, "official_interface", lambda name: timeline)

    assert runtime.deselect_time_range(10, 20) == {
        "start_frame": 10,
        "end_frame": 20,
        "selected": False,
    }
    assert runtime.invert_time_selection() == {"selection_inverted": True}
    assert runtime.select_time_from_keys() == {"selected_from_keys": True}
    assert timeline.calls == [
        ("DeselectRange", 10, 20),
        ("InvertRangeSelection",),
        ("SelectRangeFromKeys",),
    ]


def test_animation_range_and_playback_map_to_timeline(monkeypatch):
    timeline = FakeTimeline()
    monkeypatch.setattr(runtime, "official_interface", lambda name: timeline)

    assert runtime.set_animation_range(5, 90) == {"start_frame": 5, "end_frame": 90}
    assert runtime.start_playback() == {"playing": True}
    assert runtime.stop_playback() == {"playing": False}
    assert timeline.calls == [
        ("SetAnimationStart", 5),
        ("SetAnimationEnd", 90),
        ("Play",),
        ("Stop",),
    ]


def test_animation_range_restores_previous_values_after_partial_failure(monkeypatch):
    timeline = FakeTimeline()
    end_calls = 0

    def fail_once(frame):
        nonlocal end_calls
        end_calls += 1
        timeline.calls.append(("SetAnimationEnd", frame))
        if end_calls == 1:
            raise RuntimeError("vendor failure")

    timeline.SetAnimationEnd = fail_once
    monkeypatch.setattr(runtime, "official_interface", lambda name: timeline)

    with pytest.raises(RuntimeError, match="vendor failure"):
        runtime.set_animation_range(5, 90)
    assert timeline.calls == [
        ("SetAnimationStart", 5),
        ("SetAnimationEnd", 90),
        ("SetAnimationStart", 0),
        ("SetAnimationEnd", 150),
    ]


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
        (
            "label_rom",
            {"standard_deviation": 2.5, "separation_distance": 50.0},
        ),
        (
            "labeling_calibration",
            {
                "joint_importance": 1.0,
                "marker_importance": 2.0,
                "segment_importance": 3.0,
                "quality": "Normal",
                "statistics_mode": "CopyTemplate",
                "calibration_mode": "Full",
                "active_frames": 120,
            },
        ),
        (
            "circle_fit",
            {
                "enabled": True,
                "store_centroids": False,
                "enable_video_centroids": True,
                "thread_count": 4,
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


def test_official_rom_calibration_and_quick_post_operations(monkeypatch):
    offline = FakeOffline()
    monkeypatch.setattr(runtime, "official_interface", lambda name: offline)

    assert runtime.label_rom("active", "current_frame") == {
        "operation": "label_rom",
        "subjects": "active",
        "range_mode": "current_frame",
    }
    assert runtime.calibrate_subjects("solving", "selected", "selected_ranges") == {
        "operation": "calibrate_subjects",
        "skeleton": "solving",
        "subjects": "selected",
        "range_mode": "selected_ranges",
    }
    assert runtime.quick_post("retarget", "selected_ranges") == {
        "operation": "quick_post",
        "process_level": "retarget",
        "range_mode": "selected_ranges",
    }
    assert offline.calls == [
        ("LabelROM", "SubjectsActive", "CurrentFrame"),
        ("CalibrateSolvingSubjects", "SubjectsSelected", "SelectedRanges"),
        ("QuickPost", "Retarget", "SelectedRanges"),
    ]

    with pytest.raises(ValueError, match="process_level"):
        runtime.quick_post("arbitrary", "current_frame")
    with pytest.raises(ValueError, match="skeleton"):
        runtime.calibrate_subjects("arbitrary", "active", "play_range")


def test_allowlisted_processing_settings_updates(monkeypatch):
    offline = FakeOffline()
    monkeypatch.setattr(runtime, "official_interface", lambda name: offline)

    reconstruct = runtime.update_reconstruct_settings(min_cameras_to_start=4, max_radius=75.0)
    assert reconstruct["section"] == "reconstruct"
    assert reconstruct["updated"] == {
        "MinCamsToStartTrajectory": 4,
        "MaxReconstructionRadius": 75.0,
    }
    occlusion = runtime.update_occlusion_settings(enabled=False, data_fidelity=0.8)
    assert occlusion["updated"] == {"Enabled": False, "DataFidelity": 0.8}
    solving = runtime.update_solving_settings(thread_count=4, prior_importance=1.5)
    assert solving["updated"] == {"PriorImportance": 1.5, "NumThreads": 4}

    with pytest.raises(ValueError, match="at least one"):
        runtime.update_solving_settings()
    with pytest.raises(ValueError, match="between 1 and 1024"):
        runtime.update_solving_settings(thread_count=0)
    with pytest.raises(ValueError, match="true or false"):
        runtime.update_occlusion_settings(enabled="yes")
    with pytest.raises(ValueError, match="cannot exceed"):
        runtime.update_reconstruct_settings(min_cameras_to_start=2, min_cameras_to_continue=3)
    with pytest.raises(ValueError, match="cannot exceed"):
        runtime.update_reconstruct_settings(min_radius=10.0, max_radius=5.0)
    with pytest.raises(ValueError, match="between"):
        runtime.update_solving_settings(prior_importance=float("nan"))


def test_processing_settings_restore_after_vendor_failure(monkeypatch):
    offline = FakeOffline()
    attempts = 0

    def fail_once(settings):
        nonlocal attempts
        attempts += 1
        offline.calls.append(("SetReconstructSettings", settings.MinCamsToStartTrajectory))
        if attempts == 1:
            raise RuntimeError("vendor failure")

    offline.SetReconstructSettings = fail_once
    monkeypatch.setattr(runtime, "official_interface", lambda name: offline)

    with pytest.raises(RuntimeError, match="vendor failure"):
        runtime.update_reconstruct_settings(min_cameras_to_start=4)
    assert offline.calls == [
        ("SetReconstructSettings", 4),
        ("SetReconstructSettings", 3),
    ]
