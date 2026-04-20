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
- `candidate_frames/<image>.jpg`: one frame per scene.

Skipped if outputs already exist (unless `force=True`).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


# Default ContentDetector threshold. PySceneDetect's recommended baseline.
DEFAULT_THRESHOLD = 27.0


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
    # `$SCENE_NUMBER` template renders 1-based.
    scenes: list[dict] = []
    missing: list[int] = []
    for i, (start, end) in enumerate(scene_list):
        files = saved.get(i, [])
        frame_name = files[0] if files else None
        if not frame_name:
            missing.append(i + 1)
        midpoint = (start.get_seconds() + end.get_seconds()) / 2.0
        scenes.append(
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
    if missing:
        raise RuntimeError(
            f"save_images did not produce a frame for scene(s) {missing}"
        )

    return {
        "video": video_path.name,
        "detector": "ContentDetector",
        "threshold": threshold,
        "fallback": fallback,
        "scene_count": len(scenes),
        "frames_dir": frames_dir.name,
        "scenes": scenes,
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
        update_stage(
            paths,
            "scenes",
            COMPLETED,
            extra={
                "scenes": data.get("scene_count", len(data.get("scenes", []))),
                "fallback": bool(data.get("fallback", False)),
                "frames_dir": paths.candidate_frames_dir.name,
                "skipped": True,
            },
        )
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

        update_stage(
            paths,
            "scenes",
            COMPLETED,
            extra={
                "scenes": data["scene_count"],
                "fallback": data.get("fallback", False),
                "frames_dir": paths.candidate_frames_dir.name,
                "threshold": threshold,
            },
        )
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
