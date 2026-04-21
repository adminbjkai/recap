"""Phase 4 slice: optional HTML export.

Reads the same artifacts `recap assemble` reads (`job.json`,
`metadata.json`, `transcript.json`, and — when present —
`selected_frames.json` + `chapter_candidates.json`) and writes
`report.html` via direct string construction. No Markdown parsing, no
new dependencies, no network, no VLM/LLM calls.

This stage is opt-in via `recap export-html --job <path>`. It is NOT
invoked by `recap run` and it is NOT part of `job.STAGES`. It does not
modify `report.md`, `selected_frames.json`, or any upstream artifact.

Validation follows the same rules `recap assemble` enforces when
`selected_frames.json` is present. The shared validators, formatters,
and safety helpers live in `recap/stages/report_helpers.py` so all
three report stages stay in lockstep.
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, read_job, update_stage
from .report_helpers import (
    apply_frame_review_to_chapter as _apply_frame_review_to_chapter,
    caption_for as _caption_for,
    check_hero_coherence as _check_hero_coherence,
    check_supporting_coherence as _check_supporting_coherence,
    collapse_whitespace as _collapse_whitespace,
    format_ts as _format_ts,
    insights_chapters_by_index as _insights_chapters_by_index,
    iter_transcript_utterances as _iter_transcript_utterances,
    load_chapter_titles_overlay as _load_chapter_titles_overlay,
    load_frame_review_overlay as _load_frame_review_overlay,
    load_insights as _load_insights,
    load_speaker_names_overlay as _load_speaker_names_overlay,
    load_transcript_notes_overlay as _load_transcript_notes_overlay,
    resolve_chapter_title as _resolve_chapter_title,
    resolve_speaker_label as _resolve_speaker_label,
    resolve_transcript_row as _resolve_transcript_row,
    summarize_metadata as _summarize_metadata,
    validate_chapter_candidates as _validate_chapter_candidates,
    validate_selected_frames as _validate_selected_frames,
)

_INLINE_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       max-width: 900px; margin: 2rem auto; padding: 0 1rem;
       line-height: 1.5; color: #1a1a1a; }
h1 { border-bottom: 1px solid #ddd; padding-bottom: 0.3rem; }
h2 { margin-top: 2rem; border-bottom: 1px solid #eee; padding-bottom: 0.2rem; }
h3 { margin-top: 1.5rem; }
img { max-width: 100%; height: auto; display: block; margin: 0.5rem 0; }
code { background: #f4f4f4; padding: 0.1rem 0.3rem; border-radius: 3px; }
section.chapter { margin-bottom: 2rem; }
section.overview p.summary { font-size: 1.05rem; color: #222; }
ul.quick-bullets, ul.action-items, ul.chapter-bullets,
ul.chapter-action-items { margin: 0.4rem 0 0.8rem 1.4rem; }
ul.action-items li, ul.chapter-action-items li { list-style-type: none; }
ul.action-items li::before, ul.chapter-action-items li::before {
  content: "\\25A2"; margin-right: 0.4rem; color: #555; }
p.chapter-summary { margin: 0.3rem 0 0.6rem; }
p.chapter-speakers em { color: #555; }
ul.segments li { margin: 0.2rem 0; }
p em { color: #444; }
.transcript-edited { color: #8a4a00; font-style: italic; margin-left: 0.3rem; }
p.transcript-note { margin: 0.2rem 0 0.4rem 0.4rem;
                    padding: 0.3rem 0.5rem; border-left: 3px solid #b2471a;
                    background: #fff4e6; color: #3a2a1a; font-size: 0.95em; }
p.transcript-note em { color: #7a3a12; }
""".strip()


def _e(value: object) -> str:
    """Escape any content-bearing value for safe HTML text/attribute use."""
    return html.escape("" if value is None else str(value), quote=True)


