"""Typed, privacy-bounded operations used by Shogun skills."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Union

from .sdk import connect_client, official_interface

MAX_TRAJECTORY_WINDOW = 2000
MAX_CHANNEL_GAPS = 2000
MAX_MOTION_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_FRAME = 2_147_483_647
_SKELETONS = {"Labeling", "Solving"}
_IMPORT_TYPES = {
    "selCreateNew",
    "onlySelected",
    "createNewAlways",
    "mergeAll",
    "mergeSelected",
    "curClipCreateNew",
}
_IMPORT_SUFFIXES = {".bvh", ".c3d", ".mcp"}
_EXPORT_SUFFIXES = {".bvh", ".c3d", ".fbx", ".mcp"}
_RANGE_MODES = {
    "current_frame": "CurrentFrame",
    "selected_ranges": "SelectedRanges",
}
_SUBJECT_MODES = {
    "active": "SubjectsActive",
    "selected": "SubjectsSelected",
}
_PROCESS_OPERATIONS = {
    "reconstruct": "Reconstruct",
    "auto_label": "AutoLabel",
    "fix_occlusion": "FixOcclusion",
    "solve": "Solve",
    "retarget": "Retarget",
}
_CALIBRATION_RANGE_MODES = {
    "play_range": "PlayRange",
    "selected_ranges": "SelectedRanges",
}
_ROM_RANGE_MODES = {
    "play_range": "PlayRange",
    "current_frame": "CurrentFrame",
}
_QUICK_POST_LEVELS = {
    "reconstruct": "Reconstruct",
    "label": "Label",
    "solve": "Solve",
    "retarget": "Retarget",
}


def _file_label(value: str) -> str:
    return Path(value).name if value else ""


def _required_name(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("{} is required".format(label))
    return normalized


def _bounded_text(value: str, *, label: str, maximum: int) -> str:
    normalized = _required_name(value, label)
    if len(normalized) > maximum:
        raise ValueError("{} must contain at most {} characters".format(label, maximum))
    if "\x00" in normalized or "\n" in normalized or "\r" in normalized:
        raise ValueError("{} contains unsupported control characters".format(label))
    return normalized


def _scene_object(scene: Any, object_path: str) -> Any:
    path = _bounded_text(object_path, label="object_path", maximum=2048)
    value = scene.Objects[path]
    if value is None:
        raise ValueError("scene object was not found")
    return value


def _object_summary(value: Any) -> Dict[str, Any]:
    return {
        "name": str(value.Name),
        "path": str(value.Path),
        "type": str(value.Type),
        "showing": bool(value.Showing),
        "selectable": bool(value.Selectable),
    }


def _vector_value(channel: Any, frame: int) -> List[float]:
    value = channel[frame]
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise RuntimeError("Shogun returned an invalid three-component channel value")
    return [float(component) for component in value]


def _safe_sdk_value(value: Any) -> Any:
    """Convert one SDK scalar or short vector without exposing opaque objects."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RuntimeError("Shogun returned a non-finite channel value")
        return value
    if isinstance(value, str):
        if len(value) > 4096 or "\x00" in value:
            raise RuntimeError("Shogun returned an invalid string channel value")
        return value
    if isinstance(value, (list, tuple)) and len(value) <= 16:
        return [_safe_sdk_value(component) for component in value]
    raise RuntimeError("Shogun returned an unsupported channel value type")


def _validated_skeleton(skeleton: str) -> str:
    if skeleton not in _SKELETONS:
        raise ValueError("skeleton must be Labeling or Solving")
    return skeleton


def _bounded_limit(value: int, *, label: str, maximum: int) -> int:
    if not 1 <= value <= maximum:
        raise ValueError("{} must be between 1 and {}".format(label, maximum))
    return value


def _validated_frame(value: int, *, label: str) -> int:
    if not 0 <= value <= MAX_FRAME:
        raise ValueError(f"{label} must be non-negative and at most {MAX_FRAME}")
    return value


def _validated_frame_range(start_frame: int, end_frame: int) -> tuple[int, int]:
    start = _validated_frame(start_frame, label="start_frame")
    end = _validated_frame(end_frame, label="end_frame")
    if end < start:
        raise ValueError("frame range must be ordered")
    return start, end


def _input_file(
    file_path: Union[Path, str],
    *,
    suffixes: set[str],
    max_file_bytes: int,
) -> tuple[Path, int]:
    if not 1 <= max_file_bytes <= MAX_MOTION_FILE_BYTES:
        raise ValueError("max_file_bytes must be between 1 and {}".format(MAX_MOTION_FILE_BYTES))
    path = Path(file_path).expanduser().resolve()
    if path.suffix.lower() not in suffixes:
        raise ValueError("file is not a supported motion format")
    if not path.is_file():
        raise FileNotFoundError(path.name)
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("motion file is empty")
    if size > max_file_bytes:
        raise ValueError("motion file exceeds max_file_bytes")
    return path, size


