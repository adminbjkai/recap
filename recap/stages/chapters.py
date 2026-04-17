"""Phase 3 slice: chapter proposal from transcript pauses, plus
speaker-change fusion when the transcript carries Deepgram utterances.

Reads `transcript.json` and writes `chapter_candidates.json`.

A chapter boundary is placed between two adjacent transcript segments
whenever the gap between them is at least `PAUSE_SECONDS`. When the
transcript additionally contains a non-empty `utterances` list with at
least one non-null `speaker` id (Deepgram output), a boundary is also
placed on every adjacent segment pair whose speaker ids differ
(segments are 1:1 with utterances on the Deepgram path, sharing the
same `id` values). Either signal alone is enough to fire a boundary;
when both fire on the same pair the trigger is recorded as
`"pause+speaker"`. Chapters shorter than `MIN_CHAPTER_SECONDS` are
iteratively merged to avoid over-fragmentation; the merge rule is
unchanged and speaker-triggered groups are legitimate merge candidates.

Fallback behaviour — faster-whisper or any transcript without
`utterances` — is pause-only and byte-identical to the previous
version of this stage: `source_signal = "pauses"`, trigger vocabulary
`{"start","pause"}`, no `speaker_change_count` key.

Speaker-aware mode — triggered by a non-empty `utterances` list with
at least one non-null `speaker` id — extends the artifact shape:
`source_signal = "pauses+speakers"`, trigger vocabulary adds
`"speaker"` and `"pause+speaker"`, and a top-level
`speaker_change_count` records the number of pre-merge boundaries
whose source included a speaker change. The count is deliberately
pre-merge — it records the raw signal, not the count of emitted
chapters that retain a speaker trigger.

This slice does NOT consult scene boundaries, OpenCLIP similarity,
topic shifts, or any LLM for titling. It does not perform per-chapter
ranking, keep/reject, or report embedding. Speaker recognition /
manual labels, chapter titling, Groq, WhisperX, pyannote, VLM, UI,
captions, report screenshot embedding, `selected_frames.json`, and
exports remain deferred. It is opt-in via `recap chapters` and is not
invoked by `recap run`.

`PAUSE_SECONDS` (`2.0`) and `MIN_CHAPTER_SECONDS` (`30.0`) are fixed
code-level constants. Source-signal tokens (`"pauses"`,
`"pauses+speakers"`) are also fixed at the code level — a later
change that tunes the speaker rule must rename the token so the skip
contract invalidates any older artifact.

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
SOURCE_SIGNAL_PAUSES = "pauses"
SOURCE_SIGNAL_PAUSES_SPEAKERS = "pauses+speakers"


_WS_RE = re.compile(r"\s+")


def _normalize_text(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _is_number(x: object) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _is_int(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


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


def _load_utterances_map(data: dict) -> dict | None:
    """Validate `utterances` and return a dict[id -> speaker].

    Returns ``None`` when utterances are absent/empty, or when every
    present utterance has a null speaker. That return value disables
    speaker-aware mode and preserves byte-identical pause-only output.
    """
    if "utterances" not in data:
        return None
    raw = data["utterances"]
    if not isinstance(raw, list):
        raise RuntimeError("transcript.json 'utterances' must be a list")
    if not raw:
        return None

    by_id: dict = {}
    has_non_null_speaker = False
    for i, u in enumerate(raw):
        if not isinstance(u, dict):
            raise RuntimeError(
                f"transcript.json utterance at index {i} is not an object"
            )
        if "id" not in u:
            raise RuntimeError(
                f"transcript.json utterance at index {i} is missing 'id'"
            )
        if "speaker" not in u:
            raise RuntimeError(
                f"transcript.json utterance at index {i} is missing 'speaker'"
            )
        uid = u["id"]
        if not _is_int(uid):
            raise RuntimeError(
                f"transcript.json utterance at index {i} has non-integer 'id'"
            )
        sp = u["speaker"]
        if sp is not None and not _is_int(sp):
            raise RuntimeError(
                f"transcript.json utterance at index {i} has non-integer "
                "'speaker' (int or null required)"
            )
        if uid in by_id:
            raise RuntimeError(
                f"transcript.json utterances has duplicate 'id' {uid}"
            )
        by_id[uid] = sp
        if sp is not None:
            has_non_null_speaker = True

    if not has_non_null_speaker:
        return None
    return by_id


def _load_transcript(paths: JobPaths) -> tuple[list[dict], float, dict | None]:
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

    segment_to_speaker = _load_utterances_map(data)
    return normalized, duration, segment_to_speaker


def _build_chapters(
    segments: list[dict],
    duration: float,
    segment_to_speaker: dict | None,
) -> tuple[list[dict], int]:
    """Build chapters and return (chapters, speaker_change_count).

    When `segment_to_speaker` is None, pause-only behaviour is used
    and the speaker change count is zero.
    """
    utterances_available = segment_to_speaker is not None

    # Pass 1: greedy split at every pause >= PAUSE_SECONDS and/or every
    # speaker change. Each group carries its own trigger; the head
    # chapter's trigger is overridden to "start" at emit time regardless
    # of merges.
    groups: list[list[dict]] = [[segments[0]]]
    triggers: list[str] = ["start"]
    speaker_change_count = 0

    for i in range(1, len(segments)):
        prev = segments[i - 1]
        nxt = segments[i]
        gap = nxt["start"] - prev["end"]
        pause_fires = gap >= PAUSE_SECONDS

        if utterances_available:
            prev_speaker = segment_to_speaker.get(prev["id"])
            next_speaker = segment_to_speaker.get(nxt["id"])
            speaker_fires = (
                prev_speaker is not None
                and next_speaker is not None
                and prev_speaker != next_speaker
            )
        else:
            speaker_fires = False

        if speaker_fires:
            speaker_change_count += 1

        if pause_fires or speaker_fires:
            if pause_fires and speaker_fires:
                trigger = "pause+speaker"
            elif speaker_fires:
                trigger = "speaker"
            else:
                trigger = "pause"
            groups.append([nxt])
            triggers.append(trigger)
        else:
            groups[-1].append(nxt)

    # Pass 2: iteratively merge any chapter shorter than
    # MIN_CHAPTER_SECONDS. Chapter 0 merges into its successor; all
    # others merge into their predecessor. Continue until every chapter
    # meets the minimum or only one chapter remains. Span is evaluated
    # against the same contiguous timeline that is emitted below.
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
    return chapters, speaker_change_count


def _compute(
    paths: JobPaths,
    segments: list[dict],
    duration: float,
    segment_to_speaker: dict | None,
) -> dict:
    video = paths.analysis_mp4.name if paths.analysis_mp4.exists() else None
    chapters, speaker_change_count = _build_chapters(
        segments, duration, segment_to_speaker
    )
    utterances_available = segment_to_speaker is not None
    source_signal = (
        SOURCE_SIGNAL_PAUSES_SPEAKERS
        if utterances_available
        else SOURCE_SIGNAL_PAUSES
    )
    out: dict = {
        "video": video,
        "transcript_source": paths.transcript_json.name,
        "source_signal": source_signal,
        "pause_seconds": PAUSE_SECONDS,
        "min_chapter_seconds": MIN_CHAPTER_SECONDS,
        "chapter_count": len(chapters),
        "chapters": chapters,
    }
    # Emit speaker_change_count ONLY in speaker-aware mode so the
    # faster-whisper / pause-only output stays byte-identical.
    if utterances_available:
        out["speaker_change_count"] = speaker_change_count
    return out


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

    # speaker_change_count: present only in speaker-aware mode. Absence
    # and zero are NOT the same: a stored pause-only artifact lacks the
    # key, a freshly-computed speaker-aware artifact carries it.
    stored_has = "speaker_change_count" in data
    fresh_has = "speaker_change_count" in fresh
    if stored_has != fresh_has:
        return False
    if fresh_has and data["speaker_change_count"] != fresh["speaker_change_count"]:
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
    segments, duration, segment_to_speaker = _load_transcript(paths)
    fresh = _compute(paths, segments, duration, segment_to_speaker)

    if not force and _outputs_match(paths, fresh):
        with open(paths.chapter_candidates_json) as f:
            data = json.load(f)
        extra = {
            "chapter_count": data.get(
                "chapter_count", len(data.get("chapters", []))
            ),
            "pause_seconds": PAUSE_SECONDS,
            "min_chapter_seconds": MIN_CHAPTER_SECONDS,
            "source_signal": data.get("source_signal"),
            "skipped": True,
        }
        if "speaker_change_count" in data:
            extra["speaker_change_count"] = data["speaker_change_count"]
        update_stage(paths, "chapters", COMPLETED, extra=extra)
        return data

    update_stage(paths, "chapters", RUNNING)
    try:
        if force and paths.chapter_candidates_json.exists():
            paths.chapter_candidates_json.unlink()

        tmp = paths.chapter_candidates_json.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(fresh, f, indent=2, sort_keys=True)
        tmp.replace(paths.chapter_candidates_json)

        extra = {
            "chapter_count": fresh["chapter_count"],
            "pause_seconds": PAUSE_SECONDS,
            "min_chapter_seconds": MIN_CHAPTER_SECONDS,
            "source_signal": fresh["source_signal"],
        }
        if "speaker_change_count" in fresh:
            extra["speaker_change_count"] = fresh["speaker_change_count"]
        update_stage(paths, "chapters", COMPLETED, extra=extra)
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