def _overview_section_html(insights: dict) -> list[str]:
    overview = insights.get("overview") or {}
    out: list[str] = ['<section class="overview">', "<h2>Overview</h2>"]
    short_summary = (overview.get("short_summary") or "").strip()
    if short_summary:
        out.append(f'<p class="summary">{_e(short_summary)}</p>')
    detailed = (overview.get("detailed_summary") or "").strip()
    if detailed and detailed != short_summary:
        out.append(f"<p>{_e(detailed)}</p>")
    bullets = overview.get("quick_bullets") or []
    if bullets:
        out.append("<h3>Quick bullets</h3>")
        out.append('<ul class="quick-bullets">')
        for b in bullets:
            if isinstance(b, str) and b.strip():
                out.append(f"<li>{_e(b.strip())}</li>")
        out.append("</ul>")
    actions = insights.get("action_items") or []
    if actions:
        out.append("<h3>Action items</h3>")
        out.append('<ul class="action-items">')
        for ai in actions:
            if not isinstance(ai, dict):
                continue
            text = (ai.get("text") or "").strip()
            if not text:
                continue
            parts = [_e(text)]
            stamp = ai.get("timestamp_seconds")
            if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
                parts.append(
                    f' <small>[{_e(_format_ts(float(stamp)))}]</small>'
                )
            ch_idx = ai.get("chapter_index")
            if isinstance(ch_idx, int):
                parts.append(f" <small>Chapter {_e(ch_idx)}</small>")
            owner = ai.get("owner")
            if isinstance(owner, str) and owner.strip():
                parts.append(f" <small>Owner: {_e(owner.strip())}</small>")
            due = ai.get("due")
            if isinstance(due, str) and due.strip():
                parts.append(f" <small>Due: {_e(due.strip())}</small>")
            out.append(f"<li>{''.join(parts)}</li>")
        out.append("</ul>")
    out.append("</section>")
    return out


def _insights_chapter_block_html(ch: dict) -> list[str]:
    out: list[str] = []
    summary = (ch.get("summary") or "").strip()
    if summary:
        out.append(f'<p class="chapter-summary">{_e(summary)}</p>')
    bullets = ch.get("bullets") or []
    if bullets:
        out.append('<ul class="chapter-bullets">')
        for b in bullets:
            if isinstance(b, str) and b.strip():
                out.append(f"<li>{_e(b.strip())}</li>")
        out.append("</ul>")
    action_items = ch.get("action_items") or []
    if action_items:
        out.append("<p><strong>Action items:</strong></p>")
        out.append('<ul class="chapter-action-items">')
        for ai in action_items:
            if isinstance(ai, str) and ai.strip():
                out.append(f"<li>{_e(ai.strip())}</li>")
        out.append("</ul>")
    speakers = ch.get("speaker_focus") or []
    if speakers:
        rendered = ", ".join(
            _e(s) for s in speakers if isinstance(s, str) and s.strip()
        )
        out.append(
            f'<p class="chapter-speakers"><em>Speakers: {rendered}</em></p>'
        )
    return out


def _insights_only_chapters_section_html(
    insights: dict,
    chapter_titles_overlay: dict[int, str] | None = None,
) -> list[str]:
    out: list[str] = ["<h2>Chapters</h2>"]
    overlay = chapter_titles_overlay or {}
    for ch in insights.get("chapters") or []:
        if not isinstance(ch, dict):
            continue
        idx = ch.get("index")
        start = _format_ts(ch.get("start_seconds"))
        end = _format_ts(ch.get("end_seconds"))
        heading = f"Chapter {idx}"
        effective_title = None
        if isinstance(idx, int):
            effective_title = _resolve_chapter_title(
                idx,
                custom_by_idx=overlay,
                insights_title=(
                    ch.get("title")
                    if isinstance(ch.get("title"), str)
                    else None
                ),
            )
        if effective_title:
            heading += f" — {effective_title}"
        heading += f" [{start} – {end}]"
        out.append('<section class="chapter">')
        out.append(f"<h3>{_e(heading)}</h3>")
        out.extend(_insights_chapter_block_html(ch))
        out.append("</section>")
    return out