def _output_file(
    file_path: Union[Path, str],
    *,
    suffixes: set[str],
    overwrite: bool,
) -> Path:
    path = Path(file_path).expanduser().resolve()
    if path.suffix.lower() not in suffixes:
        raise ValueError("output file has an unsupported extension")
    if not path.parent.is_dir():
        raise FileNotFoundError(path.parent.name)
    if path.exists() and not overwrite:
        raise FileExistsError(path.name)
    return path


def inspect_scene(max_subjects: int = 100) -> Dict[str, Any]:
    if not 1 <= max_subjects <= 1000:
        raise ValueError("max_subjects must be between 1 and 1000")
    client = connect_client()
    scene_path, scene_name = client.GetSceneName()
    frame_count = int(client.GetFrameCount())
    warnings: List[str] = []
    try:
        all_subjects = list(client.GetSubjectNames())
        subjects = all_subjects[:max_subjects]
    except Exception as error:
        subjects = []
        warnings.append(f"subjects_unavailable:{type(error).__name__}")
    return {
        "connected": True,
        "scene_name": _file_label(scene_name),
        "scene_saved": bool(scene_path) and scene_name.lower() not in {"", ".vdf"},
        "frame_count": frame_count,
        "subjects": subjects,
        "subject_count": len(subjects),
        "subjects_truncated": len(all_subjects) > max_subjects if not warnings else False,
        "warnings": warnings,
    }


def list_markers(subject: str, max_markers: int = 1000) -> Dict[str, Any]:
    if not subject.strip():
        raise ValueError("subject is required")
    if not 1 <= max_markers <= 10000:
        raise ValueError("max_markers must be between 1 and 10000")
    markers = list(connect_client().GetMarkerNames(subject))
    return {
        "subject": subject,
        "markers": markers[:max_markers],
        "marker_count": len(markers),
        "truncated": len(markers) > max_markers,
    }


def list_bones(subject: str, skeleton: str, max_bones: int = 1000) -> Dict[str, Any]:
    subject = _required_name(subject, "subject")
    skeleton = _validated_skeleton(skeleton)
    _bounded_limit(max_bones, label="max_bones", maximum=10000)
    client = connect_client()
    bones = list(client.GetBoneNames(subject, skeleton))
    return {
        "subject": subject,
        "skeleton": skeleton,
        "root_bone": client.GetRootBone(subject, skeleton),
        "bones": bones[:max_bones],
        "bone_count": len(bones),
        "truncated": len(bones) > max_bones,
    }


def bone_details(
    subject: str,
    bone: str,
    skeleton: str,
    max_children: int = 1000,
) -> Dict[str, Any]:
    subject = _required_name(subject, "subject")
    bone = _required_name(bone, "bone")
    skeleton = _validated_skeleton(skeleton)
    _bounded_limit(max_children, label="max_children", maximum=10000)
    parent, children_value = connect_client().GetBoneDetails(subject, bone, skeleton)
    children = list(children_value)
    return {
        "subject": subject,
        "skeleton": skeleton,
        "bone": bone,
        "parent": str(parent),
        "children": children[:max_children],
        "child_count": len(children),
        "children_truncated": len(children) > max_children,
    }


def list_constraints(
    subject: str,
    skeleton: str,
    max_constraints: int = 1000,
) -> Dict[str, Any]:
    subject = _required_name(subject, "subject")
    skeleton = _validated_skeleton(skeleton)
    _bounded_limit(max_constraints, label="max_constraints", maximum=10000)
    constraints = list(connect_client().GetConstraintNames(subject, skeleton))
    return {
        "subject": subject,
        "skeleton": skeleton,
        "constraints": constraints[:max_constraints],
        "constraint_count": len(constraints),
        "truncated": len(constraints) > max_constraints,
    }


def constraint_details(subject: str, constraint: str, skeleton: str) -> Dict[str, Any]:
    subject = _required_name(subject, "subject")
    constraint = _required_name(constraint, "constraint")
    skeleton = _validated_skeleton(skeleton)
    active, source, target, offset, constraint_type = connect_client().GetConstraintDetails(
        subject, constraint, skeleton
    )
    return {
        "subject": subject,
        "skeleton": skeleton,
        "constraint": constraint,
        "active": bool(active),
        "source": str(source),
        "target": str(target),
        "offset": [float(value) for value in offset],
        "type": str(constraint_type),
    }


