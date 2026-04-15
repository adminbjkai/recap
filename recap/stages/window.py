"""Phase 3 slice: transcript-window alignment per candidate frame.

Reads `transcript.json` and `scenes.json` and writes `frame_windows.json`:
for each candidate frame, the set of transcript segments that fall within
a fixed plus/minus WINDOW_SECONDS window around the scene's
`midpoint_seconds`, and the whitespace-normalized concatenation of their
text.

This stage is deterministic. It performs no chaptering, no OpenCLIP
embedding, no VLM work, no report changes. It is opt-in via
`recap window` and is not invoked by `recap run`.

Skipped if `frame_windows.json` already matches the current
`transcript.json` and `scenes.json` (unless `force=True`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


# Half-width of the fuzzy transcript window around each frame's midpoint,
# in seconds. The brief specifies a plus/minus 5 to 7 second range; 6.0 is
# the midpoint and is fixed at the code level.
WINDOW_SECONDS = 6.0


_WS_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _load_json(path: Path, label: str) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found at {path}")
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{label} is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} must be a JSON object")
    return data


def _load_transcript(paths: JobPaths) -> tuple[list[dict], float | None]:
    data = _load_json(paths.transcript_json, "transcript.json")
    segments = data.get("segments")
    if not isinstance(segments, list):
        raise RuntimeError("transcript.json is missing a 'segments' list")
    normalized: list[dict] = []
    for seg in segments:
        if not isinstance(seg, dict):
            raise RuntimeError("transcript.json has a non-object segment")
        if "id" not in seg or "start" not in seg or "end" not in seg:
            raise RuntimeError(
                "transcript.json segment is missing id/start/end"
            )
        normalized.append(
            {
                "id": seg["id"],
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                "text": str(seg.get("text", "")),
            }
        )
    duration = data.get("duration")
    if duration is not None:
        duration = float(duration)
    return normalized, duration


def _load_scenes(paths: JobPaths) -> list[dict]:
    data = _load_json(paths.scenes_json, "scenes.json")
    scenes = data.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        raise RuntimeError("scenes.json has no scenes")
    for s in scenes:
        if not isinstance(s, dict):
            raise RuntimeError("scenes.json has a non-object scene entry")
        if s.get("index") is None:
            raise RuntimeError("scenes.json scene is missing 'index'")
        if not s.get("frame_file"):
            raise RuntimeError(
                f"scenes.json scene {s.get('index')!r} has no frame_file"
            )
        if s.get("midpoint_seconds") is None:
            raise RuntimeError(
                f"scenes.json scene {s.get('index')!r} has no midpoint_seconds"
            )
    return scenes


def _segments_in_window(
    segments: list[dict], window_start: float, window_end: float
) -> list[dict]:
    overlapping: list[dict] = []
    for seg in segments:
        if seg["start"] < window_end and seg["end"] > window_start:
            overlapping.append(seg)
    return overlapping


def _compute(
    scenes: list[dict],
    segments: list[dict],
    duration: float | None,
    video: str | None,
    paths: JobPaths,
) -> dict:
    frames: list[dict] = []
    frames_with_text_count = 0
    for s in scenes:
        midpoint = float(s["midpoint_seconds"])
        window_start = max(0.0, midpoint - WINDOW_SECONDS)
        window_end = midpoint + WINDOW_SECONDS
        if duration is not None:
            window_end = min(window_end, duration)
        overlapping = _segments_in_window(segments, window_start, window_end)
        segment_ids = [seg["id"] for seg in overlapping]
        window_text = _normalize_text(" ".join(seg["text"] for seg in overlapping))
        if window_text:
            frames_with_text_count += 1
        frames.append(
            {
                "scene_index": s["index"],
                "frame_file": s["frame_file"],
                "midpoint_seconds": midpoint,
                "window_start": window_start,
                "window_end": window_end,
                "segment_ids": segment_ids,
                "window_text": window_text,
            }
        )

    return {
        "video": video,
        "transcript_source": paths.transcript_json.name,
        "scenes_source": paths.scenes_json.name,
        "window_seconds": WINDOW_SECONDS,
        "frame_count": len(frames),
        "frames_with_text_count": frames_with_text_count,
        "frames": frames,
    }


def _outputs_match(paths: JobPaths, scenes: list[dict]) -> bool:
    if not paths.frame_windows_json.exists():
        return False
    try:
        with open(paths.frame_windows_json) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("transcript_source") != paths.transcript_json.name:
        return False
    if data.get("scenes_source") != paths.scenes_json.name:
        return False
    if data.get("window_seconds") != WINDOW_SECONDS:
        return False
    entries = data.get("frames")
    if not isinstance(entries, list) or len(entries) != len(scenes):
        return False
    for entry, scene in zip(entries, scenes):
        if entry.get("scene_index") != scene.get("index"):
            return False
        if entry.get("frame_file") != scene.get("frame_file"):
            return False
        if entry.get("midpoint_seconds") != scene.get("midpoint_seconds"):
            return False
    return True


def run(paths: JobPaths, force: bool = False) -> dict:
    scenes = _load_scenes(paths)
    # Validate transcript.json on every invocation so a stale `frame_windows.json`
    # cannot short-circuit past a missing or malformed transcript.
    segments, duration = _load_transcript(paths)

    if not force and _outputs_match(paths, scenes):
        with open(paths.frame_windows_json) as f:
            data = json.load(f)
        update_stage(
            paths,
            "window",
            COMPLETED,
            extra={
                "frame_count": data.get("frame_count", len(data.get("frames", []))),
                "frames_with_text_count": data.get("frames_with_text_count", 0),
                "window_seconds": WINDOW_SECONDS,
                "skipped": True,
            },
        )
        return data

    scenes_data = _load_json(paths.scenes_json, "scenes.json")
    video = scenes_data.get("video")

    update_stage(paths, "window", RUNNING)
    try:
        if force and paths.frame_windows_json.exists():
            paths.frame_windows_json.unlink()

        data = _compute(scenes, segments, duration, video, paths)

        tmp = paths.frame_windows_json.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp.replace(paths.frame_windows_json)

        update_stage(
            paths,
            "window",
            COMPLETED,
            extra={
                "frame_count": data["frame_count"],
                "frames_with_text_count": data["frames_with_text_count"],
                "window_seconds": WINDOW_SECONDS,
            },
        )
        return data
    except Exception as e:
        update_stage(paths, "window", FAILED, error=f"{type(e).__name__}: {e}")
        raise
