"""Phase 4 slice: optional DOCX export.

Reads the same artifacts `recap assemble` and `recap export-html` read
(`job.json`, `metadata.json`, `transcript.json`, and — when present —
`selected_frames.json` + `chapter_candidates.json`) and writes
`report.docx` via `python-docx`. No Markdown parsing, no network, no
VLM/LLM calls. Images from `candidate_frames/` are embedded into the
DOCX package with `Document.add_picture(...)`; no image files are
copied, renamed, or rewritten on disk.

This stage is opt-in via `recap export-docx --job <path>`. It is NOT
invoked by `recap run` and it is NOT part of `job.STAGES`. It does not
modify `report.md`, `report.html`, `selected_frames.json`, or any
upstream artifact.

Validation follows the same selected-path contract as the Markdown and
HTML exports. The shared validators, formatters, and safety helpers
live in `recap/stages/report_helpers.py` so all three report stages
stay in lockstep.
"""

from __future__ import annotations

import json
from pathlib import Path

from docx import Document
from docx.shared import Inches

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


_IMAGE_WIDTH_INCHES = 6.0



def _add_caption(doc, caption: str) -> None:
    p = doc.add_paragraph()
    run = p.add_run(caption)
    run.italic = True


def _render_overview(doc, insights: dict) -> None:
    overview = insights.get("overview") or {}
    doc.add_heading("Overview", level=2)
    short_summary = (overview.get("short_summary") or "").strip()
    if short_summary:
        doc.add_paragraph(short_summary)
    detailed = (overview.get("detailed_summary") or "").strip()
    if detailed and detailed != short_summary:
        doc.add_paragraph(detailed)

    bullets = overview.get("quick_bullets") or []
    if bullets:
        doc.add_heading("Quick bullets", level=3)
        for b in bullets:
            if isinstance(b, str) and b.strip():
                doc.add_paragraph(b.strip(), style="List Bullet")

    actions = insights.get("action_items") or []
    if actions:
        doc.add_heading("Action items", level=3)
        for ai in actions:
            if not isinstance(ai, dict):
                continue
            text = (ai.get("text") or "").strip()
            if not text:
                continue
            bits = [text]
            stamp = ai.get("timestamp_seconds")
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
                bits.append(f"[{_format_ts(float(stamp))}]")
            ch_idx = ai.get("chapter_index")
            if isinstance(ch_idx, int):
                bits.append(f"Chapter {ch_idx}")
            owner = ai.get("owner")
            if isinstance(owner, str) and owner.strip():
                bits.append(f"Owner: {owner.strip()}")
            due = ai.get("due")
            if isinstance(due, str) and due.strip():
                bits.append(f"Due: {due.strip()}")
            suffix = (" — " + " · ".join(bits[1:])) if len(bits) > 1 else ""
            doc.add_paragraph(
                f"☐ {bits[0]}{suffix}", style="List Bullet"
            )


def _add_chapter_insights_block(doc, ch: dict) -> None:
    summary = (ch.get("summary") or "").strip()
    if summary:
        doc.add_paragraph(summary)
    bullets = ch.get("bullets") or []
    for b in bullets:
        if isinstance(b, str) and b.strip():
            doc.add_paragraph(b.strip(), style="List Bullet")
    action_items = ch.get("action_items") or []
    if action_items:
        doc.add_paragraph("Action items:")
        for ai in action_items:
            if isinstance(ai, str) and ai.strip():
                doc.add_paragraph(f"☐ {ai.strip()}", style="List Bullet")
    speakers = ch.get("speaker_focus") or []
    if speakers:
        p = doc.add_paragraph()
        r = p.add_run(f"Speakers: {', '.join(speakers)}")
        r.italic = True


def _render_insights_only_chapters(doc, insights: dict) -> None:
    doc.add_heading("Chapters", level=2)
    for ch in insights.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        idx = ch.get("index")
        start = _format_ts(ch.get("start_seconds"))
        end = _format_ts(ch.get("end_seconds"))
        title = (ch.get("title") or "").strip()
        heading = f"Chapter {idx}"
        if title:
            heading += f" — {title}"
        heading += f" [{start} – {end}]"
        doc.add_heading(heading, level=3)
        _add_chapter_insights_block(doc, ch)


def _add_image(doc, image_path: Path) -> None:
    doc.add_picture(str(image_path), width=Inches(_IMAGE_WIDTH_INCHES))



def _render_chapters(
    doc,
    selected: dict,
    chapter_text_by_index: dict[int, str],
    frames_dir: Path,
    insights_by_idx: dict[int, dict] | None = None,
) -> None:
    doc.add_heading("Chapters", level=2)

    for ch in selected["chapters"]:
        ch_idx = ch["chapter_index"]
        if ch_idx not in chapter_text_by_index:
            raise RuntimeError(
                f"chapter_candidates.json has no chapter with index {ch_idx} "
                "required by selected_frames.json"
            )

        hero_frame = _check_hero_coherence(ch)
        _check_supporting_coherence(ch)

        start = _format_ts(ch.get("start_seconds") or 0.0)
        end = _format_ts(ch.get("end_seconds") or 0.0)
        insight = (insights_by_idx or {}).get(ch_idx)
        heading = f"Chapter {ch_idx}"
        if insight and (insight.get("title") or "").strip():
            heading += f" — {insight['title'].strip()}"
        heading += f" [{start} – {end}]"
        doc.add_heading(heading, level=3)
        if insight is not None:
            _add_chapter_insights_block(doc, insight)

        frames_by_scene: dict[int, dict] = {}
        for fr in ch["frames"]:
            frames_by_scene[fr["scene_index"]] = fr

        if hero_frame is not None:
            frame_file = hero_frame["frame_file"]
            image_path = frames_dir / frame_file
            if not image_path.exists():
                raise RuntimeError(
                    f"missing candidate frame: candidate_frames/{frame_file}"
                )
            _add_image(doc, image_path)
            caption = _caption_for(hero_frame)
            if caption:
                _add_caption(doc, caption)

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
            _add_image(doc, image_path)
            caption = _caption_for(support_frame)
            if caption:
                _add_caption(doc, caption)

        body_text = _collapse_whitespace(chapter_text_by_index[ch_idx])
        if body_text:
            doc.add_paragraph(body_text)