def list_subject_parameters(
    subject: str,
    skeleton: str,
    max_parameters: int = 1000,
) -> Dict[str, Any]:
    subject = _required_name(subject, "subject")
    skeleton = _validated_skeleton(skeleton)
    _bounded_limit(max_parameters, label="max_parameters", maximum=10000)
    parameters = list(connect_client().GetSubjectParamNames(subject, skeleton))
    return {
        "subject": subject,
        "skeleton": skeleton,
        "parameters": parameters[:max_parameters],
        "parameter_count": len(parameters),
        "truncated": len(parameters) > max_parameters,
    }


def subject_parameter(subject: str, parameter: str, skeleton: str) -> Dict[str, Any]:
    subject = _required_name(subject, "subject")
    parameter = _required_name(parameter, "parameter")
    skeleton = _validated_skeleton(skeleton)
    value, unit, default, required = connect_client().GetSubjectParamDetails(
        subject, parameter, skeleton
    )
    return {
        "subject": subject,
        "skeleton": skeleton,
        "parameter": parameter,
        "value": float(value),
        "unit": str(unit),
        "default": float(default),
        "required": bool(required),
    }


def trajectory_at_frame(subject: str, marker: str, frame: int) -> Dict[str, Any]:
    if not subject.strip() or not marker.strip():
        raise ValueError("subject and marker are required")
    if frame < 0:
        raise ValueError("frame must be non-negative")
    x, y, z, exists = connect_client().GetTrajectoryAtFrame(subject, marker, frame)
    return {
        "subject": subject,
        "marker": marker,
        "frame": frame,
        "position": [float(x), float(y), float(z)],
        "exists": bool(exists),
    }


def trajectory_window(
    subject: str,
    marker: str,
    start_frame: int,
    end_frame: int,
) -> Dict[str, Any]:
    subject = _required_name(subject, "subject")
    marker = _required_name(marker, "marker")
    if start_frame < 0 or end_frame < start_frame:
        raise ValueError("frame window must be non-negative and ordered")
    sample_count = end_frame - start_frame + 1
    if sample_count > MAX_TRAJECTORY_WINDOW:
        raise ValueError("trajectory window may contain at most 2000 frames")
    client = connect_client()
    samples = []
    existing = 0
    for frame in range(start_frame, end_frame + 1):
        x, y, z, exists = client.GetTrajectoryAtFrame(subject, marker, frame)
        present = bool(exists)
        existing += int(present)
        samples.append(
            {
                "frame": frame,
                "position": [float(x), float(y), float(z)],
                "exists": present,
            }
        )
    return {
        "subject": subject,
        "marker": marker,
        "start_frame": start_frame,
        "end_frame": end_frame,
        "sample_count": sample_count,
        "existing_sample_count": existing,
        "samples": samples,
    }


def list_scene_objects(
    max_objects: int = 500,
    object_type: str = "",
) -> Dict[str, Any]:
    """List a bounded set of objects through Vicon's official Scene interface."""
    _bounded_limit(max_objects, label="max_objects", maximum=10000)
    scene = official_interface("Scene")
    if object_type:
        normalized_type = _bounded_text(object_type, label="object_type", maximum=128)
        values = list(scene.Objects.FilterByType(normalized_type))
    else:
        normalized_type = None
        values = list(scene.Objects.ToList())
    return {
        "object_type": normalized_type,
        "objects": [_object_summary(value) for value in values[:max_objects]],
        "object_count": len(values),
        "truncated": len(values) > max_objects,
    }


def scene_object_details(
    object_path: str,
    frame: int,
    max_children: int = 100,
) -> Dict[str, Any]:
    """Read hierarchy and transform channels for one explicit object and frame."""
    frame = _validated_frame(frame, label="frame")
    _bounded_limit(max_children, label="max_children", maximum=10000)
    scene = official_interface("Scene")
    value = _scene_object(scene, object_path)
    parent = value.GetParent()
    children = list(value.GetChildren())
    return {
        **_object_summary(value),
        "frame": frame,
        "translation": _vector_value(value.Translation, frame),
        "rotation": _vector_value(value.Rotation, frame),
        "scale": _vector_value(value.Scale, frame),
        "parent": _object_summary(parent) if parent is not None else None,
        "children": [_object_summary(child) for child in children[:max_children]],
        "child_count": len(children),
        "children_truncated": len(children) > max_children,
    }


def list_object_attributes(object_path: str, max_attributes: int = 200) -> Dict[str, Any]:
    """List attribute names only; values may contain private production metadata."""
    _bounded_limit(max_attributes, label="max_attributes", maximum=1000)
    value = _scene_object(official_interface("Scene"), object_path)
    attributes = list(value.Attributes.ToList())
    names = [str(attribute.Name) for attribute in attributes]
    return {
        "object": _object_summary(value),
        "attributes": names[:max_attributes],
        "attribute_count": len(names),
        "truncated": len(names) > max_attributes,
    }


