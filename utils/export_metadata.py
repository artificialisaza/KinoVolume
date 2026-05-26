"""Utilities for persisting export metadata for reproducibility."""

import json
import os
from copy import deepcopy
from datetime import datetime, timezone

METADATA_FILENAME = "metadata.json"
SCHEMA_VERSION = 1


def _json_default(value):
    """Serialize common non-JSON-native values."""
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _to_relpath(path, output_dir):
    if not isinstance(path, str) or not path:
        return path
    try:
        return os.path.relpath(path, output_dir)
    except Exception:
        return path


def _to_abspath(path, folder_path):
    if not isinstance(path, str) or not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(folder_path, path))


def _relativize_result_paths(result, output_dir):
    """Convert known absolute paths in processor result dict to relative paths."""
    data = deepcopy(result)

    if "output_dir" in data:
        data["output_dir"] = "."

    for key in ("image_path", "vertical_path", "horizontal_path", "frames_dir", "mesh_path"):
        if key in data:
            data[key] = _to_relpath(data[key], output_dir)

    face_paths = data.get("face_paths")
    if isinstance(face_paths, dict):
        data["face_paths"] = {
            name: _to_relpath(path, output_dir) for name, path in face_paths.items()
        }

    display_frames = data.get("display_frames")
    if isinstance(display_frames, dict):
        data["display_frames"] = {
            str(frame_idx): _to_relpath(path, output_dir)
            for frame_idx, path in display_frames.items()
        }

    return data


def _build_state_snapshot(state):
    """Capture relevant generation settings from project state."""
    snapshot = {
        "mode": state.current_mode,
        "image_format": state.image_format,
        "mesh_format": state.mesh_format,
        "sampling": {
            "start": int(state.initial_frame),
            "end": int(state.last_frame),
            "skip": int(state.sampling_rate),
        },
    }

    mode = state.current_mode
    if mode == "Slice":
        snapshot["mode_settings"] = {
            "slit_position": int(state.slit_position),
            "slit_width": int(state.slit_width),
            "slit_orientation": state.slit_orientation,
            "orthogonal_enabled": bool(state.orthogonal_enabled),
            "ortho_position": int(state.ortho_position),
            "ortho_width": int(state.ortho_width),
            "display_frames_mode": state.display_frames_mode,
            "display_frames_n": int(state.display_frames_n),
            "display_frames_list": state.display_frames_list,
        }
    elif mode == "Cuboid":
        snapshot["mode_settings"] = {
            "border_left": int(state.cuboid_border_left),
            "border_right": int(state.cuboid_border_right),
            "border_top": int(state.cuboid_border_top),
            "border_bottom": int(state.cuboid_border_bottom),
            "fill_mode": state.cuboid_fill_mode,
            "preview_enabled": bool(state.cuboid_preview_enabled),
            "extraction_mode": state.extraction_mode,
        }
    elif mode == "Cylinder":
        snapshot["mode_settings"] = {
            "center_x": int(state.cylinder_center_x),
            "center_y": int(state.cylinder_center_y),
            "radius": int(state.cylinder_radius),
            "fill_mode": state.cylinder_fill_mode,
            "preview_enabled": bool(state.cylinder_preview_enabled),
            "preview_quality": state.cylinder_preview_quality,
        }
    elif mode == "Rings":
        snapshot["mode_settings"] = {
            "center_x": int(state.rings_center_x),
            "center_y": int(state.rings_center_y),
            "sampling_mode": state.rings_sampling_mode,
            "max_output": int(state.rings_max_output),
            "reverse_time": bool(state.rings_reverse_time),
        }
    elif mode == "Slit-tear":
        snapshot["mode_settings"] = {
            "line_width": int(state.slittear_line_width),
        }

    return snapshot


def build_export_metadata(state, result):
    """Build the metadata payload for a generated output folder."""
    output_dir = result.get("output_dir", "")
    vs = state.video_source

    source_video = {
        "filename": os.path.basename(vs.file_path) if vs and vs.file_path else "",
    }

    if vs is not None:
        source_video.update(
            {
                "fps": float(vs.fps),
                "frame_count": int(vs.frame_count),
                "width": int(vs.width),
                "height": int(vs.height),
                "resolution": {
                    "width": int(vs.width),
                    "height": int(vs.height),
                },
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "mode": state.current_mode,
        "source_video": source_video,
        "sampling": {
            "start": int(state.initial_frame),
            "end": int(state.last_frame),
            "skip": int(state.sampling_rate),
        },
        "state_snapshot": _build_state_snapshot(state),
        "preview_result": _relativize_result_paths(result, output_dir),
    }


def save_export_metadata(output_dir, state, result):
    """Write metadata.json into output_dir and return the file path."""
    if not output_dir:
        raise ValueError("output_dir is required")

    payload = build_export_metadata(state, result)
    path = os.path.join(output_dir, METADATA_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True, default=_json_default)
    return path


def load_export_metadata(folder_path):
    """Load metadata.json from a preview/export folder."""
    path = os.path.join(folder_path, METADATA_FILENAME)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_preview_result_paths(preview_result, folder_path):
    """Resolve relative artifact paths in preview_result to absolute paths."""
    data = deepcopy(preview_result)
    data["output_dir"] = folder_path

    for key in ("image_path", "vertical_path", "horizontal_path", "frames_dir", "mesh_path"):
        if key in data:
            data[key] = _to_abspath(data[key], folder_path)

    face_paths = data.get("face_paths")
    if isinstance(face_paths, dict):
        data["face_paths"] = {
            name: _to_abspath(path, folder_path) for name, path in face_paths.items()
        }

    display_frames = data.get("display_frames")
    if isinstance(display_frames, dict):
        resolved_frames = {}
        for frame_idx, path in display_frames.items():
            try:
                key = int(frame_idx)
            except Exception:
                key = frame_idx
            resolved_frames[key] = _to_abspath(path, folder_path)
        data["display_frames"] = resolved_frames

    return data
