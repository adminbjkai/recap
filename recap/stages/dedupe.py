"""Phase 2 slice: pHash-based duplicate marking.

Reads `scenes.json` and the JPEGs in `candidate_frames/`, computes a
perceptual hash (pHash) for each candidate frame, and marks a frame as a
duplicate of its immediate predecessor when their Hamming distance is at
or below a fixed code-level threshold. Results are written to
`frame_scores.json`.

This stage does nothing else: no SSIM, no OCR, no embeddings, no chapter
proposal, no frame deletion. It is opt-in via `recap dedupe` and is not
invoked by `recap run`.

Skipped if `frame_scores.json` already matches the current `scenes.json`
and `candidate_frames/` (unless `force=True`).
"""

from __future__ import annotations

import json
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


# pHash hash size in bits per side; 8 -> 64-bit hash.
HASH_SIZE = 8

# Inclusive Hamming-distance threshold for marking a frame as a duplicate
# of its immediate predecessor. Fixed at the code level for this slice.
DUPLICATE_THRESHOLD = 5


def _load_scenes(paths: JobPaths) -> dict:
    if not paths.scenes_json.exists():
        raise FileNotFoundError(
            "scenes.json not found; run `recap scenes` first"
        )
    try:
        with open(paths.scenes_json) as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"scenes.json is not valid JSON: {e}") from e


def _validate_inputs(paths: JobPaths, scenes_data: dict) -> list[dict]:
    if not paths.candidate_frames_dir.is_dir():
        raise FileNotFoundError(
            "candidate_frames/ not found; run `recap scenes` first"
        )
    scenes = scenes_data.get("scenes") or []
    if not scenes:
        raise RuntimeError("scenes.json contains no scenes")

    missing: list[str] = []
    for s in scenes:
        name = s.get("frame_file")
        if not name:
            raise RuntimeError(
                f"scene {s.get('index')!r} in scenes.json has no frame_file"
            )
        if not (paths.candidate_frames_dir / name).is_file():
            missing.append(name)
    if missing:
        raise RuntimeError(
            "scenes.json and candidate_frames/ disagree; missing frame file(s): "
            + ", ".join(missing)
        )
    return scenes


def _compute(paths: JobPaths, scenes: list[dict], scenes_data: dict) -> dict:
    import imagehash
    from PIL import Image

    entries: list[dict] = []
    duplicate_count = 0
    prev_hash = None
    prev_index = None

    for s in scenes:
        index = s.get("index")
        frame_file = s["frame_file"]
        frame_path = paths.candidate_frames_dir / frame_file
        with Image.open(frame_path) as img:
            h = imagehash.phash(img, hash_size=HASH_SIZE)

        if prev_hash is None:
            distance = None
            duplicate_of = None
        else:
            distance = int(h - prev_hash)
            duplicate_of = prev_index if distance <= DUPLICATE_THRESHOLD else None
            if duplicate_of is not None:
                duplicate_count += 1

        entries.append(
            {
                "scene_index": index,
                "frame_file": frame_file,
                "phash": str(h),
                "duplicate_of": duplicate_of,
                "hamming_distance": distance,
            }
        )
        prev_hash = h
        prev_index = index

    return {
        "video": scenes_data.get("video"),
        "scenes_source": paths.scenes_json.name,
        "frames_dir": paths.candidate_frames_dir.name,
        "metric": "phash",
        "hash_size": HASH_SIZE,
        "duplicate_threshold": DUPLICATE_THRESHOLD,
        "frame_count": len(entries),
        "duplicate_count": duplicate_count,
        "frames": entries,
    }


def _outputs_match(paths: JobPaths, scenes: list[dict]) -> bool:
    if not paths.frame_scores_json.exists():
        return False
    try:
        with open(paths.frame_scores_json) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("metric") != "phash":
        return False
    if data.get("hash_size") != HASH_SIZE:
        return False
    if data.get("duplicate_threshold") != DUPLICATE_THRESHOLD:
        return False
    entries = data.get("frames") or []
    if len(entries) != len(scenes):
        return False
    for entry, scene in zip(entries, scenes):
        if entry.get("scene_index") != scene.get("index"):
            return False
        if entry.get("frame_file") != scene.get("frame_file"):
            return False
        if not entry.get("phash"):
            return False
        name = entry.get("frame_file")
        if not name or not (paths.candidate_frames_dir / name).is_file():
            return False
    return True


def run(paths: JobPaths, force: bool = False) -> dict:
    scenes_data = _load_scenes(paths)
    scenes = _validate_inputs(paths, scenes_data)

    if not force and _outputs_match(paths, scenes):
        with open(paths.frame_scores_json) as f:
            data = json.load(f)
        update_stage(
            paths,
            "dedupe",
            COMPLETED,
            extra={
                "frame_count": data.get("frame_count", len(data.get("frames", []))),
                "duplicate_count": data.get("duplicate_count", 0),
                "metric": "phash",
                "skipped": True,
            },
        )
        return data

    update_stage(paths, "dedupe", RUNNING)
    try:
        if force and paths.frame_scores_json.exists():
            paths.frame_scores_json.unlink()

        data = _compute(paths, scenes, scenes_data)

        tmp = paths.frame_scores_json.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        tmp.replace(paths.frame_scores_json)

        update_stage(
            paths,
            "dedupe",
            COMPLETED,
            extra={
                "frame_count": data["frame_count"],
                "duplicate_count": data["duplicate_count"],
                "metric": "phash",
                "duplicate_threshold": DUPLICATE_THRESHOLD,
            },
        )
        return data
    except Exception as e:
        update_stage(paths, "dedupe", FAILED, error=f"{type(e).__name__}: {e}")
        raise
