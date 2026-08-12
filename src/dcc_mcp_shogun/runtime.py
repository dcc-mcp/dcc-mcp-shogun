"""Typed, privacy-bounded operations used by Shogun skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Union

from .sdk import connect_client

MAX_TRAJECTORY_WINDOW = 2000
MAX_MOTION_FILE_BYTES = 2 * 1024 * 1024 * 1024
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