def _chapters_section_html(
    selected: dict,
    chapter_text_by_index: dict[int, str],
    frames_dir: Path,
    insights_by_idx: dict[int, dict] | None = None,
    chapter_titles_overlay: dict[int, str] | None = None,
    frame_review_overlay: dict[str, dict] | None = None,
) -> list[str]:
    out: list[str] = []
    out.append("<h2>Chapters</h2>")

    title_overlay = chapter_titles_overlay or {}
    review_overlay = frame_review_overlay or {}

    for ch in selected["chapters"]:
        ch_idx = ch["chapter_index"]
        if ch_idx not in chapter_text_by_index:
            raise RuntimeError(
                f"chapter_candidates.json has no chapter with index {ch_idx} "
                "required by selected_frames.json"
            )
        start = _format_ts(ch.get("start_seconds") or 0.0)
        end = _format_ts(ch.get("end_seconds") or 0.0)

        # Coherence checks run on the raw artifact first so a corrupted
        # selected_frames.json fails loudly. The overlay is applied
        # only to the validated output.
        hero_frame_raw = _check_hero_coherence(ch)
        _check_supporting_coherence(ch)

        out.append('<section class="chapter">')
        insight = (insights_by_idx or {}).get(ch_idx)
        effective_title = _resolve_chapter_title(
            ch_idx,
            custom_by_idx=title_overlay,
            insights_title=(insight or {}).get("title") if insight else None,
        )
        title_bit = f" — {_e(effective_title)}" if effective_title else ""
        out.append(
            f"<h3>Chapter {_e(ch_idx)}{title_bit} [{_e(start)} – {_e(end)}]</h3>"
        )
        if insight is not None:
            out.extend(_insights_chapter_block_html(insight))

        effective_hero, effective_supporting = (
            _apply_frame_review_to_chapter(
                ch, hero_frame_raw, review_overlay,
            )
        )

        if effective_hero is not None:
            frame_file = effective_hero["frame_file"]
            if not (frames_dir / frame_file).exists():
                raise RuntimeError(
                    f"missing candidate frame: candidate_frames/{frame_file}"
                )
            alt = f"Chapter {ch_idx} hero"
            out.append(
                f'<img src="candidate_frames/{_e(frame_file)}" '
                f'alt="{_e(alt)}">'
            )
            caption = _caption_for(effective_hero)
            if caption:
                out.append(f"<p><em>{_e(caption)}</em></p>")

        for support_frame in effective_supporting:
            frame_file = support_frame["frame_file"]
            if not (frames_dir / frame_file).exists():
                raise RuntimeError(
                    f"missing candidate frame: candidate_frames/{frame_file}"
                )
            alt = f"Chapter {ch_idx} supporting"
            out.append(
                f'<img src="candidate_frames/{_e(frame_file)}" '
                f'alt="{_e(alt)}">'
            )
            caption = _caption_for(support_frame)
            if caption:
                out.append(f"<p><em>{_e(caption)}</em></p>")

        body_text = _collapse_whitespace(chapter_text_by_index[ch_idx])
        if body_text:
            out.append(f"<p>{_e(body_text)}</p>")

        out.append("</section>")

    return out


def _render_note_html(note: str) -> list[str]:
    """Render a reviewer note inside a transcript <li>.

    The note becomes a muted italic paragraph; newlines in the note
    are preserved by splitting into a stack of <span> elements so
    the HTML reads with the same line structure as the React
    workspace.
    """
    parts: list[str] = ['<p class="transcript-note"><em>Note:</em> ']
    first = True
    for line in note.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if not first:
            parts.append("<br>")
        parts.append(_e(stripped))
        first = False
    parts.append("</p>")
    return ["".join(parts)]


