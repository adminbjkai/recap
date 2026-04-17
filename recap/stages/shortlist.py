"""Phase 3 slice: deterministic pre-VLM keep/reject shortlist.

Reads `frame_ranks.json` and writes `frame_shortlist.json`.  For every
candidate frame in every chapter, a closed-vocabulary `decision` and
ordered `reasons` list are recorded.  Within each chapter the top
ranked non-rejected frames become a hero (1) plus up to
`SUPPORTING_PER_CHAPTER` supporting (2) frames; any remaining
non-rejected frames are marked `dropped_over_budget`.  This artifact
is the pre-VLM shortlist — it is the intended input to a later
Stage 7 VLM verification pass over the top 1 to 3 candidate frames
per chapter.  It is NOT the final report screenshot budget and does
not implement final screenshot embedding.

This is a marking-only stage.  It does NOT write
`selected_frames.json` (that filename is reserved for Phase 4
post-VLM finalists), invoke any VLM, generate captions, modify
`report.md`, export documents, add UI, or do any speaker work.  It
is opt-in via `recap shortlist` and is not invoked by `recap run`.

Blur / low-information detection and VLM-dependent
"shows code / diagrams / settings / dashboards" judgments are
deferred.

`CLIP_KEEP_THRESHOLD` (`0.30`), `OCR_NOVELTY_THRESHOLD` (`0.25`),
`HERO_PER_CHAPTER` (`1`), `SUPPORTING_PER_CHAPTER` (`2`),
`TOTAL_PER_CHAPTER` (`3`), and `POLICY_VERSION` (`"keep_reject_v1"`)
are fixed code-level constants.  They are NOT exposed as CLI flags,
env vars, or config.  A retune must bump `POLICY_VERSION` so the
skip contract invalidates any stored shortlist.

Skipped if `frame_shortlist.json` already matches a fresh
recomputation from the current `frame_ranks.json` (unless
`force=True`).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


# ---- fixed code-level constants (not CLI flags / env / config) ----------

CLIP_KEEP_THRESHOLD = 0.30
OCR_NOVELTY_THRESHOLD = 0.25
HERO_PER_CHAPTER = 1
SUPPORTING_PER_CHAPTER = 2
TOTAL_PER_CHAPTER = HERO_PER_CHAPTER + SUPPORTING_PER_CHAPTER
POLICY_VERSION = "keep_reject_v1"


# ---- helpers ------------------------------------------------------------

def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _load_json_raw(path: Path, label: str) -> dict:
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


def _fingerprint(data: object) -> str:
    """SHA-256 hex digest of canonical JSON."""
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


# ---- input validation ---------------------------------------------------

_REQUIRED_FRAME_FIELDS = (
    "rank",
    "scene_index",
    "frame_file",
    "midpoint_seconds",
    "composite_score",
    "clip_similarity",
    "text_novelty",
    "duplicate_of",
)
_REQUIRED_CHAPTER_FIELDS = (
    "chapter_index",
    "start_seconds",
    "end_seconds",
    "frames",
)


def _validate_ranks(raw: dict) -> list[dict]:
    chapters = raw.get("chapters")
    if not isinstance(chapters, list):
        raise RuntimeError(
            "frame_ranks.json is missing a 'chapters' list"
        )
    if not chapters:
        raise RuntimeError(
            "frame_ranks.json has an empty 'chapters' list"
        )

    seen_scene_indices: set[int] = set()
    for ci, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            raise RuntimeError(
                f"frame_ranks.json chapter at index {ci} is not an object"
            )
        for field in _REQUIRED_CHAPTER_FIELDS:
            if field not in ch:
                raise RuntimeError(
                    f"frame_ranks.json chapter at index {ci} "
                    f"is missing '{field}'"
                )
        if not _is_int(ch["chapter_index"]):
            raise RuntimeError(
                f"frame_ranks.json chapter at index {ci} "
                "has non-integer 'chapter_index'"
            )
        if not _is_number(ch["start_seconds"]):
            raise RuntimeError(
                f"frame_ranks.json chapter at index {ci} "
                "has non-numeric 'start_seconds'"
            )
        if not _is_number(ch["end_seconds"]):
            raise RuntimeError(
                f"frame_ranks.json chapter at index {ci} "
                "has non-numeric 'end_seconds'"
            )
        frames = ch["frames"]
        if not isinstance(frames, list):
            raise RuntimeError(
                f"frame_ranks.json chapter at index {ci} "
                "has non-list 'frames'"
            )

        for fi, fr in enumerate(frames):
            if not isinstance(fr, dict):
                raise RuntimeError(
                    f"frame_ranks.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} is not an object"
                )
            for field in _REQUIRED_FRAME_FIELDS:
                if field not in fr:
                    raise RuntimeError(
                        f"frame_ranks.json chapter {ch['chapter_index']} "
                        f"frame at index {fi} is missing '{field}'"
                    )
            if not _is_int(fr["rank"]):
                raise RuntimeError(
                    f"frame_ranks.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-integer 'rank'"
                )
            if not _is_int(fr["scene_index"]):
                raise RuntimeError(
                    f"frame_ranks.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-integer 'scene_index'"
                )
            if not isinstance(fr["frame_file"], str) or not fr["frame_file"]:
                raise RuntimeError(
                    f"frame_ranks.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has empty or non-string "
                    "'frame_file'"
                )
            if not _is_number(fr["midpoint_seconds"]):
                raise RuntimeError(
                    f"frame_ranks.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-numeric "
                    "'midpoint_seconds'"
                )
            if not _is_number(fr["composite_score"]):
                raise RuntimeError(
                    f"frame_ranks.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-numeric "
                    "'composite_score'"
                )
            if fr["clip_similarity"] is not None and not _is_number(
                fr["clip_similarity"]
            ):
                raise RuntimeError(
                    f"frame_ranks.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-numeric "
                    "'clip_similarity'"
                )
            if fr["text_novelty"] is not None and not _is_number(
                fr["text_novelty"]
            ):
                raise RuntimeError(
                    f"frame_ranks.json chapter {ch['chapter_index']} "
                    f"frame at index {fi} has non-numeric 'text_novelty'"
                )

            si = fr["scene_index"]
            if si in seen_scene_indices:
                raise RuntimeError(
                    f"frame_ranks.json has duplicate scene_index {si}"
                )
            seen_scene_indices.add(si)

        # Rank sequence must be exactly 1..N in ascending order.
        actual_ranks = [fr["rank"] for fr in frames]
        expected_ranks = list(range(1, len(frames) + 1))
        if actual_ranks != expected_ranks:
            raise RuntimeError(
                f"frame_ranks.json chapter {ch['chapter_index']} has "
                f"invalid rank sequence {actual_ranks}; expected "
                f"{expected_ranks}"
            )

    return chapters


# ---- core logic ----------------------------------------------------------

def _decide_chapter(frames: list[dict]) -> list[dict]:
    """Return new frame dicts with decision and reasons attached.

    Frames are processed in the incoming order (rank ascending in
    `frame_ranks.json`); hero is the first non-rejected frame, then
    up to SUPPORTING_PER_CHAPTER supporting frames, then
    dropped_over_budget.
    """
    heroes = 0
    supporting = 0
    out: list[dict] = []
    for fr in frames:
        dup_of = fr["duplicate_of"]
        clip = fr["clip_similarity"]
        tn = fr["text_novelty"]

        if dup_of is not None:
            decision = "rejected_duplicate"
            reasons = ["duplicate_of_predecessor"]
        else:
            clip_or_0 = float(clip) if clip is not None else 0.0
            tn_or_0 = float(tn) if tn is not None else 0.0
            if clip_or_0 < CLIP_KEEP_THRESHOLD and tn_or_0 < OCR_NOVELTY_THRESHOLD:
                decision = "rejected_weak_signal"
                reasons = [
                    "clip_similarity_below_threshold",
                    "text_novelty_below_threshold",
                ]
            elif heroes < HERO_PER_CHAPTER:
                decision = "hero"
                reasons = ["kept_as_hero"]
                heroes += 1
            elif supporting < SUPPORTING_PER_CHAPTER:
                decision = "supporting"
                reasons = ["kept_as_supporting"]
                supporting += 1
            else:
                decision = "dropped_over_budget"
                reasons = ["exceeds_total_per_chapter"]

        out.append(
            {
                "clip_similarity": clip,
                "composite_score": fr["composite_score"],
                "decision": decision,
                "duplicate_of": dup_of,
                "frame_file": fr["frame_file"],
                "midpoint_seconds": fr["midpoint_seconds"],
                "rank": fr["rank"],
                "reasons": reasons,
                "scene_index": fr["scene_index"],
                "text_novelty": tn,
            }
        )
    return out


def _compute(
    paths: JobPaths, ranks_raw: dict, fingerprint: str
) -> dict:
    video = paths.analysis_mp4.name if paths.analysis_mp4.exists() else None

    chapters_in = ranks_raw["chapters"]
    out_chapters: list[dict] = []
    kept_count = 0
    rejected_count = 0
    dropped_over_budget_count = 0
    total_frames = 0

    for ch in chapters_in:
        decided = _decide_chapter(ch["frames"])
        total_frames += len(decided)
        hero_si: int | None = None
        supporting_sis: list[int] = []
        ch_kept = 0
        for fr in decided:
            d = fr["decision"]
            if d == "hero":
                hero_si = fr["scene_index"]
                ch_kept += 1
                kept_count += 1
            elif d == "supporting":
                supporting_sis.append(fr["scene_index"])
                ch_kept += 1
                kept_count += 1
            elif d == "dropped_over_budget":
                dropped_over_budget_count += 1
            else:
                # rejected_duplicate or rejected_weak_signal
                rejected_count += 1

        out_chapters.append(
            {
                "chapter_index": ch["chapter_index"],
                "end_seconds": ch["end_seconds"],
                "frame_count": len(decided),
                "frames": decided,
                "hero_scene_index": hero_si,
                "kept_count": ch_kept,
                "start_seconds": ch["start_seconds"],
                "supporting_scene_indices": supporting_sis,
            }
        )

    return {
        "budget": {
            "hero_per_chapter": HERO_PER_CHAPTER,
            "supporting_per_chapter": SUPPORTING_PER_CHAPTER,
            "total_per_chapter": TOTAL_PER_CHAPTER,
        },
        "chapter_count": len(out_chapters),
        "chapters": out_chapters,
        "dropped_over_budget_count": dropped_over_budget_count,
        "frame_count": total_frames,
        "input_fingerprints": {"frame_ranks.json": fingerprint},
        "kept_count": kept_count,
        "policy_version": POLICY_VERSION,
        "ranks_source": paths.frame_ranks_json.name,
        "rejected_count": rejected_count,
        "thresholds": {
            "clip_keep_threshold": CLIP_KEEP_THRESHOLD,
            "ocr_novelty_threshold": OCR_NOVELTY_THRESHOLD,
        },
        "video": video,
    }


# ---- skip contract -------------------------------------------------------

_CHAPTER_FIELDS = (
    "chapter_index",
    "start_seconds",
    "end_seconds",
    "frame_count",
    "kept_count",
    "hero_scene_index",
    "supporting_scene_indices",
)
_FRAME_FIELDS = (
    "rank",
    "scene_index",
    "frame_file",
    "midpoint_seconds",
    "composite_score",
    "clip_similarity",
    "text_novelty",
    "duplicate_of",
    "decision",
    "reasons",
)


def _outputs_match(paths: JobPaths, fresh: dict) -> bool:
    if not paths.frame_shortlist_json.exists():
        return False
    try:
        with open(paths.frame_shortlist_json) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    for key in (
        "ranks_source",
        "policy_version",
        "chapter_count",
        "frame_count",
        "kept_count",
        "rejected_count",
        "dropped_over_budget_count",
    ):
        if data.get(key) != fresh[key]:
            return False
    for key in ("thresholds", "budget", "input_fingerprints"):
        if data.get(key) != fresh[key]:
            return False
    stored_chs = data.get("chapters")
    if not isinstance(stored_chs, list) or len(stored_chs) != len(
        fresh["chapters"]
    ):
        return False
    for s_ch, f_ch in zip(stored_chs, fresh["chapters"]):
        if not isinstance(s_ch, dict):
            return False
        for field in _CHAPTER_FIELDS:
            if s_ch.get(field) != f_ch.get(field):
                return False
        s_frames = s_ch.get("frames")
        f_frames = f_ch.get("frames")
        if not isinstance(s_frames, list) or len(s_frames) != len(f_frames):
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
    ranks_raw = _load_json_raw(paths.frame_ranks_json, "frame_ranks.json")
    _validate_ranks(ranks_raw)
    fingerprint = _fingerprint(ranks_raw)
    fresh = _compute(paths, ranks_raw, fingerprint)

    if not force and _outputs_match(paths, fresh):
        with open(paths.frame_shortlist_json) as f:
            data = json.load(f)
        update_stage(
            paths,
            "shortlist",
            COMPLETED,
            extra={
                "chapter_count": data.get("chapter_count"),
                "frame_count": data.get("frame_count"),
                "kept_count": data.get("kept_count"),
                "rejected_count": data.get("rejected_count"),
                "dropped_over_budget_count": data.get(
                    "dropped_over_budget_count"
                ),
                "thresholds": data.get("thresholds"),
                "budget": data.get("budget"),
                "policy_version": POLICY_VERSION,
                "skipped": True,
            },
        )
        return data

    update_stage(paths, "shortlist", RUNNING)
    try:
        if force and paths.frame_shortlist_json.exists():
            paths.frame_shortlist_json.unlink()

        tmp = paths.frame_shortlist_json.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(fresh, f, indent=2, sort_keys=True)
        tmp.replace(paths.frame_shortlist_json)

        update_stage(
            paths,
            "shortlist",
            COMPLETED,
            extra={
                "chapter_count": fresh["chapter_count"],
                "frame_count": fresh["frame_count"],
                "kept_count": fresh["kept_count"],
                "rejected_count": fresh["rejected_count"],
                "dropped_over_budget_count": fresh[
                    "dropped_over_budget_count"
                ],
                "thresholds": fresh["thresholds"],
                "budget": fresh["budget"],
                "policy_version": POLICY_VERSION,
            },
        )
        return fresh
    except Exception as e:
        tmp = paths.frame_shortlist_json.with_suffix(".json.tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        update_stage(
            paths, "shortlist", FAILED, error=f"{type(e).__name__}: {e}"
        )
        raise