def list_object_channels(object_path: str, max_channels: int = 200) -> Dict[str, Any]:
    """List channel names without returning motion values."""
    _bounded_limit(max_channels, label="max_channels", maximum=1000)
    value = _scene_object(official_interface("Scene"), object_path)
    channels = list(value.Channels.ToList())
    names = [str(channel.Name) for channel in channels]
    return {
        "object": _object_summary(value),
        "channels": names[:max_channels],
        "channel_count": len(names),
        "truncated": len(names) > max_channels,
    }


def channel_sample(object_path: str, channel_name: str, frame: int) -> Dict[str, Any]:
    """Read one explicit channel at one explicit frame."""
    frame = _validated_frame(frame, label="frame")
    name = _bounded_text(channel_name, label="channel_name", maximum=256)
    value = _scene_object(official_interface("Scene"), object_path)
    channel = value.Channels[name]
    if channel is None:
        raise ValueError("channel was not found")
    return {
        "object": _object_summary(value),
        "channel": name,
        "frame": frame,
        "value": _safe_sdk_value(channel[frame]),
        "has_key": bool(channel.HasKey(frame)),
    }


def list_channel_gaps(
    object_path: str,
    channel_name: str,
    *,
    any_subchannel: bool = False,
    max_gaps: int = 200,
) -> Dict[str, Any]:
    """Return a bounded gap summary for one explicit channel."""
    _bounded_limit(max_gaps, label="max_gaps", maximum=MAX_CHANNEL_GAPS)
    name = _bounded_text(channel_name, label="channel_name", maximum=256)
    value = _scene_object(official_interface("Scene"), object_path)
    channel = value.Channels[name]
    if channel is None:
        raise ValueError("channel was not found")
    gaps = list(channel.GetGaps(bool(any_subchannel)))
    normalized = [{"start": int(start), "end": int(end)} for start, end in gaps[:max_gaps]]
    return {
        "object": _object_summary(value),
        "channel": name,
        "any_subchannel": bool(any_subchannel),
        "gaps": normalized,
        "gap_count": len(gaps),
        "truncated": len(gaps) > max_gaps,
    }


def list_optical_cameras(max_cameras: int = 500) -> Dict[str, Any]:
    """List optical cameras through the vendor Scene type filter."""
    _bounded_limit(max_cameras, label="max_cameras", maximum=10000)
    scene = official_interface("Scene")
    cameras = list(scene.Objects.FilterByType("OpticalCamera"))
    return {
        "cameras": [_object_summary(camera) for camera in cameras[:max_cameras]],
        "camera_count": len(cameras),
        "truncated": len(cameras) > max_cameras,
    }


def optical_camera_details(object_path: str) -> Dict[str, Any]:
    """Read stable camera calibration and capture fields, excluding device identifiers."""
    camera = _scene_object(official_interface("Scene"), object_path)
    if str(camera.Type) not in {"OpticalCamera", "VideoCamera"}:
        raise ValueError("scene object is not an optical camera")
    return {
        "camera": _object_summary(camera),
        "camera_number": int(camera.Camera_Number),
        "enabled": bool(camera.Enabled),
        "recording_enabled": bool(camera.Record),
        "model": str(camera.Model),
        "field_of_view": float(camera.FOV),
        "focal_length": float(camera.Focal_Length),
        "sensor_width": int(camera.Sensor_Width),
        "sensor_height": int(camera.Sensor_Height),
        "calibration_residual": float(camera.Residual),
    }


def inspect_object_selection(max_objects: int = 500) -> Dict[str, Any]:
    """Read a bounded object selection snapshot."""
    _bounded_limit(max_objects, label="max_objects", maximum=10000)
    scene = official_interface("Scene")
    selected = list(scene.GetSelectedObjects())
    primary = scene.GetPrimarySelectedObject()
    return {
        "selected_objects": [_object_summary(value) for value in selected[:max_objects]],
        "selected_count": len(selected),
        "selected_truncated": len(selected) > max_objects,
        "primary_object": _object_summary(primary) if primary is not None else None,
    }


def select_scene_object(object_path: str, *, replace: bool = True) -> Dict[str, Any]:
    """Select one object, restoring the previous selection after a failed replacement."""
    scene = official_interface("Scene")
    value = _scene_object(scene, object_path)
    previous = list(scene.GetSelectedObjects()) if replace else []
    if replace:
        scene.DeselectAllObjects()
    try:
        scene.SelectObject(value)
    except Exception:
        if replace:
            try:
                scene.DeselectAllObjects()
                for previous_value in previous:
                    scene.SelectObject(previous_value)
            except Exception:
                pass
        raise
    return {"object": _object_summary(value), "replaced_existing_selection": bool(replace)}


