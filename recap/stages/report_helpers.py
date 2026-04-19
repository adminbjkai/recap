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

import re
from pathlib import Path


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
