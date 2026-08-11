"""Typed, privacy-bounded operations used by Shogun skills."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .sdk import connect_client


def _file_label(value: str) -> str:
    return Path(value).name if value else ""


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
    if skeleton not in {"Labeling", "Solving"}:
        raise ValueError("skeleton must be Labeling or Solving")
    if not subject.strip():
        raise ValueError("subject is required")
    if not 1 <= max_bones <= 10000:
        raise ValueError("max_bones must be between 1 and 10000")
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