def clear_object_selection() -> Dict[str, Any]:
    official_interface("Scene").DeselectAllObjects()
    return {"selection_cleared": True}


def set_scene_object_display(
    object_path: str,
    *,
    showing: Union[bool, None] = None,
    selectable: Union[bool, None] = None,
    opacity: Union[float, None] = None,
) -> Dict[str, Any]:
    """Apply an allowlisted display update with best-effort transactional rollback."""
    if showing is None and selectable is None and opacity is None:
        raise ValueError("at least one display property is required")
    if opacity is not None and not 0.0 <= float(opacity) <= 1.0:
        raise ValueError("opacity must be between 0 and 1")

    scene = official_interface("Scene")
    value = _scene_object(scene, object_path)
    previous = {
        "showing": bool(value.Showing),
        "selectable": bool(value.Selectable),
        "opacity": float(value.Opacity),
    }
    requested = {
        "showing": showing,
        "selectable": selectable,
        "opacity": float(opacity) if opacity is not None else None,
    }
    setters = {"showing": "Showing", "selectable": "Selectable", "opacity": "Opacity"}
    changed: List[str] = []
    try:
        for key, property_name in setters.items():
            if requested[key] is not None:
                setattr(value, property_name, requested[key])
                changed.append(key)
    except Exception:
        for key in reversed(changed):
            try:
                setattr(value, setters[key], previous[key])
            except Exception:
                pass
        raise
    current = {
        key: requested[key] if requested[key] is not None else previous[key] for key in setters
    }
    return {"object": _object_summary(value), "previous": previous, "current": current}


def import_motion(
    file_path: Union[Path, str],
    *,
    import_type: str = "selCreateNew",
    create_second_figure: bool = False,
    max_file_bytes: int = 512 * 1024 * 1024,
) -> Dict[str, Any]:
    if import_type not in _IMPORT_TYPES:
        raise ValueError("import_type is not supported by the Shogun SDK contract")
    path, size = _input_file(
        file_path,
        suffixes=_IMPORT_SUFFIXES,
        max_file_bytes=max_file_bytes,
    )
    connect_client().ImportFile(str(path), import_type, bool(create_second_figure))
    return {
        "file_name": path.name,
        "file_size_bytes": size,
        "import_type": import_type,
        "create_second_figure": bool(create_second_figure),
    }


def save_scene(file_path: Union[Path, str], *, overwrite: bool = False) -> Dict[str, Any]:
    path = _output_file(file_path, suffixes={".vdf"}, overwrite=overwrite)
    connect_client().SaveFile(str(path), "")
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("Shogun did not create the requested scene file")
    return {"file_name": path.name, "file_size_bytes": path.stat().st_size}


def export_motion(file_path: Union[Path, str], *, overwrite: bool = False) -> Dict[str, Any]:
    path = _output_file(file_path, suffixes=_EXPORT_SUFFIXES, overwrite=overwrite)
    output_format = path.suffix.lower().lstrip(".")
    connect_client().ExportFile(str(path), output_format)
    if not path.is_file() or path.stat().st_size <= 0:
        raise RuntimeError("Shogun did not create the requested export file")
    return {
        "file_name": path.name,
        "file_size_bytes": path.stat().st_size,
        "format": output_format,
    }


def inspect_timeline(max_selected_ranges: int = 100) -> Dict[str, Any]:
    """Read a bounded timeline snapshot through Vicon's official interface."""
    _bounded_limit(max_selected_ranges, label="max_selected_ranges", maximum=1000)
    timeline = official_interface("Timeline")
    ranges = [{"start": int(start), "end": int(end)} for start, end in timeline.GetSelectedRanges()]
    return {
        "current_frame": int(timeline.GetTimeFrames()),
        "play_range": {
            "start": int(timeline.GetPlayStart()),
            "end": int(timeline.GetPlayEnd()),
        },
        "animation_range": {
            "start": int(timeline.GetAnimationStart()),
            "end": int(timeline.GetAnimationEnd()),
        },
        "frame_rate": float(timeline.GetFrameRate()),
        "timecode_standard": str(timeline.GetTimeCodeStandard()),
        "selected_ranges": ranges[:max_selected_ranges],
        "selected_range_count": len(ranges),
        "selected_ranges_truncated": len(ranges) > max_selected_ranges,
    }


def set_current_frame(frame: int) -> Dict[str, Any]:
    frame = _validated_frame(frame, label="frame")
    official_interface("Timeline").SetTimeFrames(frame)
    return {"current_frame": frame}


