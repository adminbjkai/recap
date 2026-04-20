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
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, read_job, update_stage
from .report_helpers import (
    caption_for as _caption_for,
    check_hero_coherence as _check_hero_coherence,
    check_supporting_coherence as _check_supporting_coherence,
    collapse_whitespace as _collapse_whitespace,
    format_ts as _format_ts,
    insights_chapters_by_index as _insights_chapters_by_index,
    load_insights as _load_insights,
    summarize_metadata as _summarize_metadata,
    validate_chapter_candidates as _validate_chapter_candidates,
    validate_selected_frames as _validate_selected_frames,
)


def _overview_section_lines(insights: dict) -> list[str]:
    overview = insights.get("overview") or {}
    out: list[str] = []
    out.append("## Overview")
    out.append("")
    short_summary = (overview.get("short_summary") or "").strip()
    if short_summary:
        out.append(short_summary)
        out.append("")
    detailed = (overview.get("detailed_summary") or "").strip()
    if detailed and detailed != short_summary:
        out.append(detailed)
        out.append("")
    bullets = overview.get("quick_bullets") or []
    if bullets:
        out.append("### Quick bullets")
        out.append("")
        for b in bullets:
            if isinstance(b, str) and b.strip():
                out.append(f"- {b.strip()}")
        out.append("")
    actions = insights.get("action_items") or []
    if actions:
        out.append("### Action items")
        out.append("")
        for ai in actions:
            if not isinstance(ai, dict):
                continue
            text = (ai.get("text") or "").strip()
            if not text:
                continue
            stamp = ai.get("timestamp_seconds")
            suffix_parts: list[str] = []
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
                suffix_parts.append(f"[{_format_ts(float(stamp))}]")
            ch_idx = ai.get("chapter_index")
            if isinstance(ch_idx, int):
                suffix_parts.append(f"Chapter {ch_idx}")
            owner = ai.get("owner")
            if isinstance(owner, str) and owner.strip():
                suffix_parts.append(f"Owner: {owner.strip()}")
            due = ai.get("due")
            if isinstance(due, str) and due.strip():
                suffix_parts.append(f"Due: {due.strip()}")
            suffix = f" — {' · '.join(suffix_parts)}" if suffix_parts else ""
            out.append(f"- [ ] {text}{suffix}")
        out.append("")
    return out


def _insights_chapter_block(ch: dict) -> list[str]:
    out: list[str] = []
    summary = (ch.get("summary") or "").strip()
    if summary:
        out.append(summary)
        out.append("")
    bullets = ch.get("bullets") or []
    if bullets:
        for b in bullets:
            if isinstance(b, str) and b.strip():
                out.append(f"- {b.strip()}")
        out.append("")
    action_items = ch.get("action_items") or []
    if action_items:
        out.append("**Action items:**")
        out.append("")
        for ai in action_items:
            if isinstance(ai, str) and ai.strip():
                out.append(f"- [ ] {ai.strip()}")
        out.append("")
    speakers = ch.get("speaker_focus") or []
    if speakers:
        out.append(f"*Speakers:* {', '.join(speakers)}")
        out.append("")
    return out


def _insights_only_chapters_section_lines(insights: dict) -> list[str]:
    out: list[str] = []
    out.append("## Chapters")
    out.append("")
    for ch in insights.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        idx = ch.get("index")
        start = _format_ts(ch.get("start_seconds"))
        end = _format_ts(ch.get("end_seconds"))
        title = (ch.get("title") or "").strip()
        heading = f"### Chapter {idx}"
        if title:
            heading += f" — {title}"
        heading += f" [{start} – {end}]"
        out.append(heading)
        out.append("")
        out.extend(_insights_chapter_block(ch))
    return out


def _chapter_section_lines(
    selected: dict,
    chapter_text_by_index: dict[int, str],
    frames_dir: Path,
    insights_by_idx: dict[int, dict] | None = None,
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
        heading = f"### Chapter {ch_idx}"
        insight = (insights_by_idx or {}).get(ch_idx)
        if insight and (insight.get("title") or "").strip():
            heading += f" — {insight['title'].strip()}"
        heading += f" [{start} – {end}]"
        lines.append(heading)
        lines.append("")
        if insight is not None:
            lines.extend(_insights_chapter_block(insight))

        frames_by_scene: dict[int, dict] = {}
        for fr in ch["frames"]:
            frames_by_scene[fr["scene_index"]] = fr

        # Coherence checks run before rendering so a corrupted artifact
        # cannot silently omit or reorder frames.
        _check_hero_coherence(ch)
        _check_supporting_coherence(ch)
        hero = ch.get("hero")

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
    insights: dict | None = None,
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

    if insights is not None:
        lines.extend(_overview_section_lines(insights))

    # When selected_frames is absent but insights provides chapters,
    # still render a Chapters section (text-only) so the report
    # surfaces structured content even without hero screenshots.
    if chapters_section is None and insights is not None and (
        insights.get("chapters") or []
    ):
        lines.extend(_insights_only_chapters_section_lines(insights))

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

        insights = _load_insights(paths.insights_json)
        insights_by_idx = (
            _insights_chapters_by_index(insights) if insights else {}
        )

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
                selected,
                chapter_text_by_index,
                paths.candidate_frames_dir,
                insights_by_idx=insights_by_idx,
            )

        md = build_markdown(
            job,
            meta_summary,
            transcript,
            chapters_section,
            insights=insights,
        )
        tmp.write_text(md, encoding="utf-8")
        tmp.replace(paths.report_md)

        extra: dict = {
            "report": paths.report_md.name,
            "bytes": paths.report_md.stat().st_size,
            "embedded_selected_frames": chapters_section is not None,
            "embedded_insights": insights is not None,
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