def build_document(
    job: dict,
    meta_summary: dict,
    transcript: dict | None,
    selected: dict | None,
    chapter_text_by_index: dict[int, str] | None,
    frames_dir: Path,
    insights: dict | None = None,
):
    doc = Document()
    title = job.get("original_filename") or job.get("job_id") or "Recap"
    doc.add_heading(f"Recap: {title}", level=1)

    if job.get("job_id"):
        doc.add_paragraph(f"Job ID: {job['job_id']}")
    if job.get("original_filename"):
        doc.add_paragraph(f"Source file: {job['original_filename']}")
    if job.get("created_at"):
        doc.add_paragraph(f"Created: {job['created_at']}")

    if insights is not None:
        _render_overview(doc, insights)

    if selected is None and insights is not None and (
        insights.get("chapters") or []
    ):
        _render_insights_only_chapters(doc, insights)

    doc.add_heading("Media", level=2)
    dur = meta_summary.get("duration_seconds")
    if dur is not None:
        doc.add_paragraph(f"Duration: {_format_ts(dur)} ({dur:.2f}s)")
    if meta_summary.get("format_name"):
        doc.add_paragraph(f"Container: {meta_summary['format_name']}")
    v = meta_summary.get("video")
    if v:
        res = f"{v.get('width')}x{v.get('height')}" if v.get("width") else "unknown"
        doc.add_paragraph(
            f"Video: {v.get('codec')} {res} @ {v.get('frame_rate')}"
        )
    a = meta_summary.get("audio")
    if a:
        doc.add_paragraph(
            f"Audio: {a.get('codec')} {a.get('sample_rate')} Hz, "
            f"{a.get('channels')} ch"
        )

    if selected is not None and chapter_text_by_index is not None:
        insights_by_idx = (
            _insights_chapters_by_index(insights) if insights else None
        )
        _render_chapters(
            doc,
            selected,
            chapter_text_by_index,
            frames_dir,
            insights_by_idx=insights_by_idx,
        )

    doc.add_heading("Transcript", level=2)
    if transcript is None:
        doc.add_paragraph("No transcript available.")
        return doc

    engine = transcript.get("engine")
    model = transcript.get("model")
    doc.add_paragraph(f"Engine: {engine} (model {model})")
    if transcript.get("language"):
        doc.add_paragraph(f"Detected language: {transcript['language']}")
    segs = transcript.get("segments", []) or []
    doc.add_paragraph(f"Segments: {len(segs)}")

    doc.add_heading("Segments", level=3)
    for seg in segs:
        start = _format_ts(seg.get("start") or 0.0)
        end = _format_ts(seg.get("end") or 0.0)
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        doc.add_paragraph(
            f"[{start} – {end}] {text}", style="List Bullet"
        )

    return doc


def run(paths: JobPaths, force: bool = False) -> Path:
    update_stage(paths, "export_docx", RUNNING)
    tmp = paths.report_docx.with_suffix(".docx.tmp")
    try:
        if not force and paths.report_docx.exists():
            update_stage(
                paths, "export_docx", COMPLETED, extra={"skipped": True}
            )
            return paths.report_docx

        job = read_job(paths)

        meta_summary: dict = {}
        if paths.metadata_json.exists():
            with open(paths.metadata_json, "r", encoding="utf-8") as f:
                meta_summary = _summarize_metadata(json.load(f))

        transcript: dict | None = None
        if paths.transcript_json.exists():
            with open(paths.transcript_json, "r", encoding="utf-8") as f:
                transcript = json.load(f)

        insights = _load_insights(paths.insights_json)

        selected: dict | None = None
        chapter_text_by_index: dict[int, str] | None = None
        if paths.selected_frames_json.exists():
            try:
                with open(
                    paths.selected_frames_json, "r", encoding="utf-8"
                ) as f:
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

        doc = build_document(
            job,
            meta_summary,
            transcript,
            selected,
            chapter_text_by_index,
            paths.candidate_frames_dir,
            insights=insights,
        )

        doc.save(str(tmp))
        tmp.replace(paths.report_docx)

        extra: dict = {
            "report": paths.report_docx.name,
            "bytes": paths.report_docx.stat().st_size,
            "embedded_selected_frames": selected is not None,
            "embedded_insights": insights is not None,
        }
        update_stage(paths, "export_docx", COMPLETED, extra=extra)
        return paths.report_docx
    except Exception as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        update_stage(
            paths, "export_docx", FAILED, error=f"{type(e).__name__}: {e}"
        )
        raise