def select_time_range(
    start_frame: int,
    end_frame: int,
    *,
    replace: bool = True,
) -> Dict[str, Any]:
    start, end = _validated_frame_range(start_frame, end_frame)
    timeline = official_interface("Timeline")
    if replace:
        timeline.DeselectAll()
    timeline.SelectRange(start, end)
    return {
        "start_frame": start,
        "end_frame": end,
        "replaced_existing_selection": bool(replace),
    }


def clear_time_selection() -> Dict[str, Any]:
    official_interface("Timeline").DeselectAll()
    return {"selection_cleared": True}


def deselect_time_range(start_frame: int, end_frame: int) -> Dict[str, Any]:
    start, end = _validated_frame_range(start_frame, end_frame)
    official_interface("Timeline").DeselectRange(start, end)
    return {"start_frame": start, "end_frame": end, "selected": False}


def invert_time_selection() -> Dict[str, Any]:
    official_interface("Timeline").InvertRangeSelection()
    return {"selection_inverted": True}


def select_time_from_keys() -> Dict[str, Any]:
    official_interface("Timeline").SelectRangeFromKeys()
    return {"selected_from_keys": True}


def set_play_range(start_frame: int, end_frame: int) -> Dict[str, Any]:
    start, end = _validated_frame_range(start_frame, end_frame)
    timeline = official_interface("Timeline")
    previous_start = int(timeline.GetPlayStart())
    previous_end = int(timeline.GetPlayEnd())
    timeline.SetPlayStart(start)
    try:
        timeline.SetPlayEnd(end)
    except Exception:
        try:
            timeline.SetPlayStart(previous_start)
            timeline.SetPlayEnd(previous_end)
        except Exception:
            pass
        raise
    return {"start_frame": start, "end_frame": end}


def set_animation_range(start_frame: int, end_frame: int) -> Dict[str, Any]:
    start, end = _validated_frame_range(start_frame, end_frame)
    timeline = official_interface("Timeline")
    previous_start = int(timeline.GetAnimationStart())
    previous_end = int(timeline.GetAnimationEnd())
    timeline.SetAnimationStart(start)
    try:
        timeline.SetAnimationEnd(end)
    except Exception:
        try:
            timeline.SetAnimationStart(previous_start)
            timeline.SetAnimationEnd(previous_end)
        except Exception:
            pass
        raise
    return {"start_frame": start, "end_frame": end}


def start_playback() -> Dict[str, Any]:
    official_interface("Timeline").Play()
    return {"playing": True}


def stop_playback() -> Dict[str, Any]:
    official_interface("Timeline").Stop()
    return {"playing": False}


def inspect_processing_settings(section: str) -> Dict[str, Any]:
    """Read only stable, allowlisted fields from official processing settings."""
    offline = official_interface("Offline")
    if section == "reconstruct":
        settings = offline.GetReconstructSettings()
        return {
            "section": section,
            "min_cameras_to_start": int(settings.MinCamsToStartTrajectory),
            "min_cameras_to_continue": int(settings.MinCamsToContinueTrajectory),
            "min_radius": float(settings.MinReconstructionRadius),
            "max_radius": float(settings.MaxReconstructionRadius),
        }
    if section == "solving":
        settings = offline.GetSolvingSettings()
        return {
            "section": section,
            "prior_importance": float(settings.PriorImportance),
            "mean_pose_ratio": float(settings.MeanPoseRatio),
            "plausibility_importance": float(settings.PlausibilityImportance),
            "thread_count": int(settings.NumThreads),
        }
    if section == "occlusion":
        settings = offline.GetOcclusionFixingSettings()
        return {
            "section": section,
            "enabled": bool(settings.Enabled),
            "apply_fixed_markers": bool(settings.ApplyFixedMarkers),
            "marker_smoothing": float(settings.MarkerSmoothing),
            "data_fidelity": float(settings.DataFidelity),
            "transition_time": float(settings.TransitionTime),
        }
    if section == "label_rom":
        settings = offline.GetLabelROMSettings()
        return {
            "section": section,
            "standard_deviation": float(settings.StandardDeviation),
            "separation_distance": float(settings.SeparationDistance),
        }
    if section == "labeling_calibration":
        settings = offline.GetLabelingSubjectCalibrationSettings()
        return {
            "section": section,
            "joint_importance": float(settings.JointImportance),
            "marker_importance": float(settings.MarkerImportance),
            "segment_importance": float(settings.SegmentImportance),
            "quality": str(settings.Quality),
            "statistics_mode": str(settings.StatsMode),
            "calibration_mode": str(settings.CalibrationMode),
            "active_frames": int(settings.ActiveFrames),
        }
    if section == "circle_fit":
        settings = offline.GetCircleFitSettings()
        return {
            "section": section,
            "enabled": bool(settings.Enabled),
            "store_centroids": bool(settings.StoreCentroids),
            "enable_video_centroids": bool(settings.EnableVideoCentroids),
            "thread_count": int(settings.NumThreads),
        }
    raise ValueError(
        "section must be reconstruct, solving, occlusion, label_rom, "
        "labeling_calibration, or circle_fit"
    )


