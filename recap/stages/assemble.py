"""Stage 8: Markdown assembly.

Reads existing artifacts (`job.json`, `metadata.json`, `transcript.json`)
and writes `report.md`.

When `selected_frames.json` is present on disk, a `## Chapters` section
is inserted between `## Media` and `## Transcript` that embeds the
finalized hero/supporting screenshots (and any Gemini-provided captions)
produced by `recap verify`. When `selected_frames.json` is absent the
output is byte-identical to the Phase-1 basic report — `recap run`
continues to produce the same basic report shape.

This stage never calls a VLM and never mutates upstream artifacts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, read_job, update_stage


_WHITESPACE_RE = re.compile(r"\s+")


def _format_ts(seconds: float) -> str:
    if seconds is None:
        return "--:--:--"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _summarize_metadata(meta: dict) -> dict:
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


def _collapse_whitespace(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


_SELECTED_FRAME_DECISIONS = (
    "selected_hero",
    "selected_supporting",
    "vlm_rejected",
)


def _is_int(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _validate_selected_frames(data: object) -> dict:
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
        if not _is_int(ch["chapter_index"]):
            raise RuntimeError(
                "selected_frames.json malformed: chapter 'chapter_index' "
                "must be an integer"
            )
        ch_idx = ch["chapter_index"]
        if not _is_number(ch["start_seconds"]):
            raise RuntimeError(
                f"selected_frames.json malformed: chapter {ch_idx} "
                "'start_seconds' must be numeric"
            )
        if not _is_number(ch["end_seconds"]):
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
            if not _is_int(si):
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
            if not _is_int(hero["scene_index"]):
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} "
                    "hero 'scene_index' must be an integer"
                )
            if (
                not isinstance(hero["frame_file"], str)
                or not hero["frame_file"]
            ):
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} "
                    "hero 'frame_file' must be a non-empty string"
                )
            if not _is_number(hero["midpoint_seconds"]):
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
            if not isinstance(fr["frame_file"], str) or not fr["frame_file"]:
                raise RuntimeError(
                    "selected_frames.json malformed: frame 'frame_file' "
                    "must be a non-empty string"
                )
            if not _is_int(fr["scene_index"]):
                raise RuntimeError(
                    "selected_frames.json malformed: frame 'scene_index' "
                    "must be an integer"
                )
            if not _is_number(fr["midpoint_seconds"]):
                raise RuntimeError(
                    "selected_frames.json malformed: frame "
                    "'midpoint_seconds' must be numeric"
                )
            if not isinstance(fr["decision"], str):
                raise RuntimeError(
                    "selected_frames.json malformed: frame 'decision' "
                    "must be a string"
                )
            if fr["decision"] not in _SELECTED_FRAME_DECISIONS:
                raise RuntimeError(
                    "selected_frames.json malformed: frame 'decision' "
                    f"must be one of {list(_SELECTED_FRAME_DECISIONS)}"
                )
    return data


def _validate_chapter_candidates(data: object) -> dict[int, str]:
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


def _caption_for(frame: dict) -> str | None:
    verification = frame.get("verification")
    if not isinstance(verification, dict):
        return None
    caption = verification.get("caption")
    if isinstance(caption, str):
        collapsed = _collapse_whitespace(caption)
        if collapsed:
            return collapsed
    return None


def _chapter_section_lines(
    selected: dict,
    chapter_text_by_index: dict[int, str],
    frames_dir: Path,
) -> list[str]:
    lines: list[str] = []
    lines.append("## Chapters")
    lines.append("")

    for ch in selected["chapters"]:
        ch_idx = ch["chapter_index"]
        if ch_idx not in chapter_text_by_index:
            raise RuntimeError(
                f"chapter_candidates.json has no chapter with index {ch_idx} "
                "required by selected_frames.json"
            )
        start = _format_ts(ch.get("start_seconds") or 0.0)
        end = _format_ts(ch.get("end_seconds") or 0.0)
        lines.append(f"### Chapter {ch_idx} — [{start} – {end}]")
        lines.append("")

        frames_by_scene: dict[int, dict] = {}
        for fr in ch["frames"]:
            frames_by_scene[fr["scene_index"]] = fr

        # Coherence checks across chapter.frames[], chapter.hero, and
        # chapter.supporting_scene_indices. These run before any rendering
        # so a corrupted artifact cannot silently omit or reorder frames.
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
        else:
            if hero is not None:
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} has "
                    "chapter.hero set but no frame with "
                    "decision='selected_hero'"
                )

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

        hero_scene_index: int | None = None
        if hero is not None:
            if not isinstance(hero, dict) or "scene_index" not in hero:
                raise RuntimeError(
                    "selected_frames.json malformed: chapter hero missing "
                    "'scene_index'"
                )
            hero_scene_index = hero["scene_index"]
            hero_frame = frames_by_scene.get(hero_scene_index)
            if hero_frame is None or hero_frame.get("decision") != "selected_hero":
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} hero "
                    f"scene_index {hero_scene_index} has no matching "
                    "'selected_hero' frame"
                )
            frame_file = hero_frame["frame_file"]
            image_path = frames_dir / frame_file
            if not image_path.exists():
                raise RuntimeError(
                    f"missing candidate frame: candidate_frames/{frame_file}"
                )
            lines.append(
                f"![Chapter {ch_idx} hero](candidate_frames/{frame_file})"
            )
            lines.append("")
            caption = _caption_for(hero_frame)
            if caption:
                lines.append(f"*{caption}*")
                lines.append("")

        for si in ch["supporting_scene_indices"]:
            support_frame = frames_by_scene.get(si)
            if (
                support_frame is None
                or support_frame.get("decision") != "selected_supporting"
            ):
                raise RuntimeError(
                    f"selected_frames.json malformed: chapter {ch_idx} "
                    f"supporting_scene_indices references scene_index {si} "
                    "without a matching 'selected_supporting' frame"
                )
            frame_file = support_frame["frame_file"]
            image_path = frames_dir / frame_file
            if not image_path.exists():
                raise RuntimeError(
                    f"missing candidate frame: candidate_frames/{frame_file}"
                )
            lines.append(
                f"![Chapter {ch_idx} supporting](candidate_frames/{frame_file})"
            )
            lines.append("")
            caption = _caption_for(support_frame)
            if caption:
                lines.append(f"*{caption}*")
                lines.append("")

        body_text = _collapse_whitespace(chapter_text_by_index[ch_idx])
        if body_text:
            lines.append(body_text)
            lines.append("")

    return lines


def build_markdown(
    job: dict,
    meta_summary: dict,
    transcript: dict | None,
    chapters_section: list[str] | None = None,
) -> str:
    lines: list[str] = []
    title = job.get("original_filename") or job.get("job_id")
    lines.append(f"# Recap: {title}")
    lines.append("")
    lines.append(f"- Job ID: `{job.get('job_id')}`")
    if job.get("original_filename"):
        lines.append(f"- Source file: `{job['original_filename']}`")
    if job.get("created_at"):
        lines.append(f"- Created: {job['created_at']}")
    lines.append("")

    lines.append("## Media")
    dur = meta_summary.get("duration_seconds")
    if dur is not None:
        lines.append(f"- Duration: {_format_ts(dur)} ({dur:.2f}s)")
    if meta_summary.get("format_name"):
        lines.append(f"- Container: {meta_summary['format_name']}")
    v = meta_summary.get("video")
    if v:
        res = f"{v.get('width')}x{v.get('height')}" if v.get("width") else "unknown"
        lines.append(f"- Video: {v.get('codec')} {res} @ {v.get('frame_rate')}")
    a = meta_summary.get("audio")
    if a:
        lines.append(
            f"- Audio: {a.get('codec')} {a.get('sample_rate')} Hz, {a.get('channels')} ch"
        )
    lines.append("")

    if chapters_section:
        lines.extend(chapters_section)

    lines.append("## Transcript")
    if transcript is None:
        lines.append("_No transcript available._")
        lines.append("")
        return "\n".join(lines)

    lines.append(
        f"- Engine: `{transcript.get('engine')}` (model `{transcript.get('model')}`)"
    )
    if transcript.get("language"):
        lines.append(f"- Detected language: `{transcript['language']}`")
    segs = transcript.get("segments", []) or []
    lines.append(f"- Segments: {len(segs)}")
    lines.append("")

    lines.append("### Segments")
    lines.append("")
    for seg in segs:
        start = _format_ts(seg.get("start") or 0.0)
        end = _format_ts(seg.get("end") or 0.0)
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(f"- **[{start} – {end}]** {text}")
    lines.append("")
    return "\n".join(lines)


def run(paths: JobPaths, force: bool = False) -> Path:
    update_stage(paths, "assemble", RUNNING)
    tmp = paths.report_md.with_suffix(".md.tmp")
    try:
        job = read_job(paths)

        meta_summary: dict = {}
        if paths.metadata_json.exists():
            with open(paths.metadata_json) as f:
                meta_summary = _summarize_metadata(json.load(f))

        transcript: dict | None = None
        if paths.transcript_json.exists():
            with open(paths.transcript_json) as f:
                transcript = json.load(f)

        if not force and paths.report_md.exists():
            update_stage(paths, "assemble", COMPLETED, extra={"skipped": True})
            return paths.report_md

        chapters_section: list[str] | None = None
        if paths.selected_frames_json.exists():
            try:
                with open(paths.selected_frames_json, "r", encoding="utf-8") as f:
                    selected_raw = json.load(f)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"selected_frames.json malformed: invalid JSON: {e.msg}"
                ) from e
            selected = _validate_selected_frames(selected_raw)

            if not paths.chapter_candidates_json.exists():
                raise RuntimeError(
                    "chapter_candidates.json is required when "
                    "selected_frames.json is present but was not found"
                )
            try:
                with open(
                    paths.chapter_candidates_json, "r", encoding="utf-8"
                ) as f:
                    chapters_raw = json.load(f)
            except json.JSONDecodeError as e:
                raise RuntimeError(
                    f"chapter_candidates.json malformed: invalid JSON: {e.msg}"
                ) from e
            chapter_text_by_index = _validate_chapter_candidates(chapters_raw)

            chapters_section = _chapter_section_lines(
                selected, chapter_text_by_index, paths.candidate_frames_dir
            )

        md = build_markdown(job, meta_summary, transcript, chapters_section)
        tmp.write_text(md, encoding="utf-8")
        tmp.replace(paths.report_md)

        extra: dict = {
            "report": paths.report_md.name,
            "bytes": paths.report_md.stat().st_size,
            "embedded_selected_frames": chapters_section is not None,
        }
        update_stage(paths, "assemble", COMPLETED, extra=extra)
        return paths.report_md
    except Exception as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        update_stage(paths, "assemble", FAILED, error=f"{type(e).__name__}: {e}")
        raise