def build_html(
    job: dict,
    meta_summary: dict,
    transcript: dict | None,
    chapters_section: list[str] | None,
    insights: dict | None = None,
    chapter_titles_overlay: dict[int, str] | None = None,
    speaker_names_overlay: dict[str, str] | None = None,
    transcript_notes_overlay: dict[str, dict] | None = None,
) -> str:
    title = job.get("original_filename") or job.get("job_id") or "Recap"
    doc_title = f"Recap: {title}"

    lines: list[str] = []
    lines.append("<!doctype html>")
    lines.append('<html lang="en">')
    lines.append("<head>")
    lines.append('<meta charset="utf-8">')
    lines.append(
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
    )
    lines.append(f"<title>{_e(doc_title)}</title>")
    lines.append(f"<style>{_INLINE_CSS}</style>")
    lines.append("</head>")
    lines.append("<body>")

    lines.append(f"<h1>Recap: {_e(title)}</h1>")
    lines.append("<ul>")
    lines.append(f"<li>Job ID: <code>{_e(job.get('job_id'))}</code></li>")
    if job.get("original_filename"):
        lines.append(
            f"<li>Source file: <code>{_e(job['original_filename'])}</code></li>"
        )
    if job.get("created_at"):
        lines.append(f"<li>Created: {_e(job['created_at'])}</li>")
    lines.append("</ul>")

    if insights is not None:
        lines.extend(_overview_section_html(insights))

    if chapters_section is None and insights is not None and (
        insights.get("chapters") or []
    ):
        lines.extend(
            _insights_only_chapters_section_html(
                insights,
                chapter_titles_overlay=chapter_titles_overlay,
            )
        )

    lines.append("<h2>Media</h2>")
    lines.append("<ul>")
    dur = meta_summary.get("duration_seconds")
    if dur is not None:
        lines.append(
            f"<li>Duration: {_e(_format_ts(dur))} ({_e(f'{dur:.2f}')}s)</li>"
        )
    if meta_summary.get("format_name"):
        lines.append(f"<li>Container: {_e(meta_summary['format_name'])}</li>")
    v = meta_summary.get("video")
    if v:
        res = f"{v.get('width')}x{v.get('height')}" if v.get("width") else "unknown"
        lines.append(
            f"<li>Video: {_e(v.get('codec'))} {_e(res)} @ "
            f"{_e(v.get('frame_rate'))}</li>"
        )
    a = meta_summary.get("audio")
    if a:
        lines.append(
            f"<li>Audio: {_e(a.get('codec'))} {_e(a.get('sample_rate'))} "
            f"Hz, {_e(a.get('channels'))} ch</li>"
        )
    lines.append("</ul>")

    if chapters_section:
        lines.extend(chapters_section)

    lines.append("<h2>Transcript</h2>")
    if transcript is None:
        lines.append("<p><em>No transcript available.</em></p>")
        lines.append("</body>")
        lines.append("</html>")
        return "\n".join(lines) + "\n"

    lines.append("<ul>")
    engine = transcript.get("engine")
    model = transcript.get("model")
    lines.append(
        f"<li>Engine: <code>{_e(engine)}</code> (model "
        f"<code>{_e(model)}</code>)</li>"
    )
    if transcript.get("language"):
        lines.append(
            f"<li>Detected language: <code>{_e(transcript['language'])}</code></li>"
        )

    utterances = _iter_transcript_utterances(transcript)
    speaker_labels = speaker_names_overlay or {}
    notes_overlay = transcript_notes_overlay or {}
    if utterances:
        lines.append(f"<li>Utterances: {_e(len(utterances))}</li>")
        lines.append("</ul>")
        lines.append("<h3>Utterances</h3>")
        lines.append('<ul class="segments">')
        for idx, u in enumerate(utterances):
            if not isinstance(u, dict):
                continue
            start = _format_ts(u.get("start") or 0.0)
            end = _format_ts(u.get("end") or 0.0)
            canonical = (u.get("text") or "").strip()
            if not canonical:
                continue
            label = _resolve_speaker_label(
                u.get("speaker"), speaker_labels,
            )
            prefix = (
                f"<strong>{_e(label)}:</strong> " if label else ""
            )
            display_text, corrected, note = _resolve_transcript_row(
                "utt", idx, canonical, notes_overlay,
            )
            suffix = (
                ' <small class="transcript-edited">(edited)</small>'
                if corrected
                else ""
            )
            row_parts = [
                f"<li><strong>[{_e(start)} – {_e(end)}]</strong> ",
                f"{prefix}{_e(display_text)}{suffix}",
            ]
            if note:
                row_parts.append("".join(_render_note_html(note)))
            row_parts.append("</li>")
            lines.append("".join(row_parts))
        lines.append("</ul>")

        lines.append("</body>")
        lines.append("</html>")
        return "\n".join(lines) + "\n"

    segs = transcript.get("segments", []) or []
    lines.append(f"<li>Segments: {_e(len(segs))}</li>")
    lines.append("</ul>")

    lines.append("<h3>Segments</h3>")
    lines.append('<ul class="segments">')
    for idx, seg in enumerate(segs):
        start = _format_ts(seg.get("start") or 0.0)
        end = _format_ts(seg.get("end") or 0.0)
        canonical = (seg.get("text") or "").strip()
        if not canonical:
            continue
        display_text, corrected, note = _resolve_transcript_row(
            "seg", idx, canonical, notes_overlay,
        )
        suffix = (
            ' <small class="transcript-edited">(edited)</small>'
            if corrected
            else ""
        )
        row_parts = [
            f"<li><strong>[{_e(start)} – {_e(end)}]</strong> ",
            f"{_e(display_text)}{suffix}",
        ]
        if note:
            row_parts.append("".join(_render_note_html(note)))
        row_parts.append("</li>")
        lines.append("".join(row_parts))
    lines.append("</ul>")

    lines.append("</body>")
    lines.append("</html>")
    return "\n".join(lines) + "\n"


