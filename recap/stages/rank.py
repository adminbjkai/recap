"""Phase 3 slice: per-chapter deterministic ranking fusion.

Reads `scenes.json`, `chapter_candidates.json`, `frame_scores.json`,
`frame_windows.json`, and `frame_similarities.json` and writes
`frame_ranks.json`.  For each candidate frame, a composite score is
computed from the existing per-frame signals (OpenCLIP similarity,
OCR text novelty, and duplicate status) and the frames are ranked
within each chapter.

This is a marking-only stage.  It does NOT apply keep/reject
thresholds, enforce a screenshot budget, produce captions, write
`selected_frames.json`, modify `report.md`, or invoke any VLM.  It
is opt-in via `recap rank` and is not invoked by `recap run`.

`W_CLIP` (`1.0`), `W_OCR` (`0.5`), `W_DUP` (`0.5`),
`MISSING_SIMILARITY_VALUE` (`0.0`), `MISSING_NOVELTY_VALUE` (`0.0`),
and `SOURCE_SIGNALS` (`"phash+ssim+ocr+clip"`) are fixed code-level
constants.  They are not exposed as CLI flags, env vars, or config.
A later slice may retune these weights, at which point
`SOURCE_SIGNALS` or the weight values change and the skip contract
invalidates any stored `frame_ranks.json`.

Skipped if `frame_ranks.json` already matches a fresh recomputation
from the current inputs (unless `force=True`).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


# ---- fixed code-level constants (not CLI flags / env / config) ----------

W_CLIP = 1.0
W_OCR = 0.5
W_DUP = 0.5               # penalty subtracted when duplicate_of is not None
MISSING_SIMILARITY_VALUE = 0.0
MISSING_NOVELTY_VALUE = 0.0
SOURCE_SIGNALS = "phash+ssim+ocr+clip"


# ---- helpers ------------------------------------------------------------

def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


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


def _require_list(data: dict, key: str, label: str) -> list:
    val = data.get(key)
    if not isinstance(val, list):
        raise RuntimeError(f"{label} is missing a '{key}' list")
    if not val:
        raise RuntimeError(f"{label} has an empty '{key}' list")
    return val


def _fingerprint(data: object) -> str:
    """SHA-256 hex digest of canonical JSON."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _extract_ordered_scene_indices(
    frames: list, label: str, key: str = "scene_index",
) -> list[int]:
    """Return the ordered list of scene indices, rejecting duplicates."""
    indices: list[int] = []
    seen: set[int] = set()
    for i, f in enumerate(frames):
        if not isinstance(f, dict):
            raise RuntimeError(
                f"{label} entry at index {i} is not an object"
            )
        if key not in f:
            raise RuntimeError(
                f"{label} entry at index {i} is missing '{key}'"
            )
        idx = f[key]
        if idx in seen:
            raise RuntimeError(
                f"{label} has duplicate {key} {idx}"
            )
        seen.add(idx)
        indices.append(idx)
    return indices


# ---- input loading -------------------------------------------------------

def _load_scenes(paths: JobPaths) -> tuple[dict, list[dict], list[int]]:
    """Return (raw_data, scenes_list, ordered_scene_indices)."""
    data = _load_json(paths.scenes_json, "scenes.json")
    scenes = _require_list(data, "scenes", "scenes.json")
    indices = _extract_ordered_scene_indices(scenes, "scenes.json", key="index")
    for i, s in enumerate(scenes):
        for field in ("frame_file", "midpoint_seconds"):
            if field not in s:
                raise RuntimeError(
                    f"scenes.json scene at index {i} is missing '{field}'"
                )
    return data, scenes, indices


def _load_chapters(data: dict) -> list[dict]:
    """Validate and return chapters from pre-loaded chapter_candidates data."""
    chapters = _require_list(data, "chapters", "chapter_candidates.json")
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            raise RuntimeError(
                f"chapter_candidates.json chapter at index {i} is not an object"
            )
        for field in ("index", "start_seconds", "end_seconds"):
            if field not in ch:
                raise RuntimeError(
                    f"chapter_candidates.json chapter at index {i} "
                    f"is missing '{field}'"
                )
    # contiguity check
    if chapters[0]["start_seconds"] != 0.0:
        raise RuntimeError(
            "chapter_candidates.json first chapter does not start at 0.0"
        )
    for i in range(len(chapters) - 1):
        if chapters[i]["end_seconds"] != chapters[i + 1]["start_seconds"]:
            raise RuntimeError(
                f"chapter_candidates.json gap between chapter {i + 1} "
                f"and chapter {i + 2}: {chapters[i]['end_seconds']} != "
                f"{chapters[i + 1]['start_seconds']}"
            )
    return chapters