def _update_settings(
    getter_name: str,
    setter_name: str,
    updates: Dict[str, Any],
    validators: Dict[str, Any],
    *,
    offline: Any = None,
    settings: Any = None,
) -> Dict[str, Any]:
    """Apply allowlisted SDK settings and restore the prior object after failure."""
    requested = {key: value for key, value in updates.items() if value is not None}
    if not requested:
        raise ValueError("at least one processing setting is required")
    unknown = set(requested) - set(validators)
    if unknown:
        raise ValueError("processing setting is not allowlisted")
    normalized = {key: validators[key](value) for key, value in requested.items()}
    offline = official_interface("Offline") if offline is None else offline
    settings = getattr(offline, getter_name)() if settings is None else settings
    previous = {key: getattr(settings, key) for key in normalized}
    for key, value in normalized.items():
        setattr(settings, key, value)
    try:
        getattr(offline, setter_name)(settings)
    except Exception:
        for key, value in previous.items():
            setattr(settings, key, value)
        try:
            getattr(offline, setter_name)(settings)
        except Exception:
            pass
        raise
    return {
        "updated": {key: _safe_sdk_value(value) for key, value in normalized.items()},
        "previous": {key: _safe_sdk_value(value) for key, value in previous.items()},
    }


def _bounded_float(value: Any, *, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return normalized


def _bounded_int(value: Any, *, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    normalized = int(value)
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{label} must be an integer")
    if not minimum <= normalized <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return normalized


def update_reconstruct_settings(
    *,
    min_cameras_to_start: Any = None,
    min_cameras_to_continue: Any = None,
    min_radius: Any = None,
    max_radius: Any = None,
) -> Dict[str, Any]:
    updates = {
        "MinCamsToStartTrajectory": min_cameras_to_start,
        "MinCamsToContinueTrajectory": min_cameras_to_continue,
        "MinReconstructionRadius": min_radius,
        "MaxReconstructionRadius": max_radius,
    }
    offline = official_interface("Offline")
    current = offline.GetReconstructSettings()
    final_start = (
        current.MinCamsToStartTrajectory if min_cameras_to_start is None else min_cameras_to_start
    )
    final_continue = (
        current.MinCamsToContinueTrajectory
        if min_cameras_to_continue is None
        else min_cameras_to_continue
    )
    final_min_radius = current.MinReconstructionRadius if min_radius is None else min_radius
    final_max_radius = current.MaxReconstructionRadius if max_radius is None else max_radius
    if int(final_continue) > int(final_start):
        raise ValueError("min_cameras_to_continue cannot exceed min_cameras_to_start")
    if float(final_min_radius) > float(final_max_radius):
        raise ValueError("min_radius cannot exceed max_radius")
    result = _update_settings(
        "GetReconstructSettings",
        "SetReconstructSettings",
        updates,
        {
            "MinCamsToStartTrajectory": lambda value: _bounded_int(
                value, label="min_cameras_to_start", minimum=2, maximum=1000
            ),
            "MinCamsToContinueTrajectory": lambda value: _bounded_int(
                value, label="min_cameras_to_continue", minimum=2, maximum=1000
            ),
            "MinReconstructionRadius": lambda value: _bounded_float(
                value, label="min_radius", minimum=0.0, maximum=1_000_000.0
            ),
            "MaxReconstructionRadius": lambda value: _bounded_float(
                value, label="max_radius", minimum=0.0, maximum=1_000_000.0
            ),
        },
        offline=offline,
        settings=current,
    )
    return {"section": "reconstruct", **result}


def update_occlusion_settings(
    *,
    enabled: Any = None,
    apply_fixed_markers: Any = None,
    marker_smoothing: Any = None,
    data_fidelity: Any = None,
    transition_time: Any = None,
) -> Dict[str, Any]:
    result = _update_settings(
        "GetOcclusionFixingSettings",
        "SetOcclusionFixingSettings",
        {
            "Enabled": enabled,
            "ApplyFixedMarkers": apply_fixed_markers,
            "MarkerSmoothing": marker_smoothing,
            "DataFidelity": data_fidelity,
            "TransitionTime": transition_time,
        },
        {
            "Enabled": _validated_bool,
            "ApplyFixedMarkers": _validated_bool,
            "MarkerSmoothing": lambda value: _bounded_float(
                value, label="marker_smoothing", minimum=0.0, maximum=1_000_000.0
            ),
            "DataFidelity": lambda value: _bounded_float(
                value, label="data_fidelity", minimum=0.0, maximum=1_000_000.0
            ),
            "TransitionTime": lambda value: _bounded_float(
                value, label="transition_time", minimum=0.0, maximum=1_000_000.0
            ),
        },
    )
    return {"section": "occlusion", **result}


def _raise_bool() -> Any:
    raise ValueError("boolean processing settings must be true or false")


def _validated_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        _raise_bool()
    return value


def _importance_validator(label: str) -> Any:
    def validate(value: Any) -> float:
        return _bounded_float(value, label=label, minimum=0.0, maximum=1_000_000.0)

    return validate


def update_solving_settings(
    *,
    prior_importance: Any = None,
    mean_pose_ratio: Any = None,
    plausibility_importance: Any = None,
    thread_count: Any = None,
) -> Dict[str, Any]:
    result = _update_settings(
        "GetSolvingSettings",
        "SetSolvingSettings",
        {
            "PriorImportance": prior_importance,
            "MeanPoseRatio": mean_pose_ratio,
            "PlausibilityImportance": plausibility_importance,
            "NumThreads": thread_count,
        },
        {
            "PriorImportance": _importance_validator("prior_importance"),
            "MeanPoseRatio": _importance_validator("mean_pose_ratio"),
            "PlausibilityImportance": _importance_validator("plausibility_importance"),
            "NumThreads": lambda value: _bounded_int(
                value, label="thread_count", minimum=1, maximum=1024
            ),
        },
    )
    return {"section": "solving", **result}


def label_rom(subjects: str, range_mode: str) -> Dict[str, Any]:
    vendor_subjects = _SUBJECT_MODES.get(subjects)
    if vendor_subjects is None:
        raise ValueError("subjects must be active or selected")
    vendor_range = _ROM_RANGE_MODES.get(range_mode)
    if vendor_range is None:
        raise ValueError("range_mode must be current_frame or play_range")
    official_interface("Offline").LabelROM(vendor_subjects, vendor_range)
    return {"operation": "label_rom", "subjects": subjects, "range_mode": range_mode}


def calibrate_subjects(skeleton: str, subjects: str, range_mode: str) -> Dict[str, Any]:
    if skeleton not in {"labeling", "solving"}:
        raise ValueError("skeleton must be labeling or solving")
    vendor_subjects = _SUBJECT_MODES.get(subjects)
    if vendor_subjects is None:
        raise ValueError("subjects must be active or selected")
    vendor_range = _CALIBRATION_RANGE_MODES.get(range_mode)
    if vendor_range is None:
        raise ValueError("range_mode must be play_range or selected_ranges")
    offline = official_interface("Offline")
    method_name = (
        "CalibrateLabelingSubjects" if skeleton == "labeling" else "CalibrateSolvingSubjects"
    )
    getattr(offline, method_name)(vendor_subjects, vendor_range)
    return {
        "operation": "calibrate_subjects",
        "skeleton": skeleton,
        "subjects": subjects,
        "range_mode": range_mode,
    }


def quick_post(process_level: str, range_mode: str) -> Dict[str, Any]:
    vendor_level = _QUICK_POST_LEVELS.get(process_level)
    if vendor_level is None:
        raise ValueError("process_level must be reconstruct, label, solve, or retarget")
    vendor_range = _RANGE_MODES.get(range_mode)
    if vendor_range is None:
        raise ValueError("range_mode must be current_frame or selected_ranges")
    official_interface("Offline").QuickPost(vendor_level, vendor_range)
    return {"operation": "quick_post", "process_level": process_level, "range_mode": range_mode}


def run_processing_step(
    operation: str,
    range_mode: str,
    subjects: str = "active",
) -> Dict[str, Any]:
    """Run one closed official operation over only an explicit safe frame scope."""
    method_name = _PROCESS_OPERATIONS.get(operation)
    if method_name is None:
        raise ValueError("operation is not supported")
    vendor_range = _RANGE_MODES.get(range_mode)
    if vendor_range is None:
        raise ValueError("range_mode must be current_frame or selected_ranges")

    offline = official_interface("Offline")
    subject_result = None
    if operation in {"auto_label", "fix_occlusion"}:
        vendor_subjects = _SUBJECT_MODES.get(subjects)
        if vendor_subjects is None:
            raise ValueError("subjects must be active or selected")
        getattr(offline, method_name)(vendor_subjects, vendor_range)
        subject_result = subjects
    else:
        getattr(offline, method_name)(vendor_range)
    return {
        "operation": operation,
        "range_mode": range_mode,
        "subjects": subject_result,
    }
