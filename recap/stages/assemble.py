"""Stage 8 (Phase 1 subset): basic Markdown assembly.

Reads existing artifacts (`job.json`, `metadata.json`, `transcript.json`)
and writes a simple `report.md`. Deliberately does not claim chapters,
screenshots, or VLM-verified content — those come in later phases.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..job import COMPLETED, FAILED, RUNNING, JobPaths, read_job, update_stage


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


def build_markdown(job: dict, meta_summary: dict, transcript: dict | None) -> str:
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

        md = build_markdown(job, meta_summary, transcript)
        paths.report_md.write_text(md, encoding="utf-8")

        update_stage(
            paths,
            "assemble",
            COMPLETED,
            extra={"report": paths.report_md.name, "bytes": paths.report_md.stat().st_size},
        )
        return paths.report_md
    except Exception as e:
        update_stage(paths, "assemble", FAILED, error=f"{type(e).__name__}: {e}")
        raise
