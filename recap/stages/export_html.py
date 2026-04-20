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


def _insights_only_chapters_section_html(insights: dict) -> list[str]:
    out: list[str] = ["<h2>Chapters</h2>"]
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
) -> list[str]:
    out: list[str] = []
    out.append("<h2>Chapters</h2>")

    for ch in selected["chapters"]:
        ch_idx = ch["chapter_index"]
        if ch_idx not in chapter_text_by_index:
            raise RuntimeError(
                f"chapter_candidates.json has no chapter with index {ch_idx} "
                "required by selected_frames.json"
            )
        start = _format_ts(ch.get("start_seconds") or 0.0)
        end = _format_ts(ch.get("end_seconds") or 0.0)

        frames_by_scene: dict[int, dict] = {}
        for fr in ch["frames"]:
            frames_by_scene[fr["scene_index"]] = fr

        _check_hero_coherence(ch)
        _check_supporting_coherence(ch)
        hero = ch.get("hero")

        out.append('<section class="chapter">')
        insight = (insights_by_idx or {}).get(ch_idx)
        title_bit = ""
        if insight and (insight.get("title") or "").strip():
            title_bit = f" — {_e(insight['title'].strip())}"
        out.append(
            f"<h3>Chapter {_e(ch_idx)}{title_bit} [{_e(start)} – {_e(end)}]</h3>"
        )
        if insight is not None:
            out.extend(_insights_chapter_block_html(insight))

        if hero is not None:
            if "scene_index" not in hero:
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
            if not (frames_dir / frame_file).exists():
                raise RuntimeError(
                    f"missing candidate frame: candidate_frames/{frame_file}"
                )
            alt = f"Chapter {ch_idx} hero"
            out.append(
                f'<img src="candidate_frames/{_e(frame_file)}" '
                f'alt="{_e(alt)}">'
            )
            caption = _caption_for(hero_frame)
            if caption:
                out.append(f"<p><em>{_e(caption)}</em></p>")

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


def build_html(
    job: dict,
    meta_summary: dict,
    transcript: dict | None,
    chapters_section: list[str] | None,
    insights: dict | None = None,
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
        lines.extend(_insights_only_chapters_section_html(insights))

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
    segs = transcript.get("segments", []) or []
    lines.append(f"<li>Segments: {_e(len(segs))}</li>")
    lines.append("</ul>")

    lines.append("<h3>Segments</h3>")
    lines.append('<ul class="segments">')
    for seg in segs:
        start = _format_ts(seg.get("start") or 0.0)
        end = _format_ts(seg.get("end") or 0.0)
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        lines.append(
            f"<li><strong>[{_e(start)} – {_e(end)}]</strong> {_e(text)}</li>"
        )
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
            )

        doc = build_html(
            job,
            meta_summary,
            transcript,
            chapters_section,
            insights=insights,
        )
        tmp.write_text(doc, encoding="utf-8")
        tmp.replace(paths.report_html)

        extra: dict = {
            "report": paths.report_html.name,
            "bytes": paths.report_html.stat().st_size,
            "embedded_selected_frames": chapters_section is not None,
            "embedded_insights": insights is not None,
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