def run(paths: JobPaths, force: bool = False) -> Path:
    update_stage(paths, "export_html", RUNNING)
    tmp = paths.report_html.with_suffix(".html.tmp")
    try:
        if not force and paths.report_html.exists():
            update_stage(
                paths, "export_html", COMPLETED, extra={"skipped": True}
            )
            return paths.report_html

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
        insights_by_idx = (
            _insights_chapters_by_index(insights) if insights else {}
        )

        speaker_overlay = _load_speaker_names_overlay(
            paths.speaker_names_json,
        )
        chapter_title_overlay = _load_chapter_titles_overlay(
            paths.chapter_titles_json,
        )
        frame_review_overlay = _load_frame_review_overlay(
            paths.frame_review_json,
        )
        transcript_notes_overlay = _load_transcript_notes_overlay(
            paths.transcript_notes_json,
        )

        chapters_section: list[str] | None = None
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

            chapters_section = _chapters_section_html(
                selected,
                chapter_text_by_index,
                paths.candidate_frames_dir,
                insights_by_idx=insights_by_idx,
                chapter_titles_overlay=chapter_title_overlay,
                frame_review_overlay=frame_review_overlay,
            )

        doc = build_html(
            job,
            meta_summary,
            transcript,
            chapters_section,
            insights=insights,
            chapter_titles_overlay=chapter_title_overlay,
            speaker_names_overlay=speaker_overlay,
            transcript_notes_overlay=transcript_notes_overlay,
        )
        tmp.write_text(doc, encoding="utf-8")
        tmp.replace(paths.report_html)

        extra: dict = {
            "report": paths.report_html.name,
            "bytes": paths.report_html.stat().st_size,
            "embedded_selected_frames": chapters_section is not None,
            "embedded_insights": insights is not None,
            "overlays": {
                "speaker_names": bool(speaker_overlay),
                "chapter_titles": bool(chapter_title_overlay),
                "frame_review": bool(frame_review_overlay),
                "transcript_notes": bool(transcript_notes_overlay),
            },
        }
        update_stage(paths, "export_html", COMPLETED, extra=extra)
        return paths.report_html
    except Exception as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        update_stage(
            paths, "export_html", FAILED, error=f"{type(e).__name__}: {e}"
        )
        raise
