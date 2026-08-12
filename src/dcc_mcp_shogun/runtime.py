"""Typed, privacy-bounded operations used by Shogun skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

from .sdk import connect_client, official_interface

MAX_TRAJECTORY_WINDOW = 2000
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


def _file_label(value: str) -> str:
    return Path(value).name if value else ""


def _required_name(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("{} is required".format(label))
    return normalized


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
    raise ValueError("section must be reconstruct, solving, or occlusion")


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
