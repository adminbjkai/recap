"""Shared validation and formatting helpers for the report stages.

`recap/stages/assemble.py`, `recap/stages/export_html.py`, and
`recap/stages/export_docx.py` all read the same selected-path artifacts
(`selected_frames.json` + `chapter_candidates.json`) and all enforce the
same structural and coherence contract. The helpers below are the
canonical implementation; each renderer imports from here so a future
fix lives in exactly one place.

This module is intentionally a flat collection of small functions and
constants. It is not an export framework, not a pipeline abstraction,
and not a plugin registry. Error-message prefixes and wording are load
bearing — `scripts/verify_reports.py` matches on them — and must not
change without updating the scripts in lockstep.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .insights import validate_insights as _validate_insights


WHITESPACE_RE = re.compile(r"\s+")

SELECTED_FRAME_DECISIONS: tuple[str, ...] = (
    "selected_hero",
    "selected_supporting",
    "vlm_rejected",
)


def format_ts(seconds: float | None) -> str:
    if seconds is None:
        return "--:--:--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def summarize_metadata(meta: dict) -> dict:
    fmt = meta.get("format", {}) or {}
    streams = meta.get("streams", []) or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    def _maybe_float(x):
        try:
            return float(x)
        except (TypeError, ValueError):
            return None

    out = {
        "duration_seconds": _maybe_float(fmt.get("duration")),
        "size_bytes": int(fmt.get("size")) if fmt.get("size") else None,
        "format_name": fmt.get("format_name"),
    }
    if video:
        out["video"] = {
            "codec": video.get("codec_name"),
            "width": video.get("width"),
            "height": video.get("height"),
            "frame_rate": video.get("avg_frame_rate"),
        }
    if audio:
        out["audio"] = {
            "codec": audio.get("codec_name"),
            "sample_rate": audio.get("sample_rate"),
            "channels": audio.get("channels"),
        }
    return out


def collapse_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_safe_frame_file(name: object) -> bool:
    """A frame_file must be a plain filename inside candidate_frames/."""
    if not isinstance(name, str) or not name:
        return False
    if name in (".", ".."):
        return False
    if "/" in name or "\\" in name:
        return False
    p = Path(name)
    if p.is_absolute():
        return False
    if p.name != name:
        return False
    return True


def validate_selected_frames(data: object) -> dict:
    if not isinstance(data, dict):
        raise RuntimeError(
            "selected_frames.json malformed: top-level is not a JSON object"
        )
    chapters = data.get("chapters")
    if not isinstance(chapters, list):
        raise RuntimeError(
            "selected_frames.json malformed: 'chapters' missing or not a list"
        )
    for ch in chapters:
        if not isinstance(ch, dict):
            raise RuntimeError(
                "selected_frames.json malformed: chapter entry is not an object"
            )
        for field in ("chapter_index", "start_seconds", "end_seconds",
                      "hero", "supporting_scene_indices", "frames"):
            if field not in ch:
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter missing '{field}'"
                )
        if not is_int(ch["chapter_index"]):
            raise RuntimeError(
                "selected_frames.json malformed: chapter 'chapter_index' "
                "must be an integer"
            )
        ch_idx = ch["chapter_index"]
        if not is_number(ch["start_seconds"]):
            raise RuntimeError(
                f"selected_frames.json malformed: chapter {ch_idx} "
                "'start_seconds' must be numeric"
            )
        if not is_number(ch["end_seconds"]):
            raise RuntimeError(
                f"selected_frames.json malformed: chapter {ch_idx} "
                "'end_seconds' must be numeric"
            )
        if not isinstance(ch["frames"], list):
            raise RuntimeError(
                f"selected_frames.json malformed: chapter {ch_idx} 'frames' "
                "is not a list"
            )
        if not isinstance(ch["supporting_scene_indices"], list):
            raise RuntimeError(
                f"selected_frames.json malformed: chapter {ch_idx} "
                "'supporting_scene_indices' is not a list"
            )
        for si in ch["supporting_scene_indices"]:
            if not is_int(si):
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} "
                    "'supporting_scene_indices' entries must be integers"
                )
        hero = ch["hero"]
        if hero is not None:
            if not isinstance(hero, dict):
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} "
                    "'hero' must be null or an object"
                )
            for field in ("scene_index", "frame_file", "midpoint_seconds"):
                if field not in hero:
                    raise RuntimeError(
                        f"selected_frames.json malformed: chapter {ch_idx} "
                        f"hero missing '{field}'"
                    )
            if not is_int(hero["scene_index"]):
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} "
                    "hero 'scene_index' must be an integer"
                )
            if not is_safe_frame_file(hero["frame_file"]):
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} "
                    "hero 'frame_file' must be a plain filename inside "
                    "candidate_frames/ (no path separators, no traversal)"
                )
            if not is_number(hero["midpoint_seconds"]):
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} "
                    "hero 'midpoint_seconds' must be numeric"
                )
        for fr in ch["frames"]:
            if not isinstance(fr, dict):
                raise RuntimeError(
                    "selected_frames.json malformed: frame entry is not "
                    "an object"
                )
            for field in ("frame_file", "scene_index",
                          "midpoint_seconds", "decision"):
                if field not in fr:
                    raise RuntimeError(
                        "selected_frames.json malformed: frame missing "
                        f"'{field}'"
                    )
            if not is_safe_frame_file(fr["frame_file"]):
                raise RuntimeError(
                    "selected_frames.json malformed: frame 'frame_file' "
                    "must be a plain filename inside candidate_frames/ "
                    "(no path separators, no traversal)"
                )
            if not is_int(fr["scene_index"]):
                raise RuntimeError(
                    "selected_frames.json malformed: frame 'scene_index' "
                    "must be an integer"
                )
            if not is_number(fr["midpoint_seconds"]):
                raise RuntimeError(
                    "selected_frames.json malformed: frame "
                    "'midpoint_seconds' must be numeric"
                )
            if not isinstance(fr["decision"], str):
                raise RuntimeError(
                    "selected_frames.json malformed: frame 'decision' "
                    "must be a string"
                )
            if fr["decision"] not in SELECTED_FRAME_DECISIONS:
                raise RuntimeError(
                    "selected_frames.json malformed: frame 'decision' "
                    f"must be one of {list(SELECTED_FRAME_DECISIONS)}"
                )
    return data


def validate_chapter_candidates(data: object) -> dict[int, str]:
    if not isinstance(data, dict):
        raise RuntimeError(
            "chapter_candidates.json malformed: top-level is not a JSON object"
        )
    chapters = data.get("chapters")
    if not isinstance(chapters, list):
        raise RuntimeError(
            "chapter_candidates.json malformed: 'chapters' missing or not a list"
        )
    text_by_index: dict[int, str] = {}
    for ch in chapters:
        if not isinstance(ch, dict):
            raise RuntimeError(
                "chapter_candidates.json malformed: chapter entry is not an "
                "object"
            )
        if "index" not in ch:
            raise RuntimeError(
                "chapter_candidates.json malformed: chapter missing 'index'"
            )
        if not isinstance(ch["index"], int) or isinstance(ch["index"], bool):
            raise RuntimeError(
                "chapter_candidates.json malformed: chapter 'index' must be "
                "an integer"
            )
        text = ch.get("text", "")
        if not isinstance(text, str):
            raise RuntimeError(
                "chapter_candidates.json malformed: chapter 'text' must be "
                "a string"
            )
        text_by_index[ch["index"]] = text
    return text_by_index


def caption_for(frame: dict) -> str | None:
    verification = frame.get("verification")
    if not isinstance(verification, dict):
        return None
    caption = verification.get("caption")
    if isinstance(caption, str):
        collapsed = collapse_whitespace(caption)
        if collapsed:
            return collapsed
    return None


def check_hero_coherence(ch: dict) -> dict | None:
    """Validate chapter.hero vs. frames[] and return the hero frame or None.

    Raises RuntimeError with a `selected_frames.json malformed: ...` prefix
    on any violation.
    """
    ch_idx = ch["chapter_index"]
    hero_frames = [
        fr for fr in ch["frames"]
        if fr.get("decision") == "selected_hero"
    ]
    if len(hero_frames) > 1:
        raise RuntimeError(
            f"selected_frames.json malformed: chapter {ch_idx} has "
            f"{len(hero_frames)} frames with decision='selected_hero' "
            "(expected at most 1)"
        )
    hero = ch.get("hero")
    if hero_frames:
        hero_frame_from_list = hero_frames[0]
        if not isinstance(hero, dict):
            raise RuntimeError(
                f"selected_frames.json malformed: chapter {ch_idx} has a "
                "'selected_hero' frame but chapter.hero is null"
            )
        for field in ("scene_index", "frame_file", "midpoint_seconds"):
            if hero.get(field) != hero_frame_from_list.get(field):
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} "
                    f"hero.{field} does not match the 'selected_hero' "
                    "frame in frames[]"
                )
        return hero_frame_from_list
    if hero is not None:
        raise RuntimeError(
            f"selected_frames.json malformed: chapter {ch_idx} has "
            "chapter.hero set but no frame with "
            "decision='selected_hero'"
        )
    return None


def load_insights(path: Path) -> dict | None:
    """Load and validate ``insights.json``; return ``None`` if absent.

    Raises ``RuntimeError`` with an ``insights.json malformed: ...``
    prefix if the file exists but does not match the schema. The
    exporters deliberately surface this loudly: a half-valid insights
    artifact must not produce a half-valid report.
    """
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"insights.json malformed: invalid JSON: {e.msg}"
        ) from e
    return _validate_insights(data)


def insights_chapters_by_index(insights: dict) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for ch in insights.get("chapters") or []:
        if isinstance(ch, dict) and isinstance(ch.get("index"), int):
            out[ch["index"]] = ch
    return out


def check_supporting_coherence(ch: dict) -> None:
    """Validate that supporting_scene_indices matches the ordered scene_index
    values of frames with decision='selected_supporting'."""
    ch_idx = ch["chapter_index"]
    supporting_frame_order = [
        fr["scene_index"] for fr in ch["frames"]
        if fr.get("decision") == "selected_supporting"
    ]
    ssi = list(ch["supporting_scene_indices"])
    if supporting_frame_order != ssi:
        raise RuntimeError(
            f"selected_frames.json malformed: chapter {ch_idx} "
            "'supporting_scene_indices' does not match the ordered "
            "scene_index values of its 'selected_supporting' frames"
        )


# ----------------------------------------------------------------------
# Read-time overlay helpers.
#
# Overlays (`speaker_names.json`, `chapter_titles.json`,
# `frame_review.json`) capture user intent from the React workspace.
# Exporters read them at render time only — they never mutate the
# upstream artifacts (`transcript.json`, `chapter_candidates.json`,
# `insights.json`, `selected_frames.json`).
#
# Read policy (mirrors `recap/ui.py`):
#   - missing file → empty overlay (no effect).
#   - malformed JSON / wrong-shape top-level / per-entry bad shape →
#     empty overlay (no effect). The React app and the exporters
#     apply the same "degrade silently on bad overlay" rule so the
#     workspace preview and the exported file stay in sync.
#
# This is deliberately a read-only convenience layer. Writers still
# live in `recap/ui.py` under atomic tmp + os.replace.
# ----------------------------------------------------------------------

_OVERLAY_SPEAKER_NAME_MAX_LEN = 80
_OVERLAY_CHAPTER_TITLE_MAX_LEN = 120
_OVERLAY_FRAME_NOTE_MAX_LEN = 300
_FRAME_REVIEW_DECISIONS: frozenset[str] = frozenset({"keep", "reject"})
# Transcript-notes overlay bounds and key shape. The React
# workspace emits `utt-<n>` for utterance-based rows (Deepgram) and
# `seg-<n>` for segment-based rows (faster-whisper); the exporters
# look up the same row ids. Corrections allow longer text than the
# other overlays because they replace a full transcript line; notes
# are reviewer prose.
_OVERLAY_TRANSCRIPT_CORRECTION_MAX_LEN = 2000
_OVERLAY_TRANSCRIPT_NOTE_MAX_LEN = 1000
_TRANSCRIPT_NOTE_KEY_RE = re.compile(r"^(utt|seg)-\d+$")


def _overlay_contains_control(value: str) -> bool:
    for ch in value:
        if ch == "\t":
            continue
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            return True
    return False


def _read_overlay_json(path: Path) -> dict | None:
    """Read a JSON overlay file. Returns None if absent / malformed."""
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def load_speaker_names_overlay(path: Path) -> dict[str, str]:
    """Return ``{speaker_id: custom_label}`` from the overlay.

    Graceful read policy: every bad-entry case returns no mapping
    for that key rather than raising.
    """
    data = _read_overlay_json(path)
    if data is None:
        return {}
    speakers = data.get("speakers")
    if not isinstance(speakers, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in speakers.items():
        if not isinstance(k, str):
            continue
        if not isinstance(v, str):
            continue
        label = v.strip()
        if not label:
            continue
        if len(label) > _OVERLAY_SPEAKER_NAME_MAX_LEN:
            continue
        if _overlay_contains_control(label):
            continue
        out[k] = label
    return out


def load_chapter_titles_overlay(path: Path) -> dict[int, str]:
    """Return ``{chapter_index: custom_title}`` from the overlay.

    Keys are integer-string in the JSON file; this helper normalizes
    them to integers so callers can match against
    ``selected_frames.json#chapter_index``.
    """
    data = _read_overlay_json(path)
    if data is None:
        return {}
    titles = data.get("titles")
    if not isinstance(titles, dict):
        return {}
    out: dict[int, str] = {}
    for k, v in titles.items():
        if not isinstance(k, str):
            continue
        try:
            idx = int(k)
        except ValueError:
            continue
        if not isinstance(v, str):
            continue
        title = v.strip()
        if not title:
            continue
        if len(title) > _OVERLAY_CHAPTER_TITLE_MAX_LEN:
            continue
        if _overlay_contains_control(title):
            continue
        out[idx] = title
    return out


def load_frame_review_overlay(path: Path) -> dict[str, dict]:
    """Return ``{frame_file: {"decision": "keep"|"reject", "note": str}}``.

    Only ``keep`` and ``reject`` are persisted; the UI's ``unset``
    pseudo-decision removes the mapping upstream.
    """
    data = _read_overlay_json(path)
    if data is None:
        return {}
    frames = data.get("frames")
    if not isinstance(frames, dict):
        return {}
    out: dict[str, dict] = {}
    for fname, entry in frames.items():
        if not isinstance(fname, str) or not is_safe_frame_file(fname):
            continue
        if not isinstance(entry, dict):
            continue
        decision = entry.get("decision")
        if decision not in _FRAME_REVIEW_DECISIONS:
            continue
        note_raw = entry.get("note", "")
        if not isinstance(note_raw, str):
            note_raw = ""
        note = note_raw.strip()
        if len(note) > _OVERLAY_FRAME_NOTE_MAX_LEN:
            note = note[:_OVERLAY_FRAME_NOTE_MAX_LEN]
        if _overlay_contains_control(note):
            note = ""
        out[fname] = {"decision": decision, "note": note}
    return out


def _overlay_contains_line_control(value: str) -> bool:
    """Reject ASCII/Unicode control chars except tab, newline, CR.

    Matches the server-side transcript-notes read policy: freeform
    reviewer text is allowed to carry line breaks, so only the
    non-printable control chars outside `\\t`, `\\n`, `\\r` are
    rejected.
    """
    for ch in value:
        if ch in ("\t", "\n", "\r"):
            continue
        if ord(ch) < 0x20 or ord(ch) == 0x7F:
            return True
    return False


def load_transcript_notes_overlay(path: Path) -> dict[str, dict]:
    """Return ``{row_id: {"correction"?: str, "note"?: str}}``.

    Mirrors the server-side ``recap/ui.py::_load_transcript_notes``
    read policy: keys must match ``^(utt|seg)-\\d+$``; corrections
    are bounded at 2000 chars, notes at 1000 chars; control chars
    other than tab/newline/CR drop the field; empty fields drop;
    items with no remaining fields drop entirely. Missing or
    malformed overlay files return an empty dict — the exporters
    fall back to byte-compatible no-overlay output in that case.
    """
    data = _read_overlay_json(path)
    if data is None:
        return {}
    items = data.get("items")
    if not isinstance(items, dict):
        return {}
    out: dict[str, dict] = {}
    for key, entry in items.items():
        if (
            not isinstance(key, str)
            or not _TRANSCRIPT_NOTE_KEY_RE.match(key)
        ):
            continue
        if not isinstance(entry, dict):
            continue
        cleaned: dict[str, str] = {}
        raw_corr = entry.get("correction")
        if isinstance(raw_corr, str):
            corr = raw_corr.strip()
            if (
                corr
                and len(corr) <= _OVERLAY_TRANSCRIPT_CORRECTION_MAX_LEN
                and not _overlay_contains_line_control(corr)
            ):
                cleaned["correction"] = corr
        raw_note = entry.get("note")
        if isinstance(raw_note, str):
            note = raw_note.strip()
            if (
                note
                and len(note) <= _OVERLAY_TRANSCRIPT_NOTE_MAX_LEN
                and not _overlay_contains_line_control(note)
            ):
                cleaned["note"] = note
        if cleaned:
            out[key] = cleaned
    return out


def transcript_row_id(source: str, index: int) -> str:
    """Return the stable row id used by the transcript-notes overlay.

    ``source`` is ``"utt"`` or ``"seg"``; ``index`` is the row's
    0-based ordinal in the chosen source array. The format matches
    the keys the React workspace emits so a correction saved in the
    UI lines up with the exporter's render pass without any
    translation layer.
    """
    if source not in ("utt", "seg"):
        raise ValueError(f"transcript_row_id: unknown source {source!r}")
    if not isinstance(index, int) or index < 0:
        raise ValueError(
            f"transcript_row_id: index must be a non-negative int, "
            f"got {index!r}"
        )
    return f"{source}-{index}"


def resolve_transcript_row(
    source: str,
    index: int,
    canonical_text: str,
    overlay: dict[str, dict] | None,
) -> tuple[str, bool, str | None]:
    """Apply a transcript-notes overlay entry to a single row.

    Returns ``(display_text, is_corrected, note_or_none)``:

    - ``display_text`` is the overlay's ``correction`` when set,
      otherwise the canonical transcript text.
    - ``is_corrected`` is ``True`` iff the correction replaced the
      canonical text (empty / whitespace-only canonical still counts
      as corrected if the overlay provides non-empty text).
    - ``note_or_none`` is the overlay's reviewer note (non-empty
      string) or ``None``.

    When ``overlay`` is empty / absent, this function is the identity
    — it returns ``(canonical_text, False, None)`` so exporters stay
    byte-compatible with the no-overlay baseline.
    """
    if not overlay:
        return canonical_text, False, None
    try:
        key = transcript_row_id(source, index)
    except ValueError:
        return canonical_text, False, None
    entry = overlay.get(key)
    if not isinstance(entry, dict):
        return canonical_text, False, None
    corrected = False
    text = canonical_text
    corr = entry.get("correction")
    if isinstance(corr, str) and corr.strip():
        text = corr
        corrected = True
    note_raw = entry.get("note")
    note: str | None = None
    if isinstance(note_raw, str) and note_raw.strip():
        note = note_raw
    return text, corrected, note


def resolve_chapter_title(
    ch_idx: int,
    *,
    custom_by_idx: dict[int, str],
    insights_title: str | None,
) -> str | None:
    """Effective chapter display title.

    Precedence: ``chapter_titles.json`` overlay beats insights title
    beats the generic ``Chapter N`` heading. Returns None when no
    title is available (callers should fall back to just
    ``Chapter {idx}``).
    """
    custom = custom_by_idx.get(ch_idx)
    if isinstance(custom, str) and custom.strip():
        return custom.strip()
    if isinstance(insights_title, str) and insights_title.strip():
        return insights_title.strip()
    return None


def resolve_speaker_label(
    speaker: object,
    labels: dict[str, str],
) -> str | None:
    """Return the effective speaker label for a speaker id.

    Falls back to ``Speaker {id}`` (integer ids) or the raw string id
    when no custom label applies. Returns None when ``speaker`` is
    not a valid speaker reference so the caller can skip the prefix
    entirely.
    """
    if isinstance(speaker, bool):
        return None
    if isinstance(speaker, int):
        key = str(speaker)
        custom = labels.get(key)
        if isinstance(custom, str) and custom.strip():
            return custom.strip()
        return f"Speaker {speaker}"
    if isinstance(speaker, str) and speaker.strip():
        key = speaker.strip()
        custom = labels.get(key)
        if isinstance(custom, str) and custom.strip():
            return custom.strip()
        # Raw numeric-string id → `Speaker N` for consistency with the
        # React transcript workspace.
        if key.isdigit():
            return f"Speaker {key}"
        return key
    return None


def apply_frame_review_to_chapter(
    chapter: dict,
    hero_frame_raw: dict | None,
    overlay: dict[str, dict],
) -> tuple[dict | None, list[dict]]:
    """Return ``(effective_hero, effective_supporting_frames)``.

    - ``effective_hero`` is the validated ``selected_hero`` frame
      unless its ``frame_file`` has ``decision="reject"`` in the
      overlay, in which case it's ``None`` (no replacement — the
      exporter just skips the hero image for that chapter).
    - ``effective_supporting`` is the chapter's ``selected_supporting``
      frames in ``supporting_scene_indices`` order, **minus** any
      whose ``frame_file`` has ``decision="reject"``, plus any
      ``vlm_rejected`` frames in the chapter whose overlay decision
      is ``"keep"`` appended at the end (sorted by ``scene_index``).

    ``keep`` on an already-selected frame is a no-op (the user's
    affirmation is preserved, but no re-ordering happens).
    ``unset`` is never persisted in the overlay, so it does not
    appear here.

    This function does not mutate ``chapter`` or ``overlay``.
    """
    frames_by_scene: dict[int, dict] = {}
    for fr in chapter.get("frames") or []:
        if isinstance(fr, dict) and is_int(fr.get("scene_index")):
            frames_by_scene[fr["scene_index"]] = fr

    effective_hero: dict | None = hero_frame_raw
    if hero_frame_raw is not None:
        hero_file = hero_frame_raw.get("frame_file")
        entry = overlay.get(hero_file) if isinstance(hero_file, str) else None
        if isinstance(entry, dict) and entry.get("decision") == "reject":
            effective_hero = None

    effective_supporting: list[dict] = []
    included_files: set[str] = set()
    if effective_hero is not None:
        file_ = effective_hero.get("frame_file")
        if isinstance(file_, str):
            included_files.add(file_)
    for si in chapter.get("supporting_scene_indices") or []:
        fr = frames_by_scene.get(si)
        if fr is None or fr.get("decision") != "selected_supporting":
            continue
        fname = fr.get("frame_file")
        if not isinstance(fname, str):
            continue
        entry = overlay.get(fname)
        if isinstance(entry, dict) and entry.get("decision") == "reject":
            continue
        effective_supporting.append(fr)
        included_files.add(fname)

    # Promote any vlm_rejected frames the user marked as "keep" —
    # appended at the end in scene_index order so MD/HTML/DOCX all
    # produce stable, matching output.
    promotions: list[dict] = []
    for fr in chapter.get("frames") or []:
        if not isinstance(fr, dict):
            continue
        if fr.get("decision") != "vlm_rejected":
            continue
        fname = fr.get("frame_file")
        if not isinstance(fname, str) or fname in included_files:
            continue
        entry = overlay.get(fname)
        if isinstance(entry, dict) and entry.get("decision") == "keep":
            promotions.append(fr)
    promotions.sort(
        key=lambda f: (
            f.get("scene_index")
            if is_int(f.get("scene_index"))
            else 10**9
        ),
    )
    effective_supporting.extend(promotions)

    return effective_hero, effective_supporting


def iter_transcript_utterances(
    transcript: dict,
) -> list[dict]:
    """Return the non-empty, speaker-valid utterance list, else ``[]``.

    Mirrors the legacy transcript-viewer policy (see ``recap/ui.py``):
    we only switch the exporter's transcript rendering over to
    ``utterances[]`` when at least one utterance has a speaker id that
    is either a non-negative integer or a non-empty string. Otherwise
    the exporter falls through to ``segments[]`` and its current
    byte-compatible output.
    """
    utterances = transcript.get("utterances")
    if not isinstance(utterances, list) or not utterances:
        return []
    any_valid = False
    for u in utterances:
        if not isinstance(u, dict):
            continue
        sp = u.get("speaker")
        if isinstance(sp, bool):
            continue
        if isinstance(sp, int):
            any_valid = True
            break
        if isinstance(sp, str) and sp.strip():
            any_valid = True
            break
    return utterances if any_valid else []
