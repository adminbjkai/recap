"""Stage 5: Candidate frame extraction.

Reads `analysis.mp4`, runs PySceneDetect's `ContentDetector` to find scene
boundaries, writes `scenes.json`, and extracts one representative frame per
scene into `candidate_frames/`. If the detector finds no cuts, the whole
video is treated as a single fallback scene so downstream stages still get
exactly one candidate frame.

Outputs:
- `scenes.json`: detector config, scene list with start/end timestamps and
  frame numbers, the path of the extracted frame for each scene, and a
  `fallback` flag indicating whether the single-scene fallback was used.
  Scenes whose frame extraction was silently dropped by
  ``save_images`` are **not** included in ``scenes`` (downstream
  stages depend on every entry having a usable ``frame_file``).
  Those scenes are recorded instead under a new top-level
  ``skipped_scenes`` list so the information is auditable from
  disk.
- `candidate_frames/<image>.jpg`: one frame per surviving scene.

Skipped if outputs already exist (unless `force=True`).

Resilience:
  ``save_images`` (PySceneDetect's image extractor) occasionally
  misses a small number of scenes — the upstream bug filed against
  this repo reported
  ``save_images did not produce a frame for scene(s) [214, 218, 219, 220]``
  while 200+ frames were produced cleanly. Previously the stage
  raised a ``RuntimeError`` on any missing frame, throwing away
  every successfully-produced frame. The stage now tolerates a
  small miss rate, records skipped scene IDs, and continues
  with available frames. It still fails cleanly when zero frames
  were produced or when the miss ratio exceeds a conservative
  threshold (default 25%, env-overridable via
  ``RECAP_SCENES_MAX_MISSING_RATIO``).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


# Default ContentDetector threshold. PySceneDetect's recommended baseline.
DEFAULT_THRESHOLD = 27.0

# Upper bound on the fraction of scenes ``save_images`` is allowed to
# silently skip before the stage fails. Keep this conservative — a
# large miss rate usually indicates a corrupted video, not a backend
# hiccup. Env override ``RECAP_SCENES_MAX_MISSING_RATIO`` accepts a
# float in [0, 1]; values outside that range fall back to the default.
DEFAULT_MAX_MISSING_RATIO = 0.25


def _max_missing_ratio() -> float:
    raw = os.environ.get("RECAP_SCENES_MAX_MISSING_RATIO")
    if raw is None or raw == "":
        return DEFAULT_MAX_MISSING_RATIO
    try:
        val = float(raw)
    except ValueError:
        return DEFAULT_MAX_MISSING_RATIO
    if val < 0 or val > 1:
        return DEFAULT_MAX_MISSING_RATIO
    return val


def partition_scene_records(
    pre_scenes: list[dict],
    max_missing_ratio: float = DEFAULT_MAX_MISSING_RATIO,
) -> tuple[list[dict], list[dict]]:
    """Split pre-built scene dicts into (kept, skipped).

    Pure helper: takes a list of scene dicts (each already carrying
    ``index``, start / end seconds + frames, ``midpoint_seconds``,
    and an **optional** ``frame_file`` — ``None`` or missing when
    ``save_images`` skipped the scene) and returns:

    - ``kept``: scenes whose ``frame_file`` is a non-empty string.
      These are the only scenes downstream stages will see.
    - ``skipped``: scenes that lacked a ``frame_file``; stripped
      of the ``frame_file`` key so the payload is smaller and
      cannot be mistaken for a usable scene.

    Raises ``RuntimeError`` when:

    - The input is empty (no scenes at all), or
    - Every scene was skipped, or
    - ``len(skipped) / len(pre_scenes) > max_missing_ratio``.

    The error messages are deliberately human-readable and include
    both the skipped scene IDs and the ratio so the surfaced CLI /
    UI error is immediately actionable.
    """
    total = len(pre_scenes)
    if total == 0:
        raise RuntimeError("scenes stage produced no scenes")
    kept: list[dict] = []
    skipped: list[dict] = []
    for scene in pre_scenes:
        frame_file = scene.get("frame_file")
        if isinstance(frame_file, str) and frame_file:
            kept.append(scene)
        else:
            trimmed = {k: v for k, v in scene.items() if k != "frame_file"}
            skipped.append(trimmed)
    if not kept:
        ids = [s.get("index") for s in skipped]
        raise RuntimeError(
            f"save_images produced no frames for any of the "
            f"{total} detected scene(s); missing={ids}"
        )
    ratio = len(skipped) / total if total else 0.0
    if ratio > max_missing_ratio:
        ids = [s.get("index") for s in skipped]
        raise RuntimeError(
            f"save_images missed {len(skipped)}/{total} scene(s) "
            f"({ratio:.0%} > {max_missing_ratio:.0%}); missing={ids}. "
            "Set RECAP_SCENES_MAX_MISSING_RATIO to raise the tolerance."
        )
    return kept, skipped


def _detect_and_extract(video_path: Path, frames_dir: Path, threshold: float) -> dict:
    from scenedetect import ContentDetector, detect, open_video
    from scenedetect.scene_manager import save_images

    scene_list = detect(str(video_path), ContentDetector(threshold=threshold))

    video = open_video(str(video_path))
    fallback = False
    if not scene_list:
        # No cuts detected: synthesize one scene that spans the whole video so
        # downstream stages still receive exactly one candidate frame.
        scene_list = [(video.base_timecode, video.duration)]
        fallback = True

    frames_dir.mkdir(parents=True, exist_ok=True)

    image_template = "scene-$SCENE_NUMBER"
    saved = save_images(
        scene_list=scene_list,
        video=video,
        num_images=1,
        frame_margin=1,
        image_extension="jpg",
        image_name_template=image_template,
        output_dir=str(frames_dir),
        show_progress=False,
    )

    # save_images keys the returned dict by 0-based scene position, while the
    # `$SCENE_NUMBER` template renders 1-based. Build the full pre-filter
    # list first, then hand it to ``partition_scene_records`` to tolerate
    # a small fraction of silent ``save_images`` misses.
    pre_scenes: list[dict] = []
    for i, (start, end) in enumerate(scene_list):
        files = saved.get(i, [])
        frame_name = files[0] if files else None
        midpoint = (start.get_seconds() + end.get_seconds()) / 2.0
        pre_scenes.append(
            {
                "index": i + 1,
                "start_seconds": start.get_seconds(),
                "end_seconds": end.get_seconds(),
                "start_frame": start.get_frames(),
                "end_frame": end.get_frames(),
                "midpoint_seconds": midpoint,
                "frame_file": frame_name,
            }
        )

    scenes, skipped_scenes = partition_scene_records(
        pre_scenes, _max_missing_ratio(),
    )

    return {
        "video": video_path.name,
        "detector": "ContentDetector",
        "threshold": threshold,
        "fallback": fallback,
        "scene_count": len(scenes),
        "frames_dir": frames_dir.name,
        "scenes": scenes,
        "skipped_count": len(skipped_scenes),
        "skipped_scenes": skipped_scenes,
    }


def _outputs_exist(paths: JobPaths) -> bool:
    if not paths.scenes_json.exists():
        return False
    if not paths.candidate_frames_dir.is_dir():
        return False
    try:
        with open(paths.scenes_json) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    scenes = data.get("scenes", [])
    if not scenes:
        return False
    for s in scenes:
        name = s.get("frame_file")
        if not name:
            return False
        if not (paths.candidate_frames_dir / name).is_file():
            return False
    return True


def run(paths: JobPaths, force: bool = False, threshold: float = DEFAULT_THRESHOLD) -> dict:
    if not paths.analysis_mp4.exists():
        raise FileNotFoundError("analysis.mp4 not found; run normalize first")

    if not force and _outputs_exist(paths):
        with open(paths.scenes_json) as f:
            data = json.load(f)
        extras = {
            "scenes": data.get("scene_count", len(data.get("scenes", []))),
            "fallback": bool(data.get("fallback", False)),
            "frames_dir": paths.candidate_frames_dir.name,
            "skipped": True,
        }
        if isinstance(data.get("skipped_count"), int):
            extras["skipped_scene_count"] = data["skipped_count"]
        update_stage(paths, "scenes", COMPLETED, extra=extras)
        return data

    update_stage(paths, "scenes", RUNNING)
    try:
        if force:
            if paths.candidate_frames_dir.exists():
                shutil.rmtree(paths.candidate_frames_dir)
            if paths.scenes_json.exists():
                paths.scenes_json.unlink()

        data = _detect_and_extract(paths.analysis_mp4, paths.candidate_frames_dir, threshold)

        tmp = paths.scenes_json.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp.replace(paths.scenes_json)

        extras: dict = {
            "scenes": data["scene_count"],
            "fallback": data.get("fallback", False),
            "frames_dir": paths.candidate_frames_dir.name,
            "threshold": threshold,
        }
        if data.get("skipped_count"):
            extras["skipped_scene_count"] = data["skipped_count"]
            extras["skipped_scene_ids"] = [
                s.get("index")
                for s in data.get("skipped_scenes", [])
                if isinstance(s.get("index"), int)
            ]
        update_stage(paths, "scenes", COMPLETED, extra=extras)
        return data
    except KeyboardInterrupt:
        # Ctrl-C during PySceneDetect's cv2 frame loop would otherwise
        # leave `stages.scenes.status` as "running" because
        # KeyboardInterrupt is a BaseException and bypasses the broader
        # `except Exception` below. Mark the stage FAILED so the
        # CLI/UI don't show a stuck run, clean up the partial artifacts
        # from this recompute attempt, then re-raise so the CLI still
        # exits with the usual interrupt status.
        _cleanup_partial_artifacts(paths)
        update_stage(
            paths, "scenes", FAILED,
            error="KeyboardInterrupt: interrupted by user",
        )
        raise
    except Exception as e:
        update_stage(paths, "scenes", FAILED, error=f"{type(e).__name__}: {e}")
        raise


def _cleanup_partial_artifacts(paths: JobPaths) -> None:
    """Remove partially-written artifacts from an interrupted recompute.

    Only reached from the KeyboardInterrupt handler inside `run()`,
    which is itself only entered AFTER the skip-check. So by
    construction this helper never runs on a skip path and the caller
    has already committed to recomputing — either because `--force`
    was passed (in which case the prior `scenes.json` and
    `candidate_frames/` have already been torn down upstream) or
    because `_outputs_exist(paths)` returned False (in which case any
    pre-existing `scenes.json` was deemed stale).

    Best-effort: swallow OS errors so the outer handler can still
    record a clean FAILED state. Removes:

    - `candidate_frames/` — partial frames from the interrupted
      attempt (or stale frames from a prior incomplete run).
    - `scenes.json.tmp` — in-progress atomic write.
    - `scenes.json` — the pre-recompute artifact; the recompute
      branch considered it either absent (`--force`) or stale
      (`_outputs_exist` returned False), so it must not linger as
      a mismatched pair with an empty / partially-populated
      `candidate_frames/`.
    """
    try:
        if paths.candidate_frames_dir.exists():
            shutil.rmtree(paths.candidate_frames_dir, ignore_errors=True)
    except OSError:
        pass
    try:
        tmp = paths.scenes_json.with_suffix(".json.tmp")
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass
    try:
        if paths.scenes_json.exists():
            paths.scenes_json.unlink()
    except OSError:
        pass