def _load_scores(paths: JobPaths) -> tuple[dict, dict[int, dict], list[int]]:
    """Return (raw_data, by_scene_index, ordered_scene_indices)."""
    data = _load_json(paths.frame_scores_json, "frame_scores.json")
    frames = _require_list(data, "frames", "frame_scores.json")
    indices = _extract_ordered_scene_indices(
        frames, "frame_scores.json",
    )
    by_idx: dict[int, dict] = {}
    for i, f in enumerate(frames):
        for field in ("duplicate_of", "text_novelty"):
            if field not in f:
                raise RuntimeError(
                    f"frame_scores.json frame at index {i} "
                    f"is missing '{field}'"
                )
        by_idx[f["scene_index"]] = f
    return data, by_idx, indices


def _load_similarities(
    paths: JobPaths,
) -> tuple[dict, dict[int, dict], list[int]]:
    """Return (raw_data, by_scene_index, ordered_scene_indices)."""
    data = _load_json(
        paths.frame_similarities_json, "frame_similarities.json"
    )
    frames = _require_list(data, "frames", "frame_similarities.json")
    indices = _extract_ordered_scene_indices(
        frames, "frame_similarities.json",
    )
    by_idx: dict[int, dict] = {}
    for i, f in enumerate(frames):
        if "clip_similarity" not in f:
            raise RuntimeError(
                f"frame_similarities.json frame at index {i} "
                "is missing 'clip_similarity'"
            )
        by_idx[f["scene_index"]] = f
    return data, by_idx, indices


# ---- core logic ----------------------------------------------------------

def _assign_chapter(
    midpoint: float,
    chapters: list[dict],
) -> int | None:
    """Return the 1-based chapter index for *midpoint*, or None."""
    for i, ch in enumerate(chapters):
        is_last = i == len(chapters) - 1
        start = ch["start_seconds"]
        end = ch["end_seconds"]
        if is_last:
            if start <= midpoint <= end:
                return ch["index"]
        else:
            if start <= midpoint < end:
                return ch["index"]
    return None


def _composite(clip_sim: object, text_nov: object, dup_of: object) -> float:
    cs = (
        float(clip_sim)
        if clip_sim is not None and _is_number(clip_sim)
        else MISSING_SIMILARITY_VALUE
    )
    tn = (
        float(text_nov)
        if text_nov is not None and _is_number(text_nov)
        else MISSING_NOVELTY_VALUE
    )
    penalty = W_DUP if dup_of is not None else 0.0
    return W_CLIP * cs + W_OCR * tn - penalty


def _compute(
    paths: JobPaths,
    scenes: list[dict],
    chapters: list[dict],
    scores: dict[int, dict],
    sims: dict[int, dict],
    fingerprints: dict[str, str],
) -> dict:
    video = paths.analysis_mp4.name if paths.analysis_mp4.exists() else None

    # Build per-chapter frame buckets keyed by chapter_index.
    chapter_buckets: dict[int, list[dict]] = {
        ch["index"]: [] for ch in chapters
    }

    for sc in scenes:
        si = sc["index"]
        mid = sc["midpoint_seconds"]
        ch_idx = _assign_chapter(mid, chapters)
        if ch_idx is None:
            raise RuntimeError(
                f"scene {si} midpoint {mid} falls outside all chapters"
            )

        score_rec = scores[si]
        sim_rec = sims[si]

        clip_sim = sim_rec.get("clip_similarity")
        text_nov = score_rec.get("text_novelty")
        dup_of = score_rec.get("duplicate_of")

        chapter_buckets[ch_idx].append(
            {
                "clip_similarity": clip_sim,
                "composite_score": _composite(clip_sim, text_nov, dup_of),
                "duplicate_of": dup_of,
                "frame_file": sc["frame_file"],
                "midpoint_seconds": mid,
                "scene_index": si,
                "text_novelty": text_nov,
            }
        )

    # Sort and assign ranks.
    out_chapters: list[dict] = []
    total_frames = 0
    for ch in chapters:
        bucket = chapter_buckets[ch["index"]]
        bucket.sort(key=lambda f: (-f["composite_score"], f["scene_index"]))
        for rank, fr in enumerate(bucket, 1):
            fr["rank"] = rank
        total_frames += len(bucket)
        out_chapters.append(
            {
                "chapter_index": ch["index"],
                "end_seconds": ch["end_seconds"],
                "frame_count": len(bucket),
                "frames": bucket,
                "start_seconds": ch["start_seconds"],
            }
        )

    return {
        "chapter_count": len(chapters),
        "chapters": out_chapters,
        "chapters_source": paths.chapter_candidates_json.name,
        "frame_count": total_frames,
        "input_fingerprints": fingerprints,
        "missing_novelty_value": MISSING_NOVELTY_VALUE,
        "missing_similarity_value": MISSING_SIMILARITY_VALUE,
        "scenes_source": paths.scenes_json.name,
        "scores_source": paths.frame_scores_json.name,
        "similarities_source": paths.frame_similarities_json.name,
        "source_signals": SOURCE_SIGNALS,
        "video": video,
        "weights": {
            "clip_similarity": W_CLIP,
            "duplicate_penalty": W_DUP,
            "text_novelty": W_OCR,
        },
        "windows_source": paths.frame_windows_json.name,
    }


