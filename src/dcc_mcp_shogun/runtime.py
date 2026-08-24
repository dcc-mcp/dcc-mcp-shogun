"""Typed, privacy-bounded operations used by Shogun skills."""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .sdk import ShogunSdkError, connect_client, official_interface, official_type

MAX_TRAJECTORY_WINDOW = 2000
MAX_CHANNEL_GAPS = 2000
MAX_MOTION_FILE_BYTES = 2 * 1024 * 1024 * 1024
MAX_FRAME = 2_147_483_647
PIPELINE_ALLOWLIST_ENV = "DCC_MCP_SHOGUN_PIPELINE_ALLOWLIST"
PIPELINE_ABI_ENV = "DCC_MCP_SHOGUN_PIPELINE_ABI"
PIPELINE_ABI_FIXED9_V1 = "fixed9-v1"
MAX_PIPELINE_COMMANDS = 32
MAX_PIPELINE_RESULT_LENGTH = 4096
_PIPELINE_COMMAND_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}\Z")
_PIPELINE_PROCESSING_MODES = {"traditional": 0, "model": 1}
_PIPELINE_FILL_GAP_MODES = {"disabled": 0, "rigid": 1, "labeling_constraint": 2}
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


def _object_channel(scene: Any, object_path: str, channel_name: str) -> tuple[Any, str, Any]:
    value = _scene_object(scene, object_path)
    name = _bounded_text(channel_name, label="channel_name", maximum=256)
    channel = value.Channels[name]
    if channel is None:
        raise ValueError("channel was not found")
    return value, name, channel


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def set_trajectory_sample(
    subject: str,
    marker: str,
    frame: int,
    *,
    x: Any,
    y: Any,
    z: Any,
    exists: Any = True,
) -> Dict[str, Any]:
    """Set and verify one explicit marker trajectory sample through the official SDK."""
    normalized_subject = _bounded_text(subject, label="subject", maximum=256)
    normalized_marker = _bounded_text(marker, label="marker", maximum=256)
    normalized_frame = _validated_frame(frame, label="frame")
    normalized_position = [
        _bounded_float(value, label=label, minimum=-1_000_000_000.0, maximum=1_000_000_000.0)
        for label, value in (("x", x), ("y", y), ("z", z))
    ]
    normalized_exists = _validated_bool(exists)
    client = connect_client()
    previous_x, previous_y, previous_z, previous_exists = client.GetTrajectoryAtFrame(
        normalized_subject, normalized_marker, normalized_frame
    )
    client.SetTrajectoryAtFrame(
        normalized_subject,
        normalized_marker,
        normalized_frame,
        normalized_position[0],
        normalized_position[1],
        normalized_position[2],
        normalized_exists,
    )
    current_x, current_y, current_z, current_exists = client.GetTrajectoryAtFrame(
        normalized_subject, normalized_marker, normalized_frame
    )
    current_position = [float(current_x), float(current_y), float(current_z)]
    verified = bool(current_exists) is normalized_exists and all(
        math.isclose(actual, requested, rel_tol=1e-9, abs_tol=1e-6)
        for actual, requested in zip(current_position, normalized_position)
    )
    if not verified:
        try:
            client.SetTrajectoryAtFrame(
                normalized_subject,
                normalized_marker,
                normalized_frame,
                float(previous_x),
                float(previous_y),
                float(previous_z),
                bool(previous_exists),
            )
        except Exception:
            pass
        raise RuntimeError("Shogun did not verify the requested trajectory sample")
    return {
        "subject": normalized_subject,
        "marker": normalized_marker,
        "frame": normalized_frame,
        "previous": {
            "position": [float(previous_x), float(previous_y), float(previous_z)],
            "exists": bool(previous_exists),
        },
        "current": {"position": current_position, "exists": bool(current_exists)},
        "verified": True,
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


def list_setup_parameters(
    object_path: str,
    parameter_kind: str = "all",
    max_parameters: int = 500,
) -> Dict[str, Any]:
    """List existing labeling/solving setup parameters without returning expressions."""
    _bounded_limit(max_parameters, label="max_parameters", maximum=10000)
    if parameter_kind not in {"all", "static", "dynamic"}:
        raise ValueError("parameter_kind must be all, static, or dynamic")
    setup = _scene_object(official_interface("Scene"), object_path)
    if str(setup.Type) not in {"LabelingSetup", "SolvingSetup"}:
        raise ValueError("scene object is not a labeling or solving setup")

    parameters: List[Dict[str, Any]] = []
    if parameter_kind in {"all", "static"}:
        for parameter in setup.StaticParameters.ToList():
            parameters.append(
                {
                    "name": str(parameter.Name),
                    "kind": "static",
                    "prior": _safe_sdk_value(parameter.Prior),
                    "user_value": _safe_sdk_value(parameter.UserValue),
                    "has_expression": bool(str(parameter.Expression)),
                }
            )
    if parameter_kind in {"all", "dynamic"}:
        for parameter in setup.DynamicParameters.ToList():
            parameters.append(
                {
                    "name": str(parameter.Name),
                    "kind": "dynamic",
                    "prior": _safe_sdk_value(parameter.Prior),
                    "value": _safe_sdk_value(parameter.Value),
                }
            )
    return {
        "setup": _object_summary(setup),
        "parameter_kind": parameter_kind,
        "parameters": parameters[:max_parameters],
        "parameter_count": len(parameters),
        "truncated": len(parameters) > max_parameters,
    }


def list_rigid_bodies(max_rigid_bodies: int = 500) -> Dict[str, Any]:
    """List rigid bodies through the vendor Scene type filter."""
    _bounded_limit(max_rigid_bodies, label="max_rigid_bodies", maximum=10000)
    scene = official_interface("Scene")
    rigid_bodies = list(scene.Objects.FilterByType("RigidBody"))
    return {
        "rigid_bodies": [
            _object_summary(rigid_body) for rigid_body in rigid_bodies[:max_rigid_bodies]
        ],
        "rigid_body_count": len(rigid_bodies),
        "truncated": len(rigid_bodies) > max_rigid_bodies,
    }


def rigid_body_details(
    object_path: str,
    frame: int,
    max_markers: int = 100,
) -> Dict[str, Any]:
    """Read one rigid body's transform and bounded attached-marker inventory."""
    frame = _validated_frame(frame, label="frame")
    _bounded_limit(max_markers, label="max_markers", maximum=10000)
    rigid_body = _scene_object(official_interface("Scene"), object_path)
    if str(rigid_body.Type) != "RigidBody":
        raise ValueError("scene object is not a rigid body")
    markers = [child for child in rigid_body.GetChildren() if str(child.Type) == "Marker"]
    return {
        "rigid_body": _object_summary(rigid_body),
        "frame": frame,
        "translation": _vector_value(rigid_body.Translation, frame),
        "rotation": _vector_value(rigid_body.Rotation, frame),
        "scale": _vector_value(rigid_body.Scale, frame),
        "markers": [_object_summary(marker) for marker in markers[:max_markers]],
        "marker_count": len(markers),
        "markers_truncated": len(markers) > max_markers,
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
    value, name, channel = _object_channel(official_interface("Scene"), object_path, channel_name)
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
    value, name, channel = _object_channel(official_interface("Scene"), object_path, channel_name)
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


def select_channel_keys(object_path: str, channel_name: str, selection_mode: str) -> Dict[str, Any]:
    """Apply one allowlisted key-selection operation to an explicit channel."""
    operations = {
        "selected_ranges": "SelectKeysFromRanges",
        "all": "SelectAllKeys",
        "clear": "DeselectAllKeys",
        "invert": "InvertKeySelection",
    }
    method_name = operations.get(selection_mode)
    if method_name is None:
        raise ValueError("selection_mode must be selected_ranges, all, clear, or invert")
    value, name, channel = _object_channel(official_interface("Scene"), object_path, channel_name)
    getattr(channel, method_name)()
    return {
        "object_path": str(value.Path),
        "channel": name,
        "selection_mode": selection_mode,
    }


def delete_channel_keys(
    object_path: str,
    channel_name: str,
    *,
    delete_mode: str,
    frame: Union[int, None] = None,
) -> Dict[str, Any]:
    """Delete one explicit key or the current selected keys; never delete every key implicitly."""
    if delete_mode not in {"frame", "selected"}:
        raise ValueError("delete_mode must be frame or selected")
    normalized_frame = None
    if delete_mode == "frame":
        if frame is None:
            raise ValueError("frame is required when delete_mode is frame")
        normalized_frame = _validated_frame(frame, label="frame")
    elif frame is not None:
        raise ValueError("frame is only supported when delete_mode is frame")

    value, name, channel = _object_channel(official_interface("Scene"), object_path, channel_name)
    key_existed: Union[bool, None]
    if delete_mode == "frame":
        key_existed = bool(channel.HasKey(normalized_frame))
        channel.DeleteKey(normalized_frame)
    else:
        key_existed = None
        channel.DeleteSelectedKeys()
    return {
        "object_path": str(value.Path),
        "channel": name,
        "delete_mode": delete_mode,
        "frame": normalized_frame,
        "key_existed": key_existed,
    }


def apply_fir_filter(
    object_path: str,
    channel_name: str,
    *,
    selected_keys_only: Any = True,
    length: Any = 49,
    transition_width: Any = 0.0198,
    light_cutoff: Any = 0.3,
    threshold: Any = 15.0,
) -> Dict[str, Any]:
    """Apply Vicon's bounded FIR filter to one explicit channel."""
    normalized_length = _bounded_int(length, label="length", minimum=3, maximum=1001)
    if normalized_length % 2 == 0:
        raise ValueError("length must be odd")
    normalized = {
        "selected_keys_only": _validated_bool(selected_keys_only),
        "length": normalized_length,
        "transition_width": _bounded_float(
            transition_width, label="transition_width", minimum=0.0001, maximum=1.0
        ),
        "light_cutoff": _bounded_float(
            light_cutoff, label="light_cutoff", minimum=0.0, maximum=1000.0
        ),
        "threshold": _bounded_float(threshold, label="threshold", minimum=0.0, maximum=100.0),
    }
    value, name, channel = _object_channel(official_interface("Scene"), object_path, channel_name)
    sdk_filter = official_type("FIRFilter")
    sdk_filter.SelectedKeysOnly = normalized["selected_keys_only"]
    sdk_filter.Length = normalized["length"]
    sdk_filter.TransitionWidth = normalized["transition_width"]
    sdk_filter.LightCutoff = normalized["light_cutoff"]
    sdk_filter.Threshold = normalized["threshold"]
    sdk_filter.Apply(channel)
    return {
        "object_path": str(value.Path),
        "channel": name,
        "filter": "fir",
        **normalized,
    }


def apply_weighted_average_filter(
    object_path: str,
    channel_name: str,
    *,
    selected_keys_only: Any = True,
    width: Any = 3,
    strength: Any = 5,
) -> Dict[str, Any]:
    """Apply Vicon's bounded weighted-average filter to one explicit channel."""
    normalized_width = _bounded_int(width, label="width", minimum=1, maximum=101)
    if normalized_width % 2 == 0:
        raise ValueError("width must be odd")
    normalized = {
        "selected_keys_only": _validated_bool(selected_keys_only),
        "width": normalized_width,
        "strength": _bounded_int(strength, label="strength", minimum=1, maximum=10),
    }
    value, name, channel = _object_channel(official_interface("Scene"), object_path, channel_name)
    sdk_filter = official_type("WeightedAverageFilter")
    sdk_filter.SelectedKeysOnly = normalized["selected_keys_only"]
    sdk_filter.Width = normalized["width"]
    sdk_filter.Strength = normalized["strength"]
    sdk_filter.Apply(channel)
    return {
        "object_path": str(value.Path),
        "channel": name,
        "filter": "weighted_average",
        **normalized,
    }


def _bounded_sdk_text(value: Any, *, maximum: int = 512) -> str:
    text = str(value).replace("\x00", "").replace("\r", " ").replace("\n", " ").strip()
    return text[:maximum]


def _clip_summary(value: Any) -> Dict[str, Any]:
    return {
        "name": _bounded_sdk_text(value.Name),
        "path": _bounded_sdk_text(value.Path, maximum=2048),
        "type": _bounded_sdk_text(value.Type, maximum=128),
        "locked": bool(value.Locked),
        "start_frame": _bounded_float(
            value.Start_Frame,
            label="start_frame",
            minimum=-1_000_000_000.0,
            maximum=1_000_000_000.0,
        ),
        "clip_offset": _bounded_float(
            value.Clip_Offset,
            label="clip_offset",
            minimum=-1_000_000_000.0,
            maximum=1_000_000_000.0,
        ),
        "duration": _bounded_float(
            value.Duration, label="duration", minimum=0.0, maximum=1_000_000_000.0
        ),
        "time_scale": _bounded_float(
            value.Time_Scale, label="time_scale", minimum=-1_000_000.0, maximum=1_000_000.0
        ),
        "smpte_offset": _bounded_float(
            value.SMPTE_Offset,
            label="smpte_offset",
            minimum=-1_000_000_000.0,
            maximum=1_000_000_000.0,
        ),
        "smpte_align_clip": bool(value.SMPTE_Align_Clip),
        "smpte_offset_time_shift": _bounded_float(
            value.SMPTE_Offset_Time_Shift,
            label="smpte_offset_time_shift",
            minimum=-1_000_000_000.0,
            maximum=1_000_000_000.0,
        ),
        "smpte_offset_data_shift": _bounded_float(
            value.SMPTE_Offset_Data_Shift,
            label="smpte_offset_data_shift",
            minimum=-1_000_000_000.0,
            maximum=1_000_000_000.0,
        ),
    }


def list_clips(max_clips: int = 500) -> Dict[str, Any]:
    """List bounded clip timing state without changing active clip or NLE data."""
    _bounded_limit(max_clips, label="max_clips", maximum=10000)
    values = list(official_interface("Scene").Objects.FilterByType("Clip"))
    return {
        "clips": [_clip_summary(value) for value in values[:max_clips]],
        "clip_count": len(values),
        "truncated": len(values) > max_clips,
    }


def get_clip_timing(object_path: str) -> Dict[str, Any]:
    """Read one explicit Clip object without changing active clip or NLE data."""
    value = _scene_object(official_interface("Scene"), object_path)
    if str(value.Type) != "Clip":
        raise ValueError("scene object is not a Clip")
    return _clip_summary(value)


def _clip_by_name(scene: Any, clip_name: str) -> Any:
    name = _bounded_text(clip_name, label="clip_name", maximum=512)
    matches = [
        value
        for value in scene.Objects.FilterByType("Clip")
        if _bounded_sdk_text(value.Name) == name
    ]
    if not matches:
        raise ValueError("clip_name was not found")
    if len(matches) > 1:
        raise ValueError("clip_name is ambiguous")
    return matches[0]


def get_active_clip() -> Dict[str, Any]:
    """Read the official active Clip name without returning scene paths."""
    active_clip = _bounded_sdk_text(official_interface("Scene").ActiveClip)
    return {"active_clip": active_clip, "has_active_clip": bool(active_clip)}


def set_active_clip(clip_name: str) -> Dict[str, Any]:
    """Select one existing Clip by exact name and verify the vendor read-back."""
    scene = official_interface("Scene")
    value = _clip_by_name(scene, clip_name)
    requested = _bounded_sdk_text(value.Name)
    previous = _bounded_sdk_text(scene.ActiveClip)
    try:
        scene.ActiveClip = requested
        current = _bounded_sdk_text(scene.ActiveClip)
        if current != requested:
            raise RuntimeError("Shogun did not activate the requested clip")
    except Exception:
        try:
            scene.ActiveClip = previous
        except Exception:
            pass
        raise
    return {"previous_active_clip": previous, "active_clip": current}


def _clip_update_state(value: Any) -> Dict[str, Any]:
    return {
        "locked": bool(value.Locked),
        "start_frame": _bounded_float(
            value.Start_Frame,
            label="start_frame",
            minimum=-1_000_000_000.0,
            maximum=1_000_000_000.0,
        ),
        "clip_offset": _bounded_float(
            value.Clip_Offset,
            label="clip_offset",
            minimum=-1_000_000_000.0,
            maximum=1_000_000_000.0,
        ),
        "duration": _bounded_float(
            value.Duration,
            label="duration",
            minimum=0.0,
            maximum=1_000_000_000.0,
        ),
        "time_scale": _bounded_float(
            value.Time_Scale,
            label="time_scale",
            minimum=0.001,
            maximum=1000.0,
        ),
        "smpte_align_clip": bool(value.SMPTE_Align_Clip),
    }


def _sdk_values_equal(current: Any, requested: Any) -> bool:
    if isinstance(requested, float):
        return math.isclose(float(current), requested, rel_tol=1e-9, abs_tol=1e-9)
    return current == requested


def _transactional_property_update(
    value: Any,
    *,
    requested: Dict[str, Any],
    properties: Dict[str, str],
    previous: Dict[str, Any],
    read_current: Any,
) -> Dict[str, Any]:
    changed: List[str] = []
    try:
        for key, property_name in properties.items():
            if requested[key] is not None:
                changed.append(key)
                setattr(value, property_name, requested[key])
        current = read_current(value)
        if any(
            requested[key] is not None and not _sdk_values_equal(current[key], requested[key])
            for key in properties
        ):
            raise RuntimeError("Shogun did not return the requested property values")
    except Exception:
        for key in reversed(changed):
            try:
                setattr(value, properties[key], previous[key])
            except Exception:
                pass
        raise
    return current


def update_clip_timing(
    object_path: str,
    *,
    locked: Any = None,
    start_frame: Any = None,
    clip_offset: Any = None,
    duration: Any = None,
    time_scale: Any = None,
    smpte_align_clip: Any = None,
) -> Dict[str, Any]:
    """Update an allowlisted Clip timing subset with verification and rollback."""
    if all(
        value is None
        for value in (
            locked,
            start_frame,
            clip_offset,
            duration,
            time_scale,
            smpte_align_clip,
        )
    ):
        raise ValueError("at least one clip timing property is required")
    requested = {
        "locked": _validated_bool(locked) if locked is not None else None,
        "start_frame": (
            _bounded_float(
                start_frame,
                label="start_frame",
                minimum=-1_000_000_000.0,
                maximum=1_000_000_000.0,
            )
            if start_frame is not None
            else None
        ),
        "clip_offset": (
            _bounded_float(
                clip_offset,
                label="clip_offset",
                minimum=-1_000_000_000.0,
                maximum=1_000_000_000.0,
            )
            if clip_offset is not None
            else None
        ),
        "duration": (
            _bounded_float(
                duration,
                label="duration",
                minimum=0.0,
                maximum=1_000_000_000.0,
            )
            if duration is not None
            else None
        ),
        "time_scale": (
            _bounded_float(
                time_scale,
                label="time_scale",
                minimum=0.001,
                maximum=1000.0,
            )
            if time_scale is not None
            else None
        ),
        "smpte_align_clip": (
            _validated_bool(smpte_align_clip) if smpte_align_clip is not None else None
        ),
    }
    properties = {
        "locked": "Locked",
        "start_frame": "Start_Frame",
        "clip_offset": "Clip_Offset",
        "duration": "Duration",
        "time_scale": "Time_Scale",
        "smpte_align_clip": "SMPTE_Align_Clip",
    }
    value = _scene_object(official_interface("Scene"), object_path)
    if str(value.Type) != "Clip":
        raise ValueError("scene object is not a Clip")
    previous = _clip_update_state(value)
    current = _transactional_property_update(
        value,
        requested=requested,
        properties=properties,
        previous=previous,
        read_current=_clip_update_state,
    )
    return {"clip": _object_summary(value), "previous": previous, "current": current}


def _character_status(value: Any) -> Dict[str, Any]:
    return {
        "name": _bounded_sdk_text(value.Name),
        "path": _bounded_sdk_text(value.Path, maximum=2048),
        "type": _bounded_sdk_text(value.Type, maximum=128),
        "active": bool(value.Active),
        "frame_in": _bounded_int(
            value.Frame_In, label="frame_in", minimum=-MAX_FRAME, maximum=MAX_FRAME
        ),
        "frame_out": _bounded_int(
            value.Frame_Out, label="frame_out", minimum=-MAX_FRAME, maximum=MAX_FRAME
        ),
        "shot_labeled": bool(value.Shot_Labeled),
        "shot_edited": bool(value.Shot_Edited),
        "shot_approved": bool(value.Shot_Approved),
        "shot_attached": bool(value.Shot_Attached),
        "prop_count": _bounded_int(value.Prop_Count, label="prop_count", minimum=0, maximum=10000),
        "special_flag": bool(value.Special_Flag),
        "facing_direction": _bounded_sdk_text(value.Facing_Direction, maximum=128),
        "priority": _bounded_sdk_text(value.Priority, maximum=128),
    }


def list_character_statuses(max_characters: int = 500) -> Dict[str, Any]:
    """List bounded character QA status while excluding artists and free-form notes."""
    _bounded_limit(max_characters, label="max_characters", maximum=10000)
    values = list(official_interface("Scene").Objects.FilterByType("Character"))
    return {
        "characters": [_character_status(value) for value in values[:max_characters]],
        "character_count": len(values),
        "truncated": len(values) > max_characters,
    }


def get_character_status(object_path: str) -> Dict[str, Any]:
    """Read one Character's bounded QA state without artists or free-form notes."""
    value = _scene_object(official_interface("Scene"), object_path)
    if str(value.Type) != "Character":
        raise ValueError("scene object is not a Character")
    return _character_status(value)


def _character_qa_state(value: Any) -> Dict[str, Any]:
    return {
        "active": bool(value.Active),
        "shot_labeled": bool(value.Shot_Labeled),
        "shot_edited": bool(value.Shot_Edited),
        "shot_approved": bool(value.Shot_Approved),
        "shot_attached": bool(value.Shot_Attached),
        "special_flag": bool(value.Special_Flag),
    }


def update_character_qa_status(
    object_path: str,
    *,
    active: Any = None,
    shot_labeled: Any = None,
    shot_edited: Any = None,
    shot_approved: Any = None,
    shot_attached: Any = None,
    special_flag: Any = None,
) -> Dict[str, Any]:
    """Update only allowlisted Character QA booleans with rollback on failure."""
    raw = {
        "active": active,
        "shot_labeled": shot_labeled,
        "shot_edited": shot_edited,
        "shot_approved": shot_approved,
        "shot_attached": shot_attached,
        "special_flag": special_flag,
    }
    if all(value is None for value in raw.values()):
        raise ValueError("at least one character QA property is required")
    requested = {
        key: _validated_bool(value) if value is not None else None for key, value in raw.items()
    }
    properties = {
        "active": "Active",
        "shot_labeled": "Shot_Labeled",
        "shot_edited": "Shot_Edited",
        "shot_approved": "Shot_Approved",
        "shot_attached": "Shot_Attached",
        "special_flag": "Special_Flag",
    }
    value = _scene_object(official_interface("Scene"), object_path)
    if str(value.Type) != "Character":
        raise ValueError("scene object is not a Character")
    previous = _character_qa_state(value)
    current = _transactional_property_update(
        value,
        requested=requested,
        properties=properties,
        previous=previous,
        read_current=_character_qa_state,
    )
    return {"character": _object_summary(value), "previous": previous, "current": current}


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


def _camera_details(camera: Any) -> Dict[str, Any]:
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


def optical_camera_details(object_path: str) -> Dict[str, Any]:
    """Read stable camera calibration and capture fields, excluding device identifiers."""
    camera = _scene_object(official_interface("Scene"), object_path)
    if str(camera.Type) not in {"OpticalCamera", "VideoCamera"}:
        raise ValueError("scene object is not an optical camera")
    return _camera_details(camera)


def list_video_cameras(max_cameras: int = 500) -> Dict[str, Any]:
    """List video cameras without returning capture paths or device identifiers."""
    _bounded_limit(max_cameras, label="max_cameras", maximum=10000)
    cameras = list(official_interface("Scene").Objects.FilterByType("VideoCamera"))
    return {
        "cameras": [_object_summary(camera) for camera in cameras[:max_cameras]],
        "camera_count": len(cameras),
        "truncated": len(cameras) > max_cameras,
    }


def video_camera_details(object_path: str) -> Dict[str, Any]:
    """Read Post-safe video presentation fields, excluding device and file metadata."""
    camera = _scene_object(official_interface("Scene"), object_path)
    if str(camera.Type) != "VideoCamera":
        raise ValueError("scene object is not a video camera")
    return {
        **_camera_details(camera),
        "image_inverted": bool(camera.Invert),
        "sub_sample_ratio": _safe_sdk_value(str(camera.Sub_Sample_Ratio)),
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
    client = connect_client()
    active_scene_before = tuple(client.GetSceneName())
    client.SaveFile(str(path), "")
    active_scene_after = tuple(client.GetSceneName())
    if not path.is_file():
        raise RuntimeError("Shogun did not create the requested scene file")
    file_size = path.stat().st_size
    if file_size <= 0:
        raise RuntimeError("Shogun did not create the requested scene file")

    return {
        "receipt_version": 1,
        "file_name": path.name,
        "file_size_bytes": file_size,
        "sha256": _sha256_file(path),
        "active_scene_changed": active_scene_after != active_scene_before,
    }


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
        raise ValueError(f"{label} must be finite and between {minimum} and {maximum}")
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


def _parse_pipeline_policy(raw: str) -> tuple[List[str], bool]:
    """Normalize pipeline identifiers and report bounded policy validity."""
    commands = [item.strip() for item in raw.split(",") if item.strip()]
    policy_valid = len(commands) <= MAX_PIPELINE_COMMANDS and all(
        _PIPELINE_COMMAND_PATTERN.fullmatch(command) is not None for command in commands
    )
    return commands, policy_valid


def _pipeline_allowlist() -> frozenset[str]:
    """Return the operator-owned, exact HSL command allowlist."""
    commands, policy_valid = _parse_pipeline_policy(os.environ.get(PIPELINE_ALLOWLIST_ENV, ""))
    if not commands:
        raise ShogunSdkError(f"No pipeline commands are enabled by {PIPELINE_ALLOWLIST_ENV}")
    if len(commands) > MAX_PIPELINE_COMMANDS:
        raise ShogunSdkError(
            f"{PIPELINE_ALLOWLIST_ENV} may contain at most {MAX_PIPELINE_COMMANDS} commands"
        )
    if not policy_valid:
        raise ShogunSdkError(f"{PIPELINE_ALLOWLIST_ENV} contains an invalid command name")
    return frozenset(commands)


def pipeline_policy_receipt(requested_command: Optional[str] = None) -> Dict[str, Any]:
    """Return bounded diagnostics for the operator-owned pipeline policy."""
    commands, policy_valid = _parse_pipeline_policy(os.environ.get(PIPELINE_ALLOWLIST_ENV, ""))
    abi = os.environ.get(PIPELINE_ABI_ENV, "").strip()
    abi_valid = abi == PIPELINE_ABI_FIXED9_V1
    receipt = {
        "configured": bool(commands),
        "valid": policy_valid,
        "command_count": len(commands),
        "restart_required": True,
        "abi_configured": bool(abi),
        "abi_valid": abi_valid,
        "abi_version": PIPELINE_ABI_FIXED9_V1 if abi_valid else None,
    }
    if requested_command is not None:
        requested_valid = _PIPELINE_COMMAND_PATTERN.fullmatch(requested_command) is not None
        receipt["requested_command_enabled"] = (
            policy_valid and requested_valid and requested_command in frozenset(commands)
        )
    return receipt


def _require_pipeline_abi() -> None:
    """Require an explicit operator attestation for the fixed positional ABI."""
    if os.environ.get(PIPELINE_ABI_ENV, "").strip() != PIPELINE_ABI_FIXED9_V1:
        raise ShogunSdkError(
            f"The pipeline command ABI must be explicitly set to {PIPELINE_ABI_FIXED9_V1}"
        )


def run_pipeline_command(
    command_name: str,
    *,
    load_type: Any,
    processing_mode: str,
    export_c3d: Any,
    export_fbx: Any,
    fill_gap_mode: str,
    fill_gap_width: Any,
    filter_cutoff: Any,
    filter_threshold: Any,
    label_threshold: Any,
) -> Dict[str, Any]:
    """Run one operator-allowlisted HSL pipeline command with a fixed signature.

    Only the validated command token enters the HSL source. Every parameter is
    converted to a bounded numeric literal before the SDK connection is opened.
    """
    command = _bounded_text(command_name, label="command_name", maximum=64)
    if _PIPELINE_COMMAND_PATTERN.fullmatch(command) is None:
        raise ValueError("command_name must be a simple HSL command identifier")
    if command not in _pipeline_allowlist():
        raise ShogunSdkError("The requested pipeline command is not enabled")
    _require_pipeline_abi()

    if processing_mode not in _PIPELINE_PROCESSING_MODES:
        raise ValueError("processing_mode must be traditional or model")
    if fill_gap_mode not in _PIPELINE_FILL_GAP_MODES:
        raise ValueError("fill_gap_mode must be disabled, rigid, or labeling_constraint")

    normalized = {
        "load_type": _bounded_int(load_type, label="load_type", minimum=0, maximum=3),
        "processing_mode": processing_mode,
        "export_c3d": _validated_bool(export_c3d),
        "export_fbx": _validated_bool(export_fbx),
        "fill_gap_mode": fill_gap_mode,
        "fill_gap_width": _bounded_int(
            fill_gap_width, label="fill_gap_width", minimum=0, maximum=10_000
        ),
        "filter_cutoff": _bounded_float(
            filter_cutoff, label="filter_cutoff", minimum=0.0, maximum=1_000_000.0
        ),
        "filter_threshold": _bounded_float(
            filter_threshold, label="filter_threshold", minimum=0.0, maximum=1_000_000.0
        ),
        "label_threshold": _bounded_float(
            label_threshold, label="label_threshold", minimum=0.0, maximum=1_000_000.0
        ),
    }
    arguments = (
        normalized["load_type"],
        _PIPELINE_PROCESSING_MODES[processing_mode],
        int(normalized["export_c3d"]),
        int(normalized["export_fbx"]),
        _PIPELINE_FILL_GAP_MODES[fill_gap_mode],
        normalized["fill_gap_width"],
        normalized["filter_cutoff"],
        normalized["filter_threshold"],
        normalized["label_threshold"],
    )
    hsl = "{}({});".format(command, ", ".join(str(value) for value in arguments))

    client = connect_client()
    execute_hsl = getattr(client, "HSL", None)
    if not callable(execute_hsl):
        raise ShogunSdkError("The selected Shogun host does not expose HSL execution")
    try:
        result = execute_hsl(hsl)
    except Exception as error:
        raise ShogunSdkError(
            f"The host rejected the allowlisted pipeline command ({type(error).__name__})"
        ) from error
    if not isinstance(result, str):
        raise ShogunSdkError("The host returned an invalid HSL result")
    if len(result) > MAX_PIPELINE_RESULT_LENGTH or "\x00" in result:
        raise ShogunSdkError("The host returned an invalid HSL result")

    return {
        "command_name": command,
        "parameters": normalized,
        "host_acknowledged": True,
        "host_result_reported": bool(result.strip()),
    }


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
