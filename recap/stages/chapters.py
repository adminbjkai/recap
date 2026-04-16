"""Phase 3 slice: first chaptering pass — transcript pause-only proposal.

Reads `transcript.json` and writes `chapter_candidates.json`. A chapter
boundary is placed between two adjacent transcript segments when the gap
between them is at least `PAUSE_SECONDS`. Chapters shorter than
`MIN_CHAPTER_SECONDS` are iteratively merged to avoid over-fragmentation.

This is the first Phase 3 chaptering slice only. It does NOT consult
scene boundaries, OpenCLIP similarity, speaker diarization, topic
shifts, or any LLM for titling. It does not perform per-chapter
ranking, keep/reject, or report embedding. It is opt-in via
`recap chapters` and is not invoked by `recap run`. Later chaptering
slices may fuse additional signals, at which point `SOURCE_SIGNAL`
changes and the skip contract recomputes any older artifact.

`PAUSE_SECONDS` (`2.0`), `MIN_CHAPTER_SECONDS` (`30.0`), and
`SOURCE_SIGNAL` (`"pauses"`) are fixed code-level constants. They are
not exposed as CLI flags, env vars, or config.

Skipped if `chapter_candidates.json` already matches a fresh
recomputation from the current `transcript.json` (unless `force=True`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, update_stage


PAUSE_SECONDS = 2.0
MIN_CHAPTER_SECONDS = 30.0
SOURCE_SIGNAL = "pauses"


_WS_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


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


def _load_transcript(paths: JobPaths) -> tuple[list[dict], float]:
    data = _load_json(paths.transcript_json, "transcript.json")
    segments = data.get("segments")
    if not isinstance(segments, list):
        raise RuntimeError("transcript.json is missing a 'segments' list")
    if not segments:
        raise RuntimeError("transcript.json has an empty 'segments' list")

    normalized: list[dict] = []
    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            raise RuntimeError(
                f"transcript.json segment at index {i} is not an object"
            )
        if "start" not in seg:
            raise RuntimeError(
                f"transcript.json segment at index {i} is missing 'start'"
            )
        if "end" not in seg:
            raise RuntimeError(
                f"transcript.json segment at index {i} is missing 'end'"
            )
        if "text" not in seg:
            raise RuntimeError(
                f"transcript.json segment at index {i} is missing 'text'"
            )
        start = seg["start"]
        end = seg["end"]
        text = seg["text"]
        if not _is_number(start):
            raise RuntimeError(
                f"transcript.json segment at index {i} has non-numeric 'start'"
            )
        if not _is_number(end):
            raise RuntimeError(
                f"transcript.json segment at index {i} has non-numeric 'end'"
            )
        if not isinstance(text, str):
            raise RuntimeError(
                f"transcript.json segment at index {i} has non-string 'text'"
            )
        start_f = float(start)
        end_f = float(end)
        if end_f < start_f:
            raise RuntimeError(
                f"transcript.json segment at index {i} has end "
                f"({end_f}) < start ({start_f})"
            )
        seg_id = seg.get("id", i)
        normalized.append(
            {"id": seg_id, "start": start_f, "end": end_f, "text": text}
        )

    declared_duration = data.get("duration")
    if declared_duration is not None and not _is_number(declared_duration):
        raise RuntimeError("transcript.json has non-numeric 'duration'")
    max_end = max(seg["end"] for seg in normalized)
    if declared_duration is None:
        duration = max_end
    else:
        duration = float(declared_duration)
        if duration < max_end:
            duration = max_end
    return normalized, duration


def _build_chapters(segments: list[dict], duration: float) -> list[dict]:
    # Pass 1: greedy split at every pause >= PAUSE_SECONDS. Each group
    # carries its own trigger; final trigger for the head chapter is
    # overridden to "start" at emit time regardless of merges.
    groups: list[list[dict]] = [[segments[0]]]
    triggers: list[str] = ["start"]
    for i in range(1, len(segments)):
        gap = segments[i]["start"] - segments[i - 1]["end"]
        if gap >= PAUSE_SECONDS:
            groups.append([segments[i]])
            triggers.append("pause")
        else:
            groups[-1].append(segments[i])

    # Pass 2: iteratively merge any chapter shorter than
    # MIN_CHAPTER_SECONDS. Chapter 0 is merged into its successor; all
    # others are merged into their predecessor. Continue until every
    # chapter meets the minimum or only one chapter remains. Span is
    # evaluated using the same contiguous timeline that is emitted
    # below: a chapter's start is 0.0 for chapter 0 (else its first
    # segment's start), and its end is the next chapter's first
    # segment's start (else `duration` for the last chapter). This is
    # the "emitted boundary" convention — the gap between a chapter
    # and its successor is counted as part of the earlier chapter.
    def _span(i: int) -> float:
        start = 0.0 if i == 0 else groups[i][0]["start"]
        end = duration if i == len(groups) - 1 else groups[i + 1][0]["start"]
        return end - start

    changed = True
    while changed and len(groups) > 1:
        changed = False
        for i in range(len(groups)):
            if _span(i) < MIN_CHAPTER_SECONDS:
                if i == 0:
                    groups[1] = groups[0] + groups[1]
                    groups.pop(0)
                    triggers.pop(0)
                else:
                    groups[i - 1] = groups[i - 1] + groups[i]
                    groups.pop(i)
                    triggers.pop(i)
                changed = True
                break

    chapters: list[dict] = []
    for idx, (segs, trigger) in enumerate(zip(groups, triggers)):
        is_first = idx == 0
        is_last = idx == len(groups) - 1
        start_seconds = 0.0 if is_first else segs[0]["start"]
        end_seconds = duration if is_last else groups[idx + 1][0]["start"]
        final_trigger = "start" if is_first else trigger
        chapters.append(
            {
                "index": idx + 1,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "first_segment_id": segs[0]["id"],
                "last_segment_id": segs[-1]["id"],
                "segment_ids": [s["id"] for s in segs],
                "text": _normalize_text(" ".join(s["text"] for s in segs)),
                "trigger": final_trigger,
            }
        )
    return chapters


def _compute(paths: JobPaths, segments: list[dict], duration: float) -> dict:
    video = paths.analysis_mp4.name if paths.analysis_mp4.exists() else None
    chapters = _build_chapters(segments, duration)
    return {
        "video": video,
        "transcript_source": paths.transcript_json.name,
        "source_signal": SOURCE_SIGNAL,
        "pause_seconds": PAUSE_SECONDS,
        "min_chapter_seconds": MIN_CHAPTER_SECONDS,
        "chapter_count": len(chapters),
        "chapters": chapters,
    }


_CHAPTER_FIELDS = (
    "index",
    "start_seconds",
    "end_seconds",
    "first_segment_id",
    "last_segment_id",
    "segment_ids",
    "text",
    "trigger",
)


def _outputs_match(paths: JobPaths, fresh: dict) -> bool:
    if not paths.chapter_candidates_json.exists():
        return False
    try:
        with open(paths.chapter_candidates_json) as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if data.get("transcript_source") != fresh["transcript_source"]:
        return False
    if data.get("source_signal") != fresh["source_signal"]:
        return False
    if data.get("pause_seconds") != fresh["pause_seconds"]:
        return False
    if data.get("min_chapter_seconds") != fresh["min_chapter_seconds"]:
        return False
    if data.get("chapter_count") != fresh["chapter_count"]:
        return False
    stored = data.get("chapters")
    if not isinstance(stored, list) or len(stored) != len(fresh["chapters"]):
        return False
    for stored_ch, fresh_ch in zip(stored, fresh["chapters"]):
        if not isinstance(stored_ch, dict):
            return False
        for field in _CHAPTER_FIELDS:
            if stored_ch.get(field) != fresh_ch.get(field):
                return False
    return True


def run(paths: JobPaths, force: bool = False) -> dict:
    segments, duration = _load_transcript(paths)
    fresh = _compute(paths, segments, duration)

    if not force and _outputs_match(paths, fresh):
        with open(paths.chapter_candidates_json) as f:
            data = json.load(f)
        update_stage(
            paths,
            "chapters",
            COMPLETED,
            extra={
                "chapter_count": data.get(
                    "chapter_count", len(data.get("chapters", []))
                ),
                "pause_seconds": PAUSE_SECONDS,
                "min_chapter_seconds": MIN_CHAPTER_SECONDS,
                "source_signal": SOURCE_SIGNAL,
                "skipped": True,
            },
        )
        return data

    update_stage(paths, "chapters", RUNNING)
    try:
        if force and paths.chapter_candidates_json.exists():
            paths.chapter_candidates_json.unlink()

        tmp = paths.chapter_candidates_json.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(fresh, f, indent=2, sort_keys=True)
        tmp.replace(paths.chapter_candidates_json)

        update_stage(
            paths,
            "chapters",
            COMPLETED,
            extra={
                "chapter_count": fresh["chapter_count"],
                "pause_seconds": PAUSE_SECONDS,
                "min_chapter_seconds": MIN_CHAPTER_SECONDS,
                "source_signal": SOURCE_SIGNAL,
            },
        )
        return fresh
    except Exception as e:
        tmp = paths.chapter_candidates_json.with_suffix(".json.tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        update_stage(paths, "chapters", FAILED, error=f"{type(e).__name__}: {e}")
        raise