# ---- skip contract -------------------------------------------------------

_CHAPTER_FIELDS = ("chapter_index", "start_seconds", "end_seconds", "frame_count")
_FRAME_FIELDS = (
    "rank",
    "scene_index",
    "frame_file",
    "midpoint_seconds",
    "clip_similarity",
    "text_novelty",
    "duplicate_of",
    "composite_score",
)


def _outputs_match(paths: JobPaths, fresh: dict) -> bool:
    if not paths.frame_ranks_json.exists():
        return False
    try:
        with open(paths.frame_ranks_json) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    # top-level scalars
    for key in (
        "scenes_source",
        "chapters_source",
        "scores_source",
        "windows_source",
        "similarities_source",
        "source_signals",
        "missing_similarity_value",
        "missing_novelty_value",
        "chapter_count",
        "frame_count",
    ):
        if data.get(key) != fresh[key]:
            return False
    if data.get("weights") != fresh["weights"]:
        return False
    if data.get("input_fingerprints") != fresh["input_fingerprints"]:
        return False
    stored_chs = data.get("chapters")
    if not isinstance(stored_chs, list) or len(stored_chs) != len(fresh["chapters"]):
        return False
    for s_ch, f_ch in zip(stored_chs, fresh["chapters"]):
        if not isinstance(s_ch, dict):
            return False
        for field in _CHAPTER_FIELDS:
            if s_ch.get(field) != f_ch.get(field):
                return False
        s_frames = s_ch.get("frames")
        f_frames = f_ch.get("frames")
        if (
            not isinstance(s_frames, list)
            or len(s_frames) != len(f_frames)
        ):
            return False
        for sf, ff in zip(s_frames, f_frames):
            if not isinstance(sf, dict):
                return False
            for field in _FRAME_FIELDS:
                if sf.get(field) != ff.get(field):
                    return False
    return True


# ---- entry point ---------------------------------------------------------

def run(paths: JobPaths, force: bool = False) -> dict:
    scenes_raw, scenes, scene_indices = _load_scenes(paths)
    chap_raw = _load_json(
        paths.chapter_candidates_json, "chapter_candidates.json"
    )
    chapters = _load_chapters(chap_raw)

    # Validate scene_index agreement across inputs (exact ordered lists).
    scores_raw, scores, score_indices = _load_scores(paths)
    if score_indices != scene_indices:
        raise RuntimeError(
            "scene_index mismatch between scenes.json and frame_scores.json"
        )

    sims_raw, sims, sim_indices = _load_similarities(paths)
    if sim_indices != scene_indices:
        raise RuntimeError(
            "scene_index mismatch between scenes.json and "
            "frame_similarities.json"
        )

    # frame_windows.json: validate it exists and has matching indices.
    win_data = _load_json(paths.frame_windows_json, "frame_windows.json")
    win_frames = win_data.get("frames")
    if not isinstance(win_frames, list):
        raise RuntimeError("frame_windows.json is missing a 'frames' list")
    win_indices = _extract_ordered_scene_indices(
        win_frames, "frame_windows.json",
    )
    if win_indices != scene_indices:
        raise RuntimeError(
            "scene_index mismatch between scenes.json and "
            "frame_windows.json"
        )

    # Compute deterministic fingerprints over all input artifacts.
    fingerprints = {
        "chapter_candidates.json": _fingerprint(chap_raw),
        "frame_scores.json": _fingerprint(scores_raw),
        "frame_similarities.json": _fingerprint(sims_raw),
        "frame_windows.json": _fingerprint(win_data),
        "scenes.json": _fingerprint(scenes_raw),
    }

    fresh = _compute(paths, scenes, chapters, scores, sims, fingerprints)

    if not force and _outputs_match(paths, fresh):
        with open(paths.frame_ranks_json) as f:
            data = json.load(f)
        update_stage(
            paths,
            "rank",
            COMPLETED,
            extra={
                "chapter_count": data.get("chapter_count"),
                "frame_count": data.get("frame_count"),
                "weights": data.get("weights"),
                "source_signals": SOURCE_SIGNALS,
                "skipped": True,
            },
        )
        return data

    update_stage(paths, "rank", RUNNING)
    try:
        if force and paths.frame_ranks_json.exists():
            paths.frame_ranks_json.unlink()

        tmp = paths.frame_ranks_json.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(fresh, f, indent=2, sort_keys=True)
        tmp.replace(paths.frame_ranks_json)

        update_stage(
            paths,
            "rank",
            COMPLETED,
            extra={
                "chapter_count": fresh["chapter_count"],
                "frame_count": fresh["frame_count"],
                "weights": fresh["weights"],
                "source_signals": SOURCE_SIGNALS,
            },
        )
        return fresh
    except Exception as e:
        tmp = paths.frame_ranks_json.with_suffix(".json.tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        update_stage(paths, "rank", FAILED, error=f"{type(e).__name__}: {e}")
        raise
